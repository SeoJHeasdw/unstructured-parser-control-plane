#!/usr/bin/env bash
# Windows x64 bundle. See README.md for options and the Windows entry point.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
elif [ -x "$ROOT/backend/.venv/bin/python" ]; then
  PY="$ROOT/backend/.venv/bin/python"
else
  PY="python3"
fi
exec "$PY" "$ROOT/scripts/prepare-offline.py" "$@"
