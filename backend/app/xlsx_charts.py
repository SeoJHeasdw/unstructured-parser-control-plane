"""통합문서(XLSX·XLSM) 네이티브 차트: 계열마다 차트에 저장된 표시값(numCache)과 참조한 원본 셀을 대조할 재료.

numCache는 그 계열이 마지막으로 표시된 값이다(Microsoft OpenXML 'NumberingCache'). 셀 값과 캐시는 한 파일 안의 다른
저장 표현이라, 서로 다르면 모델 없이도 '차트에 보이는 값'과 '셀 값'의 충돌을 찾을 수 있다. 실제 Excel이 다시 계산했을 때
화면에 어느 값이 보일지는 확인하지 않는다(파일에 저장된 두 표현만 본다).

해석 범위: 같은 통합문서 안의 연속 범위(한 행 또는 한 열). 여러 영역·외부 통합문서·이름 정의 참조는 '해석 못 함'으로 남긴다.
문서 관계(통합문서 → 시트 → 그리기 → 차트)를 따라 차트가 놓인 시트를 찾는다.
"""
from __future__ import annotations

import posixpath
import re
import zipfile

from app.fidelity.probe import _part, _rels, q

C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
MAX_CHARTS = 200
MAX_POINTS = 2000          # 계열 하나에서 대조하는 점 수 상한
_REF = re.compile(r"^(?:'((?:[^']|'')+)'|([^'!\[\]]+))!\$?([A-Z]{1,3})\$?(\d{1,7})(?::\$?([A-Z]{1,3})\$?(\d{1,7}))?$")


def _c(tag: str) -> str:
    return f"{{{C}}}{tag}"


def column_index(letters: str) -> int:
    number = 0
    for ch in letters:
        number = number * 26 + ord(ch) - 64
    return number


def column_name(index: int) -> str:
    out = ""
    while index:
        index, rest = divmod(index - 1, 26)
        out = chr(65 + rest) + out
    return out


def resolve(formula: str | None) -> tuple[str, list[str]] | None:
    """'Meter'!$B$2:$B$3 → ('Meter', ['B2', 'B3']). 한 행·한 열 연속 범위만(앞 MAX_POINTS개). 해석할 수 없으면 None.
    범위 전체의 점 수는 ref_size()."""
    match = _REF.fullmatch((formula or "").strip())
    if not match:
        return None
    sheet = (match.group(1) or "").replace("''", "'") or match.group(2)
    c1, r1 = column_index(match.group(3)), int(match.group(4))
    c2, r2 = (column_index(match.group(5)), int(match.group(6))) if match.group(5) else (c1, r1)
    if c1 > c2:
        c1, c2 = c2, c1
    if r1 > r2:
        r1, r2 = r2, r1
    if c1 != c2 and r1 != r2:
        return None  # 2차원 범위는 계열 값이 아니다
    cells = [f"{column_name(c)}{r}" for c in range(c1, c2 + 1) for r in range(r1, r2 + 1)]
    return sheet, cells[:MAX_POINTS]


def ref_size(formula: str | None) -> int | None:
    """연속 범위의 점 수(잘라 내기 전). 해석할 수 없으면 None."""
    match = _REF.fullmatch((formula or "").strip())
    if not match:
        return None
    c1, r1 = column_index(match.group(3)), int(match.group(4))
    c2, r2 = (column_index(match.group(5)), int(match.group(6))) if match.group(5) else (c1, r1)
    if c1 != c2 and r1 != r2:
        return None
    return abs(c2 - c1) + abs(r2 - r1) + 1


def _cache(element) -> tuple[dict[int, str] | None, int | None]:
    """numCache·strCache의 점(idx → 글자)과 ptCount. 캐시가 없으면 (None, None)."""
    if element is None:
        return None, None
    cache = element.find(f".//{_c('numCache')}")
    if cache is None:
        cache = element.find(f".//{_c('strCache')}")
    if cache is None:
        return None, None
    points = {}
    for pt in cache.findall(_c("pt")):
        try:
            points[int(pt.get("idx", ""))] = pt.findtext(_c("v")) or ""
        except ValueError:
            continue
    count = cache.find(_c("ptCount"))
    try:
        total = int(count.get("val")) if count is not None else None
    except (TypeError, ValueError):
        total = None
    return points, total


def _title(root) -> str:
    title = root.find(f"{_c('chart')}/{_c('title')}")
    if title is None:
        return ""
    texts = [t.text or "" for t in title.iter(f"{{{A}}}t")]
    if texts:
        return "".join(texts).strip()
    return (title.findtext(f".//{_c('v')}") or "").strip()


def _hosts(archive: zipfile.ZipFile) -> dict[str, str]:
    """차트 부분 → 그 차트가 놓인 시트(차트 시트 포함) 이름."""
    workbook = _part(archive, "xl/workbook.xml")
    if workbook is None:
        return {}
    rels = _rels(archive, "xl/workbook.xml")
    hosts: dict[str, str] = {}
    for sheet in workbook.iter(q("x", "sheet")):
        part = rels.get(sheet.get(q("r", "id")) or "")
        if not part:
            continue
        for target in _rels(archive, part).values():
            if "/drawings/" not in f"/{target}":
                continue
            for chart in _rels(archive, target).values():
                if "/charts/" in f"/{chart}":
                    hosts.setdefault(chart, sheet.get("name") or "")
    return hosts


def read_charts(path) -> list[dict]:
    """차트마다 {part, title, host, series: [{name, values: {ref, sheet, cells}|None, categories: …, cache, cache_count, literal}]}."""
    out: list[dict] = []
    with zipfile.ZipFile(path) as archive:
        names = sorted((n for n in archive.namelist() if re.fullmatch(r"xl/charts/chart\d+\.xml", n)),
                       key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))[:MAX_CHARTS]
        hosts = _hosts(archive) if names else {}
        for name in names:
            root = _part(archive, name)
            if root is None:
                continue
            series = []
            for ser in root.iter(_c("ser")):
                tx = ser.find(_c("tx"))
                label, name_ref = "", None
                if tx is not None:
                    cached_name = (tx.findtext(f".//{_c('v')}") or "").strip()
                    name_formula = (tx.findtext(f".//{_c('f')}") or "").strip()
                    label = cached_name or name_formula
                    name_ref = resolve(name_formula) if name_formula and not cached_name else None  # 이름 캐시가 없으면 셀에서 읽는다
                values = ser.find(_c("val"))
                if values is None:
                    values = ser.find(_c("yVal"))
                categories = ser.find(_c("cat"))
                if categories is None:
                    categories = ser.find(_c("xVal"))
                formula = values.findtext(f".//{_c('f')}") if values is not None else None
                cache, count = _cache(values)
                cat_formula = categories.findtext(f".//{_c('f')}") if categories is not None else None
                cat_cache, cat_count = _cache(categories)
                series.append({
                    "name": label, "name_ref": name_ref, "formula": formula, "ref": resolve(formula), "ref_size": ref_size(formula),
                    "category_formula": cat_formula, "category_count": cat_count,
                    "literal": values is not None and values.find(_c("numLit")) is not None,
                    "cache": cache, "cache_count": count,
                    "categories": resolve(cat_formula), "category_cache": cat_cache,
                })
            out.append({"part": name, "title": _title(root), "host": hosts.get(name) or hosts.get(posixpath.normpath(name)) or "",
                        "series": series})
    return out
