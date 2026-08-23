"""Tests for §17.10-§17.13 pre-computation grids (Phase 3).

Covers:
- §17.10 payout M three-method cross-check + recommendation + filler-error fixture
- §17.11 penetrating return-rate grid (R*, GG, HH, Δc, R_eff, 目标买入价, ★, II, O note, HK Q cols)
- §17.12 standalone G→维持性Capex grid (12 rows, OE/H identities, bands)
- §17.13 λ revenue sensitivity (echo, scenario rows, critical multiple, degraded path)
- whole-pipeline: compute_derived_metrics contains 17.10-17.13; graceful empty store

Helper pattern (_load_mock / _make_client / store building) copied from
test_derived_metrics.py — kept local so this file is self-contained.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pandas as pd

from tushare_collector import TushareClient

MOCK_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "mock_tushare_responses")


def _load_mock(filename: str) -> pd.DataFrame:
    with open(os.path.join(MOCK_DIR, filename)) as f:
        data = json.load(f)
    if isinstance(data, list):
        return pd.DataFrame(data)
    return pd.DataFrame([data])


def _make_client() -> TushareClient:
    with patch("tushare_collector.ts") as mock_ts:
        mock_ts.pro_api.return_value = MagicMock()
        client = TushareClient("test_token")
    return client


def _base_store(dividend_file: str = "dividend.json") -> dict:
    income_df = _load_mock("income.json").sort_values("end_date", ascending=False)
    bs_df = _load_mock("balancesheet.json").sort_values("end_date", ascending=False)
    cf_df = _load_mock("cashflow.json").sort_values("end_date", ascending=False)
    div_df = _load_mock(dividend_file).sort_values("end_date", ascending=False)
    rf_df = _load_mock("yc_cb.json").sort_values("trade_date", ascending=False)
    return {
        "income": income_df,
        "balance_sheet": bs_df,
        "cashflow": cf_df,
        "dividends": div_df,
        "risk_free_rate": rf_df,
    }


def _make_grid_client(dividend_file: str = "dividend.json",
                      with_basic: bool = True) -> TushareClient:
    """Client with full store, factor3 chain + §17.10 crosscheck already run."""
    client = _make_client()
    client._store = _base_store(dividend_file)
    if with_basic:
        client._store["basic_info"] = _load_mock("daily_basic.json")
    # Run factor3 chain (populates factor3_sensitivity incl. λ) then §17.10
    client._compute_factor3_step1()
    client._compute_factor3_step4()
    client._compute_factor3_sensitivity_base()
    client._compute_payout_crosscheck()
    return client


# ===== §17.10 payout crosscheck =====


class TestPayoutCrosscheck:
    def test_headers(self):
        client = _make_grid_client()
        result = client._compute_payout_crosscheck()
        assert result is not None
        assert "17.10 支付率 M 三重校验" in result
        assert "法1 §6 DPS/EPS" in result
        assert "法2 §5 分配现金/归母" in result
        assert "法3 §17.1 口径" in result

    def test_per_year_values(self):
        """法2 2024 = 5800/10120 = 57.31%; 法1 2024 = 0.97/1.59 = 61.01%."""
        client = _make_grid_client()
        result = client._compute_payout_crosscheck()
        assert "57.31%" in result  # 法2 2024
        assert "61.01%" in result  # 法1 2024

    def test_three_year_means(self):
        """m1=58.26, m2=54.20, m3=58.08 (3yr means of 2024/2023/2022)."""
        client = _make_grid_client()
        result = client._compute_payout_crosscheck()
        pc = client._store["payout_crosscheck"]
        assert round(pc["m1"], 2) == 58.26
        assert round(pc["m2"], 2) == 54.20
        assert round(pc["m3"], 2) == 58.08

    def test_recommendation_default_is_method3(self):
        """With consistent methods (<15% dev), M_rec = 法3."""
        client = _make_grid_client()
        client._compute_payout_crosscheck()
        pc = client._store["payout_crosscheck"]
        assert pc["m_rec_label"] == "法3"
        assert round(pc["m_rec"], 2) == 58.08
        assert "M_rec = 58.08%（法3）" in client._compute_payout_crosscheck()

    def test_filler_error_fixture(self):
        """Identical A-share DPS across ≥3 years → filler warning + M_rec=法2."""
        client = _make_grid_client(dividend_file="dividend_identical.json")
        result = client._compute_payout_crosscheck()
        pc = client._store["payout_crosscheck"]
        assert pc["m_rec_label"] == "法2"
        assert any("填充" in w for w in pc["warnings"])
        assert "填充" in result

    def test_returns_none_no_data(self):
        client = _make_client()
        assert client._compute_payout_crosscheck() is None


# ===== §17.11 penetration grid =====


class TestPenetrationGrid:
    def test_headers_and_ii(self):
        client = _make_grid_client()
        result = client._compute_penetration_grid("600887.SH")
        assert result is not None
        assert "17.11 穿透回报率网格" in result
        assert "表A：主口径穿透回报率 R*" in result
        assert "表B：现金校验口径 GG" in result
        # II = max(3.5, 2.315+2) = 4.315 -> renders 4.31
        assert "门槛 II = 4.31%" in result

    def test_table_a_r_star_cell(self):
        """R*(m_rec=58.08%, Q=0, k=0.8) = 10120×0.8×0.5808/175000×100 = 2.69%."""
        client = _make_grid_client()
        result = client._compute_penetration_grid("600887.SH")
        assert "2.69%" in result

    def test_table_b_gg_and_target(self):
        """AA_2y×法3 Q0: GG=5.17%; Δc=R*−GG=2.69−5.17=−2.49<2 → R_eff=R*=2.69%;
        target=27.5×2.6869/4.315=17.12（AA_2y 与 AA_all 行同值）。"""
        client = _make_grid_client()
        result = client._compute_penetration_grid("600887.SH")
        assert "5.17%" in result
        assert "-2.49" in result  # Δc AA_2y×法3
        assert "17.12" in result  # 目标买入价（R_eff 口径，AA_2y×法3 与 AA_all×法3 同值）

    def test_target_buy_price_identity(self):
        """目标买入价 = close × R_eff / II (hand-recompute AA_2y×法3, k=0.8)."""
        client = _make_grid_client()
        client._compute_penetration_grid("600887.SH")
        # rebuild the exact numbers
        close = 27.50
        mkt_cap = 175000.0
        c = 10120.0
        aa_2y = 15588.0
        m_rec = client._store["payout_crosscheck"]["m_rec"]
        _, ii = client._get_rf_ii("600887.SH")
        gg = aa_2y * m_rec / 100 / mkt_cap * 100
        r_star = c * 0.8 * m_rec / 100 / mkt_cap * 100
        r_eff = gg if (r_star - gg) >= 2.0 else r_star
        target = close * r_eff / ii
        assert round(target, 2) == 17.12

    def test_hh_consistency(self):
        """HH(账面-现金偏差, AA_2y×法3) = R(法3,Q0) − GG(AA_2y,法3,Q0) = 3.36 − 5.17 = -1.81."""
        client = _make_grid_client()
        result = client._compute_penetration_grid("600887.SH")
        assert "-1.81" in result

    def test_star_marker_on_recommended(self):
        client = _make_grid_client()
        result = client._compute_penetration_grid("600887.SH")
        assert "★" in result
        # ★ attached to 法3 (recommended), both table A and B
        assert "法3 58.08% ★" in result

    def test_o_note(self):
        """O=0 default with additive-correction note (+100/mktcap×100)."""
        client = _make_grid_client()
        result = client._compute_penetration_grid("600887.SH")
        assert "O = 0（默认）" in result
        # 100/175000*100 = 0.0571
        assert "0.0571 pct" in result

    def test_supersedes_footnote(self):
        client = _make_grid_client()
        result = client._compute_penetration_grid("600887.SH")
        assert "税前" in result
        assert "以本节 §17.11 为准" in result

    def test_none_without_factor3_sensitivity(self):
        client = _make_client()
        client._store = {"income": _load_mock("income.json"),
                         "basic_info": _load_mock("daily_basic.json")}
        assert client._compute_penetration_grid("600887.SH") is None

    def test_none_without_basic_info(self):
        client = _make_grid_client(with_basic=False)
        assert client._compute_penetration_grid("600887.SH") is None

    def test_hk_q_columns(self):
        """HK unique tax rates → Q columns {28, 20}."""
        client = _make_client()
        client._currency = "HKD"
        client._store = _base_store()
        client._store["basic_info"] = pd.DataFrame([
            {"close": 27.50, "total_market_cap": 175000.0}])
        client._compute_factor3_step1()
        client._compute_factor3_step4()
        client._compute_factor3_sensitivity_base()
        client._compute_payout_crosscheck()
        result = client._compute_penetration_grid("00700.HK")
        assert result is not None
        assert "28%" in result
        assert "20%" in result


# ===== §17.12 G grid =====


class TestGGrid:
    def test_headers(self):
        client = _make_grid_client()
        result = client._compute_g_grid("600887.SH")
        assert result is not None
        assert "17.12 G 系数网格" in result
        assert "LLM 仅选行，禁止自算" in result

    def test_twelve_rows(self):
        """G = 0.7 … 1.8 → 12 rows."""
        client = _make_grid_client()
        result = client._compute_g_grid("600887.SH")
        for g in ["0.7", "1.0", "1.4", "1.8"]:
            assert f"| {g} |" in result
        # count data rows: 12 lines starting with "| 0." or "| 1."
        data_rows = [ln for ln in result.splitlines()
                     if ln.startswith("| 0.") or ln.startswith("| 1.")]
        assert len(data_rows) == 12

    def test_oe_equals_c_at_g_one(self):
        """OE = C + D − D×1.0 = C = 10,120.00 at G=1.0."""
        client = _make_grid_client()
        result = client._compute_g_grid("600887.SH")
        g10_row = [ln for ln in result.splitlines() if ln.startswith("| 1.0 |")][0]
        assert "10,120.00" in g10_row  # OE at G=1.0 == C

    def test_h_at_g_max(self):
        """H = D×1.8 = 3200×1.8 = 5,760.00 at G=1.8."""
        client = _make_grid_client()
        result = client._compute_g_grid("600887.SH")
        g18_row = [ln for ln in result.splitlines() if ln.startswith("| 1.8 |")][0]
        assert "5,760.00" in g18_row

    def test_band_labels(self):
        client = _make_grid_client()
        result = client._compute_g_grid("600887.SH")
        for band in ["轻", "轻中", "中", "中重", "重"]:
            assert band in result

    def test_f_reference(self):
        """F (Capex/D&A 5yr median) = 2.48."""
        client = _make_grid_client()
        result = client._compute_g_grid("600887.SH")
        assert "2.48" in result

    def test_none_without_cashflow(self):
        client = _make_client()
        client._store = {"income": _load_mock("income.json").sort_values(
            "end_date", ascending=False)}
        assert client._compute_g_grid("600887.SH") is None


# ===== §17.13 revenue sensitivity =====


class TestRevenueSensitivity:
    def test_lambda_echo(self):
        """λ = 0.1520 echoed."""
        client = _make_grid_client()
        result = client._compute_revenue_sensitivity("600887.SH")
        assert result is not None
        assert "17.13 收入敏感性" in result
        assert "0.1520" in result

    def test_scenario_rows(self):
        """GG(0.9×) = 4.57%; GG(1.0×) = 5.17%."""
        client = _make_grid_client()
        result = client._compute_revenue_sensitivity("600887.SH")
        assert "5.17%" in result  # 1.0×
        assert "4.57%" in result  # 0.9×
        for k in ["1.0×", "0.9×", "0.8×", "0.7×"]:
            assert k in result

    def test_critical_multiple(self):
        """k* solving GG(k)=II = 0.86."""
        client = _make_grid_client()
        result = client._compute_revenue_sensitivity("600887.SH")
        assert "临界收入倍数 k* = 0.86" in result

    def test_default_combo_note(self):
        client = _make_grid_client()
        result = client._compute_revenue_sensitivity("600887.SH")
        assert "默认组合" in result
        assert "比例缩放" in result

    def test_degraded_when_lambda_missing(self):
        client = _make_grid_client()
        client._store["factor3_sensitivity"]["lambda_median"] = None
        result = client._compute_revenue_sensitivity("600887.SH")
        assert result is not None
        assert "降级" in result
        assert result.count("—") >= 4  # dashed scenario rows

    def test_none_without_basic_info(self):
        client = _make_grid_client(with_basic=False)
        assert client._compute_revenue_sensitivity("600887.SH") is None


# ===== whole-pipeline integration =====


class TestPipelineGrids:
    def test_all_grid_sections_present(self):
        """compute_derived_metrics contains 17.10-17.13 with a full store."""
        client = _make_client()
        client._store = _base_store()
        client._store["basic_info"] = _load_mock("daily_basic.json")
        result = client.compute_derived_metrics("600887.SH")
        for tag in ["17.10", "17.11", "17.12", "17.13"]:
            assert tag in result

    def test_graceful_empty_store(self):
        """Empty store must not crash and must not emit 17.10-17.13."""
        client = _make_client()
        result = client.compute_derived_metrics("600887.SH")
        assert "17. 衍生指标" in result
        for tag in ["17.10", "17.11", "17.12", "17.13"]:
            assert tag not in result

    def test_lambda_fields_stored_by_17_5(self):
        """§17.5 must augment factor3_sensitivity with λ fields (for §17.13)."""
        client = _make_client()
        client._store = _base_store()
        client._compute_factor3_step1()
        client._compute_factor3_step4()
        client._compute_factor3_sensitivity_base()
        f3s = client._store["factor3_sensitivity"]
        assert "lambda_median" in f3s
        assert "lambda_reliability" in f3s
        assert round(f3s["lambda_median"], 4) == 0.1520
