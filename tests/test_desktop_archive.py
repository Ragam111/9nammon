"""test_desktop_archive.py — sync project to desktop archive"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import desktop_archive  # noqa: E402


class GetArchiveRootTest(unittest.TestCase):
    @patch("pathlib.Path.home", return_value=Path("/mock/home"))
    def test_archive_root_under_desktop(self, _mock):
        root = desktop_archive.get_archive_root()
        self.assertIn("Desktop", str(root))
        self.assertIn("LocalCodeAssistant-Data", str(root))

    def test_archive_dir_name_constant(self):
        self.assertEqual(desktop_archive.ARCHIVE_DIR_NAME, "LocalCodeAssistant-Data")

    def test_get_archive_root_returns_path(self):
        root = desktop_archive.get_archive_root()
        self.assertIsInstance(root, Path)


class SyncProjectTest(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.archive = Path(tempfile.mkdtemp())
        (self.project / "CHANGELOG_local.md").write_text("# v1\n- change", encoding="utf-8")
        (self.project / "todos.json").write_text("[]", encoding="utf-8")

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
    def test_sync_returns_path_on_success(self, mock_root):
        mock_root.return_value = self.archive
        result = desktop_archive.sync_project(self.project)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, Path)

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_no_changelog_still_works(self, mock_root):
        mock_root.return_value = self.archive
        project = Path(tempfile.mkdtemp())
        # no CHANGELOG_local.md, no todos.json
        result = desktop_archive.sync_project(project)
        self.assertIsNotNone(result)

    @patch.object(desktop_archive, "get_archive_root")
    def test_index_records_project_name(self, mock_root):
        mock_root.return_value = self.archive
        desktop_archive.sync_project(self.project)
        index_path = self.archive / "index.json"
        data = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertIn(self.project.name, data)

    @patch.object(desktop_archive, "get_archive_root")
    def test_index_has_last_sync(self, mock_root):
        mock_root.return_value = self.archive
        desktop_archive.sync_project(self.project)
        index_path = self.archive / "index.json"
        data = json.loads(index_path.read_text(encoding="utf-8"))
        entry = data[self.project.name]
        self.assertIn("last_sync", entry)

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_idempotent(self, mock_root):
        mock_root.return_value = self.archive
        desktop_archive.sync_project(self.project)
        desktop_archive.sync_project(self.project)
        # Should not raise, index should still be valid
        index_path = self.archive / "index.json"
        data = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertIn(self.project.name, data)


if __name__ == "__main__":
    unittest.main()
