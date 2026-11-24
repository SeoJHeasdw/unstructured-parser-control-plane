"""Local storage and single-worker processing orchestration."""
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
from app.adapters.registry import ParserRegistry, TEXT_FORMATS
from app.config import Settings
from app.adapters.ocr import ModelOcr
from app.fidelity.pictures import PictureOcr
from app.fidelity import OOXML_FORMATS, assess, prepare_copy, prepared_copy_path, probe
from app.filelock import try_lock, unlock
from app.format_gate import check as check_format
from app.repository import DocumentRepository, now
from app.source_preview import worksheet_preview
from app.structure import Budget, inspect_file
from app.textnorm import display_name

logger = logging.getLogger(__name__)
_ID = re.compile(r"^[0-9a-f]{32}$")
_EXT = re.compile(r"^[A-Za-z0-9]{1,20}$")
_RESULT_NAME = re.compile(r"^[0-9a-f]{32}-[0-9a-f]{32}\.md$")
PDF_OCR_WARNING = "OCR 미적용: 스캔·이미지 페이지 내용 누락 가능"
FIDELITY_FAILED_WARNING = "원문 충실도 점검을 하지 못했습니다. 파싱 결과는 그대로 저장했습니다."
PREPARE_FALLBACK_WARNING = "기호·첨자 보정 사본을 파싱하지 못해 원본으로 파싱했습니다. 기호 글꼴·첨자가 빠지거나 붙을 수 있습니다."
_WORK_PREFIX = "docops-prep-"

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
        # If parsing outlives shutdown, the worker retains the process lock until it exits.
        # If the whole process exits first, the OS releases the lock and startup recovery runs.
        if not self._worker or not self._worker.is_alive():
            self._release_lock()

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

    def begin(self, doc_id: str) -> tuple[dict, str]:
        doc = self.get(doc_id)
        run_id = uuid4().hex
        if not self.repo.claim(doc_id, run_id, self.parsers.parser_name(doc["format"])):
            raise Conflict("이미 처리 중인 문서입니다.")
        return self.get(doc_id), run_id

    def enqueue(self, doc_id: str) -> dict:
        with self._admission_lock:
            doc = self.get(doc_id)
            if doc["status"] == "processing":
                raise Conflict("이미 처리 중인 문서입니다.")
            if self._stopping.is_set() or not self._worker or not self._worker.is_alive():
                self.repo.record_event(doc_id, doc["status"], "처리 워커를 사용할 수 없어 요청을 접수하지 못했습니다.")
                raise QueueUnavailable("처리 워커를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.")
            if self._jobs.full():
                self.repo.record_event(doc_id, doc["status"], "처리 대기열이 가득 차 요청을 접수하지 못했습니다.")
                raise QueueUnavailable("처리 대기열이 가득 찼습니다. 잠시 후 다시 시도해 주세요.")
            processing_doc, run_id = self.begin(doc_id)
            try:
                self._jobs.put_nowait((doc_id, run_id))
            except Full:
                self.repo.finish(doc_id, run_id, status="failed", parser=processing_doc.get("parser"), parser_version=None, result_file=None, error="처리 대기열이 가득 차 요청을 접수하지 못했습니다.", error_code="queue_full")
                raise QueueUnavailable("처리 대기열이 가득 찼습니다. 잠시 후 다시 시도해 주세요.")
            return processing_doc

    def process(self, doc_id: str, run_id: str) -> None:
        result_path = None
        temp_path = None
        try:
            doc = self.get(doc_id)
            # Storage names originate from the server, never from the request's filename.
            source_name = doc["source_file"]
            if source_name != Path(source_name).name or not source_name.startswith(doc_id):
                raise ParserError("저장된 파일 경로를 확인할 수 없습니다.")
            path = self.settings.uploads / source_name
            extension = doc["format"]
            if self.parsers.parser_name(extension) is None:
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
                    parsed = self.parsers.text.write_to(path, extension, output)
                    warnings, locations, fidelity, ocr_enabled = [], [], None, None
                else:
                    parsed, prepared, warnings = self._parse(path, extension)
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
                        if not markdown.strip():
                            raise ParserError("Office 본문·그림에서 글자를 추출하지 못했습니다. " + " ".join(warnings[:2]), code="no_text")
                    output.write(markdown)
            duration_ms = round((time.perf_counter() - started) * 1000)
            os.replace(temp_path, result_path)
            if extension == "PDF" and not ocr_enabled:
                warnings.insert(0, PDF_OCR_WARNING)
            committed = False
            try:
                committed = self.repo.finish(doc_id, run_id, status="completed", parser=parsed.parser,
                                             parser_version=parsed.parser_version, result_file=result_name, error=None,
                                             warnings=warnings, ocr_enabled=ocr_enabled, duration_ms=duration_ms,
                                             locations=[location.model_dump() for location in locations], fidelity=fidelity)
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

    def _parse(self, path: Path, extension: str):
        """(파싱 결과, 사본 보정 통계 | None, 경고). OOXML은 원본 대신 보정 사본을 파서에 넣는다."""
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
            if doc["format"] == "XLSX":
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
                    "fidelity": json.loads(run["fidelity"]) if run.get("fidelity") else None}
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
        return {"id": doc_id, "markdown": markdown, "parser": parser, "parser_version": parser_version, "is_stale": doc["status"] != "completed", "warnings": warnings, "fidelity": fidelity}
