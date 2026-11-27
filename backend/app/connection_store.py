"""화면에서 저장한 모델 연결(생성 모델·임베딩)을 실행 폴더에 보관하고 .env 값 위에 덮어쓴다.

- 저장한 항목만 덮어쓴다. 비워 둔 항목은 .env·환경변수 값을 그대로 쓴다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

from app.llm import ModelConnection

CHAT_KEYS = {"primary": "MODEL", "secondary": "MODEL2"}
EMBED_PREFIX = "EMBED"
OCR_FIELDS = (("label", "LABEL"), ("base_url", "BASE_URL"), ("model_id", "MODEL"), ("api_key", "API_KEY"), ("mode", "MODE"),
              ("text_prompt", "TEXT_PROMPT"), ("table_prompt", "TABLE_PROMPT"), ("page_prompt", "PAGE_PROMPT"))
MAX_EMBED_MODELS = 8
_FIELDS = ("label", "base_url", "model_id", "api_key")


class StoreError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 입력 오류."""


def _text(value, name: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise StoreError(f"{name} 값은 글자여야 합니다.")
    value = value.strip()
    if len(value) > limit:
        raise StoreError(f"{name}은(는) {limit}자 이하여야 합니다.")
    if any(ord(ch) < 32 for ch in value):
        raise StoreError(f"{name}에 줄바꿈·제어 문자를 넣을 수 없습니다.")
    return value


def clean_url(value) -> str:
    url = _text(value, "Base URL", 500).rstrip("/")
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        raise StoreError("Base URL 형식이 올바르지 않습니다.") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise StoreError("Base URL은 http:// 또는 https://로 시작해야 합니다.")
    if parts.username or parts.password:
        raise StoreError("Base URL에 계정 정보를 넣지 말고 API 키 칸을 쓰세요.")
    return url


def clean_models(value) -> list[str]:
    if value is None:
        return []
    items = value.split(",") if isinstance(value, str) else value
    if not isinstance(items, list):
        raise StoreError("모델 ID 목록 형식이 올바르지 않습니다.")
    out = list(dict.fromkeys(_text(item, "모델 ID", 200) for item in items if isinstance(item, str) and item.strip()))
    if len(out) > MAX_EMBED_MODELS:
        raise StoreError(f"임베딩 모델은 {MAX_EMBED_MODELS}개까지 저장할 수 있습니다.")
    if any("," in item for item in out):
        raise StoreError("모델 ID에는 쉼표를 넣을 수 없습니다.")
    return out


def clean_patch(body: dict, embed: bool) -> dict:
    if not isinstance(body, dict):
        raise StoreError("설정 형식이 올바르지 않습니다.")
    patch: dict = {"label": _text(body.get("label"), "이름", 40), "base_url": clean_url(body.get("base_url"))}
    if embed:
        patch["models"] = clean_models(body.get("models"))
    else:
        patch["model_id"] = _text(body.get("model_id"), "Model ID", 200)
    if body.get("clear_api_key") is True:
        patch["api_key"] = ""
    elif isinstance(body.get("api_key"), str) and body["api_key"].strip():
        patch["api_key"] = _text(body["api_key"], "API 키", 4096)
    return patch


def clean_ocr_patch(body: dict) -> dict:
    if not isinstance(body, dict):
        raise StoreError("설정 형식이 올바르지 않습니다.")
    patch = {"label": _text(body.get("label"), "이름", 40), "base_url": clean_url(body.get("base_url")),
             "model_id": _text(body.get("model_id"), "Model ID", 200)}
    mode = str(body.get("mode") or "region").strip().lower()
    if mode not in ("region", "page"):
        raise StoreError("OCR 방식은 region(영역) 또는 page(쪽)여야 합니다.")
    patch["mode"] = mode
    for field, name in (("text_prompt", "글자 지시문"), ("table_prompt", "표 지시문"), ("page_prompt", "쪽 지시문")):
        patch[field] = _text(body.get(field), name, 500)
    if body.get("clear_api_key") is True:
        patch["api_key"] = ""
    elif isinstance(body.get("api_key"), str) and body["api_key"].strip():
        patch["api_key"] = _text(body["api_key"], "API 키", 4096)
    return patch


class ConnectionStore:
    def __init__(self, root: Path):
        self.path = root / "settings" / "connections.json"
        self.lock = threading.Lock()

    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def save(self, slot: str, patch: dict) -> None:
        """slot: primary | secondary | embed. 기존 저장값 위에 덮어쓴다(키를 보내지 않으면 저장된 키 유지)."""
        with self.lock:
            data = self.read()
            current = data.get(slot) if isinstance(data.get(slot), dict) else {}
            data[slot] = {**current, **patch}
            self._write(data)

    def forget(self, slot: str) -> bool:
        with self.lock:
            data = self.read()
            if slot not in data:
                return False
            del data[slot]
            self._write(data)
            return True

    def saved(self, slot: str) -> dict | None:
        entry = self.read().get(slot)
        return entry if isinstance(entry, dict) else None

    # ---------------------------------------------------------- 적용
    def environ(self, base=None) -> dict:
        env = dict(os.environ if base is None else base)
        data = self.read()
        for slot, prefix in CHAT_KEYS.items():
            entry = data.get(slot)
            if not isinstance(entry, dict):
                continue
            for field, suffix in (("label", "LABEL"), ("base_url", "BASE_URL"), ("model_id", "ID"), ("api_key", "API_KEY")):
                if field in entry:
                    env[f"{prefix}_{suffix}"] = entry[field]
        entry = data.get("embed")
        if isinstance(entry, dict):
            for field, suffix in (("label", "LABEL"), ("base_url", "BASE_URL"), ("api_key", "API_KEY")):
                if field in entry:
                    env[f"{EMBED_PREFIX}_{suffix}"] = entry[field]
            if "models" in entry and isinstance(entry["models"], list):
                env[f"{EMBED_PREFIX}_MODELS"] = ",".join(entry["models"])
        entry = data.get("ocr")
        if isinstance(entry, dict):
            for field, suffix in OCR_FIELDS:
                if field in entry:
                    env[f"OCR_{suffix}"] = entry[field]
        return env

    def chat_connections(self, startup: tuple[ModelConnection, ...]) -> list[ModelConnection]:
        data = self.read()
        by_key = {conn.key: conn for conn in startup}
        out = []
        for index, slot in enumerate(CHAT_KEYS, start=1):
            base = by_key.get(slot)
            entry = data.get(slot) if isinstance(data.get(slot), dict) else None
            if base is None and entry is None:
                continue
            base = base or ModelConnection(slot, f"모델 {index}", "", "", "")
            if entry:
                base = ModelConnection(slot, entry.get("label") or base.label, (entry["base_url"] if "base_url" in entry else base.base_url).rstrip("/"),
                                       entry["api_key"] if "api_key" in entry else base.api_key, entry["model_id"] if "model_id" in entry else base.model_id)
            out.append(base)
        return out


_ACTIVE: ConnectionStore | None = None


def activate(store: ConnectionStore | None) -> None:
    global _ACTIVE
    _ACTIVE = store


def active() -> ConnectionStore | None:
    return _ACTIVE


def effective_environ() -> dict:
    return _ACTIVE.environ() if _ACTIVE else dict(os.environ)
