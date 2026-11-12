#!/usr/bin/env bash
# 인터넷이 되는 PC(macOS/Linux)에서 실행해 Windows 대상 PC용 오프라인 묶음을 만든다.
#   scripts/prepare-offline.sh                        화면 빌드 + 백엔드 휠(Python 3.11~3.14)
#   scripts/prepare-offline.sh --with-docling         Docling 휠 포함(Python 3.12, 용량 큼)
#   scripts/prepare-offline.sh --with-docling-models  Docling 휠 + 로컬 Docling 모델 폴더 포함
# 결과: offline/unstructured-parser-control-plane-windows.zip
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/offline"
NAME="unstructured-parser-control-plane"
CORE_PY="3.11 3.12 3.13 3.14"
DOCLING_PY="3.12"
WITH_DOCLING=0
WITH_MODELS=0
for arg in "$@"; do
  case "$arg" in
    --with-docling) WITH_DOCLING=1 ;;
    --with-docling-models) WITH_DOCLING=1; WITH_MODELS=1 ;;
    *) echo "알 수 없는 옵션: $arg" >&2; exit 2 ;;
  esac
done
if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"; elif [ -x "$ROOT/backend/.venv/bin/python" ]; then PY="$ROOT/backend/.venv/bin/python"; else PY="python3"; fi
MODELS="${DOCOPS_DOCLING_ARTIFACTS:-$HOME/.cache/docling/models}"
pipdl() { "$PY" -m pip download --disable-pip-version-check -q --platform win_amd64 --implementation cp --only-binary=:all: "$@"; }

echo "1/4 화면 빌드"
(cd "$ROOT/frontend" && npm ci --no-audit --no-fund && npm run build)

echo "2/4 Windows용 백엔드 휠"
rm -rf "$OUT/wheels" "$OUT/wheels-docling" "$OUT/stage"
mkdir -p "$OUT/wheels"
for v in $CORE_PY; do pipdl --python-version "$v" -r "$ROOT/backend/requirements.lock.txt" -d "$OUT/wheels"; done
if [ "$WITH_DOCLING" = 1 ]; then
  echo "    Docling 휠 (Python $DOCLING_PY)"
  mkdir -p "$OUT/wheels-docling"
  pipdl --python-version "$DOCLING_PY" -r "$ROOT/backend/requirements-docling.lock.txt" -d "$OUT/wheels-docling"
  # macOS/Linux에서 해석하면 Windows 전용 의존성이 빠지므로 따로 받는다.
  pipdl --python-version "$DOCLING_PY" --no-deps colorama==0.4.6 pywin32==312 -d "$OUT/wheels-docling"
fi

echo "3/4 묶음 구성"
STAGE="$OUT/stage/$NAME"
mkdir -p "$STAGE/offline"
rsync -a --exclude node_modules --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude runtime \
  --exclude offline --exclude .env --exclude '*.tsbuildinfo' --exclude .DS_Store --exclude .git "$ROOT/" "$STAGE/"
cp -R "$OUT/wheels" "$STAGE/offline/"
if [ -d "$OUT/wheels-docling" ]; then cp -R "$OUT/wheels-docling" "$STAGE/offline/"; fi
if [ "$WITH_MODELS" = 1 ]; then
  [ -d "$MODELS" ] || { echo "Docling 모델 폴더가 없습니다: $MODELS" >&2; exit 1; }
  cp -R "$MODELS" "$STAGE/offline/docling-models"
fi

echo "4/4 압축"
rm -f "$OUT/$NAME-windows.zip"
(cd "$OUT/stage" && zip -qr "../$NAME-windows.zip" "$NAME")
rm -rf "$OUT/stage"
du -h "$OUT/$NAME-windows.zip"
