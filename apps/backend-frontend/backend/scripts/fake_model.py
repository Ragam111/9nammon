"""Fake OpenAI-compatible model for local development and E2E tests. Stdlib only, never use in production.

Usage: python scripts/fake_model.py [port]   (default 9100)

Put a keyword in the prompt to trigger an edge case:
  badkey     -> 401 (model key rejected)
  busy       -> 503 every time
  slowstart  -> waits 3 seconds before the first byte
  drop       -> sends two chunks, then closes the connection without finishing
otherwise it streams a short answer that echoes the prompt.
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHUNK_DELAY_S = 0.05


def _chunk(text: str) -> bytes:
    return f"data: {json.dumps({'choices': [{'delta': {'content': text}}]}, ensure_ascii=False)}\n\n".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # body ends when the connection closes, like a simple stream

    def log_message(self, fmt: str, *args: object) -> None:  # keep the console quiet
        return

    def _json(self, status: int, body: dict[str, object]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        if not self.path.endswith("/chat/completions"):
            self._json(404, {"error": {"message": "not found"}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        prompt = str((payload.get("messages") or [{}])[-1].get("content", ""))
        if "badkey" in prompt:
            self._json(401, {"error": {"message": "invalid api key"}})
            return
        if "busy" in prompt:
            self._json(503, {"error": {"message": "overloaded"}})
            return
        if "slowstart" in prompt:
            time.sleep(3)
        self._stream(prompt)

    def _stream(self, prompt: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        words = f"นี่คือคำตอบจำลองสำหรับ: {prompt[:80]} — ใช้ทดสอบ streaming ในเครื่อง".split(" ")
        for i, word in enumerate(words):
            if "drop" in prompt and i == 2:
                return  # close without [DONE]: the API should keep the partial text and report an error
            self.wfile.write(_chunk(word + " "))
            self.wfile.flush()
            time.sleep(CHUNK_DELAY_S)
        usage = {"prompt_tokens": max(1, len(prompt) // 4), "completion_tokens": len(words)}
        self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': usage})}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9100
    print(f"fake model on http://127.0.0.1:{port}/v1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
