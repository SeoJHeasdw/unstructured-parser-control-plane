#!/usr/bin/env bash
# 비정형 관리 콘솔 설치·갱신 (macOS·Linux·Git Bash). 실행은 ./run.sh
#   ./setup.sh [--lite] [--offline] [--models ZIP]   자세한 옵션: ./setup.sh --help
# 로직은 모두 scripts/console.py 에 있다. 이 파일은 그것을 돌릴 Python만 찾는다
# (가상환경용 Python 3.12는 console.py가 다시 찾는다).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
for c in python3.12 python3 python py; do
  command -v "$c" >/dev/null 2>&1 || continue
  if "$c" -c 'import sys; raise SystemExit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
    exec "$c" scripts/console.py setup "$@"
  fi
done
echo "[error] Python 3.12 이 필요합니다. 설치 후 새 터미널에서 다시 실행하세요." >&2
exit 1
