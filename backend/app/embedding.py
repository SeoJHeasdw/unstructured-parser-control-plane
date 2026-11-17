"""임베딩 후보 비교에 필요한 연결·호출·캐시·검색 지표. 표준 라이브러리만 사용한다.

연결 설정은 호출할 때마다 환경변수에서 읽는다(테스트에서 바꿀 수 있도록).
  EMBED_LABEL, EMBED_BASE_URL, EMBED_API_KEY, EMBED_MODELS(쉼표로 구분한 모델 ID)
  기존 MODEL_*/MODEL2_* 연결도 같은 게이트웨이의 /embeddings 로 쓸 수 있다(app.llm.load_connections).
API 키는 응답·로그·오류 메시지에 내보내지 않는다(app.llm._scrub).
"""
from array import array
import base64
from dataclasses import dataclass
import hashlib
import heapq
import json
import math
import operator
import os
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
from urllib import error, request

from app.llm import ModelConnection, _context, _scrub, _timeout, load_connections

MAX_RESPONSE_BYTES = 256 * 1024 * 1024
MAX_BATCH = 64
MAX_BATCH_CHARS = 120_000
KS = (1, 3, 5, 10)

HARRIER_QUERY = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: "
QWEN_QUERY = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"

# 공개 모델 카드 기준 참고값. 실제 응답에서 잰 차원이 있으면 화면이 그 값을 우선한다. 우열을 정하지 않는다.
MODEL_SPECS: tuple[dict, ...] = (
    {"id": "microsoft/harrier-oss-v1-0.6b", "dims": 1024, "dims_note": "", "max_tokens": 32768, "arch": "디코더(decoder-only)", "pooling": "마지막 토큰", "query_prefix": HARRIER_QUERY, "doc_prefix": "", "prefix_note": "질의 지시문 필요 · 문서 접두어 없음", "languages": "다국어(한국어 포함)", "note": ""},
    {"id": "Qwen/Qwen3-Embedding-0.6B", "dims": 1024, "dims_note": "MRL 32–1024", "max_tokens": 32768, "arch": "디코더(decoder-only)", "pooling": "마지막 토큰", "query_prefix": QWEN_QUERY, "doc_prefix": "", "prefix_note": "질의 지시문 필요 · 문서 접두어 없음", "languages": "다국어", "note": "출력 차원을 줄일 수 있음"},
    {"id": "BAAI/bge-m3", "dims": 1024, "dims_note": "", "max_tokens": 8192, "arch": "인코더(XLM-R)", "pooling": "", "query_prefix": "", "doc_prefix": "", "prefix_note": "접두어 없음", "languages": "다국어", "note": "dense+sparse · 이 화면은 dense만 비교"},
    {"id": "intfloat/multilingual-e5-large", "dims": 1024, "dims_note": "", "max_tokens": 512, "arch": "인코더", "pooling": "", "query_prefix": "query: ", "doc_prefix": "passage: ", "prefix_note": "query: / passage: 접두어", "languages": "다국어", "note": "512토큰 입력 한도"},
    {"id": "ibm/granite-embedding-278m-multilingual", "dims": 768, "dims_note": "", "max_tokens": 512, "arch": "인코더", "pooling": "", "query_prefix": "", "doc_prefix": "", "prefix_note": "", "languages": "다국어(한국어 포함)", "note": "512토큰 입력 한도"},
    {"id": "ibm/granite-embedding-107m-multilingual", "dims": 384, "dims_note": "", "max_tokens": 512, "arch": "인코더", "pooling": "", "query_prefix": "", "doc_prefix": "", "prefix_note": "", "languages": "다국어", "note": "512토큰 입력 한도"},
    {"id": "ibm/slate-125m-english-rtrvr", "dims": 768, "dims_note": "", "max_tokens": 512, "arch": "인코더", "pooling": "", "query_prefix": "", "doc_prefix": "", "prefix_note": "", "languages": "영어 전용", "note": "512토큰 입력 한도"},
    {"id": "ibm/slate-30m-english-rtrvr", "dims": 384, "dims_note": "", "max_tokens": 512, "arch": "인코더", "pooling": "", "query_prefix": "", "doc_prefix": "", "prefix_note": "", "languages": "영어 전용", "note": "512토큰 입력 한도"},
)


def spec_for(model_id: str) -> dict | None:
    key = (model_id or "").lower()
    for spec in MODEL_SPECS:
        if spec["id"].lower() == key or spec["id"].split("/")[-1].lower() == key.split("/")[-1]:
            return spec
    return None


# ---------------------------------------------------------------- 연결

@dataclass(frozen=True)
class EmbedConnection:
    key: str
    label: str
    base_url: str
    api_key: str
    models: tuple[str, ...]
    source: str  # embed | model

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def public(self) -> dict:
        return {"key": self.key, "label": self.label, "base_url": self.base_url, "api_key_set": bool(self.api_key),
                "configured": self.configured, "models": list(self.models), "source": self.source}

    def for_model(self, model_id: str) -> ModelConnection:
        return ModelConnection(self.key, self.label, self.base_url, self.api_key, model_id)


def embed_connections(environ=None) -> list[EmbedConnection]:
    """EMBED_* 연결(설정 여부와 상관없이 항상 첫 항목)과 주소가 있는 MODEL_*/MODEL2_* 연결."""
    env = os.environ if environ is None else environ
    models = tuple(dict.fromkeys(m.strip() for m in env.get("EMBED_MODELS", "").split(",") if m.strip()))
    out = [EmbedConnection("embed", env.get("EMBED_LABEL", "").strip() or "임베딩 게이트웨이", env.get("EMBED_BASE_URL", "").strip().rstrip("/"),
                           env.get("EMBED_API_KEY", "").strip(), models, "embed")]
    for conn in load_connections(env):
        if conn.base_url:
            out.append(EmbedConnection(conn.key, conn.label, conn.base_url, conn.api_key, (conn.model_id,) if conn.model_id else (), "model"))
    return out


def find_connection(key: str, environ=None) -> EmbedConnection | None:
    for conn in embed_connections(environ):
        if conn.key == key:
            return conn
    return None


# ---------------------------------------------------------------- 호출

class EmbedError(Exception):
    def __init__(self, message: str, status: int | None = None, over_limit: bool = False, fatal: bool = False):
        super().__init__(message)
        self.status = status
        self.over_limit = over_limit
        self.fatal = fatal


_LIMIT_HINT = re.compile(r"context length|maximum context|too long|too many tokens|max(imum)?[_ ]?(input|sequence)?[_ ]?(length|tokens)|token limit|exceeds|truncat|input length", re.I)


@dataclass
class EmbedResponse:
    vectors: list
    prompt_tokens: int | None
    seconds: float


def _decode(item) -> array:
    if isinstance(item, str):  # encoding_format=base64 응답
        vec = array("f")
        vec.frombytes(base64.b64decode(item))
        return vec
    if not isinstance(item, list) or not item:
        raise ValueError("embedding")
    vec = array("f", (float(x) for x in item))
    if not all(math.isfinite(x) for x in vec):
        raise ValueError("embedding")
    return vec


def embed_batch(conn: ModelConnection, inputs: list[str]) -> EmbedResponse:
    """POST {base_url}/embeddings. 실패하면 키를 지운 메시지로 EmbedError를 낸다."""
    url = conn.base_url if conn.base_url.endswith("/embeddings") else conn.base_url + "/embeddings"
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if conn.api_key:
        headers["Authorization"] = f"Bearer {conn.api_key}"
    data = json.dumps({"model": conn.model_id, "input": inputs}, ensure_ascii=False).encode("utf-8")
    started = time.monotonic()
    try:
        req = request.Request(url, data=data, headers=headers, method="POST")
        with request.urlopen(req, timeout=_timeout(), context=_context()) as response:
            raw = response.read(MAX_RESPONSE_BYTES)
    except error.HTTPError as exc:
        try:
            detail = exc.read(4000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            detail = ""
        over = exc.code in (400, 413, 422, 500) and bool(_LIMIT_HINT.search(detail))
        raise EmbedError(_scrub(conn, f"HTTP {exc.code} {detail}"), exc.code, over_limit=over, fatal=exc.code in (401, 403, 404, 405)) from None
    except error.URLError as exc:
        raise EmbedError(_scrub(conn, f"연결 실패: {exc.reason}"), fatal=True) from None
    except (TimeoutError, OSError, ValueError) as exc:
        raise EmbedError(_scrub(conn, f"{type(exc).__name__}: {exc}"), fatal=isinstance(exc, ValueError)) from None
    seconds = time.monotonic() - started
    try:
        payload = json.loads(raw.decode("utf-8"))
        items = payload["data"]
        ordered = sorted(items, key=lambda item: item.get("index", 0)) if all(isinstance(i, dict) for i in items) else items
        vectors = [_decode(item["embedding"]) for item in ordered]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise EmbedError(_scrub(conn, "OpenAI 호환 임베딩 응답 형식이 아닙니다."), fatal=True) from None
    if len(vectors) != len(inputs):
        raise EmbedError("응답 벡터 수가 입력 수와 다릅니다.", fatal=True)
    usage = payload.get("usage") if isinstance(payload, dict) else None
    tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    return EmbedResponse(vectors, tokens if isinstance(tokens, int) and tokens >= 0 else None, seconds)


# ---------------------------------------------------------------- 캐시

def model_key(conn: ModelConnection) -> str:
    """같은 모델 ID라도 게이트웨이가 다르면 다른 벡터일 수 있어 주소 해시를 붙인다."""
    return f"{conn.model_id}@{hashlib.sha256(conn.base_url.encode('utf-8')).hexdigest()[:10]}"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class VectorCache:
    """(모델, 접두어, sha256(본문)) → float32 벡터. 실행 폴더의 SQLite 한 파일."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS vectors (model TEXT NOT NULL, prefix TEXT NOT NULL, sha TEXT NOT NULL, dims INTEGER NOT NULL,
                vec BLOB NOT NULL, created_at REAL NOT NULL, PRIMARY KEY (model, prefix, sha)) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS throughput (model TEXT PRIMARY KEY, items INTEGER NOT NULL, seconds REAL NOT NULL,
                requests INTEGER NOT NULL, measured_at REAL NOT NULL);
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def get_many(self, model: str, prefix: str, shas) -> dict[str, array]:
        shas = list(dict.fromkeys(shas))
        found: dict[str, array] = {}
        with self._connect() as conn:
            for i in range(0, len(shas), 500):
                part = shas[i:i + 500]
                marks = ",".join("?" * len(part))
                for sha, blob in conn.execute(f"SELECT sha, vec FROM vectors WHERE model=? AND prefix=? AND sha IN ({marks})", (model, prefix, *part)):
                    vec = array("f")
                    vec.frombytes(blob)
                    found[sha] = vec
        return found

    def put_many(self, model: str, prefix: str, items: list[tuple[str, array]]) -> None:
        if not items:
            return
        now = time.time()
        with self._connect() as conn:
            conn.executemany("INSERT OR REPLACE INTO vectors (model, prefix, sha, dims, vec, created_at) VALUES (?,?,?,?,?,?)",
                             [(model, prefix, sha, len(vec), vec.tobytes(), now) for sha, vec in items])

    def record_throughput(self, model: str, items: int, seconds: float, requests: int) -> None:
        if items <= 0 or seconds <= 0:
            return
        with self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO throughput (model, items, seconds, requests, measured_at) VALUES (?,?,?,?,?)",
                         (model, items, seconds, requests, time.time()))

    def throughput(self, model: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT items, seconds, requests FROM throughput WHERE model=?", (model,)).fetchone()
        if not row:
            return None
        return {"items": row[0], "seconds": row[1], "requests": row[2]}

    def stats(self) -> dict:
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
        try:
            size = self.path.stat().st_size
        except OSError:
            size = 0
        return {"entries": count, "bytes": size}


# ---------------------------------------------------------------- 점수·지표

_dot = getattr(math, "sumprod", None) or (lambda a, b: sum(map(operator.mul, a, b)))


def unit_vector(vec) -> list[float]:
    norm = math.sqrt(math.fsum(x * x for x in vec))
    return [x / norm for x in vec] if norm > 0 else [0.0] * len(vec)


def top_k(query: list[float], vectors: list[list[float] | None], k: int) -> list[tuple[int, float]]:
    """정규화한 벡터의 코사인(내적) 상위 k. 실패한 청크(None)는 뺀다."""
    scored = ((i, _dot(query, v)) for i, v in enumerate(vectors) if v is not None)
    return heapq.nlargest(k, scored, key=lambda item: item[1])


_STRIP = re.compile(r"[\s|*`]+")


def normalize_phrase(text: str) -> str:
    """정답 문구 비교용: NFKC, 대소문자 무시, 공백과 마크다운 표·강조 기호 제거."""
    return _STRIP.sub("", unicodedata.normalize("NFKC", text or "").casefold())


def rank_metrics(relevant: list[bool], n_relevant: int) -> dict:
    """상위 청크 순서의 이진 관련도로 Hit@k, MRR@10, nDCG@10을 낸다."""
    first = next((i + 1 for i, rel in enumerate(relevant) if rel), None)
    out = {f"hit@{k}": 1.0 if first is not None and first <= k else 0.0 for k in KS}
    out["mrr@10"] = 1.0 / first if first is not None and first <= 10 else 0.0
    dcg = sum(1.0 / math.log2(i + 2) for i, rel in enumerate(relevant[:10]) if rel)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(n_relevant, 10)))
    out["ndcg@10"] = dcg / ideal if ideal else 0.0
    out["rank"] = first
    return out


def mean_metrics(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    keys = [f"hit@{k}" for k in KS] + ["mrr@10", "ndcg@10"]
    return {key: round(sum(r[key] for r in rows) / len(rows), 4) for key in keys}
