#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动化证券调研流水线（配合《研究框架_券商深度标准.md》使用）

一句话触发 -> 自动拉数 -> 自动审计 -> 生成项目骨架 -> 交给 Agent 按深度标准分析。

用法：
    python research_pipeline.py "调研 温氏股份"
    python research_pipeline.py "调研 300498"
    python research_pipeline.py --company 温氏股份 --code 300498
    python research_pipeline.py --data-dir "G:\\理财\\个股分析\\SZ.002714 牧原股份\\2026_08_22\\data" --audit-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# Start the watchdog before importing pandas, providers or plotting libraries.
if __name__ == "__main__" and "--_pipeline-worker" not in sys.argv:
    from run_support import run_process
    guard = argparse.ArgumentParser(add_help=False)
    guard.add_argument("--total-timeout", type=float, default=1200)
    options, _ = guard.parse_known_args()
    try:
        outcome = run_process([sys.executable, "-u", str(Path(__file__).resolve()), *sys.argv[1:], "--_pipeline-worker"],
                              timeout=options.total_timeout, heartbeat=15, label="B1-B3总流程")
    except ValueError as exc:
        guard.error(str(exc))
    raise SystemExit(124 if outcome["status"] == "TIMEOUT" else outcome.get("exit_code") or (0 if outcome["status"] == "PASS" else 1))

from fetch_with_fallback import add_fetch_options, fetch_datasets
from bounded_fetch import fetch_job, job
from run_support import atomic_json, run_process

import pandas as pd

RESEARCH_ROOT = Path(os.environ.get("RESEARCH_ROOT", Path.cwd()))
TODAY = datetime.now()

def parse_prompt(prompt: str) -> tuple[str | None, str | None]:
    """从 "调研 温氏股份" / "调研 300498" 中解析 公司名 / 代码"""
    text = prompt.strip()
    text = re.sub(r"^调研\s*", "", text)
    if re.fullmatch(r"\d{6}", text):
        return None, text
    if text:
        return text, None
    return None, None


def infer_market(code: str) -> str:
    if len(code) == 5 and code.isdigit():
        return "HK"
    if code.startswith(("4", "8", "92")):
        return "BJ"
    if code.startswith(("6", "9")):
        return "SH"
    return "SZ"

def _tencent_smartbox(q: str) -> list[tuple[str, str, str]]:
    """腾讯智能提示：q=名称/代码/拼音 -> [(市场前缀, 代码, 名称), ...]（GBK 解码）。

    实测可用（2026-08-21）：https://smartbox.gtimg.cn/s3/?q=小商品城&t=all
    返回 v_hint="sh~600415~小商品城~xspc~GP-A"。SSE 名称解析接口 SSL 故障时的降级主力。
    """
    import codecs
    import re as _re

    import requests
    url = "https://smartbox.gtimg.cn/s3/?q={}&t=all".format(requests.utils.quote(q))
    r = requests.get(url, timeout=10)
    # 实测（2026-08-21）：smartbox 返回 ASCII + 字面 \uXXXX 转义，需 unicode_escape 解码
    m = _re.search(r'v_hint="([^"]*)"', r.text)
    if not m or not m.group(1).strip():
        return []
    try:
        hint = codecs.decode(m.group(1), "unicode_escape")
    except Exception:
        hint = m.group(1)
    out = []
    for item in hint.split("^"):
        parts = item.split("~")
        if len(parts) >= 3 and parts[0] and parts[1] and parts[2]:
            out.append((parts[0], parts[1], parts[2]))
    return out


def _tencent_quote_name(code: str, market: str) -> str | None:
    """腾讯实时行情：代码 -> 公司名（字段[1]）。qt.gtimg.cn 实测可用。"""
    import re as _re

    import requests
    url = f"https://qt.gtimg.cn/q={market.lower()}{code}"
    r = requests.get(url, timeout=10)
    r.encoding = "gbk"
    m = _re.search(r'="([^"]*)"', r.text)
    if not m:
        return None
    f = m.group(1).split("~")
    return f[1] if len(f) > 1 and f[1].strip() else None


def _ak_code_name() -> pd.DataFrame | None:
    """akshare A 股代码-名称全列表（底层走交易所接口，SSL 故障时抛异常）。"""
    try:
        df, _ = fetch_job(job("akshare", "stock_info_a_code_name"),
                          cache_dir=RESEARCH_ROOT / ".source_failures", timeout=30, retries=1)
        if df is not None and not df.empty and {"code", "name"}.issubset(df.columns):
            return df
    except Exception as exc:
        print(f"[解析] akshare 股票列表失败（将尝试腾讯降级）: {exc}")
    return None


def resolve_code(name: str) -> str | None:
    """公司名 -> 代码。降级链：akshare 全列表（精确+包含）-> 腾讯智能提示；失败返回 None。"""
    df = _ak_code_name()
    if df is not None:
        hit = df[df["name"] == name]
        if not hit.empty:
            return str(hit.iloc[0]["code"])
        hit2 = df[df["name"].str.contains(name, na=False)]
        if not hit2.empty:
            print(f"[解析] 名称包含匹配: {name} -> {hit2.iloc[0]['name']}（{hit2.iloc[0]['code']}）")
            return str(hit2.iloc[0]["code"])
    try:
        hits = [x for x in _tencent_smartbox(name)
                if x[0].lower() in ("sh", "sz", "bj") and x[1].isdigit()]
        for _mkt, code, nm in hits:
            if nm == name:
                return code
        if hits:
            print(f"[解析] 腾讯智能提示近似匹配: {name} -> {hits[0][2]}（{hits[0][1]}）")
            return hits[0][1]
    except Exception as exc:
        print(f"[解析] 腾讯智能提示失败: {exc}")
    return None


def resolve_name(code: str) -> str | None:
    """代码 -> 公司名。降级链：akshare 全列表 -> 腾讯智能提示 -> 腾讯实时行情；失败返回 None。"""
    df = _ak_code_name()
    if df is not None:
        hit = df[df["code"] == code]
        if not hit.empty:
            return str(hit.iloc[0]["name"])
    try:
        for _mkt, c, nm in _tencent_smartbox(code):
            if c == code and nm:
                return nm
    except Exception as exc:
        print(f"[解析] 腾讯智能提示失败: {exc}")
    try:
        nm = _tencent_quote_name(code, infer_market(code))
        if nm:
            return nm
    except Exception as exc:
        print(f"[解析] 腾讯实时行情查询名称失败: {exc}")
    return None


def save_csv(frame: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(path)


def find_col(df: pd.DataFrame, *keywords: str) -> str | None:
    """按关键字找列名（大小写不敏感、包含匹配）"""
    for col in df.columns:
        up = str(col).upper()
        if all(k.upper() in up for k in keywords):
            return col
    return None


def to_date_series(df: pd.DataFrame, col: str) -> pd.Series:
    s = pd.to_datetime(df[col], errors="coerce")
    return s


def audit_data(data_dir: Path) -> tuple[list[dict], str]:
    """B3 数据审计：返回 (检查项列表, 门控状态: pass/warn/fail)"""
    checks: list[dict] = []
    status = "pass"

    def add(name: str, level: str, detail: str) -> None:
        nonlocal status
        checks.append({"name": name, "level": level, "detail": detail})
        if level == "❌":
            status = "fail"
        elif level == "⚠️" and status == "pass":
            status = "warn"

    def load(fname: str) -> pd.DataFrame | None:
        p = data_dir / fname
        if not p.exists():
            add(f"文件 {fname}", "❌", "缺失")
            return None
        try:
            df = pd.read_csv(p, dtype=str)
            if df.empty:
                add(f"文件 {fname}", "❌", "空文件")
                return None
            return df
        except Exception as exc:
            add(f"文件 {fname}", "❌", f"读取失败: {exc}")
            return None

    # ── 完整性 ──
    bs = load("资产负债表_按报告期.csv")
    inc = load("利润表_按报告期.csv")
    cf = load("现金流量表_按报告期.csv")
    # HK providers expose cumulative indicators only; do not manufacture a
    # quarterly table or make an unavailable optional endpoint a hard failure.
    hk = data_dir.parent.parent.name.startswith("HK.")
    if hk and not (data_dir / "主要财务指标_按单季度.csv").exists():
        ind_q = None
        add("港股单季度指标", "⚠️", "源未提供独立单季度指标；流量按三表累计差分，率类不作差分")
    else:
        ind_q = load("主要财务指标_按单季度.csv")
    ind_a = load("主要财务指标_按报告期.csv")

    for label, df in [("资产负债表", bs), ("利润表", inc), ("现金流量表", cf),
                      ("财务指标(季度)", ind_q), ("财务指标(年度)", ind_a)]:
        if df is None:
            continue
        dcol = find_col(df, "REPORT", "DATE") or find_col(df, "报告期")
        if dcol:
            dates = to_date_series(df, dcol).dropna()
            if len(dates):
                years = sorted({d.year for d in dates})
                latest = dates.max()
                months_old = (TODAY.year - latest.year) * 12 + TODAY.month - latest.month
                cov = f"{years[0]}-{years[-1]}（{len(years)} 年）"
                lvl = "✅" if len(years) >= 8 else "⚠️"
                if months_old > 12:
                    lvl = "❌"
                    add(f"完整性·{label}", lvl,
                        f"最新报告期 {latest:%Y-%m}（距今 {months_old} 个月），覆盖 {cov}")
                else:
                    add(f"完整性·{label}", lvl,
                        f"覆盖 {cov}，最新 {latest:%Y-%m}（{months_old} 个月）")
        else:
            add(f"完整性·{label}", "⚠️", "未找到报告期列，跳过覆盖检查")

    # ── 一致性：归母净利 vs EPS×股本；归母权益 vs BPS×股本 ──
    if bs is not None and inc is not None and ind_a is not None:
        eq_col = find_col(bs, "TOTAL_PARENT_EQUITY") or find_col(bs, "归母权益")
        ni_col = find_col(inc, "PARENT_NETPROFIT") or find_col(inc, "归母净利润")
        bps_col = find_col(ind_a, "BPS") or find_col(ind_a, "每股净资产")
        eps_col = find_col(ind_a, "EPSJB") or find_col(ind_a, "BASIC_EPS") or find_col(ind_a, "基本每股收益")
        if eq_col and ni_col and bps_col:
            bs_d = bs[[find_col(bs, "REPORT", "DATE") or "REPORT_DATE", eq_col]].dropna()
            inc_d = inc[[find_col(inc, "REPORT", "DATE") or "REPORT_DATE", ni_col]].dropna()
            indicator_columns = list(dict.fromkeys([find_col(ind_a, "REPORT", "DATE") or "REPORT_DATE",
                           bps_col, eps_col or bps_col]))
            ind_d = ind_a[indicator_columns].dropna()
            # 对齐最新年报
            def annual(d, col):
                d = d.copy()
                d["_date"] = pd.to_datetime(d.iloc[:, 0], errors="coerce")
                d = d[d["_date"].dt.month == 12]
                return d.sort_values("_date").iloc[-1][col]
            try:
                eq = float(annual(bs_d, eq_col))
                ni = float(annual(inc_d, ni_col))
                bps = float(annual(ind_d, bps_col))
                eps = float(annual(ind_d, eps_col))
                shares = eq / bps if bps else 0
                eps_implied = ni / shares if shares else 0
                if eps and shares:
                    dev = abs(eps_implied - eps) / abs(eps) * 100
                    lvl = "✅" if dev <= 10 else "⚠️"
                    add("一致性·EPS×股本 vs 报表归母净利", lvl,
                        f"隐含EPS {eps_implied:.2f} vs 披露EPS {eps:.2f}（偏差 {dev:.1f}%）")
            except Exception as exc:
                add("一致性·勾稽", "⚠️", f"无法计算: {exc}")
        else:
            add("一致性·勾稽", "⚠️", "缺少关键列，跳过交叉验证")

    # ── 一致性：经营现金流含金量（最近 5 年） ──
    if cf is not None and inc is not None:
        ocf_col = find_col(cf, "NETCASH_OPERATE") or find_col(cf, "经营活动产生的现金流量净额")
        np_col = find_col(inc, "NETPROFIT") or find_col(inc, "净利润")
        if ocf_col and np_col:
            cf_d = cf[[find_col(cf, "REPORT", "DATE") or "REPORT_DATE", ocf_col]].copy()
            inc_d = inc[[find_col(inc, "REPORT", "DATE") or "REPORT_DATE", np_col]].copy()
            cf_d["_d"] = pd.to_datetime(cf_d.iloc[:, 0], errors="coerce")
            inc_d["_d"] = pd.to_datetime(inc_d.iloc[:, 0], errors="coerce")
            cf_d = cf_d[(cf_d["_d"].dt.month == 12) & cf_d["_d"].dt.year >= TODAY.year - 5]
            inc_d = inc_d[(inc_d["_d"].dt.month == 12) & inc_d["_d"].dt.year >= TODAY.year - 5]
            merged = cf_d.merge(inc_d, on="_d", suffixes=("_cf", "_inc"))
            for _, r in merged.iterrows():
                try:
                    ocf, np_ = float(r.iloc[1]), float(r.iloc[3])
                    ratio = ocf / np_ if np_ != 0 else 99
                    lvl = "✅" if 0.5 <= ratio <= 3 else "⚠️"
                    add(f"现金流含金量 {int(r['_d'].year)}", lvl,
                        f"OCF/净利 = {ratio:.2f}")
                except (TypeError, ValueError):
                    pass

    # ── 异常值（同比突变 >50% 或符号反转，每项须有合理解释） ──
    if inc is not None:
        rev_col = find_col(inc, "TOTAL_OPERATE_INCOME") or find_col(inc, "营业总收入")
        ni_col = find_col(inc, "PARENT_NETPROFIT") or find_col(inc, "归母净利润")
        if rev_col and ni_col:
            d = inc[[find_col(inc, "REPORT", "DATE") or "REPORT_DATE", rev_col, ni_col]].copy()
            d["_d"] = pd.to_datetime(d.iloc[:, 0], errors="coerce")
            d = d[d["_d"].dt.month == 12].sort_values("_d")
            for col in [rev_col, ni_col]:
                d[col] = pd.to_numeric(d[col], errors="coerce")
            d["rev_yoy"] = d[rev_col].pct_change() * 100
            d["ni_yoy"] = d[ni_col].pct_change() * 100
            for _, r in d.iterrows():
                for label, val in [("营收", r["rev_yoy"]), ("归母净利", r["ni_yoy"])]:
                    if pd.notna(val) and abs(val) > 50:
                        add(f"异常·{int(r['_d'].year)} {label}同比", "⚠️",
                            f"{val:+.0f}%（请核实口径/重组/周期影响）")
            prev_ni = None
            for _, r in d.iterrows():
                ni = r[ni_col]
                if pd.notna(ni) and ni != 0 and prev_ni is not None and (prev_ni > 0) != (ni > 0):
                    add(f"异常·{int(r['_d'].year)} 归母净利符号反转", "⚠️",
                        f"{prev_ni:,.0f} → {ni:,.0f}（请核实重组/一次性损益/行业周期）")
                if pd.notna(ni) and ni != 0:
                    prev_ni = ni
            if (d[ni_col] < 0).any():
                add("异常·亏损年份", "⚠️",
                    f"{int((d[ni_col] < 0).sum())} 个年度亏损，估值需用周期均值法")

    # 重复报告期
    for label, df in [("资产负债表", bs), ("利润表", inc), ("现金流量表", cf)]:
        if df is None:
            continue
        dcol = find_col(df, "REPORT", "DATE") or find_col(df, "报告期")
        if dcol and df[dcol].duplicated().any():
            add(f"异常·{label}重复报告期", "⚠️", f"{int(df[dcol].duplicated().sum())} 行重复")

    # ── 分红一致性 + 支付率双法校验（近3年） ──
    div = load("分红送配记录.csv")
    if div is not None and inc is not None:
        dcol = find_col(div, "REPORT", "DATE") or find_col(div, "报告期")
        dpc = find_col(div, "现金分红比例")
        tot = find_col(div, "总股本")
        exd = (find_col(div, "除权除息日") or find_col(div, "股权登记日")
               or find_col(div, "最新公告"))
        if dcol and dpc:
            try:
                dv_cols = [dcol, dpc] + ([exd] if exd else [dcol]) + ([tot] if tot else [])
                dv = div[dv_cols].copy()
                dv["_d"] = pd.to_datetime(dv[dcol], errors="coerce")
                dv["_ex"] = pd.to_datetime(dv[exd], errors="coerce") if exd else dv["_d"]
                dv["_dps"] = pd.to_numeric(dv[dpc], errors="coerce") / 10.0
                dv = dv.dropna(subset=["_d", "_dps"]).sort_values("_d")
                if tot is None:
                    raise ValueError("分红记录缺总股本列")
                dv["_sh"] = pd.to_numeric(dv[tot], errors="coerce")
                dv = dv.dropna(subset=["_sh"])
                dv["_yr"] = dv["_d"].dt.year
                dv["_payyr"] = dv["_ex"].dt.year.fillna(dv["_yr"]).astype(int)
                dps_yr = dv.groupby("_yr")["_dps"].sum()
                dps3 = dps_yr[dps_yr.index >= TODAY.year - 3]
                if len(dps3) >= 3:
                    if len(set(dps3.round(4))) == 1:
                        add("支付率·DPS 连续3年相同", "⚠️",
                            f"DPS {list(dps3.round(2))} 三年完全相同——疑似填充错误禁用法1；"
                            "若与『分配股利支付的现金』相符则为平滑分红政策（非数据错误）")
                    # 法1 = DPS/EPS 近3年均值；法2 = DPS×股本/归母净利 近3年均值
                    eps_col = find_col(ind_a, "EPSJB") or find_col(ind_a, "基本每股收益") \
                        if ind_a is not None else None
                    ni_col2 = find_col(inc, "PARENT_NETPROFIT") or find_col(inc, "归母净利润")
                    if eps_col and ni_col2:
                        e = ind_a[[find_col(ind_a, "REPORT", "DATE") or "REPORT_DATE",
                                   eps_col]].copy()
                        e["_d"] = pd.to_datetime(e.iloc[:, 0], errors="coerce")
                        e["_eps"] = pd.to_numeric(e[eps_col], errors="coerce")
                        e = e[e["_d"].dt.month == 12]
                        n = inc[[find_col(inc, "REPORT", "DATE") or "REPORT_DATE",
                                 ni_col2]].copy()
                        n["_d"] = pd.to_datetime(n.iloc[:, 0], errors="coerce")
                        n["_ni"] = pd.to_numeric(n[ni_col2], errors="coerce")
                        n = n[n["_d"].dt.month == 12]
                        m1s, m2s, cnt = [], [], 0
                        for yr, dps in dps3.items():
                            ei = e[e["_d"].dt.year == yr]["_eps"]
                            ni = n[n["_d"].dt.year == yr]["_ni"]
                            sh = dv[dv["_yr"] == yr].groupby("_yr")["_sh"].mean()
                            if len(ei) and len(ni) and yr in sh.index and sh[yr] and ni.iloc[0]:
                                m1 = dps / ei.iloc[0]
                                m2 = dps * sh[yr] / abs(ni.iloc[0])
                                m1s.append(m1)
                                m2s.append(m2)
                                cnt += 1
                        if cnt >= 2:
                            f1, f2 = sum(m1s) / cnt, sum(m2s) / cnt
                            dev = abs(f1 - f2) / f2 * 100 if f2 else 99
                            if dev > 5:
                                add("支付率·法1 vs 法2", "⚠️",
                                    f"法1 {f1:.3f} vs 法2 {f2:.3f}（偏差 {dev:.0f}%）>5pct，排除法1")
                            else:
                                add("支付率·法1 vs 法2", "✅",
                                    f"法1 {f1:.3f} vs 法2 {f2:.3f}（偏差 {dev:.0f}%），双法互证")
                    # 分红一致性：近3个支付年 应付（DPS×股本）vs 支付现金
                    ocf_pay = find_col(cf, "ASSIGN_DIVIDEND_PORFIT") if cf is not None else None
                    if ocf_pay and cf is not None:
                        cp = cf[[find_col(cf, "REPORT", "DATE") or "REPORT_DATE",
                                 ocf_pay]].copy()
                        cp["_d"] = pd.to_datetime(cp.iloc[:, 0], errors="coerce")
                        cp["_pay"] = pd.to_numeric(cp[ocf_pay], errors="coerce")
                        cp = cp[cp["_d"].dt.month == 12]
                        dv["_pay_amt"] = dv["_dps"] * dv["_sh"]
                        due = dv.groupby("_payyr")["_pay_amt"].sum()
                        paid = cp.groupby(cp["_d"].dt.year)["_pay"].sum()
                        yrs = [y for y in range(TODAY.year - 2, TODAY.year + 1)
                               if y in due.index and y in paid.index and paid[y] != 0]
                        if len(yrs) >= 2:
                            due_sum = sum(due[y] for y in yrs)
                            paid_sum = sum(paid[y] for y in yrs)
                            dev_p = abs(due_sum - paid_sum) / paid_sum * 100
                            if dev_p > 10:
                                add("分红一致性·应付 vs 支付", "⚠️",
                                    f"近3年应付股利 {due_sum/1e8:.2f}亿 vs 支付现金 {paid_sum/1e8:.2f}亿"
                                    f"（偏差 {dev_p:.0f}%，>10% 需标注口径：中期+末期合并/含偿付利息）")
                            else:
                                add("分红一致性·应付 vs 支付", "✅",
                                    f"近3年应付股利 {due_sum/1e8:.2f}亿 vs 支付现金 {paid_sum/1e8:.2f}亿"
                                    f"（偏差 {dev_p:.0f}%）")
            except ValueError as exc:
                add("分红·检查", "⚠️", f"缺少关键列: {exc}")
            except Exception as exc:
                add("分红·检查", "⚠️", f"无法计算: {exc}")

    # ── OCF 季节性集中度：近3年 Q4 单季占比 ──
    if cf is not None:
        ocf_col = find_col(cf, "NETCASH_OPERATE") or find_col(cf, "经营活动产生的现金流量净额")
        dcol = find_col(cf, "REPORT", "DATE") or find_col(cf, "报告期")
        if ocf_col and dcol:
            try:
                c = cf[[dcol, ocf_col]].copy()
                c["_d"] = pd.to_datetime(c[dcol], errors="coerce")
                c["_v"] = pd.to_numeric(c[ocf_col], errors="coerce")
                c = c.dropna(subset=["_d", "_v"])
                ann = c[c["_d"].dt.month == 12]
                q3 = c[c["_d"].dt.month == 9]
                ratios = []
                for yr in range(TODAY.year - 2, TODAY.year + 1):
                    a = ann[ann["_d"].dt.year == yr]["_v"]
                    q = q3[q3["_d"].dt.year == yr]["_v"]
                    if len(a) and len(q) and a.iloc[0] != 0:
                        r = (a.iloc[0] - q.iloc[0]) / abs(a.iloc[0]) * 100
                        ratios.append(f"{yr}:{r:.0f}%")
                if ratios:
                    nums = [float(x.split(":")[1].rstrip("%")) for x in ratios]
                    txt = f"Q4单季占比 {', '.join(ratios)}"
                    if max(nums) > 80:
                        txt += "（季节性集中）"
                        if min(nums) > 80:
                            txt += "——连续常态集中（Q4旺季/年底回款），注明原因不视作异常"
                        else:
                            txt += "——单年突升需调查"
                        add("OCF·Q4 季节性集中度", "⚠️", txt)
                    else:
                        add("OCF·Q4 季节性集中度", "✅", txt)
            except Exception as exc:
                add("OCF·Q4 季节性集中度", "⚠️", f"无法计算: {exc}")

    return checks, status


def write_audit_report(data_dir: Path, checks: list[dict], status: str) -> Path:
    # HTML is the human-facing report; JSON is the stable machine-facing audit contract.
    (data_dir / "审计报告.json").write_text(
        json.dumps({"audit_date": TODAY.strftime("%Y-%m-%d %H:%M"),
                    "status": status, "checks": checks}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    rows = "".join(
        f"<tr><td>{c['name']}</td><td>{c['level']}</td><td>{c['detail']}</td></tr>"
        for c in checks)
    summary = {"pass": "✅ 全部通过", "warn": "⚠️ 有警告（继续，结论标注局限）",
               "fail": "❌ 有错误（降级为初筛或人工补数）"}[status]
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>数据审计报告</title><style>
body{{font-family:"Microsoft YaHei",sans-serif;max-width:900px;margin:24px auto;padding:0 20px;color:#1a1a1a}}
h1{{font-size:20px}} .gate{{font-size:14px;padding:10px 14px;border-left:3px solid #2980b9;background:#f5f8fb}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:14px}}
th,td{{border-bottom:1px solid #eee;padding:7px 10px;text-align:left}}
th{{color:#888;font-weight:500;font-size:12px}}
</style></head><body>
<h1>数据审计报告 — {data_dir.parent.name}</h1>
<div class="gate">审计时间：{TODAY:%Y-%m-%d %H:%M} ｜ 门控结果：<b>{summary}</b></div>
<table><thead><tr><th>检查项</th><th>结果</th><th>说明</th></tr></thead>
<tbody>{rows}</tbody></table>
</body></html>"""
    path = data_dir / "审计报告.html"
    path.write_text(html, encoding="utf-8")
    return path


def _skill_scripts_dir() -> Path:
    """company-research skill 的 scripts/ 目录（本文件所在目录）。"""
    return Path(__file__).resolve().parent


def _guigui_scripts_dir() -> Path | None:
    """龟龟脚本目录。三技能合并后 calc_penetration_return.py 与本文件同目录（本仓库 scripts/），
    优先返回本目录；另保留外部独立安装探测（~/.codex/skills/guigui-valuation-report/scripts）作为向后兼容。"""
    local = _skill_scripts_dir()
    if (local / "calc_penetration_return.py").exists():
        return local
    candidates: list[Path] = []
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    candidates.append(codex_home / "skills" / "guigui-valuation-report" / "scripts")
    candidates.append(Path.home() / ".codex" / "skills" / "guigui-valuation-report" / "scripts")
    env_dir = os.environ.get("GUIGUI_SKILL_DIR")
    if env_dir:
        candidates.insert(0, Path(env_dir))
    for c in candidates:
        if (c / "calc_penetration_return.py").exists():
            return c
    return None


TEMPLATE_SCRIPTS = [
    "chart_periods.py", "chart_period_qc.py", "financial_history_charts.py", "chart_numbers.py",
    "verification.py", "extract_financials.py", "analyze_charts.py", "chart_qc.py",
    "format_qc.py", "gate_all.py", "run_support.py", "bounded_fetch.py", "fetch_sources.py", "fetch_peers_financials.py", "fetch_supplement.py",
    "fetch_industry_cost_price.py", "probe_sources.py", "fetch_with_fallback.py",
    "calc_penetration_return.py", "build_penetration_input.py", "sotp_valuation.py",
    "financial_health_core.py", "financial_health_check.py", "financial_health_qc.py",
    "report_template_qc.py", "md_to_html.py",
    "research_topics.py", "research_topic_qc.py", "research_models.py", "capital_metrics.py",
    "valuation_math.py", "valuation_engine.py", "valuation_snapshot.py", "config.py", "format_utils.py",
]
GUIGUI_ONLY = {"calc_penetration_return.py", "build_penetration_input.py"}


def copy_template_scripts(batch_dir: Path) -> dict:
    """B1 自动复制复验/图表/审计模板脚本到批次 scripts/（交付清单据此如实标记）。

    来源：本 skill scripts/（三技能合并后 calc_penetration_return.py 等同目录）。
    返回 {文件名: "✅ 已复制" | "⚠️ 缺失（原因）"}；同时写 scripts/复制清单.json。
    修复 2026-08-21：此前仅 mkdir scripts/ 但未实际复制，交付清单却标注"已复制"。
    """
    src_cr = _skill_scripts_dir()
    src_gg = _guigui_scripts_dir()
    dst = batch_dir / "scripts"
    dst.mkdir(parents=True, exist_ok=True)
    status: dict[str, str] = {}
    copied: dict[str, dict[str, str]] = {}
    for fname in TEMPLATE_SCRIPTS:
        src = None
        cand = src_cr / fname
        if cand.exists():
            src = cand
        elif fname in GUIGUI_ONLY and src_gg is not None:
            cand = src_gg / fname
            if cand.exists():
                src = cand
        if src is None:
            status[fname] = "⚠️ 缺失（源文件不在 skill 目录）"
            continue
        try:
            if not (dst / fname).exists() or (dst / fname).read_bytes() != src.read_bytes():
                shutil.copy2(src, dst / fname)
            status[fname] = "✅ 已复制"
            copied[fname] = {
                "source": str(src.resolve()),
                "sha256": hashlib.sha256((dst / fname).read_bytes()).hexdigest(),
            }
        except Exception as exc:
            status[fname] = f"⚠️ 复制失败（{exc}）"
    try:
        manifest_path = dst / "复制清单.json"
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8-sig")) if manifest_path.exists() else {}
            if not isinstance(previous, dict):
                previous = {}
        except (OSError, ValueError):
            previous = {}
        if previous.get("files") != copied or previous.get("status") != status:
            atomic_json(manifest_path, {"copied_at": datetime.now().astimezone().isoformat(), "status": status, "files": copied})
    except Exception as exc:
        print(f"[立项] 写复制清单失败: {exc}")
    ok = sum(1 for v in status.values() if v.startswith("✅"))
    miss = [k for k, v in status.items() if not v.startswith("✅")]
    print(f"[立项] 模板脚本复制 {ok}/{len(TEMPLATE_SCRIPTS)} 个 -> {dst}"
          + (f"；缺失: {', '.join(miss)}" if miss else ""))
    return status


def run_financial_health(batch_dir: Path, timeout=300) -> tuple[int, dict]:
    """B3.5: generate the deterministic current-period financial health evidence."""
    try:
        script = _skill_scripts_dir() / "financial_health_check.py"
        outcome = run_process([sys.executable, "-u", str(script), "--dir", str(batch_dir)],
                              cwd=batch_dir, timeout=timeout, heartbeat=10, label="B3.5财报体检")
        if outcome["status"] != "PASS":
            return 1, {"status": "fail", "execution": outcome, "error": "本轮财报体检未完成；旧产物不计成功"}
        json_path = batch_dir / "reports" / "本期财报体检.json"
        md_path = batch_dir / "reports" / "本期财报体检_证据摘要.md"
        data = json.loads(json_path.read_text(encoding="utf-8-sig"))
        delivery_path = batch_dir / "交付清单.md"
        if delivery_path.exists():
            delivery_text = delivery_path.read_text(encoding="utf-8")
            delivery_text = delivery_text.replace(
                "| 5.5 | reports/本期财报体检.json + _证据摘要.md + _成文框架.md + 图表/体检_01~05 | B3.5 关键问题财报体检证据与成文素材，JSON 为唯一事实来源 | ⬜ B3 后自动生成 |",
                "| 5.5 | reports/本期财报体检.json + _证据摘要.md + _成文框架.md + 图表/体检_01~05 | B3.5 关键问题财报体检证据与成文素材，JSON 为唯一事实来源 | ✅ 已生成 |",
            ).replace(
                "| 12 | reports/本期财报体检.json + _证据摘要.md + _成文框架.md + 图表/体检_01~05 | B3.5 关键问题财报体检证据包和固定成文素材 | ⬜ B3 后自动生成 |",
                "| 12 | reports/本期财报体检.json + _证据摘要.md + _成文框架.md + 图表/体检_01~05 | B3.5 关键问题财报体检证据包和固定成文素材 | ✅ 已生成 |",
            )
            delivery_path.write_text(delivery_text, encoding="utf-8")
        print(f"[B3.5 财报体检] 状态: {data.get('status')} ｜ JSON: {json_path.name} ｜ 摘要: {md_path.name} ｜ 成文框架/图表已生成")
        return (0 if data.get("status") != "fail" else 1), data
    except Exception as exc:
        print(f"[B3.5 财报体检] FAIL: {exc}")
        return 1, {"status": "fail", "error": str(exc)}


def scaffold(project_dir: Path, symbol: str, code: str, name: str, status: str) -> Path:
    """B1 立项（v3 时间批次架构）：根目录 财报更新验证.md + 批次文件夹 <YYYY_MM_DD>/
    批次文件夹名 = 本次分析的实际日期（TODAY 当天）；旧批次只读保留。
    返回批次文件夹路径（data/input/scripts/reports 均在批次内）。
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    batch_dir = project_dir / TODAY.strftime("%Y_%m_%d")
    (batch_dir / "data").mkdir(parents=True, exist_ok=True)
    (batch_dir / "reports" / "图表").mkdir(parents=True, exist_ok=True)
    (batch_dir / "input").mkdir(exist_ok=True)
    (batch_dir / "scripts").mkdir(exist_ok=True)
    exemption_path = batch_dir / "input" / "图表豁免.json"
    if not exemption_path.exists():
        exemption_path.write_text('{"豁免": []}\n', encoding="utf-8")
    judgment_path = batch_dir / "input" / "判断记录.md"
    if not judgment_path.exists():
        judgment_path.write_text(
            """# 人工判断记录

本文件只记录框架规定的人工判断，不新增脚本或改变主报告结构。

| 判断点 | 选择/结论 | 证据与来源日期 | 对模型/评级影响 | 复核条件 |
|:-------|:----------|:---------------|:----------------|:---------|
| 证券身份 | 待填 | 待填 | 待填 | 代码/名称冲突时停止 |
| 行业适用性（成本价格/存货/特殊行业） | 待填 | 待填 | 待填 | 新财报或行业数据更新 |
| 分部与单位经济学口径 | 待填 | 待填 | 待填 | 年报附注取得 |
| 预测假设与三情景概率 | 待填 | 待填 | 待填 | 季报偏差超过15% |
| 龟龟 M/AA/G/k/Rf 口径 | 待填 | 待填 | 待填 | 脚本重算或新分红 |
| SOTP 是否触发 | 待填 | 待填 | 待填 | 分部/上市子公司变化 |
| 最终双轨评级与仓位 | 待填 | 待填 | 待填 | R_eff 与 II 或翻转点变化 |
""",
            encoding="utf-8")
    try:
        from financial_health_core import write_default_config

        write_default_config(batch_dir / "input" / "本期财报体检配置.json")
    except Exception as exc:
        print(f"[立项] 创建财报体检配置失败: {exc}")

    # B1 自动复制模板脚本（真实复制；交付清单据此如实标记，修复 2026-08-21 假"已复制"）
    _script_status = copy_template_scripts(batch_dir)
    st_verify = _script_status.get("verification.py", "⚠️ 缺失")
    st_pen = _script_status.get("calc_penetration_return.py", "⚠️ 缺失")
    _n_ok = sum(1 for v in _script_status.values() if v.startswith("✅"))
    st_tpl = f"✅ 已复制 {_n_ok}/{len(_script_status)} 个" if _script_status else "⚠️ 缺失"


    # 根目录 财报更新验证.md（跨批次汇总；已存在则跳过）
    verify_md = project_dir / "财报更新验证.md"
    if not verify_md.exists():
        verify_md.write_text(
            f"""# 财报更新验证 — {name}（{symbol}）

> 用途：跨财报期结论验证与 skill 迭代依据。新财报后重新分析时：
> 1) 根目录新建 `<YYYY_MM_DD>/` 批次文件夹（文件夹名=本次分析的实际日期；完整分析见批次内 README / 报告 / 台账）；
> 2) 本文件追加一行，只记四要素：当前股价 / 12M 预期三情景 / 本次财报要点 / 评级；
> 3) 目标价 12M 到期或下期财报时，核对实际股价与评级有效性，更新“验证”列。
> 模板与批次规则：company-research skill `references/project-structure-v3.md`

| 批次（分析日期） | 对应财报期 | 当前股价（A/H） | 12M 悲观 | 12M 基准 | 12M 乐观 | 评级 | 本次财报要点 | 验证 |
|:--|:--|--:|--:|--:|--:|:--|:--|:--|
""",
            encoding="utf-8")
        print(f"[立项] 根目录汇总已创建: {verify_md}")

    readme = f"""# {name}（{symbol}）— 证券分析研究报告（批次 {TODAY:%Y_%m_%d}）

> 状态：{status} ｜ 框架：company-research 技能 `references/framework.md`（v3 时间批次架构）

## 文件架构（标准，禁止改变）

```
{symbol} {name}/
├── 财报更新验证.md   # ★ 跨批次汇总（根目录，每次分析一行；本批次完成后追加）
├── <YYYY_MM_DD>/     # 本批次（文件夹名=本次分析的实际日期，本批次 {TODAY:%Y_%m_%d}）
│   ├── README.md     # 本文件：总览 + 交付状态
│   ├── ROADMAP.md    # B3.5-B6 分析路线图
│   ├── 交付清单.md    # ★ 交付物清单（B6 交付前逐项核对）
        │   ├── data/         # 原始数据：拉取清单.json / 审计报告.html+json / *.csv
│   ├── input/        # 模型输入：穿透回报率_输入.json / 本期财报体检配置.json（行业与关键问题口径）
│   ├── scripts/      # 复验、图表、B3.5 体检和门控脚本
│   └── reports/      # 主报告 / 体检 JSON+摘要 / 图表/ / 估值输出 / 跟踪台账
└── <YYYY_MM_DD>/     # 下一批次（新财报后重新分析，旧批次只读保留）
```

## 进度

| 步骤 | 内容 | 状态 |
|------|------|------|
| 0 | 数据拉取与审计 | ✅ 自动完成（见批次内 data/审计报告.html） |
| 0.5 | 本期财报体检（B3.5） | ✅ 自动生成（见 reports/本期财报体检 JSON、证据摘要、成文框架与五张固定图） |
| 1 | 宏观经济评述 | ⬜ 待分析 |
| 2 | 行业分析 | ⬜ 待分析 |
| 3 | 公司分析 | ⬜ 待分析 |
| 4 | 财务分析 | ⬜ 待分析 |
| 5 | 财务预测 | ⬜ 待分析 |
| 6 | 估值 | ⬜ 待分析 |
| 7 | 投资建议 | ⬜ 待分析 |
| 8 | 综合研究报告 | ⬜ 待分析 |

## 交付清单

- 每次交付必须按批次内 `交付清单.md` 逐项核对后输出，缺失项须说明原因；
- 分析完成后在根目录 `财报更新验证.md` 追加一行（当前股价 / 12M 三情景 / 财报要点 / 评级）。
"""
    if not (batch_dir / "README.md").exists():
        (batch_dir / "README.md").write_text(readme, encoding="utf-8")

    roadmap = """# 分析路线图

按 company-research 技能 `references/framework.md` B3.5-B6 执行：

0.5. 本期财报体检（关键问题证据包） → 1. 宏观 → 2. 行业 → 3. 公司 → 4. 财务（含 §4.3） → 5. 预测 → 6. 估值 → 7. 建议 → 8. 报告

每个核心论点 ≥ L4 证据；成稿前过 E 节质量审计清单。
"""
    if not (batch_dir / "ROADMAP.md").exists():
        (batch_dir / "ROADMAP.md").write_text(roadmap, encoding="utf-8")

    # 交付清单（B1 建骨架，B4-B6 逐步填写，B6 交付前逐项核对）
    delivery = f"""# 交付清单 — {name}（{symbol}）｜ 批次 {TODAY:%Y_%m_%d}

> 生成：{TODAY:%Y-%m-%d}（research_pipeline.py B1 自动创建，v3 时间批次架构）
> 规则：每次交付必须按本清单逐项核对；B4-B6 完成前，第二、三节不得勾选。
> 位置：本清单与 data/input/scripts/reports 均在批次文件夹 `{TODAY:%Y_%m_%d}/` 内；根目录 `财报更新验证.md` 为跨批次汇总。

## 一、B1-B3.5 自动生成（数据层，由 research_pipeline.py 完成）

| # | 交付物 | 说明 | 状态 |
|---|--------|------|------|
| 1 | README.md | 批次总览：公司/代码/评级/目标价/核心逻辑/风险 | ✅ 骨架已建 |
| 2 | ROADMAP.md | B4-B6 八步路线图 | ✅ 骨架已建 |
| 3 | 根目录 财报更新验证.md | 跨批次汇总表头（B1 创建；本批次完成时追加一行） | ✅ 表头已建 |
| 4 | data/拉取清单.json | B2 各接口拉取记录（成功/失败/行数） | ✅ 已生成 |
| 5 | data/审计报告.html + 审计报告.json | B3 人读审计报告与机器审计契约 | ✅ 已生成 |
| 5.5 | reports/本期财报体检.json + _证据摘要.md + _成文框架.md + 图表/体检_01~05 | B3.5 关键问题财报体检证据与成文素材，JSON 为唯一事实来源 | ⬜ B3 后自动生成 |
| 6 | data/*.csv | 三表/财务指标/日线/分红/概况原始数据 | ⬜ 逐项核对 |
| 7 | scripts/verification.py | 复验助手（自动复制） | {st_verify} |
| 8 | scripts/calc_penetration_return.py | 穿透回报率计算器（guigui，自动复制） | {st_pen} |
| 10 | scripts/ 模板脚本集 | analyze_charts/chart_qc/format_qc/extract_financials/fetch_peers/fetch_supplement/probe_sources/fetch_with_fallback/build_penetration_input/md_to_html/gate_all 等（自动复制） | {st_tpl} |
| 11 | input/本期财报体检配置.json | B3.5 规则、阈值和数据源配置 | ✅ 已生成 |
| 9 | 行业成本—价格数据（行业适用） | data/行业成本价格.csv + 行业成本价格_审计.json + input/行业成本价格配置.json（B2.2，fetch_industry_cost_price.py --profile dairy 生成；乳制品等成本驱动行业必做） | ⬜ 行业不适用时填"不适用" |

## 二、B4-B6 分析交付（Agent 负责，缺一不可）

| # | 交付物 | 说明 | 状态 |
|---|--------|------|------|
| 1 | 主报告 MD | reports/{name}_{code}_分析报告.md（references/report-template.md v3 固定十部分） | ⬜ |
| 2 | 主报告 HTML | reports/{name}_{code}_分析报告.html（由 scripts/md_to_html.py 从 MD 生成） | ⬜ |
| 3 | 交互图表 HTML | reports/{name}_{code}_图表.html | ⬜ |
| 4 | 图表 PNG | reports/图表/图NN_*.png（≥10 张） | ⬜ |
| 5 | 穿透回报率输入 | input/穿透回报率_输入.json | ⬜ |
| 6 | 穿透回报率输出 | reports/穿透回报率_输出.json | ⬜ |
| 7 | 跟踪验证台账 | reports/跟踪验证台账.md | ⬜ |
| 8 | README 更新 | 评级/目标价/核心逻辑/风险/交付状态 | ⬜ |
| 9 | 财报更新验证.md 追加 | 根目录汇总追加本批次一行（股价/12M三情景/财报要点/评级） | ⬜ |
| 10 | SOTP 触发检测（平台型） | input/sotp_触发.json（sotp_valuation.py --detect-only；非平台型填"不适用"） | ⬜ |
| 11 | SOTP 输入/输出（平台型触发时） | input/sotp_输入.json + reports/sotp_输出.json + 图18 分部估值SOTP | ⬜ 非平台型跳过 |

## 三、成稿门控（交付前逐项确认）

- [ ] E 节《成稿前质量审计清单》全部通过（framework.md）
- [ ] 穿透回报率脚本已运行，输出与报告数字一致（G7）
- [ ] B3.5 本期财报体检：关键问题 JSON、证据摘要、成文框架和五张固定图已生成；§4.3 已引用 JSON 并嵌图，现金流/利润/适用专项结论及 WARN/indeterminate 已用人类可读方式披露（G22）
- [ ] 图表 ≥10 张，每张有编号/标题/数据日期/来源（analyze_charts --data-date 自动标注），正文有解读
- [ ] 图表质量门（G8）：`python scripts/chart_qc.py --dir . --report reports/<报告>.md` 已运行且无 FAIL；WARN 项已在本清单说明
- [ ] 报告模板门：`python scripts/report_template_qc.py --report reports/<报告>.md` 已运行且无 FAIL；十部分、固定财务子节、每节结论和数据依据齐全
- [ ] 行业成本—价格门控（G8-INDUSTRY，行业适用）：data/行业成本价格.csv 审计通过、cost+price 双序列、≥2 独立来源，图16 已嵌入 §2 宏观与行业并解读传导；行业不适用已说明
- [ ] SOTP 门（平台型触发时）：sotp_valuation.py 已运行，reports/sotp_输出.json 存在，图18 已嵌入 §6 并引用结论；非平台型已说明跳过
- [ ] 格式质量门（G9）：`python scripts/format_qc.py --dir . --report reports/<报告>.md` 已运行且无 FAIL（F1-F11：`---##` 同行粘连/分隔线缺空行/setext 歧义/表格列数/图片引用/连续空行/行尾空白/标记闭合/换行符/BOM）；WARN 项已在本清单说明
- [ ] 图表规范：嵌入行格式 `![图NN 标题](图表/图NN_*.png)`（alt 含标题、每图只嵌入一次）；PNG 完整且 ≥800x400；交互图表 HTML 面板 ≥1
- [ ] 跟踪验证台账已填基线值与复验时点
- [ ] 根目录 财报更新验证.md 已追加本批次一行（紧贴表格分隔行，禁止空行，否则表格断裂）
- [ ] 对话交付时按本清单输出（含缺失项说明）
"""
    if not (batch_dir / "交付清单.md").exists():
        (batch_dir / "交付清单.md").write_text(delivery, encoding="utf-8")
    print(f"[立项] 批次已创建: {batch_dir}")
    return batch_dir

def main() -> int:
    parser = argparse.ArgumentParser(description="自动化证券调研流水线")
    parser.add_argument("prompt", nargs="?", help='例如 "调研 温氏股份" / "调研 300498"')
    parser.add_argument("--company", help="公司名")
    parser.add_argument("--code", help="6 位股票代码")
    parser.add_argument("--data-dir", help="对已有数据目录只做审计（跳过拉取）")
    parser.add_argument("--audit-only", action="store_true", help="配合 --data-dir 使用")
    parser.add_argument("--root", help="项目创建根目录（默认当前工作目录）")
    parser.add_argument("--sync-scripts", help="只将当前技能脚本同步到指定批次，不拉数、不重置文档")
    parser.add_argument("--total-timeout", type=float, default=1200, help="B1-B3全流程硬超时秒数")
    parser.add_argument("--stage-timeout", type=float, default=300, help="财报体检/期间证据阶段硬超时")
    parser.add_argument("--_pipeline-worker", action="store_true", help=argparse.SUPPRESS)
    add_fetch_options(parser)
    args = parser.parse_args()
    if args.sync_scripts:
        statuses = copy_template_scripts(Path(args.sync_scripts).resolve())
        return int(any(not s.startswith("✅") for s in statuses.values()))

    # B1 解析
    company, code = args.company, args.code
    if args.prompt:
        parsed_company, parsed_code = parse_prompt(args.prompt)
        company, code = company or parsed_company, code or parsed_code
    if code and code.upper().endswith(".HK"):
        code = code[:-3].zfill(5)

    if args.data_dir and args.audit_only:
        data_dir = Path(args.data_dir)
        checks, status = audit_data(data_dir)
        report = write_audit_report(data_dir, checks, status)
        print(f"\n[审计] 门控: {status} ｜ 报告: {report}")
        health_exit, health_data = run_financial_health(data_dir.parent, args.stage_timeout)
        period_result = run_process([sys.executable, "-u", str(_skill_scripts_dir()/"chart_periods.py"), "--dir", str(data_dir.parent)],
                                    timeout=args.stage_timeout, heartbeat=10, label="B3.6期间证据")
        if health_data.get("status") == "fail":
            print("[B3.5 财报体检] 门控失败：请补齐三表或可比期间后重跑。")
        return 1 if status == "fail" or health_exit or period_result["status"] != "PASS" else 0

    if not code and company:
        print(f"[解析] 用名称解析代码: {company}")
        code = resolve_code(company)
    if code and not company:
        print(f"[解析] 用代码解析名称: {code}")
        company = resolve_name(code)
    if not code:
        print("❌ 无法确定股票代码。请提供代码，如：调研 300498")
        return 1
    if not company:
        print("❌ 无法确定公司名称。文件夹命名必须为 代码+名称（如 SZ.300498 温氏股份），请补充名称后重试。")
        return 1
    if company == code:
        print("❌ 公司名称缺失（名称=代码）。文件夹命名必须为 代码+名称，请补充公司名称后重试。")
        return 1
    market = infer_market(code)
    symbol = f"{market}.{code}"

    # 立项
    root = Path(args.root) if args.root else RESEARCH_ROOT
    project_dir = root / f"{symbol} {company}"
    print(f"[立项] {symbol} {company} -> {project_dir}")
    batch_dir = scaffold(project_dir, symbol, code, company, "数据就绪/待分析")

    # B2: same bounded source adapter as the standalone fetch command.
    manifest = fetch_datasets(code, market, batch_dir / "data", timeout=args.timeout,
                              retries=args.retries, failure_ttl=args.failure_ttl, force=args.force_refresh,
                              total_budget=args.fetch_budget, success_ttl=args.success_ttl)

    # B3 审计
    checks, status = audit_data(batch_dir / "data")
    if manifest["status"] != "PASS":
        checks.append({"name":"本轮拉取缺失", "level":"⚠️", "detail":"见拉取清单；保留旧文件不等于本轮更新成功"})
        if status == "pass":
            status = "warn"
    report = write_audit_report(batch_dir / "data", checks, status)
    print(f"\n[审计] 门控: {status} ｜ 报告: {report}")

    # B3.5 本期财报体检证据层：无论 B3 是否有 WARN，都必须生成；硬失败阻断后续交付。
    health_exit, health_data = run_financial_health(batch_dir, args.stage_timeout)

    # Build latest-period chart evidence before B4. Never rely on FY-only ops inputs.
    period_result = run_process([sys.executable, "-u", str(_skill_scripts_dir()/"chart_periods.py"), "--dir", str(batch_dir)],
                                timeout=args.stage_timeout, heartbeat=10, label="B3.6期间证据")

    # 交接给 Agent
    print("\n" + "=" * 60)
    print("下一步（Agent 按 references/framework.md 继续）：")
    print("  B3.5 本期财报体检：阅读关键问题 JSON/证据摘要，优先复制 reports/本期财报体检_成文框架.md 写入 §4.3")
    print("  B4 八步分析：宏观→行业→公司→财务→预测→估值→建议→报告")
    print("  B5 交叉验证：同行对标≥5家、敏感性翻转点、尾部情景")
    print("  B6 结论：评级 + 12个月目标价 + 推导链 + 成稿审计清单")
    print(f"  交付：成稿前按 交付清单.md 逐项核对，对话中按清单输出（{batch_dir / '交付清单.md'}）")
    if status != "pass":
        print(f"\n⚠️ 审计门控为 {status}，分析时必须标注数据局限。")
    print("=" * 60)
    return 0 if status != "fail" and health_exit == 0 and period_result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
