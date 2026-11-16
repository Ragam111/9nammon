"""
test_agent_eval_live.py — เทส golden-prompt runner โดย *ไม่ต้องมี Ollama*

ฉีด responder ปลอม (callable(messages)->str) แทนโมเดลจริง เพื่อยืนยันว่า:
- check ต่างๆ ตัดสินถูก (ผ่านเมื่อควรผ่าน, ตกเมื่อควรตก)
- งานแก้โค้ดต้องได้ SEARCH/REPLACE ที่ parser แกะได้จริงถึงจะผ่าน
- ไม่มี Ollama → run_live_eval() skip (ไม่ fail), แต่ถ้าฉีด responder เองต้องไม่ skip
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import agent_eval_live as live  # noqa: E402

# responder ที่ตอบครบทุก check ของทุกเคส: มี "def", "log", และ block a.py ที่ parse ได้
_GOOD = (
    "def add(a, b):\n    return a + b\n"
    "binary search = O(log n)\n"
    "a.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n"
)


def good_responder(_messages):
    return _GOOD


def refusal_responder(_messages):
    return "I'm sorry, I cannot help with that request."


def empty_responder(_messages):
    return "   "


def _case(cid):
    return next(c for c in live.GOLDEN_CASES if c["id"] == cid)


class RunnerLogicTest(unittest.TestCase):
    def test_all_pass_with_good_responder(self):
        rep = live.run_live_eval(responder=good_responder)
        self.assertFalse(rep["skipped"])
        self.assertEqual(rep["overall"]["passed"], rep["overall"]["total"])
        self.assertEqual(rep["overall"]["score_pct"], 100.0)

    def test_injected_responder_never_skips(self):
        rep = live.run_live_eval(responder=good_responder)
        self.assertFalse(rep["skipped"])
        self.assertIn("cases", rep)
        self.assertEqual(len(rep["cases"]), len(live.GOLDEN_CASES))

    def test_model_name_passed_through_to_report(self):
        rep = live.run_live_eval(responder=good_responder, model="qwen2.5-coder:1.5b")
        self.assertEqual(rep["model"], "qwen2.5-coder:1.5b")

    def test_refusal_is_caught(self):
        res = live.run_case(_case("th_write_add"), refusal_responder)
        checks = {r["check"]: r["passed"] for r in res["checks"]}
        self.assertFalse(checks["chk_not_refusal"])
        self.assertLess(res["passed"], res["total"])

    def test_empty_fails_nonempty(self):
        res = live.run_case(_case("th_write_add"), empty_responder)
        checks = {r["check"]: r["passed"] for r in res["checks"]}
        self.assertFalse(checks["chk_nonempty"])

    def test_run_case_captures_raw_response(self):
        # เก็บคำตอบดิบไว้ debug เคสที่ตก
        res = live.run_case(_case("th_write_add"), good_responder)
        self.assertEqual(res["response"], _GOOD)

    def test_edit_case_requires_parseable_diff(self):
        edit = _case("th_edit_change_value")
        # มี block ที่ parse ได้ -> ผ่าน
        ok = live.run_case(edit, good_responder)
        self.assertEqual(ok["passed"], ok["total"])
        # ตอบแก้ให้แต่ไม่เป็น format -> parseable_diff ต้องตก
        res = live.run_case(edit, lambda m: "เปลี่ยน x เป็น 2 ให้แล้วครับ")
        names = {r["check"]: r["passed"] for r in res["checks"]}
        self.assertFalse(names["parseable_diff[a.py]"])

    def test_edit_case_includes_file_context_in_messages(self):
        # งานแก้โค้ดต้องแนบเนื้อไฟล์เข้า context (ไม่งั้นโมเดลไม่เห็นโค้ดเดิม)
        msgs = live.build_messages(_case("th_edit_change_value"))
        joined = "".join(m["content"] for m in msgs)
        self.assertIn("x = 1", joined)
        self.assertEqual(msgs[0]["role"], "system")

    def test_language_system_prompt_selected(self):
        th = live.build_messages(_case("th_write_add"))[0]["content"]
        en = live.build_messages(_case("en_reverse_string"))[0]["content"]
        self.assertIn("ภาษาไทย", th)
        self.assertIn("English", en)


class AvailabilityTest(unittest.TestCase):
    def test_ollama_available_returns_bool(self):
        self.assertIsInstance(live.ollama_available(), bool)


if __name__ == "__main__":
    unittest.main()
