"""สัญญา SSE + ไม่มี "Empty reply" อีกต่อไป

- /api/chat/stream และ /api/vscode/chat: ทุก chunk = `data: {"delta"}`, จบด้วย `{"done": true}`
  หรือ `{"error": ...}` เสมอ แม้ backend โยน exception ที่ไม่คาดคิด
- handler ที่พังก่อนส่ง header → 500 JSON (เดิม socket ถูกปิดเงียบ = curl error 52)
- หลัง header SSE ออกไปแล้ว ห้ามมี HTTP response ซ้อน (ขยะใน stream)
"""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from app import model_backend, session_store  # noqa: E402

MASTER = "master-secret-token"


def _parse_sse(raw: str):
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            events.append(json.loads(block[len("data:"):].strip()))
    return events


class SseContractTest(unittest.TestCase):
    def setUp(self):
        session_store.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._orig_stream = model_backend.generate_stream
        self._orig_gen = model_backend.generate
        handler = server.make_handler(self.root, MASTER)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.hdr = {"X-Auth-Token": MASTER, "Content-Type": "application/json"}

    def tearDown(self):
        model_backend.generate_stream = self._orig_stream
        model_backend.generate = self._orig_gen
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _post(self, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", path, body=json.dumps(body), headers=self.hdr)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        ctype = resp.getheader("Content-Type") or ""
        conn.close()
        return resp.status, ctype, raw

    def test_stream_happy_path_ends_with_done(self):
        def gen(project_root, model, messages, num_ctx=8192, options=None):
            yield "สวัส"
            yield "ดี"
        model_backend.generate_stream = gen
        for path in ("/api/chat/stream", "/api/vscode/chat"):
            st, ctype, raw = self._post(path, {"messages": [{"role": "user", "content": "hi"}], "model": "m"})
            self.assertEqual(st, 200, path)
            self.assertIn("text/event-stream", ctype)
            self.assertIn("charset=utf-8", ctype)
            events = _parse_sse(raw)
            self.assertEqual([e for e in events if "delta" in e], [{"delta": "สวัส"}, {"delta": "ดี"}])
            self.assertEqual(events[-1], {"done": True})

    def test_stream_backend_error_mid_stream_ends_with_error_event(self):
        def gen(project_root, model, messages, num_ctx=8192, options=None):
            yield "part"
            raise model_backend.BackendError("Ollama หลุด")
        model_backend.generate_stream = gen
        st, _, raw = self._post("/api/chat/stream", {"messages": [{"role": "user", "content": "hi"}], "model": "m"})
        self.assertEqual(st, 200)
        events = _parse_sse(raw)
        self.assertEqual(events[0], {"delta": "part"})
        self.assertIn("error", events[-1])
        self.assertIn("Ollama", events[-1]["error"])
        self.assertNotIn("HTTP/1.0", raw)   # ไม่มี response ซ้อนในสตรีม

    def test_stream_unexpected_exception_still_closes_stream(self):
        def gen(project_root, model, messages, num_ctx=8192, options=None):
            yield "x"
            raise RuntimeError("boom")
        model_backend.generate_stream = gen
        st, _, raw = self._post("/api/chat/stream", {"messages": [{"role": "user", "content": "hi"}], "model": "m"})
        self.assertEqual(st, 200)
        events = _parse_sse(raw)
        self.assertEqual(events[-1]["error"], "boom")
        self.assertEqual(events[-1]["status"], "error")

    def test_stream_via_chat_hub_provider_error_after_headers(self):
        # provider path (chat_hub) พังกลางสตรีม — ต้องปิดด้วย error event ไม่ใช่ JSON ซ้อน
        def stream(messages, model, *, provider, project_root=None, **_):
            yield "a"
            raise RuntimeError("provider died")

        with mock.patch("app.providers.stream", stream):
            st, ctype, raw = self._post("/api/chat/stream", {
                "messages": [{"role": "user", "content": "hi"}], "model": "m", "provider": "openai",
            })
        self.assertEqual(st, 200)
        self.assertIn("text/event-stream", ctype)
        events = _parse_sse(raw)
        self.assertEqual(events[0], {"delta": "a"})
        self.assertIn("error", events[-1])
        self.assertNotIn("HTTP/1.0", raw)

    def test_unexpected_exception_before_headers_gives_500_json_not_empty_reply(self):
        def boom(project_root, model, messages, num_ctx=8192, options=None):
            raise TypeError("unexpected")
        model_backend.generate = boom
        st, ctype, raw = self._post("/api/chat", {"messages": [{"role": "user", "content": "hi"}], "model": "m"})
        self.assertEqual(st, 500)
        self.assertIn("json", ctype)
        d = json.loads(raw)
        self.assertEqual(d["type"], "TypeError")
        # ลง error log ให้ /dev เห็น
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/admin/history/errors", headers=self.hdr)
        resp = conn.getresponse()
        errors = json.loads(resp.read().decode("utf-8"))["errors"]
        conn.close()
        self.assertTrue(any("TypeError" in e["message"] for e in errors))

    def test_busy_before_headers_is_503_json(self):
        from app import admission

        def gen(project_root, model, messages, num_ctx=8192, options=None):
            yield "never"
        model_backend.generate_stream = gen
        with mock.patch.object(admission.AdmissionGate, "slot", side_effect=admission.Busy("เครื่องเต็ม")):
            st, ctype, raw = self._post("/api/chat/stream", {"messages": [{"role": "user", "content": "hi"}], "model": "m"})
        self.assertEqual(st, 503)
        self.assertIn("json", ctype)


if __name__ == "__main__":
    unittest.main()
