"""Tests for cache_utils.ScreenerCache (extracted from screener_core)."""

from unittest.mock import patch

import pandas as pd

from cache_utils import ScreenerCache


class TestScreenerCacheRoundtrip:
    def test_put_get_roundtrip(self, tmp_path):
        cache = ScreenerCache(str(tmp_path / "cache"))
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        cache.put("k1", df)
        got = cache.get("k1", ttl_seconds=3600)
        assert got is not None
        assert got.reset_index(drop=True).equals(df.reset_index(drop=True))

    def test_get_miss_returns_none(self, tmp_path):
        cache = ScreenerCache(str(tmp_path / "cache"))
        assert cache.get("nope", ttl_seconds=3600) is None

    def test_ttl_expiry(self, tmp_path):
        cache = ScreenerCache(str(tmp_path / "cache"))
        df = pd.DataFrame({"a": [1]})
        cache.put("k", df)
        # Within TTL: hit.
        assert cache.get("k", ttl_seconds=3600) is not None
        # Past TTL: miss (simulate future clock).
        import time as _time
        future = _time.time() + 10000
        with patch("cache_utils.time.time", return_value=future):
            assert cache.get("k", ttl_seconds=3600) is None

    def test_invalidate_single_key(self, tmp_path):
        cache = ScreenerCache(str(tmp_path / "cache"))
        cache.put("k", pd.DataFrame({"a": [1]}))
        assert cache.get("k", ttl_seconds=3600) is not None
        cache.invalidate("k")
        assert cache.get("k", ttl_seconds=3600) is None

    def test_invalidate_prefix(self, tmp_path):
        cache = ScreenerCache(str(tmp_path / "cache"))
        cache.put("collector_600887.SH_income_x", pd.DataFrame({"a": [1]}))
        cache.put("collector_600887.SH_cashflow_y", pd.DataFrame({"a": [2]}))
        cache.put("collector_000858.SZ_income_z", pd.DataFrame({"a": [3]}))

        cache.invalidate_prefix("collector_600887.SH_")

        assert cache.get("collector_600887.SH_income_x", ttl_seconds=3600) is None
        assert cache.get("collector_600887.SH_cashflow_y", ttl_seconds=3600) is None
        # Other stock's entry survives.
        assert cache.get("collector_000858.SZ_income_z", ttl_seconds=3600) is not None

    def test_clear(self, tmp_path):
        cache = ScreenerCache(str(tmp_path / "cache"))
        cache.put("a", pd.DataFrame({"x": [1]}))
        cache.put("b", pd.DataFrame({"x": [2]}))
        cache.clear()
        assert cache.get("a", ttl_seconds=3600) is None
        assert cache.get("b", ttl_seconds=3600) is None
