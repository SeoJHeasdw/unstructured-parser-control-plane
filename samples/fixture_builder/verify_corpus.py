"""Validate an unpacked Fabrikam Bio corpus. Combine earlier phase ZIPs before validating a later phase."""

from __future__ import annotations

from contextlib import closing

import argparse
import csv
from datetime import date, datetime
from collections import Counter
from email import policy
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import unquote
import zipfile

from docx import Document
from lxml import etree
from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries
from PIL import Image
import pypdfium2 as pdfium
from pptx import Presentation

HANGUL = re.compile(r'[가-힣]')
BAD_GLYPH = re.compile(r'[\ufffd\u25a0\u25a1]')
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
DIMENSIONS = {
    'SOP-A1':6,'SOP-A2':6,'SOP-A3':6,'SOP-A3P':6,'SOP-A4':6,
    'SOP-B1':4,'SOP-B2':4,'SOP-B0':4,'SOP-C1':3,'SOP-C2':3,'SOP-C3':3,
    'RPT-1':7,'RPT-1P':7,'RPT-2':4,'RPT-2P':4,'RPT-3':4,'RPT-4':10,
    'COA-1':3,'COA-1S':3,'COA-3':3,'PPT-1':12,'PPT-2':8,'PPT-3':8,
    'SCN-1':3,'SCN-3':3,'EDGE-5':120,'EDGE-6':2,
}


def normalize(value):
    return unicodedata.normalize('NFC', value.replace('\r\n','\n'))


def zip_reader(payload, windows=False):
    return zipfile.ZipFile(io.BytesIO(payload),metadata_encoding='cp949' if windows else None)


def raw_email(payload):
    return BytesParser(policy=policy.default).parsebytes(payload)


def archive_item(z, name):
    by_name={normalize(n):n for n in z.namelist()}
    return z.read(by_name[normalize(name)])


def child_bytes(blob, fmt, path, *, windows=False):
    parts=path.split('!/')
    name=parts[0]
    if fmt=='zip':
        with zip_reader(blob,windows) as z:
            payload=archive_item(z,name)
    elif fmt=='pdf':
        with pdfium.PdfDocument(blob) as doc:
            attachments={normalize(doc.get_attachment(i).get_name()):doc.get_attachment(i)
                         for i in range(doc.count_attachments())}
            payload=bytes(attachments[normalize(name)].get_data())
    elif fmt in {'docx','xlsx','pptx'}:
        with zip_reader(blob) as z:
            payload=archive_item(z,name)
    elif fmt=='eml':
        mail=raw_email(blob)
        attachment=next(p for p in mail.iter_attachments() if normalize(p.get_filename() or '')==normalize(name))
        payload=(attachment.get_payload(0).as_bytes(policy=policy.SMTP)
                 if attachment.get_content_type()=='message/rfc822' else attachment.get_payload(decode=True))
    else:
        raise AssertionError((fmt,path))
    return child_bytes(payload,Path(name).suffix[1:], '!/'.join(parts[1:])) if len(parts)>1 else payload


def office_xml(payload, paths, namespace):
    strings=[]
    with zip_reader(payload) as z:
        for name in z.namelist():
            if paths(name):
                root=etree.fromstring(z.read(name))
                strings.extend(root.xpath('//*[local-name()="t" and namespace-uri()=$ns]/text()',ns=namespace))
            if name.endswith('.rels'):
                strings.extend(root_uris(z.read(name)))
    return strings


def root_uris(rel_xml):
    root=etree.fromstring(rel_xml)
    return [unquote(node.get('Target','')) for node in root if node.get('TargetMode')=='External']


def pdf_extract(blob,password):
    with pdfium.PdfDocument(blob,password=password) as doc:
        texts=[]
        for page in doc:
            with closing(page), closing(page.get_textpage()) as layer:
                texts.append(normalize(layer.get_text_bounded()))
        return texts


def html_text(source):
    tree=etree.HTML(source)
    return ' '.join(tree.itertext()) if tree is not None else ''


def plain(blob, encoding=None):
    if encoding:
        return blob.decode(encoding)
    try:
        return blob.decode('utf-8-sig')
    except UnicodeDecodeError:
        return blob.decode('cp949')


def extract(blob, fmt, password=None, encoding=None):
    if fmt=='pdf':
        return '\n'.join(pdf_extract(blob,password))
    if fmt=='docx':
        return normalize('\n'.join(office_xml(blob,
            lambda n: re.fullmatch(r'word/(?:document|header\d+|footer\d+|footnotes)\.xml',n),W)))
    if fmt=='pptx':
        return normalize('\n'.join(office_xml(blob,
            lambda n: re.fullmatch(r'ppt/(?:slides/slide|notesSlides/notesSlide|charts/chart)\d+\.xml',n),A)))
    if fmt=='xlsx':
        parts=[]
        for cached in (False,True):
            book=load_workbook(io.BytesIO(blob),data_only=cached)
            for sheet in book:
                for row in sheet.iter_rows():
                    for cell in row:
                        if cell.value is not None:
                            parts.append(str(cell.value))
                        if cell.hyperlink:
                            parts.append(cell.hyperlink.target)
            if not cached:
                for external in book._external_links:
                    parts.append(f'[{external.file_link.Target}]')
            book.close()
        return normalize('\n'.join(parts))
    if fmt=='eml':
        mail=raw_email(blob)
        return normalize('\n'.join([str(mail['Subject']), *[
            html_text(part.get_content()) if part.get_content_subtype()=='html' else part.get_content()
            for part in mail.walk() if part.get_content_maintype()=='text'
        ]]))
    if fmt in {'csv','txt','md'}:
        return normalize(plain(blob,encoding))
    return ''



def cell_text(cell):
    value=cell.value
    if value is None:
        return ''
    if isinstance(value,(date,datetime)):
        return value.strftime('%Y.%m.%d' if cell.number_format=='yyyy.mm.dd' else '%Y-%m-%d')
    formats={'0%':'.0%','0.00%':'.2%','0.00':'.2f'}
    return format(value,formats[cell.number_format]) if cell.number_format in formats else str(value)


def sheet_gold(cache, gold, metadata):
    for table, meta in zip(gold['tables'],metadata,strict=True):
        tab,cell_range=table['location'].rsplit('!',1)
        sheet=cache[tab]
        x1,y1,x2,y2=range_boundaries(cell_range)
        displayed=[[cell_text(cell) for cell in row]
                   for row in sheet.iter_rows(min_row=y1,max_row=y2,min_col=x1,max_col=x2)]
        expected_header=gold.get('display_header_rows') if meta['merged_cells'] else [table['header']]
        assert displayed==[*expected_header,*table['rows']],(gold['file_id'],tab,'XLSX gold table')


def verify_office(record, blob, gold):
    file_id=record['file_id']
    fmt=record['true_format']
    if fmt=='docx':
        document=Document(io.BytesIO(blob))
        if not record['flags']['empty']:
            native_tables=document.tables
            assert len(native_tables)==len(gold['tables']),(file_id,'DOCX table count')
            for actual,table in zip(native_tables,gold['tables']):
                expected=[table['header'],*table['rows']]
                displayed=[[c.text for c in row.cells] for row in actual.rows]
                assert displayed==expected,(file_id,'DOCX gold table',table['id'])
            with zip_reader(blob) as z:
                body=etree.fromstring(z.read('word/document.xml'))
                breaks=body.xpath('count(//w:br[@w:type="page"])',namespaces={'w':W})
                spans=sum(t['spans_pages'] for t in record['tables'])
                app=etree.fromstring(z.read('docProps/app.xml'))
                stored=int(app.xpath('//*[local-name()="Pages"]/text()')[0])
                assert 1+int(breaks)+spans==record['pages']==stored,(file_id,breaks,spans,stored)
                if spans:
                    assert body.xpath('//w:tblHeader',namespaces={'w':W}),file_id
                if file_id=='SOP-A3':
                    assert 'word/footnotes.xml' in z.namelist(),file_id
                if file_id=='SOP-C3':
                    assert body.xpath('//w:cols[@w:num="2"] | //w:txbxContent',namespaces={'w':W})
    elif fmt=='pptx':
        deck=Presentation(io.BytesIO(blob))
        assert len(deck.slides)==record['slides']==record['pages'],file_id
        if file_id=='PPT-1':
            assert any(s.has_table for s in deck.slides[2].shapes)
            assert any(s.has_chart for s in deck.slides[3].shapes)
            assert not any(s.has_table for s in deck.slides[4].shapes)
            assert '월 2건 이하' in deck.slides[9].notes_slide.notes_text_frame.text
        for table in gold['tables']:
            if '이미지' in table.get('location',''):
                continue
            index=int(table['location'].split()[1])-1
            native=next(sh.table for sh in deck.slides[index].shapes if sh.has_table)
            contents=[[native.cell(i,j).text for j in range(len(native.columns))]
                      for i in range(len(native.rows))]
            assert contents==[table['header'],*table['rows']],(file_id,'PPTX gold table')
    else:
        book=load_workbook(io.BytesIO(blob))
        assert book.sheetnames==record['sheets'],file_id
        cache=load_workbook(io.BytesIO(blob),data_only=True)
        sheet_gold(cache,gold,record['tables'])
        if file_id=='XLS-1':
            assert book['장비'].max_row==63
            assert len(book._external_links)==2
            for row,n,sheet,addr,name,cached in [
                    (4,1,'일정','C5','교정일정_2026.xlsx',8),(5,2,'Sheet1','B3','구매요청_집계.xlsx',14)]:
                assert book['교정'][f'B{row}'].value==f"='[{n}]{sheet}'!{addr}"
                assert book._external_links[n-1].file_link.Target==name
                assert cache['교정'][f'B{row}'].value==cached
        if file_id=='XLS-2':
            assert book['일정']['C5'].value==8 and book['일정'].max_row==44
        if file_id=='COA-2':
            assert book['원자료'].max_row==601 and book['원자료'].max_column==12
            assert len(book['요약'].conditional_formatting)==1 and book['기준'].sheet_state=='hidden'
            assert sum(c.comment is not None for c in book['원자료']['F'])==2
            assert len(book['차트']._charts)==1
            assert book['원자료']['I59'].data_type=='f' and cache['원자료']['I59'].value is not None
        if file_id=='XLS-4':
            assert book.active.freeze_panes=='C3'
            assert (book.active.max_row,book.active.max_column)==(303,40)
            assert book.active['AN303'].value=='=SUM(AN3:AN302)' and isinstance(cache.active['AN303'].value,int)
        book.close()
        cache.close()


def verify_special(manifest, blobs, extracted):
    assert blobs['SOP-A4']==blobs['SOP-A2']
    assert blobs['EDGE-2']==blobs['RPT-1P'] and blobs['EDGE-2'].startswith(b'%PDF-')
    if 'EDGE-4' in blobs:
        assert blobs['EDGE-4']==blobs['SOP-C1'][:len(blobs['SOP-C1'])*60//100]
    with pdfium.PdfDocument(blobs['SCN-1']) as scn:
        assert scn[2].get_rotation()==90
    with zip_reader(blobs['ZIP-1']) as z:
        assert len(z.infolist())==7 and all(info.flag_bits & 0x800 for info in z.infolist())
        with zip_reader(z.read('사진원본.zip')) as deep:
            assert len(deep.namelist())==5 and all(n.endswith('.jpg') for n in deep.namelist())
    with zip_reader(blobs['ZIP-2'],True) as z:
        assert z.namelist()==['현장인계_안내.docx','작업메모.txt','계통그림.png']
        assert not any(info.flag_bits & 0x800 for info in z.infolist())
    assert b'=?utf-8?' in blobs['EML-1'].lower()
    assert b'filename*' in blobs['EML-1'].lower()
    mail=raw_email(blobs['EML-1'])
    assert mail.get_content_type()=='multipart/mixed'
    assert mail.get_payload(0).get_content_type()=='multipart/alternative'
    assert [p.get_filename() for p in mail.iter_attachments()]==[Path(manifest[f]['path']).name for f in ['RPT-1','XLS-1']]
    original=next(raw_email(blobs['EML-2']).iter_attachments())
    assert original.get_content_type()=='message/rfc822'
    with zip_reader(next(original.get_payload(0).iter_attachments()).get_payload(decode=True)) as z:
        assert len(z.namelist())==3
    if 'EML-3' in blobs:
        mail=raw_email(blobs['EML-3'])
        assert mail.get_content_type()=='text/plain' and not list(mail.iter_attachments())
    assert extracted['COA-1'][1].splitlines().count('시험 항목 시험법 기준 결과 판정')==1
    assert extracted['COA-1'][0].splitlines().count('시험 항목 시험법 기준 결과 판정')==1
    assert '환류 분기 가스켓' in extracted['SOP-A3P'][3]
    assert '면적(cm²)' in extracted['SOP-A3P'][2] and '면적(cm²)' in extracted['SOP-A3P'][3]
    assert extracted['RPT-1P'][3].strip()==''
    assert len(extracted['RPT-1P'])==7


def print_format(records):
    counts=Counter(m['true_format'] for m in records)
    return ', '.join(f'{name} {count}' for name,count in sorted(counts.items()))


def verify(root):
    truth=root/'ground_truth'
    records=json.loads((truth/'manifest.json').read_text(encoding='utf-8'))
    refs=json.loads((truth/'references.json').read_text(encoding='utf-8'))
    questions=[json.loads(line) for line in (truth/'questions.jsonl').read_text(encoding='utf-8').splitlines()]
    manifest={r['file_id']:r for r in records}
    assert len(manifest)==len(records)==len({r['path'] for r in records})
    assert {p.stem for p in (truth/'gold').glob('*.json')}==set(manifest)
    assert {normalize(str(p.relative_to(root/'corpus'))) for p in (root/'corpus').rglob('*') if p.is_file()}=={r['path'] for r in records}
    raw={}
    read={}
    pages={}
    gold={}
    nested={}
    for r in records:
        fid=r['file_id']
        fmt=r['true_format']
        raw[fid]=payload=(root/'corpus'/r['path']).read_bytes()
        file_gold=gold[fid]=json.loads((truth/'gold'/f'{fid}.json').read_text(encoding='utf-8'))
        assert file_gold['file_id']==fid
        assert hashlib.sha256(payload).hexdigest()==r['sha256'] and len(payload)==r['bytes'],fid
        assert len(payload)<(40_000_000 if fid=='EDGE-5' else 15_000_000),fid
        if fid in DIMENSIONS:
            assert r['pages']==DIMENSIONS[fid],fid
        for t,g in zip(r['tables'],file_gold['tables'],strict=True):
            assert t['id']==g['id'] and len(g['rows'])==t['rows'],(fid,t['id'],'rows')
            assert len(g['header'])==t['cols'] and all(len(row)==t['cols'] for row in g['rows']),(fid,t['id'],'cols')
        if r['flags']['truncated']:
            assert not zipfile.is_zipfile(io.BytesIO(payload)),fid
            continue
        if fmt in {'docx','pptx','xlsx'}:
            verify_office(r,payload,file_gold)
        if fmt=='pdf':
            if r['flags']['encrypted']:
                try:
                    with pdfium.PdfDocument(payload):
                        raise AssertionError(f'{fid}: password was not required')
                except pdfium.PdfiumError:
                    pass
            pages[fid]=pdf_extract(payload,r['flags']['password'])
            assert len(pages[fid])==r['pages'],(fid,'PDF page count')
            assert [i for i,txt in enumerate(pages[fid],1) if not txt.strip()]==r['scanned_pages'],(fid,'scan map')
            text='\n'.join(pages[fid])
        else:
            text=extract(payload,fmt,r['flags']['password'],r.get('encoding'))
        if fmt in {'docx','pptx','xlsx','pdf','csv','eml','md'} and not r['flags']['empty'] and \
                (fmt!='pdf' or len(r['scanned_pages'])!=r['pages']):
            assert HANGUL.search(text) and not BAD_GLYPH.search(text),(fid,'Hangul / tofu')
        if r['flags']['empty']:
            assert not text.strip(),fid
        if fmt=='csv':
            codec=r['encoding']
            assert payload.startswith(b'\xef\xbb\xbf')==(codec=='utf-8-sig'),fid
            rows=list(csv.reader(io.StringIO(payload.decode(codec))))
            assert rows==[file_gold['tables'][0]['header'],*file_gold['tables'][0]['rows']],(fid,'CSV gold table')
        if fmt in {'tif','jpg','png'}:
            with Image.open(io.BytesIO(payload)) as image:
                frames=getattr(image,'n_frames',1)
                assert r['pages'] is None or r['pages']==frames,(fid,'image frames')
                for i in range(frames):
                    image.seek(i)
                    image.load()
        for entry in r['embedded_children']:
            path=entry['path_inside']
            suffix=entry['true_format']
            contents=child_bytes(payload,fmt,path,windows=fid=='ZIP-2')
            assert contents,(fid,path)
            if suffix=='jpg':
                with Image.open(io.BytesIO(contents)) as image:
                    image.verify()
            nested[(fid,path)]=(suffix,contents)
        read[fid]=text
    verify_special(manifest,raw,pages)
    for check_id,other,path in [('RPT-2P','ZIP-1','기록/온도기록_원본_EQ-FRZ-D_2026-10-03.csv')]:
        name=Path(path).name
        assert nested[(check_id,name)][1]==nested[(other,path)][1]
        rows=list(csv.reader(io.StringIO(nested[(check_id,name)][1].decode('utf-8-sig'))))
        expected=gold[check_id]['embedded_tables'][0]
        assert rows==[expected['header'],*expected['rows']] and len(rows)==289
    if 'PPT-3' in raw:
        ole=next(c for c in manifest['PPT-3']['embedded_children'] if c['kind']=='ole_object')
        assert nested[('PPT-3',ole['path_inside'])][1]==raw['XLS-2']
    for f in ['RPT-1','XLS-1']:
        assert nested[('EML-1',Path(manifest[f]['path']).name)][1]==raw[f]
    for ref in refs:
        fid=ref['source_file_id']
        assert set(ref['expected_target_file_ids'])<=set(manifest),(fid,ref)
        assert not ref['latest_file_id'] or ref['latest_file_id'] in manifest
        assert ref['expected_state'] in {'linked','outdated','missing','ambiguous','external'}
        text=read[fid]
        if not text.strip() and manifest[fid]['scanned_pages'] and manifest[fid]['pair_with']:
            text=read[manifest[fid]['pair_with']]
        assert ref['written_as'] in text,(fid,'reference text',ref['written_as'])
    assert len(refs)==sum(len(r['links']) for r in records)
    assert len({q['id'] for q in questions})==len(questions)
    for q in questions:
        fid=q['doc_file_id']
        answer=q['answer']
        source,*tail=q['doc_path'].split('!/',1)
        assert source==manifest[fid]['path'] and 2<=len(answer)<=30,q
        if tail:
            suffix,payload=nested[(fid,tail[0])]
            text=extract(payload,suffix)
        else:
            text=read[fid]
        if q['requires_ocr']:
            assert q['kind']=='image' and q['id'] in [e['question_id'] for e in gold[fid].get('visual_evidence',[])],q
            continue
        assert answer in text,(q['id'],fid,q['doc_path'],q['location'],answer)
        page_match=re.match(r'p\.(\d+)\b',q['location'])
        if fid in pages and page_match and not tail:
            idx=int(page_match.group(1))-1
            assert answer in pages[fid][idx],(q['id'],fid,'PDF answer page',q['location'],answer)
    counts=Counter(q['kind'] for q in questions)
    minimum=45 if all(r['priority']=='P0' for r in records) else 90
    assert len(questions)>=minimum and (minimum==45 or min(counts.values())>=30)
    assert sum('!/' in q['doc_path'] for q in questions)>=10
    assert len(refs)>=25
    return [
        f'전체 파일 {len(records)}개 재열기 및 SHA-256 일치 ({print_format(records)})',
        f'문서·슬라이드 페이지 검사 {sum(r["pages"] is not None for r in records)}건, 워크북 시트 검사 {sum("sheets" in r for r in records)}건',
        f'전체 표 정답 {sum(len(g["tables"]) for g in gold.values())}개, 참조 출현 {len(refs)}건',
        f'첨부 및 압축 자식 {len(nested)}개 열기, 스캔·회전·암호·CP949·중첩·동일 복제 조건 통과',
        f'질문 {len(questions)}개 (본문 {counts["text"]}, 표 {counts["table"]}, 이미지 {counts["image"]})',
        f'문자열 완전 일치 {sum(not q["requires_ocr"] for q in questions)}개, OCR 증거 위치 {sum(q["requires_ocr"] for q in questions)}개, 중첩 파일 질문 {sum("!/" in q["doc_path"] for q in questions)}개',
    ]


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    print('\n'.join(verify(args.directory)))
