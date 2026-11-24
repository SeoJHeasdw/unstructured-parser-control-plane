"""합성 도메인 정답(samples/generated/ground_truth)으로 영역 OCR을 잰다: 핵심 값·숫자+단위·표 칸·본문 문장.

사용: DOMAIN_OUT=bench-data/domain-out backend/.venv/bin/python scripts/ocr-bench/domain_eval.py ENGINE BASE_URL MODEL TEXT_PROMPT TABLE_PROMPT FILE_ID...
"""
from concurrent.futures import ThreadPoolExecutor
import difflib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_ocr import BACKEND_DIR, PAD, SKIP, call, delatex, ordered  # noqa: E402

from PIL import Image  # noqa: E402
from docling.datamodel.base_models import InputFormat  # noqa: E402
from docling.datamodel.pipeline_options import LayoutOptions, PdfPipelineOptions  # noqa: E402
from docling.document_converter import DocumentConverter, ImageFormatOption  # noqa: E402
from app.config import Settings  # noqa: E402

ROOT = Path(BACKEND_DIR).parent / "samples" / "generated"


def squash(text: str) -> str:
    return "".join(text.split())


def pages_of(path: Path) -> list[Image.Image]:
    if path.suffix.lower() == ".pdf":
        import pypdfium2
        pdf = pypdfium2.PdfDocument(str(path))
        return [pdf[i].render(scale=200 / 72).to_pil().convert("RGB") for i in range(len(pdf))]
    image = Image.open(path)
    frames = []
    for index in range(getattr(image, "n_frames", 1)):
        image.seek(index)
        frames.append(image.convert("RGB"))
    return frames


def main() -> None:
    engine, base_url, model, text_prompt, table_prompt, *ids = sys.argv[1:]
    settings = Settings.from_env()
    options = PdfPipelineOptions(artifacts_path=settings.docling_artifacts, do_ocr=False, do_table_structure=False,
                                 layout_options=LayoutOptions(keep_empty_clusters=True, skip_cell_assignment=True))
    converter = DocumentConverter(allowed_formats=[InputFormat.IMAGE],
                                  format_options={InputFormat.IMAGE: ImageFormatOption(pipeline_options=options)})
    manifest = {m["file_id"]: m for m in json.loads((ROOT / "ground_truth" / "manifest.json").read_text(encoding="utf-8"))}
    print(f"{'id':7} {'key':>6} {'num':>7} {'cell':>7} {'snip':>5} {'sec':>5}  path")
    totals = {"key": [0, 0], "num": [0, 0], "cell": [0, 0]}
    with ThreadPoolExecutor(4) as pool, tempfile.TemporaryDirectory() as temp:
        for file_id in ids:
            item = manifest[file_id]
            gold = json.loads((ROOT / "ground_truth" / "gold" / f"{file_id}.json").read_text(encoding="utf-8"))
            started = time.perf_counter()
            texts = []
            for number, page_image in enumerate(pages_of(ROOT / "corpus" / item["path"]), 1):
                page_path = Path(temp) / f"{file_id}-{number}.png"
                page_image.save(page_path)
                page = converter.convert(str(page_path)).pages[0]
                scale = page_image.width / page.size.width
                clusters = [c for c in page.predictions.layout.clusters if str(getattr(c.label, "value", c.label)) not in SKIP]
                if not clusters:  # 레이아웃이 아무것도 못 찾으면 쪽 전체를 한 번 읽는다
                    texts.append(call(base_url, model, text_prompt, page_image))
                    continue
                jobs = []
                for cluster in ordered(clusters, page.size.width):
                    box = cluster.bbox
                    crop = page_image.crop((max(0, int(box.l * scale) - PAD), max(0, int(box.t * scale) - PAD),
                                            min(page_image.width, int(box.r * scale) + PAD), min(page_image.height, int(box.b * scale) + PAD)))
                    prompt = table_prompt if str(getattr(cluster.label, "value", cluster.label)) == "table" else text_prompt
                    jobs.append(pool.submit(call, base_url, model, prompt, crop))
                texts += [job.result() for job in jobs]
            text = "\n\n".join(texts)
            flat = squash(delatex(text))  # PaddleOCR-VL의 \(\pm\) 같은 기호 표기를 일반 기호로
            seconds = round(time.perf_counter() - started, 1)

            def rate(values, key):
                values = [squash(v) for v in values if v]
                hit = sum(1 for v in values if v in flat)
                totals[key][0] += hit
                totals[key][1] += len(values)
                return f"{hit}/{len(values)}" if values else "-"

            cells = [cell for table in gold.get("tables", []) for row in table.get("rows", []) for cell in row]
            snippets = gold.get("text_snippets", [])
            snip = "-"
            if snippets:
                scores = []
                for s in snippets:
                    s2 = squash(s)
                    if s2 in flat:
                        scores.append(1.0)
                    else:
                        m = difflib.SequenceMatcher(None, s2, flat, autojunk=False)
                        scores.append(sum(b.size for b in m.get_matching_blocks()) / max(1, len(s2)))
                snip = f"{sum(scores) / len(scores):.2f}"
            print(f"{file_id:7} {rate([kv['value'] for kv in gold.get('key_values', [])], 'key'):>6} "
                  f"{rate(gold.get('numbers_with_units', []), 'num'):>7} {rate(cells, 'cell'):>7} {snip:>5} {seconds:>5}  {item['path']}", flush=True)
            out = Path(os.environ.get("DOMAIN_OUT", temp)) / f"{engine}-{file_id}.md"
            out.write_text(text, encoding="utf-8")
    print("total " + "  ".join(f"{k} {h}/{n}" for k, (h, n) in totals.items()))


if __name__ == "__main__":
    main()
