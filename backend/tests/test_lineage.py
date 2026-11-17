from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.lineage import build_lineage, parse_name
from main import create_app
from tests.synthetic_files import docx, xlsx, zip_bytes


def node(name, content, kind="file", links=(), children=(), location=""):
    return {"name": name, "ext": name.rsplit(".", 1)[-1].upper(), "size": 100, "kind": kind, "location": location, "detected": "docx", "flags": [], "stats": {},
            "links": [{"kind": k, "target": t, "location": loc, "evidence": ev} for k, t, loc, ev in links], "children": list(children), "hash": content, "duplicate_of": None}


def doc(doc_id, name, uploaded, structure=None):
    return {"id": doc_id, "name": name, "uploaded_at": uploaded, "size": 100, "structure": structure}


def family_of(result, title):
    return next(f for f in result["families"] if f["title"] == title)


def labels(result, family):
    return [result["entries"][e]["label"] for e in family["entries"]]


@pytest.mark.parametrize("name, expected", [
    ("SOP-QC-0040_세척 절차_Rev5.docx", {"docno": "SOP-QC-0040", "rev": 5, "title": "SOP-QC-0040 세척 절차"}),
    ("SOP-QC-0040 Rev.3 세척 절차.pdf", {"docno": "SOP-QC-0040", "rev": 3}),
    ("보고서_v2.docx", {"version": (2,), "title": "보고서"}),
    ("보고서_V2.1.docx", {"version": (2, 1)}),
    ("보고서 ver.3.docx", {"version": (3,)}),
    ("보고서_R03.docx", {"rev": 3}),
    ("보고서_r02.docx", {"rev": 2}),
    ("보고서_개정3.hwp", {"rev": 3}),
    ("회의자료_3차.pptx", {"version": (3,)}),
    ("보고서_최종.docx", {"final": 1, "title": "보고서"}),
    ("보고서_최종_수정.docx", {"final": 2}),
    ("report_final.docx", {"final": 1, "title": "report"}),
    ("보고서 (1).docx", {"copy": True, "title": "보고서"}),
    ("보고서 - 복사본.docx", {"copy": True, "title": "보고서"}),
    ("report_copy.docx", {"copy": True, "title": "report"}),
    ("점검표_20261112.xlsx", {"date": 20261112, "title": "점검표"}),
    ("점검표_2026-11-12.xlsx", {"date": 20261112}),
    ("점검표_261112.xlsx", {"date": 20261112}),
    ("개정 대비표_SOP-QC-0040.xlsx", {"docno": None}),
    ("v2.docx", {"version": (2,), "title": "v2"}),
])
def test_name_signals_are_read_and_stripped(name, expected):
    info = parse_name(name)
    for key, value in expected.items():
        assert getattr(info, key) == value, (name, key)
    assert parse_name("보고서_V2.1.docx").base_key == parse_name("보고서 - 복사본.docx").base_key == parse_name("보고서_최종_수정.docx").base_key


def test_versions_are_grouped_ordered_and_latest_reason_is_given():
    result = build_lineage([
        doc("a", "SOP-QC-0040_세척 절차_Rev3.docx", "2026-03-01T09:00:00+09:00"),
        doc("b", "SOP-QC-0040_세척 절차_Rev5.docx", "2026-05-01T09:00:00+09:00"),
        doc("c", "SOP-QC-0040_세척 절차_Rev4.docx", "2026-11-01T09:00:00+09:00"),
        doc("d", "SOP-QC-0040 Rev.5 세척 절차(서명본).pdf", "2026-04-01T09:00:00+09:00"),
        doc("e", "점검표_20261105.xlsx", "2026-11-05T09:00:00+09:00"),
        doc("f", "점검표_20261112.xlsx", "2026-11-12T09:00:00+09:00"),
    ])
    sop = family_of(result, "SOP-QC-0040 세척 절차")
    assert labels(result, sop) == ["Rev 3", "Rev 4", "Rev 5", "Rev 5"]  # 업로드 순서가 아니라 Rev 순서
    assert sop["latest"]["status"] == "confirmed" and [r["code"] for r in sop["latest"]["reasons"]] == ["rev", "format"]
    latest = [result["entries"][e] for e in sop["entries"] if result["entries"][e]["is_latest"] or result["entries"][e]["co_latest"]]
    assert {e["ext"] for e in latest} == {"DOCX", "PDF"}
    sheet = family_of(result, "점검표")
    assert sheet["latest"]["reasons"][0]["label"] == "파일명 날짜" and result["entries"][sheet["latest"]["entry"]]["label"] == "2026-11-12"
    assert result["summary"]["families"] == 2 and result["summary"]["versioned"] == 2 and result["summary"]["hold"] == 0


@pytest.mark.parametrize("names, uploads, code", [
    (["회의_v1.pptx", "회의_v2.pptx", "회의_v2_최종.pptx"], ["11-01T09", "11-07T09", "11-05T09"], "final-upload"),
    (["회의_v1_최종.pptx", "회의_v2.pptx"], ["11-01T09", "11-02T09"], "final-lower"),
    (["회의_최종.pptx", "회의_v2.pptx"], ["11-01T09", "11-02T09"], "final-lower"),
    (["회의.pptx", "회의 (1).pptx"], ["11-01T09:00", "11-01T09:20"], "no-signal"),
    (["회의_Rev5.pptx", "회의_Rev4_20261120.pptx", "회의_Rev5_20261101.pptx"], ["11-01T09", "11-02T09", "11-03T09"], "order"),
    (["회의_Rev5.pptx", "회의_20261120.pptx"], ["11-01T09", "11-02T09"], "mixed"),
])
def test_conflicting_or_missing_signals_hold_the_decision(names, uploads, code):
    docs = [doc(str(i), name, f"2026-{when}:00:00+09:00" if len(when) == 8 else f"2026-{when}:00+09:00", node(name, f"h{i}")) for i, (name, when) in enumerate(zip(names, uploads))]
    family = build_lineage(docs)["families"][0]
    assert family["latest"]["status"] == "hold"
    assert code in [c["code"] for c in family["latest"]["conflicts"]]
    assert len(family["latest"]["candidates"]) >= 2


def test_upload_time_orders_unmarked_files_from_different_batches_and_same_hash_is_a_duplicate():
    result = build_lineage([
        doc("a", "점검표.xlsx", "2026-11-01T09:00:00+09:00", node("점검표.xlsx", "h1")),
        doc("b", "점검표 (1).xlsx", "2026-11-08T09:00:00+09:00", node("점검표 (1).xlsx", "h2")),
        doc("c", "점검표 - 복사본.xlsx", "2026-11-09T09:00:00+09:00", node("점검표 - 복사본.xlsx", "h2")),
        doc("d", "완전히 다른 이름.xlsx", "2026-11-10T09:00:00+09:00", node("완전히 다른 이름.xlsx", "h2")),
    ])
    assert len(result["families"]) == 1  # 이름이 달라도 같은 내용이면 같은 문서
    family = result["families"][0]
    assert family["latest"]["status"] == "confirmed" and family["latest"]["reasons"][0]["code"] == "upload"
    assert len(family["entries"]) == 2 and family["counts"]["duplicates"] == 2 and "duplicate" in family["flags"]
    top = result["entries"][family["latest"]["entry"]]
    assert len(top["instances"]) == 3 and result["instances"][top["primary"]]["name"] == "점검표 (1).xlsx"


def test_contained_files_join_families_and_references_resolve_to_versions():
    header = [("doc-number", "SOP-QC-0040 Rev.4", "header1 문단 1", "SOP-QC-0040 Rev.4")]
    rev4 = node("SOP-QC-0040_절차_Rev4.docx", "rev4", links=header)
    std3 = node("기준표_v3.xlsx", "std3", kind="archive-entry", location="참고/기준표_v3.xlsx")
    pack = node("송부.zip", "zip", children=[node("SOP-QC-0040_절차_Rev4.docx", "rev4", kind="archive-entry", links=header), std3])
    ledger = node("관리대장.xlsx", "ledger", links=[
        ("doc-number", "SOP-QC-0040 Rev.4", "점검!B12", "SOP-QC-0040 Rev.4 참조"),
        ("doc-number", "SOP-QC-0040 Rev.2", "점검!B13", "SOP-QC-0040 Rev.2 참조"),
        ("doc-number", "SOP-QC-0040 Rev.9", "점검!B14", "SOP-QC-0040 Rev.9 참조"),
        ("doc-number", "SOP-QC-0040", "점검!B15", "SOP-QC-0040 참조"),
        ("doc-number", "SOP-PD-0076 Rev.3", "점검!B20", "SOP-PD-0076 Rev.3 기준"),
        ("external-workbook", "file:///\\\\fs01\\qa\\[기준표_v2.xlsx]기준", "점검!F8", "='[기준표_v2.xlsx]기준'!C4"),
        ("hyperlink", "\\\\fs01\\qa\\양식\\점검표.xlsx", "양식!A2", "점검표 열기"),
        ("hyperlink", "https://intranet.example.com/qms/forms?id=1", "양식!A3", "양식"),
        ("unc-path", "\\\\fs01\\qa\\공용", "양식!A4", "공용 폴더"),
        ("unc-path", "\\\\fs01\\qa\\기준\\기준표_v1.xlsx", "양식!A5", "이전 기준"),
    ])
    result = build_lineage([
        doc("r4", "SOP-QC-0040_절차_Rev4.docx", "2026-06-01T09:00:00+09:00", rev4),
        doc("r5", "SOP-QC-0040_절차_Rev5.docx", "2026-11-01T09:00:00+09:00"),  # 구조 분석 전
        doc("z", "송부.zip", "2026-11-02T09:00:00+09:00", pack),
        doc("s2", "기준표_v2.xlsx", "2026-10-01T09:00:00+09:00", node("기준표_v2.xlsx", "std2")),
        doc("l", "관리대장.xlsx", "2026-11-03T09:00:00+09:00", ledger),
        doc("p1", "점검표.xlsx", "2026-11-03T10:00:00+09:00", node("점검표.xlsx", "form1")),
        doc("p2", "점검표.xlsx", "2026-11-03T10:10:00+09:00", node("점검표.xlsx", "form2")),
    ])
    instances, entries = result["instances"], result["entries"]
    sop = family_of(result, "SOP-QC-0040 절차")
    assert sop["analysed"] == "partial" and "not-analysed" in sop["flags"]
    rev4_entry = next(entries[e] for e in sop["entries"] if entries[e]["label"] == "Rev 4")
    assert rev4_entry["duplicates"] == 1 and instances["d:z/0"]["same_as"] == "d:r4"  # 압축 안 사본은 판이 아니라 중복
    std = family_of(result, "기준표")
    assert result["entries"][std["latest"]["entry"]]["contained_only"] and std["notes"]
    refs = {(r["target"], r["location"]): r for r in result["references"]}
    assert refs[("SOP-QC-0040 Rev.4", "점검!B12")]["state"] == "outdated" and refs[("SOP-QC-0040 Rev.4", "점검!B12")]["entry"] == rev4_entry["id"]
    assert refs[("SOP-QC-0040 Rev.2", "점검!B13")]["state"] == "outdated" and refs[("SOP-QC-0040 Rev.2", "점검!B13")]["entry"] is None
    assert refs[("SOP-QC-0040 Rev.9", "점검!B14")]["state"] == "missing" and refs[("SOP-QC-0040 Rev.9", "점검!B14")]["family"] == sop["id"]
    assert refs[("SOP-QC-0040", "점검!B15")]["state"] == "linked" and entries[refs[("SOP-QC-0040", "점검!B15")]["entry"]]["label"] == "Rev 5"
    assert refs[("SOP-PD-0076 Rev.3", "점검!B20")]["state"] == "missing" and refs[("SOP-PD-0076 Rev.3", "점검!B20")]["family"] is None
    workbook = refs[("file:///\\\\fs01\\qa\\[기준표_v2.xlsx]기준", "점검!F8")]
    assert workbook["state"] == "outdated" and workbook["match"] == "exact-name" and "v3" in workbook["note"]
    assert refs[("\\\\fs01\\qa\\양식\\점검표.xlsx", "양식!A2")]["state"] == "ambiguous" and len(refs[("\\\\fs01\\qa\\양식\\점검표.xlsx", "양식!A2")]["candidates"]) == 2
    assert refs[("https://intranet.example.com/qms/forms?id=1", "양식!A3")]["state"] == "external"
    assert refs[("\\\\fs01\\qa\\공용", "양식!A4")]["state"] == "external"
    older = refs[("\\\\fs01\\qa\\기준\\기준표_v1.xlsx", "양식!A5")]
    assert older["state"] == "outdated" and older["match"] == "name-rule" and older["family"] == std["id"]
    # 자기 문서번호(머리글)와 압축 안 사본의 링크는 참조로 세지 않는다.
    assert not any(r["source"].startswith("d:r4") or r["source"].startswith("d:z/0") for r in result["references"])
    assert sop["counts"]["self_mentions"] == 1
    assert sop["counts"]["in"]["outdated"] == 2 and sop["counts"]["in"]["missing"] == 1
    assert family_of(result, "관리대장")["counts"]["out"]["ambiguous"] == 1
    assert result["summary"]["contained"] == 2


def test_api_example_shows_every_state_and_live_is_read_only(tmp_path):
    with TestClient(create_app(Settings(runtime_dir=tmp_path))) as client:
        example = client.get("/api/lineage", params={"source": "example"}).json()
        assert example["source"] == "example" and example["documents"]["not_analysed"] >= 1
        assert {r["state"] for r in example["references"]} == {"linked", "outdated", "missing", "ambiguous", "external"}
        statuses = {f["latest"]["status"] for f in example["families"]}
        assert statuses == {"confirmed", "hold", "single"} and example["summary"]["duplicates"] >= 1 and example["summary"]["contained"] >= 5
        assert client.get("/api/lineage", params={"source": "other"}).status_code == 400

        empty = client.get("/api/lineage").json()
        assert empty["source"] == "live" and empty["families"] == [] and empty["documents"]["total"] == 0
        sop = docx(["SOP-QC-0040 Rev.5 세척 절차", "기준은 점검기준표_v2.xlsx 참고"], embeddings={"계산.xlsx": xlsx({"A1": "SOP-QC-0012 Rev.2"})})
        upload = lambda name, data: client.post("/api/live/documents", files={"file": (name, data, "application/octet-stream")}).json()
        first = upload("SOP-QC-0040_세척 절차_Rev4.docx", sop)
        second = upload("SOP-QC-0040_세척 절차_Rev5.docx", sop + b"")
        bundle = upload("묶음.zip", zip_bytes({"SOP-QC-0012_교정_Rev2.docx": docx(["교정 절차"])}))
        before = client.get("/api/lineage").json()
        assert before["documents"] == {"total": 3, "analysed": 0, "not_analysed": 3, "structure_errors": 0}
        family = next(f for f in before["families"] if f["docno"] == "SOP-QC-0040")
        assert family["counts"]["versions"] == 2 and family["analysed"] == "none" and before["references"] == []
        assert client.get(f"/api/live/documents/{second['id']}/structure").status_code == 409  # 조회가 분석을 시작하지 않는다.
        assert all(d["status"] == "uploaded" for d in client.get("/api/live/documents").json()["documents"])

        client.post(f"/api/live/documents/{second['id']}/structure")
        client.post(f"/api/live/documents/{bundle['id']}/structure")
        after = client.get("/api/lineage").json()
        assert after["documents"]["analysed"] == 2
        family = next(f for f in after["families"] if f["docno"] == "SOP-QC-0040")
        assert family["analysed"] == "partial" and family["counts"]["contained"] == 1
        states = {(r["target"], r["state"]) for r in after["references"]}
        assert ("SOP-QC-0012 Rev.2", "linked") in states  # 압축 안 파일과 문서번호로 연결
        linked = next(r for r in after["references"] if r["target"] == "SOP-QC-0012 Rev.2")
        assert after["instances"][linked["instance"]]["name"] == "SOP-QC-0012_교정_Rev2.docx" and linked["source_family"] == family["id"]
        assert not any(r["target"].startswith("SOP-QC-0040") for r in after["references"])  # 자기 문서번호는 제외
        assert after["instances"][f"d:{first['id']}"]["analysed"] is False
