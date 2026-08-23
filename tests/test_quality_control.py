"""Tests for scripts/quality_control.py — 杠杆1 deterministic pre-computation."""

import os

import pytest

import quality_control as qc
from quality_control import (
    to_yi, multi_year_stats, payout_ratio, yoy_pct, pe_valuation,
    parse_sections, parse_matrix, parse_kv, find_item, build_report, main,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_data_pack_market.md")


@pytest.fixture(scope="module")
def pack_text():
    with open(FIXTURE, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def sections(pack_text):
    return parse_sections(pack_text)


# ── pure functions ──────────────────────────────────────────────────

class TestPureFunctions:
    def test_to_yi(self):
        assert to_yi(50000.0) == 500.0          # 百万 → 亿 (÷100)
        assert to_yi(89175.18) == pytest.approx(891.75, abs=0.01)

    def test_to_yi_none(self):
        assert to_yi(None) is None

    def test_multi_year_stats(self):
        st = multi_year_stats([500.0, 400.0, 300.0])
        assert st["mean"] == 400.0
        assert st["median"] == 400.0
        assert st["n"] == 3

    def test_multi_year_stats_none_tolerant(self):
        st = multi_year_stats([500.0, None, 300.0])
        assert st["mean"] == 400.0
        assert st["n"] == 2

    def test_multi_year_stats_all_none(self):
        st = multi_year_stats([None, None])
        assert st == {"mean": None, "median": None, "n": 0}

    def test_payout_ratio(self):
        # the reference bug: 6000/10000 = 60%, and the 111.75% 五粮液 case
        assert payout_ratio(6000.0, 10000.0) == 60.0
        assert payout_ratio(10006.79, 8954.26) == pytest.approx(111.75, abs=0.01)

    def test_payout_ratio_zero_np(self):
        assert payout_ratio(6000.0, 0) is None
        assert payout_ratio(None, 10000.0) is None

    def test_yoy_pct(self):
        assert yoy_pct(50000.0, 40000.0) == 25.0
        assert yoy_pct(40528.51, 89175.18) == pytest.approx(-54.55, abs=0.01)

    def test_yoy_pct_zero_prev(self):
        assert yoy_pct(100.0, 0) is None
        assert yoy_pct(None, 40000.0) is None

    def test_pe_valuation(self):
        assert pe_valuation(2.0, 20.0, 0.9) == 36.0
        assert pe_valuation(None, 20.0, 0.9) is None


# ── parser ──────────────────────────────────────────────────────────

class TestParser:
    def test_parse_sections_keys(self, sections):
        for token in ("1", "3", "4", "5", "6", "12"):
            assert token in sections

    def test_parse_matrix_income(self, sections):
        cols, data = parse_matrix(sections["3"])
        assert "2024" in cols
        assert data["营业收入"]["2024"] == 50000.0
        assert data["归母净利润"]["2024"] == 10000.0

    def test_parse_kv_basic(self, sections):
        kv = parse_kv(sections["1"])
        assert kv["当前价格"] == "100.00"
        assert kv["股票代码"] == "TEST.SZ"

    def test_find_item_prefix(self, sections):
        _, data = parse_matrix(sections["5"])
        assert find_item(data, "经营活动现金流", "OCF") is not None
        assert find_item(data, "自由现金流", "FCF") is not None

    def test_dividends_aggregated_by_year(self, sections):
        agg = qc._dividends_by_year(sections["6"])
        assert agg["2024"] == 6000.0   # 4000 + 2000 summed
        assert agg["2023"] == 4800.0


# ── end-to-end report ───────────────────────────────────────────────

class TestBuildReport:
    def test_cm1_yi_conversion(self, sections):
        report = build_report(sections, [10, 20], [1.0, 0.9])
        assert "CM§1" in report
        assert "891" not in report          # sanity: no 五粮液 leakage
        assert "500.00" in report           # 营收 2024 = 500 亿

    def test_cm4_payout_60pct(self, sections):
        report = build_report(sections, [10], [1.0])
        assert "CM§4" in report
        assert "60.00" in report            # 2024 payout = 6000/10000

    def test_cm2_yoy_present(self, sections):
        report = build_report(sections, [10], [1.0])
        assert "CM§2" in report
        assert "25.00" in report            # 营收 2024 vs 2023 = 25%

    def test_cm5_pe_grid(self, sections):
        report = build_report(sections, [20], [0.9])
        assert "CM§5" in report
        assert "36.00" in report            # EPS 2.0 × PE 20 × 0.9

    def test_header_warning_and_no_recompute(self, sections):
        report = build_report(sections, [10], [1.0])
        assert "禁止重算" in report
        assert "src: CM§N" in report

    def test_graceful_degradation_missing_section(self, sections):
        subset = {k: v for k, v in sections.items() if k != "6"}
        report = build_report(subset, [10], [1.0])
        assert "CM§4 跳过" in report         # missing §6 → ⚠️ skip line


# ── CLI ─────────────────────────────────────────────────────────────

class TestCLI:
    def test_main_success(self, tmp_path):
        out = tmp_path / "computed_metrics.md"
        rc = main(["--input", FIXTURE, "--output", str(out)])
        assert rc == 0
        assert out.exists()
        assert "CM§1" in out.read_text(encoding="utf-8")

    def test_main_missing_input(self, tmp_path):
        rc = main(["--input", str(tmp_path / "nope.md"),
                   "--output", str(tmp_path / "o.md")])
        assert rc == 2

    def test_main_custom_bands(self, tmp_path):
        out = tmp_path / "cm.md"
        rc = main(["--input", FIXTURE, "--output", str(out),
                   "--pe-bands", "15", "--discounts", "0.8"])
        assert rc == 0
        # EPS 2.0 × 15 × 0.8 = 24.00
        assert "24.00" in out.read_text(encoding="utf-8")
