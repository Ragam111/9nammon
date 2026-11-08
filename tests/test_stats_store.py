"""Unit tests for app/stats_store.py — request stats recorder."""


import tempfile
import time
import unittest
from pathlib import Path


from app.stats_store import get_stats, record


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _TmpPathMixin(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()



# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------


class TestRecord(_TmpPathMixin):
    def test_record_does_not_raise(self):
        record(self.tmp_path, "/api/chat", 200)

    def test_record_creates_db_file(self):
        record(self.tmp_path, "/api/chat", 200)
        self.assertTrue((self.tmp_path / "stats.db").exists())

    def test_record_bad_root_does_not_raise(self):
        record(Path("/nonexistent/path/xyz"), "/api/chat", 200)

    def test_record_non_standard_status_accepted(self):
        record(self.tmp_path, "/api/x", 999)
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["total_requests"], 1)

    def test_multiple_records_stored(self):
        for _ in range(5):
            record(self.tmp_path, "/api/chat", 200)
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["total_requests"], 5)



# ---------------------------------------------------------------------------
# get_stats — empty database
# ---------------------------------------------------------------------------


class TestGetStatsEmpty(_TmpPathMixin):
    def test_total_requests_zero(self):
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["total_requests"], 0)

    def test_total_errors_zero(self):
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["total_errors"], 0)

    def test_error_rate_zero(self):
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["error_rate"], 0.0)

    def test_last_24h_zero(self):
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["last_24h"], 0)

    def test_by_endpoint_empty(self):
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["by_endpoint"], [])

    def test_no_error_key_on_success(self):
        stats = get_stats(self.tmp_path)
        self.assertNotIn("error", stats)



# ---------------------------------------------------------------------------
# get_stats — counts
# ---------------------------------------------------------------------------


class TestGetStatsCounts(_TmpPathMixin):
    def test_counts_success_requests(self):
        record(self.tmp_path, "/api/a", 200)
        record(self.tmp_path, "/api/a", 201)
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["total_requests"], 2)

    def test_counts_error_requests(self):
        record(self.tmp_path, "/api/a", 200)
        record(self.tmp_path, "/api/a", 400)
        record(self.tmp_path, "/api/a", 500)
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["total_errors"], 2)

    def test_error_rate_calculation(self):
        record(self.tmp_path, "/api/a", 200)
        record(self.tmp_path, "/api/a", 500)
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["error_rate"], 0.5)

    def test_error_rate_all_success(self):
        record(self.tmp_path, "/api/a", 200)
        record(self.tmp_path, "/api/a", 201)
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["error_rate"], 0.0)

    def test_error_rate_all_errors(self):
        record(self.tmp_path, "/api/a", 500)
        record(self.tmp_path, "/api/a", 503)
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["error_rate"], 1.0)

    def test_status_399_not_counted_as_error(self):
        record(self.tmp_path, "/api/a", 399)
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["total_errors"], 0)

    def test_status_400_counted_as_error(self):
        record(self.tmp_path, "/api/a", 400)
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["total_errors"], 1)



# ---------------------------------------------------------------------------
# get_stats — by_endpoint
# ---------------------------------------------------------------------------


class TestGetStatsByEndpoint(_TmpPathMixin):
    def test_single_endpoint_in_list(self):
        record(self.tmp_path, "/api/chat", 200)
        stats = get_stats(self.tmp_path)
        self.assertEqual(len(stats["by_endpoint"]), 1)
        self.assertEqual(stats["by_endpoint"][0]["endpoint"], "/api/chat")

    def test_endpoint_count_correct(self):
        record(self.tmp_path, "/api/chat", 200)
        record(self.tmp_path, "/api/chat", 200)
        record(self.tmp_path, "/api/chat", 500)
        stats = get_stats(self.tmp_path)
        ep = stats["by_endpoint"][0]
        self.assertEqual(ep["count"], 3)

    def test_endpoint_error_count_correct(self):
        record(self.tmp_path, "/api/chat", 200)
        record(self.tmp_path, "/api/chat", 500)
        stats = get_stats(self.tmp_path)
        ep = stats["by_endpoint"][0]
        self.assertEqual(ep["errors"], 1)

    def test_multiple_endpoints_sorted_by_count(self):
        record(self.tmp_path, "/api/a", 200)
        record(self.tmp_path, "/api/b", 200)
        record(self.tmp_path, "/api/b", 200)
        record(self.tmp_path, "/api/b", 200)
        stats = get_stats(self.tmp_path)
        endpoints = [ep["endpoint"] for ep in stats["by_endpoint"]]
        self.assertEqual(endpoints[0], "/api/b")

    def test_top_20_limit(self):
        for i in range(25):
            record(self.tmp_path, f"/api/ep{i}", 200)
        stats = get_stats(self.tmp_path)
        self.assertLessEqual(len(stats["by_endpoint"]), 20)

    def test_endpoint_dict_has_required_keys(self):
        record(self.tmp_path, "/api/chat", 200)
        stats = get_stats(self.tmp_path)
        ep = stats["by_endpoint"][0]
        self.assertIn("endpoint", ep)
        self.assertIn("count", ep)
        self.assertIn("errors", ep)

    def test_two_endpoints_separate_counts(self):
        record(self.tmp_path, "/api/a", 200)
        record(self.tmp_path, "/api/b", 500)
        stats = get_stats(self.tmp_path)
        by_ep = {ep["endpoint"]: ep for ep in stats["by_endpoint"]}
        self.assertEqual(by_ep["/api/a"]["errors"], 0)
        self.assertEqual(by_ep["/api/b"]["errors"], 1)



# ---------------------------------------------------------------------------
# get_stats — last_24h
# ---------------------------------------------------------------------------


class TestGetStatsLast24h(_TmpPathMixin):
    def test_recent_records_counted_in_24h(self):
        record(self.tmp_path, "/api/chat", 200)
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["last_24h"], 1)

    def test_last_24h_matches_total_for_fresh_db(self):
        record(self.tmp_path, "/api/a", 200)
        record(self.tmp_path, "/api/b", 500)
        stats = get_stats(self.tmp_path)
        self.assertEqual(stats["last_24h"], stats["total_requests"])



# ---------------------------------------------------------------------------
# get_stats — return type
# ---------------------------------------------------------------------------


class TestGetStatsReturnType(_TmpPathMixin):
    def test_returns_dict(self):
        self.assertIsInstance(get_stats(self.tmp_path), dict)

    def test_total_requests_is_int(self):
        record(self.tmp_path, "/api/a", 200)
        self.assertIsInstance(get_stats(self.tmp_path)["total_requests"], int)

    def test_error_rate_is_float(self):
        record(self.tmp_path, "/api/a", 200)
        self.assertIsInstance(get_stats(self.tmp_path)["error_rate"], float)

    def test_by_endpoint_is_list(self):
        self.assertIsInstance(get_stats(self.tmp_path)["by_endpoint"], list)


if __name__ == "__main__":
    unittest.main()

