"""
test_agent_eval.py — ล็อก baseline ของ offline agent-quality harness (Q)

- ยืนยันว่า scorecard ปัจจุบัน = 100% (ถ้าใครแก้ prompt/heuristic แล้วทำ routing หรือ
  format contract ถอยหลัง เทสนี้จะแดงให้เห็นทันที)
- คุมพฤติกรรม build_auto_context (token budget / size cap / manual override / ignore)
  ซึ่งเป็นงบ context ที่กระทบคุณภาพคำตอบของ agent โดยตรง
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import agent_eval  # noqa: E402
from app import context_manager as cm  # noqa: E402


class ScorecardBaselineTest(unittest.TestCase):
    def test_overall_is_perfect_baseline(self):
        sc = agent_eval.scorecard()
        ov = sc["overall"]
        self.assertEqual(
            ov["passed"], ov["total"],
            f"agent-quality baseline ถอยหลัง: {ov['passed']}/{ov['total']} "
            f"— ดูมิติที่ตก: {[d for d in sc['dimensions'].values() if d['failures']]}",
        )
        self.assertEqual(ov["score_pct"], 100.0)

    def test_each_dimension_present_and_passing(self):
        sc = agent_eval.scorecard()
        for name in ("routing", "diff_parsing", "prompt_contract"):
            self.assertIn(name, sc["dimensions"])
            d = sc["dimensions"][name]
            self.assertEqual(d["passed"], d["total"], f"มิติ {name} มีเคสตก: {d['failures']}")
            self.assertGreater(d["total"], 0)


class RoutingBehaviourTest(unittest.TestCase):
    """สปอตเช็กพฤติกรรมสำคัญของ classify_input (นอกเหนือจาก dataset ใน harness)"""

    def test_external_beats_code_edit_keyword(self):
        # มีทั้ง "issue" (external) และ "แก้" (code_edit) -> external ต้องชนะ (ตรวจก่อน)
        from local_coder import classify_input
        self.assertEqual(classify_input("แก้ issue ใน jira", False), "external_project")

    def test_files_in_context_implies_code_edit(self):
        from local_coder import classify_input
        self.assertEqual(classify_input("อันนี้คืออะไร", True), "code_edit")

    def test_plain_question_is_general(self):
        from local_coder import classify_input
        self.assertEqual(classify_input("merge sort คืออะไร", False), "general")


class BuildAutoContextTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        cm._content_cache.clear()  # กัน cache ข้ามเทส (module-level)

    def tearDown(self):
        cm._content_cache.clear()
        self._tmp.cleanup()

    def _write(self, rel, content):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_picks_up_normal_file(self):
        self._write("a.py", "print(1)\n")
        ctx = cm.build_auto_context(self.root, num_ctx=8192, already_manual=set())
        self.assertIn("a.py", ctx)

    def test_skips_file_over_size_cap(self):
        big = "x" * (cm.MAX_FILE_SIZE_BYTES + 10)
        self._write("big.txt", big)
        self._write("small.txt", "ok")
        ctx = cm.build_auto_context(self.root, num_ctx=8192, already_manual=set())
        self.assertNotIn("big.txt", ctx)
        self.assertIn("small.txt", ctx)

    def test_manual_files_excluded(self):
        self._write("keep.py", "a")
        self._write("manual.py", "b")
        ctx = cm.build_auto_context(self.root, num_ctx=8192, already_manual={"manual.py"})
        self.assertNotIn("manual.py", ctx)
        self.assertIn("keep.py", ctx)

    def test_default_ignore_excludes_secrets(self):
        # config.json อยู่ใน DEFAULT_IGNORE_PATTERNS — ห้ามหลุดเข้า context เด็ดขาด
        self._write("config.json", '{"secret":"x"}')
        self._write("ok.py", "1")
        ctx = cm.build_auto_context(self.root, num_ctx=8192, already_manual=set())
        self.assertNotIn("config.json", ctx)

    def test_token_budget_limits_total(self):
        # num_ctx เล็ก -> งบ char เล็ก -> ใส่ได้ไม่ครบทุกไฟล์
        for i in range(6):
            self._write(f"f{i}.txt", "y" * 400)
        ctx = cm.build_auto_context(self.root, num_ctx=256, already_manual=set())
        budget = int(256 * cm.CONTEXT_BUDGET_RATIO * cm.CHARS_PER_TOKEN_ESTIMATE)
        used = sum(len(v) for v in ctx.values())
        self.assertLessEqual(used, budget)
        self.assertLess(len(ctx), 6)  # ต้องมีไฟล์ถูกข้ามเพราะงบเต็ม

    def test_recent_files_prioritised(self):
        # แก้ล่าสุดก่อน: เมื่องบพอแค่ไฟล์เดียว ต้องได้ไฟล์ที่ mtime ใหม่สุด
        # budget(num_ctx=256) = 256*0.6*4 = 614 chars -> ไฟล์ 400 ใส่ได้ไฟล์เดียว
        old = self._write("old.txt", "o" * 400)
        new = self._write("new.txt", "n" * 400)
        import os as _os
        past = time.time() - 1000
        _os.utime(old, (past, past))  # ทำให้ old เก่ากว่าจริงๆ
        ctx = cm.build_auto_context(self.root, num_ctx=256, already_manual=set())
        self.assertIn("new.txt", ctx)
        self.assertNotIn("old.txt", ctx)


if __name__ == "__main__":
    unittest.main()
