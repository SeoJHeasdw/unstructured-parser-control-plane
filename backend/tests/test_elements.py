"""비정형 요소 인식과 요소 인식 청킹. 합성 예시 문서만 쓴다."""
import pytest

from app.chunking import (EXAMPLE_QUESTIONS, SAMPLES, ChunkingError, Source, answer_offset, infer_question_kind, line_pages,
                          normalize_params, run_strategy, sample_source)


def by_label(src, prefix):
    return [el for el in src.elements if el.label.startswith(prefix)]


def run(src, kind, **params):
    return run_strategy(src, {"kind": kind, "params": {"unit": "chars", **params}})


def test_samples_are_parsed_into_typed_elements_with_pages():
    expected = {
        "sop": ({"heading": 13, "text": 8, "list": 3, "table": 2, "image": 1, "caption": 3, "furniture": 8}, 4),
        "report": ({"heading": 10, "text": 7, "list": 1, "table": 1, "image": 7, "caption": 7, "furniture": 8}, 5),
        "coa": ({"heading": 6, "text": 3, "list": 1, "table": 4, "caption": 4, "furniture": 6}, 3),
    }
    for sid, (composition, pages) in expected.items():
        src = sample_source(sid)
        assert src.composition() == composition, sid
        assert src.pages == pages and [el.id for el in src.elements] == [f"e{i}" for i in range(1, len(src.elements) + 1)]
        for el in src.elements:
            assert src.text[el.start:el.end] == src.text[el.start:el.end].strip() and el.page is not None
            if el.kind == "caption":  # 캡션과 대상이 서로 가리킨다
                assert src.by_id[el.caption_of].caption == el.id
        assert all(el.caption is None or src.by_id[el.caption].caption_of == el.id for el in src.elements)
    sop = sample_source("sop")
    assert [el.label for el in sop.elements if el.kind == "table"] == ["표 1 · 14행 × 5열", "표 2 · 3행 × 3열"]
    assert by_label(sop, "제목 · 4. 보관 조건")[0].path == ("시료 보관 및 장비 점검 절차 (합성 예시)", "4. 보관 조건")
    assert by_label(sop, "그림 1 · 냉장고 배치도")[0].page == 2 and by_label(sop, "캡션 · 그림 1")
    assert [el.label for el in sop.elements if el.kind == "list"] == ["목록 · 3항목", "목록 · 4항목", "목록 · 3항목"]
    furniture = [el for el in sop.elements if el.kind == "furniture"]
    assert {el.label for el in furniture} == {"반복 머리말", "쪽 번호"} and [el.page for el in furniture if el.label == "쪽 번호"] == [1, 2, 3, 4]
    report = sample_source("report")
    empty = [el for el in report.elements if el.kind == "image" and el.empty]
    assert len(empty) == 1 and empty[0].page == 4 and empty[0].label == "그림 · 글자 없음"
    chart = next(el for el in report.elements if el.kind == "image" and el.alt)
    assert "9월 3.4" in chart.alt and report.by_id[chart.caption].title == "펌프 P-2 월별 진동 추이"
    coa = sample_source("coa")
    tables = [el for el in coa.elements if el.kind == "table"]
    assert [(t.rows, t.cols, t.page) for t in tables] == [(14, 6, 1), (10, 6, 2), (6, 9, 2), (4, 4, 3)]
    assert coa.by_id[tables[1].caption].title == "품질 시험 결과(계속)"  # 쪽을 넘어간 표의 이어지는 부분
    public = tables[0].public(coa)
    assert public["rows"] == 14 and public["caption"] == tables[0].caption and public["est_tokens"] > 0


def test_element_rules_for_lists_code_captions_and_pages():
    text = ("# 제목\n\n- 하나\n  이어지는 줄\n- 둘\n\n중간 문단\n\n1. 첫째\n\n2. 둘째\n\n```\n| 코드 속 표 아님 |\n```\n\n$$\nE = mc^2\n$$\n\n"
            "표 3. 떨어진 캡션은 연결하지 않는다\n\n\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n표 아래 문단.\n\n그림 9 옆에 그림이 없는 문장.\n\n"
            "## 다음 절\n\n![Image](a.png)\n\n![장비 사진: 밸브 V-3](b.png)\n\n그림 2. 밸브\n\n3 / 12\n\n페이지 7")
    src = Source(text)
    kinds = [el.kind for el in src.elements]
    assert kinds == ["heading", "list", "text", "list", "code", "code", "text", "table", "text", "text", "heading",
                     "image", "image", "caption", "furniture", "furniture"]
    assert src.elements[1].items == 2 and src.elements[3].items == 2 and src.elements[5].label == "수식"  # 빈 줄 하나 사이 번호 목록은 이어진다
    assert src.elements[7].caption is None and src.elements[7].label == "표 1 · 1행 × 2열"  # 캡션이 없으면 순서 번호
    generic, described = src.elements[11], src.elements[12]
    assert generic.alt == "" and generic.empty and generic.label == "그림 · 글자 없음"  # Docling 기본 대체 텍스트는 내용이 아니다
    assert described.alt == "장비 사진: 밸브 V-3" and not described.empty and described.caption == src.elements[13].id
    assert [el.label for el in src.elements[14:]] == ["쪽 번호", "쪽 번호"]
    assert src.pages is None and all(el.page is None for el in src.elements)
    # 저장된 결과의 줄→쪽 정보(1부터 세는 줄)를 쓴다
    paged = Source("가\n\n나\n\n다", line_pages([{"start_line": 1, "end_line": 1, "page": 1}, {"start_line": 5, "end_line": 5, "page": 2}], "가\n\n나\n\n다"))
    assert [el.page for el in paged.elements] == [1, 1, 2] and paged.pages == 2
    breaks = Source("가\n\n<!-- page break -->\n\n나")
    assert [el.page for el in breaks.elements] == [1, 2]


def test_repeated_docling_placeholders_are_not_page_furniture():
    text = "\n\n".join(f"식 {n}의 설명\n<!-- formula-not-decoded -->" for n in range(4))
    assert [el.kind for el in Source(text).elements] == ["text"] * 4


def test_baseline_outcomes_mark_split_tables_and_bare_image_placeholders():
    coa = sample_source("coa")
    fixed = run(coa, "fixed", size=400, overlap=0)
    long_table = next(el for el in coa.elements if el.kind == "table")
    assert fixed["outcomes"][long_table.id] == "split" and fixed["by_kind"]["table"]["split"] >= 1
    assert sum(sum(v.values()) for v in fixed["by_kind"].values()) == len(coa.elements)
    covered = {eid for c in fixed["chunks"] for eid in c["elements"]}
    assert covered == set(coa.by_id)  # 기준선은 원문을 모두 덮으므로 모든 요소가 어느 청크엔가 있다
    assert fixed["outcomes"][next(el.id for el in coa.elements if el.kind == "furniture")] == "whole"
    markdown = run(coa, "markdown", size=400)
    assert markdown["outcomes"][long_table.id] == "rows"  # 머리행을 반복해 나눈다
    text = "가나다 " * 40 + "\n\n<!-- image -->\n\n" + "라마바 " * 40 + "\n\n그림 1. 펌프 사진"
    src = Source(text)
    image = next(el for el in src.elements if el.kind == "image")
    assert image.caption is None and image.empty  # 캡션이 빈 줄 하나보다 멀면 연결하지 않는다
    near = Source("가나다 " * 40 + "\n\n<!-- image -->\n\n그림 1. 펌프 사진\n\n" + "라마바 " * 40)
    image = next(el for el in near.elements if el.kind == "image")
    apart = run(near, "fixed", size=near.by_id[image.caption].start, overlap=0)  # 그림과 캡션 사이에서 자른다
    together = run(near, "recursive", size=400, overlap=0)
    assert apart["outcomes"][image.id] == "missing" and apart["outcomes"][image.caption] == "detached"
    assert together["outcomes"][image.id] == "caption" and together["outcomes"][image.caption] == "attached"
    assert apart["chunks"][0]["page"] is None and apart["chunks"][0]["parent"] is None


def test_element_strategy_keeps_tables_and_images_out_of_prose():
    report = sample_source("report")
    result = run(report, "element", size=300)
    for c in result["chunks"]:
        kinds = set(c["element_kinds"]) - {"heading"}
        assert not ({"table", "image"} & kinds and {"text", "list"} & kinds), c
        assert c["parent"] is None and c["page"] is not None
    images = [c for c in result["chunks"] if "image" in c["element_kinds"]]
    assert len(images) == 6 and all(c["text"].startswith("[그림] 그림 ") for c in images)
    assert any("9월 3.4" in c["text"] for c in images)  # 대체 텍스트도 내용이다
    assert result["by_kind"]["image"] == {"caption": 6, "missing": 1} and result["by_kind"]["caption"] == {"attached": 7}
    assert result["by_kind"]["furniture"] == {"missing": 8} and result["stats"]["flags"]["image-empty"] == 1
    assert not any("설비 점검 보고서 · RPT-EX-2611" in c["text"] for c in result["chunks"])
    dropped = run(report, "element", size=300, image="drop", drop_furniture=False)
    assert dropped["by_kind"]["image"] == {"missing": 7} and dropped["by_kind"]["caption"] == {"detached": 6, "attached": 1}  # 표 캡션은 표에
    assert dropped["by_kind"]["furniture"] == {"whole": 8} and "image-empty" not in dropped["stats"]["flags"]
    assert any(c["text"].startswith("그림 2. 냉각수 순환 계통도") or "\n\n그림 2. 냉각수" in c["text"] for c in dropped["chunks"])


def test_table_policies_whole_rows_and_row_text():
    coa = sample_source("coa")
    first = next(el for el in coa.elements if el.kind == "table")
    caption = coa.by_id[first.caption]
    whole = run(coa, "element", size=2000, table="whole")
    assert whole["outcomes"][first.id] == "whole" and whole["outcomes"][caption.id] == "attached"
    table_chunk = next(c for c in whole["chunks"] if first.id in c["elements"])
    assert table_chunk["kind"] == "table" and "표 1. 품질 시험 결과\n| 시험 항목 |" in table_chunk["text"]
    assert table_chunk["text"].startswith("## 2. 시험 결과")  # 바로 앞 제목만 함께 붙는다
    fallback = run(coa, "element", size=400, table="whole", table_rows=50)
    assert fallback["outcomes"][first.id] == "rows"  # 크기를 넘으면 행 묶음으로 바꾼다
    rows = run(coa, "element", size=2000, table="rows", table_rows=5)
    pieces = [c for c in rows["chunks"] if first.id in c["elements"]]
    assert rows["outcomes"][first.id] == "rows" and len(pieces) == 3
    for piece in pieces:
        assert "표 1. 품질 시험 결과\n| 시험 항목 | 시험 방법 | 단위 | 기준 | 결과 | 판정 |\n| --- |" in piece["text"]
        assert "table-split" in piece["flags"] and "table-no-header" not in piece["flags"]
        assert caption.id in piece["elements"]
    assert [p["start"] for p in pieces] == sorted(p["start"] for p in pieces) and pieces[0]["start"] < first.start
    bare = run(coa, "element", size=2000, table="rows", table_rows=5, attach_caption=False)
    assert bare["outcomes"][caption.id] == "detached"
    assert all(not c["text"].startswith("표 1. 품질") for c in bare["chunks"] if first.id in c["elements"])
    row_text = run(coa, "element", size=600, table="row_text")
    texts = "\n".join(c["text"] for c in row_text["chunks"])
    assert "시험 항목: 비소, 시험 방법: 유도결합플라스마 질량분석, 단위: ppm, 기준: 0.5 이하, 결과: 0.1 미만, 판정: 적합" in texts
    assert "원료명: 염화칼륨, 원료 로트: RM-0205-A" in texts and "| --- |" not in texts
    assert row_text["outcomes"][first.id] == "rows" and all(c["chars"] <= 600 for c in row_text["chunks"])


def test_parent_child_returns_small_children_linked_to_parents():
    sop = sample_source("sop")
    result = run(sop, "parent_child", size=200, parent_size=900)
    assert result["params"]["parent_size"] == 900
    parents, chunks = result["parents"], result["chunks"]
    assert parents and [p["index"] for p in parents] == list(range(len(parents)))
    assert {c["parent"] for c in chunks} == set(range(len(parents)))
    for c in chunks:
        parent = parents[c["parent"]]
        assert parent["start"] <= c["start"] and c["end"] <= parent["end"]
        assert c["chars"] <= 200 or "over-size" in c["flags"]
    assert max(p["chars"] for p in parents) > 200 and all(p["chars"] <= 900 for p in parents)
    assert parents[0]["heading_path"] and isinstance(parents[0]["est_tokens"], int)
    assert normalize_params("parent_child", {"size": 300, "parent_size": 100})["parent_size"] == 300  # 자식보다 작을 수 없다


def test_page_strategy_groups_by_page_and_splits_large_pages():
    for sid in SAMPLES:
        src = sample_source(sid)
        result = run(src, "page", size=20_000)
        pages = sorted({el.page for el in src.elements if el.kind != "furniture" and not (el.kind == "image" and el.empty)})
        assert [c["page"] for c in result["chunks"]] == pages, sid
        for c in result["chunks"]:
            assert {src.by_id[e].page for e in c["elements"]} == {c["page"]}
    report = run(sample_source("report"), "page", size=20_000)
    assert 4 not in [c["page"] for c in report["chunks"]]  # 글자 없는 스캔 쪽은 청크가 없다
    small = run(sample_source("coa"), "page", size=300, table="rows", table_rows=4)
    assert len(small["chunks"]) > 3 and all(c["chars"] <= 300 or "over-size" in c["flags"] for c in small["chunks"])
    assert [c["page"] for c in small["chunks"]] == sorted(c["page"] for c in small["chunks"])
    assert small["outcomes"][next(el.id for el in sample_source("coa").elements if el.kind == "table")] == "rows"


def test_new_strategy_parameters_are_validated():
    params = normalize_params("element", {"size": 500})
    assert params == {"unit": "chars", "size": 500, "overlap": 0, "table": "whole", "table_rows": 10, "image": "caption",
                      "attach_caption": True, "drop_furniture": True}
    assert "overlap" not in normalize_params("page", {}) and normalize_params("page", {"table_rows": 0})["table_rows"] == 1
    with pytest.raises(ChunkingError):
        normalize_params("element", {"table": "merge"})
    with pytest.raises(ChunkingError):
        normalize_params("page", {"image": "ocr"})


def test_example_questions_point_at_literal_answers_and_inferred_kinds_match():
    kinds = {"text": 0, "table": 0, "image": 0}
    for q in EXAMPLE_QUESTIONS:
        sid = q["doc_id"].split(":", 1)[1]
        src = sample_source(sid)
        assert answer_offset(src, q["answer"]) is not None, q
        assert infer_question_kind(src, q["answer"]) == q["kind"], q
        kinds[q["kind"]] += 1
    assert all(kinds.values()) and {q["doc_id"] for q in EXAMPLE_QUESTIONS} == {f"sample:{sid}" for sid in SAMPLES}
    sop = sample_source("sop")
    assert infer_question_kind(sop, "없는 문구") == "text" and infer_question_kind(sop, "") == "text"
    assert infer_question_kind(sample_source("report"), "500 µs/CM 이하") == "table"  # 정답 문구 비교와 같은 정규화
