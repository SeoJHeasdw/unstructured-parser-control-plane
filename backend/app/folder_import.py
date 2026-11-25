"""허용 폴더에서 가져오기.

브라우저가 파일을 보내지 않는다. 화면은 허용 폴더 안의 상대 경로만 고르고,
콘솔 서버(이 컴퓨터의 Python)가 그 파일을 직접 읽어 로컬 저장소에 복사한다.
브라우저 파일 첨부·전송이 보안 프로그램으로 막힌 PC에서도 쓸 수 있게 만든 경로다(2026-11-25 고객사).

허용 폴더는 작업 도구(MCP·CLI)와 같은 설정 DOCOPS_AGENT_ROOTS로만 정한다. 화면에서는 바꿀 수 없다.
비우면 프로젝트의 samples 폴더(합성 예시 말뭉치)를 쓴다. 허용 폴더 밖, 숨김·잠금 파일은 읽지 않는다.
가져오기는 저장만 한다. 파싱은 사용자가 따로 실행한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path, PurePosixPath

PROJECT = Path(__file__).resolve().parents[2]
ROOTS_ENV = "DOCOPS_AGENT_ROOTS"
DEFAULT_ROOT = PROJECT / "samples"
LOCK_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
# 한 번에 보여 줄 파일 수(하위 폴더 포함 보기). 넘으면 잘렸다고 알린다.
LIST_LIMIT = 5000


class ImportPathError(Exception):
    """허용 폴더 밖이거나 열 수 없는 경로."""


def root_candidates(environ=None) -> tuple[list[Path], bool]:
    """설정된 허용 폴더 후보와 기본값(samples) 사용 여부. 여러 개는 OS 경로 구분자(Windows ;)나 줄바꿈으로 나눈다."""
    raw = (os.environ if environ is None else environ).get(ROOTS_ENV, "")
    parts = [part.strip().strip('"') for chunk in raw.splitlines() for part in chunk.split(os.pathsep)]
    given = [Path(part).expanduser() for part in parts if part]
    if not given and DEFAULT_ROOT.is_dir():
        return [DEFAULT_ROOT], True
    return given, False


def resolve_roots(given: list[Path]) -> tuple[list[Path], list[str]]:
    roots, notes = [], []
    for root in given:
        try:
            resolved = root.resolve()
        except OSError:
            notes.append(f"허용 폴더를 열 수 없음: {root}")
            continue
        if resolved.is_dir():
            if resolved not in roots:
                roots.append(resolved)
        else:
            notes.append(f"허용 폴더가 없음: {root}")
    return roots, notes


def hidden(name: str) -> bool:
    return name.startswith((".", "$", "~$")) or name == "__MACOSX" or name.lower() in LOCK_NAMES


def relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def locate(root: Path, rel: str) -> Path:
    """허용 폴더 기준 상대 경로를 실제 경로로. 폴더 밖(.., 절대 경로, 밖을 가리키는 링크)과 숨김 경로는 거부한다."""
    text = (rel or "").replace("\\", "/").strip()
    pure = PurePosixPath(text)
    if pure.is_absolute() or ":" in text or any(part in ("..",) for part in pure.parts):
        raise ImportPathError("허용 폴더 기준 상대 경로만 쓸 수 있습니다.")
    if any(hidden(part) for part in pure.parts if part not in ("", ".")):
        raise ImportPathError("숨김·잠금 파일은 가져오지 않습니다.")
    try:
        resolved = root.joinpath(*[part for part in pure.parts if part not in ("", ".")]).resolve()
        resolved.relative_to(root)
    except ValueError:
        raise ImportPathError("허용 폴더 밖의 경로입니다.") from None
    except OSError as exc:
        raise ImportPathError(f"경로를 열 수 없습니다: {exc.strerror or exc}") from None
    if not resolved.exists():
        raise ImportPathError("경로가 없습니다.")
    return resolved


@dataclass
class Listing:
    folders: list[dict]
    files: list[Path]
    truncated: bool


def list_folder(root: Path, folder: Path, recursive: bool) -> Listing:
    if not folder.is_dir():
        raise ImportPathError("폴더가 아닙니다.")
    folders, files, truncated = [], [], False
    if recursive:
        for current, dirs, names in os.walk(folder):
            here = Path(current)
            dirs[:] = sorted(d for d in dirs if not hidden(d) and _inside(root, here / d))
            for name in sorted(names):
                if hidden(name):
                    continue
                if len(files) >= LIST_LIMIT:
                    return Listing([], files, True)
                files.append(here / name)
        return Listing([], files, False)
    try:
        entries = sorted(folder.iterdir(), key=lambda p: p.name.casefold())
    except OSError as exc:
        raise ImportPathError(f"폴더를 열 수 없습니다: {exc.strerror or exc}") from None
    for entry in entries:
        if hidden(entry.name) or not _inside(root, entry):
            continue
        if entry.is_dir():
            folders.append({"name": entry.name, "path": relative(root, entry)})
        elif entry.is_file():
            if len(files) >= LIST_LIMIT:
                truncated = True
                break
            files.append(entry)
    return Listing(folders, files, truncated)


def _inside(root: Path, path: Path) -> bool:
    """링크가 허용 폴더 밖을 가리키면 목록에서도 뺀다."""
    try:
        path.resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def modified_at(stat: os.stat_result) -> str:
    return datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()


def file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()
