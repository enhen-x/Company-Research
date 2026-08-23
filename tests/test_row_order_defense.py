"""Regression tests: broker VIP relays may return price rows oldest-first.

The collector must not assume newest-first API ordering — get_basic_info and
get_market_data must sort by trade_date/end_date descending before taking
iloc[0] as "latest". See 2026-07-04 incident: VIP daily_basic returned rows
ascending from the 1996 IPO, corrupting §1 price/market cap and §2 latest close.
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from tushare_collector import TushareClient  # noqa: E402


def _make_client():
    with patch("tushare_collector.ts") as mock_ts:
        mock_ts.pro_api.return_value = MagicMock()
        client = TushareClient("test_token")
    client._cache_dir = os.path.join("/tmp", "row_order_test_cache")
    client._cache_enabled = False
    return client


def _ascending_daily_basic():
    """Simulate a VIP relay: oldest row first (IPO era), newest last."""
    return pd.DataFrame([
        {"ts_code": "600887.SH", "trade_date": "19960312", "close": 8.39,
         "pe_ttm": 26.08, "pb": 8.48, "total_mv": 42087.12, "circ_mv": 15102.0,
         "total_share": 5017.0, "float_share": 1800.0},
        {"ts_code": "600887.SH", "trade_date": "20260703", "close": 24.60,
         "pe_ttm": 15.20, "pb": 2.95, "total_mv": 15658770.31, "circ_mv": 15496389.8,
         "total_share": 6366.0, "float_share": 6300.0},
    ])


def _ascending_daily():
    return pd.DataFrame([
        {"ts_code": "600887.SH", "trade_date": "20250704", "open": 27.5, "high": 28.0,
         "low": 27.3, "close": 27.77, "vol": 500000, "amount": 1.0e6},
        {"ts_code": "600887.SH", "trade_date": "20260703", "open": 24.4, "high": 24.8,
         "low": 23.9, "close": 24.60, "vol": 520000, "amount": 1.1e6},
    ])


class TestAscendingRowDefense:
    def test_basic_info_uses_latest_daily_basic_row(self):
        client = _make_client()
        stock_basic = pd.DataFrame([{
            "ts_code": "600887.SH", "name": "伊利股份", "fullname": "内蒙古伊利实业集团股份有限公司",
            "industry": "乳制品", "area": "内蒙", "exchange": "SSE", "list_date": "19960312",
        }])

        def fake_call(api_name, **kwargs):
            if api_name == "daily_basic":
                return _ascending_daily_basic()
            return stock_basic

        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(side_effect=fake_call)
            client._cached_basic_call = MagicMock(return_value=stock_basic)
            result = client.get_basic_info("600887.SH")

        assert "24.6" in result, "should use the NEWEST close, not the IPO-era row"
        assert "8.39" not in result
        # store must also be newest-first for downstream §17 consumers
        stored = client._store["basic_info"]
        assert str(stored.iloc[0]["trade_date"]) == "20260703"

    def test_market_data_latest_close_newest_row(self):
        client = _make_client()
        with patch("tushare_collector.time.sleep"):
            client._safe_call = MagicMock(return_value=_ascending_daily())
            result = client.get_market_data("600887.SH")

        assert "24.60" in result, "最新收盘价 must come from the newest trade_date"
        assert "27.77" not in result.split("52周")[0], \
            "year-old close must not appear as 最新收盘价"
