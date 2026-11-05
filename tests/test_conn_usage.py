"""test_conn_usage.py — นับ token/ค่าใช้จ่ายต่อ connection (Observability)

Covers:
  ConnUsageTest      — estimate_tokens (ค่าต่างๆ), estimate_messages_tokens,
                       record_usage + summary (totals/per-conn), summary empty,
                       chat() records usage automatically
  ConnUsageTypesTest — PRICE_PER_1K_TOKENS type, estimate_tokens return type,
                       summary structure (required keys), endpoint field stored
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import conn_usage, connections  # noqa: E402


class _FakeBackend:
    def is_available(self):
        return True

    def generate(self, model, messages, num_ctx=8192, options=None):
        return "คำตอบยาวพอสมควรจากสมอง"


class ConnUsageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    # ── estimate_tokens ──────────────────────────────────────────────────────

    def test_estimate_tokens_empty(self):
        self.assertEqual(conn_usage.estimate_tokens(""), 0)

    def test_estimate_tokens_single_char(self):
        self.assertEqual(conn_usage.estimate_tokens("x"), 1)

    def test_estimate_tokens_four_chars(self):
        self.assertEqual(conn_usage.estimate_tokens("abcd"), 1)

    def test_estimate_tokens_forty_chars(self):
        self.assertEqual(conn_usage.estimate_tokens("a" * 40), 10)

    def test_estimate_tokens_returns_int(self):
        result = conn_usage.estimate_tokens("hello world")
        self.assertIsInstance(result, int)

    def test_estimate_tokens_thai_text(self):
        result = conn_usage.estimate_tokens("สวัสดี")
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 1)

    # ── estimate_messages_tokens ─────────────────────────────────────────────

    def test_estimate_messages_tokens(self):
        msgs = [{"role": "system", "content": "a" * 8}, {"role": "user", "content": "b" * 4}]
        self.assertEqual(conn_usage.estimate_messages_tokens(msgs), 2 + 1)

    def test_estimate_messages_tokens_empty_list(self):
        self.assertEqual(conn_usage.estimate_messages_tokens([]), 0)

    def test_estimate_messages_tokens_none(self):
        self.assertEqual(conn_usage.estimate_messages_tokens(None), 0)

    # ── record_usage + summary ───────────────────────────────────────────────

    def test_record_and_summary(self):
        conn_usage.record_usage(self.root, "con-1", "Brain1", 10, 20)
        conn_usage.record_usage(self.root, "con-1", "Brain1", 5, 5)
        conn_usage.record_usage(self.root, "con-2", "Brain2", 100, 0)
        s = conn_usage.summary(self.root)
        self.assertEqual(s["totals"]["requests"], 3)
        self.assertEqual(s["totals"]["input_tokens"], 115)
        self.assertEqual(s["totals"]["output_tokens"], 25)
        self.assertEqual(s["totals"]["total_tokens"], 140)
        self.assertAlmostEqual(s["totals"]["est_cost"],
                               round(140 / 1000 * conn_usage.PRICE_PER_1K_TOKENS, 6))
        c1 = next(c for c in s["connections"] if c["conn_id"] == "con-1")
        self.assertEqual(c1["requests"], 2)
        self.assertEqual(c1["total_tokens"], 40)

    def test_summary_empty(self):
        s = conn_usage.summary(self.root)
        self.assertEqual(s["totals"]["requests"], 0)
        self.assertEqual(s["connections"], [])

    def test_summary_has_required_keys(self):
        s = conn_usage.summary(self.root)
        for key in ("totals", "connections"):
            self.assertIn(key, s)
        for key in ("requests", "input_tokens", "output_tokens", "total_tokens", "est_cost"):
            self.assertIn(key, s["totals"])

    def test_summary_per_conn_has_required_fields(self):
        conn_usage.record_usage(self.root, "c1", "BrainX", 5, 10)
        s = conn_usage.summary(self.root)
        self.assertEqual(len(s["connections"]), 1)
        conn = s["connections"][0]
        for field in ("conn_id", "conn_name", "requests", "input_tokens",
                      "output_tokens", "total_tokens", "est_cost"):
            self.assertIn(field, conn, f"missing field: {field}")

    def test_chat_records_usage(self):
        orig = connections._backend_for
        self.addCleanup(lambda: setattr(connections, "_backend_for", orig))
        rec = connections.add(self.root, "B", "ollama", model="m")
        connections._backend_for = lambda r: _FakeBackend()
        connections.chat(self.root, rec["id"], [{"role": "user", "content": "สวัสดี"}])
        s = conn_usage.summary(self.root)
        self.assertEqual(s["totals"]["requests"], 1)
        self.assertEqual(s["connections"][0]["conn_name"], "B")
        self.assertGreater(s["connections"][0]["output_tokens"], 0)


class ConnUsageTypesTest(unittest.TestCase):
    def test_price_per_1k_is_positive_float(self):
        self.assertIsInstance(conn_usage.PRICE_PER_1K_TOKENS, float)
        self.assertGreater(conn_usage.PRICE_PER_1K_TOKENS, 0.0)

    def test_est_cost_is_float(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        conn_usage.record_usage(root, "x", "X", 100, 100)
        s = conn_usage.summary(root)
        self.assertIsInstance(s["totals"]["est_cost"], float)
        tmp.cleanup()

    def test_record_usage_degrades_on_bad_root(self):
        # bad path: record_usage ต้อง degrade ไม่ล้ม (ตาม docstring)
        try:
            conn_usage.record_usage(Path("/nonexistent/path/xyz"), "c", "C", 1, 1)
        except Exception as e:
            self.fail(f"record_usage ต้อง degrade แต่ raise: {e}")


if __name__ == "__main__":
    unittest.main()
