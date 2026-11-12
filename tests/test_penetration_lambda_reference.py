"""Regression: an unstable nonzero slope must not become zero exposure."""
from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from calc_penetration_return import compute, diagnose_lambda


def config():
    return {'price': 10., 'shares': 100., 'market_cap': 1000.,
            'net_profit_C': 200., 'depreciation_D': 10., 'capex_ratio_G': 1.,
            'payout_M': .4, 'aa_2y': 50., 'rf': .02, 'base_revenue': 500.,
            'surplus_series': [60., 40., 50., 20., 40.],
            'revenue_series': [500., 400., 300., 200., 100.],
            'financial_years': [2025, 2024, 2023, 2022, 2021],
            'lambda_policy': 'historical_mean_reference', 'lambda': 0.}


def test_mixed_sign_estimate_is_retained_and_critical_point_is_suppressed():
    result = compute(config())
    assert result['lambda'] == pytest.approx(.05)
    assert result['lambda_reliable'] is False
    assert result['k_star'] is None
    assert result['single_year'][0]['gg'] == pytest.approx(.02)
    assert result['single_year'][-1]['gg'] == pytest.approx(.017)
    assert result['single_year'][-1]['target_buy'] == pytest.approx(4.25)
    assert '仅供' in result['lambda_warning']


def test_reliability_change_does_not_change_primary_valuation():
    cfg = config()
    reference = compute(cfg)
    legacy = compute({**cfg, 'lambda_policy': 'legacy_zero'})
    for key in ('R_star', 'GG', 'r_eff', 'II', 'KK', 'target_buy', 'floor_price'):
        assert reference[key] == legacy[key]


def test_stable_historical_slope_can_support_critical_point():
    cfg = config()
    cfg['surplus_series'] = [100., 80., 60., 40., 20.]
    result = compute(cfg)
    assert result['lambda'] == pytest.approx(.2)
    assert result['lambda_reliable'] is True
    assert result['k_star'] is not None


def test_negative_mean_is_preserved_instead_of_selecting_only_positive_segments():
    cfg = config()
    cfg['surplus_series'] = [40., 60., 50., 80., 60.]
    result = compute(cfg)
    assert result['lambda'] == pytest.approx(-.05)
    assert result['lambda_reliable'] is False
    assert result['single_year'][-1]['gg'] > result['single_year'][0]['gg']


def test_missing_reference_data_cannot_be_replaced_with_zero():
    cfg = config()
    cfg['revenue_series'] = []
    with pytest.raises(ValueError, match='不得填0'):
        compute(cfg)


def test_diagnostics_include_source_periods_and_flag_invalid_pairs():
    cfg = config()
    result = diagnose_lambda(cfg)
    assert result['intervals'][0]['period'] == '2025/2024'
    assert [row['slope'] for row in result['intervals']] == pytest.approx([.2, -.1, .3, -.2])
    cfg['surplus_series'][1] = float('nan')
    result = diagnose_lambda(cfg)
    assert result['reliable'] is False
    assert any('非有限值' in reason for reason in result['reasons'])


def test_a_true_zero_average_is_kept_with_its_unreliable_diagnosis():
    cfg = config()
    cfg['surplus_series'] = [40., 20., 40., 20., 40.]
    result = compute(cfg)
    assert result['lambda'] == pytest.approx(0.)
    assert result['lambda_diagnostics']['raw_mean'] == pytest.approx(0.)
    assert result['lambda_reliable'] is False
    assert result['k_star'] is None


def test_reference_mode_skips_missing_pairs_without_legacy_arithmetic():
    cfg = config()
    cfg['lambda'] = None
    cfg['surplus_series'][1] = None
    result = compute(cfg)
    assert result['lambda'] == pytest.approx(.05)
    assert result['lambda_reliable'] is False
    assert result['k_star'] is None


@pytest.mark.parametrize('zero_mean', [False, True])
def test_default_chart_preserves_reference_values_and_passes_semantic_gate(tmp_path, zero_mean):
    from analyze_charts import _script_sensitivity
    from chart_qc import check_sensitivity_contract

    cfg = config()
    if zero_mean:
        cfg['surplus_series'] = [40., 20., 40., 20., 40.]
    result = compute(cfg)
    (tmp_path / 'reports').mkdir()
    (tmp_path / 'input').mkdir()
    (tmp_path / 'reports/穿透回报率_输出.json').write_text(json.dumps(result), encoding='utf-8')
    chart = _script_sensitivity(tmp_path)
    (tmp_path / 'input/运营补充数据.json').write_text(json.dumps({'sensitivity': chart}), encoding='utf-8')
    (tmp_path / 'input/穿透回报率_输入.json').write_text(json.dumps({'lambda': result['lambda']}), encoding='utf-8')
    assert chart['系列'][0]['y'] == pytest.approx([r['gg'] * 100 for r in result['single_year']])
    assert '低可靠性' in chart['标题'] or 'λ为零' in chart['标题']
    assert ('收入倍数' in chart['xlabel']) is not zero_mean
    _, failures = check_sensitivity_contract(tmp_path, '![图11 敏感性](图表/图11_敏感性分析.png)')
    assert failures == []


def test_nonzero_decimal_does_not_excuse_a_flat_chart(tmp_path):
    from chart_qc import check_sensitivity_contract

    (tmp_path / 'input').mkdir()
    sensitivity = {'mode': 'script_cash_surplus', 'x': [1., .9],
                   '系列': [{'name': 'GG', 'y': [2., 2.]}],
                   '门槛': 4., 'xlabel': '收入倍数', '注': 'λ=0.0117'}
    (tmp_path / 'input/运营补充数据.json').write_text(json.dumps({'sensitivity': sensitivity}), encoding='utf-8')
    _, failures = check_sensitivity_contract(tmp_path, '![图11 敏感性](图表/图11_敏感性分析.png)')
    assert any('is flat' in finding for finding in failures)
    assert not any('lambda=0 but' in finding for finding in failures)
