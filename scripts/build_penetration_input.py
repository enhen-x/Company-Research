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
    C=归母净利(年报)  D=折旧摊销(FA_IR_DEPR+IA_AMORTIZE+LPE_AMORTIZE+USERIGHT_ASSET_AMORTIZE)
    G建议=近3年Capex/D&A比值  M法2=DPS×股本/归母净利（近3年均值；注意：分配股利现金列 ASSIGN_DIVIDEND_PORFIT
    含偿付利息会低估支付率，禁用作法2）  法1=DPS/EPS 并列对比
    surplus=OCF-D×G建议  AA_2y=近2年均值  AA_all=近5年均值  revenue_series 同口径
    net_cash 狭义=货币资金（默认）/ 广义=货币资金+交易性金融资产（判断点）
    interest_bearing_debt(短借+长借+应付债+短融，默认不含租赁)
    shares=股本(百万股)  market_cap=price×shares(百万元)  ebitda=营业利润+D  fcf=OCF-Capex
    goodwill/total_assets/dps(最新财年含中期)/net_current_assets/book_equity/low_10y_close

人判断点（脚本自动标注"需确认"，附建议值、依据、易错点）：
    G 是否采纳建议（建议值可能因扩产期 Capex 暴增而失真，需结合资本开支阶段判断）
    M 法1 vs 法2（偏差>5pct 排除法1）  AA 用 2y 还是 all
    net_cash 狭义 vs 广义（methodology 默认狭义，用广义必须说明理由）
    rf 取值日期（默认需人工核对当日10年期国债）  cycle_adjust（弱周期=0）  λ 可信度

λ 异常年诊断（复现水星家纺 2022 年教训）：对 surplus 序列逐段检测
    Δ结余/Δ收入 比值的符号一致性 + 单段主导度；任一异常 -> 自动降级为"保守参考"。
"""
import argparse
import json
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

def val_mm(df: pd.DataFrame, col: str) -> list:
    """年报列值序列（元 -> 百万元），缺失填 0。仅用于金额列。"""
    if col not in df.columns:
        return [0.0] * len(df)
    return (pd.to_numeric(df[col], errors="coerce").fillna(0) / UNIT).tolist()


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
    d = div[["报告期", "现金分红-现金分红比例"]].copy()
    d["报告期"] = pd.to_datetime(d["报告期"])
    d["财年"] = d["报告期"].dt.year
    d["DPS"] = pd.to_numeric(d["现金分红-现金分红比例"], errors="coerce") / 10.0
    d = d[d["DPS"] > 0]
    return d.groupby("财年")["DPS"].sum().sort_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="项目 data/ 目录（含三表/分红/日线 CSV）")
    ap.add_argument("--out", required=True, help="输出目录（项目 input/）")
    ap.add_argument("--company", required=True)
    ap.add_argument("--code", required=True)
    ap.add_argument("--rf", type=float, default=0.017, help="10年期国债收益率（需人工核对当日值）")
    ap.add_argument("--price", type=float, default=None, help="现价（缺省取日线最新收盘）")
    # 龟龟轨 · 成长校准（forward，2026-08-21 新增）：前瞻盈利/支付率/折扣/结余为人工判断点
    ap.add_argument("--c-fwd", type=float, default=None,
                    help="前瞻归母净利（亿元，未来12个月/下一财年；有证据支撑才启用成长校准轨）")
    ap.add_argument("--m-fwd", type=float, default=None, help="前瞻支付率锚（默认=M 保守锚）")
    ap.add_argument("--k-fwd", type=float, default=None, help="前瞻折扣系数（默认=min(k,0.85)）")
    ap.add_argument("--aa-fwd", type=float, default=None, help="前瞻真实可支配现金（亿元，可选，现金校验）")
    ap.add_argument("--c-fwd-source", default="", help="前瞻盈利来源标注（如：券商一致预期下沿 52.6 亿）")
    args = ap.parse_args()

    data = Path(args.data)
    pnl = annual_rows(pd.read_csv(data / "利润表_按报告期.csv", encoding="utf-8-sig"))
    cf = annual_rows(pd.read_csv(data / "现金流量表_按报告期.csv", encoding="utf-8-sig"))
    bs = annual_rows(pd.read_csv(data / "资产负债表_按报告期.csv", encoding="utf-8-sig"))
    div = pd.read_csv(data / "分红送配记录.csv", encoding="utf-8-sig")
    daily = pd.read_csv(data / "日线股价.csv", encoding="utf-8-sig")
    daily_close = close_col(daily)

    if len(pnl) < 5 or len(cf) < 5:
        sys.exit(f"年报不足5年: 利润表 {len(pnl)} / 现金流 {len(cf)}")

    years = [d.year for d in cf["REPORT_DATE"]]
    revs_new = list(reversed(val_mm(pnl, "OPERATE_INCOME")))          # 由新到旧
    C_new = list(reversed(val_mm(pnl, "PARENT_NETPROFIT")))
    op_profit_new = list(reversed(val_mm(pnl, "OPERATE_PROFIT")))
    # D 默认含使用权摊销（2021+ 租赁准则，实质折旧费用；水星家纺实战确认手填值含此项）
    D_new = list(reversed([a + b + c + d for a, b, c, d in zip(
        val_mm(cf, "FA_IR_DEPR"), val_mm(cf, "IA_AMORTIZE"), val_mm(cf, "LPE_AMORTIZE"),
        val_mm(cf, "USERIGHT_ASSET_AMORTIZE"))]))
    capex_new = list(reversed(val_mm(cf, "CONSTRUCT_LONG_ASSET")))    # 由新到旧
    ocf_new = list(reversed(val_mm(cf, "NETCASH_OPERATE")))

    # --- G 建议: 近3年 Capex/D&A（顺序由新到旧 -> 取 [:3]）---
    g_pairs = [capex_new[i] / D_new[i] for i in range(len(capex_new)) if D_new[i] > 0]
    g_last3 = g_pairs[:3] if len(g_pairs) >= 3 else g_pairs
    G_suggest = round(sum(g_last3) / len(g_last3), 3) if g_last3 else 0.9
    g_note = (f"近3年比值 {[round(x,2) for x in g_last3]}；"
              f"若近年为扩产期（Capex 暴增），建议值失真，需结合资本开支阶段调回 0.7~0.9")

    # --- M 法2: DPS×股本/归母净利（近3年；分配股利现金列含利息，禁用）---
    dps_fy = dps_by_fiscal_year(div)
    shares_mm = float(bs.iloc[-1].get("SHARE_CAPITAL", 0) or 0) / UNIT  # 面值1元 -> 百万股
    m2 = []
    for i in range(min(3, len(years))):
        y = years[-1 - i]
        if y in dps_fy.index and C_new[i] > 0:
            m2.append(dps_fy.loc[y] * shares_mm / C_new[i])
    M2 = round(sum(m2) / len(m2), 3) if m2 else None
    M2_min = round(min(m2), 3) if m2 else None
    # --- M 法1: DPS/EPS（近3年；DPS 连续多年相同为疑似填充错误，禁用法1）---
    eps_new = list(reversed(val_per_share(pnl, "BASIC_EPS")))
    m1 = []
    for i in range(min(3, len(years))):
        y = years[-1 - i]
        if y in dps_fy.index and eps_new[i] > 0:
            m1.append(dps_fy.loc[y] / eps_new[i])
    M1 = round(sum(m1) / len(m1), 3) if m1 else None
    M1_min = round(min(m1), 3) if m1 else None

    # --- surplus 序列 (由新到旧) 与 AA ---
    # 注意: D_new/ocf_new 已是"由新到旧"，O-H 直接配对就是由新到旧，不得再 reversed
    surplus_new = [o - h for o, h in zip(ocf_new, [d * G_suggest for d in D_new])]
    AA_2y = round(sum(surplus_new[:2]) / 2, 1)
    # AA_all = 近5年均值（methodology 定义 5 年均值，非全部历史——早期负 OCF 年会稀释均值）
    AA_all = round(sum(surplus_new[:5]) / min(5, len(surplus_new)), 1)

    # --- λ 异常年诊断 ---
    lam_diag = []
    for i in range(len(surplus_new) - 1):
        dr = revs_new[i] - revs_new[i + 1]
        ds = surplus_new[i] - surplus_new[i + 1]
        if abs(dr) < 1e-6:
            continue
        lam_diag.append({"段": f"{i+1}(近第{i+1}段)", "Δ收入": round(dr, 1),
                         "Δ结余": round(ds, 1), "λ段": round(ds / dr, 3)})
    lam_vals = [d["λ段"] for d in lam_diag]
    signs = {1 if v > 0 else -1 for v in lam_vals}
    lam_credit = "中"
    lam_verdict = "可用，建议结合业务事件判断"
    if len(signs) > 1:
        lam_credit = "低"
        lam_verdict = "Δ结余/Δ收入符号不一致，λ 应降级为保守参考（敏感性表仅作参考）"
    elif len(lam_vals) >= 3:
        med = sorted(lam_vals)[len(lam_vals) // 2]
        if abs(med) > 1e-6 and any(abs(v) > abs(med) * 2 for v in lam_vals):
            lam_credit = "低"
            lam_verdict = "单段主导（疑似异常年如疫情/资产处置），λ 应降级为保守参考，敏感性表仅作参考"

    # --- 资产负债表/其他（最新年报）---
    # 注意: 不存在的列/NaN 用 pd.to_numeric+fillna(0)，float(NaN or 0) 会因 NaN truthy 泄漏
    lb = bs.iloc[-1]

    def lv(col: str) -> float:
        return float(pd.to_numeric(lb.get(col), errors="coerce")) if pd.notna(lb.get(col)) else 0.0

    net_cash_narrow = lv("MONETARYFUNDS") / UNIT
    # 广义现金 = 货币资金 + 理财（东财列名 TRADE_FINASSET_NOTFVTPL=以公允价值计量且其变动计入当期损益
    # 的金融资产/理财，实测水星家纺 2025 年报 842.8 百万；旧列名 TRADE_FINASSET 等保留兼容）
    net_cash_broad = net_cash_narrow + sum(lv(c) / UNIT for c in
                                           ["TRADE_FINASSET_NOTFVTPL", "TRADE_FINASSET",
                                            "FVTPL_FINASSET", "APPOINT_FVTPL_FINASSET"])
    debt = sum(lv(c) / UNIT for c in ["SHORT_LOAN", "LONG_LOAN", "BOND_PAYABLE", "SHORT_BOND_PAYABLE"])
    if shares_mm <= 0:
        shares_mm = round(C_new[0] / (eps_new[0] if eps_new[0] > 0 else 1), 3)
    price = args.price if args.price else float(daily[daily_close].iloc[-1])
    market_cap = round(price * shares_mm, 1)  # 百万元

    goodwill = lv("GOODWILL") / UNIT
    total_assets = lv("TOTAL_ASSETS") / UNIT
    nca = (lv("TOTAL_CURRENT_ASSETS") - lv("TOTAL_CURRENT_LIAB")) / UNIT
    book_equity = lv("TOTAL_PARENT_EQUITY") / UNIT
    ebitda = round(op_profit_new[0] + D_new[0], 1)
    fcf = round(ocf_new[0] - capex_new[0], 1)
    dps_cur = round(dps_fy.get(years[-1], 0.0), 2) if years else 0.0
    low10 = float(daily[daily_close].min())

    cfg = {
        "company": args.company, "code": args.code, "date": str(pd.Timestamp.today().date()),
        "price": round(price, 2), "market_cap": round(market_cap, 1), "shares": round(shares_mm, 4),
        "net_profit_C": round(C_new[0], 1), "depreciation_D": round(D_new[0], 1),
        "capex_ratio_G": G_suggest, "profit_discount_k": 0.8, "payout_M": M2_min or M2 or M1 or 0.6,
        "payout_M_min": M2_min or M1 or 0.6, "payout_M_mean": M2 or M1 or 0.6,
        "aa_2y": AA_2y, "aa_all": AA_all, "rf": args.rf, "cycle_adjust_pct": 0.0,
        "base_revenue": round(revs_new[0], 1),
        "surplus_series": [round(x, 1) for x in surplus_new[:5]],
        "revenue_series": [round(x, 1) for x in revs_new[:5]],
        "net_cash": round(net_cash_narrow, 1), "interest_bearing_debt": round(debt, 1),
        "ebitda": ebitda, "fcf": fcf, "goodwill": round(goodwill, 1),
        "total_assets": round(total_assets, 1), "dps": dps_cur,
        "net_current_assets": round(nca, 1), "book_equity": round(book_equity, 1),
        "low_10y_close": round(low10, 2),
    }
    # 成长校准轨（可选）：亿元 -> 百万元（×100）
    if args.c_fwd is not None:
        cfg["net_profit_C_fwd"] = round(args.c_fwd * 100, 1)
        if args.m_fwd is not None:
            cfg["payout_M_fwd"] = args.m_fwd
        if args.k_fwd is not None:
            cfg["profit_discount_k_fwd"] = args.k_fwd
        if args.aa_fwd is not None:
            cfg["aa_fwd"] = round(args.aa_fwd * 100, 1)
        if args.c_fwd_source:
            cfg["c_fwd_source"] = args.c_fwd_source

    m_diff = "≤5pct，法1可作参考" if M1 and M2 and abs(M1 - M2) <= 0.05 else ">5pct，排除法1"
    lines = [
        f"# 穿透回报率输入 — 判断点说明（{args.company} {args.code}，{cfg['date']}）",
        "",
        "> 机器字段由 build_penetration_input.py 从三表自动计算（零手算）；人判断点已标注建议与依据。",
        "",
        "## 机器字段（自动计算）",
        f"- C 归母净利（最新年报）: {cfg['net_profit_C']} 百万（利润表 PARENT_NETPROFIT）",
        f"- D 折旧摊销: {cfg['depreciation_D']} 百万（FA_IR_DEPR+IA_AMORTIZE+LPE_AMORTIZE+USERIGHT_ASSET_AMORTIZE 使用权摊销，2021+ 租赁准则实质折旧费用）",
        f"- G 建议值: {cfg['capex_ratio_G']}——{g_note}",
        f"- k 利润折扣系数（默认 0.8）: 0.7~0.9 按可预测性取档（强0.9/中0.8/弱0.7，保守方向取小值）",
        f"- M 法2: 序列 {[round(x, 3) for x in m2]}（均值 {M2} / 最低档 {M2_min}；**分配股利现金列含偿付利息，禁用作法2**）",
        f"- M 法1: {M1}（DPS/EPS，近3年；DPS 连续多年相同为疑似填充错误，禁用法1）——两法偏差: {m_diff}",
        f"- AA_2y: {cfg['aa_2y']} / AA_all: {cfg['aa_all']}（surplus 序列: {cfg['surplus_series']}）",
        f"- net_cash 狭义(货币资金): {net_cash_narrow:.1f} 百万 / 广义(含交易性金融资产): {net_cash_broad:.1f} 百万",
        f"- 有息负债: {cfg['interest_bearing_debt']} 百万（短借+长借+应付债+短融，默认不含租赁）",
        f"- shares: {cfg['shares']} 百万股 / market_cap: {cfg['market_cap']} 百万 / price: {cfg['price']}",
        f"- ebitda: {cfg['ebitda']}（营业利润+D）/ fcf: {cfg['fcf']}（OCF-Capex）/ dps: {cfg['dps']}（最新财年含中期）",
        f"- low_10y_close: {cfg['low_10y_close']}（前复权10年最低收盘）",
        "",
        "## 人判断点（需确认，附建议与依据）",
        f"1. **G** 建议 {cfg['capex_ratio_G']}——轻资产 0.7~0.9；扩产期建议值失真时调回区间并说明依据",
        f"2. **M** 优先用章程/公告承诺最低支付率；无承诺建议取法2 历史最低档 = {M2_min}（均值 {M2} 仅交叉参考；法1 = {M1}，{m_diff}）",
        "3. **k** 利润折扣系数默认 0.8——强可预测（垄断公用/顶级品牌/极稳定现金牛）0.9；中（稳定制造/一般消费）0.8；弱（周期/强竞争/收入波动大）0.7；保守方向取小值",
        f"4. **AA** 默认 AA_2y={cfg['aa_2y']}，对比 AA_all={cfg['aa_all']}；结余口径变化必须说明理由",
        f"5. **net_cash** 默认狭义 {net_cash_narrow:.1f}；methodology 默认狭义，用广义 {net_cash_broad:.1f} 必须说明理由",
        f"6. **rf** = {args.rf}（--rf 传入，需核对当日 10 年期国债收益率；±0.5pct → 门槛 II ±0.5pct）",
        "7. **cycle_adjust** = 0（弱周期不修正；周期股需依据）",
        f"8. **λ 可信度: {lam_credit}**——{lam_verdict}；λ 段明细: {lam_diag}",
    ]
    if args.c_fwd is not None:
        _mf = cfg.get("payout_M_fwd", cfg["payout_M"])
        _kf = cfg.get("profit_discount_k_fwd", 0.85)
        lines += [
            "",
            "## 龟龟轨 · 成长校准（forward，2026-08-21 新增）",
            f"- C_fwd（前瞻盈利）: {cfg['net_profit_C_fwd']} 百万（= {args.c_fwd} 亿）——来源: {args.c_fwd_source or '未标注（须补证据：公司指引/券商一致预期下沿/自建驱动桥）'}",
            f"- M_fwd: {_mf}（默认取 M 保守锚；分红率上行+中期分红承诺可上调至近3年均值并注明依据）",
            f"- k_fwd: {_kf}（默认 min(k,0.85)，前瞻不确定性更高，折扣不放松）",
            f"- aa_fwd: {cfg.get('aa_fwd', '未提供')} 百万（可选，现金校验）",
            "- 纪律：评级锚仍为保守轨 trailing；成长校准轨只给『成长验证买入区』与升级触发（实际数据验证后才可升级主轨）；禁止把两轨目标价混用",
        ]
    lines += [
        "",
        "## 使用",
        "确认人判断点后复制 穿透回报率_输入.json 至 input/ 并运行 calc_penetration_return.py --config。",
    ]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "穿透回报率_输入.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "输入_判断点说明.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ 已生成 {out / '穿透回报率_输入.json'} 与 输入_判断点说明.md")
    print(f"   核心: C={cfg['net_profit_C']} D={cfg['depreciation_D']} G建议={cfg['capex_ratio_G']} "
          f"M2均值={M2} M2最低={M2_min} M1={M1} k={cfg['profit_discount_k']} AA_2y={cfg['aa_2y']} AA_all={cfg['aa_all']}")
    print(f"   市值={cfg['market_cap']}百万 net_cash窄/宽={net_cash_narrow:.1f}/{net_cash_broad:.1f} "
          f"λ可信度={lam_credit} 判断点详见 输入_判断点说明.md")
    if args.c_fwd is not None:
        print(f"   成长校准轨: C_fwd={args.c_fwd}亿 M_fwd={cfg.get('payout_M_fwd','(默认)')} "
              f"k_fwd={cfg.get('profit_discount_k_fwd','(默认0.85)')} 来源={args.c_fwd_source or '未标注'}")


if __name__ == "__main__":
    main()
