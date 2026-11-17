from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import zipfile
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.shared import Inches, Pt, RGBColor
from PIL import Image
import pypdfium2 as pdfium

NOTICE = '본 문서는 시험용으로 만든 가상 문서이며 실제 조직·제품·인물과 관계가 없습니다.'
COMPANY = 'Fabrikam Bio'
FONT = 'Apple SD Gothic Neo'
ACCENT = '234D62'
GRAY = '4D5A60'
ROOT = Path(os.environ['CORPUS_BUILD_DIR'])
CORPUS = ROOT / 'corpus'
WORK = ROOT / 'work'
OUTPUT = ROOT / 'delivery'
for directory in [CORPUS, WORK, OUTPUT]:
    directory.mkdir(parents=True, exist_ok=True)

MANIFEST = {}
GOLD = {}
QUESTIONS = []
PDF_JOBS = {}
SPAN_FIRST_ROWS = {'SOP-A1': 10, 'SOP-A2': 10, 'SOP-A3': 10, 'COA-1': 13, 'COA-3': 13}
DOCX_FILES = {}
FOLDERS = dict(enumerate([
    '01_sop', '02_reports', '03_certificates', '04_spreadsheets',
    '05_presentations', '06_mail', '07_archives', '08_scans', '09_images',
    '10_edge_cases',
], 1))


def register(file_id, folder, filename, title, *, priority='P0', department='QA',
             purposes='parse chunking embedding_eval vectordb', number=None, rev=None,
             issued='2026-10-15', family=None, latest=True, status='single', pair=None,
             notes='', pages=None, scanned=(), true_format=None, **flags):
    relative = f'{FOLDERS[folder]}/{filename}'
    extension = Path(filename).suffix[1:].lower()
    MANIFEST[file_id] = dict(
        file_id=file_id, path=relative, format=extension, true_format=true_format or extension,
        priority=priority, purposes=purposes.split(), language='ko', department=department,
        doc_number=number, revision=rev, issued=issued, family_id=family or number,
        is_latest_expected=latest, latest_status_expected=status, duplicate_of=None,
        pages=pages, scanned_pages=list(scanned), elements={}, tables=[],
        embedded_children=[], links=[], pair_with=pair, notes=notes,
        flags=dict(encrypted=False, password=None, extension_mismatch=False,
                   macro=False, truncated=False, empty=False) | flags,
    )
    GOLD[file_id] = dict(file_id=file_id, title=title, key_values=[], tables=[],
                         captions=[], numbers_with_units=[], headings=[], text_snippets=[])
    target = file_path(file_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def file_path(file_id):
    return CORPUS / MANIFEST[file_id]['path']


def link(file_id, written, location, state, targets=(), *, kind='doc_number', latest=None):
    entry = dict(kind=kind, target=written, location=location, expected_state=state,
                 expected_target_file_ids=list(targets), latest_file_id=latest)
    if entry not in MANIFEST[file_id]['links']:
        MANIFEST[file_id]['links'].append(entry)


def child(file_id, name, kind, fmt, inside=None):
    MANIFEST[file_id]['embedded_children'].append(
        dict(name=name, kind=kind, path_inside=inside or name, true_format=fmt)
    )


def question(file_id, prompt, answer, kind='text', location='p.1', *,
             ocr=False, hard=False, nested=None, phase=None):
    QUESTIONS.append(dict(
        question=prompt, doc_file_id=file_id,
        doc_path=MANIFEST[file_id]['path'] + (f'!/{nested}' if nested else ''),
        answer=answer, kind=kind, location=location, requires_ocr=ocr,
        difficulty='hard' if hard else ('medium' if ocr else 'easy'),
        phase=phase or int(MANIFEST[file_id]['priority'][-1]) + 1,
    ))


def gold_table(file_id, title, headers, rows, *, span=False, repeated=False,
               merged=False, location=None, page=None):
    table_id = f't{len(GOLD[file_id]["tables"]) + 1}'
    rows = [[str(value) if value is not None else '' for value in row] for row in rows]
    GOLD[file_id]['tables'].append(dict(
        id=table_id, caption=title, header=list(headers), rows=rows,
        **({'location': location} if location else {}), **({'page': page} if page else {}),
    ))
    MANIFEST[file_id]['tables'].append(dict(
        id=table_id, title=title, rows=len(rows), cols=len(headers),
        spans_pages=span, header_repeated=repeated, merged_cells=merged,
    ))


def evidence(file_id, **kwargs):
    for key, value in kwargs.items():
        GOLD[file_id].setdefault(key, []).extend(value)


def kv(file_id, page, **values):
    evidence(file_id, key_values=[dict(label=k, value=str(v), page=page) for k, v in values.items()])


def shade(cell, fill):
    cell._tc.get_or_add_tcPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill}"/>'))


def field(paragraph, instruction):
    node = OxmlElement('w:fldSimple')
    node.set(qn('w:instr'), instruction)
    paragraph._p.append(node)


def hyperlink(paragraph, label, target):
    rel = paragraph.part.relate_to(target, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    holder = OxmlElement('w:hyperlink')
    holder.set(qn('r:id'), rel)
    run = OxmlElement('w:r')
    run.append(parse_xml(f'<w:rPr {nsdecls("w")}><w:color w:val="14617E"/><w:u w:val="single"/></w:rPr>'))
    wording = OxmlElement('w:t')
    wording.text = label
    run.append(wording)
    holder.append(run)
    paragraph._p.append(holder)


def footnote(doc, text):
    namespace = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    scope = doc.part.package
    existing = [part for part in scope.parts if str(part.partname) == '/word/footnotes.xml']
    root = parse_xml(existing[0].blob) if existing else parse_xml(f'<w:footnotes {nsdecls("w")}/>')
    next_id = str(len(root) + 1)
    note = OxmlElement('w:footnote')
    note.set(qn('w:id'), next_id)
    paragraph = parse_xml(f'<w:p xmlns:w="{namespace}"><w:r><w:footnoteRef/></w:r><w:r><w:t/></w:r></w:p>')
    paragraph[-1][-1].text = ' ' + text
    paragraph[-1][-1].set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    note.append(paragraph)
    root.append(note)
    from lxml import etree
    payload = etree.tostring(root, encoding='UTF-8', xml_declaration=True)
    if existing:
        existing[0]._blob = payload
    else:
        part = Part(PackURI('/word/footnotes.xml'),
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml',
                    payload, scope)
        doc.part.relate_to(part, RELATIONSHIP_TYPE.FOOTNOTES)
    anchor = OxmlElement('w:footnoteReference')
    anchor.set(qn('w:id'), next_id)
    target = doc.paragraphs[-1]
    target.add_run()._r.append(anchor)


def columns(doc, count):
    from docx.enum.section import WD_SECTION
    section = doc.add_section(WD_SECTION.CONTINUOUS)
    cols = section._sectPr.find(qn('w:cols'))
    cols.set(qn('w:num'), str(count))
    cols.set(qn('w:space'), '430')


def textbox(doc, text):
    from lxml import etree
    node = parse_xml(f"""<w:r {nsdecls('w')} xmlns:v="urn:schemas-microsoft-com:vml">
    <w:pict><v:rect style="width:170pt;height:47pt" fillcolor="#ECF3F5" strokecolor="#7FA6B4">
    <v:textbox inset="6pt,5pt,6pt,5pt"><w:txbxContent><w:p><w:r><w:t/></w:r></w:p>
    </w:txbxContent></v:textbox></v:rect></w:pict></w:r>""")
    node.find('.//' + qn('w:t')).text = text
    doc.add_paragraph()._p.append(node)


def new_doc(title, running, display_notice=True):
    doc = Document()
    props = doc.core_properties
    props.title = title
    props.author = COMPANY
    props.subject = 'Fabrikam Bio 가상 문서 · 품질 시스템'
    section = doc.sections[0]
    section.page_width, section.page_height = Pt(595.28), Pt(841.89)
    section.left_margin, section.right_margin = Inches(.68), Inches(.68)
    section.top_margin, section.bottom_margin = Inches(.74), Inches(.68)
    section.header_distance, section.footer_distance = Inches(.35), Inches(.34)
    for name, size in [('Normal', 10.5), ('Title', 22), ('Subtitle', 11),
                       ('Heading 1', 15), ('Heading 2', 12), ('Caption', 9),
                       ('List Bullet', 10.5), ('List Number', 10.5)]:
        style = doc.styles[name]
        style.font.name = FONT
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(ACCENT if name.startswith('Heading') else '25313A')
        style.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), FONT)
        style.paragraph_format.space_before = Pt(9 if name.startswith('Heading') else 0)
        style.paragraph_format.space_after = Pt(6)
        style.paragraph_format.line_spacing = 1.22
    if running:
        head = section.header.paragraphs[0]
        run = head.add_run(running)
        run.font.name, run.font.size, run.font.color.rgb = FONT, Pt(8.5), RGBColor.from_string(ACCENT)
        run._r.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), FONT)
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        footer.add_run('대외비 · 가상 문서   |   페이지 ')
        field(footer, 'PAGE')
        footer.add_run(' / ')
        field(footer, 'NUMPAGES')
        for run in footer.runs:
            run.font.size = Pt(8)
    if display_notice:
        paragraph = doc.add_paragraph(NOTICE)
        paragraph.runs[0].font.size = Pt(8)
        paragraph.runs[0].font.color.rgb = RGBColor.from_string(GRAY)
        doc.add_paragraph(title, 'Title')
    return doc


def word_table(doc, headers, rows, *, widths=None, row_pt=0, merge=False, repeat=True):
    table = doc.add_table(rows=len(rows) + 1, cols=len(headers))
    table.style = 'Table Grid'
    if widths:
        table.autofit = False
        for column, width in zip(table.columns, widths):
            column.width = Inches(width)
    for index, (row, values) in enumerate(zip(table.rows, [headers, *rows])):
        props = row._tr.get_or_add_trPr()
        props.append(OxmlElement('w:cantSplit'))
        if index == 0 and repeat:
            props.append(OxmlElement('w:tblHeader'))
        if row_pt:
            row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
            row.height = Pt(row_pt if index else min(row_pt, 25))
        for col, (cell, value) in enumerate(zip(row.cells, values)):
            if widths:
                cell.width = Inches(widths[col])
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_before = Pt(2.2)
            paragraph.paragraph_format.space_after = Pt(2.2)
            paragraph.paragraph_format.line_spacing = 1.10
            run = paragraph.add_run(str(value))
            run.font.size = Pt(8 if len(headers) > 7 else 9)
            run.bold = index == 0
            if index == 0:
                shade(cell, ACCENT)
                run.font.color.rgb = RGBColor.from_string('FFFFFF')
            elif index % 2 == 0:
                shade(cell, 'EEF3F5')
    if merge:
        row_index, first, last = merge
        table.cell(row_index, first).merge(table.cell(row_index, last))
    return table


def h(text, level=1): return ('heading', text, level)
def p(text): return ('paragraph', text)
def bullet(text): return ('list', text, 'List Bullet')
def numbered(text): return ('list', text, 'List Number')
def note(text): return ('footnote', text)
def box(text): return ('textbox', text)
def col(n): return ('columns', n)
def href(label, target): return ('hyperlink', label, target)
def fig(path, caption=None, width=5.8): return ('image', path, caption, width)


def t(title, headers, rows, *, row_pt=0, span=False, widths=None, merge=False):
    return ('table', title, headers, rows, row_pt, span, widths, merge)


def build_word(file_id, pages, *, running=None, pdf=False, hidden=False):
    meta = MANIFEST[file_id]
    title = GOLD[file_id]['title']
    running = running or ' | '.join(filter(None, [COMPANY, meta['doc_number'], meta['revision'], title]))
    doc = new_doc(title, running)
    elements = dict(headings=1, paragraphs=1, lists=0, tables=0, images=0, captions=0,
                    uncaptioned_images=0, footnotes=0, repeated_header_lines=0, page_number_lines=0,
                    textboxes=0)
    gold = GOLD[file_id]
    offset = 0
    for logical_page, blocks in enumerate(pages, 1):
        if logical_page > 1:
            doc.add_page_break()
        for block in blocks:
            page = logical_page + offset
            key, value, *options = block
            if key == 'heading':
                doc.add_heading(value, options[0])
                gold['headings'].append(value)
                elements['headings'] += 1
            elif key in ('paragraph', 'list'):
                doc.add_paragraph(value, options[0] if options else 'Normal')
                gold['text_snippets'].append(value)
                elements['paragraphs' if key == 'paragraph' else 'lists'] += 1
            elif key == 'table':
                headers, rows, row_pt, span, widths, merge = options
                doc.add_paragraph(value, 'Caption')
                word_table(doc, headers, rows, widths=widths, row_pt=row_pt, merge=merge)
                gold_table(file_id, value, headers, rows, span=span, repeated=span,
                           merged=bool(merge), page=page)
                gold['captions'].append(dict(kind='table', text=value, page=page))
                elements['tables'] += 1
                elements['captions'] += 1
                if span:
                    offset += 1
            elif key == 'image':
                caption, width = options
                picture = doc.add_paragraph()
                picture.alignment = WD_ALIGN_PARAGRAPH.CENTER
                picture.add_run().add_picture(str(value), width=Inches(width))
                elements['images'] += 1
                if caption:
                    doc.add_paragraph(caption, 'Caption')
                    gold['captions'].append(dict(kind='figure', text=caption, page=page))
                    elements['captions'] += 1
                else:
                    elements['uncaptioned_images'] += 1
            elif key == 'hyperlink':
                hyperlink(doc.add_paragraph(), value, options[0])
                elements['paragraphs'] += 1
            elif key == 'footnote':
                footnote(doc, value)
                gold['text_snippets'].append(value)
                elements['footnotes'] += 1
            elif key == 'columns':
                columns(doc, value)
            elif key == 'textbox':
                textbox(doc, value)
                gold['text_snippets'].append(value)
                elements['textboxes'] += 1
    meta['pages'] = len(pages) + offset
    elements['repeated_header_lines'] = meta['pages']
    elements['page_number_lines'] = meta['pages']
    meta['elements'] = elements
    target = WORK / f'{file_id}.docx' if pdf or hidden else file_path(file_id)
    doc.save(target)
    DOCX_FILES[file_id] = target
    set_docx_pages(target, meta['pages'])
    PDF_JOBS[file_id] = (title, running, pages)
    return target


def clone(old, new):
    original = MANIFEST[old]
    for key in ['elements', 'tables', 'links']:
        MANIFEST[new][key] = deepcopy(original[key])
    GOLD[new] = deepcopy(GOLD[old])
    GOLD[new]['file_id'] = new


def pdf_text(page):
    with page.get_textpage() as reader:
        return reader.get_text_bounded().replace('\r\n', '\n')


def set_docx_pages(path, count):
    from lxml import etree
    with zipfile.ZipFile(path) as z:
        parts = {name: z.read(name) for name in z.namelist()}
    xml = etree.fromstring(parts['docProps/app.xml'])
    for node in xml:
        if node.tag.endswith('}Pages'):
            node.text = str(count)
    parts['docProps/app.xml'] = etree.tostring(xml, encoding='UTF-8', xml_declaration=True)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)


def pdf_pages(file_id, logical_pages):
    cols = 1
    output = []
    for page in logical_pages:
        blocks = []
        page_cols = cols
        for kind, value, *options in page:
            if kind == 'columns':
                cols = value
                if not blocks:
                    page_cols = value
                continue
            block = dict(type=kind, text=str(value))
            if kind == 'heading':
                block['level'] = options[0]
            elif kind == 'list':
                block['level'] = 2 if options[0] == 'List Number' else 1
            elif kind == 'hyperlink':
                block['target'] = options[0]
            elif kind == 'image':
                block.update(image=str(value), caption=options[0], width=options[1])
            elif kind == 'table':
                headers, rows, row_pt, span, widths, _ = options
                block.update(headers=list(headers), rows=[[str(cell) for cell in row] for row in rows],
                             rowHeight=row_pt or 20, widths=widths)
                if span:
                    if file_id.startswith('SOP-'):
                        block['rowHeight'] = 23
                    split = SPAN_FIRST_ROWS[file_id]
                    blocks.append(dict(block, rows=block['rows'][:split]))
                    output.append(dict(blocks=blocks, columns=page_cols))
                    blocks = [dict(block, text='', rows=block['rows'][split:])]
                    continue
            blocks.append(block)
        output.append(dict(blocks=blocks, columns=page_cols))
    return output


def render_digital_pdfs():
    out = WORK / 'pdf'
    out.mkdir(exist_ok=True)
    active_jobs = ['SOP-A3','SOP-B0','RPT-1','RPT-2','RPT-4','COA-1','EDGE-1','EDGE-5']
    jobs = []
    for file_id in active_jobs:
        title, running, pages = PDF_JOBS[file_id]
        jobs.append(dict(id=file_id, title=title, running=running, notice=NOTICE,
                         path=str(out / f'{file_id}.pdf'), pages=pdf_pages(file_id, pages),
                         password=MANIFEST[file_id]['flags']['password']))
    input_path = WORK / 'render-jobs.json'
    input_path.write_text(dump(jobs), encoding='utf-8')
    cache = WORK/'swift-cache'
    cache.mkdir(exist_ok=True)
    renderer = Path(__file__).with_name('render_pdf.swift')
    subprocess.run(['swift', '-module-cache-path', str(cache), str(renderer), str(input_path)],
                   timeout=240, check=True, env=os.environ | {'CLANG_MODULE_CACHE_PATH': str(cache)})
    for file_id in active_jobs:
        path = out / f'{file_id}.pdf'
        meta = MANIFEST[file_id]
        with pdfium.PdfDocument(path, password=meta['flags']['password']) as doc:
            assert len(doc) == meta['pages'], (file_id, len(doc), meta['pages'])
        if meta['true_format'] == 'pdf':
            file_path(file_id).write_bytes(path.read_bytes())
    return out


def make_image_pdf(destination, images, sizes=None, rotations=None):
    with pdfium.PdfDocument.new() as doc:
        for index, source in enumerate(images):
            image = Image.open(source) if isinstance(source, (Path, str)) else source
            blob = io.BytesIO()
            image.convert('RGB').save(blob, 'JPEG', quality=85, optimize=True)
            width, height = sizes[index] if sizes else (595.28, 841.89)
            with doc.new_page(width, height) as page:
                obj = pdfium.PdfImage.new(doc)
                obj.load_jpeg(blob)
                obj.set_matrix(pdfium.PdfMatrix().scale(width, height))
                page.insert_obj(obj)
                page.gen_content()
                if rotations and rotations[index]:
                    page.set_rotation(rotations[index])
        doc.save(destination)


def jpeg_bytes(image, quality=85):
    buffer = io.BytesIO()
    image.convert('RGB').save(buffer, 'JPEG', quality=quality, optimize=True)
    return buffer.getvalue()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def dump(data):
    return json.dumps(data, ensure_ascii=False, indent=2) + '\n'


def numbers(values):
    pattern = r'(?:[≤≥<>±]\s*)?-?\d+(?:[.,]\d+)*(?:E[+-]\d+)?\s*(?:mg/mL|EU/mg|CFU/mL|µS/cm|%RH|mm/s|cm²|ppb|ppm|rpm|bar|mL|°C|Hz|kPa|MΩ|V|%|분|개월)(?![A-Za-z0-9])'
    return list(dict.fromkeys(match.group() for value in values for match in re.finditer(pattern, value)))
