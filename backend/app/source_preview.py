"""Read a bounded window of an original worksheet for parsing review."""
import re
from pathlib import Path
from app.adapters.base import ParserError

_CELL = re.compile(r"[A-Z]{1,3}[1-9][0-9]{0,6}")


def worksheet_preview(path: Path, sheet: str | None, cell: str) -> dict:
    from openpyxl import load_workbook
    from openpyxl.utils.cell import coordinate_to_tuple, get_column_letter
    from openpyxl.worksheet._read_only import ReadOnlyWorksheet

    if not _CELL.fullmatch(cell):
        raise ParserError("셀 주소를 확인해 주세요.")
    row, column = coordinate_to_tuple(cell)
    if row > 1_048_576 or column > 16_384:
        raise ParserError("셀 주소가 워크시트 범위를 벗어납니다.")
    try:
        book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
        try:
            sheets = [entry.title for entry in book.worksheets if isinstance(entry, ReadOnlyWorksheet)]
            if not sheets or (sheet is not None and sheet not in sheets):
                raise ParserError("워크시트를 찾을 수 없습니다.")
            title = sheet or sheets[0]
            first_row, first_col = max(1, row - 3), max(1, column - 2)
            last_row, last_col = min(1_048_576, row + 8), min(16_384, column + 4)
            values = book[title].iter_rows(min_row=first_row, max_row=last_row, min_col=first_col,
                                          max_col=last_col, values_only=True)
            rows = [[str(value)[:500] if value is not None else "" for value in cells] for cells in values]
            rows.extend([[""] * (last_col - first_col + 1) for _ in range(last_row - first_row + 1 - len(rows))])
            return {"kind": "sheet", "sheets": sheets, "sheet": title, "first_row": first_row, "cell": cell,
                    "columns": [get_column_letter(index) for index in range(first_col, last_col + 1)], "rows": rows}
        finally:
            book.close()
    except ParserError:
        raise
    except Exception as exc:
        raise ParserError("원본 워크시트를 읽을 수 없습니다.") from exc
