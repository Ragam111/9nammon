"""test_cluster_forward.py — forward งาน chat ไปทำที่ node อื่นจริง + fallback local เมื่อพลาด

มีทั้ง unit (is_enabled/pick_target/forward_chat) และ integration (hub → node สองเซิร์ฟเวอร์จริง)
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
from app import cluster_forward, cluster_store, config_manager  # noqa: E402


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

class TestModuleConstants(unittest.TestCase):
    def test_chat_path_starts_with_slash(self):
        self.assertTrue(cluster_forward.CHAT_PATH.startswith("/"))

    def test_chat_stream_path_starts_with_slash(self):
        self.assertTrue(cluster_forward.CHAT_STREAM_PATH.startswith("/"))

    def test_default_timeout_positive(self):
        self.assertGreater(cluster_forward.DEFAULT_TIMEOUT, 0)

    def test_forward_error_is_exception(self):
        self.assertTrue(issubclass(cluster_forward.ForwardError, Exception))


# ---------------------------------------------------------------------------
# is_enabled — truthy/falsy values
# ---------------------------------------------------------------------------

class TestIsEnabled(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_disabled_by_default(self):
        self.assertFalse(cluster_forward.is_enabled(self.root))

    def test_enabled_by_true(self):
        config_manager.set_key(self.root, "CLUSTER_FORWARD_ENABLED", "true")
        self.assertTrue(cluster_forward.is_enabled(self.root))

    def test_enabled_by_1(self):
        config_manager.set_key(self.root, "CLUSTER_FORWARD_ENABLED", "1")
        self.assertTrue(cluster_forward.is_enabled(self.root))

    def test_enabled_by_yes(self):
        config_manager.set_key(self.root, "CLUSTER_FORWARD_ENABLED", "yes")
        self.assertTrue(cluster_forward.is_enabled(self.root))

    def test_enabled_by_on(self):
        config_manager.set_key(self.root, "CLUSTER_FORWARD_ENABLED", "on")
        self.assertTrue(cluster_forward.is_enabled(self.root))

    def test_disabled_by_false(self):
        config_manager.set_key(self.root, "CLUSTER_FORWARD_ENABLED", "false")
        self.assertFalse(cluster_forward.is_enabled(self.root))

    def test_disabled_by_zero(self):
        config_manager.set_key(self.root, "CLUSTER_FORWARD_ENABLED", "0")
        self.assertFalse(cluster_forward.is_enabled(self.root))

    def test_case_insensitive(self):
        config_manager.set_key(self.root, "CLUSTER_FORWARD_ENABLED", "TRUE")
        self.assertTrue(cluster_forward.is_enabled(self.root))


# ---------------------------------------------------------------------------
# ForwardError
# ---------------------------------------------------------------------------

class TestForwardError(unittest.TestCase):
    def test_raises_as_exception(self):
        with self.assertRaises(cluster_forward.ForwardError):
            raise cluster_forward.ForwardError("test error")

    def test_message_preserved(self):
        err = cluster_forward.ForwardError("custom msg")
        self.assertIn("custom msg", str(err))


# ---------------------------------------------------------------------------
# ForwardUnitTest (original + expanded)
# ---------------------------------------------------------------------------

class ForwardUnitTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_disabled_by_default(self):
        self.assertFalse(cluster_forward.is_enabled(self.root))

    def test_enabled_when_config_set(self):
        config_manager.set_key(self.root, "CLUSTER_FORWARD_ENABLED", "true")
        self.assertTrue(cluster_forward.is_enabled(self.root))

    def test_pick_target_none_when_no_nodes(self):
        res = cluster_forward.pick_target(self.root, rr_index=0)
        self.assertIsNone(res["node"])   # ไม่มี node → local

    def test_forward_chat_http_error_raises(self):
        # node ปลายทางที่ต่อไม่ติดจริง → ForwardError (ผู้เรียก fallback ได้)
        with self.assertRaises(cluster_forward.ForwardError):
            cluster_forward.forward_chat("http://127.0.0.1:9", "tok",
                                         {"messages": []}, timeout=0.5)

    def test_pick_target_returns_dict_with_expected_keys(self):
        res = cluster_forward.pick_target(self.root, rr_index=0)
        for key in ("node", "reason", "rr_index"):
            self.assertIn(key, res)

    def test_forward_chat_stream_raises_on_unreachable(self):
        with self.assertRaises(cluster_forward.ForwardError):
            # exhaust generator to trigger the error
            list(cluster_forward.forward_chat_stream(
                "http://127.0.0.1:9", "tok", {"messages": []}, timeout=0.5))


# ---------------------------------------------------------------------------
# ForwardIntegrationTest
# ---------------------------------------------------------------------------

class ForwardIntegrationTest(unittest.TestCase):
    """hub รับ /api/chat → forward ไป node จริง → เอา reply กลับมา"""

    def setUp(self):
        # node คำนวณ: mock model_backend ให้คืนคำตอบแน่นอน (ไม่ต้องมี Ollama)
        # เก็บ patcher ไว้ stop เฉพาะตัวที่ start (ไม่ใช้ stopall กันรั่วไปไฟล์อื่น)
        self._patchers = [
            mock.patch.object(server.model_backend, "generate",
                              lambda root, model, messages, num_ctx=8192: "ตอบจาก-NODE"),
            mock.patch.object(server.model_backend, "generate_stream",
                              lambda root, model, messages, num_ctx=8192: iter(["ตอบ", "-", "สตรีม"])),
            mock.patch.object(cluster_store, "fetch_node_health",
                              lambda url, timeout=2.0: {"reachable": True, "health": {"ollama": "up"}}),
        ]
        for p in self._patchers:
            p.start()
        # node ใช้ token เดียวกับที่ hub ส่งตอน forward; hub ใช้ token คนละตัวให้ผู้เรียก
        self._n = tempfile.TemporaryDirectory(); self._h = tempfile.TemporaryDirectory()
        self.node_root = Path(self._n.name); self.hub_root = Path(self._h.name)
        self.node = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.node_root, "huptok"))
        self.node_port = self.node.server_address[1]
        threading.Thread(target=self.node.serve_forever, daemon=True).start()
        self.node_url = f"http://127.0.0.1:{self.node_port}"
        # ตั้ง hub: เปิด forward + token + ลงทะเบียน node
        config_manager.set_key(self.hub_root, "CLUSTER_FORWARD_ENABLED", "true")
        config_manager.set_key(self.hub_root, "CLUSTER_FORWARD_TOKEN", "huptok")
        cluster_store.add_node(self.hub_root, "node1", self.node_url)
        self.hub_token = "hub-session"
        self.hub = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.hub_root, self.hub_token))
        self.hub_port = self.hub.server_address[1]
        threading.Thread(target=self.hub.serve_forever, daemon=True).start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        for s in (self.node, self.hub):
            try:
                s.shutdown(); s.server_close()
            except Exception:
                pass
        self._n.cleanup(); self._h.cleanup()

    def _post(self, port, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", path, body=json.dumps(body),
                     headers={"Content-Type": "application/json",
                              "X-Auth-Token": self.hub_token})
        r = conn.getresponse(); raw = r.read(); conn.close()
        return r.status, raw

    def test_hub_forwards_chat_to_node(self):
        st, raw = self._post(self.hub_port, "/api/chat",
                             {"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(st, 200)
        data = json.loads(raw)
        self.assertEqual(data["reply"], "ตอบจาก-NODE")   # คำตอบมาจาก node ปลายทาง
        self.assertEqual(data.get("served_by"), "node1")

    def test_hub_streams_from_node(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.hub_port, timeout=5)
        conn.request("POST", "/api/chat/stream",
                     body=json.dumps({"messages": [{"role": "user", "content": "hi"}]}),
                     headers={"Content-Type": "application/json",
                              "X-Auth-Token": self.hub_token})
        r = conn.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn("text/event-stream", r.getheader("Content-Type"))
        body = r.read().decode("utf-8"); conn.close()
        deltas = []
        for block in body.split("\n\n"):
            block = block.strip()
            if block.startswith("data:"):
                evt = json.loads(block[5:].strip())
                if "delta" in evt:
                    deltas.append(evt["delta"])
        self.assertEqual("".join(deltas), "ตอบ-สตรีม")   # relay มาจาก node
        self.assertIn('"done": true', body)

    def test_fallback_local_when_node_unreachable(self):
        # node ถูกลงทะเบียนแต่ "ล่ม" (ต่อไม่ติด) → hub ต้องทำ local ไม่ใช่โยน error ให้ผู้ใช้
        self.node.shutdown(); self.node.server_close()
        st, raw = self._post(self.hub_port, "/api/chat",
                             {"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(st, 200)
        data = json.loads(raw)
        self.assertEqual(data["reply"], "ตอบจาก-NODE")   # local ก็ใช้ mock ตัวเดียวกัน
        self.assertIsNone(data.get("served_by"))          # ไม่มี served_by = ทำที่ hub เอง


if __name__ == "__main__":
    unittest.main()
