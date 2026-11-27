"""청킹 벤치와 임베딩 평가 API. 외부 모델 호출은 사용자가 누른 요청(토큰 측정·평가 실행)에서만 한다."""
import threading
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import Response

from app.chunking import (EXAMPLE_QUESTIONS, MAX_CHUNKS, MAX_SOURCE_CHARS, SAMPLE_MARKDOWN, SAMPLE_NAME, SAMPLE_PREFIX, SAMPLES,
                          STRATEGY_LABELS, ChunkingError, NeedsEmbedding, Source, describe_source, estimate_tokens, line_pages,
                          normalize_strategy, run_strategy, sample_list, sample_source)
from app.embedding import MODEL_SPECS, EmbedError, embed_batch, embed_connections, find_connection, semantic_embedder
from app.retrieval_jobs import (CAPS, Busy, PlanError, QuestionError, QuestionStore, RunManager, build_plan, export_rows, parse_import,
                                preview_plan)
from app.chunk_qc import MAX_FINDINGS as MAX_QC_FINDINGS, annotate, text_hash
from app.service import Conflict, MissingDocument


def _local_only(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    try:
        parsed = urlsplit(origin)
        allowed = parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        allowed = False
    if not allowed:
        raise HTTPException(403, "로컬 화면에서만 사용할 수 있습니다.")


router = APIRouter(prefix="/api/retrieval", tags=["chunking and embedding bench"], dependencies=[Depends(_local_only)])
_STATE_LOCK = threading.Lock()
MAX_COMPARE = 6
MAX_PARALLEL_STRATEGIES = 4
MAX_MEASURE_TEXTS = 16
MAX_MEASURE_CHARS = 60_000


def _root(request: Request):
    return request.app.state.settings.runtime_dir / "retrieval"


def _runs(request: Request) -> RunManager:
    with _STATE_LOCK:
        manager = getattr(request.app.state, "retrieval_runs", None)
        if manager is None:
            manager = RunManager(_root(request))
            request.app.state.retrieval_runs = manager
        return manager


def _questions(request: Request) -> QuestionStore:
    return QuestionStore(_root(request))


def _completed(request: Request) -> list[dict]:
    docs = request.app.state.documents.repo.list_all()
    return [{"id": d["id"], "name": d["name"], "format": d["format"], "status": d["status"], "updated_at": d["updated_at"],
             "is_stale": d["status"] != "completed"} for d in docs if d.get("result_file")]


@router.get("/config")
def config(request: Request):
    connections = embed_connections()
    try:
        cache = _runs(request).cache().stats()
    except OSError:
        cache = {"entries": 0, "bytes": 0}
    return {"connections": [c.public() for c in connections], "configured": any(c.configured for c in connections),
            "specs": list(MODEL_SPECS), "strategies": STRATEGY_LABELS,
            "caps": {**CAPS, "max_parallel_strategies": MAX_PARALLEL_STRATEGIES, "max_source_chars": MAX_SOURCE_CHARS, "max_bench_chunks": MAX_CHUNKS}, "cache": cache}


@router.get("/documents")
def documents(request: Request):
    return {"documents": _completed(request)}


@router.get("/sample")
def sample():
    """절차서 예시 원문."""
    return {"name": SAMPLE_NAME, "text": SAMPLE_MARKDOWN}


@router.get("/samples")
def samples():
    """합성 예시 문서 목록(원문 제외). 원문은 /chunk에 source.sample로 요청한다."""
    return {"samples": sample_list()}


def _load_source(source, request: Request) -> tuple[Source, dict]:
    if not isinstance(source, dict):
        raise HTTPException(400, "원문을 고르세요.")
    doc_id = str(source.get("doc_id") or "")
    sample_id = source.get("sample") or (doc_id[len(SAMPLE_PREFIX):] if doc_id.startswith(SAMPLE_PREFIX) else None)
    if sample_id:
        src = sample_source(str(sample_id))
        if src is None:
            raise HTTPException(404, "합성 예시를 찾을 수 없습니다.")
        return src, {"doc_id": None, "sample": str(sample_id), "name": SAMPLES[str(sample_id)]["name"], "is_stale": False}
    if doc_id:
        service = request.app.state.documents
        try:
            doc = service.get(doc_id)
            result = service.result(doc["id"])
        except MissingDocument:
            raise HTTPException(404, "문서를 찾을 수 없습니다.") from None
        except Conflict as exc:
            raise HTTPException(409, str(exc)) from None
        text, pages = result["markdown"], line_pages(result.get("locations"), result["markdown"])
        meta = {"doc_id": doc["id"], "sample": None, "name": doc["name"], "is_stale": result["is_stale"],
                "run_id": result.get("run_id"), "text_sha256": text_hash(text), "_locations": result.get("locations") or []}
    else:
        text = source.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(400, "나눌 텍스트가 비어 있습니다.")
        pages = None
        meta = {"doc_id": None, "sample": None, "name": str(source.get("name") or "직접 입력")[:120], "is_stale": False}
    try:
        return Source(text, pages), meta
    except ChunkingError as exc:
        raise HTTPException(413, str(exc)) from None


def _semantic_target(params: dict) -> tuple:
    """의미 기반 전략의 (연결, 모델 ID, 문제)."""
    params = params if isinstance(params, dict) else {}
    conn = find_connection(str(params.get("connection") or "embed"))
    if not conn or not conn.configured:
        return None, "", "임베딩 연결이 없습니다. 설정 › 임베딩 모델에서 게이트웨이를 연결하세요."
    model = str(params.get("model") or "").strip() or (conn.models[0] if conn.models else "")
    if not model:
        return None, "", "임베딩 모델 ID가 없습니다. 설정 › 임베딩 모델에서 모델을 추가하세요."
    return conn, model, ""


def _embedder_for(request: Request, allow_calls: bool):
    def build(preset: dict):
        conn, model, problem = _semantic_target(preset.get("params"))
        if problem:
            raise ChunkingError(problem)
        return semantic_embedder(conn.for_model(model), _runs(request).cache(), allow_calls)
    return build


@router.post("/chunk")
def chunk(request: Request, body: dict = Body(...)):
    strategies = body.get("strategies")
    if not isinstance(strategies, list) or not 1 <= len(strategies) <= MAX_COMPARE:
        raise HTTPException(400, f"청킹 전략을 1~{MAX_COMPARE}개 보내 주세요.")
    parallelism = body.get("parallelism", 1)
    if type(parallelism) is not int or not 1 <= parallelism <= MAX_PARALLEL_STRATEGIES:
        raise HTTPException(400, f"전략 병렬 수는 1~{MAX_PARALLEL_STRATEGIES} 사이의 정수여야 합니다.")
    src, meta = _load_source(body.get("source"), request)
    limit = body.get("limit_tokens")
    limit = int(limit) if isinstance(limit, (int, float)) and not isinstance(limit, bool) and limit > 0 else None

    allow_calls = body.get("embed") is True

    def evaluate(index):
        spec = strategies[index]
        sid = str(spec.get("id") or index) if isinstance(spec, dict) else str(index)
        empty = {"chunks": [], "stats": None, "outcomes": {}, "by_kind": {}}
        try:
            embed, model = None, ""
            if isinstance(spec, dict) and spec.get("kind") == "semantic":
                conn, model, problem = _semantic_target(spec.get("params"))
                if problem:
                    return {**normalize_strategy(spec), "error": problem, **empty}
                embed = semantic_embedder(conn.for_model(model), _runs(request).cache(), allow_calls)
            result = run_strategy(src, spec, limit, embed)
            if model:
                result["semantic"]["model"] = model
            if body.get("summary_only") is True:
                return {"id": sid, "kind": result["kind"], "stats": result["stats"]}
            return result
        except NeedsEmbedding as exc:
            return {**normalize_strategy(spec), "pending": {"missing": exc.missing, "total": exc.total, "model": model}, **empty}
        except ChunkingError as exc:
            return {"id": sid, "error": str(exc), **empty}

    # 공유 풀(main.py)이 여러 탭의 동시 비교 작업 수를 묶는다.
    results = []
    for start in range(0, len(strategies), parallelism):
        batch = range(start, min(start + parallelism, len(strategies)))
        results.extend(request.app.state.chunk_pool.map(evaluate, batch))
    locations = meta.pop("_locations", None)
    if body.get("summary_only") is True:
        return {"source": meta, "results": results}
    if meta.get("doc_id") and meta.get("run_id"):
        meta["qc"] = _annotate_qc(request, meta, src.text, locations, results)
    return {"source": {**meta, **describe_source(src), "text": src.text}, "results": results}


def _annotate_qc(request: Request, meta: dict, text: str, locations, results: list[dict]) -> dict | None:
    """청크마다 덮는 쪽·시트와 사람이 아직 판정하지 않은 의심점을 붙인다. 원장이 없으면(원본을 못 읽음 등) 위치만 붙인다."""
    service = request.app.state.documents
    try:
        entries, gate = service.chunk_findings(meta["doc_id"], meta["run_id"], MAX_QC_FINDINGS)
    except Exception:  # noqa: BLE001 — 대조를 못 해도 청킹 결과는 준다
        annotate(results, text, [], locations)
        return None
    annotate(results, text, entries, locations)
    statuses = [(entry.get("review") or {}).get("status") for entry in entries]
    return {"state": gate.get("state"), "label": gate.get("label"), "unresolved": gate.get("unresolved"), "attached": len(entries),
            "wrong": statuses.count("wrong"), "unclear": statuses.count("unclear"), "open_reviews": gate.get("open_reviews")}


@router.post("/tokens")
def measure_tokens(request: Request, body: dict = Body(...)):
    """표본 청크를 하나씩 보내 게이트웨이가 돌려주는 usage.prompt_tokens로 실제 토큰 수를 잰다."""
    conn = find_connection(str(body.get("connection") or ""))
    if not conn or not conn.configured:
        raise HTTPException(409, "임베딩 연결이 설정되지 않았습니다.")
    model = str(body.get("model") or "").strip()
    texts = body.get("texts")
    if not model or not isinstance(texts, list) or not texts or len(texts) > MAX_MEASURE_TEXTS:
        raise HTTPException(400, f"모델과 표본 텍스트(최대 {MAX_MEASURE_TEXTS}개)가 필요합니다.")
    if any(not isinstance(t, str) or not t or len(t) > MAX_MEASURE_CHARS for t in texts):
        raise HTTPException(400, f"표본은 1~{MAX_MEASURE_CHARS:,}자 텍스트여야 합니다.")
    target = conn.for_model(model)
    items, dims = [], None
    for text in texts:
        try:
            response = embed_batch(target, [text])
        except EmbedError as exc:
            items.append({"tokens": None, "est_tokens": estimate_tokens(text), "error": str(exc), "over_limit": exc.over_limit})
            if exc.fatal:
                break
            continue
        dims = len(response.vectors[0])
        items.append({"tokens": response.prompt_tokens, "est_tokens": estimate_tokens(text), "error": None, "latency_ms": round(response.seconds * 1000, 1)})
    return {"model": model, "connection": conn.key, "dims": dims, "items": items,
            "usage_reported": any(item.get("tokens") is not None for item in items)}


# ---------------------------------------------------------------- 평가 질문

@router.get("/questions")
def get_questions(request: Request):
    try:
        return _questions(request).load()
    except QuestionError as exc:
        raise HTTPException(409, str(exc)) from None


@router.put("/questions")
def put_questions(request: Request, body: dict = Body(...)):
    try:
        return _questions(request).save(body.get("questions"))
    except QuestionError as exc:
        raise HTTPException(400, str(exc)) from None


@router.get("/questions/example")
def example_questions():
    """합성 예시 문서에 맞춘 예시 질문."""
    return {"questions": [dict(q) for q in EXAMPLE_QUESTIONS]}


def _doc_names(request: Request) -> dict[str, str]:
    names = {d["id"]: d["name"] for d in _completed(request)}
    names.update({SAMPLE_PREFIX + sid: sample["name"] for sid, sample in SAMPLES.items()})
    return names


@router.post("/questions/parse")
def parse_questions(request: Request, body: dict = Body(...)):
    """CSV/JSONL을 읽어 행으로 돌려준다. 문서 ID가 없으면 문서 이름으로 찾는다."""
    try:
        rows, errors = parse_import(str(body.get("format") or ""), body.get("text"))
    except QuestionError as exc:
        raise HTTPException(400, str(exc)) from None
    by_name: dict[str, list[str]] = {}
    known = set()
    for doc_id, name in _doc_names(request).items():
        known.add(doc_id)
        by_name.setdefault(name.strip().lower(), []).append(doc_id)
    out = []
    for number, row in enumerate(rows, start=1):
        doc_id = row["doc_id"]
        if not doc_id and row.get("doc_name"):
            matches = by_name.get(row["doc_name"].strip().lower(), [])
            if len(matches) == 1:
                doc_id = matches[0]
            else:
                errors.append(f"{number}번째 질문: 문서 '{row['doc_name'][:60]}'을(를) {'여러 개 찾아' if matches else '찾지 못해'} 비워 둡니다.")
        elif doc_id and doc_id not in known:
            errors.append(f"{number}번째 질문: 완료된 문서 목록에 없는 문서 ID입니다.")
        out.append({"question": row["question"], "doc_id": doc_id, "answer": row["answer"], "kind": row.get("kind")})
    return {"questions": out, "errors": errors[:50], "error_count": len(errors)}


@router.get("/questions/export")
def export_questions(request: Request, format: str = "csv"):
    if format not in ("csv", "jsonl"):
        raise HTTPException(400, "CSV 또는 JSONL만 내보낼 수 있습니다.")
    try:
        rows = _questions(request).load()["questions"]
    except QuestionError as exc:
        raise HTTPException(409, str(exc)) from None
    names = _doc_names(request)
    media = "text/csv; charset=utf-8" if format == "csv" else "application/x-ndjson; charset=utf-8"
    return Response(export_rows(format, rows, names), media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="retrieval-questions.{format}"'})


# ---------------------------------------------------------------- 평가 실행

@router.post("/plan")
def plan_run(request: Request, body: dict = Body(...)):
    """실행 전 계획(외부 호출 없음): 고른 청킹으로 나눈 청크 수, 모델별 입력 한도 초과·벡터 용량, 유형별 질문 수."""
    try:
        questions = _questions(request).load()["questions"]
    except QuestionError:
        questions = []
    try:
        return preview_plan(body, request.app.state.documents, questions, _embedder_for(request, allow_calls=False))
    except PlanError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/runs", status_code=202)
def start_run(request: Request, body: dict = Body(...)):
    runs = _runs(request)
    try:
        questions = _questions(request).load()["questions"]
        plan = build_plan(body, request.app.state.documents, questions, embed_connections(), _embedder_for(request, allow_calls=True))
    except (PlanError, QuestionError) as exc:
        raise HTTPException(400, str(exc)) from None
    try:
        return runs.start(plan).snapshot()
    except Busy:
        raise HTTPException(409, "다른 평가가 실행 중입니다. 끝나거나 취소한 뒤 다시 시작하세요.") from None


@router.get("/runs/current")
def current_run(request: Request):
    return {"run": _runs(request).current()}


@router.post("/runs/current/cancel")
def cancel_run(request: Request):
    return {"cancelled": _runs(request).cancel()}


@router.get("/runs/current/questions/{index}")
def drilldown(index: int, combo: str, request: Request):
    detail = _runs(request).drilldown(combo, index)
    if detail is None:
        raise HTTPException(404, "이 질문의 상세 결과가 없습니다. 서버를 다시 시작했다면 평가를 다시 실행하세요.")
    return detail
