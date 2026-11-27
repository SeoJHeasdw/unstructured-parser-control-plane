from dataclasses import dataclass, field
from app.models import ResultLocation

@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    parser: str
    parser_version: str
    ocr_enabled: bool | None = None
    locations: list[ResultLocation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # 판정 근거(Markdown으로 바뀌며 사라지는 정보): CSV의 인코딩·구분자 후보·원래 열 수 등. 실행(parse_runs.evidence)에 저장한다.
    evidence: dict | None = None

class ParserError(Exception):
    """Safe explanation that may be shown to the local user.

    code는 화면·운영이 문구 대신 분기할 수 있는 안정적인 사유 코드다(API·데이터 계약 참고)."""
    default_code = "parse_failed"

    def __init__(self, message: str = "", code: str | None = None):
        super().__init__(message)
        self.code = code or self.default_code

class UnsupportedFormat(ParserError):
    default_code = "unsupported_format"
