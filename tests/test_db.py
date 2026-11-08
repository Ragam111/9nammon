"""Unit tests for app/db.py — SQLite connection and migration runner."""

import sqlite3
import tempfile
import threading

import unittest
from pathlib import Path


from app.db import (
    MigrationError,
    connect_raw,
    db_path,
    list_migrations,
    split_sql,
    write_lock,
)


# ---------------------------------------------------------------------------
# split_sql
# ---------------------------------------------------------------------------


class TestSplitSql(unittest.TestCase):
    def test_single_statement_no_semicolon(self):
        result = split_sql("SELECT 1")
        self.assertEqual(result, ["SELECT 1"])

    def test_single_statement_with_semicolon(self):
        result = split_sql("SELECT 1;")
        self.assertEqual(result, ["SELECT 1"])

    def test_two_statements(self):
        result = split_sql("SELECT 1; SELECT 2")
        self.assertEqual(result, ["SELECT 1", "SELECT 2"])

    def test_two_statements_with_trailing_semicolon(self):
        result = split_sql("SELECT 1; SELECT 2;")
        self.assertEqual(result, ["SELECT 1", "SELECT 2"])

    def test_empty_string(self):
        self.assertEqual(split_sql(""), [])

    def test_whitespace_only(self):
        self.assertEqual(split_sql("   \n  "), [])


    def test_semicolon_inside_string_not_split(self):
        sql = "INSERT INTO t VALUES ('a;b')"
        result = split_sql(sql)

        self.assertEqual(result, ["INSERT INTO t VALUES ('a;b')"])


    def test_single_quoted_string_preserved(self):
        sql = "SELECT 'hello world' AS x; SELECT 2"
        result = split_sql(sql)

        self.assertEqual(len(result), 2)
        self.assertIn("'hello world'", result[0])


    def test_escaped_single_quote_in_string(self):
        sql = "SELECT 'it''s fine'; SELECT 2"
        result = split_sql(sql)

        self.assertEqual(len(result), 2)
        self.assertIn("it''s fine", result[0])


    def test_line_comment_stripped(self):
        sql = "SELECT 1 -- this is a comment\n; SELECT 2"
        result = split_sql(sql)

        self.assertEqual(len(result), 2)
        self.assertNotIn("--", result[0])


    def test_line_comment_only(self):
        sql = "-- entire line is a comment\nSELECT 1"
        result = split_sql(sql)

        self.assertEqual(result, ["SELECT 1"])


    def test_semicolon_after_comment(self):
        sql = "SELECT 1 -- comment\n; SELECT 2"
        result = split_sql(sql)

        self.assertEqual(len(result), 2)


    def test_multiple_whitespace_between_statements(self):
        sql = "SELECT 1;   \n\n   SELECT 2;"
        result = split_sql(sql)

        self.assertEqual(result, ["SELECT 1", "SELECT 2"])


    def test_empty_statements_skipped(self):
        sql = ";;; SELECT 1 ;;;"
        result = split_sql(sql)

        self.assertEqual(result, ["SELECT 1"])


    def test_create_table_statement(self):
        sql = """
        CREATE TABLE foo (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        INSERT INTO foo VALUES (1, 'bar');
        """
        result = split_sql(sql)

        self.assertEqual(len(result), 2)
        self.assertIn("CREATE TABLE", result[0])
        self.assertIn("INSERT INTO", result[1])


    def test_string_with_newline_inside(self):
        sql = "INSERT INTO t VALUES ('line1\nline2'); SELECT 1"
        result = split_sql(sql)

        self.assertEqual(len(result), 2)
        self.assertIn("line1\nline2", result[0])



# ---------------------------------------------------------------------------
# db_path
# ---------------------------------------------------------------------------


class TestDbPath(unittest.TestCase):
    def test_returns_path_object(self):
        result = db_path("/some/root")
        self.assertIsInstance(result, Path)

    def test_path_ends_with_lca_db(self):
        result = db_path("/some/root")
        self.assertEqual(result.name, "lca.db")

    def test_path_under_data_subdir(self):
        result = db_path("/some/root")
        self.assertEqual(result.parent.name, "data")

    def test_path_under_project_root(self):
        result = db_path("/my/project")
        self.assertTrue(str(result).startswith("/my/project"))

    def test_relative_root_works(self):
        result = db_path(".")
        self.assertEqual(result.name, "lca.db")



# ---------------------------------------------------------------------------
# write_lock
# ---------------------------------------------------------------------------


class TestWriteLock(unittest.TestCase):
    def test_returns_lock(self):
        lock = write_lock("/tmp/testroot_a")
        self.assertIsInstance(lock, threading.Lock)


    def test_same_root_same_lock(self):
        lock1 = write_lock("/tmp/testroot_b")
        lock2 = write_lock("/tmp/testroot_b")

        self.assertIs(lock1, lock2)


    def test_different_root_different_lock(self):
        lock1 = write_lock("/tmp/testroot_c1")
        lock2 = write_lock("/tmp/testroot_c2")

        self.assertIsNot(lock1, lock2)


    def test_lock_is_acquirable(self):
        lock = write_lock("/tmp/testroot_d")
        acquired = lock.acquire(blocking=False)
        if acquired:
            lock.release()

        self.assertTrue(acquired)



# ---------------------------------------------------------------------------
# connect_raw
# ---------------------------------------------------------------------------


class TestConnectRaw(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_returns_connection(self):
        conn = connect_raw(self.tmp_path / "test.db")
        self.assertIsInstance(conn, sqlite3.Connection)
        conn.close()

    def test_wal_mode_set(self):
        conn = connect_raw(self.tmp_path / "test.db")
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        self.assertEqual(mode, "wal")

    def test_foreign_keys_enabled(self):
        conn = connect_raw(self.tmp_path / "test.db")
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        conn.close()
        self.assertEqual(fk, 1)

    def test_row_factory_is_sqlite_row(self):
        conn = connect_raw(self.tmp_path / "test.db")
        self.assertIs(conn.row_factory, sqlite3.Row)
        conn.close()

    def test_lca_seg_function_registered(self):
        conn = connect_raw(self.tmp_path / "test.db")
        result = conn.execute("SELECT lca_seg('hello world')").fetchone()[0]
        conn.close()
        self.assertEqual(result, "hello world")

    def test_lca_seg_thai_produces_bigrams(self):
        conn = connect_raw(self.tmp_path / "test.db")
        result = conn.execute("SELECT lca_seg('กขค')").fetchone()[0]
        conn.close()
        self.assertEqual(result, "กข ขค")

    def test_parent_dir_created(self):
        nested = self.tmp_path / "deep" / "nested" / "test.db"
        conn = connect_raw(nested)
        conn.close()
        self.assertTrue(nested.exists())

    def test_in_memory_path_works(self):
        p = self.tmp_path / "mem.db"

        conn = connect_raw(p)
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
        val = conn.execute("SELECT x FROM t").fetchone()[0]
        conn.close()

        self.assertEqual(val, 42)



# ---------------------------------------------------------------------------
# list_migrations
# ---------------------------------------------------------------------------


class TestListMigrations(unittest.TestCase):
    def test_returns_list(self):
        result = list_migrations()
        self.assertIsInstance(result, list)


    def test_each_entry_is_four_tuple(self):
        result = list_migrations()
        for entry in result:

            self.assertEqual(len(entry), 4)


    def test_sorted_by_number(self):
        result = list_migrations()
        numbers = [entry[0] for entry in result]

        self.assertEqual(numbers, sorted(numbers))


    def test_number_is_int(self):
        result = list_migrations()
        for number, *_ in result:

            self.assertIsInstance(number, int)


    def test_sql_path_is_path(self):
        result = list_migrations()
        for _, _, sql_path, _ in result:

            self.assertIsInstance(sql_path, Path)


    def test_sql_path_exists(self):
        result = list_migrations()
        for _, _, sql_path, _ in result:

            self.assertTrue(sql_path.exists(), f"{sql_path} should exist")


    def test_py_path_none_or_path(self):
        result = list_migrations()
        for _, _, _, py_path in result:

            self.assertTrue(py_path is None or isinstance(py_path, Path))


if __name__ == "__main__":
    unittest.main()

