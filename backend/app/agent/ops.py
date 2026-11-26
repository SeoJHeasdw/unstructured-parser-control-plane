"""작업 에이전트 도구의 실제 동작.

역할(2026-11-26, docs/AGENT_TOOLS.md): 에이전트는 파싱 버튼을 대신 누르는 것이 아니라 검수 보조다.
원본(파서와 별개로 읽은 글자)과 파싱 결과를 대조해 사람이 눈으로 봐야 할 곳을 좁히고, 검수 요청(V번호)으로 올린다.
사람은 콘솔의 원문 대조에서 그 위치를 보고 맞음·틀림을 남긴다. 수천 개 파일의 정답 텍스트를 사람이 만들 수 없기 때문이다.

설계 전제: 도구를 부르는 쪽은 도구 호출이 불안정할 수 있는 모델이다.
- 인자는 평평하게, 필수는 1개 이하. 'D12', 'd-12', '12', 파일 이름 등 흔한 변형을 받아 준다.
- 응답은 평문. 첫 줄은 결과 판정, 둘째 줄은 다음에 할 일.
- 원본·결과 읽기는 쪽·시트·줄을 바꿔 가며 필요한 만큼 부른다(호출 횟수 제한 없음, 한 번에 READ_LIMIT자).
- 경고가 하나라도 있으면 '성공'이라 하지 않는다. 실패 원인은 서버의 오류 코드로 확정해 돌려준다.
- 사실은 서버가 기록한다(runtime/agent/calls.jsonl, 검수 요청은 서버 DB). 모델의 요약은 근거로 쓰지 않는다.
"""
from collections import Counter
from datetime import datetime, timezone
import difflib
import fnmatch
from functools import lru_cache
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
import platform
import re
import secrets
import sys
import threading
import time
import traceback
import unicodedata
from urllib.parse import urlencode

from app.agent import codes
from app.agent.client import Api, ApiError, ServerDown
from app.filelock import try_lock, unlock
from app.folder_import import hidden, resolve_roots, root_candidates

PROJECT = Path(__file__).resolve().parents[3]
APP_DIR = Path(__file__).resolve().parents[1]
MAX_UPLOAD = 100 * 1024 * 1024
SCAN_LIMIT = 20000
# 한 번 읽기(read·source)에 돌려주는 글자 수. 이어 읽기는 line으로 한다. 사내 모델 문맥에 맞춰 DOCOPS_AGENT_READ_CHARS로 바꾼다.
READ_LIMIT = max(2000, min(60000, int(os.environ.get("DOCOPS_AGENT_READ_CHARS", "12000") or 12000)))
CALL_TEXT_LIMIT = 12000  # 호출 기록에 남기는 결과 글자 수(콘솔 '호출 기록'에서 펼쳐 본다)
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


def _matches_pattern(parts: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    @lru_cache(None)
    def match(i: int, j: int) -> bool:
        if j == len(pattern):
            return i == len(parts)
        if pattern[j] == "**":
            return match(i, j + 1) or (i < len(parts) and match(i + 1, j))
        return i < len(parts) and fnmatch.fnmatch(parts[i], pattern[j]) and match(i + 1, j + 1)
    return match(0, 0)


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
    word = str(value).strip().lower()
    if value is None or word in ("false", "no", "n", "0", "off", "아니오", "아니요", "거짓"):
        return False
    if word in _TRUE:
        return True
    raise ToolError("bad-arg", "reparse와 confirm은 true 또는 false를 넣으세요.")


def as_int(value) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ToolError("bad-arg", "쪽·줄 번호는 숫자여야 합니다.", "예: page=3, line=120")
    match = re.fullmatch(r"(?:p|page|slide|슬라이드|줄|행)?\s*(\d+)\s*(?:쪽|페이지|줄|행|번|번째|장)?", str(value).strip(), re.IGNORECASE)
    if not match or int(match[1]) < 1:
        raise ToolError("bad-arg", "1 이상의 정수를 넣으세요.")
    return int(match[1])


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
        self._stop = threading.Event()
        self._last_call: tuple[str, float] | None = None
        self._parsers: dict | None = None
        self.build = build_id()
        # 이 연결(MCP 프로세스·CLI 실행)의 표식. 호출 기록을 연결별로 묶어 본다.
        self.session = secrets.token_hex(4)
        self._touched: list[str] = []          # 이번 호출이 다룬 문서 ID(호출 기록에 남긴다)
        self._sources: dict[str, dict] = {}   # 원본 글자(문서 ID → 단위 목록·불러온 단위). 원본은 바뀌지 않는다.
        self._spots: dict[str, tuple[str, list[dict]]] = {}  # 자동 대조 결과(문서 ID → (실행 ID, 의심 지점))

    # ------------------------------------------------------------------ 기반
    @staticmethod
    def _roots(given: list[Path] | None) -> tuple[list[Path], list[str]]:
        # 화면의 '허용 폴더에서 가져오기'와 같은 규칙(app/folder_import.py)을 쓴다.
        if given is None:
            given, _ = root_candidates()
            # MCP starts in OpenCode/, the console starts in backend/. Resolve relative roots like the console.
            given = [APP_DIR.parent / path for path in given]
        return resolve_roots(given)

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
        doc = self._find_doc(ref)
        if doc["id"] not in self._touched:
            self._touched.append(doc["id"])
        return doc

    def _find_doc(self, ref) -> dict:
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
    def status(self, check: str = "") -> str:
        if check:
            if check != "connection":
                raise ToolError("bad-arg", "check에는 connection을 넣거나 생략하세요.")
            health = self.api.get("/api/health")
            if health.get("status") != "ok" or health.get("live_processing") != "available":
                raise ToolError("api", "문서 콘솔의 상태 응답을 확인하지 못했습니다.")
            return f"DOCOPS-CHECK-{secrets.token_hex(6)}"
        lines = []
        try:
            parsers = self.parsers(refresh=True)
            server = f"{self.api.base}" + (" (지정한 API 주소)" if self.api.fixed else f" — {self.api.note}" if self.api.note else " (같은 저장소 확인)")
        except ServerDown as exc:
            raise ToolError("server-down", str(exc), "사용자에게 콘솔을 켜 달라고 요청하세요.") from None
        docs = self.documents()
        counts = Counter(doc["status"] for doc in docs)
        problems = list(self.root_notes)
        if not parsers["docling_installed"]:
            problems.append("Docling 미설치: Office 구조 파싱 제한. PDF 글자 층은 pdf-text 경로로 확인하세요.")
        elif not parsers["pdf_model_directory"] or parsers.get("pdf_models_ready") is False:
            problems.append("PDF 모델 없음: PDF는 글자 층만 읽음(pdf-text, 표 구조 없음·스캔 쪽은 OCR 모델 필요)")
        if not parsers["ocr_models_found"]:
            problems.append("OCR 모델 미연결: 스캔 쪽·이미지·문서 속 그림의 글자를 읽지 않음(콘솔 '모델 연결'에서 OCR 모델 설정)")
        if not self.roots:
            problems.append("허용 폴더 없음: opencode.json의 DOCOPS_AGENT_ROOTS 설정 필요")
        lines.append("결과: " + ("준비됨" if not problems else f"주의 {len(problems)}건"))
        lines.append("다음: 파싱한 문서는 verify(id=\"D번호\")로 원본과 대조하고, 사람이 볼 곳은 flag로 올리세요. 새 파일은 parse 로 파싱합니다."
                     if self.roots else "다음: 사용자에게 DOCOPS_AGENT_ROOTS(파일을 읽을 폴더) 설정을 요청하세요.")
        lines.append(f"서버: {server}")
        lines += [f"주의: {problem}" for problem in problems]
        lines.append("허용 폴더: " + (" | ".join(str(root) for root in self.roots) or "없음"))
        lines.append("문서: 전체 {} (완료 {}, 실패 {}, 미지원 {}, 처리 중 {}, 미처리 {})".format(
            len(docs), counts["completed"], counts["failed"], counts["unsupported"], counts["processing"], counts["uploaded"]))
        batch = self._latest_batch()
        if batch:
            done = sum(1 for item in batch["items"] if item["state"] in ("done", "error"))
            lines.append(f"최근 묶음: B{batch['n']} {done}/{len(batch['items'])} " + ("끝남" if batch.get("finished") else "진행 중"))
        try:
            counts = self.api.get("/api/live/reviews", limit=1)["counts"]
            if counts:
                lines.append("검수 요청: " + ", ".join(f"{VERDICT_LABELS[key]} {counts[key]}" for key in VERDICT_LABELS if counts.get(key)))
        except (ApiError, KeyError, TypeError):
            pass  # 검수 요청 API가 없는 이전 서버
        lines.append(f"원본·결과 읽기: 한 번에 {READ_LIMIT:,}자, 쪽·시트·줄을 바꿔 가며 횟수 제한 없이 부를 수 있습니다.")
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

    def _allowed_file(self, path: Path, roots=None) -> bool:
        try:
            resolved = path.resolve()
            return any(path.is_relative_to(root) and resolved.is_relative_to(root) and
                       not any(hidden(part) for part in (*path.relative_to(root).parts, *resolved.relative_to(root).parts))
                       for root in (self.roots if roots is None else roots))
        except (OSError, RuntimeError):
            return False

    def _walk(self, folder: Path):
        count = 0
        for current, dirs, files in os.walk(folder):
            dirs[:] = sorted(d for d in dirs if not hidden(d) and self._allowed_file(Path(current) / d))
            for name in sorted(files):
                count += 1
                if count > SCAN_LIMIT:
                    raise ToolError("scan-limit", f"한 폴더에서 확인할 수 있는 파일은 {SCAN_LIMIT:,}개입니다.",
                                    "하위 폴더를 지정해 다시 부르세요.")
                path = Path(current) / name
                if self._inside(path.resolve()):
                    yield path

    def resolve(self, target: str) -> tuple[list[Path], bool]:
        """파일·폴더의 실제 경로를 먼저 검사하고 존재하지 않을 때만 패턴으로 해석한다."""
        text = self._clean_target(target)
        if not text:
            raise ToolError("bad-arg", "target이 비어 있습니다.", EXAMPLES["parse"])
        if not self.roots:
            raise ToolError("outside", "파일을 읽을 허용 폴더가 설정되지 않았습니다.")
        path = Path(text).expanduser()
        if ".." in path.parts:
            raise ToolError("outside", "상위 폴더(..)를 포함한 경로입니다.", "허용 폴더 안의 전체 경로를 넣으세요.")
        candidates = [path] if path.is_absolute() else [root / path for root in self.roots]
        if path.is_absolute() and not self._inside(path):
            raise ToolError("outside", "허용 폴더 밖의 경로입니다.")
        existing = [candidate for candidate in candidates if candidate.exists()]
        if len(existing) > 1:
            raise ToolError("bad-arg", "여러 허용 폴더에 같은 경로가 있습니다.", "전체 경로를 지정하세요.")
        if existing:
            candidate = existing[0]
            if not self._allowed_file(candidate):
                raise ToolError("outside", "허용 폴더 밖이거나 숨김 경로입니다.")
            resolved = candidate.resolve()
            if resolved.is_dir():
                return list(self._walk(resolved)), True
            if resolved.is_file():
                return [resolved], False
            raise ToolError("bad-arg", "일반 파일 또는 폴더 경로를 넣으세요.")
        wildcard = any(ch in text for ch in "*?[")
        matches = set()
        if wildcard:
            # 고정 디렉터리 아래만 걷는다. 절대 패턴으로 허용 범위 밖을 스캔하지 않는다.
            split = next(i for i, part in enumerate(path.parts) if any(ch in part for ch in "*?["))
            base = Path(*path.parts[:split])
            pattern = path.parts[split:] if len(path.parts) > 1 else ("**", *path.parts)
            bases = [base] if path.is_absolute() else [root / base for root in self.roots]
            for folder in bases:
                if not self._allowed_file(folder):
                    raise ToolError("outside", "허용 폴더 밖이거나 숨김 경로입니다.")
                for file in self._walk(folder):
                    rel = file.relative_to(folder)
                    if _matches_pattern(rel.parts, pattern):
                        matches.add(file)
        elif len(path.parts) == 1:
            wanted = _nfc(path.name).casefold()
            matches = {f for root in self.roots for f in self._walk(root) if _nfc(f.name).casefold() == wanted}
        if not matches:
            raise ToolError("not-found", f"'{text}'를 허용 폴더에서 찾지 못했습니다.", "files 로 확인하세요.")
        if not wildcard and len(matches) > 1:
            raise ToolError("bad-arg", "같은 이름의 파일이 여러 개입니다: " + " | ".join(str(p) for p in sorted(matches)[:5]),
                            "전체 경로를 지정하세요.")
        return sorted(matches), wildcard

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
            if not self._allowed_file(path) or not path.is_file():
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
    def files(self, folder: str = "", offset=0) -> str:
        if isinstance(offset, bool) or not re.fullmatch(r"\d{1,8}", str(offset)):
            raise ToolError("bad-arg", "offset은 0 이상의 정수입니다.")
        offset = int(offset)
        if folder:
            paths, _ = self.resolve(folder)
        else:
            if not self.roots:
                raise ToolError("outside", "허용 폴더가 설정되지 않았습니다.", "사용자에게 DOCOPS_AGENT_ROOTS 설정을 요청하세요.")
            paths = list(dict.fromkeys(p for root in self.roots for p in self._walk(root)))
        keep, skips = self.classify(paths, True)
        by_ext = Counter(path.suffix.lstrip(".").lower() or "none" for path in keep)
        registry = self.store.load("registry", {})
        aliases = {doc["id"]: doc["n"] for doc in self.documents()} if registry else {}
        lines = [f"결과: 처리 가능한 파일 {len(keep)}개" + (f", 건너뜀 {sum(skips.values())}개" if skips else ""),
                 "다음: parse 에 파일·폴더 경로나 '*.pdf' 같은 패턴을 넣어 파싱하세요.",
                 "형식: " + (" ".join(f"{ext}{count}" for ext, count in by_ext.most_common()) or "없음")]
        if skips:
            lines.append("건너뜀: " + " ".join(f"{code}{count}" for code, count in skips.most_common()))
        if len(self.roots) == 1:
            lines.append(f"폴더: {self.roots[0]} (아래 경로는 이 폴더 기준이고, parse 에 그대로 넣을 수 있습니다)")
        for path in keep[offset:offset + 30]:
            entry = registry.get(os.path.normcase(str(path)))
            mark = f"  [D{aliases[entry['doc']]}]" if entry and entry.get("doc") in aliases else ""
            lines.append(f"- {self._display(path)}  {_size(path.stat().st_size)}{mark}")
        if len(keep) > offset + 30:
            lines.append(f"다음 목록: 같은 folder에 offset={offset + 30}을 넣으세요.")
        elif offset and offset >= len(keep):
            lines.append("이 위치에 표시할 파일이 없습니다. offset=0부터 확인하세요.")
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
            items = [{"path": str(path.resolve()), "doc": None, "state": "file", "note": ""} for path in keep]
        if len(items) > self.confirm_over and not confirm:
            preview = [f"결과: 미리보기 — 대상 {len(items)}개라 아직 시작하지 않았습니다.",
                       "다음: 사용자에게 확인을 받은 뒤 같은 target에 confirm=true를 넣어 parse를 다시 부르세요."]
            formats = Counter(Path(item["path"]).suffix.lower().lstrip(".") for item in items if item["path"])
            if formats:
                preview.append("형식: " + " ".join(f"{ext}{count}" for ext, count in formats.most_common()))
            if skips:
                preview.append("건너뜀: " + " ".join(f"{key}{n}" for key, n in skips.most_common()))
            return "\n".join(preview)
        with self.store.locked():
            batches = self.store.load("batches", {"next": 1, "items": []})
            unfinished = [b for b in batches["items"] if not b.get("finished")]
            roots = list(map(str, self.roots))
            active = next((b for b in reversed(unfinished) if b["target"] == label and b["reparse"] == bool(reparse)
                           and b.get("roots") == roots), None)
            if active is None:
                batch = {"n": batches["next"], "target": label, "reparse": bool(reparse), "started": _iso(),
                         "finished": None, "roots": roots, "skips": dict(skips), "items": items, "error": ""}
                batches["next"] += 1
                recent = batches["items"][-49:]
                batches["items"] = [b for b in batches["items"][:-49] if not b.get("finished")] + recent + [batch]
                self.store.save("batches", batches)
            else:
                batch = active
        self._ensure_pump()
        return self._await(batch["n"], started=True)

    def wait(self, batch: str = "") -> str:
        batch = self._named_batch(batch) if batch else self._latest_batch()
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

    def _named_batch(self, value: str) -> dict:
        match = re.fullmatch(r"[bB]?(\d+)", as_text(value))
        if not match:
            raise ToolError("bad-arg", "묶음 번호는 B12 형식으로 넣으세요.")
        batch = self._batch(int(match.group(1)))
        if not batch:
            raise ToolError("not-found", f"B{int(match.group(1))} 묶음 기록이 없습니다.")
        return batch

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
            self._ensure_pump()
            time.sleep(0.5)

    def _progress_text(self, batch: dict, started: bool) -> str:
        states = Counter(item["state"] for item in batch["items"])
        done = states["done"] + states["error"]
        lines = [f"결과: 진행 중 B{batch['n']} — 전체 {len(batch['items'])}, 끝남 {done}, 처리 대기 {states['queued'] + states['pending']}, 등록 중 {states['file']}",
                 f"다음: wait(batch='B{batch['n']}')로 같은 묶음을 확인하세요."]
        if batch.get("error"):
            lines.append(f"주의: {batch['error']}")
        if started:
            lines.append("참고: CLI 창이나 OpenCode 연결이 닫히면 다음 wait 호출이 남은 등록을 이어갑니다.")
        return "\n".join(lines)

    def _ensure_pump(self) -> None:
        with self._pump_lock:
            if self._pump_thread and self._pump_thread.is_alive():
                return
            self._pump_thread = threading.Thread(target=self._pump, name="docops-agent-pump", daemon=True)
            self._pump_thread.start()

    def close(self) -> None:
        """CLI 종료나 MCP EOF에서 진행 중인 회차의 기록을 끝낸다."""
        self._stop.set()
        if self._pump_thread:
            self._pump_thread.join()

    def _pump(self) -> None:
        # 네트워크 요청을 하는 작업자는 runtime마다 한 명이다. 다른 연결도 상태 파일은 읽을 수 있다.
        while True:
            if not any(not b.get("finished") for b in self.store.load("batches", {"items": []})["items"]):
                return
            with (self.store.dir / "pump.lock").open("a+b") as owner:
                try:
                    try_lock(owner)
                except OSError:
                    delay = 0.5
                else:
                    try:
                        delay = self._pump_once()
                    except (ServerDown, ApiError, OSError, ToolError) as exc:
                        self._mark_error(str(exc))
                        delay = 3
                    finally:
                        unlock(owner)
            if self._stop.wait(delay):
                return

    def _pump_once(self) -> float:
        # 회차 도중 프로세스가 종료되면 POST 완료 여부가 불명확하다. 기록을 복구하고
        # 해당 요청은 자동 재전송하지 않는다. queued만 다음 회차의 새 문서 상태로 판정한다.
        journal = self.store.dir / "pump.jsonl"
        with self.store.locked():
            batches = self.store.load("batches", {"items": []})
            active = {b["n"]: b for b in batches["items"] if not b.get("finished")}
            if journal.exists():
                with journal.open(encoding="utf-8") as handle:
                    for row in handle:
                        if not row.endswith("\n"):
                            break
                        number, index, item = json.loads(row)
                        if number in active:
                            active[number]["items"][index] = item
                self.store.save("batches", batches)
                journal.unlink()
        if not active:
            return 1
        docs = {doc["id"]: doc for doc in self.documents()}
        uploads, full = 0, False
        with journal.open("a", encoding="utf-8") as handle:
            def record(number, index, item):
                handle.write(json.dumps([number, index, item], ensure_ascii=True) + "\n")
                handle.flush()

            for number, batch in active.items():
                batch["error"] = ""
                for index, item in enumerate(batch["items"]):
                    state = item["state"]
                    if state == "queued":
                        doc = docs.get(item["doc"])
                        if doc is None:
                            item.update(state="error", note="missing")
                        elif doc["status"] != "processing":
                            item["state"] = "done"
                        continue
                    if state == "file" and uploads < 20:
                        record(number, index, {**item, "state": "error", "note": "upload-unknown"})
                        self._register_item(item, batch, docs)
                        uploads += 1
                        record(number, index, item)
                    if item["state"] == "pending" and not full:
                        record(number, index, {**item, "state": "error", "note": "process-unknown"})
                        full = self._enqueue_item(item)
                        if item["state"] == "queued" and item["doc"] in docs:
                            docs[item["doc"]]["status"] = "processing"
                        record(number, index, item)
                if all(i["state"] in ("done", "error") for i in batch["items"]):
                    batch["finished"] = _iso()
        with self.store.locked():
            batches = self.store.load("batches", {"items": []})
            batches["items"] = [active.get(b["n"], b) for b in batches["items"]]
            self.store.save("batches", batches)
            journal.unlink()
        return 0.2 if uploads else 1.0

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
        roots = [Path(root) for root in batch["roots"]] if "roots" in batch else self.roots
        if not self._allowed_file(path, roots):
            item.update(state="error", note="outside")
            return
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

    def _enqueue_item(self, item: dict) -> bool:
        """처리 요청. 대기열이 가득 차면 True(이번 회차에는 더 넣지 않는다)."""
        try:
            self.api.post(f"/api/live/documents/{item['doc']}/process")
        except ServerDown:
            item["state"], item["note"] = "error", "process-unknown"
            return False
        except ApiError as exc:
            if exc.status == 409:
                item["state"] = "queued"
                return False
            if exc.status == 503:
                return True
            item["state"], item["note"] = "error", "missing" if exc.status == 404 else f"process-{exc.status}"
            return False
        item["state"] = "queued"
        return False

    # ------------------------------------------------------------------ 묶음 요약
    def _digest_text(self, batch: dict, again: bool = False) -> str:
        ids = [item["doc"] for item in batch["items"] if item.get("doc") and item["state"] != "error"]
        errors = Counter(item["note"] for item in batch["items"] if item["state"] == "error")
        for doc_id in ids:
            if doc_id not in self._touched:
                self._touched.append(doc_id)
        text = self._batch_summary(f"B{batch['n']}", ids, Counter(batch.get("skips", {})), errors,
                                   reused=sum(1 for i in batch["items"] if i["note"] == "reuse"))
        return ("참고: 이미 끝난 묶음입니다. 지금 문서 상태로 다시 요약했습니다.\n" if again else "") + text

    def _batch_summary(self, label: str, ids: list[str], skips: Counter, errors: Counter, reused: int = 0) -> str:
        docs = {doc["id"]: doc for doc in self.documents()}
        views = [self.doc_view(docs[doc_id]) for doc_id in dict.fromkeys(ids) if doc_id in docs]
        verdicts = Counter(view["verdict"] for view in views)
        bad = verdicts["fail"] + verdicts["unsup"]
        parts = [f"{VERDICT_WORDS[key]} {verdicts[key]}" for key in codes.VERDICTS if verdicts[key]]
        head = f"결과: {label} 끝 — {len(views)}건" + (f": {', '.join(parts)}" if parts else "")
        if reused:
            head += f" (이미 처리해 다시 하지 않은 문서 {reused}건 포함)"
        if verdicts["run"] or verdicts["new"]:
            head = f"결과: {label} — 아직 끝나지 않은 문서 {verdicts['run'] + verdicts['new']}건 포함(전체 {len(views)}건)"
        if errors:
            head += f" / 등록·처리 요청 오류 {sum(errors.values())}건"
        lines = [head, "다음: 문서마다 verify(id=\"D번호\")로 원본과 대조하고, 의심 지점은 source·read로 같은 위치를 읽어 확인한 뒤 "
                       "사람이 눈으로 볼 곳을 flag로 올리세요. 경고·실패 문서부터 보세요."]
        if not bad and not verdicts["warn"] and views:
            lines.append("참고: 경고가 없어도 파싱 성공이 품질 보증은 아닙니다. verify로 원본과 대조해야 압니다.")
        by_format: dict[str, list[dict]] = {}
        for view in views:
            by_format.setdefault(view["doc"]["format"].lower() or "none", []).append(view)
        if by_format:
            pieces = []
            for fmt, group in sorted(by_format.items(), key=lambda pair: (-len(pair[1]), pair[0])):
                counts = Counter(view["verdict"] for view in group)
                timed = [view["latest"]["duration_ms"] for view in group if view["verdict"] in ("ok", "warn")
                         and view["latest"] and view["latest"].get("duration_ms") is not None]
                detail = ", ".join(f"{VERDICT_WORDS[key]} {counts[key]}" for key in codes.VERDICTS if counts[key])
                if timed:
                    detail += f", 평균 {_seconds(round(sum(timed) / len(timed)))}초"
                pieces.append(f"{fmt} {len(group)}건({detail})")
            lines.append("형식: " + " · ".join(pieces))
        fails: dict[str, list[int]] = {}
        warns: dict[str, list[int]] = {}
        for view in views:
            if view["verdict"] in ("fail", "unsup"):
                fails.setdefault(codes.error_code(view["doc"].get("error_code")), []).append(view["doc"]["n"])
            for code in dict.fromkeys(code for code, _ in view["warn"]):
                warns.setdefault(code, []).append(view["doc"]["n"])
        for title, grouped in (("실패", fails), ("경고", warns)):
            for code, numbers in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0])):
                lines.append(f"{title}: {code} {len(numbers)}건 {_refs(numbers)} — {codes.MEANINGS.get(code, '코드 설명 없음: doc 으로 원문 경고를 보세요')}")
        empties = [view["doc"]["n"] for view in views if view["verdict"] == "empty"]
        if empties:
            lines.append(f"글자 없음: {len(empties)}건 {_refs(empties)} — {codes.MEANINGS['empty']}")
        if skips:
            lines.append("건너뜀: " + ", ".join(f"{SKIP_WORDS.get(code, code) if not code.startswith('ext-') else '처리 경로 없는 확장자 ' + code[4:]} {count}"
                                             for code, count in skips.most_common()))
        if errors:
            lines.append("요청 오류: " + ", ".join(f"{code} {n}" for code, n in errors.most_common())
                         + " (등록·처리 응답이 끊겼거나 거절됨. 문서함과 실행 이력에서 반영 여부를 확인)")
        diff = self._diff_line(views)
        if diff:
            lines.append(diff)
        order = {"fail": 0, "unsup": 1, "warn": 2, "empty": 3, "run": 4, "new": 5, "ok": 6}
        listed = sorted(views, key=lambda view: (order.get(view["verdict"], 9), view["doc"]["n"]))
        if listed:
            lines.append(f"문서({len(listed)}건, 확인할 것부터):")
        for view in listed[:50]:
            doc = view["doc"]
            found = [codes.error_code(doc.get("error_code"))] if view["verdict"] in ("fail", "unsup") else list(dict.fromkeys(c for c, _ in view["warn"]))
            lines.append(f"D{doc['n']} {doc['format'].lower()} {VERDICT_WORDS.get(view['verdict'], view['verdict'])}"
                         + (f"({','.join(found)})" if found else "") + f" · {_clip(doc['name'], 50)}")
        if len(listed) > 50:
            lines.append(f"… 외 {len(listed) - 50}건은 docs 로 보세요.")
        return "\n".join(lines)

    def _diff_line(self, views: list[dict]) -> str:
        compared, changes = 0, []
        for view in views:
            if not (view["previous"] and view["metrics"] and view["verdict"] in ("ok", "warn")):
                continue
            old = self.run_metrics(view["doc"]["id"], view["previous"])
            new = view["metrics"]
            compared += 1
            if old["sha"] == new["sha"] and old["warn"] == new["warn"]:
                continue
            changes.append((self._delta_score(old, new), view["doc"]["n"], self._delta(old, new)))
        if not compared:
            return ""
        changes.sort(reverse=True)
        line = f"이전 실행과 비교: {compared}건 중 같음 {compared - len(changes)}, 바뀜 {len(changes)}"
        if changes:
            line += " (" + " / ".join(f"D{n} {delta}" for _, n, delta in changes[:REF_LIMIT]) + ")"
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
            parts.append(f"글자{pct:+.0f}%" if abs(pct) >= 1 else f"글자{new['chars'] - old['chars']:+d}")
        for key, short in (("tables", "표 행"), ("numbers", "숫자"), ("broken", "깨진 글자")):
            if new[key] != old[key]:
                parts.append(f"{short}{new[key] - old[key]:+d}")
        old_warn, new_warn = {c for c, _ in old["warn"]}, {c for c, _ in new["warn"]}
        if old_warn != new_warn:
            parts.append("경고" + "".join(f" -{c}" for c in sorted(old_warn - new_warn)) + "".join(f" +{c}" for c in sorted(new_warn - old_warn)))
        return " ".join(parts) or "서식만 다름"

    # ------------------------------------------------------------------ 콘솔 링크
    def link(self, doc: dict, **where) -> str:
        """콘솔의 원문 대조 화면 주소. 사람이 눌러 그 위치(쪽·시트·셀·결과 줄)를 바로 연다."""
        try:
            base = self.api.base or self.api.discover()
        except ServerDown:
            base = "http://127.0.0.1:8000"
        query = {"view": "live", "doc": doc["id"], "review": "source"}
        query.update({key: str(value) for key, value in where.items() if value not in (None, "")})
        return f"{base}/?{urlencode(query)}"

    # ------------------------------------------------------------------ 도구: docs / doc
    def docs(self, state: str = "all", before: str = "") -> str:
        state = (as_text(state) or "all").lower()
        aliases = {"성공": "ok", "경고": "warn", "실패": "fail", "전체": "all", "failed": "fail", "completed": "ok", "warning": "warn"}
        state = aliases.get(state, state)
        if state not in ("all", *codes.VERDICTS):
            raise ToolError("bad-arg", f"state는 all, {', '.join(codes.VERDICTS)} 중 하나입니다(받은 값: {state}).", "예: state=\"fail\"")
        docs = list(reversed(self.documents()))
        if before:
            cursor = _DOC_REF.fullmatch(as_text(before))
            if not cursor:
                raise ToolError("bad-arg", "before에는 마지막으로 본 문서 번호를 넣으세요. 예: D41")
            docs = [d for d in docs if d["n"] < int(cursor[1])]
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
                 "다음: 문서를 확인하려면 verify 에 D번호를 넣어 원본과 대조하세요. 상태·경고 원문은 doc 으로 봅니다."]
        seen: dict[str, None] = {}
        for view in views:
            doc = view["doc"]
            found = [codes.error_code(doc.get("error_code"))] if view["verdict"] in ("fail", "unsup") else list(dict.fromkeys(c for c, _ in view["warn"]))
            seen.update(dict.fromkeys(found))
            code = ",".join(found)
            lines.append(f"D{doc['n']} {doc['format'].lower()} {view['verdict']}{(' ' + code) if code else ''}  {_size(doc['size_bytes'])}  {_clip(doc['name'], 40)}")
        if len(views) == 40 and docs[-1]["n"] < views[-1]["doc"]["n"]:
            lines.append(f"다음 목록: 같은 state에 before=D{views[-1]['doc']['n']}을 넣으세요.")
        lines += [f"설명: {code} — {codes.MEANINGS.get(code, '코드표 참고')}" for code in seen]
        return "\n".join(lines)

    def doc(self, id: str) -> str:  # noqa: A002 — 도구 인자 이름
        doc = self.find_doc(id)
        view = self.doc_view(doc)
        latest, metrics = view["latest"], view["metrics"]
        verdict = view["verdict"]
        title = {"ok": "경고 없음", "warn": "경고 있음", "empty": "글자 없음", "fail": "실패", "unsup": "미지원 형식", "run": "처리 중", "new": "아직 파싱 안 함"}[verdict]
        lines = [f"결과: D{doc['n']} {title}" + (f" ({codes.error_code(doc.get('error_code'))})" if verdict in ("fail", "unsup") else ""),
                 {"empty": "다음: 글자 없는 사진인지 사람이 원본을 봐야 합니다. flag 로 원문 대조를 요청하세요.",
                  "fail": "다음: 원인을 사용자에게 그대로 전하세요. 고칠 수 있는 원인이면 사용자가 파일을 바꾼 뒤 parse 로 다시 시도합니다.",
                  "unsup": "다음: 처리 경로가 없는 형식입니다. 사용자에게 알리세요.",
                  "warn": f"다음: verify(id=\"D{doc['n']}\")로 원본과 대조해 경고 위치를 확인하세요.",
                  "run": "다음: wait 로 끝날 때까지 기다리세요.",
                  "new": f"다음: parse 에 target=\"D{doc['n']}\" 을 넣어 파싱하세요."}.get(verdict, f"다음: verify(id=\"D{doc['n']}\")로 원본과 대조하세요."),
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
                lines.append(f"경고 {code}{(' ' + extra) if extra else ''}: {_clip(text, 160)}")
        history = self.api.get(f"/api/live/documents/{doc['id']}/history")["history"][-3:]
        for entry in history:
            lines.append(f"이력: {_short_time(entry['created_at'])} {entry['status']} {_clip(entry['message'], 60)}")
        if latest:
            lines.append(f"원문 대조: {self.link(doc)}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ 도구: read(파싱 결과) / source(원본)
    def read(self, id: str, page=None, sheet: str = "", find: str = "", line=None) -> str:  # noqa: A002
        doc = self.find_doc(id)
        runs = self.runs(doc["id"])
        latest = next((run for run in runs if run.get("is_latest")), runs[0] if runs else None)
        if not latest:
            raise ToolError("not-found", f"D{doc['n']}에는 성공한 파싱 결과가 없습니다(상태: {doc['status']}).", f"doc 에 D{doc['n']} 을 넣어 원인을 보세요.")
        detail = self.run_detail(doc["id"], latest["run_id"])
        lines = detail["markdown"].splitlines()
        page, sheet, find, start = as_int(page), as_text(sheet), as_text(find), as_int(line)
        if sum(bool(key) for key in (page, sheet, find)) > 1:
            raise ToolError("bad-arg", "page, sheet, find 중 하나만 선택하세요.")
        stale = " (이전 성공본: 지금 재처리 중이거나 마지막 처리가 실패함)" if doc["status"] != "completed" else ""
        if find:
            pattern = re.compile(re.escape(find), re.IGNORECASE)
            hits = [i for i, text in enumerate(lines) if pattern.search(text)]
            if not hits:
                return f"결과: D{doc['n']} 결과 본문에 '{find}'가 없습니다{stale}.\n다음: 원본에 있는지 source(id=\"D{doc['n']}\", find=\"{find}\")로 확인하세요. 원본에만 있으면 파서가 놓친 것입니다."
            out = [f"결과: D{doc['n']} 결과 본문에서 '{find}' {len(hits)}곳{stale}",
                   f"다음: 같은 글을 원본에서 source(id=\"D{doc['n']}\", find=\"{find}\")로 찾아 비교하세요. 줄 주변은 line=줄번호로 읽습니다."]
            used = 0
            for index in hits:
                text = lines[index]
                match = pattern.search(text)
                begin = max(0, match.start() - 80)
                chunk = f"{index + 1}: " + ("…" if begin else "") + _clip(text[begin:], 400)
                used += len(chunk)
                if used > READ_LIMIT:
                    out.append(f"… 나머지 {len(hits) - (len(out) - 2)}곳 생략. 더 좁은 글자로 찾으세요.")
                    break
                out.append(chunk)
            return "\n".join(out)
        if page is not None or sheet:
            key, value = ("page", page) if page is not None else ("sheet", sheet)
            spans = [loc for loc in detail["locations"] if loc.get(key) == value or (key == "sheet" and str(loc.get("sheet", "")).casefold() == sheet.casefold())]
            if not spans:
                known = sorted({loc.get(key) for loc in detail["locations"] if loc.get(key) is not None}, key=str)
                listed = ", ".join(map(str, known[:30])) or "위치 정보 없음(이 결과는 쪽·시트 위치가 기록되지 않았습니다. line 으로 줄 번호를 지정해 읽으세요)"
                raise ToolError("not-found", f"D{doc['n']} 결과에서 {key}={value} 위치를 찾지 못했습니다. 있는 값: {listed}", "있는 값 중 하나로 다시 부르세요.")
            ranges = []
            for loc in sorted(spans, key=lambda loc: loc["start_line"]):
                first, last = max(1, loc["start_line"]), min(len(lines), loc["end_line"])
                if first > last:
                    continue
                if ranges and first <= ranges[-1][1] + 1:
                    ranges[-1] = (ranges[-1][0], max(last, ranges[-1][1]))
                else:
                    ranges.append((first, last))
            label = ("슬라이드" if doc["format"] in ("PPTX", "PPTM") else "쪽") + f" {value}" if key == "page" else f"시트 {value}"
            numbers_ = [n for first, last in ranges for n in range(first, last + 1)]
            if start:
                numbers_ = [n for n in numbers_ if n >= start]
        else:
            first = start or 1
            numbers_ = list(range(first, len(lines) + 1))
            label = "앞부분" if first == 1 else f"줄 {first}부터"
        body, used, last_shown = [], 0, None
        for number in numbers_:
            text = lines[number - 1]
            if not text.strip():
                last_shown = number
                continue  # 빈 줄은 줄 번호만 건너뛴다(글자 예산을 아낀다)
            row = f"{number}: {text}"
            if used + len(row) + 1 > READ_LIMIT and body:
                break
            body.append(row if len(row) <= READ_LIMIT else row[:READ_LIMIT] + "…")
            used += len(row) + 1
            last_shown = number
        remaining = [n for n in numbers_ if last_shown is not None and n > last_shown]
        tail = []
        if remaining:
            tail.append(f"… 이어 읽기: read(id=\"D{doc['n']}\"" + (f", page={page}" if page is not None else f", sheet=\"{sheet}\"" if sheet else "")
                        + f", line={remaining[0]}) — 남은 줄 {len(remaining):,}")
        where = f"줄 {numbers_[0]}-{last_shown}" if numbers_ and last_shown else "표시할 줄 없음"
        return "\n".join([f"결과: D{doc['n']} 파싱 결과 {label} · {where} (전체 {len(lines)}줄){stale}",
                          "다음: 같은 위치의 원본은 source 로 읽어 비교하세요(쪽은 page, 시트는 sheet). 줄 앞 숫자는 결과 줄 번호입니다(flag의 line).",
                          *body, *tail])

    def _source_index(self, doc: dict) -> dict:
        cached = self._sources.get(doc["id"])
        if cached is None:
            try:
                index = self.api.get(f"/api/live/documents/{doc['id']}/source-text")
            except ApiError as exc:
                if exc.status == 409:
                    raise ToolError("no-source", exc.detail, f"원본 글자를 직접 읽을 수 없으면 flag(id=\"D{doc['n']}\", note=\"…\")로 사람에게 원문 대조를 요청하세요.") from None
                raise
            cached = {"index": index, "units": {}}
            self._sources[doc["id"]] = cached
            while len(self._sources) > 4:
                self._sources.pop(next(iter(self._sources)))
        return cached

    def _source_unit(self, doc: dict, key: str) -> dict:
        cached = self._source_index(doc)
        if key not in cached["units"]:
            cached["units"][key] = self.api.get(f"/api/live/documents/{doc['id']}/source-text", unit=key)["unit"]
        return cached["units"][key]

    def source(self, id: str, page=None, sheet: str = "", line=None, find: str = "") -> str:  # noqa: A002
        doc = self.find_doc(id)
        page, sheet, find, start = as_int(page), as_text(sheet), as_text(find), as_int(line)
        if sum(bool(key) for key in (page, sheet, find)) > 1:
            raise ToolError("bad-arg", "page, sheet, find 중 하나만 선택하세요.")
        index = self._source_index(doc)["index"]
        units = index["units"]
        method = index.get("method", "원본")
        if find:
            hits = self.api.get(f"/api/live/documents/{doc['id']}/source-text", find=find)["hits"]
            if not hits:
                return f"결과: D{doc['n']} 원본에 '{find}'가 없습니다 — {method}\n다음: 결과에만 있다면 파서가 만든 글(OCR·보충 등)인지 read 로 확인하세요."
            out = [f"결과: D{doc['n']} 원본에서 '{find}' {len(hits)}곳" + (" (앞 50곳)" if len(hits) >= 50 else "") + f" — {method}",
                   "다음: 그 위치의 파싱 결과는 read 에 같은 page·sheet를 넣어 읽어 비교하세요."]
            used = 0
            for hit in hits:
                row = f"[{hit['ref']}] {_clip(hit['text'], 400)}"
                used += len(row)
                if used > READ_LIMIT:
                    out.append("… 나머지는 더 좁은 글자로 찾으세요.")
                    break
                out.append(row)
            return "\n".join(out)
        if page is not None:
            unit = next((u for u in units if u.get("page") == page), None)
            if unit is None:
                pages = [u["page"] for u in units if u.get("page")]
                known = f"있는 범위: {min(pages)}~{max(pages)}" if pages else "이 형식에는 쪽 구분이 없습니다(sheet 또는 line으로 읽으세요)"
                raise ToolError("not-found", f"D{doc['n']} 원본에 {page}쪽이 없습니다. {known}", "있는 번호로 다시 부르세요.")
        elif sheet:
            unit = next((u for u in units if (u.get("sheet") or "").casefold() == sheet.casefold()), None)
            if unit is None:
                names = ", ".join(u["sheet"] for u in units if u.get("sheet")) or "시트 없음"
                raise ToolError("not-found", f"D{doc['n']} 원본에 '{sheet}' 시트가 없습니다. 있는 시트: {names}", "있는 이름으로 다시 부르세요.")
        else:
            unit = next((u for u in units if u.get("lines")), units[0] if units else None)
            if unit is None:
                return f"결과: D{doc['n']} 원본에 읽을 글자가 없습니다 — {method}\n다음: flag 로 사람에게 원문 대조를 요청하세요."
        data = self._source_unit(doc, unit["key"])
        rows = data["lines"]
        heading = [f"결과: D{doc['n']} 원본 {data['label']} — {method}"]
        if data.get("note"):
            heading.append(f"주의: {data['note']}")
        if data["kind"] == "scan":
            pair = f", page={data['page']}" if data.get("page") else ""
            return "\n".join(heading + [f"다음: 원본 글자 층이 없어 직접 대조할 수 없습니다. 결과(read(id=\"D{doc['n']}\"{pair}))는 OCR이 읽은 것이므로 "
                                        f"flag(id=\"D{doc['n']}\"{pair}, note=\"…\")로 사람에게 원본 그림과 대조를 요청하세요."])
        if not rows:
            return "\n".join(heading + ["다음: 이 단위에는 글자가 없습니다. 다른 쪽·시트를 보세요."])
        first = 1
        if start:
            if data.get("sheet"):
                first = next((i for i, row in enumerate(rows, 1) if (row.get("row") or 0) >= start), len(rows) + 1)
            else:
                first = start
        prefixes = (data["label"] + " · ", data["label"] + " ")
        body, used, last = [], 0, first - 1
        for position in range(first, len(rows) + 1):
            row = rows[position - 1]
            ref = next((row["ref"][len(prefix):] for prefix in prefixes if row["ref"].startswith(prefix)), row["ref"])
            text = f"{ref}: {row['text']}"
            if used + len(text) + 1 > READ_LIMIT and body:
                break
            body.append(text if len(text) <= READ_LIMIT else text[:READ_LIMIT] + "…")
            used += len(text) + 1
            last = position
        where = "page=" + str(data["page"]) if data.get("page") else f"sheet=\"{data['sheet']}\"" if data.get("sheet") else ""
        pair = f"read(id=\"D{doc['n']}\"" + (f", {where}" if where else "") + ")"
        heading[0] += f" · 줄 {first}-{last}/{len(rows)}"
        heading.insert(1, f"다음: 같은 위치의 파싱 결과는 {pair}로 읽어 비교하세요. 원본에 있는데 결과에 없거나 다른 글이면 flag로 올립니다.")
        tail = []
        if last < len(rows):
            nxt = rows[last].get("row") if data.get("sheet") else last + 1
            tail.append(f"… 이어 읽기: source(id=\"D{doc['n']}\"" + (f", {where}" if where else "") + f", line={nxt}) — 남은 줄 {len(rows) - last:,}")
        others = [u for u in units if u["key"] != data["key"] and u.get("lines")]
        if others and not start:
            tail.append("다른 단위: " + ", ".join(f"{u['label']}" for u in others[:12]) + (f" 외 {len(others) - 12}개" if len(others) > 12 else ""))
        return "\n".join(heading + body + tail)

    # ------------------------------------------------------------------ 도구: verify(자동 대조)
    def verify(self, id: str, page=None, sheet: str = "") -> str:  # noqa: A002
        doc = self.find_doc(id)
        page, sheet = as_int(page), as_text(sheet)
        try:
            data = self.api.get(f"/api/live/documents/{doc['id']}/verify")
        except ApiError as exc:
            if exc.status == 409:
                raise ToolError("no-source", exc.detail, f"doc(id=\"D{doc['n']}\")로 상태를 보거나, 원본을 직접 볼 수 없으면 flag 로 사람에게 확인을 요청하세요.") from None
            raise
        spots = data["spots"]
        self._spots[doc["id"]] = (data["run_id"], spots)
        flagged = {}
        try:
            for review in self.api.get("/api/live/reviews", doc=doc["id"], limit=1000)["reviews"]:
                if review.get("spot") and review.get("run_id") == data["run_id"]:
                    flagged[review["spot"]] = review
        except (ApiError, KeyError, TypeError):
            pass
        units = data["units"]
        if page is not None or sheet:
            units = [u for u in units if (page is not None and u.get("page") == page) or (sheet and (u.get("sheet") or "").casefold() == sheet.casefold())]
            if not units:
                raise ToolError("not-found", f"D{doc['n']}에 그 위치가 없습니다.", "verify(id=…)를 위치 없이 불러 단위 목록을 보세요.")
            keys = {u["key"] for u in units}
            spots = [spot for spot in spots if spot["unit"] in keys]
        summary = data["summary"]
        counts = Counter(spot["severity"] for spot in spots)
        coverage = summary.get("coverage")
        stale = "" if data.get("is_latest", True) and data.get("document_status") == "completed" else " — 이전 성공본(is_stale) 기준"
        head = (f"결과: D{doc['n']} 원본 대조 — 의심 {len(spots)}곳" + (f"(높음 {counts['high']}, 보통 {counts['medium']}, 낮음 {counts['low']})" if spots else "")
                + (f", 원본 글자의 {coverage:.0%}를 결과에서 찾음" if coverage is not None else "") + stale)
        lines = [head,
                 (f"다음: 의심 지점마다 source 와 read 로 같은 위치를 읽어 직접 비교하세요. 사람이 눈으로 봐야 할 곳은 flag(id=\"D{doc['n']}\", spot=\"S번호\", note=\"무엇이 다른지\")로 올립니다."
                  if spots else f"다음: 자동 대조로는 차이가 없습니다. 표 구조·읽는 순서·그림 속 글자는 자동 대조가 보지 않으니, 중요한 문서는 flag 로 사람에게 원문 대조를 요청하세요."),
                 f"기준: {data['method']} · 파서 {data.get('parser') or '-'}"]
        for note in data.get("notes", [])[:6]:
            lines.append(f"참고: {note}")
        if len(units) > 1:
            shown = []
            for unit in units:
                if unit["state"] == "scan":
                    shown.append(f"{unit['label']} 스캔(글자 층 없음)")
                elif unit["state"] in ("hidden", "empty", "garbled"):
                    shown.append(f"{unit['label']} {UNIT_STATES[unit['state']]}")
                elif unit["coverage"] is not None and (unit["coverage"] < 0.995 or unit["spots"] or len(units) <= 12):
                    shown.append(f"{unit['label']} {unit['coverage']:.0%}" + (f" 의심{unit['spots']}" if unit["spots"] else ""))
            if shown:
                lines.append("단위: " + " · ".join(shown[:40]) + (f" 외 {len(shown) - 40}개" if len(shown) > 40 else ""))
        rank = {"high": 0, "medium": 1, "low": 2}
        ordered = sorted(spots, key=lambda spot: (rank[spot["severity"]], int(spot["key"][1:])))
        if ordered:
            lines.append(f"의심 지점({'높음 먼저' if len(ordered) > 1 else '1곳'}" + (f", 앞 20곳" if len(ordered) > 20 else "") + "):")
        for spot in ordered[:20]:
            where = spot["ref"] or spot["label"]
            result_at = f" → 결과 줄 {spot['line']}" + (f"-{spot['line_end']}" if spot.get("line_end") and spot["line_end"] != spot["line"] else "") if spot.get("line") else ""
            mark = flagged.get(spot["key"])
            tag = f" [이미 V{mark['id']} {VERDICT_LABELS.get(mark['status'], mark['status'])}]" if mark else ""
            lines.append(f"{spot['key']} [{SEVERITY_WORDS[spot['severity']]}] {where}{result_at}: {_clip(spot['message'], 220)}{tag}")
            if spot.get("source") and spot.get("source_hit"):
                lines.append(f"    원본: {_clip(spot['source'], 200)}")
            if spot.get("result"):
                label = "결과(있어야 할 자리 앞 줄)" if spot.get("result_role") == "before" else "결과"
                lines.append(f"    {label}: {_clip(spot['result'], 200)}")
        if len(ordered) > 20:
            lines.append(f"… 나머지 {len(ordered) - 20}곳은 page·sheet로 단위를 지정해 보세요.")
        lines.append(f"원문 대조: {self.link(doc)}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ 도구: flag(검수 요청) / verdicts(사람 판정)
    def flag(self, id: str, spot: str = "", page=None, sheet: str = "", cell: str = "", line=None,  # noqa: A002
             note: str = "", source_text: str = "", result_text: str = "") -> str:
        doc = self.find_doc(id)
        spot, note = as_text(spot).upper(), as_text(note)
        page, line = as_int(page), as_int(line)
        payload: dict = {"document_id": doc["id"], "origin": "agent"}
        if spot:
            if not re.fullmatch(r"S\d{1,5}", spot):
                raise ToolError("bad-arg", "spot에는 verify가 준 S번호를 넣으세요. 예: spot=\"S3\"")
            payload["spot"] = spot
            cached = self._spots.get(doc["id"])
            if cached:
                payload["run_id"] = cached[0]
                known = next((entry for entry in cached[1] if entry["key"] == spot), None)
                if known is None:
                    raise ToolError("not-found", f"{spot}는 D{doc['n']}의 자동 대조 지점이 아닙니다.", f"verify(id=\"D{doc['n']}\")로 S번호를 다시 확인하세요.")
                if note:
                    note = f"{note} — 자동 대조 {spot}: {known['message']}"
        elif not note:
            raise ToolError("bad-arg", "spot(S번호) 또는 note(사람이 무엇을 확인할지)를 넣으세요.",
                            "예: flag(id=\"D12\", spot=\"S3\") 또는 flag(id=\"D12\", page=3, line=120, note=\"표 3행의 단위가 원본과 같은지\")")
        for key, value in (("page", page), ("sheet", sheet), ("cell", as_text(cell).upper()), ("line", line),
                           ("source_text", as_text(source_text)[:2000]), ("result_text", as_text(result_text)[:2000])):
            if value:
                payload[key] = value
        if note:
            payload["note"] = note[:2000]
        batch = self._latest_batch()
        if batch and any(item.get("doc") == doc["id"] for item in batch["items"]):
            payload["batch"] = batch["n"]
        try:
            review = self.api.post("/api/live/reviews", payload)
        except ApiError as exc:
            if exc.status in (404, 409, 422):
                raise ToolError("bad-arg" if exc.status == 422 else "not-found", exc.detail or "검수 요청을 만들 수 없습니다.",
                                f"verify(id=\"D{doc['n']}\")로 지점을 다시 확인하세요.") from None
            raise
        where = " ".join(part for part in (
            f"{review['page']}{'슬라이드' if doc['format'] in ('PPTX', 'PPTM') else '쪽'}" if review.get("page") else "",
            f"{review['sheet']}!{review['cell']}" if review.get("sheet") and review.get("cell") else review.get("sheet") or "",
            f"결과 줄 {review['line']}" if review.get("line") else "") if part)
        link = self.link(doc, page=review.get("page"), sheet=review.get("sheet"), cell=review.get("cell"), line=review.get("line"),
                         check=f"V{review['id']}", run=review.get("run_id"))
        if not review.get("created", True):
            return (f"결과: 이미 올린 검수 요청 V{review['id']}입니다(상태: {VERDICT_LABELS.get(review['status'], review['status'])}).\n"
                    f"다음: 다른 의심 지점을 확인하거나, 끝났으면 올린 검수 요청 목록을 사용자에게 알리세요.\n원문 대조: {link}")
        return (f"결과: 검수 요청을 올렸습니다 — V{review['id']} · D{doc['n']} {where}".rstrip() + "\n"
                f"다음: 다른 의심 지점을 계속 확인하세요. 끝나면 사용자에게 '콘솔 에이전트 작업 → 검수 요청'이나 아래 링크에서 원문 대조로 확인해 달라고 알립니다.\n"
                f"확인할 것: {_clip(review['note'], 300)}\n원문 대조: {link}")

    def verdicts(self, state: str = "all", id: str = "") -> str:  # noqa: A002
        state = (as_text(state) or "all").lower()
        state = {"확인전": "open", "확인 전": "open", "열림": "open", "미확인": "open", "맞음": "correct", "정상": "correct",
                 "틀림": "wrong", "오류": "wrong", "보류": "unclear", "전체": "all"}.get(state, state)
        if state not in ("all", *VERDICT_LABELS):
            raise ToolError("bad-arg", "state는 open(확인 전), correct(맞음), wrong(틀림), unclear(보류), all 중 하나입니다.")
        doc = self.find_doc(id) if as_text(id) else None
        data = self.api.get("/api/live/reviews", status=None if state == "all" else state, doc=doc["id"] if doc else None, limit=200)
        reviews, counts = data["reviews"], data["counts"]
        scope = f"D{doc['n']} " if doc else ""
        overall = ", ".join(f"{VERDICT_LABELS[key]} {counts[key]}" for key in VERDICT_LABELS if counts.get(key)) or "없음"
        head = (f"결과: {scope}검수 요청 {VERDICT_LABELS[state]} {len(reviews)}건 (전체: {overall})" if state != "all"
                else f"결과: {scope}검수 요청 {overall}")
        if not reviews:
            return head + "\n다음: verify 로 의심 지점을 찾아 flag 로 올리세요."
        lines = [head, "다음: '틀림'은 사람이 원문 대조로 확인한 파싱 오류입니다. 같은 유형(숫자·기호·표 칸)이 다른 문서에도 있는지 verify 로 확인하고, "
                       "유형별로 묶어 사용자에게 보고하세요. '확인 전'은 아직 사람이 보지 않은 것입니다."]
        for review in reviews[:40]:
            where = " ".join(part for part in (
                f"{review['page']}쪽" if review.get("page") else "", f"{review['sheet']}!{review['cell']}" if review.get("cell") else review.get("sheet") or "",
                f"줄 {review['line']}" if review.get("line") else "") if part)
            text = f"V{review['id']} D{review.get('document_seq') or '?'} {where} [{VERDICT_LABELS.get(review['status'], review['status'])}] {_clip(review['note'], 160)}"
            if review.get("source_hit") or review.get("result_hit"):
                produced = f"'{_clip(review['result_hit'], 40)}'" if review.get("result_hit") else "없음"
                text += f" | 원본 '{_clip(review.get('source_hit') or '', 40)}' → 결과 {produced}"
            if review.get("comment"):
                text += f" | 사람 메모: {_clip(review['comment'], 160)}"
            if review.get("is_latest_run") is False:
                text += " (그 뒤 다시 파싱됨)"
            lines.append(text)
        if len(reviews) > 40:
            lines.append(f"… 외 {len(reviews) - 40}건은 state 나 id 로 좁혀 보세요.")
        return "\n".join(lines)

    # ------------------------------------------------------------------ 도구: chunk / compare
    def chunk(self, id: str, strategy: str = "compare", size=512) -> str:  # noqa: A002
        from app.chunking import STRATEGY_KINDS, SIZE_RANGE

        strategy = as_text(strategy).lower()
        kinds = ["fixed", "recursive", "element"] if strategy == "compare" else [strategy]
        size = as_int(size)
        low, high = SIZE_RANGE["tokens"]
        if not size or not low <= size <= high:
            raise ToolError("bad-arg", f"size는 {low}~{high} 사이의 추정 토큰 수입니다.")
        if not all(kind in STRATEGY_KINDS and kind != "semantic" for kind in kinds):
            raise ToolError("bad-arg", "지원하지 않는 청킹 방식입니다.", "compare, fixed, recursive, markdown, sentence, element, parent_child, page 중 선택하세요.")
        doc = self.find_doc(id)
        data = self.api.post("/api/retrieval/chunk", {
            "source": {"doc_id": doc["id"]}, "embed": False, "summary_only": True, "limit_tokens": size,
            "strategies": [{"kind": k, "params": {"unit": "tokens", "size": size}} for k in kinds],
        })
        rows = []
        for result in data["results"]:
            if result.get("error") or not result.get("stats"):
                raise ToolError("chunk", result.get("error") or "청킹 결과가 없습니다.")
            stats = result["stats"]
            rows.append(f"{result['kind']}: 청크 {stats['count']}개, 추정 토큰 p95 {stats['tokens']['p95']} · 최대 {stats['tokens']['max']}, "
                        f"목표 초과 {stats['over_limit']}, 원문 포함률 {stats['coverage']:.1%}, 중복률 {stats['duplication']:.1%}, "
                        f"나뉜 표 {stats['tables_split']}/{stats['tables_total']}")
        stale = bool(data["source"]["is_stale"])
        return "\n".join([f"결과: D{doc['n']} 청킹 비교(목표 {size} 추정 토큰)" + (" — 이전 성공본(is_stale)" if stale else ""),
                          "다음: 청킹 지표만 전하세요. 검색 품질은 임베딩 평가를 한 경우에만 말합니다. 콘솔 '청킹 비교'에서 청크를 직접 볼 수 있습니다.",
                          *rows])

    def compare(self, id: str) -> str:  # noqa: A002
        doc = self.find_doc(id)
        runs = self.runs(doc["id"])
        if len(runs) < 2:
            raise ToolError("not-found", f"D{doc['n']}은 성공 실행이 {len(runs)}회라 비교할 이전 실행이 없습니다.",
                            f"parse 에 target=\"D{doc['n']}\" 을 넣어 다시 파싱한 뒤 비교하세요.")
        new_run, old_run = runs[0], runs[1]
        new, old = self.run_metrics(doc["id"], new_run), self.run_metrics(doc["id"], old_run)
        same_text = new["sha"] == old["sha"]
        same = same_text and old["warn"] == new["warn"]
        lines = [f"결과: D{doc['n']} " + ("두 실행의 본문과 경고가 같습니다" if same else "본문은 같고 경고가 바뀌었습니다" if same_text else "본문이 바뀌었습니다") +
                 f" ({_short_time(old_run['completed_at'])} → {_short_time(new_run['completed_at'])})",
                 "다음: 바뀐 줄이 원본과 맞는지 verify 로 대조하세요." if not same_text else "다음: 사용자에게 변화 없음으로 보고하세요."]
        for key, name in (("chars", "글자"), ("lines", "줄"), ("tables", "표 행"), ("numbers", "숫자"), ("broken", "깨진 글자"), ("pages", "쪽")):
            if old[key] != new[key] or key in ("chars", "tables"):
                lines.append(f"{name}: {old[key]} → {new[key]}")
        old_w, new_w = [c for c, _ in old["warn"]], [c for c, _ in new["warn"]]
        lines.append(f"경고: {','.join(old_w) or '없음'} → {','.join(new_w) or '없음'}")
        lines.append(f"파서: {old_run['parser']} {old_run['parser_version']} → {new_run['parser']} {new_run['parser_version']}, "
                     f"OCR {_on(old_run['ocr_enabled'])} → {_on(new_run['ocr_enabled'])}, 시간 {_seconds(old_run['duration_ms'])}s → {_seconds(new_run['duration_ms'])}s")
        if doc["status"] != "completed":
            lines.insert(1, "주의: 이전 성공본(is_stale) 두 회차의 비교입니다.")
        if not same_text:
            old_md = self.run_detail(doc["id"], old_run["run_id"])["markdown"].splitlines()
            new_md = self.run_detail(doc["id"], new_run["run_id"])["markdown"].splitlines()
            shown = 0
            for row in difflib.unified_diff(old_md, new_md, lineterm="", n=0):
                if row.startswith(("---", "+++", "@@")):
                    continue
                lines.append("바뀐 줄 " + _clip(row, 160))
                shown += 1
                if shown >= 20:
                    break
        return "\n".join(lines)

    # ------------------------------------------------------------------ 호출 기록
    def call(self, name: str, args: dict) -> tuple[str, bool]:
        started = time.monotonic()
        key = name + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        # 같은 도구·같은 인자를 2분 안에 다시 부르면 기록에만 표시한다(모델에게는 막지도 경고하지도 않는다).
        repeat = bool(self._last_call and self._last_call[0] == key and started - self._last_call[1] < 120
                      and name not in ("wait", "status"))
        self._touched = []
        entry = {"ts": _iso(), "tool": name, "args": args, "kind": None, "repeat": repeat, "session": self.session}
        try:
            text = self.dispatch(name, args)
            error = False
        except ToolError as exc:
            entry["kind"], error = exc.kind, True
            text = f"결과: 실패 ({exc.kind})\n원인: {exc}" + (f"\n다음: {exc.hint}" if exc.hint else "")
        except ServerDown as exc:
            entry["kind"], error = "server-down", True
            text = f"결과: 실패 (server-down)\n원인: {exc}\n다음: 사용자에게 콘솔을 켜 달라고 요청하세요."
        except ApiError as exc:
            entry["kind"], error = ("busy" if exc.status in (409, 503) else "api"), True
            text = f"결과: 실패 (서버 {exc.status})\n원인: {exc.detail}\n다음: 잠시 뒤 다시 시도하거나 사용자에게 알리세요."
        except Exception as exc:  # noqa: BLE001 — 모델에게는 짧게, 기록에는 자세히
            entry["kind"], error = "internal", True
            entry["trace"] = traceback.format_exc(limit=6)
            text = f"결과: 실패 (internal)\n원인: 작업 도구 내부 오류 {type(exc).__name__}\n다음: 사용자에게 알리세요. 같은 호출을 반복하지 마세요."
        entry["ms"] = round((time.monotonic() - started) * 1000)
        entry["result"] = text.split("\n", 1)[0][:200]
        entry["text"] = text[:CALL_TEXT_LIMIT]
        entry["docs"] = list(self._touched)
        self._last_call = (key, time.monotonic())
        try:
            self.store.append_call(entry)
        except OSError:
            pass
        return text, error

    def dispatch(self, name: str, args: dict) -> str:
        spec = TOOL_ARGS.get(name)
        if spec is None:
            hint = "검수 결과 보고는 verdicts, 묶음 결과는 wait(batch=\"B번호\")입니다." if name == "report" else "status 부터 부르세요."
            raise ToolError("bad-arg", f"'{name}' 도구는 없습니다. 있는 도구: {', '.join(TOOL_ARGS)}", hint)
        args = {key: value for key, value in (args or {}).items() if value is not None}
        # 약한 모델이 자주 하는 변형: 인자 이름을 다르게 부르거나, 필수 인자를 다른 이름으로 넣는다.
        renamed = {}
        for key, value in args.items():
            canonical = ARG_ALIASES.get(key.lower(), key.lower())
            if canonical == "target" and "id" in spec:
                canonical = "id"
            if canonical == "id" and name == "parse":
                canonical = "target"
            if canonical == "target" and name == "files":
                canonical = "folder"
            if canonical == "folder" and name == "parse":
                canonical = "target"
            if canonical == "find" and name == "flag":
                canonical = "note"
            if canonical in renamed and renamed[canonical] != value:
                raise ToolError("bad-arg", f"{canonical} 값이 둘입니다.")
            renamed[canonical] = value
        unknown = [key for key in renamed if key not in spec]
        if unknown:
            raise ToolError("bad-arg", f"{name}에서 쓰지 않는 인자: {', '.join(unknown)}",
                            "가능한 인자: " + (", ".join(spec) or "없음"))
        required = REQUIRED.get(name)
        if required and not as_text(renamed.get(required)):
            raise ToolError("bad-arg", f"{name} 에는 {required} 가 필요합니다.", EXAMPLES[name])
        for key in spec:
            if key not in renamed or key in ("size", "offset", "page", "line", "confirm", "reparse"):
                continue
            value = renamed[key]
            if isinstance(value, (dict, list, bool)) and not (key == "target" and isinstance(value, list)):
                raise ToolError("bad-arg", f"{key}에 문자열을 넣으세요.")
            renamed[key] = as_text(value)
        if name == "parse":
            return self.parse(renamed["target"], as_bool(renamed.get("reparse")), as_bool(renamed.get("confirm")))
        return getattr(self, name)(**renamed)


VERDICT_WORDS = {"ok": "경고 없음", "warn": "경고", "empty": "글자 없음", "fail": "실패", "unsup": "미지원", "run": "처리 중", "new": "미처리"}
VERDICT_LABELS = {"open": "확인 전", "correct": "맞음", "wrong": "틀림", "unclear": "보류"}
SEVERITY_WORDS = {"high": "높음", "medium": "보통", "low": "낮음"}
UNIT_STATES = {"hidden": "숨김", "empty": "글자 없음", "garbled": "글자 층 깨짐", "scan": "스캔"}
SKIP_WORDS = {"lock": "Office 잠금 파일", "hidden": "숨김·시스템 파일", "empty": "0바이트", "too-big": "100 MiB 초과"}

TOOL_ARGS = {
    "status": ["check"],
    "files": ["folder", "offset"],
    "parse": ["target", "reparse", "confirm"],
    "wait": ["batch"],
    "docs": ["state", "before"],
    "doc": ["id"],
    "verify": ["id", "page", "sheet"],
    "source": ["id", "page", "sheet", "line", "find"],
    "read": ["id", "page", "sheet", "line", "find"],
    "flag": ["id", "spot", "page", "sheet", "cell", "line", "note", "source_text", "result_text"],
    "verdicts": ["state", "id"],
    "compare": ["id"],
    "chunk": ["id", "strategy", "size"],
}
REQUIRED = {"parse": "target", "doc": "id", "verify": "id", "source": "id", "read": "id", "flag": "id", "compare": "id", "chunk": "id"}
EXAMPLES = {
    "parse": "예: parse(target=\"C:/docs/보고서.pdf\") 또는 parse(target=\"*.pdf\") 또는 parse(target=\"D12\"). 경로의 \\ 대신 / 를 써도 됩니다.",
    "doc": "예: doc(id=\"D12\")",
    "verify": "예: verify(id=\"D12\") 또는 verify(id=\"D12\", page=3)",
    "source": "예: source(id=\"D12\", page=3) 또는 source(id=\"D12\", sheet=\"요약\") 또는 source(id=\"D12\", find=\"0.5 mL\")",
    "read": "예: read(id=\"D12\", page=3) 또는 read(id=\"D12\", line=120)",
    "flag": "예: flag(id=\"D12\", spot=\"S3\") 또는 flag(id=\"D12\", page=3, line=120, note=\"표 단위가 원본과 같은지\")",
    "chunk": '예: chunk(id="D12", strategy="compare", size=512)',
    "compare": "예: compare(id=\"D12\")",
}
ARG_ALIASES = {
    "path": "target", "file": "target", "files": "target", "filename": "target", "file_path": "target", "folder_path": "target",
    "doc_id": "id", "document": "id", "document_id": "id", "number": "id", "doc": "id", "name": "id",
    "page_number": "page", "pages": "page", "p": "page", "slide": "page", "slide_number": "page", "sheet_name": "sheet",
    "query": "find", "search": "find", "text": "find",
    "row": "line", "start": "line", "start_line": "line", "line_number": "line", "from_line": "line", "offset_line": "line",
    "address": "cell", "cell_address": "cell", "spot_id": "spot", "s": "spot",
    "comment": "note", "reason": "note", "message": "note", "description": "note", "memo": "note",
    "original": "source_text", "original_text": "source_text", "source_snippet": "source_text", "expected": "source_text",
    "parsed": "result_text", "parsed_text": "result_text", "actual": "result_text", "output": "result_text", "result": "result_text",
    "batch_id": "batch", "status": "state", "filter": "state", "verdict": "state", "force": "reparse", "again": "reparse",
    "yes": "confirm", "dir": "folder", "directory": "folder",
}
