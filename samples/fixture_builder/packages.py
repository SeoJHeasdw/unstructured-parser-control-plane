from email import policy
from email.message import EmailMessage
from io import BytesIO
from urllib.parse import quote

from PIL import Image, ImageDraw

from core import *
from narrative import detail
from reports import FIELD, FREEZER_PHOTO, TEMP_NAME
from sheets import TEMP_HEADER, freezer_csv, write_csv
from visuals import VISUAL_TEXT, form, noisy, nameplate, paper_photo, save, text

REQUEST_EML='원인조사_요청_원본.eml'
REQUEST_ZIP='현장사진_모음.zip'
OFFICE_DATE='Fri, 16 Oct 2026 14:10:00 +0900'


class WindowsZipName(zipfile.ZipInfo):
    def _encodeFilenameFlags(self):
        return self.filename.encode('cp949'), self.flag_bits & ~0x800


def zip_payload(items, *, windows=False):
    buffer=BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,data in items:
            info=(WindowsZipName if windows else zipfile.ZipInfo)(name,(2026,10,20,10,0,0))
            z.writestr(info,data,compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def add_file(message,path,main,sub,filename=None):
    message.add_attachment(path.read_bytes(),maintype=main,subtype=sub,filename=filename or path.name)


def message(subject,sender,to,date=OFFICE_DATE,cc=None):
    mail=EmailMessage(policy=policy.SMTP)
    mail['Subject']=subject
    mail['From']=sender+'@fabrikam.example'
    mail['To']=to+'@fabrikam.example'
    mail['Date']=date
    if cc:
        mail['Cc']=cc+'@fabrikam.example'
    return mail


def store_mail(fid,mail):
    file_path(fid).write_bytes(mail.as_bytes(policy=policy.SMTP))


def build_pkgs(assets, temp):
    mail1='EML-1'
    register(mail1,6,'FW_ 냉각수설비 점검결과 공유.eml','냉각수설비 점검결과 공유',
             department='설비',issued='2026-10-16',purposes='structure lineage parse embedding_eval vectordb')
    first=message('FW: 냉각수설비 점검결과 공유','eng.shift','qa.review',cc='qc.record')
    body=(f'{NOTICE}\n\n제1공장 냉각수 순환설비 점검이 완료되었습니다. 정기점검 보고서 RPT-EQ-2026-031과 장비 마스터를 공유합니다.\n'
          '예비 펌프 조사 담당은 설비팀 박O수입니다. 검토 회신은 2026-10-19까지 부탁드립니다.\n'
          '다음 확인은 베어링 정밀검사 일정 확정 후에 진행합니다.')
    first.set_content(body)
    first.add_alternative(
        f'<html lang="ko"><body><small>{NOTICE}</small><p>정기점검 보고서 RPT-EQ-2026-031 공유</p>'
        '<table><tr><th>설비</th><th>내용</th><th>상태</th></tr>'
        '<tr><td>EQ-PUMP-P2</td><td>수평 진동 재확인</td><td>조사 중</td></tr>'
        '<tr><td>EQ-COOL-02</td><td>운전 인계</td><td>완료</td></tr></table></body></html>',
        subtype='html')
    for child_id,suffix in [('RPT-1','document'),('XLS-1','sheet')]:
        path=file_path(child_id)
        add_file(first,path,'application',f'vnd.openxmlformats-officedocument.{"wordprocessingml" if suffix=="document" else "spreadsheetml"}.{suffix}')
        child(mail1,path.name,'email_attachment',path.suffix[1:])
    store_mail(mail1,first)
    link(mail1,'RPT-EQ-2026-031','본문 및 HTML 대체 본문','linked',['RPT-1','RPT-1P'])
    evidence(mail1,text_snippets=body.split('\n'))
    gold_table(mail1,'HTML 점검 상태',['설비','내용','상태'],
               [['EQ-PUMP-P2','수평 진동 재확인','조사 중'],['EQ-COOL-02','운전 인계','완료']],location='HTML 본문')

    mail2='EML-2'
    register(mail2,6,'RE_ 일탈 DEV-2026-0117 원인조사 요청.eml','냉동고 D 이탈 원인조사 회신',
             department='QA',issued='2026-10-07',purposes='structure lineage parse embedding_eval vectordb')
    inner=message('냉동고 D 원인조사 요청','qa.review','eng.shift','Mon, 05 Oct 2026 10:00:00 +0900')
    request=f'{NOTICE}\n\nDEV-2026-0117 원인조사를 요청합니다.\n사진 검토 분류는 도어 하단입니다.\n현장 확인 회신 기한은 2026-10-07입니다.\n보존 원자료는 경보 원장입니다.'
    inner.set_content(request)
    photo_entries=[(FREEZER_PHOTO,assets['freezer'].read_bytes()),('냉동고_내부랙.jpg',assets['racks'].read_bytes()),
                   ('시료_보관준비대.jpg',assets['bench'].read_bytes())]
    inner.add_attachment(zip_payload(photo_entries),maintype='application',subtype='zip',filename=REQUEST_ZIP)
    outer=message('RE: 일탈 DEV-2026-0117 원인조사 요청','eng.shift','qa.review',
                  'Wed, 07 Oct 2026 16:40:00 +0900',cc='qc.record')
    reply=(f'{NOTICE}\n\nDEV-2026-0117 현장 확인 결과를 회신합니다. 도어 하단의 패킹 접촉 흔적을 검토용으로 보존했습니다.\n'
           '경보 비교 담당은 설비팀 박O수입니다. 사진은 원래 요청 메일의 첨부본을 확인해 주십시오.\n\n'
           '> DEV-2026-0117 원인조사를 요청합니다.\n> 도어 닫힘 확인 내역을 검토용으로 전달해 주십시오.')
    outer.set_content(reply)
    outer.add_attachment(inner,filename=REQUEST_EML)
    store_mail(mail2,outer)
    child(mail2,REQUEST_EML,'email_attachment','eml')
    child(mail2,REQUEST_ZIP,'email_attachment','zip',f'{REQUEST_EML}!/{REQUEST_ZIP}')
    for name,_ in photo_entries:
        child(mail2,name,'zip_entry','jpg',f'{REQUEST_EML}!/{REQUEST_ZIP}!/{name}')
    link(mail2,'DEV-2026-0117','본문 및 인용문','linked',['RPT-2','RPT-2P'])
    link(mail2,'DEV-2026-0117',f'{REQUEST_EML} 본문','linked',['RPT-2','RPT-2P'])
    evidence(mail2,text_snippets=reply.split('\n'),embedded_text=[dict(path_inside=REQUEST_EML,text=request)])

    mail3='EML-3'
    register(mail3,6,'회의록_공유_2026-10-20.eml','품질 검토 회의록 공유',priority='P1',department='QA',
             issued='2026-10-20',purposes='structure parse lineage embedding_eval vectordb')
    minutes=message('품질 검토 회의록 공유','qa.review','eng.shift','Tue, 20 Oct 2026 17:45:00 +0900',cc='qc.record')
    memo=(f'{NOTICE}\n\n10월 20일 품질 회의 결과를 공유합니다. 회의 진행은 QA 승인 이O희가 담당했습니다.\n'
          '1. CAPA-2026-0042: 교대 교육 일정을 10월 29일에 확정한다.\n'
          '2. SOP-EQ-0102: 개정 점검표의 도어 확인란을 오후 교대에서 먼저 시범 적용한다.\n'
          '3. RPT-EQ-2026-031: 예비 펌프 정밀 검사 일정을 설비팀 주간표에 추가한다.\n'
          '다음 회의 자료 취합은 2026-11-05까지입니다.')
    minutes.set_content(memo)
    store_mail(mail3,minutes)
    evidence(mail3,text_snippets=memo.split('\n'))
    link(mail3,'CAPA-2026-0042','본문 조치 1','linked',['RPT-3'])
    link(mail3,'SOP-EQ-0102','본문 조치 2','linked',['SOP-C3'])
    link(mail3,'RPT-EQ-2026-031','본문 조치 3','linked',['RPT-1','RPT-1P'])

    fid='ZIP-1'
    target=register(fid,7,'점검자료_2026-10.zip','10월 설비 점검자료 묶음',department='설비',
                    purposes='structure embedding_eval',notes='UTF-8 플래그를 사용하는 경로와 중첩 ZIP.')
    outer_items=[(f'보고서/{file_path("RPT-1").name}',file_path('RPT-1').read_bytes(),'docx'),
                 (f'기록/{TEMP_NAME}',temp.read_bytes(),'csv')]
    for key,name in [('skid','냉각수설비_전경.jpg'),('pump','펌프P2_근접.jpg'),
                     ('corrosion','배관_부식부위.jpg'),('cabinet','제어반_외함.jpg')]:
        outer_items.append((f'사진/{name}',assets[key].read_bytes(),'jpg'))
    source_photos=[('배관_상부.jpg','pipe'),('순환_전경.jpg','skid'),('접합부_근접.jpg','corrosion'),
                   ('탱크_상면.jpg','tank'),('펌프_마운트.jpg','pump')]
    photo_zip=[(name,assets[key].read_bytes()) for name,key in source_photos]
    outer_items.append(('사진원본.zip',zip_payload(photo_zip),'zip'))
    target.write_bytes(zip_payload([(name,data) for name,data,_ in outer_items]))
    for name,_,extension in outer_items:
        child(fid,Path(name).name,'zip_entry',extension,name)
    for name,_ in photo_zip:
        child(fid,name,'zip_entry','jpg',f'사진원본.zip!/{name}')

    fid='ZIP-2'
    target=register(fid,7,'윈도우압축_cp949.zip','CP949 경로의 자료 묶음',department='QC',
                    purposes='structure embedding_eval',notes='중앙 디렉터리와 로컬 헤더에 CP949 이름. UTF-8 플래그 없음.')
    tiny=WORK/'cp949-practice.docx'
    word=new_doc('현장 인계 안내','Fabrikam Bio | QC 점검 기록')
    for sentence in ['이관 확인 담당은 QA 승인 이O희이다.','사진과 메모의 분류는 검교정 자료이다.',
                     '검토 대상은 제1공장 교정 대기 목록의 파일 이름과 기록 사이의 일치 여부이다.']:
        word.add_paragraph(sentence)
    word.save(tiny)
    txt=(f'{NOTICE}\r\n작업지시: 인계 목록의 파일명과 문서 내부의 제목을 대조한다.\r\n'
         '인계 지점은 QC 확인대이다.\r\n확인 기록의 보존 기간은 3년이다.\r\n')
    zip2_items=[('현장인계_안내.docx',tiny.read_bytes(),'docx'),('작업메모.txt',txt.encode('cp949'),'txt'),
                ('계통그림.png',assets['pid'].read_bytes(),'png')]
    target.write_bytes(zip_payload([(name,data) for name,data,_ in zip2_items],windows=True))
    for name,_,kind in zip2_items:
        child(fid,name,'zip_entry',kind)

    fid='ZIP-3'
    target=register(fid,7,'감사대응_자료.zip','감사 대응 자료',priority='P1',department='QA',
                    purposes='structure embedding_eval',notes='ZIP → EML → EML → ZIP → JPG 중첩.')
    paths=[file_path('EML-2'),file_path('COA-1S')]
    target.write_bytes(zip_payload([(path.name,path.read_bytes()) for path in paths]))
    for path in paths:
        child(fid,path.name,'zip_entry',path.suffix[1:])
    for entry in MANIFEST['EML-2']['embedded_children']:
        child(fid,entry['name'],entry['kind'],entry['true_format'],
              f'{file_path("EML-2").name}!/{entry["path_inside"]}')

    fid='EDGE-8'
    target=register(fid,10,'README_현장공유.md','현장 공유 자료 안내',priority='P2',
                    department='생산',purposes='parse structure lineage embedding_eval')
    txt_lines=[f'# 현장 공유 자료 안내\n\n{NOTICE}\n', '## 파일 목록\n',
               '| 파일 | 담당 | 용도 |\n| --- | --- | --- |']
    links=[('SOP-C1','QC','시스템 적합성'),('XLS-2','설비팀','교정 일정'),('PPT-1','QA','분기 검토')]
    for doc_id,owner,use in links:
        literal='../'+MANIFEST[doc_id]['path']
        txt_lines.append(f'| [{file_path(doc_id).name}](<{literal}>) | {owner} | {use} |')
        link(fid,literal,'파일 목록 Markdown 링크','linked',[doc_id],kind='hyperlink')
    txt_lines.extend(['','## 처리 상태','','\`\`\`text','status=검토 완료','plant=제1공장','\`\`\`',''])
    target.write_text('\n'.join(txt_lines),encoding='utf-8')
    evidence(fid,headings=['현장 공유 자료 안내','파일 목록','처리 상태'],text_snippets=['status=검토 완료','plant=제1공장'])
    gold_table(fid,'파일 목록',['파일','담당','용도'],[[file_path(k).name,o,u] for k,o,u in links])


def pdf_raster(path,index):
    with pdfium.PdfDocument(path) as doc:
        with doc[index] as page, page.render(scale=200/72) as bitmap:
            return bitmap.to_pil().copy().convert('RGB')


def build_pdf_variants(out, assets):
    for src,new in [('SOP-A3','SOP-A3P'),('RPT-1','RPT-1P'),('RPT-2','RPT-2P'),('COA-1','COA-1S')]:
        clone(src,new)
        MANIFEST[new]['pages']=MANIFEST[src]['pages']
    file_path('SOP-A3P').write_bytes((out/'SOP-A3.pdf').read_bytes())
    clone('SOP-A2','SOP-A4')
    MANIFEST['SOP-A4'].update(pages=MANIFEST['SOP-A2']['pages'],duplicate_of='SOP-A2')
    file_path('SOP-A4').write_bytes(file_path('SOP-A2').read_bytes())

    field_pdf=WORK/'field-scan.pdf'
    photo=noisy(pdf_raster(out/'RPT-1.pdf',3),seed=8,angle=.83,gray=False)
    d=ImageDraw.Draw(photo)
    for x,y in [(1390,400),(1394,503),(1390,607)]:
        d.line((x,y,x+7,y+8,x+23,y-15),fill='#425C78',width=4)
    make_image_pdf(field_pdf,[photo])
    with pdfium.PdfDocument(out/'RPT-1.pdf') as digit, pdfium.PdfDocument(field_pdf) as scan, pdfium.PdfDocument.new() as result:
        result.import_pages(digit,pages=[0,1,2])
        result.import_pages(scan,pages=[0])
        result.import_pages(digit,pages=[4,5,6])
        result.save(file_path('RPT-1P'))
    evidence('RPT-1P',text_snippets=['QA 확인','승인'])
    clone('RPT-1P','EDGE-2')
    MANIFEST['EDGE-2'].update(pages=7,duplicate_of='RPT-1P')
    file_path('EDGE-2').write_bytes(file_path('RPT-1P').read_bytes())

    temp=WORK/TEMP_NAME
    rows=freezer_csv()
    write_csv(temp,'utf-8-sig',TEMP_HEADER,rows)
    with pdfium.PdfDocument(out/'RPT-2.pdf') as dev:
        for name, path, extension in [(TEMP_NAME,temp,'csv'),(FREEZER_PHOTO,assets['freezer'],'jpg')]:
            dev.new_attachment(name).set_data(path.read_bytes())
            child('RPT-2P',name,'pdf_attachment',extension)
        dev.save(file_path('RPT-2P'))
    evidence('RPT-2P',embedded_tables=[
        dict(path_inside=TEMP_NAME,caption='냉동고 D 온도 기록',header=TEMP_HEADER,rows=[list(r) for r in rows])])

    images=[]
    for i in range(3):
        image=noisy(pdf_raster(file_path('COA-1'),i),seed=10+i,angle=.95 if i==1 else .5)
        if i==1:
            d=ImageDraw.Draw(image)
            text(d,(1080,1150),'재확인 완료 10/14',35,'#304961')
            d.line((1065,1197,1388,1191),fill='#304961',width=3)
        images.append(image)
    make_image_pdf(file_path('COA-1S'),images)
    evidence('COA-1S',text_snippets=['재확인 완료 10/14'],captions=[dict(kind='annotation',text='재확인 완료 10/14',page=2)])
    MANIFEST['COA-1S']['elements']['handwritten_annotations']=1

    start=file_path('SOP-C1').read_bytes()
    file_path('EDGE-4').write_bytes(start[:len(start)*60//100])
    make_image_pdf(file_path('EDGE-6'),[assets['skid'],assets['racks']],sizes=[(750,500),(750,500)])
    return temp


def build_scan_assets():
    fid='SCN-1'
    path=register(fid,8,'스캔_교정성적서_2026-09.pdf','9월 외부 교정 성적서',department='QC',issued='2026-09-23',
                  purposes='ocr parse chunking embedding_eval',pages=3,scanned=[1,2,3],
                  notes='200 dpi 회색조 모사. 1쪽 얼룩, 3쪽 PDF 회전 90도.')
    images=[]
    headers=['지시점','기준값','지시값','편차','판정']
    for idx,(identity,units,points) in enumerate([
        ('EQ-PRS-04','bar',[0,1,2,3,4]),('EQ-TEMP-11','°C',[-25,-20,-15,-10,-5]),
        ('EQ-VIB-02','mm/s',[1,2,3,4,5]),
    ],1):
        readings=[[str(n),f'{n:.2f} {units}',f'{n+(idx-1)*.02:.2f} {units}',f'{(idx-1)*.02:.2f} {units}','적합']
                  for n in points]
        title=f'교정 성적서 · {identity}'
        subtitle=f'가상교정연구소   |   교정일 2026-09-23   |   성적서 CAL-26-09-{idx:02d}'
        page=form(title,subtitle,headers,readings,comment='설비팀 박O수 · 현장 인수 확인')
        images.append(noisy(page,seed=22+idx,angle=.57+.13*idx,coffee=idx==1))
        kv(fid,idx,관리번호=identity,교정기관='가상교정연구소',교정일='2026-09-23',성적서=f'CAL-26-09-{idx:02d}')
        gold_table(fid,f'{identity} 측정 결과',headers,readings,page=idx)
    make_image_pdf(path,images,rotations=[0,0,90])
    MANIFEST[fid]['elements']=dict(tables=3,handwritten_marks=3)
    evidence(fid,text_snippets=['가상교정연구소','현장 인수 확인'])
    fid='SCN-2'
    path=register(fid,8,'현장일지_사진.jpg','현장 운전일지 사진',department='설비',issued='2026-10-14',
                  purposes='ocr chunking embedding_eval',pages=1,scanned=[1])
    heads=['확인 시각','계측 구간','기록','확인']
    readings=[['09:10','공급 배관','압력 2.6 bar','양호'],['09:15','복귀 배관','압력 2.1 bar','양호'],
              ['09:24','예비 펌프','진동 4.8 mm/s','재측정'],['09:35','이음부','국부 부식','사진']]
    subtitle='EQ-COOL-02    운전일 2026-10-14     설비팀 박O수'
    page=form('현장 운전일지',subtitle,heads,readings,comment='교대 인계 확인 · 제1공장')
    paper_photo(page,path)
    kv(fid,1,설비='EQ-COOL-02',운전일='2026-10-14',담당='설비팀 박O수')
    gold_table(fid,'현장 운전 일지',heads,readings,page=1)
    fid='SCN-3'
    path=register(fid,8,'보관조건_점검표.tif','보관조건 현장 점검표',priority='P1',department='생산',
                  purposes='ocr parse embedding_eval',pages=3,scanned=[1,2,3])
    checks=[]
    heads=['설비','확인 항목','기록','현장 판정']
    for idx,(device,status,owner) in enumerate([
        ('EQ-FRZ-D','-20 °C','설비팀 박O수'),('EQ-UF-03','-86 °C','QC 시험담당 김O준'),
        ('EQ-INC-H','25 °C','QA 승인 이O희')],1):
        records=[[device,'설정 온도',status,'확인'],[device,'문 개방 경보','수신 완료','확인'],
                 [device,'포장 상태','파손 없음','확인'],[device,'인수자',owner,'서명']]
        page=form('보관조건 현장 점검표',f'점검일 2026-09-{20+idx} · 양식 보관-{idx:02d}',heads,records)
        checks.append(noisy(page,seed=30+idx,angle=.59+idx*.1).convert('L'))
        gold_table(fid,f'{device} 보관 조건',heads,records,page=idx)
        kv(fid,idx,설비=device,점검일=f'2026-09-{20+idx}')
    checks[0].save(path,save_all=True,append_images=checks[1:],compression='tiff_lzw',dpi=(200,200))
    fid='SCN-4'
    path=register(fid,8,'설비명판_EQ-UF-03.png','초저온 냉동고 명판',priority='P1',department='설비',
                  purposes='ocr structure embedding_eval',pages=1,scanned=[1])
    nameplate(path)
    kv(fid,1,관리번호='EQ-UF-03',모델='UF-700 (가상)',일련번호='SN-2023-0417',정격온도='-86 °C',
       전원='220 V 60 Hz',제조사='가상냉동(주)')
