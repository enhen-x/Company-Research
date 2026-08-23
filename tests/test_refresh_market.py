"""Tests for --refresh-market feature (selective section refresh)."""

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


def _make_client():
    """Create a TushareClient with mocked tushare module."""
    with patch("tushare_collector.ts") as mock_ts:
        mock_ts.pro_api.return_value = MagicMock()
        from tushare_collector import TushareClient
        client = TushareClient("test_token")
    client._cache_dir = tempfile.mkdtemp(prefix="tushare_test_cache_")
    return client


def _build_minimal_datapack(timestamp=None, ts_code="600887.SH", include_parent=True):
    """Build a minimal data_pack_market.md for testing."""
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    parent_sections = ""
    if include_parent:
        parent_sections = """
## 3P. 母公司利润表

| 项目 (百万元) | 2024 | 2023 |
|:-----|-----:|-----:|
| 营业收入 | 80,000.00 | 75,000.00 |

## 4P. 母公司资产负债表

| 项目 | 2024 |
|:-----|-----:|
| 总资产 | 150,000.00 |

"""

    return f"""# 数据包 — {ts_code}

*生成时间: {timestamp}*
*数据来源: Tushare Pro*
*金额单位: 百万元 (除特殊标注)*

---

## 1. 基本信息

| 项目 | 内容 |
|:-----|:-----|
| 股票代码 | {ts_code} |
| 市值 | 100,000.00 |

## 2. 市场行情

| 指标 | 数值 |
|:-----|:-----|
| 最新收盘价 | 25.00 |

## 3. 合并利润表

| 项目 (百万元) | 2024 | 2023 |
|:-----|-----:|-----:|
| 营业收入 | 120,000.00 | 110,000.00 |

{parent_sections}## 4. 合并资产负债表

| 项目 (百万元) | 2024 | 2023 |
|:-----|-----:|-----:|
| 总资产 | 200,000.00 | 190,000.00 |

## 5. 现金流量表

| 项目 (百万元) | 2024 | 2023 |
|:-----|-----:|-----:|
| 经营活动 | 15,000.00 | 14,000.00 |

## 6. 分红历史

| 年份 | DPS |
|:-----|-----:|
| 2024 | 1.20 |

## 7. 股东与治理

| 排名 | 股东 |
|:-----|:-----|
| 1 | 控股集团 |

## 9. 主营业务构成

| 业务 | 收入占比 |
|:-----|--------:|
| 主业 | 95% |

## 11. 十年周线行情

| 年份 | 最高 | 最低 |
|:-----|-----:|-----:|
| 2024 | 32.00 | 22.00 |

## 12. 关键财务指标

| 指标 | 2024 |
|:-----|-----:|
| ROE | 15.2% |

## 15. 股票回购

无回购记录。

## 16. 股权质押

质押比例: 5.2%

## 14. 无风险利率

| 日期 | 十年期国债收益率 |
|:-----|---------------:|
| 2026-04-01 | 2.85% |

## 8. 行业与竞争

*[§8 待Agent WebSearch补充]*

## 10. 管理层讨论与分析 (MD&A)

*[§10 待Agent WebSearch补充]*

## 17. 衍生指标（Python 预计算）

> 以下指标基于 §1-§16 原始数据确定性计算。

### 17.1 财务趋势

| 指标 | 2024 |
|:-----|-----:|
| 营收增速 | 9.1% |

## 13. 风险警示

### 13.1 脚本自动检测

未检测到异常。

### 13.2 Agent WebSearch 补充

*[§13.2 待Agent WebSearch补充]*

---
*共 14/14 个数据板块成功获取*
"""


# =========================================================================
# TestParseSections
# =========================================================================

class TestParseSections:
    """Test _parse_sections() markdown splitting."""

    def test_parse_a_share_full(self):
        content = _build_minimal_datapack()
        client = _make_client()
        header, sections, footer = client._parse_sections(content)

        keys = [k for k, _ in sections]
        for expected in ["1", "2", "3", "3P", "4", "4P", "5", "6", "7",
                         "9", "11", "12", "15", "16", "14", "8", "10", "17", "13"]:
            assert expected in keys, f"Missing section {expected}"

    def test_parse_hk_pack(self):
        content = _build_minimal_datapack(ts_code="00700.HK", include_parent=False)
        client = _make_client()
        _, sections, _ = client._parse_sections(content)

        keys = [k for k, _ in sections]
        assert "3P" not in keys
        assert "4P" not in keys
        assert "3" in keys
        assert "4" in keys

    def test_parse_header_extraction(self):
        content = _build_minimal_datapack()
        client = _make_client()
        header, _, _ = client._parse_sections(content)

        assert "# 数据包" in header
        assert "生成时间" in header
        assert "百万元" in header

    def test_parse_section_content_integrity(self):
        content = _build_minimal_datapack()
        client = _make_client()
        _, sections, _ = client._parse_sections(content)

        section_map = dict(sections)
        # §3 should contain table data
        assert "120,000.00" in section_map["3"]
        # §13 should contain both sub-sections
        assert "13.1" in section_map["13"]
        assert "13.2" in section_map["13"]

    def test_parse_empty_or_malformed(self):
        client = _make_client()

        # Empty string
        header, sections, footer = client._parse_sections("")
        assert sections == []

        # No section headers
        header, sections, footer = client._parse_sections("just some text\nno headers")
        assert sections == []
        assert "just some text" in header


# =========================================================================
# TestCheckStaleness
# =========================================================================

class TestCheckStaleness:
    """Test _check_staleness() timestamp parsing and age calculation."""

    def test_fresh_file(self):
        today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        content = f"*生成时间: {today}*\nrest of file"
        client = _make_client()
        assert client._check_staleness(content) == 0

    def test_stale_file(self):
        eight_days_ago = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
        content = f"*生成时间: {eight_days_ago}*\nrest of file"
        client = _make_client()
        assert client._check_staleness(content) == 8

    def test_missing_timestamp(self):
        content = "no timestamp here\njust data"
        client = _make_client()
        assert client._check_staleness(content) == 999

    def test_malformed_timestamp(self):
        content = "*生成时间: not-a-date*\nrest"
        client = _make_client()
        assert client._check_staleness(content) == 999


# =========================================================================
# TestRefreshMarketSections
# =========================================================================

class TestRefreshMarketSections:
    """Test refresh_market_sections() selective update."""

    def _setup_client_with_mocks(self):
        client = _make_client()
        client._detect_currency = MagicMock(return_value="CNY")
        client._is_hk = MagicMock(return_value=False)
        client._is_us = MagicMock(return_value=False)
        client.get_basic_info = MagicMock(
            return_value="## 1. 基本信息\n\n| 项目 | 内容 |\n|:-----|:-----|\n| 市值 | 200,000.00 |\n"
        )
        client.get_market_data = MagicMock(
            return_value="## 2. 市场行情\n\n| 指标 | 数值 |\n|:-----|:-----|\n| 最新收盘价 | 30.00 |\n"
        )
        client.get_weekly_prices = MagicMock(
            return_value="## 11. 十年周线行情\n\n| 年份 | 最高 |\n|:-----|-----:|\n| 2024 | 35.00 |\n"
        )
        client.get_risk_free_rate = MagicMock(
            return_value="## 14. 无风险利率\n\n| 日期 | 收益率 |\n|:-----|------:|\n| 2026-04-05 | 2.90% |\n"
        )
        return client

    def test_sections_1_2_11_14_updated(self):
        client = self._setup_client_with_mocks()
        existing = _build_minimal_datapack()
        result = client.refresh_market_sections("600887.SH", existing)

        assert "200,000.00" in result  # new §1 market cap
        assert "30.00" in result       # new §2 close price
        assert "35.00" in result       # new §11 high
        assert "2.90%" in result       # new §14 rate

    def test_sections_3_to_17_preserved(self):
        client = self._setup_client_with_mocks()
        existing = _build_minimal_datapack()
        result = client.refresh_market_sections("600887.SH", existing)

        # These should be unchanged from original
        assert "120,000.00" in result   # §3 revenue
        assert "80,000.00" in result    # §3P parent revenue
        assert "200,000.00" not in _build_minimal_datapack() or "200,000.00" in result  # new §1 is different
        assert "15,000.00" in result    # §5 cashflow
        assert "控股集团" in result      # §7 shareholder
        assert "9.1%" in result         # §17 derived metric
        assert "13.1" in result         # §13 warnings sub-section

    def test_header_timestamp_updated(self):
        client = self._setup_client_with_mocks()
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        existing = _build_minimal_datapack(timestamp=yesterday)

        result = client.refresh_market_sections("600887.SH", existing)
        today_str = datetime.now().strftime("%Y-%m-%d")
        assert today_str in result

    def test_refresh_mode_annotation(self):
        client = self._setup_client_with_mocks()
        existing = _build_minimal_datapack()
        result = client.refresh_market_sections("600887.SH", existing)

        assert "--refresh-market" in result
        assert "刷新模式" in result

    def test_hk_stock_refresh(self):
        client = self._setup_client_with_mocks()
        client._detect_currency = MagicMock(return_value="HKD")
        existing = _build_minimal_datapack(ts_code="00700.HK", include_parent=False)

        result = client.refresh_market_sections("00700.HK", existing)

        # Refreshed sections present
        assert "200,000.00" in result  # new §1
        assert "30.00" in result       # new §2
        # No parent sections
        assert "3P." not in result
        assert "4P." not in result

    def test_partial_failure_graceful(self):
        client = self._setup_client_with_mocks()
        # §11 fails
        client.get_weekly_prices = MagicMock(side_effect=Exception("API timeout"))
        existing = _build_minimal_datapack()

        result = client.refresh_market_sections("600887.SH", existing)

        # §11 should retain old content
        assert "32.00" in result   # old §11 high preserved
        # §1, §2, §14 should be refreshed
        assert "200,000.00" in result  # new §1
        assert "30.00" in result       # new §2
        assert "2.90%" in result       # new §14


# =========================================================================
# TestReassemble
# =========================================================================

class TestReassemble:
    """Test parse -> reassemble roundtrip."""

    def test_section_order_a_share(self):
        content = _build_minimal_datapack()
        client = _make_client()
        header, sections, footer = client._parse_sections(content)

        keys = [k for k, _ in sections]
        # Verify order: 1 before 2, 2 before 3, 3 before 3P, etc.
        assert keys.index("1") < keys.index("2")
        assert keys.index("2") < keys.index("3")
        assert keys.index("3") < keys.index("3P")
        assert keys.index("3P") < keys.index("4")
        assert keys.index("16") < keys.index("14")  # §14 comes after §16
        assert keys.index("14") < keys.index("8")
        assert keys.index("17") < keys.index("13")   # §13 is last

    def test_section_order_hk(self):
        content = _build_minimal_datapack(ts_code="00700.HK", include_parent=False)
        client = _make_client()
        _, sections, _ = client._parse_sections(content)

        keys = [k for k, _ in sections]
        assert "3P" not in keys
        assert "4P" not in keys
        assert keys.index("3") < keys.index("4")

    def test_roundtrip_integrity(self):
        """Parse then reassemble — no content loss."""
        content = _build_minimal_datapack()
        client = _make_client()
        header, sections, footer = client._parse_sections(content)

        # Reassemble manually
        parts = [header]
        for _, text in sections:
            parts.append(text)
        result = "".join(parts)
        if footer:
            result = result.rstrip("\n") + footer

        # Key content should survive roundtrip
        assert "120,000.00" in result   # §3
        assert "25.00" in result        # §2
        assert "2.85%" in result        # §14
        assert "13.2" in result         # §13 sub-section
        assert "9.1%" in result         # §17


# =========================================================================
# TestRefreshMarketCLI
# =========================================================================

class TestRefreshMarketCLI:
    """Test CLI --refresh-market flag behavior."""

    def test_cli_flag_parsed(self):
        from tushare_collector import parse_args
        with patch("sys.argv", ["prog", "--code", "600887", "--refresh-market"]):
            args = parse_args()
        assert args.refresh_market is True

    def test_cli_flag_default_false(self):
        from tushare_collector import parse_args
        with patch("sys.argv", ["prog", "--code", "600887"]):
            args = parse_args()
        assert args.refresh_market is False

    def test_file_not_exists_fallback(self, tmp_path):
        """When --refresh-market but file doesn't exist, falls back to full collection."""
        output = tmp_path / "nonexistent.md"

        with patch("tushare_collector.ts") as mock_ts, \
             patch("tushare_collector.get_token", return_value="tok"), \
             patch("tushare_collector.time.sleep"), \
             patch("sys.argv", ["prog", "--code", "600887.SH",
                                "--refresh-market", "--output", str(output)]):
            mock_ts.pro_api.return_value = MagicMock()
            from tushare_collector import TushareClient, main

            with patch.object(TushareClient, "assemble_data_pack", return_value="full") as mock_full, \
                 patch.object(TushareClient, "refresh_market_sections") as mock_refresh:
                main()

            mock_full.assert_called_once()
            mock_refresh.assert_not_called()

    def test_stale_file_fallback(self, tmp_path):
        """When data pack is >7 days old, falls back to full collection."""
        output = tmp_path / "data_pack_market.md"
        old_ts = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        output.write_text(_build_minimal_datapack(timestamp=old_ts), encoding="utf-8")

        with patch("tushare_collector.ts") as mock_ts, \
             patch("tushare_collector.get_token", return_value="tok"), \
             patch("tushare_collector.time.sleep"), \
             patch("sys.argv", ["prog", "--code", "600887.SH",
                                "--refresh-market", "--output", str(output)]):
            mock_ts.pro_api.return_value = MagicMock()
            from tushare_collector import TushareClient, main

            with patch.object(TushareClient, "assemble_data_pack", return_value="full") as mock_full, \
                 patch.object(TushareClient, "refresh_market_sections") as mock_refresh:
                main()

            mock_full.assert_called_once()
            mock_refresh.assert_not_called()

    def test_fresh_file_refresh(self, tmp_path):
        """When data pack is fresh (<7 days), uses refresh mode."""
        output = tmp_path / "data_pack_market.md"
        output.write_text(_build_minimal_datapack(), encoding="utf-8")

        with patch("tushare_collector.ts") as mock_ts, \
             patch("tushare_collector.get_token", return_value="tok"), \
             patch("tushare_collector.time.sleep"), \
             patch("sys.argv", ["prog", "--code", "600887.SH",
                                "--refresh-market", "--output", str(output)]):
            mock_ts.pro_api.return_value = MagicMock()
            from tushare_collector import TushareClient, main

            with patch.object(TushareClient, "assemble_data_pack") as mock_full, \
                 patch.object(TushareClient, "refresh_market_sections", return_value="refreshed") as mock_refresh:
                main()

            mock_refresh.assert_called_once()
            mock_full.assert_not_called()
