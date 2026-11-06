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
        self._tmp_project = tempfile.TemporaryDirectory()
        self._tmp_archive = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp_project.name)
        self.archive = Path(self._tmp_archive.name)

    def tearDown(self):
        self._tmp_project.cleanup()
        self._tmp_archive.cleanup()

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_creates_destination_dir(self, mock_root):
        mock_root.return_value = self.archive
        desktop_archive.sync_project(self.project)
        self.assertTrue((self.archive / self.project.name).is_dir())

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_twice_no_error(self, mock_root):
        mock_root.return_value = self.archive
        (self.project / "todos.json").write_text("[]", encoding="utf-8")
        desktop_archive.sync_project(self.project)
        desktop_archive.sync_project(self.project)

    def test_get_archive_root_returns_path(self):
        with patch("pathlib.Path.home", return_value=Path("/mock/home")):
            result = desktop_archive.get_archive_root()
            self.assertIsInstance(result, Path)

    def test_get_archive_root_has_localcodeassistant(self):
        with patch("pathlib.Path.home", return_value=Path("/mock/home")):
            result = desktop_archive.get_archive_root()
            self.assertIn("LocalCodeAssistant", str(result))

    @patch.object(desktop_archive, "get_archive_root")
    def test_index_is_valid_json(self, mock_root):
        mock_root.return_value = self.archive
        (self.project / "todos.json").write_text("[]", encoding="utf-8")
        desktop_archive.sync_project(self.project)
        index_path = self.archive / "index.json"
        data = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertIsNotNone(data)

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_empty_project_no_error(self, mock_root):
        mock_root.return_value = self.archive
        desktop_archive.sync_project(self.project)


if __name__ == "__main__":
    unittest.main()
