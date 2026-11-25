"""Map Docling's emitted Markdown rows to their original page or worksheet."""
import re
from bisect import bisect_right
from app.models import ResultLocation

_TABLE_SEPARATOR = re.compile(r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")


def markdown_parts(document, markdown: str):
    """Docling 직렬화 조각별 (시작 줄, 끝 줄, 조각 글, 문서 항목). 조각을 이어 붙인 글이 저장 결과와 다르면 None."""
    from docling_core.transforms.serializer.markdown import MarkdownDocSerializer, MarkdownParams
    from docling_core.types.doc.document import DEFAULT_CONTENT_LAYERS, DOCUMENT_TOKENS_EXPORT_LABELS

    serializer = MarkdownDocSerializer(doc=document, params=MarkdownParams(
        labels=DOCUMENT_TOKENS_EXPORT_LABELS, layers=DEFAULT_CONTENT_LAYERS,
    ))
    parts = [part for part in serializer.get_parts() if part.text]
    # Offsets are meaningful only when these serializer parts reproduce the stored text.
    if "\n\n".join(part.text for part in parts) != markdown:
        return None
    spans = []
    line = 1
    for part in parts:
        end = line + part.text.count("\n")
        spans.append((line, end, part.text, part.get_unique_doc_items()))
        line = end + 2
    return spans


def markdown_locations(document, markdown: str, extension: str, parts=None) -> list[ResultLocation]:
    """PDF·PPTX는 쪽(슬라이드) 번호, XLSX·XLSM 표는 시트·행·열."""
    from docling_core.types.doc.document import TableItem

    parts = parts if parts is not None else markdown_parts(document, markdown)
    if parts is None:
        return []
    locations = []
    for line, end, text, items in parts:
        text_lines = text.split("\n")
        if extension in ("PDF", "PPTX"):
            pages = {prov.page_no for item in items for prov in item.prov}
            if len(pages) == 1:
                locations.append(ResultLocation(start_line=line, end_line=end, page=pages.pop()))
            elif pages and extension == "PDF":
                locations.extend(_pdf_spans(items, text, text_lines, line))
        elif len(items) == 1 and isinstance(items[0], TableItem):
            locations.extend(_worksheet_rows(document, items[0], text_lines, line))
    return locations


def sheet_of(document, item) -> str | None:
    """항목이 속한 워크시트 이름(Docling은 시트마다 'sheet' 묶음을 둔다)."""
    node, guard = item, 0
    while node is not None and getattr(node, "parent", None) is not None and guard < 32:
        node = node.parent.resolve(document)
        guard += 1
        if getattr(node, "label", None) == "sheet" and getattr(node, "name", None):
            return node.name
    return None


def _pdf_spans(items, text: str, lines: list[str], first_line: int) -> list[ResultLocation]:
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    result = []
    for item in items:
        body = getattr(item, "text", "")
        anchor = text.find(body) if body else -1
        if anchor < 0 or text.find(body, anchor + 1) >= 0:
            continue
        for prov in item.prov:
            begin, end = prov.charspan
            if not 0 <= begin < end <= len(body):
                continue
            begin, end = anchor + begin, anchor + end
            for index in range(bisect_right(starts, begin) - 1, bisect_right(starts, end - 1)):
                offset = starts[index]
                lo, hi = max(0, begin - offset), min(len(lines[index]), end - offset)
                if lo < hi:
                    # Browser string offsets are UTF-16 code units.
                    line = first_line + index
                    result.append(ResultLocation(start_line=line, end_line=line, page=prov.page_no,
                                                 start_offset=len(lines[index][:lo].encode("utf-16-le")) // 2,
                                                 end_offset=len(lines[index][:hi].encode("utf-16-le")) // 2))
    return result


def _worksheet_rows(document, table, lines: list[str], start_line: int) -> list[ResultLocation]:
    if len(table.prov) != 1 or table.parent is None:
        return []
    sheet = table.parent.resolve(document)
    if getattr(sheet, "label", None) != "sheet" or not sheet.name:
        return []
    box = table.prov[0].bbox
    if box.coord_origin != "TOPLEFT" or not all(float(v).is_integer() for v in (box.l, box.t, box.r, box.b)):
        return []
    left, top = int(box.l), int(box.t)
    width, height = int(box.r) - left, int(box.b) - top
    sep = next((i for i, line in enumerate(lines) if _TABLE_SEPARATOR.fullmatch(line)), 0)
    row_indexes = [sep - 1, *range(sep + 1, len(lines))]
    # Flattened headers or missing rows make an exact worksheet row ambiguous.
    if sep == 0 or height != len(row_indexes) or width != table.data.num_cols:
        return []
    if any(not lines[i].strip().startswith("|") for i in row_indexes):
        return []
    return [ResultLocation(start_line=start_line + index, end_line=start_line + index,
                           sheet=sheet.name, row=top + offset + 1, column=left + 1, columns=width)
            for offset, index in enumerate(row_indexes)]
