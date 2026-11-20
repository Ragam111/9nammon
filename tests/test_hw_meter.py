"""Unit tests for app/hw_meter.py — hardware metrics snapshot.

snapshot() does lazy imports inside the function:
  from sysmanager.monitor import collect as _collect
  from app import hw_profile

Both are overridden per-test via sys.modules injection in setUp/tearDown,
so the real hardware drivers and profile logic are never touched.
"""
import sys
import types
import unittest
from unittest.mock import MagicMock

GB = 1_073_741_824  # 1 GiB, matches hw_meter.GB constant

# Fake module objects — attrs set per-test via setUp.
_fake_sysmanager = types.ModuleType("sysmanager")
_fake_monitor = types.ModuleType("sysmanager.monitor")
_fake_sysmanager.monitor = _fake_monitor
_fake_hw_profile = types.ModuleType("app.hw_profile")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_snap(*, cpu_pct=25.0, per_core=None, freq_mhz=2400.0,
               logical_cores=4, load_avg=1.5,
               ram_total=8 * GB, ram_used=4 * GB, ram_pct=50.0):
    snap = MagicMock()
    snap.cpu.percent = cpu_pct
    snap.cpu.per_core = per_core if per_core is not None else [25.0, 30.0, 20.0, 25.0]
    snap.cpu.freq_mhz = freq_mhz
    snap.cpu.logical_cores = logical_cores
    snap.cpu.load_avg_1m = load_avg
    snap.memory.total = ram_total
    snap.memory.used = ram_used
    snap.memory.percent = ram_pct
    return snap


_DEFAULT_PROFILE = {
    "tier": "mid",
    "tier_reasons": ["8GB RAM"],
    "recommended_config": {"PREFERRED_MODEL": "llama3"},
}


# ---------------------------------------------------------------------------
# base class — injects/restores sys.modules per test so we don't pollute the
# suite (test_analyzer.py already holds the real sysmanager.monitor)
# ---------------------------------------------------------------------------

class _HwMeterBase(unittest.TestCase):
    def setUp(self):
        import app as _pkg
        self._saved = {
            "sysmanager": sys.modules.get("sysmanager"),
            "sysmanager.monitor": sys.modules.get("sysmanager.monitor"),
            "app.hw_profile": sys.modules.get("app.hw_profile"),
            "_pkg_attr": getattr(_pkg, "hw_profile", None),
        }
        sys.modules["sysmanager"] = _fake_sysmanager
        sys.modules["sysmanager.monitor"] = _fake_monitor
        sys.modules["app.hw_profile"] = _fake_hw_profile
        _pkg.hw_profile = _fake_hw_profile

    def tearDown(self):
        import app as _pkg
        for key in ("sysmanager", "sysmanager.monitor", "app.hw_profile"):
            orig = self._saved[key]
            if orig is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = orig
        orig_attr = self._saved["_pkg_attr"]
        if orig_attr is None:
            if hasattr(_pkg, "hw_profile"):
                try:
                    delattr(_pkg, "hw_profile")
                except AttributeError:
                    pass
        else:
            _pkg.hw_profile = orig_attr

    def _call(self, snap=None, profile=None, raises=False):
        _fake_monitor.collect = MagicMock(return_value=snap or _make_snap())
        if raises:
            _fake_hw_profile.profile = MagicMock(side_effect=RuntimeError("fail"))
        else:
            _fake_hw_profile.profile = MagicMock(return_value=profile or _DEFAULT_PROFILE)
        from app.hw_meter import snapshot
        return snapshot("/tmp/fake_root")


# ---------------------------------------------------------------------------
# shape
# ---------------------------------------------------------------------------

class TestSnapshotShape(_HwMeterBase):
    def test_returns_dict(self):
        self.assertIsInstance(self._call(), dict)

    def test_has_all_expected_keys(self):
        result = self._call()
        for key in ("cpu_pct", "cpu_per_core", "cpu_freq_mhz", "logical_cores",
                    "load_avg_1m", "ram_pct", "ram_used_gb", "ram_total_gb",
                    "tier", "tier_reasons", "recommended_model"):
            self.assertIn(key, result)

    def test_cpu_per_core_is_list(self):
        self.assertIsInstance(self._call()["cpu_per_core"], list)


# ---------------------------------------------------------------------------
# CPU fields
# ---------------------------------------------------------------------------

class TestSnapshotCpuFields(_HwMeterBase):
    def test_cpu_pct_rounded_one_decimal(self):
        result = self._call(snap=_make_snap(cpu_pct=33.3456))
        self.assertEqual(result["cpu_pct"], round(33.3456, 1))

    def test_cpu_freq_mhz_rounded_zero_decimal(self):
        result = self._call(snap=_make_snap(freq_mhz=2399.7))
        self.assertEqual(result["cpu_freq_mhz"], round(2399.7, 0))

    def test_cpu_freq_mhz_none_when_zero(self):
        self.assertIsNone(self._call(snap=_make_snap(freq_mhz=0))["cpu_freq_mhz"])

    def test_cpu_freq_mhz_none_when_none(self):
        self.assertIsNone(self._call(snap=_make_snap(freq_mhz=None))["cpu_freq_mhz"])

    def test_load_avg_rounded_two_decimals(self):
        result = self._call(snap=_make_snap(load_avg=1.2345))
        self.assertEqual(result["load_avg_1m"], round(1.2345, 2))

    def test_load_avg_none_when_zero(self):
        self.assertIsNone(self._call(snap=_make_snap(load_avg=0))["load_avg_1m"])

    def test_load_avg_none_when_none(self):
        self.assertIsNone(self._call(snap=_make_snap(load_avg=None))["load_avg_1m"])

    def test_cpu_per_core_values_rounded_one_decimal(self):
        result = self._call(snap=_make_snap(per_core=[10.123, 20.456]))
        self.assertEqual(result["cpu_per_core"], [round(10.123, 1), round(20.456, 1)])

    def test_logical_cores_passthrough(self):
        self.assertEqual(self._call(snap=_make_snap(logical_cores=8))["logical_cores"], 8)


# ---------------------------------------------------------------------------
# RAM fields
# ---------------------------------------------------------------------------

class TestSnapshotRamFields(_HwMeterBase):
    def test_ram_pct_rounded_one_decimal(self):
        result = self._call(snap=_make_snap(ram_pct=72.189))
        self.assertEqual(result["ram_pct"], round(72.189, 1))

    def test_ram_total_gb_in_gib(self):
        result = self._call(snap=_make_snap(ram_total=16 * GB))
        self.assertAlmostEqual(result["ram_total_gb"], 16.0, places=1)

    def test_ram_used_gb_in_gib(self):
        result = self._call(snap=_make_snap(ram_used=4 * GB))
        self.assertAlmostEqual(result["ram_used_gb"], 4.0, places=1)


# ---------------------------------------------------------------------------
# tier / profile fields
# ---------------------------------------------------------------------------

class TestSnapshotTierFields(_HwMeterBase):
    def test_tier_from_profile(self):
        result = self._call(profile={**_DEFAULT_PROFILE, "tier": "netbook"})
        self.assertEqual(result["tier"], "netbook")

    def test_tier_reasons_from_profile(self):
        result = self._call(profile={**_DEFAULT_PROFILE, "tier_reasons": ["low RAM"]})
        self.assertEqual(result["tier_reasons"], ["low RAM"])

    def test_recommended_model_from_profile(self):
        p = {**_DEFAULT_PROFILE, "recommended_config": {"PREFERRED_MODEL": "phi3"}}
        self.assertEqual(self._call(profile=p)["recommended_model"], "phi3")

    def test_recommended_model_empty_when_no_config_key(self):
        p = {**_DEFAULT_PROFILE, "recommended_config": {}}
        self.assertEqual(self._call(profile=p)["recommended_model"], "")

    def test_recommended_model_empty_when_no_recommended_config(self):
        p = {"tier": "mid", "tier_reasons": [], "recommended_config": None}
        self.assertEqual(self._call(profile=p)["recommended_model"], "")


# ---------------------------------------------------------------------------
# hw_profile exception fallback
# ---------------------------------------------------------------------------

class TestSnapshotProfileException(_HwMeterBase):
    def test_tier_unknown_on_profile_error(self):
        self.assertEqual(self._call(raises=True)["tier"], "unknown")

    def test_tier_reasons_empty_on_profile_error(self):
        self.assertEqual(self._call(raises=True)["tier_reasons"], [])

    def test_recommended_model_empty_on_profile_error(self):
        self.assertEqual(self._call(raises=True)["recommended_model"], "")


class HwMeterExtraTest(_HwMeterBase):
    def test_snapshot_cpu_pct_non_negative(self):
        result = self._call(snap=_make_snap(cpu_pct=25.0))
        self.assertGreaterEqual(result["cpu_pct"], 0)

    def test_snapshot_ram_pct_in_range(self):
        result = self._call(snap=_make_snap(ram_pct=42.0))
        self.assertGreaterEqual(result["ram_pct"], 0)
        self.assertLessEqual(result["ram_pct"], 100)

    def test_snapshot_logical_cores_positive(self):
        result = self._call(snap=_make_snap(logical_cores=8))
        self.assertGreater(result["logical_cores"], 0)

    def test_snapshot_tier_reasons_is_list(self):
        result = self._call()
        self.assertIsInstance(result["tier_reasons"], list)

    def test_snapshot_per_core_len_matches_logical_cores(self):
        result = self._call(snap=_make_snap(logical_cores=4,
                                            per_core=[10.0, 20.0, 15.0, 25.0]))
        self.assertEqual(len(result["cpu_per_core"]), 4)

    def test_snapshot_recommended_model_is_string(self):
        result = self._call()
        self.assertIsInstance(result["recommended_model"], str)
