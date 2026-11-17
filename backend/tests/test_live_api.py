from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading
import time

from app.adapters.base import ParsedDocument, ParserError
from app.service import PDF_OCR_WARNING
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.service import Conflict
from main import create_app

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(runtime_dir=tmp_path))) as instance:
        yield instance

def upload(client, name, content):
    return client.post('/api/live/documents', files={'file': (name, content, 'application/octet-stream')})

def wait_status(client, doc_id, expected, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        doc = client.get(f'/api/live/documents/{doc_id}').json()
        if doc['status'] == expected:
            return doc
        time.sleep(0.01)
    raise AssertionError(f"Expected {expected}, last document: {doc}")

def test_text_upload_requires_explicit_processing_and_returns_real_result(client):
    assert client.get('/api/health').json() == {'status': 'ok', 'mode': 'local', 'mock_data': 'available', 'live_processing': 'available'}
    assert client.get('/api/live/documents').json() == {'documents': []}
    uploaded = upload(client, '기록.txt', '안녕하세요\n두 번째 줄'.encode())
    assert uploaded.status_code == 201
    document = uploaded.json()
    assert document['status'] == 'uploaded' and document['format'] == 'TXT'
    assert 'source_file' not in document and 'result_file' not in document
    doc_id = document['id']
    assert client.get(f'/api/live/documents/{doc_id}/result').status_code == 409
    started = client.post(f'/api/live/documents/{doc_id}/process')
    assert started.status_code == 202 and started.json()['status'] == 'processing'
    wait_status(client, doc_id, 'completed')
    result = client.get(f'/api/live/documents/{doc_id}/result').json()
    assert result['markdown'] == '안녕하세요\n두 번째 줄'
    assert result['parser'] == 'python-text' and result['parser_version'].startswith('stdlib-')
    assert result['is_stale'] is False and result['warnings'] == []
    assert [event['status'] for event in client.get(f'/api/live/documents/{doc_id}/history').json()['history']] == ['uploaded', 'processing', 'completed']

def test_csv_cp949_and_unsupported_format_are_not_faked(client):
    document = upload(client, '데이터.csv', '항목,결과\n농도,정상'.encode('cp949')).json()
    client.post(f"/api/live/documents/{document['id']}/process")
    wait_status(client, document['id'], 'completed')
    result = client.get(f"/api/live/documents/{document['id']}/result").json()
    assert '| 항목 | 결과 |' in result['markdown'] and '| 농도 | 정상 |' in result['markdown']
    assert result['parser'] == 'python-csv'
    other = upload(client, 'unknown.heic', b'example').json()
    client.post(f"/api/live/documents/{other['id']}/process")
    wait_status(client, other['id'], 'unsupported')
    final = client.get(f"/api/live/documents/{other['id']}").json()
    assert final['status'] == 'unsupported' and final['error']
    assert client.get(f"/api/live/documents/{other['id']}/result").status_code == 409

def test_upload_path_is_generated_and_size_limit_cleans_up(tmp_path):
    settings = Settings(runtime_dir=tmp_path, max_upload_bytes=32)
    with TestClient(create_app(settings)) as client:
        too_big = upload(client, 'big.txt', b'x' * 33)
        assert too_big.status_code == 413
        assert list(settings.uploads.iterdir()) == []
        response = upload(client, '../../somewhere.txt', b'safe')
        assert response.status_code == 201
        assert response.json()['name'] == 'somewhere.txt'
        assert [p.name for p in settings.uploads.iterdir()] == [response.json()['id'] + '.txt']
        assert not (tmp_path.parent / 'somewhere.txt').exists()

def test_non_loopback_origin_is_rejected(client):
    response = client.post('/api/live/documents', headers={'Origin':'https://untrusted.example'}, files={'file':('demo.txt',b'no')})
    assert response.status_code == 403
    assert client.get('/api/live/documents').json() == {'documents': []}

def test_repeated_processing_is_atomic(client):
    doc_id = upload(client, 'one.txt', b'example').json()['id']
    service = client.app.state.documents
    def attempt(_):
        try:
            return service.begin(doc_id)[1]
        except Conflict:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert len([result for result in results if result]) == 1
    assert client.post(f'/api/live/documents/{doc_id}/process').status_code == 409

def test_restart_recovers_interrupted_processing(tmp_path):
    settings = Settings(runtime_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        doc_id = upload(client, 'one.txt', b'example').json()['id']
        client.app.state.documents.begin(doc_id)
    with TestClient(create_app(settings)) as client:
        doc = client.get(f'/api/live/documents/{doc_id}').json()
        assert doc['status'] == 'failed' and '중단' in doc['error']
        assert client.get(f'/api/live/documents/{doc_id}/history').json()['history'][-1]['status'] == 'failed'
        client.post(f'/api/live/documents/{doc_id}/process')
        wait_status(client, doc_id, 'completed')

def test_bad_text_and_missing_documents_are_clear(client):
    doc_id = upload(client, 'binary.txt', b'a\x00b').json()['id']
    client.post(f'/api/live/documents/{doc_id}/process')
    wait_status(client, doc_id, 'failed')
    doc = client.get(f'/api/live/documents/{doc_id}').json()
    assert doc['status'] == 'failed' and '텍스트' in doc['error']
    assert client.get(f'/api/live/documents/{doc_id}/result').status_code == 409
    assert client.get('/api/live/documents/not-an-id').status_code == 404


def test_previous_success_is_available_during_and_after_failed_retry(client, monkeypatch):
    doc_id = upload(client, 'retry.txt', b'last good result').json()['id']
    client.post(f'/api/live/documents/{doc_id}/process')
    wait_status(client, doc_id, 'completed')
    original = client.get(f'/api/live/documents/{doc_id}/result').json()
    service = client.app.state.documents
    doc, run = service.begin(doc_id)
    assert doc['status'] == 'processing'
    during = client.get(f'/api/live/documents/{doc_id}/result').json()
    assert during['is_stale'] is True
    assert during['markdown'] == original['markdown']
    assert during['parser'] == original['parser']
    assert during['parser_version'] == original['parser_version']
    def fail(*args):
        raise ParserError('실패 예시')
    monkeypatch.setattr(service.parsers, 'parse', fail)
    service.process(doc_id, run)
    assert client.get(f'/api/live/documents/{doc_id}').json()['status'] == 'failed'
    after = client.get(f'/api/live/documents/{doc_id}/result').json()
    assert after['is_stale'] is True
    assert after['markdown'] == original['markdown']
    assert after['parser_version'] == original['parser_version']
    monkeypatch.setattr(service.parsers, 'parse', lambda *_: ParsedDocument(markdown='new result', parser='test-parser', parser_version='new-version'))
    assert client.post(f'/api/live/documents/{doc_id}/process').status_code == 202
    wait_status(client, doc_id, 'completed')
    replaced = client.get(f'/api/live/documents/{doc_id}/result').json()
    assert replaced['markdown'] == 'new result' and replaced['parser_version'] == 'new-version'
    assert replaced['parser'] == 'test-parser' and replaced['is_stale'] is False
    runs = client.get(f'/api/live/documents/{doc_id}/runs').json()['runs']
    assert [run['is_latest'] for run in runs] == [True, False]
    assert all(isinstance(run['duration_ms'], int) and run['duration_ms'] >= 0 for run in runs)
    stored = [client.get(f"/api/live/documents/{doc_id}/runs/{run['run_id']}").json() for run in runs]
    assert [run['markdown'] for run in stored] == ['new result', original['markdown']]
    assert [run['parser_version'] for run in stored] == ['new-version', original['parser_version']]
    assert client.get(f'/api/live/documents/{doc_id}/source-preview').json() == {
        'kind': 'text', 'text': 'last good result', 'truncated': False,
    }
    source = client.get(f'/api/live/documents/{doc_id}/source')
    assert source.content == b'last good result' and 'attachment' in source.headers['content-disposition']
    other = upload(client, 'other.txt', b'other').json()['id']
    assert client.get(f"/api/live/documents/{other}/runs/{runs[0]['run_id']}").status_code == 404


def test_pdf_warning_contract_without_real_pdf(client, monkeypatch):
    doc_id = upload(client, 'example.pdf', b'fake-only-for-adapter-test').json()['id']
    service = client.app.state.documents
    monkeypatch.setattr(service.parsers, 'parse', lambda *_: ParsedDocument(markdown='example', parser='docling', parser_version='test'))
    assert client.post(f'/api/live/documents/{doc_id}/process').status_code == 202
    wait_status(client, doc_id, 'completed')
    result = client.get(f'/api/live/documents/{doc_id}/result').json()
    assert result['is_stale'] is False and result['warnings'] == [PDF_OCR_WARNING]


def test_existing_database_migrates_without_losing_result(tmp_path):
    settings = Settings(runtime_dir=tmp_path)
    settings.uploads.mkdir()
    settings.results.mkdir()
    doc_id = 'a' * 32
    result_name = doc_id + '-' + 'b' * 32 + '.md'
    (settings.results / result_name).write_text('previous result', encoding='utf-8')
    with sqlite3.connect(settings.database) as conn:
        conn.executescript("""CREATE TABLE documents (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL,
            size_bytes INTEGER NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            parser TEXT, parser_version TEXT, error TEXT,
            source_file TEXT NOT NULL, result_file TEXT, run_id TEXT
        );""")
        conn.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (doc_id, 'old.pdf', 'PDF', 1, 'completed', '2026-01-01', '2026-01-01', 'docling', '2.150.0', None, doc_id+'.pdf', result_name, None))
    with TestClient(create_app(settings)) as client:
        result = client.get(f'/api/live/documents/{doc_id}/result').json()
        assert result['markdown'] == 'previous result'
        assert result['parser'] == 'docling' and result['parser_version'] == '2.150.0'
        assert result['warnings'] == [PDF_OCR_WARNING] and result['is_stale'] is False
        runs = client.get(f'/api/live/documents/{doc_id}/runs').json()['runs']
        assert [run['run_id'] for run in runs] == ['b' * 32]
        legacy = client.get(f"/api/live/documents/{doc_id}/runs/{runs[0]['run_id']}").json()
        assert legacy['markdown'] == 'previous result' and legacy['ocr_enabled'] is None and legacy['locations'] == []
        client.app.state.documents.begin(doc_id)
    with TestClient(create_app(settings)) as client:
        result = client.get(f'/api/live/documents/{doc_id}/result').json()
        assert result['is_stale'] is True and result['markdown'] == 'previous result'
        assert client.get(f'/api/live/documents/{doc_id}').json()['status'] == 'failed'


def test_forty_pending_jobs_do_not_block_document_list(client, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    def blocked_parser(path, extension):
        started.set()
        assert release.wait(10)
        return ParsedDocument(markdown='ok', parser='python-text', parser_version='test')
    monkeypatch.setattr(client.app.state.documents.parsers, 'parse', blocked_parser)
    ids = [upload(client, f'{i}.txt', b'test').json()['id'] for i in range(66)]
    try:
        assert client.post(f'/api/live/documents/{ids[0]}/process').status_code == 202
        assert started.wait(3)
        for doc_id in ids[1:65]:
            assert client.post(f'/api/live/documents/{doc_id}/process').status_code == 202
        rejected = client.post(f'/api/live/documents/{ids[65]}/process')
        assert rejected.status_code == 503
        begin = time.monotonic()
        response = client.get('/api/live/documents')
        assert response.status_code == 200 and len(response.json()['documents']) == 66
        assert time.monotonic() - begin < 3
        states = {doc['id']: doc['status'] for doc in response.json()['documents']}
        assert all(states[doc_id] == 'processing' for doc_id in ids[:65])
        assert states[ids[65]] == 'uploaded'
    finally:
        release.set()


def test_full_queue_returns_503_and_preserves_document_status(tmp_path, monkeypatch):
    settings = Settings(runtime_dir=tmp_path, max_pending_jobs=2)
    with TestClient(create_app(settings)) as client:
        started = threading.Event()
        release = threading.Event()
        def blocked_parser(path, extension):
            started.set()
            assert release.wait(10)
            return ParsedDocument(markdown='ok', parser='python-text', parser_version='test')
        monkeypatch.setattr(client.app.state.documents.parsers, 'parse', blocked_parser)
        ids = [upload(client, f'{i}.txt', b'test').json()['id'] for i in range(4)]
        try:
            assert client.post(f'/api/live/documents/{ids[0]}/process').status_code == 202
            assert started.wait(3)
            assert client.post(f'/api/live/documents/{ids[1]}/process').status_code == 202
            assert client.post(f'/api/live/documents/{ids[2]}/process').status_code == 202
            rejected = client.post(f'/api/live/documents/{ids[3]}/process')
            assert rejected.status_code == 503 and '대기열' in rejected.json()['detail']
            assert client.get(f'/api/live/documents/{ids[3]}').json()['status'] == 'uploaded'
            history = client.get(f'/api/live/documents/{ids[3]}/history').json()['history']
            assert '대기열' in history[-1]['message']
        finally:
            release.set()


def test_shutdown_marks_queued_retries_failed_and_keeps_previous_result(client, monkeypatch):
    previous_id = upload(client, 'previous.txt', b'earlier result').json()['id']
    client.post(f'/api/live/documents/{previous_id}/process')
    wait_status(client, previous_id, 'completed')
    blocker_id = upload(client, 'blocking.txt', b'blocking').json()['id']
    started = threading.Event()
    release = threading.Event()
    def blocked_parser(path, extension):
        started.set()
        assert release.wait(5)
        return ParsedDocument(markdown='blocker finished', parser='python-text', parser_version='test')
    service = client.app.state.documents
    monkeypatch.setattr(service.parsers, 'parse', blocked_parser)
    assert client.post(f'/api/live/documents/{blocker_id}/process').status_code == 202
    assert started.wait(3)
    assert client.post(f'/api/live/documents/{previous_id}/process').status_code == 202
    stopper = threading.Thread(target=service.stop)
    stopper.start()
    try:
        wait_status(client, previous_id, 'failed')
        result = client.get(f'/api/live/documents/{previous_id}/result').json()
        assert result['markdown'] == 'earlier result' and result['is_stale'] is True
    finally:
        release.set()
        stopper.join(timeout=5)
    assert not stopper.is_alive()
