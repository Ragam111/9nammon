"""test_cluster_router.py — เทสสมองจัดคิวงานของคลัสเตอร์ (pick_node / route_preview)"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import cluster_router as cr  # noqa: E402


def _node(name, reachable=True, ollama="up", ram=False, url=None):
    e = {"name": name, "url": url or f"http://{name}:8420", "reachable": reachable}
    if reachable:
        e["health"] = {"ollama": ollama, "ram_pressure": ram}
    else:
        e["error"] = "URLError"
    return e


class PickNodeTest(unittest.TestCase):
    def test_no_nodes_returns_local(self):
        r = cr.pick_node([])
        self.assertIsNone(r["node"])

    def test_all_down_returns_local(self):
        r = cr.pick_node([_node("a", reachable=False), _node("b", ollama="down")])
        self.assertIsNone(r["node"])

    def test_prefers_free_over_busy(self):
        nodes = [_node("busy", ram=True), _node("free", ram=False)]
        r = cr.pick_node(nodes, strategy="prefer_free")
        self.assertEqual(r["node"]["name"], "free")

    def test_all_busy_still_picks_one(self):
        nodes = [_node("a", ram=True), _node("b", ram=True)]
        r = cr.pick_node(nodes, strategy="prefer_free")
        self.assertIn(r["node"]["name"], ("a", "b"))

    def test_round_robin_cycles(self):
        nodes = [_node("a"), _node("b")]
        r0 = cr.pick_node(nodes, strategy="round_robin", rr_index=0)
        r1 = cr.pick_node(nodes, strategy="round_robin", rr_index=r0["rr_index"])
        self.assertEqual(r0["node"]["name"], "a")
        self.assertEqual(r1["node"]["name"], "b")
        # วนกลับมา a
        r2 = cr.pick_node(nodes, strategy="round_robin", rr_index=r1["rr_index"])
        self.assertEqual(r2["node"]["name"], "a")

    def test_skips_unreachable(self):
        nodes = [_node("dead", reachable=False), _node("live")]
        r = cr.pick_node(nodes)
        self.assertEqual(r["node"]["name"], "live")

    def test_unknown_ollama_field_treated_ok(self):
        # health ไม่มี ollama field → ถือว่าพอรับได้ (ไม่ใช่ down)
        e = {"name": "x", "url": "http://x", "reachable": True, "health": {}}
        r = cr.pick_node([e])
        self.assertEqual(r["node"]["name"], "x")


class RoutePreviewTest(unittest.TestCase):
    def test_preview_shape(self):
        ch = {"nodes": [_node("free"), _node("busy", ram=True)]}
        p = cr.route_preview(ch)
        self.assertEqual(p["target"]["name"], "free")
        self.assertEqual(p["candidates"], 2)

    def test_preview_no_nodes(self):
        p = cr.route_preview({"nodes": []})
        self.assertIsNone(p["target"])
        self.assertEqual(p["candidates"], 0)


class ClusterRouterExtraTest(unittest.TestCase):
    def test_pick_node_empty_returns_dict(self):
        r = cr.pick_node([])
        self.assertIsInstance(r, dict)

    def test_pick_node_has_node_key(self):
        r = cr.pick_node([])
        self.assertIn("node", r)

    def test_pick_node_no_nodes_node_is_none(self):
        r = cr.pick_node([])
        self.assertIsNone(r["node"])

    def test_pick_node_single_reachable(self):
        node = {"name": "x", "url": "http://x:8420", "reachable": True, "health": {"ollama": "up"}}
        r = cr.pick_node([node])
        self.assertEqual(r["node"]["name"], "x")

    def test_route_preview_returns_dict(self):
        p = cr.route_preview({"nodes": []})
        self.assertIsInstance(p, dict)

    def test_route_preview_has_candidates_key(self):
        p = cr.route_preview({"nodes": []})
        self.assertIn("candidates", p)


if __name__ == "__main__":
    unittest.main()
