#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同行财务指标拉取模板 v2（2026-08-15 合并：腾讯实时行情 + F10 HTTP 兜底）。

适用场景：B5 交叉验证需要同行 BPS/EPS/ROE/归母净利/现价/PE/PB。
实测（2026-08）：东财 stock_financial_analysis_indicator_em / 三表接口对非目标股票
可能被限流（返回 None）；东财 F10 datacenter-web HTTP 直连稳定，且为主财务累计年报口径。
本脚本依次尝试  F10 HTTP → 财务指标接口 → 三表接口；腾讯实时行情失败时回退项目内同行日线。

用法：
    python fetch_peers_financials.py --dir "G:\\理财\\个股分析\\SH.601319 中国人保" \
        --peers "601318:中国平安,601628:中国人寿,601601:中国太保,601336:新华保险"

市场前缀按代码自动推断（6/9→SH，0/3→SZ，4/8/92→BJ）。

输出：data/同行_财务指标汇总.csv
列：代码/公司/最新价/现价日期/PE_TTM/PB/总市值_亿/报告期/EPS/BPS/ROE加权%/归母净利(亿)/归母净资产(亿)/TTM归母净利(亿)/数据来源

口径说明：
- EPS/BPS/ROE/归母净利/归母净资产 = 最新年报口径（F10 累计值；财务指标接口取财年 4 期单季求和；
  三表接口直接给年报值）。财务指标接口的 EPSJB/PARENTNETPROFIT 为单季度值（2026-08 实测），
  不能直接当年报用；ROE_DILUTED 为单季 ROE，故该途径 ROE 不输出。
- TTM归母净利(亿) = 总市值/PE_TTM，为交叉校验列；TTM 与年报口径差异需在报告中说明
  （如 2026-08 贵州茅台批次：五粮液 TTM 126 亿 vs 年报 89.5 亿）。
- 若已存在手工维护的 CSV 且未指定 --keep，先备份为 .bak_YYYYmmdd。
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import akshare as ak
import pandas as pd
import requests


def p(msg: str) -> None:
    print(msg, flush=True)


def infer_market(code: str, hint: str = "") -> str:
    """按代码推断市场前缀：6/9→SH，0/3→SZ，4/8/92→BJ；hint 可显式指定（如 'HK'）。"""
    h = (hint or "").strip().upper()
    if h in ("SH", "SZ", "BJ", "HK"):
        return h
    c = code.strip()
    if c.startswith(("4", "8")) or c.startswith("92"):
        return "BJ"
    if c.startswith(("6", "9")):
        return "SH"
    if c.startswith(("0", "3")):
        return "SZ"
    raise ValueError(f"无法推断市场前缀: {code}")


def fetch_retry(fn, name: str, retries: int = 3, delay: float = 12.0):
    """长间隔重试（东财接口对同行限流，短间隔重试无效）"""
    last = None
    for i in range(1, retries + 1):
        try:
            p(f"[拉取] {name}（第 {i}/{retries} 次）...")
            df = fn()
            if df is None or len(df) == 0:
                raise RuntimeError("空数据/None")
            return df
        except Exception as exc:
            last = exc
            if i < retries:
                time.sleep(delay)
    raise RuntimeError(f"{name} 连续失败: {last}")


def qq_quote(symbols: list[str]) -> dict:
    """腾讯实时行情 -> {code: {price, pe_ttm, pb, mktcap_亿}}。
    港股（hk 前缀）PB 字段布局与 A 股不同（f[46] 为英文名），PB 置 None 待手工补齐。"""
    url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
    r = requests.get(url, timeout=10)
    r.encoding = "gbk"
    out = {}
    for line in r.text.strip().split(";"):
        m = re.search(r'="([^"]*)"', line)
        if not m:
            continue
        f = m.group(1).split("~")
        # f[3]=现价 f[39]=PE_TTM f[45]=总市值(亿)；A股 f[46]=PB，港股 f[46]=英文名
        if len(f) < 47:
            continue
        try:
            out[f[2]] = {
                "price": float(f[3]), "pe_ttm": float(f[39]),
                "pb": None if f[2].isdigit() and len(f[2]) == 5 and not f[46].replace(".", "").isdigit() else _pb_or_none(f),
                "mktcap_亿": float(f[45]),
            }
        except (TypeError, ValueError):
            continue
    return out


def _pb_or_none(f: list[str]) -> float | None:
    """A 股 f[46] 为 PB；港股该位为英文名，返回 None。"""
    try:
        v = float(f[46])
        return v if 0 < v < 200 else None
    except (TypeError, ValueError):
        return None


def f10_annual(code: str, mkt: str, period: str = "annual") -> dict | None:
    """F10 cumulative accounts; period=annual/latest/YYYY-MM-DD (no YTD annualisation)."""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_F10_FINANCE_MAINFINADATA",
        "columns": "ALL",
        "filter": f'(SECUCODE="{code}.{mkt}")',
        "pageNumber": "1", "pageSize": "60", "sortColumns": "REPORT_DATE",
        "sortTypes": "-1", "source": "HSF10", "client": "PC",
    }
    r = requests.get(url, params=params, timeout=15)
    rows = (r.json().get("result") or {}).get("data") or []
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"])
    if period == "annual":
        ann = df[df["REPORT_DATE"].dt.month == 12].sort_values("REPORT_DATE")
    elif period == "latest":
        ann = df.sort_values("REPORT_DATE")
    else:
        ann = df[df["REPORT_DATE"] == pd.Timestamp(period)].sort_values("REPORT_DATE")
    if ann.empty:
        return None
    last = ann.iloc[-1]
    eps = first_num(last, ["EPSJB"])
    bps = first_num(last, ["BPS"])
    roe = first_num(last, ["ROEJQ"])
    np_亿 = first_num(last, ["PARENTNETPROFIT"])
    np_亿 = np_亿 / 1e8 if np_亿 is not None else None
    shares = first_num(last, ["TOTAL_SHARE"])
    equity_亿 = bps * shares / 1e8 if (bps is not None and shares) else None
    # 营收与增速（F10 自带同比增速列；缺失时用相邻两年绝对值重算）——图06 增速面板数据来源
    rev_亿 = first_num(last, ["TOTALOPERATEREVE", "OPERATE_INCOME_PK"])
    rev_亿 = rev_亿 / 1e8 if rev_亿 is not None else None
    rev_tz = first_num(last, ["TOTALOPERATEREVETZ", "OI_YOYRATIO_PK"])
    np_tz = first_num(last, ["PARENTNETPROFITTZ"])
    previous = df[df["REPORT_DATE"] == last["REPORT_DATE"] - pd.DateOffset(years=1)]
    if not previous.empty:
        prev = previous.iloc[-1]
        prev_rev = first_num(prev, ["TOTALOPERATEREVE", "OPERATE_INCOME_PK"])
        prev_np = first_num(prev, ["PARENTNETPROFIT"])
        if rev_tz is None and rev_亿 is not None and prev_rev:
            rev_tz = (rev_亿 * 1e8 - prev_rev) / prev_rev * 100
        if np_tz is None and np_亿 is not None and prev_np:
            np_tz = (np_亿 * 1e8 - prev_np) / prev_np * 100
    return {
        "报告期": str(last["REPORT_DATE"].date()), "EPS": eps, "BPS": bps,
        "ROE加权%": roe, "归母净利(亿)": np_亿, "归母净资产(亿)": equity_亿,
        "营收(亿)": rev_亿,
        "营收增速%": round(rev_tz, 2) if rev_tz is not None else None,
        "净利增速%": round(np_tz, 2) if np_tz is not None else None,
        "数据来源": "F10主财务（累计实际，非年化）",
    }


def ind_annual(code: str, mkt: str) -> dict | None:
    """途径2：东财财务指标接口（按报告期=单季口径，财年 4 期求和得年报值）"""
    ind = fetch_retry(
        lambda c=code, m=mkt: ak.stock_financial_analysis_indicator_em(
            symbol=f"{c}.{m}", indicator="按报告期"),
        f"{code} {mkt} 财务指标")
    ind["REPORT_DATE"] = pd.to_datetime(ind["REPORT_DATE"])
    ann_row = ind[ind["REPORT_DATE"].dt.month == 12].sort_values("REPORT_DATE")
    if ann_row.empty:
        return None
    last = ann_row.iloc[-1]
    yr = last["REPORT_DATE"].year
    q4 = ind[ind["REPORT_DATE"].dt.year == yr]
    eps = float(q4["EPSJB"].sum()) if "EPSJB" in q4 else None
    np_亿 = None
    rev_亿 = None
    for col in ("PARENTNETPROFIT", "PARENT_NETPROFIT"):
        if col in q4:
            np_亿 = float(q4[col].sum()) / 1e8
            break
    for col in ("TOTALOPERATEREVE", "TOTAL_OPERATE_INCOME"):
        if col in q4:
            rev_亿 = float(q4[col].sum()) / 1e8
            break
    bps = first_num(last, ["BPS"])
    rev_tz = np_tz = None
    prev_rows = ind[ind["REPORT_DATE"].dt.year == yr - 1]
    if not prev_rows.empty:
        p_rev = p_np = None
        for col in ("TOTALOPERATEREVE", "TOTAL_OPERATE_INCOME"):
            if col in prev_rows:
                p_rev = float(prev_rows[col].sum())
                break
        for col in ("PARENTNETPROFIT", "PARENT_NETPROFIT"):
            if col in prev_rows:
                p_np = float(prev_rows[col].sum())
                break
        if rev_亿 and p_rev:
            rev_tz = (rev_亿 * 1e8 - p_rev) / p_rev * 100
        if np_亿 and p_np:
            np_tz = (np_亿 * 1e8 - p_np) / p_np * 100
    return {
        "报告期": str(last["REPORT_DATE"].date()), "EPS": eps, "BPS": bps,
        "ROE加权%": None,  # 单季 ROE 不输出，避免误导
        "归母净利(亿)": np_亿, "归母净资产(亿)": None,
        "营收(亿)": rev_亿,
        "营收增速%": round(rev_tz, 2) if rev_tz is not None else None,
        "净利增速%": round(np_tz, 2) if np_tz is not None else None,
        "数据来源": "财务指标接口(单季求和)",
    }


def sheets_annual(code: str) -> dict | None:
    """途径3：利润表 + 资产负债表（年报口径，原模板兜底）"""
    pl = fetch_retry(lambda c=code: ak.stock_profit_sheet_by_report_em(symbol=c),
                     f"{code} 利润表")
    bs = fetch_retry(lambda c=code: ak.stock_balance_sheet_by_report_em(symbol=c),
                     f"{code} 资产负债表")
    pl["REPORT_DATE"] = pd.to_datetime(pl["REPORT_DATE"])
    bs["REPORT_DATE"] = pd.to_datetime(bs["REPORT_DATE"])
    rp = pl["REPORT_DATE"].max()
    pp = pl[pl["REPORT_DATE"] == rp].iloc[0]
    bb = bs[bs["REPORT_DATE"] == rp].iloc[0]
    np_亿 = first_num(pp, ["PARENT_NETPROFIT", "NETPROFIT"])
    rev_亿 = first_num(pp, ["TOTAL_OPERATE_INCOME", "OPERATE_INCOME"])
    eq_亿 = first_num(bb, ["TOTAL_PARENT_EQUITY", "PARENT_EQUITY", "PARENT_EQUITY_BALANCE"])
    rev_tz = np_tz = None
    pl_prev = pl[pl["REPORT_DATE"] < rp].sort_values("REPORT_DATE")
    if not pl_prev.empty:
        pp_prev = pl_prev.iloc[-1]
        p_rev = first_num(pp_prev, ["TOTAL_OPERATE_INCOME", "OPERATE_INCOME"])
        p_np = first_num(pp_prev, ["PARENT_NETPROFIT", "NETPROFIT"])
        if rev_亿 and p_rev:
            rev_tz = (rev_亿 - p_rev) / p_rev * 100
        if np_亿 and p_np:
            np_tz = (np_亿 - p_np) / p_np * 100
    return {
        "报告期": str(rp.date()), "EPS": None, "BPS": None, "ROE加权%": None,
        "归母净利(亿)": np_亿 / 1e8 if np_亿 is not None else None,
        "归母净资产(亿)": eq_亿 / 1e8 if eq_亿 is not None else None,
        "营收(亿)": rev_亿 / 1e8 if rev_亿 is not None else None,
        "营收增速%": round(rev_tz, 2) if rev_tz is not None else None,
        "净利增速%": round(np_tz, 2) if np_tz is not None else None,
        "数据来源": "三表接口",
    }


def parse_peers(s: str) -> list[tuple[str, str, str]]:
    """解析同行列表 '代码.市场:名称,代码:名称'；市场可选（SH/SZ/BJ/HK），缺省自动推断。
    港股必须带 .HK 前缀（如 '00316.HK:东方海外国际'），否则 0/3 开头会被误判为深市。"""
    out = []
    for item in (s or "").split(","):
        item = item.strip()
        if not item:
            continue
        code, _, name = item.partition(":")
        code = code.strip()
        market = ""
        if "." in code:
            code, _, market = code.partition(".")
            market = market.strip().upper()
        out.append((code, (name or code).strip(), market))
    return out


def first_num(row: pd.Series | dict, cols: list[str]) -> float | None:
    for c in cols:
        v = row.get(c) if isinstance(row, dict) else row.get(c)
        if v is not None and str(v).strip() not in ("", "nan", "None"):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="同行财务指标拉取模板 v2")
    ap.add_argument("--dir", required=True, help="项目目录（含 data/）")
    ap.add_argument("--peers", required=True, help='"代码:名称,代码:名称"')
    ap.add_argument("--keep", action="store_true", help="不备份已存在的汇总 CSV")
    ap.add_argument("--period", default="latest", help="latest（默认）/annual/共同报告期YYYY-MM-DD；中期值禁止当全年")
    args = ap.parse_args()

    data_dir = Path(args.dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_csv = data_dir / "同行_财务指标汇总.csv"
    if out_csv.exists() and not args.keep:
        bak = out_csv.with_suffix(f".bak_{datetime.now():%Y%m%d}")
        out_csv.replace(bak)
        p(f"[备份] {out_csv.name} -> {bak.name}")

    peers = parse_peers(args.peers)
    quotes = {}
    try:
        syms = [f"{infer_market(c, m).lower()}{c}" for c, _, m in peers]
        quotes = qq_quote(syms)
        p("[腾讯] 实时行情: " + ", ".join(f"{c}={quotes.get(c, {}).get('price')}" for c, _, _ in peers))
    except Exception as exc:
        p(f"[降级] 腾讯实时行情失败: {exc}，将回退项目内同行日线 CSV")

    rows, failures = [], []
    for code, name, mkt_hint in peers:
        market = infer_market(code, mkt_hint)
        row = {"代码": code, "市场": market, "公司": name, "营收(亿)": None, "营收增速%": None, "净利增速%": None}
        q = quotes.get(code, {})
        row["最新价"] = q.get("price")
        row["现价日期"] = datetime.now().strftime("%Y-%m-%d") if q.get("price") is not None else ""
        row["PE_TTM"] = q.get("pe_ttm")
        row["PB"] = q.get("pb")
        row["总市值_亿"] = q.get("mktcap_亿")
        if q.get("pe_ttm") and q.get("mktcap_亿"):
            row["TTM归母净利_亿"] = round(q["mktcap_亿"] / q["pe_ttm"], 1)
        else:
            row["TTM归母净利_亿"] = None

        got = None
        if market == "HK":
            # 港股无东财 F10/三表 A 股接口，行情已取，财务数据需联网/手工补齐
            p(f"[HK] {name}: 港股财务数据无 A 股接口，需联网搜索补齐（BPS/DPS/归母净利/ROE）")
        else:
            try:
                got = f10_annual(code, market, args.period)
                if got:
                    p(f"[OK] {name}: F10 {got['报告期']} EPS={got['EPS']} BPS={got['BPS']} ROE={got['ROE加权%']}")
            except Exception as exc:
                p(f"[降级] {name} F10 失败: {exc}")
            if not got and args.period == "annual":
                try:
                    got = ind_annual(code, market)
                    if got:
                        p(f"[OK] {name}: 财务指标接口(单季求和) {got['报告期']} EPS={got['EPS']} BPS={got['BPS']}")
                except Exception as exc:
                    p(f"[降级] {name} 财务指标接口失败: {exc}")
            if not got and args.period == "annual":
                try:
                    got = sheets_annual(code)
                    if got:
                        p(f"[OK] {name}: 三表接口 {got['报告期']}")
                except Exception as exc:
                    p(f"[降级] {name} 三表接口失败: {exc}")
        if not got:
            p(f"[WARN] {code} {name} 全部接口不可用 → 请在下方提示后手工补齐该行")
            failures.append(f"{code} {name}")
            rows.append(row)
            continue
        row.update(got)

        # 现价回退：腾讯失败时用项目内已有同行日线
        if row["最新价"] is None:
            px_file = data_dir / f"同行_{code}_{name}_日线.csv"
            if px_file.exists():
                px = pd.read_csv(px_file, encoding="utf-8")
                row["最新价"] = round(float(px.iloc[-1]["close"]), 2)
                row["现价日期"] = str(px.iloc[-1].get("date", ""))
                row["PE_TTM"] = row.get("PE_TTM")  # 保留 None，日线无 PE
        rows.append(row)
        time.sleep(8)  # 限流保护

    df = pd.DataFrame(rows)
    cols = ["代码", "市场", "公司", "最新价", "现价日期", "PE_TTM", "PB", "总市值_亿",
            "报告期", "EPS", "BPS", "ROE加权%", "归母净利(亿)", "归母净资产(亿)",
            "营收(亿)", "营收增速%", "净利增速%",
            "TTM归母净利_亿", "数据来源"]
    df = df[[c for c in cols if c in df.columns]]
    if len(df):
        df.to_csv(out_csv, index=False, encoding="utf-8-sig")
        p(f"\n=== 汇总（{out_csv.name}）===")
        p(df.to_string(index=False))
    else:
        p("[WARN] 未获取任何同行财务数据，未生成汇总 CSV")

    if failures:
        p(f"\n[兜底提示] 请用公司公告补齐同行 {args.period} 数据；禁止静默回退旧年报或混用期间：")
        p("  港股（.HK 前缀）行情已自动取，但需手工补齐：每股净资产 BPS、全年每股股息 DPS、归母净利、ROE")
        p("  每股净资产 BPS、全年每股股息 DPS、归母净利、ROE（来源：公司年报摘要/利润分配公告）")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
