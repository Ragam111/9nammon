"""แผน C: ตัวจัดการโมเดล — ไม่ใช้เครือข่ายจริง (fake opener)"""
import io
import json
import unittest

from app import model_manager as mm

GB = 1024 ** 3


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _tags_opener(names_sizes):
    def opener(url, timeout=None):
        assert str(url).endswith("/api/tags")
        payload = {"models": [{"name": n, "size": s} for n, s in names_sizes]}
        return _Resp(json.dumps(payload).encode())
    return opener


def _down_opener(url, timeout=None):
    raise OSError("connection refused")


class FitStatusTest(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(mm.fit_status(1.0, 4.0), "fit")     # need 1.3, 1.5x = 1.95
        self.assertEqual(mm.fit_status(1.0, 1.5), "tight")
        self.assertEqual(mm.fit_status(1.0, 0.8), "no")
        self.assertEqual(mm.fit_status(1.0, 1.02), "tight")   # 1.5b on this 8 GB box
        self.assertEqual(mm.fit_status(1.0, None), "unknown")
        self.assertEqual(mm.fit_status(1.0, 0), "unknown")


class CatalogTest(unittest.TestCase):
    def test_marks_installed_and_lists_all_local_models(self):
        opener = _tags_opener([("qwen2.5-coder:1.5b", GB), ("llama3:latest", 4 * GB)])
        data = mm.catalog(2 * GB, 8 * GB, opener=opener)
        self.assertTrue(data["ollama_running"])
        self.assertEqual(data["ram_free_gb"], 2.0)
        self.assertEqual(data["ram_total_gb"], 8.0)
        self.assertEqual([m["name"] for m in data["installed"]], ["llama3:latest", "qwen2.5-coder:1.5b"])
        rows = {r["name"]: r for r in data["catalog"]}
        self.assertTrue(rows["qwen2.5-coder:1.5b"]["installed"])
        self.assertFalse(rows["qwen2.5-coder:7b"]["installed"])
        self.assertEqual(rows["qwen2.5-coder:7b"]["fit"], "no")
        self.assertEqual(rows["qwen2.5-coder:0.5b"]["fit"], "fit")

    def test_ollama_down_gives_empty_installed_not_fake_list(self):
        data = mm.catalog(2 * GB, 8 * GB, opener=_down_opener)
        self.assertFalse(data["ollama_running"])
        self.assertEqual(data["installed"], [])
        self.assertTrue(all(not r["installed"] for r in data["catalog"]))

    def test_unknown_ram(self):
        data = mm.catalog(0, 0, opener=_down_opener)
        self.assertIsNone(data["ram_free_gb"])
        self.assertTrue(all(r["fit"] == "unknown" for r in data["catalog"]))


class PullTest(unittest.TestCase):
    def test_rejects_name_outside_allowlist_before_any_call(self):
        def opener(*a, **k):
            raise AssertionError("must not call Ollama")
        with self.assertRaises(mm.ModelManagerError):
            list(mm.pull("evil/model:latest", opener=opener))

    def test_streams_progress_events(self):
        seen = {}

        def opener(req, timeout=None):
            seen["url"] = req.full_url
            seen["body"] = json.loads(req.data)
            lines = [{"status": "pulling manifest"},
                     {"status": "downloading", "completed": 5, "total": 10},
                     {"status": "success"}]
            return _Resp(b"\n".join(json.dumps(x).encode() for x in lines) + b"\n")
        events = list(mm.pull("qwen2.5-coder:0.5b", opener=opener))
        self.assertTrue(seen["url"].endswith("/api/pull"))
        self.assertEqual(seen["body"]["model"], "qwen2.5-coder:0.5b")
        self.assertEqual([e["status"] for e in events], ["pulling manifest", "downloading", "success"])

    def test_ollama_error_line_raises(self):
        def opener(req, timeout=None):
            return _Resp(b'{"status":"pulling manifest"}\n{"error":"disk full"}\n')
        with self.assertRaises(mm.ModelManagerError) as cm:
            list(mm.pull("qwen2.5:1.5b", opener=opener))
        self.assertIn("disk full", str(cm.exception))

    def test_connection_dropped_mid_stream_raises_thai_error(self):
        import http.client

        class _Broken:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def __iter__(self):
                yield b'{"status":"pulling manifest"}\n'
                yield b'{"status":"downloading","completed":1,"total":9}\n'
                raise http.client.IncompleteRead(b"")

        def opener(req, timeout=None):
            return _Broken()
        got = []
        with self.assertRaises(mm.ModelManagerError):
            for e in mm.pull("qwen2.5:1.5b", opener=opener):
                got.append(e["status"])
        self.assertEqual(got, ["pulling manifest", "downloading"])

    def test_ollama_unreachable_raises_thai_error(self):
        with self.assertRaises(mm.ModelManagerError):
            list(mm.pull("qwen2.5:1.5b", opener=_down_opener))


if __name__ == "__main__":
    unittest.main()
