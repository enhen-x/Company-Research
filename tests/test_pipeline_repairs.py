"""Isolated synthetic regressions for execution omissions, stalls and financial semantics."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]/"scripts"
sys.path.insert(0,str(SCRIPTS))
from bounded_fetch import FetchError, fetch_job, job
from run_support import run_process
from build_penetration_input import depreciation_amount, financial_snapshot, val_mm
from calc_penetration_return import compute, render


@pytest.fixture
def sources(tmp_path, monkeypatch):
    module = tmp_path/"isolated_fetch_fixture.py"
    module.write_text('''
import time
from pathlib import Path

def failure(marker):
    p=Path(marker)
    p.write_text(p.read_text()+"x" if p.exists() else "x")
    raise RuntimeError("isolated synthetic failure")

def slow(marker):
    Path(marker).write_text("started")
    time.sleep(20)

def success():
    import pandas as pd
    return pd.DataFrame({"synthetic_value":[123]})
''',encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH",str(tmp_path)+os.pathsep+os.environ.get("PYTHONPATH",""))
    return lambda function,**kwargs: job("isolated_fetch_fixture",function,**kwargs)


def test_hard_timeout_terminates_actual_child(sources,tmp_path):
    start=time.monotonic()
    with pytest.raises(FetchError) as error:
        fetch_job(sources("slow",marker=str(tmp_path/"marker")),cache_dir=tmp_path/"cache",timeout=2,retries=1)
    assert error.value.attempts[0]["status"]=="TIMEOUT"
    assert (tmp_path/"marker").read_text()=="started"
    assert time.monotonic()-start<10


def test_negative_cache_retains_failure_and_honors_force_expiry(sources,tmp_path):
    marker=tmp_path/"counter"
    spec=sources("failure",marker=str(marker))
    options=dict(cache_dir=tmp_path/"cache",timeout=15,retries=2,delay=0,failure_ttl=900)
    with pytest.raises(FetchError) as first:
        fetch_job(spec,**options)
    assert len(first.value.attempts)==2 and marker.read_text()=="xx"
    with pytest.raises(FetchError) as cached:
        fetch_job(spec,**options)
    assert cached.value.attempts[0]["status"]=="FAILURE_CACHED"
    assert marker.read_text()=="xx"
    with pytest.raises(FetchError):
        fetch_job(spec,force=True,**options)
    assert marker.read_text()=="xxxx"
    cache=next((tmp_path/"cache").glob("*.failure.json"))
    data=json.loads(cache.read_text())
    data["failed_at"]=time.time()-901
    cache.write_text(json.dumps(data),encoding="utf-8")
    with pytest.raises(FetchError):
        fetch_job(spec,**options)
    assert marker.read_text()=="xxxxxx"


def test_fallback_records_all_candidates_and_does_not_relabel_old_files(sources,tmp_path,monkeypatch):
    import fetch_with_fallback as adapter
    marker=tmp_path/"calls"
    bad=sources("failure",marker=str(marker))
    good=sources("success")
    monkeypatch.setattr(adapter,"dataset_specs",lambda *args:[("synthetic","test.csv",[bad,good])])
    result=adapter.fetch_datasets("000001","SZ",tmp_path,timeout=15,retries=1)
    item=result["datasets"][0]
    assert item["status"]=="success" and "error" not in item
    assert [a["status"] for a in item["attempts"]]==["FAIL","PASS"]
    old=(tmp_path/"test.csv").read_bytes()
    monkeypatch.setattr(adapter,"dataset_specs",lambda *args:[("synthetic","test.csv",[bad])])
    failed=adapter.fetch_datasets("000001","SZ",tmp_path,timeout=15,retries=1)
    assert failed["datasets"][0]["old_file_preserved"] is True
    assert failed["datasets"][0]["status"]=="failed"
    assert (tmp_path/"test.csv").read_bytes()==old
    assert len(failed["runs"])==2
    assert failed["datasets"][0]["attempts"][0]["status"]=="FAILURE_CACHED"


def test_batch_budget_terminates_child_and_skips_remaining_sources(sources,tmp_path,monkeypatch):
    import fetch_with_fallback as adapter
    marker=tmp_path/"budget_marker"
    monkeypatch.setattr(adapter,"dataset_specs",lambda *args:[
        ("first","first.csv",[sources("slow",marker=str(marker)),sources("success")]),
        ("second","second.csv",[sources("success")])])
    started=time.monotonic()
    result=adapter.fetch_datasets("000001","SZ",tmp_path,timeout=15,retries=3,total_budget=2,failure_ttl=0)
    assert time.monotonic()-started<10
    assert marker.read_text()=="started"
    assert result["status"]=="WARN"
    assert all(item["budget_exhausted"] for item in result["datasets"])
    assert result["datasets"][0]["attempts"][0]["status"]=="TIMEOUT"
    assert result["datasets"][1]["attempts"]==[]
    assert not (tmp_path/"first.csv").exists() and not (tmp_path/"second.csv").exists()


def test_source_cache_key_changes_with_job(sources,tmp_path):
    from bounded_fetch import cache_key
    assert cache_key(sources("failure",marker="a"))!=cache_key(sources("failure",marker="b"))


def test_top10_requires_explicit_and_matching_report_period(monkeypatch):
    from fetch_sources import dataset_specs,top10_for_period
    from types import SimpleNamespace
    assert dataset_specs("600039","SH",{"top10"})[0][2]==[]
    kwargs=dataset_specs("600039","SH",{"top10"},"2026-06-30")[0][2][0]["kwargs"]
    assert kwargs["report_date"]=="2026-06-30"
    def old_data(**args):
        assert args["date"]=="20260630"
        return pd.DataFrame({"REPORT_DATE":["2021-06-30"]})
    monkeypatch.setitem(sys.modules,"akshare",SimpleNamespace(stock_gdfx_top_10_em=old_data))
    with pytest.raises(ValueError,match="报告期"):
        top10_for_period(**kwargs)


def _batch(tmp_path,preflight="pass",builder="pass"):
    project=tmp_path/"synthetic_batch"
    for folder in ("input","reports","scripts","data"):
        (project/folder).mkdir(parents=True)
    (project/"input/图表豁免.json").write_text('{"豁免":[]}',encoding="utf-8")
    (project/"input/sotp_触发.json").write_text('{"enabled":false}',encoding="utf-8")
    (project/"input/运营补充数据.json").write_text('{}',encoding="utf-8")
    (project/"reports/测试_000001_分析报告.md").write_text('# isolated synthetic report',encoding="utf-8")
    for filename in ("chart_qc.py","chart_period_qc.py","format_qc.py","report_template_qc.py","md_to_html.py","financial_health_qc.py"):
        (project/"scripts"/filename).write_text("pass\n",encoding="utf-8")
    (project/"scripts/chart_period_qc.py").write_text(preflight+"\n",encoding="utf-8")
    (project/"scripts/analyze_charts.py").write_text(builder+"\n",encoding="utf-8")
    return project


def _gate(project,*extra):
    return subprocess.run([sys.executable,str(SCRIPTS/"gate_all.py"),"--dir",str(project),*extra],capture_output=True,text=True,encoding="utf-8")


def test_preflight_failure_blocks_build_and_invalidates_previous_success(tmp_path):
    project=_batch(tmp_path,preflight="raise SystemExit(2)",builder="from pathlib import Path; Path('built').write_text('yes')")
    ledger=project/"reports/流水线执行状态.json"
    ledger.write_text('{"status":"PASS","build_completed":true}',encoding="utf-8")
    result=_gate(project)
    state=json.loads(ledger.read_text(encoding="utf-8"))
    assert result.returncode==1
    assert not (project/"built").exists()
    assert state["build_completed"] is False and state["status"]=="FAIL"
    assert state["stages"][0]["exit_code"]==2
    assert next(s for s in state["stages"] if s["name"]=="固定图表构建")["status"]=="BLOCKED"


def test_gate_records_stage_time_and_check_only_does_not_claim_build(tmp_path):
    project=_batch(tmp_path)
    result=_gate(project,"--check-only")
    state=json.loads((project/"reports/流水线执行状态.json").read_text(encoding="utf-8"))
    assert result.returncode==0,result.stdout+result.stderr
    assert state["technical_pass"] is True and state["build_completed"] is False
    assert all("elapsed_seconds" in s for s in state["stages"])
    assert state["research_quality"]=="NOT_ASSESSED"


def test_gate_detects_input_mutation_during_build(tmp_path):
    project=_batch(tmp_path,builder="from pathlib import Path; Path('input/运营补充数据.json').write_text('{\"changed\":true}')")
    result=_gate(project)
    state=json.loads((project/"reports/流水线执行状态.json").read_text(encoding="utf-8"))
    assert result.returncode==1 and state["build_completed"] is False
    assert "发生变化" in state["error"]


def test_gate_timeout_is_failure_not_completion(tmp_path):
    project=_batch(tmp_path,builder="import time; time.sleep(20)")
    result=_gate(project,"--stage-timeout","1","--heartbeat",".2")
    state=json.loads((project/"reports/流水线执行状态.json").read_text(encoding="utf-8"))
    build=next(s for s in state["stages"] if s["name"]=="固定图表构建")
    assert result.returncode==1 and build["status"]=="TIMEOUT"
    assert "仍在运行" in result.stdout
    assert state["build_completed"] is False


def _config(**kwargs):
    return dict(price=10,market_cap=1000,shares=100,net_profit_C=100,depreciation_D=20,
                capex_ratio_G=1,payout_M=.5,aa_2y=90,rf=.016,base_revenue=900,
                cash_balance=200,interest_bearing_debt=300,ebitda=100,**kwargs)


def test_cash_and_net_debt_are_distinct_and_conflicts_fail():
    result=compute(_config())
    assert result["EV"]==1100 and result["net_debt"]==100
    assert result["net_cash_actual"]==-100 and result["net_debt_ebitda"]==1
    with pytest.raises(ValueError,match="冲突"):
        compute(_config(net_cash=-100))
    with pytest.raises(ValueError,match="net_debt"):
        compute(_config(net_debt=200))


def test_working_capital_and_unverified_low_are_excluded_from_price_anchors():
    result=compute(_config(net_current_assets=800,working_capital=800,book_equity=500,low_10y_close=.01))
    assert result["anchors"]==[("每股净资产",5)]
    assert result["base_price"]==5
    assert any("十年低价" in w for w in result["warnings"])


def test_verified_price_anchors_and_grid_basis_are_explicit():
    result=compute(_config(book_equity=500,cash_protection=100,cash_protection_verified=True,
                           cash_protection_source="isolated verified fixture",low_10y_close=3,
                           low_10y_close_verified=True,low_10y_close_source="isolated adjusted-price fixture"))
    assert len(result["anchors"])==3
    assert all(row["oe_yield"]==row["GG"] and row["basis"]=="OE*M/market_cap" for row in result["g_grid"])


def test_zero_or_negative_aa_does_not_produce_invalid_cash_pe():
    cfg=_config()
    cfg["aa_2y"]=0
    result=compute(cfg)
    assert result["cash_adj_pe"] is None
    assert "不适用" in render(result)
    cfg["aa_2y"]=-10
    assert compute(cfg)["cash_adj_pe"] is None


def test_legacy_cash_compatibility_is_flagged_and_missing_debt_is_unknown():
    cfg=_config()
    cfg["net_cash"]=cfg.pop("cash_balance")
    result=compute(cfg)
    assert result["EV"]==1100 and any("旧字段" in w for w in result["warnings"])
    cfg.pop("interest_bearing_debt")
    result=compute(cfg)
    assert result["EV"] is None and result["net_debt"] is None
    render(result)


def test_ebitda_formula_and_ordinary_equity_do_not_use_wrong_subtotals():
    balance=pd.Series({"MONETARYFUNDS":200e6,"SHORT_LOAN":100e6,"LONG_LOAN":200e6,"BOND_PAYABLE":0,
                       "SHORT_BOND_PAYABLE":0,"TOTAL_CURRENT_ASSETS":900e6,"TOTAL_CURRENT_LIAB":700e6,
                       "TOTAL_PARENT_EQUITY":600e6,"OTHER_EQUITY_TOOL":100e6})
    income=pd.Series({"TOTAL_PROFIT":80e6,"FE_INTEREST_EXPENSE":10e6,"OPERATE_PROFIT":400e6,"INTEREST_EXPENSE":30e6})
    result=financial_snapshot(balance,income,20)
    assert result["ebitda"]==110
    assert result["cash_balance"]==200 and result["net_debt"]==100
    assert result["book_equity"]==500 and result["working_capital"]==200
    assert result["cash_protection"] is None
    incomplete=financial_snapshot(balance.drop("SHORT_LOAN"),income.drop("FE_INTEREST_EXPENSE"),20)
    assert incomplete["ebitda"] is None and incomplete["net_debt"] is None


def test_depreciation_aggregate_wins_and_oilgas_component_is_not_added_twice():
    row=pd.Series({"DEPR_AMORT":80e6,"FA_IR_DEPR":50e6,"OILGAS_BIO_DEPR":40e6,"IA_AMORTIZE":10e6,"LPE_AMORTIZE":5e6})
    assert depreciation_amount(row)==80
    assert depreciation_amount(row.drop("DEPR_AMORT"))==65
    assert depreciation_amount(row.drop(["DEPR_AMORT","IA_AMORTIZE"])) is None
    with pytest.raises(ValueError,match="禁止填0"):
        val_mm(pd.DataFrame({"PARENT_NETPROFIT":[None]}),"PARENT_NETPROFIT")


def test_generator_protects_existing_manual_input_before_any_read(tmp_path):
    (tmp_path/"穿透回报率_输入.json").write_text('{"analyst":"confirmed"}',encoding="utf-8")
    command=[sys.executable,str(SCRIPTS/"build_penetration_input.py"),"--data",str(tmp_path/"missing"),
             "--out",str(tmp_path),"--company","synthetic","--code","000001"]
    result=subprocess.run(command,capture_output=True,text=True,encoding="utf-8")
    assert result.returncode!=0 and "保留人工判断" in result.stderr
    assert json.loads((tmp_path/"穿透回报率_输入.json").read_text())=={"analyst":"confirmed"}


def test_xtick_collision_check_still_runs_on_final_figure():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from chart_qc import _check_figure_xticks
    fig,ax=plt.subplots(figsize=(2,2))
    ax.set_xticks([0,.01],["very long synthetic label","second very long synthetic label"])
    ax.set_xlim(0,1)
    fig.canvas.draw()
    warnings,failures=_check_figure_xticks(fig,"synthetic")
    assert any("重合" in failure for failure in failures)
    plt.close(fig)


def test_quarterly_eps_requires_immediate_predecessor(monkeypatch):
    from types import SimpleNamespace
    import requests
    from fetch_sources import emweb_indicators
    rows=[{"REPORT_DATE":date,"EPSJB":eps} for date,eps in
          [("2024-12-31",4),("2025-03-31",1),("2025-09-30",3),("2025-12-31",5),("2026-06-30",2)]]
    monkeypatch.setattr(requests,"get",lambda *a,**k: SimpleNamespace(
        raise_for_status=lambda:None,json=lambda:{"result":{"data":rows}}))
    result=emweb_indicators("000001","SZ",quarterly=True)
    values=dict(zip(result.REPORT_DATE.dt.strftime("%Y-%m-%d"),result.EPSJB))
    assert values=={"2025-03-31":1,"2025-12-31":2}


def test_generator_complete_isolated_cli_uses_correct_financial_bases(tmp_path):
    data=tmp_path/"data"
    data.mkdir()
    dates=[f"{year}-12-31" for year in range(2021,2026)]
    frames={
        "利润表_按报告期.csv":{"OPERATE_INCOME":[900e6]*5,"PARENT_NETPROFIT":[100e6]*5,
            "BASIC_EPS":[1]*5,"TOTAL_PROFIT":[80e6]*5,"FE_INTEREST_EXPENSE":[10e6]*5},
        "现金流量表_按报告期.csv":{"NETCASH_OPERATE":[120e6]*5,"CONSTRUCT_LONG_ASSET":[20e6]*5,
            "DEPR_AMORT":[20e6]*5},
        "资产负债表_按报告期.csv":{"SHARE_CAPITAL":[100e6]*5,"MONETARYFUNDS":[200e6]*5,
            "SHORT_LOAN":[100e6]*5,"LONG_LOAN":[200e6]*5,"BOND_PAYABLE":[0]*5,"SHORT_BOND_PAYABLE":[0]*5,
            "TOTAL_CURRENT_ASSETS":[900e6]*5,"TOTAL_CURRENT_LIAB":[700e6]*5,
            "TOTAL_PARENT_EQUITY":[600e6]*5,"OTHER_EQUITY_TOOL":[100e6]*5}}
    for filename,columns in frames.items():
        pd.DataFrame({"REPORT_DATE":dates,**columns}).to_csv(data/filename,index=False,encoding="utf-8-sig")
    pd.DataFrame({"报告期":dates,"现金分红-现金分红比例":[5]*5}).to_csv(data/"分红送配记录.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame({"日期":["2026-10-27","2026-10-26"],"收盘":[10,9]}).to_csv(data/"日线股价.csv",index=False,encoding="utf-8-sig")
    result=subprocess.run([sys.executable,str(SCRIPTS/"build_penetration_input.py"),"--data",str(data),
        "--out",str(tmp_path/"input"),"--company","isolated synthetic","--code","000001"],capture_output=True,text=True,encoding="utf-8")
    assert result.returncode==0,result.stderr
    cfg=json.loads((tmp_path/"input/穿透回报率_输入.json").read_text(encoding="utf-8"))
    assert cfg["ebitda"]==110 and cfg["book_equity"]==500 and cfg["price"]==10
    assert cfg["cash_balance"]==200 and cfg["net_debt"]==100 and cfg["working_capital"]==200
    assert cfg["low_10y_close"] is None and cfg["cash_protection"] is None
    assert compute(cfg)["GG"]==.05


@pytest.mark.parametrize("period_status,exit_code",[("PASS",0),("FAIL",1),("TIMEOUT",1)])
def test_main_pipeline_calls_shared_bounded_adapter(tmp_path,monkeypatch,period_status,exit_code):
    import research_pipeline as pipeline
    project=tmp_path/"isolated_batch"
    (project/"data").mkdir(parents=True)
    calls=[]
    monkeypatch.setattr(sys,"argv",["research_pipeline.py","--company","isolated synthetic","--code","000001",
        "--root",str(tmp_path),"--timeout","2","--retries","1","--failure-ttl","3","--force-refresh"])
    monkeypatch.setattr(pipeline,"scaffold",lambda *a:project)
    monkeypatch.setattr(pipeline,"fetch_datasets",lambda *a,**k:calls.append((a,k)) or {"status":"PASS"})
    monkeypatch.setattr(pipeline,"audit_data",lambda *a:([],"pass"))
    monkeypatch.setattr(pipeline,"write_audit_report",lambda *a:project/"audit.html")
    monkeypatch.setattr(pipeline,"run_financial_health",lambda *a:(0,{}))
    period_calls=[]
    monkeypatch.setattr(pipeline,"run_process",lambda *a,**k:period_calls.append((a,k)) or {"status":period_status})
    assert pipeline.main()==exit_code
    assert len(calls)==1
    assert calls[0][1]==dict(timeout=2,retries=1,failure_ttl=3,force=True,total_budget=180,success_ttl=3600)
    assert len(period_calls)==1 and period_calls[0][1]["label"]=="B3.6期间证据"
    assert "chart_periods.py" in period_calls[0][0][0][2]
    assert period_calls[0][0][0][-2:]==["--dir",str(project)]


def test_combined_qc_does_not_invoke_separate_full_xtick_rebuild():
    import ast
    module=ast.parse((SCRIPTS/"chart_qc.py").read_text(encoding="utf-8-sig"))
    report=next(node for node in module.body if isinstance(node,ast.FunctionDef) and node.name=="check_report")
    render=next(node for node in module.body if isinstance(node,ast.FunctionDef) and node.name=="_check_render_quality")
    names=lambda node:[call.func.id for call in ast.walk(node) if isinstance(call,ast.Call) and isinstance(call.func,ast.Name)]
    assert "_check_all_xticks" not in names(report)
    assert "_check_render_quality" in names(report)
    assert "_check_figure_xticks" in names(render)


def test_negative_selfcheck_requires_the_expected_finding_not_a_crash():
    from template_regression import injected_layout_bug_detected
    assert not injected_layout_bug_detected(1,"Traceback (most recent call last):\nModuleNotFoundError")
    assert not injected_layout_bug_detected(1,"[FAIL] unrelated finding")
    assert not injected_layout_bug_detected(0,"[FAIL] G8-RENDER: 图04 数据标注互相重叠")
    assert injected_layout_bug_detected(1,"[FAIL] G8-RENDER: 图04 数据标注互相重叠")
