"""API tests for provider routing, branch, regenerate, and compare.

Providers are mocked. No network and no real API keys.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from app import model_backend  # noqa: E402
from app.providers.base import ChatResponse, TextStream, Usage  # noqa: E402
from app.providers.errors import ProviderNetworkError  # noqa: E402


def _response(text, provider, model):
    return ChatResponse(text, model, provider, Usage(3, 4, 7, False, "provider"), None)


def _as_dicts(messages):
    out = []
    for message in messages:
        if isinstance(message, dict):
            out.append({"role": message.get("role"), "content": message.get("content")})
        else:
            out.append({"role": message.role, "content": message.content})
    return out


class ChatApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calls = []
        self.inflight = {"n": 0, "max": 0}
        self.lock = threading.Lock()
        self.delay = 0

        def chat(messages, model, *, provider, project_root=None, **_opts):
            with self.lock:
                self.inflight["n"] += 1
                self.inflight["max"] = max(self.inflight["max"], self.inflight["n"])
                self.calls.append({
                    "provider": provider,
                    "model": model,
                    "messages": _as_dicts(messages),
                })
            if self.delay:
                time.sleep(self.delay)
            with self.lock:
                self.inflight["n"] -= 1
            return _response(f"{provider}:{model}", provider, model)

        self.patch = mock.patch("app.providers.chat", chat)
        self.patch.start()
        handler = server.make_handler(self.root, None)
        # No master token: the server mints a per-launch session token (#107).
        self.auth = {"X-Auth-Token": handler.session_token}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.patch.stop()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def _post(self, path, payload, timeout=10):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        body = json.dumps(payload).encode("utf-8")
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json", **self.auth})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        return resp.status, json.loads(raw) if raw else {}

    def _get(self, path):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers=self.auth)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        return resp.status, json.loads(raw) if raw else {}

    def test_chat_page_carries_session_token_and_api_requires_it(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/chat")
        resp = conn.getresponse()
        html = resp.read().decode("utf-8")
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn("__LCA_SESSION_TOKEN", html)
        self.assertLess(html.index('src="/app.js"'), html.index('src="/chat.js"'))
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/chat/conversations")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 401)

    def test_provider_is_per_request_and_can_switch_mid_conversation(self):
        st, created = self._post("/api/chat/conversations", {"title": "สลับค่าย"})
        self.assertEqual(st, 200)
        cid = created["conversation"]["id"]
        st, first = self._post("/api/chat", {
            "conversation_id": cid, "content": "สวัสดี", "provider": "ollama", "model": "qwen",
        })
        self.assertEqual(st, 200)
        self.assertEqual(first["reply"], "ollama:qwen")
        self.assertEqual(first["provider"], "ollama")
        st, second = self._post("/api/chat", {
            "conversation_id": cid, "content": "ต่อด้วย", "provider": "anthropic", "model": "claude-haiku-4-5",
        })
        self.assertEqual(st, 200)
        self.assertEqual(second["provider"], "anthropic")
        sent = self.calls[-1]["messages"]
        contents = [m["content"] for m in sent]
        self.assertIn("สวัสดี", contents)
        self.assertIn("ollama:qwen", contents)
        self.assertIn("ต่อด้วย", contents)
        self.assertEqual(self.calls[-1]["provider"], "anthropic")

    def test_stateless_provider_call_does_not_require_a_conversation(self):
        st, data = self._post("/api/chat", {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        })
        self.assertEqual(st, 200)
        self.assertEqual(data["reply"], "openai:gpt-4o-mini")
        self.assertNotIn("conversation_id", data)

    def test_fallback_uses_model_backend_when_provider_is_omitted(self):
        original = model_backend.generate
        model_backend.generate = lambda project_root, model, messages, num_ctx=8192, options=None: "FROM-BACKEND"
        self.calls.clear()
        try:
            st, created = self._post("/api/chat/conversations", {})
            cid = created["conversation"]["id"]
            st, data = self._post("/api/chat", {"conversation_id": cid, "content": "ผ่านทางเดิม", "model": "qwen2.5-coder:1.5b"})
        finally:
            model_backend.generate = original
        self.assertEqual(st, 200)
        self.assertEqual(data["reply"], "FROM-BACKEND")
        self.assertEqual(self.calls, [])
        _st, loaded = self._get(f"/api/chat/conversations?id={cid}")
        roles = [m["role"] for m in loaded["messages"]]
        self.assertEqual(roles, ["user", "assistant"])
        self.assertEqual(loaded["messages"][-1]["content"], "FROM-BACKEND")

    def test_branch_regenerate_and_compare(self):
        _st, created = self._post("/api/chat/conversations", {"title": "ต้นไม้"})
        cid = created["conversation"]["id"]
        st, sent = self._post("/api/chat", {
            "conversation_id": cid, "content": "คำถาม", "provider": "ollama", "model": "qwen",
        })
        self.assertEqual(st, 200)
        user_id = sent["user_message_id"]
        assistant_id = sent["message_id"]

        st, branched = self._post("/api/chat/branch", {
            "conversation_id": cid, "message_id": user_id, "content": "สาขาใหม่",
            "provider": "gemini", "model": "gemini-2.5-flash",
        })
        self.assertEqual(st, 200)
        self.assertEqual(branched["provider"], "gemini")
        _st, loaded = self._get(f"/api/chat/conversations?id={cid}")
        origins = [m.get("origin") for m in loaded["messages"]]
        self.assertIn("branch", origins)
        branch_user = next(m for m in loaded["messages"] if m.get("origin") == "branch")
        self.assertEqual(branch_user["parent_id"], user_id)
        self.assertEqual(branch_user["content"], "สาขาใหม่")

        st, regen = self._post("/api/chat/regen", {
            "conversation_id": cid, "message_id": assistant_id,
            "provider": "xai", "model": "grok-4.3",
        })
        self.assertEqual(st, 200)
        self.assertEqual(regen["provider"], "xai")
        _st, loaded = self._get(f"/api/chat/conversations?id={cid}")
        regen_row = next(m for m in loaded["messages"] if m["id"] == regen["message_id"])
        self.assertEqual(regen_row["origin"], "regen")
        self.assertEqual(regen_row["source_id"], assistant_id)
        self.assertGreaterEqual(regen_row["n_ver"], 2)

        self.inflight = {"n": 0, "max": 0}
        self.delay = 0.15
        st, compared = self._post("/api/chat/compare", {
            "conversation_id": cid,
            "content": "เทียบคำนี้",
            "targets": [
                {"provider": "anthropic", "model": "claude-haiku-4-5"},
                {"provider": "openai", "model": "gpt-4o-mini"},
            ],
        }, timeout=10)
        self.assertEqual(st, 200, compared)
        self.assertEqual(len(compared["replies"]), 2)
        self.assertEqual({r["provider"] for r in compared["replies"]}, {"anthropic", "openai"})
        self.assertEqual(self.inflight["max"], 2)
        _st, loaded = self._get(f"/api/chat/conversations?id={cid}")
        ids = [r["message_id"] for r in compared["replies"]]
        rows = [m for m in loaded["messages"] if m["id"] in ids]
        self.assertTrue(rows)
        self.assertTrue(all(m["origin"] == "compare" for m in rows))
        self.assertEqual(len({m["compare_id"] for m in rows}), 1)
        self.assertIsNotNone(rows[0]["compare_id"])

    def test_local_compare_runs_one_at_a_time(self):
        self.delay = 0.15
        st, compared = self._post("/api/chat/compare", {
            "content": "local",
            "targets": [
                {"provider": "ollama", "model": "qwen-a"},
                {"provider": "ollama", "model": "qwen-b"},
            ],
        }, timeout=10)
        self.assertEqual(st, 200, compared)
        self.assertEqual(len(compared["replies"]), 2)
        self.assertEqual(self.inflight["max"], 1)

    def test_lan_endpoints_count_as_cloud_and_run_together(self):
        from app import config_manager
        config_manager.set_key(self.root, "OLLAMA_BASE_URL", "http://192.168.1.5:11434")
        config_manager.set_key(self.root, "OPENAI_BASE_URL", "http://192.168.1.5:8000/v1")
        self.delay = 0.3
        st, compared = self._post("/api/chat/compare", {
            "content": "lan",
            "targets": [
                {"provider": "ollama", "model": "qwen-a"},
                {"provider": "openai_compat", "model": "m"},
            ],
        }, timeout=10)
        self.assertEqual(st, 200, compared)
        self.assertEqual(len(compared["replies"]), 2)
        self.assertEqual(self.inflight["max"], 2)
        st, catalog = self._get("/api/chat/providers")
        self.assertEqual(st, 200)
        items = catalog.get("providers", catalog) if isinstance(catalog, dict) else catalog
        flags = {p["id"]: p["local"] for p in items}
        self.assertFalse(flags["ollama"])
        self.assertFalse(flags["openai_compat"])

    def test_stream_keeps_partial_text_when_provider_drops(self):
        def stream(messages, model, *, provider, project_root=None, **_opts):
            holder = {}

            def gen():
                yield "บางส่วน"
                raise ProviderNetworkError("หลุด")

            return TextStream(gen(), holder)

        with mock.patch("app.providers.stream", stream):
            _st, created = self._post("/api/chat/conversations", {})
            cid = created["conversation"]["id"]
            import http.client
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.request(
                "POST", "/api/chat/stream",
                body=json.dumps({
                    "conversation_id": cid, "content": "ถาม", "provider": "ollama", "model": "qwen",
                }).encode(),
                headers={"Content-Type": "application/json", **self.auth},
            )
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            conn.close()
        self.assertIn("บางส่วน", body)
        self.assertIn("error", body)
        self.assertNotIn('"done": true', body)
        _st, loaded = self._get(f"/api/chat/conversations?id={cid}")
        assistant = loaded["messages"][-1]
        self.assertEqual(assistant["status"], "error")
        self.assertIn("บางส่วน", assistant["content"])

    def test_unknown_provider_is_rejected(self):
        st, data = self._post("/api/chat", {
            "provider": "not-a-provider", "model": "x", "messages": [{"role": "user", "content": "hi"}],
        })
        self.assertEqual(st, 400)
        self.assertIn("unknown provider", data["error"])


class ChatApiExtraTest(ChatApiTest):
    def test_create_conversation_returns_id(self):
        st, data = self._post("/api/chat/conversations", {"title": "extra"})
        self.assertEqual(st, 200)
        self.assertIn("conversation", data)
        self.assertIn("id", data["conversation"])

    def test_list_conversations_endpoint_returns_data(self):
        self._post("/api/chat/conversations", {"title": "c1"})
        st, data = self._get("/api/chat/conversations")
        self.assertEqual(st, 200)
        convs = data.get("conversations", data) if isinstance(data, dict) else data
        self.assertIsInstance(convs, list)

    def test_stateless_chat_returns_reply(self):
        st, data = self._post("/api/chat", {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
        })
        self.assertEqual(st, 200)
        self.assertIn("reply", data)

    def test_chat_reply_includes_provider(self):
        st, data = self._post("/api/chat", {
            "provider": "anthropic",
            "model": "claude-haiku-4-5",
            "messages": [{"role": "user", "content": "test"}],
        })
        self.assertEqual(st, 200)
        self.assertIn("provider", data)

    def test_missing_auth_returns_401(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/chat", body=b"{}",
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 401)

    def test_conversation_messages_saved(self):
        _, created = self._post("/api/chat/conversations", {})
        cid = created["conversation"]["id"]
        self._post("/api/chat", {
            "conversation_id": cid,
            "content": "hello",
            "provider": "openai",
            "model": "gpt-4o-mini",
        })
        st, loaded = self._get(f"/api/chat/conversations?id={cid}")
        self.assertEqual(st, 200)
        self.assertGreater(len(loaded["messages"]), 0)


if __name__ == "__main__":
    unittest.main()
