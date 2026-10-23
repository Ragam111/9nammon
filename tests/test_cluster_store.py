"""test_cluster_store.py — ทะเบียน node + health aggregator ของคลัสเตอร์

ไม่ยิงเน็ตจริง: mock fetch_node_health / urlopen เพื่อทดสอบ aggregate + degrade
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cluster_store as cs  # noqa: E402


class NodeRegistryTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_list_remove(self):
        cs.add_node(self.root, "arm", "http://192.168.1.50:8420")
        nodes = cs.list_nodes(self.root)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["name"], "arm")
        self.assertEqual(nodes[0]["url"], "http://192.168.1.50:8420")
        self.assertTrue(cs.remove_node(self.root, "arm"))
        self.assertEqual(cs.list_nodes(self.root), [])

    def test_remove_missing_is_false(self):
        self.assertFalse(cs.remove_node(self.root, "nope"))

    def test_add_same_name_updates_url(self):
        cs.add_node(self.root, "arm", "http://a:8420")
        cs.add_node(self.root, "arm", "http://b:8420")
        nodes = cs.list_nodes(self.root)
        self.assertEqual(len(nodes), 1)           # ไม่สร้างซ้ำ
        self.assertEqual(nodes[0]["url"], "http://b:8420")

    def test_trailing_slash_stripped(self):
        cs.add_node(self.root, "arm", "http://a:8420/")
        self.assertEqual(cs.list_nodes(self.root)[0]["url"], "http://a:8420")

    def test_reject_bad_url(self):
        for bad in ("", "file:///etc/passwd", "ftp://x", "not-a-url"):
            with self.assertRaises(ValueError):
                cs.add_node(self.root, "x", bad)

    def test_reject_empty_name(self):
        with self.assertRaises(ValueError):
            cs.add_node(self.root, "", "http://a:8420")


class FetchHealthTest(unittest.TestCase):
    def _resp(self, body):
        m = mock.MagicMock()
        m.read.return_value = body.encode("utf-8")
        m.__enter__.return_value = m
        m.__exit__.return_value = False
        return m

    def test_reachable_parses_health(self):
        body = '{"ok":true,"ollama":"up","ram_pressure":false,"recommended_model":"qwen2.5-coder:1.5b"}'
        with mock.patch("app.cluster_store.urllib.request.urlopen", return_value=self._resp(body)):
            r = cs.fetch_node_health("http://a:8420")
        self.assertTrue(r["reachable"])
        self.assertEqual(r["health"]["recommended_model"], "qwen2.5-coder:1.5b")

    def test_unreachable_degrades(self):
        import urllib.error
        with mock.patch("app.cluster_store.urllib.request.urlopen",
                        side_effect=urllib.error.URLError("down")):
            r = cs.fetch_node_health("http://a:8420")
        self.assertFalse(r["reachable"])
        self.assertIn("error", r)

    def test_bad_url_degrades_not_raises(self):
        r = cs.fetch_node_health("ftp://x")
        self.assertFalse(r["reachable"])


class ClusterHealthTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_aggregate_up_and_down(self):
        cs.add_node(self.root, "up1", "http://up:8420")
        cs.add_node(self.root, "down1", "http://down:8420")

        def fake(url, timeout=2.0):
            return {"reachable": True, "health": {"ollama": "up"}} if "up" in url \
                else {"reachable": False, "error": "URLError"}

        with mock.patch.object(cs, "fetch_node_health", side_effect=fake):
            out = cs.cluster_health(self.root)
        self.assertEqual(out["summary"], {"total": 2, "up": 1, "down": 1})
        names = {n["name"]: n["reachable"] for n in out["nodes"]}
        self.assertEqual(names, {"up1": True, "down1": False})

    def test_empty_cluster(self):
        out = cs.cluster_health(self.root)
        self.assertEqual(out["summary"], {"total": 0, "up": 0, "down": 0})
        self.assertEqual(out["nodes"], [])

    def test_preserves_node_order(self):
        """ผลลัพธ์ต้องเรียงเหมือน cluster.json เสมอ ไม่ใช่ตามใครเสร็จก่อน"""
        for name in ("a", "b", "c", "d"):
            cs.add_node(self.root, name, f"http://{name}:8420")

        import time

        def slow_variable(url, timeout=2.0):
            # a ช้าสุด, d เร็วสุด — ถ้าเรียงตาม "เสร็จก่อน" จะได้ d,c,b,a
            delay = {"a": 0.04, "b": 0.03, "c": 0.02, "d": 0.01}
            for k, v in delay.items():
                if f"//{k}:" in url:
                    time.sleep(v)
                    break
            return {"reachable": True, "health": {}}

        with mock.patch.object(cs, "fetch_node_health", side_effect=slow_variable):
            out = cs.cluster_health(self.root)
        self.assertEqual([n["name"] for n in out["nodes"]], ["a", "b", "c", "d"])

    def test_parallel_is_faster_than_sequential(self):
        """พิสูจน์ว่าขนานจริง: 4 node × sleep 0.2s → ขนาน < 0.5s (sequential จะ ~0.8s)
        ขอบเขตผ่อน (0.5s) เพื่อกัน CI runner ที่ช้า — ยังชัดกว่า sequential เสมอ"""
        for name in ("a", "b", "c", "d"):
            cs.add_node(self.root, name, f"http://{name}:8420")

        import time
        DELAY = 0.2

        def slow(url, timeout=2.0):
            time.sleep(DELAY)
            return {"reachable": True, "health": {}}

        with mock.patch.object(cs, "fetch_node_health", side_effect=slow):
            t0 = time.monotonic()
            out = cs.cluster_health(self.root)
            elapsed = time.monotonic() - t0

        self.assertEqual(out["summary"], {"total": 4, "up": 4, "down": 0})
        # ขนาน: ควร ~DELAY; sequential: ~4*DELAY. ตั้ง 0.5s = กันพลาดบน CI ช้า
        self.assertLess(elapsed, 0.5,
                        f"parallel cluster_health ช้าเกินไป: {elapsed:.3f}s (expected ≈{DELAY}s)")

    def test_max_workers_1_runs_sequentially(self):
        """max_workers=1 = fallback sequential (ไว้ debug/determinism)"""
        for name in ("a", "b"):
            cs.add_node(self.root, name, f"http://{name}:8420")
        call_threads = []

        def record(url, timeout=2.0):
            import threading
            call_threads.append(threading.get_ident())
            return {"reachable": True, "health": {}}

        with mock.patch.object(cs, "fetch_node_health", side_effect=record):
            out = cs.cluster_health(self.root, max_workers=1)
        self.assertEqual(out["summary"]["up"], 2)
        # sequential = ทุก call รันบน thread เดียวกัน (ของ caller)
        self.assertEqual(len(set(call_threads)), 1)

    def test_max_workers_capped(self):
        """node เยอะกว่า _MAX_WORKERS → ไม่สร้าง thread เกิน cap"""
        import threading
        for i in range(50):  # มากกว่า _MAX_WORKERS (32)
            cs.add_node(self.root, f"n{i}", f"http://n{i}:8420")
        seen_threads = set()
        lock = threading.Lock()

        def record(url, timeout=2.0):
            with lock:
                seen_threads.add(threading.get_ident())
            return {"reachable": True, "health": {}}

        with mock.patch.object(cs, "fetch_node_health", side_effect=record):
            cs.cluster_health(self.root)
        # thread ที่ใช้จริง ≤ cap + 1 (caller thread อาจเข้ามาด้วยในบางกรณี)
        self.assertLessEqual(len(seen_threads), cs._MAX_WORKERS + 1)


class EcosystemSettingsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_defaults_empty_and_token_hidden(self):
        s = cs.get_settings(self.root)
        self.assertEqual(s["NODE_NAME"], "")
        self.assertFalse(s["hub_token_set"])
        self.assertNotIn("HUB_TOKEN", s)          # ไม่เผย token เต็ม

    def test_set_and_readback(self):
        cs.set_settings(self.root, {
            "NODE_NAME": "arm", "NODE_URL": "http://a:8420/",
            "HUB_URL": "http://hub:8420", "HUB_TOKEN": "secret",
        })
        s = cs.get_settings(self.root)
        self.assertEqual(s["NODE_NAME"], "arm")
        self.assertEqual(s["NODE_URL"], "http://a:8420")   # trailing slash ถูกตัด
        self.assertTrue(s["hub_token_set"])                # ตั้งแล้ว แต่ไม่คืนค่า

    def test_set_rejects_bad_url(self):
        with self.assertRaises(ValueError):
            cs.set_settings(self.root, {"HUB_URL": "ftp://x"})

    def test_register_missing_settings(self):
        r = cs.register_with_hub(self.root)
        self.assertFalse(r["ok"])
        self.assertIn("NODE_NAME", r["error"])

    def test_register_posts_to_hub(self):
        cs.set_settings(self.root, {
            "NODE_NAME": "arm", "NODE_URL": "http://a:8420",
            "HUB_URL": "http://hub:8420", "HUB_TOKEN": "secret",
        })
        captured = {}

        def fake_urlopen(req, timeout=3.0):
            captured["url"] = req.full_url
            captured["token"] = req.headers.get("X-auth-token")
            m = mock.MagicMock()
            m.read.return_value = b'{"node":{"name":"arm","url":"http://a:8420"}}'
            m.__enter__.return_value = m
            m.__exit__.return_value = False
            return m

        with mock.patch("app.cluster_store.urllib.request.urlopen", side_effect=fake_urlopen):
            r = cs.register_with_hub(self.root)
        self.assertTrue(r["ok"])
        self.assertEqual(captured["url"], "http://hub:8420/api/admin/cluster/nodes")
        self.assertEqual(captured["token"], "secret")

    def test_register_hub_http_error_degrades(self):
        import urllib.error
        cs.set_settings(self.root, {
            "NODE_NAME": "arm", "NODE_URL": "http://a:8420",
            "HUB_URL": "http://hub:8420", "HUB_TOKEN": "bad",
        })
        err = urllib.error.HTTPError("http://hub:8420", 403, "Forbidden", {}, None)
        with mock.patch("app.cluster_store.urllib.request.urlopen", side_effect=err):
            r = cs.register_with_hub(self.root)
        self.assertFalse(r["ok"])
        self.assertIn("403", r["error"])


if __name__ == "__main__":
    unittest.main()
