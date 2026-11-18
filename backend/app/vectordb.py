"""벡터 DB(Milvus) 읽기 전용 탐색. 표준 라이브러리만 사용한다.

설정은 호출할 때마다 환경변수(또는 프로젝트 루트 .env)에서 읽는다.
  MILVUS_URI        REST 주소(예: http://host:19530). 비우면 예시 데이터만 쓴다.
  MILVUS_TOKEN      Bearer 토큰. user:password 또는 API 키. 응답·로그에 내보내지 않는다.
  MILVUS_DB         기본 데이터베이스(기본 default)
  MILVUS_TIMEOUT    요청 제한 시간(초, 기본 30)
  MILVUS_CA_BUNDLE  사내 인증서 묶음 경로(없으면 MODEL_CA_BUNDLE)

Milvus RESTful API v2(POST {uri}/v2/vectordb/...) 중 목록·설명·통계·조회·검색만 호출한다.
생성·삭제·삽입·로드·해제 요청은 보내지 않는다. 같은 인터페이스로 합성 예시 데이터(example)를 제공한다.
"""
from __future__ import annotations

import ast
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import dataclass
from functools import lru_cache
import json
import math
import operator
import os
from pathlib import Path
import random
import re
import ssl
import threading
import time
from typing import Any, Callable
from urllib import error, request
from urllib.parse import urlsplit, urlunsplit
import uuid

EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "mock-data" / "vectordb-example.json"
MAX_WINDOW = 16_384            # Milvus: offset + limit 는 16,384 미만
MAX_FETCH = MAX_WINDOW - 1
JS_SAFE = 2 ** 53 - 1          # 이보다 큰 정수는 브라우저에서 반올림되므로 문자열로 보낸다
MAX_RESPONSE = 64 * 1024 * 1024
MAX_PARTITION_LOOKUP = 16      # 행별 파티션을 찾을 때 파티션마다 조회하는 상한
READ_ONLY_PATHS = frozenset({
    "databases/list", "collections/list", "collections/describe", "collections/get_stats", "collections/get_load_state",
    "partitions/list", "partitions/get_stats", "indexes/list", "indexes/describe", "entities/query", "entities/get", "entities/search",
})


class VectorDbError(Exception):
    """화면에 그대로 보여 줄 수 있는 오류. status 는 이 API가 돌려줄 HTTP 상태."""

    def __init__(self, message: str, status: int = 400, *, code: int | None = None, upstream: int | None = None):
        super().__init__(message)
        self.message, self.status, self.code, self.upstream = message, status, code, upstream


def _int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _map(fn: Callable, items, workers: int = 8) -> list:
    items = list(items)
    if len(items) <= 1 or workers <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(fn, items))


# ---------------------------------------------------------------- 설정

def display_uri(uri: str) -> str:
    """사용자 정보·쿼리 문자열을 뺀 주소. 토큰이 섞여 있어도 화면에 나가지 않게 한다."""
    if not uri:
        return ""
    try:
        parts = urlsplit(uri)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return ""
    if ":" in host:
        host = f"[{host}]"
    return urlunsplit((parts.scheme, host + (f":{port}" if port else ""), parts.path, "", ""))


@dataclass(frozen=True)
class MilvusConfig:
    uri: str = ""
    token: str = ""
    db: str = "default"
    timeout: float = 30.0
    ca_bundle: str = ""

    @classmethod
    def from_env(cls, environ=None) -> "MilvusConfig":
        env = os.environ if environ is None else environ
        uri = env.get("MILVUS_URI", "").strip().rstrip("/")
        if uri and "://" not in uri:
            uri = "http://" + uri
        try:
            timeout = max(3.0, float(env.get("MILVUS_TIMEOUT", "").strip() or 30))
        except ValueError:
            timeout = 30.0
        bundle = env.get("MILVUS_CA_BUNDLE", "").strip() or env.get("MODEL_CA_BUNDLE", "").strip()
        return cls(uri=uri, token=env.get("MILVUS_TOKEN", "").strip(), db=env.get("MILVUS_DB", "").strip() or "default", timeout=timeout, ca_bundle=bundle)

    @property
    def configured(self) -> bool:
        return bool(self.uri)

    def public(self) -> dict:
        return {"configured": self.configured, "uri": display_uri(self.uri), "db": self.db, "token_set": bool(self.token), "ca_bundle_set": bool(self.ca_bundle), "timeout": self.timeout}

    def secrets(self) -> list[str]:
        found = []
        if self.token:
            found.append(self.token)
            if ":" in self.token:
                password = self.token.split(":", 1)[1]
                if len(password) >= 4:
                    found.append(password)
        try:
            password = urlsplit(self.uri).password if self.uri else None
        except ValueError:
            password = None
        if password and len(password) >= 4:
            found.append(password)
        return sorted(set(found), key=len, reverse=True)

    def scrub(self, text: str) -> str:
        for secret in self.secrets():
            text = text.replace(secret, "***")
        text = re.sub(r"(?i)(bearer\s+)\S+", r"\1***", text)
        return " ".join(text.split())[:500]


# ---------------------------------------------------------------- Milvus REST v2

def _not_loaded_hint(message: str) -> str:
    if re.search(r"not\s*loaded|load.*first|LoadStateNotLoad", message, re.I):
        return message + " — 컬렉션이 메모리에 로드되지 않아 조회·검색할 수 없습니다. 이 화면은 컬렉션을 로드하지 않습니다."
    return message


UNREACHABLE_COOLDOWN = 30.0    # 연결 실패 뒤 이 시간(초) 동안은 같은 주소로 요청을 다시 보내지 않는다
_UNREACHABLE: dict[str, tuple[float, str]] = {}
_UNREACHABLE_LOCK = threading.Lock()


def unreachable_state(api_base: str) -> dict | None:
    """연결 실패로 쉬는 중이면 {retry_in, error}, 아니면 None."""
    with _UNREACHABLE_LOCK:
        entry = _UNREACHABLE.get(api_base)
        if entry is None:
            return None
        until, message = entry
        remaining = until - time.monotonic()
        if remaining <= 0:
            del _UNREACHABLE[api_base]
            return None
        return {"retry_in": math.ceil(remaining), "error": message}


def mark_unreachable(api_base: str, message: str) -> None:
    with _UNREACHABLE_LOCK:
        _UNREACHABLE[api_base] = (time.monotonic() + UNREACHABLE_COOLDOWN, message)


def clear_unreachable(api_base: str | None = None) -> None:
    with _UNREACHABLE_LOCK:
        if api_base is None:
            _UNREACHABLE.clear()
        else:
            _UNREACHABLE.pop(api_base, None)


class MilvusSource:
    key = "milvus"

    def __init__(self, config: MilvusConfig):
        self.config = config
        self.default_db = config.db

    @property
    def api_base(self) -> str:
        base = self.config.uri.rstrip("/")
        return base if base.endswith("/v2/vectordb") else base + "/v2/vectordb"

    def call(self, path: str, body: dict) -> Any:
        if path not in READ_ONLY_PATHS:
            raise VectorDbError("읽기 전용 요청만 보낼 수 있습니다.", 500)
        paused = unreachable_state(self.api_base)
        if paused:
            # 연결이 안 되는 주소에 화면이 계속 요청을 보내지 않게 한다. 사용자가 '연결 확인'을 누르면 다시 시도한다.
            raise VectorDbError(f"Milvus에 연결되지 않아 {paused['retry_in']}초 동안 요청을 멈췄습니다. 마지막 오류: {paused['error']}", 503)
        headers = {"Content-Type": "application/json", "Accept": "application/json", "Request-Timeout": str(int(self.config.timeout))}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        req = request.Request(f"{self.api_base}/{path}", data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
        scrub = self.config.scrub
        try:
            context = ssl.create_default_context(cafile=self.config.ca_bundle or None)
            with request.urlopen(req, timeout=self.config.timeout, context=context) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except error.HTTPError as exc:
            try:
                detail = exc.read(4000).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - 본문이 없어도 상태 코드는 보여 준다
                detail = ""
            try:
                parsed = json.loads(detail)
                detail = str(parsed.get("message") or parsed.get("detail") or detail) if isinstance(parsed, dict) else detail
            except ValueError:
                pass
            failure = VectorDbError(scrub(f"Milvus HTTP {exc.code}: {detail}"), 502, upstream=exc.code)
            if exc.code == 404 and path == "collections/list":
                mark_unreachable(self.api_base, failure.message)  # 모든 Milvus REST v2가 갖는 경로가 없으면 Milvus 주소가 아니다
            raise failure from None
        except error.URLError as exc:
            failure = VectorDbError(scrub(f"Milvus 연결 실패: {exc.reason}"), 502)
            mark_unreachable(self.api_base, failure.message)
            raise failure from None
        except (TimeoutError, OSError, ssl.SSLError, ValueError) as exc:
            failure = VectorDbError(scrub(f"Milvus 연결 실패: {type(exc).__name__} {exc}"), 504 if isinstance(exc, TimeoutError) else 502)
            mark_unreachable(self.api_base, failure.message)
            raise failure from None
        clear_unreachable(self.api_base)
        if len(raw) > MAX_RESPONSE:
            raise VectorDbError("Milvus 응답이 너무 큽니다. 조건을 좁혀 주세요.", 502)
        text = raw.decode("utf-8", "replace")
        try:
            payload = json.loads(text)
        except ValueError:
            raise VectorDbError(scrub(f"Milvus REST v2 응답 형식이 아닙니다: {text[:200]}"), 502) from None
        if not isinstance(payload, dict):
            raise VectorDbError("Milvus REST v2 응답 형식이 아닙니다.", 502)
        code = payload.get("code", 0)
        if code not in (0, 200, None, "0", "200"):
            message = payload.get("message") or payload.get("msg") or ""
            raise VectorDbError(scrub(_not_loaded_hint(f"Milvus 오류 {code}: {message}")), 502, code=_int(code))
        return payload.get("data")

    @staticmethod
    def _body(db: str, collection: str | None = None, **extra) -> dict:
        body: dict = {"dbName": db} if db else {}
        if collection is not None:
            body["collectionName"] = collection
        body.update({key: value for key, value in extra.items() if value is not None})
        return body

    def databases(self) -> list[str]:
        return [str(name) for name in self.call("databases/list", {}) or []]

    def collections(self, db: str) -> list[str]:
        return [str(name) for name in self.call("collections/list", self._body(db)) or []]

    def describe(self, db: str, collection: str) -> dict:
        data = self.call("collections/describe", self._body(db, collection))
        return data if isinstance(data, dict) else {}

    def row_count(self, db: str, collection: str) -> int | None:
        data = self.call("collections/get_stats", self._body(db, collection))
        return _int(data.get("rowCount")) if isinstance(data, dict) else None

    def partitions(self, db: str, collection: str) -> list[str]:
        return [str(name) for name in self.call("partitions/list", self._body(db, collection)) or []]

    def partition_rows(self, db: str, collection: str, partition: str) -> int | None:
        data = self.call("partitions/get_stats", self._body(db, collection, partitionName=partition))
        return _int(data.get("rowCount")) if isinstance(data, dict) else None

    def load_state(self, db: str, collection: str) -> dict:
        data = self.call("collections/get_load_state", self._body(db, collection))
        return data if isinstance(data, dict) else {}

    def index_names(self, db: str, collection: str) -> list[str]:
        return [str(name) for name in self.call("indexes/list", self._body(db, collection)) or []]

    def describe_index(self, db: str, collection: str, index: str) -> list[dict]:
        data = self.call("indexes/describe", self._body(db, collection, indexName=index))
        items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        return [item for item in items if isinstance(item, dict)]

    def query(self, db: str, collection: str, *, filter: str, output_fields: list[str], partitions: list[str] | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        body = self._body(db, collection, filter=filter, outputFields=output_fields, partitionNames=partitions or None, limit=limit, offset=offset or None)
        data = self.call("entities/query", body)
        return [row for row in data or [] if isinstance(row, dict)]

    def get(self, db: str, collection: str, ids: list, output_fields: list[str]) -> list[dict]:
        data = self.call("entities/get", self._body(db, collection, id=ids, outputFields=output_fields))
        return [row for row in data or [] if isinstance(row, dict)]

    def search(self, db: str, collection: str, *, vector: list[float], anns_field: str, limit: int, output_fields: list[str], filter: str | None = None, partitions: list[str] | None = None) -> list[dict]:
        body = self._body(db, collection, data=[vector], annsField=anns_field, limit=limit, outputFields=output_fields, filter=filter or None, partitionNames=partitions or None)
        data = self.call("entities/search", body) or []
        if data and isinstance(data[0], list):  # 여러 질의 벡터 형식
            data = data[0]
        return [row for row in data if isinstance(row, dict)]


# ---------------------------------------------------------------- 예시 데이터용 조건식(Milvus 필터의 일부)

_TOKEN_RE = re.compile(r"""\s*(?:(?P<num>\d+\.\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?|\d+(?:[eE][-+]?\d+)?)|(?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|(?P<op>==|!=|>=|<=|&&|\|\||[<>()\[\],!-])|(?P<name>[A-Za-z_$][A-Za-z0-9_$]*))""")
_OPS = {"==": operator.eq, "!=": operator.ne, ">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le}


def _literal_string(token: str) -> str:
    try:
        value = ast.literal_eval(token)
    except (ValueError, SyntaxError):
        raise VectorDbError(f"문자열 {token[:30]}을 해석할 수 없습니다.") from None
    return str(value)


def _like(pattern: str):
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
            continue
        out.append(".*" if ch == "%" else "." if ch == "_" else re.escape(ch))
        i += 1
    return re.compile("".join(out), re.S)


def _compare(op, left, right) -> bool:
    if left is None or right is None:
        return False
    if isinstance(left, str) != isinstance(right, str):
        raise VectorDbError("문자열 필드와 숫자를 비교할 수 없습니다. 문자열 값은 따옴표로 감싸 주세요.")
    return bool(op(left, right))


class _FilterParser:
    """==, !=, <, <=, >, >=, in, not in, like, and/&&, or/||, not/!, 괄호를 지원한다."""

    def __init__(self, text: str, fields: set[str]):
        self.tokens, self.i, self.fields = self._tokenize(text.strip()), 0, fields

    @staticmethod
    def _tokenize(text: str) -> list[tuple[str, str]]:
        tokens, pos = [], 0
        while pos < len(text):
            match = _TOKEN_RE.match(text, pos)
            if not match:
                raise VectorDbError(f"조건식을 해석할 수 없습니다: '{text[pos:pos + 20]}' 부근")
            pos = match.end()
            tokens.append((match.lastgroup or "", match.group(match.lastgroup or 0)))
        return tokens

    def _peek(self) -> tuple[str | None, str | None]:
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def _accept(self, *words: str) -> bool:
        kind, value = self._peek()
        if value is not None and ((kind == "op" and value in words) or (kind == "name" and value.lower() in words)):
            self.i += 1
            return True
        return False

    def parse(self) -> Callable[[dict], Any]:
        if not self.tokens:
            return lambda row: True
        node = self._or()
        if self.i < len(self.tokens):
            raise VectorDbError(f"조건식의 '{self.tokens[self.i][1]}' 부분을 해석할 수 없습니다.")
        return node

    def _or(self):
        node = self._and()
        while self._accept("or", "||"):
            left, right = node, self._and()
            node = lambda row, a=left, b=right: bool(a(row)) or bool(b(row))
        return node

    def _and(self):
        node = self._not()
        while self._accept("and", "&&"):
            left, right = node, self._not()
            node = lambda row, a=left, b=right: bool(a(row)) and bool(b(row))
        return node

    def _not(self):
        if self._accept("not", "!"):
            inner = self._not()
            return lambda row: not inner(row)
        return self._comparison()

    def _comparison(self):
        left = self._primary()
        kind, value = self._peek()
        if kind == "op" and value in _OPS:
            self.i += 1
            right, op = self._primary(), _OPS[value]
            return lambda row: _compare(op, left(row), right(row))
        negate = False
        if kind == "name" and value and value.lower() == "not" and self.i + 1 < len(self.tokens) and self.tokens[self.i + 1][1].lower() == "in":
            self.i += 1
            negate = True
            kind, value = self._peek()
        if kind == "name" and value and value.lower() == "in":
            self.i += 1
            right = self._primary()
            return lambda row: (left(row) in (right(row) or [])) != negate
        if kind == "name" and value and value.lower() == "like":
            self.i += 1
            kind, token = self._peek()
            if kind != "str":
                raise VectorDbError("like 뒤에는 따옴표로 감싼 패턴이 필요합니다.")
            self.i += 1
            regex = _like(_literal_string(token or ""))
            return lambda row: isinstance(left(row), str) and bool(regex.fullmatch(left(row)))
        return left

    def _primary(self):
        kind, value = self._peek()
        if kind is None:
            raise VectorDbError("조건식이 끝나지 않았습니다.")
        self.i += 1
        if kind == "op" and value == "(":
            node = self._or()
            if not self._accept(")"):
                raise VectorDbError("닫는 괄호가 필요합니다.")
            return node
        if kind == "op" and value == "[":
            items = []
            if not self._accept("]"):
                while True:
                    items.append(self._primary())
                    if self._accept("]"):
                        break
                    if not self._accept(","):
                        raise VectorDbError("목록 값은 쉼표로 구분합니다.")
            return lambda row: [item(row) for item in items]
        if kind == "op" and value == "-":
            kind, value = self._peek()
            if kind != "num":
                raise VectorDbError("'-' 뒤에는 숫자가 필요합니다.")
            self.i += 1
            number = -(float(value) if any(c in value for c in ".eE") else int(value))
            return lambda row: number
        if kind == "num":
            number = float(value) if any(c in value for c in ".eE") else int(value)
            return lambda row: number
        if kind == "str":
            text = _literal_string(value)
            return lambda row: text
        if kind == "name":
            if value.lower() in ("true", "false"):
                flag = value.lower() == "true"
                return lambda row: flag
            if value not in self.fields:
                raise VectorDbError(f"조건식의 필드 '{value}'이(가) 컬렉션에 없습니다.")
            return lambda row: row.get(value)
        raise VectorDbError(f"조건식의 '{value}' 부분을 해석할 수 없습니다.")


def compile_filter(text: str, fields: set[str]) -> Callable[[dict], bool]:
    predicate = _FilterParser(text or "", fields).parse()
    return lambda row: bool(predicate(row))


# ---------------------------------------------------------------- 예시 데이터

def _unit(rng: random.Random, dim: int) -> list[float]:
    values = [rng.gauss(0.0, 1.0) for _ in range(dim)]
    norm = math.sqrt(sum(x * x for x in values)) or 1.0
    return [x / norm for x in values]


def _mix(parts: list[tuple[float, list[float]]]) -> list[float]:
    dim = len(parts[0][1])
    out = [sum(weight * vector[i] for weight, vector in parts) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in out)) or 1.0
    return [x / norm for x in out]


def split_text(text: str, size: int, overlap: int) -> list[tuple[int, int]]:
    """단어 경계로 size 글자 이하 청크를 만들고 다음 청크가 앞 청크 끝 overlap 글자 이하를 다시 담게 한다."""
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
    spans, i = [], 0
    while i < len(words):
        j = i
        while j + 1 < len(words) and words[j + 1][1] - words[i][0] <= size:
            j += 1
        start, end = words[i][0], words[j][1]
        spans.append((start, end))
        if j == len(words) - 1:
            break
        k = j + 1
        while k - 1 > i and end - words[k - 1][0] <= overlap:
            k -= 1
        i = k
    return spans


class ExampleCollection:
    def __init__(self, spec: dict, documents: dict[str, dict]):
        self.db, self.name = spec["db"], spec["name"]
        self.metric = spec["metric"]
        self.fields = spec["fields"]
        self.field_names = {f["name"] for f in self.fields}
        roles = {f["role"]: f["name"] for f in self.fields}
        self.pk = roles["pk"]
        self.vector = roles["vector"]
        dim = next(f["dim"] for f in self.fields if f["role"] == "vector")
        self.partitions = list(spec["partitions"])
        self.index = spec["index"]
        int_pk = next(f for f in self.fields if f["role"] == "pk")["type"].lower() == "int64"
        auto_id = spec.get("auto_id_start", 0)
        rows = []
        for partition, doc_ids in spec["partitions"].items():
            for doc_id in doc_ids:
                doc = documents[doc_id]
                text = "\n".join(doc["pages"])
                page_starts, offset = [], 0
                for page in doc["pages"]:
                    page_starts.append(offset)
                    offset += len(page) + 1
                seed = spec["seed"]
                category = _unit(random.Random(f"{seed}|category|{doc['category']}"), dim)
                base = _unit(random.Random(f"{seed}|document|{doc_id}"), dim)
                drift: list[float] = []
                for index, (start, end) in enumerate(split_text(text, spec["chunk_chars"], spec["overlap_chars"])):
                    fresh = _unit(random.Random(f"{seed}|chunk|{doc_id}|{index}"), dim)
                    drift = _mix([(0.55, drift), (0.85, fresh)]) if drift else fresh
                    vector = [round(x, 6) for x in _mix([(0.35, category), (0.8, base), (0.55, drift)])]
                    if int_pk:
                        pk: Any = auto_id + len(rows)
                    else:
                        pk = str(uuid.uuid5(uuid.NAMESPACE_URL, f"vectordb-example/{self.name}/{doc_id}/{index}"))
                    values = {"pk": pk, "text": text[start:end], "vector": vector, "doc": doc_id, "order": index,
                              "page": sum(1 for s in page_starts if s <= start), "start": start}
                    row = {}
                    for field in self.fields:
                        role = field["role"]
                        row[field["name"]] = doc.get(role[4:]) if role.startswith("doc:") else values[role]
                    row["_partition"] = partition
                    rows.append(row)
        self.rows = sorted(rows, key=lambda r: r[self.pk])
        self.by_pk = {row[self.pk]: row for row in self.rows}
        params = lambda f: [{"key": "dim", "value": str(f["dim"])}] if "dim" in f else [{"key": "max_length", "value": str(f["max_length"])}] if "max_length" in f else []
        self.describe = {
            "collectionName": self.name, "collectionID": 450_000_000_000_000_000 + sum(map(ord, self.name)), "description": spec.get("description", ""),
            "autoID": any(f.get("autoId") for f in self.fields), "consistencyLevel": spec.get("consistency", "Bounded"), "enableDynamicField": False,
            "shardsNum": 1, "partitionsNum": len(self.partitions), "load": "LoadStateLoaded", "aliases": spec.get("aliases", []),
            "properties": [{"key": key, "value": value} for key, value in spec.get("properties", {}).items()],
            "fields": [{"id": 100 + i, "name": f["name"], "type": f["type"], "primaryKey": bool(f.get("primaryKey")), "autoId": bool(f.get("autoId")),
                        "partitionKey": False, "nullable": bool(f.get("nullable")), "description": f.get("description", ""), "params": params(f)} for i, f in enumerate(self.fields)],
            "indexes": [{"fieldName": self.vector, "indexName": self.index["name"], "metricType": self.metric}],
        }

    def select(self, expression: str, partitions: list[str] | None) -> list[dict]:
        for name in partitions or []:
            if name not in self.partitions:
                raise VectorDbError(f"Milvus 오류 200: partition not found[partition={name}]", 502)
        predicate = compile_filter(expression, self.field_names)
        wanted = set(partitions or [])
        return [row for row in self.rows if (not wanted or row["_partition"] in wanted) and predicate(row)]

    def project(self, row: dict, output_fields: list[str]) -> dict:
        out = {self.pk: row[self.pk]}
        for name in output_fields:
            if name == "*":
                out.update({key: value for key, value in row.items() if key != "_partition"})
            elif name in self.field_names:
                out[name] = row[name]
            else:
                raise VectorDbError(f"Milvus 오류 1100: field {name} not exist", 502)
        return out


@lru_cache(maxsize=2)
def _example_data(path: str) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    documents = {doc["id"]: doc for doc in raw["documents"]}
    collections = {(spec["db"], spec["name"]): ExampleCollection(spec, documents) for spec in raw["collections"]}
    return {"databases": {db["name"]: list(db["collections"]) for db in raw["databases"]}, "collections": collections}


class ExampleSource:
    """Milvus REST v2와 같은 형태로 응답하는 메모리 속 합성 데이터."""

    key = "example"
    default_db = "default"

    def __init__(self, path: Path = EXAMPLE_PATH):
        self.data = _example_data(str(path))

    def _collection(self, db: str, name: str) -> ExampleCollection:
        found = self.data["collections"].get((db, name))
        if found is None:
            raise VectorDbError(f"컬렉션을 찾을 수 없습니다: {db}/{name}", 404)
        return found

    def databases(self) -> list[str]:
        return list(self.data["databases"])

    def collections(self, db: str) -> list[str]:
        if db not in self.data["databases"]:
            raise VectorDbError(f"데이터베이스를 찾을 수 없습니다: {db}", 404)
        return list(self.data["databases"][db])

    def describe(self, db: str, collection: str) -> dict:
        return copy.deepcopy(self._collection(db, collection).describe)

    def row_count(self, db: str, collection: str) -> int:
        return len(self._collection(db, collection).rows)

    def partitions(self, db: str, collection: str) -> list[str]:
        return list(self._collection(db, collection).partitions)

    def partition_rows(self, db: str, collection: str, partition: str) -> int:
        return sum(1 for row in self._collection(db, collection).rows if row["_partition"] == partition)

    def load_state(self, db: str, collection: str) -> dict:
        self._collection(db, collection)
        return {"loadState": "LoadStateLoaded", "loadProgress": 100, "message": ""}

    def index_names(self, db: str, collection: str) -> list[str]:
        return [self._collection(db, collection).index["name"]]

    def describe_index(self, db: str, collection: str, index: str) -> list[dict]:
        c = self._collection(db, collection)
        if index != c.index["name"]:
            raise VectorDbError(f"Milvus 오류 700: index not found[{index}]", 502)
        return [{"fieldName": c.vector, "indexName": index, "indexType": c.index["type"], "metricType": c.metric, "indexState": "Finished",
                 "totalRows": len(c.rows), "indexedRows": len(c.rows), "pendingRows": 0, "failReason": "", "params": dict(c.index.get("params", {}))}]

    def query(self, db: str, collection: str, *, filter: str, output_fields: list[str], partitions: list[str] | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        c = self._collection(db, collection)
        rows = c.select(filter, partitions)
        if output_fields == ["count(*)"]:
            return [{"count(*)": len(rows)}]
        if offset + limit >= MAX_WINDOW:
            raise VectorDbError("Milvus 오류 1100: invalid max query result window, (offset+limit) should be in range [1, 16384]", 502)
        return [c.project(row, output_fields) for row in rows[offset:offset + limit]]

    def get(self, db: str, collection: str, ids: list, output_fields: list[str]) -> list[dict]:
        c = self._collection(db, collection)
        return [c.project(c.by_pk[i], output_fields) for i in ids if i in c.by_pk]

    def search(self, db: str, collection: str, *, vector: list[float], anns_field: str, limit: int, output_fields: list[str], filter: str | None = None, partitions: list[str] | None = None) -> list[dict]:
        c = self._collection(db, collection)
        if anns_field != c.vector:
            raise VectorDbError(f"Milvus 오류 1100: field {anns_field} is not a vector field", 502)
        q_norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        scored = []
        for row in c.select(filter or "", partitions):
            other = row[c.vector]
            if c.metric == "L2":
                distance = sum((a - b) ** 2 for a, b in zip(vector, other))
            else:
                distance = sum(a * b for a, b in zip(vector, other))
                if c.metric == "COSINE":
                    distance /= q_norm * (math.sqrt(sum(x * x for x in other)) or 1.0)
            scored.append((distance, row))
        scored.sort(key=lambda item: item[0], reverse=c.metric != "L2")
        return [{**c.project(row, output_fields), "distance": round(distance, 6)} for distance, row in scored[:limit]]


# ---------------------------------------------------------------- 스키마 정리와 필드 자동 감지

_TYPES = {"bool": "BOOL", "int8": "INT8", "int16": "INT16", "int32": "INT32", "int64": "INT64", "float": "FLOAT", "double": "DOUBLE",
          "string": "STRING", "varchar": "VARCHAR", "array": "ARRAY", "json": "JSON", "geometry": "GEOMETRY", "timestamptz": "TIMESTAMPTZ",
          "binaryvector": "BINARY_VECTOR", "floatvector": "FLOAT_VECTOR", "float16vector": "FLOAT16_VECTOR", "bfloat16vector": "BFLOAT16_VECTOR",
          "sparsefloatvector": "SPARSE_FLOAT_VECTOR", "int8vector": "INT8_VECTOR"}
STRING_TYPES = {"VARCHAR", "STRING"}
INT_TYPES = {"INT8", "INT16", "INT32", "INT64"}
NUMERIC_TYPES = INT_TYPES | {"FLOAT", "DOUBLE"}
TEXT_NAMES = ("text", "content", "page_content", "chunk", "chunk_text", "contents", "body", "passage", "document")
DOC_NAMES = ("doc_id", "document_id", "id", "docid", "source_id", "source", "file_name", "filename", "file_path", "path", "doc_name", "title")
ORDER_NAMES = ("chunk_index", "chunk_idx", "chunk_id", "chunk_no", "chunk_seq", "seq", "sequence", "start_index", "start", "position", "idx")
SOURCE_NAMES = ("source", "file_name", "filename", "file_path", "path", "url", "uri", "title", "doc_name")
PAGE_NAMES = ("page", "page_no", "page_number", "page_num", "page_index")


def canonical_type(value: Any) -> str:
    if value in (None, ""):
        return ""
    return _TYPES.get(re.sub(r"[^a-z0-9]", "", str(value).lower()), str(value).upper())


def _params(items: Any) -> dict:
    if isinstance(items, dict):
        return {str(key): value for key, value in items.items()}
    return {str(item["key"]): item.get("value") for item in items or [] if isinstance(item, dict) and "key" in item}


def _field(raw: dict) -> dict:
    params = _params(raw.get("params"))
    kind = canonical_type(raw.get("type") or raw.get("dataType"))
    nullable = raw.get("nullable")
    return {
        "name": str(raw["name"]), "type": kind, "element_type": canonical_type(raw.get("elementType") or params.get("element_type")) or None,
        "dim": _int(params.get("dim", raw.get("dim"))), "max_length": _int(params.get("max_length", raw.get("max_length"))),
        "max_capacity": _int(params.get("max_capacity")), "primary_key": bool(raw.get("primaryKey")), "auto_id": bool(raw.get("autoId", raw.get("autoID"))),
        "nullable": nullable if isinstance(nullable, bool) else None, "partition_key": bool(raw.get("partitionKey")),
        "description": str(raw.get("description") or ""), "is_vector": kind.endswith("_VECTOR"),
    }


def _pick(fields: list[dict], names: tuple[str, ...]) -> str | None:
    by_lower = {f["name"].lower(): f["name"] for f in fields}
    return next((by_lower[name] for name in names if name in by_lower), None)


def detect_fields(fields: list[dict]) -> dict:
    """화면 기본값. 사용자가 텍스트·문서·순서 필드를 바꿀 수 있다."""
    pk = next((f["name"] for f in fields if f["primary_key"]), None)
    vectors = [f for f in fields if f["is_vector"]]
    vector = next((f["name"] for f in vectors if f["type"] == "FLOAT_VECTOR"), vectors[0]["name"] if vectors else None)
    varchars = [f for f in fields if f["type"] in STRING_TYPES and not f["primary_key"]]
    text = _pick(varchars, TEXT_NAMES)
    if not text:
        loose = [f for f in varchars if re.search(r"text|content|chunk|passage|body", f["name"], re.I) and not re.search(r"(^|_)(id|idx|index|no|num|seq|hash|type|len|length|count)$", f["name"], re.I)]
        text = loose[0]["name"] if loose else None
    if not text:
        long = [f for f in varchars if (f["max_length"] or 0) >= 2048 and f["name"].lower() not in DOC_NAMES + SOURCE_NAMES]
        text = max(long, key=lambda f: f["max_length"] or 0)["name"] if long else None
    keys = [f for f in fields if not f["is_vector"] and not f["primary_key"] and f["name"] != text and f["type"] in STRING_TYPES | NUMERIC_TYPES]
    doc = _pick(keys, DOC_NAMES)
    rest = [f for f in keys if f["name"] != doc]
    order = _pick(rest, ORDER_NAMES)
    source = _pick([f for f in rest if f["name"] != order and f["type"] in STRING_TYPES], SOURCE_NAMES)
    page = _pick([f for f in rest if f["name"] != order and f["type"] in NUMERIC_TYPES], PAGE_NAMES)
    return {"pk": pk, "text": text, "doc": doc, "order": order, "source": source, "page": page, "vector": vector}


class Schema:
    def __init__(self, describe: dict):
        self.desc = describe or {}
        self.fields = [_field(f) for f in self.desc.get("fields") or [] if isinstance(f, dict) and f.get("name")]
        self.by_name = {f["name"]: f for f in self.fields}
        pk = next((f for f in self.fields if f["primary_key"]), None)
        if pk is None:
            raise VectorDbError("컬렉션 스키마에서 기본 키 필드를 찾지 못했습니다.", 502)
        self.pk = pk
        self.vectors = [f for f in self.fields if f["is_vector"]]
        self.scalars = [f for f in self.fields if not f["is_vector"]]
        self.dynamic = bool(self.desc.get("enableDynamicField"))
        self.detected = detect_fields(self.fields)

    def field(self, name: str, *, what: str = "필드", scalar: bool = True) -> dict:
        found = self.by_name.get(name)
        if found is None:
            raise VectorDbError(f"{what} '{name}'이(가) 컬렉션에 없습니다.")
        if scalar and found["is_vector"]:
            raise VectorDbError(f"{what}로 벡터 필드를 쓸 수 없습니다.")
        return found

    def text_field(self, override: str | None) -> str | None:
        if override is None:
            return self.detected["text"]
        if override == "":
            return None
        if self.field(override, what="텍스트 필드")["type"] not in STRING_TYPES:
            raise VectorDbError("텍스트 필드는 VARCHAR 형식이어야 합니다.")
        return override

    def vector_field(self) -> dict | None:
        name = self.detected["vector"]
        return self.by_name.get(name) if name else None

    def pk_value(self, value: str) -> Any:
        return coerce(value, self.pk)

    def default_filter(self) -> str:
        name = self.pk["name"]
        return f'{name} != ""' if self.pk["type"] in STRING_TYPES else f"{name} >= -9223372036854775807"

    def metric_for(self, field: str) -> str | None:
        return next((str(ix.get("metricType")) for ix in self.desc.get("indexes") or [] if isinstance(ix, dict) and ix.get("fieldName") == field and ix.get("metricType")), None)


def coerce(value: Any, field: dict) -> Any:
    if field["type"] in INT_TYPES:
        try:
            return int(str(value).strip())
        except ValueError:
            raise VectorDbError(f"'{field['name']}'은(는) 정수 필드입니다.") from None
    if field["type"] in {"FLOAT", "DOUBLE"}:
        try:
            return float(str(value).strip())
        except ValueError:
            raise VectorDbError(f"'{field['name']}'은(는) 숫자 필드입니다.") from None
    if field["type"] == "BOOL":
        return str(value).strip().lower() in {"true", "1", "예"}
    return str(value)


def literal(value: Any, field: dict) -> str:
    value = coerce(value, field)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value, ensure_ascii=False)


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return str(value) if abs(value) > JS_SAFE else value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (bytes, bytearray)):
        return base64.b64encode(bytes(value)).decode("ascii")
    return str(value)


def vector_summary(value: Any, field: dict, head: int = 16) -> dict:
    """벡터를 그대로 보내지 않고 차원·노름·범위·앞부분 값만 요약한다."""
    if isinstance(value, list) and value and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value[:8]):
        numbers = [float(x) for x in value]
        return {"kind": "dense", "type": field["type"], "dim": len(numbers), "norm": round(math.sqrt(sum(x * x for x in numbers)), 4),
                "min": round(min(numbers), 4), "max": round(max(numbers), 4), "mean": round(sum(numbers) / len(numbers), 5),
                "head": [round(x, 4) for x in numbers[:head]]}
    if isinstance(value, dict):
        return {"kind": "sparse", "type": field["type"], "dim": field.get("dim"), "nnz": len(value)}
    return {"kind": "opaque", "type": field["type"], "dim": field.get("dim")}


def natural_key(value: Any) -> tuple:
    if isinstance(value, bool) or value is None:
        return (2, ())
    if isinstance(value, (int, float)):
        return (0, (float(value),))
    parts = re.split(r"(\d+)", str(value))
    return (1, tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in parts if part))


def overlap(prev: str, cur: str, minimum: int = 8, cap: int = 4000) -> tuple[int, int]:
    """앞 청크 끝과 현재 청크 앞이 같은 길이. (현재 청크에서 건너뛸 글자 수, 겹친 길이)를 돌려준다."""
    if not prev or not cur:
        return 0, 0
    a = prev.rstrip()[-cap:]
    stripped = cur.lstrip()
    lead = len(cur) - len(stripped)
    b = stripped[:cap]
    s = b + "\x00" + a
    pi = [0] * len(s)
    for i in range(1, len(s)):
        k = pi[i - 1]
        while k and s[i] != s[k]:
            k = pi[k - 1]
        if s[i] == s[k]:
            k += 1
        pi[i] = k
    length = pi[-1] if s else 0
    return (lead + length, length) if length >= minimum else (0, 0)


# ---------------------------------------------------------------- 화면용 조회

def sources_info(config: MilvusConfig | None = None) -> dict:
    """화면이 처음 열릴 때 부른다. Milvus에는 요청하지 않고, 최근 연결 실패가 있으면 예시 데이터를 기본으로 권한다."""
    config = config or MilvusConfig.from_env()
    paused = unreachable_state(MilvusSource(config).api_base) if config.configured else None
    return {"default": "milvus" if config.configured and not paused else "example",
            "sources": [{"key": "example", "label": "예시 데이터", "available": True}, {"key": "milvus", "label": "Milvus 연결", "available": config.configured}],
            "milvus": {**config.public(), "unreachable": paused}, "max_window": MAX_WINDOW}


def get_source(key: str):
    if key == "example":
        return ExampleSource()
    if key == "milvus":
        config = MilvusConfig.from_env()
        if not config.configured:
            raise VectorDbError("Milvus 주소(MILVUS_URI)가 설정되지 않았습니다.", 409)
        return MilvusSource(config)
    raise VectorDbError("알 수 없는 데이터 출처입니다.", 404)


def check_connection(config: MilvusConfig | None = None) -> dict:
    """사용자가 누를 때만 실행한다. 데이터베이스 목록을 한 번 조회한다."""
    config = config or MilvusConfig.from_env()
    if not config.configured:
        return {"ok": False, "status": None, "latency_ms": 0, "error": "MILVUS_URI가 설정되지 않았습니다."}
    source, started = MilvusSource(config), time.monotonic()
    clear_unreachable(source.api_base)  # 사용자가 직접 누른 확인은 쉬는 중이어도 실제로 요청해 본다
    try:
        try:
            databases, note = source.databases(), None
        except VectorDbError as exc:
            if exc.upstream in (401, 403) or unreachable_state(source.api_base):
                raise  # 연결 자체가 안 되면 다른 경로로 한 번 더 시도하지 않고 처음 오류를 보여 준다
            source.collections(config.db)
            databases, note = [config.db], f"데이터베이스 목록은 볼 수 없어 {config.db}만 확인했습니다."
    except VectorDbError as exc:
        return {"ok": False, "status": exc.upstream, "code": exc.code, "latency_ms": round((time.monotonic() - started) * 1000), "error": exc.message}
    return {"ok": True, "status": 200, "latency_ms": round((time.monotonic() - started) * 1000), "databases": databases[:100],
            "db": config.db, "db_found": config.db in databases, "note": note}


def _databases(source) -> tuple[list[str], list[str]]:
    try:
        names = source.databases()
    except VectorDbError as exc:
        if exc.upstream in (401, 403) or not isinstance(source, MilvusSource) or unreachable_state(source.api_base):
            raise
        source.collections(source.default_db)
        return [source.default_db], [f"데이터베이스 목록을 볼 수 없어 {source.default_db}만 표시합니다."]
    names = list(dict.fromkeys(names))
    if source.default_db in names:
        names.remove(source.default_db)
        names.insert(0, source.default_db)
    return names, []


def _partition_counts(source, db: str, collection: str, workers: int = 8) -> list[dict]:
    def one(name: str) -> dict:
        try:
            return {"name": name, "row_count": source.partition_rows(db, collection, name), "error": None}
        except VectorDbError as exc:
            return {"name": name, "row_count": None, "error": exc.message}
    return _map(one, source.partitions(db, collection), workers)


def _collection_node(source, db: str, name: str) -> dict:
    node: dict = {"name": name, "row_count": None, "dim": None, "vector_field": None, "vector_fields": 0, "metric": None, "load_state": None, "partitions": [], "error": None}
    errors = []
    try:
        schema = Schema(source.describe(db, name))
        vector = schema.vector_field()
        node.update(load_state=schema.desc.get("load") or None, vector_fields=len(schema.vectors), description=str(schema.desc.get("description") or ""))
        if vector:
            node.update(dim=vector["dim"], vector_field=vector["name"], metric=schema.metric_for(vector["name"]))
    except VectorDbError as exc:
        errors.append(exc.message)
    try:
        node["row_count"] = source.row_count(db, name)
    except VectorDbError as exc:
        errors.append(exc.message)
    try:
        node["partitions"] = _partition_counts(source, db, name, workers=1)
    except VectorDbError as exc:
        errors.append(exc.message)
    node["error"] = errors[0] if errors else None
    return node


def tree(source) -> dict:
    databases, warnings = _databases(source)

    def listing(db: str) -> dict:
        try:
            return {"name": db, "names": source.collections(db), "error": None}
        except VectorDbError as exc:
            return {"name": db, "names": [], "error": exc.message}

    listed = _map(listing, databases, 4)
    tasks = [(entry["name"], name) for entry in listed for name in entry["names"]]
    nodes = dict(zip(tasks, _map(lambda task: _collection_node(source, *task), tasks, 8)))
    out = [{"name": entry["name"], "error": entry["error"], "collections": [nodes[(entry["name"], name)] for name in entry["names"]]} for entry in listed]
    collections = [c for db in out for c in db["collections"]]
    return {"source": source.key, "databases": out, "warnings": warnings,
            "totals": {"databases": len(out), "collections": len(collections), "partitions": sum(len(c["partitions"]) for c in collections),
                       "rows": sum(c["row_count"] or 0 for c in collections)}}


def _index_info(source, db: str, collection: str, schema: Schema) -> tuple[dict[str, dict], list[str]]:
    info: dict[str, dict] = {}
    warnings: list[str] = []
    names = []
    for ix in schema.desc.get("indexes") or []:
        if isinstance(ix, dict) and ix.get("fieldName"):
            info.setdefault(str(ix["fieldName"]), {}).update(index_name=ix.get("indexName"), metric=ix.get("metricType"))
            if ix.get("indexName"):
                names.append(str(ix["indexName"]))
    if not names:
        try:
            names = source.index_names(db, collection)
        except VectorDbError as exc:
            warnings.append(f"인덱스 목록: {exc.message}")
    for name in dict.fromkeys(names):
        try:
            described = source.describe_index(db, collection, name)
        except VectorDbError as exc:
            warnings.append(f"인덱스 {name}: {exc.message}")
            continue
        for item in described:
            params = _params(item.get("params"))
            nested = params.pop("params", None)
            if isinstance(nested, str):
                try:
                    nested = json.loads(nested)
                except ValueError:
                    nested = None
            if isinstance(nested, dict):
                params.update(nested)
            index_type = item.get("indexType") or params.get("index_type")
            metric = item.get("metricType") or params.get("metric_type")
            extra = {k: jsonable(v) for k, v in params.items() if k not in ("index_type", "metric_type")}
            field = str(item.get("fieldName") or "")
            entry = info.setdefault(field, {})
            entry.update({k: v for k, v in {"index_name": item.get("indexName") or name, "index_type": index_type, "metric": metric,
                                            "index_params": extra if "params" in item or extra else None, "index_state": item.get("indexState"),
                                            "indexed_rows": _int(item.get("indexedRows")), "total_rows": _int(item.get("totalRows")),
                                            "pending_rows": _int(item.get("pendingRows")), "fail_reason": item.get("failReason") or None}.items() if v is not None or k not in entry})
    return info, warnings


_MODEL_TEXT = re.compile(r"(?:embedding[ _-]?model|embed[ _-]?model|model[ _-]?(?:name|id)?|임베딩\s*모델)\s*[:=]\s*([^\s,;|)]+)", re.I)


def embedding_record(schema: Schema, vector: dict | None) -> dict:
    props = _params(schema.desc.get("properties"))
    model = where = None
    recorded_dim = None
    for key, value in props.items():
        if value in (None, ""):
            continue
        if re.search(r"(embed|vector).*dim|^dim(ension)?$", key, re.I):
            recorded_dim = recorded_dim or _int(value)
        elif re.search(r"embed|model", key, re.I) and model is None:
            model, where = str(value), f"컬렉션 속성 {key}"
    if model is None and vector:
        match = _MODEL_TEXT.search(vector["description"])
        if match:
            model, where = match.group(1), f"벡터 필드 {vector['name']} 설명"
    if model is None:
        match = _MODEL_TEXT.search(str(schema.desc.get("description") or ""))
        if match:
            model, where = match.group(1), "컬렉션 설명"
    dim = vector["dim"] if vector else None
    return {"model": model, "recorded_in": where, "dim": dim, "recorded_dim": recorded_dim, "dim_mismatch": bool(recorded_dim and dim and recorded_dim != dim)}


def collection_detail(source, db: str, collection: str) -> dict:
    schema = Schema(source.describe(db, collection))
    warnings: list[str] = []

    def safe(label: str, fn: Callable, default=None):
        try:
            return fn()
        except VectorDbError as exc:
            warnings.append(f"{label}: {exc.message}")
            return default

    rows = safe("행 수", lambda: source.row_count(db, collection))
    partitions = safe("파티션", lambda: _partition_counts(source, db, collection), [])
    load = safe("로드 상태", lambda: source.load_state(db, collection), {}) or {}
    indexes, index_warnings = _index_info(source, db, collection, schema)
    warnings += index_warnings
    vector = schema.vector_field()
    fields = [{**f, "index_type": indexes.get(f["name"], {}).get("index_type")} for f in schema.fields]
    vectors = [{"name": f["name"], "type": f["type"], "dim": f["dim"], "description": f["description"], **{k: indexes.get(f["name"], {}).get(k) for k in
               ("index_name", "index_type", "metric", "index_params", "index_state", "indexed_rows", "total_rows", "pending_rows", "fail_reason")}} for f in schema.vectors]
    return {
        "db": db, "name": collection, "description": str(schema.desc.get("description") or ""), "row_count": rows,
        "load_state": load.get("loadState") or schema.desc.get("load") or None, "load_progress": _int(load.get("loadProgress")),
        "consistency_level": schema.desc.get("consistencyLevel"), "shards": _int(schema.desc.get("shardsNum")),
        "partitions_num": _int(schema.desc.get("partitionsNum")) or len(partitions), "auto_id": bool(schema.desc.get("autoID", schema.pk["auto_id"])),
        "enable_dynamic_field": schema.dynamic, "aliases": [str(a) for a in schema.desc.get("aliases") or []],
        "properties": [{"key": k, "value": jsonable(v)} for k, v in _params(schema.desc.get("properties")).items()],
        "fields": fields, "vector_fields": vectors, "partitions": partitions, "detected": schema.detected,
        "embedding": embedding_record(schema, vector), "warnings": warnings,
    }


def _row(raw: dict, schema: Schema, text_field: str | None, head: int) -> dict:
    fields, vector = {}, None
    vector_name = schema.detected["vector"]
    for key, value in raw.items():
        if key == text_field or key == "distance":
            continue
        field = schema.by_name.get(key)
        if field and field["is_vector"]:
            if key == vector_name:
                vector = vector_summary(value, field, head)
            continue
        fields[key] = jsonable(value)
    pk = raw.get(schema.pk["name"], raw.get("id"))
    text = raw.get(text_field) if text_field else None
    return {"pk": str(pk), "text": text if isinstance(text, str) else None, "fields": fields, "vector": vector, "partition": None}


def _membership(source, db: str, collection: str, schema: Schema, pks: list, partitions: list[str]) -> dict[str, str]:
    """Milvus 조회 결과에는 파티션 이름이 없다. 파티션이 적으면 파티션별로 같은 pk를 다시 조회해 찾는다."""
    if not pks or not partitions:
        return {}
    if len(partitions) == 1:
        return {str(pk): partitions[0] for pk in pks}
    if len(partitions) > MAX_PARTITION_LOOKUP:
        return {}
    name = schema.pk["name"]
    expression = f"{name} in [{', '.join(literal(pk, schema.pk) for pk in pks)}]"

    def one(partition: str) -> tuple[str, list[dict]]:
        try:
            return partition, source.query(db, collection, filter=expression, output_fields=[name], partitions=[partition], limit=len(pks))
        except VectorDbError:
            return partition, []

    found: dict[str, str] = {}
    for partition, rows in _map(one, partitions):
        for row in rows:
            found.setdefault(str(row.get(name)), partition)
    return found


def _count(source, db: str, collection: str, expression: str, partitions: list[str] | None) -> int | None:
    try:
        rows = source.query(db, collection, filter=expression, output_fields=["count(*)"], partitions=partitions)
        return _int(rows[0].get("count(*)")) if rows else None
    except VectorDbError:
        return None


def browse(source, db: str, collection: str, *, filter: str = "", partition: str | None = None, output_fields: list[str] | None = None,
           text_field: str | None = None, limit: int = 50, offset: int = 0, include_vector: bool = True) -> dict:
    limit, offset = max(1, min(int(limit), 200)), max(0, int(offset))
    if offset + limit >= MAX_WINDOW:
        raise VectorDbError(f"Milvus 조회는 앞에서 {MAX_WINDOW:,}건 안쪽만 넘겨 볼 수 있습니다. 조건을 좁혀 주세요.")
    schema = Schema(source.describe(db, collection))
    text = schema.text_field(text_field)
    if output_fields is None:
        chosen = [f["name"] for f in schema.scalars if f["name"] not in (schema.pk["name"], text)]
    else:
        chosen = []
        for name in output_fields:
            if name in (schema.pk["name"], text):
                continue
            if name in schema.by_name:
                schema.field(name, what="출력 필드")
            elif not schema.dynamic:
                raise VectorDbError(f"출력 필드 '{name}'이(가) 컬렉션에 없습니다.")
            chosen.append(name)
    vector = schema.vector_field() if include_vector else None
    request_fields = list(dict.fromkeys([schema.pk["name"], *([text] if text else []), *chosen, *([vector["name"]] if vector else [])]))
    expression = filter.strip() or schema.default_filter()
    parts = [partition] if partition else None
    raw = source.query(db, collection, filter=expression, output_fields=request_fields, partitions=parts, limit=limit, offset=offset)
    total = _count(source, db, collection, expression, parts)
    total_basis = "count" if total is not None else None
    if total is None and not filter.strip():
        try:
            total = source.partition_rows(db, collection, partition) if partition else source.row_count(db, collection)
            total_basis = "stats"
        except VectorDbError:
            total = None
    rows = [_row(item, schema, text, 16) for item in raw]
    if partition:
        for row in rows:
            row["partition"] = partition
    elif rows:
        try:
            names = source.partitions(db, collection)
        except VectorDbError:
            names = []
        found = _membership(source, db, collection, schema, [schema.pk_value(row["pk"]) for row in rows], names)
        for row in rows:
            row["partition"] = found.get(row["pk"])
    return {"rows": rows, "total": total, "total_basis": total_basis, "effective_filter": expression, "user_filter": filter.strip(),
            "text_field": text, "output_fields": chosen, "limit": limit, "offset": offset, "partition": partition, "max_window": MAX_WINDOW}


def chunk_detail(source, db: str, collection: str, pk: str, *, text_field: str | None = None) -> dict:
    schema = Schema(source.describe(db, collection))
    text = schema.text_field(text_field)
    rows = source.get(db, collection, [schema.pk_value(pk)], [f["name"] for f in schema.fields])
    if not rows:
        raise VectorDbError("청크를 찾을 수 없습니다.", 404)
    row = _row(rows[0], schema, text, 32)
    try:
        names = source.partitions(db, collection)
    except VectorDbError:
        names = []
    row["partition"] = _membership(source, db, collection, schema, [schema.pk_value(pk)], names).get(row["pk"])
    return {**row, "text_field": text, "detected": schema.detected}


def similar(source, db: str, collection: str, pk: str, *, text_field: str | None = None, doc_field: str | None = None, limit: int = 10) -> dict:
    """그 청크에 저장된 벡터로 검색한다. 임베딩 모델 호출이 필요 없다."""
    schema = Schema(source.describe(db, collection))
    text = schema.text_field(text_field)
    doc = schema.detected["doc"] if doc_field is None else (doc_field or None)
    if doc:
        schema.field(doc, what="문서 필드")
    vector = schema.vector_field()
    if vector is None:
        raise VectorDbError("벡터 필드가 없어 비슷한 청크를 찾을 수 없습니다.")
    order = schema.detected["order"]
    key = schema.pk_value(pk)
    got = source.get(db, collection, [key], [vector["name"], *([doc] if doc else [])])
    if not got:
        raise VectorDbError("청크를 찾을 수 없습니다.", 404)
    values = got[0].get(vector["name"])
    if not (isinstance(values, list) and values and all(isinstance(x, (int, float)) for x in values[:8])):
        raise VectorDbError(f"{vector['type']} 벡터는 이 화면에서 유사 검색을 지원하지 않습니다.")
    own_doc = got[0].get(doc) if doc else None
    metric = schema.metric_for(vector["name"])
    if metric is None:
        try:
            metric = _index_info(source, db, collection, schema)[0].get(vector["name"], {}).get("metric")
        except VectorDbError:
            metric = None
    outputs = list(dict.fromkeys(f for f in (text, doc, order, schema.detected["page"]) if f))
    hits_raw = source.search(db, collection, vector=values, anns_field=vector["name"], limit=min(limit + 1, 100), output_fields=outputs)
    hits = []
    for hit in hits_raw:
        hit_pk = hit.get(schema.pk["name"], hit.get("id"))
        if str(hit_pk) == str(key):
            continue
        hit_doc = hit.get(doc) if doc else None
        hits.append({"rank": len(hits) + 1, "pk": str(hit_pk), "score": hit.get("distance"), "text": hit.get(text) if text else None,
                     "doc": jsonable(hit_doc), "order": jsonable(hit.get(order)) if order else None, "page": jsonable(hit.get(schema.detected["page"])) if schema.detected["page"] else None,
                     "same_document": (hit_doc == own_doc) if doc and own_doc is not None else None})
        if len(hits) >= limit:
            break
    upper = (metric or "").upper()
    return {"pk": str(key), "metric": metric, "higher_is_closer": None if not upper else upper not in ("L2", "HAMMING", "JACCARD"),
            "vector_field": vector["name"], "doc_field": doc, "doc": jsonable(own_doc), "text_field": text, "hits": hits}


def document_values(source, db: str, collection: str, doc_field: str) -> dict:
    schema = Schema(source.describe(db, collection))
    field = schema.field(doc_field, what="문서 필드")
    rows = source.query(db, collection, filter=schema.default_filter(), output_fields=[field["name"]], limit=MAX_FETCH)
    counts = Counter(str(jsonable(row.get(field["name"]))) for row in rows if row.get(field["name"]) not in (None, ""))
    values = [{"value": value, "count": count} for value, count in sorted(counts.items(), key=lambda item: natural_key(item[0]))]
    return {"doc_field": field["name"], "values": values, "scanned": len(rows), "truncated": len(rows) >= MAX_FETCH}


def read_document(source, db: str, collection: str, doc_field: str, value: str, *, order_field: str | None = None, text_field: str | None = None) -> dict:
    """한 문서의 청크를 모두 가져와 순서대로 잇는다. 겹친 부분은 앞뒤 청크의 끝·앞이 같은 길이로 찾는다."""
    schema = Schema(source.describe(db, collection))
    field = schema.field(doc_field, what="문서 필드")
    text = schema.text_field(text_field)
    order = schema.detected["order"] if order_field is None else (order_field or None)
    if order:
        schema.field(order, what="순서 필드")
    page = schema.detected["page"]
    outputs = list(dict.fromkeys(f for f in (text, field["name"], order, page) if f))
    rows = source.query(db, collection, filter=f"{field['name']} == {literal(value, field)}", output_fields=outputs, limit=MAX_FETCH)
    pk = schema.pk["name"]
    rows.sort(key=lambda r: ((natural_key(r.get(order)) if order else ()), natural_key(r.get(pk))))
    chunks, previous = [], None
    for index, row in enumerate(rows):
        body = row.get(text) if text else None
        body = body if isinstance(body, str) else None
        skip, length = overlap(previous, body) if previous and body else (0, 0)
        if chunks and length:
            chunks[-1]["tail"] = [len(previous.rstrip()) - length, len(previous.rstrip())]
        chunks.append({"index": index, "pk": str(row.get(pk)), "order": jsonable(row.get(order)) if order else None,
                       "page": jsonable(row.get(page)) if page else None, "text": body, "head_skip": skip, "overlap": length, "tail": None})
        previous = body
    overlaps = [c["overlap"] for c in chunks if c["overlap"]]
    return {"doc_field": field["name"], "value": value, "order_field": order, "ordered_by": order or pk, "text_field": text,
            "chunks": chunks, "total": len(chunks), "truncated": len(rows) >= MAX_FETCH,
            "overlaps": len(overlaps), "overlap_avg": round(sum(overlaps) / len(overlaps)) if overlaps else 0}
