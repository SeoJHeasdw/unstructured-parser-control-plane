from dataclasses import dataclass, field
from app.models import ResultLocation

@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    parser: str
    parser_version: str
    ocr_enabled: bool | None = None
    locations: list[ResultLocation] = field(default_factory=list)

class ParserError(Exception):
    """Safe explanation that may be shown to the local user."""

class UnsupportedFormat(ParserError):
    pass
