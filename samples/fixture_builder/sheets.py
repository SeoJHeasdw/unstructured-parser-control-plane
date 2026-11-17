from datetime import date, datetime, timedelta
import csv
from lxml import etree
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.comments import Comment
from openpyxl.formatting.rule import FormulaRule
from openpyxl.packaging.relationship import Relationship
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.external_link.external import (
    ExternalBook, ExternalCell, ExternalLink, ExternalRow, ExternalSheetData,
    ExternalSheetDataSet, ExternalSheetNames,
)

from core import *
from sop import CAL_INSTRUMENTS

SCHEMA = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
RELATIVE_SOP = '../01_sop/SOP-QC-014_HPLC_시스템적합성_v3.docx'
SHARED_CERT = r'\\fabrikam-fs01\qa\교정\원본성적서.pdf'
CAL_URL = 'https://intranet.fabrikam.example/calibration/calendar'
LOG_HEADER = ['일시','설정온도(°C)','측정온도(°C)','습도(%RH)','경보']
TEMP_HEADER = ['일시','설비번호','측정온도(°C)','경보','비고']


def sheet_banner(ws, title, columns, notice=True):
    ws.merge_cells(start_row=1,start_column=1,end_row=1,end_column=columns)
    ws['A1']=title
    ws['A1'].font=Font(name='Apple SD Gothic Neo',bold=True,size=14,color='FFFFFF')
    ws['A1'].fill=PatternFill('solid',fgColor=ACCENT)
    ws.row_dimensions[1].height=25
    if notice:
        ws.merge_cells(start_row=2,start_column=1,end_row=2,end_column=columns)
        ws['A2']=NOTICE
        ws['A2'].font=Font(name='Apple SD Gothic Neo',size=9,color='49616E')


def table_style(ws, header_row, widths, max_row=None):
    for i,width in enumerate(widths,1):
        ws.column_dimensions[get_column_letter(i)].width=width
    for row in ws.iter_rows(min_row=header_row,max_row=max_row or ws.max_row,max_col=len(widths)):
        for cell in row:
            cell.font=Font(name='Apple SD Gothic Neo',size=10,bold=cell.row==header_row,
                           color='FFFFFF' if cell.row==header_row else '233744')
            cell.alignment=Alignment(vertical='center')
            if cell.row==header_row:
                cell.fill=PatternFill('solid',fgColor=ACCENT)
            elif cell.row%2==0:
                cell.fill=PatternFill('solid',fgColor='EDF4F6')
    ws.row_dimensions[header_row].height=22


def write_cache(target, by_sheet):
    with zipfile.ZipFile(target) as package:
        parts={name:package.read(name) for name in package.namelist()}
    for number,cache in by_sheet.items():
        name=f'xl/worksheets/sheet{number}.xml'
        root=etree.fromstring(parts[name])
        for addr,value in cache.items():
            node=root.find(f".//{{{SCHEMA}}}c[@r='{addr}']/{{{SCHEMA}}}v")
            if node is None:
                raise AssertionError(addr)
            node.text=str(value)
        parts[name]=etree.tostring(root,encoding='UTF-8',xml_declaration=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as package:
        for name,contents in parts.items():
            package.writestr(name,contents)


def external_book(book, filename, sheetname, address, cached):
    sheet=ExternalSheetData(sheetId=0,row=[ExternalRow(r=int(address[1:]),cell=[
        ExternalCell(r=address,t='n',v=str(cached))])])
    book_link=ExternalLink(externalBook=ExternalBook(
        sheetNames=ExternalSheetNames(sheetName=[sheetname]),
        sheetDataSet=ExternalSheetDataSet(sheetData=[sheet]),id='rId1'))
    book_link.file_link=Relationship(type='externalLinkPath',Id='rId1',Target=filename,TargetMode='External')
    book._external_links.append(book_link)


def write_csv(path, encoding, header, rows):
    with path.open('w',encoding=encoding,newline='') as output:
        writer=csv.writer(output)
        writer.writerow(header)
        writer.writerows(rows)


def freezer_csv():
    rows=[]
    ramp={110:'-14.9',111:'-14.7',112:'-13.8',113:'-12.7',114:'-11.8',115:'-10.8',
          116:'-11.4',117:'-12.5',118:'-13.1',119:'-14.8',120:'-15.5'}
    for i in range(288):
        instant=datetime(2026,10,3)+timedelta(minutes=5*i)
        measurement=ramp.get(i,f'{-19.8+(i%7-3)*.1:.1f}')
        rows.append((instant.strftime('%Y-%m-%d %H:%M'),'EQ-FRZ-D',measurement,
                     '고온' if float(measurement)>-15 else '',NOTICE if i==0 else
                     ('도어 닫힘 재확인' if i==117 else '')))
    return rows


def masters():
    extra=[('냉각수 순환설비','EQ-COOL-02'),('주 펌프','EQ-PUMP-P1'),('예비 펌프','EQ-PUMP-P2')]
    types=['온도계','교반기','압력계','유량계','전도도계','진동계','점검 타이머']
    equipment=[(name,code) for name,code,_ in CAL_INSTRUMENTS]+extra
    equipment.extend((f'{types[i%7]} {i+1:02d}',f'EQ-UTL-{i+21:03d}') for i in range(60-len(equipment)))
    headings=['장비번호','장비명','위치','관리 SOP','최근 교정일','다음 교정일','상태','문서']
    target=register('XLS-1',4,'장비마스터_목록_2026.xlsx','2026 장비 마스터',
                    department='설비',number='REG-EQ-2026-001',purposes='parse structure lineage chunking embedding_eval vectordb')
    workbook=Workbook()
    ws=workbook.active
    ws.title='장비'
    sheet_banner(ws,'2026 장비 마스터 · 제1공장',8)
    ws.append(headings)
    date_styles=['yyyy-mm-dd','yyyy.mm.dd','yyyy-mm-dd']
    devices=[]
    for i,(name,code) in enumerate(equipment):
        sop=['SOP-QC-0012','SOP-QC-014','SOP-EQ-0101','SOP-QC-0040 Rev.3','SOP-EQ-0102',
             'SOP-QC-0040 Rev.5'][i%6]
        last=date(2025,12,12)+timedelta(days=i*4)
        due=last+timedelta(days=365)
        doc_label={2:'적합성 절차',3:'원본 성적서',4:'교정 현황'} if i in (2,3,4) else {}
        row=[code,name,['제1공장 QC','제1공장 설비','제2공장 지원'][i%3],sop,last,due,
             '확인 필요' if i%11==5 else '사용 가능',doc_label.get(i,'')]
        ws.append(row)
        excel_row=4+i
        for position in [5,6]:
            ws.cell(excel_row,position).number_format=date_styles[i%3]
        devices.append([*row[:4],last.strftime('%Y.%m.%d' if i%3==1 else '%Y-%m-%d'),
                        due.strftime('%Y.%m.%d' if i%3==1 else '%Y-%m-%d'),*row[6:]])
        states={
            'SOP-QC-0012':('ambiguous',['SOP-B1','SOP-B2'],None),
            'SOP-QC-014':('linked',['SOP-C1'],None),
            'SOP-EQ-0101':('missing',[],None),
            'SOP-QC-0040 Rev.3':('outdated',['SOP-A1'],'SOP-A3'),
            'SOP-EQ-0102':('linked',['SOP-C3'],None),
            'SOP-QC-0040 Rev.5':('linked',['SOP-A3','SOP-A3P'],'SOP-A3'),
        }
        state,targets,latest=states[sop]
        link('XLS-1',sop,f'장비!D{excel_row}',state,targets,latest=latest)
    for row,address,state,targets,kind in [
        (6,RELATIVE_SOP,'linked',['SOP-C1'],'hyperlink'),
        (7,SHARED_CERT,'missing',[],'shared_path'),
        (8,CAL_URL,'external',[],'url'),
    ]:
        ws[f'H{row}'].hyperlink=address
        link('XLS-1',address,f'장비!H{row}',state,targets,kind=kind)
    table_style(ws,3,[19,24,20,27,18,18,16,22])
    ws.freeze_panes='D4'
    ws.auto_filter.ref='A3:H63'
    gc=workbook.create_sheet('교정')
    sheet_banner(gc,'연간 교정 일정 연결',3)
    gc.append(['근거','참조 값','단위'])
    # OOXML serializes external workbook formulas using relationship indexes.
    gc.append(['교정일정_2026.xlsx',"='[1]일정'!C5",'일'])
    gc.append(['구매요청_집계.xlsx',"='[2]Sheet1'!B3",'건'])
    table_style(gc,3,[38,23,12])
    external_book(workbook,'교정일정_2026.xlsx','일정','C5',8)
    external_book(workbook,'구매요청_집계.xlsx','Sheet1','B3',14)
    link('XLS-1','[교정일정_2026.xlsx]','교정!B4','linked',['XLS-2'],kind='external_workbook')
    link('XLS-1','[구매요청_집계.xlsx]','교정!B5','missing',kind='external_workbook')
    workbook.save(target)
    write_cache(target,{2:{'B4':8,'B5':14}})
    MANIFEST['XLS-1']['sheets']=['장비','교정']
    gold_table('XLS-1','장비',['장비번호','장비명','위치','관리 SOP','최근 교정일','다음 교정일','상태','문서'],devices,location='장비!A3:H63')
    gold_table('XLS-1','교정',['근거','참조 값','단위'],
               [['교정일정_2026.xlsx','8','일'],['구매요청_집계.xlsx','14','건']],location='교정!A3:C5')
    GOLD['XLS-1']['formulas']={'교정!B4':"='[교정일정_2026.xlsx]일정'!C5",'교정!B5':"='[구매요청_집계.xlsx]Sheet1'!B3"}
    return equipment


def schedule(equipment):
    target=register('XLS-2',4,'교정일정_2026.xlsx','2026년 정기 교정 일정',department='설비',
                    purposes='parse structure chunking embedding_eval vectordb')
    book=Workbook()
    ws=book.active
    ws.title='일정'
    sheet_banner(ws,'2026년 정기 교정 일정 · 계측실',26)
    for index,key in enumerate(['장비번호','장비명'],1):
        ws.cell(3,index,key)
        ws.merge_cells(start_row=3,end_row=4,start_column=index,end_column=index)
    cells=['장비번호','장비명']
    for month in range(1,13):
        n=3+2*(month-1)
        ws.cell(3,n,f'{month}월')
        ws.merge_cells(start_row=3,end_row=3,start_column=n,end_column=n+1)
        ws.cell(4,n,'예정일')
        ws.cell(4,n+1,'상태')
        cells.extend([f'{month}월 예정일',f'{month}월 상태'])
    rows=[]
    for i,(name,code) in enumerate(equipment[:40]):
        month=1+(i*5)%12
        value=8 if i==0 else 5+(i*3)%22
        data=[code,name]
        for n in range(1,13):
            data.extend([value,'완료' if n<=9 else '예정'] if n==month else ['',''])
        ws.append(data)
        rows.append(data)
    table_style(ws,4,[19,22]+[11,11]*12)
    for row in range(5,45):
        for col in range(3,27,2):
            if ws.cell(row,col).value:
                ws.cell(row,col).fill=PatternFill('solid',fgColor='CCE5D3' if col<21 else 'F7DFB8')
    ws.freeze_panes='C5'
    book.save(target)
    MANIFEST['XLS-2']['sheets']=['일정']
    gold_table('XLS-2','일정',cells,rows,merged=True,location='일정!A3:Z44')
    GOLD['XLS-2']['display_header_rows']=[
        ['장비번호','장비명',*[word for m in range(1,13) for word in [f'{m}월','']]],
        ['','',*(['예정일','상태']*12)],
    ]


def logs():
    rows=[]
    for index in range(31*24*12):
        stamp=datetime(2026,10,1)+timedelta(minutes=5*index)
        measurement=4+(index%19-9)*.05
        event=''
        if 4028<=index<4036:
            measurement=[7.2,7.4,8.1,8.4,8.3,7.8,7.0,6.8][index-4028]
            event='냉장고A 고온'
        rows.append([stamp.strftime('%Y-%m-%d %H:%M'),'4.0',f'{measurement:.1f}',
                     f'{42.0+(index%31)*.2:.1f}',NOTICE if index==0 else event])
    for fid,filename,encoding,active in [
        ('XLS-3','온도기록_냉장고A_2026-10.csv','utf-8-sig',rows),
        ('XLS-3C','온도기록_냉장고A_2026-10_cp949.csv','cp949',rows[:2000]),
    ]:
        target=register(fid,4,filename,'냉장고 A 2026-10 온도 기록',priority='P0' if fid=='XLS-3' else 'P1',
                        department='생산',purposes='parse compare chunking embedding_eval vectordb',
                        pair='XLS-3C' if fid=='XLS-3' else 'XLS-3',
                        notes='첫 기록의 경보 열에는 가상 고지를 넣었다. 고온 구간은 냉동고 D 일탈과 무관하다.')
        write_csv(target,encoding,LOG_HEADER,active)
        MANIFEST[fid]['encoding']=encoding
        gold_table(fid,'냉장고 A 온도 기록',LOG_HEADER,active,location=f'CSV 레코드 1–{len(active):,}')


def input_coa():
    fid='COA-2'
    target=register(fid,3,'시험성적서_원료검수_2026-10.xlsx','10월 원료 검수 시험 성적',
                    priority='P1',department='QC',purposes='parse structure chunking embedding_eval vectordb')
    book=Workbook()
    summary=book.active
    summary.title='요약'
    sheet_banner(summary,'원료 검수 시험 요약 · 2026년 10월',7)
    summary.merge_cells('A3:A4')
    summary.merge_cells('B3:D3')
    summary.merge_cells('E3:G3')
    for addr,value in {'A3':'원료 코드','B3':'월간 시험 결과','E3':'조사 및 판정',
                       'B4':'입고 건','C4':'시험 건','D4':'완료율','E4':'부적합 건','F4':'상태','G4':'담당'}.items():
        summary[addr]=value
    summary_rows=[['RM-A',200,200,1.0,1,'부적합','QC 시험담당 김O준'],
                  ['RM-B',200,200,1.0,1,'부적합','QC 시험담당 김O준'],
                  ['RM-C',200,200,1.0,0,'적합','QA 승인 이O희']]
    for row in summary_rows:
        summary.append(row)
    for srow in range(5,8):
        summary[f'D{srow}'].number_format='0%'
    table_style(summary,4,[15,12,12,15,12,14,23])
    summary.conditional_formatting.add('A5:G7',FormulaRule(formula=['$F5="부적합"'],
        fill=PatternFill('solid',fgColor='F7D8DA')))
    raw=book.create_sheet('원자료')
    headings=['시험번호','일자','원료','항목','단위','측정1','측정2','측정3','평균','RSD','판정','비고']
    raw.append(headings)
    table_data=[]
    cache={}
    for index in range(600):
        material=['RM-A','RM-B','RM-C'][index//200]
        stamp=date(2026,10,1)+timedelta(days=index%31)
        base=99.20+(index%13)*.035
        bad=index in (57,341)
        if bad:
            base=96.20 if index==57 else 96.45
        vals=[round(base+v,2) for v in [.02,-.03,.01]]
        mean=sum(vals)/3
        rsd=(sum((v-mean)**2 for v in vals)/2)**.5/mean
        row=index+2
        rowdata=[f'RMQ-26-{index+1:04d}',stamp,material,'함량','%',*vals,
                 f'=AVERAGE(F{row}:H{row})',f'=STDEV(F{row}:H{row})/I{row}',
                 '부적합' if bad else '적합','격리 검토' if bad else '']
        raw.append(rowdata)
        table_data.append([rowdata[0],stamp.isoformat(),material,'함량','%',
                           *[f'{v:.2f}' for v in vals],f'{mean:.2f}',f'{rsd:.2%}',*rowdata[-2:]])
        for col in 'FGHI':
            raw[f'{col}{row}'].number_format='0.00'
        raw[f'J{row}'].number_format='0.00%'
        raw[f'B{row}'].number_format='yyyy-mm-dd'
        if bad:
            raw[f'F{row}'].comment=Comment('원료 격리 후 두 번째 검토를 요청했다.','QC 시험담당 김O준')
        cache[f'I{row}']=mean
        cache[f'J{row}']=rsd
    table_style(raw,1,[22,15,13,14,10,12,12,12,13,12,13,17])
    raw.freeze_panes='D2'
    standards=book.create_sheet('기준')
    standards.append(['항목','하한','상한'])
    standards.append(['함량','98.0 %','102.0 %'])
    standards.sheet_state='hidden'
    graphs=book.create_sheet('차트')
    graphs.append(['시험번호','함량 평균'])
    sample=[]
    for index in range(0,600,50):
        sample.append([table_data[index][0],round(cache[f'I{index+2}'],2)])
        graphs.append(sample[-1])
    plot=LineChart()
    plot.title='원료 함량 구간별 점검'
    plot.y_axis.title='함량 (%)'
    plot.add_data(Reference(graphs,min_col=2,min_row=1,max_row=graphs.max_row),titles_from_data=True)
    plot.set_categories(Reference(graphs,min_col=1,min_row=2,max_row=graphs.max_row))
    graphs.add_chart(plot,'D2')
    book.save(target)
    write_cache(target,{2:cache})
    MANIFEST[fid]['sheets']=['요약','원자료','기준','차트']
    gold_table(fid,'요약',['원료 코드','입고 건','시험 건','완료율','부적합 건','상태','담당'],
               [[*r[:3],f'{r[3]:.0%}',*r[4:]] for r in summary_rows],merged=True,location='요약!A3:G7')
    GOLD[fid]['display_header_rows']=[['원료 코드','월간 시험 결과','','','조사 및 판정','',''],
                                     ['','입고 건','시험 건','완료율','부적합 건','상태','담당']]
    gold_table(fid,'원자료',headings,table_data,location='원자료!A1:L601')
    gold_table(fid,'기준',['항목','하한','상한'],[['함량','98.0 %','102.0 %']],location='기준!A1:C2')
    gold_table(fid,'차트',['시험번호','함량 평균'],sample,location='차트!A1:B13')


def wide():
    fid='XLS-4'
    target=register(fid,4,'배치기록_요약_2026Q3.xlsx','2026년 3분기 배치 기록 요약',
                    priority='P1',department='생산',purposes='parse chunking embedding_eval vectordb',
                    notes='두 단계 표 머리글 바로 위에 행을 삽입하지 않도록 1행 A1 셀 메모와 첫 두 식별 열 머리글에 가상 고지를 표시했다.')
    book=Workbook()
    ws=book.active
    ws.title='배치 요약'
    ws.merge_cells('A1:B1')
    ws['A1']='배치 식별 · Fabrikam Bio 가상 문서'
    ws['A1'].comment=Comment(NOTICE,'Fabrikam Bio')
    for base in range(3,41,4):
        end=min(base+3,40)
        ws.merge_cells(start_row=1,start_column=base,end_row=1,end_column=end)
        ws.cell(1,base,f'기록 구간 {(base-3)//4+1:02d}')
        ws.column_dimensions.group(get_column_letter(base),get_column_letter(end),outline_level=1)
    measures=['배치 ID','기록 일자',*[f'구간 {(i-3)//4+1:02d} {["확인","보완","승인","보류"][(i-3)%4]} 건' for i in range(3,41)]]
    ws.append(measures)
    rows=[]
    totals=[0]*38
    for index in range(300):
        vals=[(index*5+j*3+(index//13))%18 for j in range(38)]
        for j,value in enumerate(vals):
            totals[j]+=value
        day=date(2026,7,1)+timedelta(days=index%92)
        label=['2026A031','2026A032','2026B007'][index] if index<3 else f'작업기록-{index+1:03d}'
        ws.append([label,day,*vals])
        ws[f'B{index+3}'].number_format='yyyy-mm-dd'
        rows.append([label,day.isoformat(),*vals])
    formulas=[f'=SUM({get_column_letter(i)}3:{get_column_letter(i)}302)' for i in range(3,41)]
    ws.append(['합계','',*formulas])
    ws.freeze_panes='C3'
    table_style(ws,2,[20,16]+[16]*38)
    book.save(target)
    write_cache(target,{1:{f'{get_column_letter(i+3)}303':v for i,v in enumerate(totals)}})
    MANIFEST[fid]['sheets']=['배치 요약']
    gold_table(fid,'배치 요약',measures,rows+[['합계','',*totals]],merged=True,location='배치 요약!A1:AN303')
    GOLD[fid]['display_header_rows']=[[ws.cell(1,i).value or '' for i in range(1,41)],measures]


def build_sheets():
    equipment=masters()
    schedule(equipment)
    logs()
    input_coa()
    wide()
