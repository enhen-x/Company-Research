"""Tests for TushareClient class — init, rate limiting, retry, data methods."""

import json
import os
import tempfile
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pandas as pd
import pytest

from tushare_collector import TushareClient, WarningsCollector, rate_limit

MOCK_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "mock_tushare_responses")


def _load_mock(filename: str) -> pd.DataFrame:
    """Load a mock fixture as DataFrame."""
    with open(os.path.join(MOCK_DIR, filename)) as f:
        data = json.load(f)
    if isinstance(data, list):
        return pd.DataFrame(data)
    return pd.DataFrame([data])


def _make_client():
    """Create a TushareClient with mocked tushare module."""
    with patch("tushare_collector.ts") as mock_ts:
        mock_ts.pro_api.return_value = MagicMock()
        client = TushareClient("test_token")
    # Isolate tests from production cache and from each other
    client._cache_dir = tempfile.mkdtemp(prefix="tushare_test_cache_")
    return client


class TestRateLimit:
    def test_enforces_delay(self):
        """rate_limit decorator should sleep ~0.5s."""
        call_count = 0

        @rate_limit
        def dummy():
            nonlocal call_count
            call_count += 1
            return call_count

        start = time.time()
        dummy()
        elapsed = time.time() - start
        assert elapsed >= 0.45  # allow slight tolerance
        assert call_count == 1


class TestTushareClientInit:
    @patch("tushare_collector.ts")
    def test_init_sets_token(self, mock_ts):
        mock_ts.pro_api.return_value = MagicMock()
        client = TushareClient("test_token")
        mock_ts.set_token.assert_called_once_with("test_token")
        mock_ts.pro_api.assert_called_once_with(timeout=30)
        assert client.token == "test_token"


class TestCachedBasicCall:
    def test_cached_basic_call_uses_cache(self, tmp_path):
        """Second call should read from file cache, not API."""
        client = _make_client()
        client._cache_dir = str(tmp_path)
        expected_df = pd.DataFrame({"ts_code": ["600887.SH"], "name": ["伊利股份"]})
        client._safe_call = MagicMock(return_value=expected_df)

        with patch("tushare_collector.time.sleep"):
            result1 = client._cached_basic_call("stock_basic", ts_code="600887.SH")
            result2 = client._cached_basic_call("stock_basic", ts_code="600887.SH")

        assert client._safe_call.call_count == 1
        assert result1.equals(expected_df)
        assert list(result2["name"]) == ["伊利股份"]

    def test_cached_basic_call_expired(self, tmp_path):
        """Stale cache (>7 days) should trigger fresh API call."""
        client = _make_client()
        client._cache_dir = str(tmp_path)
        expected_df = pd.DataFrame({"ts_code": ["600887.SH"], "name": ["伊利股份"]})
        client._safe_call = MagicMock(return_value=expected_df)

        with patch("tushare_collector.time.sleep"):
            result1 = client._cached_basic_call("stock_basic", ts_code="600887.SH")

        # Age the cache file beyond TTL
        cache_file = os.path.join(str(tmp_path), "stock_basic_600887.SH.json")
        old_time = time.time() - 8 * 86400
        os.utime(cache_file, (old_time, old_time))

        with patch("tushare_collector.time.sleep"):
            result2 = client._cached_basic_call("stock_basic", ts_code="600887.SH")

        assert client._safe_call.call_count == 2
        assert list(result2["name"]) == ["伊利股份"]

    def test_cached_basic_call_empty_not_cached(self, tmp_path):
        """Empty API results should NOT be written to cache."""
        client = _make_client()
        client._cache_dir = str(tmp_path)
        client._safe_call = MagicMock(return_value=pd.DataFrame())

        with patch("tushare_collector.time.sleep"):
            client._cached_basic_call("stock_basic", ts_code="999999.SH")

        cache_file = os.path.join(str(tmp_path), "stock_basic_999999.SH.json")
        assert not os.path.exists(cache_file)


class TestCachedUsDaily:
    """Tests for _cached_us_daily bulk cache with same-day TTL."""

    def test_first_call_fetches_and_caches(self, tmp_path):
        """First call should hit API and write Parquet cache file."""
        client = _make_client()
        client._cache_dir = str(tmp_path)
        bulk_df = pd.DataFrame([
            {"ts_code": "AAPL", "trade_date": "20241231", "close": 254.49,
             "pe": 32.5, "pb": 48.2, "total_mv": 3850000},
            {"ts_code": "NVDA", "trade_date": "20241231", "close": 130.50,
             "pe": 60.0, "pb": 30.0, "total_mv": 3200000},
        ])
        client._safe_call = MagicMock(return_value=bulk_df)

        result = client._cached_us_daily(ts_code="AAPL")

        client._safe_call.assert_called_once()
        assert os.path.exists(os.path.join(str(tmp_path), "us_daily_all.parquet"))
        assert len(result) == 1
        assert result.iloc[0]["ts_code"] == "AAPL"

    def test_second_call_uses_cache(self, tmp_path):
        """Same-day second call should read from cache, not API."""
        client = _make_client()
        client._cache_dir = str(tmp_path)
        bulk_df = pd.DataFrame([
            {"ts_code": "AAPL", "trade_date": "20241231", "close": 254.49,
             "pe": 32.5, "pb": 48.2, "total_mv": 3850000},
            {"ts_code": "NVDA", "trade_date": "20241231", "close": 130.50,
             "pe": 60.0, "pb": 30.0, "total_mv": 3200000},
        ])
        client._safe_call = MagicMock(return_value=bulk_df)

        client._cached_us_daily(ts_code="AAPL")
        result = client._cached_us_daily(ts_code="NVDA")

        assert client._safe_call.call_count == 1  # Only one API call
        assert len(result) == 1
        assert result.iloc[0]["ts_code"] == "NVDA"

    def test_filter_by_ts_code(self, tmp_path):
        """Filtering by ts_code should return correct subset."""
        client = _make_client()
        client._cache_dir = str(tmp_path)
        bulk_df = pd.DataFrame([
            {"ts_code": "AAPL", "trade_date": "20241231", "close": 254.49},
            {"ts_code": "NVDA", "trade_date": "20241231", "close": 130.50},
            {"ts_code": "MSFT", "trade_date": "20241231", "close": 420.00},
        ])
        client._safe_call = MagicMock(return_value=bulk_df)

        result = client._cached_us_daily(ts_code="MSFT")
        assert len(result) == 1
        assert result.iloc[0]["close"] == 420.00

    def test_no_filter_returns_all(self, tmp_path):
        """Calling without ts_code should return all rows."""
        client = _make_client()
        client._cache_dir = str(tmp_path)
        bulk_df = pd.DataFrame([
            {"ts_code": "AAPL", "close": 254.49},
            {"ts_code": "NVDA", "close": 130.50},
        ])
        client._safe_call = MagicMock(return_value=bulk_df)

        result = client._cached_us_daily()
        assert len(result) == 2

    def test_stale_cache_triggers_fresh_fetch(self, tmp_path):
        """Cache from yesterday should trigger a new API call."""
        client = _make_client()
        client._cache_dir = str(tmp_path)
        bulk_df = pd.DataFrame([
            {"ts_code": "AAPL", "trade_date": "20241231", "close": 254.49,
             "pe": 32.5, "pb": 48.2, "total_mv": 3850000},
        ])
        client._safe_call = MagicMock(return_value=bulk_df)

        # First call populates cache
        client._cached_us_daily(ts_code="AAPL")

        # Age the cache file to yesterday
        cache_file = os.path.join(str(tmp_path), "us_daily_all.parquet")
        yesterday = time.time() - 86400
        os.utime(cache_file, (yesterday, yesterday))

        # Second call should hit API again
        client._cached_us_daily(ts_code="AAPL")
        assert client._safe_call.call_count == 2

    def test_empty_result_not_cached(self, tmp_path):
        """Empty API result should NOT write cache file."""
        client = _make_client()
        client._cache_dir = str(tmp_path)
        client._safe_call = MagicMock(return_value=pd.DataFrame())

        result = client._cached_us_daily(ts_code="AAPL")

        cache_file = os.path.join(str(tmp_path), "us_daily_all.parquet")
        assert not os.path.exists(cache_file)
        assert result.empty


class TestSafeCall:
    @patch("tushare_collector.ts")
    def test_successful_call(self, mock_ts):
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        expected_df = pd.DataFrame({"col": [1, 2, 3]})
        mock_pro.stock_basic.return_value = expected_df

        client = TushareClient("token")
        # Bypass rate_limit sleep for testing speed
        with patch("tushare_collector.time.sleep"):
            result = client._safe_call("stock_basic", ts_code="600887.SH")

        assert result.equals(expected_df)
        mock_pro.stock_basic.assert_called_once_with(ts_code="600887.SH")

    @patch("tushare_collector.ts")
    def test_retry_on_failure(self, mock_ts):
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        expected_df = pd.DataFrame({"col": [1]})
        # Fail twice, succeed on third
        mock_pro.income.side_effect = [
            Exception("timeout"),
            Exception("timeout"),
            expected_df,
        ]

        client = TushareClient("token")
        with patch("tushare_collector.time.sleep"):
            result = client._safe_call("income", ts_code="600887.SH")

        assert result.equals(expected_df)
        assert mock_pro.income.call_count == 3

    @patch("tushare_collector.ts")
    def test_raises_after_max_retries(self, mock_ts):
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        mock_pro.daily.side_effect = Exception("permanent failure")

        client = TushareClient("token")
        with patch("tushare_collector.time.sleep"):
            with pytest.raises(RuntimeError, match="failed after 5 retries"):
                client._safe_call("daily", ts_code="600887.SH")

        assert mock_pro.daily.call_count == 5

    @patch("tushare_collector.ts")
    def test_connection_error_recreates_pro(self, mock_ts):
        """RemoteDisconnected-style errors should re-create the pro_api client."""
        mock_pro_old = MagicMock()
        mock_pro_new = MagicMock()
        expected_df = pd.DataFrame({"col": [1]})
        # First call fails with connection error, second succeeds on new client
        mock_pro_old.cashflow.side_effect = OSError("RemoteDisconnected")
        mock_pro_new.cashflow.return_value = expected_df
        mock_ts.pro_api.side_effect = [mock_pro_old, mock_pro_new]

        client = TushareClient("token")
        with patch("tushare_collector.time.sleep"):
            result = client._safe_call("cashflow", ts_code="600887.SH")

        assert result.equals(expected_df)
        # pro_api called twice: once in __init__, once for reconnect
        assert mock_ts.pro_api.call_count == 2
        mock_pro_old.cashflow.assert_called_once()
        mock_pro_new.cashflow.assert_called_once()


# --- Feature #14: get_basic_info ---

class TestGetBasicInfo:
    def test_basic_info_output(self):
        client = _make_client()
        mock_basic = _load_mock("stock_basic.json")
        mock_daily = _load_mock("daily_basic.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(side_effect=[mock_basic, mock_daily])
            result = client.get_basic_info("600887.SH")

        assert "## 1. 基本信息" in result
        assert "伊利股份" in result
        assert "600887.SH" in result
        assert "乳品" in result

    def test_empty_data(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_basic_info("600887.SH")
        assert "数据缺失" in result


# --- Feature #15: get_market_data ---

class TestGetMarketData:
    def test_52_week_range(self):
        client = _make_client()
        # Create mock daily data with known high/low
        mock_df = pd.DataFrame([
            {"ts_code": "600887.SH", "trade_date": "20241230", "open": 27, "high": 35.0, "low": 26.0, "close": 27.5, "vol": 100000, "amount": 275000},
            {"ts_code": "600887.SH", "trade_date": "20240701", "open": 30, "high": 32.0, "low": 22.0, "close": 30.0, "vol": 120000, "amount": 360000},
            {"ts_code": "600887.SH", "trade_date": "20240301", "open": 28, "high": 29.0, "low": 25.0, "close": 28.0, "vol": 110000, "amount": 308000},
        ])

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_market_data("600887.SH")

        assert "## 2. 市场行情" in result
        assert "35.00" in result  # 52-week high
        assert "22.00" in result  # 52-week low
        assert "27.50" in result  # latest close


# --- Feature #16: get_income ---

class TestGetIncome:
    def test_five_year_income(self):
        client = _make_client()
        mock_df = _load_mock("income.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_income("600887.SH")

        assert "## 3. 合并利润表" in result
        assert "2024" in result
        assert "2020" in result
        # Check amount conversion: 96886000000 -> 96,886.00
        assert "96,886.00" in result
        assert "百万元" in result

    def test_empty_income(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_income("600887.SH")
        assert "数据缺失" in result


# --- Feature #17: get_income_parent ---

class TestGetIncomeParent:
    def test_parent_income_uses_report_type_6(self):
        client = _make_client()
        mock_df = _load_mock("income.json")
        # Change report_type to "6" to simulate parent data
        mock_df["report_type"] = "6"

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_income_parent("600887.SH")

        assert "3P. 母公司利润表" in result
        # Verify _safe_call was called (report_type=6 is handled internally)
        client._safe_call.assert_called_once()


# --- Feature #18: get_balance_sheet ---

class TestGetBalanceSheet:
    def test_five_year_balance_sheet(self):
        client = _make_client()
        mock_df = _load_mock("balancesheet.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_balance_sheet("600887.SH")

        assert "## 4. 合并资产负债表" in result
        assert "合同负债" in result
        assert "短期借款" in result
        assert "长期借款" in result
        assert "百万元" in result

    def test_interest_bearing_debt_fields(self):
        client = _make_client()
        mock_df = _load_mock("balancesheet.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_balance_sheet("600887.SH")

        # Verify st_borr and lt_borr are present (interest-bearing debt)
        assert "短期借款" in result
        assert "长期借款" in result


# --- Feature #19: get_balance_sheet_parent ---

class TestGetBalanceSheetParent:
    def test_parent_balance_sheet(self):
        client = _make_client()
        mock_df = _load_mock("balancesheet.json")
        mock_df["report_type"] = "6"

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_balance_sheet_parent("600887.SH")

        assert "4P. 母公司资产负债表" in result
        assert "货币资金" in result
        assert "长期股权投资" in result


# --- Feature #20: get_cashflow ---

class TestGetCashflow:
    def test_fcf_calculation(self):
        client = _make_client()
        mock_df = _load_mock("cashflow.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_cashflow("600887.SH")

        assert "## 5. 现金流量表" in result
        assert "自由现金流" in result
        assert "FCF" in result
        # 2024: OCF=16850M, Capex(c_pay_acq_const_fiolta)=7850M, FCF=9000M = 9,000.00
        assert "9,000.00" in result

    def test_empty_cashflow(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_cashflow("600887.SH")
        assert "数据缺失" in result


# --- Feature #21: get_dividends ---

class TestGetDividends:
    def test_dividend_extraction(self):
        client = _make_client()
        mock_df = _load_mock("dividend.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_dividends("600887.SH")

        assert "## 6. 分红历史" in result
        assert "2024" in result
        assert "0.9700" in result  # cash_div_tax for 2024
        # Total dividend: 0.97 * 636363.64(万股) * 10000 = 6172727108 yuan = 6,172.73 million
        assert "6,172.73" in result

    def test_empty_dividends(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_dividends("600887.SH")
        assert "暂无分红" in result


# --- Feature #22: get_weekly_prices ---

class TestGetWeeklyPrices:
    def test_10_year_range(self):
        client = _make_client()
        mock_df = _load_mock("weekly.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_weekly_prices("600887.SH")

        assert "## 11. 十年周线行情" in result
        assert "10年最高" in result
        assert "10年最低" in result
        # 10yr high is 41.80 (from 2021 data)
        assert "41.80" in result
        # 10yr low is 15.20 (from 2015 data)
        assert "15.20" in result

    def test_annual_aggregation(self):
        client = _make_client()
        mock_df = _load_mock("weekly.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_weekly_prices("600887.SH")

        assert "年度行情汇总" in result
        # Should have multiple years
        assert "2024" in result
        assert "2015" in result


# --- Feature #23: get_fina_indicators ---

class TestGetFinaIndicators:
    def test_financial_indicators(self):
        client = _make_client()
        mock_df = _load_mock("fina_indicator.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_fina_indicators("600887.SH")

        assert "## 12. 关键财务指标" in result
        assert "ROE" in result
        assert "毛利率" in result
        assert "17.15" in result  # ROE 2024
        assert "29.22" in result  # gross margin 2024

    def test_empty_indicators(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_fina_indicators("600887.SH")
        assert "数据缺失" in result


# --- Feature #24: get_segments ---

class TestGetSegments:
    def test_segment_breakdown(self):
        client = _make_client()
        mock_df = _load_mock("fina_mainbz.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_segments("600887.SH")

        assert "## 9. 主营业务构成" in result
        assert "液体乳" in result
        assert "冷饮产品" in result

    def test_permission_error(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(side_effect=RuntimeError("no permission"))
            result = client.get_segments("600887.SH")
        assert "无权限" in result or "数据缺失" in result


# --- Feature #25: get_holders ---

class TestGetHolders:
    def test_top10_holders(self):
        client = _make_client()
        mock_df = _load_mock("top10_holders.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_holders("600887.SH")

        assert "## 7. 股东与治理" in result
        assert "呼和浩特投资" in result
        assert "9.05" in result  # hold ratio


# --- Feature #25: get_audit ---

class TestGetAudit:
    def test_audit_with_agency_and_fees(self):
        client = _make_client()
        mock_df = _load_mock("fina_audit.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_audit("600887.SH")

        assert "审计意见" in result
        assert "标准无保留意见" in result
        assert "安永华明" in result
        assert "1350.0" in result  # 13500000 / 10000 = 1350.0

    def test_audit_empty(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_audit("600887.SH")
        assert "审计数据缺失" in result


# --- Feature #28: assemble_data_pack ---

class TestAssembleDataPack:
    def test_all_section_headers_present(self):
        client = _make_client()
        # Mock all API calls to return empty DataFrames
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.assemble_data_pack("600887.SH")

        # Verify main structure
        assert "# 数据包 — 600887.SH" in result
        assert "Tushare Pro" in result
        assert "百万元" in result

        # Verify section headers present
        for sec in ["1. 基本信息", "2. 市场行情", "3. 合并利润表",
                     "4. 合并资产负债表", "5. 现金流量表", "6. 分红历史",
                     "11. 十年周线行情", "12. 关键财务指标"]:
            assert sec in result

        # Verify placeholder sections
        assert "8. 行业与竞争" in result
        assert "10. 管理层讨论与分析" in result
        assert "13. 风险警示" in result
        assert "Agent WebSearch" in result


# --- Feature #30: WarningsCollector ---

class TestWarningsCollector:
    def test_missing_data_warning(self):
        wc = WarningsCollector()
        wc.check_missing_data("利润表", pd.DataFrame())
        assert len(wc.warnings) == 1
        assert wc.warnings[0]["type"] == "DATA_MISSING"

    def test_yoy_anomaly(self):
        wc = WarningsCollector()
        # 400% change: 500 vs 100
        wc.check_yoy_change("利润表", "revenue", [500, 100], dates=["2024", "2023"])
        assert len(wc.warnings) == 1
        assert wc.warnings[0]["type"] == "YOY_ANOMALY"
        assert wc.warnings[0]["severity"] == "高"
        assert "2023→2024" in wc.warnings[0]["message"]

    def test_yoy_normal(self):
        wc = WarningsCollector()
        wc.check_yoy_change("利润表", "revenue", [110, 100], dates=["2024", "2023"])
        assert len(wc.warnings) == 0

    def test_yoy_without_dates(self):
        """Backward compat: works without dates param."""
        wc = WarningsCollector()
        wc.check_yoy_change("利润表", "revenue", [500, 100])
        assert len(wc.warnings) == 1
        assert wc.warnings[0]["type"] == "YOY_ANOMALY"

    def test_audit_risk(self):
        wc = WarningsCollector()
        wc.check_audit_risk("保留意见")
        assert len(wc.warnings) == 1
        assert wc.warnings[0]["type"] == "AUDIT_RISK"

    def test_audit_clean(self):
        wc = WarningsCollector()
        wc.check_audit_risk("标准无保留意见")
        assert len(wc.warnings) == 0

    def test_goodwill_risk(self):
        wc = WarningsCollector()
        # 25% goodwill ratio
        wc.check_goodwill_ratio(25e9, 100e9)
        assert len(wc.warnings) == 1
        assert wc.warnings[0]["type"] == "GOODWILL_RISK"

    def test_goodwill_ok(self):
        wc = WarningsCollector()
        wc.check_goodwill_ratio(5e9, 100e9)
        assert len(wc.warnings) == 0

    def test_debt_ratio_risk(self):
        wc = WarningsCollector()
        wc.check_debt_ratio(75e9, 100e9)
        assert len(wc.warnings) == 1
        assert wc.warnings[0]["type"] == "LEVERAGE_RISK"

    def test_format_warnings_empty(self):
        wc = WarningsCollector()
        result = wc.format_warnings()
        assert "未检测到异常" in result

    def test_format_warnings_grouped(self):
        wc = WarningsCollector()
        wc.check_audit_risk("保留意见")
        wc.check_missing_data("利润表", pd.DataFrame())
        result = wc.format_warnings()
        assert "高风险" in result
        assert "中风险" in result
        assert "共 2 条" in result


# --- _prepare_display_periods ---

class TestPrepareDisplayPeriods:
    """Tests for TushareClient._prepare_display_periods."""

    def test_annual_only_returns_five_years(self):
        """Pure annual data should return 5 years descending."""
        df = pd.DataFrame([
            {"end_date": "20241231", "revenue": 100},
            {"end_date": "20231231", "revenue": 90},
            {"end_date": "20221231", "revenue": 80},
            {"end_date": "20211231", "revenue": 70},
            {"end_date": "20201231", "revenue": 60},
        ])
        result_df, labels = _make_client()._prepare_display_periods(df)
        assert labels == ["2024", "2023", "2022", "2021", "2020"]
        assert len(result_df) == 5

    def test_annual_plus_newer_interim(self):
        """Interim reports newer than latest annual appear before annual cols."""
        df = pd.DataFrame([
            {"end_date": "20250930", "revenue": 95},
            {"end_date": "20250630", "revenue": 62},
            {"end_date": "20250331", "revenue": 31},
            {"end_date": "20241231", "revenue": 120},
            {"end_date": "20231231", "revenue": 112},
            {"end_date": "20221231", "revenue": 123},
            {"end_date": "20211231", "revenue": 110},
            {"end_date": "20201231", "revenue": 96},
        ])
        result_df, labels = _make_client()._prepare_display_periods(df)
        assert labels == ["2025Q3", "2025H1", "2025Q1", "2024", "2023", "2022", "2021", "2020"]
        assert len(result_df) == 8

    def test_older_interim_not_included(self):
        """Interim reports from same year or earlier than latest annual are excluded."""
        df = pd.DataFrame([
            {"end_date": "20240930", "revenue": 90},  # same year as latest annual
            {"end_date": "20241231", "revenue": 120},
            {"end_date": "20231231", "revenue": 112},
        ])
        result_df, labels = _make_client()._prepare_display_periods(df)
        assert labels == ["2024", "2023"]
        assert len(result_df) == 2

    def test_h1_label(self):
        """0630 end_date maps to H1 label."""
        df = pd.DataFrame([
            {"end_date": "20250630", "revenue": 62},
            {"end_date": "20241231", "revenue": 120},
        ])
        _, labels = _make_client()._prepare_display_periods(df)
        assert labels[0] == "2025H1"

    def test_q1_label(self):
        """0331 end_date maps to Q1 label."""
        df = pd.DataFrame([
            {"end_date": "20250331", "revenue": 31},
            {"end_date": "20241231", "revenue": 120},
        ])
        _, labels = _make_client()._prepare_display_periods(df)
        assert labels[0] == "2025Q1"

    def test_q3_label(self):
        """0930 end_date maps to Q3 label."""
        df = pd.DataFrame([
            {"end_date": "20250930", "revenue": 95},
            {"end_date": "20241231", "revenue": 120},
        ])
        _, labels = _make_client()._prepare_display_periods(df)
        assert labels[0] == "2025Q3"

    def test_empty_dataframe(self):
        """Empty DataFrame returns empty labels."""
        df = pd.DataFrame(columns=["end_date", "revenue"])
        result_df, labels = _make_client()._prepare_display_periods(df)
        assert labels == []
        assert result_df.empty

    def test_only_interim_no_annual(self):
        """If only interim data exists, return it (no annual cutoff)."""
        df = pd.DataFrame([
            {"end_date": "20250930", "revenue": 95},
            {"end_date": "20250630", "revenue": 62},
        ])
        result_df, labels = _make_client()._prepare_display_periods(df)
        assert labels == ["2025Q3", "2025H1"]
        assert len(result_df) == 2

    def test_deduplication(self):
        """Duplicate end_dates are removed."""
        df = pd.DataFrame([
            {"end_date": "20241231", "revenue": 120},
            {"end_date": "20241231", "revenue": 120},  # duplicate
            {"end_date": "20231231", "revenue": 112},
        ])
        result_df, labels = _make_client()._prepare_display_periods(df)
        assert labels == ["2024", "2023"]
        assert len(result_df) == 2


# --- Parent income field exclusion ---

class TestParentIncomeFieldExclusion:
    """Tests for report_type=6 excluding minority_gain/basic_eps/diluted_eps."""

    def test_report_type_6_excludes_fields(self):
        """Parent income (report_type=6) should not contain certain fields."""
        client = _make_client()
        mock_df = _load_mock("income.json")
        mock_df["report_type"] = "6"

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_income("600887.SH", report_type="6")

        assert "少数股东损益" not in result
        assert "基本EPS" not in result
        assert "稀释EPS" not in result
        # Core fields should still be present
        assert "营业收入" in result
        assert "净利润" in result
        assert "归母净利润" in result

    def test_report_type_1_includes_all_fields(self):
        """Consolidated income (report_type=1) should include all fields."""
        client = _make_client()
        mock_df = _load_mock("income.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_income("600887.SH", report_type="1")

        assert "少数股东损益" in result
        assert "基本EPS" in result
        assert "稀释EPS" in result


# --- Feature #79: Income statement expanded fields ---

class TestIncomeExpanded:
    def test_new_fields_present(self):
        """Verify 11 new income fields appear in output."""
        client = _make_client()
        mock_df = _load_mock("income.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_income("600887.SH")

        new_labels = [
            "财务费用", "所得税费用", "利润总额", "投资收益",
            "营业外收入", "营业外支出", "资产减值损失",
            "信用减值损失", "公允价值变动收益", "资产处置收益",
            "税金及附加",
        ]
        for label in new_labels:
            assert label in result, f"Missing: {label}"

    def test_field_order(self):
        """Verify fields are in accounting standards order."""
        client = _make_client()
        mock_df = _load_mock("income.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_income("600887.SH")

        ordered_labels = [
            "营业收入", "营业成本", "税金及附加",
            "销售费用", "管理费用", "研发费用", "财务费用",
            "营业利润", "营业外收入", "营业外支出",
            "利润总额", "所得税费用", "净利润", "归母净利润",
        ]
        positions = []
        for label in ordered_labels:
            pos = result.index(label)
            positions.append(pos)
        # Each label should appear after the previous
        for i in range(1, len(positions)):
            assert positions[i] > positions[i - 1], \
                f"{ordered_labels[i]} should appear after {ordered_labels[i - 1]}"

    def test_report_type_6_excludes_credit_impair(self):
        """Parent income (report_type=6) should also exclude credit_impair_loss."""
        client = _make_client()
        mock_df = _load_mock("income.json")
        mock_df["report_type"] = "6"

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_income("600887.SH", report_type="6")

        assert "信用减值损失" not in result
        # Other new fields should still be present
        assert "财务费用" in result
        assert "所得税费用" in result


# --- Feature #80: Balance sheet expanded fields ---

class TestBalanceSheetExpanded:
    def test_13_new_fields_present(self):
        """Verify 13 new balance sheet fields appear in output."""
        client = _make_client()
        mock_df = _load_mock("balancesheet.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_balance_sheet("600887.SH")

        new_labels = [
            "交易性金融资产", "其他流动资产", "无形资产",
            "在建工程", "应付账款", "应付票据",
            "递延所得税资产", "递延所得税负债", "应付债券",
            "一年内到期非流动负债", "其他流动负债",
            "流动资产合计", "流动负债合计",
        ]
        for label in new_labels:
            assert label in result, f"Missing: {label}"

    def test_balance_sheet_order(self):
        """Verify assets before liabilities before equity."""
        client = _make_client()
        mock_df = _load_mock("balancesheet.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_balance_sheet("600887.SH")

        # Assets appear before liabilities
        assert result.index("货币资金") < result.index("总资产")
        assert result.index("总资产") < result.index("短期借款")
        assert result.index("总负债") < result.index("归母所有者权益")


# --- Feature #81: Parent balance sheet expanded ---

class TestParentBalanceSheetExpanded:
    def test_parent_new_fields(self):
        """Parent balance sheet should include bond_payable, non_cur_liab_due_1y, equity."""
        client = _make_client()
        mock_df = _load_mock("balancesheet.json")
        mock_df["report_type"] = "6"

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_balance_sheet_parent("600887.SH")

        assert "4P. 母公司资产负债表" in result
        assert "应付债券" in result
        assert "一年内到期非流动负债" in result
        assert "归母权益" in result


# --- Feature #82: Cashflow expanded fields ---

class TestCashflowExpanded:
    def test_new_cashflow_fields(self):
        """Verify 5 new cashflow fields + c_pay_dist_dpcp_int_exp display."""
        client = _make_client()
        mock_df = _load_mock("cashflow.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_cashflow("600887.SH")

        new_labels = [
            "支付给职工现金", "支付的各项税费",
            "处置固定资产收回现金", "收到税费返还",
            "取得投资收益收到现金", "分配股利偿付利息",
        ]
        for label in new_labels:
            assert label in result, f"Missing: {label}"

    def test_cashflow_values(self):
        """Verify specific cashflow values appear."""
        client = _make_client()
        mock_df = _load_mock("cashflow.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_cashflow("600887.SH")

        # c_pay_to_staff 2024: 8520000000 -> 8,520.00
        assert "8,520.00" in result
        # c_pay_dist_dpcp_int_exp 2024: 5800000000 -> 5,800.00
        assert "5,800.00" in result


# --- Feature #83: Financial indicators expanded ---

class TestFinaIndicatorsExpanded:
    def test_new_indicator_fields(self):
        """Verify growth, per-share, and quality fields appear."""
        client = _make_client()
        mock_df = _load_mock("fina_indicator.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_fina_indicators("600887.SH")

        new_labels = [
            "营收同比增长率", "净利润同比增长率",
            "每股经营现金流", "每股净资产",
            "扣非净利润",
        ]
        for label in new_labels:
            assert label in result, f"Missing: {label}"

    def test_indicator_values(self):
        """Verify specific indicator values."""
        client = _make_client()
        mock_df = _load_mock("fina_indicator.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_fina_indicators("600887.SH")

        # revenue_yoy 2024: 7.12
        assert "7.12" in result
        # ocfps 2024: 2.65
        assert "2.65" in result
        # profit_dedt 2024: 9850000000 -> 9,850.00
        assert "9,850.00" in result


# --- Feature #84: Risk-free rate ---

class TestRiskFreeRate:
    def test_rf_output(self):
        """Verify risk-free rate section output."""
        client = _make_client()
        mock_df = _load_mock("yc_cb.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_risk_free_rate()

        assert "## 14. 无风险利率" in result
        assert "10年期国债收益率" in result
        assert "2.3150" in result
        assert "20260305" in result

    def test_rf_empty(self):
        """Verify graceful handling of empty data."""
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_risk_free_rate()
        assert "数据缺失" in result

    def test_rf_permission_error(self):
        """Verify graceful handling of API permission error."""
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(side_effect=RuntimeError("no permission"))
            result = client.get_risk_free_rate()
        assert "无权限" in result or "数据缺失" in result

    def test_rf_us_uses_treasury(self):
        """US stocks should use US 10-year Treasury yield, not Chinese bonds."""
        client = _make_client()
        client._yf_available = True
        mock_hist = pd.DataFrame(
            {"Close": [4.21]},
            index=pd.DatetimeIndex(["2026-03-11"]),
        )
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist
        with patch("tushare_collector.yf.Ticker", return_value=mock_ticker):
            result = client.get_risk_free_rate("AAPL.US")
        assert "美国10年期国债收益率" in result
        assert "4.2100" in result
        assert "^TNX" in result
        # Should NOT use Chinese bond source
        assert "中债" not in result

    def test_rf_us_stores_for_downstream(self):
        """US risk-free rate should be stored in _store for §17 computation."""
        client = _make_client()
        client._yf_available = True
        mock_hist = pd.DataFrame(
            {"Close": [4.21]},
            index=pd.DatetimeIndex(["2026-03-11"]),
        )
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = mock_hist
        with patch("tushare_collector.yf.Ticker", return_value=mock_ticker):
            client.get_risk_free_rate("AAPL.US")
        rf_df = client._store.get("risk_free_rate")
        assert rf_df is not None
        assert not rf_df.empty
        assert abs(float(rf_df.iloc[0]["yield"]) - 4.21) < 0.01

    def test_rf_a_share_uses_cn_bond(self):
        """A-share stocks should still use Chinese bond curve."""
        client = _make_client()
        mock_df = _load_mock("yc_cb.json")
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_risk_free_rate("600887.SH")
        assert "中债" in result
        assert "美国" not in result


# --- Feature #85: Share repurchase ---

class TestRepurchase:
    # Freeze "now" so the 3-year ann_date window never ages the fixture out.
    # Fixture ann_dates span 20230201-20250815; with real time the earliest 完成
    # record fell out of the window on 2026-06-15 and broke the dedup expectations.
    FROZEN_NOW = "tushare_modules.other_data._now"
    FROZEN_TS = pd.Timestamp("2026-01-15")

    def test_repurchase_output(self):
        """Verify repurchase section output."""
        client = _make_client()
        mock_df = _load_mock("repurchase.json")

        with patch("tushare_collector.time.sleep"), \
                patch(self.FROZEN_NOW, return_value=self.FROZEN_TS):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_repurchase("600887.SH")

        assert "## 15. 股票回购" in result
        assert "回购金额" in result
        assert "累计回购金额" in result
        assert "年均回购金额" in result
        # Should show proc column
        assert "进度" in result

    def test_repurchase_dedup_removes_duplicates(self):
        """Verify duplicate (ann_date, amount) records are deduplicated."""
        client = _make_client()
        # Fixture has 8 rows including same-date and cross-date duplicates
        mock_df = _load_mock("repurchase.json")
        assert len(mock_df) == 8, "fixture should have 8 rows including duplicates"

        with patch("tushare_collector.time.sleep"), \
                patch(self.FROZEN_NOW, return_value=self.FROZEN_TS):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_repurchase("600887.SH")

        # After all dedup: 2 完成 records (1050M + 1200M), 实施 removed (same high_limit as 完成)
        stored = client._store.get("repurchase")
        assert stored is not None
        assert len(stored) == 2, f"expected 2 records after cross-date dedup, got {len(stored)}"
        assert all(stored["proc"].isin(["完成", "实施"]))

    def test_repurchase_status_filter_completed_only(self):
        """Verify only proc in ['完成', '实施'] records are kept when available."""
        client = _make_client()
        mock_df = _load_mock("repurchase.json")

        with patch("tushare_collector.time.sleep"), \
                patch(self.FROZEN_NOW, return_value=self.FROZEN_TS):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_repurchase("600887.SH")

        stored = client._store.get("repurchase")
        for _, row in stored.iterrows():
            assert row["proc"] in ["完成", "实施"]

    def test_repurchase_fallback_no_completed(self):
        """When no executed records, fallback to deduped full data."""
        client = _make_client()
        # All records are 董事会预案/股东大会通过 (no 完成/实施)
        mock_df = pd.DataFrame([
            {"ts_code": "600887.SH", "ann_date": "20250101", "proc": "董事会预案",
             "amount": 1000000000.0, "vol": 30000000.0, "high_limit": 30.0, "low_limit": 20.0},
            {"ts_code": "600887.SH", "ann_date": "20240601", "proc": "股东大会通过",
             "amount": 800000000.0, "vol": 25000000.0, "high_limit": 28.0, "low_limit": 18.0},
        ])

        with patch("tushare_collector.time.sleep"), \
                patch(self.FROZEN_NOW, return_value=self.FROZEN_TS):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_repurchase("600887.SH")

        stored = client._store.get("repurchase")
        assert len(stored) == 2, "should fallback to all deduped records"

    def test_repurchase_amount_after_dedup(self):
        """Verify total amount reflects deduped + filtered data only."""
        client = _make_client()
        mock_df = _load_mock("repurchase.json")

        with patch("tushare_collector.time.sleep"), \
                patch(self.FROZEN_NOW, return_value=self.FROZEN_TS):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_repurchase("600887.SH")

        # Only 完成 records: 1,050 + 1,200 = 2,250 (million)
        # In raw yuan: 1,050,000,000 + 1,200,000,000 = 2,250,000,000
        # format_number divides by 1e6 → 2,250.00
        assert "2,250.00" in result

    def test_repurchase_cross_date_dedup(self):
        """Verify same plan across different dates is deduplicated."""
        client = _make_client()
        # Two 完成 records with same (amount=1050M, high_limit=32) on different dates
        mock_df = _load_mock("repurchase.json")

        with patch("tushare_collector.time.sleep"), \
                patch(self.FROZEN_NOW, return_value=self.FROZEN_TS):
            client._safe_call = MagicMock(return_value=mock_df)
            client.get_repurchase("600887.SH")

        stored = client._store.get("repurchase")
        # Should have exactly one record with amount=1050M (cross-date dedup)
        completed_1050 = stored[stored["amount"] == 1050000000.0]
        assert len(completed_1050) == 1, (
            f"expected 1 record for amount=1050M, got {len(completed_1050)}")

    def test_repurchase_executing_dedup(self):
        """Verify 实施 records with same high_limit keep only max amount,
        and are dropped when a 完成 record exists for the same plan."""
        client = _make_client()
        # Fixture has 实施 records (high_limit=33, amounts 800M and 300M)
        # and a 完成 record (high_limit=33, amount=1200M) for the same plan
        mock_df = _load_mock("repurchase.json")

        with patch("tushare_collector.time.sleep"), \
                patch(self.FROZEN_NOW, return_value=self.FROZEN_TS):
            client._safe_call = MagicMock(return_value=mock_df)
            client.get_repurchase("600887.SH")

        stored = client._store.get("repurchase")
        # 实施 records should be gone (完成 takes priority for high_limit=33)
        executing = stored[stored["proc"] == "实施"]
        assert len(executing) == 0, (
            f"expected 0 实施 records (完成 takes priority), got {len(executing)}")

    def test_repurchase_warning_annotation(self):
        """Verify 注销型 warning is appended to output."""
        client = _make_client()
        mock_df = _load_mock("repurchase.json")

        with patch("tushare_collector.time.sleep"), \
                patch(self.FROZEN_NOW, return_value=self.FROZEN_TS):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_repurchase("600887.SH")

        assert "注销型回购" in result
        assert "Phase 3" in result

    def test_repurchase_empty(self):
        """Verify graceful handling of no repurchase data."""
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_repurchase("600887.SH")
        assert "无回购记录" in result

    def test_repurchase_permission_error(self):
        """Verify graceful handling of API permission error."""
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(side_effect=RuntimeError("no permission"))
            result = client.get_repurchase("600887.SH")
        assert "无权限" in result or "数据缺失" in result


# --- Feature #86: Share pledge statistics ---

class TestPledgeStat:
    def test_pledge_stat_output(self):
        """Verify pledge statistics section output."""
        client = _make_client()
        mock_df = _load_mock("pledge_stat.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_pledge_stat("600887.SH")

        assert "## 16. 股权质押" in result
        assert "质押笔数" in result
        assert "无限售质押" in result
        assert "有限售质押" in result
        assert "质押比例" in result
        assert "5.19" in result  # pledge_ratio

    def test_pledge_stat_empty(self):
        """Verify graceful handling of empty pledge data."""
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_pledge_stat("600887.SH")
        assert "数据缺失" in result

    def test_pledge_stat_permission_error(self):
        """Verify graceful handling of API permission error."""
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(side_effect=RuntimeError("no permission"))
            result = client.get_pledge_stat("600887.SH")
        assert "无权限" in result or "数据缺失" in result


# --- Feature #36: WarningsCollector wired into assemble_data_pack ---

class TestAssembleDataPackWarnings:
    """Verify §13 in assembly output has auto-warnings and agent placeholder."""

    def _assemble_with_mock(self, safe_call_side_effect=None):
        """Helper: run assemble_data_pack with a custom _safe_call mock."""
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            if safe_call_side_effect is not None:
                client._safe_call = MagicMock(side_effect=safe_call_side_effect)
            else:
                client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.assemble_data_pack("600887.SH")
        return result

    def test_section_13_has_auto_warnings_subsection(self):
        """§13 output must contain '13.1 脚本自动检测'."""
        result = self._assemble_with_mock()
        assert "13.1 脚本自动检测" in result

    def test_section_13_has_agent_supplement_placeholder(self):
        """§13 output must contain '13.2 Agent WebSearch'."""
        result = self._assemble_with_mock()
        assert "13.2 Agent WebSearch" in result
        assert "§13.2 待Agent WebSearch补充" in result

    def test_empty_data_triggers_missing_warnings(self):
        """Empty DataFrames should trigger DATA_MISSING warnings."""
        result = self._assemble_with_mock()
        assert "DATA_MISSING" in result

    def test_high_debt_ratio_triggers_warning(self):
        """80% debt ratio should trigger LEVERAGE_RISK warning."""
        def mock_safe_call(api_name, **kwargs):
            if api_name == "balancesheet":
                return pd.DataFrame([{
                    "ts_code": "600887.SH",
                    "end_date": "20231231",
                    "total_assets": 1000000,
                    "total_liab": 800000,
                    "goodwill": 10000,
                }])
            if api_name == "income":
                return pd.DataFrame([{
                    "ts_code": "600887.SH",
                    "end_date": "20231231",
                    "revenue": 100000,
                    "n_income_attr_p": 50000,
                    "n_cashflow_act": 30000,
                }])
            if api_name == "cashflow":
                return pd.DataFrame([{
                    "ts_code": "600887.SH",
                    "end_date": "20231231",
                    "n_cashflow_act": 30000,
                }])
            if api_name == "fina_audit":
                return pd.DataFrame([{
                    "ts_code": "600887.SH",
                    "end_date": "20231231",
                    "audit_agency": "普华永道",
                    "audit_result": "标准无保留意见",
                }])
            return pd.DataFrame()

        result = self._assemble_with_mock(safe_call_side_effect=mock_safe_call)
        assert "LEVERAGE_RISK" in result

    def test_audit_risk_triggers_warning(self):
        """Non-standard audit opinion should trigger AUDIT_RISK warning."""
        def mock_safe_call(api_name, **kwargs):
            if api_name == "fina_audit":
                return pd.DataFrame([{
                    "ts_code": "600887.SH",
                    "end_date": "20231231",
                    "audit_agency": "某会计所",
                    "audit_result": "保留意见",
                }])
            if api_name == "balancesheet":
                return pd.DataFrame([{
                    "ts_code": "600887.SH",
                    "end_date": "20231231",
                    "total_assets": 1000000,
                    "total_liab": 500000,
                    "goodwill": 10000,
                }])
            if api_name in ("income", "cashflow"):
                return pd.DataFrame([{
                    "ts_code": "600887.SH",
                    "end_date": "20231231",
                    "revenue": 100000,
                    "n_income_attr_p": 50000,
                    "n_cashflow_act": 30000,
                }])
            return pd.DataFrame()

        result = self._assemble_with_mock(safe_call_side_effect=mock_safe_call)
        assert "AUDIT_RISK" in result

    def test_no_anomalies_shows_clean_message(self):
        """Normal data should show '未检测到异常'."""
        def mock_safe_call(api_name, **kwargs):
            if api_name == "balancesheet":
                return pd.DataFrame([{
                    "ts_code": "600887.SH",
                    "end_date": "20231231",
                    "total_assets": 1000000,
                    "total_liab": 400000,
                    "goodwill": 10000,
                }])
            if api_name == "fina_audit":
                return pd.DataFrame([{
                    "ts_code": "600887.SH",
                    "end_date": "20231231",
                    "audit_agency": "普华永道",
                    "audit_result": "标准无保留意见",
                }])
            if api_name in ("income", "cashflow"):
                return pd.DataFrame([{
                    "ts_code": "600887.SH",
                    "end_date": "20231231",
                    "revenue": 100000,
                    "n_income_attr_p": 50000,
                    "n_cashflow_act": 30000,
                }])
            return pd.DataFrame()

        result = self._assemble_with_mock(safe_call_side_effect=mock_safe_call)
        assert "未检测到异常" in result


# --- Feature #29: yfinance fallback tests ---

class TestYfinanceFallback:
    """Tests for yfinance fallback when Tushare fails."""

    def test_yf_ticker_conversion_sh(self):
        """SH suffix converts to SS for yfinance."""
        assert TushareClient._yf_ticker("600887.SH") == "600887.SS"

    def test_yf_ticker_conversion_sz(self):
        """SZ suffix stays as SZ for yfinance."""
        assert TushareClient._yf_ticker("000858.SZ") == "000858.SZ"

    def test_yf_ticker_conversion_hk(self):
        """HK suffix converts Tushare 5-digit to YF 4-digit."""
        assert TushareClient._yf_ticker("00700.HK") == "0700.HK"

    def test_yf_ticker_conversion_hk_single_digit(self):
        """HK code with few significant digits zero-pads to 4 digits."""
        assert TushareClient._yf_ticker("00005.HK") == "0005.HK"

    def test_yf_ticker_conversion_hk_4digit_tushare(self):
        """00696.HK → 0696.HK for Yahoo Finance."""
        assert TushareClient._yf_ticker("00696.HK") == "0696.HK"

    def test_fallback_skipped_when_unavailable(self):
        """When yfinance is not installed, fallback returns None."""
        client = _make_client()
        client._yf_available = False
        assert client._yf_fallback_price("600887.SH") is None

    def test_fallback_triggers_on_tushare_failure(self):
        """When Tushare section fails and yfinance available, fallback data is used."""
        client = _make_client()
        client._yf_available = True

        # Mock _yf_fallback_price to return data
        client._yf_fallback_price = MagicMock(return_value={
            "close": 30.5,
            "market_cap": 120000000000,
            "source": "yfinance (降级)",
        })

        # Mock all _safe_call to fail for get_basic_info, succeed for others
        call_count = [0]
        def mock_safe_call(api_name, **kwargs):
            call_count[0] += 1
            if api_name == "stock_basic":
                raise RuntimeError("Tushare API failed")
            return pd.DataFrame()

        with patch.object(client, '_safe_call', side_effect=mock_safe_call):
            result = client.assemble_data_pack("600887.SH")

        assert "yfinance (降级)" in result

    def test_fallback_source_tag_in_output(self):
        """Fallback output includes '来源: yfinance (降级)' tag."""
        client = _make_client()
        client._yf_available = True
        client._yf_fallback_price = MagicMock(return_value={
            "close": 25.0,
            "market_cap": 80000000000,
            "source": "yfinance (降级)",
        })

        def mock_safe_call(api_name, **kwargs):
            if api_name == "stock_basic":
                raise RuntimeError("Tushare failed")
            return pd.DataFrame()

        with patch.object(client, '_safe_call', side_effect=mock_safe_call):
            result = client.assemble_data_pack("600887.SH")

        assert "来源: yfinance (降级)" in result
        assert "当前价格: 25.0" in result

    def test_hk_market_data_uses_yfinance_primary(self):
        """HK market data calls yfinance first, not hk_daily."""
        client = _make_client()
        client._yf_available = True
        client._yf_hk_market_data = MagicMock(return_value={
            "close": 350.0,
            "high_52w": 400.0,
            "low_52w": 300.0,
            "market_cap": 3_000_000_000_000,
            "volume_avg": 10_000_000,
        })

        with patch.object(client, '_safe_call', return_value=pd.DataFrame()) as mock_call:
            result = client._get_market_data_hk("00700.HK")

        # yfinance was called and used — hk_daily should NOT have been called
        client._yf_hk_market_data.assert_called_once_with("00700.HK")
        mock_call.assert_not_called()
        assert "350.00" in result
        # No degradation tag since yfinance is the primary source
        assert "降级" not in result
        assert "hk_daily" not in result

    def test_hk_weekly_uses_yfinance_primary(self):
        """HK weekly prices calls _yf_weekly_history first, not hk_daily."""
        client = _make_client()
        client._yf_available = True
        weekly_df = pd.DataFrame({
            "trade_date": ["20240101", "20240108", "20240115"],
            "ts_code": ["00700.HK"] * 3,
            "open": [350.0, 355.0, 360.0],
            "high": [360.0, 365.0, 370.0],
            "low": [345.0, 350.0, 355.0],
            "close": [355.0, 360.0, 365.0],
            "vol": [1000000, 1100000, 1200000],
        })
        client._yf_weekly_history = MagicMock(return_value=weekly_df)

        with patch.object(client, '_safe_call', return_value=pd.DataFrame()) as mock_call:
            result = client._get_weekly_prices_hk("00700.HK")

        # yfinance was called and used — hk_daily should NOT have been called
        client._yf_weekly_history.assert_called_once_with("00700.HK")
        mock_call.assert_not_called()
        assert "365.00" in result
        # No degradation tag since yfinance is the primary source
        assert "降级" not in result
        assert "hk_daily" not in result


# --- Feature #70: HK stock currency annotation ---

class TestHKCurrencyAnnotation:
    """Tests for Hong Kong stock currency detection and annotation."""

    def test_detect_currency_hk(self):
        """HK stock codes return HKD."""
        assert TushareClient._detect_currency("00700.HK") == "HKD"

    def test_detect_currency_a_share(self):
        """A-share codes return CNY."""
        assert TushareClient._detect_currency("600887.SH") == "CNY"
        assert TushareClient._detect_currency("000858.SZ") == "CNY"

    def test_hk_annotation_in_data_pack(self):
        """HK stock data pack includes HKD currency annotation."""
        client = _make_client()

        def mock_safe_call(api_name, **kwargs):
            return pd.DataFrame()

        with patch.object(client, '_safe_call', side_effect=mock_safe_call):
            result = client.assemble_data_pack("00700.HK")

        assert "报表币种: HKD" in result
        assert "百万港元" in result

    def test_a_share_no_hkd_annotation(self):
        """A-share data pack does NOT include HKD annotation."""
        client = _make_client()

        def mock_safe_call(api_name, **kwargs):
            return pd.DataFrame()

        with patch.object(client, '_safe_call', side_effect=mock_safe_call):
            result = client.assemble_data_pack("600887.SH")

        assert "报表币种: HKD" not in result
        assert "百万元" in result


# =============================================================================
# HK Stock Support Tests (#109-#120)
# =============================================================================


class TestBrokerConfig:
    """Test broker API URL configuration (#109)."""

    @patch("tushare_collector.get_api_url", return_value=None)
    @patch("tushare_collector.ts")
    def test_no_broker_vip_off(self, mock_ts, mock_url):
        """Without TUSHARE_API_URL, VIP mode should be off."""
        mock_ts.pro_api.return_value = MagicMock()
        client = TushareClient("token")
        assert client._vip_mode is False

    @patch("tushare_collector.get_api_url", return_value="http://broker.example.com")
    @patch("tushare_collector.ts")
    def test_broker_enables_vip(self, mock_ts, mock_url):
        """With TUSHARE_API_URL, VIP mode should be on and hacks applied."""
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        client = TushareClient("my_token")
        assert client._vip_mode is True
        assert mock_pro._DataApi__token == "my_token"
        assert mock_pro._DataApi__http_url == "http://broker.example.com"

    @patch("tushare_collector.get_api_url", return_value="http://broker.example.com")
    @patch("tushare_collector.ts")
    def test_broker_retry_re_applies_hacks(self, mock_ts, mock_url):
        """After connection error retry, broker hacks should be re-applied."""
        mock_pro_old = MagicMock()
        mock_pro_new = MagicMock()
        expected_df = pd.DataFrame({"col": [1]})
        mock_pro_old.income_vip.side_effect = OSError("RemoteDisconnected")
        mock_pro_new.income_vip.return_value = expected_df
        mock_ts.pro_api.side_effect = [mock_pro_old, mock_pro_new]

        client = TushareClient("token")
        with patch("tushare_collector.time.sleep"):
            result = client._safe_call("income", ts_code="00700.HK")

        assert result.equals(expected_df)
        # New pro should have hacks applied
        assert mock_pro_new._DataApi__token == "token"
        assert mock_pro_new._DataApi__http_url == "http://broker.example.com"


class TestVIPSwitch:
    """Test VIP API auto-upgrade (#110)."""

    @patch("tushare_collector.get_api_url", return_value="http://broker.example.com")
    @patch("tushare_collector.ts")
    def test_vip_name_substitution(self, mock_ts, mock_url):
        """_safe_call should use income_vip when VIP mode is on."""
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        expected_df = pd.DataFrame({"col": [1]})
        mock_pro.income_vip.return_value = expected_df

        client = TushareClient("token")
        with patch("tushare_collector.time.sleep"):
            result = client._safe_call("income", ts_code="600887.SH")

        mock_pro.income_vip.assert_called_once_with(ts_code="600887.SH")
        assert result.equals(expected_df)

    @patch("tushare_collector.get_api_url", return_value="http://broker.example.com")
    @patch("tushare_collector.ts")
    def test_vip_all_mapped_endpoints(self, mock_ts, mock_url):
        """All VIP-mapped endpoints should be upgraded."""
        from tushare_collector import _VIP_MAP
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro

        client = TushareClient("token")
        for standard, vip in _VIP_MAP.items():
            expected_df = pd.DataFrame({"col": [1]})
            getattr(mock_pro, vip).return_value = expected_df
            with patch("tushare_collector.time.sleep"):
                client._safe_call(standard, ts_code="600887.SH")
            getattr(mock_pro, vip).assert_called()

    @patch("tushare_collector.get_api_url", return_value=None)
    @patch("tushare_collector.ts")
    def test_no_vip_no_substitution(self, mock_ts, mock_url):
        """Without broker, standard endpoint names should be used."""
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        expected_df = pd.DataFrame({"col": [1]})
        mock_pro.income.return_value = expected_df

        client = TushareClient("token")
        with patch("tushare_collector.time.sleep"):
            result = client._safe_call("income", ts_code="600887.SH")

        mock_pro.income.assert_called_once_with(ts_code="600887.SH")
        assert result.equals(expected_df)

    @patch("tushare_collector.get_api_url", return_value="http://broker.example.com")
    @patch("tushare_collector.ts")
    def test_non_mapped_endpoint_unchanged(self, mock_ts, mock_url):
        """Endpoints not in _VIP_MAP should keep their original name."""
        mock_pro = MagicMock()
        mock_ts.pro_api.return_value = mock_pro
        expected_df = pd.DataFrame({"col": [1]})
        mock_pro.stock_basic.return_value = expected_df

        client = TushareClient("token")
        with patch("tushare_collector.time.sleep"):
            result = client._safe_call("stock_basic", ts_code="600887.SH")

        mock_pro.stock_basic.assert_called_once()


class TestIsHK:
    """Test _is_hk static method."""

    def test_hk_code(self):
        assert TushareClient._is_hk("00700.HK") is True

    def test_sh_code(self):
        assert TushareClient._is_hk("600887.SH") is False

    def test_sz_code(self):
        assert TushareClient._is_hk("000858.SZ") is False

    def test_case_insensitive(self):
        assert TushareClient._is_hk("00700.hk") is True


class TestHKPivot:
    """Test _pivot_hk_line_items (#111)."""

    def test_basic_pivot(self):
        """Line-item rows should pivot into columnar format."""
        from tushare_collector import HK_INCOME_MAP
        df = pd.DataFrame([
            {"ts_code": "00700.HK", "end_date": "20241231", "ind_name": "营业额", "ind_value": 660125000000},
            {"ts_code": "00700.HK", "end_date": "20241231", "ind_name": "除税后溢利", "ind_value": 181815000000},
            {"ts_code": "00700.HK", "end_date": "20231231", "ind_name": "营业额", "ind_value": 609015000000},
            {"ts_code": "00700.HK", "end_date": "20231231", "ind_name": "除税后溢利", "ind_value": 155975000000},
        ])
        result = TushareClient._pivot_hk_line_items(df, HK_INCOME_MAP)
        assert not result.empty
        assert "revenue" in result.columns
        assert "n_income" in result.columns
        assert len(result) == 2
        # Check 2024 revenue
        row_2024 = result[result["end_date"] == "20241231"].iloc[0]
        assert row_2024["revenue"] == 660125000000

    def test_missing_fields_handled(self):
        """Fields not in map should be ignored without error."""
        from tushare_collector import HK_INCOME_MAP
        df = pd.DataFrame([
            {"ts_code": "00700.HK", "end_date": "20241231", "ind_name": "营业额", "ind_value": 100},
            {"ts_code": "00700.HK", "end_date": "20241231", "ind_name": "未知项目", "ind_value": 999},
        ])
        result = TushareClient._pivot_hk_line_items(df, HK_INCOME_MAP)
        assert "revenue" in result.columns
        assert len(result) == 1

    def test_empty_dataframe(self):
        """Empty input should return empty output."""
        from tushare_collector import HK_INCOME_MAP
        df = pd.DataFrame(columns=["ts_code", "end_date", "ind_name", "ind_value"])
        result = TushareClient._pivot_hk_line_items(df, HK_INCOME_MAP)
        assert result.empty

    def test_no_matching_fields(self):
        """If no ind_name matches, return empty."""
        from tushare_collector import HK_INCOME_MAP
        df = pd.DataFrame([
            {"ts_code": "00700.HK", "end_date": "20241231", "ind_name": "完全不匹配", "ind_value": 100},
        ])
        result = TushareClient._pivot_hk_line_items(df, HK_INCOME_MAP)
        assert result.empty


class TestHKIncome:
    """Test HK income statement (#113)."""

    def test_hk_income_output(self):
        client = _make_client()
        mock_df = _load_mock("hk_income_00700.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_income("00700.HK")

        assert "## 3. 合并利润表" in result
        assert "百万港元" in result
        assert "2024" in result
        assert "2020" in result
        # Check Tencent's 2024 revenue: 660125000000 / 1e6 = 660,125.00
        assert "660,125.00" in result
        assert "营业额" in result
        assert "股东应占溢利" in result

    def test_hk_income_empty(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_income("00700.HK")
        assert "数据缺失" in result

    def test_hk_income_parent_placeholder(self):
        """HK parent income should return placeholder."""
        client = _make_client()
        result = client.get_income_parent("00700.HK")
        assert "HKFRS" in result
        assert "3P. 母公司利润表" in result


class TestHKBalanceSheet:
    """Test HK balance sheet (#114)."""

    def test_hk_balance_sheet_output(self):
        client = _make_client()
        mock_df = _load_mock("hk_balancesheet_00700.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_balance_sheet("00700.HK")

        assert "## 4. 合并资产负债表" in result
        assert "百万港元" in result
        assert "现金及等价物" in result
        assert "总资产" in result
        assert "股东权益" in result
        # 2024 total_assets: 1520000000000 / 1e6 = 1,520,000.00
        assert "1,520,000.00" in result

    def test_hk_balance_sheet_parent_placeholder(self):
        client = _make_client()
        result = client.get_balance_sheet_parent("00700.HK")
        assert "HKFRS" in result
        assert "4P. 母公司资产负债表" in result


class TestHKCashflow:
    """Test HK cashflow (#115)."""

    def test_hk_cashflow_output(self):
        client = _make_client()
        mock_df = _load_mock("hk_cashflow_00700.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_cashflow("00700.HK")

        assert "## 5. 现金流量表" in result
        assert "百万港元" in result
        assert "经营业务现金净额" in result
        assert "自由现金流" in result
        assert "c_pay_to_staff 港股不可用" in result
        # 2024 OCF: 225000000000 / 1e6 = 225,000.00
        assert "225,000.00" in result
        # 2024 FCF = 225000M - 42000M = 183,000.00
        assert "183,000.00" in result

    def test_hk_cashflow_empty(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_cashflow("00700.HK")
        assert "数据缺失" in result


class TestHKFinaIndicators:
    """Test HK financial indicators (#116)."""

    def test_hk_fina_indicators_output(self):
        client = _make_client()
        mock_df = _load_mock("hk_fina_indicator_00700.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_fina_indicators("00700.HK")

        assert "## 12. 关键财务指标" in result
        assert "ROE" in result
        assert "毛利率" in result
        assert "22.85" in result  # ROE 2024
        assert "52.80" in result  # gross margin 2024
        assert "PE (TTM)" in result

    def test_hk_fina_indicators_empty(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_fina_indicators("00700.HK")
        assert "数据缺失" in result


class TestHKDividends:
    """Test HK dividends (#116)."""

    def test_hk_dividends_output(self):
        client = _make_client()
        mock_df = _load_mock("hk_fina_indicator_00700.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_dividends("00700.HK")

        assert "## 6. 分红历史" in result
        assert "每股股息 (HKD)" in result
        assert "4.4000" in result  # 2024 DPS

    def test_hk_dividends_empty(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_dividends("00700.HK")
        assert "暂无分红" in result


class TestHKPlaceholderSections:
    """Test HK placeholder sections for unsupported data."""

    def test_hk_holders_yf_unavailable(self):
        client = _make_client()
        client._yf_available = False
        result = client.get_holders("00700.HK")
        assert "yfinance不可用" in result

    def test_hk_segments_placeholder(self):
        client = _make_client()
        result = client.get_segments("00700.HK")
        assert "港股暂不支持" in result

    def test_hk_audit_placeholder(self):
        client = _make_client()
        result = client.get_audit("00700.HK")
        assert "港股暂不支持" in result

    def test_hk_repurchase_placeholder(self):
        client = _make_client()
        result = client.get_repurchase("00700.HK")
        assert "港股暂不支持" in result

    def test_hk_pledge_not_applicable(self):
        client = _make_client()
        result = client.get_pledge_stat("00700.HK")
        assert "不适用" in result
        assert "港股无此制度" in result


class TestHKAssembly:
    """Test full HK data pack assembly (#118)."""

    def test_hk_assembly_section_list(self):
        """HK assembly should skip §3P and §4P."""
        client = _make_client()

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.assemble_data_pack("00700.HK")

        assert "# 数据包 — 00700.HK" in result
        assert "报表币种: HKD" in result
        assert "百万港元" in result
        # Core sections should be present
        assert "1. 基本信息" in result
        assert "3. 合并利润表" in result
        assert "4. 合并资产负债表" in result
        assert "5. 现金流量表" in result
        assert "11. 十年周线行情" in result
        # §3P and §4P should NOT be present
        assert "3P. 母公司利润表" not in result
        assert "4P. 母公司资产负债表" not in result
        # HK warning in §13
        assert "港股数据覆盖有限" in result

    def test_hk_assembly_with_data(self):
        """HK assembly with mock data should produce complete output."""
        client = _make_client()
        mock_data = {
            "hk_basic": _load_mock("hk_basic_00700.json"),
            "hk_income": _load_mock("hk_income_00700.json"),
            "hk_balancesheet": _load_mock("hk_balancesheet_00700.json"),
            "hk_cashflow": _load_mock("hk_cashflow_00700.json"),
            "hk_fina_indicator": _load_mock("hk_fina_indicator_00700.json"),
        }

        def mock_safe_call(api_name, **kwargs):
            if api_name in mock_data:
                return mock_data[api_name]
            return pd.DataFrame()

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(side_effect=mock_safe_call)
            client._yf_available = False  # disable yfinance for deterministic test
            result = client.assemble_data_pack("00700.HK")

        assert "腾讯控股" in result
        assert "660,125.00" in result  # income revenue
        assert "1,520,000.00" in result  # total assets
        assert "225,000.00" in result  # OCF


class TestYfFillMissingHK:
    """Test _yf_fill_missing_hk helper for backfilling NaN fields."""

    def _make_pivoted(self, missing_cols=None):
        """Create a pivoted DataFrame with some NaN fields."""
        data = {
            "end_date": ["20231231", "20221231"],
            "ts_code": ["00700.HK", "00700.HK"],
            "revenue": [660125.0, 554552.0],
            "n_income": [115220.0, 88827.0],
        }
        if missing_cols:
            for col in missing_cols:
                data[col] = [float("nan"), float("nan")]
        return pd.DataFrame(data)

    def _mock_yf_income(self):
        """Create a mock yfinance income_stmt DataFrame."""
        import numpy as np
        dates = [pd.Timestamp("2023-12-31"), pd.Timestamp("2022-12-31")]
        data = {
            dates[0]: {"Operating Income": 200000.0, "Tax Provision": 30000.0},
            dates[1]: {"Operating Income": 180000.0, "Tax Provision": 25000.0},
        }
        return pd.DataFrame(data)

    def test_fills_missing_income_fields(self):
        """Should fill NaN fields from yfinance data."""
        client = _make_client()
        client._yf_available = True
        pivoted = self._make_pivoted(missing_cols=["operate_profit", "income_tax"])

        mock_ticker = MagicMock()
        mock_ticker.income_stmt = self._mock_yf_income()

        with patch("tushare_collector.yf.Ticker", return_value=mock_ticker):
            filled, yf_used = client._yf_fill_missing_hk(pivoted, "00700.HK", "income")

        assert yf_used is True
        assert filled.at[0, "operate_profit"] == 200000.0
        assert filled.at[1, "operate_profit"] == 180000.0
        assert filled.at[0, "income_tax"] == 30000.0
        # Original data should be preserved
        assert filled.at[0, "revenue"] == 660125.0

    def test_does_not_overwrite_existing(self):
        """Should never overwrite existing Tushare values (but may fill absent mapped cols)."""
        client = _make_client()
        client._yf_available = True
        pivoted = self._make_pivoted()  # revenue & n_income have values

        mock_ticker = MagicMock()
        mock_ticker.income_stmt = self._mock_yf_income()

        with patch("tushare_collector.yf.Ticker", return_value=mock_ticker):
            filled, yf_used = client._yf_fill_missing_hk(pivoted, "00700.HK", "income")

        # yf_used may be True (absent mapped cols were added and filled),
        # but existing Tushare values must be preserved
        assert filled.at[0, "revenue"] == 660125.0
        assert filled.at[0, "n_income"] == 115220.0
        assert filled.at[1, "revenue"] == 554552.0
        assert filled.at[1, "n_income"] == 88827.0

    def test_yf_unavailable_returns_unchanged(self):
        """Should return unchanged DataFrame when yfinance unavailable."""
        client = _make_client()
        client._yf_available = False
        pivoted = self._make_pivoted(missing_cols=["operate_profit"])

        filled, yf_used = client._yf_fill_missing_hk(pivoted, "00700.HK", "income")

        assert yf_used is False
        assert pd.isna(filled.at[0, "operate_profit"])

    def test_no_missing_returns_unchanged(self):
        """Should return unchanged when no NaN in existing fields, even though
        mapped columns are absent — yfinance is called, but returns empty DF
        so original is returned without extra NaN columns."""
        client = _make_client()
        client._yf_available = True
        pivoted = self._make_pivoted()  # all existing fields have values

        # yfinance WILL be called now (absent mapped cols added as NaN),
        # but empty yf_df causes early return of original
        mock_ticker = MagicMock()
        mock_ticker.income_stmt = pd.DataFrame()  # empty

        with patch("tushare_collector.yf.Ticker", return_value=mock_ticker):
            filled, yf_used = client._yf_fill_missing_hk(pivoted, "00700.HK", "income")

        assert yf_used is False
        # Original columns preserved — no extra NaN columns leaked
        assert set(filled.columns) == set(pivoted.columns)

    def test_yf_exception_returns_unchanged(self):
        """Should handle yfinance exceptions gracefully (retries exhausted)."""
        client = _make_client()
        client._yf_available = True
        pivoted = self._make_pivoted(missing_cols=["operate_profit"])

        with patch("tushare_collector.yf.Ticker", side_effect=Exception("API error")):
            with patch("tushare_modules.yfinance_integration.time.sleep"):
                filled, yf_used = client._yf_fill_missing_hk(pivoted, "00700.HK", "income")

        assert yf_used is False
        assert pd.isna(filled.at[0, "operate_profit"])

    def test_cashflow_fill_da_and_capex(self):
        """Should fill D&A and Capex from yfinance cashflow data."""
        client = _make_client()
        client._yf_available = True
        data = {
            "end_date": ["20231231"],
            "ts_code": ["00700.HK"],
            "n_cashflow_act": [225000.0],
            "depr_fa_coga_dpba": [float("nan")],
            "c_pay_acq_const_fiolta": [float("nan")],
        }
        pivoted = pd.DataFrame(data)

        dates = [pd.Timestamp("2023-12-31")]
        yf_data = {
            dates[0]: {
                "Depreciation And Amortization": 45000.0,
                "Capital Expenditure": -32000.0,
            },
        }
        mock_ticker = MagicMock()
        mock_ticker.cashflow = pd.DataFrame(yf_data)

        with patch("tushare_collector.yf.Ticker", return_value=mock_ticker):
            filled, yf_used = client._yf_fill_missing_hk(pivoted, "00700.HK", "cashflow")

        assert yf_used is True
        assert filled.at[0, "depr_fa_coga_dpba"] == 45000.0
        assert filled.at[0, "c_pay_acq_const_fiolta"] == -32000.0

    def test_fills_completely_absent_column(self):
        """Should fill a column that doesn't exist at all in pivoted DF."""
        client = _make_client()
        client._yf_available = True
        # pivoted has NO operate_profit column at all (not even NaN)
        data = {
            "end_date": ["20231231", "20221231"],
            "ts_code": ["00700.HK", "00700.HK"],
            "revenue": [660125.0, 554552.0],
        }
        pivoted = pd.DataFrame(data)
        assert "operate_profit" not in pivoted.columns

        mock_ticker = MagicMock()
        mock_ticker.income_stmt = self._mock_yf_income()

        with patch("tushare_collector.yf.Ticker", return_value=mock_ticker):
            filled, yf_used = client._yf_fill_missing_hk(pivoted, "00700.HK", "income")

        assert yf_used is True
        assert "operate_profit" in filled.columns
        assert filled.at[0, "operate_profit"] == 200000.0
        assert filled.at[1, "operate_profit"] == 180000.0
        # Original data preserved
        assert filled.at[0, "revenue"] == 660125.0

    def test_absent_column_no_yf_data_returns_original(self):
        """When yfinance returns empty DF, no extra NaN columns should leak."""
        client = _make_client()
        client._yf_available = True
        data = {
            "end_date": ["20231231"],
            "ts_code": ["00700.HK"],
            "revenue": [660125.0],
        }
        pivoted = pd.DataFrame(data)
        original_cols = set(pivoted.columns)

        mock_ticker = MagicMock()
        mock_ticker.income_stmt = pd.DataFrame()  # empty

        with patch("tushare_collector.yf.Ticker", return_value=mock_ticker):
            filled, yf_used = client._yf_fill_missing_hk(pivoted, "00700.HK", "income")

        assert yf_used is False
        assert set(filled.columns) == original_cols

    def test_absent_column_yf_unavailable_returns_original(self):
        """When _yf_available=False, no extra columns should be added."""
        client = _make_client()
        client._yf_available = False
        data = {
            "end_date": ["20231231"],
            "ts_code": ["00700.HK"],
            "revenue": [660125.0],
        }
        pivoted = pd.DataFrame(data)
        original_cols = set(pivoted.columns)

        filled, yf_used = client._yf_fill_missing_hk(pivoted, "00700.HK", "income")

        assert yf_used is False
        assert set(filled.columns) == original_cols


class TestYfFillRetryAndWarnings:
    """Test retry logic and stderr warnings in _yf_fill_missing_hk."""

    def _make_pivoted_with_nan(self):
        return pd.DataFrame({
            "end_date": ["20231231"],
            "ts_code": ["00700.HK"],
            "revenue": [660125.0],
            "operate_profit": [float("nan")],
        })

    def _mock_yf_income(self):
        dates = [pd.Timestamp("2023-12-31")]
        return pd.DataFrame({
            dates[0]: {"Operating Income": 200000.0},
        })

    def test_yf_fill_retries_on_exception(self):
        """Should retry once after first exception and succeed on second call."""
        client = _make_client()
        client._yf_available = True
        pivoted = self._make_pivoted_with_nan()

        mock_ticker = MagicMock()
        mock_ticker.income_stmt = self._mock_yf_income()

        with patch("tushare_collector.yf.Ticker",
                   side_effect=[Exception("rate limit"), mock_ticker]):
            with patch("tushare_modules.yfinance_integration.time.sleep") as mock_sleep:
                filled, yf_used = client._yf_fill_missing_hk(pivoted, "00700.HK", "income")

        assert yf_used is True
        assert filled.at[0, "operate_profit"] == 200000.0
        mock_sleep.assert_called_once_with(1)

    def test_yf_fill_warns_after_retries_exhausted(self, capsys):
        """Should warn on stderr and return original after all retries fail."""
        client = _make_client()
        client._yf_available = True
        pivoted = self._make_pivoted_with_nan()

        with patch("tushare_collector.yf.Ticker",
                   side_effect=Exception("API error")):
            with patch("tushare_modules.yfinance_integration.time.sleep"):
                filled, yf_used = client._yf_fill_missing_hk(pivoted, "00700.HK", "income")

        assert yf_used is False
        assert pd.isna(filled.at[0, "operate_profit"])
        captured = capsys.readouterr()
        assert "[yfinance] 00700.HK income: fallback failed after 2 retries" in captured.err

    def test_yf_fill_warns_on_empty_data(self, capsys):
        """Should warn on stderr when yfinance returns empty DataFrame."""
        client = _make_client()
        client._yf_available = True
        pivoted = self._make_pivoted_with_nan()

        mock_ticker = MagicMock()
        mock_ticker.income_stmt = pd.DataFrame()

        with patch("tushare_collector.yf.Ticker", return_value=mock_ticker):
            filled, yf_used = client._yf_fill_missing_hk(pivoted, "00700.HK", "income")

        assert yf_used is False
        captured = capsys.readouterr()
        assert "[yfinance] 00700.HK income: no data returned" in captured.err


class TestGetPayoutByYear:
    """Test _get_payout_by_year helper."""

    def test_hk_cross_validates_divi_ratio_with_eps(self):
        """HK path: when Tushare and computed are close (<20%), use Tushare."""
        client = _make_client()
        client._store["dividends_hk"] = pd.DataFrame({
            "end_date": ["20231231", "20221231"],
            "dps_hkd": [4.40, 3.40],
            "divi_ratio": [23.25, 22.19],
        })
        client._store["income"] = pd.DataFrame({
            "end_date": ["20231231", "20221231"],
            "basic_eps": [18.92, 16.12],
        })
        result = client._get_payout_by_year()
        # computed: 4.40/18.92*100=23.26, diff=0.04% → use Tushare 23.25
        assert result["2023"] == 23.25
        # computed: 3.40/16.12*100=21.09, diff=5.2% → use Tushare 22.19
        assert result["2022"] == 22.19

    def test_hk_divi_ratio_dirty_data_fixed(self):
        """HK path: divi_ratio < 1 treated as dirty data → ×100 fix."""
        client = _make_client()
        client._store["dividends_hk"] = pd.DataFrame({
            "end_date": ["20231231"],
            "dps_hkd": [0.50],
            "divi_ratio": [0.49],
        })
        client._store["income"] = pd.DataFrame({
            "end_date": ["20231231"],
            "basic_eps": [1.02],
        })
        result = client._get_payout_by_year()
        # fixed ts_ratio=49.0, computed=0.50/1.02*100≈49.02, diff≈0.04% → use Tushare(fixed) 49.0
        assert result["2023"] == 49.0

    def test_hk_cross_validate_uses_computed_when_divergent(self):
        """HK path: when Tushare and computed diverge (≥20%), use computed."""
        client = _make_client()
        client._store["dividends_hk"] = pd.DataFrame({
            "end_date": ["20231231"],
            "dps_hkd": [4.40],
            "divi_ratio": [50.0],  # way off from computed ~23%
        })
        client._store["income"] = pd.DataFrame({
            "end_date": ["20231231"],
            "basic_eps": [18.92],
        })
        result = client._get_payout_by_year()
        computed = 4.40 / 18.92 * 100
        assert abs(result["2023"] - computed) < 0.01

    def test_hk_falls_back_to_divi_ratio_when_no_eps(self):
        """HK path: no income data → use (fixed) divi_ratio."""
        client = _make_client()
        client._store["dividends_hk"] = pd.DataFrame({
            "end_date": ["20231231"],
            "dps_hkd": [4.40],
            "divi_ratio": [0.49],  # dirty → fixed to 49.0
        })
        # No income data
        result = client._get_payout_by_year()
        assert result["2023"] == 49.0

    def test_hk_falls_back_to_computed_when_no_divi_ratio(self):
        """HK path: divi_ratio is NaN → use DPS/EPS computed."""
        client = _make_client()
        client._store["dividends_hk"] = pd.DataFrame({
            "end_date": ["20231231"],
            "dps_hkd": [4.40],
            "divi_ratio": [float("nan")],
        })
        client._store["income"] = pd.DataFrame({
            "end_date": ["20231231"],
            "basic_eps": [18.92],
        })
        result = client._get_payout_by_year()
        computed = 4.40 / 18.92 * 100
        assert abs(result["2023"] - computed) < 0.01

    def test_hk_no_dps_no_eps_uses_divi_ratio(self):
        """HK path: no DPS, no EPS → use divi_ratio (fixed if needed)."""
        client = _make_client()
        client._store["dividends_hk"] = pd.DataFrame({
            "end_date": ["20231231"],
            "dps_hkd": [float("nan")],
            "divi_ratio": [25.0],
        })
        result = client._get_payout_by_year()
        assert result["2023"] == 25.0

    def test_ashare_computes_from_formula(self):
        """A-share path should compute from cash_div × base_share × 10000 / net_income."""
        client = _make_client()
        # No HK data
        client._store["dividends"] = pd.DataFrame({
            "end_date": ["20231231", "20221231"],
            "cash_div_tax": [0.5, 0.4],
            "base_share": [100.0, 100.0],  # 万股 → 100 万股
            "div_proc": ["实施", "实施"],
        })
        client._store["income"] = pd.DataFrame({
            "end_date": ["20231231", "20221231"],
            "n_income_attr_p": [1000000.0, 800000.0],
        })
        result = client._get_payout_by_year()
        # 0.5 * 100 * 10000 / 1000000 * 100 = 50%
        assert abs(result["2023"] - 50.0) < 0.01
        # 0.4 * 100 * 10000 / 800000 * 100 = 50%
        assert abs(result["2022"] - 50.0) < 0.01

    def test_empty_dividends_returns_empty(self):
        """Should return empty dict when no dividend data."""
        client = _make_client()
        result = client._get_payout_by_year()
        assert result == {}

    def test_empty_income_returns_empty(self):
        """Should return empty dict when dividends exist but no income data."""
        client = _make_client()
        client._store["dividends"] = pd.DataFrame({
            "end_date": ["20231231"],
            "cash_div_tax": [0.5],
            "base_share": [100.0],
            "div_proc": ["实施"],
        })
        # No income data
        result = client._get_payout_by_year()
        assert result == {}


class TestHKHoldersYfinance:
    """Test HK holders section via yfinance."""

    def test_holders_with_yfinance_data(self):
        """Should display institutional holders from yfinance."""
        client = _make_client()
        client._yf_available = True

        mock_major = pd.DataFrame({
            0: ["70.50%", "25.30%"],
            1: ["% of Shares Held by Insiders", "% of Shares Held by Institutions"],
        })
        mock_inst = pd.DataFrame({
            "Holder": ["Vanguard Group", "BlackRock"],
            "Shares": [50000000, 40000000],
            "pctHeld": [0.05, 0.04],
            "Date Reported": [pd.Timestamp("2023-09-30"), pd.Timestamp("2023-09-30")],
        })

        mock_ticker = MagicMock()
        mock_ticker.major_holders = mock_major
        mock_ticker.institutional_holders = mock_inst

        with patch("tushare_collector.yf.Ticker", return_value=mock_ticker):
            result = client.get_holders("00700.HK")

        assert "股东与治理" in result
        assert "Vanguard" in result
        assert "BlackRock" in result
        assert "数据来源: yfinance" in result

    def test_holders_yf_unavailable(self):
        """Should show fallback message when yfinance unavailable."""
        client = _make_client()
        client._yf_available = False
        result = client.get_holders("00700.HK")
        assert "yfinance不可用" in result
        assert "§7 待Agent WebSearch补充" in result

    def test_holders_yf_exception(self):
        """Should handle yfinance exception gracefully."""
        client = _make_client()
        client._yf_available = True

        with patch("tushare_collector.yf.Ticker", side_effect=Exception("API error")):
            result = client.get_holders("00700.HK")

        assert "yfinance不可用" in result


# ===== US Stock Support Tests =====


class TestIsUS:
    """Test _is_us static method."""

    def test_us_code(self):
        assert TushareClient._is_us("AAPL.US") is True

    def test_sh_code(self):
        assert TushareClient._is_us("600887.SH") is False

    def test_hk_code(self):
        assert TushareClient._is_us("00700.HK") is False

    def test_case_insensitive(self):
        assert TushareClient._is_us("aapl.us") is True


class TestUSApiCode:
    """Test _us_api_code suffix stripping."""

    def test_strip_us_suffix(self):
        assert TushareClient._us_api_code("AAPL.US") == "AAPL"

    def test_strip_preserves_code(self):
        assert TushareClient._us_api_code("GOOGL.US") == "GOOGL"


class TestUSPivot:
    """Test pivot with US_INCOME_MAP."""

    def test_us_income_pivot(self):
        from tushare_collector import US_INCOME_MAP
        df = pd.DataFrame([
            {"ts_code": "AAPL", "end_date": "20241231", "ind_name": "营业收入", "ind_value": 391035000000},
            {"ts_code": "AAPL", "end_date": "20241231", "ind_name": "净利润", "ind_value": 93736000000},
            {"ts_code": "AAPL", "end_date": "20231231", "ind_name": "营业收入", "ind_value": 383285000000},
            {"ts_code": "AAPL", "end_date": "20231231", "ind_name": "净利润", "ind_value": 96995000000},
        ])
        result = TushareClient._pivot_hk_line_items(df, US_INCOME_MAP)
        assert not result.empty
        assert "revenue" in result.columns
        assert "n_income" in result.columns
        assert len(result) == 2
        row_2024 = result[result["end_date"] == "20241231"].iloc[0]
        assert row_2024["revenue"] == 391035000000


class TestUSBasicInfo:
    """Test US basic info."""

    def test_us_basic_info_output(self):
        client = _make_client()
        mock_basic = _load_mock("us_basic_AAPL.json")
        mock_daily = _load_mock("us_daily_AAPL.json")

        with patch("tushare_collector.time.sleep"):
            client._cached_basic_call = MagicMock(return_value=mock_basic)
            client._cached_us_daily = MagicMock(return_value=mock_daily)
            result = client.get_basic_info("AAPL.US")

        assert "## 1. 基本信息" in result
        assert "Apple" in result
        assert "AAPL.US" in result


class TestUSIncome:
    """Test US income statement."""

    def test_us_income_output(self):
        client = _make_client()
        mock_df = _load_mock("us_income_AAPL.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            client._yf_available = False
            result = client.get_income("AAPL.US")

        assert "## 3. 合并利润表" in result
        assert "百万美元" in result
        assert "2024" in result
        assert "2020" in result
        # AAPL 2024 revenue: 391035000000 / 1e6 = 391,035.00
        assert "391,035.00" in result
        assert "营业收入" in result
        assert "归母净利润" in result

    def test_us_income_empty(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_income("AAPL.US")
        assert "数据缺失" in result

    def test_us_income_parent_placeholder(self):
        client = _make_client()
        result = client.get_income_parent("AAPL.US")
        assert "US GAAP" in result
        assert "3P. 母公司利润表" in result


class TestUSBalanceSheet:
    """Test US balance sheet."""

    def test_us_balance_sheet_output(self):
        client = _make_client()
        mock_df = _load_mock("us_balancesheet_AAPL.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            client._yf_available = False
            result = client.get_balance_sheet("AAPL.US")

        assert "## 4. 合并资产负债表" in result
        assert "百万美元" in result
        assert "现金及等价物" in result
        assert "总资产" in result
        assert "股东权益" in result
        # 2024 total_assets: 364980000000 / 1e6 = 364,980.00
        assert "364,980.00" in result

    def test_us_balance_sheet_parent_placeholder(self):
        client = _make_client()
        result = client.get_balance_sheet_parent("AAPL.US")
        assert "US GAAP" in result
        assert "4P. 母公司资产负债表" in result


class TestUSCashflow:
    """Test US cashflow."""

    def test_us_cashflow_output(self):
        client = _make_client()
        mock_df = _load_mock("us_cashflow_AAPL.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            client._yf_available = False
            result = client.get_cashflow("AAPL.US")

        assert "## 5. 现金流量表" in result
        assert "百万美元" in result
        assert "经营活动现金净额" in result
        assert "自由现金流" in result
        assert "c_pay_to_staff 美股不可用" in result
        # 2024 OCF: 118254000000 / 1e6 = 118,254.00
        assert "118,254.00" in result

    def test_us_cashflow_empty(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_cashflow("AAPL.US")
        assert "数据缺失" in result


class TestUSFinaIndicators:
    """Test US financial indicators."""

    def test_us_fina_indicators_output(self):
        client = _make_client()
        mock_df = _load_mock("us_fina_indicator_AAPL.json")

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_df)
            result = client.get_fina_indicators("AAPL.US")

        assert "## 12. 关键财务指标" in result
        assert "ROE" in result
        assert "毛利率" in result
        assert "160.58" in result  # ROE 2024
        assert "46.28" in result  # gross margin 2024
        assert "PE (TTM)" in result

    def test_us_fina_indicators_empty(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            result = client.get_fina_indicators("AAPL.US")
        assert "数据缺失" in result


class TestUSPlaceholderSections:
    """Test US placeholder sections for unsupported data."""

    def test_us_segments_placeholder(self):
        client = _make_client()
        result = client.get_segments("AAPL.US")
        assert "美股暂不支持" in result

    def test_us_audit_placeholder(self):
        client = _make_client()
        result = client.get_audit("AAPL.US")
        assert "美股暂不支持" in result

    def test_us_repurchase_placeholder(self):
        client = _make_client()
        result = client.get_repurchase("AAPL.US")
        assert "美股暂不支持" in result

    def test_us_pledge_not_applicable(self):
        client = _make_client()
        result = client.get_pledge_stat("AAPL.US")
        assert "不适用" in result
        assert "美股无此制度" in result


class TestUSCurrencyAnnotation:
    """Test USD currency detection and annotation."""

    def test_detect_currency_us(self):
        assert TushareClient._detect_currency("AAPL.US") == "USD"

    def test_detect_currency_a_share(self):
        assert TushareClient._detect_currency("600887.SH") == "CNY"

    def test_us_annotation_in_data_pack(self):
        client = _make_client()

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            client._yf_available = False
            result = client.assemble_data_pack("AAPL.US")

        assert "报表币种: USD" in result
        assert "百万美元" in result


class TestUSAssembly:
    """Test full US data pack assembly."""

    def test_us_assembly_section_list(self):
        """US assembly should skip §3P and §4P."""
        client = _make_client()

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=pd.DataFrame())
            client._yf_available = False
            result = client.assemble_data_pack("AAPL.US")

        assert "# 数据包 — AAPL.US" in result
        assert "报表币种: USD" in result
        assert "百万美元" in result
        # Core sections should be present
        assert "1. 基本信息" in result
        assert "3. 合并利润表" in result
        assert "4. 合并资产负债表" in result
        assert "5. 现金流量表" in result
        assert "11. 十年周线行情" in result
        # §3P and §4P should NOT be present
        assert "3P. 母公司利润表" not in result
        assert "4P. 母公司资产负债表" not in result
        # US warning in §13
        assert "美股数据覆盖有限" in result

    def test_us_assembly_with_data(self):
        """US assembly with mock data should produce complete output."""
        client = _make_client()
        mock_data = {
            "us_basic": _load_mock("us_basic_AAPL.json"),
            "us_income": _load_mock("us_income_AAPL.json"),
            "us_balancesheet": _load_mock("us_balancesheet_AAPL.json"),
            "us_cashflow": _load_mock("us_cashflow_AAPL.json"),
            "us_fina_indicator": _load_mock("us_fina_indicator_AAPL.json"),
            "us_daily": _load_mock("us_daily_AAPL.json"),
        }

        def mock_safe_call(api_name, **kwargs):
            if api_name in mock_data:
                return mock_data[api_name]
            return pd.DataFrame()

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(side_effect=mock_safe_call)
            client._cached_basic_call = MagicMock(side_effect=lambda name, **kw: mock_data.get(name, pd.DataFrame()))
            client._cached_us_daily = MagicMock(return_value=mock_data["us_daily"])
            client._yf_available = False
            result = client.assemble_data_pack("AAPL.US")

        assert "Apple" in result
        assert "391,035.00" in result  # income revenue
        assert "364,980.00" in result  # total assets
        assert "118,254.00" in result  # OCF


class TestYfTickerUS:
    """Test yfinance ticker conversion for US stocks."""

    def test_yf_ticker_us(self):
        assert TushareClient._yf_ticker("AAPL.US") == "AAPL"

    def test_yf_ticker_us_multi_letter(self):
        assert TushareClient._yf_ticker("GOOGL.US") == "GOOGL"


# --- Fiscal Year Detection ---

class TestFiscalYearDetection:
    """Tests for TushareClient._detect_fy_end_month."""

    def test_detect_calendar_year(self):
        """Data with 1231 dates should detect month=12."""
        client = _make_client()
        df = pd.DataFrame([
            {"end_date": "20241231", "revenue": 100},
            {"end_date": "20231231", "revenue": 90},
            {"end_date": "20221231", "revenue": 80},
            {"end_date": "20211231", "revenue": 70},
            {"end_date": "20201231", "revenue": 60},
        ])
        assert client._detect_fy_end_month(df) == 12

    def test_detect_september_fy(self):
        """AAPL-like data with Sep dates should detect month=9."""
        client = _make_client()
        df = pd.DataFrame([
            {"end_date": "20240928", "revenue": 100},
            {"end_date": "20230930", "revenue": 90},
            {"end_date": "20220924", "revenue": 80},
            {"end_date": "20210925", "revenue": 70},
            {"end_date": "20200926", "revenue": 60},
        ])
        assert client._detect_fy_end_month(df) == 9

    def test_detect_march_fy(self):
        """Data with March end dates should detect month=3."""
        client = _make_client()
        df = pd.DataFrame([
            {"end_date": "20240331", "revenue": 100},
            {"end_date": "20230331", "revenue": 90},
            {"end_date": "20220331", "revenue": 80},
        ])
        assert client._detect_fy_end_month(df) == 3

    def test_empty_df_fallback(self):
        """Empty DataFrame should return default month=12."""
        client = _make_client()
        df = pd.DataFrame(columns=["end_date", "revenue"])
        assert client._detect_fy_end_month(df) == 12

    def test_no_end_date_column_fallback(self):
        """DataFrame without end_date column should return default month=12."""
        client = _make_client()
        df = pd.DataFrame([{"revenue": 100}])
        assert client._detect_fy_end_month(df) == 12


class TestPrepareDisplayPeriodsNonCalendarFY:
    """Tests for _prepare_display_periods with non-calendar fiscal years."""

    def test_september_fy_annual_detection(self):
        """Sep FY data: periods ending in 09 should be treated as annual."""
        client = _make_client()
        client._fy_end_month = 9
        df = pd.DataFrame([
            {"end_date": "20240928", "revenue": 100},
            {"end_date": "20230930", "revenue": 90},
            {"end_date": "20220924", "revenue": 80},
            {"end_date": "20210925", "revenue": 70},
            {"end_date": "20200926", "revenue": 60},
        ])
        result_df, labels = client._prepare_display_periods(df)
        assert len(result_df) == 5
        # All should be year labels (annual), not Q3/H1
        for label in labels:
            assert "Q" not in label
            assert "H" not in label

    def test_september_fy_with_interim(self):
        """Sep FY: interim data newer than latest annual should be included."""
        client = _make_client()
        client._fy_end_month = 9
        df = pd.DataFrame([
            {"end_date": "20250331", "revenue": 50},  # interim
            {"end_date": "20240928", "revenue": 100},  # annual
            {"end_date": "20230930", "revenue": 90},   # annual
        ])
        result_df, labels = client._prepare_display_periods(df)
        assert len(result_df) == 3
        assert labels[0] == "2025Q1"
        assert labels[1] == "2024"
        assert labels[2] == "2023"


class TestUnitLabelHelpers:
    """Tests for _unit_label and _price_unit helpers."""

    def test_cny_defaults(self):
        client = _make_client()
        assert client._unit_label() == "百万元"
        assert client._price_unit() == "元"

    def test_hkd_labels(self):
        client = _make_client()
        client._currency = "HKD"
        assert client._unit_label() == "百万港元"
        assert client._price_unit() == "港元"

    def test_usd_labels(self):
        client = _make_client()
        client._currency = "USD"
        assert client._unit_label() == "百万美元"
        assert client._price_unit() == "美元"


class TestUSTotalMvUnit:
    """Tests for US total_mv unit handling in basic info display."""

    def test_us_basic_info_total_mv_divider(self):
        """total_mv should be divided by 1e6 for display as 百万美元."""
        client = _make_client()
        mock_basic = pd.DataFrame([{
            "ts_code": "AAPL", "name": "Apple Inc", "enname": "Apple Inc.",
            "market": "NASDAQ", "list_date": "19801212",
        }])
        mock_daily = pd.DataFrame([{
            "ts_code": "AAPL", "trade_date": "20241231",
            "close": 254.49, "pe": 32.5, "pb": 48.2,
            "total_mv": 3834612000000,  # raw USD
        }])

        with patch("tushare_collector.time.sleep"):
            client._cached_basic_call = MagicMock(return_value=mock_basic)
            client._cached_us_daily = MagicMock(return_value=mock_daily)
            result = client._get_basic_info_us("AAPL.US")

        # Should show ~3,834,612.00 (百万美元), NOT 3,834,612,000,000
        assert "3,834,612.00" in result
        assert "3,834,612,000,000" not in result


class TestUSFYDetectionBeforeYFFill:
    """Verify FY detection runs before yfinance fill in _get_income_us()."""

    def test_fy_detection_before_yf_fill(self):
        """Ensure _detect_fy_end_month is called BEFORE _yf_fill_missing_hk
        so the fallback date match in yfinance fill uses the correct month."""
        client = _make_client()
        client._yf_available = True

        # Tushare returns income data with September end_dates (Chinese ind_names)
        mock_income = pd.DataFrame([
            {"ts_code": "AAPL", "end_date": "20240928", "ind_name": "营业收入", "ind_value": 391035000000},
            {"ts_code": "AAPL", "end_date": "20230930", "ind_name": "营业收入", "ind_value": 383285000000},
        ])

        call_order = []

        original_detect = client._detect_fy_end_month
        original_yf_fill = client._yf_fill_missing_hk

        def tracking_detect(df):
            call_order.append("detect_fy")
            return original_detect(df)

        def tracking_yf_fill(pivoted, ts_code, stmt_type):
            call_order.append("yf_fill")
            return pivoted, False  # skip actual yfinance call

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=mock_income)
            client._detect_fy_end_month = tracking_detect
            client._yf_fill_missing_hk = tracking_yf_fill
            client._get_income_us("AAPL.US")

        assert "detect_fy" in call_order
        assert "yf_fill" in call_order
        assert call_order.index("detect_fy") < call_order.index("yf_fill"), \
            "FY detection must run before yfinance fill"

    def test_yf_fill_uses_detected_fy_month(self):
        """After FY detection sets _fy_end_month=9, yfinance fallback match
        should succeed for dates like 20240928 (month 09 == fy_end_month 9)."""
        client = _make_client()
        client._yf_available = True

        # Simulate: Tushare has revenue but missing operate_profit
        pivoted = pd.DataFrame([
            {"end_date": "20240928", "revenue": 391035.0, "operate_profit": float("nan")},
            {"end_date": "20230930", "revenue": 383285.0, "operate_profit": 114301.0},
        ])

        # Set fy_end_month=9 (as would be detected from September end_dates)
        client._fy_end_month = 9

        # Mock yfinance with September 30 dates
        yf_income = pd.DataFrame(
            {"2024-09-30": [120000.0], "2023-09-30": [114301.0]},
            index=["Operating Income"],
        )
        yf_income.columns = pd.to_datetime(yf_income.columns)

        mock_ticker = MagicMock()
        mock_ticker.income_stmt = yf_income

        with patch("tushare_collector.yf") as mock_yf:
            mock_yf.Ticker.return_value = mock_ticker
            filled, yf_used = client._yf_fill_missing_hk(pivoted, "AAPL.US", "income")

        assert yf_used
        # 20240928 should have been matched to 2024-09-30 via fallback
        assert filled.iloc[0]["operate_profit"] == 120000.0
