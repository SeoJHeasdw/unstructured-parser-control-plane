"""작업 에이전트 도구의 실제 동작.

설계 전제(docs/AGENT_TOOLS.md): 도구를 부르는 쪽은 도구 호출이 불안정한 중형 모델이다.
- 인자는 평평하게, 필수는 1개 이하. 'D12', 'd-12', '12', 파일 이름 등 흔한 변형을 받아 준다.
- 응답은 짧은 평문. 첫 줄은 결과 판정, 둘째 줄은 다음에 할 일.
- 경고가 하나라도 있으면 '성공'이라 하지 않는다. 실패 원인은 서버의 오류 코드로 확정해 돌려준다.
- 사람이 옮겨 칠 '타이핑용' 블록은 ASCII 짧은 코드(codes.py)로만 만든다.
- 사실은 서버가 기록한다(runtime/agent/calls.jsonl). 모델의 요약은 근거로 쓰지 않는다.
"""
from collections import Counter
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
import platform
import re
import sys
import threading
import time
import traceback
import unicodedata

from app.agent import codes
from app.agent.client import Api, ApiError, ServerDown
from app.filelock import try_lock, unlock

PROJECT = Path(__file__).resolve().parents[3]
APP_DIR = Path(__file__).resolve().parents[1]
MAX_UPLOAD = 100 * 1024 * 1024
SCAN_LIMIT = 20000
READ_LIMIT = 3500
REF_LIMIT = 3
LOCK_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}
_TABLE_SEP = re.compile(r"^\s*\|(\s*:?-+:?\s*\|)+\s*$")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_DOC_REF = re.compile(r"(?:#|d\s*-?\s*)?(\d{1,6})", re.IGNORECASE)
_DOC_LIST = re.compile(r"^\s*((?:#|d\s*-?\s*)?\d{1,6})(\s*[, ]\s*(?:#|d\s*-?\s*)?\d{1,6})*\s*$", re.IGNORECASE)
_HEX_ID = re.compile(r"[0-9a-f]{32}")
_TRUE = {"true", "yes", "y", "1", "on", "예", "네", "응", "참"}


class ToolError(Exception):
    def __init__(self, kind: str, message: str, hint: str = ""):
        super().__init__(message)
        self.kind = kind
        self.hint = hint


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(moment: datetime | None = None) -> str:
    return (moment or _now()).isoformat(timespec="seconds")


def _local(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone()


def _short_time(value: str | None) -> str:
    moment = _local(value)
    return moment.strftime("%m-%d %H:%M") if moment else "-"


def _seconds(ms: int | None) -> str:
    if ms is None:
        return "-"
    value = ms / 1000
    return f"{value:.1f}" if value < 10 else str(round(value))


def _size(value: int) -> str:
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if value >= scale:
            return f"{value / scale:.1f}{unit}"
    return f"{value}B"


def _on(value) -> str:
    return "켜짐" if value else "꺼짐"


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _refs(numbers: list[int]) -> str:
    numbers = sorted(set(numbers))
    shown = " ".join(f"D{n}" for n in numbers[:REF_LIMIT])
    return shown + (f" +{len(numbers) - REF_LIMIT}" if len(numbers) > REF_LIMIT else "")


def build_id() -> str:
    """배포된 코드 판별용 6자리. 줄바꿈(CRLF/LF)과 무관하게 같은 소스면 같은 값이다."""
    digest = hashlib.sha256()
    for path in sorted(APP_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(APP_DIR).as_posix().encode("utf-8"))
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:6]


def as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE if value is not None else False


def as_int(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ToolError("bad-arg", "쪽 번호는 숫자여야 합니다.", "예: page=3")
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"\d+", str(value))
    if not match:
        raise ToolError("bad-arg", f"숫자를 읽지 못했습니다: {value!r}", "예: page=3")
    return int(match.group())


def as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(as_text(item) for item in value)
    return str(value).strip()


class Store:
    """runtime/agent 아래 JSON 상태. 같은 PC에서 MCP 서버가 여럿 떠도 번호가 겹치지 않게 파일 잠금으로 묶는다."""

    def __init__(self, directory: Path):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "reports").mkdir(exist_ok=True)
        self._thread_lock = threading.RLock()
        self._local = threading.local()

    def _path(self, name: str) -> Path:
        return self.dir / f"{name}.json"

    def load(self, name: str, default):
        try:
            return json.loads(self._path(name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def save(self, name: str, value) -> None:
        path = self._path(name)
        temp = path.with_suffix(f".{os.getpid()}.tmp")
        try:
            temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            for attempt in range(20):
                try:
                    os.replace(temp, path)
                    return
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            temp.unlink(missing_ok=True)

    @contextmanager
    def locked(self):
        """Serialize state changes across threads and processes, allowing nested calls."""
        with self._thread_lock:
            if getattr(self._local, "holding_lock", False):
                yield
                return
            with (self.dir / "agent.lock").open("a+") as handle:
                deadline = time.monotonic() + 10
                while True:
                    try:
                        try_lock(handle)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise ToolError("busy", "작업 도구 상태 파일이 잠겨 있습니다. 잠시 뒤 다시 시도해 주세요.")
                        time.sleep(0.05)
                self._local.holding_lock = True
                try:
                    yield
                finally:
                    self._local.holding_lock = False
                    unlock(handle)

    def append_call(self, entry: dict) -> None:
        with (self.dir / "calls.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def calls(self, since: datetime | None) -> list[dict]:
        try:
            lines = (self.dir / "calls.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        result = []
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            moment = _local(entry.get("ts"))
            if since is None or (moment and moment >= since):
                result.append(entry)
        return result


class Ops:
    def __init__(self, runtime_dir: Path, runtime_id: str | None = None, roots: list[Path] | None = None,
                 wait_seconds: float | None = None, confirm_over: int | None = None, api: Api | None = None):
        self.store = Store(runtime_dir / "agent")
        self.api = api or Api(runtime_id)
        self.roots, self.root_notes = self._roots(roots)
        # OpenCode의 MCP 요청 시간 제한 기본값이 5초다. 설정 없이도 시간 초과가 나지 않게 기본 대기는 4초로 두고,
        # 작업 폴더 설정(init-workspace)이 시간 제한을 늘리면서 이 값도 함께 늘린다.
        self.wait_seconds = wait_seconds if wait_seconds is not None else float(os.environ.get("DOCOPS_AGENT_WAIT_SECONDS", "4"))
        self.confirm_over = confirm_over if confirm_over is not None else int(os.environ.get("DOCOPS_AGENT_CONFIRM_OVER", "50"))
        self._pump_thread: threading.Thread | None = None
        self._pump_lock = threading.Lock()
        self._last_call: tuple[str, float, str] | None = None
        self._parsers: dict | None = None
        self.build = build_id()

    # ------------------------------------------------------------------ 기반
    @staticmethod
    def _roots(given: list[Path] | None) -> tuple[list[Path], list[str]]:
        if given is None:
            raw = os.environ.get("DOCOPS_AGENT_ROOTS", "")
            parts = [part.strip().strip('"') for chunk in raw.splitlines() for part in chunk.split(os.pathsep)]
            given = [Path(part).expanduser() for part in parts if part]
            if not given and (PROJECT / "samples").is_dir():
                given = [PROJECT / "samples"]
        roots, notes = [], []
        for root in given:
            try:
                resolved = root.resolve()
            except OSError:
                notes.append(f"허용 폴더를 열 수 없음: {root}")
                continue
            if resolved.is_dir():
                roots.append(resolved)
            else:
                notes.append(f"허용 폴더가 없음: {root}")
        return roots, notes

    def parsers(self, refresh: bool = False) -> dict:
        if self._parsers is None or refresh:
            self._parsers = self.api.get("/api/live/parsers")
        return self._parsers

    def documents(self) -> list[dict]:
        """D번호를 붙인 문서 목록(오래된 것부터). 번호는 서버가 매긴 문서 번호(seq)라 화면과 같다."""
        docs = list(reversed(self.api.get("/api/live/documents")["documents"]))
        if docs and all(doc.get("seq") for doc in docs):
            for doc in docs:
                doc["n"] = doc["seq"]
            return sorted(docs, key=lambda doc: doc["n"])
        # 문서 번호가 없는 이전 버전 서버: 작업 도구가 따로 매긴 번호를 쓴다.
        with self.store.locked():
            aliases = self.store.load("aliases", {"next": 1, "ids": {}})
            changed = False
            for doc in docs:
                if doc["id"] not in aliases["ids"]:
                    aliases["ids"][doc["id"]] = aliases["next"]
                    aliases["next"] += 1
                    changed = True
            if changed:
                self.store.save("aliases", aliases)
        for doc in docs:
            doc["n"] = aliases["ids"][doc["id"]]
        return docs

    def find_doc(self, ref) -> dict:
        text = as_text(ref)
        if not text:
            raise ToolError("bad-arg", "문서 번호가 비어 있습니다.", "예: id=\"D12\" (번호는 docs 로 확인)")
        docs = self.documents()
        if _HEX_ID.fullmatch(text.lower()):
            match = [doc for doc in docs if doc["id"] == text.lower()]
            if match:
                return match[0]
        number = _DOC_REF.fullmatch(text.replace(" ", ""))
        if number:
            n = int(number.group(1))
            match = [doc for doc in docs if doc["n"] == n]
            if match:
                return match[0]
            known = f"등록된 번호는 D1~D{max(d['n'] for d in docs)}입니다." if docs else "아직 등록된 문서가 없습니다."
            raise ToolError("not-found", f"D{n} 문서가 없습니다. {known}", "docs 로 목록을 보세요." if docs else "parse 로 먼저 파일을 등록하세요.")
        name = _nfc(text).casefold()
        exact = [doc for doc in docs if _nfc(doc["name"]).casefold() == name]
        partial = exact or [doc for doc in docs if name in _nfc(doc["name"]).casefold()]
        if len(partial) == 1:
            return partial[0]
        if partial:
            listed = ", ".join(f"D{doc['n']} {_clip(doc['name'], 30)}" for doc in partial[-5:])
            raise ToolError("bad-arg", f"'{text}'에 맞는 문서가 {len(partial)}개입니다: {listed}", "D번호 하나로 다시 불러 주세요.")
        raise ToolError("not-found", f"'{text}' 문서를 찾지 못했습니다.", "docs 로 D번호를 확인하세요.")

    def runs(self, doc_id: str) -> list[dict]:
        return self.api.get(f"/api/live/documents/{doc_id}/runs")["runs"]

    def run_detail(self, doc_id: str, run_id: str) -> dict:
        return self.api.get(f"/api/live/documents/{doc_id}/runs/{run_id}")

    def run_metrics(self, doc_id: str, run: dict) -> dict:
        """실행 결과 지표. 실행 결과는 바뀌지 않으므로 run_id로 영구 저장해 다시 받지 않는다."""
        with self.store.locked():
            cache = self.store.load("runs", {})
        if run["run_id"] in cache:
            return cache[run["run_id"]]
        detail = self.run_detail(doc_id, run["run_id"])
        markdown = detail["markdown"]
        lines = markdown.splitlines()
        metrics = {
            "chars": sum(1 for ch in markdown if not ch.isspace()),
            "lines": len(lines),
            "tables": sum(1 for line in lines if line.lstrip().startswith("|") and not _TABLE_SEP.match(line)),
            "numbers": len(_NUMBER.findall(markdown)),
            "broken": markdown.count("\ufffd"),
            "pages": max((loc.get("page") or 0 for loc in detail.get("locations", [])), default=0) or None,
            "sha": hashlib.sha256(markdown.encode("utf-8")).hexdigest()[:16],
            "warn": codes.warning_codes(detail.get("warnings", []), detail.get("fidelity")),
        }
        with self.store.locked():
            cache = self.store.load("runs", {})
            cache[run["run_id"]] = metrics
            self.store.save("runs", cache)
        return metrics

    def doc_view(self, doc: dict) -> dict:
        """판정에 필요한 정보: 최신 실행·직전 실행·경고 코드."""
        runs = self.runs(doc["id"]) if doc["status"] != "uploaded" else []
        latest = next((run for run in runs if run.get("is_latest")), runs[0] if runs else None)
        metrics = self.run_metrics(doc["id"], latest) if latest else None
        previous = next((run for run in runs if latest and run["run_id"] != latest["run_id"]), None)
        warn = metrics["warn"] if metrics and doc["status"] == "completed" else []
        return {"doc": doc, "runs": runs, "latest": latest, "metrics": metrics, "previous": previous,
                "warn": warn, "verdict": codes.verdict(doc["status"], warn, doc.get("error_code"), doc.get("format"))}

    # ------------------------------------------------------------------ 도구: status
    def status(self) -> str:
        lines = []
        try:
            parsers = self.parsers(refresh=True)
            server = f"{self.api.base}" + (" (같은 저장소 확인)" if not self.api.note else f" — {self.api.note}")
        except ServerDown as exc:
            raise ToolError("server-down", str(exc), "사용자에게 콘솔을 켜 달라고 요청하세요.") from None
        docs = self.documents()
        counts = Counter(doc["status"] for doc in docs)
        problems = []
        if not parsers["docling_installed"]:
            problems.append("Docling 미설치: PDF·Office 파싱 불가(setup을 --lite 없이 다시 실행)")
        elif not parsers["pdf_model_directory"]:
            problems.append("PDF 모델 폴더 없음: PDF 파싱 불가")
        elif parsers.get("pdf_models_ready") is False:
            problems.append("PDF 모델 파일 누락: 콘솔을 끄고 setup 다시 실행(또는 docling-tools models download layout tableformer)")
        if not parsers["ocr_models_found"]:
            problems.append("OCR 모델 미연결: 스캔 쪽·이미지·문서 속 그림의 글자를 읽지 않음(콘솔 '모델 연결'에서 OCR 모델 설정)")
        if not self.roots:
            problems.append("허용 폴더 없음: opencode.json의 DOCOPS_AGENT_ROOTS 설정 필요")
        lines.append("결과: " + ("준비됨" if not problems else f"주의 {len(problems)}건"))
        lines.append("다음: files 로 허용 폴더의 파일을 보거나, parse 로 파싱을 시작하세요." if self.roots else
                     "다음: 사용자에게 DOCOPS_AGENT_ROOTS(파일을 읽을 폴더) 설정을 요청하세요.")
        lines.append(f"서버: {server}")
        lines += [f"주의: {problem}" for problem in problems]
        lines.append("허용 폴더: " + (" | ".join(str(root) for root in self.roots) or "없음"))
        lines += [f"주의: {note}" for note in self.root_notes]
        lines.append("문서: 전체 {} (완료 {}, 실패 {}, 미지원 {}, 처리 중 {}, 미처리 {})".format(
            len(docs), counts["completed"], counts["failed"], counts["unsupported"], counts["processing"], counts["uploaded"]))
        batch = self._latest_batch()
        if batch:
            done = sum(1 for item in batch["items"] if item["state"] in ("done", "error"))
            lines.append(f"최근 묶음: B{batch['n']} {done}/{len(batch['items'])} " + ("끝남" if batch.get("finished") else "진행 중"))
        lines.append(f"빌드: {self.build}  Python {platform.python_version()}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ 경로 해석
    def _inside(self, path: Path) -> bool:
        for root in self.roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    def _clean_target(self, text: str) -> str:
        text = text.strip().strip("`").strip().strip("\"'“”‘’").strip()
        if os.name != "nt":
            text = text.replace("\\", "/")
        return text

    def _display(self, path: Path) -> str:
        """허용 폴더가 하나면 그 기준 상대 경로(짧게), 여럿이면 전체 경로."""
        if len(self.roots) == 1:
            try:
                return path.relative_to(self.roots[0]).as_posix()
            except ValueError:
                pass
        return str(path)

    def _path_exists(self, text: str) -> bool:
        path = Path(self._clean_target(text))
        return any((candidate.exists() for candidate in ([path] if path.is_absolute() else [root / path for root in self.roots])))

    def _walk(self, folder: Path):
        count = 0
        for current, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not d.startswith((".", "$", "__MACOSX")))
            for name in sorted(files):
                count += 1
                if count > SCAN_LIMIT:
                    return
                yield Path(current) / name

    def resolve(self, target: str) -> tuple[list[Path], bool]:
        """(파일 목록, 폴더·패턴 여부). 폴더·패턴이면 처리 경로가 없는 확장자를 거른다."""
        text = self._clean_target(target)
        if not text:
            raise ToolError("bad-arg", "target이 비어 있습니다.", EXAMPLES["parse"])
        if not self.roots:
            raise ToolError("outside", "파일을 읽을 허용 폴더가 설정되지 않았습니다.", "사용자에게 DOCOPS_AGENT_ROOTS 설정을 요청하세요.")
        if any(ch in text for ch in "*?["):
            pattern_path = Path(text)
            matches = []
            if pattern_path.is_absolute():
                anchor = Path(pattern_path.anchor)
                parts = pattern_path.parts[1:]
                split = next(i for i, part in enumerate(parts) if any(ch in part for ch in "*?["))
                base = anchor.joinpath(*parts[:split])
                bases = [(base, str(Path(*parts[split:])))]
            else:
                bases = [(root, text if "/" in text or "\\" in text else "**/" + text) for root in self.roots]
            for base, pattern in bases:
                try:
                    matches += [path for path in base.glob(pattern) if path.is_file()]
                except (OSError, ValueError, NotImplementedError):
                    continue
            matches = [path.resolve() for path in matches]
            outside = [path for path in matches if not self._inside(path)]
            matches = sorted({path for path in matches if self._inside(path)})
            if not matches:
                hint = f" 허용 폴더 밖 {len(outside)}개는 제외했습니다." if outside else ""
                raise ToolError("not-found", f"'{text}'에 맞는 파일이 없습니다.{hint}", "files 로 허용 폴더의 파일을 확인하세요.")
            return matches, True
        path = Path(text).expanduser()
        candidates = [path] if path.is_absolute() else [root / path for root in self.roots]
        for candidate in candidates:
            if candidate.exists():
                resolved = candidate.resolve()
                if not self._inside(resolved):
                    raise ToolError("outside", f"허용 폴더 밖의 경로입니다: {resolved}",
                                    "허용 폴더: " + " | ".join(str(root) for root in self.roots))
                if resolved.is_dir():
                    return [p for p in self._walk(resolved) if p.is_file()], True
                return [resolved], False
        # 파일 이름만 준 경우: 허용 폴더 안에서 같은 이름(대소문자·한글 조합형 무시)을 찾는다.
        wanted = _nfc(path.name).casefold()
        found = []
        for root in self.roots:
            for file in self._walk(root):
                if _nfc(file.name).casefold() == wanted:
                    found.append(file.resolve())
        if len(found) == 1:
            return found, False
        if found:
            listed = " | ".join(str(p) for p in found[:5])
            raise ToolError("bad-arg", f"같은 이름의 파일이 {len(found)}개입니다: {listed}", "전체 경로로 다시 불러 주세요.")
        raise ToolError("not-found", f"'{text}'를 허용 폴더에서 찾지 못했습니다.", "files 로 파일 이름을 확인하세요.")

    def classify(self, files: list[Path], filtered: bool) -> tuple[list[Path], Counter]:
        supported = set(self.parsers()["routes"])
        keep, skips = [], Counter()
        for path in files:
            name = path.name
            if name.startswith("~$"):
                skips["lock"] += 1
                continue
            if name.startswith(".") or name.lower() in LOCK_NAMES:
                skips["hidden"] += 1
                continue
            try:
                size = path.stat().st_size
            except OSError:
                skips["hidden"] += 1
                continue
            if size == 0:
                skips["empty"] += 1
                continue
            if size > MAX_UPLOAD:
                skips["too-big"] += 1
                continue
            extension = path.suffix.lstrip(".").upper()
            if filtered and extension not in supported:
                skips["ext-" + (extension.lower() or "none")] += 1
                continue
            keep.append(path)
        return keep, skips

    # ------------------------------------------------------------------ 도구: files
    def files(self, folder: str = "") -> str:
        if folder:
            paths, _ = self.resolve(folder)
        else:
            if not self.roots:
                raise ToolError("outside", "허용 폴더가 설정되지 않았습니다.", "사용자에게 DOCOPS_AGENT_ROOTS 설정을 요청하세요.")
            paths = [p for root in self.roots for p in self._walk(root) if p.is_file()]
        keep, skips = self.classify(paths, True)
        by_ext = Counter(path.suffix.lstrip(".").lower() or "none" for path in keep)
        registry = self.store.load("registry", {})
        aliases = self.store.load("aliases", {"ids": {}})["ids"]
        lines = [f"결과: 처리 가능한 파일 {len(keep)}개" + (f", 건너뜀 {sum(skips.values())}개" if skips else ""),
                 "다음: parse 에 파일·폴더 경로나 '*.pdf' 같은 패턴을 넣어 파싱하세요.",
                 "형식: " + (" ".join(f"{ext}{count}" for ext, count in by_ext.most_common()) or "없음")]
        if skips:
            lines.append("건너뜀: " + " ".join(f"{code}{count}" for code, count in skips.most_common()))
        if len(self.roots) == 1:
            lines.append(f"폴더: {self.roots[0]} (아래 경로는 이 폴더 기준이고, parse 에 그대로 넣을 수 있습니다)")
        for path in keep[:30]:
            entry = registry.get(os.path.normcase(str(path)))
            mark = f"  [D{aliases[entry['doc']]}]" if entry and entry.get("doc") in aliases else ""
            lines.append(f"- {self._display(path)}  {_size(path.stat().st_size)}{mark}")
        if len(keep) > 30:
            lines.append(f"- … 외 {len(keep) - 30}개")
        return "\n".join(lines)

    # ------------------------------------------------------------------ 도구: parse / wait
    def parse(self, target: str, reparse: bool = False, confirm: bool = False) -> str:
        text = as_text(target)
        lowered = text.strip().lower()
        items, skips, label = [], Counter(), text
        if lowered in ("failed", "fail", "실패", "실패한 문서"):
            docs = [doc for doc in self.documents() if doc["status"] in ("failed", "unsupported")]
            if not docs:
                return "결과: 실패한 문서가 없습니다.\n다음: docs 로 목록을 보거나 report 로 보고서를 만드세요."
            items = [{"path": None, "doc": doc["id"], "state": "pending", "note": ""} for doc in docs]
            reparse = True
        elif _DOC_LIST.match(text) and (re.search(r"[dD#]", text) or not self._path_exists(text)):
            numbers = [int(n) for n in re.findall(r"\d+", text)]
            docs = [self.find_doc(f"D{n}") for n in dict.fromkeys(numbers)]
            items = [{"path": None, "doc": doc["id"], "state": "pending", "note": ""} for doc in docs]
            reparse = True
        else:
            files, filtered = self.resolve(text)
            keep, skips = self.classify(files, filtered)
            if not keep:
                detail = " ".join(f"{code}{count}" for code, count in skips.most_common()) or "없음"
                raise ToolError("not-found", f"처리할 파일이 없습니다(건너뜀: {detail}).", "files 로 확인하세요.")
            if len(keep) > self.confirm_over and not confirm:
                by_ext = Counter(path.suffix.lstrip(".").lower() for path in keep)
                return "\n".join([
                    f"결과: 미리보기 — 파일 {len(keep)}개라 아직 시작하지 않았습니다.",
                    f"다음: 사용자에게 확인을 받은 뒤 같은 target에 confirm=true를 넣어 parse를 다시 부르세요.",
                    "형식: " + " ".join(f"{ext}{count}" for ext, count in by_ext.most_common()),
                ] + (["건너뜀: " + " ".join(f"{c}{n}" for c, n in skips.most_common())] if skips else []))
            items = [{"path": str(path), "doc": None, "state": "file", "note": ""} for path in keep]
        with self.store.locked():
            batches = self.store.load("batches", {"next": 1, "items": []})
            batch = {"n": batches["next"], "target": label, "reparse": bool(reparse), "started": _iso(),
                     "finished": None, "skips": dict(skips), "items": items, "error": ""}
            batches["next"] += 1
            batches["items"] = (batches["items"] + [batch])[-50:]
            self.store.save("batches", batches)
        self._ensure_pump()
        return self._await(batch["n"], started=True)

    def wait(self) -> str:
        batch = self._latest_batch()
        if not batch:
            return "결과: 진행 중인 묶음이 없습니다.\n다음: parse 로 파싱을 시작하세요."
        if batch.get("finished"):
            return self._digest_text(batch, again=True)
        self._ensure_pump()
        return self._await(batch["n"], started=False)

    def _latest_batch(self) -> dict | None:
        batches = self.store.load("batches", {"items": []})["items"]
        unfinished = [batch for batch in batches if not batch.get("finished")]
        return (unfinished or batches or [None])[-1]

    def _batch(self, n: int) -> dict | None:
        return next((batch for batch in self.store.load("batches", {"items": []})["items"] if batch["n"] == n), None)

    def _await(self, n: int, started: bool) -> str:
        deadline = time.monotonic() + self.wait_seconds
        while True:
            batch = self._batch(n)
            if batch is None:
                raise ToolError("internal", f"B{n} 묶음 기록을 찾지 못했습니다.")
            if batch.get("finished"):
                return self._digest_text(batch)
            if time.monotonic() >= deadline:
                return self._progress_text(batch, started)
            time.sleep(0.5)

    def _progress_text(self, batch: dict, started: bool) -> str:
        states = Counter(item["state"] for item in batch["items"])
        done = states["done"] + states["error"]
        lines = [f"결과: 진행 중 B{batch['n']} — 전체 {len(batch['items'])}, 끝남 {done}, 처리 대기 {states['queued'] + states['pending']}, 등록 중 {states['file']}",
                 "다음: wait 를 부르세요(한 번에 최대 {}초 기다립니다).".format(round(self.wait_seconds))]
        if batch.get("error"):
            lines.append(f"주의: {batch['error']}")
        if started:
            lines.append("참고: 이 묶음은 도구를 부르지 않는 동안에도 콘솔 서버에서 계속 처리됩니다.")
        return "\n".join(lines)

    def _ensure_pump(self) -> None:
        with self._pump_lock:
            if self._pump_thread and self._pump_thread.is_alive():
                return
            self._pump_thread = threading.Thread(target=self._pump, name="docops-agent-pump", daemon=True)
            self._pump_thread.start()

    def _pump(self) -> None:
        """묶음 진행: 파일 등록 → 처리 요청(대기열 64건 한도 안에서) → 완료 확인. 도구 호출과 무관하게 돈다."""
        loop, down_since = 0, None
        while True:
            loop += 1
            try:
                docs = {doc["id"]: doc for doc in self.documents()}
                down_since = None
            except ServerDown as exc:
                down_since = down_since or time.monotonic()
                self._mark_error(str(exc))
                if time.monotonic() - down_since > 120:
                    return
                time.sleep(3)
                continue
            except Exception as exc:  # noqa: BLE001 — 스레드가 조용히 죽지 않게
                print(f"[docops-agent] pump error: {type(exc).__name__}: {exc}", file=sys.stderr)
                time.sleep(3)
                continue
            with self.store.locked():
                active = [batch for batch in self.store.load("batches", {"items": []})["items"] if not batch.get("finished")]
            if not active:
                return
            # 네트워크 작업(등록·처리 요청)은 잠금 밖에서 하고, 결과만 잠금 안에서 합친다.
            full, uploads = False, 0
            for batch in active:
                batch["error"] = ""
                for item in batch["items"]:
                    if item["state"] == "file" and uploads < 20:
                        self._register_item(item, batch, docs)
                        uploads += 1
                    if item["state"] == "pending" and not full:
                        full = self._enqueue_item(item, loop)
                    if item["state"] == "queued" and item.get("q", 0) < loop:
                        doc = docs.get(item["doc"])
                        if doc is None:
                            item["state"], item["note"] = "error", "missing"
                        elif doc["status"] != "processing":
                            item["state"] = "done"
                if all(item["state"] in ("done", "error") for item in batch["items"]):
                    batch["finished"] = _iso()
            updated = {batch["n"]: batch for batch in active}
            with self.store.locked():
                batches = self.store.load("batches", {"next": 1, "items": []})
                batches["items"] = [updated.get(batch["n"], batch) for batch in batches["items"]]
                self.store.save("batches", batches)
            time.sleep(0.2 if uploads else 1.0)

    def _mark_error(self, message: str) -> None:
        with self.store.locked():
            batches = self.store.load("batches", {"next": 1, "items": []})
            for batch in batches["items"]:
                if not batch.get("finished"):
                    batch["error"] = message
            self.store.save("batches", batches)

    def _matching_source(self, path: Path, candidates: list[dict], entry: dict | None):
        if not candidates:
            return None, None
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if entry and entry.get("sha256") == digest:
            known = next((d for d in candidates if d["id"] == entry.get("doc")), None)
            if known:
                return known, digest
        for candidate in candidates:
            try:
                if self.api.source_digest(candidate["id"]) == digest:
                    return candidate, digest
            except ApiError as exc:
                if exc.status not in (404, 409):
                    raise
        return None, None

    def _register_item(self, item: dict, batch: dict, docs: dict) -> None:
        path = Path(item["path"])
        try:
            stat = path.stat()
        except OSError:
            item["state"], item["note"] = "error", "missing-file"
            return
        key = os.path.normcase(str(path))
        registry = self.store.load("registry", {})
        entry = registry.get(key)
        if stat.st_size > MAX_UPLOAD:
            item["state"], item["note"] = "error", "too-big"
            return
        name = _nfc(path.name)
        candidates = [d for d in reversed(docs.values())
                      if _nfc(d["name"]) == name and d["size_bytes"] == stat.st_size]
        try:
            doc, digest = self._matching_source(path, candidates, entry)
        except OSError:
            item["state"], item["note"] = "error", "read-fail"
            return
        except (ServerDown, ApiError):
            item["state"], item["note"] = "error", "source-check"
            return
        reused = doc is not None
        if doc is None:
            try:
                doc = self.api.upload(path, path.name)
            except ApiError as exc:
                item["state"], item["note"] = "error", "too-big" if exc.status == 413 else f"upload-{exc.status}"
                return
            except OSError:
                item["state"], item["note"] = "error", "read-fail"
                return
            except ServerDown:
                item["state"], item["note"] = "error", "upload-unknown"
                return
            docs[doc["id"]] = doc
        with self.store.locked():
            registry = self.store.load("registry", {})
            registry[key] = {"doc": doc["id"], "sha256": digest}
            self.store.save("registry", registry)
        item["doc"], item["note"] = doc["id"], "reuse" if reused else "new"
        if reused and not batch["reparse"] and doc["status"] in ("completed", "failed", "unsupported"):
            item["state"] = "done"
        elif doc["status"] == "processing":
            item["state"], item["q"] = "queued", 0
        else:
            item["state"] = "pending"

    def _enqueue_item(self, item: dict, loop: int) -> bool:
        """처리 요청. 대기열이 가득 차면 True(이번 회차에는 더 넣지 않는다)."""
        try:
            self.api.post(f"/api/live/documents/{item['doc']}/process")
        except ServerDown:
            item["state"], item["note"] = "error", "process-unknown"
            return False
        except ApiError as exc:
            if exc.status == 409:
                item["state"], item["q"] = "queued", loop
                return False
            if exc.status == 503:
                return True
            item["state"], item["note"] = "error", "missing" if exc.status == 404 else f"process-{exc.status}"
            return False
        item["state"], item["q"] = "queued", loop
        return False

    # ------------------------------------------------------------------ 요약(타이핑용)
    def _digest_text(self, batch: dict, again: bool = False) -> str:
        ids = [item["doc"] for item in batch["items"] if item.get("doc")]
        errors = Counter(item["note"] for item in batch["items"] if item["state"] == "error")
        skips = Counter(batch.get("skips", {}))
        for note, count in errors.items():
            skips[note] += count
        since = _local(batch["started"])
        block, summary = self.summary(f"B{batch['n']}", ids, since, skips, reused=sum(1 for i in batch["items"] if i["note"] == "reuse"))
        return self._wrap(f"B{batch['n']}", block, summary, again)

    def _wrap(self, label: str, block: list[str], summary: str, again: bool = False) -> str:
        path = self.store.dir / "reports" / f"{label}.txt"
        path.write_text("\n".join(block) + "\n", encoding="utf-8")
        head = [summary,
                ("참고: 이미 끝난 묶음입니다. 같은 결과를 다시 보여 줍니다.\n" if again else "") +
                "다음: 응답에 아래 '타이핑용' 블록을 ```text 코드 블록으로 한 글자도 바꾸지 말고 복사하세요. "
                "코드를 스스로 풀이하지 말고, 설명이 필요하면 위 '설명' 줄을 그대로 쓰세요. 도구 결과에 없는 조언은 하지 마세요.",
                "----- 타이핑용 -----", *block, "-----", f"파일: {path}"]
        return "\n".join(head)

    def summary(self, label: str, ids: list[str], since: datetime | None, skips: Counter, reused: int = 0) -> tuple[list[str], str]:
        docs = {doc["id"]: doc for doc in self.documents()}
        views = [self.doc_view(docs[doc_id]) for doc_id in dict.fromkeys(ids) if doc_id in docs]
        verdicts = Counter(view["verdict"] for view in views)
        try:
            parsers = self.parsers()
        except (ServerDown, ApiError):
            parsers = {}
        osname = {"nt": "win"}.get(os.name, "mac" if sys.platform == "darwin" else "linux")
        flag = lambda key: "1" if parsers.get(key) else "0"  # noqa: E731
        block = [f"DOCOPS {label} {_now().strftime('%m-%d %H:%M')} build {self.build}",
                 f"env {osname} py{sys.version_info[0]}.{sys.version_info[1]} docling{flag('docling_installed')} "
                 f"pdfm{flag('pdf_models_ready' if 'pdf_models_ready' in parsers else 'pdf_model_directory')} ocr{flag('ocr_enabled')} ocrm{flag('ocr_models_found')}"]
        versions = sorted({f"{v['latest']['parser']}={(v['latest'].get('parser_version') or '').replace(' ', '')}" for v in views if v["latest"] and v["latest"].get("parser")})
        if versions:
            block.append("ver " + " ".join(versions))
        order = [key for key in codes.VERDICTS if verdicts[key]]
        block.append(f"sum {len(views)} " + " ".join(f"{key}{verdicts[key]}" for key in order) + (f" reuse{reused}" if reused else ""))
        by_format: dict[str, list[dict]] = {}
        for view in views:
            by_format.setdefault(view["doc"]["format"].lower(), []).append(view)
        for fmt, group in sorted(by_format.items(), key=lambda pair: (-len(pair[1]), pair[0])):
            counts = Counter(view["verdict"] for view in group)
            line = f"{fmt} {len(group)} " + " ".join(f"{key}{counts[key]}" for key in codes.VERDICTS if counts[key])
            timed = [(view["latest"]["duration_ms"], view["doc"]["n"]) for view in group
                     if view["verdict"] in ("ok", "warn") and view["latest"] and view["latest"].get("duration_ms") is not None]
            if timed:
                average = sum(ms for ms, _ in timed) / len(timed)
                slowest = max(timed)
                line += f" t{_seconds(round(average))}/{_seconds(slowest[0])}s(D{slowest[1]})"
            block.append(line)
        fails: dict[str, list[int]] = {}
        empties = [view["doc"]["n"] for view in views if view["verdict"] == "empty"]
        for view in views:
            if view["verdict"] in ("fail", "unsup"):
                fails.setdefault(codes.error_code(view["doc"].get("error_code")), []).append(view["doc"]["n"])
        notes: list[str] = []
        if fails:
            block += self._code_lines("fail", fails)
        if empties:
            block.append(f"empty{len(empties)} {_refs(empties)}")
            notes.append(f"설명(글자 없음): {len(empties)}건 {_refs(empties)} — {codes.MEANINGS['empty']}")
        warns: dict[str, list[int]] = {}
        for view in views:
            for code in dict.fromkeys(code for code, _ in view["warn"]):
                warns.setdefault(code, []).append(view["doc"]["n"])
        if warns:
            block += self._code_lines("warn", warns)
        for prefix, grouped in (("실패", fails), ("경고", warns)):
            for code, numbers in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0])):
                notes.append(f"설명({prefix}): {code} {len(numbers)}건 {_refs(numbers)} — {codes.MEANINGS.get(code, '코드표 참고')}")
        if skips:
            block.append("skip " + " ".join(f"{code}{count}" for code, count in skips.most_common()))
        diff = self._diff_line(views)
        if diff:
            block.append(diff)
        calls = self.store.calls(since)
        if calls:
            kinds = Counter(entry.get("kind") for entry in calls if entry.get("kind"))
            repeats = sum(1 for entry in calls if entry.get("repeat"))
            line = f"agent call{len(calls)}" + (f" err{sum(kinds.values())}" if kinds else "") + "".join(f" {kind}{count}" for kind, count in kinds.most_common())
            block.append(line + (f" repeat{repeats}" if repeats else ""))
        bad = verdicts["fail"] + verdicts["unsup"]
        if verdicts["run"] or verdicts["new"]:
            summary = f"결과: 아직 끝나지 않은 문서 {verdicts['run'] + verdicts['new']}건 포함 (전체 {len(views)}건)"
        elif bad:
            summary = f"결과: 실패 있음 — 전체 {len(views)}건 중 실패·미지원 {bad}, 경고 {verdicts['warn']}"
        elif verdicts["warn"]:
            summary = f"결과: 경고 있음 — 전체 {len(views)}건 중 경고 {verdicts['warn']} (경고는 품질 확인이 필요하다는 뜻입니다)"
        else:
            summary = f"결과: 경고 없이 끝남 — {len(views)}건 (파싱 성공이 품질 보증은 아닙니다)"
        return block, "\n".join([summary, *notes])

    @staticmethod
    def _code_lines(prefix: str, grouped: dict[str, list[int]]) -> list[str]:
        parts = [f"{code}{len(numbers)} {_refs(numbers)}" for code, numbers in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0]))]
        return [f"{prefix} " + " / ".join(parts[i:i + 3]) for i in range(0, len(parts), 3)]

    def _diff_line(self, views: list[dict]) -> str:
        compared, changes = 0, []
        for view in views:
            if not (view["previous"] and view["metrics"] and view["verdict"] in ("ok", "warn")):
                continue
            old = self.run_metrics(view["doc"]["id"], view["previous"])
            new = view["metrics"]
            compared += 1
            if old["sha"] == new["sha"]:
                continue
            changes.append((self._delta_score(old, new), view["doc"]["n"], self._delta(old, new)))
        if not compared:
            return ""
        changes.sort(reverse=True)
        line = f"diff {compared} same{compared - len(changes)} chg{len(changes)}"
        if changes:
            line += " " + " / ".join(f"D{n} {delta}" for _, n, delta in changes[:REF_LIMIT])
        return line

    @staticmethod
    def _delta_score(old: dict, new: dict) -> float:
        base = max(old["chars"], 1)
        return abs(new["chars"] - old["chars"]) / base + abs(new["tables"] - old["tables"]) / max(old["tables"], 1)

    @staticmethod
    def _delta(old: dict, new: dict) -> str:
        parts = []
        if new["chars"] != old["chars"]:
            pct = (new["chars"] - old["chars"]) * 100 / max(old["chars"], 1)
            parts.append(f"txt{pct:+.0f}%" if abs(pct) >= 1 else f"txt{new['chars'] - old['chars']:+d}")
        for key, short in (("tables", "tbl"), ("numbers", "num"), ("broken", "bad")):
            if new[key] != old[key]:
                parts.append(f"{short}{new[key] - old[key]:+d}")
        old_warn, new_warn = {c for c, _ in old["warn"]}, {c for c, _ in new["warn"]}
        if old_warn != new_warn:
            parts.append("warn" + "".join(f" -{c}" for c in sorted(old_warn - new_warn)) + "".join(f" +{c}" for c in sorted(new_warn - old_warn)))
        return " ".join(parts) or "fmt"

    # ------------------------------------------------------------------ 도구: docs / doc
    def docs(self, state: str = "all") -> str:
        state = (as_text(state) or "all").lower()
        aliases = {"성공": "ok", "경고": "warn", "실패": "fail", "전체": "all", "failed": "fail", "completed": "ok", "warning": "warn"}
        state = aliases.get(state, state)
        if state not in ("all", *codes.VERDICTS):
            raise ToolError("bad-arg", f"state는 all, {', '.join(codes.VERDICTS)} 중 하나입니다(받은 값: {state}).", "예: state=\"fail\"")
        docs = list(reversed(self.documents()))
        views = []
        for doc in docs:
            view = self.doc_view(doc) if doc["status"] == "completed" else {"doc": doc, "warn": [], "verdict": codes.verdict(doc["status"], None, doc.get("error_code"), doc.get("format"))}
            if state == "all" or view["verdict"] == state:
                views.append(view)
            if len(views) >= 40:
                break
        if not views:
            return f"결과: '{state}' 문서가 없습니다.\n다음: parse 로 파싱하거나 state=all 로 전체를 보세요."
        lines = [f"결과: 문서 {len(views)}건 표시 (최근 것부터" + (", 최대 40건)" if len(views) >= 40 else ")"),
                 "다음: 자세히 볼 문서는 doc 에 D번호를 넣으세요."]
        seen: dict[str, None] = {}
        for view in views:
            doc = view["doc"]
            found = [codes.error_code(doc.get("error_code"))] if view["verdict"] in ("fail", "unsup") else list(dict.fromkeys(c for c, _ in view["warn"]))
            seen.update(dict.fromkeys(found))
            code = ",".join(found)
            lines.append(f"D{doc['n']} {doc['format'].lower()} {view['verdict']}{(' ' + code) if code else ''}  {_size(doc['size_bytes'])}  {_clip(doc['name'], 40)}")
        lines += [f"설명: {code} — {codes.MEANINGS.get(code, '코드표 참고')}" for code in seen]
        return "\n".join(lines)

    def doc(self, id: str) -> str:  # noqa: A002 — 도구 인자 이름
        doc = self.find_doc(id)
        view = self.doc_view(doc)
        latest, metrics = view["latest"], view["metrics"]
        verdict = view["verdict"]
        title = {"ok": "경고 없음", "warn": "경고 있음", "empty": "글자 없음", "fail": "실패", "unsup": "미지원 형식", "run": "처리 중", "new": "아직 파싱 안 함"}[verdict]
        lines = [f"결과: D{doc['n']} {title}" + (f" ({codes.error_code(doc.get('error_code'))})" if verdict in ("fail", "unsup") else ""),
                 {"empty": "다음: 글자 없는 사진인지 사용자에게 확인을 부탁하세요. 글자가 보이는 이미지라면 OCR이 놓친 것입니다.",
                  "fail": "다음: 원인을 사용자에게 그대로 전하세요. 고칠 수 있는 원인이면 사용자가 파일을 바꾼 뒤 parse 로 다시 시도합니다.",
                  "unsup": "다음: 처리 경로가 없는 형식입니다. 사용자에게 알리세요.",
                  "warn": "다음: 경고 위치는 read 로 본문을 확인할 수 있습니다(page·sheet).",
                  "run": "다음: wait 로 끝날 때까지 기다리세요.",
                  "new": f"다음: parse 에 target=\"D{doc['n']}\" 을 넣어 파싱하세요."}.get(verdict, "다음: read 로 본문을 볼 수 있습니다."),
                 f"이름: {doc['name']}  형식 {doc['format']}  크기 {_size(doc['size_bytes'])}"]
        if doc.get("error"):
            lines.append(f"원인: {doc['error']}")
        if latest:
            stale = " — 지금 보이는 결과는 이전 성공본(is_stale)" if doc["status"] != "completed" else ""
            lines.append(f"마지막 성공 실행: {_short_time(latest.get('completed_at'))} {latest.get('parser')} {latest.get('parser_version')} "
                         f"OCR {'켜짐' if latest.get('ocr_enabled') else '꺼짐/해당 없음'} {_seconds(latest.get('duration_ms'))}s, 성공 실행 {len(view['runs'])}회{stale}")
            lines.append(f"본문: 글자 {metrics['chars']:,} 줄 {metrics['lines']:,} 표 행 {metrics['tables']:,} 숫자 {metrics['numbers']:,}"
                         + (f" 쪽 {metrics['pages']}" if metrics["pages"] else "") + (f" 깨진 글자 {metrics['broken']}" if metrics["broken"] else ""))
        if view["warn"] or (metrics and doc["status"] != "completed" and metrics["warn"]):
            detail = self.run_detail(doc["id"], latest["run_id"])
            for (code, extra), text in zip(codes.warning_codes(detail["warnings"], detail.get("fidelity")), detail["warnings"]):
                lines.append(f"경고 {code}{(' ' + extra) if extra else ''}: {_clip(text, 120)}")
        history = self.api.get(f"/api/live/documents/{doc['id']}/history")["history"][-3:]
        for entry in history:
            lines.append(f"이력: {_short_time(entry['created_at'])} {entry['status']} {_clip(entry['message'], 60)}")
        block = [f"D{doc['n']} {doc['format'].lower()} {_size(doc['size_bytes'])} {verdict}" +
                 (f" {codes.error_code(doc.get('error_code'))}" if verdict in ("fail", "unsup") else "") + f" runs{len(view['runs'])}"]
        if latest:
            block.append(f"last {_short_time(latest.get('completed_at'))[:5]} {latest.get('parser')}{latest.get('parser_version')} "
                         f"ocr{1 if latest.get('ocr_enabled') else 0} {_seconds(latest.get('duration_ms'))}s"
                         + (f" {metrics['pages']}p" if metrics["pages"] else "") + f" c{metrics['chars']} t{metrics['tables']}")
        if metrics and metrics["warn"]:
            block.append("warn " + " ".join(code + (f"({extra})" if extra else "") for code, extra in metrics["warn"]))
        return "\n".join(lines + ["----- 타이핑용 -----", *block, "-----"])

    # ------------------------------------------------------------------ 도구: read / compare
    def read(self, id: str, page=None, sheet: str = "", find: str = "") -> str:  # noqa: A002
        doc = self.find_doc(id)
        runs = self.runs(doc["id"])
        latest = next((run for run in runs if run.get("is_latest")), runs[0] if runs else None)
        if not latest:
            raise ToolError("not-found", f"D{doc['n']}에는 성공한 파싱 결과가 없습니다(상태: {doc['status']}).", f"doc 에 D{doc['n']} 을 넣어 원인을 보세요.")
        detail = self.run_detail(doc["id"], latest["run_id"])
        lines = detail["markdown"].splitlines()
        page, sheet, find = as_int(page), as_text(sheet), as_text(find)
        stale = " (이전 성공본: 지금 재처리 중이거나 마지막 처리가 실패함)" if doc["status"] != "completed" else ""
        if page is not None or sheet:
            key, value = ("page", page) if page is not None else ("sheet", sheet)
            spans = [loc for loc in detail["locations"] if loc.get(key) == value or (key == "sheet" and str(loc.get("sheet", "")).casefold() == sheet.casefold())]
            if not spans:
                known = sorted({loc.get(key) for loc in detail["locations"] if loc.get(key) is not None}, key=str)
                listed = ", ".join(map(str, known[:20])) or "위치 정보 없음"
                raise ToolError("not-found", f"D{doc['n']}에서 {key}={value} 위치를 찾지 못했습니다. 있는 값: {listed}", "있는 값 중 하나로 다시 부르세요.")
            start, end = min(loc["start_line"] for loc in spans), max(loc["end_line"] for loc in spans)
            label = f"{key} {value}"
        elif find:
            wanted = find.casefold()
            hits = [i for i, line in enumerate(lines) if wanted in line.casefold()]
            if not hits:
                return f"결과: D{doc['n']} 본문에 '{find}'가 없습니다{stale}.\n다음: 다른 단어로 찾거나 page 로 쪽을 읽으세요."
            out = [f"결과: D{doc['n']} '{find}' {len(hits)}곳{stale}", "다음: 더 넓게 보려면 page 를 넣어 읽으세요."]
            used = 0
            for index in hits[:12]:
                chunk = f"[줄 {index + 1}] " + _clip(lines[index], 160)
                used += len(chunk)
                if used > READ_LIMIT:
                    break
                out.append(chunk)
            if len(out) - 2 < len(hits):
                out.append(f"… 나머지 {len(hits) - (len(out) - 2)}곳 생략. 더 좁은 단어로 찾거나 page 로 읽으세요.")
            return "\n".join(out)
        else:
            start, end, label = 1, min(len(lines), 60), "앞부분"
        body, used = [], 0
        for number in range(start, end + 1):
            text = lines[number - 1] if number - 1 < len(lines) else ""
            if used + len(text) > READ_LIMIT:
                body.append(f"… 잘림: 줄 {number}~{end} 생략(전체 {len(lines)}줄)")
                break
            body.append(text)
            used += len(text) + 1
        return "\n".join([f"결과: D{doc['n']} {label} (줄 {start}-{end} / 전체 {len(lines)}줄){stale}",
                          "다음: 내용을 요약할 때 경고(doc)와 함께 전하세요.", *body])

    def compare(self, id: str) -> str:  # noqa: A002
        doc = self.find_doc(id)
        runs = self.runs(doc["id"])
        if len(runs) < 2:
            raise ToolError("not-found", f"D{doc['n']}은 성공 실행이 {len(runs)}회라 비교할 이전 실행이 없습니다.",
                            f"parse 에 target=\"D{doc['n']}\" 을 넣어 다시 파싱한 뒤 비교하세요.")
        new_run, old_run = runs[0], runs[1]
        new, old = self.run_metrics(doc["id"], new_run), self.run_metrics(doc["id"], old_run)
        same = new["sha"] == old["sha"]
        lines = [f"결과: D{doc['n']} " + ("두 실행의 본문이 같습니다" if same else "본문이 바뀌었습니다") +
                 f" ({_short_time(old_run['completed_at'])} → {_short_time(new_run['completed_at'])})",
                 "다음: 사용자에게 아래 타이핑용 블록을 그대로 보여 주세요." if not same else "다음: 사용자에게 변화 없음으로 보고하세요."]
        for key, name in (("chars", "글자"), ("lines", "줄"), ("tables", "표 행"), ("numbers", "숫자"), ("broken", "깨진 글자"), ("pages", "쪽")):
            if old[key] != new[key] or key in ("chars", "tables"):
                lines.append(f"{name}: {old[key]} → {new[key]}")
        old_w, new_w = [c for c, _ in old["warn"]], [c for c, _ in new["warn"]]
        lines.append(f"경고: {','.join(old_w) or '없음'} → {','.join(new_w) or '없음'}")
        lines.append(f"파서: {old_run['parser']} {old_run['parser_version']} → {new_run['parser']} {new_run['parser_version']}, "
                     f"OCR {_on(old_run['ocr_enabled'])} → {_on(new_run['ocr_enabled'])}, 시간 {_seconds(old_run['duration_ms'])}s → {_seconds(new_run['duration_ms'])}s")
        if not same:
            old_md = self.run_detail(doc["id"], old_run["run_id"])["markdown"].splitlines()
            new_md = self.run_detail(doc["id"], new_run["run_id"])["markdown"].splitlines()
            shown = 0
            for line in difflib.unified_diff(old_md, new_md, lineterm="", n=0):
                if line.startswith(("---", "+++", "@@")):
                    continue
                lines.append("바뀐 줄 " + _clip(line, 120))
                shown += 1
                if shown >= 8:
                    break
        block = [f"D{doc['n']} diff " + ("same" if same else self._delta(old, new)) +
                 f" t{_seconds(old_run['duration_ms'])}>{_seconds(new_run['duration_ms'])}"]
        return "\n".join(lines + ["----- 타이핑용 -----", *block, "-----"])

    # ------------------------------------------------------------------ 도구: report
    def report(self, scope: str = "today") -> str:
        scope = (as_text(scope) or "today").lower()
        scope = {"오늘": "today", "마지막": "last", "전체": "all", "latest": "last", "recent": "last"}.get(scope, scope)
        if scope not in ("today", "last", "all"):
            raise ToolError("bad-arg", f"scope는 today, last, all 중 하나입니다(받은 값: {scope}).", "예: scope=\"today\"")
        batches = self.store.load("batches", {"items": []})["items"]
        if scope == "last":
            batch = self._latest_batch()
            if not batch:
                raise ToolError("not-found", "아직 parse 로 처리한 묶음이 없습니다.", "scope=\"today\" 또는 \"all\" 로 부르세요.")
            if not batch.get("finished"):
                return self._progress_text(batch, False)
            return self._digest_text(batch)
        docs = self.documents()
        if scope == "today":
            midnight = _now().replace(hour=0, minute=0, second=0, microsecond=0)
            ids = [doc["id"] for doc in docs if (_local(doc["updated_at"]) or midnight) >= midnight]
            since = midnight
            scoped = [batch for batch in batches if (_local(batch["started"]) or midnight) >= midnight]
        else:
            ids, since, scoped = [doc["id"] for doc in docs], None, batches
        if not ids:
            raise ToolError("not-found", "보고할 문서가 없습니다(오늘 처리한 문서 없음)." if scope == "today" else "등록된 문서가 없습니다.",
                            "scope=\"all\" 로 전체를 보거나 parse 로 먼저 파싱하세요.")
        skips = Counter()
        for batch in scoped:
            skips.update(batch.get("skips", {}))
            skips.update(item["note"] for item in batch["items"] if item["state"] == "error")
        with self.store.locked():
            counters = self.store.load("counters", {"report": 1})
            n = counters["report"]
            counters["report"] += 1
            self.store.save("counters", counters)
        block, summary = self.summary(f"R{n} {scope}", ids, since, skips)
        return self._wrap(f"R{n}", block, summary)

    # ------------------------------------------------------------------ 호출 기록과 반복 감지
    def call(self, name: str, args: dict) -> tuple[str, bool]:
        started = time.monotonic()
        key = name + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        repeat = bool(self._last_call and self._last_call[0] == key and started - self._last_call[1] < 120
                      and name not in ("wait", "status"))
        entry = {"ts": _iso(), "tool": name, "args": args, "kind": None, "repeat": repeat}
        try:
            text = self.dispatch(name, args)
            error = False
        except ToolError as exc:
            entry["kind"], error = exc.kind, True
            text = f"결과: 실패 ({exc.kind})\n원인: {exc}" + (f"\n다음: {exc.hint}" if exc.hint else "")
        except ServerDown as exc:
            entry["kind"], error = "server-down", True
            text = f"결과: 실패 (server-down)\n원인: {exc}\n다음: 사용자에게 콘솔을 켜 달라고 요청하세요. 같은 도구를 반복해 부르지 마세요."
        except ApiError as exc:
            entry["kind"], error = ("busy" if exc.status in (409, 503) else "api"), True
            text = f"결과: 실패 (서버 {exc.status})\n원인: {exc.detail}\n다음: 잠시 뒤 다시 시도하거나 사용자에게 알리세요."
        except Exception as exc:  # noqa: BLE001 — 모델에게는 짧게, 기록에는 자세히
            entry["kind"], error = "internal", True
            entry["trace"] = traceback.format_exc(limit=6)
            text = f"결과: 실패 (internal)\n원인: 작업 도구 내부 오류 {type(exc).__name__}\n다음: 사용자에게 알리세요. 같은 호출을 반복하지 마세요."
        if repeat:
            text = "주의: 방금과 같은 요청입니다. 결과가 같다면 다른 도구를 쓰거나 지금까지의 결과를 사용자에게 보고하세요.\n" + text
        entry["ms"] = round((time.monotonic() - started) * 1000)
        entry["result"] = text.split("\n", 1)[0][:120]
        self._last_call = (key, time.monotonic(), text)
        try:
            self.store.append_call(entry)
        except OSError:
            pass
        return text, error

    def dispatch(self, name: str, args: dict) -> str:
        spec = TOOL_ARGS.get(name)
        if spec is None:
            raise ToolError("bad-arg", f"'{name}' 도구는 없습니다. 있는 도구: {', '.join(TOOL_ARGS)}", "status 부터 부르세요.")
        args = {key: value for key, value in (args or {}).items() if value is not None}
        # 약한 모델이 자주 하는 변형: 인자 이름을 다르게 부르거나, 필수 인자를 다른 이름으로 넣는다.
        renamed = {}
        for key, value in args.items():
            canonical = ARG_ALIASES.get(key.lower(), key.lower())
            renamed.setdefault(canonical, value)
        unknown = [key for key in renamed if key not in spec]
        if unknown and len(spec) == 1 and len(renamed) == 1:
            renamed = {spec[0]: next(iter(renamed.values()))}
            unknown = []
        for key in unknown:
            renamed.pop(key)
        required = REQUIRED.get(name)
        if required and not as_text(renamed.get(required)):
            raise ToolError("bad-arg", f"{name} 에는 {required} 가 필요합니다.", EXAMPLES[name])
        if name in ("parse",):
            return self.parse(renamed["target"], as_bool(renamed.get("reparse")), as_bool(renamed.get("confirm")))
        return getattr(self, name)(**renamed)


TOOL_ARGS = {
    "status": [],
    "files": ["folder"],
    "parse": ["target", "reparse", "confirm"],
    "wait": [],
    "docs": ["state"],
    "doc": ["id"],
    "read": ["id", "page", "sheet", "find"],
    "compare": ["id"],
    "report": ["scope"],
}
REQUIRED = {"parse": "target", "doc": "id", "read": "id", "compare": "id"}
EXAMPLES = {
    "parse": "예: parse(target=\"C:/docs/보고서.pdf\") 또는 parse(target=\"*.pdf\") 또는 parse(target=\"D12\"). 경로의 \\ 대신 / 를 써도 됩니다.",
    "doc": "예: doc(id=\"D12\")",
    "read": "예: read(id=\"D12\", page=3)",
    "compare": "예: compare(id=\"D12\")",
}
ARG_ALIASES = {
    "path": "target", "file": "target", "files": "target", "filename": "target", "file_path": "target", "folder_path": "target",
    "doc_id": "id", "document": "id", "document_id": "id", "number": "id", "doc": "id", "name": "id",
    "page_number": "page", "pages": "page", "p": "page", "sheet_name": "sheet", "query": "find", "search": "find", "text": "find",
    "status": "state", "filter": "state", "force": "reparse", "again": "reparse", "yes": "confirm", "dir": "folder", "directory": "folder",
}
