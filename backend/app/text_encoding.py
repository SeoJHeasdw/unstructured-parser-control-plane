"""Strict encodings shared by the format gate and the text reader."""
import codecs


def encodings(head: bytes) -> tuple[str, ...]:
    if head.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return ("utf-32",)
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return ("utf-16",)
    if head.startswith(codecs.BOM_UTF8):
        return ("utf-8-sig",)
    return ("utf-8", "cp949")


def text_sample(data: bytes, *, final: bool = False) -> str | None:
    for encoding in encodings(data):
        try:
            text = codecs.getincrementaldecoder(encoding)().decode(data, final=final)
        except UnicodeError:
            continue
        if "\0" not in text:
            return text
    return None
