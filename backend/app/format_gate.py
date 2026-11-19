"""파싱 전 형식 확인: 확장자가 아니라 파일 내용으로 DRM·암호·형식 불일치를 먼저 가려낸다.

- DRM 제품 서명은 공개 자료로 확정할 수 없어서 내장하지 않는다. 실제 파일에서 확인한 머리말을
  `DOCOPS_DRM_SIGNATURES`로 등록한다. 예: `NASCA=ascii:<확인한 문자열>; 다른제품=hex:0A0B0C0D`
  - `hex:` 파일 맨 앞(0번째 바이트)부터 일치, `ascii:` 앞 4 KiB 안 어디에서든 일치.
- 서명이 없어도 Office 확장자인데 Office·ZIP·OLE 서명이 없고 본문이 암호문처럼 보이면 `drm_suspected`로 둔다.
- 이 모듈은 판별만 한다. 복호화·우회는 하지 않는다. 해제는 DRM 제품의 공식 해제 경로에서 처리한다.
"""
from collections import Counter
from dataclasses import dataclass, field
import math
from pathlib import Path
import re
import zipfile

from app.cfb import SIGNATURE as CFB_SIGNATURE, CfbError, CompoundFile
from app.structure import sniff

OOXML_MAIN = {
    "DOCX": "word/document.xml", "DOCM": "word/document.xml",
    "XLSX": "xl/workbook.xml", "XLSM": "xl/workbook.xml",
    "PPTX": "ppt/presentation.xml", "PPTM": "ppt/presentation.xml",
}
_MAIN_KIND = {"word/document.xml": "docx", "xl/workbook.xml": "xlsx", "ppt/presentation.xml": "pptx"}
LABEL = {
    "zip": "일반 ZIP 압축", "cfb": "OLE 복합 문서", "pdf": "PDF", "image": "이미지", "text": "텍스트", "html": "HTML",
    "xml": "XML", "mime": "메일(MIME)", "docx": "Word(DOCX)", "xlsx": "Excel(XLSX)", "pptx": "PowerPoint(PPTX)",
    "doc": "구형 Word(DOC)", "xls": "구형 Excel(XLS)", "ppt": "구형 PowerPoint(PPT)", "hwp": "한글(HWP)",
    "msg": "Outlook 메일(MSG)", "ole": "OLE 개체", "unknown": "알 수 없는 이진 파일",
}
ENTROPY_SUSPECT = 7.5  # bits/byte. 압축·암호문은 8에 가깝고 일반 문서 이진은 대개 이보다 낮다.
_SAMPLE = 64 * 1024


@dataclass(frozen=True)
class DrmSignature:
    label: str
    kind: str  # "hex" | "ascii"
    pattern: bytes


def parse_signatures(raw: str | None) -> tuple[DrmSignature, ...]:
    """'이름=hex:…; 이름=ascii:…' 형식. 잘못된 항목은 무시하지 않고 오류로 알린다(조용한 미탐 방지)."""
    result = []
    for item in (raw or "").split(";"):
        item = item.strip()
        if not item:
            continue
        label, sep, spec = item.partition("=")
        kind, sep2, value = spec.strip().partition(":")
        label, kind = label.strip(), kind.strip().lower()
        if not sep or not sep2 or not label or not value:
            raise ValueError(f"DRM 서명 항목 형식이 잘못되었습니다: {item!r} (예: 제품=hex:0A0B 또는 제품=ascii:TAG)")
        if kind == "hex":
            cleaned = re.sub(r"[\s:-]", "", value)
            if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}){2,64}", cleaned):
                raise ValueError(f"DRM 서명 hex 값은 2~64바이트여야 합니다: {item!r}")
            result.append(DrmSignature(label, "hex", bytes.fromhex(cleaned)))
        elif kind == "ascii":
            if len(value) < 3:
                raise ValueError(f"DRM 서명 ascii 값은 3글자 이상이어야 합니다: {item!r}")
            result.append(DrmSignature(label, "ascii", value.encode("utf-8")))
        else:
            raise ValueError(f"DRM 서명 종류는 hex 또는 ascii입니다: {item!r}")
    return tuple(result)


def match_signature(head: bytes, signatures: tuple[DrmSignature, ...]) -> str | None:
    for signature in signatures:
        if signature.kind == "hex" and head.startswith(signature.pattern):
            return signature.label
        if signature.kind == "ascii" and signature.pattern in head[:4096]:
            return signature.label
    return None


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    total = len(data)
    return -sum(c / total * math.log2(c / total) for c in Counter(data).values())


@dataclass(frozen=True)
class GateResult:
    code: str | None  # None이면 파서로 보낸다
    detected: str
    message: str | None = None
    vendor: str | None = None
    evidence: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.code is None


def _header_evidence(head: bytes) -> dict:
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in head[:32])
    return {"header_hex": head[:16].hex(" "), "header_text": printable}


def _cfb_kind(data: bytes) -> tuple[str, str | None]:
    """(형식, 보호 종류) 보호 종류: 'irm' | 'password' | None"""
    try:
        cf = CompoundFile(data)
    except CfbError:
        return "cfb", None
    top = {entry.name for entry in cf.children("")}
    if "EncryptionInfo" in top and "EncryptedPackage" in top:
        names = {entry.name for entry in cf.items()}
        # [MS-OFFCRYPTO]: 권한 관리(IRM)는 DRMEncryptedDataSpace, 암호는 StrongEncryptionDataSpace를 쓴다.
        irm = any("DRMEncrypted" in name for name in names)
        return "encrypted-ooxml", "irm" if irm else "password"
    if "WordDocument" in top:
        return "doc", None
    if "Workbook" in top or "Book" in top:
        return "xls", None
    if "PowerPoint Document" in top:
        return "ppt", None
    if "FileHeader" in top and "BodyText" in top:
        return "hwp", None
    if "__properties_version1.0" in top:
        return "msg", None
    return "ole", None


def _mismatch(extension: str, detected: str, evidence: dict) -> GateResult:
    return GateResult("format_mismatch", detected,
                      f"확장자는 {extension}이지만 실제 내용은 {LABEL.get(detected, detected)}입니다. "
                      "확장자를 바로잡아 다시 올리거나 해당 형식의 처리 경로가 필요합니다.", evidence=evidence)


def _opaque(extension: str, head: bytes, evidence: dict) -> GateResult:
    """알려진 서명이 없는 이진 파일: 암호문처럼 보이면 DRM 의심, 아니면 미확인."""
    sample = head[512:] if len(head) > 1024 else head
    bits = round(entropy(sample), 3)
    evidence = {**evidence, "entropy": bits}
    if bits >= ENTROPY_SUSPECT:
        return GateResult("drm_suspected", "unknown",
                          f"{extension} 확장자이지만 문서 서명이 없고 본문이 암호문처럼 보입니다. DRM으로 감싼 파일로 보입니다. "
                          "DRM을 해제한 사본이 필요합니다. 제품 머리말을 확인했다면 DOCOPS_DRM_SIGNATURES에 등록할 수 있습니다.",
                          evidence=evidence)
    return GateResult("format_unrecognized", "unknown",
                      f"{extension} 확장자이지만 알려진 문서 서명이 없습니다. 손상되었거나 다른 프로그램이 감싼 파일일 수 있습니다.",
                      evidence=evidence)


def check(path: Path, extension: str, signatures: tuple[DrmSignature, ...] = (), max_bytes: int = 100 * 1024 * 1024) -> GateResult:
    with open(path, "rb") as handle:
        head = handle.read(_SAMPLE)
    evidence = _header_evidence(head)
    vendor = match_signature(head, signatures)
    if vendor:
        return GateResult("drm_protected", "drm", f"{vendor} DRM으로 보호된 파일입니다. 표준 파서로 열 수 없으므로 DRM을 해제한 사본이 필요합니다.",
                          vendor=vendor, evidence=evidence)
    detected = sniff(head)
    if extension in OOXML_MAIN:
        if detected == "zip":
            try:
                with zipfile.ZipFile(path) as archive:
                    names = set(archive.namelist())
            except (zipfile.BadZipFile, OSError):
                return GateResult("format_unrecognized", "zip", "ZIP 서명은 있지만 목차를 읽을 수 없습니다. 파일이 손상되었을 수 있습니다.", evidence=evidence)
            if "[Content_Types].xml" not in names:
                return _mismatch(extension, "zip", evidence)
            actual = next((kind for main, kind in _MAIN_KIND.items() if main in names), "zip")
            if OOXML_MAIN[extension] not in names:
                return _mismatch(extension, actual, evidence)
            return GateResult(None, actual, evidence=evidence)
        if detected == "cfb":
            with open(path, "rb") as handle:
                data = handle.read(max_bytes)
            kind, protection = _cfb_kind(data)
            if protection == "irm":
                return GateResult("drm_protected", "encrypted-ooxml",
                                  "Microsoft 권한 관리(IRM)로 보호된 Office 문서입니다. 권한 해제본이 필요합니다.",
                                  vendor="Microsoft IRM", evidence=evidence)
            if protection == "password":
                return GateResult("encrypted", "encrypted-ooxml", "암호가 걸린 Office 문서입니다. 암호를 해제한 사본이 필요합니다.", evidence=evidence)
            return _mismatch(extension, kind, evidence)
        if detected == "unknown":
            return _opaque(extension, head, evidence)
        return _mismatch(extension, detected, evidence)
    if extension == "PDF":
        if detected == "pdf":
            return GateResult(None, "pdf", evidence=evidence)
        return _opaque(extension, head, evidence) if detected == "unknown" else _mismatch(extension, detected, evidence)
    if detected in ("zip", "cfb", "pdf", "image"):
        return _mismatch(extension, detected, evidence)
    if detected == "unknown":
        opaque = _opaque(extension, head, evidence)
        if opaque.code == "drm_suspected":
            return opaque
        # 암호문처럼 보이지 않으면 텍스트 어댑터가 인코딩 문제를 더 구체적으로 알린다.
    return GateResult(None, detected, evidence=evidence)
