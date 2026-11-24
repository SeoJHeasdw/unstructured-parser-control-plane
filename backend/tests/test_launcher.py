"""Real-process check for port fallback and reopening an existing console."""
from http.client import HTTPConnection, HTTPException
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from app.config import runtime_id


def test_launch_on_occupied_port_and_reuse(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    runtime = tmp_path / "콘솔 데이터"
    env = os.environ | {"DOCOPS_RUNTIME_DIR": str(runtime), "PYTHONUTF8": "1"}
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        start = occupied.getsockname()[1]
        args = [sys.executable, "launch_local.py", str(start), "0"]
        process = subprocess.Popen(args, cwd=backend, env=env)
        try:
            deadline = time.monotonic() + 20
            while True:
                assert process.poll() is None, "console exited before startup"
                for port in range(start + 1, min(start + 20, 65536)):
                    conn = HTTPConnection("127.0.0.1", port, timeout=0.2)
                    try:
                        conn.request("GET", "/api/health")
                        response = conn.getresponse()
                        if response.status == 200 and response.getheader("x-docops-runtime") == runtime_id(runtime):
                            break
                    except (HTTPException, OSError):
                        pass
                    finally:
                        conn.close()
                else:
                    assert time.monotonic() < deadline, "console never became ready"
                    time.sleep(0.1)
                    continue
                break
            reopened = subprocess.run(args, env=env, cwd=backend, timeout=10, capture_output=True, encoding="utf-8")
            assert reopened.returncode == 0 and f"127.0.0.1:{port}/" in reopened.stdout
            assert process.poll() is None
        finally:
            process.terminate()
            process.wait(timeout=10)
