from dataclasses import dataclass

@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    parser: str
    parser_version: str

class ParserError(Exception):
    """Safe explanation that may be shown to the local user."""

class UnsupportedFormat(ParserError):
    pass
