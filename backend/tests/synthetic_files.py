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
