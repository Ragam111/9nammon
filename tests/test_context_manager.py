"""test_context_manager.py — ignore patterns, scan_workspace, build_auto_context"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import context_manager  # noqa: E402


class LoadIgnorePatternsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_default_patterns_always_present(self):
        patterns = context_manager.load_ignore_patterns(self.tmp)
        self.assertIn(".git", patterns)
        self.assertIn("__pycache__", patterns)
        self.assertIn("config.json", patterns)

    def test_lcaignore_adds_patterns(self):
        (self.tmp / ".lcaignore").write_text("*.log\ntemp/", encoding="utf-8")
        patterns = context_manager.load_ignore_patterns(self.tmp)
        self.assertIn("*.log", patterns)
        self.assertIn("temp/", patterns)

    def test_comments_and_blanks_skipped(self):
        (self.tmp / ".lcaignore").write_text("# comment\n\n*.tmp", encoding="utf-8")
        patterns = context_manager.load_ignore_patterns(self.tmp)
        self.assertNotIn("# comment", patterns)
        self.assertIn("*.tmp", patterns)


class IsIgnoredTest(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(context_manager._is_ignored("config.json", ["config.json"]))

    def test_glob_match(self):
        self.assertTrue(context_manager._is_ignored("app/test.pyc", ["*.pyc"]))

    def test_not_ignored(self):
        self.assertFalse(context_manager._is_ignored("app/main.py", ["*.pyc"]))

    def test_dir_pattern(self):
        self.assertTrue(context_manager._is_ignored("node_modules", ["node_modules"]))


class ScanWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "main.py").write_text("print('hi')", encoding="utf-8")
        (self.tmp / "sub").mkdir()
        (self.tmp / "sub" / "helper.py").write_text("pass", encoding="utf-8")

    def test_finds_files(self):
        files = context_manager.scan_workspace(self.tmp)
        names = [f.name for f in files]
        self.assertIn("main.py", names)
        self.assertIn("helper.py", names)

    def test_ignores_git_dir(self):
        git_dir = self.tmp / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
        files = context_manager.scan_workspace(self.tmp)
        names = [str(f) for f in files]
        self.assertFalse(any(".git" in n.split(os.sep) for n in names))

    def test_ignores_pycache(self):
        cache = self.tmp / "__pycache__"
        cache.mkdir()
        (cache / "mod.cpython-310.pyc").write_bytes(b"\x00")
        files = context_manager.scan_workspace(self.tmp)
        names = [str(f) for f in files]
        self.assertFalse(any("__pycache__" in n for n in names))

    def test_ignores_config_json(self):
        (self.tmp / "config.json").write_text("{}", encoding="utf-8")
        files = context_manager.scan_workspace(self.tmp)
        names = [f.name for f in files]
        self.assertNotIn("config.json", names)


class BuildAutoContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "a.py").write_text("# file a", encoding="utf-8")
        (self.tmp / "b.py").write_text("# file b", encoding="utf-8")

    def test_returns_dict_of_content(self):
        ctx = context_manager.build_auto_context(self.tmp, num_ctx=4096, already_manual=set())
        self.assertIsInstance(ctx, dict)
        self.assertIn("a.py", ctx)
        self.assertEqual(ctx["a.py"], "# file a")

    def test_excludes_manual_files(self):
        ctx = context_manager.build_auto_context(self.tmp, num_ctx=4096, already_manual={"a.py"})
        self.assertNotIn("a.py", ctx)
        self.assertIn("b.py", ctx)

    def test_budget_limits_files(self):
        for i in range(20):
            (self.tmp / f"big{i}.py").write_text("x" * 5000, encoding="utf-8")
        ctx = context_manager.build_auto_context(self.tmp, num_ctx=100, already_manual=set())
        total_chars = sum(len(v) for v in ctx.values())
        budget = int(100 * context_manager.CONTEXT_BUDGET_RATIO * context_manager.CHARS_PER_TOKEN_ESTIMATE)
        self.assertLessEqual(total_chars, budget)

    def test_skips_large_files(self):
        big = self.tmp / "huge.py"
        big.write_text("x" * (context_manager.MAX_FILE_SIZE_BYTES + 1), encoding="utf-8")
        ctx = context_manager.build_auto_context(self.tmp, num_ctx=999999, already_manual=set())
        self.assertNotIn("huge.py", ctx)

    def test_skips_binary_files(self):
        (self.tmp / "img.bin").write_bytes(b"\x00\x01\x02\xff" * 100)
        ctx = context_manager.build_auto_context(self.tmp, num_ctx=4096, already_manual=set())
        self.assertNotIn("img.bin", ctx)


class CachedContentTest(unittest.TestCase):
    def test_cache_returns_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            f = p / "test.py"
            f.write_text("hello", encoding="utf-8")
            content = context_manager._get_cached_content(p, f)
            self.assertEqual(content, "hello")

    def test_cache_returns_none_for_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            content = context_manager._get_cached_content(p, p / "nope.py")
            self.assertIsNone(content)


if __name__ == "__main__":
    unittest.main()
