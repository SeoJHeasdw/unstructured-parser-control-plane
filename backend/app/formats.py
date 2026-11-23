"""Extensions with native text and raster parsing routes."""
TEXT_FORMATS = {"TXT", "CSV", "MD", "LOG"}
IMAGE_FORMATS = {"PNG": "PNG", "JPG": "JPEG", "JPEG": "JPEG", "BMP": "BMP", "TIFF": "TIFF",
                 "TIF": "TIFF", "WEBP": "WEBP", "GIF": "GIF"}

def raster_format(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if head.startswith((b"II*\0", b"MM\0*", b"II+\0", b"MM\0+")):
        return "TIFF"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "WEBP"
    if head.startswith(b"BM") and len(head) >= 18 and int.from_bytes(head[14:18], "little") in (12, 40, 52, 56, 64, 108, 124):
        return "BMP"
    return None
