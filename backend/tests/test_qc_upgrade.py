"""대조 규칙이 바뀐 뒤 기존 실행 다시 대조(리뷰 지적 2). 합성 PDF·임시 저장소만 쓴다.

첫 커밋(f7f7ebb)의 DB를 두 번째 커밋 코드로 열면 같은 규칙 이름의 원장이 그대로 쓰여 숨은 층 PDF의 의심점이 0이었다.
이 테스트는 그 상태(이전 규칙 원장: 의심점 0 + 검수자 판정)를 DB에 만들고, 다시 시작했을 때 재업로드 없이 다시 대조되는지 본다."""
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app import qc
from app.adapters.registry import ParserRegistry
from app.config import Settings
from app.repository import now
from main import create_app
from tests.pdf_fixtures import raster_pdf

pytest.importorskip("pypdfium2")
OLD_RULE = "verify-2026.11.27"


def _old_runtime(tmp_path, monkeypatch):
    """현재 코드로 처리한 뒤, 원장을 '첫 커밋 규칙: 의심점 0'으로 바꿔 두고 검수자 판정(틀림·메모·근거)을 남긴다."""
    monkeypatch.setattr(ParserRegistry, "pdf_models_ready", lambda self: False)
    runtime = tmp_path / "runtime"
    with TestClient(create_app(Settings(runtime_dir=runtime, qc_reverify=False))) as client:
        doc_id = client.post("/api/live/documents", files={"file": ("압력.pdf", raster_pdf(hidden="PRESSURE 71 bar"))}).json()["id"]
        client.post(f"/api/live/documents/{doc_id}/process")
        for _ in range(200):
            if client.get(f"/api/live/documents/{doc_id}").json()["status"] != "processing":
                break
            time.sleep(0.05)
        run_id = client.get(f"/api/live/documents/{doc_id}/runs").json()["runs"][0]["run_id"]
        review = client.post("/api/live/reviews", json={"document_id": doc_id, "page": 1, "line": 1, "note": "압력 값 확인", "status": "wrong",
                                                        "comment": "화면은 17 bar", "source_text": "PRESSURE 17 bar",
                                                        "result_text": "PRESSURE 71 bar", "origin": "console"}).json()
    with sqlite3.connect(runtime / "documents.sqlite3") as conn:
        conn.execute("DELETE FROM qc_findings")
        conn.execute("DELETE FROM qc_runs")
        conn.execute("INSERT INTO qc_runs (document_id, run_id, rule_version, state, machine_state, spots_total, high, blocking, created_at, "
                     "updated_at, completed_at, result) VALUES (?, ?, ?, 'done', 'undetermined', 0, 0, 2, ?, ?, ?, ?)",
                     (doc_id, run_id, OLD_RULE, now(), now(), now(), '{"reasons": [], "summary": {}, "units": [], "notes": [], "spots_total": 0}'))
    return runtime, doc_id, run_id, review


def _wait_reverify(client):
    service = client.app.state.documents
    for _ in range(400):
        if service.reverify_state["state"] in ("done", "failed", "stopped"):
            return service.reverify_state
        time.sleep(0.05)
    raise AssertionError("다시 대조가 끝나지 않았습니다")


def test_rule_change_reverifies_existing_runs_without_reupload_and_keeps_reviews(tmp_path, monkeypatch):
    runtime, doc_id, run_id, review = _old_runtime(tmp_path, monkeypatch)
    with TestClient(create_app(Settings(runtime_dir=runtime))) as client:
        state = _wait_reverify(client)
        assert state["total"] == 1 and state["stale"] == 1 and state["done"] == 1 and state["failed"] == 0
        ledger = client.app.state.documents.repo.qc_run(doc_id, run_id, qc.rule_key())
        assert ledger["state"] == "done" and ledger["spots_total"] == 1 and ledger["high"] == 1  # 조회하기 전에 이미 다시 대조됨
        checked = client.get(f"/api/live/documents/{doc_id}/verify").json()
        assert checked["rule_version"] == qc.rule_key() != OLD_RULE
        assert [(s["kind"], s["severity"], s["source_hit"]) for s in checked["spots"]] == [("hidden_layer", "high", "71")]
        assert checked["rule_history"][0]["rule_version"] == OLD_RULE and checked["rule_history"][0]["spots_total"] == 0
        changed = next(r for r in checked["gate"]["reasons"] if r["code"] == "rules_changed")
        assert not changed["blocking"] and "의심점 0곳 → 지금 1곳" in changed["message"]
        assert checked["gate"]["state"] == "needs_review" and checked["gate"]["wrong_reviews"] == 1
        # 이전 검수자의 판정과 근거는 그대로
        kept = client.get("/api/live/reviews", params={"doc": doc_id}).json()["reviews"]
        assert [(r["id"], r["status"], r["comment"], r["source_text"], r["result_text"]) for r in kept] == [
            (review["id"], "wrong", "화면은 17 bar", "PRESSURE 17 bar", "PRESSURE 71 bar")]
        # 청크에는 새 규칙의 의심점과 이전 판정이 함께
        body = client.post("/api/retrieval/chunk", json={"source": {"doc_id": doc_id}, "strategies": [{"kind": "fixed", "params": {"size": 64}}]}).json()
        chunk = next(c for c in body["results"][0]["chunks"] if "71 bar" in c["text"])
        assert {"confirmed-wrong", "unverified"} <= set(chunk["flags"])
        assert [item["key"] for item in chunk["qc"]] == [f"V{review['id']}", "S1"]
        summary = client.get("/api/live/qc-summary").json()
        assert summary["qc_done"] == 1 and summary["qc_stale"] == 0 and summary["reverify"]["state"] == "done"
    with sqlite3.connect(runtime / "documents.sqlite3") as conn:  # 이전 규칙의 원장은 지우지 않는다
        assert sorted(row[0] for row in conn.execute("SELECT rule_version FROM qc_runs")) == sorted([OLD_RULE, qc.rule_key()])


def test_without_background_reverify_the_stale_run_is_pending_then_recomputed_on_access(tmp_path, monkeypatch):
    runtime, doc_id, _, _ = _old_runtime(tmp_path, monkeypatch)
    with TestClient(create_app(Settings(runtime_dir=runtime, qc_reverify=False))) as client:
        summary = client.get("/api/live/qc-summary").json()
        assert summary["qc_pending"] == 1 and summary["qc_stale"] == 1 and summary["qc_done"] == 0  # 이전 규칙 원장을 '완료'로 쓰지 않는다
        listed = client.get("/api/live/documents", params={"limit": 10}).json()["documents"][0]
        assert listed["qc"]["state"] == "pending" and "규칙 변경" in listed["qc"]["label"]
        checked = client.get(f"/api/live/documents/{doc_id}/verify").json()
        assert checked["spots_total"] == 1 and checked["spots"][0]["kind"] == "hidden_layer"


def test_rule_key_follows_code_and_library_versions(monkeypatch):
    import importlib.metadata
    first = qc.rule_key()
    assert first.startswith(qc.RULE_VERSION + "+") and len(first.split("+")[1]) == 10
    real = importlib.metadata.version
    monkeypatch.setattr(qc, "_rule_key", None)
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "99.0" if name == "pypdfium2" else real(name))
    assert qc.rule_key() != first  # 원본 읽기 라이브러리가 바뀌면 다시 대조한다
    monkeypatch.setattr(qc, "_rule_key", None)
