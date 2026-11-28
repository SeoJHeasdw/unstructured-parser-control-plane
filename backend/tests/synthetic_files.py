"""테스트용 합성 파일 생성기. 실제 문서를 쓰지 않는다."""
from email.message import EmailMessage
import io
import math
import struct
import zipfile
import zlib

END, FREE, FATSECT, NOSTREAM = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD, 0xFFFFFFFF


def cfb(tree: dict) -> bytes:
    """{이름: bytes | dict} 트리로 CFB(v3, 512바이트 섹터) 파일을 만든다. 작은 스트림은 미니 스트림에 둔다."""
    entries = [{"name": "Root Entry", "type": 5, "data": b"", "kids": []}]

    def add(name, node):
        index = len(entries)
        entry = {"name": name, "type": 1 if isinstance(node, dict) else 2, "data": b"" if isinstance(node, dict) else node, "kids": []}
        entries.append(entry)
        if isinstance(node, dict):
            for key, value in node.items():
                entry["kids"].append(add(key, value))
        return index

    for key, value in tree.items():
        entries[0]["kids"].append(add(key, value))
    mini, minifat = b"", []
    big = []
    for entry in entries[1:]:
        if entry["type"] != 2:
            entry["start"], entry["size"] = END, 0
            continue
        data = entry["data"]
        entry["size"] = len(data)
        if len(data) < 4096:
            count = max(1, math.ceil(len(data) / 64))
            entry["start"] = len(mini) // 64
            minifat.extend(list(range(entry["start"] + 1, entry["start"] + count)) + [END])
            mini += data.ljust(count * 64, b"\0")
        else:
            big.append(entry)
    dir_bytes_len = math.ceil(len(entries) / 4) * 512
    sectors, chains = 0, {}

    def alloc(name, length):
        nonlocal sectors
        count = math.ceil(length / 512) if length else 0
        chains[name] = list(range(sectors, sectors + count))
        sectors += count
        return chains[name][0] if count else END

    first_dir = alloc("dir", dir_bytes_len)
    first_minifat = alloc("minifat", len(minifat) * 4)
    entries[0]["start"] = alloc("mini", len(mini))
    entries[0]["size"] = len(mini)
    for i, entry in enumerate(big):
        entry["start"] = alloc(f"big{i}", len(entry["data"]))
    n_fat = 1
    while (sectors + n_fat) > n_fat * 128:
        n_fat += 1
    fat_ids = list(range(sectors, sectors + n_fat))
    fat = [FREE] * (n_fat * 128)
    for chain in chains.values():
        for a, b in zip(chain, chain[1:] + [END]):
            fat[a] = b
    for sid in fat_ids:
        fat[sid] = FATSECT
    # directory
    for entry in entries:
        entry.setdefault("left", NOSTREAM)
        entry.setdefault("right", NOSTREAM)
        entry["child"] = entry["kids"][0] if entry["kids"] else NOSTREAM
        for a, b in zip(entry["kids"], entry["kids"][1:]):
            entries[a]["right"] = b
    directory = b""
    for entry in entries:
        name = entry["name"].encode("utf-16-le") + b"\0\0"
        raw = name.ljust(64, b"\0") + struct.pack("<HBBIII", len(name), entry["type"], 1, entry["left"], entry["right"], entry["child"])
        raw += b"\0" * 16 + b"\0" * 4 + b"\0" * 16 + struct.pack("<IQ", entry["start"], entry["size"])
        directory += raw
    directory = directory.ljust(dir_bytes_len, b"\0")
    body = directory + struct.pack(f"<{len(minifat)}I", *minifat).ljust(len(chains["minifat"]) * 512, b"\xff") + mini.ljust(len(chains["mini"]) * 512, b"\0")
    for entry in big:
        body += entry["data"].ljust(math.ceil(len(entry["data"]) / 512) * 512, b"\0")
    body += struct.pack(f"<{len(fat)}I", *fat)
    difat = fat_ids + [FREE] * (109 - len(fat_ids))
    header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 16 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\0" * 6
    header += struct.pack("<IIIIIIIII", 0, n_fat, first_dir, 0, 4096, first_minifat if minifat else END, len(chains["minifat"]), END, 0)
    header += struct.pack("<109I", *difat)
    return header + body


def ovba_compress(data: bytes) -> bytes:
    """[MS-OVBA] 2.4.1 압축 컨테이너. 복사 토큰 없이 글자 토큰만 쓴다(꽉 찬 4096바이트 조각은 비압축 조각)."""
    out = bytearray(b"\x01")
    for start in range(0, len(data), 4096):
        block = data[start:start + 4096]
        if len(block) == 4096:
            out += struct.pack("<H", 0x3FFF) + block
            continue
        body = bytearray()
        for index in range(0, len(block), 8):
            body += b"\x00" + block[index:index + 8]
        if len(body) + 2 > 4098:
            raise ValueError("마지막 조각이 너무 깁니다.")
        out += struct.pack("<H", 0xB000 | (len(body) + 2 - 3)) + body
    return bytes(out)


def vba_project(modules: dict, codepage: int = 949, strip: tuple = ()) -> bytes:
    """{모듈 이름: (소스, 'standard'|'document')} → vbaProject.bin. strip에 든 모듈은 소스를 지운다(p-code만 남은 경우)."""
    codec = f"cp{codepage}"

    def record(ident, value=b""):
        return struct.pack("<HI", ident, len(value)) + value

    def text(ident, unicode_ident, value):
        return record(ident, value.encode(codec)) + record(unicode_ident, value.encode("utf-16-le"))

    directory = (record(0x0001, struct.pack("<I", 1)) + record(0x0002, struct.pack("<I", 0x0412)) + record(0x0014, struct.pack("<I", 0x0412))
                 + record(0x0003, struct.pack("<H", codepage)) + record(0x0004, b"VBAProject") + text(0x0005, 0x0040, "")
                 + text(0x0006, 0x003D, "") + record(0x0007, struct.pack("<I", 0)) + record(0x0008, struct.pack("<I", 0))
                 + struct.pack("<HIIH", 0x0009, 4, 0x5B, 0x0002) + text(0x000C, 0x003C, "")
                 + text(0x0016, 0x003E, "stdole") + record(0x000D, b"*\\G{00020430-0000-0000-C000-000000000046}#2.0#0#stdole2.tlb#OLE Automation")
                 + record(0x000F, struct.pack("<H", len(modules))) + record(0x0013, struct.pack("<H", 0xFFFF)))
    streams = {}
    for index, (name, (source, kind)) in enumerate(modules.items()):
        stream = f"Mod{index}" if name.isascii() else f"M{index}"
        cache = bytes(range(16)) * 8  # 성능 캐시 자리(MODULEOFFSET 앞부분)
        streams[stream] = cache + (b"" if name in strip else ovba_compress(source.replace("\n", "\r\n").encode(codec)))
        directory += (text(0x0019, 0x0047, name) + text(0x001A, 0x0032, stream) + text(0x001C, 0x0048, "")
                      + record(0x0031, struct.pack("<I", len(cache))) + record(0x001E, struct.pack("<I", 0))
                      + record(0x002C, struct.pack("<H", 0xFFFF)) + record(0x0021 if kind == "standard" else 0x0022) + record(0x002B))
    directory += record(0x0010)
    return cfb({"VBA": {"dir": ovba_compress(directory), "_VBA_PROJECT": b"\xcc\x61\xff\xff\x00\x00\x00", **streams},
                "PROJECT": b'ID="{00000000-0000-0000-0000-000000000000}"\r\n', "PROJECTwm": b"\0\0"})


def ole_package(filename: str, payload: bytes) -> bytes:
    name = filename.encode("cp949")
    native = struct.pack("<H", 2) + name + b"\0" + b"C:\\temp\\" + name + b"\0" + struct.pack("<II", 0x00030000, 0) + b"C:\\temp\\" + name + b"\0" + struct.pack("<I", len(payload)) + payload
    return cfb({"\x01Ole10Native": struct.pack("<I", len(native)) + native, "\x01CompObj": b"\x01\x00\xfe\xff"})


def zip_bytes(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def raw_zip(items: list) -> bytes:
    """(이름 바이트, 내용, 플래그) 목록으로 비압축 ZIP을 직접 만든다. CP949 파일명·암호 표시 재현용."""
    local, central, offset = b"", b"", 0
    for name, data, flags in items:
        crc = zlib.crc32(data)
        header = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, flags, 0, 0, 0, crc, len(data), len(data), len(name), 0) + name
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, flags, 0, 0, 0, crc, len(data), len(data), len(name), 0, 0, 0, 0, 0, offset) + name
        local += header + data
        offset += len(header) + len(data)
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(items), len(items), len(central), offset, 0)
    return local + central + end


def xlsx(cells: dict, hyperlinks: dict = (), external: str | None = None, sheet="점검 이력") -> bytes:
    strings = [v for v in cells.values() if not v.startswith("=")]
    rows = ""
    for ref, value in cells.items():
        if value.startswith("="):
            rows += f'<c r="{ref}"><f>{value[1:].replace("&", "&amp;").replace(chr(34), "&quot;")}</f><v>0</v></c>'
        else:
            rows += f'<c r="{ref}" t="s"><v>{strings.index(value)}</v></c>'
    links = "".join(f'<hyperlink ref="{ref}" r:id="rIdH{i}"/>' for i, ref in enumerate(dict(hyperlinks)))
    sheet_xml = f'<worksheet xmlns:r="r"><sheetData><row>{rows}</row></sheetData><hyperlinks>{links}</hyperlinks></worksheet>'
    sheet_rels = "".join(f'<Relationship Id="rIdH{i}" Type="http://x/hyperlink" Target="{target}" TargetMode="External"/>' for i, target in enumerate(dict(hyperlinks).values()))
    files = {
        "[Content_Types].xml": "<Types/>",
        "xl/workbook.xml": f'<workbook xmlns:r="r"><sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="rId1" Type="http://x/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": sheet_xml,
        "xl/worksheets/_rels/sheet1.xml.rels": f"<Relationships>{sheet_rels}</Relationships>",
        "xl/sharedStrings.xml": "<sst>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>",
    }
    if external:
        files["xl/externalLinks/externalLink1.xml"] = "<externalLink/>"
        files["xl/externalLinks/_rels/externalLink1.xml.rels"] = f'<Relationships><Relationship Id="rId1" Type="http://x/externalLinkPath" Target="{external}" TargetMode="External"/></Relationships>'
    return zip_bytes(files)


def docx(paragraphs: list, embeddings: dict = (), hyperlink: str | None = None, macro=False) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" if not p.startswith("FIELD:") else f'<w:p><w:r><w:instrText xml:space="preserve"> {p[6:]} </w:instrText></w:r></w:p>' for p in paragraphs)
    files = {"[Content_Types].xml": "<Types/>", "word/document.xml": f"<w:document><w:body>{body}</w:body></w:document>", "word/media/image1.png": b"\x89PNG fake"}
    if hyperlink:
        files["word/_rels/document.xml.rels"] = f'<Relationships><Relationship Id="rId9" Type="http://x/hyperlink" Target="{hyperlink}" TargetMode="External"/></Relationships>'
    for name, data in dict(embeddings).items():
        files[f"word/embeddings/{name}"] = data
    if macro:
        files["word/vbaProject.bin"] = b"\0"
    return zip_bytes(files)


def pdf_with_attachment(uri: str, attachment_name: str, attachment: bytes) -> bytes:
    stream = zlib.compress(attachment)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles << /Names [(a) 5 0 R] >> >> >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Annots [4 0 R] >>",
        b"<< /Type /Annot /Subtype /Link /A << /S /URI /URI (" + uri.encode() + b") >> >>",
        b"<< /Type /Filespec /F (" + attachment_name.encode() + b") /EF << /F 6 0 R >> >>",
        b"<< /Type /EmbeddedFile /Filter /FlateDecode /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = b"%PDF-1.7\n"
    for i, body in enumerate(objects, start=1):
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    return out + b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"


def eml(body: str, attachments: dict = (), nested: EmailMessage | None = None, html: str | None = None) -> bytes:
    message = EmailMessage()
    message["Subject"] = "변경 요청 회신"
    message["From"] = "a@example.com"
    message["To"] = "b@example.com"
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    for name, data in dict(attachments).items():
        message.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    if nested is not None:
        message.add_attachment(nested)
    return message.as_bytes()


def msg(subject: str, body: str, attachments: dict) -> bytes:
    tree = {"__properties_version1.0": b"\0" * 32, "__substg1.0_0037001F": subject.encode("utf-16-le"), "__substg1.0_1000001F": body.encode("utf-16-le")}
    for i, (name, data) in enumerate(dict(attachments).items()):
        tree[f"__attach_version1.0_#{i:08X}"] = {"__properties_version1.0": b"\0" * 16, "__substg1.0_3707001F": name.encode("utf-16-le"), "__substg1.0_37010102": data}
    return cfb(tree)


def msg_props(header: int, fixed: dict = ()) -> bytes:
    """[MS-OXMSG] 2.4 속성 스트림. fixed: {(속성 ID, 형식): 값}. 형식 0x0003(LONG)·0x000B(BOOLEAN)·0x0040(SYSTIME)."""
    out = b"\0" * header
    for (prop, kind), value in dict(fixed).items():
        raw = struct.pack("<q" if kind == 0x0040 else "<i", int(value)).ljust(8, b"\0")
        out += struct.pack("<II", (prop << 16) | kind, 0x06) + raw
    return out


def outlook_message(subject: str, *, sender=("", ""), recipients=(), body: str | None = None, html: bytes | None = None,
                    rtf: bool = False, attachments=(), codepage: int | None = None, string8: bool = False,
                    headers: str | None = None, message_class: str = "IPM.Note", embedded: bool = False) -> dict:
    """MSG 저장소 트리 한 벌. recipients: [(이름, 주소, 1=받는 사람·2=참조)].
    attachments: [{'name','data','mime','cid','hidden'} 또는 {'name','message': outlook_message(..., embedded=True)}]"""
    encoding, suffix = ("cp949", "001E") if string8 else ("utf-16-le", "001F")

    def text(prop: int, value: str) -> tuple[str, bytes]:
        return f"__substg1.0_{prop:04X}{suffix}", value.encode(encoding)

    fixed = {(0x3FFD, 0x0003): codepage} if codepage else {}
    tree = dict([text(0x001A, message_class), text(0x0037, subject)])
    if sender[0]:
        tree.update([text(0x0C1A, sender[0])])
    if sender[1]:
        tree.update([text(0x5D01, sender[1])])
    if body is not None:
        tree.update([text(0x1000, body)])
    if html is not None:
        tree["__substg1.0_10130102"] = html
    if rtf:
        tree["__substg1.0_10090102"] = b"\x10\0\0\0\x08\0\0\0MELA\0\0\0\0{\\rtf1}"
    if headers:
        tree.update([text(0x007D, headers)])
    for index, (name, address, kind) in enumerate(recipients):
        tree[f"__recip_version1.0_#{index:08X}"] = {"__properties_version1.0": msg_props(8, {(0x0C15, 0x0003): kind}),
                                                     **dict([text(0x3001, name), text(0x39FE, address)])}
    for index, item in enumerate(attachments):
        node = dict([text(0x3707, item["name"])])
        props = {}
        if "message" in item:
            props[(0x3705, 0x0003)] = 5
            node["__substg1.0_3701000D"] = item["message"]
        else:
            props[(0x3705, 0x0003)] = 1
            node["__substg1.0_37010102"] = item["data"]
            if item.get("mime"):
                node.update([text(0x370E, item["mime"])])
            if item.get("cid"):
                node.update([text(0x3712, item["cid"])])
            if item.get("hidden"):
                props[(0x7FFE, 0x000B)] = 1
        node["__properties_version1.0"] = msg_props(8, props)
        tree[f"__attach_version1.0_#{index:08X}"] = node
    tree["__properties_version1.0"] = msg_props(24 if embedded else 32, fixed)
    return tree


def outlook_msg(subject: str, **kwargs) -> bytes:
    return cfb(outlook_message(subject, **kwargs))
