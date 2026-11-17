from core import *
from narrative import detail

QA_PATH = r'\\fabrikam-fs01\qa\SOP\SOP-QC-0012_Rev2.docx'
CLEAN_URL = 'https://intranet.fabrikam.example/sop/SOP-QC-0040'
CLEAN_TITLE = '세척 밸리데이션 절차'
CLEAN_FILES = {
    'SOP-A1': ('SOP-QC-0040_세척밸리데이션_Rev.3.docx',3,'2024-03-11'),
    'SOP-A2': ('SOP-QC-0040_세척밸리데이션_Rev.4.docx',4,'2025-01-20'),
    'SOP-A3': ('SOP-QC-0040 세척 밸리데이션 절차 Rev.5 (최종).docx',5,'2026-02-14'),
}
SPOTS = [
    ('탱크 맨홀','25','내측'),('배출 노즐','25','내측'),('교반축 하단','25','외주'),
    ('도어 가스켓','16','접촉면'),('리턴 노즐','25','연결부'),('탱크 천장','25','상면'),
    ('액위 센서 접액부','12','흠집 점검'),('온도 센서 끝단','10','접촉면'),
    ('배플 상단','25','앞면'),('배플 하단','25','뒷면'),('탱크 하부 곡면','25','후면'),
    ('공급 헤더','25','용접부'),('샘플 밸브 입구','16','안쪽'),
    ('계기 연결 티','12','모서리'),('분기 배관','25','상면'),('엘보 저점','25','저점'),
    ('클램프 분리면','16','가스켓'),('배출 배관 끝','25','내벽'),
    ('복귀 배관','25','하부 용접부'),('밸브 시트','12','접촉면'),('환류 분기 가스켓','16','신규 채취점'),
]
APPROVAL = [
    ('작성','QC 시험담당 김O준','제1공장 QC','기록 확인'),
    ('검토','설비팀 박O수','제1공장 설비','현장 대조'),
    ('승인','QA 승인 이O희','품질보증','배포 승인'),
]
REV_HISTORY = [
    ('Rev.2','2024-01-08','보관 조건 및 검체 식별 기준 반영'),
    ('Rev.3','2024-03-11','채취 위치를 작업 구역별로 정리'),
    ('Rev.4','2025-01-20','잔류 허용 기준 개정 및 환류 가스켓 채취점 추가'),
    ('Rev.5','2026-02-14','TOC 한계 개정 및 시각 검사 기준 신설'),
]


def clean_pages(assets, rev, date):
    residue = '≤ 20 ppm' if rev == 3 else '≤ 10 ppm'
    toc = '≤ 500 ppb' if rev == 5 else '≤ 800 ppb'
    definition = [
        ('스왑','지정 면적을 닦아 표면 잔류물을 회수하는 도구'),
        ('검체','설비에서 채취하고 식별번호를 부여한 시험 시료'),
        ('공시험','채취 경로에서 유입되는 시험 간섭을 확인하는 대조군'),
        ('TOC','전유기탄소를 평가하는 지표'),
        ('잔류 허용 기준','제품 잔류 여부를 판단하는 시험별 한계'),
        ('접액부','제품 또는 공정액과 직접 접촉하는 표면'),
        ('회수율','표면에서 채취한 양과 기준 첨가량의 비율'),
        ('시각 점검','조명이 확보된 상태에서 잔류 흔적을 검사하는 활동'),
    ]
    criteria = [
        ('제품 잔류',residue,'HPLC','제품 잔류 평가표'),
        ('최종 헹굼액 TOC',toc,'TOC 분석','청정도 검토표'),
        ('전도도','≤ 1.3 µS/cm','전도도계','헹굼액 기록'),
        ('공시험 간섭','≤ 2.0 %','표준 응답 비교','대조 시험 기록'),
        ('회수율','70.0–130.0 %','첨가 검체 비교','회수율 검토표'),
        ('시각 상태','잔류 흔적 없음','조명하 관찰','표면 점검 기록'),
    ]
    spots = [(str(i), '탱크부' if i < 12 else '배관부', name,
              'PTFE' if i in [4,20,21] else 'SUS316L', area, memo)
             for i,(name,area,memo) in enumerate(SPOTS[:20 if rev==3 else 21],1)]
    visual = ([h('7. 시각 검사 기준'), *detail('clean',9),
               p('관찰 결과에 이상이 없으면 육안 적합으로 표시한다. 정상 조명을 확보할 수 없는 면은 재확인 전까지 승인하지 않는다.'),
               fig(assets['tank'],'그림 2. 제품 접촉면 시각 검사 예시',4.85),
               h('7.2 기록',2)] if rev==5 else [h('7. 기록')])
    return [
        [h(f'문서번호 SOP-QC-0040 | 개정번호 Rev.{rev}',2), p(f'시행일 {date} · 제1공장 시험관리본'),
         t('결재란',['구분','담당','소속','결재 구분'],APPROVAL),
         h('1. 목적'), p('이 절차는 세척 완료 후 시험 검체를 채취하고 잔류 허용 기준과 판정을 관리하기 위한 공통 요건을 규정한다.'),
         *detail('clean',0,1), h('2. 적용 범위'),
         bullet('제품 FBX-101과 접촉하는 제1공장 탱크 및 연결 배관을 대상으로 한다.'),
         bullet('검체를 직접 채취하기 어려운 분기부는 설비팀의 접근 가능 여부를 먼저 검토한다.'),
         bullet('시험 결과에 영향을 주지 않는 외함 청소 기록은 별도의 설비 대장에서 관리한다.'),
         h('3. 책임과 권한'), h('3.1 시험 담당',2), p('채취 작업과 원자료 점검을 수행하고 기준을 벗어난 데이터를 검토자에게 전달한다.'),
         h('3.2 검토 및 승인',2), p('품질보증은 결과와 개정 이력의 일치 여부를 검토하고 서면 승인한다.')],
        [h('4. 용어 정의'), t('용어 정의표',['용어','정의'],definition,widths=[1.58,5.1]),
         h('5. 허용 기준'), p('제품 잔류 기준은 채취 면적을 고려하여 계산한 검체 보고값에 적용한다.'),
         note('ppm 수치는 검체 추출액의 질량분율을 뜻한다. 원래 표면의 면적 환산값과 별도로 기록한다.'),
         t('표 1. 세척 후 허용 기준',['항목','기준','시험법','근거'],criteria),
         *detail('clean',7)],
        [h('6. 절차'),h('6.1 작업 전 확인',2),*detail('clean',1),
         p('작업 배정표에 기재된 설비와 채취 설비가 같은지 마지막으로 대조한다.'),
         h('6.2 용기 및 준비물',2),*detail('clean',2),
         p('준비물은 인계 전에 수량을 세고 필요한 예비 용기를 포함한다.'),
         h('6.3 대조 검체',2),*detail('clean',5),
         p('대조 검체는 본 검체와 분리한 번호로 접수한다.'),
         h('6.4 표면 검체 채취',2),*detail('clean',3,4),
         p('위치별 면적과 접근 방향은 아래 표에 따라 채취 기록과 대조한다.'),
         t('표 2. 스왑 채취 위치',['번호','설비','위치','재질','면적(cm²)','비고'],spots,
           row_pt=30,span=True,widths=[.5,.75,1.68,1.0,.96,1.76]),
         fig(assets['swab'],'그림 1. 스왑 채취 위치 배치도',4.12)],
        [h('6.5 검체 운반과 접수',2),*detail('clean',6,7),
         p('시험 접수 중 문제를 발견하면 시험 기록의 상태란을 보류로 전환한다.'),
         h('6.6 시험 결과 검토',2),*detail('clean',8,11),
         p('채취 담당과 결과 검토 담당이 다르면 의심 사항을 검토란에 공동으로 기록한다.'),
         *visual, *detail('clean',10),
         p('시험 완료 후 기록 원본은 검증 기록함에 등록하고 작업일 기준으로 확인할 수 있게 한다.')],
        [h('8. 참고 문서'), bullet('SOP-QC-0012 Rev.2 · 시험기기 교정'),
         bullet('WI-QC-052 · pH미터 일상점검'), bullet('SOP-EQ-0101 · 설비 인계 및 정비'),
         href(QA_PATH,QA_PATH), href(CLEAN_URL,CLEAN_URL),
         h('9. 개정 이력'),
         t('개정 이력',['개정','시행일','변경 내용'],REV_HISTORY[:rev-1],widths=[1,1.38,4.27]),
         h('배포 확인',2),
         p('출력본은 배포 목록에 등록된 공정 구역과 시험실에 비치한다. 기존 개정 파일은 교체 후 회수 사실을 서면으로 남긴다.'),
         p('작업 중 이 절차에서 다루지 않는 위치가 발견되면 도면 관리 담당자와 확인한 다음 채취 계획에 반영한다.')],
    ]


def clean_links(file_id):
    link(file_id,'SOP-QC-0012 Rev.2','§8 참고 문서','ambiguous',['SOP-B1','SOP-B2'])
    link(file_id,'WI-QC-052','§8 참고 문서','linked',['SOP-C2'])
    link(file_id,'SOP-EQ-0101','§8 참고 문서','missing')
    link(file_id,QA_PATH,'§8 시험기기 교정 파일','ambiguous',['SOP-B1','SOP-B2'],kind='shared_path')
    link(file_id,CLEAN_URL,'§8 인트라넷','external',kind='url')


CAL_INSTRUMENTS = [
    ('분석용 저울','EQ-BAL-01','±0.2 mg'),('정밀 저울','EQ-BAL-02','±1.0 mg'),
    ('HPLC','EQ-HPLC-07','±1.0 %'),('전도도계','EQ-CND-02','±0.5 µS/cm'),
    ('pH미터','EQ-PH-03','±0.05 pH'),('UV 검출기','EQ-UV-01','±1 nm'),
    ('온습도계','EQ-TH-08','±0.5 °C'),('온도 기록계','EQ-TEMP-11','±0.4 °C'),
    ('냉동고 D','EQ-FRZ-D','±0.5 °C'),('초저온 냉동고','EQ-UF-03','±1.0 °C'),
    ('항온 배양기','EQ-INC-H','±0.5 °C'),('압력계','EQ-PRS-04','±0.05 bar'),
    ('타이머','EQ-TMR-06','±1 s'),('진동계','EQ-VIB-02','±0.2 mm/s'),
    ('유량계','EQ-FLW-09','±0.8 %'),
]


def calibration_pages(rev, date, modified):
    instrument_rows = [(name,code,'6개월' if modified and idx<2 else '12개월',tol,
                        '가상교정연구소' if idx%3==0 else '제1공장 계측실')
                       for idx,(name,code,tol) in enumerate(CAL_INSTRUMENTS)]
    return [
        [h(f'문서번호 SOP-QC-0012 | 개정번호 Rev.{rev}',2),p(f'시행일 {date}'),
         t('결재란',['구분','담당','소속','결재 구분'],APPROVAL),
         h('1. 목적'),p('시험용 기기의 측정 정확도가 관리 범위 내에 있는지 확인하고, 교정 후 장비 사용 상태를 관리한다.'),
         h('2. 적용 범위와 역할'),*detail('calibration',0,1),
         p('시험기기 책임자는 교정 대상 선정과 기록 인계를 수행한다. 품질보증은 허용 오차 이탈의 영향 범위와 처리 방침을 확인한다.'),
         h('3. 기본 주기',2),
         p('일반 기기의 표준 교정 주기는 12개월이다. ' +
           ('저울 교정 주기는 6개월로 별도 적용한다.' if modified else '저울도 같은 주기로 관리한다.'))],
        [h('4. 교정 대상과 허용 오차'),
         t('표 1. 시험기기 교정 기준',['기기','관리번호','교정 주기','허용 오차','교정 기관'],
           instrument_rows,row_pt=23,widths=[1.22,1.33,.88,1.32,1.92]),
         *detail('calibration',2,3)],
        [h('5. 교정 수행'),h('5.1 현장 준비',2),*detail('calibration',4,5),
         p('표준기가 기기와 연결된 시각과 측정에 사용된 기록의 경로를 교정 확인서에 적는다.'),
         h('5.2 기록 및 검토',2),*detail('calibration',6,7),
         numbered('적합 기기의 교정 표지를 바꾸고 유효기간을 장비 대장에 반영한다.'),
         numbered('사용 보류 기기는 시험 중지 상태로 표시하고 시험 담당자에게 통보한다.'),
         numbered('등록한 성적서의 항목명이 내부 시험 기록에서도 동일한지 확인한다.'),
         h('5.3 수리 후 복귀',2),*detail('calibration',8)],
        [h('6. 기록 관리'),*detail('calibration',9),
         h('6.1 관리 양식',2),bullet('FRM-QC-0012-A · 교정 일정 확인표'),
         bullet('FRM-QC-0012-B · 허용 오차 이탈 조사표'),
         bullet('FRM-QC-0012-C · 교정 결과 인계서'),
         p('서명된 서식은 교정 완료일을 기준으로 보관하고, 담당자 변경 시 서식의 저장 위치와 보류 항목을 함께 인계한다.'),
         h('7. 개정 이력'),
         t('개정 이력',['개정','검토일','변경 내용'],[
             ('Rev.1','2023-09-01','최초 시행'),*([('Rev.2','2025-06-10','교정 성적서 검토 항목 명시')] if rev==2 else [])])],
    ]


def build_sops(assets):
    for fid,(name,rev,date) in CLEAN_FILES.items():
        register(fid,1,name,CLEAN_TITLE,number='SOP-QC-0040',rev=f'Rev.{rev}',issued=date,
                 department='QC',latest=rev==5,status='confirmed',pair='SOP-A3P' if rev==5 else None,
                 purposes='parse compare structure lineage chunking embedding_eval vectordb',
                 notes={3:'잔류 20 ppm, 채취 위치 20개.',4:'이전 개정. 잔류 10 ppm 및 21번 채취점 추가.',
                        5:'최신 개정. TOC 기준 500 ppb 및 시각 검사 기준 추가.'}[rev])
        build_word(fid,clean_pages(assets,rev,date))
        kv(fid,1,문서번호='SOP-QC-0040',개정번호=f'Rev.{rev}',시행일=date)
        clean_links(fid)
    register('SOP-A3P',1,'SOP-QC-0040_Rev5.pdf',CLEAN_TITLE,number='SOP-QC-0040',rev='Rev.5',
             issued='2026-02-14',department='QC',status='confirmed',pair='SOP-A3',
             purposes='parse compare structure lineage chunking embedding_eval vectordb',
             notes='SOP-A3의 동일 페이지·내용을 유지한 디지털 PDF.')
    register('SOP-A4',1,'복사본 - SOP-QC-0040_세척밸리데이션_Rev.4.docx',CLEAN_TITLE,
             number='SOP-QC-0040',rev='Rev.4',issued='2025-01-20',department='QC',latest=False,
             status='confirmed',purposes='parse lineage structure',notes='SOP-A2의 바이트 동일 복사본.')
    for fid,rev,date,name in [
        ('SOP-B1',2,'2025-06-10','SOP-QC-0012_시험기기_교정_Rev.2.docx'),
        ('SOP-B2',2,'2025-06-12','SOP-QC-0012_시험기기교정_Rev2_수정.docx'),
        ('SOP-B0',1,'2023-09-01','SOP-QC-0012_시험기기_교정_Rev.1.pdf'),
    ]:
        register(fid,1,name,'시험기기 교정',number='SOP-QC-0012',rev=f'Rev.{rev}',issued=date,
                 priority='P1' if rev==1 else 'P0',department='QC',latest=None if rev==2 else False,
                 status='hold',purposes='parse lineage chunking embedding_eval vectordb',
                 notes='동일 Rev.2의 두 시행일 및 저울 교정 주기가 다르며 개정 이력은 동일하다.' if rev==2
                 else '카탈로그에 지정된 2023년 시행일의 구판.')
        build_word(fid,calibration_pages(rev,date,fid=='SOP-B2'),pdf=rev==1)
        kv(fid,1,문서번호='SOP-QC-0012',개정번호=f'Rev.{rev}',시행일=date)
        for letter,name in zip('ABC',['교정 일정 확인표','허용 오차 이탈 조사표','교정 결과 인계서']):
            link(fid,'FRM-QC-0012-'+letter,f'§6.1 {name}','missing')
    register('SOP-C1',1,'SOP-QC-014_HPLC_시스템적합성_v3.docx','HPLC 시스템 적합성 시험',
             number='SOP-QC-014',rev='v3',department='QC',issued='2026-04-06')
    build_word('SOP-C1',[
        [h('문서번호 SOP-QC-014 | 개정번호 v3',2),p('시행일 2026.04.06 · 관리 기기 EQ-HPLC-07'),
         h('1. 목적 및 적용 범위'),p('제품 FBX-101 시험 전 HPLC 시스템의 반복성 및 분리 상태를 점검한다.'),
         *detail('hplc',0,1),h('2. 이동상 준비'),
         *detail('hplc',2),t('표 1. 이동상 준비 단계',['단계','기록','확인 기준'],[
             ('용기 식별','이동상 A / 이동상 B','승인 메서드와 일치'),
             ('조제 확인','조제 시각 및 책임자','유효 시간 내 사용'),
             ('라인 확인','유입 방향 및 연결 대상','시험 기기와 동일'),
             ('시험 전 점검','공시험 기록 및 압력','변화 없음')])],
        [h('3. 시스템 적합성 기준'),*detail('hplc',3,4,6),
         t('표 2. 시스템 적합성 판정',['항목','기준','적용 구간'],[
            ('이론단수','≥ 2000','주 피크'),('테일링 계수','≤ 2.0','주 피크'),
            ('반복 주입 %RSD','≤ 2.0 %','n=5'),('공시험 응답','유의 피크 없음','표준액 전')]),
         h('4. 적분과 재시험'), *detail('hplc',5,7)],
        [h('5. 결과 보고'),fig(assets['chromatogram'],'그림 1. 표준액 크로마토그램 예시',5.6),
         *detail('hplc',8,9),p('판정용 시퀀스에는 표준액 반복 주입 5회를 기록한다.'),
         h('6. 참고'),bullet('SOP-QC-0012 · 시험기기 교정')],
    ])
    kv('SOP-C1',1,문서번호='SOP-QC-014',관리기기='EQ-HPLC-07')
    link('SOP-C1','SOP-QC-0012','§6 참고','ambiguous',['SOP-B1','SOP-B2'])
    register('SOP-C2',1,'WI-QC-052_pH미터_일상점검.docx','pH미터 일상점검',
             number='WI-QC-052',rev='Rev.2',priority='P1',department='QC',issued='2026-08-03')
    build_word('SOP-C2',[
        [h('문서번호 WI-QC-052 | 개정번호 Rev.2',2),p('보호 캡 세척 및 표준 완충액의 유효기간을 확인한다. 적용 기기는 EQ-PH-03이다.'),
         h('1. 준비 및 적용 범위'),*detail('calibration',0,2,3,4),
         p('보정 기록에는 사용한 저울이나 온도계가 있을 경우 관리번호를 함께 남긴다.')],
        [h('2. 일상점검'),t('표 1. 작업 전 체크리스트',['구분','확인 사항','점검'],[
             ('전극','보호 캡 분리 전 파손 확인','☐'),('온도','실온과 완충액 온도 대조','☐'),
             ('표준액','표준액 2종 식별','☐'),('보정','기울기 95.0–105.0 % 기록','☐'),
             ('종료','결과 저장과 전극 세척','☐')]),*detail('calibration',5,6,7)],
        [h('3. 이탈 및 보관'),*detail('calibration',8,9),h('4. 참고'),bullet('SOP-QC-0012 · 시험기기 교정')],
    ])
    link('SOP-C2','SOP-QC-0012','p.3 §4 참고','ambiguous',['SOP-B1','SOP-B2'])
    register('SOP-C3',1,'SOP-EQ-0102_냉동고_관리.docx','시험 시료 냉동고 관리',
             number='SOP-EQ-0102',rev='Rev.3',priority='P1',department='설비',issued='2026-05-09')
    build_word('SOP-C3',[
        [h('문서번호 SOP-EQ-0102 | 개정번호 Rev.3',2),h('1. 적용 대상'),
         p('냉동고 D EQ-FRZ-D와 초저온 냉동고 EQ-UF-03을 대상으로 한다.'),
         *detail('storage',0,1,2),t('표 1. 관리 설비',['설비','설정 값','예비 위치'],[
             ('EQ-FRZ-D','-20 °C','예비 랙 B'),('EQ-UF-03','-86 °C','초저온 랙 C')])],
        [col(2),h('2. 경보와 보관품 이동'),*detail('storage',3,4,5),
         box('경고 · 경보 해제 전 보류품을 일반 보관품과 섞지 않는다.'),
         h('3. 복구 판단'),*detail('storage',6,7,8,9),col(1)],
        [h('4. 관련 기록'),p('경보가 발생하면 대응 지시의 변경 이력과 창고 위치 목록을 관리한다.'),
         bullet('DEV-2026-0117 · 냉동고 D 온도 이탈 조사 사례'),*detail('storage',2,7)],
    ])
    link('SOP-C3','DEV-2026-0117','§4 관련 기록','linked',['RPT-2','RPT-2P'])
    register('SOP-C4',1,'문서번호없는_파일명_보관조건.docx','세척 검증 검체 보관 조건',
             number='SOP-QC-0040',rev='Rev.2',priority='P2',department='QC',latest=False,status='confirmed',
             issued='2024-01-08',purposes='parse lineage embedding_eval vectordb',
             notes='파일명에 번호가 없고 표지에만 구판 Rev.2 식별자가 있다. 표지 식별자를 계보와 참조 정답에 포함했다.')
    build_word('SOP-C4',[
        [h('문서번호 SOP-QC-0040 Rev.2',2),p('시행일 2024년 1월 8일 · 이전 양식 보존본'),
         h('1. 검체 보관'),*detail('clean',2,5,6,10),
         t('표 1. 보관 조건',['구분','보관 위치','확인 주체'],[
             ('검체','QC 검체 인계대','QC 시험담당'),('공시험','분리 밀폐함','QC 시험담당'),
             ('보류검체','QA 확인 선반','QA 승인자')])],
    ],running='Fabrikam Bio | 검체 보관 조건')
    link('SOP-C4','SOP-QC-0040 Rev.2','p.1 표지','outdated',['SOP-C4'],latest='SOP-A3')
