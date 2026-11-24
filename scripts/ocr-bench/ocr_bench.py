"""OpenAI 호환 비전 API로 OCR 모델을 돌려 KoOCR-Bench 예측(JSONL)을 만든다.

  python ocr_bench.py sample  BENCH_DIR N_PER_SLICE            → BENCH_DIR/sample_ids.txt, 이미지·정답 내려받기
  python ocr_bench.py run     BENCH_DIR ENGINE BASE_URL MODEL PROMPT  → BENCH_DIR/pred/ENGINE.jsonl (이어 돌리기 가능)
"""
import base64
import json
import sys
import time
from pathlib import Path
from urllib import request

HF = "https://huggingface.co/datasets/schift-io/KoOCR-Bench/resolve/main/"
SLICES = ("gwanbo_table", "kdi_headings", "user_real", "suneung2026", "tables", "kostat_wide")
NO_PROXY = request.build_opener(request.ProxyHandler({}))


def fetch(bench: Path, rel: str) -> Path:
    target = bench / rel
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        with request.urlopen(HF + rel, timeout=120) as response:
            target.write_bytes(response.read())
    return target


def sample(bench: Path, per_slice: int) -> None:
    rows = [json.loads(line) for line in (bench / "manifest.jsonl").open(encoding="utf-8")]
    chosen = []
    for name in SLICES:
        ids = sorted(r["id"] for r in rows if r["slice"] == name and "full" in r["tier"])
        step = max(1, len(ids) // per_slice)
        chosen += ids[::step][:per_slice]
    by_id = {r["id"]: r for r in rows}
    for page_id in chosen:
        row = by_id[page_id]
        fetch(bench, row["image"])
        if isinstance(row["truth"], dict) and row["truth"].get("text"):
            fetch(bench, row["truth"]["text"])
    (bench / "sample_ids.txt").write_text("\n".join(chosen) + "\n", encoding="utf-8")
    print(f"sampled {len(chosen)} pages")


def ocr(base_url: str, model: str, prompt: str, image: Path) -> str:
    data = base64.b64encode(image.read_bytes()).decode("ascii")
    mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
    body = {"model": model, "temperature": 0, "max_tokens": 8192, "stream": False,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt},
                                                      {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}]}]}
    req = request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                          headers={"Content-Type": "application/json"})
    with NO_PROXY.open(req, timeout=600) as response:
        payload = json.loads(response.read())
    return payload["choices"][0]["message"].get("content") or ""


def run(bench: Path, engine: str, base_url: str, model: str, prompt: str) -> None:
    rows = {json.loads(line)["id"]: json.loads(line) for line in (bench / "manifest.jsonl").open(encoding="utf-8")}
    ids = (bench / "sample_ids.txt").read_text(encoding="utf-8").split()
    out = bench / "pred" / f"{engine}.jsonl"
    out.parent.mkdir(exist_ok=True)
    done = {json.loads(line)["id"] for line in out.open(encoding="utf-8")} if out.is_file() else set()
    with out.open("a", encoding="utf-8") as handle:
        for index, page_id in enumerate(ids, 1):
            if page_id in done:
                continue
            started = time.perf_counter()
            text, error = "", ""
            for attempt in range(3):  # 공식 규칙: 오류면 최대 3회, 모두 실패하면 빈 출력
                try:
                    text = ocr(base_url, model, prompt, bench / rows[page_id]["image"])
                    error = ""
                    break
                except Exception as exc:  # noqa: BLE001
                    error = f"{type(exc).__name__}: {exc}"
            seconds = round(time.perf_counter() - started, 1)
            handle.write(json.dumps({"id": page_id, "text": text, "sec": seconds, "error": error}, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"[{engine}] {index}/{len(ids)} {page_id} {seconds}s {len(text)}chars {error[:60]}", flush=True)


if __name__ == "__main__":
    command, bench = sys.argv[1], Path(sys.argv[2])
    if command == "sample":
        sample(bench, int(sys.argv[3]))
    else:
        run(bench, *sys.argv[3:7])
