"""PDF 모델 ZIP: huggingface.co에 접속되는 PC에서 묶고, 막힌 PC에서 검증한 뒤 설치한다.

표준 라이브러리만 쓴다(설치 스크립트가 가상환경 밖에서도 부른다).
"""
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import zipfile

from app.docling_models import LAYOUT_DIR, PDF_FILES, TABLE_DIR

KIND = "docops-docling-pdf-models"
ROOT = "docling-pdf-models"   # ZIP 안 최상위 폴더
MANIFEST = "manifest.json"
MODEL_DIRS = (LAYOUT_DIR, TABLE_DIR)
MAX_TOTAL = 8 * 1024 ** 3     # 압축을 푼 전체 크기 상한(손상·악의적 ZIP 대비)
_CHUNK = 1024 * 1024


class BundleError(Exception):
    pass


@dataclass
class Installed:
    target: Path
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    verified: bool = False  # manifest의 SHA-256으로 확인했는지


def _sha256(handle) -> str:
    digest = hashlib.sha256()
    while chunk := handle.read(_CHUNK):
        digest.update(chunk)
    return digest.hexdigest()


def _model_files(root: Path) -> list[str]:
    found = []
    for directory in MODEL_DIRS:
        top = root / directory
        if not top.is_dir():
            continue
        for path in sorted(top.rglob("*")):
            relative = path.relative_to(root)
            if path.is_file() and not any(part.startswith(".") for part in relative.parts):
                found.append(relative.as_posix())
    return found


def pack(source: Path, output: Path, docling_version: str | None = None) -> dict:
    """source(모델 캐시 폴더) → output ZIP."""
    names = _model_files(source)
    missing = [name.as_posix() for name in PDF_FILES if name.as_posix() not in names
               or (source / name).stat().st_size == 0]
    if missing:
        raise BundleError("PDF 모델 파일이 빠져 있거나 비어 있습니다: " + ", ".join(missing))
    files = {}
    for name in names:
        with open(source / name, "rb") as handle:
            files[name] = {"size": (source / name).stat().st_size, "sha256": _sha256(handle)}
    manifest = {"kind": KIND, "version": 1, "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "docling": docling_version, "files": files}
    temp = output.with_name(output.name + ".part")
    try:
        # 가중치는 거의 압축되지 않으므로 저장만 한다(만들기·풀기가 빠르다).
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
            archive.writestr(f"{ROOT}/{MANIFEST}", json.dumps(manifest, ensure_ascii=False, indent=1))
            for name in names:
                archive.write(source / name, f"{ROOT}/{name}")
        with zipfile.ZipFile(temp) as archive:
            if archive.testzip() is not None:
                raise BundleError("만든 ZIP을 다시 읽지 못했습니다.")
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    return manifest


# ---------------------------------------------------------------- 설치

def _safe(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or PureWindowsPath(name).drive or ".." in path.parts or not path.parts:
        raise BundleError(f"안전하지 않은 경로가 있어 설치하지 않습니다: {name}")
    return path


class _Source:
    """ZIP이나 폴더를 같은 방식으로 읽는다. prefix는 모델 폴더들이 들어 있는 위치."""

    def __init__(self, path: Path):
        self.path = path
        self.archive = None
        if path.is_dir():
            entries = {p.relative_to(path).as_posix(): p.stat().st_size for p in path.rglob("*") if p.is_file()}
        elif zipfile.is_zipfile(path):
            self.archive = zipfile.ZipFile(path)
            entries = {}
            for info in self.archive.infolist():
                if info.is_dir():
                    continue
                if info.flag_bits & 1:
                    raise BundleError("암호가 걸린 ZIP입니다. 암호 없이 다시 묶어 주세요.")
                entries[_safe(info.filename).as_posix()] = info.file_size
        else:
            raise BundleError(f"ZIP 파일이나 폴더가 아닙니다: {path}")
        self.entries = entries
        self.prefix = self._find_prefix()

    def _find_prefix(self) -> str:
        layout = LAYOUT_DIR.as_posix() + "/"
        prefixes = sorted({name[:name.index(layout)] for name in self.entries if layout in name}, key=len)
        if not prefixes:
            raise BundleError(f"모델 폴더({LAYOUT_DIR.as_posix()})를 찾지 못했습니다. "
                              "prepare-offline.py --models-only 로 만든 ZIP이나 모델 캐시 폴더를 지정해 주세요.")
        return prefixes[0]

    def open(self, name: str):
        full = self.prefix + name
        return self.archive.open(full) if self.archive else open(self.path / full, "rb")

    def close(self):
        if self.archive:
            self.archive.close()


def _manifest(source: _Source) -> dict | None:
    if source.prefix + MANIFEST not in source.entries:
        return None
    with source.open(MANIFEST) as handle:
        try:
            manifest = json.loads(handle.read(4 * 1024 * 1024).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise BundleError("manifest.json을 읽을 수 없습니다.") from exc
    if not isinstance(manifest, dict) or manifest.get("kind") != KIND or not isinstance(manifest.get("files"), dict):
        raise BundleError("이 ZIP의 manifest.json은 PDF 모델 묶음 형식이 아닙니다.")
    return manifest


def install(path: Path, target: Path) -> Installed:
    """ZIP·폴더의 모델을 target(콘솔이 모델을 찾는 폴더)에 설치한다. SHA-256이 다르면 그 파일에서 멈추고 이미 쓴 파일은 그대로 둔다."""
    path = Path(path).expanduser()
    if not path.exists():
        raise BundleError(f"모델 ZIP이나 폴더가 없습니다: {path}")
    source = _Source(path.resolve())
    try:
        manifest = _manifest(source)
        if manifest:
            expected = {_safe(name).as_posix(): info for name, info in manifest["files"].items()}
        else:
            expected = {name[len(source.prefix):]: {"size": size} for name, size in source.entries.items()
                        if name.startswith(source.prefix) and any(name[len(source.prefix):].startswith(d.as_posix() + "/") for d in MODEL_DIRS)}
        missing = [name.as_posix() for name in PDF_FILES if not expected.get(name.as_posix(), {}).get("size")]
        absent = [name for name in expected if source.prefix + name not in source.entries]
        if missing or absent:
            raise BundleError("묶음에 필요한 모델 파일이 빠져 있습니다: " + ", ".join((missing + absent)[:6]))
        if sum(info["size"] for info in expected.values()) > MAX_TOTAL:
            raise BundleError("모델 묶음이 크기 상한을 넘습니다.")
        wrong_size = [name for name, info in expected.items() if source.entries[source.prefix + name] != info["size"]]
        if wrong_size:
            raise BundleError("manifest와 크기가 다른 파일이 있습니다(옮기다 깨졌을 수 있음): " + ", ".join(wrong_size[:6]))

        result = Installed(target=target, verified=manifest is not None)
        conflicts, todo = [], []
        for name, info in expected.items():
            dest = target / name
            if not dest.is_file() or dest.stat().st_size == 0:
                todo.append(name)
                continue
            if dest.stat().st_size == info["size"]:
                with open(dest, "rb") as handle:
                    current = _sha256(handle)
                if "sha256" not in info:
                    with source.open(name) as handle:
                        info = {**info, "sha256": _sha256(handle)}
                if current == info["sha256"]:
                    result.unchanged.append(name)
                    continue
            conflicts.append(name)
        if conflicts:
            raise BundleError(f"{target} 에 내용이 다른 모델 파일이 이미 있어 설치하지 않았습니다: {', '.join(conflicts[:4])}. "
                              "그 파일을 직접 옮기거나 지운 뒤 다시 실행하거나, .env의 DOCOPS_DOCLING_ARTIFACTS 로 빈 폴더를 지정하세요.")
        for name in todo:
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            temp = dest.with_name(dest.name + ".part")
            try:
                digest = hashlib.sha256()
                with source.open(name) as reader, open(temp, "wb") as writer:
                    while chunk := reader.read(_CHUNK):
                        digest.update(chunk)
                        writer.write(chunk)
                if "sha256" in expected[name] and digest.hexdigest() != expected[name]["sha256"]:
                    raise BundleError(f"SHA-256이 manifest와 다릅니다(옮기다 깨졌을 수 있음): {name}")
                os.replace(temp, dest)
            finally:
                temp.unlink(missing_ok=True)
            result.written.append(name)
        return result
    finally:
        source.close()
