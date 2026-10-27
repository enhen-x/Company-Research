"""Behavioral latest-period checks: raw evidence -> plotted values -> stale rejection."""
from pathlib import Path
import copy
import hashlib
import json
import sys
import math

import pandas as pd
import pytest
import matplotlib
matplotlib.use('Agg')

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from chart_periods import build_period_pack, refresh_period_pack, CHART_METRICS, chart_values, changes, annual_growth
from chart_period_qc import check_chart_periods
from financial_history_charts import series_data


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


@pytest.fixture
def batch(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    dates = ['2025-06-30','2025-09-30','2025-12-31','2026-03-31','2026-06-30','2026-09-30']
    def csv(name, **cols):
        pd.DataFrame({'REPORT_DATE': dates, **cols}).to_csv(data / name, index=False)
    csv('利润表_按报告期.csv', OPERATE_INCOME=[120e6,200e6,350e6,100e6,150e6,220e6], PARENT_NETPROFIT=[25e6,40e6,60e6,16e6,26e6,38e6], OPERATE_COST=[70e6,110e6,180e6,60e6,90e6,130e6])
    csv('现金流量表_按报告期.csv', NETCASH_OPERATE=[5e6,20e6,90e6,-10e6,-20e6,-10e6], CONSTRUCT_LONG_ASSET=[5e6,8e6,12e6,4e6,9e6,14e6])
    csv('资产负债表_按报告期.csv', TOTAL_ASSETS=[400e6]*6, TOTAL_LIABILITIES=[100e6]*6,
        TOTAL_PARENT_EQUITY=[300e6]*6, SHARE_CAPITAL=[100e6]*6, MONETARYFUNDS=[80e6]*6,
        SHORT_LOAN=[5e6]*6, LONG_LOAN=[10e6]*6, BOND_PAYABLE=[0]*6, NONCURRENT_LIAB_1YEAR=[3e6]*6, LEASE_LIAB=[1e6]*6)
    csv('主要财务指标_按报告期.csv', ROEJQ=[7,11,18,4,8,10.92], BPS=[3]*6)
    pack = refresh_period_pack(tmp_path)
    review = {'checked_through': '2026-09-30', 'period_end': '2026-06-30', 'source': '真实披露位置', 'basis': 'H1', 'reason': '季度未披露共同分部期'}
    ops = {'segment': {'labels': ['2025', '2026H1'], 'period_review': review},
           'peers_period': {'period_review': review}, 'peers': [{'报告期': '2026-06-30'}],
           'dps': {'period_review': {**review, 'period_end': '2025-12-31', 'current_fiscal_year_status': '本财年未披露'}}}
    write(tmp_path / 'input/运营补充数据.json', ops)
    write(tmp_path / 'input/图表豁免.json', {'豁免': []})
    charts = {}
    for chart, metrics in CHART_METRICS.items():
        png = tmp_path / f'reports/图表/{chart}_test.png'
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(b'fixture-artifact')
        charts[chart] = {'file': png.name, 'png_sha256': hashlib.sha256(png.read_bytes()).hexdigest(),
                         'latest_period': pack['latest_period'], 'basis': 'YTD', 'is_forecast': False,
                         'integrated_original_axes': True,
                         'layout': {'axes_count':2*len(metrics), 'latest_tick_visible':True, 'right_gutter_ratio':.08, 'grouped_by_year':True,
                                    'number_format':{'max_decimal_places':2,'small_nonzero':'inequality','trim_trailing_zeros':True},
                                    'number_format_violations':[],
                                    'measured':True,'annotation_collisions':[], 'header_gap_pt':10,'footer_gap_pt':10,'row_gaps_pt':[10]*(len(metrics)-1),
                                    'bar_label_counts':{key:{'annual':sum(v is not None for v in series_data(pack,key)['annual']),
                                                           'quarter':sum(v is not None for seq in series_data(pack,key)['quarters'] for v in seq),
                                                           'text_matches_values':True,'number_format_valid':True} for key in metrics}},
                         'rendered_values': {key: chart_values(pack,key) for key in metrics},
                         'growth_lines': {'policy':'annual_yoy_only','legend_labels':['年度（空心；仅完整年）','Q1','Q2','Q3','Q4','年度同比'],
                             'metrics':{key:[{'label':'年度同比','years':series_data(pack,key)['years'],
                                             'values':series_data(pack,key)['annual_yoy'],
                                             'unit':'pp' if key in ('roe','gross_margin','net_margin','liability_ratio','debt_ratio') else 'percent'}] for key in metrics}},
                         'display_basis':'year_grouped_annual_quarters; flows=single_quarter; stocks=end; ROE=YTD'}
    manifest = {'latest_statement_period': pack['latest_period'], 'source_sha256': pack['source_sha256'], 'charts': charts,
                'ops_sha256': hashlib.sha256((tmp_path / 'input/运营补充数据.json').read_bytes()).hexdigest()}
    write(tmp_path / 'reports/图表期间覆盖.json', manifest)
    return tmp_path, pack, manifest, ops


def test_latest_ytd_comparison_values_and_negative_fcf(batch):
    path, pack, _, _ = batch
    assert pack['latest_period'] == '2026-09-30'
    assert [r['period'] for r in pack['comparisons']] == ['2025-09-30', '2026-09-30']
    assert pack['comparisons'][-1]['values']['fcf'] == -24e6
    assert pack['comparisons'][-1]['values']['roe'] == 10.92
    assert chart_values(pack,'revenue') == [80e6,50e6,70e6]
    assert changes(pack,'revenue')['yoy']['value'] == -12.5
    assert changes(pack,'revenue')['qoq']['value'] == pytest.approx(40)
    assert changes(pack,'ocf')['qoq']['type'] == 'absolute'
    assert changes(pack,'roe')['qoq']['type'] == 'not_applicable'
    assert not check_chart_periods(path)[1]


def test_chart_renders_actual_bars_and_explicit_ytd_labels(batch):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import analyze_charts as charts
    path, pack, _, _ = batch
    charts.configure_latest(path / 'data')
    fig = charts.fig_cashflow({'cashflow': {'labels':['2024','2025'], 'OCF':[.8,.9], 'Capex':[.1,.12], 'FCF':[.7,.78]}})
    assert fig._latest_values['fcf'] == [12e6,-15e6,5e6]
    assert any('单季' in t.get_text() for t in fig.texts)
    assert any('2026' == t.get_text() for a in fig.axes for t in a.get_xticklabels())
    assert len(fig.axes) == 6
    assert len(fig.axes[0].containers) == 5
    assert math.isnan(fig.axes[0].containers[0].datavalues[-1])
    plt.close(fig)


@pytest.mark.parametrize('mutation', ['stale_period', 'full_year', 'forecast', 'wrong_value', 'wrong_snapshot', 'changed_png', 'side_panel','footer_overlap','header_whitespace','missing_label','label_collision','unbounded_decimals','false_zero','actual_text_precision'])
def test_rejects_stale_or_mislabelled_artifact(batch, mutation):
    path, _, manifest, _ = batch
    chart = manifest['charts']['图01']
    if mutation == 'stale_period': chart['latest_period'] = '2025-12-31'
    if mutation == 'full_year': chart['basis'] = 'FY'
    if mutation == 'forecast': chart['is_forecast'] = True
    if mutation == 'wrong_value': chart['rendered_values']['revenue'][-1] *= 4/3
    if mutation == 'wrong_snapshot': manifest['charts']['图15']['rendered_values']['net_cash'][-1] = 123
    if mutation == 'changed_png': (path / 'reports/图表' / chart['file']).write_bytes(b'old chart')
    if mutation == 'side_panel': chart['integrated_original_axes'] = False
    if mutation == 'footer_overlap': chart['layout']['footer_gap_pt']=-3
    if mutation == 'header_whitespace': chart['layout']['header_gap_pt']=90
    if mutation == 'missing_label': chart['layout']['bar_label_counts']['revenue']['quarter']-=1
    if mutation == 'label_collision': chart['layout']['annotation_collisions']=[['1','2']]
    if mutation == 'unbounded_decimals': chart['layout']['number_format']['max_decimal_places']=6
    if mutation == 'false_zero': chart['layout']['bar_label_counts']['revenue']['number_format_valid']=False
    if mutation == 'actual_text_precision': chart['layout']['number_format_violations']=['0.003939']
    write(path / 'reports/图表期间覆盖.json', manifest)
    assert check_chart_periods(path)[1]


def test_rejects_source_refresh_without_rebuilding(batch):
    path, *_ = batch
    file = path / 'data/利润表_按报告期.csv'
    df = pd.read_csv(file)
    df.loc[2, 'OPERATE_INCOME'] = 999e6
    df.to_csv(file, index=False)
    assert any('过期' in f for f in check_chart_periods(path)[1])


@pytest.mark.parametrize('mutation', ['old_segment', 'mixed_peer', 'missing_dividend_status'])
def test_independent_calendars_cannot_be_date_only_claims(batch, mutation):
    path, _, _, ops = batch
    if mutation == 'old_segment': ops['segment']['labels'] = ['2024', '2025']
    if mutation == 'mixed_peer': ops['peers'][0]['报告期'] = '2025-12-31'
    if mutation == 'missing_dividend_status': del ops['dps']['period_review']['current_fiscal_year_status']
    write(path / 'input/运营补充数据.json', ops)
    assert check_chart_periods(path)[1]


def test_missing_debt_is_unknown_without_explicit_policy(batch):
    path, *_ = batch
    file = path / 'data/资产负债表_按报告期.csv'
    df = pd.read_csv(file).drop(columns='BOND_PAYABLE')
    df.to_csv(file, index=False)
    assert build_period_pack(path)['comparisons'][-1]['values']['net_cash'] is None
    write(path / 'input/图表期间配置.json', {'debt_absent_as_zero': ['bond'], 'reason': '公告无债券余额'})
    assert build_period_pack(path)['comparisons'][-1]['values']['net_cash'] == 61e6


def test_new_year_is_detected_without_calendar_hardcoding(batch):
    path, *_ = batch
    for file in (path / 'data').glob('*.csv'):
        df = pd.read_csv(file)
        df['REPORT_DATE'] = pd.to_datetime(df['REPORT_DATE']) + pd.DateOffset(years=1)
        df.to_csv(file, index=False)
    assert build_period_pack(path)['latest_period'] == '2027-09-30'


def test_latest_tick_survives_sparse_labels_and_legend_has_no_right_gutter(batch):
    import matplotlib.pyplot as plt
    import analyze_charts as charts
    path, *_ = batch
    charts.configure_latest(path / 'data')
    original = pd.DataFrame({'REPORT_DATE':pd.to_datetime([f'{year}-12-31' for year in range(2010,2026)]),
                             'OPERATE_INCOME':[300e6]*16, 'PARENT_NETPROFIT':[60e6]*16})
    fig = charts.fig_revenue(original)
    charts._auto_fix_layout(fig)
    fig.canvas.draw()
    assert any('2026' == t.get_text() for t in fig.axes[0].get_xticklabels())
    assert fig._year_grouped
    assert len(fig.axes) == 4
    assert fig.axes[0].get_position().width > .70
    assert not any(ax.get_legend() for ax in fig.axes)
    assert len(fig.legends) == 1
    bounds = fig.legends[0].get_window_extent(fig.canvas.get_renderer())
    assert bounds.x0 >= 0 and bounds.x1 <= fig.bbox.width
    plt.close(fig)


@pytest.mark.parametrize('case', ['dense_years','negative_cash','flat_bps','long_notes'])
def test_layout_adapts_to_data_labels_and_text(batch,case):
    import matplotlib.pyplot as plt
    import analyze_charts
    from financial_history_charts import fig_history,layout_history
    _,source,*_=batch
    pack=copy.deepcopy(source)
    prototype=copy.deepcopy(pack['history'][-1])
    rows=[]
    for year in range(2015,2027):
        for q in range(1,5):
            if year==2026 and q==4:
                continue
            row=copy.deepcopy(prototype)
            row['period']=str((pd.Timestamp(year,q*3,1)+pd.offsets.MonthEnd()).date())
            for key,value in row['values'].items():
                if value is not None:
                    factor=1 if case=='flat_bps' else (1+.015*(year-2015)+q*.009)
                    if case=='negative_cash' and key in ('ocf','fcf'):
                        factor*=(-1 if q%2==0 else 1)*(.03 if q==1 else 3)
                    row['values'][key]=value*factor
            row['cumulative_values']=dict(row['values'])
            rows.append(row)
    pack['history']=rows
    chart={'negative_cash':'图05','flat_bps':'图02','long_notes':'图04'}.get(case,'图01')
    fig=fig_history(pack,chart)
    if case=='long_notes':
        fig._history_footer_text+=' 额外口径说明、长期项目名称、不同单位及缺失字段需要完整呈现。'*5
        fig.set_size_inches(9,fig.get_figheight())
    layout_history(fig)
    audit=fig._layout_audit
    assert audit['annotation_collisions']==[]
    gaps=[audit['header_gap_pt'],audit['footer_gap_pt'],*audit['row_gaps_pt']]
    assert all(3<=v<=26 for v in gaps),gaps
    for ax in fig.axes:
        if not hasattr(ax,'_metric_key'):
            continue
        data=series_data(pack,ax._metric_key)
        counts=audit['bar_label_counts'][ax._metric_key]
        assert counts['annual']==sum(v is not None for v in data['annual'])
        assert counts['quarter']==sum(v is not None for seq in data['quarters'] for v in seq)
        labels=[t for t in ax.texts if getattr(t,'_bar_value_label',False)]
        assert all(t.get_fontsize()==(8.5 if t._annual_label else 6.2) for t in labels)
        box=ax.get_window_extent(fig.canvas.get_renderer())
        assert all(box.y0<=t.get_window_extent(fig.canvas.get_renderer()).y0 and t.get_window_extent(fig.canvas.get_renderer()).y1<=box.y1 for t in labels)
    plt.close(fig)


@pytest.mark.parametrize('n',[1,4,5])
def test_native_multiaxis_legend_and_footer_are_outside_plot(tmp_path,n):
    import matplotlib.pyplot as plt
    import analyze_charts as charts
    fig=charts.fig_segment({'segment':{'labels':[str(2022+i) for i in range(n)],
        'series':[{'name':'主要产品','values':[10+i for i in range(n)]},{'name':'补充产品','values':[1+i for i in range(n)]}],
        '注':'完整年度与本期半年实际分别披露，仅比较构成。'*4}})
    charts._auto_fix_layout(fig)
    fig.canvas.draw(); renderer=fig.canvas.get_renderer()
    legend=fig.legends[0].get_window_extent(renderer)
    assert all(legend.y0>ax.get_window_extent(renderer).y1 for ax in fig.axes if ax.get_visible())
    footer=fig._native_footer.get_window_extent(renderer)
    assert all(footer.y1<ax.get_window_extent(renderer).y0 for ax in fig.axes if ax.get_visible())
    assert all(3<=v<=26 for v in [fig._layout_audit['header_gap_pt'],fig._layout_audit['footer_gap_pt'],*fig._layout_audit['row_gaps_pt']])
    height=fig.get_figheight()*150
    charts.save(fig,tmp_path,'native.png')
    from PIL import Image
    with Image.open(tmp_path/'native.png') as im:
        assert im.height>=height*.9


def test_flowing_health_panel_wraps_and_keeps_subtitle_and_footer(tmp_path):
    import matplotlib.pyplot as plt
    from financial_history_charts import layout_text_panel,layout_native
    fig,ax=plt.subplots(figsize=(7,6))
    fig.suptitle('财报检查标题')
    fig._layout_subtitle=fig.text(.03,.93,'较长的副标题需要根据画布宽度换行、避免与图例重叠。'*3)
    fig.text(.03,.02,'数据来源及口径说明。'*5)
    ax.axis('off')
    for index in range(7):
        ax.text(.02,.9-index*.1,f'{index+1}. 后续观察与风险核对需要完整说明；文字随不同公司数据变化。'*2,va='top',fontsize=10)
    layout_text_panel(fig,ax); layout_native(fig)
    audit=fig._layout_audit
    assert audit['text_collisions']==[]
    assert 3<=audit['header_gap_pt']<=26
    assert 3<=audit['footer_gap_pt']<=26
    fig.canvas.draw(); renderer=fig.canvas.get_renderer()
    assert fig._layout_subtitle.get_window_extent(renderer).y0>ax.get_tightbbox(renderer).y1
    plt.close(fig)


def test_metric_window_trims_empty_years_without_filling_missing_debt(batch):
    _,pack,*_=batch
    pack=copy.deepcopy(pack)
    older=copy.deepcopy(pack['history'][0]); older['period']='2014-12-31'
    older['values']['net_cash']=None; older['cumulative_values']['net_cash']=None
    pack['history'].insert(0,older)
    assert series_data(pack,'net_cash')['years'][0]==2025
    assert series_data(pack,'liability_ratio')['years'][0]==2014


def test_q1_qoq_uses_prior_year_q4(batch):
    path,*_=batch
    for file in (path/'data').glob('*.csv'):
        df=pd.read_csv(file)
        df=df[pd.to_datetime(df['REPORT_DATE'])<=pd.Timestamp('2026-03-31')]
        df.to_csv(file,index=False)
    # Quarterly comparisons remain available to evidence tables, not chart lines.
    assert changes(build_period_pack(path),'revenue')['qoq']['value']==pytest.approx((100/150-1)*100)


def test_annual_yoy_uses_full_year_and_keeps_missing_years_empty(batch):
    _,source,*_=batch
    pack=copy.deepcopy(source)
    previous=copy.deepcopy(next(r for r in pack['history'] if r['period']=='2025-12-31'))
    previous['period']='2024-12-31'
    previous['cumulative_values'].update(revenue=280e6,roe=15,fcf=-10e6)
    older=copy.deepcopy(previous); older['period']='2022-12-31'
    pack['history']=[older,previous,*pack['history']]
    data=series_data(pack,'revenue')
    assert data['years']==[2022,2023,2024,2025,2026]
    assert data['annual_yoy'][:-2]==[None,None,None]
    assert data['annual_yoy'][-2]==pytest.approx(25)
    assert data['annual_yoy'][-1] is None
    assert annual_growth(pack,'roe',[2025,2026])==[3,None]
    assert annual_growth(pack,'fcf',[2025,2026])==[None,None]
    assert 'yoy' not in data and 'qoq' not in data


@pytest.mark.parametrize('chart_id',list(CHART_METRICS))
def test_static_charts_have_only_annual_yoy_growth_lines(batch,chart_id):
    import matplotlib.pyplot as plt
    from financial_history_charts import fig_history,growth_line_evidence,growth_line_failures
    _,pack,*_=batch
    ops={'forecast':{'labels_fcast':['2026E','2027E','2028E'],'基准':[1,2,3]}}
    fig=fig_history(pack,chart_id,ops)
    evidence=growth_line_evidence(fig)
    assert not growth_line_failures(pack,chart_id,evidence,ops)
    for lines in evidence['metrics'].values():
        assert len(lines)==1 and lines[0]['label']=='年度同比'
        assert all(v is None for y,v in zip(lines[0]['years'],lines[0]['values']) if y>=2026)
    text=' '.join(t.get_text() for ax in fig.axes for t in [ax.title,*ax.texts])
    assert '环比' not in text and 'Q3同比' not in text
    plt.close(fig)


@pytest.mark.parametrize('mutation',['quarter_yoy','quarter_qoq','extra_line','invented_fy','wrong_annual_yoy'])
def test_growth_qc_rejects_quarter_lines_and_wrong_annual_values(batch,mutation):
    path,_,manifest,_=batch
    evidence=manifest['charts']['图01']['growth_lines']
    line=evidence['metrics']['revenue'][0]
    if mutation=='quarter_yoy': line['label']='Q3同比'
    if mutation=='quarter_qoq': evidence['legend_labels'].append('Q3环比')
    if mutation=='extra_line': evidence['metrics']['revenue'].append(copy.deepcopy(line))
    if mutation=='invented_fy': line['values'][-1]=12
    if mutation=='wrong_annual_yoy': line['values'][0]=25
    write(path/'reports/图表期间覆盖.json',manifest)
    assert any('同比' in m or '增长线' in m for m in check_chart_periods(path)[1])


def test_interactive_financial_panels_have_one_annual_growth_trace(batch,tmp_path,monkeypatch):
    from financial_history_charts import write_interactive
    import plotly.graph_objects as go
    _,pack,*_=batch
    captured=[]
    def capture(fig,**kwargs):
        captured.append(fig.to_plotly_json())
        return '<div>captured</div>'
    monkeypatch.setattr(go.Figure,'to_html',capture)
    out=tmp_path/'interactive.html'
    write_interactive(pack,{},out,'test')
    assert captured
    for panel in captured:
        lines=[t for t in panel['data'] if t['type']=='scatter']
        assert len(lines)==1 and lines[0]['name']=='年度同比'
        assert lines[0]['y'][-1] is None
        assert not lines[0]['connectgaps']
        assert panel['layout']['yaxis2']['tickformat']==',.2~f'
    assert '绿虚线' not in out.read_text(encoding='utf-8')


@pytest.mark.parametrize('values',[[.0249],[.00042],[-.004,.003],[1.2,15.8],[-150,500]])
def test_annual_growth_axis_ticks_are_bounded_and_distinct(values):
    import matplotlib.pyplot as plt
    from financial_history_charts import format_growth_axis,valid_number_label
    fig,ax=plt.subplots()
    ax.plot(list(range(len(values))),values)
    ax.axhline(0)
    format_growth_axis(ax)
    fig.canvas.draw()
    labels=[t.get_text() for t in ax.get_yticklabels()]
    assert len(labels)==len(set(labels))
    assert all(valid_number_label(t) for t in labels)
    lower,upper=ax.get_ylim()
    assert lower<=min(values) and upper>=max(values)
    plt.close(fig)


@pytest.mark.parametrize('width,scale',[(8,1),(12,1000),(16,.001)])
def test_native_scatter_offset_names_stay_inside_final_axes(width,scale):
    import matplotlib.pyplot as plt
    from matplotlib.text import Text
    import analyze_charts as charts
    fig,axes=plt.subplots(1,2,figsize=(width,4))
    fig.suptitle('同行比较')
    for ax in axes:
        ax.scatter([0,100*scale],[0,100])
        ax.annotate('最右侧完整公司名称',(100*scale,100),textcoords='offset points',xytext=(8,6),fontsize=9)
        ax.set_xlabel('营收增长率')
    charts._auto_fix_layout(fig)
    renderer=fig.canvas.get_renderer()
    for ax in axes:
        bounds=ax.get_window_extent(renderer)
        for label in ax.texts:
            bb=Text.get_window_extent(label,renderer)
            assert bounds.x0<=bb.x0 and bb.x1<=bounds.x1
            assert bounds.y0<=bb.y0 and bb.y1<=bounds.y1
    assert fig._layout_audit['text_out_of_bounds']==[]
    plt.close(fig)


@pytest.mark.parametrize('value,expected',[(0,'0'),(-0.0,'0'),(.003939,'<0.01'),(-.003939,'>-0.01'),
    (.009999,'<0.01'),(-.009999,'>-0.01'),(.01,'0.01'),(-.01,'-0.01'),(.5308,'0.53'),
    (-.8209,'-0.82'),(1.2,'1.2'),(10.12,'10.12'),(1234.567,'1,234.57')])
def test_chart_number_precision_is_bounded_and_preserves_nonzero(value,expected):
    from financial_history_charts import format_number,valid_number_label
    assert format_number(value)==expected
    assert valid_number_label(expected)
    assert not valid_number_label('0.003939')
    assert not valid_number_label('3.9e-03')
