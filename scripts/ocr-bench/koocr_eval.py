"""KoOCR-Bench 표본 채점(자체 구현). 지표 정의는 공개 채점기(code/koocr_score.py)를 따른다.

- 글자: 1 - CER. 태그·마크다운 제거 → NFKC → 글자·숫자만. 정답에 없는 외국 문자(한자·가나 등)는 1자당 +2 오류. 쪽 CER 상한 1.
- 표(table_grid): 예측의 <table> 중 가장 잘 맞는 것과 정답 격자의 TEDS(apted). 외국 문자 벌점 동일. Markdown 표는 0.
- PaddleOCR-VL 원출력의 OTSL 표 토큰(<fcel> 등)은 HTML 표로 바꾼다(형식 변환 어댑터).
사용: koocr_eval.py BENCH_DIR ENGINE=pred.jsonl ...
"""
from collections import Counter, defaultdict
import html as H
import json
import re
import sys
import unicodedata
from pathlib import Path

from apted import APTED, Config
from lxml import html as lhtml
from rapidfuzz.distance import Levenshtein

FOREIGN_RE = re.compile("[㐀-䶿一-鿿豈-﫿぀-ヿㇰ-ㇿЀ-ӿ฀-๿؀-ۿ֐-׿，。：；！？]")
OTSL = re.compile(r"<(fcel|ecel|lcel|ucel|xcel|nl)>")


def plain(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"<\|det\|>.*?<\|/det\|>", "\n", s)
    s = re.sub(r"<\|ref\|>.*?<\|/ref\|>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = H.unescape(s)
    s = re.sub(r"(?m)^\s*#{1,6}\s*", "", s)
    s = re.sub(r"[|*_`]|:?-{3,}:?|!\[[^\]]*\]\([^)]*\)|\$\$?|\\\\[()\[\]]", " ", s)
    return re.sub(r"\s+", "", s)


def nrm(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", s) if ch.isalnum())


def foreign_extra(p: str, t: str) -> int:
    pc, tc = Counter(FOREIGN_RE.findall(p)), Counter(FOREIGN_RE.findall(t))
    return sum(max(0, n - tc[c]) for c, n in pc.items())


def otsl_to_html(text: str) -> str:
    """OTSL 토큰 구간을 HTML 표로 바꾼다. 토큰이 없는 줄은 그대로 둔다."""
    out = []
    for block in re.split(r"\n\s*\n", text):
        if not OTSL.search(block):
            out.append(block)
            continue
        parts = OTSL.split(block)
        rows, row = [], []
        lead = parts[0].strip()
        if lead:
            row.append(["fcel", lead])
        for i in range(1, len(parts), 2):
            tag, content = parts[i], parts[i + 1]
            if tag == "nl":
                rows.append(row)
                row = []
                if content.strip():
                    row.append(["fcel", content.strip()])
            else:
                row.append([tag, content.strip()])
        if row:
            rows.append(row)
        html_rows = []
        for r, cells in enumerate(rows):
            tds = []
            for c, (tag, content) in enumerate(cells):
                if tag not in ("fcel", "ecel"):
                    continue
                colspan = 1
                while c + colspan < len(cells) and cells[c + colspan][0] == "lcel":
                    colspan += 1
                rowspan = 1
                while r + rowspan < len(rows) and c < len(rows[r + rowspan]) and rows[r + rowspan][c][0] in ("ucel", "xcel"):
                    rowspan += 1
                attrs = (f' colspan="{colspan}"' if colspan > 1 else "") + (f' rowspan="{rowspan}"' if rowspan > 1 else "")
                tds.append(f"<td{attrs}>{H.escape(content)}</td>")
            html_rows.append("<tr>" + "".join(tds) + "</tr>")
        out.append("<table>" + "".join(html_rows) + "</table>")
    return "\n\n".join(out)


class Node:
    def __init__(self, tag, colspan=1, rowspan=1, content=""):
        self.tag, self.colspan, self.rowspan, self.content, self.children = tag, colspan, rowspan, content, []


class TedsConfig(Config):
    def rename(self, a, b):
        if a.tag != b.tag or a.colspan != b.colspan or a.rowspan != b.rowspan:
            return 1.0
        if a.tag == "td":
            return Levenshtein.normalized_distance(a.content, b.content) if (a.content or b.content) else 0.0
        return 0.0

    def children(self, node):
        return node.children


def table_tree(table_html: str) -> tuple[Node, int]:
    element = lhtml.fragment_fromstring(table_html, create_parent=False)
    root, count = Node("table"), 1
    for tr in element.iter("tr"):
        row = Node("tr")
        root.children.append(row)
        count += 1
        for td in tr:
            if td.tag not in ("td", "th"):
                continue
            def span(name):
                try:
                    return max(1, int(td.get(name, "1")))
                except ValueError:
                    return 1
            row.children.append(Node("td", span("colspan"), span("rowspan"), plain(td.text_content())))
            count += 1
    return root, count


def teds(pred_html: str, gold_html: str) -> float:
    try:
        p, pn = table_tree(pred_html)
        g, gn = table_tree(gold_html)
    except Exception:  # noqa: BLE001 — 깨진 예측 표는 0점
        return 0.0
    distance = APTED(p, g, TedsConfig()).compute_edit_distance()
    return max(0.0, 1.0 - distance / max(pn, gn))


def grid_html(rows) -> str:
    return "<table>" + "".join("<tr>" + "".join(
        f'<td colspan="{c["cs"]}" rowspan="{c["rs"]}">{H.escape(c["text"])}</td>' for c in r) + "</tr>" for r in rows) + "</table>"


def tables_of(text: str) -> list[str]:
    text = re.sub(r"<\|det\|>.*?<\|/det\|>", "\n", text)
    text = re.sub(r"<(/?)th\b", r"<\1td", text, flags=re.I)
    return re.findall(r"<table.*?</table>", text, re.S | re.I)


def score(bench: Path, engine: str, pred_path: Path) -> dict:
    rows = {json.loads(l)["id"]: json.loads(l) for l in open(bench / "manifest.jsonl", encoding="utf-8")}
    ids = (bench / "sample_ids.txt").read_text(encoding="utf-8").split()
    preds = {}
    for line in open(pred_path, encoding="utf-8"):
        item = json.loads(line)
        preds[item["id"]] = item
    result = defaultdict(lambda: defaultdict(list))
    for page_id in ids:
        row, item = rows[page_id], preds.get(page_id)
        if item is None:
            continue
        out = item.get("text") or ""
        if OTSL.search(out):
            out = otsl_to_html(out)
        sl, truth = row["slice"], row["truth"]
        if item.get("sec") is not None:
            result[sl]["sec"].append(item["sec"])
        if truth["type"] == "table_grid":
            gold = grid_html(truth["rows"])
            cands = tables_of(out)
            gt_plain = plain(" ".join(c["text"] for r in truth["rows"] for c in r))
            best = max((teds(c, gold) for c in cands), default=0.0)
            best = max(0.0, best - 2 * foreign_extra(plain(out), gt_plain) / max(1, len(gt_plain)))
            result[sl]["teds"].append(best)
            # 참고: 표 글자만 비교한 1-CER(표 구조와 무관)
            result[sl]["cell_text"].append(1 - min(1.0, Levenshtein.distance(nrm(plain(out)), nrm(gt_plain)) / max(1, len(nrm(gt_plain)))))
        else:
            t = (bench / truth["text"]).read_text(encoding="utf-8")
            if page_id.startswith("suneung2026/math"):
                out = re.sub(r"\\\(.*?\\\)|\\\[.*?\\\]|\$\$.*?\$\$|\$[^$\n]*\$", " ", out, flags=re.S)
            pp, tp = plain(out), plain(t)
            fx = foreign_extra(pp, tp)
            cer = min(1.0, (Levenshtein.distance(nrm(pp), nrm(tp)) + 2 * fx) / max(1, len(nrm(tp))))
            result[sl]["text"].append(1 - cer)
            result[sl]["foreign"].append(fx)
    return result


def main() -> None:
    bench = Path(sys.argv[1])
    table = {}
    for spec in sys.argv[2:]:
        engine, path = spec.split("=", 1)
        table[engine] = score(bench, engine, Path(path))
    slices = ["gwanbo_table", "kdi_headings", "user_real", "suneung2026", "tables", "kostat_wide"]
    print(f"{'slice':14} {'metric':9} " + " ".join(f"{e:>16}" for e in table))
    for sl in slices:
        for metric in ("text", "teds", "cell_text", "foreign", "sec"):
            values = [table[e][sl].get(metric) for e in table]
            if not any(values):
                continue
            cells = [f"{sum(v) / len(v):16.3f}" if v else f"{'-':>16}" for v in values]
            print(f"{sl:14} {metric:9} " + " ".join(cells))
    print()
    for e, res in table.items():
        text = [v for sl in slices for v in res[sl].get("text", [])]
        tab = [v for sl in slices for v in res[sl].get("teds", [])]
        secs = [v for sl in slices for v in res[sl].get("sec", [])]
        print(f"{e:16} text(1-CER) {sum(text)/len(text) if text else 0:.3f}  table TEDS {sum(tab)/len(tab) if tab else 0:.3f}  "
              f"sec/page {sum(secs)/len(secs) if secs else float('nan'):.1f}  pages {len(text) + len(tab)}")


if __name__ == "__main__":
    main()
