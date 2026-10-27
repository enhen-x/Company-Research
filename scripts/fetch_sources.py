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
    return pd.DataFrame([("总市值", cap), ("流通市值", float(fields[44])*1e8), ("最新价", price),
        ("市盈率(TTM)", float(fields[39])), ("市净率", float(fields[46])),
        ("总股本", round(cap/price) if price>0 else None)], columns=["item", "value"])


def top10_for_period(code, market, report_date):
    import akshare as ak
    period = pd.Timestamp(report_date).strftime("%Y%m%d")
    df = ak.stock_gdfx_top_10_em(symbol=market.lower()+code, date=period)
    # API accepts a date but does not always echo it: do not claim independent period verification.
    period_cols = [c for c in df.columns if c in ("报告期", "报告日期", "REPORT_DATE", "END_DATE", "截止日期")]
    if not period_cols or not all(pd.to_datetime(df[c], errors="coerce").eq(pd.Timestamp(report_date)).all() for c in period_cols):
        raise ValueError("十大股东响应未确认请求报告期；须以披露文件补核")
    return df
