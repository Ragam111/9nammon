"""Free-tier monthly token allowance (FREE_MONTHLY_TOKENS) on top of the daily quota.

Real counts come from the backend (prompt_eval_count + eval_count, or /v1 usage);
a conservative estimate is reserved before generation and settled after.
"""

import http.client
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
from app.agent import jobs as agent_jobs  # noqa: E402
from app import bots, feature_flags, model_backend, openai_gateway, org_store  # noqa: E402

MASTER = "master-secret-token"


class TokenAllowanceTest(unittest.TestCase):
    TOKENS_PER_REPLY = 400

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "config.json").write_text(json.dumps({"FREE_MONTHLY_TOKENS": "1000"}),
                                               encoding="utf-8")
        self.delay = 0.0

        def fake_generate(project_root, model, messages, num_ctx=8192, options=None):
            if self.delay:
                time.sleep(self.delay)
            model_backend.record_usage(self.TOKENS_PER_REPLY)   # what Ollama reports
            return "ok"

        p = mock.patch.object(model_backend, "generate", fake_generate)
        p.start()
        self.addCleanup(p.stop)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.root, MASTER))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        org_store.create_user(self.root, "boss", "password123", "CEO")
        org_store.create_user(self.root, "dev", "password123", "USER", created_by_role="CEO")
        st, d = self.req("POST", "/api/auth/login", {"username": "dev", "password": "password123"})
        self.assertEqual(st, 200, d)
        self.assertEqual(d["tier"], "free")
        self.auth = {"X-Auth-Token": d["token"]}

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._tmp.cleanup()

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        conn.request(method, path, body=json.dumps(body) if body is not None else None,
                     headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        conn.close()
        if resp.getheader("Content-Type", "").startswith("text/event-stream"):
            return resp.status, raw   # SSE body
        return resp.status, (json.loads(raw) if raw else {})

    def chat(self):
        return self.req("POST", "/api/chat", {"messages": [{"role": "user", "content": "hi"}]},
                        self.auth)

    def usage(self):
        return org_store.token_usage(self.root, "dev")

    def test_exceeding_allowance_is_429_then_next_month_resets(self):
        for _ in range(3):   # 0, 400, 800 < 1000 -> admitted
            st, d = self.chat()
            self.assertEqual(st, 200, d)
        self.assertEqual(self.usage(), {"month": org_store._month_str(), "used": 1200,
                                        "reserved": 0})
        st, d = self.chat()
        self.assertEqual(st, 429)
        self.assertIn("token", d["error"])
        self.assertEqual(self.usage()["used"], 1200)
        # the 429 gave the daily request back: 3 counted, not 4
        row = org_store._read(self.root, "SELECT count FROM org_user_usage WHERE username='dev'",
                              one=True)
        self.assertEqual(row[0], 3)
        with mock.patch.object(org_store, "_month_str", return_value="2099-01"):
            st, d = self.chat()
            self.assertEqual(st, 200, d)
            self.assertEqual(self.usage()["used"], self.TOKENS_PER_REPLY)

    def test_me_shows_allowance(self):
        self.chat()
        st, d = self.req("GET", "/api/me", headers=self.auth)
        self.assertEqual(d["tokens"]["used"], 400)
        self.assertEqual(d["tokens"]["limit"], 1000)

    def test_failed_generation_releases_reservation(self):
        def boom(*a, **k):
            raise model_backend.BackendError("down")

        with mock.patch.object(model_backend, "generate", boom):
            st, _ = self.chat()
        self.assertEqual(st, 502)
        self.assertEqual(self.usage()["used"], 0)
        self.assertEqual(self.usage()["reserved"], 0)

    def test_no_reported_usage_falls_back_to_estimate(self):
        with mock.patch.object(model_backend, "generate", lambda *a, **k: "ok"):
            self.assertEqual(self.chat()[0], 200)
        u = self.usage()
        self.assertGreater(u["used"], 0)
        self.assertEqual(u["reserved"], 0)

    def test_twenty_concurrent_requests_overshoot_at_most_one_request(self):
        self.delay = 0.05
        results = []

        def go():
            results.append(self.chat()[0])

        threads = [threading.Thread(target=go) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        u = self.usage()
        self.assertEqual(u["reserved"], 0)
        self.assertLessEqual(u["used"], 1000 + self.TOKENS_PER_REPLY)
        self.assertEqual(u["used"], results.count(200) * self.TOKENS_PER_REPLY)
        self.assertIn(429, results)

    def test_store_reserve_is_atomic_under_threads(self):
        admitted = []

        def go():
            month = org_store.reserve_tokens(self.root, "racer", 100, 1000)
            if month:
                admitted.append(1)
                org_store.settle_tokens(self.root, "racer", month, 100, 100)

        threads = [threading.Thread(target=go) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        u = org_store.token_usage(self.root, "racer")
        self.assertLessEqual(u["used"], 1000 + 100)
        self.assertEqual(u["used"], 100 * len(admitted))
        self.assertEqual(u["reserved"], 0)

    def test_v1_uses_reported_usage(self):
        reply = {"id": "x", "object": "chat.completion", "choices": [],
                 "usage": {"prompt_tokens": 100, "completion_tokens": 500, "total_tokens": 600}}
        models = {"object": "list", "data": [{"id": "m", "object": "model"}]}
        with mock.patch.object(openai_gateway, "list_models", return_value=models), \
                mock.patch.object(openai_gateway, "complete", return_value=reply):
            body = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 50}
            self.assertEqual(self.req("POST", "/v1/chat/completions", body, self.auth)[0], 200)
            self.assertEqual(self.req("POST", "/v1/chat/completions", body, self.auth)[0], 200)
            st, d = self.req("POST", "/v1/chat/completions", body, self.auth)
        self.assertEqual(st, 429)
        self.assertEqual(d["error"]["code"], "insufficient_quota")
        self.assertEqual(self.usage()["used"], 1200)

    def test_bots_and_agent_routes_are_metered_and_429_when_allowance_used(self):
        feature_flags.set_flag(self.root, "connections", True)
        feature_flags.set_flag(self.root, "agent", True)

        def fake_run(project_root, bot_id, user_input, model="", workspace="."):
            model_backend.record_usage(self.TOKENS_PER_REPLY)
            return {"output": "ok"}

        def fake_stream(project_root, bot_id, user_input, model=""):
            def gen():
                model_backend.record_usage(self.TOKENS_PER_REPLY)
                yield "ok"
            return gen()

        with mock.patch.object(bots, "run", fake_run),                 mock.patch.object(bots, "run_stream", fake_stream),                 mock.patch.object(agent_jobs, "enqueue", return_value={"id": "j1"}):
            st, d = self.req("POST", "/api/bots/run", {"id": "b", "input": "hi"}, self.auth)
            self.assertEqual(st, 200, d)
            self.assertEqual(self.usage()["used"], 400)
            st, _ = self.req("POST", "/api/bots/run/stream", {"id": "b", "input": "hi"}, self.auth)
            self.assertEqual(st, 200)
            self.assertEqual(self.usage()["used"], 800)
            st, d = self.chat()   # 800 < 1000 -> admitted, now 1200
            self.assertEqual(st, 200, d)
            for path in ("/api/bots/run", "/api/bots/run/stream", "/api/agent/jobs"):
                st, d = self.req("POST", path, {"id": "b", "input": "hi", "task": "t"}, self.auth)
                self.assertEqual(st, 429, (path, d))
        u = self.usage()
        self.assertEqual((u["used"], u["reserved"]), (1200, 0))

    def test_agent_job_charges_flat_reservation_for_free_session(self):
        feature_flags.set_flag(self.root, "agent", True)
        with mock.patch.object(agent_jobs, "enqueue", return_value={"id": "j1"}):
            st, d = self.req("POST", "/api/agent/jobs", {"task": "t"}, self.auth)
        self.assertEqual(st, 200, d)
        u = self.usage()
        self.assertEqual((u["used"], u["reserved"]), (server.AGENT_JOB_TOKEN_COST, 0))

    def test_v1_stream_usage_chunk_only_forwarded_when_client_asked(self):
        models = {"object": "list", "data": [{"id": "m", "object": "model"}]}
        usage = {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}

        def fake_stream(payload):
            self.assertTrue(payload["stream_options"]["include_usage"])   # always metered
            yield b'data: {"choices": [{"index": 0, "delta": {"content": "ok"}}]}\n\n'
            yield ("data: " + json.dumps({"choices": [], "usage": usage}) + "\n\n").encode()
            yield b"data: [DONE]\n\n"

        base = {"model": "m", "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 50, "stream": True}
        with mock.patch.object(openai_gateway, "list_models", return_value=models),                 mock.patch.object(openai_gateway, "stream", fake_stream):
            st, naive = self.req("POST", "/v1/chat/completions", base, self.auth)
            self.assertEqual(st, 200)
            self.assertEqual(self.usage()["used"], 300)
            st, asked = self.req("POST", "/v1/chat/completions",
                                 dict(base, stream_options={"include_usage": True}), self.auth)
            self.assertEqual(st, 200)
        self.assertEqual(self.usage()["used"], 600)
        self.assertNotIn('"usage"', naive)
        self.assertIn('"content": "ok"', naive)
        self.assertIn("[DONE]", naive)
        self.assertIn('"usage"', asked)

    def test_machine_owner_not_limited(self):
        for _ in range(4):
            st, _ = self.req("POST", "/api/chat",
                             {"messages": [{"role": "user", "content": "hi"}]},
                             {"X-Auth-Token": MASTER})
            self.assertEqual(st, 200)


if __name__ == "__main__":
    unittest.main()
