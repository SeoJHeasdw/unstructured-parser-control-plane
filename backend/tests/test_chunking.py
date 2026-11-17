import pytest

from app.chunking import (MAX_CHUNKS, SAMPLE_MARKDOWN, ChunkingError, Source, estimate_tokens, normalize_params, parse_blocks,
                          run_strategy, sentence_bounds, token_weights)

STRATEGIES = [
    {"kind": "fixed", "params": {"unit": "chars", "size": 300, "overlap": 40}},
    {"kind": "recursive", "params": {"unit": "chars", "size": 300, "overlap": 40}},
    {"kind": "markdown", "params": {"unit": "chars", "size": 300}},
    {"kind": "sentence", "params": {"unit": "chars", "size": 300, "overlap_sentences": 1}},
    {"kind": "fixed", "params": {"unit": "tokens", "size": 120, "overlap": 20}},
    {"kind": "recursive", "params": {"unit": "tokens", "size": 120, "overlap": 20}},
    {"kind": "markdown", "params": {"unit": "tokens", "size": 120}},
    {"kind": "sentence", "params": {"unit": "tokens", "size": 120}},
]


def sentences(text):
    bounds = sentence_bounds(text, 0, len(text))
    return [text[a:b] for a, b in zip([0] + bounds, bounds + [len(text)])]


def test_token_estimate_counts_hangul_heavier_than_ascii():
    assert estimate_tokens("가나다라마바사아자차") == 10
    assert estimate_tokens("abcdefghij") == 3  # 0.5 + 9 * 0.25
    assert estimate_tokens("hello world") < estimate_tokens("안녕하세요 세계")
    assert estimate_tokens("2026") == 2 and estimate_tokens("   \n\t") == 0
    assert estimate_tokens("---") == 2  # 반복 기호는 가볍게
    assert sum(token_weights("SOP-QC-0040")) == pytest.approx(0.5 + 0.5 + 1 + 0.5 + 0.25 + 1 + 2.0)


def test_korean_sentence_boundaries_skip_list_numbers_and_abbreviations():
    parts = sentences("1. 첫 항목이다. 둘째 문장이에요? 그렇죠! Rev. 3 기준. 값은 3.5 mg이다. 끝.\n다음 줄")
    assert parts == ["1. 첫 항목이다. ", "둘째 문장이에요? ", "그렇죠! ", "Rev. 3 기준. ", "값은 3.5 mg이다. ", "끝.\n", "다음 줄"]
    assert sentences('그는 "끝났다." 라고 말했다.') == ['그는 "끝났다." ', "라고 말했다."]


def test_markdown_blocks_find_headings_tables_and_code():
    text = "# 제목\n\n본문 한 줄\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n\n```\n# 코드 속 제목 아님\n```\n## 다음"
    blocks = parse_blocks(text)
    assert [b.kind for b in blocks] == ["heading", "text", "table", "code", "heading"]
    table = blocks[2]
    assert text[table.start:table.header_end] == "| a | b |\n| --- | --- |"
    assert [text[s:e] for s, e in table.rows] == ["| 1 | 2 |", "| 3 | 4 |"]
    assert blocks[4].title == "다음" and blocks[4].level == 2


@pytest.mark.parametrize("spec", STRATEGIES, ids=lambda s: f"{s['kind']}-{s['params']['unit']}")
def test_every_strategy_covers_the_source_and_keeps_offsets(spec):
    src = Source(SAMPLE_MARKDOWN)
    result = run_strategy(src, spec, limit_tokens=512)
    chunks = result["chunks"]
    assert chunks and result["stats"]["coverage"] == 1.0
    assert [c["index"] for c in chunks] == list(range(len(chunks)))
    unit, size = result["params"]["unit"], result["params"]["size"]
    for c in chunks:
        assert 0 <= c["start"] < c["end"] <= src.n
        if "table-split" in c["flags"] and c["text"] != SAMPLE_MARKDOWN[c["start"]:c["end"]]:
            assert c["text"].startswith("| 구분 |") or c["text"].startswith("| 개정 |")  # 머리행 반복
        else:
            assert c["text"] == SAMPLE_MARKDOWN[c["start"]:c["end"]]
            assert c["text"] == c["text"].strip()
        length = c["chars"] if unit == "chars" else c["est_tokens"]
        assert length <= size + (2 if unit == "tokens" else 0), c
        assert c["kind"] in ("text", "table", "mixed")
        assert c["chars"] == len(c["text"])
    stats = result["stats"]
    assert stats["count"] == len(chunks) and stats["tables_total"] == 2
    assert stats["chars"]["min"] <= stats["chars"]["median"] <= stats["chars"]["p95"] <= stats["chars"]["max"]


def test_fixed_windows_overlap_by_the_requested_amount():
    text = "가" * 1000
    chunks = run_strategy(Source(text), {"kind": "fixed", "params": {"unit": "chars", "size": 300, "overlap": 50}})["chunks"]
    assert [(c["start"], c["end"]) for c in chunks] == [(0, 300), (250, 550), (500, 800), (750, 1000)]
    stats = run_strategy(Source(text), {"kind": "fixed", "params": {"unit": "chars", "size": 300, "overlap": 50}})["stats"]
    assert stats["duplication"] == pytest.approx(150 / 1000)


def test_recursive_prefers_paragraphs_then_sentences_then_hard_split():
    para_a = "첫 문단의 문장이다. " * 8
    para_b = "둘째 문단이다. " * 3
    text = para_a.strip() + "\n\n" + para_b.strip() + "\n\n" + "가" * 260
    result = run_strategy(Source(text), {"kind": "recursive", "params": {"unit": "chars", "size": 100, "overlap": 0}})
    texts = [c["text"] for c in result["chunks"]]
    assert all(t.endswith("다.") for t in texts[:2])  # 첫 문단은 문장 경계에서 나뉜다
    assert para_b.strip() in texts
    assert [c for c in result["chunks"] if "hard-split" in c["flags"]]  # 띄어쓰기 없는 긴 줄은 글자 단위
    assert result["stats"]["coverage"] == 1.0


def test_markdown_keeps_heading_path_and_small_tables_whole():
    text = "# 문서\n\n## 1장\n\n### 1.1 절\n\n본문 하나.\n\n| 항목 | 값 |\n| --- | --- |\n| 온도 | 5 °C |\n\n## 2장\n\n둘째 장 본문."
    chunks = run_strategy(Source(text), {"kind": "markdown", "params": {"unit": "chars", "size": 400, "merge_small": False}})["chunks"]
    by_text = {c["text"].splitlines()[0]: c for c in chunks}
    assert by_text["### 1.1 절"]["heading_path"] == ["문서", "1장", "1.1 절"]
    assert by_text["### 1.1 절"]["kind"] == "mixed" and "| 온도 | 5 °C |" in by_text["### 1.1 절"]["text"]
    assert by_text["## 2장"]["heading_path"] == ["문서", "2장"]
    assert "heading-only" in by_text["# 문서"]["flags"] and "heading-only" in by_text["## 1장"]["flags"]
    merged = run_strategy(Source(text), {"kind": "markdown", "params": {"unit": "chars", "size": 400, "merge_small": True, "min_size": 50}})["chunks"]
    assert not any("heading-only" in c["flags"] for c in merged)
    first = merged[0]
    assert first["text"].startswith("# 문서\n\n## 1장\n\n### 1.1 절") and first["heading_path"] == ["문서", "1장", "1.1 절"]
    assert "merged-sections" in first["flags"]


def test_markdown_splits_large_tables_by_rows_and_repeats_header():
    rows = "\n".join(f"| 장비 {i:02d} | {i}.5 °C | 1일 {i % 3 + 1}회 |" for i in range(40))
    text = f"## 보관 조건\n\n| 장비 | 온도 | 주기 |\n| --- | --- | --- |\n{rows}\n\n표 아래 문장."
    result = run_strategy(Source(text), {"kind": "markdown", "params": {"unit": "chars", "size": 300}})
    pieces = [c for c in result["chunks"] if "table-split" in c["flags"]]
    assert len(pieces) >= 4 and result["stats"]["tables_split"] == 1
    assert pieces[0]["text"].startswith("## 보관 조건\n\n| 장비 | 온도 | 주기 |")
    for piece in pieces[1:]:
        assert piece["text"].startswith("| 장비 | 온도 | 주기 |\n| --- | --- | --- |\n| 장비 ")
        assert text[piece["start"]:piece["end"]].startswith("| 장비 ") and piece["kind"] == "table"
        assert piece["chars"] <= 300 and "table-no-header" not in piece["flags"]
    body = "".join(text[p["start"]:p["end"]] for p in pieces)
    assert all(f"| 장비 {i:02d} |" in body for i in range(40))  # 행이 빠지지 않는다
    fixed = run_strategy(Source(text), {"kind": "fixed", "params": {"unit": "chars", "size": 300, "overlap": 0}})
    assert fixed["stats"]["flags"].get("table-cut") and fixed["stats"]["flags"].get("table-no-header")


def test_sentence_groups_with_overlap_and_splits_long_sentences():
    text = " ".join(f"{i}번째 문장입니다." for i in range(1, 21))
    chunks = run_strategy(Source(text), {"kind": "sentence", "params": {"unit": "chars", "size": 60, "overlap_sentences": 1}})["chunks"]
    assert chunks[0]["text"].startswith("1번째") and all(c["chars"] <= 60 for c in chunks)
    for a, b in zip(chunks, chunks[1:]):
        assert b["start"] < a["end"]  # 한 문장씩 겹친다
        assert a["text"].split(". ")[-1].rstrip(".") in b["text"]
    long = "가나다 " * 60 + "끝."
    split = run_strategy(Source(long), {"kind": "sentence", "params": {"unit": "chars", "size": 60, "overlap_sentences": 0}})
    assert all("sentence-split" in c["flags"] for c in split["chunks"]) and split["stats"]["coverage"] == 1.0


def test_over_limit_flags_and_stats_use_the_target_token_limit():
    src = Source(SAMPLE_MARKDOWN)
    result = run_strategy(src, {"kind": "fixed", "params": {"unit": "chars", "size": 600, "overlap": 0}}, limit_tokens=200)
    over = [c for c in result["chunks"] if "over-limit" in c["flags"]]
    assert over and all(c["est_tokens"] > 200 for c in over)
    assert result["stats"]["over_limit"] == len(over) == result["stats"]["flags"]["over-limit"]
    assert result["stats"]["total_tokens"] == sum(c["est_tokens"] for c in result["chunks"])


def test_parameters_are_clamped_and_invalid_input_rejected():
    assert normalize_params("fixed", {"unit": "chars", "size": 10, "overlap": 999}) == {"unit": "chars", "size": 50, "overlap": 25}
    assert normalize_params("sentence", {"unit": "tokens", "size": 100000, "overlap_sentences": 9}) == {"unit": "tokens", "size": 8000, "overlap_sentences": 5}
    assert normalize_params("markdown", {})["merge_small"] is True
    with pytest.raises(ChunkingError):
        normalize_params("semantic", {})
    with pytest.raises(ChunkingError):
        normalize_params("fixed", {"unit": "words"})
    with pytest.raises(ChunkingError):
        normalize_params("fixed", {"size": "많이"})
    with pytest.raises(ChunkingError):
        Source("가" * 400_001)


def test_chunk_count_is_capped():
    with pytest.raises(ChunkingError):
        run_strategy(Source("가" * 300_000), {"kind": "fixed", "params": {"unit": "chars", "size": 50, "overlap": 25}})
    assert MAX_CHUNKS == 10_000


def test_crlf_text_keeps_offsets():
    text = "# 제목\r\n\r\n첫 문장이다. 둘째 문장이다.\r\n\r\n| a | b |\r\n| --- | --- |\r\n| 1 | 2 |\r\n"
    for spec in STRATEGIES[:4]:
        result = run_strategy(Source(text), {**spec, "params": {**spec["params"], "size": 60}})
        assert result["stats"]["coverage"] == 1.0
        for c in result["chunks"]:
            if "table-split" not in c["flags"]:
                assert c["text"] == text[c["start"]:c["end"]]
