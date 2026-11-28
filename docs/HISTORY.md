# 작업 이력

지난 경위를 찾아볼 때만 연다. 작업을 시작할 때 읽는 문서가 아니다.

- 현재 동작의 근거는 코드, 테스트, 계약 문서다. 여기 적힌 과거 판단이나 "그대로 둔다"·"보류" 같은 기록을 지금 고치지 않을 이유로 삼지 않는다.
- 결정의 근거·영향·남은 위험은 [결정과 미결 사항](DECISIONS.md)에 있다.
- 기록은 쓴 시점의 스냅샷이다. 테스트 개수, 파일 이름, 화면 명칭은 그 뒤 바뀌었을 수 있다.
- 새 이력은 해당 절 맨 위에 날짜와 함께 더한다. 코드 주석에는 이력을 쓰지 않는다.

## 1. 날짜별 작업 기록

[인수인계와 실행 안내](HANDOFF_AND_RUNBOOK.md) 앞부분에 쌓여 있던 세션별 기록을 2026-11-27에 그대로 옮겼다(최신이 위).

### 2026-11-28 주석 정리 2차(verify·chunking·화면), 이미지 자동 대조 복구, Node 25 테스트 설정

- **요청(사용자):** 주석 정리를 이어서. 커밋 안 된 frontend 변경 때문에 프론트 테스트 33개가 실패하는지 확인하고 원인이면 버린다. AGENTS.md '주석과 이력' 기준으로 `verify.py`·`chunking.py` 주석을 정리하고 지운 경위는 §2에 둔다. 이어서 남은 것(1차 정리의 경위, 청크 위치 계약, Node 25 설정)까지 처리해 main에 올리고 불필요한 원격 브랜치를 지운다.
- **프론트 테스트 33개 실패는 커밋 안 된 변경 탓이 아니다:** 작업 트리의 frontend 변경(22개 파일, 주석을 지우거나 줄이기만 함)을 stash한 HEAD에서도 같은 33개(4개 파일)가 `localStorage.clear is not a function`으로 실패했다. 개발 Mac의 Node.js 25.9.0이 내장 `localStorage`를 전역에 두어 jsdom의 것을 가린다. 그래서 변경은 버리지 않고 이 정리와 함께 커밋했다. `frontend/vite.config.ts`가 테스트 작업자에 `--no-experimental-webstorage`를 넘기게 했다(그 플래그를 아는 Node에서만, Node 20에서는 넘기지 않음).
- **`vectordb.test.tsx` 간헐 실패(11-27 기록에도 있음):** 청크 목록이 먼저 그려지고 첫 청크 선택은 다음 effect에서 붙는데, 테스트가 그 사이에 선택 상태를 읽었다. 선택이 붙을 때까지 기다리게 고쳤다(전체 실행 6회 모두 통과).
- **이미지 자동 대조 복구:** `verify.py` 끝에 `measurements`부터 `image_only`까지가 한 벌 더 있었다. `f7f7ebb`(11-27)에서 새 판을 앞에 넣으면서 `acd7ce8`(11-26)의 옛 판이 남은 것이다. 겹친 함수 10개는 글자까지 같았지만 `image_only`는 옛 모양(`reasons`·`checks`·`contract`·`rule_version`·finding ID 없음)이었고, 파이썬은 뒤 정의를 쓴다. 그래서 PNG·JPG·SVG 같은 이미지 문서는 `ensure_qc`에서 `KeyError: 'reasons'`가 나서 원장을 만들지 못했다. 원문 대조와 `GET …/verify`는 500이었고 깔때기에는 '미평가'로 남았다. 옛 판을 지우고 API 경로 회귀 테스트 `test_qc_ledger.py::test_image_result_goes_through_the_ledger_as_ocr_that_needs_review`를 더했다(고치기 전 코드에서 같은 KeyError로 실패). 실패한 계산은 원장에 저장되지 않았으므로, 업데이트 뒤 조회하거나 시작 시 다시 대조할 때 계산된다.
- **주석 정리:** 기준과 지운 경위는 §2(화면, `verify`·`chunking`, 1차 정리의 다른 모듈). 주석으로만 있던 규칙을 테스트로 고정했다(백엔드 12개, 화면 4개, 화면이 서버 값을 따로 든 곳 2개는 `test_frontend_mirrors.py`). 규칙을 하나씩 깨면 해당 테스트가 실패하는 것을 확인했다. `verify.py`·`chunking.py`는 docstring을 뺀 AST를 정리 전과 비교해 주석만 바뀐 것을 확인했다. 청크 위치 규칙은 [API·데이터 계약](API_AND_DATA_CONTRACT.md) '청크 위치'로 옮겼다.
- **브랜치:** 원격 `ccr-23f5b2fb-ouvb49`(`e66e190`)·`ccr-32aeeb51-ksbsji`(`f5c64e3`)·`ccr-5167992f-whgl0f`(`acd7ce8`)·`ccr-e549082e-ta1etq`(`c18138c`)는 모두 main에 이미 들어간 커밋을 가리켜(main보다 앞선 커밋 0개) 지웠다. 괄호 안은 지울 때의 끝 커밋이다.
- **검증:** 백엔드 `pytest` 372개 통과(새 13개). 프론트 `npm test` 189개 통과(새 4개, 플래그 없이)·빌드.
- **고객사 PC 반영:** 이미지 문서가 있으면 업데이트 뒤 원문 대조가 열린다. DB 변경은 없다.

### 2026-11-27 (오후) 반입 리뷰 8건 반영

- **리뷰(다른 에이전트, `f7f7ebb`·`9ec49da`를 따로 꺼내 합성 문서로 재현):** 1차 반입 보류. 필수 수정 1~3번과 추가 5건. 원칙은 '사람이 볼 수 없는 차이·확인하지 않은 범위는 해결로 세지 않는다'로 묶었다. 결정 기록: [결정](DECISIONS.md) '반입 리뷰 8건 반영'. 계약: [API·데이터 계약](API_AND_DATA_CONTRACT.md) §11 '리뷰 반영'.
- **고친 것(재현 → 수정 → 회귀 테스트):**
  1. 청크의 판정 보존: 화면 17 bar / 숨은 층 71 bar PDF에서 '틀림'·'보류'를 누르면 청크 경고가 사라졌다(청크 연결이 판정한 지점을 모두 뺐다). → '틀림'은 `confirmed-wrong`, 보류·확인 전은 `unverified`, V번호·메모·'판정·원문 위치' 링크. '맞음'만 해결. (`test_pdf_hidden_layer.py`, `qc-ledger.test.tsx`)
  2. 업그레이드 후 다시 대조: 첫 커밋 코드로 만든 DB를 그대로 재현(worktree)해 현재 코드로 열면 같은 규칙 이름이라 의심점 0이었다. → 규칙 키 = 이름 + 대조 코드·라이브러리 지문, 서버 시작 때 최신 성공 실행을 백그라운드에서 다시 대조(`DOCOPS_QC_REVERIFY`). 재현 DB에서 재업로드 없이 고위험 1건(71)이 나오고 이전 '틀림'·메모·근거와 이전 원장 행이 남는 것을 확인. (`test_qc_upgrade.py`)
  3. CSV 구분자 오판: `|` 3열의 짧은 행 → '확정 아님'(판정 불가), 구분자 지정 후에는 빠진 칸이 드러나 `ragged`. 1열 CSV 대조군은 통과 후보 유지.
  4. 201번째 차이: 단위별 상세 상한(CSV 200행 등)이 차이를 원장에서 뺐다. → 상한 제거, 전체 2만 곳 밖은 '상세 없음'으로 미해결. 칸마다 의심점(한 행의 공백 차이만 보고 같은 행의 수치 오류까지 '맞음' 처리되는 것을 막음). 200곳 '맞음' 뒤에도 압력 오류 1곳이 남아 검수 필요.
  5. 숨은 층 ↔ 그림 OCR: 숫자 모음 비교 → 같은 그림(상자 겹침)의 OCR과 **항목·값·단위** 한 벌 비교. A·B 맞바꿈·bar→kPa는 충돌, 항목 대응 불가는 미확인. 한 쪽의 그림 둘은 상자로 짝짓는다.
  6. 차트: (범주, 값) 한 쌍·점 개수·캐시에만 있는 점, 2,000점 초과는 부분 검증(2,000/2,001).
  7. 재처리 실패: 목록 '이전 성공본 · 통과 후보'(점선), 집계의 현재 수에서 빼고 `previous_results`로.
  8. EML: 모든 MIME 부분에서 그림·첨부를 센다(표시하지 않은 HTML 대체 본문의 그림 포함), 위치를 표·경고에.
- **검증:** 백엔드 358개, 프론트 183개 통과·빌드(마무리 점검 뒤 359·185). 계획서 CSV 216종 그대로(오류 180/180, 정상 오경보 0), 말뭉치 EML 3건 의심점 0.
- **확인하지 않은 것:** 고객사 Windows에서 시작 시 다시 대조에 걸리는 시간(문서 수만큼 원본을 다시 읽음), 실제 OCR 모델 출력의 항목 이름 표기(낱말 규칙이라 표·여러 줄 라벨은 미확인으로 남기 쉬움), Excel이 저장한 실제 날짜 범주 차트.
- **고객사 PC 반영:** 앞 항목과 같다. 처음 시작할 때 기존 문서를 다시 대조하므로 문서가 많으면 깔때기의 '규칙 변경 · 다시 대조 n/N'이 끝날 때까지 기다린다(그 사이 원문 대조를 열면 그 문서는 바로 계산).
- **마무리 점검(같은 날 저녁):** 독립 리뷰 에이전트 둘은 사용량 한도로 결과 없이 멈춰, 같은 기준(사람이 보지 않은 차이가 통과로 새지 않는가, 판정이 사라지거나 다른 사실에 붙지 않는가)으로 직접 다시 읽었다. 고친 것(각각 고치기 전 코드에서 실패하는 테스트로 고정):
  1. 목록·집계의 해결 수가 검수 요청을 만든 때의 규칙 키로 걸러져, 코드만 바뀌어도 '맞음'으로 해결한 지점이 목록에서 다시 미해결로 보였다(상세 gate와 불일치). → 지금 원장에 있는 finding ID를 가리키는 '맞음'·'틀림'으로 센다. (`test_qc_upgrade.py`)
  2. 원문 대조 '확인할 곳'에서 받은 지점 일부를 판정한 뒤 '더 보기'를 누르면, 서버 목록이 그만큼 당겨져 다음 쪽 앞 지점을 건너뛰었다(사람이 못 보는 지점). → 받을 자리를 판정한 수만큼 당긴다. (`qc-ledger.test.tsx`)
  3. 문서함에서 처리 중 다시 읽기와 '더 보기'가 겹치면 이어 받은 행이 사라지거나 응답이 버려졌다. → 조건이 바뀔 때만 버리고, 다시 읽은 범위 밖의 이어 받은 행과 다음 쪽 위치를 남긴다. (`qc-ledger.test.tsx`)
  4. 상한을 없앤 뒤 한 쪽이 통째로 빠지면 지점을 하나씩 지워 제곱 시간이 걸렸다(3만 줄 쪽 → 한 번에 빼서 0.4초). 판정한 지점 빼기는 ID 목록 대신 하위 질의로.
  - 표시: 목록 배지에 '틀림 N'(미해결이 0이어도 검수 필요인 까닭), 청크의 숨은 층 지점은 "숨은 글자 층 '71' (화면 값 미확인)"(원본→결과가 같은 값이라 '일치'로 읽히지 않게).
  - 실제 서버(임시 저장소)·Chromium으로 다시 확인: 청크 '틀림 확인 · V1'과 링크, 재처리 실패 '이전 성공본', `|` CSV 원천 형식 지정 → 빠진 칸 사유, EML 그림 위치, 코드가 바뀐 뒤 다시 시작하면 4건 다시 대조하고 판정 유지, 390px 넘침 0, 콘솔 오류 0. 말뭉치 56건: 파싱 35·대조 35, 검수 필요 1(스캔 쪽)·판정 불가 33·통과 후보 1. 테스트: 백엔드 359, 프론트 185.

### 2026-11-27 파서 품질 검수 고도화: 검수 전달 원장, CSV 기록 모드, 문서함 서버 목록, 숨은 글자 층·차트 캐시

- **요청(사용자):** '파서 품질 검수 고도화 계획'(개정 2, 2026-11-27, 저장소 밖 `Samsung_Biologics /파서_품질검수_고도화_계획.md`)을 기반으로 고도화. "100% 신뢰할 필요는 없지만 굉장히 신뢰도 높은 자료". 계획의 반입 권고 범위(1 검수 전달·2 CSV 기록 모드·병행 UI)를 끝내고 3·4의 핵심과 5의 EML을 더했다. 결정 기록: [결정](DECISIONS.md) '파서 품질 검수 고도화'.
- **계획의 문제를 코드로 재현한 뒤 고쳤다:**
  - 상세 400곳 절단: 12시트 441지점(고위험 1곳이 문서 끝)에서 예전에는 S441이 상세에 없고 검수 요청 POST가 409. → 자동 대조 **원장**(`qc_runs`·`qc_findings`)을 성공 실행과 같은 트랜잭션에서 '미평가'로 등록하고 같은 작업자가 이어 계산. 의심점은 **우선순위 순** 쪽 단위(`severity`·`unit`·`kind`·`offset`·`unreviewed`), S번호·**finding ID** 단건 조회(`…/verify/spots/{ref}`), 검수 요청은 원장 전체에서 찾고 finding ID로 하나만. 규칙 버전(`verify-2026.11.27`)이 바뀌어도 V는 스냅샷 그대로. 작업 도구 `verify`(20곳씩, `severity`·`offset`)·`flag`도 같은 원장.
  - 판정 상태(gate): 검수 필요 → 판정 불가 → 통과 후보. **통과 후보도 기록 모드**(자동 통과 없음). 막는 이유·검사 항목(`checks`, 근거의 계통 `source_layer`·`derived_from`)을 같이 준다. `GET /api/live/qc-summary` 깔때기.
  - CSV: 원본에서만 출발하던 대조가 같은 행 두 칸 맞바꿈·빈 칸에 생긴 값·결과에만 있는 행·중복 행을 통과시켰다. → 실행 `evidence`(인코딩 근거·구분자 후보·원래 열 수)와 **주소별 양방향 대조**. 계획서의 216종을 같은 방식으로 돌려 오류 180/180 검출·정상 36건 오경보 0(현행 방식은 108/180이었다고 계획서에 기록). 구분자 모호(`id;val,unit`)·CP949 추정·짧은 행은 판정 불가. 원천 형식(구분자·인코딩)은 `POST …/process` 바디나 문서 상세 '원천 형식 지정'으로 다시 파싱.
  - PDF 숨은 글자 층: 픽셀은 '17 bar', 숨은 층은 '71 bar'인 PDF가 coverage 1.0·의심점 0이었다(렌더 해시가 같은 두 파일로 재현). → `app/pdf_layers.py`가 렌더 모드 3 + 그림 겹침을 찾아 `hidden_layer`(화면 값 미확인, 높음)로 올리고 그림 OCR이 있으면 다른 값을 `hidden_conflict`로. 숨은 층은 지우지 않는다. 회전 쪽도 같다. 경고 `그림 위의 보이지 않는 글자 층에서 읽은 PDF 쪽: …`(작업 도구 코드 `hidden-layer`).
  - 차트: `xl/charts`의 `numCache`(71)와 셀(17) 충돌을 모델 없이 `chart_conflict`로, 캐시 없음은 판정 불가(`chart_no_cache`).
  - 청크: 청킹 비교의 실제 문서 청크에 실행 ID·본문 해시·덮는 쪽/시트·겹치는 미판정 의심점과 '확인 안 된 지점' 표시(막지 않음). '71 bar' 청크에서 원문 대조 그 지점으로 간다.
  - OCR 정규화: `m<sup>2</sup>`→`m²`, `10<sup>-3</sup>`→`10⁻³`, `CO<sub>2</sub>`→`CO₂`, `10<sup>th</sup>`→`10th`, 그 밖(각주 `<sup>a</sup>`)은 태그를 남긴다.
  - 문서함: 서버 쪽 검색·상태·**확장자**·정렬·커서·확장자/상태별 수, 50개씩 더 보기, 쪽 밖 작업 완료 알림(`ids=`), 뒤로 가기 복원, 행마다 판정 상태, 처리 깔때기. 조건 없는 `GET`은 예전처럼 전체(파서 화면·에이전트·구조 분석).
  - 제목: 읽기 보기와 원문 대조가 같은 CommonMark 해석(`# C#`→'C#', 들여쓴 제목, 코드 블록·`#LOT-7`·`\#`은 제목 아님). 원문 대조는 `#`을 다시 그리지 않고 작은 `H2`.
  - PDFium: PDF 파싱과 원본 읽기를 한 잠금(`app/pdf_layers.PDFIUM`)으로 직렬화.
  - EML(§4.4 첫 구현): `python-eml` 파서(헤더 표·plain 우선 본문·HTML 표→Markdown·첨부 목록·첨부 메일 위치), 첨부 본문은 읽지 않음. 본문 없는 메일은 정상. 구조 분석만 되는 형식은 미지원 사유에 '구조 분석 가능, 보호 여부 미확인'.
- **검증:** 백엔드 `pytest` 338개 통과(새 `test_qc_ledger.py`·`test_document_page.py`·`test_pdf_hidden_layer.py`·`test_xlsx_charts.py`·`test_eml.py`, OCR 첨자 1개). 프론트 182개 통과(새 `qc-ledger.test.tsx`, 기존 목록 테스트는 쿼리 붙은 주소를 받게 고침)·빌드. 전체 실행 한 번에서 `vectordb.test.tsx` 1개가 시간 때문에 실패했고 단독 3회·전체 재실행에서 통과했다(이번 변경과 무관한 모듈). 합성 말뭉치 56건을 임시 저장소 API로(PDF 모델 미연결 조건, 외부 호출 0): 파싱 완료 35(예전 32, EML 3건 추가), 대조 35, 검수 필요 2·판정 불가 32·통과 후보 1(UTF-8 CSV). 실제 서버를 띄워 합성 파일 6개(숨은 층 PDF·차트 충돌 XLSX·모호 CSV·UTF-8 CSV·CP949 CSV·EML)로 Chrome 화면 확인: 문서함 깔때기·확장자 거르기·행 판정, 문서 상세 자동 대조 칸·원천 형식 지정, 원문 대조의 판정 팝오버(Esc로 닫힘)·차트 충돌 카드가 원본 셀로 이동, 청크 상세의 확인 안 된 지점 링크. 390px에서 가로 넘침 0, 콘솔 오류 0. 화면 확인 중 같은 쪽의 보이는 바닥글 지점까지 '숨은 글자 층'으로 표시하던 것과 차트 계열 이름이 셀 참조로 보이던 것을 고쳤다.
- **확인하지 않은 것:** 고객사 Windows PC·실제 고객 문서의 오통과율·검수 시간·속도, 1,001시트 실제 통합문서의 원장 크기, Excel이 저장한 실제 차트(여러 영역·이름 정의), 흰 글자·클리핑·덮어쓰기 같은 다른 숨김, OCR 모델을 붙인 숨은 층 대조(가짜 OCR 서버로만), 사내 모델이 새 `verify` 인자를 쓰는지, 실제 MSG·TAR.
- **고객사 PC 반영:** 콘솔을 닫고 ZIP을 덮어쓴 뒤 `setup.cmd` → `run.cmd`. DB에는 `qc_runs`·`qc_findings` 테이블과 `parse_runs.evidence`·`options`, `review_requests.finding_id`·`rule_version` 열만 더해진다(기존 데이터 유지). 예전 실행은 원문 대조를 열 때 원장을 계산하고, 예전 CSV 실행은 근거가 없어 '판정 불가: 다시 파싱하면 기록'으로 보인다. 브라우저는 한 번 `Ctrl+F5`.
- **다음 후보:** 첫 방문 보정(무작위 20~30건 + 알려진 실패, 중요 오류 정의를 고객 검수자와), 숨은 층 영역만 골라 OCR 모델로 다시 읽기, 표 헤더 계보·병합 범위, XLSX 시트·셀 주소를 청크 위치로, OCR 캐시 영속화와 PDF 변환 프로세스 격리(Windows 측정 후), BOM 없는 UTF-16, ZIP 목록 모드.

### 2026-11-26 고객사 OpenCode 후기 반영: 에이전트를 검수 보조로, 원문 대조 화면 넓히기

- **사용자 피드백(고객사에서 OpenCode로 실제 시험):** ① 원문 대조의 가로·세로 폭이 너무 작다. 여백을 다 쓰고, 사이드바는 접어 두되 마우스를 올리면 잠시 펼쳐졌다가 벗어나면 접히면 좋겠다. ② 에이전트가 파싱한 문서와 그 원문 대조를 어디서 보는지 헷갈린다(묶음 안에만 있음). ③ 보고서는 유의미한 데이터가 아니다. ④ 호출 기록은 좋지만 담긴 것이 적다. ⑤ 도구가 파싱·청킹만 대신하면 쓸 이유가 없다. 사람은 수천 개 파일의 정답 텍스트를 만들 수 없으니 에이전트가 원본과 대조해 사람이 눈으로 볼 곳을 짚어 줘야 하는데, 원본을 못 보고(`docops_read`는 결과만, OpenCode 파일 읽기는 꺼 둠) 반복 호출 안내·3,500자 한도에 막혔다. Claude가 파일을 직접 볼 수 없어서 만든 대리인이다. 결정 기록: [결정](DECISIONS.md) '작업 에이전트는 검수 보조'.
- **원인(코드로 확인):** 원문 대조는 `.lw-workspace`의 최대 폭 1260px과 본문 1510px, 결과 칸 `max-height: 65dvh`·PDF `68dvh`에 묶여 있었다. 접힌 사이드바는 68px. 작업 도구에는 원본을 읽는 도구가 없고 `READ_LIMIT = 3500`, OpenCode 안내에 "같은 도구를 같은 인자로 두 번 넘게 부르지 않습니다", 반복이면 결과 앞에 "방금과 같은 요청입니다"를 붙였다. 보고서는 사람이 옮겨 칠 ASCII 코드 블록이었다. 호출 기록은 결과 첫 줄 120자만 남겼다.
- **바꾼 것(백엔드):**
  - `app/source_text.py`: 원본 글자를 파서와 별개로 읽음(PDF 쪽별 글자 층, DOCX 문단·표 행·글상자·머리말·각주 — `fidelity/probe.py`의 기호 글꼴·첨자·숨김 처리를 상속, PPTX 슬라이드별 도형·표·메모, XLSX·XLSM 셀 값과 주소·표기 후보, 텍스트·CSV). `app/verify.py`: 결과의 원문 위치로 같은 단위끼리 대조해 의심 지점(S번호: 바뀜·빠짐·기호·결과에만 있는 숫자·깨진 글자·표 칸·쪽 대부분 없음·글자 층 없는 쪽·그림 OCR 줄)을 고름. 쪽 위·아래 끝에 되풀이되는 줄과 숨긴 시트·슬라이드는 의심 지점에서 뺌.
  - 검수 요청(V번호): `review_requests` 테이블(시작 때 자동), `GET/POST /api/live/reviews`, `PATCH /api/live/reviews/{n}`. S번호로 만들면 서버가 위치·글자를 채우고 같은 실행·같은 S번호는 하나만.
  - API: `GET /api/live/documents/{id}/source-text`(단위 목록·`unit`·`find`), `GET /api/live/documents/{id}/verify?run=`. 활동 API에 `documents`(에이전트가 다룬 문서·검수 요청 수)·호출 `text`·`docs`·`session`, `reports` 뺌. [API·데이터 계약](API_AND_DATA_CONTRACT.md).
  - 작업 도구 13개: `source`·`verify`·`flag`·`verdicts` 추가, `report` 삭제, `read`에 결과 줄 번호·`line` 이어 읽기, 한 번 읽기 12,000자(`DOCOPS_AGENT_READ_CHARS`), 반복 경고 문구 삭제(기록만), 묶음 요약은 읽는 문장과 D번호 목록, `doc`·`verify`·`flag`는 원문 대조 링크. 코드표에 `pic-skip`·`text-only`·`text-broken`·`notes-added`·`title-row` 추가(이전 세션의 경고가 `other`로, 큰 그림 경고가 `ocr-limit`로 잘못 묶이던 것). OpenCode 안내 `opencode-workspace/AGENTS.md`를 검수 흐름으로 다시 씀. [작업 에이전트 도구](AGENT_TOOLS.md).
- **바꾼 것(화면):** 원문 대조가 화면 폭·높이를 다 씀(머리 한 줄, 두 칸 각각 스크롤, 폭 조절 손잡이 25~75%·키보드, 빈 결과 줄 얇게). 위에 **확인할 곳** 막대(V·S, 이전·다음·목록, 맞음·틀림·보류·메모, 다른 실행이면 '그 실행으로 보기'). 주소에 `page`·`sheet`·`cell`·`line`·`check`·`run`. 사이드바: 접으면 52px, 마우스(120ms)·키보드 초점으로 겹쳐 펼치고 벗어나면 접힘, '펼친 채 고정', 접힘 기억. 에이전트 작업: 검수 요청(원문 대조로 바로, 빠른 판정, 틀림 정리 복사) · 문서(다룬 문서와 원문 대조) · 묶음 · 호출 기록(연결별, 결과 전체 펼침, D번호가 원문 대조 위치로) 탭. 보고서 탭 삭제. [프론트·화면 계약](FRONTEND_AND_INTERACTION_CONTRACT.md).
- **검증:** 백엔드 테스트 313개 통과·2개 건너뜀(새 `test_verify.py` 13개, `test_agent_tools.py` 재작성·추가). 이 환경에 Docling Office 경로(`docling-slim[format-office]` 2.150.0, 토치 없음)를 깔아 합성 말뭉치 56개를 실제로 파싱하고 자동 대조: 정상 파싱 문서 30건에서 의심 지점은 실제 스캔 쪽 1곳뿐(오탐 0). 결과에 무작위 변조를 넣는 시험(시드 3개, 문서당 9회)에서 숫자 한 자리 88~91%, 줄 삭제 79~81%, 특수기호 100%를 ±4줄 안에서 잡음(놓친 것은 대부분 쪽마다 되풀이되는 머리말과 같은 문장 반복). 임시 저장소 서버에서 CLI `status → parse → verify → source → read → flag(중복 포함) → verdicts`를 돌렸다. 프론트 테스트 178개 통과(새 `review-desk.test.tsx` 5개, `agent-activity.test.tsx` 재작성 11개)·빌드. Chromium으로 1440×900(사이드바 펼침·접힘·엿보기)과 390×844를 찍어 원문 대조가 폭 1360×높이 570으로 채우고 페이지가 넘치지 않으며, 휴대폰 폭 가로 넘침 0, 콘솔 오류 0을 확인했다.
- **확인하지 않은 것:** 고객사 Windows PC와 사내 모델로 새 도구 호출(도구 13개를 잘 고르는지), 실제 고객 문서의 자동 대조 오탐·놓침, Docling PDF 모델 경로의 대조(이 환경은 `pdf-text`), OCR 모델을 붙인 스캔 쪽, 고객사 Edge에서의 엿보기·폭 조절.
- **고객사 PC 반영:** 콘솔을 닫고 ZIP을 덮어쓴 뒤 `setup.cmd` → `run.cmd`. setup이 OpenCode 작업 폴더의 AGENTS.md를 새 흐름으로 바꾼다(직접 쓴 AGENTS.md는 보존하고 DOCOPS_GUIDE.md를 둠). DB에는 검수 요청 테이블만 더해진다. 브라우저는 한 번 `Ctrl+F5`. 현장 시험 문장은 [작업 에이전트 도구](AGENT_TOOLS.md) §3.
- **다음 후보:** 실제 고객 문서 몇 건으로 자동 대조 오탐을 보고 기준을 다듬기. 표 구조(칸 합치기·머리글)와 읽는 순서 대조. 사내 모델이 그림을 받으면 스캔 쪽·그림 원본을 모델에 보여 1차 대조. 틀림으로 확인된 유형을 모아 파서 개선 목록으로.

### 2026-11-25 OpenCode 고객사 시험 인계

고객사에서는 콘솔 설치와 스크립트 파서 실행을 확인했다. Qwen 로컬 모델 실험은 개발용 Mac에서 수행했다. 사내 모델과 고객사 OpenCode의 조합은 아직 확인 대상이다. 배포본의 합성 문서로 stdio → 콘솔 → 모델 실제 호출 → 파싱 근거 조회 → 청킹 비교 순서로 재현할 수 있다. 모델 ID는 현장 설정에서 고른다. 장애가 발생한 단계와 B번호·D번호를 기록한다. [Windows 명령과 합격 기준](AGENT_TOOLS.md#3-고객사-pc-설치)



### 2026-11-25 (밤) 파서 개선: 모델 없는 PDF, 시트 제목·병합 제목 행, 슬라이드 위치·발표자 메모, 각주

- **요청(사용자):** 앞 작업을 main에 푸시하고, 보이는 파서 개선점을 먼저 고쳐 main까지 푸시. 앞 작업은 main을 앞으로 감기만 해서 올렸다(`f5c64e3..a3c9f54`).
- **찾은 문제(실험으로 확인):**
  - PDF 모델 보류로 고객사 PC에서 PDF가 전부 `parser_unavailable`이었다.
  - XLSX 결과에 시트 이름이 없다(시트 둘이 이름 없는 표 둘). 표 전체 너비로 병합된 제목 행이 칸마다 반복됐다(말뭉치 `교정일정_2026.xlsx`: 제목이 26칸에 26번).
  - PPTX: Docling이 슬라이드 번호(prov)를 갖고 있지만 위치로 쓰지 않았고, 발표자 메모는 본문이 아닌 층에 두어 Markdown에서 빠졌다.
  - DOCX 각주·미주가 결과에서 빠졌다(변경 내용 추적은 Docling이 맞게 처리: 삭제 제외·삽입 반영).
  - 번호 목록 바로 뒤의 표가 빈 줄 없이 붙었다.
- **바꾼 것:**
  - `app/adapters/pdf_text.py` + 레지스트리: 모델이 없으면 PDF → `pdf-text`. `/api/live/parsers`의 `routes`는 지금 경로(`ParserRegistry.routes()`). setup 요약·run 시작 화면·작업 도구 점검 문구를 '글자 층만 읽음'으로.
  - `app/adapters/markdown_edit.py`(줄 끼우기·위치 밀기, 표 앞 빈 줄, 맨 위 병합 제목 행 옮기기), `docling_locations.markdown_parts`·`sheet_of`, `app/adapters/pptx_notes.py`, `DoclingAdapter._structure`.
  - 원문 대조: PPTX 위치를 `슬라이드 N`으로 부르고 누르면 원본 칸이 그 슬라이드로 이동·강조. 근거 버튼은 묶음 첫 줄에만, 표 줄은 오른쪽 아이콘. 파서 플로우에 `PDF 글자 층` 경로.
  - 원문 대조 probe: 각주·미주(`footnote` 종류, `각주 N`) 보충.
- **검증:** 백엔드 289개 통과·2개 건너뜀(새 `test_parser_structure.py` 14개). 프론트 166개 통과·빌드. 합성 말뭉치 56개 전체를 새 코드로 처리해 예외 없음(디지털 PDF 7건 `pdf-text` 완료, 실패는 OCR 미연결 이미지·스캔·빈 파일·손상·암호·확장자 불일치로 모두 의도한 사유). 실제 서버에서 PPTX 슬라이드 이동, XLSX 시트·병합 제목 행, PDF 원문 대조를 Chromium으로 확인했다(콘솔 오류 0. 헤드리스 Chromium은 PDF 미리보기를 그리지 않음).
- **확인하지 않은 것:** 실제 고객 PDF·XLSX·PPTX, 회전 쪽의 큰 그림, OCR 모델을 붙인 `pdf-text`(가짜 OCR 서버로만 확인).
- **다음 후보:** 표 중간의 병합 셀 반복(구간 머리글)은 그대로 둠. 확장자 불일치 파일(예: 이름만 .docx인 PDF)을 실제 형식으로 파싱할지는 기존 결정(억지로 성공시키지 않음)과 함께 정할 일.

### 2026-11-25 (저녁) 추출 결과 읽기 보기, 원문 대조의 DOCX·PPTX 원본, PDF 모델 보류

- **사용자 피드백:** ① 추출 결과 화면이 아쉽다(들여쓰기 등이 맞는지). ② 원문 대조가 '전용 앱에서 원본을 확인하세요'만 보이면 화면의 의미가 없다. ③ 모델은 보류(고객사 PC: i5 10세대 · RAM 16GB).
- **①에 대한 확인:** Docling 결과 자체는 맞다. 합성 DOCX로 제목 단계, 중첩 목록(4칸 들여쓰기), 번호 목록, 표 행·열이 정확히 나오는 것을 확인했다. 어긋나 보인 원인은 표시였다. 결과를 `<pre>`에 가변폭 글꼴로 찍었고, Docling은 표 칸 너비를 글자 수로 맞춰 한글(화면 2칸 폭)이 섞이면 세로선이 어긋난다. 실제 한계는 두 가지다. 병합 셀 값이 칸마다 반복되고(기존 원문 대조 경고), 번호 목록 바로 뒤에 표가 빈 줄 없이 붙는다(일반 Markdown 렌더러는 표를 목록에 붙여 버릴 수 있음. 읽기 보기는 표로 나눈다).
- **바꾼 것(프론트만):**
  - `markdown.ts`(블록·글자 꾸밈 해석, 표 줄 지도, 화면 폭 글자 수), `MarkdownView.tsx`·`markdownView.css`(읽기 보기). 문서 상세 추출 결과에 `읽기 보기 / Markdown 원문` 전환(`ResultBody`, 선택은 브라우저에 기억). 원문 대조 추출 결과 칸도 같은 선택으로 표 줄을 칸으로 그린다(줄 번호·원문 위치 유지).
  - 원문 대조 원본 칸: `compare/OfficeSource.tsx`(DOCX: `docx-preview`, altChunk 끔, 링크 정리, 칸 폭 맞춤 / PPTX: 슬라이드 목록·숨김·메모), `compare/pptx.ts`(PPTX 모델: 자리표시자 상속, 테마 색·글꼴, 그룹, 표 병합, 그림 자르기, 차트 제목·SmartArt 글자, 배경, 마스터 장식). SVG는 `<img>`로. 라벨 `DOCX · 브라우저 재현`과 한계 안내 한 줄.
  - 의존성: `docx-preview` 0.4.1, `jszip` 3.10.1(정확한 버전, `package-lock.json`). 원문 대조에서만 불러오는 별도 묶음(OfficeSource ≈ 37 KB gzip, docx-preview ≈ 21 KB gzip)이라 첫 화면 크기는 그대로다.
  - 서버·API 변경 없음. 원본 파일은 기존 `GET /api/live/documents/{id}/source`로 받는다.
- **PDF 모델:** 사용자 결정으로 보류([결정](DECISIONS.md) 'PDF 모델 설치 보류'). `setup --models`는 그대로 두고 쓰지 않는다. 고객사 PC에서 PDF는 `parser_unavailable`로 남는다.
- **검증:** 프론트 테스트 165개 통과(새 `markdown-view.test.tsx` 9개, `office-source.test.tsx` 6개: 마스터·레이아웃 상속, 테마 밝기(강조 1 50% 어둡게 = `#254061`), 그룹 좌표, 표 병합, 그림 자르기·EMF, 차트 제목, 숨김·메모, PowerPoint 아닌 파일, DOCX 본문·`javascript:` 링크 제거·iframe 없음), 빌드 정상. 백엔드 변경 없음. 실제 서버에 합성 DOCX(제목·중첩 목록·병합 표)와 python-pptx로 만든 PPTX(제목·글머리표·표·차트·그림·글상자·메모)를 올려 Docling으로 파싱하고, Chromium으로 상세(1440px·390px, 가로 넘침 0)·원문 대조·크게 보기를 찍어 확인했다(콘솔 오류 0).
- **확인하지 않은 것:** 실제 고객 DOCX·PPTX의 재현 품질, 고객사 Edge 버전, 큰 파일(수백 쪽 DOCX·수백 장 PPTX)의 그리기 시간.
- **다음:** 고객사 문서 몇 건으로 원문 대조 화면을 보고, 자주 어긋나는 요소(글꼴·도형·표 스타일)를 모은다. 고객사 PDF 처리 위치를 정한다.

### 2026-11-25 huggingface.co 차단 대응(PDF 모델 ZIP)과 XLSM 파서

- **사용자 보고:** 고객사 PC에서 `huggingface.co` 접속이 막혀 있다(PDF 모델을 받지 못함). XLSM 파서도 필요하다.
- **재현:** 이 저장소의 클라우드 개발 환경도 `huggingface.co`가 막혀 있다(프록시 403). 전체 모드 `./setup.sh`가 `docling-tools`의 긴 오류 추적(`httpx.ProxyError: 403`)을 쏟은 뒤 요약에 `[주의] PDF 모델: 받지 못했습니다`를 남기는 것을 확인했다. 받기에 실패하면 빈 `~/.cache/docling/models` 폴더가 남는다.
- **PDF 모델(바꾼 것):**
  - `check_local.py`: 받기 전에 `huggingface.co`(또는 `HF_ENDPOINT`)의 레이아웃 모델 정보를 10초 제한으로 조회한다. 막혀 있으면 `docling-tools`를 부르지 않고 원인(`프록시가 연결을 막았습니다(403)`, `프록시 인증이 필요합니다(407)`, 시간 초과, 인증서 실패)을 한 줄로 알린다. 이 환경에서 setup 재실행은 5초에 끝난다. `HF_ENDPOINT`가 빈 값이면 하위 프로세스에 넘기지 않는다.
  - `app/model_bundle.py`(표준 라이브러리): `pack`은 레이아웃·표 모델 폴더와 `manifest.json`(파일별 크기·SHA-256)을 ZIP으로 묶는다. `install`은 ZIP·폴더를 받아 경로 안전성·필수 파일·크기를 쓰기 전에 확인하고, 임시 파일에 쓰며 SHA-256을 대조한 뒤 바꿔 넣는다. 같은 파일은 건너뛰고 빈 파일만 바꿔 쓰며, 내용이 다른 기존 파일이 있으면 아무것도 쓰지 않고 멈춘다. manifest 없이 손으로 압축한 모델 캐시도 받는다(크기만 확인).
  - `scripts/prepare-offline.py --models-only` → `offline/docling-pdf-models.zip`. `setup --models <ZIP|폴더>`(`scripts/console.py`) → `check_local.py --models-from`. 설치 위치는 콘솔이 모델을 찾는 폴더(`DOCOPS_DOCLING_ARTIFACTS` → `offline/docling-models` → `~/.cache/docling/models`). 묶음 설치가 실패해도 이미 모델이 갖춰져 있으면 요약에 '안 됨'으로 올리지 않는다.
  - 안내 문구: setup 요약·run 시작 화면·PDF 파서 오류·작업 도구 점검·파서 플로우 설치 안내를 모델 ZIP 경로로 바꿨다. `.env.example`에 `DOCOPS_DOCLING_ARTIFACTS`와 주석 처리한 `HF_ENDPOINT`를 넣었다. README에 'huggingface.co가 막힌 PC' 절.
  - 테스트 `test_parser_resilience.py`의 PDF 실측 2건은 모델 폴더가 비어 있어도 건너뛰게 고쳤다(전에는 빈 폴더면 실패).
- **XLSM(바꾼 것):**
  - 라우팅(`registry.DOCLING_FORMATS`), Docling 워크시트 경로(`InputFormat.XLSX`로 변환, 시트 수 한도, 시트·행 위치), 원본 셀 미리보기, OOXML 사본 보정·원문 대조(`OOXML_FORMATS`)에 XLSM을 넣었다. Docling 2.150.0은 `xl/workbook.xml`로 형식을 판별하고 `.xlsm` 확장자도 받는다(실측).
  - `app/vba.py`: `vbaProject.bin`(CFB)의 `VBA/dir`을 [MS-OVBA] 압축 해제로 읽어 모듈 이름·종류·소스·코드 줄 수(`Attribute VB_`·`Option` 줄 제외)·자동 실행 프로시저를 얻는다. 크기 상한(프로젝트 32 MiB, 모듈 소스 4 MiB, 모듈 500개). 매크로는 실행하지 않는다. 압축 해제는 명세 3.2.1·3.2.2 예제로 확인했다.
  - 결과 `warnings`에 `매크로 포함: VBA 모듈 N개(코드 M줄)는 실행하지 않았고 결과 본문에 넣지 않았습니다. 셀 값은 파일에 마지막으로 저장된 값입니다.`(+ 자동 실행 이름). 빈 문서 모듈만 있으면 경고 없음. 코드는 본문에 넣지 않는다.
  - 구조 분석: `stats.macro`(모듈 목록), 플래그 `macro-autorun`, 매크로 코드 속 UNC·파일 경로·URL·문서번호 후보(`매크로 <모듈> N행`). 화면은 `매크로 모듈 N · M줄`·`열 때 자동 실행 매크로`로 보인다.
  - 화면: 파서 플로우 XLSM 설명, 원문 대조의 XLSM 셀 값 미리보기, 지원 형식 안내 문구.
- **검증:** 백엔드 `pytest` 276개 통과, 2개 건너뜀(PDF 모델 없음). 새 `test_xlsm.py` 17개(명세 예제·잘못된 압축·출력 상한, 한글 모듈 이름 cp949, 소스 없는 모듈, 경고 문구, 형식 확인, API 경로·원문 대조·미리보기, 구조 분석 링크, 실제 Docling의 시트·행 위치), `test_model_bundle.py` 13개(묶기·검증·재실행·충돌·깨진 ZIP·손 압축·위험 경로·접속 확인·setup 연결), `test_console.py`에 `--models` 2개. 프론트 150개 통과(새 2개: XLSM 파서 플로우, 구조 분석 매크로 표시)·빌드. 이 환경에서 `./setup.sh`(접속 확인 후 건너뜀) → 가짜 모델로 `prepare-offline.py --models-only` → 공백 든 경로의 ZIP으로 `./setup.sh --models`(SHA-256 확인, 재실행 시 건너뜀)를 확인했다.
- **확인하지 않은 것:** 실제 PDF 모델 파일로 묶기·설치(이 환경도 HF가 막혀 가짜 파일만), Windows 실기기의 `setup.cmd --models`, Excel이 저장한 실제 XLSM과 고객 XLSM, 고객사 HF 미러 유무와 ZIP 반입 허용 여부.
- **다음:** 사용자 Mac(모델 있음)에서 `--models-only`로 ZIP을 만들어 고객사 PC에 `setup.cmd --models`로 설치하고 PDF 파싱 확인. 고객사 XLSM 몇 건으로 셀·매크로 경고 확인. DOCM·PPTM도 같은 방식으로 열지 결정.

### 2026-11-25 허용 폴더에서 가져오기 (브라우저 파일 첨부가 막힌 고객사 PC)

- **상황(사용자 보고):** 고객사 PC에서 문서함 파일 추가 때 "보안정책에 의거 파일첨부 ActiveX 실행 및 파일전송이 통제됩니다"가 뜬다. 콘솔 코드의 문구가 아니다(저장소 전체 검색). 보안 프로그램이 브라우저의 파일 선택·전송을 막는 것으로 보이며, OpenCode Desktop은 파일을 잘 읽었다.
- **결정(사용자):** 보안팀과는 확인하지 못한 채 진행. 화면에서 브라우저 통제를 우회(다른 파일 API·base64 전송 등)하거나 Electron으로 감싸지 않고, 서버가 허용 폴더에서 직접 읽는 경로를 붙였다. 고객사 보안 정책이 이 방식을 허용하는지는 **미확인**이다.
- **구현:**
  - `backend/app/folder_import.py`: 허용 폴더 해석(`DOCOPS_AGENT_ROOTS`, 비우면 `samples/`), 상대 경로 검사(밖·절대·`:`·숨김 거부, 링크는 풀어서 밖이면 거부), 폴더 목록. 작업 도구 `Ops._roots`도 이 함수를 쓴다.
  - `backend/app/routers/folder_import.py`: `GET /api/live/import/roots`, `GET /api/live/import/entries`, `POST /api/live/import`. 계약은 [API·데이터 계약](API_AND_DATA_CONTRACT.md) §1·§2·§8.
  - `DocumentService.store_local`: 업로드와 같은 저장 규칙(서버 생성 이름, 임시 파일 후 교체, 크기 제한)으로 복사. 처리 이력 첫 줄이 "허용 폴더에서 가져와 로컬에 저장했습니다(<원본 경로>)"가 된다(`repository.create`에 `message` 인자 추가). 이름·크기·SHA-256이 같은 원본이 있으면 새 문서를 만들지 않는다(작업 도구의 재사용 규칙과 같음).
  - 화면 `FolderImport.tsx`(+`folderImport.css`), 문서함 머리 버튼, 결과 창의 일괄 파싱 접수(`processMany`). 화면 계약은 [프론트·화면 계약](FRONTEND_AND_INTERACTION_CONTRACT.md) §5-3.
  - 가져오기는 저장만 한다. 파싱은 결과 창의 **N개 파싱 실행**이나 문서 상세에서 사용자가 누를 때만 접수한다.
- **고객사 설정:** 프로젝트 위치 `C:\Users\USER\Desktop\vswrk\unstructured-parser-control-plane`(사용자 제공). `.env`를 비워 두면 그 아래 `samples`가 허용 폴더다. 합성 말뭉치 56개는 `samples\generated\corpus`에 이미 풀려 있다. `corpus_phase1~3.zip`에만 있는 것은 정답 JSON과 생성 기록뿐이라 풀 필요가 없다. 말뭉치로 바로 열려면 `DOCOPS_AGENT_ROOTS=C:\Users\USER\Desktop\vswrk\unstructured-parser-control-plane\samples\generated\corpus`.
- **검증:** 백엔드 235개 통과, 11개 건너뜀(새 `test_folder_import.py` 19개: 기본값·작업 도구와 같은 폴더, 숨김·밖·링크 거부, 복사·이력, 재사용과 내용 변경, 빈 파일·크기 초과, Origin 거부). 프론트 148개 통과(새 `folder-import.test.tsx` 2개). Linux에서 lite 설치로 서버를 띄우고 Chromium으로 `samples/generated/corpus`를 하위 폴더 포함으로 열어 49개 가져오기 → 결과 창 → 49개 파싱 접수, 다시 열면 `문서함에 있음` 표시까지 확인했다(콘솔 오류 없음). Windows 실기기와 고객사 보안 프로그램 아래에서는 확인하지 않았다.
- **남은 것:** 대기열(기본 64) 이상을 한 번에 파싱 접수하면 넘친 문서는 오류 줄에 남아 상세에서 다시 눌러야 한다. 작업 도구처럼 기다렸다 이어 넣는 일괄 접수는 없다. 허용 폴더 변경은 `.env` 수정 후 콘솔 재시작이 필요하다.

### 2026-11-25 고객사에서 화면이 옛 버전으로 뜬 문제: 빌드 기록으로 옛 `frontend/dist` 차단

- **증상(사용자 보고):** 고객사 PC에서 새 코드를 받아 서버를 띄웠는데 11-23·11-24 프론트 개선(3·4·5차, D번호·에이전트 작업·OCR 모델 연결 탭)이 없는 옛 화면이 떴다. 그 커밋들은 `main`에 들어 있었다(최근 커밋이 많아 9~21번째 뒤로 밀려 있었을 뿐).
- **원인(코드로 확인):**
  - 이전 실행기(`start.cmd`→`scripts/windows_launcher.py`, `run.sh`)는 `frontend/dist`가 있으면 화면을 다시 빌드하지 않았다. 11-19 업데이트 절차도 "같은 폴더에 덮어쓰기 → `frontend\dist`가 있으면 다시 빌드하지 않는다"였다. 덮어쓰면 옛 빌드가 그대로 남는다.
  - 11-25 `setup`에도 같은 구멍이 남아 있었다. 설치 기록이 없는 PC(예전 실행기로 설치한 PC는 모두 해당)에 Node.js가 없으면 "들어 있는 화면 빌드를 그대로 씁니다"로 옛 빌드를 쓰고, 지금 소스 지문을 기록해 `run`도 통과시켰다. `--offline`은 지문을 보지 않고 dist가 있기만 하면 썼다.
  - 서버가 `index.html`을 캐시 지시 없이 보내 브라우저가 옛 화면을 계속 쓸 여지도 있었다.
  - 사용자 확인: 처음엔 `start.cmd`로 띄웠고, 폴더를 다 지우고 `setup.cmd`→`run.cmd`로 다시 설치해도 옛 화면이 떠서 확인해 보니 **Edge 캐시**였다(옛 서버가 캐시 지시 없이 보낸 `index.html`을 Edge가 다시 묻지 않고 썼다). `start.cmd` 때는 남은 dist가 원인이었을 수 있으나 그 PC의 상태는 확인하지 못했다.
- **바꾼 것:**
  - 화면을 빌드하면 `frontend/dist/docops-build.json`에 그 빌드를 만든 화면 소스(`FRONTEND_INPUTS`와 `src/` 전부)의 파일별 SHA-256(줄바꿈 정규화)과 빌드 시각을 남긴다. `setup`과 `prepare-offline.py`가 쓴다.
  - `setup`은 기록이 지금 소스와 같을 때만 빌드를 건너뛴다. 기록이 없거나 다르면 Node.js로 다시 빌드하고, Node.js가 없거나 `--offline`이면 이유와 함께 멈춘다. 설치 기록(`docops-setup.json`)에는 더 이상 화면 지문을 넣지 않는다.
  - `run`도 같은 기록으로 확인하고, 시작할 때 `[run] 화면 빌드: <시각>`을 보여 준다.
  - 기록에 없는 새 파일은 세지 않는다. 같은 폴더에 덮어써서 남은 옛 소스 때문에 맞는 빌드를 거부하지 않기 위해서다(빌드에 들어가려면 다른 소스가 불러야 하고, 그 소스의 변화로 잡힌다).
  - 오프라인 ZIP은 `frontend/src`를 확장자 제한 없이 넣고, ZIP 안의 소스가 빌드 기록과 맞는지 만들 때 검사한다.
  - `/`(index.html)에 `Cache-Control: no-cache`. 이전 서버에게서 받아 이미 캐시된 화면은 한 번 `Ctrl+F5`로 지워야 한다.
  - `index.html`에 인라인 SVG 아이콘을 넣어 브라우저의 `GET /favicon.ico` 404를 없앴다.
  - 고객사 실행 창의 `GET /health 404`는 이 저장소의 어떤 코드(과거 커밋의 화면 포함)도 보내지 않는다. Milvus 미설정과도 무관하다(설정이 없으면 백엔드는 Milvus에 요청하지 않고, Milvus 확인은 Milvus 주소로 나가므로 콘솔 접속 기록에 찍히지 않는다). 같은 PC의 다른 프로그램이 같은 포트를 확인하는 것으로 보이며, 어떤 프로그램인지는 확인하지 못했다. 별칭 응답은 만들지 않았다(포트 충돌을 가리게 된다). README 문제 해결 표에 찾는 법을 적었다.
- **기존 설치 PC 영향:** 기록이 없는 기존 dist는 처음 한 번 다시 빌드된다(Node.js 필요). 이 변경 전에 만든 오프라인 ZIP은 기록이 없어 `setup --offline`이 멈춘다. ZIP을 다시 만든다.
- **검증:** 백엔드 216개 통과, 11개 건너뜀. `test_console.py`에 옛 빌드 재빌드, Node.js 없을 때 거부, 오프라인 불일치 거부, 덮어쓰기로 남은 파일 무시, run 거부·빌드 시각 표시를 추가했다. Linux에서 기록 없는 dist → `./setup.sh --lite`(다시 빌드) → 재실행(건너뜀) → Node.js 없는 PATH(거부) → `./run.sh`(헤더 `no-cache`, 11-24 화면 문자열이 든 번들 제공)를 확인했다. 오프라인 ZIP은 휠 없이 `build_archive`만 돌려 풀린 폴더에서 기록이 맞는 것과, 기록을 어긋나게 하면 묶음 검증이 실패하는 것을 확인했다. Windows 실기기에서는 확인하지 않았다. 프론트 변경은 `index.html` 아이콘뿐이다(프론트 테스트 146개 통과, Chromium에서 `/favicon.ico` 요청 없음과 404 0건 확인).

### 2026-11-25 설치·실행 정리: `setup` / `run`, 기본 = Docling 포함

- **사용자 결정:**
  - 사용자 2명이 시험하는 단계라 Docling이 기본이어야 한다.
  - 가상환경을 둘로 나누는 방식은 헷갈린다.
  - 설치와 실행을 나눈다. 사용자는 `setup`·`run`만 알면 된다. 진입점은 얇은 래퍼면 충분하다.
  - 고객사 PC는 PyPI·npm 접속이 열려 있다. `huggingface.co` 접속 여부는 확인하지 못했다.
  - 근거와 영향은 [결정](DECISIONS.md)의 "설치·실행"에 적었다.
- **진입점:**
  - `setup.cmd`·`setup.sh`는 Python을 찾아 `scripts/console.py setup`을 부른다.
  - `run.cmd`·`run.sh`는 `backend/.venv`의 Python으로 `scripts/console.py run`을 부른다.
  - 로직은 `console.py` 하나(표준 라이브러리, Python 3.9 이상)에 있다. `start.cmd`와 `scripts/windows_launcher.py`는 지웠고, 예전 bash 설치 로직도 없앴다.
- **setup:**
  1. 콘솔이 실행 중이면 멈춘다. 데이터 폴더의 `server.lock`과 8000~8019 포트로 확인한다.
  2. `backend/.venv`를 준비한다. 전체 모드는 Python 3.12와 `requirements-docling.lock.txt`, `--lite`는 3.12~3.15와 기본 잠금 파일을 쓴다. 지금 Python이 맞지 않으면 `py -3.12`나 `python3.12`를 찾는다.
  3. 화면을 빌드한다. `frontend/dist/docops-build.json`의 빌드 기록이 지금 소스와 같으면 건너뛴다(위 절 참고).
  4. `.env`가 없으면 만든다.
  5. `check_local.py --docling --fetch-models --report <임시 파일>`을 부른다. 빠진 PDF 모델은 `docling-tools models download layout tableformer`로 받는다. `DOCOPS_DOCLING_ARTIFACTS`를 지정했으면 받지 않는다. 이어서 자체 점검을 한다. (같은 날 추가: 받기 전 접속 확인과 `--models` 묶음 설치, 맨 위 절)
  6. 받지 못해도 설치는 계속하되, 받지 못한 것은 보고 파일에 남긴다(사용자 요청). setup은 그 내용을 맨 끝 요약(`====` 사이)에 `[주의] … N건`과 영향·해결 방법으로 다시 보여 준다.
  7. `backend/.venv/docops-setup.json`에 모드, 잠금 파일 지문, 그 경고를 남긴다(화면 지문은 dist의 빌드 기록으로 옮겼다).
  - 사용자가 혼자 쓰는 단계라 호환용 옵션(`--base`·`--docling`·`--check`)과 `.venv-docling` 안내는 없앴다(사용자 결정). run을 띄울 때 `launch_local.py`가 지금 파일 상태를 보고 PDF 모델이 없으면 한 줄로 알린다.
- **run:**
  - 기록이 없으면 "setup 먼저"라고 알린다.
  - 잠금 파일 지문이나 화면 빌드 기록이 지금 코드와 다르면(기록이 없어도) "setup 다시"라고 알린다. 줄바꿈 차이는 같은 것으로 본다.
  - 둘 다 맞으면 `launch_local.py`를 띄운다. 설치하거나 네트워크를 쓰지 않는다.
  - 모드 옵션을 주면 setup에서 정하라고 안내한다.
- **기존 설치 PC:**
  - 처음에는 `run`이 "setup 먼저"라고 멈춘다(기록 파일이 없으므로). `setup.cmd`를 한 번 실행한다.
  - `backend/.venv`가 3.12면 Docling을 더 설치하고, 3.13 이상이면 이름을 바꾸라고 안내한다.
  - 예전 `backend/.venv-docling`은 쓰지 않는다. 남아 있으면 직접 지운다(실행기는 건드리지 않음).
  - 오프라인 기본 묶음은 `setup.cmd --offline --lite`로 설치한다.
- **그 밖의 정리:**
  - `.env.example`에서 효과가 없는 EasyOCR 항목(`DOCOPS_OCR`, `DOCOPS_OCR_MODELS`)을 뺐다.
  - README를 빠른 시작(setup → run) → 옵션 → 모델 연결 → 제약 → 문제 해결 → 오프라인 → 개발 순서로 다시 썼다.
  - PDF 모델이 없을 때 화면·작업 도구·파서 오류 안내에 "setup 다시 실행"을 넣었다.
  - CI(`windows.yml`)는 `setup.cmd --lite`, `console.check_ready()`, 오프라인 묶음 `setup --offline --lite`로 점검한다.
- **검증:**
  - 백엔드 테스트 210개 통과, 8개 건너뜀(Docling 실측 등). 새 `tests/test_console.py` 23개가 옵션, 모드, 실행 중 감지(잠금·포트), 코드 업데이트 감지, 줄바꿈, Windows 전용 고정 버전, 마지막 요약을 확인한다.
  - 프론트 테스트 146개 통과.
  - Linux에서 실제로 확인한 것:
    - `./run.sh`(setup 전 거부) → `./setup.sh --lite`(첫 설치·재실행 1.3초) → `./run.sh`(서버 응답)
    - 8030번 포트로 띄운 콘솔이 있을 때 setup이 멈추는 것, 화면 소스를 바꾸면 run이 멈추는 것
    - 3.13으로 실행해도 3.12 가상환경을 만드는 것, 3.13 `.venv`에서 전체 모드가 멈추는 것
    - 가짜 `docling-tools`로 모델 받기의 성공·실패 경로. 실패하면 setup 맨 끝 요약에 `[주의] … 1건`과 해결 방법이 나오고, run 시작 화면에도 한 줄이 나오는 것
    - 오프라인 기본 묶음(`prepare-offline.py`)에 새 진입점이 들어가는 것
  - **Windows 실기기, 전체 모드 실제 설치(Docling·torch), 실제 `huggingface.co` 모델 받기는 돌려보지 않았다.**

### 2026-11-25 고객 PC 실행

- (위 정리로 바뀜) Windows 소스 ZIP은 `setup.cmd` 후 `run.cmd`, 준비된 ZIP은 `setup.cmd --offline`(Docling 휠이 없는 기본 ZIP은 `--offline --lite`) 후 `run.cmd`. setup의 자체 점검은 해당 데이터 경로의 임시 SQLite 저장소에서 한글 CSV 파싱·청킹을 확인한다. 기존 문서함에 시험 기록을 넣지 않는다.
- Windows와 Bash 실행기가 같은 포트 선택 코드를 사용한다. 포트가 겹치면 실행 창에 표시된 실제 주소로 접속한다. GitHub 소스 ZIP 첫 설치의 네트워크 요건 및 Docling 설치 옵션은 프로젝트 README에 있다.
- PDF 모델 일부만 옮긴 PC에서는 파서 플로우의 PDF 설치 안내를 펼쳐 빠진 파일을 확인한다. 파일 확인은 모델 가중치의 무결성 검사나 OCR 게이트웨이 접속 시험까지 수행하지 않는다.

### 2026-11-24 (마감) 모델 OCR 연결·D번호·에이전트 활동 — 다음 세션 시작점

**끝낸 것(백엔드, 커밋함):**
- **모델 OCR 연결**(`app/ocr_model.py`, `app/adapters/ocr.py`): OpenAI 호환 비전 API. `OCR_BASE_URL·OCR_MODEL·OCR_MODE(region|page)·지시문` 또는 화면 저장값(`/api/models/ocr`, 연결 확인은 글자 든 시험 그림을 실제로 읽힘). region은 Docling 레이아웃 영역마다 호출(겹친 영역 제거, 단 구분 읽기 순서), page는 쪽 한 번 호출(`<|det|>` 블록 해석). 출력 정리: OTSL·HTML 표 → Markdown 표, `\(\pm\)` 같은 LaTeX 기호 → 일반 기호, **끝까지 이어지는 반복 폭주만** 자름(중간 되풀이는 정상 내용이라 둠).
- 적용 경로: 이미지 파일(프레임마다), Office·SVG 속 그림(`fidelity/pictures.py`), **PDF의 글자 층 없는 쪽**(200 dpi 렌더링 → OCR → 쪽 순서 자리에 끼우고 뒤 위치 정보를 민다). OCR로 읽은 결과에는 항상 `OCR 모델로 읽은…원본 대조 필요` 경고(`ocr-read`)를 남겨 `ok`로 부풀리지 않는다. EasyOCR 코드는 모두 지웠다.
- **문서 번호**(`documents.seq`): 올린 순서, 기존 DB는 올릴 때 매김. `LiveDocument.seq`. 작업 에이전트 D번호가 이 값을 쓴다(화면과 같은 번호).
- **에이전트 활동 API** `GET /api/agent/activity`(묶음·보고서·호출 기록, 읽기 전용).
- 보고서에 `empty`(글자 없는 이미지, 실패로 세지 않음), `ocr-read`·`ocr-repeat` 코드. `ver` 줄은 `docling=2.150.0 ocr-model=PaddleOCR-VL-1.6-GGUF/region` 형식.
- 검증: 백엔드 188 통과(가짜 OCR 서버로 이미지·Office 그림·스캔 PDF 끼워 넣기·설정 API). 실제 PaddleOCR-VL로 `08_scans` 4건을 콘솔 경로 그대로 처리해 4건 모두 `ocr-read` 경고로 끝나는 것 확인.

**프론트(커밋함, 같은 날 밤):** D번호 표시·검색(`D12`·`d-12`·`#12`·`12`), '에이전트 작업' 화면(`?view=agent`: 묶음·보고서·호출 기록, 10초 자동 새로고침은 화면이 보일 때만), 모델 연결의 'OCR 모델' 탭(방식·지시문·게이트웨이 모델 목록에서 고르기·저장 전 확인·되돌리기, 키는 표시 안 함), 이미지 `no_text`는 '글자 없음'(실패 필터·건수에서 제외), 파서 플로우에 연결된 OCR 모델 ID. 프론트 145 통과·빌드. 헤드리스 Chrome으로 문서함(D번호·글자 없음)과 에이전트 작업의 묶음 탭을 실제 데이터로 찍어 확인했다(탭 전환 페이드 중에 찍히면 흐리게 보이므로 `--force-prefers-reduced-motion`으로 찍는다). 보고서·호출 기록 탭과 OCR 모델 탭은 클릭이 필요해 테스트로만 확인 → 다음 세션에 브라우저로 본다.
**같은 날 밤 추가(백엔드):** 디지털 PDF 쪽의 큰 그림(쪽 면적 10% 이상, 문서당 40개) OCR → 그 쪽 끝에 `[그림 속 글자]`, `/api/agent/activity`에 로컬 Origin 검사, 문서 정합성(API 계약·아키텍처·README·형식·파이프라인).

**다음 할 일(추천 순서):**
1. 새 화면 브라우저 검수 마무리(에이전트 작업의 보고서·호출 기록 탭, 모델 연결의 OCR 모델 탭).
2. 실제 OCR 모델로 다시 확인(모델 실행은 이번 밤에 하지 않음): 반복 자르기(끝 반복만), 디지털 PDF 큰 그림, 도표 이미지의 그림 영역, `08_scans`·`09_images`·스캔 COA 재처리 후 보고서.
3. 작업 에이전트 2단계(청킹·임베딩 평가), 3단계 Milvus 적재(로컬 Milvus 2.6.27: `infra/milvus-dev`, `docker compose up -d`, REST 127.0.0.1:19530).
4. 고객사 요청: 게이트웨이 OCR 모델 서빙(영역 방식 PaddleOCR-VL-1.6 또는 쪽 방식 Schift·Unlimited-OCR), Milvus 제공, 임베딩 모델, 에이전트용 LLM 목록.

**이 Mac 상태:** Docker Desktop·Milvus 컨테이너는 켜 둠(끄려면 `infra/milvus-dev`에서 `docker compose stop`). 시험용 llama-server·임시 콘솔 서버는 껐다. 다시 켜기: `llama-server -hf PaddlePaddle/PaddleOCR-VL-1.6-GGUF --host 127.0.0.1 --port 8091 --temp 0 -c 16384 -ngl 99`.

### 2026-11-24 OCR: 라이브러리 OCR 끔, 모델 OCR로 교체 진행

- **사용자 결정:** OCR은 문서 OCR 모델만 쓴다. EasyOCR·Tesseract 같은 라이브러리 OCR은 쓰지 않고 벤치마크하지도 않는다(경험상 품질이 매우 낮음). 고객사에는 OCR 모델을 게이트웨이(GPU 서빙)에 올려 달라고 요청할 예정이라 연결은 OpenAI 호환 비전 API로 한다.
- **근거가 된 사실:** EasyOCR로 읽은 스캔 COA(`COA_FBX-101_Lot-2026A031_스캔.pdf`)는 정답 대비 숫자+단위 26개 중 11개만 맞았는데(디지털 PDF는 26/26) 경고 없이 `ok`였다. EasyOCR 신뢰도는 오인한 줄에도 0.85~0.98로 높아 신뢰도 기준 경고로는 잡을 수 없다.
- **이번 변경:** `app/adapters/ocr.model_dir()`가 항상 `None`을 돌려 PDF·이미지·Office 그림·SVG 모든 경로에서 EasyOCR을 부르지 않는다. 이미지 경로 이름은 `ocr-model`(연결 전에는 `parser_unavailable`). 오프라인 묶음에 EasyOCR 가중치를 넣지 않는다. 화면 실행 환경 표시는 'OCR 모델 연결됨/미연결'. EasyOCR 코드는 모델 OCR 연결 때 지운다.
- **기존 설치에 미치는 영향:** 업데이트 후 스캔 PDF는 OCR 없이 텍스트 층만 읽고(`ocr-off` 경고, 글자 층이 없으면 `no-text` 실패), 이미지 파일은 'OCR 모델 미연결'로 실패한다. 이전 EasyOCR 결과는 실행 이력에 그대로 남는다.
- **다음:** 이 Mac에서 GLM-OCR(Ollama)과 PaddleOCR-VL-1.6(llama.cpp)을 한국어 OCR 벤치(Schift KoOCR-Bench)와 합성 정답으로 비교한 뒤, 고른 모델을 OpenAI 호환 API로 연결한다.

### 2026-11-24 작업 에이전트 도구 (MCP·CLI) 1단계

구축팀(사용자와 비정형 파트 부장님)이 고객사 PC의 OpenCode Desktop + 사내 중형 모델에게 "이 폴더 파싱하고 보고서 보여줘"처럼 실험을 시키기 위한 도구를 추가했다. 설계·설치·보고서 형식은 [작업 에이전트 도구](AGENT_TOOLS.md)에 있다.

- **역할 경계(사용자 확인):** 에이전트는 실험과 보고만 하고 코드를 고치지 않는다. 고객사 PC의 파일은 밖으로 가져갈 수 없어 사람이 `타이핑용` 블록을 손으로 옮겨 적어 전달한다. 그래서 보고서는 ASCII 짧은 코드와 검산 가능한 합계로 만든다. 문구 수정도 현장에서 하지 않는다.
- **모델 전제(사용자 확인):** 고객사에서 쓸 수 있는 것은 사내 게이트웨이의 중형 오픈웨이트 모델뿐이다. 도구 호출이 불안정하다고 가정해 도구 9개·평평한 인자·짧은 평문 응답·관대한 인자 해석·반복 호출 감지로 만들었다.
- **코드:** `backend/app/agent/`(`client.py` HTTP·서버 찾기, `ops.py` 도구·묶음 진행·요약, `codes.py` 짧은 코드, `mcp.py` stdio MCP), 진입점 `backend/docops.py`(`mcp`, `init-workspace`, CLI), 작업 폴더 안내 `opencode-workspace/AGENTS.md`. 표준 라이브러리만 써서 잠금 파일은 바뀌지 않았다.
- **서버 변경:** 저장소 표식 헤더 `x-docops-runtime`을 실행기가 아니라 앱(`app/middleware.RuntimeHeader`)이 붙인다. `start.cmd`로 띄운 서버도 찾을 수 있다. `Settings.runtime_id` 추가.
- **고객사 PC 실행기:** Git Bash에서 `run.sh`를 계속 써도 된다(이미 떠 있는 콘솔 감지·빈 포트 찾기가 `start.cmd`보다 낫다). `start.cmd`의 장점은 오프라인 설치뿐이다. 두 실행기 통합은 미루었다. WSL은 현재 보안 정책으로 막혀 있다(사용자 확인).
- **OpenCode 확인 사항:** 1.18.31 스키마 기준 MCP 요청 시간 제한 기본값이 5초라 `init-workspace`가 `timeout: 120000`과 `DOCOPS_AGENT_WAIT_SECONDS=40`을 함께 넣는다. 설정 없이 띄우면 도구 대기는 4초다.
- **검증:** 백엔드 테스트 182개 통과(새 `tests/test_agent_tools.py` 10개: 실제 HTTP 서버·합성 파일·MCP 프로토콜). 임시 저장소 서버와 `samples/generated/corpus`로 CLI 전 도구를 돌렸다. OpenCode 1.18.31 + Ollama `qwen3.6:35b-a3b`로 실제 문장 6개를 시켜 도구 호출 15회·잘못된 인자 0·반복 0을 확인했다([작업 에이전트 도구](AGENT_TOOLS.md) §7). 고객사 Windows·게이트웨이 모델로는 아직 돌려보지 않았다.
- **시험 모델 하한(사용자 확인):** 35B-A3B. 고객사 메인은 몇백B급이고 4B 같은 소형은 쓰지 않는다.
- **시험에서 드러난 파서 문제(미해결):** 스캔 PDF가 OCR 오인이 많은데도 경고 없이 `ok`(PDF OCR 경로에 신뢰도·OCR 적용 쪽 경고 없음), 글자 없는 사진이 `fail no-text`로 집계.
- **남은 것:** 위 파서 문제 두 건, 2단계 청킹·임베딩 평가 도구, 3단계 Milvus 적재(계획→실행 분리, 실행만 승인), 4단계 검색(읽기 전용 묶음). 고객사에 Milvus가 아직 없고 OCR·임베딩 모델 제공도 고객과 논의가 필요하다(사용자 확인). 이 Mac에서 OCR 모델을 먼저 시험할 예정.
- 이 Mac의 Ollama에 시험용 변형 모델 `docops-qwen36-35b-a3b-32k`(qwen3.6:35b-a3b, 컨텍스트 32K만 바꿈)를 만들었다. 필요 없으면 `ollama rm docops-qwen36-35b-a3b-32k`. OpenCode에서 쓸 때는 작업 폴더 `opencode.json`에 `provider.ollama`(`npm: @ai-sdk/openai-compatible`, `baseURL: http://127.0.0.1:11434/v1`, 모델은 `name`만)를 넣는다.

### 2026-11-23 파서 플로우와 청킹 탐색

문서함과 주 메뉴에서 파서 플로우·청킹 비교를 바로 연다. 형식별 실제 파서 조회에는 `GET /api/live/parsers`가 필요하므로 서버와 프론트 빌드를 함께 갱신한다. 모의 설계와 실제 문서별 청킹 주소는 [프론트 화면 계약](FRONTEND_AND_INTERACTION_CONTRACT.md)에 있다.

실행 중이던 서버가 청킹 설정에서 순차 실행만 제공하면 현재 작업이 끝난 뒤 서버를 다시 시작한다. 갱신된 서버의 `GET /api/retrieval/config` 응답에는 `caps.max_parallel_strategies: 4`가 포함된다. 청킹 비교에서 전략 동시 실행을 바꾸면 다음 비교부터 적용된다.

### 2026-11-23 파서 변경

로컬 EasyOCR 모델 준비 방법은 프로젝트 README의 PDF·Office 실제 파싱 절에 있다. 이전 실행의 결과와 설정은 그대로 조회할 수 있다. 새 회귀 사례는 `backend/tests/test_parser_resilience.py`에서 확인한다. 합성 입력으로 긴 한글 CSV 셀, 다중 프레임, SVG 내부 이미지, 빈 PDF 페이지, 희소 워크시트 등을 검증한다. 다중 시트 XLSX 회귀 테스트는 데이터 시트 1,001개 사이에 빈 시트와 숨김 시트를 끼운 파일을 업로드하고, 저장된 결과의 데이터 순서·원본 행 좌표·마지막 시트의 캐시 없는 수식과 원본 미리보기를 대조한다. 별도 합성 파일로 시트 1,001개 × 데이터 100행, 시트 2,000개 × 데이터 10행의 전체 순서와 원본 행 연결도 확인했다. 두 파일 모두 시트당 2열이다.

### 2026-11-22 프론트 화면 개편

첫 화면은 실제 문서함이다. 문서 상세·원문 검수의 주소, 분석 도구와 예시 메뉴의 위치는 [프론트 화면 계약](FRONTEND_AND_INTERACTION_CONTRACT.md)에 정리했다. 이전 기록의 화면 명칭과 메뉴 위치는 해당 날짜 기준이다. 이번 화면을 기존 설치에서 사용하려면 새 프론트 빌드가 필요하다. 소스 설치는 `frontend/`에서 `npm run build`를 실행하고, 오프라인 패키지는 새 빌드를 포함해 준비한다.

### 2026-11-19 파싱 엣지 케이스 작업

사용자가 전달한 엣지 케이스 11건(특수기호·기호 글꼴, SVG+래스터, ±, 첨자·병합 셀, 그림 속 그림, 기호 파일명, 215기호 문서, NASCA DRM DOCX·XLSX, 표 위 글상자, 흰회색 글자)을 **합성 파일로 재현**해 Docling 2.150.0 Office 경로(토치 없는 `docling-slim[format-office]`)에서 실측하고 백엔드를 보강했다. 대응표와 OCR 위치 제안은 [파이프라인·검색 설계](PIPELINE_AND_SEARCH_DESIGN.md) '전달받은 파싱 엣지 케이스 11건', API는 [API·데이터 계약](API_AND_DATA_CONTRACT.md) §3·§4-1.

- **파싱 전 판별** `backend/app/format_gate.py`: 내용 서명으로 DRM(`drm_protected`/`drm_suspected`)·암호(`encrypted`)·확장자 불일치(`format_mismatch`)를 걸러 파서를 부르지 않는다. `LiveDocument.error_code` 추가. NASCA 서명은 공개 자료로 확인하지 못해 내장하지 않았다. 실제 파일 머리말을 구조 분석으로 확인해 `DOCOPS_DRM_SIGNATURES`에 등록해야 한다.
- **사본 보정·원문 대조** `backend/app/fidelity/`: OOXML 사본에서 Symbol 글꼴 문자·바꿀 수 있는 첨자를 유니코드로 바꿔 파싱하고, 원본 XML 인벤토리와 결과를 대조해 `fidelity` 보고서·경고·보충 추출을 만든다. 합성 215기호 문서 208→215건.
- **파일명** `backend/app/textnorm.py`: 업로드 이름 NFC·방향 제어 글자 제거. 문서 계보 키가 `-70℃`와 `70℃`, `±0.5`와 `0.5`를 같은 문서군으로 합치던 버그를 고쳤다.
- 검증: 백엔드 134개(Docling 실측 1개 포함, scratch 가상환경), 프로젝트 `.venv`에서는 Docling 실측 1개 건너뜀. 실제 고객 파일·실제 NASCA 파일로는 확인하지 않았다. 프론트는 바꾸지 않았다(`error_code`·`fidelity`는 아직 화면에 표시하지 않음).
- **Python 지원 범위 3.12~3.15로 변경(3.11 제외, 사용자 결정).** `run.sh`·`start.cmd`·`scripts/windows_launcher.py`(버전 검사 두 곳)·`scripts/prepare-offline.py`(오프라인 휠 3.12~3.15). Docling은 잠금 파일이 3.12 기준이라 3.12 그대로. 백엔드 테스트 3.12.3·3.15.0b4 각각 133 통과(Docling 실측 1 건너뜀), 기본 잠금 파일의 `win_amd64` 휠이 3.12~3.15 모두 받아지는 것 확인. Windows 실기기에서 `start.cmd`는 돌려보지 않았다. 3.11로 만든 기존 `backend/.venv`는 실행기가 거부하므로 이름을 바꾸고 다시 만든다. 이제 3.12 문법을 써도 된다.
- 남은 것: 병합 셀 값 반복 제거, 스타일·테마 상속 글자색, PPTX 저대비, PDF 글자 층 대조(기호 글꼴 ToUnicode 누락 등), 영역 단위 OCR 연결과 후보 비교, `format_mismatch` 파일의 자동 경로 전환(예: `.xlsx`인 XLS), 화면에 실패 코드·충실도 표시.

#### 이미 `start.cmd`로 설치한 고객사에 이 변경을 올릴 때

사용자 확인(2026-11-19): 고객사 PC에 `start.cmd`로 백엔드·화면 모두 설치돼 있다. 이 변경은 작업 브랜치에만 있고 배포 전까지 고객사에는 영향이 없다.

1. **설치된 Python 확인:** `backend\.venv\Scripts\python.exe --version`이 3.12~3.15여야 한다. 3.11이면 새 실행기가 그 가상환경을 거부하므로, 3.12를 설치하고 `backend\.venv`의 이름을 바꾼 뒤 `start.cmd`를 다시 실행한다(오프라인 ZIP에는 3.12 휠이 들어 있다). Docling 환경(`.venv-docling`)은 원래 3.12라 그대로 쓴다.
2. **처리 중인 문서가 없을 때 중지:** 실제 파일 처리 화면에 `processing`이 없는지 보고 실행 창에서 `Ctrl+C`. 대기 중이던 작업은 실패로 바뀌고 다시 실행해야 한다.
3. **백업:** `runtime\` 폴더와 `.env`를 복사해 둔다. DB 변경은 열 추가뿐이고, 이전 코드도 새 열을 무시하고 읽으므로 되돌릴 때 코드만 바꾸면 된다.
4. **코드 덮어쓰기:** 같은 폴더에 덮어쓴다. `runtime\`, `.env`, `backend\.venv`, `backend\.venv-docling`, `offline\docling-models`(모델 포함 ZIP)는 지우지 않는다. 새 폴더에 풀면 위 항목을 옮겨야 기존 문서가 보인다.
5. **같은 옵션으로 `start.cmd` 실행:** 잠금 파일의 패키지 버전은 바뀌지 않아 재설치하지 않고, `frontend\dist`가 있으면 다시 빌드하지 않는다(화면 코드는 바뀌지 않았다). *2026-11-25: 이 "dist가 있으면 건너뛴다" 동작 때문에 화면 코드가 바뀐 업데이트에서 옛 화면이 남았다. 지금 `setup`은 빌드 기록으로 확인한다(맨 위 절).* 시작 때 `documents.error_code`, `parse_runs.fidelity` 열이 자동으로 추가된다.

검증(이 세션): 이전 커밋(275b64a)으로 만든 런타임(완료·미처리 문서, 구조 분석)을 새 코드로 열어 문서·결과·실행 이력·처리 이력·구조 분석 보존, 열 추가, 재처리 성공을 확인했다. Windows 실기기에서는 확인하지 않았다.

업데이트 뒤 사용자에게 보이는 변화: 기존 결과는 그대로이고 **다시 파싱해야** 기호·첨자 보정과 충실도 경고가 붙는다. DRM·형식 불일치 파일은 일반 오류 대신 사유가 적힌 실패로 바뀐다. 문서 계보 화면은 즉시 다시 계산되므로 `-70℃`/`70℃`처럼 기호만 다른 파일명이 다른 문서군으로 나뉠 수 있다. Office 처리 시간은 보정·대조만큼 늘어난다(합성 DOCX에서 2ms 대 Docling 18ms, 큰 통합문서는 미측정).

배포 전 점검에서 고친 것: 텍스트 파일이 `BMR-…`(BMP 서명 `BM`)이나 `%PDF-` 문자열로 시작하면 형식 불일치로 거부되던 문제(텍스트로 읽히면 항상 통과), Office 본문 파일 이름을 `word/document.xml`로 고정해 `document2.xml` 같은 정상 파일을 거부하던 문제(패키지 관계로 찾음). 구조 분석의 BMP 오판도 함께 고쳤다.

### 2026-11-17 이어서 할 작업

**이 세션에서 끝낸 것 (커밋 안 함)**
- 이름 변경: 비정형 관리 콘솔 (Unstructured Data Console). 메뉴 그룹: 모니터링 / 문서 처리 / 검색 준비 / 시스템.
- 검색 파이프라인 화면: `frontend/src/SearchPipeline.tsx`, `searchPipeline.css`, `__tests__/search-pipeline.test.tsx`. 에이전트·검색 엔드포인트·색인의 세 줄 구상도이고, 단계 hover·클릭 상세·접힌 참고 섹션으로 구성했다.
- 운영 대시보드 재구성: `Dashboard.tsx`, `flow/LiveFlowPanel.tsx`, `flow/liveFlow.css`, `dashboard.css`. 지표 한 줄 + 흐름 한 줄, 형식별 표와 주의 목록은 펼쳐서 보고, 지표 hover로 단계를 강조한다. 위젯 배치 저장 키는 v2로 바꿨다. `workspace.test.tsx`의 대시보드 케이스도 갱신했다.
- `DECISIONS.md`에 2026-11-17 결정 4건(Milvus 확정, 임베딩 후보, 검색 범위, 문서 계보) 추가. `.env.example`에 `EMBED_*`, `MILVUS_*` 추가.
- `main.py`에 `/api/lineage`, `/api/retrieval`, `/api/vectordb` 라우터를 등록했다(처음에는 빈 자리 파일).

**같은 날 이어서 끝낸 것 (커밋 안 함)**
| 화면 | 파일 | 기본 화면 |
|---|---|---|
| 문서 계보 | `LineageView.tsx`, `lineage/*`, `lineage.css`, `__tests__/lineage.test.tsx`(+`fixtures/lineage.json`) | 문서군 목록 + 선택 문서군(판·포함 트리·참조 탭 또는 관계 그래프). 요약 접힘, hover 강조, 클릭 상세 고정. 옛 `RelationsView.tsx` 삭제, `workspace.test.tsx` 해당 케이스 교체 |
| 청킹 벤치 | `ChunkBench.tsx`, `retrieval.css`, `__tests__/chunk-bench.test.tsx` | 첫 화면에서 전략별 크기·겹침과 동시 실행 수를 변경한다. 표·그림·캡션 정책과 토큰 실측은 상세 창에서 설정한다. 처음 열 때 저장된 설정으로 한 번 나눈다. |
| 임베딩 평가 | `EmbeddingEval.tsx`, `embedding.css`, `__tests__/embedding-eval.test.tsx` | 후보 × 프리셋 결과 행렬 하나. 설정은 서랍. 기본 후보 Harrier-OSS-v1 0.6B, 512토큰 모델은 표시만 |
| 벡터 DB | `VectorDbWorkspace.tsx`, `vectordb/*`, `vectordb.css`, `__tests__/vectordb.test.tsx` | 트리 + 청크 표(기본 탭) / 스키마·인덱스 탭. Milvus 미설정이면 예시 데이터 |

검증(2026-11-17): 프론트 테스트 63개, 빌드, 백엔드 테스트 103개 통과. 8000번 백엔드를 사용자 확인 후 같은 명령으로 다시 띄웠고, 브라우저에서 네 화면의 기본 상태·hover·클릭 고정·Escape를 확인했다. `API_AND_DATA_CONTRACT.md`, `FRONTEND_AND_INTERACTION_CONTRACT.md`, `ARCHITECTURE.md`에 새 화면과 API를 반영했다.

**같은 날 사용자 리뷰 후 다시 만든 것 (커밋 안 함)**
- 공통 화면 부품 `frontend/src/ui/`(팝업·탭·선택 버튼 묶음·리스트 박스·목록 + 상세)과 화면 설계 원칙(`FRONTEND_AND_INTERACTION_CONTRACT.md` §1-1). 세부·설정은 팝업으로 연다.
- 청킹: 원문을 본문·목록·표·그림·캡션·반복 머리말로 인식하고, 요소 인지·부모-자식·페이지 단위 전략 추가(`backend/app/chunking.py`, 테스트 `test_elements.py`). 합성 예시 3종과 예시 질문 26개.
- 의미 기반 청킹(`semantic`): 문장(앞뒤 문장을 묶은 창)을 임베딩 연결로 임베딩해 이웃 거리가 문서 안 상위 구간(나누는 빈도: 5·10·20%)인 곳에서 나눈다. 제목에서 끊고, 표·코드는 위 제목·캡션과 함께 통째로 두며, 그림과 캡션 사이와 쪽 표시·반복 머리말은 경계 후보에서 뺀다. 최대·최소 크기로 다듬는다. 문장 임베딩은 평가 캐시(`runtime/retrieval/embeddings.sqlite3`)에 넣어 다시 쓰고, 청킹 비교의 자동 재계산은 캐시만 쓴다. 실제 사내 임베딩 모델로의 품질은 아직 확인 전(가짜 게이트웨이로만 확인).
- 청킹 벤치: 전략 비교표(표 보존·그림·캡션·머리말 제거·한도 초과) + 원문 구성 탭, 행을 누르면 팝업(청크·문서 위 청크·설정).
- 임베딩 평가: 모델 5개 순위표(본문·표·그림 질문별 정확도, 입력 한도 초과 청크·벡터 용량은 실행 전에도 계산). 청킹은 청킹 벤치 전략 하나로 고정. 문서·질문·모델 설정과 칸별 결과는 팝업.
- 벡터 DB: 탭 개요(파티션 타일) / 컬렉션. 타일·청크 상세는 팝업.
- 파싱 비교: '기준/비교 결과'를 '이전 실행 → 현재 실행'으로 바꾸고, 처리 시간(`parse_runs.duration_ms`, 새 실행부터 기록)·글자·표 칸·숫자·단위·문서번호·깨진 글자 변화 요약과 정답 자료(JSON) 대조 팝업을 넣었다. 정답 자료 형식은 `samples/GPT_SAMPLE_GENERATION_PROMPT.md` §6.2의 gold와 같다.
- 검증: 프론트 테스트 88개, 빌드, 백엔드 116개. 8000번 백엔드는 다시 띄웠다.
- (2026-11-18) 루트에 `run.sh`(macOS/Linux/WSL/Git Bash용 실행기)를 추가했다. Milvus가 연결되지 않으면(주소 오류·404 포함) 화면이 트리를 반복 호출해 404를 쌓던 문제를 막았다: 백엔드가 연결 실패 주소를 30초 쉬게 하고, 프론트는 자동으로 연 Milvus가 실패하면 예시 데이터로 전환한다. 검증: 프론트 91개, 빌드, 백엔드 118개. 실제 Milvus로는 아직 확인하지 않았다.

**남은 것**
- 실제 임베딩 연결(`EMBED_*`)과 Milvus(`MILVUS_*`)로는 아직 확인하지 않았다. 둘 다 미설정 상태에서 예시 데이터·비활성 상태만 봤다. 평가 질문 세트는 저장된 것이 없다(예시 질문은 질문 팝업에서 불러와 저장해야 쓰인다).
- 부모-자식 전략의 정답 구절 판정은 자식 청크 기준이라 '작게 찾고 넓게 읽는' 이점은 아직 재지 않는다.
- 청크가 수천 개인 문서는 청킹 벤치가 모든 조각을 그려 hover가 느려질 수 있다.
- 커밋은 사용자가 요청할 때만 한다.

## 2. 코드 주석에서 옮긴 경위

주석 정리 때 코드 주석·docstring에서 뺀 경위다(최신이 위). 위치는 옮길 당시의 모듈과 함수 이름이다.

### 2026-11-28 `frontend/src`

기준은 아래 `verify`·`chunking` 항목과 같다. 규칙을 적은 주석은 테스트가 있는지 확인했고, 없던 것은 테스트를 더했다(규칙을 깨면 실패하는 것을 확인).

**주석으로만 있던 규칙 → 테스트**

- `AgentActivity.groupCalls`: 연결(MCP 프로세스·CLI 실행)마다 묶고, 연결 표식이 없는 예전 기록은 10분 넘게 쉬면 나눈다 → `agent-activity.test.tsx` '연결 표식이 없는 예전 호출 기록은 10분 넘게 쉰 곳에서 나눈다'.
- `MarkdownView.List`: 같은 깊이에서 번호 목록과 글머리표가 섞이면 원래 표지(1. · -)를 그대로 보인다 → `markdown-view.test.tsx` '같은 깊이에서 번호와 글머리표가 섞이면…'.
- `SearchPipeline.useFlow`: 처음 열 때 흐름을 차례로 켜고, 동작 줄이기 설정이면 바로 다 켠다 → `search-pipeline.test.tsx` '흐름은 처음 열 때 차례로 켜고…'.
- `ChunkBench`: 한도 초과는 알려진 모델 가운데 가장 작은 입력 한도로 센다(기존 테스트는 모델이 하나뿐이었다) → `chunk-bench.test.tsx` '한도 초과는 알려진 모델 가운데 가장 작은 입력 한도로 센다'.
- 화면이 서버 값을 따로 든 곳: `LiveDocumentView.IMAGE_FORMATS`(= `app/formats.py`), `ModelWorkspace.OCR_DEFAULTS`(= `app/ocr_model.py` `DEFAULTS`, 예전 서버가 defaults를 보내지 않을 때만 씀) → `backend/tests/test_frontend_mirrors.py`. 주석은 대응하는 서버 위치로 남겼다.

**이미 테스트가 있던 규칙**

- 사이드바: 접힌 채 마우스·키보드 초점이 들어가면 본문을 밀지 않고 겹쳐 펼치고 벗어나면 접힌다, 접힘은 이 브라우저에만 기억한다 → `review-desk.test.tsx`. 저장소를 못 쓰면 펼친 상태로 시작한다는 것은 테스트하지 않는다(`readSidebarOpen`의 `catch`).
- 에이전트 작업: 화면이 보일 때만 10초마다 다시 읽는다, 검수 요청을 못 읽어도 활동은 보인다 → `agent-activity.test.tsx`.
- 이미지에서 글자를 찾지 못한 경우(서버 `failed` + `no_text`)는 실패가 아니라 '글자 없음', D번호는 'D12'·'d12'·'D-12'·'#12'·'12'로 읽는다 → `live-labels.test.tsx`.
- 문서함: 조건(검색·상태·확장자·정렬)이 바뀔 때만 늦게 온 응답을 버린다. 처리 중 다시 읽기는 처음부터 받은 만큼(최대 500)만 다시 받고, 그 범위 밖에서 '더 보기'로 이어 받은 행과 다음 쪽 위치는 남긴다(다시 읽기가 먼저 시작해 늦게 끝나도 사라지지 않게) → `qc-ledger.test.tsx`.
- '모두 선택'은 파서가 있고 문서함에 아직 없는 파일만 고른다 → `folder-import.test.tsx`.
- OCR 지시문이 기본값과 같으면 빈 칸으로 두고 자리 표시에 기본값을 보인다(비워 저장하면 서버가 기본값), API 키를 비워 두면 저장된 키를 유지한다 → `model-workspace.test.tsx`.
- 임베딩 평가: 지금 고른 청킹과 같은 실행일 때만 결과 칸을 채운다 → `embedding-eval.test.tsx`. 의미 기반 전략은 사용자가 '나누기'를 누를 때만 문장 임베딩을 계산한다 → `chunk-bench.test.tsx`.

**옮긴 경위·설명**

- `EmbeddingEval.SETUP_KEY`(`…:v3`): 기본 모델이 다섯으로 바뀌어 저장 키를 올렸고 이전 구성은 읽지 않는다.
- `api/live.ts` 원장 필드: "원장(2026-11-27). 예전 서버에는 없다."
- 예전 서버 호환 메모(그 값이 없으면 화면이 빈 값을 채우거나 그리지 않는다): 문서 `seq`(D번호), 의심점 `id`·`rank`, `ocr_model`, 원장 필드, 목록의 `qc`(쪽 단위 질의에만 붙음), 검수 요청 `finding_id`·`rule_version`, 에이전트 활동의 `documents`, 처리 깔때기(`qc-summary`가 없으면 그리지 않음), 다시 대조 진행·`qc_stale`, 청크의 `qc`와 `source.run_id`, 조건 없는 전체 목록(화면이 거르고 정렬하고 센다).
- `QcFunnel`: 마지막 단계(통과 후보)만 보고 처리율을 말하면 스캔·미지원 파일이 통계에서 사라지므로 분모를 차례로 보인다. 통과 후보도 기록 모드라 사람 검수를 이어 간다.
- `EmbeddingEval`: 청킹은 청킹 벤치의 방식 하나로 고정한다. 입력 한도 초과·벡터 용량 열은 실행 전에도 실제 계산값이다(외부 호출 없는 계획).
- `ModelWorkspace`: 바꾼 지시문이 있으면 지시문 칸을 처음부터 펼치고, 이후 열고 닫기는 사용자에게 맡긴다.
- `LiveWorkspace`: 검색어는 입력을 250ms 멈췄을 때 서버에 묻는다(예전 서버는 화면이 거르므로 기다리지 않는다). 지금 쪽 밖에서 처리 중인 접수 문서는 `ids=`로 따로 물어 완료 알림을 놓치지 않는다.
- `SearchPipeline`: 에이전트 개발 측·운영자·현업과 같은 그림을 보며 이야기하려고 만든 화면이다. 흐름 지도 한 장(에이전트 → 검색 엔드포인트 → 저장소 ← 색인 파이프라인)에 단계와 결정 상태를 올리고, 좌표는 1060 × 548이다. 검색 엔드포인트 줄은 늘 펼쳐 두고, 접은 줄은 캡슐 하나로 서며 다른 줄의 선은 그 캡슐에 닿는다. 단계를 누르면 정한 것과 정할 것을 보이고 원래 설명 글은 '자세히'로 접는다.
- 그 밖에 이름·화면 설명을 되풀이한 JSDoc, 구획선, `catch { /* … */ }` 안의 설명은 옮기지 않고 지웠다.

### 2026-11-28 `app/verify.py`·`app/chunking.py`

남긴 것은 외부 사실(파일 형식·Docling 동작), 임계값 근거, 데이터 뜻(필드 값 목록, 0부터·1부터, 튜플 반환 구성)뿐이다. 이름을 되풀이하거나 코드 순서를 풀어 쓴 docstring과 구획선(`# ---- …`)은 옮기지 않고 지웠다. `chunking.py`는 1차 정리(`f87a0b4`)에서 지운 내용도 여기 함께 옮긴다(1차 표시).

**코드와 어긋나 있던 주석**

- `verify` 모듈 docstring: "위치가 없는 결과 줄은 바로 앞(없으면 뒤) 위치의 단위로 본다." `Verifier._map_regions`는 앞뒤 단위 모두에 넣는다. 그 자리 주석이 이유를 적고 있었다: 단위 경계에 걸린 제목(빈 줄·시트 이름 포함)을 놓치지 않으려고. 주석대로 바꾸면 `test_verify.py::test_unlocated_line_between_pages_belongs_to_both_neighbouring_pages`가 실패한다.
- `verify.MAX_SPOTS`: "화면·에이전트가 한 번에 받는 상세 수." `service.verify`의 기본 `limit`이지만, 작업 도구 `verify`는 20곳씩 받는다(`app/agent/ops.py`).
- `chunking._Unit`: 단위를 "문단·표 행 묶음·그림"이라 했지만 `heading` 단위도 있다. 값 목록(heading · prose · table · image)으로 고쳐 남겼다.
- `test_chunking.py::test_semantic_units_window_does_not_cross_sections`는 이름과 달리 창을 검사하지 않았다(창이 절을 넘게 바꿔도 통과). 창 검사를 더했다.

**주석으로만 있던 규칙 → 테스트**(사본에서 그 규칙을 깨면 테스트가 실패하는 것을 확인했다)

- `verify.Verifier._map_regions`: 위 첫 항목.
- `verify.Verifier._check_text`: 같은 글이 원본에 여러 번 나오면 결과에도 그만큼 있어야 한다 → `test_verify.py::test_text_repeated_in_the_source_must_appear_as_often_in_the_result`.
- 같은 함수: 40자 이상 단위에서 결과에 보이는 글자가 40% 미만이면 줄·기호·숫자 지점을 따로 올리지 않고 `unit_missing` 하나로 묶는다 → `test_a_mostly_missing_page_is_one_finding_instead_of_one_per_line`.
- `verify.Verifier._check_cells`: 바뀐·빠진 칸은 같은 행이어도 칸마다 의심점 하나다. 행으로 묶으면 한 번의 '맞음'이 같은 행의 다른 오류까지 해결한다. CSV 주소별 대조는 이미 `test_qc_ledger.py::test_a_row_with_a_whitespace_change_and_a_value_change_gives_two_findings`가 있었다 → XLSX는 `test_two_changed_cells_in_one_sheet_row_are_two_findings`.
- `chunking._line_kinds`: `<!-- formula-not-decoded -->` 같은 Docling 자리 표시는 반복돼도 머리말이 아니다(외부 사실이라 주석도 남김) → `test_elements.py::test_repeated_docling_placeholders_are_not_page_furniture`.
- `chunking._markdown`: 제목만 있는 절은 본문이 있는 앞 청크에 붙이지 않는다. 뒤의 하위 절과 합쳐지게 하려는 것 → `test_chunking.py::test_markdown_heading_only_section_joins_its_subsection_not_the_previous_body`.
- `chunking.semantic_units`: 표 위에 제목이 붙어 있으면(새 절) 그 앞 캡션은 앞 절의 것이다. 쪼개진 캡션('표 1.' / 설명)은 제목에서 시작한 조각까지 붙인다. 표 바로 아래 캡션은 표와 한 덩어리다(1차) → `test_semantic_table_captions_belong_to_their_own_section`(세 경우). 기존 견본 테스트로는 셋 다 깨도 통과했다.
- `chunking._windows`(1차): 표·코드·제목이 끼면 다른 절로 보고 창이 넘어가지 않는다 → `test_semantic_units_window_does_not_cross_sections`.
- `chunking._norm_phrase`: `embedding.normalize_phrase`와 같은 규칙(NFKC, 대소문자 무시, 공백·표·강조 기호 제거). `chunking`이 `embedding`을 가져오지 않아 두 벌이다 → `test_embedding.py::test_phrase_normalization_and_cosine_top_k`.
- `chunking` 모듈 docstring: 표준 라이브러리만 쓰는 순수 함수 → `test_chunking.py::test_chunking_imports_only_the_standard_library`(가져오기만 검사한다).

**이미 테스트가 있어 지운 규칙**

- `verify.MAX_FINDINGS`: 넘으면 우선순위 높은 것부터 남기고 판정 불가 → `test_qc_ledger.py::test_differences_beyond_the_global_cap_block_the_pass_candidate`.
- `verify.Verifier._check_chart`: 축 눈금으로 값을 추정하지 않는다. 캐시가 없으면 의심점 없이 '미확인', 막는 이유 `chart_no_cache` → `test_xlsx_charts.py::test_chart_cache_matches_conflicts_or_is_missing`.
- `chunking._table_pieces`: 두 번째 조각부터 머리행을 반복한다 → `test_markdown_splits_large_tables_by_rows_and_repeats_header`.
- `chunking.normalize_params`: 범위를 벗어난 값은 가까운 허용값으로 맞춘다 → `test_parameters_are_clamped_and_invalid_input_rejected`.
- `chunking.sentence_bounds`(1차): 목록 번호(1. )와 흔한 약어(Rev. 등)는 끊지 않는다 → `test_korean_sentence_boundaries_skip_list_numbers_and_abbreviations`.
- `chunking.semantic_units`(1차): 표·코드는 통째 한 단위, 바로 위 제목은 표와 함께(제목만 떨어진 청크를 만들지 않게), 연달아 나온 제목은 함께 다음 문장에 붙는다 → `test_semantic_chunking_breaks_where_meaning_changes_and_respects_structure`.
- `chunking._semantic`(1차): 그림과 캡션, 한 캡션의 조각 사이는 나누지 않는다 → `test_semantic_chunking_keeps_figures_and_table_captions_with_their_targets`.
- `chunking.parse_elements`(1차): 문서가 캡션으로 번호를 매겼으면 그 번호를 쓰고 캡션 없는 것은 번호 없이 둔다(겹침 방지). 캡션이 하나도 없으면 순서 번호 → `test_elements.py`(규칙을 깨면 2개 실패).
- `chunking.NeedsEmbedding`(1차): 사용자가 누른 요청에서만 모델을 부른다 → `test_embedding.py::test_semantic_strategy_only_calls_the_model_when_the_user_asks_and_reuses_the_cache`.

**옮긴 설명**(테스트로 고정하지 않은 것)

- `chunking` 모듈 docstring(1차), 청크 위치: 모든 청크는 원문 문자 위치 start/end(파이썬 문자열 인덱스, end 미포함)를 가진다. text는 원문[start:end]와 같다(앞뒤 공백을 걷어 내고 위치도 그만큼 옮긴다). 예외는 문서 구조 전략이 큰 표를 행 단위로 나눌 때 두 번째 조각부터 머리행(머리+구분선)을 앞에 다시 붙이는 경우로, start/end는 실제 행 범위이고 flags에 `table-split`이 붙는다. 요소 인식 전략(element·parent_child·page)은 요소를 이어 붙여 text를 만든다(버린 머리말·그림은 빠지고, 표는 머리행 반복·'열: 값' 문장으로 바뀔 수 있다). 이때 start/end는 청크가 덮는 원문 범위다. 앞의 두 문장과 `table-split` 예외는 `test_chunking.py::test_every_strategy_covers_the_source_and_keeps_offsets`가 고정·재귀·문서 구조·문장 전략에서 검사한다. 같은 날 [API·데이터 계약](API_AND_DATA_CONTRACT.md) '청크 위치'로 옮겼다(의미 기반 전략도 같은 규칙이고 큰 표에서 `table-split`이 생기는 것을 견본 문서로 확인).
- `chunking` 모듈 docstring(1차), 토큰 추정: 한글 음절·자모, 한자·가나 1자 = 1토큰(근거는 `token_weights` docstring에 남김). 영문 단어 첫 글자 0.5, 이후 글자 0.25(약 4글자당 1토큰, 짧은 단어도 최소 0.5토큰). 숫자 1자리 0.5(토크나이저에 따라 한 자리씩 또는 몇 자리씩 묶는다). 문장부호·기호 1자 1, 바로 앞과 같은 기호가 이어지면 0.25('---', '|||'). 그 밖의 문자(라틴 확장·키릴 등) 0.5, 공백·줄바꿈 0. 청크의 추정 토큰은 가중치 합의 올림이고 특수 토큰(BOS/EOS, 지시문)은 넣지 않는다. 화면에도 '추정'으로 표시한다. 실제 값은 게이트웨이 응답의 `usage.prompt_tokens`로 표본을 재어 비교할 수 있다.
- `chunking._markdown`(1차): 첫 조각에서 제목 몫을 덜어 낸 나머지가 크기의 30% 미만이면(제목이 지나치게 길면) 덜어 내지 않는다.
- `chunking._semantic`(1차·2차): 이웃 문장(앞뒤 문장을 묶은 창)의 임베딩 거리가 문서 안에서 상위 구간이면 경계로 삼고 크기로 다듬는다. 거리는 같은 절 안에서 이어지는 두 내용 문장 사이에서만 재고, 경계는 뒤 문장 앞에 두며 사이의 머리말은 앞 청크에 남는다. 최소 크기보다 작은 묶음은 같은 절의 다음 묶음과, 안 되면 앞 묶음과 합친다(최대 크기를 넘지 않을 때만). 쪽 표시·반복 머리말만 든 묶음은 절·표와 상관없이 앞 묶음에(문서 맨 앞이면 뒤 묶음에) 붙인다. 쪽 표시와 반복 머리말은 뜻 비교에서 빼고 앞 청크에 그대로 붙인다(`_noise`).
- `chunking._recursive`: 문단 → 줄 → 문장 → 띄어쓰기 → 글자 순서로 크기 안에 들 때까지 나누고 이웃 조각을 다시 합친다. `_table_pieces`(1차): 한 행이 너무 길면 그 행만 다시 나눈다. `Source`(1차): 누적 합으로 구간 길이를 O(1)에 잰다. `Source.fit_end`: 최소 한 글자는 전진한다. `parse_elements`(1차): 캡션은 표·그림 바로 앞뒤(빈 줄 하나 이내)의 짧은 '그림 N'·'표 N' 문단이다.
- `verify.Verifier._hidden_layer`: 보이지 않는 글자 층은 PDF 렌더 모드 3이다(`app/pdf_layers.py` 모듈 설명에 있다).
- `verify._GRID_DIFF_ROWS`: CSV 차이 구간의 원본·결과 행 수 합이 이보다 크면 행 정렬(`SequenceMatcher`) 없이 순서대로 비교한다.

### 2026-11-27 1차 정리(`f87a0b4`): 백엔드 다른 모듈

1차 정리는 경위를 옮기지 않고 지웠다. 2026-11-28에 그 커밋의 변경분을 다시 읽고, 날짜·리뷰 경위·계획서 절 번호와 규칙·근거를 적은 것만 여기 옮긴다. 이름을 되풀이한 docstring은 옮기지 않았다. `chunking`·`verify`의 1차 분은 위 항목에 있다. 여기 적힌 규칙이 테스트로 고정돼 있는지는 이번에 하나씩 확인하지 않았다.

**경위**(날짜·리뷰·계획서)

- `qc.RULE_VERSION`: 2026-11-27 두 번째 커밋에서 대조 규칙(숨은 글자 층·차트)이 바뀌었는데 이름을 올리지 않아, 첫 커밋 때 만든 원장이 그대로 쓰였다(의심점 0). 그래서 이름에 기대지 않고 코드 지문으로 바뀜을 감지한다(`rule_key()` = 이름 + 대조 코드·원본 읽기 라이브러리 지문 10자, 바뀌면 기존 실행을 다시 대조).
- `verify`(모듈 상단): 단위별 상세 상한은 두지 않는다. 2026-11-27 리뷰에서 CSV 201번째 차이가 원장에서 빠져, 앞 200곳을 '맞음'으로 처리하자 압력 오류가 남은 채 통과 후보가 됐다. 찾은 차이는 모두 의심점이 되고, 전체 상한(`MAX_FINDINGS`)을 넘은 것은 '상세 없음'으로 세어 미해결로 남긴다.
- `verify._grid_pair_spot`: 한 행의 차이를 하나로 묶으면 공백 차이만 보고 '맞음'을 눌러 같은 행의 수치 오류(17 bar → 71 bar)까지 해결로 처리될 수 있다(2026-11-27 리뷰). 행 순서 바뀜은 행 하나, 두 칸 맞바뀜은 그 쌍 하나, 그 밖의 다른 칸은 칸마다 하나.
- `verify._hidden_layer`: 숫자 모음만 비교하면 A·B 값 맞바꿈이나 bar → kPa를 놓친다(2026-11-27 리뷰). 그래서 같은 그림의 OCR과 항목·값·단위를 한 벌로 대조한다. 모두 같으면 '다른 표현과 일치'(의심점 없음, 판정 불가 근거는 남음), 값·단위가 다르면 `hidden_conflict`, 같은 그림의 OCR이 없거나 항목 대응을 정할 수 없으면 `hidden_layer`(화면 값 미확인).
- `service.qc_summary`: 지금 처리 중·실패지만 이전 성공본이 있는 문서의 판정은 그 실행에 남지만 지금 유효한 결과가 아니다. 현재 처리 결과로 세면 재처리에 실패한 문서가 통과 후보로 남는다(2026-11-27 리뷰). 그래서 `previous_results`로 따로 세고 상태 이름에 '이전 성공본'을 붙인다.
- `chunk_qc`(모듈): 파서 품질 검수 고도화 계획 §3.2.4. 청크가 어느 실행의 어느 본문에서 나왔는지(run ID·본문 해시), 어느 원본 영역을 덮는지, 그 안에 해결되지 않은 검수 항목이 있는지를 남긴다. '71 bar' 청크를 누르면 원본 위치와 후보 값을 보는 근거다. 청킹 벤치는 미검수 결과를 그대로 실험할 수 있다(막지 않는다). 검색용 발행 정책은 아직 정하지 않았다.
- `qc`(모듈): 판정 순서(계획 §3.1). ① 실행 실패는 원인을 기록한다(이 모듈 밖). ② 성공 실행에 대조가 아직 도달하지 않았으면 '미평가'. ③ 확인 안 된 의심점이나 열린 사람 검수가 있으면 '검수 필요'. ④ 필수 검사의 미완료·잘림·공유 원천·미지원 표현이 있으면 '판정 불가'. ⑤ 모든 필수 조건을 채운 형식군만 '통과 후보'이며, 현장 검증 전이라 자동 통과는 하지 않고 사람 검수를 이어 간다(기록 모드). 지금 통과 후보 기준이 있는 형식은 구분자·인코딩이 확정된 직사각 CSV뿐이다.
- `folder_import`(모듈): 브라우저 파일 첨부·전송이 보안 프로그램으로 막힌 PC에서도 쓰려고 만든 경로다(2026-11-25 고객사).
- `models` 검수 요청 구획: V번호 도입은 2026-11-26. `fidelity/pictures`: `low_confidence`는 모델 OCR에 믿을 만한 신뢰도 값이 없어 0으로 둔다(이전 형식 호환).

**규칙·근거**

- `qc`: finding ID(F + 12자리)는 종류·원본 단위·원본 주소·원문/결과 조각과 같은 서명의 발생 순번으로 만든다. 결과에만 있는 것(숫자·깨진 글자·OCR 줄)은 결과 줄로 구별한다. 우선순위는 심각도 → 원본 단위 순서 → 결과 줄 → 문서 순서. 판정 '틀림'은 오류가 확인된 것이라 검수 필요로 남는다. `reason`의 `blocking`이면 그것만으로 통과 후보가 될 수 없다. 중요 오류나 확인 안 된 필수 범위가 문서 평균에 묻히지 않도록 일치율은 쓰지 않는다. 상세를 남기지 못한 차이는 사람이 볼 수 없으니 해결될 수 없고, 남은 수만큼 통과 후보를 막는다.
- `chunk_qc`·`service`: 청크의 판정은 '틀림'(확인된 오류, `confirmed-wrong`) → '보류'·확인 전·판정 없음(`unverified`) 순이고 '맞음'만 해결이라 오지 않는다. 검수 요청은 화면 상세 목록(한 쪽)이 아니라 원장 전체에서 찾는다(우선순위 밖으로 잘린 지점도 V가 된다).
- `models`: S번호는 표시 순번이라 규칙 버전이 바뀌면 달라질 수 있고 finding ID가 안정적이다. 문서 번호(D번호)는 올린 순서로 매기며 바뀌지 않는다. 목록의 `qc` 상태는 pending·needs_review·undetermined·pass_candidate·unavailable. 가져오기 파일 상태 ready(파서 있음)·no_parser(저장만)·empty·too_large(가져오지 않음). 이름·크기가 같은 기존 문서 중 원본 SHA-256까지 같으면 새로 만들지 않는다.
- `folder_import`: 허용 폴더는 작업 도구와 같은 `DOCOPS_AGENT_ROOTS`로만 정하고 화면에서는 바꿀 수 없다. 비우면 프로젝트의 `samples`를 쓴다. 여러 개는 OS 경로 구분자(Windows `;`)나 줄바꿈으로 나눈다. 폴더 밖(`..`, 절대 경로, 밖을 가리키는 링크)과 숨김·잠금 파일은 읽지 않고, 밖을 가리키는 링크는 목록에서도 뺀다. 가져오기는 저장만 하고 파싱은 사용자가 따로 실행한다.
- `format_gate`·`config`: DRM 서명은 `DOCOPS_DRM_SIGNATURES`에 `이름=hex:0A0B0C0D; 이름=ascii:<확인한 문자열>` 형식으로 등록한다. `hex:`는 파일 맨 앞(0번째 바이트)부터, `ascii:`는 앞 4 KiB 안 어디서든 일치. 잘못된 항목은 무시하지 않고 오류로 알린다(조용한 미탐 방지). 알려진 서명이 없는 이진 파일은 암호문처럼 보이면 DRM 의심, 아니면 미확인. 글자로 읽히는 파일은 'BMR-…'·'%PDF-' 같은 서명 문자열로 시작해도 텍스트다.
- `service`: 업로드 이름은 표시용일 뿐 저장 경로로 쓰지 않는다(저장 이름은 서버가 만든다). macOS 분해형 한글(NFD)은 조합형으로 바꾸고 방향 제어 글자는 지우되 ℃·±·− 같은 기호는 남긴다. 확장자가 아니라 내용으로 먼저 확인해 DRM 래핑·암호·형식 불일치를 파서 오류로 뭉뚱그리지 않는다. 구조 분석만 되는 형식은 본문 파서가 없다는 것과 보호 여부를 확인하지 않았다는 것을 함께 알린다. 매크로는 실행하지 않고, 있으면 셀 값이 저장 시점의 값이라는 경고를 남긴다. OOXML은 원본 대신 보정 사본을 파서에 넣고, 사본을 만들기 전에 압축 폭탄·위험 경로를 거른다. 파싱을 마친 작업자가 이어서 원장을 만들며(외부 호출 없음) 실패해도 파싱 결과는 그대로다. 서버 시작 때 다시 대조는 원본만 다시 읽고(파싱·외부 호출 없음), 이전 규칙의 원장과 검수 요청(V번호·판정·메모)은 지우지 않는다. 구조 분석은 원본을 바꾸지 않고 사용자가 요청할 때만 한다.
- `middleware`·`routers`: 실제 파일·외부 모델 호출 경로(`/api/live`, `/api/retrieval`, `/api/vectordb`)와 작업 에이전트 기록(`/api/agent`, 파일 경로·인자가 들어 있음)은 로컬 화면에서 온 요청만 받는다. 마지막에 더한 미들웨어가 가장 바깥이라 403·413 응답에도 저장소 표식이 붙는다. API 키는 받기만 하고 응답에는 설정 여부(`api_key_set`)만, Milvus 토큰은 응답에 나오지 않는다. 생성 모델 연결은 primary·secondary 두 자리, 임베딩은 embed 한 자리. 모델 연결 확인에서 키를 새로 넣지 않았으면 저장된 키로 확인한다. 계보 API는 업로드 목록과 사용자가 이미 실행해 둔 구조 분석 결과만 읽고 새로 분석하지 않는다. 검수 요청은 작업 에이전트(`flag`)와 원문 대조 화면이 만들고 판정은 사람이 남긴다.
- `routers/live`: 조건 없는 목록은 예전처럼 전체(파서 화면·에이전트·구조 분석이 쓴다). PDF 모델이 없으면 PDF는 `pdf-text`로 가므로 고정 표가 아니라 지금 경로를 돌려준다. OCR 모델은 설정 여부만 보고 호출하지 않는다.
- `routers/retrieval`: 의미 기반 전략은 캐시의 문장 임베딩만 쓰고, 사용자가 '나누기'를 눌러 `embed=true`로 보낸 요청에서만 모델을 부른다. 모델을 비워 두면 연결의 첫 모델을 쓴다. 질문 가져오기는 읽기만 하고 저장은 화면에서 확인한 뒤 PUT.
- `pdf_layers`: 픽셀에 '17 bar'가 보여도 숨은 층의 '71 bar'를 파서와 대조가 같은 값으로 확인해 버린다(같은 계통을 두 번 읽음). 숨은 층은 지우지 않는다(올바른 숨은 층도 많다). 화면 표시용 좌표가 필요하면 쪽 크기와 회전(`rotation`·`width`·`height`)으로 바꾼다. 글자 객체를 읽지 못한 쪽은 판정하지 않는다(`measured=False`).
- `xlsx_charts`: 셀 값과 numCache는 한 파일 안의 다른 저장 표현이라 서로 다르면 모델 없이 충돌을 찾을 수 있다. 해석하는 참조는 같은 통합문서 안의 연속 범위(한 행 또는 한 열)이고, 여러 영역·외부 통합문서·이름 정의는 '해석 못 함'. 문서 관계(통합문서 → 시트 → 그리기 → 차트)를 따라 차트가 놓인 시트를 찾는다. 계열 이름 캐시가 없으면 셀에서 읽는다.
- `verify`(1차): 숨은 층 묶음과 같은 그림의 OCR은 실행 근거의 그림 상자가 겹치면(IoU ≥ 0.5), 상자가 없으면 그 쪽에 숨은 층 묶음과 OCR 묶음이 하나씩일 때만 짝짓는다. 차트 캐시와 셀 값은 숫자면 상대 오차 1e-9 안에서 같다. 점이 많아 앞 `xlsx_charts.MAX_POINTS`개만 대조했으면 '부분 검증'이고 완료로 표시하지 않는다. CSV 통과 후보 조건은 실행에 기록된 계약(인코딩·구분자 확정), 모든 레코드의 열 수 보존, 전체 범위 대조, 차이 없음. 원본에서 출발하는 비교만으로는 같은 행의 두 칸 맞바꿈, 빈 칸에 생긴 값, 결과에만 있는 행·복제 행을 놓친다. 비슷한 결과 줄이 없으면 엉뚱한 줄과 '바뀜'으로 짝짓지 않고 있어야 할 자리의 '없음'으로 본다. 글머리 기호는 지우되 번호(1. 2) …)는 남겨 번호 변경을 본다.
- `fidelity`: 기준은 파서와 무관한 OOXML 원본이라 Docling을 다른 파서로 바꿔도 같은 점검을 쓴다. 사본 보정은 해당 XML 조각만 정규식으로 바꾸고(나머지 바이트·네임스페이스 접두어는 그대로), 첨자는 모든 글자를 유니코드 첨자로 바꿀 수 있을 때만 바꾸며 한 run에서 하나라도 실패하면 바꾸지 않는다. 보충 추출은 원래 위치가 아니라 결과 끝에 붙이고 원문 위치를 함께 남긴다. 파싱 성공이 품질 보증이 아니라는 원칙에 따라 고친 것과 고치지 못한 것을 모두 드러낸다. 원본 점검은 보이는 글자의 특수기호, 기호 글꼴·첨자 변환 가능 여부, 병합 셀, 떠 있는 글상자, 흰색에 가까운 글자, 숨김 글자, 그림 종류(래스터·SVG·메타파일)와 겹침, SVG 안의 벡터 글자를 센다. 그림 '속' 글자는 OCR 없이는 알 수 없다.
- `model_bundle`: manifest 없이 손으로 압축한 ZIP도 받되 크기만 확인한다. 빈 파일(받다 만 흔적)만 바꿔 쓴다. 빠진 필수 파일이 있으면 묶지 않고, 설치는 빠진 파일·크기 불일치·기존 파일과의 충돌이 있으면 쓰기 전에 멈춘다.
- `vba`: [MS-OVBA]의 dir 스트림에서 모듈 목록을 얻고 압축된 소스를 풀어 모듈 이름·종류·코드 줄 수와 자동 실행 프로시저를 알린다. 소스 글은 구조 분석이 경로·URL·문서번호 후보를 찾는 데만 쓰고 결과 본문에는 넣지 않는다(문서 내용이 아니라 동작이다). 자동 실행 프로시저는 셀 값이 저장 이후 매크로로 바뀌는 문서를 가려내는 데 쓴다. 빈 시트·통합문서 모듈만 있는 XLSM은 경고하지 않는다.
- `llm`: 환경변수(`MODEL_*`, `MODEL2_*`, `MODEL_CA_BUNDLE`, `MODEL_TIMEOUT` 기본 30초)는 `.env.example`에 있다. API 키는 응답·로그에 내보내지 않는다. `connection_store`: 화면에서 보낸 `api_key`가 문자열이면 바꾸고, `clear_api_key`면 비우고, 없으면 그대로 둔다. OCR 지시문은 비우면 기본값.
- `main`: 새 빌드를 올린 뒤에도 브라우저가 캐시한 옛 `index.html`을 쓰지 않게 매번 다시 확인시키고, `/assets` 파일은 이름에 내용 지문이 있어 캐시해도 된다. 개발 중에는 Vite(5173)를 쓴다.

