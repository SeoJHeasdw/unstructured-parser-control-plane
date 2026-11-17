from core import *
from narrative import detail
from visuals import chart

COOL_PATH = r'\\fabrikam-fs01\eng\equipment\EQ-COOL-02\점검이력.xlsx'
TEMP_NAME = '온도기록_원본_EQ-FRZ-D_2026-10-03.csv'
FREEZER_PHOTO = '현장사진_냉동고D.jpg'
FINDINGS = [
    ('01','공급 압력','2.6 bar','2.2–2.9 bar','양호','현상 유지'),
    ('02','복귀 압력','2.1 bar','1.8–2.4 bar','양호','현상 유지'),
    ('03','주 펌프 수평 진동','2.5 mm/s','≤ 4.5 mm/s','양호','월간 추세 확인'),
    ('04','예비 펌프 수평 진동','4.8 mm/s','≤ 4.5 mm/s','불량','베어링 정밀검사'),
    ('05','예비 펌프 수직 진동','4.1 mm/s','≤ 4.5 mm/s','주의','재측정 시 방향 기록'),
    ('06','주 펌프 회전수','1,450 rpm','1,420–1,480 rpm','양호','현상 유지'),
    ('07','공급 온도','12.4 °C','11.0–14.0 °C','양호','기록 유지'),
    ('08','복귀 온도','14.0 °C','12.0–17.0 °C','양호','기록 유지'),
    ('09','배관 이음부 외관','국부 부식','부식 없음','주의','플랜지 재확인'),
    ('10','제어반 외함','들뜸 없음','손상 없음','양호','현상 유지'),
    ('11','저수위 경보','표시 확인','정상 표시','양호','기능 검토'),
    ('12','탱크 접근부 누수','누수 없음','누수 없음','양호','현상 유지'),
]
FIELD = [
    ('09:10','압력계 공급측','2.6 bar','✓ 현장 확인'),
    ('09:15','압력계 복귀측','2.1 bar','✓ 현장 확인'),
    ('09:24','펌프 P-2 수평 진동','4.8 mm/s','✓ 재측정'),
    ('09:35','이음부 외관','국부 부식','✓ 사진 보존'),
]
TIMELINE = [
    ('09:10','서버 기록에서 -15 °C 초과 최초 확인','QC 시험담당 김O준'),
    ('09:12','현장 경보 접수 및 신규 검체 반입 정지','QC 시험담당 김O준'),
    ('09:24','도어 걸쇠 확인 및 예비 위치 확인','설비팀 박O수'),
    ('09:40','대상 로트 접수 보류 및 재고 대조','QA 승인 이O희'),
    ('09:57','서버 기록에서 -15 °C 이하 복귀','설비팀 박O수'),
    ('10:05','현장 패킹 하단 및 경보 기록 보존','설비팀 박O수'),
]
RESULTS = [
    ('외관','육안','무색 내지 미황색','무색','적합'),
    ('pH','전극법','6.0 ± 0.3','6.1','적합'),
    ('단백질 함량','UV','10.0 ± 0.5 mg/mL','10.2 mg/mL','적합'),
    ('순도(SEC)','SEC-HPLC','≥ 95.0 %','98.7 %','적합'),
    ('엔도톡신','내부 시험법','≤ 0.5 EU/mg','< 0.1 EU/mg','적합'),
    ('생균수','내부 시험법','≤ 10 CFU/mL','0 CFU/mL','적합'),
    ('동일성','펩타이드 대조','일치','일치','적합'),
    ('삼투압','빙점법','270–330 mOsm/kg','298 mOsm/kg','적합'),
    ('점도','점도계','≤ 8.0 mPa·s','3.2 mPa·s','적합'),
    ('비전도도','전도도계','9.0–13.0 mS/cm','10.4 mS/cm','적합'),
    ('탁도','광학법','≤ 5.0 NTU','1.2 NTU','적합'),
    ('실충전량','중량법','≥ 1.00 mL','1.06 mL','적합'),
    ('응집체','SEC-HPLC','≤ 2.0 %','1.1 %','적합'),
    ('절단체','SEC-HPLC','≤ 1.0 %','0.2 %','적합'),
    ('산성 변이체','전하 분리','≤ 24.0 %','16.8 %','적합'),
    ('염기성 변이체','전하 분리','≤ 15.0 %','9.4 %','적합'),
    ('주 전하 변이체','전하 분리','≥ 60.0 %','73.8 %','적합'),
    ('결합 활성','결합 시험','80.0–120.0 %','101.2 %','적합'),
    ('잔류 처리제','비색법','≤ 10 ppm','2.4 ppm','적합'),
    ('침전 확인','확대 관찰','침전 없음','침전 없음','적합'),
    ('용기 외관','육안','파손 없음','파손 없음','적합'),
    ('용기 밀봉','밀봉 확인','누출 없음','누출 없음','적합'),
    ('표시 점검','대조 검토','승인본 일치','일치','적합'),
    ('불용성 입자','광학 계수','≤ 1,250 개/mL','127 개/mL','적합'),
]
RAW_MATERIAL = [
    ('완충염 A','벤더 A','RM-260081','2026-02-17','2028-02-16','RMQ-0081','99.4 %','적합','개봉 전'),
    ('완충염 B','벤더 B','RM-260105','2026-02-21','2028-02-20','RMQ-0105','99.7 %','적합','밀봉'),
    ('희석액','벤더 C','RM-260107','2026-03-02','2027-03-01','RMQ-0107','무색','적합','냉장'),
]


def build_reports(assets):
    register('RPT-1',2,'RPT-EQ-2026-031_냉각수순환설비_정기점검보고서.docx',
             '냉각수 순환설비 정기점검 보고서',department='설비',number='RPT-EQ-2026-031',
             purposes='parse compare structure lineage chunking embedding_eval vectordb',pair='RPT-1P',status='confirmed')
    build_word('RPT-1',[
        [h('문서번호 RPT-EQ-2026-031',2),p('제1공장 · EQ-COOL-02 · 점검일 2026년 10월 14일 · 발행 2026-10-15'),
         h('1. 목적과 현장 범위'),*detail('cool',0,1,2),
         p('공급 압력은 재측정에서 2.6 bar로 확인되었다. 순환 예비 펌프는 별도 추세 기록의 검토 대상으로 등록하였다.'),
         fig(assets['skid'],'그림 1. 냉각수 순환 스키드 전경',5.2)],
        [h('2. 펌프와 배관 사진'),*detail('cool',3,4),
         fig(assets['pump'],'그림 2. 예비 펌프 P-2 근접',4.75),
         fig(assets['corrosion'],'그림 3. 배관 이음부 국부 부식',4.75)],
        [h('3. 점검 결과'),*detail('cool',5,7),
         t('표 1. 점검 결과',['번호','점검 항목','측정값','기준','판정','조치'],FINDINGS,
           row_pt=22,widths=[.45,1.40,1.0,1.0,.55,2.32]),
         p('이번 점검의 불량 항목은 예비 펌프 수평 진동 1건이다. 후속 조치에서 베어링 정밀검사를 요청하였다.')],
        [h('4. 현장 확인서'),p('현장 확인 시각 09:35 · 현장 담당 설비팀 박O수'),
         t('표 2. 현장 계측 기록',['시각','계측 위치','기록값','현장 확인'],FIELD,row_pt=36),
         p('현장 원기록은 승인된 점검 구역의 운전일지와 함께 보관한다.'),
         *detail('cool',8),fig(assets['stamp'],None,1.4)],
        [h('5. 진동 경향 및 순환 계통'),p('예비 펌프 진동의 10월 값은 4.8 mm/s다. 관리 기준인 4.5 mm/s를 처음 넘은 시점은 10월이다.'),
         fig(assets['vibration'],'그림 4. 냉각수 펌프 진동 추이',5.12),
         fig(assets['pid'],'그림 5. 냉각수 순환계통 P&ID',5.12)],
        [h('6. 제어반 및 후속 조치'),*detail('cool',6,9),
         fig(assets['cabinet'],'그림 6. 제어반 외함 상태',4.72),
         fig(assets['pipe'],None,4.72)],
        [h('7. 결론과 인계'),*detail('cool',10),
         p('예비 펌프 상태 개선의 책임 부서는 설비팀이다. 차기 확인일은 2026.11.05로 정하였다.'),
         h('8. 참고 문서'),bullet('SOP-QC-0040 Rev.4 · 현장 적용 당시 세척 허용 기준 ≤ 10 ppm'),
         bullet('SOP-EQ-0101 · 설비 인계 및 정비'),bullet('SOP-QC-014 · 시험기기 확인 절차'),
         href(COOL_PATH,COOL_PATH),
         t('검토 및 승인',['구분','담당','일자'],[
             ('작성','설비팀 박O수','2026-10-15'),('검토','QC 시험담당 김O준','2026-10-15'),
             ('승인','QA 승인 이O희','2026-10-15')]),fig(assets['signature'],None,1.5)],
    ])
    for written,state,targets,kind,latest in [
        ('SOP-QC-0040 Rev.4','outdated',['SOP-A2','SOP-A4'],'doc_number','SOP-A3'),
        ('SOP-EQ-0101','missing',[],'doc_number',None),('SOP-QC-014','linked',['SOP-C1'],'doc_number',None),
        (COOL_PATH,'missing',[],'shared_path',None),
    ]:
        link('RPT-1',written,'p.7 §8 참고 문서',state,targets,kind=kind,latest=latest)
    kv('RPT-1',1,문서번호='RPT-EQ-2026-031',설비='EQ-COOL-02',발행='2026-10-15')
    register('RPT-1P',2,'RPT-EQ-2026-031_점검보고서_서명본.pdf','냉각수 순환설비 정기점검 보고서',
             department='설비',number='RPT-EQ-2026-031',purposes='parse ocr compare structure lineage chunking embedding_eval vectordb',
             pair='RPT-1',status='confirmed',scanned=[4],notes='4쪽 현장 확인서는 붉은 승인 도장과 수기 체크가 있는 스캔. 마지막 장 서명 이미지.')
    register('RPT-2',2,'DEV-2026-0117_일탈보고서_온도이탈.docx','냉동고 D 온도 이탈 보고서',
             department='QA',number='DEV-2026-0117',issued='2026-10-08',status='confirmed',
             pair='RPT-2P',purposes='parse compare structure lineage chunking embedding_eval vectordb')
    build_word('RPT-2',[
        [h('문서번호 DEV-2026-0117',2),p('제1공장 · 발생일 2026-10-03 · 발행일 2026-10-08'),
         h('1. 접수 정보'),p('발생 설비는 냉동고 D EQ-FRZ-D이며 이탈 분류는 보관 온도이다. 담당자는 품질보증에 사건을 접수하였다.'),
         *detail('deviation',0,1,2),h('초기 경보 기준',2),
         p('기준 온도는 -15 °C이며 복귀 전 신규 반입을 일시 중지하였다. 최고 5분 기록은 -10.8 °C다.')],
        [h('2. 사건 개요'),p('냉동고 D는 2026-10-03에 -15 °C를 초과하였다. 확인된 온도 이탈은 47분 지속되었다.'),
         *detail('deviation',3),
         t('표 1. 사건 타임라인',['시각','사건','담당'],TIMELINE,widths=[.8,3.8,2.1]),
         p('경보 원장과 CSV의 측정 간격이 달라 최초 초과 시각과 복귀 시각은 경보 원장을 기준으로 산정하였다.')],
        [h('3. 조사 결과와 근본 원인'),*detail('deviation',4,5,6),
         fig(assets['fishbone'],'그림 1. 냉동고 D 이탈 원인 분석',5.52),
         p('직접 원인은 하단 도어 패킹 들뜸이다. 닫힘 확인 항목의 누락은 재발 위험을 높인 절차상 원인으로 판정하였다.')],
        [h('4. 영향 평가'),*detail('deviation',7,8),
         t('표 2. 영향 로트',['제품','로트','위치','판정','근거'],[
             ('FBX-101','2026A031','랙 D-2','보류','동일 보관 구간'),
             ('FBX-101','2026A032','랙 D-3','보류','동일 보관 구간')]),
         h('5. 시정 및 예방 조치'),numbered('하단 패킹 교체 후 도어 닫힘 확인 항목을 점검표에 추가한다.'),
         numbered('경보 수신 및 인계 담당을 지정하고 부재 시 대체 연락을 시험한다.'),
         numbered('CAPA-2026-0042에 완료 기준 및 효과 확인 일정을 등록한다.'),
         *detail('deviation',9,10)],
    ])
    kv('RPT-2',1,문서번호='DEV-2026-0117',발생설비='EQ-FRZ-D',발생일='2026-10-03')
    link('RPT-2','CAPA-2026-0042','p.4 §5 시정 및 예방 조치','linked',['RPT-3'])
    register('RPT-2P',2,'DEV-2026-0117_일탈보고서_첨부포함.pdf','냉동고 D 온도 이탈 보고서',
             department='QA',number='DEV-2026-0117',issued='2026-10-08',status='confirmed',
             pair='RPT-2',purposes='parse compare structure lineage chunking embedding_eval vectordb',
             notes='원본 온도기록 CSV 및 현장 사진을 PDF 파일 첨부로 포함.')
    register('RPT-3',2,'CAPA-2026-0042_시정예방조치_계획.docx','냉동고 온도 이탈 시정예방조치 계획',
             priority='P1',department='QA',number='CAPA-2026-0042',issued='2026-10-15')
    build_word('RPT-3',[
        [h('문서번호 CAPA-2026-0042',2),p('제1공장 · 담당 부서 품질보증 · 시행 2026-10-15'),
         h('1. 계획 범위'),p('DEV-2026-0117에 기록된 냉동고 D의 온도 이탈에 대하여 설비와 점검 기록을 개선한다.'),
         *detail('deviation',0,5,6), h('2. 검토자 지정'),
         p('현장 절차 확인은 설비팀 박O수가 담당한다. 전체 계획의 승인 책임은 QA 승인 이O희에게 있다.')],
        [h('3. 실행 조치표'),t('표 1. 조치 일정',['조치','책임','기한','상태'],[
             ('도어 패킹 교체','설비팀','2026-10-20','완료'),
             ('일상 점검표 개정','QA 승인','2026-10-23','완료'),
             ('교대 점검 교육','QC 시험담당','2026-10-29','진행 중'),
             ('경보 재발 검토','QA 승인','2026-11-30','예정')]),*detail('deviation',1,2,7)],
        [h('4. 효과 확인'),p('조치 후 효과를 확인하는 기간은 30일이다. 확인 기간에 들어온 경보는 수신 시간과 복귀 여부를 함께 평가한다.'),
         *detail('deviation',8,9,10), p('온도가 정상 범위로 유지되었어도 훈련 기록이 없으면 효과 확인을 연장한다.')],
        [h('5. 참고 문서'),bullet('SOP-EQ-0102 · 냉동고 관리 절차'),
         p('완료 기준에 도달했는지 확인하려면 조치 결과와 일상 점검 이력을 한 묶음으로 평가한다.'),
         *detail('storage',6,7,8)],
    ])
    link('RPT-3','DEV-2026-0117','p.1 §1 계획 범위','linked',['RPT-2','RPT-2P'])
    link('RPT-3','SOP-EQ-0102','p.4 §5 참고 문서','linked',['SOP-C3'])
    build_monthly()


def build_monthly():
    register('RPT-4',2,'월간_품질동향_보고서_2026-10.pdf','10월 월간 품질 동향 보고서',
             priority='P1',department='QA',number='RPT-QA-2026-010',issued='2026-11-12',
             notes='2–6쪽 2단 연속 구역 및 여백 주의 상자. 네 개의 도표와 세 개의 표를 포함한다.')
    trends=[]
    for i,(subject,unit,values) in enumerate([
        ('설비 경보 추이','건',[3,4,3,5]),('시험보류 추이','건',[2,1,2,3]),
        ('교육 완료율','%',[81,86,93,95]),('교정 기한 준수율','%',[94,97,96,98]),
    ],1):
        path=chart(WORK/f'monthly-{i}.png',subject,['7월','8월','9월','10월'],
                   [('월별 실적',values)],limits=(0,6 if unit=='건' else 100),unit=unit)
        trends.append(fig(path,f'그림 {i}. {subject}',5.2))
    pages=[
        [h('편집 번호 RPT-QA-2026-010',2),p('제1공장 · 검토기간 2026-10-01~2026-10-31 · 발행 2026-11-12'),
         h('1. 요약'),p('교정 기한 준수율은 98 %이다. 일탈 건수 검토는 사건 접수 월을 기준으로 집계한다.'),
         *detail('deviation',0,9),t('표 1. 월간 지표',['지표','9월','10월','상태'],[
             ('설비 경보','3건','5건','관찰'),('교정 기한 준수율','96 %','98 %','양호'),
             ('교육 완료율','93 %','95 %','양호')])],
    ]
    titles=['2. 접수 기록','3. 시험 상태','4. 교육 이력','5. 설비 변경','6. 교정 추적']
    for i,title in enumerate(titles):
        theme=['deviation','hplc','calibration','cool','calibration'][i]
        blocks=[col(2)] if i==0 else []
        blocks.extend([h(title),*detail(theme,*range(i,i+4)),
                       p('대상 기간 안에 새로 생성된 기록은 검토 월의 기준에 따라 확정하였다. 이월 항목의 이전 상태와 완료된 기록은 대장 출처와 함께 작성하였다.')])
        if i==1:
            blocks.extend([box('집계 주의 · 같은 설비 경보의 중복 수신은 1건으로 산정한다.'),
                           p('확정된 접수번호만 이번 월의 섹션에서 계수한다.'),
                           note('초기 경보 통보와 결함 접수는 중복 여부를 검토하고 집계한다.')])
        if i==4:
            blocks.append(col(1))
        pages.append(blocks)
    for i,block in enumerate(trends):
        pages.append([h(f'{i+7}. 지표 상세'),block,*detail(['cool','hplc','storage','calibration'][i],2,4,6),
                      *([t('표 2. 시험 보류',['구분','건수'],[['확인 중','3건'],['승인 완료','2건']])] if i==1 else []),
                      *([t('표 3. 다음 달 검토',['항목','담당'],[['경보 반복','설비팀'],['교육 이수','QA 승인']])] if i==3 else [])])
    build_word('RPT-4',pages,pdf=True)


def certificates(assets):
    for fid,filename,lot,number,manufacture,expiry,issued in [
        ('COA-1','COA_FBX-101_Lot-2026A031.pdf','2026A031','COA-FBX101-2026A031','2026-03-31','2028-03-31','2026-10-14'),
        ('COA-3','COA_FBX-101_Lot-2026A032.docx','2026A032','COA-FBX101-2026A032','2026-04-02','2028-04-02','2026-10-14'),
    ]:
        report='COA-3'==fid
        title=f'시험성적서 FBX-101 Lot {lot}'
        register(fid,3,filename,title,department='QC',number=number,issued=issued,
                 priority='P1' if report else 'P0',status='single' if report else 'confirmed',
                 purposes='parse compare structure lineage chunking embedding_eval vectordb',
                 pair=None if report else 'COA-1S')
        results=deepcopy(RESULTS)
        if report:
            results[1]=('pH','전극법','6.0 ± 0.3','6.2','적합')
            results[3]=('순도(SEC)','SEC-HPLC','≥ 95.0 %','94.8 %','부적합')
            results[2]=('단백질 함량','UV','10.0 ± 0.5 mg/mL','10.1 mg/mL','적합')
        build_word(fid,[
            [h('1. 제품 정보'),p(f'제품명 FBX-101 · 로트 {lot} · 문서번호 {number}'),
             p(f'제조일 {manufacture} · 유효기한 {expiry} · 발행일 {issued} · 규격 문서 SPEC-FBX101 Rev.2'),
             *detail('certificate',0,1,2,3),
             h('2. 시험 결과'),
             t('표 1. 시험 결과',['시험 항목','시험법','기준','결과','판정'],results,
               row_pt=29,span=True,widths=[1.61,1.21,1.50,1.43,.97]),
             *detail('certificate',4),
             *([p('순도 항목은 규격 미달이며 조사 완료 전 출하를 보류한다.'),
                note('SEC 순도 94.8 %의 조사 상태는 부적합이다. 승인 없이 재시험 결과를 대체하지 않는다.')] if report else [])],
            [h('3. 원료 정보'),t('표 2. 원료 정보',['원료명','공급처(가상)','로트','입고일','유효기한','시험번호','결과','판정','비고'],
                                  RAW_MATERIAL,widths=[.63,.72,.85,.87,.87,.80,.64,.52,.8]),
             *detail('certificate',5,6,7,8,9),h('4. 판정'),
             p('본 로트는 규격에 부적합하며 출하를 보류한다.' if report else '본 로트는 규격에 적합함을 확인한다.'),
             p('QC 시험담당 김O준 · QA 승인 이O희 · 검토일 2026.10.14'),
             fig(assets['stamp'],None,1.4)],
        ],pdf=not report)
        kv(fid,1,제품명='FBX-101',로트=lot,제조일=manufacture,유효기한=expiry,규격문서='SPEC-FBX101 Rev.2')
        link(fid,'SPEC-FBX101 Rev.2','p.1 §1 제품 정보','missing')
    register('COA-1S',3,'COA_FBX-101_Lot-2026A031_스캔.pdf','시험성적서 FBX-101 Lot 2026A031',
             department='QC',number='COA-FBX101-2026A031',issued='2026-10-14',status='confirmed',
             purposes='ocr compare structure lineage chunking embedding_eval vectordb',pair='COA-1',scanned=[1,2,3],
             notes='COA-1 전 페이지를 스캔화했으며 2쪽에 스캔본 전용 수기 확인을 추가했다.')


def build_edge_words(assets):
    register('EDGE-1',10,'암호설정_공급계약_요약.pdf','공급계약 조건 요약',department='생산',
             purposes='structure parse',encrypted=True,password='fabrikam-test')
    build_word('EDGE-1',[[h('1. 계약 개요'),p('Fabrikam Bio 제2공장 설비용 검품 자재 납품의 내부 검토용이다.'),
                         p('납품 시 확인할 정보에는 자재 식별번호, 포장 단위, 납품 예정일이 포함된다.'),
                         t('표 1. 공급 일정',['공급처','예정일','계약 상태'],[
                             ('벤더 A','2026-11-23','검토 완료'),('벤더 B','2026-11-30','검토 중')]),
                         h('2. 연락 및 접수'),p('계약 담당자 확인 번호 02-000-0000 · 가상시 가상구 1번지.')]],pdf=True)
    register('EDGE-2',10,'확장자불일치_보고서.docx','냉각수 순환설비 정기점검 보고서',
             true_format='pdf',extension_mismatch=True,department='설비',number='RPT-EQ-2026-031',
             status='confirmed',purposes='structure lineage compare',scanned=[4],notes='RPT-1P와 바이트가 동일한 PDF. 이름만 DOCX.')
    blank=register('EDGE-3',10,'빈문서.docx','빈 문서',empty=True,pages=1,purposes='parse structure')
    new_doc('',None,False).save(blank)
    register('EDGE-4',10,'손상된파일_일부잘림.docx','잘린 작업 절차',priority='P1',truncated=True,
             purposes='parse structure',notes='SOP-C1 원본 앞쪽 60 %만 남겨 중앙 디렉터리가 없는 파일.')
    register('EDGE-5',10,'대용량_교육자료_120쪽.pdf','현장 기록과 품질 검토 교육자료',priority='P1',
             department='생산',purposes='parse chunking vectordb embedding_eval')
    modules=[
        ('설비 인계','cool','설비팀'),('시료 보관','storage','생산팀'),('기기 교정','calibration','QC'),
        ('시험 데이터','hplc','QC'),('품질 일탈','deviation','QA'),('원자료 정합성','certificate','QA'),
    ]
    sections=[]
    for i in range(1,121):
        subject,theme,owner=modules[(i-1)//20]
        group=(i-1)%20
        scenario=['시작 전 점검','차이의 확인','검토자 인계','조치 후 확인'][group%4]
        day=3+group
        content=[
            h(f'{i:03d}. {subject} · {scenario}'),
            p(f'교육 실습 기록 TRN-{i:03d}에 따라 {owner}에서 2026년 10월 {day}일의 점검 기록을 검토한다. 실습 기록은 원본 확인, 시각 비교, 검토자의 서명 대조를 포함한다.'),
            *detail(theme,*[(group+n)%10 for n in [0,2,4,6,8]]),
            p(f'수강자는 연습 기록 {i:03d}의 결과를 작성한 후 당일 취합 목록과 대조한다. 시험 값 옆에는 원자료 열과 읽은 시간을 기입하고, 전달 단계에서 추가된 사항은 정정란에 남긴다.'),
        ]
        if i%4==0:
            content.append(t(f'표 {i//4}. {subject} 실습 기록',['구분','원자료 번호','분류','기한'],[
                ('원본 대조',f'TRN-{i:03d}-A','확인','당일'),
                ('범위 확인',f'TRN-{i:03d}-B','검토','다음 교대 전'),
                ('인계 기록',f'TRN-{i:03d}-C','작성','다음 근무일')]))
        sections.append(content)
    build_word('EDGE-5',sections,pdf=True)
    register('EDGE-6',10,'이미지만_있는_문서.pdf','설비 사진 묶음',priority='P1',department='설비',
             purposes='ocr parse chunking',pages=2,scanned=[1,2],notes='사진 두 장만 포함하며 문구 및 텍스트 레이어 없음.')
    register('EDGE-7',10,'0byte.txt','0바이트 파일',priority='P2',purposes='parse structure',empty=True).touch()
    register('EDGE-9',10,'특수문자_파일명 #1 (복사) [최종]…v2.docx','점검 기록 파일명 이관 메모',priority='P2')
    build_word('EDGE-9',[[h('1. 이관 점검'),p('대괄호, 괄호, 숫자 표기와 생략 부호가 포함된 파일명을 이관 목록에 적는다.'),
                          p('문서 개정 상태는 표지의 식별 정보와 배포 기록을 확인한 후 입력한다.')]])
