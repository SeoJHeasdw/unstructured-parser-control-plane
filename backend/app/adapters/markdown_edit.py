"""파서가 낸 Markdown에 줄을 끼워 넣고 원문 위치(locations)의 줄 번호를 함께 민다.

시트 제목·발표자 메모·표 앞 빈 줄처럼 파서 결과를 보강할 때 쓴다. 기존 줄의 글자는 바꾸지 않는다.
"""
import re

from app.models import ResultLocation

_TABLE_SEPARATOR = re.compile(r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")


def insert_lines(markdown: str, locations: list[ResultLocation], inserts: list[tuple[int, list[str], dict | None]]):
    """inserts: (이 줄 번호 앞에 넣음(1부터, 끝이면 줄 수+1), 넣을 줄들, 넣은 줄의 위치 정보 또는 None).

    같은 자리에 여러 개면 준 순서대로 넣는다. (새 Markdown, 밀린 위치 + 넣은 줄 위치)를 돌려준다.
    """
    lines = markdown.split("\n") if markdown else []
    by_line: dict[int, list[tuple[list[str], dict | None]]] = {}
    for before, new_lines, location in inserts:
        by_line.setdefault(min(max(1, before), len(lines) + 1), []).append((new_lines, location))
    out: list[str] = []
    moved: dict[int, int] = {}
    added: list[ResultLocation] = []
    for number in range(1, len(lines) + 2):
        for new_lines, location in by_line.get(number, []):
            start = len(out) + 1
            out.extend(new_lines)
            content = [start + i for i, line in enumerate(new_lines) if line.strip()]
            if location and content:
                added.append(ResultLocation(start_line=content[0], end_line=content[-1], **location))
        if number <= len(lines):
            moved[number] = len(out) + 1
            out.append(lines[number - 1])
    shifted = [loc.model_copy(update={"start_line": moved[loc.start_line], "end_line": moved[loc.end_line]})
               for loc in locations if loc.start_line in moved and loc.end_line in moved]
    return "\n".join(out), sorted(shifted + added, key=lambda loc: (loc.start_line, loc.end_line))


def table_gaps(markdown: str) -> list[tuple[int, list[str], None]]:
    """글·목록 줄 바로 뒤에 빈 줄 없이 붙은 표 앞에 빈 줄을 넣을 자리.

    Docling은 번호 목록 바로 뒤의 표를 빈 줄 없이 잇는다. 일반 Markdown 해석기는 그 표를 목록 항목의 글로 붙여 버린다.
    """
    lines = markdown.split("\n")
    gaps = []
    for index in range(1, len(lines) - 1):
        previous, line = lines[index - 1], lines[index]
        if previous.strip() and not previous.lstrip().startswith("|") and line.lstrip().startswith("|") \
                and _TABLE_SEPARATOR.fullmatch(lines[index + 1]):
            gaps.append((index + 1, [""], None))
    return gaps


def _cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


def _title_row(line: str) -> str | None:
    """모든 칸이 같은 글자인 표 행(전체 너비로 병합된 제목·안내 셀)이면 그 글자. 숫자·기호만 있는 행은 아니다."""
    cells = _cells(line)
    if len(cells) < 2 or len(set(cells)) != 1 or not re.search(r"[^\W\d_]", cells[0]):
        return None
    return cells[0].replace("\\|", "|")


def lift_title_rows(markdown: str, locations: list[ResultLocation]):
    """표 맨 위의 전체 너비 병합 행(제목·안내 문구)을 표 위 문단으로 옮긴다.

    Docling은 병합 셀 값을 칸마다 반복해, 시트 제목처럼 표 전체에 걸친 셀이 26칸에 26번 들어간다(검색 청크도 오염).
    맨 위 행들만 옮기고(표 중간 행은 그대로), 옮긴 줄의 원문 위치는 그대로 따라간다. (새 글, 위치, 옮긴 행 수)
    """
    lines = markdown.split("\n")
    out: list[str] = []
    moved: dict[int, int] = {}
    lifted = 0
    i = 0
    while i < len(lines):
        is_table = lines[i].lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEPARATOR.fullmatch(lines[i + 1])
        if not is_table:
            moved[i + 1] = len(out) + 1
            out.append(lines[i])
            i += 1
            continue
        end = i + 2
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1
        titles = []  # (원래 줄 번호, 글자)
        if (text := _title_row(lines[i])) is not None:
            titles.append((i + 1, text))
            row = i + 2
            while row < end and (text := _title_row(lines[row])) is not None:
                titles.append((row + 1, text))
                row += 1
        else:
            row = None
        if not titles:
            for index in range(i, end):
                moved[index + 1] = len(out) + 1
                out.append(lines[index])
            i = end
            continue
        lifted += len(titles)
        for number, text in titles:
            moved[number] = len(out) + 1
            out.extend([text, ""])
        if row < end:  # 남은 첫 행을 머리글로 삼고 구분선을 그 아래에 둔다
            moved[row + 1] = len(out) + 1
            out.append(lines[row])
            moved[i + 2] = len(out) + 1
            out.append(lines[i + 1])
            for index in range(row + 1, end):
                moved[index + 1] = len(out) + 1
                out.append(lines[index])
        else:  # 제목 행뿐인 표: 문단만 남긴다
            while out and not out[-1].strip():
                out.pop()
            moved[i + 2] = len(out)
        i = end
    if not lifted:
        return markdown, locations, 0
    shifted = [loc.model_copy(update={"start_line": moved[loc.start_line], "end_line": max(moved[loc.start_line], moved[loc.end_line])})
               for loc in locations if loc.start_line in moved and loc.end_line in moved]
    return "\n".join(out), sorted(shifted, key=lambda loc: (loc.start_line, loc.end_line)), lifted
