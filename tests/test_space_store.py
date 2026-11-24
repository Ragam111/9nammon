"""test_space_store.py — เทสพื้นที่ส่วนตัว/บริษัท + access control (RBAC)"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import space_store as ss  # noqa: E402


class SpaceStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_and_get(self):
        s = ss.create_space(self.root, "งานส่วนตัว", owner="nok", visibility="private")
        self.assertEqual(s["owner"], "nok")
        self.assertEqual(s["visibility"], "private")
        self.assertEqual(ss.get_space(self.root, s["id"])["name"], "งานส่วนตัว")

    def test_create_rejects_bad_visibility(self):
        with self.assertRaises(ValueError):
            ss.create_space(self.root, "x", owner="a", visibility="public")

    def test_create_rejects_empty_name(self):
        with self.assertRaises(ValueError):
            ss.create_space(self.root, "  ", owner="a")

    def test_private_access_owner_only(self):
        s = ss.create_space(self.root, "ส่วนตัวนก", owner="nok", visibility="private")
        self.assertTrue(ss.can_access(s, "nok", "USER"))     # เจ้าของ
        self.assertFalse(ss.can_access(s, "other", "USER"))  # คนอื่น เข้าไม่ได้

    def test_private_access_admin_can_see(self):
        s = ss.create_space(self.root, "ส่วนตัวนก", owner="nok", visibility="private")
        self.assertTrue(ss.can_access(s, "boss", "ADMIN"))   # แอดมินดูได้ (ดูแลระบบ)

    def test_shared_access_any_user(self):
        s = ss.create_space(self.root, "ห้องบริษัท", owner="nok", visibility="shared")
        self.assertTrue(ss.can_access(s, "anyone", "USER"))

    def test_add_member_grants_private_access(self):
        s = ss.create_space(self.root, "โปรเจกต์ลับ", owner="nok", visibility="private")
        self.assertFalse(ss.can_access(s, "mint", "USER"))
        ss.add_member(self.root, s["id"], "mint")
        s2 = ss.get_space(self.root, s["id"])
        self.assertTrue(ss.can_access(s2, "mint", "USER"))

    def test_list_spaces_filters_by_access(self):
        ss.create_space(self.root, "ส่วนตัว-A", owner="a", visibility="private")
        ss.create_space(self.root, "ส่วนตัว-B", owner="b", visibility="private")
        ss.create_space(self.root, "บริษัท", owner="a", visibility="shared")
        # b เห็น: ส่วนตัวของตัวเอง + shared (ไม่เห็นส่วนตัวของ a)
        names = {s["name"] for s in ss.list_spaces(self.root, "b", "USER")}
        self.assertEqual(names, {"ส่วนตัว-B", "บริษัท"})
        # แอดมินเห็นหมด
        admin_names = {s["name"] for s in ss.list_spaces(self.root, "boss", "ADMIN")}
        self.assertEqual(len(admin_names), 3)

    def test_items_in_space(self):
        s = ss.create_space(self.root, "ห้อง", owner="a", visibility="shared")
        ss.add_item(self.root, s["id"], "a", "สวัสดี")
        ss.add_item(self.root, s["id"], "b", "ครับ")
        items = ss.list_items(self.root, s["id"])
        self.assertEqual([i["text"] for i in items], ["สวัสดี", "ครับ"])

    def test_add_item_empty_rejected(self):
        s = ss.create_space(self.root, "ห้อง", owner="a", visibility="shared")
        with self.assertRaises(ValueError):
            ss.add_item(self.root, s["id"], "a", "   ")

    def test_add_item_unknown_space(self):
        with self.assertRaises(ValueError):
            ss.add_item(self.root, "sp-nope", "a", "hi")

    def test_concurrent_create_space_persists_all(self):
        # 30 การสร้างพร้อมกัน ต้องไม่มีอันไหนหายเพราะเขียนทับกัน (read-modify-write ใต้ lock)
        import threading
        errors = []
        barrier = threading.Barrier(30)

        def worker(i):
            try:
                barrier.wait()
                ss.create_space(self.root, f"ห้อง{i}", owner="nok", visibility="shared")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        spaces = ss.list_spaces(self.root, "nok", "CEO")
        self.assertEqual(len(spaces), 30)
        self.assertEqual(len({s["id"] for s in spaces}), 30)
        self.assertEqual(sorted(s["name"] for s in spaces),
                         sorted(f"ห้อง{i}" for i in range(30)))
        # ไม่มีไฟล์ชั่วคราวค้าง
        self.assertEqual(list(self.root.glob(".spaces-*.tmp")), [])

    def test_corrupt_store_is_preserved_before_next_write(self):
        truncated = '{"spaces": [{"id": "sp1", "name": "เก่า"'
        (self.root / ss.STORE_FILE).write_text(truncated, encoding="utf-8")
        self.assertEqual(ss.list_spaces(self.root, "nok", "CEO"), [])
        ss.create_space(self.root, "ใหม่", owner="nok")
        backups = sorted(self.root.glob(ss.STORE_FILE + ".corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), truncated)
        self.assertEqual([s["name"] for s in ss.list_spaces(self.root, "nok", "CEO")], ["ใหม่"])


if __name__ == "__main__":
    unittest.main()
