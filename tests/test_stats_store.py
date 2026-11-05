"""Unit tests for app/stats_store.py — request stats recorder."""

import time
from pathlib import Path

import pytest

from app.stats_store import get_stats, record


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _root(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return tmp_path


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------

class TestRecord:
    def test_record_does_not_raise(self, tmp_path):
        record(_root(tmp_path), "/api/chat", 200)

    def test_record_creates_db_file(self, tmp_path):
        record(_root(tmp_path), "/api/chat", 200)
        assert (tmp_path / "stats.db").exists()

    def test_record_bad_root_does_not_raise(self, tmp_path):
        record(Path("/nonexistent/path/xyz"), "/api/chat", 200)

    def test_record_non_standard_status_accepted(self, tmp_path):
        record(_root(tmp_path), "/api/x", 999)
        stats = get_stats(tmp_path)
        assert stats["total_requests"] == 1

    def test_multiple_records_stored(self, tmp_path):
        for _ in range(5):
            record(_root(tmp_path), "/api/chat", 200)
        stats = get_stats(tmp_path)
        assert stats["total_requests"] == 5


# ---------------------------------------------------------------------------
# get_stats — empty database
# ---------------------------------------------------------------------------

class TestGetStatsEmpty:
    def test_total_requests_zero(self, tmp_path):
        stats = get_stats(_root(tmp_path))
        assert stats["total_requests"] == 0

    def test_total_errors_zero(self, tmp_path):
        stats = get_stats(_root(tmp_path))
        assert stats["total_errors"] == 0

    def test_error_rate_zero(self, tmp_path):
        stats = get_stats(_root(tmp_path))
        assert stats["error_rate"] == 0.0

    def test_last_24h_zero(self, tmp_path):
        stats = get_stats(_root(tmp_path))
        assert stats["last_24h"] == 0

    def test_by_endpoint_empty(self, tmp_path):
        stats = get_stats(_root(tmp_path))
        assert stats["by_endpoint"] == []

    def test_no_error_key_on_success(self, tmp_path):
        stats = get_stats(_root(tmp_path))
        assert "error" not in stats


# ---------------------------------------------------------------------------
# get_stats — counts
# ---------------------------------------------------------------------------

class TestGetStatsCounts:
    def test_counts_success_requests(self, tmp_path):
        record(tmp_path, "/api/a", 200)
        record(tmp_path, "/api/a", 201)
        stats = get_stats(tmp_path)
        assert stats["total_requests"] == 2

    def test_counts_error_requests(self, tmp_path):
        record(tmp_path, "/api/a", 200)
        record(tmp_path, "/api/a", 400)
        record(tmp_path, "/api/a", 500)
        stats = get_stats(tmp_path)
        assert stats["total_errors"] == 2

    def test_error_rate_calculation(self, tmp_path):
        record(tmp_path, "/api/a", 200)
        record(tmp_path, "/api/a", 500)
        stats = get_stats(tmp_path)
        assert stats["error_rate"] == 0.5

    def test_error_rate_all_success(self, tmp_path):
        record(tmp_path, "/api/a", 200)
        record(tmp_path, "/api/a", 201)
        stats = get_stats(tmp_path)
        assert stats["error_rate"] == 0.0

    def test_error_rate_all_errors(self, tmp_path):
        record(tmp_path, "/api/a", 500)
        record(tmp_path, "/api/a", 503)
        stats = get_stats(tmp_path)
        assert stats["error_rate"] == 1.0

    def test_status_399_not_counted_as_error(self, tmp_path):
        record(tmp_path, "/api/a", 399)
        stats = get_stats(tmp_path)
        assert stats["total_errors"] == 0

    def test_status_400_counted_as_error(self, tmp_path):
        record(tmp_path, "/api/a", 400)
        stats = get_stats(tmp_path)
        assert stats["total_errors"] == 1


# ---------------------------------------------------------------------------
# get_stats — by_endpoint
# ---------------------------------------------------------------------------

class TestGetStatsByEndpoint:
    def test_single_endpoint_in_list(self, tmp_path):
        record(tmp_path, "/api/chat", 200)
        stats = get_stats(tmp_path)
        assert len(stats["by_endpoint"]) == 1
        assert stats["by_endpoint"][0]["endpoint"] == "/api/chat"

    def test_endpoint_count_correct(self, tmp_path):
        record(tmp_path, "/api/chat", 200)
        record(tmp_path, "/api/chat", 200)
        record(tmp_path, "/api/chat", 500)
        stats = get_stats(tmp_path)
        ep = stats["by_endpoint"][0]
        assert ep["count"] == 3

    def test_endpoint_error_count_correct(self, tmp_path):
        record(tmp_path, "/api/chat", 200)
        record(tmp_path, "/api/chat", 500)
        stats = get_stats(tmp_path)
        ep = stats["by_endpoint"][0]
        assert ep["errors"] == 1

    def test_multiple_endpoints_sorted_by_count(self, tmp_path):
        record(tmp_path, "/api/a", 200)
        record(tmp_path, "/api/b", 200)
        record(tmp_path, "/api/b", 200)
        record(tmp_path, "/api/b", 200)
        stats = get_stats(tmp_path)
        endpoints = [ep["endpoint"] for ep in stats["by_endpoint"]]
        assert endpoints[0] == "/api/b"

    def test_top_20_limit(self, tmp_path):
        for i in range(25):
            record(tmp_path, f"/api/ep{i}", 200)
        stats = get_stats(tmp_path)
        assert len(stats["by_endpoint"]) <= 20

    def test_endpoint_dict_has_required_keys(self, tmp_path):
        record(tmp_path, "/api/chat", 200)
        stats = get_stats(tmp_path)
        ep = stats["by_endpoint"][0]
        assert "endpoint" in ep
        assert "count" in ep
        assert "errors" in ep

    def test_two_endpoints_separate_counts(self, tmp_path):
        record(tmp_path, "/api/a", 200)
        record(tmp_path, "/api/b", 500)
        stats = get_stats(tmp_path)
        by_ep = {ep["endpoint"]: ep for ep in stats["by_endpoint"]}
        assert by_ep["/api/a"]["errors"] == 0
        assert by_ep["/api/b"]["errors"] == 1


# ---------------------------------------------------------------------------
# get_stats — last_24h
# ---------------------------------------------------------------------------

class TestGetStatsLast24h:
    def test_recent_records_counted_in_24h(self, tmp_path):
        record(tmp_path, "/api/chat", 200)
        stats = get_stats(tmp_path)
        assert stats["last_24h"] == 1

    def test_last_24h_matches_total_for_fresh_db(self, tmp_path):
        record(tmp_path, "/api/a", 200)
        record(tmp_path, "/api/b", 500)
        stats = get_stats(tmp_path)
        assert stats["last_24h"] == stats["total_requests"]


# ---------------------------------------------------------------------------
# get_stats — return type
# ---------------------------------------------------------------------------

class TestGetStatsReturnType:
    def test_returns_dict(self, tmp_path):
        assert isinstance(get_stats(_root(tmp_path)), dict)

    def test_total_requests_is_int(self, tmp_path):
        record(tmp_path, "/api/a", 200)
        assert isinstance(get_stats(tmp_path)["total_requests"], int)

    def test_error_rate_is_float(self, tmp_path):
        record(tmp_path, "/api/a", 200)
        assert isinstance(get_stats(tmp_path)["error_rate"], float)

    def test_by_endpoint_is_list(self, tmp_path):
        assert isinstance(get_stats(_root(tmp_path))["by_endpoint"], list)
