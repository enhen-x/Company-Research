"""Tests for Phase 2 speed-track changes in the Tushare collector:

  * Step 2.1 — configurable rate limit via TUSHARE_RATE_DELAY
  * Step 2.2 — §13 warnings read from _store (no redundant re-fetch)
  * Step 2.3 — TTL cache for heavy endpoints (_cached_call)

These are NEW tests; existing tests remain untouched.
"""

import tempfile
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tushare_collector import TushareClient, rate_limit


def _make_client():
    """Create a TushareClient with mocked tushare module and isolated cache."""
    with patch("tushare_collector.ts") as mock_ts:
        mock_ts.pro_api.return_value = MagicMock()
        client = TushareClient("test_token")
    client._cache_dir = tempfile.mkdtemp(prefix="collector_cache_test_")
    return client


# ============================================================
# Step 2.1 — configurable rate limit
# ============================================================

class TestConfigurableRateLimit:
    def test_zero_delay_skips_sleep(self, monkeypatch):
        """TUSHARE_RATE_DELAY=0 → no time.sleep call, returns immediately."""
        monkeypatch.setenv("TUSHARE_RATE_DELAY", "0")

        @rate_limit
        def dummy():
            return 42

        with patch("tushare_collector.time.sleep") as mock_sleep:
            result = dummy()

        assert result == 42
        mock_sleep.assert_not_called()

    def test_default_delay_sleeps_half_second(self, monkeypatch):
        """Unset env → default 0.5s path calls time.sleep(0.5)."""
        monkeypatch.delenv("TUSHARE_RATE_DELAY", raising=False)

        @rate_limit
        def dummy():
            return "ok"

        with patch("tushare_collector.time.sleep") as mock_sleep:
            result = dummy()

        assert result == "ok"
        mock_sleep.assert_called_once_with(0.5)

    def test_custom_delay_value(self, monkeypatch):
        """A custom positive delay is honored."""
        monkeypatch.setenv("TUSHARE_RATE_DELAY", "0.1")

        @rate_limit
        def dummy():
            return None

        with patch("tushare_collector.time.sleep") as mock_sleep:
            dummy()

        mock_sleep.assert_called_once_with(0.1)

    def test_invalid_delay_falls_back_to_default(self, monkeypatch):
        """A non-numeric env value falls back to 0.5 (no crash)."""
        monkeypatch.setenv("TUSHARE_RATE_DELAY", "not-a-number")

        @rate_limit
        def dummy():
            return None

        with patch("tushare_collector.time.sleep") as mock_sleep:
            dummy()

        mock_sleep.assert_called_once_with(0.5)


# ============================================================
# Step 2.2 — §13 warnings read from _store (no re-fetch)
# ============================================================

class TestSection13NoRefetch:
    """Full A-share assemble should read income/balance/cashflow/audit from
    _store instead of re-fetching them for the §13 warnings block."""

    def _run(self, mock_safe_call):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(side_effect=mock_safe_call)
            result = client.assemble_data_pack("600887.SH")
        return client, result

    @staticmethod
    def _standard_mock():
        """Route mock responses by endpoint name (single annual row each)."""
        def mock_safe_call(api_name, **kwargs):
            if api_name == "income":
                return pd.DataFrame([{
                    "ts_code": "600887.SH", "end_date": "20231231",
                    "revenue": 100000, "n_income_attr_p": 50000,
                }])
            if api_name == "balancesheet":
                return pd.DataFrame([{
                    "ts_code": "600887.SH", "end_date": "20231231",
                    "total_assets": 1000000, "total_liab": 800000,
                    "goodwill": 10000,
                }])
            if api_name == "cashflow":
                return pd.DataFrame([{
                    "ts_code": "600887.SH", "end_date": "20231231",
                    "n_cashflow_act": 30000,
                }])
            if api_name == "fina_audit":
                return pd.DataFrame([{
                    "ts_code": "600887.SH", "end_date": "20231231",
                    "audit_agency": "普华永道", "audit_result": "标准无保留意见",
                }])
            return pd.DataFrame()
        return mock_safe_call

    def test_endpoint_call_counts(self):
        """After the §13 refactor, each core statement endpoint is called only
        the minimum number of times (no redundant §13 re-fetch)."""
        client, _ = self._run(self._standard_mock())

        counts = {}
        for call in client._safe_call.call_args_list:
            name = call.args[0] if call.args else call.kwargs.get("api_name")
            counts[name] = counts.get(name, 0) + 1

        # income: consolidated (report_type=1) + parent (report_type=6) = 2
        assert counts.get("income") == 2
        # balancesheet: consolidated + parent = 2 (§13 no longer re-fetches)
        assert counts.get("balancesheet") == 2
        # cashflow: single fetch (§13 no longer re-fetches)
        assert counts.get("cashflow") == 1
        # fina_audit: single fetch in get_audit (§13 reads from _store)
        assert counts.get("fina_audit") == 1

    def test_store_populated_for_section13(self):
        """The §13 warnings source (_store) is populated after assembly."""
        client, _ = self._run(self._standard_mock())
        assert client._store.get("income") is not None
        assert client._store.get("balance_sheet") is not None
        assert client._store.get("cashflow") is not None
        assert client._store.get("fina_audit") is not None

    def test_leverage_risk_still_fires_from_store(self):
        """High debt ratio (from stored balance sheet) → LEVERAGE_RISK."""
        _, result = self._run(self._standard_mock())
        assert "LEVERAGE_RISK" in result
        assert "13.1 脚本自动检测" in result

    def test_audit_risk_still_fires_from_store(self):
        """Non-standard audit opinion (from stored fina_audit) → AUDIT_RISK."""
        def mock_safe_call(api_name, **kwargs):
            base = TestSection13NoRefetch._standard_mock()(api_name, **kwargs)
            if api_name == "fina_audit":
                return pd.DataFrame([{
                    "ts_code": "600887.SH", "end_date": "20231231",
                    "audit_agency": "某会计所", "audit_result": "保留意见",
                }])
            return base
        _, result = self._run(mock_safe_call)
        assert "AUDIT_RISK" in result

    def test_missing_data_still_fires(self):
        """All-empty responses → DATA_MISSING warnings (store empty)."""
        client, result = self._run(lambda api_name, **kw: pd.DataFrame())
        assert "DATA_MISSING" in result


# ============================================================
# Step 2.3 — TTL cache for heavy endpoints (_cached_call)
# ============================================================

class TestCachedCall:
    def _income_df(self):
        return pd.DataFrame([{
            "ts_code": "600887.SH", "end_date": "20231231", "revenue": 1,
        }])

    def test_cache_hit_skips_safe_call(self):
        """A second identical cacheable call is served from cache."""
        client = _make_client()
        df = self._income_df()
        client._safe_call = MagicMock(return_value=df)

        r1 = client._cached_call("income", ts_code="600887.SH", report_type="1")
        r2 = client._cached_call("income", ts_code="600887.SH", report_type="1")

        assert client._safe_call.call_count == 1  # miss then hit
        assert r1.equals(df)
        assert r2.reset_index(drop=True).equals(df.reset_index(drop=True))

    def test_kwargs_differentiation(self):
        """Different kwargs (report_type 1 vs 6) → separate cache entries."""
        client = _make_client()
        client._safe_call = MagicMock(return_value=self._income_df())

        client._cached_call("income", ts_code="600887.SH", report_type="1")
        client._cached_call("income", ts_code="600887.SH", report_type="6")

        assert client._safe_call.call_count == 2

    def test_non_cacheable_endpoint_passthrough(self):
        """daily is never cached → _safe_call every time."""
        client = _make_client()
        client._safe_call = MagicMock(return_value=self._income_df())

        client._cached_call("daily", ts_code="600887.SH")
        client._cached_call("daily", ts_code="600887.SH")

        assert client._safe_call.call_count == 2

    def test_cache_disabled_bypass(self):
        """_cache_enabled=False → passthrough to _safe_call every call."""
        client = _make_client()
        client._cache_enabled = False
        client._safe_call = MagicMock(return_value=self._income_df())

        client._cached_call("income", ts_code="600887.SH", report_type="1")
        client._cached_call("income", ts_code="600887.SH", report_type="1")

        assert client._safe_call.call_count == 2

    def test_empty_df_not_cached(self):
        """An empty result is not cached → next call hits _safe_call again."""
        client = _make_client()
        client._safe_call = MagicMock(return_value=pd.DataFrame())

        client._cached_call("income", ts_code="600887.SH", report_type="1")
        client._cached_call("income", ts_code="600887.SH", report_type="1")

        assert client._safe_call.call_count == 2

    def test_ttl_expiry_refetches(self):
        """When the TTL has expired, a re-fetch occurs."""
        client = _make_client()
        client._safe_call = MagicMock(return_value=self._income_df())

        # First call populates the cache.
        client._cached_call("income", ts_code="600887.SH", report_type="1")
        assert client._safe_call.call_count == 1

        # Simulate the cached entry aging past the financial TTL (168h).
        real_time = __import__("time").time
        future = real_time() + 200 * 3600
        with patch("cache_utils.time.time", return_value=future):
            client._cached_call("income", ts_code="600887.SH", report_type="1")

        assert client._safe_call.call_count == 2

    def test_cache_dir_override_respected(self):
        """Overriding _cache_dir after construction re-roots the TTL cache."""
        client = _make_client()
        cache = client._get_ttl_cache()
        assert client._cache_dir in cache.cache_dir

        new_dir = tempfile.mkdtemp(prefix="collector_cache_test2_")
        client._cache_dir = new_dir
        cache2 = client._get_ttl_cache()
        assert new_dir in cache2.cache_dir

    def test_invalidate_prefix_via_cache_refresh(self):
        """invalidate_prefix drops entries for a given ts_code prefix."""
        client = _make_client()
        client._safe_call = MagicMock(return_value=self._income_df())

        client._cached_call("income", ts_code="600887.SH", report_type="1")
        assert client._safe_call.call_count == 1

        client._get_ttl_cache().invalidate_prefix("collector_600887.SH_")
        client._cached_call("income", ts_code="600887.SH", report_type="1")
        assert client._safe_call.call_count == 2  # cache was invalidated
