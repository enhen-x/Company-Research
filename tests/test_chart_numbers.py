"""Display precision and amount rescaling retain raw numeric meaning."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from chart_numbers import format_number, format_amount, figure_number_audit, report_amount_unit_violations


@pytest.mark.parametrize('yuan,expected', [
    (0,'0万元'), (8050000,'805万元'), (-62480000,'-6,248万元'),
    (99999999,'10,000万元'), (100000000,'1亿元'), (-100000000,'-1亿元'),
    (8343600000,'83.44亿元'), (0.01,'<0.01万元'), (-0.01,'>-0.01万元'),
    (None,'—'), (float('nan'),'—'), (float('inf'),'—'),
])
def test_amounts_scale_from_raw_yuan(yuan,expected):
    assert format_amount(yuan)==expected


def test_signed_amounts_and_missing_numbers():
    assert format_amount(362000000,signed=True)=='+3.62亿元'
    assert format_amount(-362000000,signed=True)=='-3.62亿元'
    assert format_number('invalid')=='—'
    assert format_number(float('inf'))=='—'
    assert format_number(.00001,signed=True)=='<0.01'
    assert format_number(-.00001,signed=True)=='>-0.01'


@pytest.mark.parametrize('text', ['市值100百万元','总股本80百万股','现金3百万美元','100 CNY million','USD million','million USD','金额单位：百万','市值10百万'])
def test_report_legacy_units_are_rejected(text):
    from report_template_qc import check_report
    assert report_amount_unit_violations(text)
    assert any('金额/股数单位' in failure for failure in check_report(text)[0])


def test_report_allows_wan_yi_and_population_counts():
    assert not report_amount_unit_violations('市值83.44亿元；净利805万元；十亿人口、百万消费者；每股0.5元')


def test_audit_inspects_actual_visible_figure_text():
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots()
    ax.text(.5,.5,'<0.01')
    fig.suptitle('现金805万元')
    assert figure_number_audit(fig)['number_format_violations']==[]
    label=ax.text(.1,.1,'0.003939')
    assert figure_number_audit(fig)['number_format_violations']==['0.003939']
    label.set_visible(False)
    ax.set_title('净利率1.2345%')
    assert figure_number_audit(fig)['number_format_violations']==['净利率1.2345%']
    plt.close(fig)


def test_health_numbers_preserve_tiny_nonzero():
    from financial_health_check import _chart_amount,_amount_value
    assert _chart_amount(.000039)== '<0.01'
    assert _chart_amount(-.000039)== '>-0.01'
    assert _chart_amount(0)=='0'
    assert _amount_value(3900)=='<0.01'


def test_wan_and_yi_normalize_to_same_amount():
    from report_consistency import extract
    yi=extract('2026归母净利润1.23亿元')
    wan=extract('2026归母净利润12,300万元')
    assert yi.keys()==wan.keys() and yi
    assert next(iter(yi.values()))[0].value==pytest.approx(next(iter(wan.values()))[0].value)


def test_calculator_reader_text_converts_internal_scale_without_mutation():
    import copy
    from calc_penetration_return import compute,render
    cfg={'price':10,'market_cap':1000,'shares':100,'net_profit_C':100,
         'depreciation_D':10,'capex_ratio_G':1,'payout_M':.5,'aa_2y':90,
         'rf':.016,'base_revenue':1000,'net_cash':200}
    result=compute(cfg)
    snapshot=copy.deepcopy(result)
    text=render(result)
    assert '百万' not in text
    assert '1亿元' in text and '1,000万元' in text
    assert result==snapshot


def test_external_chart_prose_is_formatted_before_layout_and_repeated_layout():
    import matplotlib.pyplot as plt
    from chart_numbers import format_chart_text
    from financial_history_charts import layout_native
    assert format_chart_text('2026.10.25；v1.2.345；R*=2.624%；变动-0.003939')=='2026.10.25；v1.2.345；R*=2.62%；变动>-0.01'
    fig,ax=plt.subplots(figsize=(8,4))
    ax.bar([1,2],[1,2])
    fig.suptitle('检验')
    fig.text(.5,.01,'基准2.6241%；来源2026-09-30',ha='center')
    layout_native(fig)
    assert '2.62%' in fig._native_footer.get_text()
    layout_native(fig)
    assert figure_number_audit(fig)['number_format_violations']==[]
    plt.close(fig)
