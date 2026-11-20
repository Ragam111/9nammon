"""Unit tests for app/cli_session.py — CLI session log persistence.

Covers:
  data_dir()         — env override vs LOCALAPPDATA vs home fallback
  sessions_dir()     — derived from data_dir()
  SessionLog.append  — creates dirs/file, writes valid JSONL, OSError fallback
  load_messages()    — parses JSONL, skips bad lines / wrong roles
  latest_session()   — finds newest matching project file
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.cli_session as cs


class _TmpDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# ---------------------------------------------------------------------------
# data_dir / sessions_dir
# ---------------------------------------------------------------------------

class TestDataDir(_TmpDir):
    def test_uses_lca_data_dir_override(self):
        custom = str(self.root / "custom")
        with patch.dict(os.environ, {"LCA_DATA_DIR": custom}, clear=False):
            self.assertEqual(cs.data_dir(), Path(custom))

    def test_uses_localappdata_when_no_override(self):
        base = str(self.root / "appdata")
        env = {"LOCALAPPDATA": base}
        with patch.dict(os.environ, env, clear=False):
            # Temporarily remove LCA_DATA_DIR if present
            with patch.dict(os.environ, {"LCA_DATA_DIR": ""}, clear=False):
                os.environ.pop("LCA_DATA_DIR", None)
                result = cs.data_dir()
        self.assertIn("LocalCodeAssistant", str(result))

    def test_fallback_to_home_when_no_localappdata(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("LCA_DATA_DIR", "LOCALAPPDATA")}
        with patch.dict(os.environ, env, clear=True):
            result = cs.data_dir()
        self.assertIn("LocalCodeAssistant", str(result))

    def test_sessions_dir_is_under_data_dir(self):
        custom = str(self.root / "d")
        with patch.dict(os.environ, {"LCA_DATA_DIR": custom}, clear=False):
            self.assertEqual(cs.sessions_dir(), Path(custom) / "cli_sessions")


# ---------------------------------------------------------------------------
# SessionLog — construction
# ---------------------------------------------------------------------------

class TestSessionLogInit(_TmpDir):
    def test_path_auto_generated(self):
        log = cs.SessionLog(self.root / "proj")
        self.assertTrue(str(log.path).endswith(".jsonl"))

    def test_explicit_path_accepted(self):
        p = self.root / "my.jsonl"
        log = cs.SessionLog(self.root, path=p)
        self.assertEqual(log.path, p)

    def test_project_resolved(self):
        proj = self.root / "proj"
        proj.mkdir()
        log = cs.SessionLog(proj)
        self.assertEqual(log.project, str(proj.resolve()))

    def test_enabled_true_by_default(self):
        self.assertTrue(cs.SessionLog(self.root).enabled)


# ---------------------------------------------------------------------------
# SessionLog.append
# ---------------------------------------------------------------------------

class TestSessionLogAppend(_TmpDir):
    def _log(self, name="test.jsonl"):
        return cs.SessionLog(self.root, path=self.root / name)

    def test_creates_file_on_first_append(self):
        log = self._log()
        log.append("user", "hello")
        self.assertTrue(log.path.exists())

    def test_creates_parent_dirs(self):
        p = self.root / "sub" / "deep" / "s.jsonl"
        log = cs.SessionLog(self.root, path=p)
        log.append("user", "hi")
        self.assertTrue(p.exists())

    def test_written_as_valid_json(self):
        log = self._log()
        log.append("user", "hello")
        rec = json.loads(log.path.read_text())
        self.assertIsInstance(rec, dict)

    def test_role_and_content_present(self):
        log = self._log()
        log.append("assistant", "world")
        rec = json.loads(log.path.read_text())
        self.assertEqual(rec["role"], "assistant")
        self.assertEqual(rec["content"], "world")

    def test_ts_field_present(self):
        log = self._log()
        log.append("user", "x")
        rec = json.loads(log.path.read_text())
        self.assertIn("ts", rec)

    def test_project_field_present(self):
        log = self._log()
        log.append("user", "x")
        rec = json.loads(log.path.read_text())
        self.assertIn("project", rec)

    def test_extra_kwargs_in_record(self):
        log = self._log()
        log.append("user", "x", model="llama3")
        rec = json.loads(log.path.read_text())
        self.assertEqual(rec["model"], "llama3")

    def test_multiple_appends_one_line_each(self):
        log = self._log()
        log.append("user", "a")
        log.append("assistant", "b")
        lines = log.path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)

    def test_disabled_flag_skips_write(self):
        log = self._log()
        log.enabled = False
        log.append("user", "x")
        self.assertFalse(log.path.exists())

    def test_oserror_disables_log(self):
        # Creating a directory at the target path causes open("a") to raise OSError
        p = self.root / "is_dir.jsonl"
        p.mkdir()
        log = cs.SessionLog(self.root, path=p)
        log.append("user", "x")
        self.assertFalse(log.enabled)

    def test_oserror_does_not_raise(self):
        p = self.root / "is_dir2.jsonl"
        p.mkdir()
        log = cs.SessionLog(self.root, path=p)
        try:
            log.append("user", "x")
        except OSError:
            self.fail("append should not raise on OSError")


# ---------------------------------------------------------------------------
# load_messages
# ---------------------------------------------------------------------------

class TestLoadMessages(_TmpDir):
    def _write(self, records, name="s.jsonl"):
        p = self.root / name
        with p.open("w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return p

    def test_empty_file_returns_empty(self):
        p = self.root / "empty.jsonl"
        p.touch()
        self.assertEqual(cs.load_messages(p), [])

    def test_nonexistent_file_returns_empty(self):
        self.assertEqual(cs.load_messages(self.root / "nope.jsonl"), [])

    def test_user_message_returned(self):
        p = self._write([{"role": "user", "content": "hi", "ts": "x", "project": "p"}])
        msgs = cs.load_messages(p)
        self.assertEqual(msgs, [{"role": "user", "content": "hi"}])

    def test_assistant_message_returned(self):
        p = self._write([{"role": "assistant", "content": "ok", "ts": "x", "project": "p"}])
        msgs = cs.load_messages(p)
        self.assertEqual(msgs[0]["role"], "assistant")

    def test_non_user_assistant_role_skipped(self):
        p = self._write([
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ])
        msgs = cs.load_messages(p)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["role"], "user")

    def test_bad_json_line_skipped(self):
        p = self.root / "bad.jsonl"
        p.write_text('{"role":"user","content":"ok"}\nnot-json\n')
        msgs = cs.load_messages(p)
        self.assertEqual(len(msgs), 1)

    def test_missing_content_skipped(self):
        p = self._write([{"role": "user"}])
        msgs = cs.load_messages(p)
        self.assertEqual(msgs, [])

    def test_non_string_content_skipped(self):
        p = self._write([{"role": "user", "content": 123}])
        msgs = cs.load_messages(p)
        self.assertEqual(msgs, [])

    def test_multiple_messages_order_preserved(self):
        records = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ]
        p = self._write(records)
        msgs = cs.load_messages(p)
        self.assertEqual([m["content"] for m in msgs], ["a", "b", "c"])


# ---------------------------------------------------------------------------
# latest_session
# ---------------------------------------------------------------------------

class TestLatestSession(_TmpDir):
    def _make_sessions_dir(self):
        d = self.root / "cli_sessions"
        d.mkdir(parents=True)
        return d

    def test_returns_none_when_no_sessions_dir(self):
        custom = str(self.root / "nodata")
        with patch.dict(os.environ, {"LCA_DATA_DIR": custom}, clear=False):
            self.assertIsNone(cs.latest_session(self.root / "proj"))

    def test_returns_none_when_no_matching_project(self):
        d = self._make_sessions_dir()
        p = d / "20260101-120000-99.jsonl"
        p.write_text(json.dumps({"project": "/other/proj"}) + "\n")
        with patch.dict(os.environ, {"LCA_DATA_DIR": str(self.root)}, clear=False):
            result = cs.latest_session(self.root / "myproj")
        self.assertIsNone(result)

    def test_returns_matching_session(self):
        d = self._make_sessions_dir()
        proj = (self.root / "proj").resolve()
        p = d / "20260101-120000-99.jsonl"
        p.write_text(json.dumps({"project": str(proj)}) + "\n")
        with patch.dict(os.environ, {"LCA_DATA_DIR": str(self.root)}, clear=False):
            result = cs.latest_session(proj)
        self.assertEqual(result, p)

    def test_returns_most_recent_when_multiple(self):
        d = self._make_sessions_dir()
        proj = (self.root / "proj").resolve()
        p1 = d / "20260101-120000-1.jsonl"
        p2 = d / "20260102-120000-2.jsonl"
        for p in (p1, p2):
            p.write_text(json.dumps({"project": str(proj)}) + "\n")
        with patch.dict(os.environ, {"LCA_DATA_DIR": str(self.root)}, clear=False):
            result = cs.latest_session(proj)
        self.assertEqual(result, p2)


class CliSessionExtraTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_session_log_path_ends_with_jsonl(self):
        log = cs.SessionLog(self.root)
        self.assertTrue(str(log.path).endswith(".jsonl"))

    def test_session_log_enabled_by_default(self):
        log = cs.SessionLog(self.root)
        self.assertTrue(log.enabled)

    def test_append_creates_file(self):
        p = self.root / "test.jsonl"
        log = cs.SessionLog(self.root, path=p)
        log.append("user", "hello")
        self.assertTrue(p.exists())

    def test_load_messages_nonexistent_returns_empty(self):
        result = cs.load_messages(self.root / "nope.jsonl")
        self.assertEqual(result, [])

    def test_latest_session_returns_none_when_no_data(self):
        custom = str(self.root / "nodata")
        with patch.dict(os.environ, {"LCA_DATA_DIR": custom}, clear=False):
            result = cs.latest_session(self.root / "proj")
        self.assertIsNone(result)

    def test_data_dir_returns_path(self):
        custom = str(self.root / "custom")
        with patch.dict(os.environ, {"LCA_DATA_DIR": custom}, clear=False):
            result = cs.data_dir()
        self.assertIsInstance(result, Path)


if __name__ == "__main__":
    unittest.main()
