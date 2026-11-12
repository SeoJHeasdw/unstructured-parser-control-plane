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

기본 설치는 TXT, CSV, MD, LOG를 파이썬 표준 라이브러리로 읽습니다. Docling이 필요한 경우 별도로 설치합니다.

```bash
pip install -r requirements-docling.lock.txt   # Windows 포함 정확한 버전
```

패키지 설치에는 패키지 저장소 접근이 필요할 수 있습니다. Docling PDF 처리는 미리 내려받은 모델 파일이 필요하며, 로컬에 `~/.cache/docling/models`가 있으면 이를 사용합니다. 다른 위치를 사용할 때는 서버를 시작하기 전에 지정합니다.

```bash
export DOCOPS_DOCLING_ARTIFACTS=/path/to/prepared/models
```

실행 중 Hugging Face 오프라인 모드를 활성화하며 원격 Docling 서비스와 외부 플러그인은 사용하지 않습니다. PDF OCR은 기본 비활성입니다. 텍스트 없는 스캔 문서는 OCR 연결 후 처리해야 합니다. Docling 2.150.0으로 시험했으며, 테스트한 문서는 합성 PDF와 DOCX입니다. PPTX와 XLSX는 어댑터에 연결만 되어 있어 추가 검증이 필요합니다. HWP, ZIP, 이미지, 메일 등은 처리 미지원입니다.

## API

- `GET /api/health`: 서비스와 Mock/로컬 처리 제공 상태
- `GET /api/data`: 대시보드용 Mock 데이터
- `GET /api/live/documents`: 실제 로컬 문서 목록
- `POST /api/live/documents`: `multipart/form-data`의 `file` 필드로 업로드. 업로드는 저장만 수행합니다.
- `GET /api/live/documents/{id}`: 처리 상태
- `POST /api/live/documents/{id}/process`: 처리 요청 접수. 응답은 `202`와 `processing` 상태입니다. `processing`은 실제 처리 중 또는 대기 중을 뜻합니다. 중복 요청은 `409`, 대기열 만석은 `503`입니다.
- `GET /api/live/documents/{id}/result`: 마지막 성공 결과와 파서 정보, `is_stale`, `warnings`를 반환합니다. 재처리 중이거나 실패한 경우에도 이전 성공 결과가 있으면 `is_stale: true`로 반환하고, 성공 이력이 없으면 `409`입니다. PDF 결과에는 OCR 미적용 경고가 항상 포함됩니다.
- `GET /api/live/documents/{id}/history`: 로컬 처리 이력

원본, SQLite DB, 결과는 프로젝트의 `runtime/`에 남으며 Git 대상에서 제외됩니다. 파일명은 메타데이터로만 사용하고 실제 경로는 서버가 생성한 ID를 사용합니다. 기본 업로드 한도는 100 MiB이며 표준 텍스트 파서는 10 MiB, CSV는 최대 10,000행입니다. 단일 서버와 전용 단일 파싱 워커를 전제로 하며, 최대 64건의 요청을 추가로 대기합니다. 서버 종료 시 대기 작업은 실패 상태로 기록되며, 갑작스러운 종료로 남은 진행 중 상태는 다음 시작 시 실패 상태로 복구됩니다. 마지막 성공 결과는 재처리 실패나 중단 이후에도 보존합니다. 이 서비스는 운영용 인증·권한 시스템을 포함하지 않습니다.

## 테스트

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```
