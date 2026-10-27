"""Known-answer and adversarial tests for source-linked V3 topic calculations."""
from __future__ import annotations

import copy
import io
import json
import sys
from pathlib import Path

import pytest

from research_models import PROFILES
import research_topics
from research_topics import evaluate_topics, run
from run_support import run_process


def _meta(**values):
    result = {"entity": "SYNTH", "scope": "consolidated", "period": "2025", "metric": "profit",
              "unit": "million", "currency": "CNY", "basis": "GAAP", "source_ref": "F1"}
    result.update(values)
    return result


def _base(**overrides):
    config = {
        "schema_version": 1, "as_of": "2026-03-31",
        "facts": {"entity": {"id": "SYNTH", "name": "Synthetic industrial"}, "records": [
            {"id": "F1", "value": 100, "unit": "million", "period": "2025",
             "source": {"title": "Synthetic annual report", "locator": "p. 10 table 1"}}
        ]},
        "assumptions": [{"id": "A1", "value": 120, "unit": "million", "period": "2026", "reason": "Explicit synthetic base case", "source_ref": "F1"}],
        "industry": {"profile": "industrials", "order_based": True},
        "guidance": {"versions": [_meta(id="G1", status="initial", published_at="2025-01-01", lower=90, upper=110)],
                     "actuals": [_meta(value=100, published_at="2026-01-31")]},
        "orders": {"period": "2025", "definition": "firm backlog", "unit": "million", "currency": "CNY", "scope": "consolidated", "tax_included": False,
                   "fulfillment_definition": "contract delivery rolloff", "bridges": [{"source_ref": "F1",
                       "gross": {"opening": 100, "new_included": 40, "fx_scope_adjustment": 0, "fulfilled": 25, "cancelled": 5, "closing": 110},
                       "net": {"opening": 100, "new_included": 35, "fx_scope_adjustment": 0, "fulfilled": 25, "closing": 110}}],
                   "cash_links": [{"period": "2025", "recognized_revenue": 25, "cost": 15, "cash_received": 20, "receivable": 5, "source_ref": "F1"}]},
        "forecast": {"period": "2026", "unit": "million", "currency": "CNY", "scope": "consolidated", "basis": "GAAP",
                     "revenue_mode": "direct", "revenue": {"ref": "A1"}, "gross_margin": 0.4, "opex": 20, "da": 5,
                     "tax_rate": 0.25, "capex": 10, "delta_nwc": 3, "opex_excludes_da": True, "gross_margin_excludes_da": True, "source_ref": "F1",
                     "scenarios": [{"name": "bear", "probability": 0.25, "value": 80, "source_ref": "F1"},
                                   {"name": "base", "probability": 0.5, "value": 120, "source_ref": "F1"},
                                   {"name": "bull", "probability": 0.25, "value": 160, "source_ref": "F1"}]},
        "theses": {"items": [{"id": "T1", "text": "Customer demand supports value", "counterarguments": [
            {"text": "Customer inventory contradicts demand", "refs": ["F1"], "disposition": "partially_accepted",
             "reason": "Inventory evidence affects volume assumption", "changed_assumption_ids": ["A1"],
             "action": "monitor sell-through before adding", "verify_date": "2026-06-30"}]}]},
        "decision": {"recommendation": "observe", "capital_metrics": {"invested_capital_begin": 100, "invested_capital_end": 120,
                     "nopat": 24, "prior_nopat": 15, "window_start": "2023-12-31", "window_end": "2025-12-31", "source_ref": "F1"}},
    }
    config.update(overrides)
    return config


def _codes(result):
    return [finding["id"] for finding in result["findings"]]


def _bank_forecast():
    return {"period": "2026", "unit": "million", "currency": "CNY", "scope": "consolidated", "basis": "GAAP", "source_ref": "F1",
            "earning_assets": 1000, "asset_yield": 0.05, "interest_bearing_liabilities": 900, "funding_cost": 0.02,
            "loan_balance": 800, "credit_cost": 0.01, "fees": 10, "opex": 15, "tax_rate": 0.25,
            "capital_constraints": {"risk_weighted_assets": 800, "cet1_capital": 100, "minimum_cet1_ratio": 0.1,
                                    "dividend_payout": 0.5, "source_ref": "F1"}}


def test_complete_industrial_known_answers_and_no_mutation():
    config = _base()
    before = copy.deepcopy(config)
    result = evaluate_topics(config)
    assert result["status"] == "OK", result["findings"]
    assert config == before
    bridge = result["modules"]["forecast"]["bridge"]
    assert bridge["revenue"] == 120
    assert bridge["gross_profit"] == 48
    assert bridge["ebit"] == 23
    assert bridge["nopat"] == pytest.approx(17.25)
    assert bridge["fcff"] == pytest.approx(9.25)
    assert result["modules"]["forecast"]["weighted_value"] == 120
    assert result["assumptions_used"][0]["id"] == "A1"


@pytest.mark.parametrize("profile", list(PROFILES))
def test_explicit_industry_profiles_do_not_default_to_fcff(profile):
    result = evaluate_topics(_base(industry={"profile": profile, "order_based": False}))
    industry = result["modules"]["industry"]
    assert industry["profile"] == profile
    assert industry["primary_method"] == PROFILES[profile][0][0]
    assert industry["status"] == "OK"


def test_unknown_industry_and_missing_order_flag_are_incomplete():
    result = evaluate_topics(_base(industry={"profile": "unclassified insurer"}))
    assert result["status"] == "INCOMPLETE"
    assert result["modules"]["industry"]["primary_method"] is None
    assert result["modules"]["industry"]["order_applicability"] == "UNKNOWN"
    assert result["modules"]["orders"]["status"] == "INCOMPLETE"


@pytest.mark.parametrize("profile,method", [("banks", "EV/EBITDA"), ("life_insurance", "bank_rotce"), ("mining_production", "perpetuity"), ("mreit", "p_affo")])
def test_disabled_industry_methods_are_invalid(profile, method):
    result = evaluate_topics(_base(industry={"profile": profile, "order_based": False, "primary_method": method}))
    assert result["modules"]["industry"]["status"] == "INVALID"
    assert result["status"] == "INVALID"
    assert "disabled_method_selected" in _codes(result)


def test_guidance_initial_miss_and_revision_met_are_both_visible():
    config = _base(guidance={"versions": [
        _meta(id="G1", status="initial", published_at="2025-01-01", lower=90, upper=110),
        _meta(id="G2", status="lowered", published_at="2025-07-01", lower=70, upper=80, previous_version_id="G1")],
        "actuals": [_meta(value=75, published_at="2026-01-31")]})
    result = evaluate_topics(config)
    assert result["status"] == "OK", result["findings"]
    guidance = result["modules"]["guidance"]
    assert guidance["initial_vs_last_valid"] == {"initial_id": "G1", "last_valid_id": "G2"}
    assert [item["status"] for item in guidance["actual_evaluation"]] == ["MISSED", "MET"]


def test_guidance_groups_multiple_metrics_instead_of_global_initial():
    config = _base(guidance={"versions": [
        _meta(id="P1", status="initial", published_at="2025-01-01", lower=90, upper=110),
        _meta(id="R1", metric="revenue", status="initial", published_at="2025-01-01", lower=900, upper=1100)],
        "actuals": [_meta(value=100, published_at="2026-01-31"), _meta(metric="revenue", value=1000, published_at="2026-01-31")]})
    result = evaluate_topics(config)
    assert len(result["modules"]["guidance"]["series"]) == 2
    assert {record["version_id"] for record in result["modules"]["guidance"]["actual_evaluation"]} == {"P1", "R1"}


def test_reused_guidance_series_id_still_separates_entities_periods_and_metrics():
    config = _base()
    config["guidance"] = {"versions": [
        _meta(id="G1", guidance_id="annual", status="initial", published_at="2025-01-01", lower=90, upper=110),
        _meta(id="G2", guidance_id="annual", metric="revenue", status="initial", published_at="2025-01-01", lower=900, upper=1100)],
        "actuals": [_meta(guidance_id="annual", value=100, published_at="2026-01-31"),
                    _meta(guidance_id="annual", metric="revenue", value=1000, published_at="2026-01-31")]}
    result = evaluate_topics(config)
    assert len(result["modules"]["guidance"]["series"]) == 2
    assert {record["version_id"] for record in result["modules"]["guidance"]["actual_evaluation"]} == {"G1", "G2"}


@pytest.mark.parametrize("missing", ["unit", "currency", "scope", "basis", "entity", "metric", "period"])
def test_guidance_missing_comparison_metadata_never_met_or_missed(missing):
    config = _base()
    del config["guidance"]["actuals"][0][missing]
    result = evaluate_topics(config)
    assert result["modules"]["guidance"]["status"] == "INCOMPLETE"
    assert all(item["status"] not in {"MET", "MISSED"} for item in result["modules"]["guidance"]["actual_evaluation"])


def test_withdrawal_removes_current_valid_version_without_reusing_old_version():
    config = _base()
    config["guidance"]["versions"].append(_meta(id="GW", status="withdrawn", published_at="2025-04-01", previous_version_id="G1"))
    guidance = evaluate_topics(config)["modules"]["guidance"]
    assert guidance["series"][0]["withdrawn"] is True
    assert guidance["initial_vs_last_valid"]["last_valid_id"] is None
    assert guidance["actual_evaluation"][1]["status"] == "WITHDRAWN"


def test_guidance_future_versions_and_future_actuals_are_excluded():
    config = _base()
    config["guidance"]["versions"].append(_meta(id="GF", status="raised", published_at="2026-04-01", lower=1000, upper=2000))
    config["guidance"]["actuals"][0]["published_at"] = "2026-04-30"
    result = evaluate_topics(config)
    guidance = result["modules"]["guidance"]
    assert [record["id"] for record in guidance["versions"]] == ["G1"]
    assert {record["reason"] for record in guidance["excluded"]} == {"AFTER_AS_OF", "ACTUAL_AFTER_AS_OF"}
    assert all(record["actual"] is None for record in guidance["actual_evaluation"])


def test_initial_guidance_published_after_results_cannot_score_a_hit():
    config = _base()
    config["guidance"]["versions"][0]["published_at"] = "2026-02-01"
    result = evaluate_topics(config)
    assert result["modules"]["guidance"]["status"] == "INCOMPLETE"
    assert all(item["status"] not in {"MET", "MISSED"} for item in result["modules"]["guidance"]["actual_evaluation"])
    assert "guidance_post_results" in _codes(result)


def test_missing_guidance_bounds_is_unavailable_not_missed():
    config = _base()
    del config["guidance"]["versions"][0]["lower"]
    result = evaluate_topics(config)
    assert result["modules"]["guidance"]["status"] == "INCOMPLETE"
    assert all(item["status"] != "MISSED" for item in result["modules"]["guidance"]["actual_evaluation"])


def test_explicit_guidance_non_disclosure_is_not_applicable():
    config = _base(guidance={"disclosed": False, "reason": "issuer does not issue quantitative guidance"})
    result = evaluate_topics(config)
    assert result["modules"]["guidance"]["status"] == "NOT_APPLICABLE"


def test_gross_and_net_order_known_answers_and_zero_preserved():
    result = evaluate_topics(_base())
    bridge = result["modules"]["orders"]["bridges"][0]
    assert bridge["gross"]["expected_closing"] == 110
    assert bridge["net"]["expected_closing"] == 110
    assert bridge["gross"]["residual"] == 0
    assert bridge["net"]["cancelled"] is None
    assert bridge["gross"]["fx_scope_adjustment"] == 0


@pytest.mark.parametrize("missing", ["fx_scope_adjustment", "cancelled", "new_included", "fulfilled"])
def test_unknown_order_components_not_silently_zero(missing):
    config = _base()
    del config["orders"]["bridges"][0]["gross"][missing]
    result = evaluate_topics(config)
    gross = result["modules"]["orders"]["bridges"][0]["gross"]
    assert result["modules"]["orders"]["status"] == "INCOMPLETE"
    assert gross["expected_closing"] is None
    assert gross["residual"] is None
    assert missing in gross["unknown_components"]
    assert gross["residual_unexplained"] is not None


def test_each_order_bridge_is_validated_and_bad_net_residual_cannot_hide():
    config = _base()
    config["orders"]["bridges"][0]["net"]["closing"] = 120
    result = evaluate_topics(config)
    assert result["modules"]["orders"]["status"] == "INCOMPLETE"
    assert "order_residual_unexplained" in _codes(result)


def test_nested_order_metadata_mismatch_is_invalid():
    config = _base()
    config["orders"]["bridges"][0]["net"]["unit"] = "billion"
    result = evaluate_topics(config)
    assert result["status"] == "INVALID"
    assert "order_metadata_mismatch" in _codes(result)


def test_empty_cash_link_object_does_not_pass_profit_and_cash_validation():
    config = _base()
    config["orders"]["cash_links"] = [{}]
    result = evaluate_topics(config)
    assert result["modules"]["orders"]["status"] == "INCOMPLETE"
    assert "order_profit_link_missing" in _codes(result)
    assert "order_cash_link_missing" in _codes(result)


@pytest.mark.parametrize("key,value", [("opening", -1), ("cancelled", -1), ("new_is_net", "false")])
def test_invalid_order_sign_or_bool_is_not_hidden(key, value):
    config = _base()
    config["orders"]["bridges"][0]["gross"][key] = value
    result = evaluate_topics(config)
    assert result["status"] == "INVALID"


def test_non_order_business_is_not_applicable_without_zero_bridges():
    result = evaluate_topics(_base(industry={"profile": "consumer", "order_based": False}, orders=None))
    assert result["status"] == "OK", result["findings"]
    assert result["modules"]["orders"]["status"] == "NOT_APPLICABLE"
    assert result["modules"]["orders"]["bridges"] == []


@pytest.mark.parametrize("field", ["gross_margin", "opex", "da", "tax_rate", "capex", "delta_nwc"])
def test_forecast_profit_cash_missing_drivers_propagate_null(field):
    config = _base()
    del config["forecast"][field]
    result = evaluate_topics(config)
    assert result["modules"]["forecast"]["status"] == "INCOMPLETE"
    assert result["modules"]["forecast"]["bridge"]["fcff"] is None


def test_inclusive_da_is_not_deducted_twice_and_mixed_da_requires_split():
    config = _base()
    forecast = config["forecast"]
    forecast.update(opex_excludes_da=False, gross_margin_excludes_da=False)
    bridge = evaluate_topics(config)["modules"]["forecast"]["bridge"]
    assert bridge["ebit"] == 28
    assert bridge["additional_da_deduction"] == 0
    forecast["opex_excludes_da"] = True
    result = evaluate_topics(config)
    assert result["modules"]["forecast"]["status"] == "INCOMPLETE"
    assert result["modules"]["forecast"]["bridge"]["ebit"] is None
    forecast["opex_da"] = 2
    assert evaluate_topics(config)["modules"]["forecast"]["bridge"]["ebit"] == 26


def test_negative_profit_does_not_silently_create_tax_benefit():
    config = _base()
    config["forecast"]["gross_margin"] = -0.1
    result = evaluate_topics(config)
    assert result["modules"]["forecast"]["bridge"]["ebit"] == -37
    assert result["modules"]["forecast"]["bridge"]["nopat"] is None
    assert result["modules"]["forecast"]["status"] == "INCOMPLETE"
    config["forecast"]["loss_tax_benefit"] = False
    assert evaluate_topics(config)["modules"]["forecast"]["bridge"]["nopat"] == -37
    config["forecast"]["loss_tax_benefit"] = True
    assert evaluate_topics(config)["modules"]["forecast"]["bridge"]["nopat"] == pytest.approx(-27.75)


def test_order_conversion_forecast_requires_delivery_period_and_is_not_qty_price_only():
    config = _base()
    forecast = config["forecast"]
    forecast["revenue_mode"] = "order_conversion"
    forecast["order_batches"] = [{"id": "B1", "amount": 200, "conversion_rate": 0.6, "delivery_period": "2026", "source_ref": "F1"}]
    result = evaluate_topics(config)
    assert result["modules"]["forecast"]["bridge"]["revenue"] == 120
    assert result["modules"]["forecast"]["bridge"]["fcff"] == pytest.approx(9.25)
    forecast["order_batches"][0]["delivery_period"] = "2027"
    result = evaluate_topics(config)
    assert result["modules"]["forecast"]["bridge"]["revenue"] is None
    assert result["modules"]["forecast"]["status"] == "INCOMPLETE"


def test_quantity_price_requires_matching_quantity_units():
    config = _base()
    config["forecast"].update(revenue_mode="quantity_price", quantity=10, price=12, quantity_unit="ton", price_quantity_unit="ton")
    assert evaluate_topics(config)["modules"]["forecast"]["bridge"]["revenue"] == 120
    config["forecast"]["price_quantity_unit"] = "kg"
    result = evaluate_topics(config)
    assert result["modules"]["forecast"]["bridge"]["revenue"] is None
    assert result["modules"]["forecast"]["status"] == "INCOMPLETE"


@pytest.mark.parametrize("probability", [-0.1, 1.1, "0.5", True])
def test_bad_scenario_probabilities_invalidate_weighting(probability):
    config = _base()
    config["forecast"]["scenarios"][0]["probability"] = probability
    result = evaluate_topics(config)
    assert result["status"] == "INVALID"
    assert result["modules"]["forecast"]["weighted_value"] is None


def test_probability_sum_not_one_is_invalid_without_renormalisation():
    config = _base()
    config["forecast"]["scenarios"][0]["probability"] = 0.2
    result = evaluate_topics(config)
    assert result["status"] == "INVALID"
    assert result["modules"]["forecast"]["weighted_value"] is None


def test_bank_forecast_needs_all_capital_and_operating_drivers_and_has_known_answer():
    config = _base(industry={"profile": "banks", "order_based": False}, forecast=_bank_forecast(),
                   decision={"recommendation": "observe", "capital_metrics": {"ptbv": 1.2, "ke": 0.1, "g": 0.03, "source_ref": "F1"}})
    result = evaluate_topics(config)
    assert result["status"] == "OK", result["findings"]
    forecast = result["modules"]["forecast"]
    assert forecast["bridge"]["net_interest_income"] == 32
    assert forecast["bridge"]["net_profit"] == pytest.approx(14.25)
    assert forecast["capital_constraints"]["required_cet1"] == 80
    assert forecast["capital_constraints"]["capital_limited_distribution"] == pytest.approx(7.125)
    capital = result["modules"]["decision"]["capital_metrics"]
    assert capital["roic"]["status"] == "NOT_APPLICABLE"
    assert capital["implied_rotce"]["value"] == pytest.approx(0.114)
    config["forecast"]["capital_constraints"] = {"cet1_capital": 100}
    assert evaluate_topics(config)["modules"]["forecast"]["status"] == "INCOMPLETE"


def test_bank_capital_shortfall_blocks_unconstrained_distributions():
    forecast = _bank_forecast()
    forecast["capital_constraints"]["cet1_capital"] = 70
    result = evaluate_topics(_base(industry={"profile": "banks", "order_based": False}, forecast=forecast))
    assert result["modules"]["forecast"]["capital_constraints"]["capital_limited_distribution"] == 0
    assert result["modules"]["forecast"]["status"] == "INCOMPLETE"
    assert "bank_capital_shortfall" in _codes(result)


def test_life_insurer_does_not_receive_bank_forecast_or_bank_implied_rotce():
    config = _base(industry={"profile": "life_insurance", "order_based": False}, forecast=_bank_forecast(),
                   decision={"capital_metrics": {"ptbv": 1, "ke": 0.1, "g": 0.03, "source_ref": "F1"}})
    result = evaluate_topics(config)
    assert result["modules"]["forecast"]["status"] == "INCOMPLETE"
    assert "implied_rotce" not in result["modules"]["decision"]["capital_metrics"]


def test_roiic_is_delta_nopat_over_delta_ic_without_dividing_multi_year_window():
    capital = evaluate_topics(_base())["modules"]["decision"]["capital_metrics"]
    assert capital["roiic"]["value"] == pytest.approx(0.45)
    assert capital["roiic"]["window_years"] > 1.99
    assert capital["roic"]["value"] == pytest.approx(24 / 110)


@pytest.mark.parametrize("begin,end", [(100, 100), (100, 80), (-10, -20)])
def test_nonpositive_incremental_capital_is_diagnostic_not_normal_return(begin, end):
    config = _base()
    config["decision"]["capital_metrics"].update(invested_capital_begin=begin, invested_capital_end=end)
    result = evaluate_topics(config)
    assert result["modules"]["decision"]["capital_metrics"]["roiic"]["value"] is None
    assert result["modules"]["decision"]["status"] == "INCOMPLETE"


def test_empty_counterargument_list_is_incomplete_and_refs_are_not_factual_verification():
    config = _base()
    thesis = evaluate_topics(config)["modules"]["theses"]
    assert thesis["claims"][0]["counterarguments"][0]["citation_status"] == "RESOLVED_REFERENCE"
    config["theses"]["items"][0]["counterarguments"] = []
    assert evaluate_topics(config)["modules"]["theses"]["status"] == "INCOMPLETE"


def test_self_referencing_counterargument_and_non_assumption_change_ids_are_invalid():
    config = _base()
    counter = config["theses"]["items"][0]["counterarguments"][0]
    counter["refs"] = ["SELF"]
    counter["changed_assumption_ids"] = ["F1"]
    result = evaluate_topics(config)
    assert result["status"] == "INVALID"
    assert result["modules"]["theses"]["claims"][0]["counterarguments"][0]["citation_status"] == "UNRESOLVED_REFERENCE"


@pytest.mark.parametrize("field", ["disposition", "reason", "action", "verify_date", "changed_assumption_ids"])
def test_counterargument_requires_disposition_and_followup_fields(field):
    config = _base()
    del config["theses"]["items"][0]["counterarguments"][0][field]
    assert evaluate_topics(config)["modules"]["theses"]["status"] in {"INVALID", "INCOMPLETE"}


def test_arbitrary_source_ref_cannot_self_authenticate_a_fact():
    config = _base()
    fact = config["facts"]["records"][0]
    del fact["source"]
    fact["source_ref"] = "F1"
    result = evaluate_topics(config)
    assert result["status"] == "INVALID"
    assert "fact_source_missing" in _codes(result)


def test_external_reference_with_locator_is_accepted_but_path_only_is_not():
    config = _base()
    fact = config["facts"]["records"][0]
    del fact["source"]
    fact["external_ref"] = {"path": "data/report.pdf", "locator": "p10"}
    assert evaluate_topics(config)["registry"]["status"] == "OK"
    del fact["external_ref"]["locator"]
    result = evaluate_topics(config)
    assert result["registry"]["status"] in {"INCOMPLETE", "INVALID"}
    assert "fact_source_missing" in _codes(result)


def test_duplicate_fact_and_assumption_ids_are_invalid():
    config = _base()
    config["assumptions"][0]["id"] = "F1"
    assert evaluate_topics(config)["status"] == "INVALID"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_anywhere_returns_invalid_without_serialization_exception(value):
    config = _base()
    config["free_prose_metadata"] = {"nested": [value]}
    result = evaluate_topics(config)
    assert result["status"] == "INVALID"
    json.dumps(result, allow_nan=False)


def test_finite_inputs_that_overflow_calculation_return_invalid_with_null_result():
    config = _base()
    config["forecast"].update(revenue_mode="quantity_price", quantity=1e308, price=1e308, quantity_unit="unit", price_quantity_unit="unit")
    result = evaluate_topics(config)
    assert result["status"] == "INVALID"
    assert result["modules"]["forecast"]["bridge"]["revenue"] is None
    json.dumps(result, allow_nan=False)


def test_non_json_python_value_returns_invalid_instead_of_raising():
    config = _base()
    config["accidental_set"] = {"bad"}
    assert evaluate_topics(config)["status"] == "INVALID"


def test_future_fact_cannot_be_used_to_self_validate_an_asof_model():
    config = _base()
    config["facts"]["records"][0]["published_at"] = "2026-04-01"
    result = evaluate_topics(config)
    assert result["status"] == "INVALID"
    assert "fact_after_as_of" in _codes(result)


def test_driver_reference_unit_and_period_are_validated():
    config = _base()
    config["assumptions"][0]["unit"] = "billion"
    result = evaluate_topics(config)
    assert result["status"] == "INVALID"
    assert result["modules"]["forecast"]["bridge"]["revenue"] is None


def test_asof_argument_overrides_config_and_omitting_asof_stays_deterministic():
    config = _base()
    result = evaluate_topics(config, as_of="2025-12-31")
    assert result["as_of"] == "2025-12-31"
    assert all(item["actual"] is None for item in result["modules"]["guidance"]["actual_evaluation"])
    del config["as_of"]
    result = evaluate_topics(config)
    assert result["generated_at"] is None
    assert result["status"] == "INCOMPLETE"
    assert result == evaluate_topics(config)


def test_zero_values_are_not_replaced_by_fallbacks():
    config = _base()
    config["assumptions"][0]["value"] = 0
    config["forecast"].update(gross_margin=0, opex=0, da=0, tax_rate=0, capex=0, delta_nwc=0)
    result = evaluate_topics(config)
    bridge = result["modules"]["forecast"]["bridge"]
    assert bridge["revenue"] == 0
    assert bridge["fcff"] == 0
    assert result["status"] == "OK"


def test_same_input_is_deterministic_and_findings_are_consistently_aggregated():
    config = _base()
    del config["forecast"]["capex"]
    result = evaluate_topics(config)
    assert result == evaluate_topics(config)
    module_findings = [finding for module in result["modules"].values() for finding in module["findings"]]
    assert all(finding in result["findings"] for finding in module_findings)


def test_missing_file_writes_incomplete_and_invalid_json_writes_invalid_atomically(tmp_path: Path):
    payload, code = run(tmp_path)
    assert (payload["status"], code) == ("INCOMPLETE", 2)
    output = tmp_path / "reports" / "研究模型_输出.json"
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "INCOMPLETE"
    input_path = tmp_path / "input" / "研究模型.json"
    input_path.parent.mkdir()
    input_path.write_text("{bad}", encoding="utf-8")
    payload, code = run(tmp_path)
    assert (payload["status"], code) == ("INVALID", 3)
    assert not output.with_suffix(".json.tmp").exists()


def test_successful_run_writes_the_exact_recalculated_contract(tmp_path: Path):
    path = tmp_path / "input" / "研究模型.json"
    path.parent.mkdir()
    path.write_text(json.dumps(_base(), ensure_ascii=False), encoding="utf-8")
    payload, code = run(tmp_path)
    assert code == 0
    assert payload["status"] == "OK"
    assert payload == json.loads((tmp_path / "reports" / "研究模型_输出.json").read_text(encoding="utf-8"))


def _input_path(tmp_path: Path) -> Path:
    path = tmp_path / "input" / "研究模型.json"
    path.parent.mkdir(exist_ok=True)
    return path


def test_run_input_limit_matches_qc_and_accepts_exactly_ten_mb(tmp_path: Path):
    assert research_topics.MAX_INPUT_BYTES == 10_000_000
    raw = json.dumps(_base(), ensure_ascii=False).encode("utf-8-sig")
    path = _input_path(tmp_path)
    path.write_bytes(raw + b" " * (research_topics.MAX_INPUT_BYTES - len(raw)))
    payload, code = run(tmp_path)
    assert (payload["status"], code) == ("OK", 0)


def test_run_rejects_oversized_stat_without_opening_input(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(research_topics, "MAX_INPUT_BYTES", 128)
    path = _input_path(tmp_path)
    path.write_bytes(b" " * 129)
    original_open = Path.open

    def guarded_open(self, *args, **kwargs):
        if self == path:
            pytest.fail("oversized input must be rejected before opening it")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    payload, code = run(tmp_path)
    assert (payload["status"], code) == ("INVALID", 3)
    assert "研究模型输入超过" in payload["findings"][0]["message"]


def test_run_bounded_read_rejects_input_growing_after_stat(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(research_topics, "MAX_INPUT_BYTES", 128)
    path = _input_path(tmp_path)
    path.write_bytes(b"{}")
    original_open = Path.open
    reads = []

    class GrowingInput(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def growing_open(self, *args, **kwargs):
        if self == path:
            assert args == ("rb",)
            return GrowingInput(b" " * 10_000)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", growing_open)
    payload, code = run(tmp_path)
    assert reads == [129]
    assert (payload["status"], code) == ("INVALID", 3)
    assert "研究模型输入超过" in payload["findings"][0]["message"]


@pytest.mark.parametrize("raw", [b"{bad}", b"\xff", b"[" * 2_000 + b"0" + b"]" * 2_000], ids=["bad-json", "bad-utf8", "deep-json"])
def test_run_malformed_encoding_json_and_deep_nesting_are_structured_invalid(tmp_path: Path, raw):
    _input_path(tmp_path).write_bytes(raw)
    payload, code = run(tmp_path)
    assert (payload["status"], code) == ("INVALID", 3)
    assert _codes(payload) == ["input_json_invalid"]
    assert payload == json.loads((tmp_path / "reports" / "研究模型_输出.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("value", [None, [], "wrong root", 1, True])
def test_run_bad_root_types_are_structured_invalid(tmp_path: Path, value):
    _input_path(tmp_path).write_text(json.dumps(value), encoding="utf-8")
    payload, code = run(tmp_path)
    assert (payload["status"], code) == ("INVALID", 3)
    assert _codes(payload) == ["input_type"]


@pytest.mark.parametrize("field,value", [("industry", []), ("guidance", "bad"), ("orders", True), ("forecast", 7), ("theses", [None]), ("decision", "bad")])
def test_run_bad_nested_module_types_do_not_escape(tmp_path: Path, field, value):
    config = _base()
    config[field] = value
    _input_path(tmp_path).write_text(json.dumps(config), encoding="utf-8")
    payload, code = run(tmp_path)
    assert (payload["status"], code) == ("INVALID", 3)
    json.dumps(payload, allow_nan=False)


def test_run_parseable_deep_model_is_rejected_before_calculation(tmp_path: Path):
    raw = '{"schema_version":1,"nested":' + "[" * 600 + "0" + "]" * 600 + "}"
    assert isinstance(json.loads(raw), dict)
    _input_path(tmp_path).write_text(raw, encoding="utf-8")
    payload, code = run(tmp_path)
    assert (payload["status"], code) == ("INVALID", 3)
    assert _codes(payload) == ["input_json_invalid"]
    assert "嵌套超过128层" in payload["findings"][0]["message"]


@pytest.mark.parametrize("depth,expected", [(127, ("INCOMPLETE", 0)), (128, ("INVALID", 3))])
def test_run_nesting_limit_has_a_deterministic_boundary(tmp_path: Path, depth, expected):
    raw = '{"schema_version":1,"nested":' + "[" * depth + "0" + "]" * depth + "}"
    _input_path(tmp_path).write_text(raw, encoding="utf-8")
    payload, code = run(tmp_path)
    assert (payload["status"], code) == expected


@pytest.mark.parametrize("error_type", [TypeError, ValueError, KeyError, AttributeError, RecursionError, OverflowError])
def test_run_calculation_input_errors_are_contained(tmp_path: Path, monkeypatch, error_type):
    _input_path(tmp_path).write_text("{}", encoding="utf-8")

    def invalid_model(*args, **kwargs):
        raise error_type("invalid nested model input")

    monkeypatch.setattr(research_topics, "evaluate_topics", invalid_model)
    payload, code = run(tmp_path)
    assert (payload["status"], code) == ("INVALID", 3)
    assert _codes(payload) == ["input_model_invalid"]
    assert error_type.__name__ in payload["findings"][0]["message"]


@pytest.mark.parametrize("raw", [b"{bad}", b"[" * 2_000 + b"0" + b"]" * 2_000, b"null"], ids=["bad-json", "deep-json", "null-root"])
def test_run_cli_invalid_input_exits_with_json_and_no_traceback(tmp_path: Path, raw):
    _input_path(tmp_path).write_bytes(raw)
    script = Path(research_topics.__file__)
    result = run_process([sys.executable, "-B", "-X", "utf8", str(script), "--dir", str(tmp_path)], timeout=10, heartbeat=1, echo=False)
    assert result["exit_code"] == 3, result
    assert result["status"] == "FAIL"
    assert "Traceback" not in result["output"]
    assert json.loads(result["output"].strip())["status"] == "INVALID"
    assert json.loads((tmp_path / "reports" / "研究模型_输出.json").read_text(encoding="utf-8"))["status"] == "INVALID"


@pytest.mark.parametrize("raw", [None, b"{bad}", b"null"])
def test_repeated_run_preserves_unchanged_output_and_has_no_side_artifacts(tmp_path: Path, raw):
    path = _input_path(tmp_path)
    path.write_bytes(json.dumps(_base(), ensure_ascii=False).encode("utf-8") if raw is None else raw)
    first_payload, first_code = run(tmp_path)
    output = tmp_path / "reports" / "研究模型_输出.json"
    first_stat = output.stat()
    for _ in range(3):
        assert run(tmp_path) == (first_payload, first_code)
    assert output.stat().st_mtime_ns == first_stat.st_mtime_ns
    assert {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()} == {"input/研究模型.json", "reports/研究模型_输出.json"}
