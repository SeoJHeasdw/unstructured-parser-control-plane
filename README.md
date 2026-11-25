# 비정형 관리 콘솔 (Unstructured Data Console)

문서를 로컬에 저장해 파싱하고, 추출 결과를 원문과 대조·검수하는 작업 화면입니다. PC 한 대에서 쓰는 **로컬 프로토타입**이며 인증·권한 기능은 없습니다.

## 빠른 시작 (Windows)

**1. 준비물 설치 (처음 한 번)**

```cmd
winget install --exact --id Python.Python.3.12 --architecture x64
winget install --exact --id OpenJS.NodeJS.LTS
```

설치 후 **새 터미널**을 엽니다. Node.js는 화면을 빌드할 때만 필요합니다(20.19 이상 또는 22.12 이상). [오프라인 ZIP](#인터넷이-없는-pc-오프라인-zip)을 받았다면 설치하지 않아도 됩니다.

**2. 설치와 점검 (처음 한 번, 몇 분 걸림)**

```cmd
start.cmd --check
```

Python 패키지(Docling 포함)와 화면을 설치한 뒤, 합성 CSV로 파싱·청킹을 시험합니다. 시험은 임시 저장소에서 하므로 문서함에는 아무것도 남지 않습니다.

**3. PDF 모델 받기 (처음 한 번)**

```cmd
backend\.venv\Scripts\docling-tools.exe models download layout tableformer
```

PDF 파싱에 쓰는 레이아웃·표 모델을 `%USERPROFILE%\.cache\docling\models`에 받습니다. 파싱하는 중에는 모델을 내려받지 않으므로, 이 단계를 건너뛰면 PDF 파싱이 실패합니다. Office 문서는 이 모델 없이도 파싱됩니다.

**4. 실행**

```cmd
start.cmd
```

브라우저에서 `http://127.0.0.1:8000/`이 열립니다. 종료할 때는 실행 창에서 `Ctrl+C`를 누릅니다.

> **macOS·Linux·Git Bash**에서는 `start.cmd` 대신 `./run.sh`를 같은 옵션으로 씁니다. 3단계 명령은 `backend/.venv/bin/docling-tools`이고, Windows의 Git Bash에서는 `backend/.venv/Scripts/docling-tools.exe`입니다.

## 실행 옵션

| 옵션 | 하는 일 |
|---|---|
| (없음) | **전체 모드.** Docling까지 설치해 PDF·DOCX·PPTX·XLSX와 TXT·CSV·MD·LOG를 모두 파싱합니다. Python 3.12가 필요합니다. |
| `--lite` | **가벼운 모드.** Docling 없이 TXT·CSV·MD·LOG만 파싱합니다. Python 3.12~3.15에서 동작하며, 화면만 볼 때나 3.12가 없는 PC에서 씁니다. |
| `--check` | 서버는 띄우지 않고 설치와 점검만 합니다. |
| `8010` | 시작 포트를 지정합니다(기본 8000). 이미 쓰는 포트면 다음 빈 포트를 찾고, 최대 20개까지 시도합니다. |
| `--no-browser` | 브라우저를 열지 않습니다. |
| `--offline` | 준비된 ZIP에 든 파일로만 설치합니다(`start.cmd` 전용). |
| `--rebuild` | 화면을 다시 빌드합니다(`run.sh` 전용). |

두 모드는 같은 가상환경 `backend\.venv`를 씁니다. 전체 모드로 설치한 뒤 `--lite`로 띄우면 다시 설치하지 않습니다. 두 번째 실행부터는 바뀐 것만 설치하므로 금방 뜹니다.

## 화면

- **문서함**: 파일을 추가하면 원본이 로컬 저장소에 보관됩니다. 처리는 문서 상세에서 **파싱 실행**을 눌러야 시작됩니다. 성공한 실행이 하나면 원문과 결과를 대조하고, 둘 이상이면 실행 간 차이를 검수합니다.
- **파서 플로우**: 형식별로 실제 연결된 파서와 OCR 모델 연결 상태를 보여 줍니다. **모의 경로 설계**는 브라우저 안에서만 도는 시뮬레이터이며, 실제 라우팅에는 반영되지 않습니다.
- **청킹 비교**: 완료된 문서에 여러 분할 전략을 적용해 비교합니다.
- **분석 도구**: 임베딩 평가, 문서 계보, 벡터 DB, 검색 설계 참고를 엽니다.
- **설정**: 모델 연결을 관리합니다.
- **예시 둘러보기**: 준비된 예시 데이터입니다. 대시보드·파이프라인·관계도의 수치는 **예시이며 실제 처리와 분리**되어 있습니다.

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
- 파서는 확장자로 고릅니다. TXT·CSV·MD·LOG는 내장 파서, PDF·DOCX·PPTX·XLSX는 Docling, 이미지는 OCR 모델이 맡습니다. HWP/HWPX, ZIP 안 파일, 메일 첨부는 본문을 파싱하지 않고 구조 분석에서 목록만 보여 줍니다. 지원하지 않는 형식은 `unsupported`가 됩니다.
- **파싱 성공이 품질 보증은 아닙니다.** Docling 결과는 합성 문서로만 확인했고, 실제 고객 문서 품질은 아직 평가하지 않았습니다. 복잡한 표나 원문 위치가 정확하다고 보장하지 않습니다.
- 파서를 부르기 전에 내용 서명을 확인합니다. DRM, 암호, 확장자 불일치는 사유 코드(`error_code`)를 붙여 실패로 남깁니다. DRM은 판별만 하므로 해제본이 필요합니다.
- DOCX·XLSX·PPTX는 사본에서 기호 글꼴과 첨자를 보정한 뒤 파싱합니다. 원문과 대조해 특수기호 손실, 병합 셀, 흰색 글자, 읽지 않은 그림을 경고합니다.
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
| `Docling ... needs Python 3.12` | Python 3.12를 설치하고 새 터미널에서 다시 실행합니다. 당장 화면만 띄우려면 `--lite`를 씁니다. |
| `backend\.venv uses Python 3.13` | 예전에 다른 버전으로 만든 환경입니다. `backend\.venv` 이름을 바꾸고(예: `.venv-py313`) 다시 실행합니다. |
| `backend\.venv-docling is no longer used` | 예전 방식의 환경이라 이제 쓰지 않습니다. 확인한 뒤 지워도 됩니다. |
| 인증서 오류(`UNABLE_TO_VERIFY_LEAF_SIGNATURE`, pip SSL) | npm은 `NODE_EXTRA_CA_CERTS=<사내 루트 CA 파일>`(Node 22.15 이상이면 `NODE_OPTIONS=--use-system-ca`도 가능), pip는 `PIP_CERT=<같은 파일>`을 설정합니다. |
| 사내 패키지 미러를 써야 함 | `npm_config_registry`와 `PIP_INDEX_URL`을 설정합니다. |
| 설치 도중 끊기거나 시간이 초과됨 | 다시 실행합니다. 끝난 부분은 남아 있어 이어서 설치합니다. |
| PDF만 실패하고 '모델 파일 누락'이 뜸 | [3단계](#빠른-시작-windows)에서 모델을 받습니다. 모델을 다른 위치에 두었다면 `DOCOPS_DOCLING_ARTIFACTS`를 설정합니다. |
| 다른 PC에서 접속이 안 됨 | 이 PC에서만 접속하도록 만들어져 있습니다(위 제약 참고). |
| 주소의 포트가 8000이 아님 | 실행 창에 표시된 주소로 접속합니다. 같은 데이터 폴더를 쓰는 콘솔이 이미 떠 있으면 그 주소가 열립니다. |
| 코드를 업데이트했는데 반영되지 않음 | `Ctrl+C`로 끄고 다시 실행합니다. 화면 코드가 바뀌었다면 `frontend\dist`를 지우고 실행합니다(`run.sh`는 `--rebuild`). |

## 인터넷이 없는 PC (오프라인 ZIP)

인터넷이 되는 PC에서 ZIP을 만들어 대상 PC로 옮깁니다. 만드는 PC에는 Node.js와 Python 3.12가 필요합니다. macOS·Linux에서는 `scripts/prepare-offline.sh`에 같은 옵션을 줍니다.

| 만드는 명령 | 결과 ZIP | 대상 PC에서 실행 |
|---|---|---|
| `py -3.12 scripts\prepare-offline.py --with-docling-models` (권장, 먼저 [3단계](#빠른-시작-windows)로 모델을 받아 둠) | `…-windows-docling-models.zip`: Docling과 PDF 모델 포함 | `start.cmd --offline` |
| `py -3.12 scripts\prepare-offline.py --with-docling` | `…-windows-docling.zip`: Docling 포함, PDF 모델 제외 | `start.cmd --offline` |
| `py -3.12 scripts\prepare-offline.py` | `…-windows.zip`: 기본 묶음, Docling 없음 | `start.cmd --offline --lite` |

ZIP은 `offline\` 폴더에 만들어집니다. 대상 PC에는 Python만 있으면 됩니다. Docling을 쓰는 묶음은 3.12, 기본 묶음은 3.12~3.15가 필요합니다. Node, npm, PyPI 접속은 필요 없습니다. 처음에는 실행 명령 끝에 `--check`를 붙여 점검합니다.

`--from-cache`를 주면 이미 설치된 `node_modules`와 기존 `offline\wheels*` 폴더로 다시 만듭니다.

## 개발자용

**개발 서버**(화면 핫 리로드). `.venv`는 먼저 `./run.sh --check`로 준비합니다. Windows에서는 `backend\.venv\Scripts\python.exe`를 씁니다.

```bash
cd backend && .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000   # 터미널 1
cd frontend && npm ci && npm run dev                                              # 터미널 2 → http://127.0.0.1:5173/
```

개발 서버는 `/api` 요청을 8000번 포트로 넘깁니다. `frontend/dist`가 있으면 백엔드만 띄워도 8000번에서 화면이 열립니다.

**테스트**

```bash
cd frontend && npm test && npm run build
cd backend && .venv/bin/python -m pip install -r requirements-dev.txt && .venv/bin/python -m pytest -q
```

**작업 에이전트 도구**(OpenCode MCP·CLI, 표준 라이브러리만 사용)는 [작업 에이전트 도구](docs/AGENT_TOOLS.md)에 정리돼 있습니다.

```bash
py -3.12 backend/docops.py init-workspace "C:/work/docops-agent" --roots "C:/work/samples"
```

**문서**: 이어서 작업할 때는 [인수인계와 실행 안내](docs/HANDOFF_AND_RUNBOOK.md)부터 읽습니다. 구조는 [아키텍처](docs/ARCHITECTURE.md), API는 [백엔드 README](backend/README.md), 나머지는 [문서 안내](docs/README.md)에 있습니다.
