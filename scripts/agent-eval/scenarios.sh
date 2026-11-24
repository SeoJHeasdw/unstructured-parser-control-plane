#!/usr/bin/env bash
# 실제 쓰임새 문장으로 OpenCode + 로컬 모델 시나리오를 차례로 돌린다(각각 새 세션).
# WORKSPACE: init-workspace로 만든 OpenCode 작업 폴더, OUT: 결과(JSONL) 폴더
WORKSPACE="${WORKSPACE:?WORKSPACE=작업 폴더}"
OUT="${OUT:-$PWD/agent-eval-out}"
MODEL="${MODEL:-ollama/docops-qwen36-35b-a3b-32k}"
mkdir -p "$OUT"
cd "$WORKSPACE" || exit 1
run() {
  local name="$1"; shift
  local started=$(date +%s)
  timeout 900 opencode run -m "$MODEL" --format json "$*" > "$OUT/sc-$name.jsonl" 2> "$OUT/sc-$name.err"
  echo "$name exit=$? $(( $(date +%s) - started ))s"
}
run 1-folder "09_images 폴더 파싱하고 결과 보고서 보여줘"
run 2-fail   "실패하거나 경고 있는 문서 있어? 제일 문제 큰 것 하나 원인 알려줘"
run 3-sheet  "시험성적서 엑셀에서 요약 시트 내용 보여줘"
run 4-scan   "스캔된 PDF 파일 찾아서 파싱하고 OCR이 제대로 됐는지 확인해줘"
run 5-redo   "D2 다시 파싱해서 이전 결과랑 비교해줘"
run 6-report "오늘 작업 보고서 만들어줘. 내가 옮겨 적을 거야"
