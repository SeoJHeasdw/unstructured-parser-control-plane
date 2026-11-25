#!/usr/bin/env bash
# Unstructured Data Console - macOS / Linux / WSL / Git Bash launcher (start.cmd 의 bash 버전).
#
#   ./run.sh [port] [--lite] [--rebuild] [--check] [--no-browser]
#
# 처음 한 번: Python 가상환경(backend/.venv) 만들고 의존성 설치, 화면(frontend/dist) 빌드, .env 생성.
# 기본은 Docling(PDF·Office 파싱)까지 설치하는 전체 모드(Python 3.12). --lite는 Docling 없이 띄운다.
# 두 모드 모두 같은 backend/.venv를 쓴다. 이후에는 이미 준비된 것을 건너뛴다.
# 기본 포트는 8000이며 충돌하면 다음 빈 포트를 사용한다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
PORT=8000
LITE=0
REBUILD=0
CHECK=0
BROWSER=1

usage() {
  cat <<'EOF'
Usage: ./run.sh [port] [--lite] [--rebuild] [--check] [--no-browser]
  port          포트 탐색 시작값 (기본 8000)
  (기본)        전체 모드: Docling으로 PDF·DOCX·PPTX·XLSX까지 파싱 (Python 3.12)
  --lite        가벼운 모드: Docling 없이 TXT·CSV·MD·LOG만 (Python 3.12~3.15)
  --rebuild     frontend/dist 가 있어도 화면을 다시 빌드
  --check       서버를 띄우지 않고 준비 상태만 확인
  --no-browser  브라우저를 자동으로 열지 않음
EOF
}

for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --lite|--base) LITE=1 ;;
    --docling) ;;  # 예전 옵션. 이제 기본값이라 아무 일도 하지 않는다.
    --rebuild) REBUILD=1 ;;
    --check) CHECK=1 ;;
    --no-browser) BROWSER=0 ;;
    ''|*[!0-9]*) echo "[error] 알 수 없는 옵션: $arg" >&2; usage >&2; exit 2 ;;
    *) PORT="$arg" ;;
  esac
done
if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "[error] 포트는 1~65535 사이여야 합니다." >&2; exit 2
fi

say() { printf '[setup] %s\n' "$*"; }
die() { printf '[error] %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- Python (1/2)
pick_python() {
  local versions="3.12"
  [ "$LITE" = 1 ] && versions="3.12 3.13 3.14 3.15"
  local v c
  for v in $versions; do
    for c in "python$v" python3 python py; do
      command -v "$c" >/dev/null 2>&1 || continue
      if "$c" -c "import sys; raise SystemExit(0 if '$v' == '%d.%d' % sys.version_info[:2] else 1)" >/dev/null 2>&1; then
        echo "$c"; return 0
      fi
    done
  done
  return 1
}

VENV="$BACKEND/.venv"
BASE_LOCK="$BACKEND/requirements.lock.txt"
FULL_LOCK="$BACKEND/requirements-docling.lock.txt"
if [ "$LITE" = 1 ]; then
  MODE=lite; LOCK="$BASE_LOCK"; MODE_TEXT="lite (Docling 없음: TXT·CSV·MD·LOG만)"
else
  MODE=full; LOCK="$FULL_LOCK"; MODE_TEXT="전체 (Docling: PDF·Office 파싱 포함)"
fi
say "모드: $MODE_TEXT"
if [ -d "$BACKEND/.venv-docling" ]; then
  say "backend/.venv-docling 은 더 이상 쓰지 않습니다. Docling은 이제 backend/.venv 에 설치됩니다. 필요 없으면 지워도 됩니다."
fi

venv_python() { if [ -x "$VENV/bin/python" ]; then echo "$VENV/bin/python"; else echo "$VENV/Scripts/python.exe"; fi; }
VPY="$(venv_python)"

# 의존성 잠금 파일이 바뀌면 다시 설치하도록 "모드:지문"을 남긴다. 전체 모드로 설치한 환경은 lite에서도 그대로 쓴다.
fingerprint() {
  if [ "$1" = full ]; then cat "$FULL_LOCK" "$BASE_LOCK"; else cat "$BASE_LOCK"; fi | cksum | tr -d ' '
}
STAMP="$VENV/.lock-stamp"
stamp_ok() {
  [ -f "$STAMP" ] || return 1
  local stamp; stamp="$(cat "$STAMP")"
  [ "$stamp" = "full:$(fingerprint full)" ] && return 0
  [ "$MODE" = lite ] && [ "$stamp" = "lite:$(fingerprint lite)" ]
}
IMPORTS="import fastapi, uvicorn, multipart"
[ "$MODE" = full ] && IMPORTS="$IMPORTS; from importlib.util import find_spec; raise SystemExit(find_spec('docling') is None)"

if [ -f "$VPY" ]; then
  VENV_VER="$("$VPY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
  if [ "$MODE" = full ] && [ "$VENV_VER" != "3.12" ]; then
    die "backend/.venv 는 Python ${VENV_VER:-?} 입니다. Docling은 Python 3.12가 필요합니다. backend/.venv 이름을 바꾸고(예: .venv-old) 다시 실행하세요. Docling 없이 띄우려면 ./run.sh --lite"
  fi
else
  PY="$(pick_python)" || {
    if [ "$MODE" = full ]; then die "Python 3.12 가 필요합니다(Docling). 설치 후 새 터미널에서 다시 실행하세요. Docling 없이 띄우려면 ./run.sh --lite (Python 3.12~3.15)"; fi
    die "Python 3.12~3.15 가 필요합니다. 설치 후 새 터미널에서 다시 실행하세요."
  }
  say "가상환경 만드는 중: backend/.venv ($("$PY" -c 'import sys; print(sys.version.split()[0])'))"
  "$PY" -m venv "$VENV"
  VPY="$(venv_python)"
fi

if ! stamp_ok || ! "$VPY" -c "$IMPORTS" >/dev/null 2>&1; then
  if [ "$MODE" = full ]; then say "Python 패키지 설치 중 ($(basename "$LOCK"), Docling 포함이라 처음에는 몇 분 걸립니다)"
  else say "Python 패키지 설치 중 ($(basename "$LOCK"))"; fi
  "$VPY" -m pip install --disable-pip-version-check --only-binary=:all: -r "$LOCK" \
    || die "패키지 설치에 실패했습니다. 다시 실행하면 이어서 설치합니다. 사내 인증서 문제라면 PIP_CERT=<사내 루트 CA .pem> 을 설정하고 다시 실행하세요."
  echo "$MODE:$(fingerprint "$MODE")" > "$STAMP"
fi

# ---------------------------------------------------------------- 화면(frontend) (2/2)
frontend_ready() { [ -f "$FRONTEND/dist/index.html" ]; }
if [ "$REBUILD" = 1 ] || ! frontend_ready; then
  command -v npm >/dev/null 2>&1 || die "화면을 빌드하려면 Node.js 20.19+ 또는 22.12+ 가 필요합니다(npm). 또는 빌드된 frontend/dist 를 넣어 주세요."
  say "화면 빌드 중 (npm ci → npm run build)"
  if ! ( cd "$FRONTEND" && npm ci --prefer-offline --no-audit --no-fund && npm run build ); then
    die "화면 빌드에 실패했습니다. 위 npm 오류를 확인하세요. UNABLE_TO_VERIFY_LEAF_SIGNATURE 같은 인증서 오류면 NODE_EXTRA_CA_CERTS=<사내 루트 CA 파일> 또는 NODE_OPTIONS=--use-system-ca 를 설정하고 다시 실행하세요."
  fi
  frontend_ready || die "빌드 결과(frontend/dist/index.html)가 없습니다."
fi

# ---------------------------------------------------------------- 설정 파일
if [ ! -f "$ROOT/.env" ] && [ -f "$ROOT/.env.example" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  say ".env 를 .env.example 에서 만들었습니다. 모델·Milvus 주소는 비워 두면 예시 데이터로 동작합니다."
fi

if [ "$CHECK" = 1 ]; then
  set --
  [ "$MODE" = lite ] || set -- --docling
  ( cd "$BACKEND" && "$VPY" check_local.py "$@" )
  exit 0
fi

# ---------------------------------------------------------------- 실행
cd "$BACKEND"
exec "$VPY" launch_local.py "$PORT" "$BROWSER"
