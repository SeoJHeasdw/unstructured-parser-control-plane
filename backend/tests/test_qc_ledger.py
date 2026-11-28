"""자동 대조 원장(QC): 우선순위로 자른 상세, 단건 조회, 검수 요청 생성, 판정 상태, CSV 주소별 대조. 합성 파일·임시 저장소만 쓴다."""
import csv
import io
import random
import time

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import ParsedDocument
from app.adapters.text import TextAdapter, decode_table, sniff_csv
from app.config import Settings
from app.models import ResultLocation
from app.qc import gate, rule_key
from app.source_text import read_source
from app.verify import verify
from main import create_app


def _wait(client, doc_id, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        doc = client.get(f"/api/live/documents/{doc_id}").json()
        if doc["status"] != "processing":
            return doc
        time.sleep(0.05)
    raise AssertionError("처리가 끝나지 않았습니다")


def _workbook_and_result(tmp_path):
    """12시트: 앞 11시트는 40행씩 두 칸이 맞바뀐 결과(낮음 440곳), 마지막 시트는 17이 999로 바뀐 결과(높음 1곳)."""
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.remove(book.active)
    lines: list[str] = []
    locations: list[ResultLocation] = []
    for index in range(12):
        name = f"S{index + 1:02}"
        sheet = book.create_sheet(name)
        sheet.append(["항목", "값"])
        rows = [[f"가{index}-{r}", f"나{index}-{r}"] for r in range(40)] if index < 11 else [["압력", 17]]
        for row in rows:
            sheet.append(row)
        lines += [f"## {name}", ""]
        start = len(lines) + 1
        lines += ["| 항목 | 값 |", "|---|---|"]
        locations.append(ResultLocation(start_line=start, end_line=start, sheet=name, row=1, column=1, columns=2))
        for r, row in enumerate(rows, start=2):
            shown = [row[1], row[0]] if index < 11 else [row[0], 999]
            lines.append(f"| {shown[0]} | {shown[1]} |")
            locations.append(ResultLocation(start_line=len(lines), end_line=len(lines), sheet=name, row=r, column=1, columns=2))
        lines.append("")
    path = tmp_path / "압력기록.xlsx"
    book.save(path)
    return path, "\n".join(lines), locations


def test_high_finding_outside_first_400_reaches_review(tmp_path, monkeypatch):
    path, markdown, locations = _workbook_and_result(tmp_path)
    settings = Settings(runtime_dir=tmp_path / "runtime")
    with TestClient(create_app(settings)) as client:
        service = client.app.state.documents
        monkeypatch.setattr(service.parsers, "parse",
                            lambda p, ext, options=None: ParsedDocument(markdown, "docling", "test", locations=locations))
        doc_id = client.post("/api/live/documents", files={"file": (path.name, path.read_bytes())}).json()["id"]
        client.post(f"/api/live/documents/{doc_id}/process")
        assert _wait(client, doc_id)["status"] == "completed"
        checked = client.get(f"/api/live/documents/{doc_id}/verify").json()
        assert checked["spots_total"] == 441 and checked["summary"]["high"] == 1
        assert checked["rule_version"] == rule_key() and checked["qc_state"] == "done"
        # 우선순위 순: 문서 끝(마지막 시트)의 높음 1곳이 첫 상세다. 예전에는 문서 순서 앞 400곳만 줘서 빠졌다.
        first = checked["spots"][0]
        assert first["key"] == "S441" and first["severity"] == "high" and first["sheet"] == "S12"
        assert checked["top"][0] == "S441" and checked["top_spots"][0]["key"] == "S441"
        assert len(checked["spots"]) == 400 and checked["page"]["next"] == 400 and checked["spots_matched"] == 441
        assert checked["gate"]["state"] == "needs_review" and checked["gate"]["unresolved_high"] == 1
        rest = client.get(f"/api/live/documents/{doc_id}/verify", params={"offset": 400}).json()
        assert len(rest["spots"]) == 41 and rest["page"]["next"] is None
        assert {s["key"] for s in checked["spots"]} | {s["key"] for s in rest["spots"]} == {f"S{n}" for n in range(1, 442)}
        only_high = client.get(f"/api/live/documents/{doc_id}/verify", params={"severity": "high"}).json()
        assert [s["key"] for s in only_high["spots"]] == ["S441"] and only_high["spots_matched"] == 1
        by_unit = client.get(f"/api/live/documents/{doc_id}/verify", params={"unit": "sheet:S03", "order": "document"}).json()
        assert by_unit["spots_matched"] == 40 and all(s["unit"] == "sheet:S03" for s in by_unit["spots"])
        assert client.get(f"/api/live/documents/{doc_id}/verify", params={"severity": "urgent"}).status_code == 400
        # 단건 조회: S번호와 finding ID 모두
        single = client.get(f"/api/live/documents/{doc_id}/verify/spots/S441").json()
        assert single["id"] == first["id"] and single["message"] == first["message"]
        assert client.get(f"/api/live/documents/{doc_id}/verify/spots/{first['id']}").json()["key"] == "S441"
        assert client.get(f"/api/live/documents/{doc_id}/verify/spots/S9999").status_code == 404
        # 검수 요청: 400곳 밖이던 S441도 V가 된다. 같은 요청을 두 번 보내도 V 하나.
        created = client.post("/api/live/reviews", json={"document_id": doc_id, "spot": "S441", "origin": "console"})
        assert created.status_code == 201 and created.json()["created"] is True
        review = created.json()
        assert review["finding_id"] == first["id"] and review["severity"] == "high" and review["sheet"] == "S12"
        again = client.post("/api/live/reviews", json={"document_id": doc_id, "finding_id": first["id"], "origin": "console"}).json()
        assert again["created"] is False and again["id"] == review["id"]
        # 사람이 '맞음'이라 하면 그 지점은 해결된다(다른 지점의 상태는 바꾸지 않는다).
        client.patch(f"/api/live/reviews/{review['id']}", json={"status": "correct"})
        after = client.get(f"/api/live/documents/{doc_id}/verify", params={"limit": 5}).json()
        assert after["gate"]["unresolved"] == 440 and after["gate"]["unresolved_high"] == 0
        assert after["verdicts"][first["id"]] == "correct"
        unreviewed = client.get(f"/api/live/documents/{doc_id}/verify", params={"unreviewed": True, "limit": 1}).json()
        assert unreviewed["spots_matched"] == 440 and unreviewed["spots"][0]["key"] != "S441"
        summary = client.get("/api/live/qc-summary").json()
        assert summary["documents"] == 1 and summary["qc_done"] == 1 and summary["states"]["needs_review"] == 1


def test_qc_is_registered_with_the_run_and_survives_restart(tmp_path):
    settings = Settings(runtime_dir=tmp_path / "runtime")
    with TestClient(create_app(settings)) as client:
        doc_id = client.post("/api/live/documents", files={"file": ("기록.csv", "항목,값\n압력,17\n".encode())}).json()["id"]
        client.post(f"/api/live/documents/{doc_id}/process")
        _wait(client, doc_id)
        run_id = client.get(f"/api/live/documents/{doc_id}/runs").json()["runs"][0]["run_id"]
        ledger = client.app.state.documents.repo.qc_run(doc_id, run_id, rule_key())
        assert ledger["state"] == "done" and ledger["machine_state"] == "pass_candidate"
    with TestClient(create_app(settings)) as client:
        checked = client.get(f"/api/live/documents/{doc_id}/verify").json()
        assert checked["gate"]["state"] == "pass_candidate" and "기록 모드" in checked["gate"]["note"]
        assert checked["checks"][0]["id"] == "preserved" and any(c["id"] == "csv_grid" for c in checked["checks"])


def test_image_result_goes_through_the_ledger_as_ocr_that_needs_review(tmp_path, monkeypatch):
    from tests.edge_case_files import png
    settings = Settings(runtime_dir=tmp_path / "runtime")
    with TestClient(create_app(settings)) as client:
        service = client.app.state.documents
        monkeypatch.setattr(service.parsers, "parse",
                            lambda p, ext, options=None: ParsedDocument("명판 글자 EQ-UF-03\n정격 220V", "ocr-model", "test"))
        doc_id = client.post("/api/live/documents", files={"file": ("명판.png", png(8, 8))}).json()["id"]
        client.post(f"/api/live/documents/{doc_id}/process")
        assert _wait(client, doc_id)["status"] == "completed"
        response = client.get(f"/api/live/documents/{doc_id}/verify")
        assert response.status_code == 200
        checked = response.json()
        assert checked["rule_version"] == rule_key() and checked["qc_state"] == "done"
        assert [(s["key"], s["kind"], s["source_layer"]) for s in checked["spots"]] == [("S1", "image_ocr", "ocr_model")]
        assert checked["gate"]["state"] == "needs_review" and any(r["code"] == "image_only" for r in checked["reasons"])
        assert client.get(f"/api/live/documents/{doc_id}/verify/spots/{checked['spots'][0]['id']}").json()["key"] == "S1"


def test_pending_qc_is_shown_as_not_evaluated_until_computed(tmp_path, monkeypatch):
    settings = Settings(runtime_dir=tmp_path / "runtime")
    with TestClient(create_app(settings)) as client:
        service = client.app.state.documents
        monkeypatch.setattr(type(service), "ensure_qc", lambda self, doc, run: (_ for _ in ()).throw(RuntimeError("작업자 중단")))
        doc_id = client.post("/api/live/documents", files={"file": ("a.txt", "본문 12".encode())}).json()["id"]
        client.post(f"/api/live/documents/{doc_id}/process")
        assert _wait(client, doc_id)["status"] == "completed"   # 대조가 실패해도 파싱 결과는 열린다
        summary = client.get("/api/live/qc-summary").json()
        assert summary["parsed"] == 1 and summary["qc_pending"] == 1 and summary["qc_done"] == 0
        monkeypatch.undo()
        checked = client.get(f"/api/live/documents/{doc_id}/verify").json()  # 조회할 때 계산한다
        assert checked["qc_state"] == "done"
        assert client.get("/api/live/qc-summary").json()["qc_done"] == 1


# ---------------------------------------------------------------- CSV 기록 모드
def _csv(tmp_path, text: str, encoding="utf-8", name="t.csv"):
    path = tmp_path / name
    path.write_bytes(text.encode(encoding))
    return path


def _check(tmp_path, path, markdown=None, options=None):
    settings = Settings(runtime_dir=tmp_path / "rt")
    parsed = TextAdapter(settings).parse(path, "CSV", options)
    evidence = parsed.evidence
    source = read_source(path, "CSV", settings, {"encoding": evidence["encoding"], "delimiter": evidence["delimiter"]})
    return parsed, verify(source, parsed.markdown if markdown is None else markdown, [], "python-csv", "CSV", evidence)


def test_csv_grid_catches_the_four_blind_spots_of_source_first_matching(tmp_path):
    path = _csv(tmp_path, "장비,최소,최대,상태,비고\nP-1,20,30,적합,\nP-2,20,20,대기,순서 유지\n단위,-7.0,0.07,확인,01\n")
    parsed, clean = _check(tmp_path, path)
    assert clean["spots"] == [] and clean["contract"] is True and clean["summary"]["coverage"] == 1.0
    lines = parsed.markdown.split("\n")
    cases = {
        "cell_swapped": "\n".join([*lines[:2], "| P-1 | 30 | 20 | 적합 |  |", *lines[3:]]),
        "cell_added": "\n".join([*lines[:2], "| P-1 | 20 | 30 | 적합 | 7 |", *lines[3:]]),
        "row_extra": parsed.markdown + "\n| NEW | 8 | 9 | 적합 |  |",
        "row_extra_clone": parsed.markdown + "\n" + lines[2],
        "row_missing": "\n".join(lines[:2] + lines[3:]),
        "row_moved": "\n".join([*lines[:2], lines[3], lines[2], *lines[4:]]),
    }
    for name, markdown in cases.items():
        _, result = _check(tmp_path, path, markdown)
        kinds = {spot["kind"] for spot in result["spots"]}
        expected = name.replace("_clone", "")
        assert kinds == {expected}, (name, result["spots"])
        assert all(spot["id"].startswith("F") and spot["cell"] for spot in result["spots"])
    _, cloned = _check(tmp_path, path, cases["row_extra_clone"])
    assert "중복" in cloned["spots"][0]["message"] and cloned["spots"][0]["severity"] == "high"
    _, swapped = _check(tmp_path, path, cases["cell_swapped"])
    assert swapped["spots"][0]["cell"] == "2행 2열" and swapped["spots"][0]["line"] == 3


def test_ambiguous_delimiter_is_never_a_pass_candidate_until_declared(tmp_path):
    path = _csv(tmp_path, "id;val,unit\nA;1,25\nB;2,50\n")
    parsed, result = _check(tmp_path, path)
    assert parsed.evidence["delimiter"] == "," and parsed.evidence["delimiter_certain"] is False
    assert parsed.evidence["delimiter_alternatives"] == [";"]
    assert result["spots"] == [] and result["contract"] is False  # 같은 잘못된 계약으로 읽으면 둘 다 '일치'다
    assert [r["code"] for r in result["reasons"] if r["blocking"]] == ["delimiter_ambiguous"]
    declared, fixed = _check(tmp_path, path, options={"csv_delimiter": ";"})
    assert declared.evidence["delimiter_basis"] == "declared" and fixed["contract"] is True
    assert decode_table(declared.markdown) == [["id", "val,unit"], ["A", "1,25"], ["B", "2,50"]]


def test_ragged_rows_and_guessed_encoding_block_the_contract(tmp_path):
    _, short = _check(tmp_path, _csv(tmp_path, "a,b\nx\n", name="short.csv"))
    _, padded = _check(tmp_path, _csv(tmp_path, "a,b\nx,\n", name="padded.csv"))
    # 'x'와 'x,'는 같은 Markdown이 된다: 앞의 것은 판정 불가, 뒤의 것은 계약 충족
    assert short["spots"] == [] and "ragged" in [r["code"] for r in short["reasons"]] and short["contract"] is False
    assert padded["spots"] == [] and padded["contract"] is True
    parsed, korean = _check(tmp_path, _csv(tmp_path, "항목,값\n압력,17\n", "cp949", name="kr.csv"))
    assert parsed.evidence["encoding_basis"] == "cp949" and "encoding_uncertain" in [r["code"] for r in korean["reasons"]]
    parsed, declared = _check(tmp_path, _csv(tmp_path, "항목,값\n압력,17\n", "cp949", name="kr2.csv"), options={"encoding": "cp949"})
    assert parsed.evidence["encoding_basis"] == "declared" and declared["contract"] is True


def test_csv_escapes_round_trip_without_false_alarms(tmp_path):
    rows = [["경로", "메모", "공백"], ["\\\\fs01\\qa", "a|b <br> &amp;", "  앞뒤  "], ["줄\n바꿈", "따옴표 \"x\"", ""], ["", "", ""]]
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(rows)
    path = _csv(tmp_path, buffer.getvalue())
    parsed, result = _check(tmp_path, path)
    assert decode_table(parsed.markdown) == [[c.replace("\r\n", "\n") for c in r] for r in rows]
    assert result["spots"] == [], result["spots"]


def test_sniff_reports_alternatives_but_keeps_the_old_choice():
    assert sniff_csv("a,b\n1,2\n")["certain"] is True
    tab = sniff_csv("name\tdesc\nA\tx, y\nB\tz\n")
    assert tab["delimiter"] == "\t" and tab["certain"] is True
    pipe = sniff_csv("a|b|c\n1|2|3\n")
    assert pipe["delimiter"] == "," and pipe["certain"] is False and pipe["plausible"] == ["|"]


def test_large_csv_grid_diff_reports_only_the_changed_rows(tmp_path):
    rng = random.Random(7)
    rows = [["id", "a", "b"]] + [[f"R{i}", str(rng.randrange(1000)), str(rng.randrange(1000))] for i in range(10_000)]
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(rows)
    path = _csv(tmp_path, buffer.getvalue())
    parsed, clean = _check(tmp_path, path)
    assert clean["spots"] == []
    lines = parsed.markdown.split("\n")
    del lines[5000]  # 데이터 한 행 삭제
    started = time.perf_counter()
    _, result = _check(tmp_path, path, "\n".join(lines))
    assert [spot["kind"] for spot in result["spots"]] == ["row_missing"]
    assert time.perf_counter() - started < 5


def test_gate_orders_reviews_before_missing_evidence():
    spot = {"id": "F000000000001", "severity": "high"}
    blocking = [{"code": "scan", "message": "스캔", "blocking": True}]
    assert gate([spot], blocking, {}, 0, 0)["state"] == "needs_review"
    assert gate([spot], blocking, {"F000000000001": "correct"}, 0, 0)["state"] == "undetermined"
    assert gate([spot], [], {"F000000000001": "correct"}, 0, 0)["state"] == "pass_candidate"
    assert gate([spot], [], {"F000000000001": "wrong"}, 0, 1)["state"] == "needs_review"
    assert gate([], [], {}, 1, 0)["state"] == "needs_review"  # 열린 검수 요청


def test_pipe_file_with_a_short_row_is_not_read_as_a_certain_single_column(tmp_path):
    """리뷰 지적: '|' 구분 3열에서 한 행의 마지막 칸이 빠지면 '|'가 후보에서 탈락해 전체가 1열로 읽히고 통과 후보가 됐다."""
    path = _csv(tmp_path, "장비|최소|최대\nP-1|20|30\nP-2|21\nP-3|22|32\n", name="pipe.csv")
    parsed, result = _check(tmp_path, path)
    assert parsed.evidence["delimiter"] == "," and parsed.evidence["width"] == 1
    assert parsed.evidence["delimiter_certain"] is False and parsed.evidence["delimiter_alternatives"] == ["|"]
    assert result["contract"] is False
    ambiguous = next(r for r in result["reasons"] if r["code"] == "delimiter_ambiguous")
    assert ambiguous["blocking"] and ambiguous["alternatives"] == ["|"]
    assert "1열로 읽었지만" in ambiguous["message"] and "세로선(으)로 읽으면 표본 4행 중 100%가 여러 칸" in ambiguous["message"]
    declared, fixed = _check(tmp_path, path, options={"csv_delimiter": "|"})
    assert declared.evidence["width"] == 3 and declared.evidence["delimiter_basis"] == "declared"
    assert "ragged" in [r["code"] for r in fixed["reasons"] if r["blocking"]] and fixed["contract"] is False  # 빠진 칸은 그대로 판정 불가


def test_single_column_csv_controls_stay_pass_candidates(tmp_path):
    controls = {"one.csv": "이름\n홍길동\n김철수\n이영희\n", "stray.csv": "name\nA\nB|C\nD\nE\nF\n"}
    for name, text in controls.items():
        parsed, result = _check(tmp_path, _csv(tmp_path, text, name=name))
        assert parsed.evidence["delimiter_certain"] is True and parsed.evidence["width"] == 1, name
        assert result["spots"] == [] and result["contract"] is True, name
        assert not [r for r in result["reasons"] if r["blocking"]], name


def test_gate_for_pipe_and_single_column_files_through_the_api(tmp_path):
    with TestClient(create_app(Settings(runtime_dir=tmp_path / "runtime"))) as client:
        ids = {}
        for name, text in (("pipe.csv", "장비|최소|최대\nP-1|20|30\nP-2|21\nP-3|22|32\n"), ("one.csv", "이름\n홍길동\n김철수\n")):
            ids[name] = client.post("/api/live/documents", files={"file": (name, text.encode())}).json()["id"]
            client.post(f"/api/live/documents/{ids[name]}/process")
            _wait(client, ids[name])
        pipe = client.get(f"/api/live/documents/{ids['pipe.csv']}/verify").json()["gate"]
        assert pipe["state"] == "undetermined" and "delimiter_ambiguous" in [r["code"] for r in pipe["reasons"]]
        assert client.get(f"/api/live/documents/{ids['one.csv']}/verify").json()["gate"]["state"] == "pass_candidate"
        # 구분자를 지정해 다시 파싱: 빠진 칸이 드러나 여전히 판정 불가(ragged)
        client.post(f"/api/live/documents/{ids['pipe.csv']}/process", json={"csv_delimiter": "|"})
        _wait(client, ids["pipe.csv"])
        declared = client.get(f"/api/live/documents/{ids['pipe.csv']}/verify").json()
        assert declared["gate"]["state"] == "undetermined" and "ragged" in [r["code"] for r in declared["gate"]["reasons"]]
        assert "delimiter_ambiguous" not in [r["code"] for r in declared["gate"]["reasons"]]


def _whitespace_and_pressure(tmp_path):
    """리뷰 재현: 차이 201개 — 앞 200개는 '점검 완료'의 공백, 마지막은 압력 17 bar → 71 bar."""
    rows = ["항목,상태,값"] + [f"R{i},점검 완료,{i}" for i in range(200)] + ["압력,확인,17 bar"]
    path = _csv(tmp_path, "\n".join(rows) + "\n", name="w.csv")
    parsed, _ = _check(tmp_path, path)
    return path, parsed, parsed.markdown.replace("점검 완료", "점검완료").replace("17 bar", "71 bar")


def test_the_201st_difference_is_a_finding_and_reviewing_the_first_200_does_not_pass(tmp_path):
    _, _, markdown = _whitespace_and_pressure(tmp_path)
    _, result = _check(tmp_path, tmp_path / "w.csv", markdown)
    assert result["spots_total"] == 201 and len(result["spots"]) == 201 and result["omitted"] == 0
    pressure = next(spot for spot in result["spots"] if spot["severity"] == "high")
    assert pressure["rank"] == 0 and pressure["source_hit"] == "17 bar" and pressure["result_hit"] == "71 bar"
    verdicts = {spot["id"]: "correct" for spot in result["spots"] if spot is not pressure}  # 화면의 200곳을 모두 '맞음'
    g = gate(result["spots"], result["reasons"], verdicts, 0, 0)
    assert g["state"] == "needs_review" and g["unresolved"] == 1 and g["unresolved_high"] == 1


def test_differences_beyond_the_global_cap_block_the_pass_candidate(tmp_path, monkeypatch):
    import app.verify as verify_module
    monkeypatch.setattr(verify_module, "MAX_FINDINGS", 50)
    _, _, markdown = _whitespace_and_pressure(tmp_path)
    _, result = _check(tmp_path, tmp_path / "w.csv", markdown)
    assert result["spots_total"] == 201 and len(result["spots"]) == 50 and result["omitted"] == 151
    assert any(spot["severity"] == "high" for spot in result["spots"])  # 남기는 것은 우선순위 순: 압력 오류가 먼저
    capped = next(r for r in result["reasons"] if r["code"] == "findings_capped")
    assert capped["blocking"] and capped["omitted"] == 151
    verdicts = {spot["id"]: "correct" for spot in result["spots"]}  # 상세가 있는 50곳을 모두 '맞음'
    g = gate(result["spots"], result["reasons"], verdicts, 0, 0, omitted=result["omitted"])
    assert g["state"] == "needs_review" and g["unresolved"] == 151 and "findings_omitted" in [r["code"] for r in g["reasons"]]


def test_review_through_the_api_pages_200_at_a_time_and_finds_the_201st(tmp_path, monkeypatch):
    path, parsed, markdown = _whitespace_and_pressure(tmp_path)
    settings = Settings(runtime_dir=tmp_path / "runtime")
    with TestClient(create_app(settings)) as client:
        service = client.app.state.documents
        monkeypatch.setattr(service.parsers, "parse", lambda p, ext, options=None: ParsedDocument(markdown, "python-csv", "test", evidence=parsed.evidence))
        doc_id = client.post("/api/live/documents", files={"file": ("w.csv", path.read_bytes())}).json()["id"]
        client.post(f"/api/live/documents/{doc_id}/process", json={"csv_delimiter": ","})
        _wait(client, doc_id)
        page1 = client.get(f"/api/live/documents/{doc_id}/verify", params={"limit": 200, "order": "document"}).json()
        assert page1["spots_matched"] == 201 and page1["page"]["next"] == 200
        page2 = client.get(f"/api/live/documents/{doc_id}/verify", params={"limit": 200, "offset": 200, "order": "document"}).json()
        last = page2["spots"][0]
        assert last["source_hit"] == "17 bar" and last["severity"] == "high"
        assert client.get(f"/api/live/documents/{doc_id}/verify/spots/{last['key']}").status_code == 200
        for spot in page1["spots"]:
            client.post("/api/live/reviews", json={"document_id": doc_id, "finding_id": spot["id"], "status": "correct", "origin": "console"})
        after = client.get(f"/api/live/documents/{doc_id}/verify", params={"limit": 1}).json()["gate"]
        assert after["state"] == "needs_review" and after["unresolved"] == 1
        assert client.get("/api/live/qc-summary").json()["states"]["pass_candidate"] == 0


def test_a_row_with_a_whitespace_change_and_a_value_change_gives_two_findings(tmp_path):
    """한 행의 차이를 묶으면 공백만 보고 '맞음'을 눌러 같은 행의 수치 오류도 해결로 처리된다: 칸마다 따로 올린다."""
    path = _csv(tmp_path, "항목,상태,값\n압력,점검 완료,17 bar\n", name="row.csv")
    parsed, _ = _check(tmp_path, path)
    _, result = _check(tmp_path, path, parsed.markdown.replace("점검 완료", "점검완료").replace("17 bar", "71 bar"))
    cells = sorted((spot["cell"], spot["severity"], spot["source_hit"], spot["result_hit"]) for spot in result["spots"])
    assert cells == [("2행 2열", "medium", "점검 완료", "점검완료"), ("2행 3열", "high", "17 bar", "71 bar")]
    whitespace = next(spot for spot in result["spots"] if spot["severity"] == "medium")
    assert gate(result["spots"], result["reasons"], {whitespace["id"]: "correct"}, 0, 0)["unresolved_high"] == 1


def test_a_failed_reprocess_keeps_the_old_verdict_apart_from_current_counts(tmp_path):
    """리뷰 재현: CP949 CSV를 정상 처리한 뒤 UTF-8을 지정해 재처리를 실패시키면 문서함·집계에 통과 후보로 남았다."""
    with TestClient(create_app(Settings(runtime_dir=tmp_path / "runtime"))) as client:
        doc_id = client.post("/api/live/documents", files={"file": ("kr.csv", "항목,값\n압력,17\n".encode("cp949"))}).json()["id"]
        client.post(f"/api/live/documents/{doc_id}/process", json={"encoding": "cp949"})
        _wait(client, doc_id)
        assert client.get("/api/live/qc-summary").json()["states"]["pass_candidate"] == 1
        client.post(f"/api/live/documents/{doc_id}/process", json={"encoding": "utf-8"})
        doc = _wait(client, doc_id)
        assert doc["status"] == "failed" and doc["error_code"] == "encoding_unknown"
        listed = client.get("/api/live/documents", params={"limit": 10}).json()["documents"][0]
        assert listed["status"] == "failed" and listed["qc"]["previous"] is True
        assert listed["qc"]["state"] == "pass_candidate" and listed["qc"]["label"] == "이전 성공본 · 통과 후보"  # 당시 판정은 보존
        summary = client.get("/api/live/qc-summary").json()
        assert summary["states"]["pass_candidate"] == 0 and summary["parsed"] == 0 and summary["qc_done"] == 0
        assert summary["previous_results"] == {"failed": 1} and summary["not_parsed"] == {"encoding_unknown": 1}
        checked = client.get(f"/api/live/documents/{doc_id}/verify").json()  # 상세: 이전 성공본의 판정과 그 사실
        assert checked["gate"]["state"] == "pass_candidate" and "stale" in [r["code"] for r in checked["gate"]["reasons"]]
