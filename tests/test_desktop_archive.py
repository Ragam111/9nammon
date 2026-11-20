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


class DesktopArchiveExtraTest(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp())
        self.archive = Path(tempfile.mkdtemp())

    @patch("pathlib.Path.home", return_value=Path("/mock/home"))
    def test_archive_root_is_path(self, _mock):
        root = desktop_archive.get_archive_root()
        self.assertIsInstance(root, Path)

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_creates_project_subdir(self, mock_root):
        mock_root.return_value = self.archive
        (self.project / "CHANGELOG_local.md").write_text("# v1", encoding="utf-8")
        (self.project / "todos.json").write_text("[]", encoding="utf-8")
        desktop_archive.sync_project(self.project)
        self.assertTrue((self.archive / self.project.name).is_dir())

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_idempotent(self, mock_root):
        mock_root.return_value = self.archive
        (self.project / "CHANGELOG_local.md").write_text("# v1", encoding="utf-8")
        (self.project / "todos.json").write_text("[]", encoding="utf-8")
        desktop_archive.sync_project(self.project)
        desktop_archive.sync_project(self.project)
        synced = self.archive / self.project.name / "CHANGELOG_local.md"
        self.assertTrue(synced.exists())

    @patch.object(desktop_archive, "get_archive_root")
    def test_missing_changelog_still_syncs_todos(self, mock_root):
        mock_root.return_value = self.archive
        (self.project / "todos.json").write_text("[]", encoding="utf-8")
        desktop_archive.sync_project(self.project)
        synced = self.archive / self.project.name / "todos.json"
        self.assertTrue(synced.exists())

    @patch.object(desktop_archive, "get_archive_root")
    def test_index_is_valid_json(self, mock_root):
        mock_root.return_value = self.archive
        (self.project / "CHANGELOG_local.md").write_text("x", encoding="utf-8")
        (self.project / "todos.json").write_text("[]", encoding="utf-8")
        desktop_archive.sync_project(self.project)
        raw = (self.archive / "index.json").read_text(encoding="utf-8")
        json.loads(raw)  # must not raise

    @patch("pathlib.Path.home", return_value=Path("/mock/home"))
    def test_archive_root_has_localcodeassistant(self, _mock):
        root = desktop_archive.get_archive_root()
        self.assertIn("LocalCodeAssistant", str(root))


if __name__ == "__main__":
    unittest.main()
