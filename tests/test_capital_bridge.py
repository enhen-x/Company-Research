"""Known answers and adversarial accounting boundaries, using synthetic amounts."""
from __future__ import annotations

import copy
import json

import pytest

from capital_metrics import FINANCING_KEYS, OPERATING_KEYS
from research_topics import evaluate_topics, run
from tests.test_research_topics import _base


def _config():
    config = _base()
    metrics = config["decision"]["capital_metrics"]
    metrics.update(window_start="2024-12-31", window_end="2025-12-31")
    operating = dict(zip(OPERATING_KEYS, (60, 5, 5, 30, 50, 5, 10, 10, 5, 20)))
    financing = dict(zip(FINANCING_KEYS, (70, 5, 30, 10, 5, 2, 8)))
    final_operating = dict(operating, operating_current_assets_ex_cash=75, operating_current_liabilities_non_interest=35, net_ppe_ex_rou=60)
    final_financing = dict(financing, equity_parent=90)
    metrics["invested_capital_bridge"] = {
        "entity": "SYNTH", "unit": "million", "currency": "CNY", "scope": "consolidated", "basis": "GAAP",
        "goodwill_policy": "include", "lease_policy": "capitalized", "non_controlling_interest_policy": "include_consolidated",
        "restricted_cash_policy": "classified_operating_or_non_operating_never_excess", "acquisition_basis": "none",
        "nopat_basis": "consolidated_operating_after_tax", "nopat_lease_consistent": True,
        "classification_note": "Synthetic nonoverlapping components, cash and ROU separately classified",
        "acquisition_note": "No acquisitions in synthetic window", "nopat_adjustment_note": "Synthetic NOPAT matches consolidated capital and capitalized leases",
        "source_ref": "F1", "absolute_tolerance": 0.001,
        "periods": {"nopat_period": "2025", "prior_nopat_period": "2024", "nopat_start": "2025-01-01", "nopat_end": "2025-12-31",
                    "prior_nopat_start": "2024-01-01", "prior_nopat_end": "2024-12-31"},
        "begin": {"date": "2024-12-31", "operating": operating, "financing": financing},
        "end": {"date": "2025-12-31", "operating": final_operating, "financing": final_financing},
    }
    return config


def _metrics(config):
    return config["decision"]["capital_metrics"]


def _capital(config):
    return evaluate_topics(config)["modules"]["decision"]["capital_metrics"]


def _codes(config):
    return {f["id"] for f in evaluate_topics(config)["findings"]}


def test_dual_bridge_known_answer_and_original_return_formulas():
    result = evaluate_topics(_config())
    assert result["status"] == "OK", result["findings"]
    capital = result["modules"]["decision"]["capital_metrics"]
    bridge = capital["invested_capital_bridge"]
    assert bridge["status"] == "OK"
    assert bridge["begin"]["operating_invested_capital"] == 100
    assert bridge["begin"]["financing_invested_capital"] == 100
    assert bridge["end"]["operating_invested_capital"] == 120
    assert bridge["end"]["residual"] == 0
    assert capital["roic"]["average_invested_capital"] == 110
    assert capital["roic"]["value"] == pytest.approx(24/110)
    assert capital["roiic"]["value"] == pytest.approx((24-15)/(120-100))


def test_bridge_supplies_missing_legacy_capital_and_dates_without_inventing_values():
    config = _config()
    for key in ("invested_capital_begin", "invested_capital_end", "window_start", "window_end"):
        del _metrics(config)[key]
    result = _capital(config)
    assert result["roic"]["value"] == pytest.approx(24/110)
    assert result["roiic"]["window_start"] == "2024-12-31"
    assert result["invested_capital_bridge"]["begin"]["reconciled_invested_capital"] == 100


def test_legacy_inputs_are_compatible_and_double_bridge_is_not_assessed():
    capital = _capital(_base())
    assert capital["invested_capital_bridge"]["status"] == "NOT_ASSESSED"
    assert capital["roic"]["value"] == pytest.approx(24/110)
    assert capital["roiic"]["value"] == pytest.approx(0.45)
    assert capital["roiic"]["window_years"] > 1.99


@pytest.mark.parametrize("side,key", [("operating", key) for key in OPERATING_KEYS] + [("financing", key) for key in FINANCING_KEYS])
def test_each_missing_bridge_component_is_unknown_and_suppresses_returns(side, key):
    config = _config()
    _metrics(config)["invested_capital_bridge"]["begin"][side][key] = None
    capital = _capital(config)
    assert capital["invested_capital_bridge"]["status"] == "INCOMPLETE"
    assert capital["invested_capital_bridge"]["begin"][f"{side}_components"][key] is None
    assert capital["roic"]["value"] is None
    assert capital["roiic"]["value"] is None


def test_zero_components_are_real_zero_and_nonpositive_capital_is_diagnostic():
    config = _config()
    metrics = _metrics(config)
    metrics.update(invested_capital_begin=0, invested_capital_end=0, nopat=0, prior_nopat=0)
    for label in ("begin", "end"):
        snapshot = metrics["invested_capital_bridge"][label]
        snapshot["operating"] = dict.fromkeys(OPERATING_KEYS, 0)
        snapshot["financing"] = dict.fromkeys(FINANCING_KEYS, 0)
    capital = _capital(config)
    assert capital["invested_capital_bridge"]["status"] == "OK"
    assert capital["invested_capital_bridge"]["begin"]["reconciled_invested_capital"] == 0
    assert capital["roic"]["average_invested_capital"] == 0
    assert capital["roic"]["nopat"] == 0
    assert capital["roic"]["value"] is None
    assert capital["roiic"]["value"] is None


def test_negative_equity_and_negative_invested_capital_do_not_become_normal_returns():
    config = _config()
    metrics = _metrics(config)
    metrics.update(invested_capital_begin=-10, invested_capital_end=-20)
    for label, amount in (("begin", -10), ("end", -20)):
        snapshot = metrics["invested_capital_bridge"][label]
        snapshot["operating"] = dict.fromkeys(OPERATING_KEYS, 0)
        snapshot["operating"]["operating_current_liabilities_non_interest"] = -amount
        snapshot["financing"] = dict.fromkeys(FINANCING_KEYS, 0)
        snapshot["financing"]["equity_parent"] = amount
    capital = _capital(config)
    assert capital["invested_capital_bridge"]["status"] == "OK"
    assert capital["roic"]["average_invested_capital"] == -15
    assert capital["roic"]["value"] is None and capital["roiic"]["value"] is None


@pytest.mark.parametrize("change", ["financing", "operating", "legacy_begin", "legacy_end"])
def test_bridge_or_legacy_mismatch_is_invalid_and_suppresses_returns(change):
    config = _config()
    metrics = _metrics(config)
    if change.startswith("legacy"):
        metrics["invested_capital_" + change.removeprefix("legacy_")] += 1
    else:
        side = metrics["invested_capital_bridge"]["end"][change]
        side["equity_parent" if change == "financing" else "net_ppe_ex_rou"] += 1
    capital = _capital(config)
    assert capital["invested_capital_bridge"]["status"] == "INVALID"
    assert capital["roic"]["status"] == capital["roiic"]["status"] == "INVALID"
    assert capital["roic"]["value"] is None and capital["roiic"]["value"] is None


def test_goodwill_exclusion_adjusts_both_bridges_once():
    config = _config()
    metrics = _metrics(config)
    metrics["invested_capital_bridge"]["goodwill_policy"] = "exclude"
    metrics.update(invested_capital_begin=90, invested_capital_end=110)
    capital = _capital(config)
    assert capital["invested_capital_bridge"]["status"] == "OK"
    assert capital["roic"]["average_invested_capital"] == 100
    assert capital["roic"]["value"] == pytest.approx(0.24)
    assert capital["roiic"]["value"] == pytest.approx(0.45)


@pytest.mark.parametrize("key", ["unit", "currency", "scope", "basis", "entity", "goodwill_policy", "lease_policy", "non_controlling_interest_policy", "restricted_cash_policy", "acquisition_basis", "nopat_basis", "classification_note", "acquisition_note", "nopat_adjustment_note", "nopat_lease_consistent"])
def test_missing_required_basis_cannot_produce_normal_returns(key):
    config = _config()
    del _metrics(config)["invested_capital_bridge"][key]
    capital = _capital(config)
    assert capital["invested_capital_bridge"]["status"] == "INCOMPLETE"
    assert capital["roic"]["value"] is None and capital["roiic"]["value"] is None


@pytest.mark.parametrize("key,value", [("unit", "yuan"), ("currency", "USD"), ("scope", "parent"), ("basis", "adjusted"), ("entity", "OTHER")])
def test_conflicting_snapshot_metadata_is_invalid(key, value):
    config = _config()
    _metrics(config)["invested_capital_bridge"]["end"][key] = value
    capital = _capital(config)
    assert capital["invested_capital_bridge"]["status"] == "INVALID"
    assert capital["roic"]["value"] is None


@pytest.mark.parametrize("key,value", [("lease_policy", "off_balance_sheet"), ("acquisition_basis", "unknown"), ("scope", "parent"), ("restricted_cash_policy", "all_excess")])
def test_unsupported_accounting_policies_are_explicitly_incomplete(key, value):
    config = _config()
    _metrics(config)["invested_capital_bridge"][key] = value
    assert _capital(config)["invested_capital_bridge"]["status"] == "INCOMPLETE"


@pytest.mark.parametrize("kind", ["window", "future_snapshot", "long_period", "unmatched_periods", "missing_period", "date_reversal"])
def test_temporal_mismatch_does_not_produce_normal_returns(kind):
    config = _config()
    metrics = _metrics(config)
    bridge = metrics["invested_capital_bridge"]
    if kind == "window":
        metrics["window_start"] = "2023-12-31"
    elif kind == "future_snapshot":
        config["as_of"] = "2025-06-30"
    elif kind == "long_period":
        metrics["window_start"] = bridge["begin"]["date"] = "2023-12-31"
        bridge["periods"]["nopat_start"] = "2024-01-01"
    elif kind == "unmatched_periods":
        bridge["periods"]["prior_nopat_start"] = "2024-07-01"
    elif kind == "missing_period":
        del bridge["periods"]["nopat_start"]
    else:
        bridge["periods"]["nopat_start"] = "2026-01-01"
    capital = _capital(config)
    assert capital["invested_capital_bridge"]["status"] in {"INVALID", "INCOMPLETE"}
    assert capital["roic"]["value"] is None and capital["roiic"]["value"] is None


@pytest.mark.parametrize("value", [True, "100", -1, {}, [1]])
def test_bad_or_negative_operating_stock_is_invalid(value):
    config = _config()
    _metrics(config)["invested_capital_bridge"]["begin"]["operating"]["net_ppe_ex_rou"] = value
    assert _capital(config)["invested_capital_bridge"]["status"] == "INVALID"


@pytest.mark.parametrize("value", [-1, True, "0", None])
def test_invalid_reconciliation_tolerance_is_not_silently_replaced(value):
    config = _config()
    _metrics(config)["invested_capital_bridge"]["absolute_tolerance"] = value
    assert "capital_tolerance_invalid" in _codes(config)
    assert _capital(config)["roic"]["value"] is None


def test_exact_tolerance_is_allowed_and_larger_residual_is_rejected():
    config = _config()
    bridge = _metrics(config)["invested_capital_bridge"]
    bridge["absolute_tolerance"] = 0.5
    bridge["end"]["financing"]["equity_parent"] += 0.5
    assert _capital(config)["invested_capital_bridge"]["status"] == "OK"
    bridge["end"]["financing"]["equity_parent"] += 0.001
    assert _capital(config)["invested_capital_bridge"]["status"] == "INVALID"


def _fact(config, **updates):
    fact = {"id": "CAP1", "value": 60, "unit": "million", "period": "2024-12-31", "entity": "SYNTH", "currency": "CNY", "scope": "consolidated", "basis": "GAAP", "source": {"title": "Synthetic annual report", "locator": "p. 9"}}
    fact.update(updates)
    config["facts"]["records"].append(fact)
    return fact


def test_per_component_fact_and_assumption_references_are_resolved_and_tracked():
    config = _config()
    _fact(config)
    _metrics(config)["invested_capital_bridge"]["begin"]["operating"]["operating_current_assets_ex_cash"] = {"ref": "CAP1"}
    result = evaluate_topics(config)
    assert result["status"] == "OK", result["findings"]
    assert "CAP1" in result["modules"]["decision"]["capital_metrics"]["invested_capital_bridge"]["evidence_refs"]
    record = dict(config["facts"]["records"].pop(), id="CAPASSUME", reason="Explicit synthetic capital assumption", source_ref="F1")
    config["assumptions"].append(record)
    _metrics(config)["invested_capital_bridge"]["begin"]["operating"]["operating_current_assets_ex_cash"] = {"ref": "CAPASSUME"}
    result = evaluate_topics(config)
    assert result["status"] == "OK", result["findings"]
    assert "CAPASSUME" in {r["id"] for r in result["assumptions_used"]}


@pytest.mark.parametrize("key,bad", [("unit", "yuan"), ("period", "2023-12-31"), ("currency", "USD"), ("scope", "parent"), ("basis", "adjusted"), ("entity", "OTHER")])
def test_reference_metadata_cannot_be_overridden_to_bypass_bridge_basis(key, bad):
    config = _config()
    _fact(config, **{key: bad})
    _metrics(config)["invested_capital_bridge"]["begin"]["operating"]["operating_current_assets_ex_cash"] = {"ref": "CAP1", key: bad}
    capital = _capital(config)
    assert capital["invested_capital_bridge"]["status"] == "INVALID"
    assert capital["roic"]["value"] is None


def test_nopat_reference_wrong_unit_blocks_returns_even_with_good_capital_bridge():
    config = _config()
    _fact(config, value=24, unit="yuan", period="2025")
    _metrics(config)["nopat"] = {"ref": "CAP1", "unit": "yuan"}
    capital = _capital(config)
    assert capital["invested_capital_bridge"]["status"] == "INVALID"
    assert capital["roic"]["value"] is None and capital["roiic"]["value"] is None


@pytest.mark.parametrize("profile", ["banks", "life_insurance", "property_insurance", "mreit"])
def test_financial_models_ignore_even_malformed_enterprise_capital_bridges(profile):
    config = _config()
    config["industry"] = {"profile": profile, "order_based": False}
    _metrics(config)["invested_capital_bridge"] = ["do not interpret"]
    _metrics(config)["reinvestment_check"] = None
    capital = _capital(config)
    for key in ("invested_capital_bridge", "roic", "roiic", "reinvestment_check"):
        assert capital[key]["status"] == "NOT_APPLICABLE"


def _reinvestment(config, **overrides):
    value = {"net_reinvestment": 20, "return_metric": "roiic", "steady_state": True, "assumption_note": "Synthetic same-period incremental return identity", "source_ref": "F1", "growth_tolerance": 0.001}
    value.update(overrides)
    _metrics(config)["reinvestment_check"] = value


def test_reinvestment_incremental_identity_is_not_claimed_as_independent_evidence():
    config = _config()
    _reinvestment(config)
    result = _capital(config)["reinvestment_check"]
    assert result["status"] == "OK"
    assert result["reinvestment_rate"] == pytest.approx(20/15)
    assert result["implied_growth"] == pytest.approx(0.6)
    assert result["actual_nopat_growth"] == pytest.approx(0.6)
    assert result["interpretation"] == "ACCOUNTING_IDENTITY_NOT_INDEPENDENT_VALIDATION"


@pytest.mark.parametrize("overrides,code", [({"steady_state": False}, "reinvestment_steady_state_unconfirmed"), ({"net_reinvestment": None}, "numeric_missing"), ({"net_reinvestment": -1}, "negative_reinvestment"), ({"return_metric": "bad"}, "reinvestment_return_metric_invalid"), ({"currency": "USD"}, "capital_metadata_mismatch"), ({"growth_tolerance": True}, "reinvestment_tolerance_invalid"), ({"return_metric": "roic"}, "reinvestment_growth_mismatch")])
def test_reinvestment_bad_assumptions_or_growth_gap_are_explicit(overrides, code):
    config = _config()
    _reinvestment(config, **overrides)
    result = _capital(config)["reinvestment_check"]
    assert result["status"] in {"INCOMPLETE", "INVALID"}
    assert result["implied_growth"] is None
    assert code in _codes(config)


def test_reinvestment_nonpositive_nopat_cannot_explain_normal_growth():
    config = _config()
    _metrics(config)["prior_nopat"] = 0
    _reinvestment(config)
    check = _capital(config)["reinvestment_check"]
    assert check["status"] == "INCOMPLETE"
    assert check["reinvestment_rate"] is None and check["actual_nopat_growth"] is None


def test_reinvestment_period_is_inherited_and_explicit_cross_period_is_invalid():
    config = _config()
    _reinvestment(config)
    check = _capital(config)["reinvestment_check"]
    assert check["period"] == "2025"
    assert check["metadata"]["unit"] == "million"
    _metrics(config)["reinvestment_check"]["period"] = "2024"
    check = _capital(config)["reinvestment_check"]
    assert check["status"] == "INVALID" and check["implied_growth"] is None
    assert "reinvestment_period_mismatch" in _codes(config)


@pytest.mark.parametrize("field", ["net_ppe_ex_rou", "operating_current_assets_ex_cash"])
def test_finite_components_whose_sum_overflows_do_not_escape_model_boundary(field):
    config = _config()
    operating = _metrics(config)["invested_capital_bridge"]["end"]["operating"]
    operating[field] = 1.5e308
    operating["other_operating_noncurrent_assets"] = 1.5e308
    result = evaluate_topics(config)
    assert result["status"] == "INVALID"
    assert "capital_calculation_nonfinite" in {item["id"] for item in result["findings"]}
    assert result["modules"]["decision"]["capital_metrics"]["roic"]["value"] is None


def _set_dual_capital(config, begin, end):
    metrics = _metrics(config)
    metrics.update(invested_capital_begin=begin, invested_capital_end=end)
    for label, amount in (("begin", begin), ("end", end)):
        snapshot = metrics["invested_capital_bridge"][label]
        snapshot["operating"] = dict.fromkeys(OPERATING_KEYS, 0)
        snapshot["financing"] = dict.fromkeys(FINANCING_KEYS, 0)
        if amount >= 0:
            snapshot["operating"]["operating_current_assets_ex_cash"] = amount
        else:
            snapshot["operating"]["operating_current_liabilities_non_interest"] = -amount
        snapshot["financing"]["equity_parent"] = amount


def test_large_finite_balances_have_stable_average_and_nonzero_return():
    config = _config()
    _set_dual_capital(config, 1.5e308, 1.5e308)
    capital = _capital(config)
    assert capital["invested_capital_bridge"]["status"] == "OK"
    assert capital["roic"]["status"] == "OK"
    assert capital["roic"]["average_invested_capital"] == 1.5e308
    assert capital["roic"]["value"] == 24/1.5e308
    assert capital["roic"]["value"] > 0
    assert "capital_calculation_nonfinite" not in _codes(config)


def test_equal_subnormal_balances_do_not_underflow_average_to_zero():
    config = _config()
    _set_dual_capital(config, 5e-324, 5e-324)
    _metrics(config)["nopat"] = 5e-324
    roic = _capital(config)["roic"]
    assert roic["average_invested_capital"] == 5e-324
    assert roic["status"] == "OK" and roic["value"] == 1


@pytest.mark.parametrize("case", ["roic", "roiic", "delta_nopat", "delta_invested_capital"])
def test_nonrepresentable_capital_intermediates_invalidate_affected_child(case):
    config = _config()
    metrics = _metrics(config)
    if case == "roic":
        _set_dual_capital(config, 1e-300, 1e-300)
        metrics["nopat"] = 1.5e308
        target = "roic"
    elif case == "roiic":
        _set_dual_capital(config, 0, 1e-300)
        metrics["prior_nopat"] = -1.5e308
        target = "roiic"
    elif case == "delta_nopat":
        metrics.update(nopat=1.5e308, prior_nopat=-1.5e308)
        target = "roiic"
    else:
        _set_dual_capital(config, -1.5e308, 1.5e308)
        target = "roiic"
    result = evaluate_topics(config)
    capital = result["modules"]["decision"]["capital_metrics"]
    assert result["status"] == "INVALID"
    assert capital[target]["status"] == "INVALID"
    assert capital[target]["value"] is None
    if case in {"delta_nopat", "delta_invested_capital"}:
        assert capital["roiic"][case] is None
    assert "capital_calculation_nonfinite" in {item["id"] for item in result["findings"]}


def test_overflowing_bank_implied_return_is_not_an_ok_null_child():
    config = _base(industry={"profile": "banks", "order_based": False})
    config["decision"]["capital_metrics"] = {"ptbv": 1.5e308, "ke": 2, "g": 0.01, "source_ref": "F1"}
    implied = _capital(config)["implied_rotce"]
    assert implied["status"] == "INVALID" and implied["value"] is None


def test_bridge_run_is_deterministic_and_keeps_one_output(tmp_path):
    path = tmp_path / "input" / "研究模型.json"
    path.parent.mkdir()
    config = _config()
    original = copy.deepcopy(config)
    assert evaluate_topics(config) == evaluate_topics(config)
    assert config == original
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    result, code = run(tmp_path)
    assert code == 0 and result["status"] == "OK"
    output = tmp_path / "reports" / "研究模型_输出.json"
    mtime = output.stat().st_mtime_ns
    assert run(tmp_path) == (result, code)
    assert output.stat().st_mtime_ns == mtime
    assert {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()} == {"input/研究模型.json", "reports/研究模型_输出.json"}
