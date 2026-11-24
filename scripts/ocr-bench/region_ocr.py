"""Docling 레이아웃 모델로 쪽을 영역(문단·제목·표 …)으로 나누고, 영역마다 OCR 모델(OpenAI 호환 API)을 부른다.

사용: backend/.venv/bin/python scripts/ocr-bench/region_ocr.py bench-data/koocr ENGINE BASE_URL MODEL TEXT_PROMPT TABLE_PROMPT
게이트웨이에는 VL 모델 하나만 있으면 되고, 레이아웃은 이미 설치된 Docling 모델이 맡는 구성을 시험한다.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib import request

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
BACKEND_DIR = os.environ.get("BACKEND_DIR", str(Path(__file__).resolve().parents[2] / "backend"))
sys.path.insert(0, BACKEND_DIR)

from PIL import Image  # noqa: E402
from docling.datamodel.base_models import InputFormat  # noqa: E402
from docling.datamodel.pipeline_options import LayoutOptions, PdfPipelineOptions  # noqa: E402
from docling.document_converter import DocumentConverter, ImageFormatOption  # noqa: E402
from app.config import Settings  # noqa: E402

NO_PROXY = request.build_opener(request.ProxyHandler({}))
SKIP = {"picture", "chart"}
SYMBOLS = {r"\pm": "±", r"\mp": "∓", r"\geq": "≥", r"\ge": "≥", r"\leq": "≤", r"\le": "≤", r"\times": "×",
           r"\mu": "µ", r"^\circ": "°", r"\circ": "°", r"\degree": "°", r"\%": "%", r"\sim": "~", r"\approx": "≈", r"\neq": "≠"}


def delatex(text: str) -> str:
    """짧은 인라인 수식 안의 기호만 일반 문자로 바꾼다. 긴 수식은 그대로 둔다."""
    def inline(body: str) -> str:
        for key in sorted(SYMBOLS, key=len, reverse=True):
            body = body.replace(key, SYMBOLS[key])
        body = re.sub(r"\\(?:mathrm|text)\{([^}]*)\}", r"\1", body)
        return body.replace("{", "").replace("}", "").replace("^", "").strip()
    return re.sub(r"\\\((.{1,40}?)\\\)|\$([^$\n]{1,40})\$", lambda m: inline(m.group(1) if m.group(1) is not None else m.group(2)), text)
PAD = 8


def call(base_url: str, model: str, prompt: str, image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    body = {"model": model, "temperature": 0, "max_tokens": 4096, "stream": False,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")}}]}]}
    req = request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                          headers={"Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with NO_PROXY.open(req, timeout=300) as response:
                return json.loads(response.read())["choices"][0]["message"].get("content") or ""
        except Exception:  # noqa: BLE001
            if attempt == 2:
                return ""
    return ""


def ordered(clusters, width: float):
    """단 구분 읽기 순서: 쪽 폭의 60%를 넘는 영역은 띠 경계, 그 사이의 좁은 영역은 왼쪽 단 → 오른쪽 단."""
    items = sorted(clusters, key=lambda c: (c.bbox.t, c.bbox.l))
    result, band = [], []

    def flush():
        band.sort(key=lambda c: (0 if (c.bbox.l + c.bbox.r) / 2 < width / 2 else 1, c.bbox.t))
        result.extend(band)
        band.clear()

    for cluster in items:
        if cluster.bbox.r - cluster.bbox.l > 0.6 * width:
            flush()
            result.append(cluster)
        else:
            band.append(cluster)
    flush()
    return result


def main() -> None:
    bench, engine, base_url, model, text_prompt, table_prompt = Path(sys.argv[1]), *sys.argv[2:7]
    settings = Settings.from_env()
    options = PdfPipelineOptions(artifacts_path=settings.docling_artifacts, do_ocr=False, do_table_structure=False,
                                 layout_options=LayoutOptions(keep_empty_clusters=True, skip_cell_assignment=True))
    converter = DocumentConverter(allowed_formats=[InputFormat.IMAGE],
                                  format_options={InputFormat.IMAGE: ImageFormatOption(pipeline_options=options)})
    rows = {json.loads(l)["id"]: json.loads(l) for l in open(bench / "manifest.jsonl", encoding="utf-8")}
    ids = (bench / "sample_ids.txt").read_text(encoding="utf-8").split()
    out = bench / "pred" / f"{engine}.jsonl"
    done = {json.loads(l)["id"] for l in out.open(encoding="utf-8")} if out.is_file() else set()
    with out.open("a", encoding="utf-8") as handle, ThreadPoolExecutor(4) as pool:
        for index, page_id in enumerate(ids, 1):
            if page_id in done:
                continue
            started = time.perf_counter()
            path = bench / rows[page_id]["image"]
            page = converter.convert(str(path)).pages[0]
            image = Image.open(path).convert("RGB")
            scale = image.width / page.size.width
            clusters = [c for c in page.predictions.layout.clusters if str(getattr(c.label, "value", c.label)) not in SKIP]
            jobs = []
            for cluster in ordered(clusters, page.size.width):
                box = cluster.bbox
                crop = image.crop((max(0, int(box.l * scale) - PAD), max(0, int(box.t * scale) - PAD),
                                   min(image.width, int(box.r * scale) + PAD), min(image.height, int(box.b * scale) + PAD)))
                label = str(getattr(cluster.label, "value", cluster.label))
                prompt = table_prompt if label == "table" else text_prompt
                jobs.append(pool.submit(call, base_url, model, prompt, crop))
            parts = [job.result().strip() for job in jobs]
            text = "\n\n".join(part for part in parts if part)
            seconds = round(time.perf_counter() - started, 1)
            handle.write(json.dumps({"id": page_id, "text": text, "sec": seconds, "regions": len(jobs)}, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"[{engine}] {index}/{len(ids)} {page_id} {seconds}s regions={len(jobs)} {len(text)}chars", flush=True)


if __name__ == "__main__":
    main()
