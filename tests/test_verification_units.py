"""Offline integration for share units, report-year baseline and feed recovery."""
import importlib.util
import json
from pathlib import Path

import pandas as pd


def test_units_year_and_price_recovery(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    data = tmp_path / 'data'
    data.mkdir()
    (tmp_path / 'reports').mkdir()
    (tmp_path / 'input').mkdir()
    pd.DataFrame([
        {'REPORT_DATE':'2025-09-30','PARENT_NETPROFIT':80000000},
        {'REPORT_DATE':'2025-12-31','PARENT_NETPROFIT':100000000},
        {'REPORT_DATE':'2026-09-30','PARENT_NETPROFIT':200000000},
    ]).to_csv(data / '利润表_按报告期.csv', index=False)
    pd.DataFrame([{'REPORT_DATE':'2026-09-30','TOTAL_PARENT_EQUITY':3000000000}]).to_csv(data / '资产负债表_按报告期.csv', index=False)
    pd.DataFrame([{'REPORT_DATE':'2026-09-30','BPS':3}]).to_csv(data / '主要财务指标_按报告期.csv', index=False)
    pd.DataFrame([{'date':'2026-10-23','close':14}]).to_csv(data / '日线股价.csv', index=False)
    pd.DataFrame([{'item':'总股本','value':1000000000}]).to_csv(data / '公司概况.csv', index=False)
    (tmp_path / 'input/估值模型.json').write_text(json.dumps({'scenarios':{'基准':{'2026':4,'2027':5}},'target_price':15}), encoding='utf-8')
    path = Path(__file__).resolve().parents[1] / 'scripts/verification.py'
    spec = importlib.util.spec_from_file_location('verification_offline_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def forbidden_refresh(*args, **kwargs):
        raise AssertionError('offline verification must not fetch data')
    monkeypatch.setattr(module, 'fetch_datasets', forbidden_refresh)
    original_files = {p.relative_to(tmp_path) for p in tmp_path.rglob('*') if p.is_file()}
    module.verify(tmp_path, '603993', 'SH', offline=True)
    snap = json.loads((data / '验证快照.json').read_text(encoding='utf-8'))
    assert snap['shares_yi'] == 10
    assert snap['market_cap_yi'] == 140
    assert snap['pe_ttm'] == 63.6
    assert snap['ttm_ni_yi'] == 2.2
    assert snap['refresh_status'] == 'OFFLINE'
    assert snap['comparison']['status'] == 'NO_FROZEN_BASELINE'
    assert (data / '日线股价.csv').exists()
    module.verify(tmp_path, '603993', 'SH', offline=True)
    final_files = {p.relative_to(tmp_path) for p in tmp_path.rglob('*') if p.is_file()}
    assert final_files == original_files | {Path('data/验证快照.json')}
    output = capsys.readouterr().out
    assert '2026E 完成进度' in output
    assert '2027E 完成进度' not in output
