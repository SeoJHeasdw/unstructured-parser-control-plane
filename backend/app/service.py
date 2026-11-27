"""Local storage and single-worker processing orchestration."""
from collections import OrderedDict
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from queue import Empty, Full, Queue
import re
import shutil
import tempfile
import threading
from uuid import uuid4

from fastapi import UploadFile
from app.adapters.base import ParserError, UnsupportedFormat
from app.adapters.docling import WORKBOOKS
from app.adapters.registry import ParserRegistry, TEXT_FORMATS
from app.config import Settings
from app.adapters.ocr import ModelOcr
from app.fidelity.pictures import PictureOcr
from app.fidelity import OOXML_FORMATS, assess, prepare_copy, prepared_copy_path, probe
from app.filelock import try_lock, unlock
from app.format_gate import check as check_format
from app.formats import IMAGE_FORMATS
from app.repository import DocumentRepository, now
from app.source_preview import worksheet_preview
from app import qc
from app.source_text import SourceText, SourceUnavailable, read_source
from app.verify import MAX_SPOTS, image_only, verify as verify_result
from app.structure import Budget, inspect_file
from app.textnorm import display_name
from app.vba import parse_notes as macro_notes

logger = logging.getLogger(__name__)
_ID = re.compile(r"^[0-9a-f]{32}$")
_EXT = re.compile(r"^[A-Za-z0-9]{1,20}$")
_RESULT_NAME = re.compile(r"^[0-9a-f]{32}-[0-9a-f]{32}\.md$")
PDF_OCR_WARNING = "OCR 미적용: 스캔·이미지 페이지 내용 누락 가능"
FIDELITY_FAILED_WARNING = "원문 충실도 점검을 하지 못했습니다. 파싱 결과는 그대로 저장했습니다."
PREPARE_FALLBACK_WARNING = "기호·첨자 보정 사본을 파싱하지 못해 원본으로 파싱했습니다. 기호 글꼴·첨자가 빠지거나 붙을 수 있습니다."
_WORK_PREFIX = "docops-prep-"

def _review_ref(review: dict) -> dict:
    """청크·목록에 싣는 검수 요청 요약(V번호·판정·메모·위치)."""
    return {"id": review["id"], "status": review["status"], "comment": review.get("comment"), "origin": review.get("origin"),
            "page": review.get("page"), "sheet": review.get("sheet"), "cell": review.get("cell"), "line": review.get("line"),
            "decided_at": review.get("decided_at")}


class MissingDocument(Exception): pass
class MissingRun(Exception): pass
class Conflict(Exception): pass
class QueueUnavailable(Exception): pass
class TooLarge(Exception): pass
class InvalidName(Exception): pass

def clean_name(filename: str | None) -> tuple[str, str]:
    if not filename:
        raise InvalidName("파일명이 필요합니다.")
    # The supplied name is display metadata only, never a storage path.
    name = filename.replace("\\", "/").split("/")[-1]
    # macOS 분해형 한글(NFD)은 조합형으로, 방향 제어 글자는 제거한다. ℃·±·− 같은 기호는 그대로 둔다.
    name = display_name("".join(c for c in name if ord(c) >= 32 and ord(c) != 127)).strip()
    if not name or name in {".", ".."}:
        raise InvalidName("유효한 파일명이 필요합니다.")
    suffix = Path(name).suffix[1:]
    extension = suffix.upper() if _EXT.fullmatch(suffix) else ""
    if len(name) > 220:
        name = name[:200] + ("." + suffix if extension else "")
    return name, extension

class DocumentService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.repo = DocumentRepository(settings.database)
        self.parsers = ParserRegistry(settings)
        self.lock_file = None
        self._lock_guard = threading.Lock()
        self._admission_lock = threading.Lock()
        self._stopping = threading.Event()
        self._jobs: Queue[tuple[str, str] | None] = Queue(maxsize=max(1, settings.max_pending_jobs))
        self._worker: threading.Thread | None = None
        # 원본 글자(원본은 문서마다 바뀌지 않는다)를 잠시 둔다. 자동 대조 결과는 원장(qc_runs·qc_findings)에 둔다.
        self._cache_lock = threading.Lock()
        self._sources: OrderedDict[tuple, SourceText] = OrderedDict()
        # 자동 대조 계산은 한 번에 하나(같은 실행을 두 요청이 동시에 계산하지 않게, PDF 네이티브 호출도 겹치지 않게).
        self._qc_lock = threading.Lock()
        # 사용자가 지정한 원천 계약(CSV 구분자·인코딩). 접수한 실행 ID → 옵션. 처리할 때 꺼내 실행에 기록한다.
        self._run_options: dict[str, dict] = {}
        # 대조 규칙(코드 지문)이 바뀐 뒤 기존 실행을 다시 대조하는 작업자와 진행 상황
        self._reverifier: threading.Thread | None = None
        self.reverify_state = {"state": "idle", "total": 0, "stale": 0, "done": 0, "failed": 0, "rule_version": qc.rule_key()}

    def start(self) -> None:
        self.settings.runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.settings.uploads.mkdir(mode=0o700, exist_ok=True)
        self.settings.results.mkdir(mode=0o700, exist_ok=True)
        self.settings.structures.mkdir(mode=0o700, exist_ok=True)
        self.settings.work.mkdir(mode=0o700, exist_ok=True)
        self.lock_file = (self.settings.runtime_dir / "server.lock").open("a+")
        try:
            try_lock(self.lock_file)
        except OSError as exc:
            self.lock_file.close()
            self.lock_file = None
            raise RuntimeError("이 데이터 폴더를 사용하는 다른 문서 처리 서버가 이미 실행 중입니다.") from exc
        try:
            self._clear_work()
            self.repo.initialize()
            self.repo.recover_interrupted()
            self._stopping.clear()
            self._worker = threading.Thread(target=self._run_worker, name="document-parser", daemon=True)
            self._worker.start()
            if self.settings.qc_reverify:
                self._reverifier = threading.Thread(target=self._reverify, name="qc-reverify", daemon=True)
                self._reverifier.start()
        except BaseException:
            self._release_lock()
            raise

    def _clear_work(self) -> None:
        # 이전 프로세스가 비정상 종료하며 남긴 파싱용 사본만 지운다(이 서비스가 만든 이름만, 잠금을 얻은 뒤).
        for leftover in self.settings.work.glob(_WORK_PREFIX + "*"):
            shutil.rmtree(leftover, ignore_errors=True)

    def _release_lock(self) -> None:
        with self._lock_guard:
            if self.lock_file:
                unlock(self.lock_file)
                self.lock_file.close()
                self.lock_file = None

    def stop(self) -> None:
        with self._admission_lock:
            self._stopping.set()
            # Tasks which have not started are made retryable. The active task may finish.
            while True:
                try:
                    job = self._jobs.get_nowait()
                except Empty:
                    break
                try:
                    if job:
                        self._mark_interrupted(*job)
                finally:
                    self._jobs.task_done()
            if self._worker and self._worker.is_alive():
                self._jobs.put_nowait(None)
        if self._worker:
            self._worker.join(timeout=5)
        if self._reverifier:
            self._reverifier.join(timeout=5)
        # If parsing outlives shutdown, the worker retains the process lock until it exits.
        # If the whole process exits first, the OS releases the lock and startup recovery runs.
        if (not self._worker or not self._worker.is_alive()) and (not self._reverifier or not self._reverifier.is_alive()):
            self._release_lock()

    def _reverify(self) -> None:
        """현재 대조 규칙의 원장이 없는 최신 성공 실행을 다시 대조한다(규칙·코드가 바뀐 뒤 처음 시작할 때, 작업자가 대조 전에 멈췄을 때).
        원본을 다시 읽어 대조만 한다(파싱·외부 호출 없음). 이전 규칙의 원장과 검수 요청(V번호·판정·메모)은 지우지 않는다."""
        state = self.reverify_state
        try:
            needed = self.repo.qc_needed(qc.rule_key())
        except Exception as exc:  # noqa: BLE001
            logger.warning("QC re-verification skipped (%s)", type(exc).__name__)
            state["state"] = "failed"
            return
        state.update(state="running" if needed else "done", total=len(needed), stale=sum(1 for _, _, stale in needed if stale))
        for doc_id, run_id, _ in needed:
            if self._stopping.is_set():
                state["state"] = "stopped"
                return
            try:
                self.ensure_qc(doc_id, run_id)
            except Exception as exc:  # noqa: BLE001 — 원본을 읽을 수 없는 문서는 '대조 불가'로 남는다
                state["failed"] += 1
                logger.info("QC re-verification failed for one run (%s)", type(exc).__name__)
            state["done"] += 1
        state["state"] = "done"

    def _mark_interrupted(self, doc_id: str, run_id: str) -> None:
        doc = self.repo.get(doc_id)
        if doc:
            self.repo.finish(doc_id, run_id, status="failed", parser=doc.get("parser"), parser_version=None, result_file=None, error="서버 종료로 대기 중인 처리가 중단되었습니다. 다시 실행해 주세요.", error_code="interrupted")

    def _run_worker(self) -> None:
        try:
            while True:
                job = self._jobs.get()
                try:
                    if job is None:
                        return
                    if self._stopping.is_set():
                        self._mark_interrupted(*job)
                    else:
                        self.process(*job)
                except Exception as exc:
                    # Keep the worker alive if an unexpected task-level error occurs.
                    logger.error("Worker task failed (%s)", type(exc).__name__)
                    if job:
                        try:
                            self._mark_interrupted(*job)
                        except Exception:
                            logger.error("Could not record interrupted task")
                finally:
                    self._jobs.task_done()
        finally:
            self._release_lock()

    def get(self, doc_id: str) -> dict:
        if not _ID.fullmatch(doc_id):
            raise MissingDocument()
        doc = self.repo.get(doc_id)
        if not doc:
            raise MissingDocument()
        return doc

    async def store(self, file: UploadFile) -> dict:
        name, extension = clean_name(file.filename)
        doc_id = uuid4().hex
        suffix = f".{extension.lower()}" if extension else ""
        final_name = doc_id + suffix
        final_path = self.settings.uploads / final_name
        temp_path = self.settings.uploads / f"{doc_id}.part"
        total = 0
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as out:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.settings.max_upload_bytes:
                        raise TooLarge()
                    out.write(chunk)
            os.replace(temp_path, final_path)
            try:
                return self.repo.create(doc_id, name, extension, total, final_name)
            except BaseException:
                final_path.unlink(missing_ok=True)
                raise
        finally:
            temp_path.unlink(missing_ok=True)
            await file.close()

    def store_local(self, source: Path, origin: str) -> dict:
        """이 컴퓨터의 파일을 서버가 직접 읽어 저장한다(허용 폴더에서 가져오기). 업로드와 같은 저장 규칙을 따른다."""
        name, extension = clean_name(source.name)
        doc_id = uuid4().hex
        suffix = f".{extension.lower()}" if extension else ""
        final_name = doc_id + suffix
        final_path = self.settings.uploads / final_name
        temp_path = self.settings.uploads / f"{doc_id}.part"
        total = 0
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as out, source.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.settings.max_upload_bytes:
                        raise TooLarge()
                    out.write(chunk)
            os.replace(temp_path, final_path)
            try:
                return self.repo.create(doc_id, name, extension, total, final_name,
                                        f"허용 폴더에서 가져와 로컬에 저장했습니다({origin}). 아직 처리하지 않았습니다.")
            except BaseException:
                final_path.unlink(missing_ok=True)
                raise
        finally:
            temp_path.unlink(missing_ok=True)

    def same_original(self, source: Path, candidates: list[dict], digest: str) -> dict | None:
        """이름·크기가 같은 기존 문서 중 저장된 원본의 SHA-256까지 같은 것. 같은 파일을 두 번 저장하지 않는다."""
        for doc in candidates:
            try:
                path = self._source_path(doc)
                with path.open("rb") as handle:
                    if hashlib.file_digest(handle, "sha256").hexdigest() == digest:
                        return doc
            except (Conflict, OSError):
                continue
        return None

    def begin(self, doc_id: str) -> tuple[dict, str]:
        doc = self.get(doc_id)
        run_id = uuid4().hex
        if not self.repo.claim(doc_id, run_id, self.parsers.parser_name(doc["format"])):
            raise Conflict("이미 처리 중인 문서입니다.")
        return self.get(doc_id), run_id

    def enqueue(self, doc_id: str, options: dict | None = None) -> dict:
        """options: 사용자가 지정한 원천 계약(텍스트·CSV의 encoding, csv_delimiter). 다른 형식에는 쓰지 않는다."""
        with self._admission_lock:
            doc = self.get(doc_id)
            options = {key: value for key, value in (options or {}).items() if value not in (None, "")}
            if options and doc["format"] not in TEXT_FORMATS:
                raise Conflict("구분자·인코딩 지정은 텍스트·CSV 문서에만 쓸 수 있습니다.")
            if options.get("csv_delimiter") and doc["format"] != "CSV":
                raise Conflict("구분자 지정은 CSV 문서에만 쓸 수 있습니다.")
            if doc["status"] == "processing":
                raise Conflict("이미 처리 중인 문서입니다.")
            if self._stopping.is_set() or not self._worker or not self._worker.is_alive():
                self.repo.record_event(doc_id, doc["status"], "처리 워커를 사용할 수 없어 요청을 접수하지 못했습니다.")
                raise QueueUnavailable("처리 워커를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.")
            if self._jobs.full():
                self.repo.record_event(doc_id, doc["status"], "처리 대기열이 가득 차 요청을 접수하지 못했습니다.")
                raise QueueUnavailable("처리 대기열이 가득 찼습니다. 잠시 후 다시 시도해 주세요.")
            processing_doc, run_id = self.begin(doc_id)
            if options:
                self._run_options[run_id] = options
            try:
                self._jobs.put_nowait((doc_id, run_id))
            except Full:
                self.repo.finish(doc_id, run_id, status="failed", parser=processing_doc.get("parser"), parser_version=None, result_file=None, error="처리 대기열이 가득 차 요청을 접수하지 못했습니다.", error_code="queue_full")
                raise QueueUnavailable("처리 대기열이 가득 찼습니다. 잠시 후 다시 시도해 주세요.")
            return processing_doc

    def process(self, doc_id: str, run_id: str) -> None:
        result_path = None
        temp_path = None
        options = self._run_options.pop(run_id, None)
        committed = False
        try:
            doc = self.get(doc_id)
            # Storage names originate from the server, never from the request's filename.
            source_name = doc["source_file"]
            if source_name != Path(source_name).name or not source_name.startswith(doc_id):
                raise ParserError("저장된 파일 경로를 확인할 수 없습니다.")
            path = self.settings.uploads / source_name
            extension = doc["format"]
            if self.parsers.parser_name(extension) is None:
                from app.structure import FAMILY
                if extension in FAMILY:
                    # 구조 분석만 되는 형식: 본문 파서가 없다는 것과, 보호(암호·DRM) 여부는 확인하지 않았다는 것을 함께 알린다.
                    raise UnsupportedFormat("이 형식은 본문 파서가 없습니다. 하위 문서·링크는 문서 상세의 '구조·참조'에서 구조 분석으로 볼 수 있습니다"
                                            "(암호·보호 여부는 확인하지 않았습니다).")
                raise UnsupportedFormat("이 파일 형식은 아직 처리 경로가 없습니다.")
            # 확장자가 아니라 내용으로 먼저 확인한다: DRM 래핑·암호·형식 불일치는 파서 오류로 뭉뚱그리지 않는다.
            gate = check_format(path, extension, self.settings.drm_signatures, self.settings.max_upload_bytes)
            if not gate.passed:
                raise ParserError(gate.message or "파일 형식을 확인할 수 없습니다.", code=gate.code)
            started = time.perf_counter()
            result_name = f"{doc_id}-{run_id}.md"
            result_path = self.settings.results / result_name
            temp_path = self.settings.results / f"{doc_id}-{run_id}.tmp"
            fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
                if extension in TEXT_FORMATS and path.stat().st_size >= 1024 * 1024:
                    parsed = self.parsers.text.write_to(path, extension, output, options)
                    warnings, locations, fidelity, ocr_enabled = [], [], None, None
                else:
                    parsed, prepared, warnings = self._parse(path, extension, options)
                    markdown, locations, fidelity = parsed.markdown, list(parsed.locations), None
                    warnings.extend(parsed.warnings)
                    ocr_enabled = parsed.ocr_enabled
                    if extension in OOXML_FORMATS:
                        ocr = ModelOcr(self.settings)
                        pictures = PictureOcr(ocr) if ocr.configured else None
                        try:
                            inventory = probe(path, extension, pictures)
                            markdown, extra, notes, fidelity = assess(inventory, markdown, prepared)
                            locations += extra
                            warnings += notes
                            if inventory["images"]["total"]:
                                ocr_enabled = bool(pictures and pictures.applied)
                        except Exception as exc:
                            logger.warning("Fidelity check skipped (%s)", type(exc).__name__)
                            warnings.append(FIDELITY_FAILED_WARNING)
                        if extension in WORKBOOKS:
                            # 매크로는 실행하지 않는다. 있으면 셀 값이 저장 시점의 값이라는 것을 결과에 남긴다.
                            # (이름만 .xlsx로 바꾼 매크로 통합문서도 같은 경고를 받는다)
                            warnings.extend(macro_notes(path))
                        if not markdown.strip():
                            raise ParserError("Office 본문·그림에서 글자를 추출하지 못했습니다. " + " ".join(warnings[:2]), code="no_text")
                    output.write(markdown)
            duration_ms = round((time.perf_counter() - started) * 1000)
            os.replace(temp_path, result_path)
            if extension == "PDF" and not ocr_enabled:
                warnings.insert(0, PDF_OCR_WARNING)
            try:
                committed = self.repo.finish(doc_id, run_id, status="completed", parser=parsed.parser,
                                             parser_version=parsed.parser_version, result_file=result_name, error=None,
                                             warnings=warnings, ocr_enabled=ocr_enabled, duration_ms=duration_ms,
                                             locations=[location.model_dump() for location in locations], fidelity=fidelity,
                                             evidence=parsed.evidence, options=options, qc_version=qc.rule_key())
            finally:
                if not committed:
                    result_path.unlink(missing_ok=True)
        except UnsupportedFormat as exc:
            self.repo.finish(doc_id, run_id, status="unsupported", parser=None, parser_version=None, result_file=None, error=str(exc), error_code=exc.code)
        except ParserError as exc:
            doc = self.repo.get(doc_id)
            self.repo.finish(doc_id, run_id, status="failed", parser=doc.get("parser") if doc else None, parser_version=None, result_file=None, error=str(exc), error_code=exc.code)
        except Exception as exc:
            # Avoid logging raw document contents, file names, or exception text.
            logger.error("Document processing failed (%s)", type(exc).__name__)
            doc = self.repo.get(doc_id)
            self.repo.finish(doc_id, run_id, status="failed", parser=doc.get("parser") if doc else None, parser_version=None, result_file=None, error="파일 처리 중 오류가 발생했습니다. 파일 상태와 서버 설정을 확인해 주세요.", error_code="internal_error")
        finally:
            if temp_path:
                temp_path.unlink(missing_ok=True)
        if committed:
            # 같은 작업자가 이어서 자동 대조 원장을 만든다(사용자가 시작한 처리의 일부, 외부 호출 없음). 실패해도 파싱 결과는 그대로다.
            try:
                self.ensure_qc(doc_id, run_id)
            except Exception as exc:  # noqa: BLE001 — 원장은 '미평가'로 남고 조회할 때 다시 계산한다
                logger.info("QC after parse skipped (%s)", type(exc).__name__)

    def _parse(self, path: Path, extension: str, options: dict | None = None):
        """(파싱 결과, 사본 보정 통계 | None, 경고). OOXML은 원본 대신 보정 사본을 파서에 넣는다."""
        if options:
            return self.parsers.parse(path, extension, options), None, []
        if extension not in OOXML_FORMATS:
            return self.parsers.parse(path, extension), None, []
        # 사본을 만들기 전에 압축 폭탄·위험 경로를 거른다.
        self.parsers.docling.check_office_archive(path)
        if not self.settings.ooxml_prepare:
            return self.parsers.parse(path, extension), None, []
        with tempfile.TemporaryDirectory(prefix=_WORK_PREFIX, dir=self.settings.work, ignore_cleanup_errors=True) as workdir:
            target = prepared_copy_path(Path(workdir), extension)
            try:
                stats = prepare_copy(path, target, extension, only_if_changed=True)
            except Exception as exc:
                logger.warning("OOXML preparation skipped (%s)", type(exc).__name__)
                return self.parsers.parse(path, extension), None, [PREPARE_FALLBACK_WARNING]
            if not stats.changed:
                return self.parsers.parse(path, extension), stats.as_dict(), []
            try:
                return self.parsers.parse(target, extension), stats.as_dict(), []
            except ParserError as exc:
                if exc.code == "parser_unavailable":
                    raise
                logger.warning("Prepared copy failed to parse; retrying the original (%s)", exc.code)
        return self.parsers.parse(path, extension), None, [PREPARE_FALLBACK_WARNING]

    def _source_path(self, doc: dict) -> Path:
        source_name = doc["source_file"]
        if source_name != Path(source_name).name or not source_name.startswith(doc["id"]):
            raise Conflict("저장된 파일 경로를 확인할 수 없습니다.")
        return self.settings.uploads / source_name

    def original(self, doc_id: str) -> tuple[dict, Path]:
        doc = self.get(doc_id)
        path = self._source_path(doc)
        if not path.is_file():
            raise Conflict("저장된 원본 파일을 찾을 수 없습니다.")
        return doc, path

    def source_preview(self, doc_id: str, sheet: str | None, cell: str) -> dict:
        doc, path = self.original(doc_id)
        try:
            if doc["format"] in WORKBOOKS:
                self.parsers.docling.check_office_archive(path)
                return worksheet_preview(path, sheet, cell)
            if doc["format"] in TEXT_FORMATS:
                text = self.parsers.text.read_source(path, limit=60_001)
                return {"kind": "text", "text": text[:60_000], "truncated": len(text) > 60_000}
        except ImportError as exc:
            raise Conflict("워크시트 미리보기에 필요한 선택 의존성이 설치되어 있지 않습니다.") from exc
        except (ParserError, OSError) as exc:
            raise Conflict(str(exc) if isinstance(exc, ParserError) else "저장된 원본을 읽을 수 없습니다.") from exc
        raise Conflict("이 형식은 원본 파일로 열어 확인할 수 있습니다.")

    # ------------------------------------------------------------ 원본 글자·자동 대조
    def source_text(self, doc_id: str, dialect: dict | None = None) -> tuple[dict, SourceText]:
        """파서와 별개로 읽은 원본 글자(app/source_text.py). 읽을 수 없는 형식·손상 파일은 Conflict.
        dialect: 텍스트·CSV에서 그 실행이 쓴 인코딩·구분자(실행에 기록된 계약으로 다시 읽는다)."""
        doc, path = self.original(doc_id)
        key = (doc_id, (dialect or {}).get("encoding"), (dialect or {}).get("delimiter"))
        with self._cache_lock:
            cached = self._sources.get(key)
            if cached is not None:
                self._sources.move_to_end(key)
                return doc, cached
        try:
            if doc["format"] in OOXML_FORMATS:
                self.parsers.docling.check_office_archive(path)  # 압축 폭탄·위험 경로
            source = read_source(path, doc["format"], self.settings, dialect)
        except SourceUnavailable as exc:
            raise Conflict(str(exc)) from exc
        except ParserError as exc:
            raise Conflict(str(exc)) from exc
        except OSError as exc:
            raise Conflict("저장된 원본을 읽을 수 없습니다.") from exc
        with self._cache_lock:
            self._sources[key] = source
            while len(self._sources) > 3:
                self._sources.popitem(last=False)
        return doc, source

    def _run_for(self, doc_id: str, run_id: str | None) -> dict:
        runs = self.repo.parse_runs(doc_id)
        if not runs:
            raise Conflict("성공한 파싱 결과가 없어 원본과 대조할 수 없습니다.")
        if run_id is None:
            return next((run for run in runs if run["is_latest"]), runs[0])
        run = next((run for run in runs if run["run_id"] == run_id), None)
        if run is None:
            raise MissingRun()
        return run

    def ensure_qc(self, doc_id: str, run_id: str) -> dict:
        """그 실행의 자동 대조 원장(현재 규칙 버전). 없거나 '미평가'면 지금 계산해 저장한다. 원본을 읽을 수 없으면 Conflict."""
        ledger = self.repo.qc_run(doc_id, run_id, qc.rule_key())
        if ledger and ledger["state"] == "done":
            return json.loads(ledger["result"])
        with self._qc_lock:
            ledger = self.repo.qc_run(doc_id, run_id, qc.rule_key())
            if ledger and ledger["state"] == "done":
                return json.loads(ledger["result"])
            doc = self.get(doc_id)
            stored = self.parse_run(doc_id, run_id)
            started = time.perf_counter()
            if doc["format"] in IMAGE_FORMATS or doc["format"] == "SVG":
                result = image_only(stored["markdown"], doc["format"], stored["parser"])
            else:
                evidence = stored.get("evidence") or {}
                dialect = {"encoding": evidence.get("encoding"), "delimiter": evidence.get("delimiter")} if evidence.get("encoding") else None
                try:
                    _, source = self.source_text(doc_id, dialect)
                except Conflict as exc:
                    self.repo.mark_qc(doc_id, run_id, qc.rule_key(), "unavailable", str(exc))
                    raise
                result = verify_result(source, stored["markdown"], stored["locations"], stored["parser"], doc["format"], evidence)
            spots = result.pop("spots")
            header = {**result, "computed_at": now()}
            self.repo.save_qc(doc_id, run_id, qc.rule_key(), header, spots,
                              qc.machine_state(result["spots_total"], result["reasons"]),
                              round((time.perf_counter() - started) * 1000))
            return header

    def verify(self, doc_id: str, run_id: str | None = None, *, severity: list[str] | None = None, unit: str | None = None,
               kind: list[str] | None = None, order: str = "priority", offset: int = 0, limit: int = MAX_SPOTS,
               unreviewed: bool = False) -> dict:
        """파싱 결과를 원본 글자와 자동 대조한 원장. 의심점(S번호)은 우선순위 순으로 한 쪽씩 준다(전체 수와 다음 쪽 위치 포함).
        판정이 아니라 사람이 볼 곳의 후보다. gate는 사람 판정까지 합친 문서 상태(검수 필요·판정 불가·통과 후보)."""
        doc = self.get(doc_id)
        run = self._run_for(doc_id, run_id)
        header = self.ensure_qc(doc_id, run["run_id"])
        verdicts, counts = self.repo.review_verdicts(doc_id, run["run_id"])
        exclude = {fid for fid, status in verdicts.items() if status != "open"} if unreviewed else None
        spots, matched = self.repo.qc_findings(doc_id, run["run_id"], qc.rule_key(), severity=severity, unit=unit, kind=kind,
                                               order=order, offset=offset, limit=limit, exclude=exclude)
        top_spots, _ = self.repo.qc_findings(doc_id, run["run_id"], qc.rule_key(), order="priority", limit=20)
        stale = not run["is_latest"] or doc["status"] != "completed"
        history = self.repo.qc_history(doc_id, run["run_id"], qc.rule_key())
        reasons = list(header.get("reasons", []))
        if history:
            before = history[0]
            reasons.append(qc.reason("rules_changed", f"대조 규칙이 바뀌어 이 실행을 다시 대조했습니다(이전 규칙 {before['rule_version']}: 의심점 "
                                     f"{before['spots_total'] or 0}곳 → 지금 {header.get('spots_total', 0)}곳). 이전 검수 판정과 근거(V번호·메모)는 그대로입니다.",
                                     blocking=False, previous=before["rule_version"]))
        gate = qc.gate(self.repo.qc_all(doc_id, run["run_id"], qc.rule_key()), reasons, verdicts,
                       counts.get("open", 0) + counts.get("unclear", 0), counts.get("wrong", 0), stale=stale)
        following = offset + len(spots)
        return {"id": doc_id, "run_id": run["run_id"], "completed_at": run["completed_at"], "parser_version": run["parser_version"],
                **header, "qc_state": "done", "spots": spots, "spots_matched": matched,
                "page": {"offset": offset, "limit": limit, "order": order, "next": following if following < matched else None},
                "top_spots": top_spots, "gate": gate, "verdicts": verdicts, "rule_history": history,
                "is_latest": bool(run["is_latest"]), "document_status": doc["status"]}

    def chunk_findings(self, doc_id: str, run_id: str, limit: int) -> tuple[list[dict], dict]:
        """청크에 붙일 검수 항목: 원장 의심점 중 사람이 '맞음'으로 해결하지 않은 것(판정이 있으면 V번호·판정·메모를 붙임)과,
        의심점 없이 올린 검수 요청 중 결과 줄이 있고 '맞음'이 아닌 것. '틀림'은 확인된 오류, '보류'·확인 전은 미해결로 남긴다.
        순서: 틀림 → 보류 → 확인 전 → 판정 없음(각각 우선순위 순). (항목, 판정 상태)를 돌려준다."""
        data = self.verify(doc_id, run_id, limit=1)
        reviews = self.repo.run_reviews(doc_id, run_id)
        by_finding: dict[str, dict] = {}
        for review in reviews:
            if review["finding_id"] and review["finding_id"] not in by_finding:
                by_finding[review["finding_id"]] = review
        resolved = {fid for fid, review in by_finding.items() if review["status"] == "correct"}
        spots, _ = self.repo.qc_findings(doc_id, run_id, qc.rule_key(), order="priority", limit=limit, exclude=resolved)
        entries: list[dict] = []
        for spot in spots:
            review = by_finding.get(spot.get("id") or "")
            entries.append({**spot, "review": _review_ref(review) if review else None})
        known = {spot.get("id") for spot in spots}
        for review in reviews:
            if review["status"] == "correct" or not review["line"] or (review["finding_id"] and review["finding_id"] in known):
                continue
            if review["finding_id"] and review["finding_id"] in resolved:
                continue
            entries.append({"key": f"V{review['id']}", "id": review["finding_id"], "severity": review["severity"] or "medium",
                            "kind": review["kind"], "message": review["note"], "page": review["page"], "sheet": review["sheet"],
                            "cell": review["cell"], "line": review["line"], "line_end": review["line_end"] or review["line"],
                            "source_hit": review["source_hit"] or "", "result_hit": review["result_hit"] or "", "review": _review_ref(review)})
        weight = {"wrong": 0, "unclear": 1, "open": 2}
        entries.sort(key=lambda entry: (weight.get((entry.get("review") or {}).get("status"), 3), entry.get("rank", 10**9)))
        return entries, data.get("gate") or {}

    def finding(self, doc_id: str, run_id: str | None, ref: str) -> dict:
        """원장의 의심점 하나(S번호 또는 finding ID). 상세 목록에서 잘린 고위험 항목도 바로 열 수 있다."""
        self.get(doc_id)
        run = self._run_for(doc_id, run_id)
        self.ensure_qc(doc_id, run["run_id"])
        if not (qc.SPOT_KEY.fullmatch(ref) or qc.FINDING_ID.fullmatch(ref)):
            raise Conflict("S번호(예: S3) 또는 finding ID(F로 시작하는 13자리)를 넣으세요.")
        spot = self.repo.qc_finding(doc_id, run["run_id"], qc.rule_key(), ref)
        if spot is None:
            raise Conflict(f"{ref} 자동 대조 지점이 없습니다. 자동 대조를 다시 확인하세요.")
        return {**spot, "run_id": run["run_id"], "rule_version": qc.rule_key()}

    @staticmethod
    def _qc_state(row: dict) -> str | None:
        """목록·깔때기용 문서 판정 상태(최신 성공 실행, 사람 판정 합침). gate와 같은 순서: 검수 필요 → 판정 불가 → 통과 후보."""
        if not row["result_file"]:
            return None
        if row["qc_state"] in (None, "pending"):
            return "pending"
        if row["qc_state"] != "done":
            return "unavailable"
        reviews = row["reviews"]
        unresolved = max(0, (row["spots_total"] or 0) - row["resolved"])
        if unresolved or reviews.get("open") or reviews.get("unclear") or reviews.get("wrong"):
            return "needs_review"
        return "undetermined" if row["blocking"] else "pass_candidate"

    def qc_summary(self) -> dict:
        """처리 깔때기: 반입 전체 → 파싱 완료 → 자동 대조 → 판정 상태. 마지막 단계만 보고 처리율을 말하지 않도록 분모를 함께 준다.
        판정 상태는 문서마다 최신 성공 실행 기준이고, 사람 판정(맞음·틀림·보류·열림)을 합친다(gate와 같은 규칙)."""
        rows = self.repo.qc_overview(qc.rule_key())
        out = {"rule_version": qc.rule_key(), "documents": len(rows), "parsed": 0, "qc_done": 0, "qc_pending": 0,
               "qc_unavailable": 0, "states": {state: 0 for state in ("needs_review", "undetermined", "pass_candidate")},
               "not_parsed": {}, "human_decided": 0, "processing": 0, "qc_stale": 0, "reverify": dict(self.reverify_state)}
        for row in rows:
            if row["status"] == "processing":
                out["processing"] += 1
            state = self._qc_state(row)
            if state is None:
                if row["status"] != "processing":
                    key = row["error_code"] or row["status"]
                    out["not_parsed"][key] = out["not_parsed"].get(key, 0) + 1
                continue
            out["parsed"] += 1
            if state == "pending":
                out["qc_pending"] += 1
                if row["stale"]:
                    out["qc_stale"] += 1  # 이전 규칙의 원장만 있다: 다시 대조할 실행
                continue
            if state == "unavailable":
                out["qc_unavailable"] += 1
                continue
            out["qc_done"] += 1
            out["states"][state] += 1
            if any(row["reviews"].get(status) for status in ("correct", "wrong", "unclear")):
                out["human_decided"] += 1
        return out

    def documents_page(self, *, query: str = "", status: str = "all", formats: list[str] | None = None, sort: str = "recent",
                       cursor: str | None = None, limit: int = 50) -> dict:
        page = self.repo.list_page(query=query, status=status, formats=formats, sort=sort, cursor=cursor, limit=limit)
        self._attach_qc(page["documents"])
        return page

    def documents_by_id(self, ids: list[str]) -> list[dict]:
        docs = self.repo.get_many([doc_id for doc_id in ids if _ID.fullmatch(doc_id)])
        self._attach_qc(docs)
        return docs

    def _attach_qc(self, docs: list[dict]) -> None:
        if not docs:
            return
        rows = {row["id"]: row for row in self.repo.qc_overview(qc.rule_key(), [doc["id"] for doc in docs])}
        for doc in docs:
            row = rows.get(doc["id"])
            state = self._qc_state(row) if row else None
            label = "규칙 변경 · 다시 대조 대기" if state == "pending" and row and row["stale"] else qc.STATE_LABELS.get(state, "")
            doc["qc"] = {"state": state, "label": label,
                         "unresolved": max(0, (row["spots_total"] or 0) - row["resolved"]) if row and state not in (None, "pending", "unavailable") else None} if state else None

    # ------------------------------------------------------------ 검수 요청(V번호)
    def create_review(self, payload: dict) -> tuple[dict, bool]:
        doc = self.get(payload["document_id"])
        fields = dict(payload)
        run_id = fields.get("run_id")
        if run_id is None:
            runs = self.repo.parse_runs(doc["id"])
            latest = next((run for run in runs if run["is_latest"]), runs[0] if runs else None)
            fields["run_id"] = latest["run_id"] if latest else None
        elif not self.repo.parse_run(doc["id"], run_id):
            raise MissingRun()
        ref = fields.get("finding_id") or fields.get("spot")
        if ref:
            if not fields["run_id"]:
                raise Conflict("성공한 파싱 결과가 없어 자동 대조 지점을 찾을 수 없습니다.")
            # 화면 상세 목록(한 쪽)이 아니라 원장 전체에서 찾는다: 우선순위 밖으로 잘린 지점도 검수 요청이 된다.
            spot = self.finding(doc["id"], fields["run_id"], ref)
            fields["spot"], fields["finding_id"], fields["rule_version"] = spot["key"], spot["id"], spot["rule_version"]
            for key, value in (("kind", spot["kind"]), ("severity", spot["severity"]), ("page", spot["page"]),
                               ("sheet", spot["sheet"]), ("cell", spot["cell"]), ("line", spot["line"]), ("line_end", spot["line_end"]),
                               ("ref", spot["ref"]), ("source_text", spot["source"]), ("source_hit", spot["source_hit"]),
                               ("result_text", spot["result"]), ("result_hit", spot["result_hit"])):
                if fields.get(key) in (None, "") and value not in (None, ""):
                    fields[key] = value
            fields["note"] = fields.get("note") or spot["message"]
        if not (fields.get("note") or "").strip():
            raise Conflict("무엇을 확인할지(note)를 적어 주세요.")
        fields["kind"] = fields.get("kind") or ("agent" if fields.get("origin") == "agent" else "manual")
        return self.repo.create_review(doc["id"], fields)

    def parse_runs(self, doc_id: str) -> list[dict]:
        self.get(doc_id)
        return self.repo.parse_runs(doc_id)

    def parse_run(self, doc_id: str, run_id: str) -> dict:
        self.get(doc_id)
        run = self.repo.parse_run(doc_id, run_id) if _ID.fullmatch(run_id) else None
        if run is None:
            raise MissingRun()
        try:
            markdown = (self.settings.results / f"{doc_id}-{run_id}.md").read_text(encoding="utf-8")
            return {**run, "markdown": markdown, "warnings": json.loads(run["warnings"]), "locations": json.loads(run["locations"]),
                    "fidelity": json.loads(run["fidelity"]) if run.get("fidelity") else None,
                    "evidence": json.loads(run["evidence"]) if run.get("evidence") else None,
                    "options": json.loads(run["options"]) if run.get("options") else None}
        except (OSError, ValueError) as exc:
            raise Conflict("저장된 실행 결과를 읽을 수 없습니다.") from exc

    def inspect(self, doc_id: str) -> dict:
        """원본을 바꾸지 않고 구조(하위 문서·링크)를 분석해 결과를 보관한다. 사용자가 요청할 때만 실행한다."""
        doc = self.get(doc_id)
        result = inspect_file(self._source_path(doc), doc["name"], Budget(signatures=self.settings.drm_signatures))
        payload = {"id": doc_id, "name": doc["name"], "format": doc["format"], "inspected_at": now(), **result}
        target = self.settings.structures / f"{doc_id}.json"
        temp = self.settings.structures / f"{doc_id}.{uuid4().hex}.tmp"
        with open(temp, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False)
        os.replace(temp, target)
        return payload

    def structure(self, doc_id: str) -> dict:
        self.get(doc_id)
        try:
            return json.loads((self.settings.structures / f"{doc_id}.json").read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise Conflict("구조 분석 결과가 없습니다.") from exc
        except (OSError, ValueError) as exc:
            raise Conflict("저장된 구조 분석 결과를 읽을 수 없습니다.") from exc

    def structure_summary(self) -> dict:
        docs = self.repo.list_all()
        total = {"documents_total": len(docs), "inspected": 0, "documents": 0, "derived": 0, "max_depth": 0, "links": 0,
                 "by_child_kind": {}, "by_link_kind": {}, "flags": {}, "with_children": 0, "with_links": 0}
        for doc in docs:
            try:
                summary = json.loads((self.settings.structures / f"{doc['id']}.json").read_text(encoding="utf-8"))["summary"]
            except (OSError, ValueError, KeyError):
                continue
            total["inspected"] += 1
            for key in ("documents", "derived", "links"):
                total[key] += summary.get(key, 0)
            total["max_depth"] = max(total["max_depth"], summary.get("max_depth", 0))
            total["with_children"] += 1 if summary.get("derived") else 0
            total["with_links"] += 1 if summary.get("links") else 0
            for key in ("by_child_kind", "by_link_kind", "flags"):
                for name, count in summary.get(key, {}).items():
                    total[key][name] = total[key].get(name, 0) + count
        total["expansion"] = round(total["documents"] / total["inspected"], 2) if total["inspected"] else None
        return total

    def result(self, doc_id: str) -> dict:
        doc = self.get(doc_id)
        if not doc["result_file"]:
            raise Conflict("완료된 파싱 결과가 없습니다.")
        name = doc["result_file"]
        if not _RESULT_NAME.fullmatch(name) or not name.startswith(doc_id + "-"):
            raise Conflict("저장된 결과를 확인할 수 없습니다.")
        parser = doc.get("result_parser")
        parser_version = doc.get("result_parser_version")
        if not parser or not parser_version:
            raise Conflict("저장된 결과 정보를 확인할 수 없습니다.")
        try:
            markdown = (self.settings.results / name).read_text(encoding="utf-8")
        except OSError as exc:
            raise Conflict("저장된 결과 파일을 찾을 수 없습니다.") from exc
        try:
            warnings = json.loads(doc.get("result_warnings") or "[]")
            if not isinstance(warnings, list) or any(not isinstance(warning, str) for warning in warnings):
                warnings = []
        except (ValueError, TypeError):
            warnings = []
        fidelity = None
        run = self.repo.parse_run(doc_id, name[33:65])
        if run and run.get("fidelity"):
            try:
                fidelity = json.loads(run["fidelity"])
            except ValueError:
                fidelity = None
        return {"id": doc_id, "markdown": markdown, "parser": parser, "parser_version": parser_version, "is_stale": doc["status"] != "completed", "warnings": warnings, "fidelity": fidelity,
                "run_id": name[33:65], "locations": json.loads(run["locations"]) if run and run.get("locations") else []}
