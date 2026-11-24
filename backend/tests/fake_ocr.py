"""OpenAI 호환 비전 API 흉내(테스트용 OCR 모델). 받은 그림과 지시문을 기록하고 정해 둔 글을 돌려준다."""
import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeOcr:
    def __init__(self, reply):
        """reply(prompt, png_bytes) -> str"""
        self.reply = reply
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                content = body["messages"][0]["content"]
                prompt = next(part["text"] for part in content if part["type"] == "text")
                url = next(part["image_url"]["url"] for part in content if part["type"] == "image_url")
                png = base64.b64decode(url.split(",", 1)[1])
                fake.requests.append({"model": body["model"], "prompt": prompt, "auth": self.headers.get("Authorization")})
                payload = json.dumps({"choices": [{"message": {"content": fake.reply(prompt, png)}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def env(self, monkeypatch, mode="page"):
        monkeypatch.setenv("OCR_BASE_URL", self.url)
        monkeypatch.setenv("OCR_MODEL", "fake-ocr")
        monkeypatch.setenv("OCR_MODE", mode)

    def close(self):
        self.server.shutdown()


def brightness(png: bytes) -> int:
    from PIL import Image
    return Image.open(io.BytesIO(png)).convert("L").getpixel((0, 0))
