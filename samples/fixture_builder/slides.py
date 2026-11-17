from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import PROG_ID
from PIL import Image, ImageDraw
from pptx.dml.color import RGBColor as Color
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches as I, Pt as PtSlide

from core import *
from visuals import form, save

PPT_URL='https://intranet.fabrikam.example/quality/review/2026-q3'
PPT_PIXELS = [
    ['설비 경보','4건','설비팀 확인'],
    ['시료 보류','3건','QA 검토'],
    ['기록 누락','2건','QC 보완'],
    ['점검표 갱신','1건','완료'],
]


def new_deck():
    deck=Presentation()
    deck.slide_width=I(13.3333)
    deck.slide_height=I(7.5)
    deck.core_properties.author=COMPANY
    return deck


def frame(slide, fid, index, title, subtitle=None):
    background=slide.background.fill
    background.solid()
    background.fore_color.rgb=Color.from_string('F5F8F9')
    add_text(slide,.78,.38,11.5,.35,COMPANY+'   |   제1공장 품질 검토',11,'376373')
    add_text(slide,.78,.83,11.9,.76,title,30,'18313E',True)
    if subtitle:
        add_text(slide,.80,1.73,11.5,.48,subtitle,16,'426678')
    add_text(slide,.80,7.02,11.4,.27,NOTICE if index==1 else '대외비 · 가상 문서',9,'4D6975')
    add_text(slide,12.13,6.99,.65,.30,f'{index:02d}',10,'4D6975')
    evidence(fid,headings=[title],text_snippets=[subtitle] if subtitle else [])


def add_text(slide,x,y,w,height,text,size=17,color='233744',bold=False,bullets=False,link_to=None):
    shape=slide.shapes.add_textbox(I(x),I(y),I(w),I(height))
    tf=shape.text_frame
    tf.word_wrap=True
    for index,line in enumerate(text.split('\n')):
        paragraph=tf.paragraphs[0] if index==0 else tf.add_paragraph()
        paragraph.space_after=PtSlide(12 if bullets else 5)
        if bullets:
            props=paragraph._p.get_or_add_pPr()
            bullet=OxmlElement('a:buChar')
            bullet.set('char','•')
            props.append(bullet)
            props.set('marL','211000')
            props.set('indent','-155000')
        run=paragraph.add_run()
        run.text=line
        if link_to:
            run.hyperlink.address=link_to
        run.font.name=FONT
        run.font.size=PtSlide(size)
        run.font.bold=bold
        run.font.color.rgb=Color.from_string(color)
    return shape


def text_frame(deck, fid, index, title, copy, bullets=False):
    slide=deck.slides.add_slide(deck.slide_layouts[6])
    frame(slide,fid,index,title)
    add_text(slide,.83,2.02,11.5,4.3,copy,20,bullets=bullets)
    evidence(fid,text_snippets=copy.split('\n'))
    return slide


def table_slide(slide, fid, index, title, headings, rows):
    tbl=slide.shapes.add_table(len(rows)+1,len(headings),I(.85),I(2.0),I(11.58),I(3.65)).table
    for i,row in enumerate([headings,*rows]):
        for j,value in enumerate(row):
            cell=tbl.cell(i,j)
            cell.text=value
            cell.fill.solid()
            cell.fill.fore_color.rgb=Color.from_string('234D62' if i==0 else ('EDF4F6' if i%2==0 else 'FFFFFF'))
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.name=FONT
                    run.font.size=PtSlide(15)
                    run.font.bold=i==0
                    run.font.color.rgb=Color.from_string('FFFFFF' if i==0 else '233744')
    gold_table(fid,title,headings,rows,location=f'슬라이드 {index}')


def plot(slide,categories,data,label):
    values=CategoryChartData()
    values.categories=categories
    values.add_series(label,data)
    chart=slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED,I(1.02),I(1.91),I(10.95),I(4.88),values).chart
    chart.has_legend=True
    chart.legend.position=XL_LEGEND_POSITION.BOTTOM
    chart.legend.font.size=PtSlide(13)
    chart.series[0].format.fill.solid()
    chart.series[0].format.fill.fore_color.rgb=Color.from_string('23788C')
    chart.value_axis.minimum_scale=0
    chart.value_axis.tick_labels.font.size=PtSlide(12)
    chart.category_axis.tick_labels.font.size=PtSlide(12)


def photo_slide(deck,fid,index,title,photo,caption):
    slide=deck.slides.add_slide(deck.slide_layouts[6])
    frame(slide,fid,index,title)
    slide.shapes.add_picture(str(photo),I(1.49),I(1.72),height=I(4.55))
    add_text(slide,1.49,6.35,10.1,.38,caption,14,'3E6170')
    evidence(fid,captions=[dict(kind='figure',text=caption,page=index)])


def build_slides(assets):
    fid='PPT-1'
    target=register(fid,5,'2026_Q3_품질지표_리뷰.pptx','2026년 3분기 품질지표 검토',number='PPT-QA-2026-Q3',
                    department='QA',issued='2026-10-20',pages=12,
                    purposes='parse ocr chunking structure lineage embedding_eval vectordb')
    deck=new_deck()
    slide=deck.slides.add_slide(deck.slide_layouts[6])
    frame(slide,fid,1,'2026년 3분기 품질지표 검토','제1공장 · 품질보증 · 2026년 10월 20일')
    add_text(slide,.83,3.15,10.2,2.12,
             '7–9월 마감 수치와 10월 초 후속 사례를 검토한다.\n공통 집계 기준과 조치 담당을 회의에서 확정한다.',22)
    text_frame(deck,fid,2,'검토 순서','주요 품질 지표와 분기 편차\n설비 경보 및 검체 보류 사례\n후속 점검·교육 일정 공유',True)
    slide=deck.slides.add_slide(deck.slide_layouts[6])
    frame(slide,fid,3,'분기별 주요 품질 지표')
    table_slide(slide,fid,3,'분기별 주요 품질 지표',['지표','목표','Q2','Q3','추세'],[
        ['교정 준수율','≥ 95 %','94 %','97 %','개선'],['일탈 종료율','≥ 90 %','91 %','92 %','개선'],
        ['기록 누락','≤ 4건','4건','3건','감소'],['부적합 검토','≤ 3건','1건','2건','증가']])
    slide=deck.slides.add_slide(deck.slide_layouts[6])
    frame(slide,fid,4,'월별 일탈 접수')
    plot(slide,['4월','5월','6월','7월','8월','9월'],[4,3,4,3,3,2],'일탈 접수 건수')
    evidence(fid,chart_data=[dict(slide=4,categories=['4월','5월','6월','7월','8월','9월'],
                                  series='일탈 접수 건수',values=[4,3,4,3,3,2])])
    slide=deck.slides.add_slide(deck.slide_layouts[6])
    frame(slide,fid,5,'현장 자료 캡처')
    header=['지표','건수','후속 상태']
    path=WORK/'slides-field.png'
    image=form('현장 자료','9월 종합 확인표',header,PPT_PIXELS,tick=False).crop((72,25,1560,650))
    save(image,path,[*[v for row in PPT_PIXELS for v in row]])
    slide.shapes.add_picture(str(path),I(.9),I(2.0),width=I(11.4))
    gold_table(fid,'현장 자료 캡처',header,PPT_PIXELS,location='슬라이드 5 이미지')
    photo_slide(deck,fid,6,'냉각수 설비 관찰',assets['skid'],'그림 1. 제1공장 순환 스키드 점검')
    photo_slide(deck,fid,7,'보관 위치 검토',assets['racks'],'그림 2. 냉동고 내부 랙 검토')
    text_frame(deck,fid,8,'분기 말 확인 사항','관찰 결과를 기억에 의존하지 않고 원본 시각과 대조한다.\n현장 보완 사항은 승인 담당과 예정일을 같은 기록에 연결한다.',True)
    slide=text_frame(deck,fid,9,'10월 후속 조사','DEV-2026-0117 · 냉동고 D 온도 이탈\nCAPA-2026-0042 · 패킹 교체 및 효과 확인',True)
    add_text(slide,.89,5.68,11.1,.53,PPT_URL,14,'216D86',link_to=PPT_URL)
    link(fid,'DEV-2026-0117','슬라이드 9 후속 조사','linked',['RPT-2','RPT-2P'])
    link(fid,'CAPA-2026-0042','슬라이드 9 후속 조사','linked',['RPT-3'])
    link(fid,PPT_URL,'슬라이드 9 인트라넷','external',kind='url')
    slide=text_frame(deck,fid,10,'다음 회의 준비','게시판에 반영할 자료와 담당자의 승인 일정은 회의 뒤 별도 확정한다.')
    slide.notes_slide.notes_text_frame.text='다음 분기 목표 일탈 건수는 월 2건 이하. 목표 수치는 QA 정례 회의의 진행자가 설명한다.'
    evidence(fid,speaker_notes=[dict(page=10,text=slide.notes_slide.notes_text_frame.text)])
    text_frame(deck,fid,11,'담당 검토','미완료 조치는 설비팀과 품질보증이 공동 점검한다.\n보고 시점의 검토 결과는 주간 일정표에 표시한다.')
    text_frame(deck,fid,12,'회의 마감','회의 운영 · QA 승인 이O희\n다음 회의에서는 운전과 정비 기록의 연결 상태를 확인한다.')
    deck.save(target)
    MANIFEST[fid]['slides']=len(deck.slides)
    MANIFEST[fid]['elements']=dict(native_tables=1,image_only_tables=1,native_charts=1,images=3,captions=2,speaker_notes=1)
    for revision,filename,fid in [(2,'설비교체_검토_v2.pptx','PPT-2'),(3,'설비교체_검토_v3_최종.pptx','PPT-3')]:
        replacement(revision,filename,fid,assets)


def replacement(revision,filename,fid,assets):
    latest=revision==3
    target=register(fid,5,filename,'순환 설비 교체안 검토',number='PPT-EQ-2026-005',
                    rev=f'v{revision}',status='confirmed',latest=latest,priority='P1',pages=8,
                    department='설비',issued='2026-11-09' if latest else '2026-10-27',
                    purposes='parse lineage compare structure chunking embedding_eval vectordb')
    deck=new_deck()
    chosen='벤더 C' if latest else '벤더 B'
    costs=[3760,3450,3310] if latest else [3510,3150,3710]
    text_frame(deck,fid,1,'순환 설비 교체안 검토',f'제1공장 냉각수 순환설비 · 개정 v{revision}\n{chosen}의 교체안을 권고한다.')
    text_frame(deck,fid,2,'현장 제약','기존 배관 접속 거리와 전원 인계 방식을 비교한다.\n휴일 정지 가능 시간과 반입 통로를 사전에 확인한다.',True)
    slide=deck.slides.add_slide(deck.slide_layouts[6])
    frame(slide,fid,3,'대안 비교')
    rows=[[vendor,f'{cost:,} 만원',str(days),risk] for vendor,cost,days,risk in
          zip(['벤더 A','벤더 B','벤더 C'],costs,[15,18 if latest else 13,14 if latest else 20],
              ['배관 재확인','시운전 포함','정비 대응 포함'])]
    table_slide(slide,fid,3,'교체안 비교',['후보','견적','반입 소요일','조건'],rows)
    slide=deck.slides.add_slide(deck.slide_layouts[6])
    frame(slide,fid,4,'교체 공사 견적 비교')
    plot(slide,['벤더 A','벤더 B','벤더 C'],costs,'견적 (만원)')
    evidence(fid,chart_data=[dict(slide=4,categories=['벤더 A','벤더 B','벤더 C'],series='견적 (만원)',values=costs)])
    photo_slide(deck,fid,5,'현장 반입 구역',assets['skid'],'그림 1. 기존 스키드 주위 반입 경로')
    text_frame(deck,fid,6,'인수 범위','교체 후에는 운전 압력과 예비 펌프 진동을 인수 기록에 남긴다.\n계통 변경 내역은 검토자가 도면과 대조한다.',True)
    text_frame(deck,fid,7,'최종 검토',(
        '벤더 C가 정비 대응을 견적에 포함하여 이번 개정에서 권고안으로 바뀌었다.' if latest else
        '벤더 B가 공사비와 반입 소요일에서 우선 검토 대상이다.'))
    review=text_frame(deck,fid,8,'검토 이력','원본 근거 RPT-EQ-2026-031 · 냉각수 순환설비 정기점검 보고서\n담당 설비팀 박O수')
    link(fid,'RPT-EQ-2026-031','슬라이드 8 원본 근거','linked',['RPT-1','RPT-1P'])
    if latest:
        document_link='../'+MANIFEST['XLS-2']['path']
        icon=Image.new('RGB',(160,116),'#edf4f6')
        draw=ImageDraw.Draw(icon)
        draw.rounded_rectangle((40,12,119,104),radius=7,outline='#234D62',width=4)
        for y in [37,55,73]:
            draw.line((53,y,106,y),fill='#347288',width=4)
        icon_path=WORK/'embedded-sheet-icon.png'
        icon.save(icon_path)
        review.shapes.add_ole_object(str(file_path('XLS-2')),PROG_ID.XLSX,I(1.1),I(4),
                                     width=I(1.36),height=I(.98),icon_file=str(icon_path),
                                     icon_width=I(1.36),icon_height=I(.98))
        add_text(review,2.65,4.25,8.8,.48,'첨부 · 교정일정_2026.xlsx',16,link_to=document_link)
    deck.save(target)
    if latest:
        with zipfile.ZipFile(target) as package:
            embedded=next(name for name in package.namelist() if name.startswith('ppt/embeddings/') and name.endswith('.xlsx') and package.read(name)==file_path('XLS-2').read_bytes())
        child(fid,file_path('XLS-2').name,'ole_object','xlsx',embedded)
        link(fid,document_link,'슬라이드 8 교정 일정 첨부','linked',['XLS-2'],kind='hyperlink')
    MANIFEST[fid]['slides']=len(deck.slides)
    MANIFEST[fid]['elements']=dict(native_tables=1,native_charts=1,images=1,captions=1,ole_objects=int(latest))
