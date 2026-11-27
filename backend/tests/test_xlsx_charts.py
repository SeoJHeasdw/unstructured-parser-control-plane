"""통합문서 네이티브 차트: 저장된 표시값(numCache)과 원본 셀 대조(파서 품질 검수 고도화 계획 §2.4). 합성 XLSX만 쓴다."""
import io
import zipfile

import pytest

from app.config import Settings
from app.source_text import read_source
from app.verify import verify
from app.xlsx_charts import ref_size, resolve

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
    assert "(1월, 17)" in spot["message"] and "(범주 없음, 71)" in spot["message"] and "계열 '압력'" in spot["message"]
    assert spot["source_layer"] == "xlsx_chart_cache"
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
    assert ref_size("Data!$B$2:$B$2002") == 2001 and len(resolve("Data!$B$2:$B$2002")[1]) == 2000


def _lot_workbook(tmp_path, name, rows, categories, values, count=None):
    """LOT 범주(A열)와 수치(B열) 차트. 차트에 저장된 범주(strCache)·수치(numCache)를 원하는 대로 넣는다."""
    from openpyxl.chart import BarChart, Reference
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Lot"
    sheet.append(["LOT", "수율"])
    for row in rows:
        sheet.append(row)
    chart = BarChart()
    chart.title = "LOT 수율"
    last = len(rows) + 1
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=last), titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=last))
    sheet.add_chart(chart, "D2")
    buffer = io.BytesIO()
    book.save(buffer)
    cats = "".join(f'<pt idx="{i}"><v>{v}</v></pt>' for i, v in enumerate(categories))
    vals = "".join(f'<pt idx="{i}"><v>{v}</v></pt>' for i, v in enumerate(values))
    source, target = io.BytesIO(buffer.getvalue()), io.BytesIO()
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as new:
        for item in old.infolist():
            body = old.read(item)
            if item.filename == "xl/charts/chart1.xml":
                text = body.decode()
                text = text.replace(f"<cat><numRef><f>'Lot'!$A$2:$A${last}</f></numRef></cat>",
                                    f"<cat><strRef><f>'Lot'!$A$2:$A${last}</f><strCache><ptCount val=\"{len(categories)}\"/>{cats}</strCache></strRef></cat>")
                text = text.replace(f"<val><numRef><f>'Lot'!$B$2:$B${last}</f></numRef></val>",
                                    f"<val><numRef><f>'Lot'!$B$2:$B${last}</f><numCache><formatCode>General</formatCode>"
                                    f"<ptCount val=\"{count if count is not None else len(values)}\"/>{vals}</numCache></numRef></val>")
                assert "strCache" in text and "numCache" in text
                body = text.encode()
            new.writestr(item, body)
    path = tmp_path / name
    path.write_bytes(target.getvalue())
    source_text = read_source(path, "XLSX", Settings(runtime_dir=tmp_path / "rt"))
    return verify(source_text, "## 시트: Lot", [], "docling", "XLSX")


def _chart_unit(result):
    return next(u for u in result["units"] if u["kind"] == "chart")


def test_swapped_categories_with_unchanged_values_are_a_conflict(tmp_path):
    """리뷰 재현: 원본 셀 LOT-1·LOT-2와 차트에 저장된 범주 이름을 반대로 두고 수치는 그대로면 '계열 일치'였다."""
    same = _lot_workbook(tmp_path, "same.xlsx", [["LOT-1", 10], ["LOT-2", 20]], ["LOT-1", "LOT-2"], [10, 20])
    assert _chart_unit(same)["state"] == "checked" and not [s for s in same["spots"] if s["kind"] == "chart_conflict"]
    swapped = _lot_workbook(tmp_path, "swap.xlsx", [["LOT-1", 10], ["LOT-2", 20]], ["LOT-2", "LOT-1"], [10, 20])
    spots = [s for s in swapped["spots"] if s["kind"] == "chart_conflict"]
    assert len(spots) == 2 and _chart_unit(swapped)["series"][0]["state"] == "conflict"
    assert "범주이(가) 다릅니다" in spots[0]["message"] and "(LOT-1, 10)" in spots[0]["message"] and "(LOT-2, 10)" in spots[0]["message"]
    assert spots[0]["cell"] == "B2" and spots[0]["source_hit"] == "LOT-1" and spots[0]["result_hit"] == "LOT-2"


def test_a_point_only_in_the_chart_cache_is_a_conflict(tmp_path):
    """리뷰 재현: 참조 셀은 2개인데 차트 캐시에만 세 번째 값 7001이 있으면 '검사 완료'였다."""
    result = _lot_workbook(tmp_path, "extra.xlsx", [["LOT-1", 10], ["LOT-2", 20]], ["LOT-1", "LOT-2"], [10, 20, 7001])
    spot = next(s for s in result["spots"] if s["kind"] == "chart_conflict")
    assert "참조 셀 2개, 차트에 저장된 점 3개" in spot["message"] and "3번째 7001" in spot["message"] and spot["result_hit"] == "7001"
    assert _chart_unit(result)["series"][0]["state"] == "conflict"


def test_more_points_than_the_cap_is_a_partial_check_not_done(tmp_path):
    """리뷰 재현: 2,001개 점 중 마지막 값만 틀린 차트가 '검사 완료'였다. 앞 2,000개만 대조했으면 부분 검증이다."""
    rows = [[f"LOT-{i}", i] for i in range(1, 2002)]
    values = [i for i in range(1, 2001)] + [9999]
    result = _lot_workbook(tmp_path, "big.xlsx", rows, [r[0] for r in rows], values)
    series = _chart_unit(result)["series"][0]
    assert series["state"] == "partial" and series["checked"] == 2000 and series["points"] == 2001
    check = next(c for c in result["checks"] if c["id"] == "chart_values")
    assert check["state"] != "done" and "2,000/2,001" in check["detail"]
    partial = next(r for r in result["reasons"] if r["code"] == "chart_partial")
    assert partial["blocking"] and "2,000/2,001" in partial["message"]
