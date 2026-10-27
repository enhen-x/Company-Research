"""Exemptions must avoid work while retaining explicit data and stale-output checks."""
import json
import sys

import pytest

import analyze_charts as charts
from chart_qc import _chart_exemptions, check_listing_vs_embed, check_ops_contract, check_valuation_band_contract


def _input(project, payload, name="图表豁免.json"):
    target = project / "input" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8-sig")
    return target


@pytest.mark.parametrize("entry", [
    {"图": "图99", "原因": "not applicable"},
    {"图": "图06", "原因": None},
    {"图": "图06", "原因": []},
    {"图": "图06", "原因": "  "},
    {"图": ["图06"], "原因": "invalid label"},
])
def test_malformed_exemptions_are_rejected(tmp_path, entry):
    _input(tmp_path, {"豁免": [entry]})
    with pytest.raises(ValueError):
        _chart_exemptions(tmp_path)


def test_listing_reads_the_requested_batch_not_the_script_location(tmp_path):
    _input(tmp_path, {"豁免": [{"图": "图06", "原因": "independent disclosure missing"}]})
    _input(tmp_path, {"enabled": False}, "sotp_触发.json")
    lines = ["| 图06 | peers | §6 |", "| 图18 | SOTP | §6 |"]
    assert check_listing_vs_embed(lines, tmp_path) == []
    _input(tmp_path, {"豁免": []})
    assert any("图06" in error for error in check_listing_vs_embed(lines, tmp_path))


def test_peers_exemption_allows_missing_but_rejects_supplied_bad_data(tmp_path):
    _input(tmp_path, {"豁免": [{"图": "图06", "原因": "no comparable firms disclosed"}]})
    _input(tmp_path, {"peers": []}, "运营补充数据.json")
    assert not check_ops_contract(tmp_path)[1]
    _input(tmp_path, {"peers": ["invalid record"]}, "运营补充数据.json")
    assert any("peers" in error for error in check_ops_contract(tmp_path)[1])


@pytest.mark.parametrize("payload", [[], None, "invalid", 1,
    {"leverage": [1]}, {"forecast": True}, {"cashflow": {"labels": 3}},
    {"segment": {"series": [None]}}, {"segment": {"series": [{"values": 2}]}},
    {"segment": {"增速": []}}, {"segment": {"增速": {"合计增速": 2}}},
    {"sensitivity": {"系列": ["invalid"]}}, {"sensitivity": {"x": "invalid"}},
    {"pe_band": {"labels": {"year": 2026}}},
])
def test_malformed_operational_containers_fail_without_traceback(tmp_path, payload):
    _input(tmp_path, payload, "运营补充数据.json")
    for check in (check_ops_contract, check_valuation_band_contract):
        assert check(tmp_path)[1]


@pytest.mark.parametrize("raw", ["{broken json", "[" * 1100 + "]" * 1100])
def test_unreadable_or_deep_operational_json_is_a_failure(tmp_path, raw):
    path = _input(tmp_path, {}, "运营补充数据.json")
    path.write_text(raw, encoding="utf-8")
    for check in (check_ops_contract, check_valuation_band_contract):
        assert check(tmp_path)[1]


def test_oversized_operational_json_is_rejected_before_read(tmp_path):
    path = _input(tmp_path, {}, "运营补充数据.json")
    with path.open("wb") as stream:
        stream.truncate(10 * 1024 * 1024 + 1)
    for check in (check_ops_contract, check_valuation_band_contract):
        assert any("10 MiB" in error for error in check(tmp_path)[1])


def test_bom_and_optional_null_series_do_not_crash(tmp_path):
    _input(tmp_path, {"豁免": [{"图": "图06", "原因": "no comparable disclosure"}]})
    _input(tmp_path, {"segment": {"labels": ["A"], "series": [{"values": None}], "增速": None},
                      "forecast": {"labels_fcast": [2027], "基准": None}}, "运营补充数据.json")
    assert not check_ops_contract(tmp_path)[1]
    assert not check_valuation_band_contract(tmp_path)[1]


@pytest.mark.parametrize("stale", [False, True])
def test_exempted_charts_do_not_call_factories_or_accept_stale_png(tmp_path, monkeypatch, stale):
    entries = [{"图": f"图{i:02d}", "原因": "isolated exemption fixture"}
               for i in [*range(1, 17), 18]]
    _input(tmp_path, {"豁免": entries})
    _input(tmp_path, {"enabled": False}, "sotp_触发.json")
    monkeypatch.setattr(charts, "configure_latest", lambda *a, **k: {
        "latest_period": "2026-06-30", "has_interim_income": True})
    monkeypatch.setattr(charts, "load_csv", lambda *a: None)
    monkeypatch.setattr(charts, "load_industry_cost_price", lambda *a: None)

    def forbidden(*args, **kwargs):
        raise AssertionError("an exempt chart factory was evaluated")

    for name in ("fig_revenue", "fig_roe_bps", "fig_segment", "fig_profitability", "fig_cashflow",
                 "fig_peers", "fig_dps", "fig_price", "fig_targets", "fig_penetration", "fig_sensitivity",
                 "fig_forecast", "fig_pe_band", "fig_pb_band", "fig_leverage", "fig_industry_cost_price", "fig_sotp"):
        monkeypatch.setattr(charts, name, forbidden)
    import financial_history_charts
    monkeypatch.setattr(financial_history_charts, "write_interactive", lambda *a, **k: 1)
    marker = tmp_path / "reports/图表/图06_同行估值与增长对比.png"
    if stale:
        marker.parent.mkdir(parents=True)
        marker.write_bytes(b"previous artifact")
    monkeypatch.setattr(sys, "argv", ["analyze_charts.py", "--dir", str(tmp_path),
                                      "--code", "000001", "--data-date", "2026-10-28"])
    assert charts.main() == (2 if stale else 0)
    if stale:
        assert marker.read_bytes() == b"previous artifact"
