import pytest

from app.chunking import (MAX_CHUNKS, SAMPLE_MARKDOWN, ChunkingError, NeedsEmbedding, Source, estimate_tokens, normalize_params, parse_blocks,
                          run_strategy, semantic_units, sentence_bounds, token_weights)

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


def test_markdown_heading_only_section_joins_its_subsection_not_the_previous_body():
    text = "## 1장\n\n본문 하나.\n\n## 2장\n\n### 2.1 절\n\n둘째 본문."
    chunks = run_strategy(Source(text), {"kind": "markdown", "params": {"unit": "chars", "size": 400, "merge_small": True, "min_size": 200}})["chunks"]
    assert [c["text"] for c in chunks] == ["## 1장\n\n본문 하나.", "## 2장\n\n### 2.1 절\n\n둘째 본문."]


def test_chunking_imports_only_the_standard_library():
    import ast
    import sys
    from pathlib import Path
    import app.chunking
    tree = ast.parse(Path(app.chunking.__file__).read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert {name.split(".")[0] for name in imported} <= set(sys.stdlib_module_names)


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
        normalize_params("llm_guess", {})
    semantic = normalize_params("semantic", {"unit": "chars", "size": 600, "breakpoint": 10, "buffer": 9, "min_size": 9999})
    assert semantic == {"unit": "chars", "size": 600, "min_size": 600, "breakpoint": 50, "buffer": 3, "connection": "embed", "model": ""}
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


# ---------------------------------------------------------------- 의미 기반

TOPIC = {"펌프": [1.0, 0.0, 0.0], "배관": [0.0, 1.0, 0.0], "표": [0.0, 0.0, 1.0]}


def topic_embed(calls=None):
    """창 글에서 가장 많이 나온 주제어 방향의 벡터. 어떤 글을 임베딩했는지 calls에 남긴다."""
    def embed(texts):
        if calls is not None:
            calls.extend(texts)
        out = []
        for text in texts:
            counts = [text.count(word) for word in ("펌프", "배관")]
            out.append([counts[0] + 0.01, counts[1] + 0.01, 0.01])
        return out
    return embed


SEMANTIC_DOC = """# 점검 보고

펌프 진동을 측정했다. 펌프 베어링 온도도 확인했다. 펌프 소음은 정상이었다. 펌프 정렬을 다시 맞췄다.
배관 누설을 점검했다. 배관 보온재가 일부 손상되었다. 배관 지지대는 양호했다. 배관 플랜지를 다시 조였다.

## 측정값

| 항목 | 값 |
|---|---|
| 진동 | 2.1 |

## 다음 조치
### 일정
다음 점검은 3개월 뒤다.
"""


def test_semantic_chunking_breaks_where_meaning_changes_and_respects_structure():
    calls = []
    result = run_strategy(Source(SEMANTIC_DOC), {"kind": "semantic", "params": {"unit": "chars", "size": 400, "min_size": 0, "buffer": 0, "breakpoint": 90}}, embed=topic_embed(calls))
    texts = [c["text"] for c in result["chunks"]]
    pump = next(t for t in texts if "펌프 진동" in t)
    assert "배관" not in pump and pump.startswith("# 점검 보고")          # 제목은 첫 문장에 붙고, 주제가 바뀌는 곳에서 끊는다
    assert any(t.startswith("배관 누설") and "플랜지" in t for t in texts)
    table = next(t for t in texts if "| 진동 |" in t)
    assert table.startswith("## 측정값") and "배관" not in table and "다음 점검" not in table  # 표는 위 제목과 함께, 앞뒤 문장과는 섞지 않는다
    assert any(t.startswith("## 다음 조치\n### 일정") for t in texts)    # 연달아 나온 제목은 함께 다음 문장에 붙는다
    assert not any(c["flags"] and "heading-only" in c["flags"] for c in result["chunks"])
    assert result["semantic"]["breakpoints"] >= 1 and result["stats"]["coverage"] == 1.0
    assert not any("| 진동 |" in text for text in calls)                  # 표는 임베딩하지 않는다


def test_semantic_chunking_needs_an_embedder_and_caps_size():
    with pytest.raises(ChunkingError, match="임베딩"):
        run_strategy(Source(SEMANTIC_DOC), {"kind": "semantic", "params": {}})

    def refuse(texts):
        raise NeedsEmbedding(len(texts), len(texts))
    with pytest.raises(NeedsEmbedding):
        run_strategy(Source(SEMANTIC_DOC), {"kind": "semantic", "params": {}}, embed=refuse)
    long = "펌프 점검 문장이다. " * 200
    result = run_strategy(Source(long), {"kind": "semantic", "params": {"unit": "chars", "size": 300}}, embed=topic_embed())
    assert all(c["chars"] <= 300 for c in result["chunks"]) and result["semantic"]["size_cuts"] > 0


def test_semantic_units_window_does_not_cross_sections():
    units = semantic_units(Source(SEMANTIC_DOC))
    assert sum(u.atomic for u in units) == 1 and units[0].hard
    calls = []
    text = "## A\n\n펌프 문장 하나다. 펌프 문장 둘이다.\n\n## B\n\n배관 문장 하나다. 배관 문장 둘이다."
    run_strategy(Source(text), {"kind": "semantic", "params": {"unit": "chars", "size": 400, "buffer": 1}}, embed=topic_embed(calls))
    assert calls and not any("펌프" in window and "배관" in window for window in calls)


def test_semantic_chunking_keeps_figures_and_table_captions_with_their_targets():
    from app.chunking import sample_source
    import zlib

    def hashed(texts):
        out = []
        for text in texts:
            vec = [0.0] * 64
            for a, b in zip(text, text[1:]):
                vec[zlib.crc32((a + b).encode()) % 64] += 1.0
            out.append(vec)
        return out
    for sample in ("report", "sop", "coa"):
        src = sample_source(sample)
        semantic = run_strategy(src, {"kind": "semantic", "params": {"unit": "chars", "size": 800}}, embed=hashed)
        element = run_strategy(src, {"kind": "element", "params": {"unit": "chars", "size": 800}})
        assert semantic["by_kind"].get("caption") == element["by_kind"].get("caption")   # 캡션은 대상과 같은 청크
        assert set(semantic["by_kind"].get("table", {})) <= {"whole"}                      # 표는 통째
        assert semantic["stats"]["coverage"] == 1.0


@pytest.mark.parametrize("text, expected", [
    # 표 위에 제목이 붙으면 그 앞 캡션은 앞 절(그림)의 것이다
    ("<!-- image -->\n그림 1. 펌프 사진\n\n## 2장\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n",
     ["<!-- image -->\n그림 1. 펌프 사진", "## 2장\n\n| a | b |\n| --- | --- |\n| 1 | 2 |"]),
    # 쪼개진 캡션은 제목에서 시작한 조각까지만 표에 붙는다
    ("<!-- image -->\n그림 1. 펌프 사진\n\n## 2장\n\n표 1. 압력 기록\n측정 조건\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n",
     ["<!-- image -->\n그림 1. 펌프 사진", "## 2장\n\n표 1. 압력 기록\n측정 조건\n\n| a | b |\n| --- | --- |\n| 1 | 2 |"]),
    # 표 바로 아래 캡션은 표와 한 덩어리
    ("| a | b |\n| --- | --- |\n| 1 | 2 |\n\n표 1. 압력 기록\n\n배관 점검 문단이다.\n",
     ["| a | b |\n| --- | --- |\n| 1 | 2 |\n\n표 1. 압력 기록", "배관 점검 문단이다."]),
])
def test_semantic_table_captions_belong_to_their_own_section(text, expected):
    params = {"unit": "chars", "size": 400, "min_size": 0, "buffer": 0, "breakpoint": 90}
    chunks = run_strategy(Source(text), {"kind": "semantic", "params": params}, embed=topic_embed())["chunks"]
    assert [c["text"] for c in chunks] == expected
