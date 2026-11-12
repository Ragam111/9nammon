"""Unit tests for app/router.py — multi-tier Ollama model selector.

recommend() does a lazy import inside the function:
  from app import hw_profile as _hwp

Stubbed via sys.modules injection in setUp/tearDown.
_ollama_installed_models() is patched via unittest.mock.patch.
app.router._cache cleared in setUp to prevent cache hits from other tests.
"""
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import app.router as router


_DEFAULT_PROFILE = {
    "tier": "netbook",
    "tier_reasons": ["4GB RAM"],
    "recommended_config": {"PREFERRED_MODEL": "qwen2.5-coder:1.5b"},
}

_fake_hw_profile = types.ModuleType("app.hw_profile")


class _RouterBase(unittest.TestCase):
    def setUp(self):
        # Clear module-level cache so tests don't see stale entries
        with router._cache_lock:
            router._cache.clear()

        # Inject fake hw_profile (same pattern as test_hw_meter)
        import app as _pkg
        self._saved = {
            "app.hw_profile": sys.modules.get("app.hw_profile"),
            "_pkg_attr": getattr(_pkg, "hw_profile", None),
        }
        sys.modules["app.hw_profile"] = _fake_hw_profile
        _pkg.hw_profile = _fake_hw_profile

    def tearDown(self):
        import app as _pkg
        orig = self._saved["app.hw_profile"]
        if orig is None:
            sys.modules.pop("app.hw_profile", None)
        else:
            sys.modules["app.hw_profile"] = orig
        orig_attr = self._saved["_pkg_attr"]
        if orig_attr is None:
            if hasattr(_pkg, "hw_profile"):
                try:
                    delattr(_pkg, "hw_profile")
                except AttributeError:
                    pass
        else:
            _pkg.hw_profile = orig_attr

    def _recommend(self, tier="netbook", tier_reasons=None,
                   ollama_running=False, installed=None,
                   profile_raises=False, project_root="/tmp/p"):
        if profile_raises:
            _fake_hw_profile.profile = MagicMock(side_effect=RuntimeError("fail"))
        else:
            _fake_hw_profile.profile = MagicMock(return_value={
                "tier": tier,
                "tier_reasons": tier_reasons or [],
            })
        installed_list = installed or []
        with patch.object(router, "_ollama_installed_models",
                          return_value=(ollama_running, installed_list)):
            return router.recommend(project_root)


# ---------------------------------------------------------------------------
# _TIER_MODELS structure
# ---------------------------------------------------------------------------

class TestTierModels(unittest.TestCase):
    def test_all_expected_tiers_present(self):
        for tier in ("netbook", "workstation", "server"):
            self.assertIn(tier, router._TIER_MODELS)

    def test_each_tier_has_models(self):
        for tier, models in router._TIER_MODELS.items():
            self.assertGreater(len(models), 0, f"{tier} has no models")

    def test_each_model_has_required_fields(self):
        for tier, models in router._TIER_MODELS.items():
            for m in models:
                for field in ("name", "size_gb", "description", "priority"):
                    self.assertIn(field, m, f"{tier} model missing {field}")

    def test_priority_starts_at_one(self):
        for tier, models in router._TIER_MODELS.items():
            priorities = [m["priority"] for m in models]
            self.assertIn(1, priorities, f"{tier} has no priority-1 model")


# ---------------------------------------------------------------------------
# _ollama_installed_models
# ---------------------------------------------------------------------------

class TestOllamaInstalledModels(unittest.TestCase):
    def _fake_urlopen(self, payload: bytes):
        """Return a context manager that yields a response with given bytes."""
        import io
        resp = MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_returns_running_true_and_names_on_success(self):
        import json
        import urllib.request
        payload = json.dumps({"models": [{"name": "llama3"}, {"name": "phi3"}]}).encode()
        with patch.object(urllib.request, "urlopen", return_value=self._fake_urlopen(payload)):
            running, names = router._ollama_installed_models()
        self.assertTrue(running)
        self.assertIn("llama3", names)
        self.assertIn("phi3", names)

    def test_returns_running_false_on_connection_error(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            running, names = router._ollama_installed_models()
        self.assertFalse(running)
        self.assertEqual(names, [])

    def test_returns_running_false_on_bad_json(self):
        resp = MagicMock()
        resp.read.return_value = b"not-json"
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=resp):
            running, names = router._ollama_installed_models()
        self.assertFalse(running)

    def test_filters_empty_names(self):
        import json
        import urllib.request
        payload = json.dumps({"models": [{"name": "llama3"}, {"name": ""}]}).encode()
        resp = MagicMock()
        resp.read.return_value = payload
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch.object(urllib.request, "urlopen", return_value=resp):
            _, names = router._ollama_installed_models()
        self.assertNotIn("", names)


# ---------------------------------------------------------------------------
# recommend — return shape
# ---------------------------------------------------------------------------

class TestRecommendShape(_RouterBase):
    def test_returns_dict(self):
        self.assertIsInstance(self._recommend(), dict)

    def test_has_all_required_keys(self):
        result = self._recommend()
        for key in ("tier", "tier_reasons", "models", "top_pick",
                    "ollama_running", "installed", "cached_until"):
            self.assertIn(key, result)

    def test_models_is_list(self):
        self.assertIsInstance(self._recommend()["models"], list)

    def test_installed_is_list(self):
        self.assertIsInstance(self._recommend()["installed"], list)


# ---------------------------------------------------------------------------
# recommend — tier / models
# ---------------------------------------------------------------------------

class TestRecommendTier(_RouterBase):
    def test_tier_from_hw_profile(self):
        result = self._recommend(tier="workstation")
        self.assertEqual(result["tier"], "workstation")

    def test_tier_reasons_from_hw_profile(self):
        result = self._recommend(tier_reasons=["16GB RAM"])
        self.assertEqual(result["tier_reasons"], ["16GB RAM"])

    def test_models_match_tier(self):
        result = self._recommend(tier="server")
        expected_names = {m["name"] for m in router._TIER_MODELS["server"]}
        returned_names = {m["name"] for m in result["models"]}
        self.assertEqual(returned_names, expected_names)

    def test_unknown_tier_falls_back_to_netbook(self):
        result = self._recommend(tier="unknown_tier")
        expected_names = {m["name"] for m in router._TIER_MODELS["netbook"]}
        returned_names = {m["name"] for m in result["models"]}
        self.assertEqual(returned_names, expected_names)

    def test_profile_exception_gives_unknown_tier(self):
        result = self._recommend(profile_raises=True)
        self.assertEqual(result["tier"], "unknown")

    def test_profile_exception_falls_back_to_netbook_models(self):
        result = self._recommend(profile_raises=True)
        expected_names = {m["name"] for m in router._TIER_MODELS["netbook"]}
        returned_names = {m["name"] for m in result["models"]}
        self.assertEqual(returned_names, expected_names)


# ---------------------------------------------------------------------------
# recommend — Ollama / installed
# ---------------------------------------------------------------------------

class TestRecommendOllama(_RouterBase):
    def test_ollama_running_flag_true(self):
        result = self._recommend(ollama_running=True)
        self.assertTrue(result["ollama_running"])

    def test_ollama_running_flag_false(self):
        result = self._recommend(ollama_running=False)
        self.assertFalse(result["ollama_running"])

    def test_installed_list_in_result(self):
        result = self._recommend(ollama_running=True, installed=["llama3"])
        self.assertIn("llama3", result["installed"])

    def test_installed_flag_set_on_matching_model(self):
        name = router._TIER_MODELS["netbook"][0]["name"]
        result = self._recommend(tier="netbook", ollama_running=True, installed=[name])
        model = next(m for m in result["models"] if m["name"] == name)
        self.assertTrue(model["installed"])

    def test_installed_flag_false_for_non_installed(self):
        result = self._recommend(tier="netbook", ollama_running=False, installed=[])
        for m in result["models"]:
            self.assertFalse(m["installed"])


# ---------------------------------------------------------------------------
# recommend — top_pick
# ---------------------------------------------------------------------------

class TestRecommendTopPick(_RouterBase):
    def test_top_pick_is_priority_one_when_nothing_installed(self):
        result = self._recommend(tier="netbook", installed=[])
        priority_one = min(router._TIER_MODELS["netbook"], key=lambda x: x["priority"])
        self.assertEqual(result["top_pick"], priority_one["name"])

    def test_top_pick_prefers_installed_model(self):
        # Install the priority-2 model only → it should be top_pick
        p2_name = None
        for m in sorted(router._TIER_MODELS["netbook"], key=lambda x: x["priority"]):
            if m["priority"] == 2:
                p2_name = m["name"]
                break
        if p2_name is None:
            self.skipTest("No priority-2 model in netbook tier")
        result = self._recommend(tier="netbook", installed=[p2_name])
        self.assertEqual(result["top_pick"], p2_name)


# ---------------------------------------------------------------------------
# recommend — cache
# ---------------------------------------------------------------------------

class TestRecommendCache(_RouterBase):
    def test_second_call_returns_cached(self):
        _fake_hw_profile.profile = MagicMock(return_value={
            "tier": "netbook", "tier_reasons": []})
        with patch.object(router, "_ollama_installed_models", return_value=(False, [])):
            r1 = router.recommend("/tmp/proj")
            r2 = router.recommend("/tmp/proj")
        # profile called only once if cache hit
        self.assertEqual(_fake_hw_profile.profile.call_count, 1)
        self.assertEqual(r1["tier"], r2["tier"])

    def test_cached_until_is_in_future(self):
        import time
        result = self._recommend()
        self.assertGreater(result["cached_until"], time.time())


# ---------------------------------------------------------------------------
# RouterExtraTest — additional coverage
# ---------------------------------------------------------------------------

class RouterExtraTest(unittest.TestCase):
    def test_tier_models_is_dict(self):
        self.assertIsInstance(router._TIER_MODELS, dict)

    def test_netbook_tier_present(self):
        self.assertIn("netbook", router._TIER_MODELS)

    def test_workstation_tier_present(self):
        self.assertIn("workstation", router._TIER_MODELS)

    def test_server_tier_present(self):
        self.assertIn("server", router._TIER_MODELS)

    def test_netbook_models_non_empty(self):
        self.assertGreater(len(router._TIER_MODELS["netbook"]), 0)

    def test_model_priority_is_int(self):
        for tier, models in router._TIER_MODELS.items():
            for m in models:
                self.assertIsInstance(m["priority"], int,
                                      f"{tier}/{m['name']} priority not int")


if __name__ == "__main__":
    unittest.main()
