"""원본 인벤토리와 파싱 결과를 대조해 손실을 보고하고, 본문에서 빠진 도형·SVG 글자를 끝에 보충한다.

보충은 원래 위치가 아니라 결과 끝에 '보충 추출' 구획으로 붙인다(원문 위치 정보는 함께 남긴다).
파싱 성공이 품질 보증이 아니라는 원칙에 따라, 고친 것과 고치지 못한 것을 모두 드러낸다.
"""
import re
import unicodedata

from app.models import ResultLocation
from app.textnorm import compatibility_form, special_counts

SUPPLEMENT_MARK = "<!-- docops:supplement -->"
_KIND_LABEL = {"floating_text": "글상자", "svg_text": "SVG 글자"}


def _compact(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\\", "")
    return re.sub(r"\s+", "", text)


def _examples(counter: dict[str, int], limit: int = 6) -> str:
    return ", ".join(f"{ch}×{n}" for ch, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit])


def assess(inventory: dict, markdown: str, prepared: dict | None = None) -> tuple[str, list[ResultLocation], list[str], dict]:
    """(보충한 결과, 보충 줄 위치, 경고, 보고서)"""
    compact_output = _compact(markdown)
    missing_items = []
    seen = set()
    for item in inventory.get("items", []):
        key = _compact(item["text"])
        if not key or key in seen:
            continue
        seen.add(key)
        if key not in compact_output:
            missing_items.append(item)

    final, locations = markdown, []
    if missing_items:
        base = markdown.rstrip("\n")
        lines = [SUPPLEMENT_MARK, "## 보충 추출: 파서 결과에 없던 원본 글자", ""]
        first = (base.count("\n") + 1 if base else 0) + 2  # 빈 줄 하나 뒤에 시작
        for item in missing_items:
            text = " / ".join(part.strip() for part in item["text"].splitlines() if part.strip())
            line_no = first + len(lines)
            lines.append(f"- [{_KIND_LABEL.get(item['kind'], item['kind'])} · {item['location']}] {text}")
            if item.get("sheet") and item.get("row"):
                locations.append(ResultLocation(start_line=line_no, end_line=line_no, sheet=item["sheet"], row=item["row"],
                                                column=item.get("column"), columns=item.get("columns")))
        final = (base + "\n\n" if base else "") + "\n".join(lines)

    # 기대치는 문서 본문·글상자 글자다. SVG 글자는 기대치에 없으므로 보충분 중 글상자만 더해 센다(손실이 가려지지 않게).
    expected = inventory.get("symbols", {})
    found = special_counts(markdown)
    for item in missing_items:
        if item["kind"] == "floating_text":
            for ch, count in special_counts(item["text"]).items():
                found[ch] = found.get(ch, 0) + count
    lost, normalized = {}, {}
    for ch, count in expected.items():
        gap = count - found.get(ch, 0)
        if gap <= 0:
            continue
        # '℃'→'°C', 'µ'→'μ'처럼 기호가 남는 변환만 '바뀜'으로 본다. '²'→'2'처럼 ASCII로 내려앉으면 뜻이 사라진 손실이다.
        compat = compatibility_form(ch)
        if compat and not compat.isascii() and compat in final:
            normalized[ch] = gap
        else:
            lost[ch] = gap

    findings, warnings = [], []

    def finding(code: str, severity: str, count: int, message: str, **detail) -> None:
        findings.append({"code": code, "severity": severity, "count": count, "message": message, **detail})
        if severity == "warning":
            warnings.append(message)

    total = inventory.get("symbol_total", 0)
    if lost:
        finding("symbol_lost", "warning", sum(lost.values()),
                f"특수기호 {sum(lost.values())}건이 결과에서 빠짐(원문 {total}건): {_examples(lost)}", chars=lost)
    if normalized:
        finding("symbol_normalized", "info", sum(normalized.values()),
                f"특수기호 {sum(normalized.values())}건이 호환 문자로 바뀌었을 수 있음: {_examples(normalized)}", chars=normalized)
    prepared = prepared or {}
    if prepared.get("symbol_font_converted"):
        finding("symbol_font_converted", "info", prepared["symbol_font_converted"],
                f"기호 글꼴 문자 {prepared['symbol_font_converted']}건을 유니코드로 바꿔 파싱함")
    unmapped = inventory.get("symbol_font", {}).get("unmapped", 0)
    if unmapped:
        finding("symbol_font_unmapped", "warning", unmapped,
                f"유니코드로 바꿀 수 없는 기호 글꼴 문자 {unmapped}건(Wingdings 등)은 결과에서 빠졌을 수 있음",
                examples=inventory["symbol_font"].get("examples", [])[:10])
    if prepared.get("scripts_converted"):
        finding("script_converted", "info", prepared["scripts_converted"],
                f"위·아래첨자 {prepared['scripts_converted']}건을 유니코드 첨자로 바꿔 파싱함(예: m², 10⁻³)")
    scripts = inventory.get("scripts", {})
    if not prepared and scripts.get("converted"):
        finding("script_flattened", "warning", scripts["converted"],
                f"위·아래첨자 {scripts['converted']}건이 일반 글자로 붙었을 수 있음(예: m² → m2)")
    if scripts.get("flattened"):
        sample = ", ".join(f"{e.get('context', '')}[{e['text']}]" for e in scripts.get("examples", [])[:3])
        finding("script_unconvertible", "warning", scripts["flattened"],
                f"유니코드로 바꿀 수 없는 첨자 {scripts['flattened']}건은 앞 글자에 붙어 나옴: {sample}",
                examples=scripts.get("examples", [])[:10])
    compact_final = _compact(final)
    low = [entry for entry in inventory.get("low_contrast", []) if _compact(entry["text"]) and _compact(entry["text"]) in compact_final]
    if low:
        total_low = inventory.get("low_contrast_total", len(low))
        finding("low_contrast_text", "warning", total_low,
                f"흰색에 가까운 글자 {total_low}건이 본문에 포함됨(숨은 메모·워터마크일 수 있음): {low[0]['text'][:30]}",
                examples=low[:10])
    hidden = inventory.get("hidden", [])
    shown_hidden = [entry for entry in hidden if _compact(entry["text"]) in compact_output]
    if shown_hidden:
        finding("hidden_text_included", "warning", len(shown_hidden), f"숨김 서식 글자 {len(shown_hidden)}건이 본문에 포함됨", examples=shown_hidden[:10])
    elif hidden:
        finding("hidden_text", "info", inventory.get("hidden_total", len(hidden)), f"숨김 서식 글자 {inventory.get('hidden_total', len(hidden))}건은 결과에서 제외됨")
    if inventory.get("hidden_sheets"):
        finding("hidden_sheets", "info", len(inventory["hidden_sheets"]), f"숨긴 시트 {len(inventory['hidden_sheets'])}개가 있음",
                sheets=inventory["hidden_sheets"][:20])
    merged_total = inventory.get("merged_total", 0)
    if merged_total:
        finding("merged_cells", "warning", merged_total,
                f"병합 셀 {merged_total}개: 결과 표에서 같은 값이 칸마다 반복될 수 있음(원 범위는 보고서 참고)",
                examples=inventory.get("merged", [])[:20])
    if missing_items:
        finding("supplemented", "warning", len(missing_items),
                f"파서 결과에 없던 글상자·SVG 글자 {len(missing_items)}건을 끝의 '보충 추출'에 덧붙임(원래 위치 아님)")
    images = inventory.get("images", {})
    raster = images.get("raster", 0) + images.get("raster_in_svg", 0)
    if raster:
        nested = images.get("in_groups", 0) + images.get("in_text_boxes", 0) + images.get("in_objects", 0) + images.get("raster_in_svg", 0)
        finding("images_not_read", "warning", raster,
                f"래스터 그림 {raster}개(겹침·그룹·SVG 속 {nested}개)는 OCR 미적용으로 그림 속 글자를 추출하지 않음", images=images)
    if images.get("metafile"):
        finding("metafiles_not_read", "info", images["metafile"], f"EMF·WMF 그림 {images['metafile']}개의 글자는 추출하지 않음")

    report = {
        "version": 1,
        "symbols": {"expected": total, "found": sum(found.get(ch, 0) for ch in expected), "lost": lost, "normalized": normalized,
                    "top": dict(list(expected.items())[:30])},
        "prepared": prepared or None,
        "findings": findings,
        "supplemented": len(missing_items),
        "notes": inventory.get("notes", []),
    }
    return final, locations, warnings, report
