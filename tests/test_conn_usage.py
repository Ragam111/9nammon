"""test_conn_usage.py — นับ token/ค่าใช้จ่ายต่อ connection (Observability)"""

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

    def test_estimate_tokens(self):
        self.assertEqual(conn_usage.estimate_tokens(""), 0)
        self.assertEqual(conn_usage.estimate_tokens("x"), 1)         # มีเนื้อ → อย่างน้อย 1
        self.assertEqual(conn_usage.estimate_tokens("a" * 40), 10)   # 40/4

    def test_estimate_messages_tokens(self):
        msgs = [{"role": "system", "content": "a" * 8}, {"role": "user", "content": "b" * 4}]
        self.assertEqual(conn_usage.estimate_messages_tokens(msgs), 2 + 1)

    def test_record_and_summary(self):
        conn_usage.record_usage(self.root, "con-1", "Brain1", 10, 20)
        conn_usage.record_usage(self.root, "con-1", "Brain1", 5, 5)
        conn_usage.record_usage(self.root, "con-2", "Brain2", 100, 0)
        s = conn_usage.summary(self.root)
        self.assertEqual(s["totals"]["requests"], 3)
        self.assertEqual(s["totals"]["input_tokens"], 115)
        self.assertEqual(s["totals"]["output_tokens"], 25)
        self.assertEqual(s["totals"]["total_tokens"], 140)
        # cost = 140/1000 * price
        self.assertAlmostEqual(s["totals"]["est_cost"],
                               round(140 / 1000 * conn_usage.PRICE_PER_1K_TOKENS, 6))
        # ต่อ connection: con-1 รวม 2 requests
        c1 = next(c for c in s["connections"] if c["conn_id"] == "con-1")
        self.assertEqual(c1["requests"], 2)
        self.assertEqual(c1["total_tokens"], 40)

    def test_summary_empty(self):
        s = conn_usage.summary(self.root)
        self.assertEqual(s["totals"]["requests"], 0)
        self.assertEqual(s["connections"], [])

    def test_chat_records_usage(self):
        # chat() ต้องบันทึก usage ของ connection อัตโนมัติ (จุดเดียวครอบ Playground/Bot/agent)
        orig = connections._backend_for
        self.addCleanup(lambda: setattr(connections, "_backend_for", orig))
        rec = connections.add(self.root, "B", "ollama", model="m")
        connections._backend_for = lambda r: _FakeBackend()
        connections.chat(self.root, rec["id"], [{"role": "user", "content": "สวัสดี"}])
        s = conn_usage.summary(self.root)
        self.assertEqual(s["totals"]["requests"], 1)
        self.assertEqual(s["connections"][0]["conn_name"], "B")
        self.assertGreater(s["connections"][0]["output_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
