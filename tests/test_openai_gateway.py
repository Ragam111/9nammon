"""OpenAI-compatible /v1 ของ LCA — ไม่ใช้ Ollama จริง"""
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server
from app import openai_gateway as gw


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


INSTALLED = {"qwen2.5-coder:0.5b", "qwen2.5:1.5b"}


class BuildRequestTest(unittest.TestCase):
    def _ok(self, **kw):
        body = {"model": "qwen2.5-coder:0.5b", "messages": [{"role": "user", "content": "hi"}]}
        body.update(kw)
        return gw.build_request(body, INSTALLED)

    def test_keeps_allowed_fields_and_caps_tokens(self):
        out = self._ok(max_tokens=99999, temperature=0.2, tools=[{"x": 1}], api_base="http://evil")
        self.assertEqual(out["max_tokens"], gw.MAX_TOKENS_CAP)
        self.assertEqual(out["temperature"], 0.2)
        self.assertNotIn("tools", out)
        self.assertNotIn("api_base", out)
        self.assertFalse(out["stream"])

    def test_unknown_model_is_404(self):
        with self.assertRaises(gw.GatewayError) as cm:
            gw.build_request({"model": "gpt-4", "messages": [{"role": "user", "content": "x"}]}, INSTALLED)
        self.assertEqual(cm.exception.status, 404)

    def test_bad_messages_are_400(self):
        for msgs in ([], "hi", [{"role": "tool", "content": "x"}], [{"role": "user", "content": 5}]):
            with self.assertRaises(gw.GatewayError) as cm:
                gw.build_request({"model": "qwen2.5:1.5b", "messages": msgs}, INSTALLED)
            self.assertEqual(cm.exception.status, 400)

    def test_list_models_from_tags_and_empty_when_down(self):
        def tags(url, timeout=None):
            return _Resp(json.dumps({"models": [{"name": "qwen2.5:1.5b", "size": 1}]}).encode())
        self.assertEqual([m["id"] for m in gw.list_models(opener=tags)["data"]], ["qwen2.5:1.5b"])

        def down(url, timeout=None):
            raise OSError("refused")
        self.assertEqual(gw.list_models(opener=down)["data"], [])

    def test_stream_forwards_only_data_lines(self):
        def opener(req, timeout=None):
            return _Resp(b'data: {"a":1}\n\n: keepalive\ndata: [DONE]\n')
        out = list(gw.stream({"model": "m", "messages": []}, opener=opener))
        self.assertEqual(out, [b'data: {"a":1}\n\n', b"data: [DONE]\n\n"])

    def test_ollama_down_is_503(self):
        def down(req, timeout=None):
            raise OSError("refused")
        with self.assertRaises(gw.GatewayError) as cm:
            gw.complete({"model": "m", "messages": []}, opener=down)
        self.assertEqual(cm.exception.status, 503)


class V1HttpTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        handler = server.make_handler(Path(self._tmp.name), None)
        self.token = handler.session_token
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        models = {"object": "list", "data": [{"id": n, "object": "model", "created": 0, "owned_by": "local"}
                                             for n in sorted(INSTALLED)]}
        self._p = mock.patch.object(gw, "list_models", return_value=models)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def _req(self, method, path, body=None, auth="bearer"):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if auth == "bearer":
            h["Authorization"] = f"Bearer {self.token}"
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read().decode("utf-8")
        c.close()
        return r.status, data

    def test_models_requires_auth(self):
        status, data = self._req("GET", "/v1/models", auth=None)
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(data)["error"]["code"], "invalid_api_key")

    def test_models_with_bearer(self):
        status, data = self._req("GET", "/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual([m["id"] for m in json.loads(data)["data"]], sorted(INSTALLED))

    def test_chat_non_stream(self):
        reply = {"id": "x", "object": "chat.completion", "choices": [{"message": {"role": "assistant", "content": "สวัสดี"}}]}
        with mock.patch.object(gw, "complete", return_value=reply) as c:
            status, data = self._req("POST", "/v1/chat/completions",
                                     {"model": "qwen2.5:1.5b", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["choices"][0]["message"]["content"], "สวัสดี")
        self.assertEqual(c.call_args[0][0]["model"], "qwen2.5:1.5b")

    def test_chat_stream(self):
        chunks = iter([b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n', b"data: [DONE]\n\n"])
        with mock.patch.object(gw, "stream", return_value=chunks):
            status, data = self._req("POST", "/v1/chat/completions",
                                     {"model": "qwen2.5:1.5b", "stream": True,
                                      "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 200)
        self.assertIn("data: [DONE]", data)

    def test_chat_unknown_model_404(self):
        status, data = self._req("POST", "/v1/chat/completions",
                                 {"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(data)["error"]["code"], "model_not_found")

    def test_chat_ollama_down_503(self):
        err = gw.GatewayError(503, "ติดต่อ Ollama ไม่ได้", "upstream_unavailable")
        with mock.patch.object(gw, "complete", side_effect=err):
            status, _ = self._req("POST", "/v1/chat/completions",
                                  {"model": "qwen2.5:1.5b", "messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(status, 503)


if __name__ == "__main__":
    unittest.main()
