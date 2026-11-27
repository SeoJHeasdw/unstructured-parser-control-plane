"""통합문서 네이티브 차트: 저장된 표시값(numCache)과 원본 셀 대조(파서 품질 검수 고도화 계획 §2.4). 합성 XLSX만 쓴다."""
import io
import zipfile

import pytest

from app.config import Settings
from app.source_text import read_source
from app.verify import verify
from app.xlsx_charts import resolve

openpyxl = pytest.importorskip("openpyxl")


def _workbook(tmp_path, cache: list[str] | None, name="chart.xlsx"):
    from openpyxl.chart import BarChart, Reference
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Meter"
    for row in (["월", "압력"], ["1월", 17], ["2월", 21]):
        sheet.append(row)
    chart = BarChart()
    chart.title = "압력 추이"
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=3), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=3))
    sheet.add_chart(chart, "D2")
    buffer = io.BytesIO()
    book.save(buffer)
    data = buffer.getvalue()
    if cache is not None:
        # openpyxl은 캐시를 쓰지 않는다: Excel이 저장한 것처럼 마지막 표시값(numCache)을 넣는다.
        points = "".join(f'<pt idx="{i}"><v>{v}</v></pt>' for i, v in enumerate(cache))
        source, target = io.BytesIO(data), io.BytesIO()
        with zipfile.ZipFile(source) as old, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as new:
            for item in old.infolist():
                body = old.read(item)
                if item.filename == "xl/charts/chart1.xml":
                    text = body.decode()
                    text = text.replace("<val><numRef><f>'Meter'!$B$2:$B$3</f></numRef></val>",
                                        f"<val><numRef><f>'Meter'!$B$2:$B$3</f><numCache><formatCode>General</formatCode>"
                                        f"<ptCount val=\"{len(cache)}\"/>{points}</numCache></numRef></val>")
                    assert "numCache" in text
                    body = text.encode()
                new.writestr(item, body)
        data = target.getvalue()
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _markdown():
    return "## 시트: Meter\n\n| 월 | 압력 |\n|---|---|\n| 1월 | 17 |\n| 2월 | 21 |", [
        {"start_line": 3, "end_line": 3, "sheet": "Meter", "row": 1, "column": 1, "columns": 2},
        {"start_line": 5, "end_line": 5, "sheet": "Meter", "row": 2, "column": 1, "columns": 2},
        {"start_line": 6, "end_line": 6, "sheet": "Meter", "row": 3, "column": 1, "columns": 2}]


def _check(tmp_path, cache, name):
    path = _workbook(tmp_path, cache, name)
    source = read_source(path, "XLSX", Settings(runtime_dir=tmp_path / "rt"))
    markdown, locations = _markdown()
    return source, verify(source, markdown, locations, "docling", "XLSX")


def test_chart_cache_matches_conflicts_or_is_missing(tmp_path):
    source, same = _check(tmp_path, ["17", "21"], "same.xlsx")
    chart = next(unit for unit in source.units if unit.kind == "chart")
    assert chart.label == "차트 '압력 추이'" and chart.sheet == "Meter" and chart.chart["series"][0]["values"] == [17, 21]
    assert same["spots"] == [] and next(u for u in same["units"] if u["kind"] == "chart")["state"] == "checked"
    assert next(c for c in same["checks"] if c["id"] == "chart_values")["state"] == "done"

    _, conflict = _check(tmp_path, ["71", "21"], "conflict.xlsx")
    assert [s["kind"] for s in conflict["spots"]] == ["chart_conflict"]
    spot = conflict["spots"][0]
    assert spot["severity"] == "high" and spot["sheet"] == "Meter" and spot["cell"] == "B2" and spot["source_hit"] == "17" and spot["result_hit"] == "71"
    assert "범주 '1월'" in spot["message"] and "계열 '압력'" in spot["message"] and spot["source_layer"] == "xlsx_chart_cache"
    assert next(u for u in conflict["units"] if u["kind"] == "chart")["state"] == "conflict"

    _, missing = _check(tmp_path, None, "nocache.xlsx")
    assert missing["spots"] == []
    assert "chart_no_cache" in [r["code"] for r in missing["reasons"] if r["blocking"]]
    assert next(u for u in missing["units"] if u["kind"] == "chart")["state"] == "unverified"
    # 세 경우가 서로 다른 상태다
    assert len({next(u for u in r["units"] if u["kind"] == "chart")["state"] for r in (same, conflict, missing)}) == 3


def test_reference_resolution_rules():
    assert resolve("'Meter'!$B$2:$B$3") == ("Meter", ["B2", "B3"])
    assert resolve("Data!$A$1:$C$1") == ("Data", ["A1", "B1", "C1"])
    assert resolve("'It''s'!B2") == ("It's", ["B2"])
    assert resolve("Data!$A$1:$B$2") is None          # 2차원 범위
    assert resolve("[1]Data!$A$1:$A$3") is None       # 외부 통합문서
    assert resolve("(Data!$A$1,Data!$A$3)") is None   # 여러 영역
