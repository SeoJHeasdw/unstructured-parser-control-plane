"""파싱 엣지 케이스를 재현하는 합성 Office 파일. 표준 라이브러리만 쓰고 실제 고객 문서는 쓰지 않는다.

python-docx·openpyxl(Docling 내부)이 실제로 열 수 있는 최소 OOXML 패키지를 만든다.
DRM 래핑은 특정 제품 형식을 흉내 내지 않는다. '정상 서명이 아닌 머리말 + 암호문처럼 보이는 본문'만 재현한다.
"""
import base64
import hashlib
import io
import struct
import zipfile
import zlib

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_R = "http://schemas.openxmlformats.org/package/2006/relationships"
IMAGE_REL = R + "/image"
NS_DOC = (
    f'xmlns:w="{W}" xmlns:r="{R}" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:asvg="http://schemas.microsoft.com/office/drawing/2016/SVG/main" '
    'mc:Ignorable="wps wpg asvg"'
)


def png(width: int = 2, height: int = 2, rgb: tuple = (200, 30, 30)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def svg_with_raster(texts: list[str]) -> bytes:
    """벡터 글자와 래스터 그림이 한 SVG 안에 섞인 그림(엣지 케이스 2·5)."""
    raster = base64.b64encode(png(4, 4, (20, 120, 200))).decode()
    body = "".join(f'<text x="8" y="{20 + 18 * i}">{t}</text>' for i, t in enumerate(texts))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="240" height="120">'
            f'<rect width="240" height="120" fill="#fff"/>{body}'
            f'<image x="160" y="10" width="64" height="64" xlink:href="data:image/png;base64,{raster}"/></svg>').encode()


def _package(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _types(overrides: dict) -> str:
    items = "".join(f'<Override PartName="{part}" ContentType="{kind}"/>' for part, kind in overrides.items())
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            '<Default Extension="svg" ContentType="image/svg+xml"/>' + items + '</Types>')


def _rels(items: list[tuple[str, str, str]]) -> str:
    body = "".join(f'<Relationship Id="{rid}" Type="{kind}" Target="{target}"/>' for rid, kind, target in items)
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG_R}">{body}</Relationships>'


# ---------------------------------------------------------------- DOCX

def run(text: str, *, sup=False, sub=False, color: str | None = None, vanish=False) -> str:
    props = ""
    if color:
        props += f'<w:color w:val="{color}"/>'
    if vanish:
        props += "<w:vanish/>"
    if sup or sub:
        props += f'<w:vertAlign w:val="{"superscript" if sup else "subscript"}"/>'
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def sym(char_hex: str, font: str = "Symbol") -> str:
    """Word '기호 삽입'으로 넣은 문자. 본문 글자가 아니라 글꼴 코드(F0xx)로만 저장된다."""
    return f'<w:r><w:sym w:font="{font}" w:char="{char_hex}"/></w:r>'


def para(*runs: str) -> str:
    return "<w:p>" + "".join(runs) + "</w:p>"


def _blip(rid: str, svg_rid: str | None = None) -> str:
    ext = (f'<a:extLst><a:ext uri="{{96DAC541-7B7A-43D3-8B79-37D633B846F1}}"><asvg:svgBlip r:embed="{svg_rid}"/></a:ext></a:extLst>'
           if svg_rid else "")
    return f'<a:blip r:embed="{rid}">{ext}</a:blip>'


def _pic(pid: int, rid: str, svg_rid: str | None = None) -> str:
    return (f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{pid}" name="그림 {pid}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill>{_blip(rid, svg_rid)}<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="914400" cy="457200"/></a:xfrm><a:prstGeom prst="rect"/></pic:spPr></pic:pic>')


def picture(pid: int, rid: str, svg_rid: str | None = None) -> str:
    return ('<w:r><w:drawing><wp:inline><wp:extent cx="914400" cy="457200"/>'
            f'<wp:docPr id="{pid}" name="그림 {pid}"/><a:graphic>'
            f'<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">{_pic(pid, rid, svg_rid)}</a:graphicData>'
            '</a:graphic></wp:inline></w:drawing></w:r>')


def _anchor(pid: int, name: str, uri: str, inner: str) -> str:
    return ('<wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="2" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            '<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="column"><wp:posOffset>0</wp:posOffset></wp:positionH>'
            '<wp:positionV relativeFrom="paragraph"><wp:posOffset>120000</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="2743200" cy="457200"/><wp:wrapNone/><wp:docPr id="{pid}" name="{name}"/>'
            f'<a:graphic><a:graphicData uri="{uri}">{inner}</a:graphicData></a:graphic></wp:anchor>')


def floating_text_box(pid: int, text: str) -> str:
    """표 선 위에 떠 있는 글상자(엣지 케이스 10). Word 2010+ 형식과 VML 대체본을 함께 둔다."""
    content = f"<w:txbxContent>{para(run(text))}</w:txbxContent>"
    wsp = f'<wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr/><wps:txbx>{content}</wps:txbx><wps:bodyPr/></wps:wsp>'
    return ('<w:r><mc:AlternateContent><mc:Choice Requires="wps"><w:drawing>'
            + _anchor(pid, f"Text Box {pid}", "http://schemas.microsoft.com/office/word/2010/wordprocessingShape", wsp)
            + '</w:drawing></mc:Choice><mc:Fallback><w:pict><v:shape style="position:absolute"><v:textbox>'
            + content + '</v:textbox></v:shape></w:pict></mc:Fallback></mc:AlternateContent></w:r>')


def picture_group(pid: int, rids: list[str]) -> str:
    """그룹 도형 안의 그림들(엣지 케이스 5: 그림 안에 다른 그림을 겹쳐 둔 경우)."""
    pics = "".join(_pic(pid + i + 1, rid) for i, rid in enumerate(rids))
    group = f"<wpg:wgp><wpg:cNvGrpSpPr/><wpg:grpSpPr/>{pics}</wpg:wgp>"
    return ('<w:r><mc:AlternateContent><mc:Choice Requires="wpg"><w:drawing>'
            + _anchor(pid, f"Group {pid}", "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup", group)
            + "</w:drawing></mc:Choice><mc:Fallback/></mc:AlternateContent></w:r>")


def cell(content: str, *, span: int = 1, vmerge: str | None = None) -> str:
    props = (f'<w:gridSpan w:val="{span}"/>' if span > 1 else "") + (
        ('<w:vMerge w:val="restart"/>' if vmerge == "restart" else "<w:vMerge/>") if vmerge else "")
    body = content if content.startswith("<w:p") else para(run(content)) if content else "<w:p/>"
    return f"<w:tc>{f'<w:tcPr>{props}</w:tcPr>' if props else ''}{body}</w:tc>"


def table(rows: list[list[str]], columns: int) -> str:
    borders = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
                      for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    grid = "".join('<w:gridCol w:w="2400"/>' for _ in range(columns))
    return (f'<w:tbl><w:tblPr><w:tblBorders>{borders}</w:tblBorders></w:tblPr><w:tblGrid>{grid}</w:tblGrid>'
            + "".join("<w:tr>" + "".join(row) + "</w:tr>" for row in rows) + "</w:tbl>")


def docx(body: str, media: dict | None = None) -> bytes:
    """media: {rId: (파일명, bytes)} — word/media/에 두고 관계를 만든다."""
    media = media or {}
    files = {
        "[Content_Types].xml": _types({"/word/document.xml": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"}),
        "_rels/.rels": _rels([("rId1", R + "/officeDocument", "word/document.xml")]),
        "word/document.xml": f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS_DOC}><w:body>{body}<w:sectPr/></w:body></w:document>',
        "word/_rels/document.xml.rels": _rels([(rid, IMAGE_REL, f"media/{name}") for rid, (name, _) in media.items()]),
    }
    for name, data in media.values():
        files[f"word/media/{name}"] = data
    return _package(files)


def edge_case_docx() -> bytes:
    """엣지 케이스 1·2·3·4·5·10·11을 한 문서에 담는다."""
    body = "".join([
        para(run("보관 온도 -70℃ 이하, 압력 ≥ 2 bar, 허용 오차 ±0.5, 범위 10∓1")),
        para(run("기호 글꼴: 압력 "), sym("F0B3"), run(" 10 bar, 편차 "), sym("F0B1"), run("0.2")),
        para(run("면적 25 m"), run("2", sup=True), run(", 용매 H"), run("2", sub=True), run("O, 농도 10"), run("-3", sup=True), run(" mol")),
        para(run("내부 검토용 흰회색 문구", color="F2F2F2")),
        para(run("인쇄 안 되는 숨김 문구", vanish=True)),
        para(run("아래 표 참고"), floating_text_box(10, "표 위 메모: 재측정 필요")),
        table([
            [cell("시험 조건", span=3)],
            [cell("보관", vmerge="restart"), cell("온도"), cell("-70℃")],
            [cell("", vmerge="continue"), cell("습도"), cell("≤ 30%")],
        ], 3),
        para(run("측정 그림"), picture(20, "rIdPng", "rIdSvg")),
        para(picture_group(30, ["rIdG1", "rIdG2"])),
    ])
    return docx(body, {
        "rIdPng": ("image1.png", png()),
        "rIdSvg": ("image2.svg", svg_with_raster(["설정 온도 -70℃", "허용 편차 ±2℃"])),
        "rIdG1": ("image3.png", png(3, 3, (10, 200, 10))),
        "rIdG2": ("image4.png", png(2, 2, (10, 10, 200))),
    })


SYMBOL_SET = "℃±≥≤∓µΩ°²³×÷→∼‰"


def symbol_heavy_docx(total: int = 215) -> tuple[bytes, dict]:
    """특수기호가 많은 문서(엣지 케이스 7). 제곱은 유니코드 '²'와 위첨자 서식 '2'를 섞는다.
    반환: (파일, {문자: 기대 개수}). 위첨자 서식은 '²' 기대치에 포함한다."""
    expected: dict[str, int] = {}
    rows, count, i = [], 0, 0
    while count < total:
        char = SYMBOL_SET[i % len(SYMBOL_SET)]
        if char == "²" and i % 2:
            rows.append(para(run(f"{i}행 면적 {i} m"), run("2", sup=True)))
        else:
            rows.append(para(run(f"{i}행 값 {i}{char}")))
        expected[char] = expected.get(char, 0) + 1
        count += 1
        i += 1
    return docx("".join(rows)), expected


# ---------------------------------------------------------------- XLSX

XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _script_props(kind: str | None) -> str:
    if not kind:
        return ""
    return '<rPr><vertAlign val="%s"/></rPr>' % ("superscript" if kind == "sup" else "subscript")


def _shared(strings: list) -> str:
    items = []
    for value in strings:
        if isinstance(value, str):
            items.append(f'<si><t xml:space="preserve">{value}</t></si>')
        else:  # 서식 조각 목록 [(텍스트, 'sup'|'sub'|None)]
            runs = "".join("<r>" + _script_props(kind) + f'<t xml:space="preserve">{text}</t></r>' for text, kind in value)
            items.append(f"<si>{runs}</si>")
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            f'count="{len(strings)}" uniqueCount="{len(strings)}">{"".join(items)}</sst>')


STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
          '<font><sz val="11"/><color rgb="FFF2F2F2"/><name val="Calibri"/></font></fonts>'
          '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
          '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
          '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def _drawing(text_boxes: list[tuple[str, tuple[int, int, int, int]]], picture_anchor: tuple[int, int] | None) -> str:
    def marker(tag, col, row):
        return f"<xdr:{tag}><xdr:col>{col}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:{tag}>"
    anchors = []
    for index, (text, (c1, r1, c2, r2)) in enumerate(text_boxes, start=2):
        anchors.append(f'<xdr:twoCellAnchor>{marker("from", c1, r1)}{marker("to", c2, r2)}'
                       f'<xdr:sp macro="" textlink=""><xdr:nvSpPr><xdr:cNvPr id="{index}" name="TextBox {index}"/><xdr:cNvSpPr txBox="1"/></xdr:nvSpPr>'
                       '<xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr>'
                       f'<xdr:txBody><a:bodyPr/><a:p><a:r><a:t>{text}</a:t></a:r></a:p></xdr:txBody></xdr:sp><xdr:clientData/></xdr:twoCellAnchor>')
    if picture_anchor:
        col, row = picture_anchor
        anchors.append(f'<xdr:oneCellAnchor>{marker("from", col, row)}<xdr:ext cx="609600" cy="304800"/>'
                       '<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="9" name="Picture 9"/><xdr:cNvPicPr/></xdr:nvPicPr>'
                       f'<xdr:blipFill><a:blip xmlns:r="{R}" r:embed="rIdImg"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
                       '<xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:oneCellAnchor>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><xdr:wsDr xmlns:xdr="{XDR}" xmlns:a="{A}">'
            + "".join(anchors) + "</xdr:wsDr>")


def xlsx(rows: dict, *, merges: list[str] = (), text_boxes: list = (), picture_at: tuple[int, int] | None = None,
         sheet: str = "시험 조건", vba: bytes | None = None) -> bytes:
    """rows: {'A1': 값}. 값은 문자열, 숫자, 서식 조각 목록, 또는 ('흰회색', 문자열).
    vba를 주면 매크로 사용 통합문서(XLSM)로 만든다: 본문 형식과 xl/vbaProject.bin."""
    strings: list = []
    cells_by_row: dict[int, list[str]] = {}
    for ref, value in rows.items():
        row = int("".join(ch for ch in ref if ch.isdigit()))
        style = ""
        if isinstance(value, tuple) and value[0] == "흰회색":
            value, style = value[1], ' s="1"'
        if isinstance(value, (int, float)):
            xml = f'<c r="{ref}"{style}><v>{value}</v></c>'
        else:
            strings.append(value)
            xml = f'<c r="{ref}" t="s"{style}><v>{len(strings) - 1}</v></c>'
        cells_by_row.setdefault(row, []).append(xml)
    data = "".join(f'<row r="{row}">{"".join(cells)}</row>' for row, cells in sorted(cells_by_row.items()))
    merge_xml = (f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in merges) + "</mergeCells>") if merges else ""
    has_drawing = bool(text_boxes or picture_at)
    drawing_ref = '<drawing r:id="rIdD"/>' if has_drawing else ""
    sheet_xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="{R}">'
                 f'<sheetData>{data}</sheetData>{merge_xml}{drawing_ref}</worksheet>')
    overrides = {
        "/xl/workbook.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        "/xl/worksheets/sheet1.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
        "/xl/sharedStrings.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml",
        "/xl/styles.xml": "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml",
    }
    files = {
        "_rels/.rels": _rels([("rId1", R + "/officeDocument", "xl/workbook.xml")]),
        "xl/workbook.xml": (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="{R}">'
                            f'<sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        "xl/_rels/workbook.xml.rels": _rels([("rId1", R + "/worksheet", "worksheets/sheet1.xml"),
                                             ("rId2", R + "/sharedStrings", "sharedStrings.xml"),
                                             ("rId3", R + "/styles", "styles.xml")]),
        "xl/worksheets/sheet1.xml": sheet_xml,
        "xl/sharedStrings.xml": _shared(strings),
        "xl/styles.xml": STYLES,
    }
    if has_drawing:
        overrides["/xl/drawings/drawing1.xml"] = "application/vnd.openxmlformats-officedocument.drawing+xml"
        files["xl/worksheets/_rels/sheet1.xml.rels"] = _rels([("rIdD", R + "/drawing", "../drawings/drawing1.xml")])
        files["xl/drawings/drawing1.xml"] = _drawing(list(text_boxes), picture_at)
        if picture_at:
            files["xl/drawings/_rels/drawing1.xml.rels"] = _rels([("rIdImg", IMAGE_REL, "../media/image1.png")])
            files["xl/media/image1.png"] = png()
    if vba is not None:
        overrides["/xl/workbook.xml"] = "application/vnd.ms-excel.sheet.macroEnabled.main+xml"
        overrides["/xl/vbaProject.bin"] = "application/vnd.ms-office.vbaProject"
        files["xl/_rels/workbook.xml.rels"] = _rels([("rId1", R + "/worksheet", "worksheets/sheet1.xml"),
                                                     ("rId2", R + "/sharedStrings", "sharedStrings.xml"),
                                                     ("rId3", R + "/styles", "styles.xml"),
                                                     ("rId4", "http://schemas.microsoft.com/office/2006/relationships/vbaProject", "vbaProject.bin")])
        files["xl/vbaProject.bin"] = vba
    files["[Content_Types].xml"] = _types(overrides)
    return _package(files)


def edge_case_xlsx() -> bytes:
    """엣지 케이스 1·3·4(병합셀·첨자)·10(표 위 글상자)·11(흰회색 글자)."""
    return xlsx({
        "A1": "온도 조건",
        "A2": "항목", "B2": "기준", "C2": "단위", "D2": "비고",
        "A3": "보관 온도", "B3": "≤ −70", "C3": "℃", "D3": ("흰회색", "검토자 숨은 메모"),
        "A4": "면적", "B4": 25, "C4": [("m", None), ("2", "sup")],
        "A5": "허용 오차", "B5": "±0.5", "C5": [("mg/m", None), ("3", "sup")],
        "A6": "냉매", "B6": [("CO", None), ("2", "sub")], "C6": "-",
        "A7": "구간", "B7": "공통",
    }, merges=["A1:D1", "B7:D7"], text_boxes=[("표 위 글상자: 단위 확인 필요", (1, 2, 3, 4))], picture_at=(4, 2))


# ---------------------------------------------------------------- 보호·래핑 파일

def drm_wrapped(payload: bytes, tag: bytes = b"SYNTHETIC-DRM") -> bytes:
    """정상 OOXML 서명 대신 제품 머리말과 암호문처럼 보이는 본문을 가진 파일(엣지 케이스 8·9).
    실제 DRM 제품의 형식이 아니다. 판별 로직 시험용으로만 쓴다."""
    header = b"<" + tag + b" v1>" + b"\0" * (64 - len(tag) - 5)
    stream, block = b"", hashlib.sha256(payload).digest()
    while len(stream) < max(8192, len(payload)):
        block = hashlib.sha256(block).digest()
        stream += block
    return header + stream


def unmarked_ciphertext(size: int = 16384) -> bytes:
    """알려진 머리말 없이 처음부터 암호문처럼 보이는 파일."""
    stream, block = b"", b"seed"
    while len(stream) < size:
        block = hashlib.sha256(block).digest()
        stream += block
    return stream[:size]
