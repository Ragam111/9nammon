"""test_cluster_forward.py — forward งาน chat ไปทำที่ node อื่นจริง + fallback local เมื่อพลาด

มีทั้ง unit (is_enabled/pick_target/forward_chat) และ integration (hub → node สองเซิร์ฟเวอร์จริง)

Covers:
  ForwardUnitTest       — disabled_by_default, enabled_when_config_set,
                          pick_target_none_when_no_nodes, forward_chat_http_error_raises
  ForwardIntegrationTest — hub_forwards_chat_to_node, hub_streams_from_node,
                           fallback_local_when_node_unreachable
  ForwardMetaTest       — is_enabled returns bool, is_disabled after set false,
                          ForwardError is Exception, pick_target returns dict with node key,
                          forward_error has message, is_enabled after enable and disable
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
        self.assertIsNone(res["node"])

    def test_forward_chat_http_error_raises(self):
        with self.assertRaises(cluster_forward.ForwardError):
            cluster_forward.forward_chat("http://127.0.0.1:9", "tok",
                                         {"messages": []}, timeout=0.5)


class ForwardIntegrationTest(unittest.TestCase):
    """hub รับ /api/chat → forward ไป node จริง → เอา reply กลับมา"""

    def setUp(self):
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
        self._n = tempfile.TemporaryDirectory(); self._h = tempfile.TemporaryDirectory()
        self.node_root = Path(self._n.name); self.hub_root = Path(self._h.name)
        self.node = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.node_root, "huptok"))
        self.node_port = self.node.server_address[1]
        threading.Thread(target=self.node.serve_forever, daemon=True).start()
        self.node_url = f"http://127.0.0.1:{self.node_port}"
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
        self.assertEqual(data["reply"], "ตอบจาก-NODE")
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
        self.assertEqual("".join(deltas), "ตอบ-สตรีม")
        self.assertIn('"done": true', body)

    def test_fallback_local_when_node_unreachable(self):
        self.node.shutdown(); self.node.server_close()
        st, raw = self._post(self.hub_port, "/api/chat",
                             {"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(st, 200)
        data = json.loads(raw)
        self.assertEqual(data["reply"], "ตอบจาก-NODE")
        self.assertIsNone(data.get("served_by"))


class ForwardMetaTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_is_enabled_returns_bool(self):
        result = cluster_forward.is_enabled(self.root)
        self.assertIsInstance(result, bool)

    def test_is_disabled_after_enable_then_disable(self):
        config_manager.set_key(self.root, "CLUSTER_FORWARD_ENABLED", "true")
        self.assertTrue(cluster_forward.is_enabled(self.root))
        config_manager.set_key(self.root, "CLUSTER_FORWARD_ENABLED", "")
        self.assertFalse(cluster_forward.is_enabled(self.root))

    def test_forward_error_is_exception(self):
        self.assertTrue(issubclass(cluster_forward.ForwardError, Exception))

    def test_forward_error_carries_message(self):
        try:
            cluster_forward.forward_chat("http://127.0.0.1:9", "tok",
                                         {"messages": []}, timeout=0.5)
        except cluster_forward.ForwardError as e:
            self.assertGreater(len(str(e)), 0)
        else:
            self.fail("ต้อง raise ForwardError")

    def test_pick_target_returns_dict_with_node_key(self):
        result = cluster_forward.pick_target(self.root, rr_index=0)
        self.assertIsInstance(result, dict)
        self.assertIn("node", result)


if __name__ == "__main__":
    unittest.main()
