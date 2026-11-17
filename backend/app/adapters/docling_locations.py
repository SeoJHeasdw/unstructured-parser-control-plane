"""Map Docling's emitted Markdown rows to their original page or worksheet."""
import re
from bisect import bisect_right
from app.models import ResultLocation

_TABLE_SEPARATOR = re.compile(r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")


def markdown_locations(document, markdown: str, extension: str) -> list[ResultLocation]:
    from docling_core.transforms.serializer.markdown import MarkdownDocSerializer, MarkdownParams
    from docling_core.types.doc.document import DEFAULT_CONTENT_LAYERS, DOCUMENT_TOKENS_EXPORT_LABELS, TableItem

    serializer = MarkdownDocSerializer(doc=document, params=MarkdownParams(
        labels=DOCUMENT_TOKENS_EXPORT_LABELS, layers=DEFAULT_CONTENT_LAYERS,
    ))
    parts = [part for part in serializer.get_parts() if part.text]
    # Offsets are meaningful only when these serializer parts reproduce the stored text.
    if "\n\n".join(part.text for part in parts) != markdown:
        return []

    locations = []
    line = 1
    for part in parts:
        text_lines = part.text.split("\n")
        end = line + len(text_lines) - 1
        items = part.get_unique_doc_items()
        if extension == "PDF":
            pages = {prov.page_no for item in items for prov in item.prov}
            if len(pages) == 1:
                locations.append(ResultLocation(start_line=line, end_line=end, page=pages.pop()))
            elif pages:
                locations.extend(_pdf_spans(items, part.text, text_lines, line))
        elif len(items) == 1 and isinstance(items[0], TableItem):
            locations.extend(_worksheet_rows(document, items[0], text_lines, line))
        line = end + 2
    return locations


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
