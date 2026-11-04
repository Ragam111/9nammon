"""
test_cli_render.py — CLI แชทต้อง "ไม่ดึงจอ" ตอนผู้ใช้เลื่อนขึ้นอ่านระหว่างโมเดลตอบ (fix/cli-scroll-stable)

ตรวจ: ไม่มี redraw (\\r วนซ้ำ/ANSI cursor/clear screen/alt-screen), flush ถูก throttle,
โหมด quiet ไม่เขียนอะไรระหว่างตอบ, Ctrl+C หยุดคำตอบแต่ไม่ปิดแชท, Ollama ล่มไม่ sys.exit,
และประวัติแชทบันทึก/โหลดกลับได้
"""

import io
import json
import os
import re
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import cli_render  # noqa: E402
import cli_session  # noqa: E402
import local_coder  # noqa: E402

# ANSI ที่ "ขยับ cursor/ลบจอ/สลับจอ" = ต้นเหตุจอกระโดด (สี SGR ...m อนุญาต)
CURSOR_ANSI = re.compile(r"\x1b\[(\?1049|\d*[ABCDEFGHJKST]|\d*;\d*[Hf])")


class TTYOut(io.StringIO):
    def __init__(self, tty=True):
        super().__init__()
        self._tty = tty
        self.writes = []
        self.flushes = 0

    def isatty(self):
        return self._tty

    def write(self, s):
        self.writes.append(s)
        return super().write(s)

    def flush(self):
        self.flushes += 1


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class ResolveModeTest(unittest.TestCase):
    def test_legacy_windows_console_defaults_quiet(self):
        self.assertEqual(cli_render.resolve_mode("auto", env={}, os_name="nt"), "quiet")

    def test_windows_terminal_defaults_live(self):
        self.assertEqual(cli_render.resolve_mode("auto", env={"WT_SESSION": "x"}, os_name="nt"), "live")
        self.assertEqual(cli_render.resolve_mode(None, env={"TERM_PROGRAM": "vscode"}, os_name="nt"), "live")

    def test_posix_defaults_live(self):
        self.assertEqual(cli_render.resolve_mode(None, env={}, os_name="posix"), "live")

    def test_explicit_and_env(self):
        self.assertEqual(cli_render.resolve_mode("quiet", env={}, os_name="posix"), "quiet")
        self.assertEqual(cli_render.resolve_mode(None, env={"LCA_STREAM_MODE": "quiet"}, os_name="posix"), "quiet")
        self.assertEqual(cli_render.resolve_mode("bogus", env={}, os_name="posix"), "live")


class LiveRendererTest(unittest.TestCase):
    def _run(self, chunks, step=0.0, interval=0.25):
        out, clock, titles = TTYOut(), FakeClock(), []
        r = cli_render.StreamRenderer("live", out=out, flush_interval=interval, clock=clock,
                                      title=titles.append)
        r.start()
        for c in chunks:
            clock.t += step
            r.feed(c)
        return r, out, r.finish(), titles

    def test_append_only_no_redraw(self):
        r, out, text, _ = self._run([f"tok{i} " for i in range(200)], step=0.01)
        full = out.getvalue()
        self.assertEqual(text, "".join(f"tok{i} " for i in range(200)))
        self.assertIsNone(CURSOR_ANSI.search(full), "ห้ามมี ANSI ขยับ cursor/ลบจอ")
        # \r ใช้ได้แค่ลบบรรทัดสถานะครั้งเดียว (2 ตัว: ก่อนและหลังช่องว่าง)
        self.assertLessEqual(full.count("\r"), 2)
        self.assertIn(text, full)

    def test_flush_is_throttled(self):
        # 200 token ภายใน 2 วิ (ทุก 10ms) → flush ได้ไม่เกิน ~2/0.25 + ส่วนเริ่ม/จบ
        _, out, _, _ = self._run(["x"] * 200, step=0.01)
        self.assertLess(out.flushes, 15)

    def test_status_written_once(self):
        _, out, _, _ = self._run(["a", "b"])
        self.assertEqual(out.getvalue().count("กำลังคิด"), 1)

    def test_not_tty_has_no_status_line(self):
        out = TTYOut(tty=False)
        r = cli_render.StreamRenderer("live", out=out, title=lambda t: None)
        r.start()
        r.feed("hello")
        r.finish()
        self.assertNotIn("\r", out.getvalue())
        self.assertIn("hello", out.getvalue())

    def test_interrupted_note(self):
        out = TTYOut()
        r = cli_render.StreamRenderer("live", out=out, title=lambda t: None)
        r.start()
        r.feed("partial")
        self.assertEqual(r.finish(interrupted=True), "partial")
        self.assertIn("หยุดแล้ว", out.getvalue())


class QuietRendererTest(unittest.TestCase):
    def test_nothing_written_while_streaming(self):
        out, clock, titles = TTYOut(), FakeClock(), []
        r = cli_render.StreamRenderer("quiet", out=out, clock=clock, title=titles.append)
        r.start()
        before = len(out.writes)
        for i in range(100):
            clock.t += 0.05
            r.feed(f"w{i} ")
        self.assertEqual(len(out.writes), before, "โหมด quiet ห้ามเขียนลงจอระหว่างตอบ")
        self.assertTrue(titles, "ควรแสดงความคืบหน้าที่ title แทน")
        self.assertLessEqual(len(titles), 7)  # อัปเดต title ไม่เกินวิละครั้ง (5 วิ)
        text = r.finish()
        self.assertIn(text, out.getvalue())
        self.assertIsNone(CURSOR_ANSI.search(out.getvalue()))
        self.assertNotIn("\r", out.getvalue())


class PagerTest(unittest.TestCase):
    def test_pages_and_quit(self):
        out = TTYOut()
        keys = iter(["", "q"])
        text = "\n".join(f"line{i}" for i in range(30))
        cli_render.page_text(text, out=out, read_key=lambda p: next(keys), rows=7)  # 5 บรรทัด/หน้า
        got = out.getvalue()
        self.assertIn("line9", got)
        self.assertNotIn("line10", got)  # กด q หลังหน้า 2

    def test_short_text_no_prompt(self):
        out = TTYOut()
        cli_render.page_text("a\nb", out=out, read_key=lambda p: self.fail("ไม่ควรถาม"), rows=24)
        self.assertIn("b", out.getvalue())


class FakeResp:
    def __init__(self, lines, raise_after=None):
        self.lines, self.raise_after = lines, raise_after

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for i, line in enumerate(self.lines):
            if self.raise_after is not None and i == self.raise_after:
                raise KeyboardInterrupt
            yield line


def _ndjson(*contents, done=True):
    rows = [json.dumps({"message": {"content": c}, "done": False}).encode() + b"\n" for c in contents]
    if done:
        rows.append(json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n")
    return rows


class StreamChatTest(unittest.TestCase):
    def test_full_answer(self):
        out = TTYOut()
        with mock.patch("urllib.request.urlopen", return_value=FakeResp(_ndjson("สวัสดี", " ครับ"))):
            text, intr = local_coder.stream_chat("m", [], 2048, "live", out=out)
        self.assertEqual((text, intr), ("สวัสดี ครับ", False))

    def test_ctrl_c_keeps_partial_and_does_not_exit(self):
        out = TTYOut()
        resp = FakeResp(_ndjson("a", "b", "c"), raise_after=2)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            text, intr = local_coder.stream_chat("m", [], 2048, "quiet", out=out)
        self.assertEqual((text, intr), ("ab", True))

    def test_ollama_down_returns_instead_of_exit(self):
        out = TTYOut()
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")), \
                mock.patch("sys.stdout", new=io.StringIO()):
            text, intr = local_coder.stream_chat("m", [], 2048, "live", out=out)
        self.assertEqual((text, intr), ("", False))

    def test_legacy_wrapper_returns_str(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResp(_ndjson("x"))), \
                mock.patch("sys.stdout", new=TTYOut()):
            self.assertEqual(local_coder.call_ollama_stream("m", [], 2048, "live"), "x")


class SessionLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"LCA_DATA_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_append_load_and_latest(self):
        proj = Path(self.tmp.name) / "proj"
        proj.mkdir()
        log = cli_session.SessionLog(proj)
        log.append("user", "ถาม")
        log.append("assistant", "ตอบ", interrupted=True)
        self.assertTrue(log.path.is_relative_to(Path(self.tmp.name)))
        self.assertEqual(cli_session.latest_session(proj), log.path)
        self.assertEqual(cli_session.load_messages(log.path),
                         [{"role": "user", "content": "ถาม"}, {"role": "assistant", "content": "ตอบ"}])
        other = Path(self.tmp.name) / "other"
        other.mkdir()
        self.assertIsNone(cli_session.latest_session(other))

    def test_disabled_writes_nothing(self):
        log = cli_session.SessionLog(Path(self.tmp.name))
        log.enabled = False
        log.append("user", "x")
        self.assertFalse(log.path.exists())


if __name__ == "__main__":
    unittest.main()
