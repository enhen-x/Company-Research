#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""穿透回报率输入 JSON 生成器（skill 通用资产，水星家纺分析实战沉淀）
用途：把"人工从 CSV 手填输入 JSON"改为"机器自动算 + 判断点标注"，消除手算错误与无痕迹判断。

用法：
    python build_penetration_input.py --data <项目>/data --out <项目>/input \
        --company 水星家纺 --code 603365 [--rf 0.017] [--price 17.85]
输出：
    <out>/穿透回报率_输入.json     （与 calc_penetration_return.py --config 完全兼容，单位：百万元）
    <out>/输入_判断点说明.md       （每个字段：值/来源/口径/机器算 or 人判断，判断点给建议+依据）

机器字段（从三表 CSV 自动计算，零手算）：
    C=归母净利(年报)  D=折旧摊销（优先总额，否则明细加总；油气折耗不重复）
    G建议=近3年Capex/D&A比值  M法2=DPS×股本/归母净利（近3年均值；注意：分配股利现金列 ASSIGN_DIVIDEND_PORFIT
    含偿付利息及归属差异，不能直接当普通股分红，禁用作法2）  法1=DPS/EPS 并列对比
    surplus=OCF-D×G建议  AA_2y=近2年均值  AA_all=近5年均值  revenue_series 同口径
    cash_balance=货币资金（未扣债）；net_debt=有息负债−货币资金
    interest_bearing_debt(短借+长借+应付债+短融，默认不含租赁)
    shares=股本(百万股)  market_cap=price×shares(百万元)  ebitda=税前利润+费用化利息+D  fcf=OCF-Capex
    goodwill/total_assets/dps(最新财年含中期)/working_capital/book_equity（扣其他权益工具）
    cash_protection/low_10y_close 默认null，须经证据核实后启用；三表共同最近5个完整财年

人判断点（脚本自动标注"需确认"，附建议值、依据、易错点）：
    G 是否采纳建议（建议值可能因扩产期 Capex 暴增而失真，需结合资本开支阶段判断）
    M 法1 vs 法2（偏差>5pct 排除法1）  AA 用 2y 还是 all
    现金/债务范围及其他权益工具（缺失不可判定）
    rf 取值日期（默认需人工核对当日10年期国债）  cycle_adjust（弱周期=0）  λ 可信度

λ 异常年诊断（复现水星家纺 2022 年教训）：对 surplus 序列逐段检测
    Δ结余/Δ收入 比值的符号一致性 + 单段主导度；任一异常 -> 自动降级为"保守参考"。
"""
import math
import argparse
import json
from valuation_math import canonical_ebitda
from calc_penetration_return import diagnose_lambda, infer_industry_archetype, _MAINT_GAMMA_CAP
import sys
from pathlib import Path

import pandas as pd

UNIT = 1e6  # 东财 CSV 金额单位: 元 -> 百万元


def annual_rows(df: pd.DataFrame) -> pd.DataFrame:
    """取年报行，按 REPORT_DATE 升序去重"""
    df = df.copy()
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"])
    df = df[df["REPORT_DATE"].dt.month == 12].sort_values("REPORT_DATE")
    return df[~df["REPORT_DATE"].duplicated(keep="last")]


def close_col(df) -> str:
    """日线收盘价列：兼容东财中文列名（收盘）与腾讯/新浪英文列名（close）"""
    for cand in ("收盘", "close"):
        if cand in df.columns:
            return cand
    raise KeyError(f"日线 CSV 缺少收盘价列，现有列: {list(df.columns)}")

def shares_from_profile(data_dir: Path) -> tuple[float | None, float | None]:
    """从 公司概况.csv（腾讯 item/value 行）读取 总股本(百万股)/总市值(百万元)。
    2026-08-23 中远海控批次校准：资产负债表 SHARE_CAPITAL 可能为历史口径（回购注销后未更新），
    导致 price×shares 市值与腾讯实时总市值偏差；概况为当前权威口径，优先采用。"""
    f = data_dir / "公司概况.csv"
    if not f.exists():
        return None, None
    try:
        df = pd.read_csv(f, encoding="utf-8-sig", dtype=str)
        if df.shape[1] < 2:
            return None, None
        vals = dict(zip(df.iloc[:, 0], df.iloc[:, 1]))
        shares = mktcap = None
        for k, v in vals.items():
            k2 = str(k).strip()
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if "总股本" in k2:
                shares = fv / 1e6      # 股 -> 百万股
            elif "总市值" in k2:
                mktcap = fv / 1e6      # 元 -> 百万元
        return (shares if shares and shares > 0 else None,
                mktcap if mktcap and mktcap > 0 else None)
    except Exception:
        return None, None


def val_mm(df: pd.DataFrame, col: str) -> list:
    """Required core amounts; missing observations cannot become zero."""
    if col not in df.columns:
        raise ValueError(f"必需金额字段缺失：{col}")
    values = pd.to_numeric(df[col], errors="coerce")/UNIT
    if values.isna().any() or not all(math.isfinite(v) for v in values):
        raise ValueError(f"必需金额字段不可判定：{col}，禁止填0")
    return values.tolist()


def val_per_share(df: pd.DataFrame, col: str) -> list:
    """每股类列值序列（元/股，**不做单位转换**，如 EPS），缺失填 0"""
    if col not in df.columns:
        return [0.0] * len(df)
    return pd.to_numeric(df[col], errors="coerce").fillna(0).tolist()


def dps_by_fiscal_year(div: pd.DataFrame) -> pd.DataFrame:
    """分红记录 -> 每财年 DPS 合计（元/股）。
    分红记录"现金分红-现金分红比例"列值为"每10股派X元"的 X -> DPS = X/10；
    同财年多个报告期（年报+中期）合并求和（如 2025 年报0.8+中期0.2=1.0）。
    """
    if {"财政年度", "分红方案"}.issubset(div.columns):
        # HK feed cash dividends are per share HKD. Distributions in specie are excluded.
        d = div.copy()
        d["财年"] = pd.to_numeric(d["财政年度"], errors="coerce")
        d["DPS"] = pd.to_numeric(d["分红方案"].astype(str).str.extract(r"每股派港币([\d.]+)元")[0], errors="coerce")
        return d.dropna(subset=["财年", "DPS"]).groupby("财年")["DPS"].sum().sort_index()
    d = div[["报告期", "现金分红-现金分红比例"]].copy()
    d["报告期"] = pd.to_datetime(d["报告期"])
    d["财年"] = d["报告期"].dt.year
    d["DPS"] = pd.to_numeric(d["现金分红-现金分红比例"], errors="coerce") / 10.0
    d = d[d["DPS"] > 0]
    return d.groupby("财年")["DPS"].sum().sort_index()


def amount_at(row, *names):
    for name in names:
        value = pd.to_numeric(row.get(name), errors="coerce")
        if pd.notna(value) and math.isfinite(float(value)):
            return float(value)/UNIT
    return None


def depreciation_amount(row):
    # Aggregate takes precedence over its components. FA_IR_DEPR already includes
    # oil/gas depletion; OILGAS_BIO_DEPR must not be added a second time.
    total = amount_at(row, "DEPR_AMORT", "TOTAL_DEPR_AMORT")
    if total is not None:
        return total
    fa = amount_at(row, "FA_IR_DEPR")
    if fa is None:
        return None
    ia = amount_at(row, "IA_AMORTIZE") or 0.0
    lpe = amount_at(row, "LPE_AMORTIZE") or 0.0
    d = fa + ia + lpe
    useright = amount_at(row, "USERIGHT_ASSET_AMORTIZE")
    if useright is not None:
        d += useright
    return d


def financial_snapshot(balance, income, depreciation):
    warnings = []
    cash = amount_at(balance, "MONETARYFUNDS")
    core_components = [amount_at(balance, name) for name in ("SHORT_LOAN","LONG_LOAN")]
    if all(v is not None for v in core_components):
        bond = amount_at(balance, "BOND_PAYABLE") or 0.0
        short_bond = amount_at(balance, "SHORT_BOND_PAYABLE") or 0.0
        noncurrent_1y = amount_at(balance, "NONCURRENT_LIAB_1YEAR") or 0.0
        debt = sum(core_components) + bond + short_bond + noncurrent_1y
    else:
        debt = None
    warnings.append("有息负债为短借+长借+应付债券+短融+一年内到期非流动负债，租赁及其他融资须人工补核")
    pbt = amount_at(income, "TOTAL_PROFIT")
    interest = amount_at(income, "FE_INTEREST_EXPENSE", "INTEREST_EXPENSE", "FINANCE_EXPENSE")
    ebitda = canonical_ebitda(pbt, interest, depreciation)
    assets = amount_at(balance,"TOTAL_CURRENT_ASSETS")
    liabilities = amount_at(balance,"TOTAL_CURRENT_LIAB")
    working_capital = assets-liabilities if assets is not None and liabilities is not None else None
    equity = amount_at(balance,"TOTAL_PARENT_EQUITY")
    other_equity = amount_at(balance,"OTHER_EQUITY_TOOL")
    ordinary_equity = equity-other_equity if equity is not None and other_equity is not None else None
    result = {"cash_balance":cash, "interest_bearing_debt":debt,
              "net_debt":debt-cash if debt is not None and cash is not None else None,
              "working_capital":working_capital, "cash_protection":None,
              "book_equity":ordinary_equity, "ebitda":ebitda}
    for field, value in result.items():
        if value is None:
            warnings.append(f"{field} 未确认，保留null；不得用缺失值0或营运资本替代")
    result["formula_sources"] = {"ebitda":"TOTAL_PROFIT+FE_INTEREST_EXPENSE+D（费用化利息，不以营业利润替代税前利润）",
                                "cash_balance":"MONETARYFUNDS（未扣债）", "net_debt":"interest_bearing_debt-cash_balance",
                                "working_capital":"TOTAL_CURRENT_ASSETS-TOTAL_CURRENT_LIAB（非现金保护）",
                                "book_equity":"TOTAL_PARENT_EQUITY-OTHER_EQUITY_TOOL（归母普通股）"}
    result["input_warnings"] = warnings
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--company", required=True)
    ap.add_argument("--code", required=True)
    ap.add_argument("--rf", type=float, default=.017)
    ap.add_argument("--price", type=float)
    ap.add_argument("--payout", type=float, help="有证据支持的人工支付率；不提供时取历史最低档")
    ap.add_argument("--quote-fx", type=float, default=1.0, help="每单位交易币种折合财务币种；港股须明确填HKD/CNY，历史支付率仍用已支付现金校准")
    ap.add_argument("--c-fwd", type=float, help="亿元")
    ap.add_argument("--m-fwd", type=float)
    ap.add_argument("--k-fwd", type=float)
    ap.add_argument("--aa-fwd", type=float, help="亿元")
    ap.add_argument("--c-fwd-source", default="")
    ap.add_argument("--archetype", default="", help="行业原型 (bank/non_bank_fin/internet_tech/manufacturing/consumer/utility_infra)")
    ap.add_argument("--buyback", type=float, default=0.0, help="经核实年度注销式回购金额（亿元）")
    ap.add_argument("--overwrite", action="store_true", help="明确允许覆盖已有输入；默认保护人工判断")
    args = ap.parse_args()
    out = Path(args.out)
    if (out/"穿透回报率_输入.json").exists() and not args.overwrite:
        sys.exit("输入已存在，保留人工判断；确需重建时显式加 --overwrite")
    data = Path(args.data)
    pnl, cf, bs = [annual_rows(pd.read_csv(data/name,encoding="utf-8-sig")) for name in
                   ("利润表_按报告期.csv","现金流量表_按报告期.csv","资产负债表_按报告期.csv")]
    if any(frame.empty for frame in (pnl,cf,bs)):
        raise ValueError("三表缺少完整财年")
    latests = [frame["REPORT_DATE"].max() for frame in (pnl,cf,bs)]
    if len(set(latests))!=1:
        raise ValueError("三表最新完整财年不一致，禁止跨期拼接")
    dates = sorted(set(pnl["REPORT_DATE"]) & set(cf["REPORT_DATE"]) & set(bs["REPORT_DATE"]))[-5:]
    if len(dates)<5:
        raise ValueError("三表可比完整财年不足5年")
    pnl,cf,bs = [frame.set_index("REPORT_DATE").loc[dates].reset_index() for frame in (pnl,cf,bs)]
    newest = lambda values: list(reversed(values))
    revenues = newest(val_mm(pnl,"OPERATE_INCOME"))
    profits = newest(val_mm(pnl,"PARENT_NETPROFIT"))
    depreciation = newest([depreciation_amount(row) for _,row in cf.iterrows()])
    if any(value is None for value in depreciation):
        raise ValueError("折旧摊销核心字段缺失，无法生成G/AA；请补齐总额或明细，禁止填0")
    capex = newest(val_mm(cf,"CONSTRUCT_LONG_ASSET"))
    ocf = newest(val_mm(cf,"NETCASH_OPERATE"))
    eps = newest(val_per_share(pnl,"BASIC_EPS" if "BASIC_EPS" in pnl.columns else "EPSJB"))
    g_ratios = [c/d for c,d in zip(capex[:3],depreciation[:3]) if d>0]
    if not g_ratios:
        raise ValueError("Capex/D不可识别，G须人工判断")
    g = round(sum(g_ratios)/len(g_ratios),3)
    surplus = [o-d*g for o,d in zip(ocf,depreciation)]
    shares, profile_cap = shares_from_profile(data)
    shares_source = "公司概况.csv" if shares else "资产负债表SHARE_CAPITAL"
    if shares is None:
        shares = amount_at(bs.iloc[-1],"SHARE_CAPITAL")
    if shares is None or shares<=0:
        shares = profits[0]/eps[0] if eps[0]>0 else None
        shares_source = "C/EPS反推（待核）"
    if shares is None or shares<=0:
        raise ValueError("股本不可判定")
    div = pd.read_csv(data/"分红送配记录.csv",encoding="utf-8-sig")
    dps = dps_by_fiscal_year(div)
    years = [dt.year for dt in reversed(dates)]
    bs_shares = newest([amount_at(row, "SHARE_CAPITAL") for _, row in bs.iterrows()])
    def _row_book_eq(row):
        eq = amount_at(row, "TOTAL_PARENT_EQUITY")
        if eq is None:
            return None
        oe_tool = amount_at(row, "OTHER_EQUITY_TOOL")
        return (eq - oe_tool) if oe_tool is not None else eq
    book_equity_series = newest([_row_book_eq(row) for _, row in bs.iterrows()])
    compatible_dividend = "财政年度" not in div.columns and args.quote_fx == 1.0
    m2 = []
    ma_payout_notes = []
    if compatible_dividend:
        for i, y in enumerate(years[:3]):
            if y in dps.index and profits[i] > 0:
                yr_sh = bs_shares[i] if (i < len(bs_shares) and bs_shares[i] and bs_shares[i] > 0) else shares
                use_sh = yr_sh if abs(yr_sh - shares) / shares > 0.10 else shares
                if use_sh != shares:
                    ma_payout_notes.append(f"{y}年分红支付率按当期股本{use_sh:.2f}百万股配比（防并购扩股虚增历史分红率）")
                m2.append(float(dps.loc[y]) * use_sh / profits[i])
    m1 = [float(dps.loc[y])/eps[i] for i,y in enumerate(years[:3]) if y in dps.index and eps[i]>0] if compatible_dividend else []
    payout = args.payout if args.payout is not None else min(m2) if m2 else None
    if payout is None or not 0<=payout<=1:
        raise ValueError("支付率不可判定或超出0~1；须核查分红与股本后用--payout明确输入")
    daily = pd.read_csv(data/"日线股价.csv",encoding="utf-8-sig")
    date_col = "日期" if "日期" in daily.columns else "date"
    daily[date_col] = pd.to_datetime(daily[date_col],errors="raise")
    daily = daily.sort_values(date_col)
    price = args.price if args.price is not None else float(daily[close_col(daily)].iloc[-1])
    if not math.isfinite(price) or price<=0:
        raise ValueError("现价无效")
    if not math.isfinite(args.quote_fx) or args.quote_fx <= 0:
        raise ValueError("quote-fx 必须是明确、有效的正汇率")
    cap = price*shares*args.quote_fx
    snapshot = financial_snapshot(bs.iloc[-1],pnl.iloc[-1],depreciation[0])
    warnings = snapshot["input_warnings"]
    warnings.extend(["G为总资本开支/折旧代理，不等于已确认的维持性资本开支；扩产期须人工判断",
                     "十年低价未核实复权因子及十年覆盖，默认null，不能仅以正价格启用",
                     "Rf默认或传入值仍须核对估值日；货币资金须补核受限资金"])
    if len(m2)<3:
        warnings.append("历史支付率不足3个可核实财年，最低档仅为部分观察；须核查缺失年度")
    if ma_payout_notes:
        warnings.extend(ma_payout_notes)
    if profile_cap and abs(cap-profile_cap)/profile_cap>.03:
        warnings.append("price×shares与概况市值偏差超过3%，须核对时点及股本")
    segments = [(surplus[i]-surplus[i+1])/(revenues[i]-revenues[i+1]) for i in range(len(surplus)-1) if revenues[i]!=revenues[i+1]]
    signs = {1 if v>0 else -1 for v in segments}
    median = sorted(segments)[len(segments)//2] if segments else None
    reliable = bool(segments) and len(signs)<=1 and all(abs(v)<=1.5 for v in segments)
    if median is not None and abs(median)>1e-6 and any(abs(v)>2*abs(median) for v in segments):
        reliable = False
    lambda_diagnostics = diagnose_lambda({'surplus_series': surplus, 'revenue_series': revenues,
                                          'financial_years': years})
    lam = lambda_diagnostics['raw_mean']
    if lam is None:
        warnings.append("无有效历史λ区间，不启用历史均值参考；旧模式平线不表示经营弹性为0，不输出k*")
    elif not reliable:
        warnings.append("λ历史估计可靠性低，保留原始均值仅作条件敏感性参考；不以0替代估计，不输出精确k*")
    lambda_policy = "historical_mean_reference" if lambda_diagnostics["raw_mean"] is not None else "legacy_zero"
    archetype = args.archetype.strip() if args.archetype.strip() in _MAINT_GAMMA_CAP else infer_industry_archetype({
        "company": args.company, "depreciation_D": depreciation[0], "input_warnings": warnings,
    })
    gamma_cap = _MAINT_GAMMA_CAP[archetype]
    maint_gamma = 0.0 if (archetype in ("bank", "non_bank_fin") or depreciation[0] <= 0) else round(min(g, gamma_cap), 3)
    fe_int = amount_at(pnl.iloc[-1], "FE_INTEREST_EXPENSE") or 0.0
    ocf_latest = ocf[0]
    ocf_after_int = ocf_latest - fe_int
    capex_latest = capex[0]
    book_eq_val = snapshot.get("book_equity")
    nd_val = snapshot.get("net_debt")
    roe_latest = (profits[0] / book_eq_val) if (book_eq_val is not None and book_eq_val > 0) else None
    if archetype in ("bank", "non_bank_fin"):
        roic_est = roe_latest
    elif book_eq_val is not None and book_eq_val > 0:
        ic_est = max(book_eq_val * 0.25, book_eq_val + (nd_val if nd_val is not None else 0.0))
        roic_est = profits[0] / ic_est
    else:
        roic_est = None
    buyback_mm = max(0.0, args.buyback * 100.0)  # 亿元 → 百万元

    cfg = {"schema_version":3,"model_mode":"v3_look_through","industry_archetype":archetype,
           "company":args.company,"code":args.code,"date":str(daily[date_col].max().date()),
           "price":price,"market_cap":cap,"shares":shares,"quote_fx":args.quote_fx,"net_profit_C":profits[0],"depreciation_D":depreciation[0],
           "capex_ratio_G":g,"total_capex_ratio_G":g,"maint_capex_ratio_gamma":maint_gamma,"gamma_maint":maint_gamma,
           "profit_discount_k":.8,"payout_M":payout,"payout_M_min":min(m2) if m2 else None,
           "payout_M_mean":sum(m2)/len(m2) if m2 else None,"buyback_amount":buyback_mm,
           "aa_2y":sum(surplus[:2])/2,"aa_all":sum(surplus)/len(surplus),
           "ocf_latest":ocf_latest,"capex_latest":capex_latest,"fe_interest_expense":fe_int,"ocf_after_interest":ocf_after_int,
           "roe_latest":roe_latest,"roic_est":roic_est,
           "rf":args.rf,"cycle_adjust_pct":0,"base_revenue":revenues[0],"lambda":lam,"surplus_series":surplus,
           "lambda_policy":lambda_policy,"lambda_reliable":reliable,
           "lambda_diagnostics":lambda_diagnostics,"financial_years":years,
           "revenue_series":revenues,"net_profit_series":profits,"book_equity_series":book_equity_series,"shares_series":bs_shares,
           "fcf":ocf[0]-capex[0],"goodwill":amount_at(bs.iloc[-1],"GOODWILL"),
           "total_assets":amount_at(bs.iloc[-1],"TOTAL_ASSETS"),"dps":float(dps.loc[years[0]]) if years[0] in dps.index else None,
           "low_10y_close":None,"low_10y_close_verified":False,"financial_period":str(dates[-1].date()),**snapshot}
    if args.c_fwd is not None:
        cfg.update(net_profit_C_fwd=args.c_fwd*100,c_fwd_source=args.c_fwd_source,c_fwd_verified=False)
        for key,value in (("payout_M_fwd",args.m_fwd),("profit_discount_k_fwd",args.k_fwd),("aa_fwd",args.aa_fwd*100 if args.aa_fwd is not None else None)):
            if value is not None:
                cfg[key]=value
    roic_pct_txt = f"{roic_est*100:.2f}%" if roic_est is not None else "未知"
    roe_pct_txt = f"{roe_latest*100:.2f}%" if roe_latest is not None else "未知"
    notes = [f"# 穿透回报率法 v3（Look-Through Return Method）输入与口径说明（{args.company} {args.code}）", "",
             f"财务期：{cfg['financial_period']}；行情日：{cfg['date']}；股本来源：{shares_source}；行业原型：{archetype}；模型模式：v3_look_through。",
             "机器 JSON 内部金额保持原生尺度；主报告及对外正文必须换算为亿元／万元，确认人工判断点后再运行计算器。", "",
             f"总资本开支强度 γ_total（历史G代理）：{g}；近三年 Capex/D：{g_ratios}；v3 维持性系数 γ_maint：{maint_gamma}",
             f"经营现金流 OCF_latest：{ocf_latest:.2f}（扣费用化利息 {fe_int:.2f} → {ocf_after_int:.2f}）；Capex_latest：{capex_latest:.2f}",
             f"广义分配率 p_dist：分红支付率法2={m2}；法1={m1}；采纳保守分红锚 p_div={payout:.4f}；注销式回购={buyback_mm:.2f}",
             f"资本回报估计：ROE_latest={roe_pct_txt}；ROIC_est={roic_pct_txt}",
             f"经营杠杆 λ 段值：{segments}；有效λ：{lam}", "", "## 公式及来源",
             *[f"- {key}: {value}" for key,value in snapshot["formula_sources"].items()], "", "## 需核实及警告",
             *["- "+warning for warning in warnings], "",
             "不得将营运资本当现金保护，不得把货币资金命名为净现金。",
             "请核实维持性开支系数 γ_maint、注销式回购金额、分红承诺底线、无风险利率 Rf、现金/债务范围、普通股权益及十年复权低价证据。"]
    from run_support import atomic_json
    atomic_json(out/"穿透回报率_输入.json",cfg)
    (out/"输入_判断点说明.md").write_text("\n".join(notes)+"\n",encoding="utf-8")
    print(f"已生成 {out/'穿透回报率_输入.json'}；警告{len(warnings)}项，未覆盖既有人工输入")


if __name__ == "__main__":
    main()
