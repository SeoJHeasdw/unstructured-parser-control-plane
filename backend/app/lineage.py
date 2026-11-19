"""문서 계보: 같은 문서의 여러 판을 묶어 최신을 판단하고, 포함 관계와 문서 간 참조를 연결한다.

입력은 원시 문서 목록이다(실제 파일 목록 또는 예시 데이터).
    {"id", "name", "uploaded_at", "size", "hash"?, "status"?, "structure": 구조 분석 root 노드 | None}

- 버전 묶음: 파일 이름에서 판 표시(Rev·버전·날짜·'최종'·사본 표시)를 떼어 낸 기본 이름과 형식 계열,
  이름 맨 앞의 문서번호, 같은 내용(해시)으로 묶는다. 구조 분석 전 문서도 이름으로 참여한다.
  압축 항목·첨부·내장 개체는 내용이나 이름이 같은 문서군이 있을 때만 그 문서군의 판으로 붙는다.
- 최신 판단: Rev → 버전 → 파일명 날짜 → '최종' → 업로드 시각 순으로 정렬하고,
  표시끼리 어긋나거나 순서를 정할 표시가 없으면 '판단 보류'로 둔다.
- 참조 연결: 구조 분석이 찾은 링크·문서번호 후보를 다른 문서(압축·첨부 안의 파일 포함)와 맞춘다.
  상태는 linked(연결됨) · outdated(구버전 참조) · missing(대상 미발견) · ambiguous(후보 여러 개) · external(외부 주소).

입력을 바꾸지 않고 표준 라이브러리만 쓴다. 파일을 열거나 분석·파싱을 실행하지 않는다.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from app.structure import DOCNUM, DOCNUM_STOP
from app.textnorm import name_key

# 이름에 순서 표시가 없을 때, 업로드 시각 차이가 이보다 작으면 같은 반입으로 보고 순서를 정하지 않는다.
SAME_BATCH_SECONDS = 3600
DIMS = ("rev", "version", "date")
SIGNAL_LABEL = {"rev": "Rev 표기", "version": "버전 번호", "date": "파일명 날짜", "final": "'최종' 표기", "copy": "사본 표시", "docno": "문서번호"}
REASON_LABEL = {"rev": "Rev 표기", "version": "버전 번호", "date": "파일명 날짜", "final": "'최종' 표기", "upload": "업로드 시각", "format": "형식만 다름", "content": "같은 내용"}
EXT_FAMILY = {
    "DOC": "word", "DOCX": "word", "DOCM": "word", "DOT": "word", "DOTX": "word", "RTF": "word",
    "XLS": "excel", "XLSX": "excel", "XLSM": "excel", "XLSB": "excel", "XLT": "excel", "XLTX": "excel",
    "PPT": "powerpoint", "PPTX": "powerpoint", "PPTM": "powerpoint", "PPS": "powerpoint", "PPSX": "powerpoint",
    "HWP": "hwp", "HWPX": "hwp", "HTM": "html", "HTML": "html", "MHT": "mht", "MHTML": "mht", "JPG": "jpeg", "JPEG": "jpeg", "TIF": "tiff", "TIFF": "tiff",
}
WEB_EXT = {"HTM", "HTML", "ASP", "ASPX", "PHP", "JSP", "DO", "CGI", "ACTION", "JSF", "NSF"}
STATES = ("linked", "outdated", "missing", "ambiguous", "external")

# ---------------------------------------------------------------- 이름 규칙

_B = r"(?<![A-Za-z0-9])"
_E = r"(?![A-Za-z0-9])"
FINAL_KO = re.compile(r"(?:(진짜|찐)[ _-]?)?(최+)종((?:[ _-]*(?:최+종|수정본|수정))*)")
FINAL_EN = re.compile(_B + r"final((?:[ _-]*final)*)" + _E, re.I)
COPY = (
    re.compile(r"[ _]*-?[ _]*복사본(?:[ _]*\(?(\d{1,3})\)?)?"),
    re.compile(r"[ _]+사본(?:[ _]*\(?(\d{1,3})\)?)?\s*$"),
    re.compile(_B + r"copy(?:[ _-]*of)?(?:[ _-]*\(?(\d{1,3})\)?)?" + _E, re.I),
    re.compile(r"[ _]*\((\d{1,3})\)"),
)
DATES = (
    (re.compile(r"(?<!\d)(20\d{2})\s?년\s?(\d{1,2})\s?월\s?(\d{1,2})\s?일"), lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    (re.compile(r"(?<!\d)(20\d{2})([-._])(\d{1,2})\2(\d{1,2})(?!\d)"), lambda m: (int(m.group(1)), int(m.group(3)), int(m.group(4)))),
    (re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)"), lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    (re.compile(r"(?<![A-Za-z0-9])(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)"), lambda m: (2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    (re.compile(r"(?<!\d)(20\d{2})[-.](0[1-9]|1[0-2])(?![\d])"), lambda m: (int(m.group(1)), int(m.group(2)), 0)),
)
REVS = (
    re.compile(_B + r"rev(?:ision)?[ ._-]?(\d{1,3})(?!\d)", re.I),
    re.compile(r"(?<!\d)(\d{1,3})[ _-]?차[ _-]?개정"),
    re.compile(r"개정[ _-]?(?:판[ _-]?)?(\d{1,3})(?:[ _-]?(?:판|차))?(?!\d)"),
    re.compile(_B + r"r(\d{1,3})" + _E, re.I),
)
VERSIONS = (
    re.compile(_B + r"v(?:er(?:sion)?)?[ ._-]?(\d{1,3}(?:\.\d{1,3}){0,2})(?![\d])", re.I),
    re.compile(r"버전[ _-]?(\d{1,3}(?:\.\d{1,3}){0,2})(?![\d])"),
    re.compile(r"(?<![\d.])(\d{1,2})[ _]?차(?![가-힣])"),
)
_DOCNUM_SPLIT = re.compile(r"^(.*?)(?:\s?(?:Rev|REV|rev)\.?\s?(\d{1,3}))?$")
_PLACEHOLDER = re.compile("\ue000(.)\ue001")


def split_docnum(text: str) -> tuple[str, int | None]:
    """'SOP-QC-0040 Rev.5' → ('SOP-QC-0040', 5)."""
    match = _DOCNUM_SPLIT.match(text.strip())
    number = (match.group(1) if match else text).strip()
    return number, int(match.group(2)) if match and match.group(2) else None


@dataclass
class NameInfo:
    name: str
    stem: str
    ext: str
    ext_family: str
    base_key: str = ""
    title: str = ""
    docno: str | None = None
    rev: int | None = None
    version: tuple | None = None
    date: int | None = None
    final: int = 0
    copy: bool = False
    signals: list = field(default_factory=list)

    @property
    def has_order(self) -> bool:
        return any(getattr(self, dim) is not None for dim in DIMS) or self.final > 0

    def order(self) -> tuple:
        return (self.rev if self.rev is not None else -1, self.version or (), self.date or 0, self.final)

    def label(self) -> str:
        parts = []
        if self.rev is not None:
            parts.append(f"Rev {self.rev}")
        if self.version is not None:
            parts.append("v" + ".".join(map(str, self.version)))
        if self.date is not None:
            parts.append(_date_text(self.date))
        if self.final:
            parts.append(next((s["text"] for s in self.signals if s["code"] == "final"), "최종"))
        return " · ".join(parts) or "판 표시 없음"


def _date_text(value: int) -> str:
    y, m, d = value // 10000, value // 100 % 100, value % 100
    return f"{y}-{m:02d}-{d:02d}" if d else f"{y}-{m:02d}"


def split_name(name: str) -> tuple[str, str, str]:
    name = unicodedata.normalize("NFC", str(name or "")).strip()
    match = re.match(r"^(.*[^.\s])\.([A-Za-z0-9]{1,10})$", name)
    if match and re.search(r"[A-Za-z]", match.group(2)):
        return name, match.group(1), match.group(2).upper()
    return name, name, ""


def parse_name(name: str) -> NameInfo:
    """파일 이름에서 판 표시를 읽고, 그것을 뗀 기본 이름(비교 키·표시 제목)을 만든다."""
    full, stem, ext = split_name(name)
    info = NameInfo(name=full, stem=stem, ext=ext, ext_family=EXT_FAMILY.get(ext, ext.lower()))
    kept: list[str] = []

    def signal(code: str, text: str) -> None:
        text = text.strip(" _-.()")
        if text and not any(s["code"] == code and s["text"] == text for s in info.signals):
            info.signals.append({"code": code, "label": SIGNAL_LABEL[code], "text": text})

    def protect(text: str) -> str:
        kept.append(text)
        return f" \ue000{chr(0xE100 + len(kept) - 1)}\ue001 "

    def docno(match: re.Match) -> str:
        text = match.group(0)
        if text.split("-")[0] in DOCNUM_STOP:
            return text
        number, rev = split_docnum(text)
        if rev is not None:
            info.rev = max(info.rev or 0, rev)
            signal("rev", text[len(number):])
        if info.docno is None and not match.string[: match.start()].strip(" _-[(【「"):
            info.docno = number  # 이름 맨 앞의 문서번호만 문서 식별자로 쓴다.
            signal("docno", number)
        return protect(number)

    work = DOCNUM.sub(docno, stem)

    def final_ko(match: re.Match) -> str:
        level = (1 if match.group(1) else 0) + len(match.group(2)) + sum(len(x) for x in re.findall(r"(최+)종", match.group(3))) + match.group(3).count("수정")
        info.final = max(info.final, level)
        signal("final", match.group(0))
        return " "

    def final_en(match: re.Match) -> str:
        info.final = max(info.final, 1 + match.group(1).lower().count("final"))
        signal("final", match.group(0))
        return " "

    work = FINAL_EN.sub(final_en, FINAL_KO.sub(final_ko, work))

    def copy(match: re.Match) -> str:
        info.copy = True
        signal("copy", match.group(0))
        return " "

    for pattern in COPY:
        work = pattern.sub(copy, work)

    for pattern, parts in DATES:
        def date(match: re.Match, parts=parts) -> str:
            y, m, d = parts(match)
            try:
                datetime(y, m, d or 1)
            except ValueError:
                return match.group(0)
            value = y * 10000 + m * 100 + d
            info.date = max(info.date or 0, value)
            signal("date", match.group(0))
            return " "
        work = pattern.sub(date, work)

    def rev(match: re.Match) -> str:
        info.rev = max(info.rev or 0, int(match.group(1)))
        signal("rev", match.group(0))
        return " "

    for pattern in REVS:
        work = pattern.sub(rev, work)

    def version(match: re.Match) -> str:
        parts = [int(x) for x in match.group(1).split(".")]
        while len(parts) > 1 and parts[-1] == 0:
            parts.pop()
        value = tuple(parts)
        info.version = max(info.version or (), value)
        signal("version", match.group(0))
        return " "

    for pattern in VERSIONS:
        work = pattern.sub(version, work)

    work = _PLACEHOLDER.sub(lambda m: kept[ord(m.group(1)) - 0xE100], work)
    title = re.sub(r"\(\s*\)|\[\s*\]|【\s*】", " ", work)
    title = re.sub(r"[\s_]+", " ", title)
    title = re.sub(r"\s+[-.]+(?=\s|$)|(?:^|\s)[-.]+\s+", " ", title).strip(" -_.,")
    # 기호 보존 키: '-70℃'와 '70℃'는 다른 문서, '−70°C'와 '-70℃'·'m²'와 'm2'는 같은 이름으로 본다.
    key = name_key(title)
    if not key:  # 이름 전체가 판 표시뿐이면 원래 이름으로 비교한다(서로 다른 문서가 섞이지 않게).
        title = stem
        key = name_key(stem) or stem.casefold() or "-"
    info.title, info.base_key = title, key
    return info


# ---------------------------------------------------------------- 공통 도우미

def _ts(value) -> float:
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _norm(name: str) -> str:
    return unicodedata.normalize("NFC", str(name or "")).strip().casefold()


def _fid(key: str) -> str:
    return "f-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def _basename(target: str) -> str:
    text = unquote(target.strip())
    bracket = re.search(r"\[([^\[\]]+\.[A-Za-z0-9]{2,5})\]", text)  # 'C:\경로\[통합문서.xlsx]시트'
    if bracket:
        return bracket.group(1).strip()
    text = re.sub(r"^[a-z][a-z0-9+.-]*:(?://)?", "", text, flags=re.I) if re.match(r"^[a-z][a-z0-9+.-]{2,}:", text, re.I) else text
    text = text.split("?", 1)[0].split("#", 1)[0]
    parts = [part for part in re.split(r"[\\/]+", text) if part.strip()]
    return parts[-1].strip() if parts else ""


class _Families:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


# ---------------------------------------------------------------- 계산

def build_lineage(documents: list, *, source: str = "live", as_of: str | None = None) -> dict:
    instances: dict[str, dict] = {}
    infos: dict[str, NameInfo] = {}
    links: dict[str, list] = {}
    tops: list[str] = []
    counts = {"total": 0, "analysed": 0, "not_analysed": 0, "structure_errors": 0}

    def add(node: dict | None, iid: str, doc: dict, parent: str | None, depth: int, root: str) -> None:
        node = node if isinstance(node, dict) else None
        name = str((node or {}).get("name") or doc.get("name") or "(이름 없음)") if depth else str(doc.get("name") or (node or {}).get("name") or "(이름 없음)")
        info = parse_name(name)
        children = [c for c in (node or {}).get("children") or [] if isinstance(c, dict)]
        instances[iid] = {
            "id": iid, "doc_id": str(doc["id"]), "root": root, "parent": parent, "depth": depth, "children": [f"{iid}/{i}" for i in range(len(children))],
            "name": info.name, "ext": info.ext, "kind": str((node or {}).get("kind") or "file") if depth else "file", "location": str((node or {}).get("location") or ""),
            "size": int((node or {}).get("size") or (doc.get("size") if depth == 0 else 0) or 0), "hash": (node or {}).get("hash") or (doc.get("hash") if depth == 0 else None),
            "detected": (node or {}).get("detected"), "flags": [str(f) for f in (node or {}).get("flags") or []],
            "uploaded_at": doc.get("uploaded_at"), "status": doc.get("status") if depth == 0 else None,
            "analysed": node is not None, "inspected_at": doc.get("inspected_at") if depth == 0 else None, "structure_state": doc.get("structure_state") if depth == 0 else None,
            "family": None, "entry": None, "same_as": None, "signals": info.signals, "version_label": info.label(), "links": 0,
        }
        infos[iid] = info
        links[iid] = [l for l in (node or {}).get("links") or [] if isinstance(l, dict) and l.get("target")]
        instances[iid]["links"] = len(links[iid])
        for index, child in enumerate(children):
            add(child, f"{iid}/{index}", doc, iid, depth + 1, root)

    seen_ids = set()
    for doc in documents or []:
        if not isinstance(doc, dict) or not doc.get("id") or not doc.get("name") or str(doc["id"]) in seen_ids:
            continue
        seen_ids.add(str(doc["id"]))
        iid = f"d:{doc['id']}"
        root = doc.get("structure") if isinstance(doc.get("structure"), dict) else None
        counts["total"] += 1
        counts["analysed" if root else "not_analysed"] += 1
        counts["structure_errors"] += 1 if doc.get("structure_state") == "error" else 0
        add(root, iid, doc, None, 0, iid)
        tops.append(iid)

    # 1) 문서군: 이름 규칙 · 이름 앞 문서번호 · 같은 내용으로 묶는다.
    groups = _Families()
    key_owner: dict[str, str] = {}

    def keys_of(iid: str) -> list[str]:
        info, inst = infos[iid], instances[iid]
        keys = [f"name:{info.base_key}|{info.ext_family}"]
        if info.docno:
            keys.append(f"docno:{info.docno}")
        if inst["hash"] and inst["size"]:
            keys.append(f"hash:{inst['hash']}")
        return keys

    for iid in tops:
        groups.find(iid)
        for key in keys_of(iid):
            if key in key_owner:
                groups.union(iid, key_owner[key])
            else:
                key_owner[key] = iid
    members: dict[str, list[str]] = {}
    for iid in tops:
        members.setdefault(groups.find(iid), []).append(iid)
    families: dict[str, dict] = {}
    key_family: dict[str, str] = {}
    for group in members.values():
        keys = sorted({key for iid in group for key in keys_of(iid)})
        ident = next((k for k in keys if k.startswith("docno:")), None) or next(k for k in keys if k.startswith("name:"))
        fid = _fid(ident)
        families[fid] = {"id": fid, "members": list(group)}
        for key in keys:
            key_family[key] = fid
        for iid in group:
            instances[iid]["family"] = fid

    # 2) 압축 항목·첨부·내장 개체는 같은 내용이나 같은 이름 규칙의 문서군이 있을 때 그 문서군의 판으로 붙인다.
    for iid, inst in instances.items():
        if inst["depth"] == 0:
            continue
        info = infos[iid]
        candidates = ([f"hash:{inst['hash']}"] if inst["hash"] and inst["size"] else []) + ([f"docno:{info.docno}"] if info.docno else []) + [f"name:{info.base_key}|{info.ext_family}"]
        fid = next((key_family[k] for k in candidates if k in key_family), None)
        if fid:
            inst["family"] = fid
            families[fid]["members"].append(iid)

    # 3) 판(entry): 같은 내용(해시)은 하나의 판으로 모으고 정렬한다.
    entries: dict[str, dict] = {}
    entry_info: dict[str, NameInfo] = {}
    for fid, family in families.items():
        # 문서군의 대표 이름: 최상위 파일에서 가장 많이 쓰인 기본 이름(같으면 최근 업로드).
        tally: dict[str, list] = {}
        for iid in family["members"]:
            if instances[iid]["depth"] == 0:
                item = tally.setdefault(infos[iid].base_key, [0, 0.0])
                item[0] += 1
                item[1] = max(item[1], _ts(instances[iid]["uploaded_at"]))
        family["base"] = max(tally, key=lambda k: (tally[k][0], tally[k][1], k))
        buckets: dict[str, list[str]] = {}
        for iid in family["members"]:
            inst = instances[iid]
            buckets.setdefault(f"h:{inst['hash']}" if inst["hash"] and inst["size"] else f"i:{iid}", []).append(iid)
        made = []
        for bucket, ids in buckets.items():
            ids.sort(key=lambda i: (instances[i]["depth"] > 0, infos[i].base_key != family["base"], infos[i].copy, _ts(instances[i]["uploaded_at"]), i))
            best = max(ids, key=lambda i: (infos[i].order(), instances[i]["depth"] == 0, not infos[i].copy))
            eid = f"{fid}/{bucket}"
            tops_in = [i for i in ids if instances[i]["depth"] == 0]
            uploaded = min((instances[i]["uploaded_at"] for i in tops_in), key=_ts, default=instances[ids[0]]["uploaded_at"])
            labels = sorted({infos[i].label() for i in ids if infos[i].has_order})
            notes = [f"같은 내용인데 이름의 판 표시가 다름: {', '.join(labels)}"] if len(labels) > 1 else []
            entry = {"id": eid, "family": fid, "instances": ids, "primary": ids[0], "label": infos[best].label(), "signals": infos[best].signals,
                     "ext": instances[ids[0]]["ext"], "uploaded_at": uploaded, "contained_only": not tops_in, "duplicates": len(ids) - 1,
                     "is_latest": False, "co_latest": False, "candidate": False, "order": 0, "notes": notes}
            entries[eid] = entry
            entry_info[eid] = infos[best]
            for i in ids:
                instances[i]["entry"] = eid
                if i != ids[0] and instances[ids[0]]["depth"] == 0:
                    instances[i]["same_as"] = ids[0]
            made.append(eid)
        made.sort(key=lambda e: (entry_info[e].order(), _ts(entries[e]["uploaded_at"]), e))
        for index, eid in enumerate(made):
            entries[eid]["order"] = index
        family["entries"] = made
        family["latest"] = _decide_latest(made, entries, entry_info)

    # 4) 문서군 정보
    by_base: dict[str, set] = {}
    for fid, family in families.items():
        top = entries[family["entries"][-1]]
        info = infos[top["primary"]]
        tops_in = [i for i in family["members"] if instances[i]["depth"] == 0]
        named = [e for e in reversed(family["entries"]) for i in entries[e]["instances"] if infos[i].base_key == family["base"] and instances[i]["depth"] == 0]
        family["title"] = infos[next(i for i in entries[named[0]]["instances"] if infos[i].base_key == family["base"])].title
        family["docno"] = next((infos[i].docno for i in tops_in if infos[i].docno), None)
        family["ext_family"] = info.ext_family
        family["formats"] = sorted({instances[i]["ext"] for i in family["members"] if instances[i]["ext"]})
        family["files"] = len(tops_in)
        analysed = sum(1 for i in tops_in if instances[i]["analysed"])
        family["analysed"] = "all" if analysed == len(tops_in) else "none" if not analysed else "partial"
        family["notes"] = []
        if top["contained_only"]:
            holder = instances[top["primary"]]
            family["notes"].append(f"최신 판이 다른 파일 안에만 있습니다: {_path_text(holder, instances)}")
        if not family["docno"]:
            by_base.setdefault(family["base"], set()).add(fid)
    for fid, family in families.items():
        family["related"] = sorted(by_base.get(family["base"], set()) - {fid}) if not family["docno"] else []

    # 5) 참조 연결
    by_name: dict[str, list[str]] = {}
    for iid, inst in instances.items():
        by_name.setdefault(_norm(inst["name"]), []).append(iid)
    docno_family = {key[6:]: fid for key, fid in key_family.items() if key.startswith("docno:")}
    docno_contained: dict[str, list[str]] = {}  # 문서군이 없는 포함 파일 중 이름 앞에 문서번호가 있는 것
    for iid, inst in instances.items():
        if inst["depth"] and not inst["family"] and infos[iid].docno:
            docno_contained.setdefault(infos[iid].docno, []).append(iid)
    namekey_family = {key[5:]: fid for key, fid in key_family.items() if key.startswith("name:")}
    base_families: dict[str, set] = {}
    for key, fid in namekey_family.items():
        base_families.setdefault(key.rsplit("|", 1)[0], set()).add(fid)

    def nearest_family(iid: str | None) -> str | None:
        while iid:
            if instances[iid]["family"]:
                return instances[iid]["family"]
            iid = instances[iid]["parent"]
        return None

    copies = set()  # 같은 내용의 사본(대표가 아닌 파일)과 그 하위는 참조를 다시 세지 않는다.
    for iid in sorted(instances, key=lambda i: instances[i]["depth"]):
        inst = instances[iid]
        if (inst["parent"] in copies) or (inst["entry"] and entries[inst["entry"]]["primary"] != iid):
            copies.add(iid)

    references: list[dict] = []
    self_mentions: dict[str, int] = {}
    for iid in instances:
        if iid in copies:
            continue
        own = nearest_family(iid)
        for link in links[iid]:
            resolved = _resolve(link, iid, instances, infos, families, entries, entry_info, by_name, docno_family, docno_contained, namekey_family, base_families)
            if resolved.get("family") and resolved["family"] == own and resolved["state"] != "ambiguous":
                self_mentions[own] = self_mentions.get(own, 0) + 1
                continue
            references.append({
                "id": f"r{len(references) + 1}", "source": iid, "source_root": instances[iid]["root"], "source_family": own,
                "kind": str(link.get("kind") or ""), "target": str(link.get("target") or ""), "location": str(link.get("location") or ""),
                "evidence": str(link.get("evidence") or ""), "state": resolved["state"], "match": resolved.get("match"),
                "family": resolved.get("family"), "entry": resolved.get("entry"), "instance": resolved.get("instance"),
                "candidates": resolved.get("candidates", []), "wanted": resolved.get("wanted"), "note": resolved.get("note", ""),
            })

    # 6) 집계
    for fid, family in families.items():
        family["counts"] = {"files": family["files"], "versions": len(family["entries"]), "duplicates": sum(entries[e]["duplicates"] for e in family["entries"]),
                            "contained": _descendants(entries[family["entries"][-1]]["primary"], instances), "self_mentions": self_mentions.get(fid, 0),
                            "out": {state: 0 for state in STATES}, "out_all": {state: 0 for state in STATES}, "in": {state: 0 for state in STATES}}
    for ref in references:
        holding = _families_holding(ref["source"], instances, entries)
        for fid, from_latest in holding.items():
            families[fid]["counts"]["out_all"][ref["state"]] += 1
            if from_latest:  # 문서군 표시는 최신 판에서 나간 참조만 센다.
                families[fid]["counts"]["out"][ref["state"]] += 1
        targets = {ref["family"]} if ref["family"] else set()
        targets |= {c["family"] for c in ref["candidates"] if c.get("family")}
        for fid in targets - set(holding):
            families[fid]["counts"]["in"][ref["state"]] += 1
    for family in families.values():
        c = family["counts"]
        flags = []
        if family["latest"]["status"] == "hold":
            flags.append("hold")
        if c["out"]["outdated"] or c["in"]["outdated"]:
            flags.append("outdated")
        if c["out"]["missing"]:
            flags.append("missing")
        if c["out"]["ambiguous"] or c["in"]["ambiguous"]:
            flags.append("ambiguous")
        if c["duplicates"]:
            flags.append("duplicate")
        if family["analysed"] != "all":
            flags.append("not-analysed")
        family["flags"] = flags
        del family["members"], family["base"]

    ordered = sorted(families.values(), key=lambda f: (f["latest"]["status"] != "hold", -max((_ts(entries[e]["uploaded_at"]) for e in f["entries"]), default=0), f["title"]))
    states = {state: sum(1 for r in references if r["state"] == state) for state in STATES}
    summary = {
        "families": len(families), "versioned": sum(1 for f in families.values() if len(f["entries"]) > 1),
        "hold": sum(1 for f in families.values() if f["latest"]["status"] == "hold"),
        "contained": sum(1 for i in instances.values() if i["depth"] > 0), "duplicates": sum(f["counts"]["duplicates"] for f in families.values()),
        "references": states,
    }
    return {"source": source, "as_of": as_of, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "documents": counts,
            "summary": summary, "families": ordered, "entries": entries, "instances": instances, "references": references}


def _descendants(iid: str, instances: dict) -> int:
    return sum(1 + _descendants(child, instances) for child in instances[iid]["children"])


def _families_holding(iid: str, instances: dict, entries: dict) -> dict:
    """링크가 있는 파일과 그 상위 파일들이 속한 문서군 → 그 파일이 최신 판인지(포함한 쪽도 출발 문서로 본다)."""
    found: dict[str, bool] = {}
    while iid:
        inst = instances[iid]
        if inst["family"] and inst["family"] not in found:
            entry = entries.get(inst["entry"]) if inst["entry"] else None
            found[inst["family"]] = bool(entry and (entry["is_latest"] or entry["co_latest"]))
        iid = inst["parent"]
    return found


def _path_text(inst: dict, instances: dict) -> str:
    names = []
    current = inst["parent"]
    while current:
        names.append(instances[current]["name"])
        current = instances[current]["parent"]
    return " › ".join(reversed(names)) or inst["name"]


# ---------------------------------------------------------------- 최신 판단

def _direction(a: NameInfo, b: NameInfo, dim: str):
    va, vb = getattr(a, dim), getattr(b, dim)
    if va is not None and vb is not None:
        return (va > vb) - (va < vb)
    if va is not None:
        return "+"
    if vb is not None:
        return "-"
    return None


def _decide_latest(order: list, entries: dict, info: dict) -> dict:
    top_id = order[-1]
    top = entries[top_id]
    top["is_latest"] = True
    if len(order) == 1:
        reasons = [{"code": "content", "label": REASON_LABEL["content"], "detail": f"같은 내용 파일 {top['duplicates'] + 1}개"}] if top["duplicates"] else []
        return {"status": "single", "entry": top_id, "reasons": reasons, "conflicts": [], "candidates": [top_id]}
    t = info[top_id]
    reasons: dict[str, dict] = {}
    conflicts: list[dict] = []
    candidates = {top_id}

    def reason(code: str, other: str, detail: str | None = None) -> None:
        reasons.setdefault(code, {"code": code, "label": REASON_LABEL[code], "detail": detail or f"{entries[other]['label']} → {top['label']}"})

    def conflict(code: str, other: str, message: str) -> None:
        conflicts.append({"code": code, "message": message, "entries": [other, top_id]})
        candidates.add(other)
        entries[other]["candidate"] = True

    for other_id in reversed(order[:-1]):
        other, o = entries[other_id], info[other_id]
        dirs = {dim: _direction(t, o, dim) for dim in DIMS}
        wins = [d for d in DIMS if dirs[d] == 1]
        losses = [d for d in DIMS if dirs[d] == -1]
        has = [d for d in DIMS if dirs[d] == "+"]
        lacks = [d for d in DIMS if dirs[d] == "-"]
        decided = None
        if losses:
            by = wins[0] if wins else has[0] if has else "final"
            conflict("order", other_id, f"{REASON_LABEL[by]}로는 '{top['label']}', {REASON_LABEL[losses[0]]}로는 '{other['label']}'이(가) 나중입니다.")
        elif wins:
            decided = wins[0]
        elif has and lacks:
            conflict("mixed", other_id, f"'{top['label']}'와 '{other['label']}'은(는) 판 표시 방식({REASON_LABEL[has[0]]}, {REASON_LABEL[lacks[0]]})이 달라 비교할 수 없습니다.")
        elif has:
            decided = has[0]
        elif lacks:  # 정렬상 일어나지 않지만 방어적으로 보류한다.
            conflict("mixed", other_id, f"'{other['label']}'이(가) 더 나중일 수 있습니다.")
        else:
            gap = _ts(top["uploaded_at"]) - _ts(other["uploaded_at"])
            if t.final > o.final:
                if gap <= -SAME_BATCH_SECONDS:
                    conflict("final-upload", other_id, f"'최종' 표기 파일보다 같은 판의 '{entries[other_id]['label']}' 파일이 나중에 들어왔습니다.")
                else:
                    decided = "final"
            elif top["ext"] != other["ext"]:
                other["co_latest"] = True
                reasons.setdefault("format", {"code": "format", "label": REASON_LABEL["format"], "detail": f"{other['ext']} · {top['ext']} 같은 판"})
            elif gap >= SAME_BATCH_SECONDS:
                decided = "upload"
            else:
                conflict("no-signal", other_id, "이름에 순서를 정할 표시가 없고 같은 시기에 들어온 파일입니다.")
        if decided and o.final > t.final and not other["co_latest"]:
            conflict("final-lower", other_id, f"'최종' 표기가 있는 '{other['label']}'보다 '{top['label']}'이(가) {REASON_LABEL[decided]}상 나중입니다.")
        elif decided:
            if decided == "upload":
                reason("upload", other_id, "이름에 순서 표시가 없어 업로드 시각으로 판단")
            else:
                reason(decided, other_id)
    status = "hold" if conflicts else "confirmed"
    if conflicts:
        top["candidate"] = True
    ordered_reasons = [reasons[code] for code in ("rev", "version", "date", "final", "upload", "format") if code in reasons]
    return {"status": status, "entry": top_id, "reasons": ordered_reasons, "conflicts": conflicts, "candidates": [e for e in order if e in candidates]}


# ---------------------------------------------------------------- 참조 연결

def _resolve(link, owner, instances, infos, families, entries, entry_info, by_name, docno_family, docno_contained, namekey_family, base_families) -> dict:
    kind = str(link.get("kind") or "")
    target = str(link.get("target") or "").strip()

    def family_state(fid: str, eid: str | None) -> tuple[str, str]:
        latest = families[fid]["latest"]
        top = entries[latest["entry"]]
        if eid is None:
            return "linked", ""
        entry = entries[eid]
        if entry["is_latest"] or entry["co_latest"]:
            return "linked", "대상 문서군의 최신 판단이 보류 중입니다." if latest["status"] == "hold" else ""
        if latest["status"] == "hold" and eid in latest["candidates"]:
            return "linked", "대상 문서군의 최신 판단이 보류 중이며, 이 판은 최신 후보입니다."
        return "outdated", f"최신은 '{top['label']}'입니다."

    def to_instance(iid: str, match: str) -> dict:
        inst = instances[iid]
        if inst["family"] and inst["entry"]:
            state, note = family_state(inst["family"], inst["entry"])
            return {"state": state, "match": match, "family": inst["family"], "entry": inst["entry"], "instance": iid, "note": note}
        note = "다른 파일 안에 포함된 파일입니다." if inst["depth"] else ""
        return {"state": "linked", "match": match, "family": None, "entry": None, "instance": iid, "note": note}

    def to_version(fid: str, want: NameInfo, match: str, wanted: str | None) -> dict:
        order = families[fid]["entries"]
        latest = families[fid]["latest"]
        top = entries[latest["entry"]]
        dims = [d for d in DIMS if getattr(want, d) is not None]
        if not dims and not want.final:
            note = "판을 지정하지 않아 최신 판으로 연결했습니다." if len(order) > 1 else ""
            state, extra = family_state(fid, latest["entry"])
            return {"state": state, "match": match, "family": fid, "entry": latest["entry"], "instance": top["primary"], "wanted": wanted, "note": " ".join(x for x in (note, extra) if x)}
        same = [e for e in order if all(getattr(entry_info[e], d) == getattr(want, d) for d in dims)]
        if want.final and len(same) > 1:
            same = [e for e in same if entry_info[e].final == want.final] or same
        if same:
            eid = same[-1]
            state, note = family_state(fid, eid)
            return {"state": state, "match": match + "-version", "family": fid, "entry": eid, "instance": entries[eid]["primary"], "wanted": wanted, "note": note}
        comparable = [d for d in dims if getattr(entry_info[latest["entry"]], d) is not None]
        if comparable:
            d = comparable[0]
            if getattr(want, d) < getattr(entry_info[latest["entry"]], d):
                return {"state": "outdated", "match": match, "family": fid, "entry": None, "instance": None, "wanted": wanted,
                        "note": f"참조한 판의 파일은 없습니다. 최신은 '{top['label']}'입니다."}
            return {"state": "missing", "match": match, "family": fid, "entry": None, "instance": None, "wanted": wanted,
                    "note": f"문서군은 있으나 참조한 판의 파일이 없습니다. 보유한 최신은 '{top['label']}'입니다."}
        state, extra = family_state(fid, latest["entry"])
        return {"state": state, "match": match, "family": fid, "entry": latest["entry"], "instance": top["primary"], "wanted": wanted,
                "note": " ".join(x for x in ("판 표시 방식이 달라 문서군의 최신 판으로 연결했습니다.", extra) if x)}

    def ambiguous(cands: list[dict], match: str, note: str) -> dict:
        return {"state": "ambiguous", "match": match, "family": None, "entry": None, "instance": None, "candidates": cands, "note": note}

    missing = {"state": "missing", "match": None, "family": None, "entry": None, "instance": None}

    if kind == "doc-number":
        number, rev = split_docnum(target)
        want = NameInfo(name=target, stem=target, ext="", ext_family="", rev=rev)
        wanted = f"Rev {rev}" if rev is not None else None
        fid = docno_family.get(number)
        if fid:
            return to_version(fid, want, "docno", wanted)
        prefixed = sorted({f for no, f in docno_family.items() if no.startswith(number + "-")})
        if len(prefixed) == 1:
            return to_version(prefixed[0], want, "docno-prefix", wanted)
        inside = [i for i in docno_contained.get(number, []) if i != owner and (rev is None or infos[i].rev == rev)]
        if inside and not prefixed:
            distinct = {instances[i]["hash"] or i: i for i in inside}
            if len(distinct) == 1:
                return {**to_instance(next(iter(distinct.values())), "docno"), "wanted": wanted}
            return ambiguous([{"family": None, "entry": None, "instance": i} for i in distinct.values()], "docno", "같은 문서번호의 포함 파일이 여러 개입니다.")
        if prefixed:
            return ambiguous([{"family": f, "entry": families[f]["latest"]["entry"], "instance": None} for f in prefixed], "docno-prefix", "문서번호 일부가 일치하는 문서군이 여러 개입니다.")
        return {**missing, "match": "docno", "wanted": wanted, "note": "같은 문서번호의 문서가 없습니다."}

    base = _basename(target)
    web = re.match(r"^https?://", target, re.I)
    if web:
        path = unquote(urlsplit(target).path or "")
        base = path.rstrip("/").rsplit("/", 1)[-1] if path.strip("/") else ""
    info = parse_name(base) if base else None
    if not base or info is None or (web and (not info.ext or info.ext in WEB_EXT)):
        return {"state": "external", "match": None, "family": None, "entry": None, "instance": None, "note": "문서 파일이 아닌 외부 주소입니다."}
    if not info.ext and kind in ("unc-path", "file-path"):
        return {"state": "external", "match": None, "family": None, "entry": None, "instance": None, "note": "파일이 아닌 폴더 경로입니다."}
    if re.fullmatch(r"외부 통합문서 \[\d+\]", target):
        return {**missing, "note": "연결된 통합문서의 경로를 확인할 수 없습니다."}

    hits = [i for i in by_name.get(_norm(info.name), []) if i != owner]
    if hits:
        distinct: dict[str, str] = {}
        for iid in hits:
            distinct.setdefault(instances[iid]["entry"] or iid, iid)
        if len(distinct) == 1:
            return to_instance(next(iter(distinct.values())), "exact-name")
        cands = [{"family": instances[i]["family"], "entry": instances[i]["entry"], "instance": i} for i in distinct.values()]
        return ambiguous(cands, "exact-name", f"이름이 같은 서로 다른 파일이 {len(cands)}개 있습니다.")
    if info.docno and info.docno in docno_family:
        fams = [docno_family[info.docno]]
    elif info.ext:
        fid = namekey_family.get(f"{info.base_key}|{info.ext_family}")
        fams = [fid] if fid else []
    else:
        fams = sorted(base_families.get(info.base_key, ()))
    if len(fams) == 1:
        return to_version(fams[0], info, "name-rule", info.label() if info.has_order else None)
    if fams:
        return ambiguous([{"family": f, "entry": families[f]["latest"]["entry"], "instance": None} for f in fams], "name-rule", "이름이 맞는 문서군이 여러 개입니다.")
    return {**missing, "match": "name-rule", "note": "이름이 맞는 문서가 없습니다."}
