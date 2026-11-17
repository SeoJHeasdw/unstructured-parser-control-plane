# unstructured-parser-control-plane

**비정형 관리 콘솔 (Unstructured Data Console)**: 비정형 문서의 처리 흐름을 운영·설계하고, 파싱 결과와 문서 관계를 검토하는 로컬 작업 공간입니다. 화면에서 **Mock 워크스페이스**와 **실제 파일 처리**를 구분합니다.

- **Mock 워크스페이스:** 대시보드·문서 탐색·파이프라인·관계도·비교 화면의 문서와 수치는 모두 가상의 예시입니다. 여기서 파일을 놓으면 이름·확장자·크기만 브라우저 메모리에 표시하며, 파일 내용은 읽거나 서버에 보내지 않습니다. 위젯 배치와 파이프라인 흐름 정의는 브라우저에 저장되고, 파이프라인 운영 모드의 수치·개입은 브라우저 안 모의 엔진에서만 동작하며 실제 처리 설정을 바꾸지 않습니다.
- **실제 파일 처리:** 사용자가 파일을 선택하거나 놓으면 `runtime/`에 실제 파일이 저장됩니다. **파싱 실행**을 눌러야 처리합니다. 결과 및 처리 상태도 로컬에 보관됩니다. Mock 대시보드와 실제 처리 목록은 서로 연결되지 않습니다. Mock 데이터가 로딩 중이거나 오류여도 실제 파일 처리 탭으로 이동할 수 있습니다. 실제 API 자체에 문제가 있으면 해당 화면에서 별도로 오류가 표시됩니다.

## Windows PC로 옮기기 (Python만 필요)

대상 PC에는 Node가 없어도 됩니다. 빌드된 화면을 백엔드가 같은 주소(`http://127.0.0.1:8000/`)에서 제공합니다.

1. **인터넷이 되는 PC**(macOS/Linux, Node·Python 필요)에서 묶음을 만듭니다. 결과는 `offline/unstructured-parser-control-plane-windows.zip`입니다(기본 약 10MB).

   ```bash
   scripts/prepare-offline.sh
   ```

   Docling(PDF·Office 파싱)까지 옮기려면 `--with-docling`(휠 약 1GB 이상), 이 PC의 Docling 모델 폴더까지 넣으려면 `--with-docling-models`를 붙입니다.
2. **대상 PC**에서 압축을 풀고 `start.cmd`를 실행합니다. 첫 실행에 `backend\.venv`를 만들고 `offline\wheels`에서 패키지를 설치한 뒤 브라우저를 엽니다. 포트를 바꾸려면 `start.cmd 8010`.
   - Python이 없으면: `winget install -e --id Python.Python.3.12` (3.11~3.14 지원, Docling은 3.12 권장)
   - `offline\wheels`가 없으면 인터넷으로 설치를 시도합니다. 사내 미러가 있으면 `pip config set global.index-url <미러 주소>`를 먼저 설정합니다.
   - 내려받은 압축이라 실행이 막히면 zip 파일 속성에서 **차단 해제** 후 다시 풉니다.
3. 모델 연결은 프로젝트 루트 `.env`(첫 실행 때 `.env.example`에서 복사)에 넣고 다시 시작합니다. 화면의 **모델 연결**에서 연결 확인과 모델 목록 조회를 할 수 있습니다.

   ```ini
   MODEL_BASE_URL=https://게이트웨이주소/v1
   MODEL_API_KEY=...
   MODEL_ID=...
   ```

   두 번째 연결은 `MODEL2_*`, 사내 인증서는 `MODEL_CA_BUNDLE`, 프록시는 `HTTPS_PROXY`로 지정합니다. 연결 확인은 OpenAI 호환 `/chat/completions`에 짧은 요청 한 번을 보내며, API 키는 화면·응답에 나오지 않습니다.

화면을 수정해야 할 때만 Node가 필요합니다(`winget install -e --id OpenJS.NodeJS.LTS`, 20.19 이상). `frontend`에서 `npm ci`로 `package-lock.json`의 고정 버전을 설치하며, Windows용 네이티브 패키지(`@rolldown/binding-win32-x64-msvc`, `lightningcss-win32-x64-msvc`)도 레지스트리에서 받아야 합니다.

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

PDF에는 미리 준비된 오프라인 Docling 모델이 필요합니다. 기본적으로 `~/.cache/docling/models`를 사용하며, 다른 위치를 사용하려면 서버 시작 전에 `DOCOPS_DOCLING_ARTIFACTS` 또는 `DOCLING_ARTIFACTS_PATH`를 설정합니다. 개발 시 합성 DOCX와 텍스트 기반 PDF를 실제 처리했습니다. XLSX·PPTX 경로도 마련했지만 결과 품질은 별도 검증이 필요합니다. **현재 OCR은 비활성화되어 스캔 PDF나 이미지 인식은 지원하지 않습니다.** PDF가 성공 처리되어도 이미지·스캔 페이지의 내용이 빠질 수 있어 모든 PDF 결과에 OCR 미적용 경고를 표시합니다. 이 경고는 실제 누락 페이지를 식별했다는 뜻은 아닙니다.

### 2. 프론트엔드

다른 터미널에서:

```bash
cd frontend
npm ci
npm run dev
```

브라우저에서 [http://127.0.0.1:5173/](http://127.0.0.1:5173/)을 엽니다. 개발 서버는 `/api` 요청을 로컬 백엔드의 8000 포트로 전달합니다. 서버를 종료하면 화면을 새로 띄울 수 없으므로 사용 중에는 두 터미널을 실행 상태로 유지하세요.

## 현재 실제 처리 범위

- 업로드 1건당 기본 100 MiB 제한. TXT/CSV 등 텍스트 처리는 10 MiB 및 CSV 10,000행 제한이 있습니다.
- 원본은 임의 생성된 ID로 `runtime/uploads/`에 저장하고, 작업 이력은 `runtime/documents.sqlite3`, Markdown 결과는 `runtime/results/`에 저장합니다. 원본 파일명은 표시용 정보로만 사용합니다.
- 전용 워커 1개가 한 번에 문서 1건을 처리하고, 메모리 대기열에는 기본 최대 64건이 추가로 기다립니다. `processing`은 실제 처리와 대기를 모두 포함합니다. 대기열이 가득 차면 새 처리 요청은 HTTP 503으로 거절되고 거절 이력이 남습니다. 동일 문서의 중복 처리 요청은 HTTP 409입니다.
- 정상 종료 시 새 요청을 막고 미실행 대기 작업은 실패 이력과 함께 재시도 가능한 상태로 바꿉니다. 진행 중 작업은 최대 5초 기다리며 그 뒤에도 실행 중이면 워커가 끝날 때까지 데이터 폴더 잠금을 유지합니다. 프로세스가 먼저 종료되면 재시작 시 남은 `processing` 작업을 실패로 기록합니다. 중단된 작업은 자동 재실행하지 않습니다.
- 재처리 중이나 실패 후에도 마지막 성공 결과를 조회할 수 있으며 `is_stale: true`와 함께 표시합니다. 성공 이력이 없거나 저장된 결과를 읽을 수 없으면 결과 조회가 HTTP 409를 반환합니다. 화면은 현재 오류 메시지로 이 두 경우를 구분하며, 안정적인 오류 코드는 향후 과제입니다. 결과 경고는 `warnings`로 반환합니다.
- Docling은 로컬에서 실행하고 원격 서비스와 모델 다운로드를 사용하지 않도록 구성했습니다. 텍스트 PDF와 합성 DOCX 외의 실제 자료에 대한 정확도는 검증되지 않았습니다.
- **구조 분석**(실제 파일 처리 화면): 원본을 열어 압축 항목·메일 첨부·Office/HWP 내장 개체·PDF 첨부를 하위 문서로 펼치고, 하이퍼링크·외부 통합문서 참조(셀 위치)·필드 연결·공유 폴더 경로·문서번호 후보와 암호화·DRM 의심·확장자 불일치·매크로를 표시합니다. 원본은 바꾸지 않고 디스크에 풀지 않으며 버튼을 눌러야 실행합니다. 결과는 `runtime/structure/`에 저장합니다.
- 형식 선택은 현재 확장자 기반이며, 스캔 OCR·ZIP/메일 첨부 분해·XLSX 외부 참조 추출·검색 인덱싱은 아직 구현하지 않았습니다. 모델은 연결 확인과 목록 조회만 하며 문서 처리 단계에서는 호출하지 않습니다.
- `runtime/`은 Git에서 제외합니다. 실제 파일, 추출 결과, API 키를 저장소에 올리지 마세요. 현재는 **로컬 단일 사용자용 프로토타입**이며 인증·문서별 권한·파일 삭제 화면을 제공하지 않습니다.

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
