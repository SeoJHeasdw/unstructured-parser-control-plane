# unstructured-parser-control-plane

**비정형 관리 콘솔 (Unstructured Data Console)**은 로컬에 저장한 문서의 파싱 결과를 읽고 원문과 대조하는 작업 공간입니다.

- **문서함**에서 파일을 추가하면 원본이 로컬 저장소에 보관됩니다. 문서 상세에서 **파싱 실행**을 누르면 처리가 시작됩니다. 성공본이 한 개면 원문과 추출 결과를 대조하고, 두 개 이상이면 이전·현재 실행의 차이를 검수할 수 있습니다.
- **파서 플로우**에서 실제 등록된 형식별 파서, 로컬 OCR 환경과 해당 형식의 문서를 확인합니다. **모의 경로 설계**를 누르면 같은 형식의 브라우저 시뮬레이터를 엽니다.
- **청킹 비교**에서 원문과 분할 전략을 선택합니다. 문서 상세 또는 파서 플로우에서 완료된 문서의 청킹을 바로 열 수 있습니다.
- **분석 도구**에서 임베딩 평가·문서 계보·벡터 DB·검색 설계 참고를 엽니다. **설정**에서 모델 연결을 확인합니다.
- **예시 둘러보기**에는 준비된 문서의 처리 현황과 원본 검수가 있습니다.

## Windows PC에서 실행

Windows x64에서 실행합니다. 기본 실행은 **Python 3.12~3.15**를 지원합니다(3.11 이하는 지원하지 않음). Docling(PDF·Office 파싱)은 잠금 파일이 3.12 기준이라 **Python 3.12 x64**가 필요합니다. 3.15만 설치돼 있으면 기본 실행은 되고, Docling을 쓰려면 3.12를 함께 설치하세요.

```cmd
winget install --exact --id Python.Python.3.12 --architecture x64
py -3.12 --version
```

| 받은 파일 | 실행 | 첫 설치에 필요한 것 |
|---|---|---|
| 준비된 Windows ZIP | `start.cmd --offline` | Python. 화면과 설치용 휠이 들어 있어 Node, npm 레지스트리, PyPI 접속이 필요 없습니다. |
| GitHub **Code → Download ZIP** | `start.cmd` | Python, Node.js 20.19 이상(20.x) 또는 22.12 이상, npm 레지스트리와 Python 패키지 인덱스 접근. |

1. ZIP을 로컬 폴더에 풀고 새 터미널에서 해당 폴더의 `start.cmd`를 실행합니다. 소스 ZIP은 처음에 `npm ci`로 화면을 빌드하고 가상환경을 준비합니다. npm 또는 pip가 차단된 경우 준비된 Windows ZIP을 사용하세요.
2. 시작 주소는 `http://127.0.0.1:8000/`입니다. 포트가 이미 쓰이고 있으면 `start.cmd 8010`을 실행하세요. 브라우저 없이 준비만 확인하려면 `start.cmd --check`를 사용합니다. 앱을 닫으려면 실행 창에서 `Ctrl+C`를 누릅니다.
3. npm·pip 사내 레지스트리가 있으면 현재 터미널에 `npm_config_registry`와 `PIP_INDEX_URL`을 설정하고 실행합니다. npm·pip의 기존 설정도 사용할 수 있습니다.

### macOS·Linux·WSL·Git Bash: `run.sh`

루트의 `run.sh`는 `start.cmd`와 같은 일을 bash로 합니다. Python 3.12~3.15(Docling은 3.12)와 소스 ZIP이면 Node.js도 필요합니다. 첫 실행에서 `backend/.venv`를 만들어 `requirements.lock.txt`를 설치하고(잠금 파일이 바뀌면 다시 설치), `frontend/dist`가 없으면 `npm ci`와 빌드를 한 뒤, `.env`가 없으면 `.env.example`에서 만들고 서버를 띄웁니다.

```bash
./run.sh                 # 기본 8000번에서 시작하고 브라우저를 엽니다
./run.sh 8010 --no-browser
./run.sh --docling       # PDF·Office 파싱(Python 3.12 가상환경 backend/.venv-docling)
./run.sh --check         # 서버 없이 준비 상태만 확인
./run.sh --rebuild       # 화면 다시 빌드
```

지정한 포트(기본 8000)부터 최대 20개를 확인해 첫 빈 포트에서 시작합니다. 예를 들어 다른 서비스가 8000번을 쓰면 8001번으로 시작하고 해당 주소를 엽니다. 같은 데이터 폴더를 쓰는 콘솔이 이미 실행 중이면 기존 주소를 사용합니다. 새 백엔드 코드나 Python 환경을 적용하려면 기존 실행 창에서 `Ctrl+C`로 종료한 뒤 다시 실행하세요.

사내 인증서 때문에 `UNABLE_TO_VERIFY_LEAF_SIGNATURE`가 나면 `NODE_EXTRA_CA_CERTS=<사내 루트 CA 파일>`(또는 Node 22.15+에서 `NODE_OPTIONS=--use-system-ca`)을, pip는 `PIP_CERT=<같은 파일>`을 설정하고 다시 실행하세요.

### PDF·Office 실제 파싱

기본 설치로 화면, TXT·CSV·MD·LOG 처리, 구조 분석을 사용할 수 있습니다. **PDF·DOCX·PPTX·XLSX 본문 파싱**에는 Docling이 필요하고, PDF에는 로컬 모델 파일도 필요합니다.

- Docling 포함 ZIP은 `start.cmd --offline`만 실행하면 별도 Python 3.12 가상환경을 준비합니다. 모델까지 포함된 ZIP은 PDF에 필요한 파일도 제공합니다. 기본 화면만 확인하려면 `start.cmd --offline --base`를 실행합니다.
- 인터넷이 열려 있는 PC에서는 `start.cmd --docling --check`로 패키지를 먼저 설치하세요. PDF 모델은 다음 명령으로 받습니다. 모델은 기본적으로 사용자 홈의 `.cache/docling/models`에 저장됩니다. 다른 위치의 모델을 쓰려면 `DOCOPS_DOCLING_ARTIFACTS`를 설정하세요. 이후 `start.cmd --docling`으로 시작합니다.

```cmd
backend\.venv-docling\Scripts\docling-tools.exe models download layout tableformer
```

### Windows용 ZIP 만들기

인터넷이 열리는 PC에서 Node.js와 pip가 있는 Python으로 씁니다. Windows에서는 다음 명령을, macOS/Linux에서는 `scripts/prepare-offline.sh`를 같은 옵션으로 실행합니다.

```cmd
py -3.12 scripts\prepare-offline.py
py -3.12 scripts\prepare-offline.py --with-docling-models
```

- 기본 결과는 `offline/unstructured-parser-control-plane-windows.zip`입니다.
- `--with-docling`은 Windows x64용 Python 3.12 Docling 휠을 더한 `-docling.zip`을 만듭니다. `--with-docling-models`는 준비해 둔 레이아웃·표 모델까지 더한 `-docling-models.zip`을 만듭니다.
- `--from-cache`는 설치된 프론트 의존성으로 빌드하고 기존 `offline/wheels` 및 `offline/wheels-docling`을 사용합니다. 준비된 ZIP 자체는 대상 PC의 npm이나 pip 인덱스에 의존하지 않습니다.
- 외부 모델 게이트웨이는 화면의 **설정 › 모델 연결**에서 생성 모델·임베딩 모델별로 주소·모델 ID·API 키를 넣고 저장하면 다시 시작하지 않아도 바로 씁니다(값은 `runtime/settings/connections.json`, `.env`보다 우선). 여러 PC에 같은 값을 배포할 때는 프로젝트 루트 `.env`의 `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_ID`(임베딩은 `EMBED_*`)를 설정한 뒤 다시 시작합니다. 두 번째 연결은 `MODEL2_*`, 사내 인증서는 `MODEL_CA_BUNDLE`, 프록시는 `HTTPS_PROXY`를 사용합니다.

## 개발 실행

서버 두 개를 씁니다. 첫 실행 시 각각 아래 명령을 실행합니다. (`frontend/dist`가 있으면 백엔드만 띄워도 `http://127.0.0.1:8000/`에서 화면이 열립니다.)

### 1. 백엔드

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

TXT·CSV·MD·LOG는 기본 설치만으로 처리할 수 있습니다. **Docling을 사용하려면** 가상환경에서 다음 선택 의존성도 설치하세요.

```bash
pip install -r requirements-docling.lock.txt
```

PDF에는 미리 준비된 Docling 레이아웃·표 모델이 필요합니다. macOS·Linux에서는 Docling 가상환경에서 `docling-tools models download layout tableformer`로 받습니다. 파싱 중에는 모델을 다운로드하지 않습니다.

**OCR은 문서 OCR 모델만 씁니다(2026-11-24 결정).** EasyOCR 같은 라이브러리 OCR 경로는 껐습니다. OCR 모델(OpenAI 호환 비전 API, 고객사 게이트웨이 서빙 예정)을 연결하기 전까지 스캔 PDF는 텍스트 층만 읽고 `OCR 미적용` 경고를 남기며, 글자 층이 없으면 `no_text`로 실패합니다. 이미지 파일과 Office·SVG 안의 그림 글자는 'OCR 모델 미연결'로 처리하지 않습니다. SVG의 벡터 글자와 Office 본문은 그대로 읽습니다. `DOCOPS_OCR`·`DOCOPS_OCR_MODELS`는 더 이상 효과가 없습니다.

PDF에서는 본문 글자나 표가 없는 페이지를 경고합니다.

### 2. 프론트엔드

다른 터미널에서:

```bash
cd frontend
npm ci
npm run dev
```

브라우저에서 [http://127.0.0.1:5173/](http://127.0.0.1:5173/)을 엽니다. 개발 서버는 `/api` 요청을 로컬 백엔드의 8000 포트로 전달합니다. 서버를 종료하면 화면을 새로 띄울 수 없으므로 사용 중에는 두 터미널을 실행 상태로 유지하세요.

## 현재 실제 처리 범위

- 텍스트 입력은 파일당 100 MiB, CSV는 100만 행·1,000열, 셀당 4,194,304자, 물리적 한 줄당 8,388,608자, UTF-8 Markdown 결과 100 MiB까지 처리합니다. 1 MiB 이상의 텍스트와 CSV는 임시 결과 파일에 순차적으로 씁니다.
- 원본은 임의 생성된 ID로 `runtime/uploads/`에 저장하고, 작업 이력은 `runtime/documents.sqlite3`, Markdown 결과는 `runtime/results/`에 저장합니다. 원본 파일명은 표시용 정보로만 사용합니다.
- 전용 워커 1개가 한 번에 문서 1건을 처리하고, 메모리 대기열에는 기본 최대 64건이 추가로 기다립니다. `processing`은 실제 처리와 대기를 모두 포함합니다. 대기열이 가득 차면 새 처리 요청은 HTTP 503으로 거절되고 거절 이력이 남습니다. 동일 문서의 중복 처리 요청은 HTTP 409입니다.
- 정상 종료 시 새 요청을 막고 미실행 대기 작업은 실패 이력과 함께 재시도 가능한 상태로 바꿉니다. 진행 중 작업은 최대 5초 기다리며 그 뒤에도 실행 중이면 워커가 끝날 때까지 데이터 폴더 잠금을 유지합니다. 프로세스가 먼저 종료되면 재시작 시 남은 `processing` 작업을 실패로 기록합니다. 중단된 작업은 자동 재실행하지 않습니다.
- 재처리 중이나 실패 후에도 마지막 성공 결과를 조회할 수 있으며 `is_stale: true`와 함께 표시합니다. 성공 이력이 없거나 저장된 결과를 읽을 수 없으면 결과 조회가 HTTP 409를 반환합니다. 화면은 현재 오류 메시지로 이 두 경우를 구분하며, 안정적인 오류 코드는 향후 과제입니다. 결과 경고는 `warnings`로 반환합니다.
- Docling은 로컬에서 실행합니다. 합성 문서로 본문 보존과 위치를 검증했습니다. OCR은 문서 OCR 모델 연결 후 처리하며 후보 모델을 평가 중입니다.
- **구조 분석**(실제 파일 처리 화면): 원본을 열어 압축 항목·메일 첨부·Office/HWP 내장 개체·PDF 첨부를 하위 문서로 펼치고, 하이퍼링크·외부 통합문서 참조(셀 위치)·필드 연결·공유 폴더 경로·문서번호 후보와 암호화·DRM 의심·확장자 불일치·매크로를 표시합니다. 원본은 바꾸지 않고 디스크에 풀지 않으며 버튼을 눌러야 실행합니다. 결과는 `runtime/structure/`에 저장합니다.
- **파싱 전 판별·원문 대조(2026-11-19):** 처리 전에 내용 서명으로 DRM·암호·확장자 불일치를 걸러 실패 사유 코드(`error_code`)로 남깁니다. DRM은 판별만 하며 해제본이 필요합니다. DOCX·XLSX·PPTX는 임시 사본에서 기호 글꼴·위/아래첨자를 유니코드로 바꿔 파싱하고, 원본과 대조해 특수기호 손실·병합 셀·흰회색 글자·읽지 않은 그림을 경고하며 빠진 글상자·SVG 글자는 결과 끝에 보충합니다.
- 형식 선택은 현재 확장자 기반이며, ZIP/메일 첨부 분해·XLSX 외부 참조 추출·검색 인덱싱은 아직 구현하지 않았습니다. 모델은 연결 확인과 목록 조회만 하며 문서 처리 단계에서는 호출하지 않습니다.
- `runtime/`은 Git에서 제외합니다. 실제 파일, 추출 결과, API 키를 저장소에 올리지 마세요. 현재는 **로컬 단일 사용자용 프로토타입**이며 인증·문서별 권한·파일 삭제 화면을 제공하지 않습니다.

## 작업 에이전트 도구 (OpenCode MCP · CLI)

콘솔을 띄운 뒤 OpenCode 같은 에이전트가 문서를 등록·파싱하고 짧은 보고서를 만들 수 있습니다. 표준 라이브러리만 쓰므로 추가 설치는 없습니다.

```bash
py -3.12 backend/docops.py init-workspace "C:/work/docops-agent" --roots "C:/work/samples"   # OpenCode 작업 폴더 만들기
python backend/docops.py status                                                                # CLI로 직접 쓰기
```

도구 목록, 설정 이유, 보고서 코드표는 [작업 에이전트 도구](docs/AGENT_TOOLS.md)를 보세요.

## 구조와 확인

다른 세션에서 이어갈 때는 [인수인계와 실행 안내](docs/HANDOFF_AND_RUNBOOK.md)부터 읽으세요. 화면·API 계약과 설계 문서는 [문서 안내](docs/README.md)에 모았습니다. [아키텍처 문서](docs/ARCHITECTURE.md)에는 전체 구조와 현재/향후 범위가 있습니다.

```bash
# 프론트 검사
cd frontend
npm test
npm run build
```

```bash
# 백엔드 검사
cd backend
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
```
