"""합성 PDF: 글자를 그린 래스터 그림 + (선택) 보이지 않는 글자 층(렌더 모드 3)·보이는 글자 줄·쪽 회전.

파서 품질 검수 고도화 계획 §2.3의 실험을 재현한다: 화면(픽셀)에는 'PRESSURE 17 bar'가 보이고, 숨은 층에는 다른 값을 넣는다.
외부 라이브러리 없이 PDF 객체를 직접 쓴다(그림은 Pillow로 그려 FlateDecode로 넣는다).
"""
from __future__ import annotations

import zlib


def _raster(text: str, width: int, height: int) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=28)
    except TypeError:  # 오래된 Pillow
        font = ImageFont.load_default()
    draw.text((30, 60), text, fill=0, font=font)
    return image.tobytes()


def raster_pdf(shown: str = "PRESSURE 17 bar", hidden: str | None = None, *, rotate: int = 0, visible: str | None = None,
               width: int = 420, height: int = 160, image: bool = True) -> bytes:
    """shown: 그림에 그려진(눈에 보이는) 글자. hidden: 그림 위에 얹는 보이지 않는 글자. visible: 그림 밖 보이는 글자 줄."""
    content = ""
    if image:
        content += f"q {width} 0 0 {height} 0 0 cm /Im1 Do Q\n"
    if hidden:
        content += f"BT 3 Tr /F1 24 Tf 30 70 Td ({hidden}) Tj ET\n"
    if visible:
        content += f"BT 0 Tr /F1 10 Tf 10 6 Td ({visible}) Tj ET\n"
    pixels = zlib.compress(_raster(shown, width, height)) if image else b""
    rotation = f" /Rotate {rotate}" if rotate else ""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}]{rotation} /Resources << /Font << /F1 4 0 R >>"
         + (" /XObject << /Im1 5 0 R >>" if image else "") + " >> /Contents 6 0 R >>").encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace /DeviceGray /BitsPerComponent 8 "
         f"/Filter /FlateDecode /Length {len(pixels)} >>\nstream\n").encode() + pixels + b"\nendstream",
        f"<< /Length {len(content.encode())} >>\nstream\n{content}endstream".encode(),
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
