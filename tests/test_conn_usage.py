"""test_conn_usage.py — นับ token/ค่าใช้จ่ายต่อ connection (Observability)

Covers:
  estimate_tokens()          — empty/boundary/minimum
  estimate_messages_tokens() — None/empty/non-dict/missing-content
  record_usage()             — None conn_id/name, zero tokens, multiple endpoints
  summary()                  — shape, price_per_1k_tokens, ordering, aggregation
  _cost()                    — zero/1000/500/1 tokens
  integration                — record → summary round-trip, chat auto-records
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


class _TmpRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# estimate_tokens — happy path + boundary cases
# ---------------------------------------------------------------------------

class TestEstimateTokens(unittest.TestCase):
    def test_empty_string_returns_zero(self):
        self.assertEqual(conn_usage.estimate_tokens(""), 0)

    def test_single_char_returns_one(self):
        self.assertEqual(conn_usage.estimate_tokens("x"), 1)

    def test_exactly_four_chars_returns_one(self):
        # round(4/4)=1, max(1,1)=1
        self.assertEqual(conn_usage.estimate_tokens("abcd"), 1)

    def test_eight_chars_returns_two(self):
        self.assertEqual(conn_usage.estimate_tokens("a" * 8), 2)

    def test_forty_chars_returns_ten(self):
        self.assertEqual(conn_usage.estimate_tokens("a" * 40), 10)

    def test_non_empty_always_returns_at_least_one(self):
        # 1-char: max(1, round(1/4)) = max(1, 0) = 1
        for text in ("a", "!", "ก", " "):
            with self.subTest(text=repr(text)):
                self.assertGreaterEqual(conn_usage.estimate_tokens(text), 1)


# ---------------------------------------------------------------------------
# estimate_messages_tokens — edge cases
# ---------------------------------------------------------------------------

class TestEstimateMessagesTokens(unittest.TestCase):
    def test_happy_path(self):
        msgs = [{"role": "system", "content": "a" * 8},
                {"role": "user", "content": "b" * 4}]
        self.assertEqual(conn_usage.estimate_messages_tokens(msgs), 2 + 1)

    def test_none_input_returns_zero(self):
        self.assertEqual(conn_usage.estimate_messages_tokens(None), 0)

    def test_empty_list_returns_zero(self):
        self.assertEqual(conn_usage.estimate_messages_tokens([]), 0)

    def test_non_dict_items_are_skipped(self):
        msgs = ["not a dict", 42, None, {"role": "user", "content": "hi"}]
        result = conn_usage.estimate_messages_tokens(msgs)
        self.assertEqual(result, conn_usage.estimate_tokens("hi"))

    def test_missing_content_key_treated_as_empty(self):
        msgs = [{"role": "user"}]
        self.assertEqual(conn_usage.estimate_messages_tokens(msgs), 0)

    def test_none_content_uses_str_none(self):
        # str(None) == "None" (4 chars) -> estimate_tokens("None")
        msgs = [{"role": "user", "content": None}]
        self.assertEqual(conn_usage.estimate_messages_tokens(msgs),
                         conn_usage.estimate_tokens("None"))


# ---------------------------------------------------------------------------
# record_usage — degrades / edge cases
# ---------------------------------------------------------------------------

class TestRecordUsage(_TmpRoot):
    def test_basic_record_does_not_raise(self):
        conn_usage.record_usage(self.root, "c1", "Name", 10, 5)

    def test_none_conn_id_stored_as_empty_string(self):
        conn_usage.record_usage(self.root, None, "Brain", 1, 1)
        s = conn_usage.summary(self.root)
        self.assertEqual(s["connections"][0]["conn_id"], "")

    def test_none_conn_name_stored_as_empty_string(self):
        conn_usage.record_usage(self.root, "c1", None, 1, 1)
        s = conn_usage.summary(self.root)
        self.assertEqual(s["connections"][0]["conn_name"], "")

    def test_zero_tokens_does_not_raise(self):
        conn_usage.record_usage(self.root, "c1", "Brain", 0, 0)
        s = conn_usage.summary(self.root)
        self.assertEqual(s["totals"]["total_tokens"], 0)

    def test_multiple_endpoints_all_counted(self):
        conn_usage.record_usage(self.root, "c1", "Brain", 5, 5, endpoint="chat")
        conn_usage.record_usage(self.root, "c1", "Brain", 5, 5, endpoint="bot")
        s = conn_usage.summary(self.root)
        self.assertEqual(s["totals"]["requests"], 2)


# ---------------------------------------------------------------------------
# summary — shape and field correctness
# ---------------------------------------------------------------------------

class TestSummaryShape(_TmpRoot):
    def test_empty_returns_zero_totals(self):
        s = conn_usage.summary(self.root)
        self.assertEqual(s["totals"]["requests"], 0)
        self.assertEqual(s["connections"], [])

    def test_has_price_per_1k_tokens_key(self):
        s = conn_usage.summary(self.root)
        self.assertIn("price_per_1k_tokens", s)

    def test_price_per_1k_tokens_matches_constant(self):
        s = conn_usage.summary(self.root)
        self.assertEqual(s["price_per_1k_tokens"], conn_usage.PRICE_PER_1K_TOKENS)

    def test_per_conn_has_required_keys(self):
        conn_usage.record_usage(self.root, "c1", "Brain", 10, 20)
        s = conn_usage.summary(self.root)
        for key in ("conn_id", "conn_name", "requests", "input_tokens",
                    "output_tokens", "total_tokens", "est_cost"):
            self.assertIn(key, s["connections"][0])

    def test_per_conn_total_tokens_is_input_plus_output(self):
        conn_usage.record_usage(self.root, "c1", "Brain", 10, 20)
        c = conn_usage.summary(self.root)["connections"][0]
        self.assertEqual(c["total_tokens"], c["input_tokens"] + c["output_tokens"])

    def test_per_conn_est_cost_matches_formula(self):
        conn_usage.record_usage(self.root, "c1", "Brain", 400, 600)
        c = conn_usage.summary(self.root)["connections"][0]
        expected = round(1000 / 1000.0 * conn_usage.PRICE_PER_1K_TOKENS, 6)
        self.assertAlmostEqual(c["est_cost"], expected)

    def test_totals_total_tokens_is_all_tokens(self):
        conn_usage.record_usage(self.root, "c1", "A", 10, 20)
        conn_usage.record_usage(self.root, "c2", "B", 30, 40)
        s = conn_usage.summary(self.root)
        self.assertEqual(s["totals"]["total_tokens"], 100)


# ---------------------------------------------------------------------------
# summary — ordering
# ---------------------------------------------------------------------------

class TestSummaryOrdering(_TmpRoot):
    def test_ordered_by_requests_descending(self):
        # c2 has 3 requests, c1 has 1 → c2 must come first
        conn_usage.record_usage(self.root, "c1", "One", 1, 1)
        for _ in range(3):
            conn_usage.record_usage(self.root, "c2", "Two", 1, 1)
        conns = conn_usage.summary(self.root)["connections"]
        self.assertEqual(conns[0]["conn_id"], "c2")
        self.assertEqual(conns[1]["conn_id"], "c1")

    def test_multiple_calls_same_conn_aggregated(self):
        for _ in range(5):
            conn_usage.record_usage(self.root, "c1", "Brain", 10, 10)
        s = conn_usage.summary(self.root)
        self.assertEqual(len(s["connections"]), 1)
        self.assertEqual(s["connections"][0]["requests"], 5)
        self.assertEqual(s["connections"][0]["total_tokens"], 100)


# ---------------------------------------------------------------------------
# _cost helper
# ---------------------------------------------------------------------------

class TestCostFunction(unittest.TestCase):
    def test_zero_tokens_returns_zero(self):
        self.assertEqual(conn_usage._cost(0), 0.0)

    def test_1000_tokens_returns_price_per_1k(self):
        self.assertAlmostEqual(conn_usage._cost(1000),
                               conn_usage.PRICE_PER_1K_TOKENS)

    def test_500_tokens_returns_half_price(self):
        self.assertAlmostEqual(conn_usage._cost(500),
                               round(0.5 * conn_usage.PRICE_PER_1K_TOKENS, 6))

    def test_result_rounded_to_6_decimals(self):
        result = conn_usage._cost(1)
        expected = round(1 / 1000.0 * conn_usage.PRICE_PER_1K_TOKENS, 6)
        self.assertEqual(result, expected)


# ---------------------------------------------------------------------------
# Integration — record + summary round-trip + chat auto-records
# ---------------------------------------------------------------------------

class ConnUsageTest(_TmpRoot):
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


if __name__ == "__main__":
    unittest.main()
