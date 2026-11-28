"""매크로 사용 Office 문서(XLSM·DOCM·PPTM)의 VBA 프로젝트(vbaProject.bin)를 [MS-OVBA]대로 읽는다. 매크로는 실행하지 않는다.

p-code만 남기고 소스를 지운 프로젝트(VBA stomping)는 소스가 없는 모듈로 보인다. 표준 라이브러리만 쓴다.
"""
import codecs
from dataclasses import dataclass, field
import re
import struct
import zipfile

from app.cfb import CfbError, CompoundFile

MAX_PROJECT = 32 * 1024 * 1024   # vbaProject.bin 크기 상한
MAX_SOURCE = 4 * 1024 * 1024     # 모듈 하나의 풀린 소스 상한
MAX_MODULES = 500
# 문서를 열거나 닫을 때 저절로 도는 프로시저 이름.
AUTO_RUN = ("Auto_Open", "Workbook_Open", "AutoOpen", "Document_Open", "AutoExec", "Auto_Close",
            "Workbook_BeforeClose", "AutoClose", "Document_Close", "Workbook_Activate")
_AUTO = re.compile(r"^[ \t]*(?:(?:Public|Private|Friend)[ \t]+)?(?:Static[ \t]+)?(?:Sub|Function)[ \t]+(" +
                   "|".join(AUTO_RUN) + r")\b", re.I | re.M)
# VBA 편집기가 자동으로 넣는 속성 줄과 모듈 옵션(시트 모듈에도 들어간다).
_BOILERPLATE = re.compile(r"\s*(?:Attribute\s+VB_|Option\s+(?:Explicit|Base|Compare|Private\s+Module)\b)", re.I)


class VbaError(Exception):
    pass


@dataclass
class Module:
    name: str
    stream: str
    kind: str  # "standard"(표준 모듈) | "document"(시트·통합문서·클래스·폼)
    code_lines: int = 0
    source: str = ""
    auto_run: list[str] = field(default_factory=list)
    missing_source: bool = False


@dataclass
class Project:
    modules: list[Module]
    codepage: int
    errors: list[str] = field(default_factory=list)

    @property
    def code_modules(self) -> list[Module]:
        """Excel은 시트마다 빈 문서 모듈을 만들어 둔다."""
        return [module for module in self.modules if module.code_lines]

    @property
    def code_lines(self) -> int:
        return sum(module.code_lines for module in self.modules)

    @property
    def auto_run(self) -> list[str]:
        return sorted({name for module in self.modules for name in module.auto_run})

    def summary(self) -> dict:
        return {"modules": len(self.modules), "code_modules": len(self.code_modules), "code_lines": self.code_lines,
                "auto_run": self.auto_run, "stripped_modules": sum(1 for m in self.modules if m.missing_source),
                "items": [{"name": m.name, "kind": m.kind, "code_lines": m.code_lines,
                           **({"auto_run": m.auto_run} if m.auto_run else {})} for m in self.modules[:50]]}


def decompress(data: bytes, limit: int = MAX_SOURCE) -> bytes:
    """[MS-OVBA] 2.4.1 CompressedContainer를 푼다."""
    if not data or data[0] != 1:
        raise VbaError("VBA 압축 서명이 없습니다.")
    out = bytearray()
    pos = 1
    while pos + 2 <= len(data):
        header = struct.unpack_from("<H", data, pos)[0]
        if (header >> 12) & 0b111 != 0b011:
            raise VbaError("VBA 압축 조각 머리말이 잘못되었습니다.")
        chunk_end = min(pos + (header & 0x0FFF) + 3, len(data))
        pos += 2
        start = len(out)
        if not header & 0x8000:  # 압축하지 않은 4096바이트 조각
            out += data[pos:pos + 4096]
            pos += 4096
        else:
            while pos < chunk_end:
                flags = data[pos]
                pos += 1
                for bit in range(8):
                    if pos >= chunk_end:
                        break
                    if not (flags >> bit) & 1:
                        out.append(data[pos])
                        pos += 1
                        continue
                    if pos + 2 > chunk_end:
                        raise VbaError("VBA 압축 복사 토큰이 잘렸습니다.")
                    token = struct.unpack_from("<H", data, pos)[0]
                    pos += 2
                    bits = max((len(out) - start - 1).bit_length(), 4)
                    length = (token & (0xFFFF >> bits)) + 3
                    source = len(out) - ((token >> (16 - bits)) + 1)
                    if source < start:
                        raise VbaError("VBA 압축 복사 위치가 조각 밖을 가리킵니다.")
                    for index in range(length):  # 겹치는 복사가 있어 한 바이트씩 옮긴다.
                        out.append(out[source + index])
            pos = chunk_end
        if len(out) > limit:
            raise VbaError("풀린 VBA 소스가 크기 상한을 넘었습니다.")
    return bytes(out)


def _records(data: bytes):
    """dir 스트림의 (Id, 값) 레코드. PROJECTVERSION(0x0009)만 크기 필드와 실제 길이가 다르다(4 대신 6)."""
    pos = 0
    while pos + 6 <= len(data):
        ident, size = struct.unpack_from("<HI", data, pos)
        pos += 6
        if ident == 0x0009:
            size = 6
        if pos + size > len(data):
            raise VbaError("VBA dir 레코드가 잘렸습니다.")
        yield ident, data[pos:pos + size]
        pos += size
        if ident == 0x0010:  # dir 끝
            return


def _codec(codepage: int) -> str:
    for name in (f"cp{codepage}", "utf-16-le" if codepage == 1200 else None, "utf-8" if codepage == 65001 else None):
        if not name:
            continue
        try:
            return codecs.lookup(name).name
        except LookupError:
            continue
    return "latin-1"


def read_project(data: bytes) -> Project:
    if len(data) > MAX_PROJECT:
        raise VbaError("VBA 프로젝트가 크기 상한을 넘었습니다.")
    try:
        cf = CompoundFile(data)
        directory = next((entry for entry in cf.items() if entry.path.upper() == "VBA/DIR"), None)
        if directory is None:
            raise VbaError("VBA dir 스트림이 없습니다.")
        records = list(_records(decompress(cf.read(directory, limit=MAX_PROJECT))))
    except CfbError as exc:
        raise VbaError("VBA 프로젝트(OLE)를 읽을 수 없습니다.") from exc
    codepage = 1252
    modules: list[Module] = []
    current: dict | None = None
    for ident, value in records:
        if ident == 0x0003 and len(value) == 2:
            codepage = struct.unpack("<H", value)[0]
        elif ident == 0x0019:  # MODULENAME: 새 모듈 시작
            current = {"name": value.decode(_codec(codepage), "replace"), "kind": "document"}
        elif current is None:
            continue
        elif ident == 0x0047:
            current["name"] = value.decode("utf-16-le", "replace") or current["name"]
        elif ident == 0x001A:
            current["stream"] = value.decode(_codec(codepage), "replace")
        elif ident == 0x0032 and value:
            current["stream"] = value.decode("utf-16-le", "replace")
        elif ident == 0x0031 and len(value) == 4:
            current["offset"] = struct.unpack("<I", value)[0]
        elif ident == 0x0021:
            current["kind"] = "standard"
        elif ident == 0x002B:  # 모듈 끝
            modules.append(current)
            current = None
            if len(modules) >= MAX_MODULES:
                break
    project = Project([], codepage)
    codec = _codec(codepage)
    for info in modules:
        module = Module(info["name"], info.get("stream", info["name"]), info["kind"])
        project.modules.append(module)
        entry = next((e for e in cf.items() if e.path.upper() == f"VBA/{module.stream}".upper()), None)
        try:
            if entry is None:
                raise VbaError("모듈 스트림이 없습니다.")
            raw = cf.read(entry, limit=MAX_PROJECT)
            offset = info.get("offset", 0)
            if offset >= len(raw):
                module.missing_source = True
                continue
            module.source = decompress(raw[offset:]).decode(codec, "replace")
        except (CfbError, VbaError) as exc:
            module.missing_source = True
            project.errors.append(f"{module.name}: {exc}")
            continue
        lines = [line for line in module.source.splitlines() if line.strip() and not _BOILERPLATE.match(line)]
        module.code_lines = len(lines)
        module.auto_run = sorted({match.group(1) for match in _AUTO.finditer(module.source)}, key=str.lower)
    return project


def from_package(path_or_archive) -> Project | None:
    archive = path_or_archive if isinstance(path_or_archive, zipfile.ZipFile) else zipfile.ZipFile(path_or_archive)
    try:
        info = next((item for item in archive.infolist() if item.filename.lower().endswith("vbaproject.bin")), None)
        if info is None:
            return None
        if info.file_size > MAX_PROJECT or info.flag_bits & 1:
            raise VbaError("VBA 프로젝트가 크기 상한을 넘었거나 암호화되어 있습니다.")
        return read_project(archive.read(info))
    finally:
        if archive is not path_or_archive:
            archive.close()


def parse_notes(path, workbook: bool = True) -> list[str]:
    """파싱 결과에 남길 매크로 경고. workbook=False는 Word 문서(DOCM)."""
    saved = "셀 값은 파일에 마지막으로 저장된 값입니다." if workbook else "본문은 파일에 마지막으로 저장된 내용입니다."
    try:
        project = from_package(path)
    except (VbaError, zipfile.BadZipFile, OSError, KeyError, ValueError):
        return ["매크로(VBA) 프로젝트가 있지만 읽지 못했습니다. 매크로는 실행하지 않았고, " + saved]
    if project is None:
        return []
    stripped = sum(1 for module in project.modules if module.missing_source)
    if not project.code_modules and not stripped:
        return []
    note = (f"매크로 포함: VBA 모듈 {len(project.code_modules)}개(코드 {project.code_lines}줄)는 실행하지 않았고 결과 본문에 넣지 않았습니다. "
            + saved)
    if project.auto_run:
        note += f" 열거나 닫을 때 자동 실행되는 프로시저({', '.join(project.auto_run)})가 있어, 매크로가 채우는 값은 저장 시점 이후와 다를 수 있습니다."
    notes = [note]
    if stripped:
        notes.append(f"소스 코드가 없는 VBA 모듈 {stripped}개가 있습니다(실행 코드만 남았거나 손상). 매크로 내용은 확인하지 못했습니다.")
    return notes
