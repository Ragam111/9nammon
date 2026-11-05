"""test_desktop_archive.py — sync project to desktop archive"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import desktop_archive  # noqa: E402


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

class TestModuleConstants(unittest.TestCase):
    def test_archive_dir_name_is_string(self):
        self.assertIsInstance(desktop_archive.ARCHIVE_DIR_NAME, str)

    def test_archive_dir_name_non_empty(self):
        self.assertTrue(desktop_archive.ARCHIVE_DIR_NAME)


# ---------------------------------------------------------------------------
# get_archive_root
# ---------------------------------------------------------------------------

class GetArchiveRootTest(unittest.TestCase):
    @patch("pathlib.Path.home", return_value=Path("/mock/home"))
    def test_archive_root_under_desktop(self, _mock):
        root = desktop_archive.get_archive_root()
        self.assertIn("Desktop", str(root))
        self.assertIn("LocalCodeAssistant-Data", str(root))

    @patch("pathlib.Path.home", return_value=Path("/mock/home"))
    def test_archive_root_contains_archive_dir_name(self, _mock):
        root = desktop_archive.get_archive_root()
        self.assertIn(desktop_archive.ARCHIVE_DIR_NAME, str(root))

    @patch("pathlib.Path.home", return_value=Path("/mock/home"))
    def test_archive_root_is_path(self, _mock):
        root = desktop_archive.get_archive_root()
        self.assertIsInstance(root, Path)


# ---------------------------------------------------------------------------
# sync_project — happy path
# ---------------------------------------------------------------------------

class SyncProjectTest(unittest.TestCase):
    def setUp(self):
        self._proj_tmp = tempfile.TemporaryDirectory()
        self._arch_tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._proj_tmp.name)
        self.archive = Path(self._arch_tmp.name)
        (self.project / "CHANGELOG_local.md").write_text("# v1\n- change", encoding="utf-8")
        (self.project / "todos.json").write_text("[]", encoding="utf-8")

    def tearDown(self):
        self._proj_tmp.cleanup()
        self._arch_tmp.cleanup()

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_copies_changelog(self, mock_root):
        mock_root.return_value = self.archive
        desktop_archive.sync_project(self.project)
        synced = self.archive / self.project.name / "CHANGELOG_local.md"
        self.assertTrue(synced.exists())
        self.assertIn("v1", synced.read_text(encoding="utf-8"))

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_copies_todos(self, mock_root):
        mock_root.return_value = self.archive
        desktop_archive.sync_project(self.project)
        synced = self.archive / self.project.name / "todos.json"
        self.assertTrue(synced.exists())

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_creates_index(self, mock_root):
        mock_root.return_value = self.archive
        desktop_archive.sync_project(self.project)
        index_path = self.archive / "index.json"
        self.assertTrue(index_path.exists())
        data = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertIsInstance(data, (dict, list))

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_returns_path(self, mock_root):
        mock_root.return_value = self.archive
        result = desktop_archive.sync_project(self.project)
        self.assertIsInstance(result, Path)

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_no_changelog_ok(self, mock_root):
        mock_root.return_value = self.archive
        (self.project / "CHANGELOG_local.md").unlink()
        result = desktop_archive.sync_project(self.project)
        self.assertIsNotNone(result)

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_no_todos_ok(self, mock_root):
        mock_root.return_value = self.archive
        (self.project / "todos.json").unlink()
        result = desktop_archive.sync_project(self.project)
        self.assertIsNotNone(result)

    @patch.object(desktop_archive, "get_archive_root")
    def test_index_has_project_entry(self, mock_root):
        mock_root.return_value = self.archive
        desktop_archive.sync_project(self.project)
        index = json.loads((self.archive / "index.json").read_text(encoding="utf-8"))
        self.assertIn(self.project.name, index)

    @patch.object(desktop_archive, "get_archive_root")
    def test_index_entry_has_last_sync(self, mock_root):
        mock_root.return_value = self.archive
        desktop_archive.sync_project(self.project)
        index = json.loads((self.archive / "index.json").read_text(encoding="utf-8"))
        entry = index[self.project.name]
        self.assertIn("last_sync", entry)

    @patch.object(desktop_archive, "get_archive_root")
    def test_index_updated_on_second_sync(self, mock_root):
        mock_root.return_value = self.archive
        desktop_archive.sync_project(self.project)
        desktop_archive.sync_project(self.project)
        index = json.loads((self.archive / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len([k for k in index if k == self.project.name]), 1)

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_returns_none_when_mkdir_fails(self, mock_root):
        # make archive_root a file so mkdir fails
        fake_root = self.archive / "not_a_dir.txt"
        fake_root.write_text("block", encoding="utf-8")
        mock_root.return_value = fake_root
        result = desktop_archive.sync_project(self.project)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
