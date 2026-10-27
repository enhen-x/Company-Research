"""Known-answer checks for valuation units, cash-flow basis and missing data."""

import copy
import math

import pandas as pd
import pytest

from build_penetration_input import financial_snapshot
from valuation_engine import ValuationEngine
from valuation_math import (canonical_ebitda, cagr, enterprise_dcf,
                            implied_perpetual_growth, perpetuity_value,
                            implied_stable_growth, stable_cashflow_path)


class StoredClient:
    def __init__(self, contract=None, cap_mm=1000):
        self._store = {
            "basic_info": pd.DataFrame([{"close": 10, "total_mv": cap_mm * 100,
                                          "total_share": cap_mm * 10, "pe_ttm": 10}]),
            "income": pd.DataFrame([{"end_date": f"{year}1231", "revenue": 1000e6,
                                      "n_income_attr_p": 100e6, "total_profit": 125e6,
                                      "income_tax": 25e6, "int_exp": 0}
                                     for year in (2024, 2023, 2022)]),
            "cashflow": pd.DataFrame([{"end_date": f"{year}1231", "n_cashflow_act": 80e6,
                                        "c_pay_acq_const_fiolta": 10e6}
                                       for year in (2024, 2023, 2022)]),
            "balance_sheet": pd.DataFrame([{"end_date": f"{year}1231", "money_cap": 50e6,
                                             "st_borr": 0, "lt_borr": 0, "bond_payable": 0,
                                             "non_cur_liab_due_1y": 0}
                                            for year in (2024, 2023)]),
        }
        if contract is not None:
            self._store["valuation_contract"] = copy.deepcopy(contract)

    @staticmethod
    def _safe_float(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    def _get_annual_df(self, key):
        return self._store.get(key, pd.DataFrame())

    def _get_payout_by_year(self):
        return {}

    def _unit_label(self):
        return "million"

    def _price_unit(self):
        return "CNY"


def contract(basis="FCFF"):
    result = {
        "cashflow_basis": basis, "currency": "CNY", "amount_unit": "million",
        "historical_source": "explicit", "stable_growth_pct": 0, "terminal_growth_pct": 0,
        "historical_cashflows": [{"period": str(year), "value": 100, "evidence_id": f"F{year}"}
                                 for year in (2024, 2023, 2022)],
    }
    if basis == "FCFF":
        result["equity_bridge"] = {"cash": 50, "debt": 200, "other_equity_adjustment": -10,
                                   "evidence_id": "balance-scope-reconciliation"}
    else:
        result["cashflow_scope"] = "parent_common"
    return result


def engine(config=None, cap_mm=1000):
    return ValuationEngine("600000.SH", ".", StoredClient(config, cap_mm))


RATES = {"wacc": 10, "ke": 12.5, "tax_rate": 20}


@pytest.mark.parametrize("cap_mm,beta", [(100_001, .8), (100_000, 1), (10_000, 1), (9_999, 1.2)])
def test_beta_boundaries_are_in_millions(cap_mm, beta):
    assert engine(cap_mm=cap_mm).compute_wacc()["beta"] == beta


def test_cagr_preserves_year_gap_and_does_not_hide_loss_endpoint():
    assert cagr([("2024", 200), ("2023", None), ("2022", 100)]) == pytest.approx(math.sqrt(2) - 1)
    assert cagr([200, None, 100]) == pytest.approx(math.sqrt(2) - 1)
    assert cagr([("2024", 200), ("2021", 100)]) == pytest.approx(2 ** (1 / 3) - 1)
    assert cagr([("2024", -1), ("2023", 200), ("2022", 100)]) is None
    assert cagr([("2024", 0), ("2022", 100)]) is None


def test_known_answer_dcf_and_perpetuity_inverse():
    # A flat 100 cash flow forever at 10% is worth 1,000, regardless of explicit horizon.
    assert enterprise_dcf([100] * 5, .10, 0)["ev"] == pytest.approx(1000)
    value = perpetuity_value(100, .10, .03)
    assert value == pytest.approx(103 / .07)
    assert implied_perpetual_growth(100, value, .10) == pytest.approx(.03)


@pytest.mark.parametrize("discount,growth", [(.03, .03), (.02, .03), (0, -.01), (.1, -1)])
def test_invalid_terminal_is_rejected(discount, growth):
    with pytest.raises(ValueError):
        enterprise_dcf([100], discount, growth)


def test_fcff_and_fcfe_have_different_discount_and_value_bridges():
    fcff = engine(contract()).dcf_stable(RATES)
    fcfe = engine(contract("FCFE")).dcf_stable(RATES)
    assert fcff["intrinsic"] == pytest.approx(8.4)  # (100/.10 +50 -200 -10)/100 shares
    assert fcfe["intrinsic"] == pytest.approx(8.0)  # 100/.125 /100 shares; no second debt deduction
    assert fcff["cashflow_basis"] == "FCFF" and fcff["discount_rate_basis"] == "WACC"
    assert fcfe["cashflow_basis"] == "FCFE" and fcfe["discount_rate_basis"] == "KE"
    assert fcfe["ev"] is None


def test_missing_contract_and_bridge_do_not_generate_dcf():
    target = engine()
    assert target.dcf_stable(RATES) is None
    assert target.method_status["DCF"]["status"] == "INSUFFICIENT_DATA"
    config = contract()
    config["equity_bridge"].pop("cash")
    assert engine(config).dcf_stable(RATES) is None
    config["equity_bridge"].update(cash=0, debt=0, other_equity_adjustment=0)
    assert engine(config).dcf_stable(RATES)["intrinsic"] == pytest.approx(10)


def test_invalid_wacc_does_not_change_terminal_growth():
    config = contract()
    config["terminal_growth_pct"] = 10
    with pytest.raises(ValueError, match="greater"):
        engine(config).dcf_stable(RATES)
    assert config["terminal_growth_pct"] == 10


def test_ocf_conversion_requires_explicit_interest_classification_and_financing():
    config = contract()
    config["historical_source"] = "ocf"
    assert engine(config).dcf_stable(RATES) is None
    config["ocf_interest_classification"] = "within_operating"
    assert engine(config).dcf_stable(RATES) is None
    config["ocf_adjustments"] = {f"{year}1231": {"after_tax_interest": 5, "evidence_id": "I"}
                                 for year in (2024, 2023, 2022)}
    # CFO80-capex10+after-tax-interest5 = FCFF75.
    assert engine(config).dcf_stable(RATES)["fcf_base"] == pytest.approx(75e6)
    config = contract("FCFE")
    config["historical_source"] = "ocf"
    config["ocf_interest_classification"] = "within_operating"
    assert engine(config).dcf_stable(RATES) is None
    config["ocf_adjustments"] = {f"{year}1231": {"net_borrowing": -5, "evidence_id": "D"}
                                 for year in (2024, 2023, 2022)}
    assert engine(config).dcf_stable(RATES)["fcf_base"] == pytest.approx(65e6)


def test_reverse_uses_exact_gordon_and_enterprise_bridge_not_net_profit_proxy():
    result = engine(contract()).reverse_valuation(RATES, {"np_cagr_pct": 99})
    assert result["reference_value"] == pytest.approx(1160e6)
    assert result["implied_g_fcf"] == pytest.approx(16 / 1260 * 100)
    assert result["reconstructed_value"] == pytest.approx(1160e6)
    assert result["actual_fcf_cagr"] == 0
    assert result["implied_g_earnings"] is None


@pytest.mark.parametrize("base,growth,discount,terminal", [
    (100, 0, .10, 0), (80, .20, .12, .03), (300, -.15, .09, .02), (30, .7, .15, .04),
])
def test_five_year_reverse_reconstructs_same_forward_model(base, growth, discount, terminal):
    target = enterprise_dcf(stable_cashflow_path(base, growth, terminal), discount, terminal)["ev"]
    solved = implied_stable_growth(base, target, discount, terminal)
    assert solved["status"] == "COMPUTED"
    assert solved["implied_growth"] == pytest.approx(growth, abs=1e-8)
    assert solved["reconstructed_value"] == pytest.approx(target, rel=1e-9)
    assert solved["iterations"] <= 100


@pytest.mark.parametrize("basis", ["FCFF", "FCFE"])
def test_engine_five_year_reverse_uses_same_forward_equity_bridge(basis):
    config = contract(basis)
    config.update(stable_growth_pct=15, terminal_growth_pct=2)
    target = engine(config)
    forward = target.dcf_stable(RATES)
    shares = target._basic_info()["total_shares"]
    price = forward["intrinsic"]
    basic = target.client._store["basic_info"]
    basic["close"] = basic["close"].astype(float)
    basic["total_mv"] = basic["total_mv"].astype(float)
    basic.loc[0, "close"] = price
    basic.loc[0, "total_mv"] = price * shares / 1e4
    reverse = target.reverse_valuation(RATES, {})["five_year_dcf"]
    assert reverse["status"] == "COMPUTED"
    assert reverse["cashflow_basis"] == basis
    assert reverse["implied_growth_pct"] == pytest.approx(15, abs=1e-6)
    assert reverse["gap_pct_points"] == pytest.approx(0, abs=1e-6)
    assert reverse["reconstructed_value"] == pytest.approx(forward["ev"] if basis == "FCFF" else forward["equity_value"])


def test_reverse_bounds_fail_visible_and_do_not_expand_or_change_terminal():
    target = enterprise_dcf(stable_cashflow_path(100, .3, .02), .1, .02)["ev"]
    result = implied_stable_growth(100, target, .1, .02, bounds=[-.1, .1])
    assert result["status"] == "NO_SOLUTION"
    assert result["implied_growth"] is None and result["iterations"] == 0
    assert result["bounds"] == [-.1, .1] and result["terminal_growth"] == .02


@pytest.mark.parametrize("bounds", [[], [1], [-1, 1], [1, 0], [False, 1], [0, float("inf")]])
def test_reverse_invalid_bounds_raise_without_retry(bounds):
    with pytest.raises(ValueError):
        implied_stable_growth(100, 1000, .1, .02, bounds=bounds)


def test_inverse_requires_explicit_terminal_even_when_forward_has_default():
    config = contract()
    config.pop("terminal_growth_pct")
    result = engine(config).reverse_valuation(RATES, {})
    assert result["five_year_dcf"]["status"] == "INSUFFICIENT_DATA"
    assert result["implied_g_fcf"] is not None


def test_growth_dcf_requires_explicit_cash_flow_paths_and_valid_probabilities():
    config = contract()
    assert engine(config).dcf_scenarios(RATES) is None
    config["scenarios"] = {name: {"cashflows": [100] * 5, "probability": probability,
                                 "evidence_id": "forecast-assumptions"}
                           for name, probability in (("optimistic", .2), ("base", .6), ("pessimistic", .2))}
    assert engine(config).dcf_scenarios(RATES)["intrinsic"] == pytest.approx(8.4)
    config["scenarios"]["base"]["probability"] = .5
    with pytest.raises(ValueError, match="sum to 1"):
        engine(config).dcf_scenarios(RATES)


def test_mixed_dividend_interest_cash_does_not_overwrite_dps():
    target = engine()
    target.client._store["dividends"] = pd.DataFrame([{"end_date": "20241231", "cash_div_tax": .1}])
    target.client._store["cashflow"].loc[0, "c_pay_dist_dpcp_int_exp"] = 300e6
    assert target._aggregate_annual_dps() == [("2024", .1)]


def test_canonical_ebitda_is_shared_and_missing_interest_is_unknown():
    assert canonical_ebitda(80, 10, 20) == 110
    assert canonical_ebitda(80, 0, 20) == 100
    assert canonical_ebitda(80, None, 20) is None
    balance = pd.Series(dtype=float)
    income = pd.Series({"TOTAL_PROFIT": 80e6, "FE_INTEREST_EXPENSE": 10e6,
                        "OPERATE_PROFIT": 999e6, "FINANCE_EXPENSE": 999e6})
    assert financial_snapshot(balance, income, 20)["ebitda"] == 110
    assert financial_snapshot(balance, income.drop("FE_INTEREST_EXPENSE"), 20)["ebitda"] is None


def test_contract_unit_scale_does_not_change_per_share_value():
    config = contract()
    expected = engine(config).dcf_stable(RATES)["intrinsic"]
    config["amount_unit"] = "raw"
    for row in config["historical_cashflows"]:
        row["value"] *= 1e6
    for key in ("cash", "debt", "other_equity_adjustment"):
        config["equity_bridge"][key] *= 1e6
    assert engine(config).dcf_stable(RATES)["intrinsic"] == pytest.approx(expected)
    config["currency"] = "USD"
    assert engine(config).dcf_stable(RATES) is None


def test_negative_terminal_cash_flow_is_not_replaced_with_zero_terminal_value():
    config = contract()
    for row in config["historical_cashflows"]:
        row["value"] = -100
    target = engine(config)
    assert target.dcf_stable(RATES) is None
    assert "non-positive terminal" in target.method_status["DCF"]["reason"]


def test_missing_debt_is_not_an_observed_zero_and_assumptions_are_labelled():
    target = engine()
    target.client._store["balance_sheet"] = target.client._store["balance_sheet"].drop(columns="bond_payable")
    rates = target.compute_wacc()
    assert rates["debt_mm"] is None and rates["wacc"] is None
    assert "not a statistically" in rates["parameter_sources"]["beta"]
    assert "assumption" in rates["parameter_sources"]["kd_pre"]


def test_derived_ebitda_does_not_use_finance_exp_or_unverified_provider_override():
    from tests.test_derived_metrics import _make_client_with_ev_store

    client = _make_client_with_ev_store()
    client._store["income"] = client._store["income"].drop(columns=["int_exp"], errors="ignore")
    client._store["income"]["finance_exp"] = 320e6
    client._store["fina_indicators"] = pd.DataFrame([{"end_date": "20241231", "ebitda": 999e6}])
    output = client._compute_factor4_ev_baseline("600887.SH")
    line = next(line for line in output.splitlines() if "EBITDA（" in line)
    assert "| — |" in line
    assert "provider EBITDA=999.00" in line
    assert "16,410.00" not in output


def test_dcf_insufficiency_remains_visible_in_generated_output():
    target = engine()
    assert target.dcf_stable(RATES) is None
    output = target.run()
    assert "INSUFFICIENT_DATA" in output and "cashflow_basis" in output
