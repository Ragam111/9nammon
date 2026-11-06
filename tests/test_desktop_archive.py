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
    def test_get_archive_root_returns_path(self):
        with patch("pathlib.Path.home", return_value=Path("/mock/home")):
            root = desktop_archive.get_archive_root()
            self.assertIsInstance(root, Path)

    def test_archive_dir_name_constant_exists(self):
        self.assertTrue(hasattr(desktop_archive, "ARCHIVE_DIR_NAME"))
        self.assertIsInstance(desktop_archive.ARCHIVE_DIR_NAME, str)
        self.assertGreater(len(desktop_archive.ARCHIVE_DIR_NAME), 0)

    def test_get_archive_root_contains_archive_dir_name(self):
        with patch("pathlib.Path.home", return_value=Path("/mock/home")):
            root = desktop_archive.get_archive_root()
            self.assertIn(desktop_archive.ARCHIVE_DIR_NAME, str(root))

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_returns_path_on_success(self, mock_root):
        with tempfile.TemporaryDirectory() as project_tmp, \
                tempfile.TemporaryDirectory() as archive_tmp:
            mock_root.return_value = Path(archive_tmp)
            result = desktop_archive.sync_project(Path(project_tmp))
            self.assertIsNotNone(result)
            self.assertIsInstance(result, Path)

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_missing_changelog_still_works(self, mock_root):
        with tempfile.TemporaryDirectory() as project_tmp, \
                tempfile.TemporaryDirectory() as archive_tmp:
            mock_root.return_value = Path(archive_tmp)
            # project ไม่มี CHANGELOG_local.md → sync ต้องไม่ crash
            result = desktop_archive.sync_project(Path(project_tmp))
            self.assertIsNotNone(result)

    @patch.object(desktop_archive, "get_archive_root")
    def test_sync_idempotent(self, mock_root):
        with tempfile.TemporaryDirectory() as project_tmp, \
                tempfile.TemporaryDirectory() as archive_tmp:
            mock_root.return_value = Path(archive_tmp)
            project = Path(project_tmp)
            (project / "todos.json").write_text("[]", encoding="utf-8")
            desktop_archive.sync_project(project)
            desktop_archive.sync_project(project)  # ครั้งที่สอง ต้องไม่ crash
            index_path = Path(archive_tmp) / "index.json"
            self.assertTrue(index_path.exists())

    @patch.object(desktop_archive, "get_archive_root")
    def test_index_has_project_name_key(self, mock_root):
        with tempfile.TemporaryDirectory() as project_tmp, \
                tempfile.TemporaryDirectory() as archive_tmp:
            mock_root.return_value = Path(archive_tmp)
            project = Path(project_tmp)
            desktop_archive.sync_project(project)
            data = json.loads((Path(archive_tmp) / "index.json").read_text(encoding="utf-8"))
            self.assertIn(project.name, data)

    @patch.object(desktop_archive, "get_archive_root")
    def test_index_entry_has_last_sync_field(self, mock_root):
        with tempfile.TemporaryDirectory() as project_tmp, \
                tempfile.TemporaryDirectory() as archive_tmp:
            mock_root.return_value = Path(archive_tmp)
            project = Path(project_tmp)
            desktop_archive.sync_project(project)
            data = json.loads((Path(archive_tmp) / "index.json").read_text(encoding="utf-8"))
            self.assertIn("last_sync", data[project.name])


if __name__ == "__main__":
    unittest.main()
