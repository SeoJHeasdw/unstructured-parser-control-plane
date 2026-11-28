"""규모 측정(합성 1,500건)에서 나온 문제의 회귀 테스트. 합성 파일과 임시 저장소만 쓴다."""
import io
import random
import time
from collections import Counter

import pytest

from app import source_text, verify as verify_module
from app.adapters.registry import ParserRegistry
from app.config import Settings
from app.source_text import read_source
from app.verify import verify


@pytest.fixture
def small_source_limit(monkeypatch):
    # 400만 자 상한을 넘는 파일 대신 상한을 낮춰 같은 경로를 탄다.
    monkeypatch.setattr(source_text, "MAX_CHARS", 30_000)


def _text_result(registry, path, fmt):
    out = io.StringIO()
    parsed = registry.text.write_to(path, fmt, out, None)
    return parsed, out.getvalue()


def test_truncated_csv_does_not_flag_unread_rows_but_still_catches_read_ones(tmp_path, small_source_limit):
    settings = Settings(runtime_dir=tmp_path / "rt")
    registry = ParserRegistry(settings)
    path = tmp_path / "big.csv"
    path.write_text("id,item,value,unit\n" + "".join(f"{i},항목 {i % 97},{i * 0.37:.2f},mg/mL\n" for i in range(1, 4001)), encoding="utf-8")
    parsed, markdown = _text_result(registry, path, "CSV")
    source = read_source(path, "CSV", settings, {"encoding": parsed.evidence["encoding"], "delimiter": parsed.evidence["delimiter"]})
    assert source.truncated
    clean = verify(source, markdown, [], parsed.parser, "CSV", parsed.evidence)
    assert clean["spots_total"] == 0                                    # 예전: 읽지 않은 행이 모두 row_extra(높음)
    truncated = next(r for r in clean["reasons"] if r["code"] == "truncated")
    assert truncated["blocking"] and truncated["unread"] > 3000          # 확인하지 않은 범위로 센다
    tampered = markdown.replace("| 100 | 항목 3 | 37.00 |", "| 100 | 항목 3 | 37.80 |")
    assert tampered != markdown
    spots = verify(source, tampered, [], parsed.parser, "CSV", parsed.evidence)["spots"]
    assert [(s["kind"], s["severity"]) for s in spots] == [("cell_changed", "high")]


def test_truncated_text_compares_only_the_read_range(tmp_path, small_source_limit):
    settings = Settings(runtime_dir=tmp_path / "rt")
    registry = ParserRegistry(settings)
    path = tmp_path / "big.txt"
    path.write_text("".join(f"{i}번째 줄: 압력 {i * 0.3:.1f} bar, 온도 {i % 40} ℃\n" for i in range(1, 20001)), encoding="utf-8")
    parsed, markdown = _text_result(registry, path, "TXT")
    source = read_source(path, "TXT", settings, None)
    assert source.truncated
    assert verify(source, markdown, [], parsed.parser, "TXT", parsed.evidence)["spots_total"] == 0   # 예전: extra_number 수만 곳
    # 뒤쪽(읽지 않은 범위)의 '330.0'·'630.0'에 같은 '30.0'이 있어도 앞의 바뀐 값을 놓치지 않는다(예전에는 '다른 곳에 있음'으로 넘어감)
    changed = markdown.replace("\n100번째 줄: 압력 30.0", "\n100번째 줄: 압력 30.9")
    spots = verify(source, changed, [], parsed.parser, "TXT", parsed.evidence)["spots"]
    assert [(s["kind"], s["severity"]) for s in spots] == [("changed", "high")]
    deleted = markdown.replace("\n500번째 줄: 압력 150.0 bar, 온도 20 ℃", "")
    spots = verify(source, deleted, [], parsed.parser, "TXT", parsed.evidence)["spots"]
    assert spots and all(s["severity"] == "high" for s in spots) and any(s["ref"] == "500줄" for s in spots)


def test_every_table_on_a_sheet_keeps_worksheet_rows(tmp_path):
    pytest.importorskip("docling.document_converter")
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "기록"
    sheet.append(["LOT", "압력", "단위"])
    for r in range(1, 401):
        sheet.append([f"LOT-{r}", r * 1.5, "bar"])
    sheet.merge_cells("A404:B404")                                     # 표 아래 일부 칸만 병합한 비고(따로 떨어진 표가 된다)
    sheet["A404"] = "비고: 재측정 필요"
    blocks = book.create_sheet("두 블록")
    blocks.append(["항목", "값"])
    blocks.append(["pH", 7.2])
    blocks.append([])
    blocks.append([])
    blocks.append(["항목", "값"])
    blocks.append(["온도", 25])
    path = tmp_path / "기록.xlsx"
    book.save(path)
    settings = Settings(runtime_dir=tmp_path / "rt")
    parsed = ParserRegistry(settings).parse(path, "XLSX")
    rows = Counter(location.sheet for location in parsed.locations)
    assert rows == {"기록": 402, "두 블록": 4}                          # 예전: 표가 둘 이상인 시트는 위치 0
    source = read_source(path, "XLSX", settings)
    started = time.perf_counter()
    result = verify(source, parsed.markdown, [location.model_dump() for location in parsed.locations], parsed.parser, "XLSX", parsed.evidence)
    assert result["spots_total"] == 0 and time.perf_counter() - started < 2
    assert not any(r["code"] == "unlocated" for r in result["reasons"])


def test_compact_matches_the_character_by_character_definition():
    assert set(verify_module._WHITESPACE) == {chr(i) for i in range(0x110000) if chr(i).isspace()}

    def reference(text):
        return "".join(ch for ch in verify_module.fold(text) if not ch.isspace() and ch not in verify_module._IGNORED)
    pool = list(verify_module._WHITESPACE) + list(verify_module._IGNORED) + [chr(k) for k in verify_module._FOLD] + list("가나 ab 0.5 ℃≤±é") + ["é"]
    rng = random.Random(7)
    for _ in range(5000):
        text = "".join(rng.choice(pool) for _ in range(rng.randint(0, 30)))
        assert verify_module.compact(text) == reference(text), repr(text)
