"""Shared source candidates for both research_pipeline and fetch_with_fallback."""
from __future__ import annotations

import re
import pandas as pd
from bounded_fetch import job


def dataset_specs(code, market, items, report_date=None):
    em = market.upper()+code
    specs = []
    def add(name, filename, candidates):
        specs.append((name, filename, candidates))
    if market.upper() == "HK":
        if "sheets" in items:
            for title in ("资产负债表", "利润表", "现金流量表"):
                add(title, title+"_按报告期.csv", [job("fetch_sources", "hk_statement", code=code, title=title)])
        if "indicators" in items:
            add("港股主要财务指标", "主要财务指标_按报告期.csv", [job("akshare", "stock_financial_hk_analysis_indicator_em", symbol=code, indicator="报告期")])
        if "daily" in items:
            for adjust, suffix in (("", ""), ("qfq", "_前复权")):
                add("港股日线"+suffix, "日线股价"+suffix+".csv", [job("akshare", "stock_hk_hist", symbol=code, period="daily", start_date="20000101", adjust=adjust)])
        if "dividends" in items:
            add("港股分红", "分红送配记录.csv", [job("akshare", "stock_hk_dividend_payout_em", symbol=code)])
        if "profile" in items:
            add("公司概况/现价/股本", "公司概况.csv", [job("fetch_sources", "tencent_info", code=code, mkt=market)])
        return specs
    if "sheets" in items:
        for title, api in (("资产负债表", "balance"), ("利润表", "profit"), ("现金流量表", "cash_flow")):
            add(title, title+"_按报告期.csv", [job("akshare", f"stock_{api}_sheet_by_report_em", symbol=em)])
    if "indicators" in items:
        for period, basis in (("报告期", "按报告期"), ("单季度", "按单季度")):
            add("主要财务指标（"+basis+"）", "主要财务指标_"+basis+".csv", [
                job("akshare", "stock_financial_analysis_indicator_em", symbol=f"{code}.{market.upper()}", indicator=basis),
                job("fetch_sources", "emweb_indicators", code=code, market=market, quarterly=period=="单季度")])
    if "daily" in items:
        for adjust, suffix in (("", ""), ("qfq", "_前复权")):
            add("日线行情"+suffix, "日线股价"+suffix+".csv", [
                job("akshare", "stock_zh_a_hist", symbol=code, period="daily", start_date="20000101", adjust=adjust),
                job("akshare", "stock_zh_a_hist_tx", symbol=market.lower()+code, start_date="20000101", adjust=adjust)])
    if "dividends" in items:
        add("分红送配记录", "分红送配记录.csv", [job("akshare", "stock_fhps_detail_em", symbol=code)])
    if "profile" in items:
        add("公司概况/现价/股本", "公司概况.csv", [job("akshare", "stock_individual_info_em", symbol=code),
            job("fetch_sources", "tencent_info", code=code, mkt=market)])
    if "top10" in items:
        # No API default dates: explicit requested disclosure period is mandatory.
        candidates = [job("fetch_sources", "top10_for_period", code=code, market=market, report_date=report_date)] if report_date else []
        add("十大股东", "十大股东.csv", candidates)
    return specs


def hk_statement(code, title):
    """Pivot HK item rows; preserve provider names and amounts without guessing aliases."""
    import akshare as ak
    frame = ak.stock_financial_hk_report_em(stock=code, symbol=title, indicator="报告期")
    if frame.empty:
        raise ValueError("港股三表无数据")
    if frame.duplicated(["REPORT_DATE", "STD_ITEM_NAME"]).any():
        raise ValueError("港股报表同期间同项目重复，须核合并范围后处理")
    return normalize_hk_statement(frame.pivot(index="REPORT_DATE", columns="STD_ITEM_NAME", values="AMOUNT").reset_index(), title)


def normalize_hk_statement(frame, title):
    """Add conservative canonical aliases; keep original provider columns/scale.

    HK `营业额` may exclude other revenue: only `营运收入` is the total.
    Missing components stay unknown. Nominal Cayman share capital is not shares.
    """
    result = frame.copy()
    aliases = {
        "利润表": {"TOTAL_OPERATE_INCOME":"营运收入", "OPERATE_INCOME":"营运收入",
            "PARENT_NETPROFIT":"股东应占溢利", "NETPROFIT":"除税后溢利", "BASIC_EPS":"每股基本盈利",
            "INVEST_INCOME":"溢利其他项目",
            "OPERATE_COST":"营运支出", "OPERATE_PROFIT":"经营溢利", "TOTAL_PROFIT":"除税前溢利",
            "INCOME_TAX":"税项", "ADMIN_EXPENSE":"行政开支", "SELLING_EXPENSE":"销售及分销费用"},
        "资产负债表": {"TOTAL_PARENT_EQUITY":"股东权益", "TOTAL_EQUITY":"总权益", "TOTAL_ASSETS":"总资产",
            "TOTAL_LIABILITIES":"总负债", "MONETARYFUNDS":"现金及等价物", "RESTRICTED_CASH":"受限制存款及现金",
            "SHORT_LOAN":"短期贷款", "LONG_LOAN":"长期贷款", "TOTAL_CURRENT_ASSETS":"流动资产合计",
            "TOTAL_CURRENT_LIAB":"流动负债合计", "ACCOUNTS_RECE":"应收帐款", "ACCOUNTS_PAYABLE":"应付帐款",
            "INVENTORY":"存货", "CIP":"在建工程", "INTANGIBLE_ASSET":"无形资产",
            "LONG_EQUITY_INVEST":"联营公司权益", "OTHER_NONCURRENT_FINASSET":"其他金融资产(非流动)",
            "TRADE_FINASSET":"交易性金融资产(流动)", "OTHER_PAYABLE":"其他应付款及应计费用"},
        "现金流量表": {"NETCASH_OPERATE":"经营业务现金净额", "NETCASH_INVEST":"投资业务现金净额",
            "NETCASH_FINANCE":"融资业务现金净额", "DEPR_AMORT":"加:折旧及摊销",
            "BEGIN_CCE":"期初现金", "END_CCE":"期末现金", "CCE_ADD":"现金净额", "RATE_CHANGE_EFFECT":"期间变动其他项目",
            "INVENTORY_REDUCE":"存货(增加)减少", "OPERATE_RECE_REDUCE":"应收帐款减少",
            "OPERATE_PAYABLE_ADD":"应付帐款及应计费用增加(减少)", "PAY_ALL_TAX":"已付税项"},
    }
    for canonical, original in aliases.get(title, {}).items():
        if original in result:
            result[canonical] = pd.to_numeric(result[original], errors="coerce")
    if title == "利润表" and {"NETPROFIT", "PARENT_NETPROFIT"}.issubset(result.columns):
        result["MINORITY_INTEREST"] = result["NETPROFIT"] - result["PARENT_NETPROFIT"]
    if title == "资产负债表" and {"指定以公允价值记账之金融资产", "指定以公允价值记账之金融资产(流动)"}.issubset(result.columns):
        result["FAIR_VALUE_FINASSET"] = result[["指定以公允价值记账之金融资产", "指定以公允价值记账之金融资产(流动)"]].apply(pd.to_numeric, errors="coerce").sum(axis=1,min_count=2)
    sums = {
        "资产负债表": {"BOND_PAYABLE":["应付票据", "应付票据(非流动)"],
                      "LEASE_LIAB":["融资租赁负债(流动)", "融资租赁负债(非流动)"],
                      "CONTRACT_LIAB":["递延收入(流动)", "递延收入(非流动)"]},
        "现金流量表": {"CONSTRUCT_LONG_ASSET":["购建固定资产", "购建无形资产及其他资产"]},
    }
    for canonical, originals in sums.get(title, {}).items():
        if all(name in result for name in originals):
            result[canonical] = result[originals].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=len(originals))
    return result


def emweb_indicators(code, market, quarterly=False):
    import requests
    params = {"reportName":"RPT_F10_FINANCE_MAINFINADATA", "columns":"ALL", "pageNumber":1, "pageSize":500,
              "sortColumns":"REPORT_DATE", "sortTypes":-1, "filter":f'(SECUCODE="{code}.{market.upper()}")'}
    response = requests.get("https://datacenter-web.eastmoney.com/api/data/v1/get", params=params, timeout=15)
    response.raise_for_status()
    df = pd.DataFrame((response.json().get("result") or {}).get("data") or [])
    if not quarterly or df.empty:
        return df
    # EPS differences require the immediate predecessor; missing Q1/Q2/Q3 is not zero.
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"])
    df = df.sort_values("REPORT_DATE").drop_duplicates("REPORT_DATE", keep="last")
    eps = pd.to_numeric(df["EPSJB"], errors="coerce")
    periods = df["REPORT_DATE"].dt.to_period("Q")
    previous = periods.shift(1)
    contiguous = periods.astype("int64") - previous.astype("int64") == 1
    same_year = df["REPORT_DATE"].dt.year.eq(df["REPORT_DATE"].shift().dt.year)
    df["EPSJB"] = eps.where(df["REPORT_DATE"].dt.quarter == 1, (eps-eps.shift()).where(contiguous & same_year))
    return df[["REPORT_DATE", "EPSJB"]].dropna(subset=["EPSJB"])


def tencent_info(code, mkt):
    import requests
    response = requests.get(f"https://qt.gtimg.cn/q={mkt.lower()}{code}", timeout=10)
    response.raise_for_status()
    response.encoding = "gbk"
    match = re.search(r'="([^"]*)"', response.text)
    if not match:
        raise ValueError("腾讯实时行情无数据")
    fields = match.group(1).split("~")
    if len(fields) < 47:
        raise ValueError("腾讯行情字段不足")
    price = float(fields[3])
    cap = float(fields[45])*1e8
    hk = mkt.upper() == "HK"
    if hk and len(fields) < 71:
        raise ValueError("腾讯港股行情字段不足，拒绝套用A股布局")
    return pd.DataFrame([("总市值", cap), ("流通市值", float(fields[44])*1e8), ("最新价", price),
        ("市盈率(TTM)", float(fields[39])), ("市净率", float(fields[58] if hk else fields[46])),
        ("总股本", float(fields[69]) if hk else round(cap/price) if price>0 else None)], columns=["item", "value"])


def top10_for_period(code, market, report_date):
    import akshare as ak
    period = pd.Timestamp(report_date).strftime("%Y%m%d")
    df = ak.stock_gdfx_top_10_em(symbol=market.lower()+code, date=period)
    # API accepts a date but does not always echo it: do not claim independent period verification.
    period_cols = [c for c in df.columns if c in ("报告期", "报告日期", "REPORT_DATE", "END_DATE", "截止日期")]
    if not period_cols or not all(pd.to_datetime(df[c], errors="coerce").eq(pd.Timestamp(report_date)).all() for c in period_cols):
        raise ValueError("十大股东响应未确认请求报告期；须以披露文件补核")
    return df
