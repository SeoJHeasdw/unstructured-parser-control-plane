"""임베딩 평가: 평가 질문 한 벌(버전 관리 없음)과 한 번에 하나만 도는 백그라운드 평가 작업.

질문은 실행 폴더의 retrieval/questions.json, 벡터 캐시는 retrieval/embeddings.sqlite3,
마지막 평가 요약은 retrieval/last_run.json 에 둔다. 질문별 상위 청크 본문은 서버 메모리에만 있다.
"""
from collections import Counter
import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import statistics
import threading
from uuid import uuid4

from app.chunking import (QUESTION_KINDS, SAMPLE_PREFIX, SAMPLES, ChunkingError, Source, estimate_tokens, infer_question_kind,
                          line_pages, normalize_strategy, run_strategy, sample_source)
from app.embedding import (EmbedConnection, EmbedError, VectorCache, embed_batch, mean_metrics, model_key, normalize_phrase,
                           rank_metrics, spec_for, text_hash, top_k, unit_vector, MAX_BATCH, MAX_BATCH_CHARS)

CAPS = {"max_chunks": 5000, "max_questions": 500, "max_presets": 4, "max_candidates": 6, "max_documents": 200,
        "max_question_rows": 2000, "top_k_min": 10, "top_k_max": 50}
_DOC_ID = re.compile(r"^(?:[0-9a-f]{32}|sample:[a-z0-9_-]{1,40})$")  # 실제 문서 또는 합성 예시('sample:<id>')
_ROW_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        with open(temp, "w", encoding="utf-8") as out:
            out.write(text)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


# ---------------------------------------------------------------- 평가 질문

class QuestionError(ValueError):
    pass


_KIND_ALIASES = {"text": "text", "본문": "text", "텍스트": "text", "문단": "text", "table": "table", "표": "table",
                 "image": "image", "그림": "image", "이미지": "image", "figure": "image", "캡션": "image"}


def clean_kind(value) -> str | None:
    """질문 유형(text·table·image, 본문·표·그림도 받는다). 비었거나 모르는 값은 None."""
    if value is None:
        return None
    return _KIND_ALIASES.get(str(value).strip().lower())


def clean_rows(rows) -> list[dict]:
    if not isinstance(rows, list):
        raise QuestionError("질문 목록 형식이 올바르지 않습니다.")
    if len(rows) > CAPS["max_question_rows"]:
        raise QuestionError(f"평가 질문은 {CAPS['max_question_rows']:,}행까지 저장할 수 있습니다.")
    out, seen = [], set()
    for number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise QuestionError(f"{number}행 형식이 올바르지 않습니다.")
        question = str(row.get("question") or "").strip()
        doc_id = str(row.get("doc_id") or "").strip().lower()
        answer = str(row.get("answer") or "").strip()
        if not question:
            raise QuestionError(f"{number}행: 질문이 비어 있습니다.")
        if len(question) > 2000 or len(answer) > 1000:
            raise QuestionError(f"{number}행: 질문은 2,000자, 정답 문구는 1,000자까지 쓸 수 있습니다.")
        if doc_id and not _DOC_ID.fullmatch(doc_id):
            raise QuestionError(f"{number}행: 문서 ID 형식이 올바르지 않습니다.")
        row_id = str(row.get("id") or "")
        if not _ROW_ID.fullmatch(row_id) or row_id in seen:
            row_id = uuid4().hex[:12]
        seen.add(row_id)
        out.append({"id": row_id, "question": question, "doc_id": doc_id, "answer": answer, "kind": clean_kind(row.get("kind"))})
    return out


class QuestionStore:
    def __init__(self, root: Path):
        self.path = root / "questions.json"
        self._lock = threading.Lock()

    def load(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return {"questions": clean_rows(payload.get("questions", [])), "updated_at": payload.get("updated_at")}
        except FileNotFoundError:
            return {"questions": [], "updated_at": None}
        except (OSError, ValueError, AttributeError):
            raise QuestionError("저장된 평가 질문을 읽을 수 없습니다.") from None

    def save(self, rows) -> dict:
        cleaned = clean_rows(rows)
        payload = {"questions": cleaned, "updated_at": _now()}
        with self._lock:
            _atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=1))
        return payload


_ALIASES = {
    "question": {"question", "query", "질문", "질의"},
    "doc_id": {"doc_id", "document_id", "relevant_doc", "relevant_doc_id", "문서id", "문서 id", "정답 문서 id", "정답문서id"},
    "doc_name": {"doc_name", "document", "document_name", "문서", "문서명", "정답 문서", "정답 문서명"},
    "answer": {"answer", "answer_text", "phrase", "정답", "정답 문구", "정답문구"},
    "kind": {"kind", "type", "question_type", "유형", "질문 유형", "질문유형", "정답 위치", "정답위치"},
}


def _field(name: str) -> str | None:
    key = name.strip().lstrip("﻿").lower()
    for field_name, aliases in _ALIASES.items():
        if key in aliases:
            return field_name
    return None


def parse_import(fmt: str, text: str) -> tuple[list[dict], list[str]]:
    """CSV(머리행 자동 인식, 없으면 질문·문서 ID·정답 문구 순서) 또는 JSONL을 행 목록으로 읽는다. 저장하지 않는다."""
    if not isinstance(text, str) or len(text) > 5_000_000:
        raise QuestionError("가져올 내용이 없거나 너무 큽니다.")
    text = text.lstrip("﻿")
    rows: list[dict] = []
    errors: list[str] = []
    if fmt == "csv":
        try:
            records = list(csv.reader(io.StringIO(text, newline="")))
        except csv.Error:
            raise QuestionError("CSV 구조를 읽을 수 없습니다. 구분자와 따옴표를 확인해 주세요.") from None
        records = [r for r in records if any(cell.strip() for cell in r)]
        if not records:
            return [], []
        header = [_field(cell) for cell in records[0]]
        if "question" in header:
            mapping, body, offset = header, records[1:], 2
        else:
            mapping, body, offset = ["question", "doc_id", "answer", "kind"], records, 1
        for number, record in enumerate(body, start=offset):
            row = {name: record[i].strip() for i, name in enumerate(mapping) if name and i < len(record)}
            rows.append({**row, "_line": number})
    elif fmt == "jsonl":
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                errors.append(f"{number}줄: JSON 형식이 아닙니다.")
                continue
            if not isinstance(item, dict):
                errors.append(f"{number}줄: 객체 형식이 아닙니다.")
                continue
            row = {}
            for key, value in item.items():
                name = _field(str(key))
                if name and value is not None:
                    row[name] = str(value).strip()
            rows.append({**row, "_line": number})
    else:
        raise QuestionError("CSV 또는 JSONL만 가져올 수 있습니다.")
    valid = []
    for row in rows:
        line = row.pop("_line")
        if not row.get("question"):
            errors.append(f"{line}행: 질문이 비어 있어 건너뜁니다.")
            continue
        doc_id = row.get("doc_id", "").lower()
        if doc_id and not _DOC_ID.fullmatch(doc_id):
            errors.append(f"{line}행: 문서 ID 형식이 아니어서 문서 이름으로 찾습니다.")
            row.setdefault("doc_name", row.get("doc_id", ""))
            doc_id = ""
        entry = {"question": row["question"][:2000], "doc_id": doc_id, "doc_name": row.get("doc_name", "")[:300], "answer": row.get("answer", "")[:1000]}
        if row.get("kind"):
            kind = clean_kind(row["kind"])
            if kind:
                entry["kind"] = kind
            else:
                errors.append(f"{line}행: 질문 유형 '{row['kind'][:20]}'을(를) 알 수 없어 비워 둡니다(text·table·image).")
        valid.append(entry)
    return valid, errors


def export_rows(fmt: str, rows: list[dict], names: dict[str, str]) -> str:
    if fmt == "jsonl":
        return "".join(json.dumps({"question": r["question"], "doc_id": r["doc_id"], "doc_name": names.get(r["doc_id"], ""), "answer": r["answer"],
                                   "kind": r.get("kind")}, ensure_ascii=False) + "\n" for r in rows)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["question", "doc_id", "doc_name", "answer", "kind"])
    for r in rows:
        writer.writerow([r["question"], r["doc_id"], names.get(r["doc_id"], ""), r["answer"], r.get("kind") or ""])
    return "﻿" + out.getvalue()


# ---------------------------------------------------------------- 실행 계획

class PlanError(ValueError):
    pass


def load_source(service, doc_id: str) -> tuple[dict, Source]:
    """평가·계획에 쓰는 원문. 'sample:<id>'는 합성 예시, 그 밖은 완료된 파싱 결과(줄→쪽 정보 포함)."""
    if doc_id.startswith(SAMPLE_PREFIX):
        sample_id = doc_id[len(SAMPLE_PREFIX):]
        src = sample_source(sample_id)
        if src is None:
            raise PlanError(f"합성 예시 '{sample_id[:40]}'을(를) 찾을 수 없습니다.")
        return {"id": doc_id, "name": SAMPLES[sample_id]["name"]}, src
    from app.service import Conflict, MissingDocument  # 순환 import 방지
    try:
        doc = service.get(doc_id)
    except MissingDocument:
        raise PlanError("선택한 문서를 찾을 수 없습니다. 목록을 새로 고쳐 주세요.") from None
    try:
        result = service.result(doc_id)
    except (MissingDocument, Conflict):
        raise PlanError(f"{doc['name']}: 완료된 파싱 결과가 없습니다.") from None
    try:
        src = Source(result["markdown"], line_pages(result.get("locations"), result["markdown"]))
    except ChunkingError as exc:
        raise PlanError(f"{doc['name']}: {exc}") from None
    return {"id": doc_id, "name": doc["name"]}, src


def preview_plan(body: dict, service, questions: list[dict], embedder_for=None) -> dict:
    """실행 전 계획: 한 프리셋으로 문서를 나눠 모델별 입력 한도 초과와 벡터 용량을 계산한다. 외부 호출이 없다.
    찾을 수 없거나 나눌 수 없는 문서는 errors에 적고 나머지로 계산한다."""
    from app.embedding import spec_for
    if not isinstance(body, dict):
        raise PlanError("요청 형식이 올바르지 않습니다.")
    raw_ids = body.get("doc_ids")
    doc_ids = list(dict.fromkeys(str(d) for d in raw_ids)) if isinstance(raw_ids, list) else []
    if not doc_ids:
        raise PlanError("평가할 문서를 하나 이상 고르세요.")
    if len(doc_ids) > CAPS["max_documents"]:
        raise PlanError(f"문서는 한 번에 {CAPS['max_documents']}개까지 고를 수 있습니다.")
    try:
        preset = normalize_strategy(body.get("preset"))  # type: ignore[arg-type]
    except ChunkingError as exc:
        raise PlanError(str(exc)) from None
    raw_models = body.get("models")
    models = list(dict.fromkeys(str(m).strip()[:200] for m in raw_models if str(m).strip())) if isinstance(raw_models, list) else []
    models = models[: CAPS["max_candidates"] * 2]
    errors: list[str] = []
    tokens: list[int] = []
    loaded: dict[str, Source] = {}
    for doc_id in doc_ids:
        try:
            meta, src = load_source(service, doc_id)
            result = run_strategy(src, preset, embed=embedder_for(preset) if embedder_for and preset["kind"] == "semantic" else None)
        except PlanError as exc:
            errors.append(str(exc))
            continue
        except ChunkingError as exc:
            errors.append(f"{meta['name']}: {exc}")
            continue
        loaded[doc_id] = src
        tokens += [c["est_tokens"] for c in result["chunks"]]
    plan_models = []
    for model in models:
        spec = spec_for(model) or {}
        max_tokens, dims = spec.get("max_tokens") or None, spec.get("dims") or None
        plan_models.append({"model": model, "max_tokens": max_tokens, "dims": dims,
                            "over_limit": sum(1 for t in tokens if max_tokens and t > max_tokens),
                            "storage_bytes": dims * 4 * len(tokens) if dims else None})
    by_kind = {kind: 0 for kind in QUESTION_KINDS}
    for row in questions:
        src = loaded.get(row.get("doc_id") or "")
        if src is not None:
            by_kind[row.get("kind") or infer_question_kind(src, row.get("answer", ""))] += 1
    return {"documents": len(loaded), "chunks": len(tokens), "max_chunk_tokens": max(tokens, default=0),
            "median_chunk_tokens": round(statistics.median(tokens), 1) if tokens else 0,
            "models": plan_models, "questions": {"total": sum(by_kind.values()), "by_kind": by_kind}, "errors": errors[:50]}


@dataclass
class Candidate:
    id: str
    connection: EmbedConnection
    model: str
    query_prefix: str
    doc_prefix: str
    max_tokens: int | None
    batch_size: int

    def public(self) -> dict:
        return {"id": self.id, "connection": self.connection.key, "connection_label": self.connection.label, "model": self.model,
                "query_prefix": self.query_prefix, "doc_prefix": self.doc_prefix, "max_tokens": self.max_tokens, "batch_size": self.batch_size}


@dataclass
class Plan:
    documents: list[dict]
    presets: list[dict]
    corpora: dict[str, list[dict]]
    candidates: list[Candidate]
    questions: list[dict]
    skipped: dict
    top_k: int
    normalized: dict = field(default_factory=dict)  # preset id -> 정답 문구 비교용 본문

    def public(self) -> dict:
        return {"documents": self.documents, "presets": self.presets, "candidates": [c.public() for c in self.candidates],
                "questions": len(self.questions), "skipped": self.skipped, "top_k": self.top_k,
                "chunks": {pid: len(chunks) for pid, chunks in self.corpora.items()}}


def _int(value, default: int, lo: int, hi: int, name: str) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise PlanError(f"{name} 값은 정수여야 합니다.") from None
    return min(hi, max(lo, number))


def build_plan(body: dict, service, questions: list[dict], connections: list[EmbedConnection], embedder_for=None) -> Plan:
    """요청을 검증하고 문서를 미리 청킹해 한도를 확인한다. 이 단계에서는 외부 호출이 없다."""
    if not isinstance(body, dict):
        raise PlanError("요청 형식이 올바르지 않습니다.")
    doc_ids = list(dict.fromkeys(str(d) for d in body.get("doc_ids") or []))
    if not doc_ids:
        raise PlanError("평가할 문서를 하나 이상 고르세요.")
    if len(doc_ids) > CAPS["max_documents"]:
        raise PlanError(f"문서는 한 번에 {CAPS['max_documents']}개까지 고를 수 있습니다.")
    documents, sources = [], {}
    for doc_id in doc_ids:
        meta, sources[doc_id] = load_source(service, doc_id)
        documents.append(meta)
    raw_presets = body.get("presets") or []
    if not raw_presets or len(raw_presets) > CAPS["max_presets"]:
        raise PlanError(f"청킹 프리셋을 1~{CAPS['max_presets']}개 고르세요.")
    presets = []
    for raw in raw_presets:
        try:
            preset = normalize_strategy(raw)
        except ChunkingError as exc:
            raise PlanError(str(exc)) from None
        if any(p["id"] == preset["id"] for p in presets):
            raise PlanError("같은 프리셋이 두 번 선택되었습니다.")
        presets.append(preset)
    raw_candidates = body.get("candidates") or []
    if not raw_candidates or len(raw_candidates) > CAPS["max_candidates"]:
        raise PlanError(f"임베딩 후보를 1~{CAPS['max_candidates']}개 고르세요.")
    by_key = {c.key: c for c in connections}
    candidates: list[Candidate] = []
    for index, raw in enumerate(raw_candidates, start=1):
        if not isinstance(raw, dict):
            raise PlanError("후보 형식이 올바르지 않습니다.")
        conn = by_key.get(str(raw.get("connection") or ""))
        if not conn or not conn.configured:
            raise PlanError(f"후보 {index}: 설정된 연결을 고르세요.")
        model = str(raw.get("model") or "").strip()
        if not model or len(model) > 200:
            raise PlanError(f"후보 {index}: 모델 ID가 필요합니다.")
        query_prefix, doc_prefix = str(raw.get("query_prefix") or ""), str(raw.get("doc_prefix") or "")
        if len(query_prefix) > 1000 or len(doc_prefix) > 1000:
            raise PlanError(f"후보 {index}: 접두어는 1,000자까지 쓸 수 있습니다.")
        spec = spec_for(model)
        max_tokens = _int(raw.get("max_tokens"), (spec or {}).get("max_tokens") or 0, 0, 1_000_000, "최대 토큰")
        cid = str(raw.get("id") or f"c{index}")[:64]
        if any(c.id == cid for c in candidates):
            cid = f"{cid}-{index}"
        candidates.append(Candidate(cid, conn, model, query_prefix, doc_prefix, max_tokens or None,
                                    _int(raw.get("batch_size"), 16, 1, MAX_BATCH, "묶음 크기")))
    selected = set(doc_ids)
    chosen, skipped = [], {"no_document": 0, "not_selected": 0}
    for row in questions:
        if not row.get("doc_id"):
            skipped["no_document"] += 1
        elif row["doc_id"] not in selected:
            skipped["not_selected"] += 1
        else:
            kind = row.get("kind") or infer_question_kind(sources[row["doc_id"]], row.get("answer", ""))
            chosen.append({"index": len(chosen), "id": row["id"], "question": row["question"], "doc_id": row["doc_id"],
                           "answer": row.get("answer", ""), "kind": kind})
    if not chosen:
        raise PlanError("선택한 문서에 연결된 평가 질문이 없습니다. 질문에 정답 문서를 지정해 주세요.")
    if len(chosen) > CAPS["max_questions"]:
        raise PlanError(f"질문은 한 번에 {CAPS['max_questions']}개까지 평가할 수 있습니다. 현재 {len(chosen):,}개입니다.")
    corpora: dict[str, list[dict]] = {}
    for preset in presets:
        chunks: list[dict] = []
        for doc in documents:
            try:
                result = run_strategy(sources[doc["id"]], preset, embed=embedder_for(preset) if embedder_for and preset["kind"] == "semantic" else None)
            except ChunkingError as exc:
                raise PlanError(f"{doc['name']}: {exc}") from None
            for c in result["chunks"]:
                chunks.append({"doc_id": doc["id"], "index": c["index"], "text": c["text"], "heading_path": c["heading_path"], "est_tokens": c["est_tokens"], "chars": c["chars"]})
            if len(chunks) > CAPS["max_chunks"]:
                raise PlanError(f"{preset['name']}: 청크가 {CAPS['max_chunks']:,}개를 넘습니다. 문서를 줄이거나 청크 크기를 늘려 주세요.")
        if not chunks:
            raise PlanError(f"{preset['name']}: 만들어진 청크가 없습니다.")
        corpora[preset["id"]] = chunks
    top = _int(body.get("top_k"), 10, CAPS["top_k_min"], CAPS["top_k_max"], "상위 k")
    plan = Plan(documents, presets, corpora, candidates, chosen, skipped, top)
    plan.normalized = {pid: [normalize_phrase(c["text"]) for c in chunks] for pid, chunks in corpora.items()}
    return plan


# ---------------------------------------------------------------- 실행

class Cancelled(Exception):
    pass


@dataclass
class Usage:
    latencies: list = field(default_factory=list)
    seconds: float = 0.0
    embedded: int = 0
    cached: int = 0
    failures: int = 0
    over_limit_failed: int = 0
    errors: list = field(default_factory=list)
    usage_tokens: int = 0
    usage_estimated: int = 0

    def record(self, response, inputs: list[str]) -> None:
        self.latencies.append(response.seconds * 1000)
        self.seconds += response.seconds
        self.embedded += len(inputs)
        if response.prompt_tokens is not None:
            self.usage_tokens += response.prompt_tokens
            self.usage_estimated += sum(estimate_tokens(text) for text in inputs)

    def fail(self, exc: EmbedError) -> None:
        self.failures += 1
        self.over_limit_failed += 1 if exc.over_limit else 0
        message = str(exc)
        if message not in self.errors and len(self.errors) < 5:
            self.errors.append(message)


class EvalRun:
    def __init__(self, plan: Plan, cache: VectorCache, root: Path):
        self.id = uuid4().hex[:12]
        self.plan = plan
        self.cache = cache
        self.root = root
        self.status = "running"
        self.error: str | None = None
        self.created_at = _now()
        self.finished_at: str | None = None
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()
        q = len(plan.questions)
        per_candidate = q + sum(len(c) for c in plan.corpora.values()) + q * len(plan.presets)
        self.progress = {"done": 0, "total": per_candidate * len(plan.candidates), "phase": "준비 중", "detail": ""}
        self.results: list[dict] = []
        self.tops: dict[str, list] = {}

    # -- 진행 상태
    def _advance(self, amount: int, phase: str | None = None, detail: str | None = None) -> None:
        with self.lock:
            self.progress["done"] = min(self.progress["total"], self.progress["done"] + amount)
            if phase is not None:
                self.progress["phase"] = phase
            if detail is not None:
                self.progress["detail"] = detail

    def _check(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled()

    def snapshot(self) -> dict:
        with self.lock:
            return {"id": self.id, "status": self.status, "created_at": self.created_at, "finished_at": self.finished_at,
                    "error": self.error, "progress": dict(self.progress), "drilldown": True, "caps": CAPS,
                    "request": self.plan.public(), "questions": self.plan.questions, "results": list(self.results)}

    # -- 임베딩
    def _call(self, conn, inputs: list[str], usage: Usage) -> list:
        try:
            response = embed_batch(conn, inputs)
            usage.record(response, inputs)
            return response.vectors
        except EmbedError as exc:
            if exc.fatal:
                raise
            if len(inputs) == 1:
                usage.fail(exc)
                return [None]
        out = []
        for text in inputs:  # 입력 하나 때문에 묶음 전체가 실패하지 않도록 하나씩 다시 보낸다
            self._check()
            try:
                response = embed_batch(conn, [text])
                usage.record(response, [text])
                out.append(response.vectors[0])
            except EmbedError as exc:
                if exc.fatal:
                    raise
                usage.fail(exc)
                out.append(None)
        return out

    def _embed(self, cand: Candidate, prefix: str, texts: list[str], usage: Usage, label: str) -> list:
        conn = cand.connection.for_model(cand.model)
        mkey = model_key(conn)
        shas = [text_hash(t) for t in texts]
        cached = self.cache.get_many(mkey, prefix, shas)
        vectors: list = [None] * len(texts)
        groups: dict[str, list[int]] = {}
        for i, sha in enumerate(shas):
            if sha in cached:
                vectors[i] = unit_vector(cached[sha])
                usage.cached += 1
            else:
                groups.setdefault(sha, []).append(i)
        self._advance(len(texts) - sum(len(v) for v in groups.values()), detail=label)
        pending = list(groups)
        start = 0
        while start < len(pending):
            self._check()
            batch, chars = [], 0
            while start < len(pending) and len(batch) < cand.batch_size:
                size = len(prefix) + len(texts[groups[pending[start]][0]])
                if batch and chars + size > MAX_BATCH_CHARS:
                    break
                batch.append(pending[start])
                chars += size
                start += 1
            inputs = [prefix + texts[groups[sha][0]] for sha in batch]
            store = []
            for sha, vec in zip(batch, self._call(conn, inputs, usage)):
                if vec is None:
                    continue
                store.append((sha, vec))
                unit = unit_vector(vec)
                for i in groups[sha]:
                    vectors[i] = unit
            self.cache.put_many(mkey, prefix, store)
            self._advance(sum(len(groups[sha]) for sha in batch))
        return vectors

    # -- 실행 본체
    def execute(self) -> None:
        try:
            for cand in self.plan.candidates:
                self._check()
                self._run_candidate(cand)
            final = "completed"
        except Cancelled:
            final = "cancelled"
        except Exception as exc:  # noqa: BLE001 - 작업 스레드가 조용히 죽지 않게 한다
            final = "failed"
            with self.lock:
                self.error = f"평가 중 오류가 발생했습니다 ({type(exc).__name__})."
        with self.lock:
            self.status = final
            self.finished_at = _now()
            if final == "completed":
                self.progress["done"] = self.progress["total"]
            self.progress["phase"] = {"completed": "완료", "cancelled": "취소됨", "failed": "실패"}[final]
        self._persist()

    def _failed_combo(self, cand: Candidate, preset: dict, message: str) -> dict:
        return {"key": f"{cand.id}::{preset['id']}", "candidate_id": cand.id, "preset_id": preset["id"], "model": cand.model,
                "connection": cand.connection.key, "connection_label": cand.connection.label, "preset_name": preset["name"],
                "preset_kind": preset["kind"], "status": "failed", "error": message, "doc": None, "span": None,
                "chunks": len(self.plan.corpora[preset["id"]]), "documents": len(self.plan.documents), "per_question": []}

    def _run_candidate(self, cand: Candidate) -> None:
        plan = self.plan
        q_usage = Usage()
        per_candidate_units = len(plan.questions) + sum(len(plan.corpora[p["id"]]) + len(plan.questions) for p in plan.presets)
        done_before = self.progress["done"]
        try:
            self._advance(0, phase=f"{cand.model}", detail="질문 임베딩")
            q_vecs = self._embed(cand, cand.query_prefix, [q["question"] for q in plan.questions], q_usage, "질문 임베딩")
        except EmbedError as exc:
            with self.lock:
                self.results += [self._failed_combo(cand, p, str(exc)) for p in plan.presets]
            self._advance(max(0, done_before + per_candidate_units - self.progress["done"]))
            return
        for preset in plan.presets:
            self._check()
            chunks = plan.corpora[preset["id"]]
            c_usage = Usage()
            before = self.progress["done"]
            try:
                c_vecs = self._embed(cand, cand.doc_prefix, [c["text"] for c in chunks], c_usage, f"{preset['name']} · 청크 임베딩")
            except EmbedError as exc:
                with self.lock:
                    self.results.append(self._failed_combo(cand, preset, str(exc)))
                self._advance(max(0, before + len(chunks) + len(plan.questions) - self.progress["done"]))
                continue
            self._advance(0, detail=f"{preset['name']} · 검색 점수 계산")
            combo = self._score(cand, preset, chunks, q_vecs, c_vecs, q_usage, c_usage)
            with self.lock:
                self.results.append(combo)

    def _score(self, cand: Candidate, preset: dict, chunks: list[dict], q_vecs: list, c_vecs: list, q_usage: Usage, c_usage: Usage) -> dict:
        plan = self.plan
        key = f"{cand.id}::{preset['id']}"
        k = max(10, plan.top_k)
        doc_of = [c["doc_id"] for c in chunks]
        per_doc: dict[str, list[int]] = {}
        for i, d in enumerate(doc_of):
            per_doc.setdefault(d, []).append(i)
        norm = plan.normalized[preset["id"]]
        dims = Counter(len(v) for v in list(c_vecs) + list(q_vecs) if v is not None)
        common_dims = dims.most_common(1)[0][0] if dims else None
        if len(dims) > 1:
            # 차원이 섞이면 내적이 무의미하다. 다른 차원 벡터는 비교에서 뺀다.
            c_vecs = [v if v is not None and len(v) == common_dims else None for v in c_vecs]
            q_vecs = [v if v is not None and len(v) == common_dims else None for v in q_vecs]
        doc_rows, span_rows, per_question, tops = [], [], [], []
        kind_rows: dict[str, dict[str, list]] = {kind: {"doc": [], "span": []} for kind in QUESTION_KINDS}
        phrase_missing = 0
        for q in plan.questions:
            self._check()
            qv = q_vecs[q["index"]]
            if qv is None:
                per_question.append({"failed": True, "doc_rank": None, "span_rank": None})
                tops.append(None)
                self._advance(1)
                continue
            top = top_k(qv, c_vecs, k)
            tops.append(top)
            target = q["doc_id"]
            doc_m = rank_metrics([doc_of[i] == target for i, _ in top], len(per_doc.get(target, [])))
            doc_rows.append(doc_m)
            rows_for_kind = kind_rows.setdefault(q.get("kind") or "text", {"doc": [], "span": []})
            rows_for_kind["doc"].append(doc_m)
            entry = {"doc_rank": doc_m["rank"], "span_rank": None, "top_score": round(top[0][1], 4) if top else None}
            if q["answer"]:
                phrase = normalize_phrase(q["answer"])
                holders = [i for i in per_doc.get(target, []) if phrase and phrase in norm[i]]
                if not holders:
                    phrase_missing += 1
                span_m = rank_metrics([doc_of[i] == target and bool(phrase) and phrase in norm[i] for i, _ in top], len(holders))
                span_rows.append(span_m)
                rows_for_kind["span"].append(span_m)
                entry["span_rank"] = span_m["rank"]
                entry["phrase_found"] = bool(holders)
            per_question.append(entry)
            self._advance(1)
        self.tops[key] = tops
        max_tokens = cand.max_tokens
        prefix_tokens = estimate_tokens(cand.doc_prefix) if cand.doc_prefix else 0
        over_limit = sum(1 for c in chunks if max_tokens and c["est_tokens"] + prefix_tokens > max_tokens)
        mkey = model_key(cand.connection.for_model(cand.model))
        throughput, source = None, None
        if c_usage.embedded and c_usage.seconds > 0:
            throughput, source = c_usage.embedded / c_usage.seconds, "measured"
            self.cache.record_throughput(mkey, c_usage.embedded, c_usage.seconds, len(c_usage.latencies))
        else:
            previous = self.cache.throughput(mkey)
            if previous and previous["seconds"] > 0:
                throughput, source = previous["items"] / previous["seconds"], "previous"
        latencies = q_usage.latencies + c_usage.latencies
        ratio_tokens = q_usage.usage_tokens + c_usage.usage_tokens
        ratio_est = q_usage.usage_estimated + c_usage.usage_estimated
        errors = c_usage.errors + [e for e in q_usage.errors if e not in c_usage.errors]
        return {
            "key": key, "candidate_id": cand.id, "preset_id": preset["id"], "model": cand.model, "connection": cand.connection.key,
            "connection_label": cand.connection.label, "preset_name": preset["name"], "preset_kind": preset["kind"],
            "status": "ok", "error": errors[0] if errors else None, "errors": errors,
            "doc": mean_metrics(doc_rows), "span": mean_metrics(span_rows), "questions": len(doc_rows), "span_questions": len(span_rows),
            "by_kind": {kind: {"questions": len(rows["doc"]), "doc": mean_metrics(rows["doc"]), "span": mean_metrics(rows["span"])}
                        for kind, rows in kind_rows.items()},
            "phrase_missing": phrase_missing, "chunks": len(chunks), "documents": len(plan.documents),
            "dims": common_dims, "dims_consistent": len(dims) <= 1,
            "latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else None, "requests": len(latencies),
            "chunks_per_sec": round(throughput, 2) if throughput else None, "throughput_source": source,
            "embedded": c_usage.embedded, "cached": c_usage.cached, "failures": c_usage.failures, "query_failures": q_usage.failures,
            "over_limit": over_limit, "over_limit_failed": c_usage.over_limit_failed, "max_tokens": max_tokens,
            "token_ratio": round(ratio_tokens / ratio_est, 3) if ratio_tokens and ratio_est else None,
            "storage_bytes": (common_dims or 0) * 4 * len(chunks),
            "per_question": per_question,
        }

    def drilldown(self, combo_key: str, index: int) -> dict | None:
        tops = self.tops.get(combo_key)
        if tops is None or not 0 <= index < len(tops):
            return None
        preset_id = combo_key.split("::", 1)[1]
        chunks = self.plan.corpora.get(preset_id, [])
        norm = self.plan.normalized.get(preset_id, [])
        question = self.plan.questions[index]
        phrase = normalize_phrase(question["answer"]) if question["answer"] else ""
        names = {d["id"]: d["name"] for d in self.plan.documents}
        results = []
        for rank, (i, score) in enumerate(tops[index] or [], start=1):
            c = chunks[i]
            hit_doc = c["doc_id"] == question["doc_id"]
            results.append({"rank": rank, "score": round(score, 4), "doc_id": c["doc_id"], "doc_name": names.get(c["doc_id"], ""),
                            "chunk_index": c["index"], "heading_path": c["heading_path"], "chars": c["chars"], "est_tokens": c["est_tokens"],
                            "text": c["text"], "hit_doc": hit_doc, "hit_span": bool(phrase) and hit_doc and phrase in norm[i]})
        return {"combo": combo_key, "question": question, "failed": tops[index] is None, "results": results[: self.plan.top_k]}

    def _persist(self) -> None:
        try:
            summary = self.snapshot()
            summary["drilldown"] = False
            _atomic_write(self.root / "last_run.json", json.dumps(summary, ensure_ascii=False))
        except (OSError, TypeError, ValueError):
            pass


class Busy(Exception):
    pass


class RunManager:
    """한 번에 평가 하나. 마지막 평가 요약은 서버를 다시 켜도 볼 수 있다."""

    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()
        self.run: EvalRun | None = None

    def cache(self) -> VectorCache:
        return VectorCache(self.root / "embeddings.sqlite3")

    def start(self, plan: Plan) -> EvalRun:
        with self.lock:
            if self.run and self.run.status == "running":
                raise Busy()
            run = EvalRun(plan, self.cache(), self.root)
            self.run = run
            threading.Thread(target=run.execute, name="embedding-eval", daemon=True).start()
            return run

    def current(self) -> dict | None:
        with self.lock:
            run = self.run
        if run:
            return run.snapshot()
        try:
            return json.loads((self.root / "last_run.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def cancel(self) -> bool:
        with self.lock:
            if self.run and self.run.status == "running":
                self.run.cancel_event.set()
                return True
        return False

    def drilldown(self, combo_key: str, index: int) -> dict | None:
        with self.lock:
            run = self.run
        return run.drilldown(combo_key, index) if run else None
