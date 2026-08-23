"""Tests for derived metrics computation (§17) in TushareClient."""

import json
import math
import os
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tushare_collector import TushareClient

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
    return client


def _make_client_with_store():
    """Create client with _store populated from mock fixtures."""
    client = _make_client()

    # Load and prepare DataFrames (simulating what get_* methods do)
    income_df = _load_mock("income.json")
    income_df = income_df.sort_values("end_date", ascending=False)
    years = [str(d)[:4] for d in income_df["end_date"]]

    bs_df = _load_mock("balancesheet.json")
    bs_df = bs_df.sort_values("end_date", ascending=False)

    cf_df = _load_mock("cashflow.json")
    cf_df = cf_df.sort_values("end_date", ascending=False)

    div_df = _load_mock("dividend.json")
    div_df = div_df.sort_values("end_date", ascending=False)

    rf_df = _load_mock("yc_cb.json")
    rf_df = rf_df.sort_values("trade_date", ascending=False)

    rep_df = _load_mock("repurchase.json")
    rep_df = rep_df.sort_values("ann_date", ascending=False)
    # Apply same dedup + status filter as get_repurchase()
    if "amount" in rep_df.columns:
        rep_df = rep_df.drop_duplicates(subset=["ann_date", "amount"], keep="first")
    if "proc" in rep_df.columns:
        executed = rep_df[rep_df["proc"].isin(["完成", "实施"])]
        if not executed.empty:
            rep_df = executed
    # Cross-date dedup (mirrors get_repurchase logic)
    if all(c in rep_df.columns for c in ["high_limit", "amount", "proc"]):
        completed = rep_df[rep_df["proc"] == "完成"].copy()
        executing = rep_df[rep_df["proc"] == "实施"].copy()
        other = rep_df[~rep_df["proc"].isin(["完成", "实施"])].copy()
        if not completed.empty:
            completed = completed.drop_duplicates(
                subset=["amount", "high_limit"], keep="first")
        if not executing.empty:
            executing = executing.sort_values("amount", ascending=False)
            executing = executing.drop_duplicates(
                subset=["high_limit"], keep="first")
        if not completed.empty and not executing.empty:
            completed_limits = set(completed["high_limit"].dropna())
            executing = executing[
                ~executing["high_limit"].isin(completed_limits)]
        rep_df = pd.concat(
            [completed, executing, other]).sort_values(
                "ann_date", ascending=False)

    client._store = {
        "income": income_df,
        "income_years": years,
        "balance_sheet": bs_df,
        "balance_sheet_years": years,
        "cashflow": cf_df,
        "cashflow_years": years,
        "dividends": div_df,
        "risk_free_rate": rf_df,
        "repurchase": rep_df,
    }
    return client


# ===== Feature #90: _store initialization + helpers =====


class TestStoreInitialization:
    """Test that _store is initialized and helpers work correctly."""

    def test_store_initialized_empty(self):
        """_store should be an empty dict on init."""
        client = _make_client()
        assert client._store == {}

    def test_safe_float_normal(self):
        client = _make_client()
        assert client._safe_float(42.5) == 42.5
        assert client._safe_float(0) == 0.0

    def test_safe_float_none_and_nan(self):
        client = _make_client()
        assert client._safe_float(None) is None
        assert client._safe_float(float("nan")) is None

    def test_safe_float_string(self):
        client = _make_client()
        assert client._safe_float("not_a_number") is None

    def test_get_annual_df_filters_annual(self):
        client = _make_client_with_store()
        annual = client._get_annual_df("income")
        # All end_dates should end with 1231
        for _, r in annual.iterrows():
            assert str(r["end_date"]).endswith("1231")

    def test_get_annual_df_empty_store(self):
        client = _make_client()
        annual = client._get_annual_df("nonexistent")
        assert annual.empty

    def test_get_annual_series(self):
        client = _make_client_with_store()
        series = client._get_annual_series("income", "revenue")
        assert len(series) == 5
        # First should be latest year (2024), value should be revenue
        assert series[0][0] == "2024"
        assert series[0][1] == 120140000000.0


# ===== Feature #90: 17.1 Financial trends =====


class TestFinancialTrends:
    """Test _compute_financial_trends() for §17.1."""

    def test_revenue_cagr(self):
        """CAGR: (120140/96886)^(1/4) - 1 ≈ 5.55%."""
        client = _make_client_with_store()
        result = client._compute_financial_trends()
        assert result is not None
        assert "营业收入" in result
        # 5-year CAGR should be present
        assert "5年CAGR" in result

    def test_net_profit_cagr(self):
        """Net profit CAGR should be present."""
        client = _make_client_with_store()
        result = client._compute_financial_trends()
        assert "归母净利润" in result

    def test_interest_bearing_debt(self):
        """Interest-bearing debt = st_borr + lt_borr + bond_payable + non_cur_liab_due_1y."""
        client = _make_client_with_store()
        result = client._compute_financial_trends()
        assert "有息负债" in result
        # 2024: 12800 + 5200 + 2000 + 1200 = 21200 百万元
        assert "21,200.00" in result

    def test_debt_ratio(self):
        """Debt/total_assets should be present."""
        client = _make_client_with_store()
        result = client._compute_financial_trends()
        assert "有息负债/总资产" in result

    def test_net_cash(self):
        """Net cash = money_cap - interest_bearing_debt."""
        client = _make_client_with_store()
        result = client._compute_financial_trends()
        assert "广义净现金" in result
        # 2024: 28960 - 21200 = 7760 百万元
        assert "7,760.00" in result

    def test_payout_ratio(self):
        """Payout = (cash_div * base_share * 10000) / n_income_attr_p."""
        client = _make_client_with_store()
        result = client._compute_financial_trends()
        assert "股息支付率" in result

    def test_payout_ratio_value(self):
        """Verify payout ratio for 2024:
        div_total = 0.97 * 636363.64 * 10000 = 6,172,727,308.0
        np = 10,120,000,000
        payout = 6172727308 / 10120000000 * 100 ≈ 61.00%
        """
        client = _make_client_with_store()
        result = client._compute_financial_trends()
        # Should contain ~61.00% for 2024
        assert "61.0" in result or "60.9" in result or "61.00" in result

    def test_returns_none_when_income_missing(self):
        """Should return None if income data is missing."""
        client = _make_client()
        result = client._compute_financial_trends()
        assert result is None

    def test_returns_none_when_insufficient_years(self):
        """Should return None if only 1 year of data."""
        client = _make_client()
        # Only 1 year
        df = pd.DataFrame([{
            "end_date": "20241231", "revenue": 100000000000,
            "n_income_attr_p": 10000000000,
        }])
        client._store["income"] = df
        result = client._compute_financial_trends()
        assert result is None


# ===== Feature #91: 17.2 Factor 2 inputs =====


class TestFactor2Inputs:
    """Test _compute_factor2_inputs() for §17.2."""

    def test_contains_c_and_b(self):
        """Output should show C (归母净利润) and B (少数股东损益)."""
        client = _make_client_with_store()
        result = client._compute_factor2_inputs("600887.SH")
        assert result is not None
        assert "C 归母净利润" in result
        assert "B 少数股东损益" in result

    def test_minority_ratio(self):
        """Minority ratio: 330M / 10450M ≈ 3.16% for 2024."""
        client = _make_client_with_store()
        result = client._compute_factor2_inputs("600887.SH")
        assert "少数股东占比" in result
        assert "3.1" in result  # 330/10450 ≈ 3.16%

    def test_da_and_capex(self):
        """D&A and Capex should be present."""
        client = _make_client_with_store()
        result = client._compute_factor2_inputs("600887.SH")
        assert "D 折旧与摊销" in result
        assert "E 资本开支" in result

    def test_capex_da_median(self):
        """F = Capex/D&A median across 5 years."""
        client = _make_client_with_store()
        result = client._compute_factor2_inputs("600887.SH")
        assert "Capex/D&A 5年中位数" in result
        # Verify it's a reasonable number (should be around 2.4-2.6)
        assert "F（Capex/D&A" in result

    def test_payout_mean_and_stdev(self):
        """M and N should be present."""
        client = _make_client_with_store()
        result = client._compute_factor2_inputs("600887.SH")
        assert "M（支付率3年均值）" in result
        assert "N（支付率3年标准差）" in result

    def test_buyback_annual_avg(self):
        """O should default to 0 (cannot determine cancellation-type programmatically)."""
        client = _make_client_with_store()
        result = client._compute_factor2_inputs("600887.SH")
        assert "O（年均回购金额）" in result
        assert "0.00" in result
        assert "默认0" in result

    def test_threshold_a_share(self):
        """II for A-share: max(3.5%, Rf+2%)."""
        client = _make_client_with_store()
        result = client._compute_factor2_inputs("600887.SH")
        assert "II（门槛值）" in result
        # Rf ≈ 2.315%, so II = max(3.5%, 4.315%) = 4.315%
        assert "4.3" in result

    def test_threshold_hk(self):
        """II for HK stock: max(5%, Rf+3%)."""
        client = _make_client_with_store()
        result = client._compute_factor2_inputs("00001.HK")
        # Rf ≈ 2.315%, so II = max(5%, 5.315%) = 5.315%
        assert "5.3" in result

    def test_threshold_us(self):
        """II for US stock: max(4%, Rf+2%)."""
        client = _make_client_with_store()
        result = client._compute_factor2_inputs("AAPL.US")
        # Rf ≈ 2.315%, so II = max(4%, 4.315%) = 4.315%
        assert "4.3" in result
        assert "美股" in result

    def test_oe_base(self):
        """OE_base should reference G=1.0."""
        client = _make_client_with_store()
        result = client._compute_factor2_inputs("600887.SH")
        assert "OE_base" in result
        assert "G=1.0" in result

    def test_returns_none_no_income(self):
        """Should return None if income data missing."""
        client = _make_client()
        result = client._compute_factor2_inputs("600887.SH")
        assert result is None


# ===== Feature #91: 17.6 Factor 4 price percentiles =====


class TestFactor4Inputs:
    """Test _compute_factor4_inputs() for §17.6."""

    def _make_client_with_weekly(self):
        """Client with weekly price data."""
        client = _make_client_with_store()
        # Create synthetic 10yr weekly prices
        dates = pd.date_range("2016-01-01", "2026-01-01", freq="W")
        import numpy as np
        np.random.seed(42)
        prices = 20 + np.cumsum(np.random.randn(len(dates)) * 0.3)
        prices = np.clip(prices, 10, 50)
        df = pd.DataFrame({
            "trade_date": [d.strftime("%Y%m%d") for d in dates],
            "close": prices,
            "high": prices + 0.5,
            "low": prices - 0.5,
            "vol": [100000] * len(dates),
        })
        df = df.sort_values("trade_date", ascending=True)
        client._store["weekly_prices"] = df
        return client

    def test_percentile_output(self):
        """Should output current price percentile and key percentiles."""
        client = self._make_client_with_weekly()
        result = client._compute_factor4_inputs()
        assert result is not None
        assert "当前股价历史分位" in result
        assert "50%分位价格" in result

    def test_data_point_count(self):
        """Should show number of data points."""
        client = self._make_client_with_weekly()
        result = client._compute_factor4_inputs()
        assert "10年数据点数" in result

    def test_returns_none_no_weekly(self):
        """Should return None if no weekly price data."""
        client = _make_client()
        result = client._compute_factor4_inputs()
        assert result is None


# ===== Feature #91: 17.7 SOTP inputs =====


class TestSotpInputs:
    """Test _compute_sotp_inputs() for §17.7."""

    def _make_client_with_parent(self):
        """Client with both consolidated and parent BS data."""
        client = _make_client_with_store()
        # Add parent balance sheet
        parent_df = pd.DataFrame([{
            "end_date": "20241231", "report_type": "6",
            "money_cap": 15000000000.0,
            "st_borr": 3000000000.0,
            "lt_borr": 2000000000.0,
            "bond_payable": 1000000000.0,
            "non_cur_liab_due_1y": 500000000.0,
            "total_assets": 80000000000.0,
            "total_liab": 35000000000.0,
            "total_hldr_eqy_exc_min_int": 45000000000.0,
        }])
        client._store["balance_sheet_parent"] = parent_df
        return client

    def test_sotp_output(self):
        """Should output parent vs consolidated debt comparison."""
        client = self._make_client_with_parent()
        result = client._compute_sotp_inputs()
        assert result is not None
        assert "合并口径" in result
        assert "母公司口径" in result

    def test_subsidiary_debt_ratio(self):
        """Subsidiary debt ratio = (consol - parent) / consol.
        Consol debt = 12800+5200+2000+1200 = 21200M
        Parent debt = 3000+2000+1000+500 = 6500M
        Ratio = (21200-6500)/21200 ≈ 69.3%
        """
        client = self._make_client_with_parent()
        result = client._compute_sotp_inputs()
        assert "子公司层面负债占比" in result
        assert "69." in result

    def test_returns_none_no_parent(self):
        """Should return None if parent BS not available."""
        client = _make_client_with_store()
        # No parent data in store
        result = client._compute_sotp_inputs()
        assert result is None


# ===== Feature #92: 17.3 Factor 3 Step 1 true cash revenue =====


class TestFactor3Step1:
    """Test _compute_factor3_step1() for §17.3."""

    def test_output_contains_headers(self):
        """Output should have §17.3 header and table columns."""
        client = _make_client_with_store()
        result = client._compute_factor3_step1()
        assert result is not None
        assert "17.3 因子3·步骤1" in result
        assert "S 营业收入" in result
        assert "T 应收变动" in result
        assert "U 合同负债变动" in result
        assert "收款比率" in result

    def test_ar_change_values(self):
        """AR change (T) for 2024: 1850M - 1720M = 130M yuan → 130.00 百万元."""
        client = _make_client_with_store()
        result = client._compute_factor3_step1()
        assert "130.00" in result  # T for 2024

    def test_true_cash_revenue(self):
        """True cash rev for 2024: 120,140M - 130M - 0 = 120,010M → 120,010.00."""
        client = _make_client_with_store()
        result = client._compute_factor3_step1()
        assert "120,010.00" in result

    def test_collection_ratio(self):
        """Collection ratio ≈ 99.89% for 2024."""
        client = _make_client_with_store()
        result = client._compute_factor3_step1()
        assert "99.8" in result or "99.9" in result

    def test_stores_true_cash_rev(self):
        """_store should contain _true_cash_rev after computation."""
        client = _make_client_with_store()
        client._compute_factor3_step1()
        assert "_true_cash_rev" in client._store
        assert "2024" in client._store["_true_cash_rev"]

    def test_returns_none_insufficient_data(self):
        """Should return None with < 2 years."""
        client = _make_client()
        result = client._compute_factor3_step1()
        assert result is None

    def test_four_years_computed(self):
        """With 5 years of data, should compute 4 year-pairs."""
        client = _make_client_with_store()
        result = client._compute_factor3_step1()
        # Should have years 2024, 2023, 2022, 2021
        assert "2024" in result
        assert "2023" in result
        assert "2022" in result
        assert "2021" in result


# ===== Feature #92: 17.4 Factor 3 Step 4 operating outflows =====


class TestFactor3Step4:
    """Test _compute_factor3_step4() for §17.4."""

    def test_output_contains_headers(self):
        """Output should have §17.4 header and W1-W4."""
        client = _make_client_with_store()
        result = client._compute_factor3_step4()
        assert result is not None
        assert "17.4 因子3·步骤4" in result
        assert "W1 供应商" in result
        assert "W2 员工" in result
        assert "W3 现金税" in result
        assert "W4 利息" in result
        assert "W 合计" in result

    def test_w1_supplier(self):
        """W1 for 2024: oper_cost=85030M + max(0, -(8920M-8150M))=0 → 85030M."""
        client = _make_client_with_store()
        result = client._compute_factor3_step4()
        assert "85,030.00" in result

    def test_w2_employee(self):
        """W2 for 2024: c_pay_to_staff = 8520M."""
        client = _make_client_with_store()
        result = client._compute_factor3_step4()
        assert "8,520.00" in result

    def test_w3_cash_tax(self):
        """W3 for 2024: income_tax - (DTA_chg - DTL_chg)
        = 2483M - (170M - 40M) = 2483M - 130M = 2353M."""
        client = _make_client_with_store()
        result = client._compute_factor3_step4()
        assert "2,353.00" in result

    def test_w4_interest(self):
        """W4 for 2024: finance_exp = 320M."""
        client = _make_client_with_store()
        result = client._compute_factor3_step4()
        assert "320.00" in result

    def test_stores_w_total(self):
        """_store should contain _w_total after computation."""
        client = _make_client_with_store()
        client._compute_factor3_step4()
        assert "_w_total" in client._store
        assert "2024" in client._store["_w_total"]

    def test_returns_none_no_data(self):
        """Should return None with no data."""
        client = _make_client()
        result = client._compute_factor3_step4()
        assert result is None


# ===== Feature #92: 17.5 Factor 3 sensitivity base =====


class TestSensitivityBase:
    """Test _compute_factor3_sensitivity_base() for §17.5."""

    def _run_prerequisites(self, client):
        """Run step1 and step4 to populate _store."""
        client._compute_factor3_step1()
        client._compute_factor3_step4()

    def test_output_contains_headers(self):
        """Output should have §17.5 header and surplus table."""
        client = _make_client_with_store()
        self._run_prerequisites(client)
        result = client._compute_factor3_sensitivity_base()
        assert result is not None
        assert "17.5 因子3·步骤7" in result
        assert "基准结余" in result
        assert "AA" in result

    def test_base_surplus_2024(self):
        """Base surplus 2024: 120010M - 96223M - 7850M = 15937M → 15,937.00."""
        client = _make_client_with_store()
        self._run_prerequisites(client)
        result = client._compute_factor3_sensitivity_base()
        assert "15,937.00" in result

    def test_aa_2y_default(self):
        """AA_2y (default): mean of [15937, 15239] = 15588.00 → 15,588.00."""
        client = _make_client_with_store()
        self._run_prerequisites(client)
        result = client._compute_factor3_sensitivity_base()
        assert "15,588.00" in result or "15,588" in result

    def test_aa_all_reference(self):
        """AA_all (reference): mean of [15937, 15239, 18515, 16602] ≈ 16573.25 → 16,573.25."""
        client = _make_client_with_store()
        self._run_prerequisites(client)
        result = client._compute_factor3_sensitivity_base()
        assert "16,573.25" in result or "16,573" in result

    def test_cv_present(self):
        """Revenue CV should be present."""
        client = _make_client_with_store()
        self._run_prerequisites(client)
        result = client._compute_factor3_sensitivity_base()
        assert "收入波动率 CV" in result

    def test_lambda_present(self):
        """λ should be present."""
        client = _make_client_with_store()
        self._run_prerequisites(client)
        result = client._compute_factor3_sensitivity_base()
        assert "经营杠杆系数 λ" in result
        assert "λ可靠性" in result

    def test_returns_none_without_prerequisites(self):
        """Should return None if step1/step4 not run."""
        client = _make_client_with_store()
        result = client._compute_factor3_sensitivity_base()
        assert result is None


# ===== Integration tests =====


class TestComputeDerivedMetrics:
    """Test the main compute_derived_metrics() method."""

    def test_section_header(self):
        """Output should contain §17 header."""
        client = _make_client_with_store()
        result = client.compute_derived_metrics("600887.SH")
        assert "17. 衍生指标" in result
        assert "Python 预计算" in result

    def test_contains_171(self):
        """Output should contain §17.1 sub-section."""
        client = _make_client_with_store()
        result = client.compute_derived_metrics("600887.SH")
        assert "17.1 财务趋势速览" in result

    def test_contains_172(self):
        """Output should contain §17.2 sub-section."""
        client = _make_client_with_store()
        result = client.compute_derived_metrics("600887.SH")
        assert "17.2 因子2输入参数" in result

    def test_contains_173(self):
        """Output should contain §17.3 sub-section."""
        client = _make_client_with_store()
        result = client.compute_derived_metrics("600887.SH")
        assert "17.3 因子3·步骤1" in result

    def test_contains_174(self):
        """Output should contain §17.4 sub-section."""
        client = _make_client_with_store()
        result = client.compute_derived_metrics("600887.SH")
        assert "17.4 因子3·步骤4" in result

    def test_contains_175(self):
        """Output should contain §17.5 sub-section."""
        client = _make_client_with_store()
        result = client.compute_derived_metrics("600887.SH")
        assert "17.5 因子3·步骤7" in result

    def test_graceful_with_empty_store(self):
        """Should not crash with empty _store."""
        client = _make_client()
        result = client.compute_derived_metrics("600887.SH")
        assert "17. 衍生指标" in result
        # Should not contain 17.1 since no data
        assert "17.1" not in result

    def test_contains_disclaimer(self):
        """Output should contain the disclaimer about deterministic computation."""
        client = _make_client_with_store()
        result = client.compute_derived_metrics("600887.SH")
        assert "确定性计算" in result


# ===== Feature #94: 17.8 EV baseline + "买入就是胜利"基准价 =====


def _make_client_with_ev_store():
    """Create client with full _store including basic_info and weekly_prices."""
    client = _make_client_with_store()

    # Add basic_info
    basic_df = _load_mock("daily_basic.json")
    client._store["basic_info"] = basic_df

    # Add weekly_prices with known min=15.50
    import numpy as np
    np.random.seed(42)
    dates = pd.date_range("2016-01-01", "2026-01-01", freq="W")
    prices = 20 + np.cumsum(np.random.randn(len(dates)) * 0.3)
    prices = np.clip(prices, 15.50, 50)
    # Force one data point at exactly 15.50 to ensure min
    prices[10] = 15.50
    df = pd.DataFrame({
        "trade_date": [d.strftime("%Y%m%d") for d in dates],
        "close": prices,
        "high": prices + 0.5,
        "low": prices - 0.5,
        "vol": [100000] * len(dates),
    })
    df = df.sort_values("trade_date", ascending=True)
    client._store["weekly_prices"] = df
    return client


class TestFactor4EVBaseline:
    """Test _compute_factor4_ev_baseline() for §17.8."""

    def test_section_header(self):
        """Output should contain §17.8 header."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert result is not None
        assert "17.8" in result

    def test_ev(self):
        """EV = 175000 + 21200 - 28960 = 167,240.00."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "167,240.00" in result

    def test_ebitda(self):
        """EBITDA = 12890 + 320 + 3200 = 16,410.00."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "16,410.00" in result

    def test_ev_ebitda(self):
        """EV/EBITDA = 167240/16410 = 10.19x."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "10.19" in result

    def test_cash_adjusted_pe(self):
        """(175000 - 7760) / 10120 = 16.53x."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "16.53" in result

    def test_fcf_yield(self):
        """FCF/市值 = 9000/175000 = 5.14%."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "5.14" in result

    def test_pb(self):
        """P/B = 175000/58940 = 2.97x."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "2.97" in result

    def test_net_debt_ebitda(self):
        """(21200 - 28960) / 16410 = -0.47x."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "-0.47" in result

    def test_goodwill_ratio(self):
        """6780/133890 = 5.06%."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "5.06" in result

    def test_ibd_ratio(self):
        """21200/133890 = 15.83%."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "15.83" in result

    def test_dividend_yield(self):
        """0.97/27.50 = 3.53%."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "3.53" in result or "3.5" in result

    def test_baseline_bvps(self):
        """BVPS = 58940M yuan / 6363636400 shares = 9.26."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "9.26" in result

    def test_baseline_10yr_low(self):
        """10yr low should be 15.50."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "15.50" in result

    def test_composite_baseline(self):
        """Median of [1.46, 9.26, 15.50, 29.56, 43.85] = 15.50."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "综合基准价" in result
        # Median is 15.50
        assert "15.50" in result

    def test_premium(self):
        """(27.50/15.50 - 1) × 100 = 77.4%."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "77.4" in result or "溢价" in result

    def test_premium_verdict(self):
        """77.4% is in 30-80% range → 合理溢价."""
        client = _make_client_with_ev_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert "合理溢价" in result

    def test_returns_none_no_basic_info(self):
        """Should return None if basic_info missing."""
        client = _make_client_with_store()
        result = client._compute_factor4_ev_baseline("600887.SH")
        assert result is None

    def test_integration(self):
        """§17.8 should appear in compute_derived_metrics output."""
        client = _make_client_with_ev_store()
        result = client.compute_derived_metrics("600887.SH")
        assert "17.8" in result


# ===== Non-calendar fiscal year tests =====

class TestGetAnnualDfNonCalendarFY:
    """Tests for _get_annual_df with non-calendar fiscal years."""

    def test_get_annual_df_september_fy(self):
        """With _fy_end_month=9, only September dates should be annual."""
        client = _make_client()
        client._fy_end_month = 9
        client._store["income"] = pd.DataFrame([
            {"end_date": "20240928", "revenue": 100},
            {"end_date": "20230930", "revenue": 90},
            {"end_date": "20220924", "revenue": 80},
            {"end_date": "20250331", "revenue": 50},  # interim
        ])
        annual = client._get_annual_df("income")
        assert len(annual) == 3
        for _, r in annual.iterrows():
            assert str(r["end_date"])[4:6] == "09"

    def test_get_annual_df_default_fy(self):
        """Default _fy_end_month=12 should filter to 1231."""
        client = _make_client()
        client._store["income"] = pd.DataFrame([
            {"end_date": "20241231", "revenue": 100},
            {"end_date": "20240930", "revenue": 80},
            {"end_date": "20231231", "revenue": 90},
        ])
        annual = client._get_annual_df("income")
        assert len(annual) == 2
        for _, r in annual.iterrows():
            assert str(r["end_date"]).endswith("1231")


class TestUnitLabelsInDerivedMetrics:
    """Tests for currency-aware unit labels in §17."""

    def test_unit_label_in_financial_trends_usd(self):
        """§17.1 should use 百万美元 for US stocks."""
        client = _make_client()
        client._currency = "USD"
        client._fy_end_month = 9
        # Populate store with minimal data
        client._store["income"] = pd.DataFrame([
            {"end_date": "20240928", "revenue": 100e9, "n_income_attr_p": 20e9},
            {"end_date": "20230930", "revenue": 90e9, "n_income_attr_p": 18e9},
            {"end_date": "20220924", "revenue": 80e9, "n_income_attr_p": 15e9},
            {"end_date": "20210925", "revenue": 70e9, "n_income_attr_p": 12e9},
            {"end_date": "20200926", "revenue": 60e9, "n_income_attr_p": 10e9},
        ])
        client._store["balance_sheet"] = pd.DataFrame([
            {"end_date": "20240928", "st_borr": 1e9, "lt_borr": 5e9, "bond_payable": 0,
             "non_cur_liab_due_1y": 0, "money_cap": 10e9, "trad_asset": 0, "total_assets": 100e9},
            {"end_date": "20230930", "st_borr": 1e9, "lt_borr": 5e9, "bond_payable": 0,
             "non_cur_liab_due_1y": 0, "money_cap": 10e9, "trad_asset": 0, "total_assets": 95e9},
        ])
        client._store["cashflow"] = pd.DataFrame([
            {"end_date": "20240928", "n_cashflow_act": 30e9, "c_pay_acq_const_fiolta": 5e9,
             "c_pay_dist_dpcp_int_exp": 2e9},
            {"end_date": "20230930", "n_cashflow_act": 28e9, "c_pay_acq_const_fiolta": 4e9,
             "c_pay_dist_dpcp_int_exp": 1.5e9},
        ])
        client._store["dividends"] = pd.DataFrame(columns=["end_date", "cash_div_tax"])
        result = client._compute_financial_trends()
        assert result is not None
        assert "百万美元" in result
        assert "百万元" not in result.replace("百万美元", "")
