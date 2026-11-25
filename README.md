# 비정형 관리 콘솔 (Unstructured Data Console)

문서를 로컬에 저장해 파싱하고, 추출 결과를 원문과 대조·검수하는 작업 화면입니다. PC 한 대에서 쓰는 **로컬 프로토타입**이며 인증·권한 기능은 없습니다.

## 빠른 시작

**이미 설치한 Windows PC**에서는 실행 중인 콘솔을 닫고 GitHub **Code → Download ZIP**을 받습니다. 압축을 푼 폴더 안의 파일과 폴더를 기존 `run.cmd`가 있는 폴더에 복사하고 **모두 덮어쓰기**를 선택합니다. **`setup.cmd` → `run.cmd`** 순서로 실행하면 업데이트가 끝납니다. OpenCode를 쓸 때는 설치 폴더 안의 **`OpenCode`** 폴더를 엽니다. MCP 설정은 준비 단계에서 자동으로 생성됩니다.

**1. 준비물 설치 (Windows, 처음 한 번)**

```cmd
winget install --exact --id Python.Python.3.12 --architecture x64
winget install --exact --id OpenJS.NodeJS.LTS
```

설치한 뒤 **새 터미널**을 엽니다. Node.js(20.19 이상 또는 22.12 이상)는 화면을 빌드할 때만 필요하며, [오프라인 ZIP](#인터넷이-없는-pc-오프라인-zip)에는 빌드된 화면이 들어 있어 없어도 됩니다.

**2. 설치: 처음 한 번, 그리고 코드를 업데이트할 때마다**

```cmd
setup.cmd
```

다음을 한 번에 처리합니다. 처음에는 Docling 때문에 몇 분 걸리고, 다시 실행하면 바뀐 것만 처리하므로 금방 끝납니다.

1. Python 가상환경 `backend\.venv`를 만들고 패키지를 설치합니다(Docling 포함).
2. 화면을 빌드하고, `.env`가 없으면 `.env.example`로 만듭니다.
3. PDF 모델(레이아웃·표)을 받습니다. `huggingface.co`에 접속해야 합니다. 받기 전에 10초 안에 접속되는지 확인하고, 막혀 있으면 받지 않고 원인을 한 줄로 알려 줍니다. 받지 못해도 설치는 계속합니다. 이 경우 PDF는 레이아웃·표 모델 없이 **글자 층만** 읽습니다(아래 '파싱' 참고). 받지 못한 것은 **setup 마지막 요약에 `[주의]`로 다시 표시**되고, `run`을 띄울 때도 한 줄로 알려 줍니다. `huggingface.co`가 막힌 PC는 [아래 절](#huggingfaceco가-막힌-pc-pdf-모델-zip으로-옮기기)처럼 다른 PC에서 만든 모델 ZIP으로 설치합니다.
4. 합성 CSV로 파싱과 청킹을 시험합니다. 시험은 임시 저장소에서 하므로 문서함에는 아무것도 남지 않습니다.

**3. 실행: 매번**

```cmd
run.cmd
```

브라우저에서 `http://127.0.0.1:8000/`이 열리고, 종료는 실행 창에서 `Ctrl+C`로 합니다. `run`은 설치나 네트워크 접속을 하지 않고 준비 상태만 확인합니다. 코드가 바뀌어 다시 설치해야 하면 "setup을 다시 실행하세요"라고 알려 줍니다.

## 옵션

| 명령 | 옵션 | 하는 일 |
|---|---|---|
| setup | (없음) | **전체 모드.** Docling을 넣어 PDF·DOCX·PPTX·XLSX·XLSM과 TXT·CSV·MD·LOG를 모두 파싱합니다. Python 3.12가 필요합니다. |
| setup | `--lite` | **가벼운 모드.** Docling 없이 TXT·CSV·MD·LOG만 파싱합니다. Python 3.12~3.15에서 되며, 화면만 볼 때나 3.12가 없는 PC용입니다. |
| setup | `--offline` | 준비된 ZIP에 든 휠과 화면 빌드만 씁니다(네트워크 없음). |
| setup | `--models <ZIP>` | PDF 모델을 받지 않고, 다른 PC에서 만든 모델 ZIP(또는 모델 폴더)을 검증해 설치합니다. `huggingface.co`가 막힌 PC용입니다. |
| run | `8010` | 시작 포트를 지정합니다(기본 8000). 쓰는 중이면 다음 빈 포트로 넘어가며 최대 20개까지 찾습니다. |
| run | `--no-browser` | 브라우저를 열지 않습니다. |

- 모드는 setup에서 정하고 기록되므로 run에는 모드 옵션이 없습니다.
- 가상환경은 `backend\.venv` 하나입니다. 전체 모드로 설치한 뒤 `setup --lite`를 실행하면 다시 설치하지 않습니다.
- 콘솔이 켜져 있으면 setup이 멈춥니다. Windows에서는 실행 중인 파일이 잠겨 설치가 중간에 깨질 수 있기 때문입니다.

## huggingface.co가 막힌 PC: PDF 모델 ZIP으로 옮기기

PDF 파싱에 쓰는 Docling 레이아웃·표 모델은 `huggingface.co`에서 받습니다. PyPI·npm은 열려 있어도 `huggingface.co`만 막힌 PC에서는 setup 요약에 `[주의] PDF 모델: https://huggingface.co 에 접속되지 않습니다(…)`가 뜹니다. DOCX·PPTX·XLSX·XLSM·텍스트 파싱은 모델이 없어도 됩니다.

**1. `huggingface.co`에 접속되는 PC에서 모델 ZIP 만들기** (이 프로젝트를 setup한 PC. 모델은 setup 때 받아 둡니다)

```cmd
backend\.venv\Scripts\python.exe scripts\prepare-offline.py --models-only
```

macOS·Linux는 `backend/.venv/bin/python scripts/prepare-offline.py --models-only`입니다. `offline\docling-pdf-models.zip`이 생깁니다. 모델 파일과 파일별 SHA-256을 적은 `manifest.json`이 들어 있습니다. 화면 빌드나 휠은 만들지 않습니다.

**2. ZIP을 막힌 PC로 옮겨 설치하기**

```cmd
setup.cmd --models C:\경로\docling-pdf-models.zip
```

- 평소 setup과 같고, 모델만 받지 않고 ZIP에서 설치합니다. 이미 setup을 마친 PC면 바뀐 것만 처리하므로 금방 끝납니다.
- 파일마다 크기와 SHA-256을 확인합니다. 옮기다 깨진 ZIP은 설치하지 않습니다.
- 설치 위치는 콘솔이 모델을 찾는 폴더입니다: `.env`의 `DOCOPS_DOCLING_ARTIFACTS` → 프로젝트의 `offline\docling-models`(있을 때) → `%USERPROFILE%\.cache\docling\models`. 보통은 마지막 위치이며, 사용자 폴더 아래라 프로젝트 폴더를 지우고 다시 받아도 남습니다.
- 그 폴더에 **내용이 다른 모델 파일**이 이미 있으면 덮어쓰지 않고 멈춥니다. 같은 파일은 건너뛰고, 받다 만 빈 파일만 바꿔 씁니다.
- 모델 캐시 폴더(`.cache\docling\models`)를 손으로 압축한 ZIP이나 그 폴더 경로를 줘도 됩니다. 이때는 SHA-256 기록이 없어 크기만 확인합니다.
- 사내에 Hugging Face 미러(프록시 저장소)가 있으면 `.env`에 `HF_ENDPOINT=<미러 주소>`를 넣고 setup을 다시 실행하는 방법도 있습니다. 미러 여부는 고객사에 확인이 필요합니다.

## 화면

- **문서함**: 파일을 추가하면 원본이 로컬 저장소에 보관됩니다. 처리는 문서 상세에서 **파싱 실행**을 눌러야 시작됩니다. 성공한 실행이 하나면 원문과 결과를 대조하고, 둘 이상이면 실행 간 차이를 검수합니다.
  - 추출 결과는 **읽기 보기**(표·제목·목록을 그림)와 **Markdown 원문**(저장된 글자 그대로)을 오갑니다.
  - 원문 대조의 원본 칸은 PDF·엑셀 셀·텍스트·이미지와 함께 **DOCX·PPTX도 브라우저 안에서 다시 그려** 보여 줍니다(파일을 밖으로 보내지 않음). Word·PowerPoint와 글꼴·줄바꿈이 다를 수 있으니 정확한 배치는 원본 다운로드로 확인합니다.
  - **폴더에서 가져오기**: 브라우저로 파일을 보내지 않고, 콘솔 서버가 이 PC의 **허용 폴더**에서 직접 읽어 저장합니다. 보안 프로그램 때문에 브라우저 파일 첨부가 막힌 PC에서 씁니다(아래 절).
- **파서 플로우**: 형식별로 실제 연결된 파서와 OCR 모델 연결 상태를 보여 줍니다. **모의 경로 설계**는 브라우저 안에서만 도는 시뮬레이터이며, 실제 라우팅에는 반영되지 않습니다.
- **청킹 비교**: 완료된 문서에 여러 분할 전략을 적용해 비교합니다.
- **분석 도구**: 임베딩 평가, 문서 계보, 벡터 DB, 검색 설계 참고를 엽니다.
- **설정**: 모델 연결을 관리합니다.
- **예시 둘러보기**: 준비된 예시 데이터입니다. 대시보드·파이프라인·관계도의 수치는 **예시이며 실제 처리와 분리**되어 있습니다.

## 브라우저 파일 첨부가 막힌 PC: 허용 폴더에서 가져오기

"보안정책에 의거 파일첨부 … 파일전송이 통제됩니다" 같은 안내가 뜨는 PC는 브라우저가 파일을 고르거나 보내는 동작 자체가 막혀 있습니다. 콘솔의 문제가 아니며, 화면에서 우회하지 않습니다. 대신 문서함의 **폴더에서 가져오기**를 씁니다.

1. 허용 폴더를 `.env`에 적습니다. 여러 개는 `;`로 구분합니다. 비워 두면 프로젝트의 `samples` 폴더(합성 예시 말뭉치)를 씁니다.
   ```
   DOCOPS_AGENT_ROOTS=C:\docs\검증문서
   ```
2. `run.cmd`를 다시 실행합니다(`.env`는 시작할 때 읽습니다).
3. 문서함 › **폴더에서 가져오기**에서 폴더를 열고 파일을 고른 뒤 **가져오기**를 누릅니다. **하위 폴더 포함**을 켜면 아래 폴더의 파일까지 한 목록에 나오고, 맨 위 체크 상자는 파서가 있고 문서함에 아직 없는 파일만 고릅니다.
4. 결과 창에서 **N개 파싱 실행**을 누르거나, 문서 상세에서 하나씩 파싱합니다. 가져오기만으로는 파싱하지 않습니다.

- 콘솔 서버가 파일을 `runtime/`으로 **복사**합니다. 원본 폴더의 파일은 그대로입니다. 허용 폴더 밖, 숨김·잠금 파일(`.`·`~$`로 시작), 빈 파일, 크기 제한(100MB)을 넘는 파일은 가져오지 않습니다.
- 이름·크기·내용(SHA-256)이 같은 원본이 이미 있으면 새로 만들지 않고 그 문서를 씁니다.
- 허용 폴더는 `.env`로만 바꿀 수 있고 화면에서는 바꿀 수 없습니다. 작업 도구(`docops.py`·OpenCode)와 같은 설정 이름이지만, OpenCode는 작업 폴더에 지정한 값이 있으면 우선 사용합니다.
- 고객사 보안 정책이 "로컬 프로그램이 지정 폴더의 파일을 읽는 것"까지 허용하는지는 확인하지 않았습니다.

## 모델 연결 (OCR · 생성 · 임베딩)

- 화면의 **설정 › 모델 연결**에서 주소, 모델 ID, API 키를 넣고 저장하면 재시작 없이 바로 적용됩니다. 저장 위치는 `runtime/settings/connections.json`이고, `.env`보다 우선합니다.
- 여러 PC에 같은 값을 넣을 때는 루트의 `.env`에 `MODEL_*`·`EMBED_*`·`OCR_*`를 적고 서버를 다시 시작합니다. 항목 설명은 [`.env.example`](.env.example)에 있습니다. 사내 인증서는 `MODEL_CA_BUNDLE`, 프록시는 `HTTPS_PROXY`로 지정합니다.
- **OCR은 문서 OCR 모델만 씁니다(2026-11-24 결정).** OpenAI 호환 비전 API로 연결하며, EasyOCR 같은 라이브러리 OCR은 쓰지 않습니다.
  - 연결하면 PDF의 글자 층 없는 쪽, 쪽 면적의 10% 이상을 차지하는 그림, 이미지 파일(PNG·JPEG·BMP·TIFF·GIF·WebP), Office·SVG 속 그림을 읽습니다. OCR로 읽은 결과에는 항상 원본 대조 경고가 붙습니다.
  - 연결 전에는 스캔 PDF의 글자 층만 읽고 `OCR 미적용` 경고를 남깁니다. 글자 층이 없으면 `no_text`로 실패합니다. 이미지 파일은 'OCR 모델 미연결'로 처리하지 않습니다.
  - 호출 방식은 두 가지입니다. `region`은 Docling 레이아웃 영역마다, `page`는 쪽 전체를 한 번 호출합니다. 후보 모델 비교는 [OCR 모델 비교](docs/reports/ocr-bench/README.md)에 있습니다.

## 지금 버전의 제약

**사용 범위**
- 서버는 `127.0.0.1`에서만 받으므로 **실행한 PC에서만 접속**할 수 있습니다. 인증, 문서별 권한, 파일 삭제 화면이 없습니다.
- 실제 원본·결과·이력은 `runtime/`에 저장됩니다(`DOCOPS_RUNTIME_DIR`로 바꿀 수 있음). Git에는 올리지 않습니다.

**파싱**
- 파서는 확장자로 고릅니다. TXT·CSV·MD·LOG는 내장 파서, PDF·DOCX·PPTX·XLSX·XLSM은 Docling(PDF 모델이 없으면 PDF는 글자 층 파서), 이미지는 OCR 모델이 맡습니다. HWP/HWPX, ZIP 안 파일, 메일 첨부는 본문을 파싱하지 않고 구조 분석에서 목록만 보여 줍니다. 지원하지 않는 형식은 `unsupported`가 됩니다.
- **파싱 성공이 품질 보증은 아닙니다.** Docling 결과는 합성 문서로만 확인했고, 실제 고객 문서 품질은 아직 평가하지 않았습니다. 복잡한 표나 원문 위치가 정확하다고 보장하지 않습니다.
- 파서를 부르기 전에 내용 서명을 확인합니다. DRM, 암호, 확장자 불일치는 사유 코드(`error_code`)를 붙여 실패로 남깁니다. DRM은 판별만 하므로 해제본이 필요합니다.
- DOCX·XLSX·XLSM·PPTX는 사본에서 기호 글꼴과 첨자를 보정한 뒤 파싱합니다. 원문과 대조해 특수기호 손실, 병합 셀, 흰색 글자, 읽지 않은 그림을 경고합니다.
- **XLSM(매크로 사용 통합문서)** 은 셀과 표를 XLSX와 같이 읽습니다. **매크로는 실행하지 않고** 코드도 결과 본문에 넣지 않습니다. 코드가 든 VBA 모듈이 있으면 모듈 수·줄 수와 "셀 값은 파일에 마지막으로 저장된 값"이라는 경고를 남기고, 열 때 자동 실행되는 프로시저(`Workbook_Open`·`Auto_Open` 등)가 있으면 함께 알립니다. 모듈 목록과 매크로 코드 속 경로·URL·문서번호 후보는 문서 상세의 **구조 분석**에서 봅니다.
- **PDF 모델이 없을 때(고객사 PC 기본):** PDF는 레이아웃·표 모델 없이 **글자 층만** 읽습니다(파서 `pdf-text`, pypdfium2). 쪽 위치는 남지만 표는 칸 구조 없이 줄 글자로 나오고, 여러 단 문서는 읽는 순서가 섞일 수 있어 결과에 항상 경고가 붙습니다. 글자 층이 없는 쪽은 OCR 모델을 연결했으면 그 모델로 읽고, 글꼴 문제로 글자 층이 깨진 쪽은 따로 경고합니다. 모델 파일이 준비되면 다시 Docling으로 파싱합니다.
- **결과 보강:** XLSX·XLSM은 시트마다 `## 시트: 이름` 제목을 넣고, PPTX는 슬라이드 번호를 원문 위치로 남기며 발표자 메모를 슬라이드 끝에 `> 발표자 메모(슬라이드 N): …`로 붙입니다(Docling은 메모를 버림). 목록 바로 뒤에 붙은 표 앞에는 빈 줄을 넣습니다. DOCX 각주·미주가 결과에 없으면 `보충 추출`에 `각주 N`으로 덧붙입니다.
- 재처리 중이거나 실패한 뒤에도 마지막 성공본을 볼 수 있으며, 이때 `is_stale`로 표시됩니다.

**처리 한도**
- 파일당 100 MiB, CSV 100만 행·1,000열, 셀당 4,194,304자, 한 줄당 8,388,608자, Markdown 결과 100 MiB까지 처리합니다.
- 워커 1개가 한 번에 1건을 처리하고, 64건까지 대기합니다. 대기열이 넘치면 503, 같은 문서를 중복 요청하면 409를 돌려줍니다.
- 서버를 종료하면 대기 중이던 작업은 실패로 바뀝니다. 자동으로 다시 실행하지 않으므로 직접 다시 실행해야 합니다.

**외부로 나가는 데이터**
- 파싱 중에는 OCR 모델을 연결한 경우에만 이미지가 그 모델로 전송됩니다.
- 화면에서 의미 기반 청킹이나 임베딩 평가를 실행하면 임베딩 모델을 호출합니다.
- 그 밖에는 외부로 보내지 않습니다. Docling 모델도 파싱 중에는 내려받지 않습니다.

## 문제 해결

| 증상 | 해결 |
|---|---|
| `아직 설치되지 않았습니다` | `setup.cmd`를 먼저 실행합니다. |
| `패키지 목록이 바뀌었습니다` / `화면 코드가 바뀌었습니다` | 코드를 업데이트한 뒤에 나옵니다. `setup.cmd`를 다시 실행합니다(lite로 쓰던 PC는 `--lite`). |
| `frontend/dist 를 어느 코드로 만들었는지 기록이 없습니다` | 예전 실행기(`start.cmd`)가 남긴 화면 빌드입니다. 그대로 쓰면 코드를 업데이트해도 **옛 화면**이 뜹니다. `setup.cmd`가 Node.js로 다시 빌드합니다. Node.js가 없는 PC는 Node.js를 설치하거나 같은 코드로 만든 오프라인 ZIP을 씁니다. |
| 실행 창에 `GET /health … 404 Not Found`가 찍힘 | 콘솔이 보내는 요청이 아닙니다(콘솔의 상태 확인 주소는 `/api/health`이고, Milvus를 쓰지 않아도 이 요청은 생기지 않습니다). 이 PC의 다른 프로그램이 같은 포트를 자기 서버로 알고 확인하는 것입니다. 콘솔에는 영향이 없습니다. 어떤 프로그램인지는 리소스 모니터(`resmon`) › 네트워크 › TCP 연결에서 그 포트로 찾습니다. 그 프로그램이 원래 8000번을 써야 한다면 `run.cmd 8010`처럼 다른 포트로 띄웁니다. |
| 파일 추가 때 `보안정책에 의거 파일첨부 ActiveX 실행 및 파일전송이 통제됩니다` | PC의 보안 프로그램이 브라우저의 파일 첨부·전송을 막는 것입니다. 문서함의 **폴더에서 가져오기**를 씁니다([위 절](#브라우저-파일-첨부가-막힌-pc-허용-폴더에서-가져오기)). |
| 업데이트했는데 화면이 옛날 그대로 | 실행 창의 `[run] 화면 빌드: <시각>`이 방금 setup한 시각인지 봅니다. 맞으면 브라우저 캐시이므로 `Ctrl+Shift+R`(Windows `Ctrl+F5`)로 새로 고칩니다. 이 버전부터 서버는 화면의 시작 파일을 캐시하지 않게 보냅니다. |
| `콘솔이 실행 중입니다` | 콘솔 실행 창에서 `Ctrl+C`로 끈 뒤 setup을 다시 실행합니다. |
| `Docling(PDF·Office 파싱)에는 Python 3.12가 필요합니다` | Python 3.12를 설치하고 새 터미널에서 다시 실행합니다. 당장 화면만 띄우려면 `setup.cmd --lite`를 씁니다. |
| `backend/.venv 는 Python 3.13 입니다` | 예전에 다른 버전으로 만든 환경입니다. `backend\.venv` 이름을 바꾸고(예: `.venv-py313`) setup을 다시 실행합니다. |
| setup 요약에 `[주의] PDF 모델`이 뜸, 또는 PDF 결과에 `글자 층만 읽었습니다` 경고 | `huggingface.co`가 막혀 있으면(요약에 `접속되지 않습니다`) 다른 PC에서 만든 모델 ZIP을 `setup.cmd --models <ZIP>`으로 설치합니다([위 절](#huggingfaceco가-막힌-pc-pdf-모델-zip으로-옮기기)). 접속되는 PC라면 setup을 다시 실행합니다. 다른 위치의 모델 폴더를 쓰려면 `.env`의 `DOCOPS_DOCLING_ARTIFACTS`로 지정합니다. |
| `setup --models` 가 `내용이 다른 모델 파일이 이미 있어` 멈춤 | 설치 위치에 다른 버전의 모델이 있습니다. 콘솔은 그 파일을 지우지 않습니다. 직접 옮기거나 지운 뒤 다시 실행하거나, `.env`의 `DOCOPS_DOCLING_ARTIFACTS`로 빈 폴더를 지정합니다. |
| 인증서 오류(`UNABLE_TO_VERIFY_LEAF_SIGNATURE`, pip SSL) | npm은 `NODE_EXTRA_CA_CERTS=<사내 루트 CA 파일>`(Node 22.15 이상이면 `NODE_OPTIONS=--use-system-ca`도 가능), pip는 `PIP_CERT=<같은 파일>`을 설정합니다. |
| 사내 패키지 미러를 써야 함 | `npm_config_registry`와 `PIP_INDEX_URL`을 설정합니다. |
| 설치 도중 끊기거나 시간이 초과됨 | setup을 다시 실행하면 끝난 부분은 남아 있어 이어서 설치합니다. |
| 다른 PC에서 접속이 안 됨 | 이 PC에서만 접속하도록 만들어져 있습니다(위 제약 참고). |
| 주소의 포트가 8000이 아님 | 실행 창에 표시된 주소로 접속합니다. 같은 데이터 폴더를 쓰는 콘솔이 이미 떠 있으면 그 주소가 열립니다. |

## 인터넷이 없는 PC (오프라인 ZIP)

인터넷이 되는 PC에서 ZIP을 만들어 대상 PC로 옮깁니다. 만드는 PC에는 Node.js와 Python 3.12가 필요하고, macOS·Linux에서는 `scripts/prepare-offline.sh`에 같은 옵션을 줍니다.

| 만드는 명령 | 결과 ZIP | 대상 PC에서 설치 |
|---|---|---|
| `py -3.12 scripts\prepare-offline.py --with-docling-models` (권장, 이 PC에서 먼저 setup으로 모델을 받아 둠) | `…-windows-docling-models.zip`: Docling·PDF 모델 포함 | `setup.cmd --offline` |
| `py -3.12 scripts\prepare-offline.py --with-docling` | `…-windows-docling.zip`: Docling 포함, PDF 모델 제외 | `setup.cmd --offline` |
| `py -3.12 scripts\prepare-offline.py` | `…-windows.zip`: 기본 묶음, Docling 없음 | `setup.cmd --offline --lite` |

- ZIP은 `offline\` 폴더에 만들어집니다.
- PyPI·npm은 되는데 `huggingface.co`만 막힌 PC는 전체 ZIP 대신 모델만 묶는 `--models-only`가 간단합니다([위 절](#huggingfaceco가-막힌-pc-pdf-모델-zip으로-옮기기)).
- 대상 PC에는 Python만 있으면 됩니다. Docling을 쓰는 묶음은 3.12, 기본 묶음은 3.12~3.15가 필요하며, Node·npm·PyPI 접속은 필요 없습니다.
- 설치한 뒤 실행은 똑같이 `run.cmd`입니다.
- `--from-cache`를 주면 이미 설치된 `node_modules`와 기존 `offline\wheels*` 폴더로 다시 만듭니다.
- ZIP의 화면 빌드에는 빌드 기록(`frontend\dist\docops-build.json`: 소스 파일별 지문과 빌드 시각)이 들어갑니다. `setup --offline`은 기록이 ZIP 안의 화면 소스와 맞는 빌드만 쓰므로, 예전 ZIP의 화면이나 옛 설치에 남은 빌드는 쓰지 않습니다.

## 개발자용

**개발 서버**(화면 핫 리로드)는 먼저 `./setup.sh`로 `.venv`를 준비한 뒤 띄웁니다. Windows에서는 `backend\.venv\Scripts\python.exe`를 씁니다.

```bash
cd backend && .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000   # 터미널 1
cd frontend && npm run dev                                                        # 터미널 2 → http://127.0.0.1:5173/
```

개발 서버는 `/api` 요청을 8000번 포트로 넘깁니다. 설치와 실행 로직은 [`scripts/console.py`](scripts/console.py) 하나에 있고, `setup.*`·`run.*`는 Python을 찾아 이 파일을 부르기만 하는 얇은 래퍼입니다.

**테스트**

```bash
cd frontend && npm test && npm run build
cd backend && .venv/bin/python -m pip install -r requirements-dev.txt && .venv/bin/python -m pytest -q
```

**OpenCode에서 첫 시험**은 설치 폴더 안의 `OpenCode`를 열고 “연결을 확인해줘”라고 요청하면 됩니다. 필요한 경우 [연결 진단과 파싱 실험](docs/AGENT_TOOLS.md)을 참고하세요.

**문서**: 이어서 작업할 때는 [인수인계와 실행 안내](docs/HANDOFF_AND_RUNBOOK.md)부터 읽습니다. 구조는 [아키텍처](docs/ARCHITECTURE.md), API는 [백엔드 README](backend/README.md), 나머지는 [문서 안내](docs/README.md)에 있습니다.
