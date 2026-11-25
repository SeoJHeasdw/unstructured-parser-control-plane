#!/usr/bin/env bash
# 비정형 관리 콘솔 실행 (macOS·Linux·Git Bash). 처음과 코드 업데이트 뒤에는 ./setup.sh
#   ./run.sh [port] [--no-browser]       자세한 옵션: ./run.sh --help
# 로직은 모두 scripts/console.py 에 있다. 이 파일은 backend/.venv 의 Python으로 그것을 부른다.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
for python in backend/.venv/bin/python backend/.venv/Scripts/python.exe; do
  if [ -x "$python" ]; then exec "$python" scripts/console.py run "$@"; fi
done
echo "[error] 아직 설치되지 않았습니다. 먼저 ./setup.sh 를 실행하세요." >&2
exit 1
