"""Start the local console for run.sh, or open its existing instance."""

import errno
from http.client import HTTPConnection, HTTPException
import socket
import subprocess
import sys
import threading
import time
import webbrowser

import uvicorn

from app.config import Settings


HOST = "127.0.0.1"
RUNTIME_HEADER = "x-docops-runtime"
PORT_COUNT = 20


def legacy_port(lock_path):
    """Find older servers by the listener and lock file held by the same process."""
    def lsof(*args):
        return subprocess.run(
            ["lsof", *args], capture_output=True, text=True, timeout=2
        ).stdout.splitlines()

    try:
        owners = lsof("-t", "--", str(lock_path))
        if not owners:
            return None
        listeners = lsof("-nP", "-a", "-p", ",".join(owners), "-i4TCP", "-sTCP:LISTEN", "-Fn")
    except (OSError, subprocess.TimeoutExpired):
        return None
    for record in listeners:
        address, _, port = record.partition(":")
        if address in {f"n{HOST}", "n*"} and port.isdecimal():
            return int(port)
    return None


def running_port(runtime_dir, ports, runtime_id):
    lock_path = runtime_dir / "server.lock"
    if not lock_path.is_file():
        return None
    port = legacy_port(lock_path)
    if port is not None:
        return port
    for port in ports:
        conn = HTTPConnection(HOST, port, timeout=0.25)
        try:
            conn.request("GET", "/api/health")
            with conn.getresponse() as response:
                if response.status == 200 and response.getheader(RUNTIME_HEADER) == runtime_id:
                    return port
        except (OSError, HTTPException):
            continue
        finally:
            conn.close()
    return None


def reserve_listener(ports):
    for port in ports:
        listener = socket.socket()
        try:
            # Exclusive binds on Windows. On POSIX, allow immediate restarts after shutdown.
            if sys.platform == "win32":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((HOST, port))
            listener.listen()
        except OSError as exc:
            listener.close()
            if exc.errno == errno.EADDRINUSE or getattr(exc, "winerror", None) in {10013, 10048}:
                continue
            raise
        return listener, port
    raise OSError(f"{ports.start}~{ports[-1]}번 포트가 사용 중입니다. ./run.sh <다른 포트>로 실행하세요.")


def open_when_ready(server, url):
    for _ in range(100):
        if server.started:
            webbrowser.open(url)
            return
        time.sleep(0.25)


def launch(requested_port, browser):
    settings = Settings.from_env()
    runtime_dir, runtime_id = settings.runtime_dir, settings.runtime_id
    ports = range(requested_port, min(requested_port + PORT_COUNT, 65536))
    port = running_port(runtime_dir, ports, runtime_id)
    if port is not None:
        url = f"http://{HOST}:{port}/"
        print(f"[ok] 이미 실행 중인 콘솔을 사용합니다. {url}", flush=True)
        if browser:
            webbrowser.open(url)
        return 0

    listener, port = reserve_listener(ports)
    with listener:
        url = f"http://{HOST}:{port}/"
        if port != requested_port:
            print(f"[setup] {requested_port}번 포트가 사용 중이어서 {port}번 포트로 실행합니다.")
        print(f"\nUnstructured Data Console - {url}\nStop: Ctrl+C\n", flush=True)
        # 저장소 표식(x-docops-runtime)은 앱이 모든 응답에 붙인다(app.middleware.RuntimeHeader).
        server = uvicorn.Server(uvicorn.Config("main:app", host=HOST, port=port))
        if browser:
            threading.Thread(target=open_when_ready, args=(server, url), daemon=True).start()
        # Give Uvicorn the same socket so another process cannot claim the selected port.
        server.run(sockets=[listener])
        return 0 if server.started else 1


if __name__ == "__main__":
    try:
        sys.exit(launch(int(sys.argv[1]), sys.argv[2] == "1"))
    except OSError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
