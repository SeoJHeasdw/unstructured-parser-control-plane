#!/usr/bin/env bash
# Unstructured Data Console - macOS / Linux / WSL / Git Bash launcher (start.cmd 의 bash 버전).
#
#   ./run.sh [port] [--docling] [--rebuild] [--check] [--no-browser]
#
# 처음 한 번: Python 가상환경(backend/.venv) 만들고 의존성 설치, 화면(frontend/dist) 빌드, .env 생성.
# 이후에는 이미 준비된 것을 건너뛰고 바로 서버를 띄운다. 기본 주소는 http://127.0.0.1:8000/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
PORT=8000
DOCLING=0
REBUILD=0
CHECK=0
BROWSER=1

usage() {
  cat <<'EOF'
Usage: ./run.sh [port] [--docling] [--rebuild] [--check] [--no-browser]
  port          서버 포트 (기본 8000)
  --docling     PDF·Office 파싱용 Docling 환경(Python 3.12) 사용
  --rebuild     frontend/dist 가 있어도 화면을 다시 빌드
  --check       서버를 띄우지 않고 준비 상태만 확인
  --no-browser  브라우저를 자동으로 열지 않음
EOF
}

for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    --docling) DOCLING=1 ;;
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
  local versions="3.12 3.13 3.14 3.11"
  [ "$DOCLING" = 1 ] && versions="3.12"
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

if [ "$DOCLING" = 1 ]; then
  VENV="$BACKEND/.venv-docling"; LOCK="$BACKEND/requirements-docling.lock.txt"
else
  VENV="$BACKEND/.venv"; LOCK="$BACKEND/requirements.lock.txt"
fi
if [ -x "$VENV/bin/python" ]; then VPY="$VENV/bin/python"; else VPY="$VENV/Scripts/python.exe"; fi

# 의존성 잠금 파일이 바뀌면 다시 설치하도록 지문을 남긴다.
fingerprint() { cksum < "$LOCK" | tr -d ' '; }
STAMP="$VENV/.lock-stamp"

if [ ! -f "$VPY" ]; then
  PY="$(pick_python)" || die "Python 3.11~3.14 가 필요합니다(Docling은 3.12). 설치 후 새 터미널에서 다시 실행하세요."
  say "가상환경 만드는 중: $(basename "$VENV") ($("$PY" -c 'import sys; print(sys.version.split()[0])'))"
  "$PY" -m venv "$VENV"
  if [ -x "$VENV/bin/python" ]; then VPY="$VENV/bin/python"; else VPY="$VENV/Scripts/python.exe"; fi
fi

if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$(fingerprint)" ] || ! "$VPY" -c "import fastapi, uvicorn, multipart" >/dev/null 2>&1; then
  say "Python 패키지 설치 중 ($(basename "$LOCK"))"
  "$VPY" -m pip install --disable-pip-version-check --only-binary=:all: -r "$LOCK" \
    || die "패키지 설치에 실패했습니다. 사내 인증서 문제라면 PIP_CERT=<사내 루트 CA .pem> 을 설정하고 다시 실행하세요."
  fingerprint > "$STAMP"
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
  ( cd "$BACKEND" && "$VPY" -c "from main import app, DATA; assert app.state.settings.static_dir and DATA.is_file(), 'Frontend or mock data is missing.'" )
  echo "[ok] frontend and Python dependencies are ready."
  exit 0
fi

# ---------------------------------------------------------------- 실행
if "$VPY" - "$PORT" <<'EOF'
import socket, sys
with socket.socket() as s:
    try:
        s.bind(("127.0.0.1", int(sys.argv[1])))
    except OSError:
        raise SystemExit(1)
EOF
then :; else die "포트 $PORT 가 이미 사용 중입니다. 예: ./run.sh $((PORT + 10))"; fi

URL="http://127.0.0.1:$PORT/"
printf '\nUnstructured Data Console - %s\nStop: Ctrl+C\n\n' "$URL"

if [ "$BROWSER" = 1 ]; then
  (
    for _ in $(seq 1 100); do
      if "$VPY" -c "import json, sys, urllib.request as u; sys.exit(0 if json.load(u.build_opener(u.ProxyHandler({})).open('${URL}api/health', timeout=0.5)).get('status') == 'ok' else 1)" >/dev/null 2>&1; then
        if command -v open >/dev/null 2>&1; then open "$URL"
        elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1
        elif command -v cmd.exe >/dev/null 2>&1; then cmd.exe /c start "" "$URL" >/dev/null 2>&1
        fi
        exit 0
      fi
      sleep 0.25
    done
  ) &
fi

cd "$BACKEND"
exec "$VPY" -m uvicorn main:app --host 127.0.0.1 --port "$PORT"
