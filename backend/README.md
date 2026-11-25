# Local document API

Mock 데이터 API와 별도로, 사용자가 선택한 파일을 로컬에 저장하고 명시적으로 요청한 뒤 처리하는 실험용 백엔드입니다. 모델 게이트웨이에는 `.env`의 `MODEL_*` 설정으로 사용자가 누른 연결 확인·모델 목록 조회만 보냅니다(`/api/models`). `frontend/dist`가 있으면 화면도 같은 주소에서 제공합니다. 서버는 `127.0.0.1`에서 단일 프로세스로만 실행합니다.

## 설치와 실행

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock.txt   # 정확한 버전(권장). 범위 지정은 requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

보통은 루트의 `setup.cmd`·`setup.sh`가 이 과정을 대신하며, 기본 모드에서 Docling과 PDF 모델까지 같은 `.venv`에 준비합니다(`--lite`는 Docling 제외). 실행은 `run.cmd`·`run.sh`입니다. 아래는 손으로 설치하는 방법입니다. 기본 잠금 파일만으로 TXT, CSV, MD, LOG를 파이썬 표준 라이브러리로 읽습니다. PDF·Office에는 Docling을 추가로 설치합니다(Python 3.12).

```bash
pip install -r requirements-docling.lock.txt   # Windows 포함 정확한 버전
```

패키지 설치에는 패키지 저장소 접근이 필요할 수 있습니다. Docling PDF 처리는 미리 내려받은 모델 파일이 필요하며, 로컬에 `~/.cache/docling/models`가 있으면 이를 사용합니다. 다른 위치를 사용할 때는 서버를 시작하기 전에 지정합니다.

```bash
export DOCOPS_DOCLING_ARTIFACTS=/path/to/prepared/models
```

**OCR은 문서 OCR 모델만 씁니다(2026-11-24 결정).** 라이브러리 OCR(EasyOCR 등)은 쓰지 않습니다. 콘솔 '모델 연결'이나 `.env`의 `OCR_BASE_URL`·`OCR_MODEL`·`OCR_MODE`로 OpenAI 호환 비전 API의 OCR 모델(고객사 게이트웨이 서빙 예정, 개발 중에는 llama.cpp·Ollama)을 연결하면 PDF의 글자 층 없는 쪽과 쪽 면적 10% 이상 그림, 이미지 파일(PNG·JPEG·BMP·TIFF·GIF·WebP), Office·SVG 안 그림을 읽습니다. `region` 방식은 Docling 레이아웃 영역마다, `page` 방식은 쪽 전체를 한 번 호출합니다. OCR로 읽은 결과에는 항상 원본 대조 경고가 붙습니다. 연결 전에는 스캔 PDF는 텍스트 층만 읽고 `OCR 미적용` 경고를 남기며(글자 층이 없으면 `no_text`), 이미지 파일은 'OCR 모델 미연결'(`parser_unavailable`)로 처리하지 않습니다. 후보 모델 비교는 [OCR 모델 비교](../docs/reports/ocr-bench/README.md)에 있습니다.

## API

- `GET /api/health`: 서비스와 Mock/로컬 처리 제공 상태
- `GET /api/data`: 대시보드용 Mock 데이터
- `GET /api/live/documents`: 실제 로컬 문서 목록
- `POST /api/live/documents`: `multipart/form-data`의 `file` 필드로 업로드. 업로드는 저장만 수행합니다.
- `GET /api/live/documents/{id}`: 처리 상태
- `POST /api/live/documents/{id}/process`: 처리 요청 접수. 응답은 `202`와 `processing` 상태입니다. `processing`은 실제 처리 중 또는 대기 중을 뜻합니다. 중복 요청은 `409`, 대기열 만석은 `503`입니다.
- `GET /api/live/documents/{id}/result`: 마지막 성공 결과와 파서 정보, `is_stale`, `warnings`를 반환합니다. 재처리 중이거나 실패한 경우에도 이전 성공 결과가 있으면 `is_stale: true`로 반환하고, 성공 이력이 없으면 `409`입니다. OCR 없이 처리한 PDF에는 미적용 경고를 남깁니다.
- `GET /api/live/documents/{id}/history`: 로컬 처리 이력

### 파싱 전 판별과 원문 충실도 (2026-11-19)

- 처리 요청 시 파서보다 먼저 **내용 서명**을 본다. DRM으로 감싼 파일(`drm_protected`/`drm_suspected`), 암호 문서(`encrypted`), 확장자와 내용이 다른 파일(`format_mismatch`)은 파서를 부르지 않고 `failed`와 `error_code`로 남긴다. DRM은 판별만 하며 복호화하지 않는다. 제품 머리말은 `DOCOPS_DRM_SIGNATURES`로 등록한다(`.env.example` 참고).
- DOCX·XLSX·PPTX는 `runtime/work/`에 임시 사본을 만들어 Word '기호 삽입'(Symbol 글꼴)·위/아래첨자를 유니코드(`≥`, `m²`, `CO₂`)로 바꾼 뒤 파싱한다. 원본은 바꾸지 않고 사본은 처리 후 지운다. `DOCOPS_OOXML_PREPARE=0`이면 끈다.
- 파싱 뒤 원본 XML을 직접 읽어 결과와 대조한다: 특수기호 손실 수, 병합 셀, 흰색에 가까운 글자·숨김 글자, OCR 없이 읽지 않은 그림 수. 결과에 없던 글상자·SVG 글자는 결과 끝 `## 보충 추출`에 원문 위치와 함께 덧붙인다. 보고서는 `result`·`runs/{run_id}` 응답의 `fidelity`, 요약은 `warnings`.
- 엣지 케이스 회귀 테스트는 `tests/test_edge_cases.py`. Docling 실측 테스트 1개는 Docling이 설치된 가상환경에서만 돈다.

원본, SQLite DB, 결과는 프로젝트의 `runtime/`에 남으며 Git 대상에서 제외됩니다. 파일명은 메타데이터로만 사용하고 실제 경로는 서버가 생성한 ID를 사용합니다. 기본 업로드 한도는 100 MiB이며 표준 텍스트 파서는 100 MiB, CSV는 최대 100만 행입니다. 단일 서버와 전용 단일 파싱 워커를 전제로 하며, 최대 64건의 요청을 추가로 대기합니다. 서버 종료 시 대기 작업은 실패 상태로 기록되며, 갑작스러운 종료로 남은 진행 중 상태는 다음 시작 시 실패 상태로 복구됩니다. 마지막 성공 결과는 재처리 실패나 중단 이후에도 보존합니다. 이 서비스는 운영용 인증·권한 시스템을 포함하지 않습니다.

## 테스트

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```
