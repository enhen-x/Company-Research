"""Market PB is an observation, not the rolling band's central statistic."""
from pathlib import Path
import importlib.util,json
SPEC=importlib.util.spec_from_file_location('valuation_band_qc',Path(__file__).resolve().parents[1]/'scripts/chart_qc.py')
MOD=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MOD)

def run(tmp_path,data):
    (tmp_path/'input').mkdir()
    (tmp_path/'input/运营补充数据.json').write_text(json.dumps(data),encoding='utf-8')
    return MOD.check_valuation_band_contract(tmp_path)

def test_actual_pb_may_break_quantile_band(tmp_path):
    _,fail=run(tmp_path,{'pb_band':{'labels':['a','b','c'],'pb_low':[1,2,3],'pb_high':[3,4,5],'pb':[.5,10,2]}})
    assert not fail

def test_pb_inverted_band_still_fails(tmp_path):
    _,fail=run(tmp_path,{'pb_band':{'labels':['a','b','c'],'pb_low':[4,2,3],'pb_high':[3,4,5],'pb':[.5,10,2]}})
    assert any('low <= high' in x for x in fail)

def test_pe_central_statistic_must_be_within_band(tmp_path):
    _,fail=run(tmp_path,{'pe_band':{'labels':['a','b','c'],'pe_low':[1,2,3],'pe_high':[3,4,5],'pe_mean':[2,10,4]}})
    assert any('low <= mean <= high' in x for x in fail)

def test_constant_pb_band_still_fails(tmp_path):
    _,fail=run(tmp_path,{'pb_band':{'labels':['a','b','c'],'pb_low':[1,1,1],'pb_high':[3,3,3],'pb':[.5,10,2]}})
    assert any('恒定' in x for x in fail)
