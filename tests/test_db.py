"""Unit tests for app/db.py — SQLite connection and migration runner."""

import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest

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

class TestSplitSql:
    def test_single_statement_no_semicolon(self):
        result = split_sql("SELECT 1")
        assert result == ["SELECT 1"]

    def test_single_statement_with_semicolon(self):
        result = split_sql("SELECT 1;")
        assert result == ["SELECT 1"]

    def test_two_statements(self):
        result = split_sql("SELECT 1; SELECT 2")
        assert result == ["SELECT 1", "SELECT 2"]

    def test_two_statements_with_trailing_semicolon(self):
        result = split_sql("SELECT 1; SELECT 2;")
        assert result == ["SELECT 1", "SELECT 2"]

    def test_empty_string(self):
        assert split_sql("") == []

    def test_whitespace_only(self):
        assert split_sql("   \n  ") == []

    def test_semicolon_inside_string_not_split(self):
        sql = "INSERT INTO t VALUES ('a;b')"
        result = split_sql(sql)
        assert result == ["INSERT INTO t VALUES ('a;b')"]

    def test_single_quoted_string_preserved(self):
        sql = "SELECT 'hello world' AS x; SELECT 2"
        result = split_sql(sql)
        assert len(result) == 2
        assert "'hello world'" in result[0]

    def test_escaped_single_quote_in_string(self):
        sql = "SELECT 'it''s fine'; SELECT 2"
        result = split_sql(sql)
        assert len(result) == 2
        assert "it''s fine" in result[0]

    def test_line_comment_stripped(self):
        sql = "SELECT 1 -- this is a comment\n; SELECT 2"
        result = split_sql(sql)
        assert len(result) == 2
        assert "--" not in result[0]

    def test_line_comment_only(self):
        sql = "-- entire line is a comment\nSELECT 1"
        result = split_sql(sql)
        assert result == ["SELECT 1"]

    def test_semicolon_after_comment(self):
        sql = "SELECT 1 -- comment\n; SELECT 2"
        result = split_sql(sql)
        assert len(result) == 2

    def test_multiple_whitespace_between_statements(self):
        sql = "SELECT 1;   \n\n   SELECT 2;"
        result = split_sql(sql)
        assert result == ["SELECT 1", "SELECT 2"]

    def test_empty_statements_skipped(self):
        sql = ";;; SELECT 1 ;;;"
        result = split_sql(sql)
        assert result == ["SELECT 1"]

    def test_create_table_statement(self):
        sql = """
        CREATE TABLE foo (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        INSERT INTO foo VALUES (1, 'bar');
        """
        result = split_sql(sql)
        assert len(result) == 2
        assert "CREATE TABLE" in result[0]
        assert "INSERT INTO" in result[1]

    def test_string_with_newline_inside(self):
        sql = "INSERT INTO t VALUES ('line1\nline2'); SELECT 1"
        result = split_sql(sql)
        assert len(result) == 2
        assert "line1\nline2" in result[0]


# ---------------------------------------------------------------------------
# db_path
# ---------------------------------------------------------------------------

class TestDbPath:
    def test_returns_path_object(self):
        result = db_path("/some/root")
        assert isinstance(result, Path)

    def test_path_ends_with_lca_db(self):
        result = db_path("/some/root")
        assert result.name == "lca.db"

    def test_path_under_data_subdir(self):
        result = db_path("/some/root")
        assert result.parent.name == "data"

    def test_path_under_project_root(self):
        result = db_path("/my/project")
        assert str(result).startswith("/my/project")

    def test_relative_root_works(self):
        result = db_path(".")
        assert result.name == "lca.db"


# ---------------------------------------------------------------------------
# write_lock
# ---------------------------------------------------------------------------

class TestWriteLock:
    def test_returns_lock(self):
        lock = write_lock("/tmp/testroot_a")
        assert isinstance(lock, threading.Lock)

    def test_same_root_same_lock(self):
        lock1 = write_lock("/tmp/testroot_b")
        lock2 = write_lock("/tmp/testroot_b")
        assert lock1 is lock2

    def test_different_root_different_lock(self):
        lock1 = write_lock("/tmp/testroot_c1")
        lock2 = write_lock("/tmp/testroot_c2")
        assert lock1 is not lock2

    def test_lock_is_acquirable(self):
        lock = write_lock("/tmp/testroot_d")
        acquired = lock.acquire(blocking=False)
        if acquired:
            lock.release()
        assert acquired


# ---------------------------------------------------------------------------
# connect_raw
# ---------------------------------------------------------------------------

class TestConnectRaw:
    def test_returns_connection(self, tmp_path):
        conn = connect_raw(tmp_path / "test.db")
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_wal_mode_set(self, tmp_path):
        conn = connect_raw(tmp_path / "test.db")
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_foreign_keys_enabled(self, tmp_path):
        conn = connect_raw(tmp_path / "test.db")
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        conn.close()
        assert fk == 1

    def test_row_factory_is_sqlite_row(self, tmp_path):
        conn = connect_raw(tmp_path / "test.db")
        assert conn.row_factory is sqlite3.Row
        conn.close()

    def test_lca_seg_function_registered(self, tmp_path):
        conn = connect_raw(tmp_path / "test.db")
        result = conn.execute("SELECT lca_seg('hello world')").fetchone()[0]
        conn.close()
        assert result == "hello world"

    def test_lca_seg_thai_produces_bigrams(self, tmp_path):
        conn = connect_raw(tmp_path / "test.db")
        result = conn.execute("SELECT lca_seg('กขค')").fetchone()[0]
        conn.close()
        assert result == "กข ขค"

    def test_parent_dir_created(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "test.db"
        conn = connect_raw(nested)
        conn.close()
        assert nested.exists()

    def test_in_memory_path_works(self, tmp_path):
        p = tmp_path / "mem.db"
        conn = connect_raw(p)
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
        val = conn.execute("SELECT x FROM t").fetchone()[0]
        conn.close()
        assert val == 42


# ---------------------------------------------------------------------------
# list_migrations
# ---------------------------------------------------------------------------

class TestListMigrations:
    def test_returns_list(self):
        result = list_migrations()
        assert isinstance(result, list)

    def test_each_entry_is_four_tuple(self):
        result = list_migrations()
        for entry in result:
            assert len(entry) == 4

    def test_sorted_by_number(self):
        result = list_migrations()
        numbers = [entry[0] for entry in result]
        assert numbers == sorted(numbers)

    def test_number_is_int(self):
        result = list_migrations()
        for number, *_ in result:
            assert isinstance(number, int)

    def test_sql_path_is_path(self):
        result = list_migrations()
        for _, _, sql_path, _ in result:
            assert isinstance(sql_path, Path)

    def test_sql_path_exists(self):
        result = list_migrations()
        for _, _, sql_path, _ in result:
            assert sql_path.exists(), f"{sql_path} should exist"

    def test_py_path_none_or_path(self):
        result = list_migrations()
        for _, _, _, py_path in result:
            assert py_path is None or isinstance(py_path, Path)
