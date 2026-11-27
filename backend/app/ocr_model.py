"""문서 OCR 모델 연결(OpenAI 호환 비전 API). 표준 라이브러리만 쓴다.

2026-11-24 결정: OCR은 문서 OCR 모델만 쓴다. 라이브러리 OCR(EasyOCR 등)은 쓰지 않는다.
고객사에는 게이트웨이(vLLM 등)에 OCR 모델을 올려 달라고 요청한다. 이 Mac에서는 llama.cpp·Ollama로 시험한다.

설정(.env 또는 화면 '모델 연결' 저장값):
  OCR_BASE_URL, OCR_API_KEY, OCR_MODEL, OCR_LABEL
  OCR_MODE           region(기본): Docling 레이아웃으로 영역을 나눠 영역마다 호출 — PaddleOCR-VL·GLM-OCR처럼 영역 단위 모델
                     page: 쪽 전체를 한 번 호출 — Schift·Unlimited-OCR·DeepSeek-OCR처럼 쪽 단위 모델
  OCR_TEXT_PROMPT    영역 글자 지시문(기본 'OCR:')
  OCR_TABLE_PROMPT   표 영역 지시문(기본 'Table Recognition:')
  OCR_PAGE_PROMPT    쪽 방식 지시문(기본 'document parsing.')
  OCR_TIMEOUT        호출 한 번의 시간 제한(초, 기본 180), OCR_CONCURRENCY 동시 호출 수(기본 4)
모델 출력은 Markdown으로 맞춘다: OTSL·HTML 표 → Markdown 표, LaTeX 기호(\\(\\pm\\)) → 일반 기호, 반복 폭주 자르기.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import os
import re
import time
from urllib import error, request

from app.llm import _context
from app.textnorm import to_script

MODES = ("region", "page")
DEFAULTS = {"mode": "region", "text_prompt": "OCR:", "table_prompt": "Table Recognition:", "page_prompt": "document parsing."}
# 연결 확인용 그림: 'OCR TEST 12.5 mg/mL'(520x90 PNG)
TEST_TEXT = "12.5"
TEST_PNG = (
    "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"
    "cIo/zLAkAAAAAElFTkSuQmCC"
)


@dataclass(frozen=True)
class OcrConnection:
    label: str
    base_url: str
    api_key: str
    model_id: str
    mode: str = "region"
    text_prompt: str = DEFAULTS["text_prompt"]
    table_prompt: str = DEFAULTS["table_prompt"]
    page_prompt: str = DEFAULTS["page_prompt"]

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model_id)

    def public(self) -> dict:
        return {"key": "ocr", "label": self.label, "base_url": self.base_url, "model_id": self.model_id,
                "api_key_set": bool(self.api_key), "configured": self.configured, "mode": self.mode,
                "text_prompt": self.text_prompt, "table_prompt": self.table_prompt, "page_prompt": self.page_prompt}


def load_ocr(environ=None) -> OcrConnection:
    if environ is None:
        from app.connection_store import effective_environ
        environ = effective_environ()
    mode = environ.get("OCR_MODE", "").strip().lower()
    return OcrConnection(
        label=environ.get("OCR_LABEL", "").strip() or "OCR 모델",
        base_url=environ.get("OCR_BASE_URL", "").strip().rstrip("/"),
        api_key=environ.get("OCR_API_KEY", "").strip(),
        model_id=environ.get("OCR_MODEL", "").strip(),
        mode=mode if mode in MODES else DEFAULTS["mode"],
        text_prompt=environ.get("OCR_TEXT_PROMPT", "").strip() or DEFAULTS["text_prompt"],
        table_prompt=environ.get("OCR_TABLE_PROMPT", "").strip() or DEFAULTS["table_prompt"],
        page_prompt=environ.get("OCR_PAGE_PROMPT", "").strip() or DEFAULTS["page_prompt"],
    )


def concurrency() -> int:
    try:
        return max(1, min(16, int(os.environ.get("OCR_CONCURRENCY", "4"))))
    except ValueError:
        return 4


def _timeout() -> float:
    try:
        return max(10.0, float(os.environ.get("OCR_TIMEOUT", "180")))
    except ValueError:
        return 180.0


class OcrError(Exception):
    pass


def recognize(conn: OcrConnection, png: bytes, prompt: str, max_tokens: int = 4096, attempts: int = 3) -> str:
    """그림 한 장(PNG)을 모델에 보내 글자를 받는다. 실패하면 attempts번까지 다시 시도한다."""
    body = {"model": conn.model_id, "temperature": 0, "max_tokens": max_tokens, "stream": False,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}}]}]}
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if conn.api_key:
        headers["Authorization"] = f"Bearer {conn.api_key}"
    url = conn.base_url if conn.base_url.endswith("/chat/completions") else conn.base_url + "/chat/completions"
    last: Exception | None = None
    for attempt in range(attempts):
        req = request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=_timeout(), context=_context()) as response:
                payload = json.loads(response.read(8_000_000).decode("utf-8", "replace"))
            return payload["choices"][0]["message"].get("content") or ""
        except error.HTTPError as exc:
            last = exc
            if exc.code in (400, 401, 403, 404):
                break  # 설정 문제는 다시 해도 같다
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            last = exc
        if attempt + 1 < attempts:
            time.sleep(1.5 * (attempt + 1))
    reason = f"HTTP {last.code}" if isinstance(last, error.HTTPError) else type(last).__name__ if last else "알 수 없음"
    raise OcrError(f"OCR 모델 호출에 실패했습니다({reason}). OCR 연결 설정과 게이트웨이 상태를 확인해 주세요.")


def check_ocr(conn: OcrConnection) -> dict:
    """글자가 든 작은 그림 하나를 읽혀 주소·키·모델·형식을 함께 확인한다(사용자가 누른 경우에만)."""
    started = time.monotonic()
    try:
        text = recognize(conn, base64.b64decode(TEST_PNG), conn.text_prompt if conn.mode == "region" else conn.page_prompt, max_tokens=256, attempts=1)
    except OcrError as exc:
        return {"ok": False, "status": None, "latency_ms": round((time.monotonic() - started) * 1000), "error": str(exc), "model": conn.model_id}
    reply = " ".join(normalize(text).split())[:200]
    ok = TEST_TEXT in reply
    return {"ok": ok, "status": 200, "latency_ms": round((time.monotonic() - started) * 1000), "model": conn.model_id, "reply": reply,
            **({} if ok else {"error": "응답은 왔지만 시험 그림의 글자(OCR TEST 12.5 mg/mL)를 읽지 못했습니다. 모델과 지시문을 확인해 주세요."})}


# ---------------------------------------------------------------- 출력 정리

_OTSL = re.compile(r"<(fcel|ecel|lcel|ucel|xcel|nl)>")
_SYMBOLS = {r"\pm": "±", r"\mp": "∓", r"\geq": "≥", r"\ge": "≥", r"\leq": "≤", r"\le": "≤", r"\times": "×",
            r"\mu": "µ", r"^\circ": "°", r"^{\circ}": "°", r"\circ": "°", r"\degree": "°", r"\%": "%", r"\sim": "~",
            r"\approx": "≈", r"\neq": "≠", r"\cdot": "·"}
_DET = re.compile(r"<\|det\|>\s*([a-z_]+)\s*\[\[?\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]\]?\s*<\|/det\|>", re.I)
_FURNITURE = {"header", "footer", "page_number", "page_header", "page_footer"}


def _md_cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def grid_markdown(grid: list[list[str]]) -> str:
    """병합 칸은 같은 값을 반복한다(Docling Markdown과 같은 방식)."""
    width = max((len(row) for row in grid), default=0)
    if not width:
        return ""
    rows = [[_md_cell(cell) for cell in row] + [""] * (width - len(row)) for row in grid]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return "\n".join(lines)


def otsl_markdown(block: str) -> str:
    parts = _OTSL.split(block)
    rows, row = [], []
    if parts[0].strip():
        row.append(["fcel", parts[0].strip()])
    for index in range(1, len(parts), 2):
        tag, content = parts[index], parts[index + 1]
        if tag == "nl":
            rows.append(row)
            row = [["fcel", content.strip()]] if content.strip() else []
        else:
            row.append([tag, content.strip()])
    if row:
        rows.append(row)
    grid = []
    for r, cells in enumerate(rows):
        out = []
        for c, (tag, content) in enumerate(cells):
            if tag == "lcel" and out:
                out.append(out[-1])
            elif tag in ("ucel", "xcel") and r and c < len(grid[r - 1]):
                out.append(grid[r - 1][c])
            else:
                out.append(content)
        grid.append(out)
    return grid_markdown([row for row in grid if row])


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, int, int]]] = []
        self.cell: list[str] | None = None
        self.span = (1, 1)

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th"):
            values = dict(attrs)

            def number(name):
                try:
                    return max(1, min(100, int(values.get(name) or 1)))
                except ValueError:
                    return 1
            self.cell, self.span = [], (number("colspan"), number("rowspan"))
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            if not self.rows:
                self.rows.append([])
            self.rows[-1].append(("".join(self.cell).strip(), *self.span))
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def html_table_markdown(table: str) -> str:
    parser = _TableParser()
    parser.feed(table)
    grid: list[list[str | None]] = []
    for r, cells in enumerate(parser.rows):
        while len(grid) <= r:
            grid.append([])
        c = 0
        for text, colspan, rowspan in cells:
            while c < len(grid[r]) and grid[r][c] is not None:
                c += 1
            for dr in range(rowspan):
                while len(grid) <= r + dr:
                    grid.append([])
                target = grid[r + dr]
                while len(target) < c + colspan:
                    target.append(None)
                for dc in range(colspan):
                    target[c + dc] = text
            c += colspan
    return grid_markdown([[cell or "" for cell in row] for row in grid if row])


def delatex(text: str) -> str:
    """짧은 인라인 수식(\\(…\\), $…$) 안의 기호를 일반 문자로. 긴 수식은 그대로 둔다."""
    def inline(body: str) -> str:
        for key in sorted(_SYMBOLS, key=len, reverse=True):
            body = body.replace(key, _SYMBOLS[key])
        body = re.sub(r"\\(?:mathrm|text|mathbf)\{([^}]*)\}", r"\1", body)
        # 10^{-3} → 10⁻³, m^2 → m², CO_2 → CO₂. 유니코드 첨자로 다 바꿀 수 없는 것은 그대로 둔다(부분 변환은 뜻을 흐린다).
        body = re.sub(r"\^\{([^{}]{1,8})\}|\^([0-9])", lambda m: to_script(m.group(1) or m.group(2), "sup") or m.group(0), body)
        body = re.sub(r"_\{([^{}]{1,8})\}|_([0-9])", lambda m: to_script(m.group(1) or m.group(2), "sub") or m.group(0), body)
        return body.replace("{", "").replace("}", "").strip()
    return re.sub(r"\\\((.{1,60}?)\\\)|\$([^$\n]{1,60})\$", lambda m: inline(m.group(1) if m.group(1) is not None else m.group(2)), text)


_SCRIPT = re.compile(r"(\d?)<(sup|sub)\b[^>]*>(.{1,12}?)</\2\s*>", re.I | re.S)
_ORDINAL = re.compile(r"(?:st|nd|rd|th)", re.I)


def scripts(text: str) -> str:
    """모델 출력의 <sup>·<sub>를 태그를 지우기 전에 처리한다(파서 품질 검수 고도화 계획 §4.3).
    - 숫자·부호 첨자(m<sup>2</sup>, 10<sup>-3</sup>, CO<sub>2</sub>) → 유니코드 첨자(m², 10⁻³, CO₂). 지우면 단위·차수가 바뀐다.
    - 숫자 뒤 서수 접미사(10<sup>th</sup>) → 평문 10th(검색에 충분하고 뜻이 그대로).
    - 그 밖(각주 표시 <sup>a</sup> 등) → 태그를 남긴다. 앞 낱말에 붙여 'Assaya'처럼 만들지 않는다."""
    def replace(match: re.Match) -> str:
        digit, kind, body = match.group(1), match.group(2).lower(), match.group(3)
        converted = to_script(body, kind)
        if converted is not None:
            return digit + converted
        if kind == "sup" and digit and _ORDINAL.fullmatch(body.strip()):
            return digit + body.strip()
        return digit + f"<{kind}>{body}</{kind}>"
    return _SCRIPT.sub(replace, text)


_REPEAT = re.compile(r"(.{15,300}?)(?:\s*\1){4,}\s*$", re.S)


def cut_repetition(text: str) -> tuple[str, bool]:
    """반복 폭주(모델이 같은 구절을 끝까지 되풀이)를 한 번으로 줄인다.
    출력 끝까지 이어지는 반복만 자른다. 중간의 되풀이(점검표의 같은 문구, 같은 값이 든 표 행)는 정상 내용이라 둔다."""
    cut = _REPEAT.sub(r"\1", text)
    return cut, cut != text


def det_blocks(text: str) -> list[tuple[str, tuple[int, int, int, int], str]]:
    """쪽 방식 모델의 '<|det|>종류 [x0,y0,x1,y1]<|/det|>내용' 블록. 좌표는 0~999."""
    marks = list(_DET.finditer(text))
    blocks = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        kind = mark.group(1).lower()
        box = tuple(int(mark.group(i)) for i in range(2, 6))
        blocks.append((kind, box, text[mark.end():end].strip()))
    return blocks


def normalize(text: str) -> str:
    """모델 출력 → Markdown. 표 토큰·HTML 표 변환, 기호 정리, 쪽 방식 블록 태그 제거(머리말·쪽 번호는 뺀다)."""
    if _DET.search(text):
        parts = []
        for kind, _, content in det_blocks(text):
            if kind in _FURNITURE or kind == "image" or not content:
                continue
            parts.append(("## " if kind == "title" else "") + content)
        text = "\n\n".join(parts)
    if _OTSL.search(text):
        text = "\n\n".join(otsl_markdown(block) if _OTSL.search(block) else block for block in re.split(r"\n\s*\n", text))
    text = scripts(text)
    text = re.sub(r"<table\b.*?</table>", lambda m: "\n\n" + html_table_markdown(m.group(0)) + "\n\n", text, flags=re.S | re.I)
    text = re.sub(r"</?(?:div|span|p|b|i|u)\b[^>]*>", "", text, flags=re.I)
    text = delatex(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
