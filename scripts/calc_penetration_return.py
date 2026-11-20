#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''穿透回报率估值计算器（Look-Through Return Method v3，确定性，仅标准库）

用法：
    python calc_penetration_return.py --config 输入.json
    python calc_penetration_return.py --config 输入.json --v3        # 强制使用 v3 广义穿透回报率为主输出
    python calc_penetration_return.py --config 输入.json --json      # 纯 JSON → stdout（人类可读文本 → stderr）
    python calc_penetration_return.py --selftest                     # 用凌霄泵业校准基准及 v3 正式指标自检

核心口径（v3 Look-Through Return Method，与预期差/Capex拐点模块解耦）：
    1. 维持性现金底座 OE_cash：
       非金融以 OCF_扣息 - D&A×γ_maint 为校验底座（剥离扩张性 Capex 错杀）；
       商业银行以监管可分配利润底座 min(NP, AA_2y) 校验；非银金融采用五年均值平滑抑制周期顶点虚高。
    2. 广义穿透回报率 R_LT = R_dist（现金分红 + 注销式回购） + R_retain（经现金含金量与 ROIC>R_req 双重校验的留存复利 × η）。
    3. 铁血防守纪律：现金含金量校验不通过或 ROIC_eff < R_req + 2% 时，η 强制归零并降级现金口径。

输出兼容契约：
    - 始终在 `formal_metrics` 与 `look_through_v3` 输出完整 v3 正式术语结果；
    - 当 `model_mode == "v3_look_through"` 或传入 `v3=True` / `--v3` 时，顶层主字段（R_star, GG, r_eff, II, KK, target_buy, floor_price）切换为 v3 口径；
    - 未启用 v3 模式时保持顶层 legacy 字段与历史单元测试 100% 兼容。

公式与阈值见 ../references/methodology.md。
'''

from __future__ import annotations

import math
import argparse
import json
import sys
from pathlib import Path

_ARCHETYPE_LABELS = {
    'bank': '商业银行',
    'non_bank_fin': '非银金融',
    'internet_tech': '互联网与轻资产科技',
    'consumer': '消费品与零售',
    'utility_infra': '公用事业与基础设施',
    'manufacturing': '制造业与工业',
}

_MAINT_GAMMA_CAP = {
    'bank': 0.0,
    'non_bank_fin': 0.0,
    'internet_tech': 0.80,
    'consumer': 0.80,
    'manufacturing': 0.90,
    'utility_infra': 0.90,
}

_ETA_MAX_CAP = {
    'internet_tech': 0.80,
    'consumer': 0.80,
    'manufacturing': 0.80,
    'bank': 0.25,
    'non_bank_fin': 0.25,
    'utility_infra': 0.55,
}

_ETA_SPREAD_SCALE = {
    'internet_tech': 0.15,
    'consumer': 0.15,
    'manufacturing': 0.15,
    'bank': 0.065,
    'non_bank_fin': 0.065,
    'utility_infra': 0.12,
}

# 金融板块基础权益资本成本门槛 K_{e,fin}（已叠加 η_max=0.25 扣除 75% 监管维持资本与 PB<1 折价，此处设定合理连续起算底线避免双重扣减）
_FIN_KE_HURDLE = {
    'bank': 0.075,
    'non_bank_fin': 0.065,
}


def infer_industry_archetype(cfg: dict) -> str:
    """根据显式声明或名称/财务特征识别六大行业原型。"""
    explicit = str(cfg.get('industry_archetype') or '').strip()
    if explicit in _ARCHETYPE_LABELS:
        return explicit
    company = str(cfg.get('company') or '')
    notes = ' '.join(str(x) for x in cfg.get('input_warnings', []))
    combined = f'{company} {notes}'
    d_val = cfg.get('depreciation_D')
    if any(k in combined for k in ('银行', '农商行', '银行业')):
        return 'bank'
    if any(k in combined for k in ('保险', '人保', '太保', '新华', '平安', '证券', '海通', '券商', '非银', '信托')):
        return 'non_bank_fin'
    if d_val is not None and float(d_val) == 0.0:
        return 'non_bank_fin'
    if any(k in combined for k in ('电力', '水务', '环境', '高速', '铁路', '公路', '港口', '燃气', '能源', '核电', '矿业', '海油', '神华', '移动', '电信', '成渝', '轮船', '海控')):
        return 'utility_infra'
    if any(k in combined for k in ('腾讯', '阿里', '美团', '百度', '网易', '完美', '游戏', '互联网', '软件', '传媒', '网宿', '光环')):
        return 'internet_tech'
    if any(k in combined for k in ('茅台', '五粮液', '伊利', '啤酒', '乳业', '食品', '饮料', '阿胶', '白药', '达仁堂', '家纺', '百货', '旅游', '免税', '消费', '泵业')):
        return 'consumer' if not any(k in combined for k in ('泵业', '化工', '机械', '汽车', '轮胎', '电气', '光电')) else 'manufacturing'
    return 'manufacturing'


def pct(x: float) -> str:
    return '{:.2f}%'.format(x * 100)


def fmt2(x) -> str:
    return '{:.2f}'.format(x) if x is not None else '—'


def pct2(x: float) -> str:
    '''带正负号、保留2位的百分点文本'''
    return '{:+.2f} pct'.format(x * 100)


def diagnose_lambda(cfg: dict) -> dict:
    """Keep the historical estimate separate from its reliability assessment."""
    surplus = cfg.get('surplus_series') or []
    revenues = cfg.get('revenue_series') or []
    years = cfg.get('financial_years') or []
    intervals, reasons = [], []
    if len(surplus) < 2 or len(surplus) != len(revenues):
        reasons.append('历史结余与收入配对不足')
    else:
        for index in range(len(surplus) - 1):
            values = (surplus[index], surplus[index + 1], revenues[index], revenues[index + 1])
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                reasons.append('历史配对包含缺失或非有限值')
                continue
            delta_revenue = revenues[index] - revenues[index + 1]
            if delta_revenue == 0:
                reasons.append('相邻年度收入差为0')
                continue
            slope = (surplus[index] - surplus[index + 1]) / delta_revenue
            interval = {'index': index, 'slope': slope}
            if len(years) == len(surplus):
                interval['period'] = f'{years[index]}/{years[index + 1]}'
            intervals.append(interval)
    slopes = [row['slope'] for row in intervals]
    raw_mean = math.fsum(slopes) / len(slopes) if slopes else None
    signs = {1 if value > 0 else -1 for value in slopes if value != 0}
    if len(signs) > 1:
        reasons.append('逐段斜率正负混合')
    if any(abs(value) > 1.5 for value in slopes):
        reasons.append('单段斜率绝对值大于1.5')
    return {'method': 'mean_of_adjacent_annual_slopes', 'raw_mean': raw_mean,
            'intervals': intervals, 'reliable': bool(slopes) and not reasons,
            'reasons': list(dict.fromkeys(reasons))}


def _finite_num(val) -> float | None:
    if isinstance(val, bool) or val is None:
        return None
    try:
        f = float(val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _detect_ma_scale_jump(
    cfg: dict,
    *,
    C: float,
    aa: float,
    aa_all: float | None,
    book_eq: float | None,
    is_fin: bool,
) -> dict:
    """识别吸收合并或重大外源扩表引发的历史基数不可比问题，将历史盈利/结余按体量倍率折算为同口径备考基准。"""
    base_aa_all = aa_all if aa_all is not None else aa
    no_adj = {
        'detected': False,
        'method': 'none',
        'scale_all': 1.0,
        'scale_2y': 1.0,
        'f_full_year': 1.0,
        'c_full_year_pro_forma': C,
        'aa_all_pro_forma': base_aa_all,
        'aa_2y_pro_forma': aa,
        'note': '',
    }
    if cfg.get('ma_restructuring') is False:
        return no_adj

    explicit_scale = _finite_num(cfg.get('ma_scale_factor'))
    if explicit_scale is not None and explicit_scale > 1.05:
        s_all = min(3.0, explicit_scale)
        s_2y = min(3.0, (1.0 + s_all) / 2.0) if (aa is not None and C > 0 and aa < 0.90 * C) else 1.0
        return {
            'detected': True,
            'method': 'explicit_factor',
            'scale_all': s_all,
            'scale_2y': s_2y,
            'f_full_year': 1.0,
            'c_full_year_pro_forma': C,
            'aa_all_pro_forma': (base_aa_all * s_all) if base_aa_all is not None else None,
            'aa_2y_pro_forma': aa * s_2y if aa is not None else aa,
            'note': f'显式并购扩表倍率 {s_all:.2f}x（同步还原 5Y/2Y 备考基准）',
        }

    def _valid_seq(val) -> list[float]:
        if not isinstance(val, (list, tuple)):
            return []
        res = []
        for x in val:
            fx = _finite_num(x)
            if fx is None:
                return []
            res.append(fx)
        return res

    eq_seq = _valid_seq(cfg.get('book_equity_series'))
    sh_seq = _valid_seq(cfg.get('shares_series'))
    np_seq = _valid_seq(cfg.get('net_profit_series'))
    rev_seq = _valid_seq(cfg.get('revenue_series'))
    gw = _finite_num(cfg.get('goodwill')) or 0.0

    # 路径 A：优先基于资产负债表净资产 / 股本序列检测外源并购扩表跃迁（最新年份在前）
    if len(eq_seq) >= 3 and all(e > 0 for e in eq_seq):
        n_years = len(eq_seq)
        jump_idx: int | None = None
        for idx in range(1, n_years):
            e_curr, e_prev = eq_seq[idx - 1], eq_seq[idx]
            ratio_e = e_curr / e_prev if e_prev > 0 else 1.0
            delta_e = e_curr - e_prev
            np_curr = np_seq[idx - 1] if (len(np_seq) == n_years) else (C if idx == 1 else 0.0)
            beyond_organic = (np_curr <= 0 and delta_e > 0) or (delta_e > 1.35 * max(0.0, np_curr))
            ratio_s = (sh_seq[idx - 1] / sh_seq[idx]) if (len(sh_seq) == n_years and sh_seq[idx] > 0) else 1.0
            if (ratio_e >= 1.30 and beyond_organic) or (ratio_e >= 1.25 and ratio_s >= 1.20):
                jump_idx = idx
                break
        if jump_idx is not None:
            e_anchor = eq_seq[jump_idx - 1]
            # 并购首年（jump_idx==1）利润为年中并表流量而期末净资产/市值为 100% 存量：按加权净资产口径年化至全期并表盈利基数
            e_weighted = 0.75 * eq_seq[0] + 0.25 * eq_seq[1]
            f_full_year = min(1.25, max(1.0, eq_seq[0] / e_weighted)) if (jump_idx == 1 and e_weighted > 0) else 1.0
            c_pf = C * f_full_year if (jump_idx == 1 and C > 0) else C
            factors = [
                max(1.0, min(3.0, e_anchor / eq_seq[t])) if t >= jump_idx else f_full_year
                for t in range(n_years)
            ]
            scale_all = sum(factors) / len(factors)
            scale_2y = (factors[0] + factors[1]) / 2.0
            if is_fin and len(np_seq) == n_years:
                scaled_nps = [np_seq[t] * factors[t] for t in range(n_years)]
                aa_all_pf = sum(scaled_nps) / len(scaled_nps)
                aa_2y_pf = (scaled_nps[0] + scaled_nps[1]) / 2.0
            else:
                aa_all_pf = (base_aa_all * scale_all) if base_aa_all is not None else None
                aa_2y_pf = aa * scale_2y if (aa is not None and jump_idx == 1) else aa
            fy_txt = f'；首年全期年化 {f_full_year:.2f}x → NP_pf={c_pf:.2f}' if f_full_year > 1.0 else ''
            return {
                'detected': True,
                'method': 'balance_sheet_jump',
                'scale_all': scale_all,
                'scale_2y': scale_2y,
                'f_full_year': f_full_year,
                'c_full_year_pro_forma': c_pf,
                'aa_all_pro_forma': aa_all_pf,
                'aa_2y_pro_forma': aa_2y_pf,
                'note': (
                    f'并购/外源扩表跃迁（期{jump_idx-1}/期{jump_idx}净资产 {eq_seq[jump_idx-1]/eq_seq[jump_idx]:.2f}x）'
                    f'{fy_txt}；5Y 备考均值 {aa_all_pf:.2f}（均倍 {scale_all:.2f}x）'
                    if aa_all_pf is not None else f'并购/外源扩表跃迁{fy_txt}'
                ),
            }

    # 路径 B：缺省净资产序列时，用营收同步阶跃 + 并购/规模ROE佐证回退检测
    if len(rev_seq) >= 3 and rev_seq[0] > 0 and rev_seq[1] > 0:
        prior_revs = [r for r in rev_seq[1:] if r > 0]
        if len(prior_revs) >= 2:
            r_ratio_1 = rev_seq[0] / rev_seq[1]
            r_prior_mean = sum(prior_revs) / len(prior_revs)
            r_ratio_prior = rev_seq[0] / r_prior_mean
            prior_stable = (max(prior_revs) / min(prior_revs)) < 1.45
            fin_scale_roe = is_fin and (book_eq is not None and book_eq > 0 and C > 0 and (C / book_eq) <= 0.12)
            corroborated = (gw > 0) or (cfg.get('ma_restructuring') is True) or fin_scale_roe
            if r_ratio_1 >= 1.40 and r_ratio_prior >= 1.40 and prior_stable and corroborated:
                r_weighted = 0.75 * rev_seq[0] + 0.25 * rev_seq[1]
                f_full_year = min(1.25, max(1.0, rev_seq[0] / r_weighted)) if r_weighted > 0 else 1.0
                c_pf = C * f_full_year if C > 0 else C
                r_0_fy = rev_seq[0] * f_full_year
                r_all_mean = sum(rev_seq) / len(rev_seq)
                scale_all = max(1.0, min(3.0, r_0_fy / r_all_mean))
                r_2y_mean = (rev_seq[0] + rev_seq[1]) / 2.0
                scale_2y = max(1.0, min(3.0, r_0_fy / r_2y_mean))
                aa_all_pf = (base_aa_all * scale_all) if base_aa_all is not None else None
                aa_2y_pf = (aa * scale_2y) if (aa is not None and c_pf > 0 and aa < 0.90 * c_pf) else aa
                return {
                    'detected': True,
                    'method': 'revenue_step_fallback',
                    'scale_all': scale_all,
                    'scale_2y': scale_2y,
                    'f_full_year': f_full_year,
                    'c_full_year_pro_forma': c_pf,
                    'aa_all_pro_forma': aa_all_pf,
                    'aa_2y_pro_forma': aa_2y_pf,
                    'note': (
                        f'并购级营收阶跃（当期/上年={r_ratio_1:.2f}x；首年全期年化 {f_full_year:.2f}x → NP_pf={c_pf:.2f}），'
                        f'5Y 备考均值 {aa_all_pf:.2f}（{scale_all:.2f}x）'
                        if aa_all_pf is not None else f'并购级营收阶跃（首年全期年化 {f_full_year:.2f}x）'
                    ),
                }

    return no_adj


def _compute_fin_growth_realization(
    cfg: dict,
    *,
    roic_eff: float | None,
    retained_share: float,
    c_eff: float,
    ma_detected: bool,
    ma_f_full_year: float,
) -> tuple[float, float | None, float | None]:
    """金融板块近5年实际利润增速兑现度 ρ_g（防静态高 ROE 与真实增长脱节导致留存高估）。"""
    g_theo = (roic_eff * retained_share) if (roic_eff is not None and retained_share > 0) else None
    raw_seq = cfg.get('net_profit_series') or cfg.get('surplus_series') or []
    perf_seq: list[float] = []
    for item in raw_seq:
        v = _finite_num(item)
        if v is None:
            break
        perf_seq.append(v)

    if len(perf_seq) < 3 or g_theo is None or g_theo <= 0:
        return 1.0, g_theo, None

    y0 = c_eff if (ma_detected and ma_f_full_year > 1.0) else perf_seq[0]
    if y0 <= 0:
        g_actual = -1.0
    else:
        g_2y = ((y0 / perf_seq[2]) ** 0.5 - 1.0) if perf_seq[2] > 0 else None
        g_long = (
            ((y0 / perf_seq[-1]) ** (1.0 / (len(perf_seq) - 1)) - 1.0)
            if len(perf_seq) >= 4 and perf_seq[-1] > 0
            else g_2y
        )
        if g_2y is not None and g_long is not None:
            g_actual = min(g_long, 0.6 * g_2y + 0.4 * g_long)
        elif g_long is not None:
            g_actual = g_long
        else:
            g_actual = 0.0

    rho_g = min(1.0, max(0.0, g_actual / g_theo))
    return rho_g, g_theo, g_actual


def _compute_look_through_v3(
    cfg: dict,
    *,
    C: float,
    D: float,
    G_total: float,
    M: float,
    aa: float,
    market_cap: float,
    price: float,
    alpha: float,
    net_debt: float | None,
    rf: float,
    cycle_adj: float,
    II: float,
    warnings: list[str],
) -> dict:
    """穿透回报率法 v3 内核（维持性现金底座 OE_cash + 留存复利转化 η + 行业适配）。"""
    archetype = infer_industry_archetype(cfg)
    archetype_cn = _ARCHETYPE_LABELS.get(archetype, archetype)
    is_fin = archetype in ('bank', 'non_bank_fin')
    aa_all = _finite_num(cfg.get('aa_all'))
    fe_int = _finite_num(cfg.get('fe_interest_expense')) or 0.0
    book_eq = _finite_num(cfg.get('book_equity'))
    ma_info = _detect_ma_scale_jump(cfg, C=C, aa=aa, aa_all=aa_all, book_eq=book_eq, is_fin=is_fin)
    aa_eff = ma_info['aa_2y_pro_forma'] if ma_info['detected'] else aa
    aa_all_eff = ma_info['aa_all_pro_forma'] if ma_info['detected'] else aa_all
    if ma_info['detected'] and ma_info['note'] and ma_info['note'] not in warnings:
        warnings.append(ma_info['note'])

    # 1) 维持性资本开支系数 γ_maint 与维持性资本开支 Capex_maint
    explicit_gamma = _finite_num(cfg.get('gamma_maint') if cfg.get('gamma_maint') is not None else cfg.get('maint_capex_factor'))
    gamma_cap = _MAINT_GAMMA_CAP[archetype]
    if is_fin or D <= 0:
        gamma_maint = 0.0
    elif explicit_gamma is not None and explicit_gamma >= 0:
        gamma_maint = explicit_gamma
    elif G_total > 0:
        gamma_maint = min(G_total, gamma_cap)
    else:
        gamma_maint = 0.0
    capex_maint = D * gamma_maint

    # 2) 常态化盈利基数 NP_base（非银金融按近5年均值防周期顶点高估；并购首年采用全期并表年化盈利基数并与同口径备考均值对齐）
    c_eff = ma_info['c_full_year_pro_forma'] if ma_info['detected'] else C
    np_base = c_eff
    np_normalized_note = (
        f'并购首年全期年化备考归母净利 NP_pf={c_eff:.2f}（并表年化 {ma_info["f_full_year"]:.2f}x）'
        if ma_info['detected'] and ma_info['f_full_year'] > 1.0 else '当期归母净利润 NP'
    )
    if archetype == 'non_bank_fin' and aa_all_eff is not None and aa_all_eff > 0 and c_eff > 1.25 * aa_all_eff:
        np_base = 1.25 * aa_all_eff
        np_normalized_note = f'非银周期平滑基数 min(NP, 1.25×5Y均值)={np_base:.2f}（抑制周期高点虚高）'
    elif archetype == 'non_bank_fin' and ma_info['detected'] and aa_all is not None and c_eff > 1.25 * aa_all:
        np_normalized_note = (
            f'并购/扩表同口径备考校准：全期NP={np_base:.2f}，5Y备考均值={aa_all_eff:.2f}（1.25×上限={1.25*aa_all_eff:.2f}），未触发误砍'
        )
    oe_v3 = np_base + D - capex_maint

    # 3) 维持性现金底座 OE_cash（剥离扩张性 Capex 错杀；金融按监管可分配利润稳态底座）
    explicit_ocf_after_int = _finite_num(cfg.get('ocf_after_interest'))
    explicit_ocf = _finite_num(cfg.get('ocf_latest') if cfg.get('ocf_latest') is not None else cfg.get('ocf'))
    if is_fin:
        if archetype == 'bank':
            oe_cash = min(np_base, aa_eff) if aa_eff is not None else np_base
            oe_cash_basis = '商业银行监管稳态可分配盈余 min(NP, 2Y均值)'
        else:
            anchor_aa = max(aa_eff, aa_all_eff) if aa_all_eff is not None else aa_eff
            oe_cash = min(np_base, anchor_aa) if anchor_aa is not None else np_base
            oe_cash_basis = '非银金融周期平滑稳态盈余 min(NP_norm, 稳态均值)'
            if ma_info['detected']:
                oe_cash_basis += '（含并购同口径备考校准）'
        ocf_after_int = None
    else:
        if explicit_ocf_after_int is not None:
            ocf_after_int = explicit_ocf_after_int
            oe_cash_basis = '实测扣息经营现金流 ocf_after_interest − 维持性 Capex'
        elif explicit_ocf is not None:
            ocf_after_int = explicit_ocf - fe_int
            oe_cash_basis = '实测经营现金流 OCF_latest − 费用化利息 − 维持性 Capex'
        else:
            # 由 aa_2y = mean(OCF - D * G_total) 无偏还原近2年均 OCF
            ocf_after_int = aa_eff + D * G_total - fe_int
            oe_cash_basis = '由历史结余还原2Y均OCF − 维持性 Capex（剥离扩张性 Capex）'
            if ma_info['detected'] and aa_eff != aa:
                oe_cash_basis += '（并购备考体量对齐）'
        oe_cash = ocf_after_int - capex_maint

    # 4) 广义股东分配率 p_dist（现金分红率 p_div + 注销式回购率 p_buyback）
    p_div = max(0.0, float(M))
    explicit_pb = _finite_num(cfg.get('buyback_payout_ratio'))
    buyback_amt = _finite_num(cfg.get('buyback_amount')) or 0.0
    if explicit_pb is not None and explicit_pb >= 0:
        p_buyback = explicit_pb
    elif buyback_amt > 0 and C > 0:
        p_buyback = buyback_amt / C
    else:
        p_buyback = 0.0
    p_dist_raw = p_div + p_buyback
    p_dist = min(p_dist_raw, 1.25)  # 允许少量超额回馈上限至 125%，并由现金校验兜底
    retained_share = max(0.0, 1.0 - p_dist)

    # 5) 现金含金量校验（以维持性现金底座检验利润是否真实落袋）
    denom_prof = np_base * alpha
    cash_coverage = (oe_cash / denom_prof) if denom_prof > 0 else (1.0 if oe_cash >= 0 else 0.0)
    r_dist = (np_base * alpha * p_dist / market_cap) if np_base > 0 else 0.0
    r_cash_dist = (oe_cash * p_dist / market_cap) if oe_cash > 0 else 0.0
    dist_cash_dev = r_dist - r_cash_dist
    cash_quality_passed = (denom_prof > 0) and (cash_coverage >= 0.85) and (dist_cash_dev < 0.02)

    # 6) 有效投入资本回报率 ROIC_eff 与留存转化率 η
    roic_explicit = _finite_num(cfg.get('roic'))
    roe_explicit = _finite_num(cfg.get('roe') if cfg.get('roe') is not None else cfg.get('roe_latest'))
    roic_basis = ''
    roic_eff: float | None = None
    if is_fin:
        if roe_explicit is not None:
            roic_eff = roe_explicit
            roic_basis = '显式净资产收益率 ROE'
        elif book_eq is not None and book_eq > 0 and np_base > 0:
            roic_eff = np_base / book_eq
            roic_basis = 'NP_base / 归母普通股权益 BookEquity（金融 ROE 口径）'
    else:
        if roic_explicit is not None:
            roic_eff = roic_explicit
            roic_basis = '显式投入资本回报率 ROIC'
        elif book_eq is not None and book_eq > 0 and np_base > 0:
            nd_val = net_debt if net_debt is not None else 0.0
            invested_cap = max(book_eq * 0.25, book_eq + nd_val)
            roic_eff = np_base / invested_cap
            roic_basis = 'NP_base / 经营投入资本 max(0.25×净资产, 净资产+净负债)'
        elif roe_explicit is not None:
            roic_eff = roe_explicit
            roic_basis = '显式 ROE 代理（缺净债务明细）'

    eta = 0.0
    eta_reason = ''
    eta_max = _ETA_MAX_CAP[archetype]
    spread_scale = _ETA_SPREAD_SCALE[archetype]
    fin_ke = max(_FIN_KE_HURDLE[archetype], II + 0.02) if is_fin else None
    g_theo = (roic_eff * retained_share) if (roic_eff is not None and retained_share > 0) else None
    g_actual: float | None = None
    rho_g = 1.0
    if is_fin:
        rho_g, g_theo, g_actual = _compute_fin_growth_realization(
            cfg,
            roic_eff=roic_eff,
            retained_share=retained_share,
            c_eff=c_eff,
            ma_detected=ma_info['detected'],
            ma_f_full_year=ma_info['f_full_year'],
        )
    if not cash_quality_passed:
        eta = 0.0
        eta_reason = f'现金含金量校验未通过（Cov_cash={cash_coverage:.2f}<0.85 或现金偏差≥2%），留存转化率 η 强制归零'
    elif retained_share <= 0:
        eta = 0.0
        eta_reason = '分配率 ≥ 100%，无留存再投资比例（1 - p_dist = 0）'
    elif roic_eff is None:
        eta = 0.0
        eta_reason = '缺失净资产或 ROIC 口径，保守将 η 置零'
    elif is_fin and fin_ke is not None:
        if roic_eff <= fin_ke:
            eta = 0.0
            eta_reason = (
                f'金融 ROE={roic_eff*100:.2f}% 未超越金融权益资本成本门槛 Ke={fin_ke*100:.2f}%，'
                f'留存仅补充监管资本，η 置零'
            )
        else:
            raw_eta = min(eta_max, max(0.0, eta_max * (roic_eff - fin_ke) / spread_scale))
            eta = round(raw_eta * rho_g, 4)
            rho_desc = (
                f'，增速兑现度 ρ_g={rho_g:.2f}'
                f'（实际复合 {g_actual*100:.2f}% vs 理论内生 {g_theo*100:.2f}%）'
                if g_actual is not None and g_theo is not None
                else ''
            )
            eta_reason = (
                f'现金含金量合格且金融 ROE={roic_eff*100:.2f}% 超权益资本成本 Ke={fin_ke*100:.2f}% '
                f'+{(roic_eff-fin_ke)*100:.2f}pct{rho_desc} → η={eta:.4f}（{archetype_cn}上限 {eta_max:.2f}）'
            )
    elif roic_eff < II + 0.02:
        eta = 0.0
        eta_reason = f'ROIC_eff={roic_eff*100:.2f}% 低于要求门槛+2pct（{(II+0.02)*100:.2f}%），未创造显著超额价值，η 置零'
    else:
        raw_eta = eta_max * (roic_eff - II) / spread_scale
        eta = round(min(eta_max, max(0.0, raw_eta)), 4)
        eta_reason = (
            f'现金含金量合格且 ROIC_eff={roic_eff*100:.2f}% 超门槛 II={II*100:.2f}% '
            f'+{(roic_eff-II)*100:.2f}pct → η={eta:.4f}（{archetype_cn}上限 {eta_max:.2f}）'
        )

    # 7) 广义穿透回报率 R_LT、维持性现金校验 R_cash 与有效口径 R_eff
    # 金融股在 PB < 1 时按账面净资产增厚（分母取 max(市值, 净资产) 避免 1/PB 虚增留存复利）
    retain_denom = max(market_cap, book_eq) if (is_fin and book_eq is not None and book_eq > 0) else market_cap
    pb_discount_applied = bool(is_fin and book_eq is not None and book_eq > market_cap)
    r_retain = (np_base * alpha * retained_share * eta / retain_denom) if np_base > 0 else 0.0
    r_lt = r_dist + r_retain
    r_cash_retain = (oe_cash * retained_share * eta / retain_denom) if oe_cash > 0 else 0.0
    r_cash_full = (r_cash_dist + r_cash_retain) if oe_cash > 0 else (oe_cash * p_dist / market_cap)
    cash_dev_v3 = r_lt - r_cash_full

    if cash_quality_passed and cash_dev_v3 < 0.02:
        primary_v3 = 'R_LT（广义穿透主口径）' if r_retain > 0 else 'R_dist（直接分配主口径）'
        r_eff_v3 = r_lt
    elif cash_quality_passed and r_cash_dist >= II:
        # 即使现金校验低于 R_LT 超 2pct，至少不虚高，取两者较小值
        primary_v3 = 'R_cash（维持性现金上限校准）'
        r_eff_v3 = min(r_lt, max(r_cash_full, r_cash_dist))
    else:
        primary_v3 = 'R_cash（现金含金量不足降级）'
        r_eff_v3 = r_cash_dist if oe_cash > 0 else 0.0

    jj_v3 = r_eff_v3 - II
    mos_v3 = jj_v3 + cycle_adj
    p_buy_v3 = price * r_eff_v3 / II if II > 0 else 0.0
    p_floor_v3 = (price * II / r_eff_v3) if (r_eff_v3 or 0) > 0 else None

    return {
        'model_version': 'look_through_v3',
        'industry_archetype': archetype,
        'industry_archetype_label': archetype_cn,
        'np_base': np_base,
        'np_normalized_note': np_normalized_note,
        'ma_scale_adjusted': ma_info['detected'],
        'ma_scale_note': ma_info['note'],
        'ma_full_year_factor': ma_info['f_full_year'],
        'aa_all_pro_forma': aa_all_eff,
        'aa_2y_pro_forma': aa_eff,
        'total_capex_factor_G': G_total,
        'maint_capex_factor_gamma': gamma_maint,
        'maint_capex_amount': capex_maint,
        'owner_earnings_OE': oe_v3,
        'ocf_after_interest': ocf_after_int,
        'maint_cash_owner_earnings': oe_cash,
        'oe_cash_basis': oe_cash_basis,
        'cash_coverage': cash_coverage,
        'cash_quality_passed': cash_quality_passed,
        'p_div': p_div,
        'p_buyback': p_buyback,
        'buyback_amount': buyback_amt,
        'total_distribution_ratio_p': p_dist,
        'retained_share': retained_share,
        'alpha': alpha,
        'roic_eff': roic_eff,
        'roic_basis': roic_basis,
        'fin_ke_hurdle': fin_ke,
        'growth_realization_rho': round(rho_g, 4),
        'g_theoretical': g_theo,
        'g_actual': g_actual,
        'retain_denominator': retain_denom,
        'pb_discount_applied': pb_discount_applied,
        'eta': eta,
        'eta_reason': eta_reason,
        'r_dist': r_dist,
        'r_retain': r_retain,
        'r_lt': r_lt,
        'r_cash_dist': r_cash_dist,
        'r_cash': r_cash_full,
        'cash_dev': cash_dev_v3,
        'primary': primary_v3,
        'r_eff': r_eff_v3,
        'required_return_II': II,
        'jj': jj_v3,
        'margin_of_safety_KK': mos_v3,
        'target_buy': p_buy_v3,
        'floor_price': p_floor_v3,
        'qualified': bool(r_eff_v3 > II),
    }


def compute(cfg: dict, *, v3: bool | None = None) -> dict:
    warnings = list(cfg.get('input_warnings', []))
    cash = cfg.get('cash_balance')
    legacy_cash = cfg.get('net_cash')
    if cash is not None and legacy_cash is not None and not math.isclose(cash, legacy_cash, rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError('cash_balance 与旧字段 net_cash 冲突；旧字段历史语义是货币资金，不能填真实净现金')
    if cash is None and legacy_cash is not None:
        cash = legacy_cash
        warnings.append('旧字段 net_cash 按历史货币资金语义兼容，请迁移为 cash_balance；实际净现金另算 cash_balance-debt')
    debt = cfg.get('interest_bearing_debt')
    for field, value in (('cash_balance', cash), ('interest_bearing_debt', debt), ('ebitda',cfg.get('ebitda'))):
        if value is not None and (not isinstance(value,(float,int)) or not math.isfinite(value)):
            raise ValueError(f'{field} 必须是有限数字或null')
    net_debt = debt-cash if debt is not None and cash is not None else None
    if cfg.get('net_debt') is not None and (net_debt is None or not math.isclose(cfg['net_debt'],net_debt,rel_tol=1e-9,abs_tol=1e-6)):
        raise ValueError('net_debt 必须等于 interest_bearing_debt-cash_balance')
    if net_debt is None:
        warnings.append('现金或有息负债缺失，EV和净债务比率不可判定')
    price = cfg['price']
    market_cap = cfg['market_cap']
    shares = cfg['shares']
    C = cfg['net_profit_C']
    D = cfg['depreciation_D']
    G = cfg['capex_ratio_G']
    M = cfg['payout_M']
    aa = cfg['aa_2y']
    rf = cfg['rf']
    cycle_adj = cfg.get('cycle_adjust_pct', 0.0)
    revenue = cfg['base_revenue']

    for field in ('price','market_cap','shares','net_profit_C','depreciation_D','capex_ratio_G','payout_M','aa_2y','rf','base_revenue'):
        value = cfg[field]
        if not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError(f'{field} 是必需有限数字，缺失不可填0')
    if min(price, market_cap, shares)<=0:
        raise ValueError('price/market_cap/shares 必须为正数')
    # --- 经典滞后分红口径（legacy_v2，用于兼容旧输入回归对比） ---
    H = D * G
    oe = C + D - H
    k = cfg.get('profit_discount_k', 0.8)   # 盈利确定性折算系数 α（默认0.8，0.7~0.9）
    R_star = C * k * M / market_cap         # 纯分红穿透回报率（旧口径）
    R = C * M / market_cap                  # 账面未折算分红率
    GG = aa * M / market_cap                # 历史全资本开支口径现金校验
    HH = R - GG                             # 账面-现金偏差
    cash_dev = R_star - GG                  # 现金校验偏差：≥2pct → 现金验证失败，降级为 GG
    if cash_dev >= 0.02:
        primary = 'GG（现金校验降级）'
        r_eff = GG
    else:
        primary = 'R*'
        r_eff = R_star
    ii_floor = cfg.get('ii_floor', 0.035)  # 市场门槛下限：A股0.035 / 港股0.05 / 美股0.04
    rf_margin = cfg.get('rf_margin', 0.02)  # Rf 加成：A股+2pct / 港股+3pct / 美股+2pct
    II = max(ii_floor, rf + rf_margin)
    JJ = r_eff - II
    KK = JJ + cycle_adj  # 弱周期 cycle_adj=0
    target_buy = price * r_eff / II  # 目标买入价（旧口径）
    floor_price = (price * II / r_eff) if (r_eff or 0) > 0 else None

    # --- 穿透回报率法 v3（维持性现金底座 OE_cash + 留存复利转化 η） ---
    lt_v3 = _compute_look_through_v3(
        cfg,
        C=C, D=D, G_total=G, M=M, aa=aa, market_cap=market_cap, price=price,
        alpha=k, net_debt=net_debt, rf=rf, cycle_adj=cycle_adj, II=II, warnings=warnings,
    )
    use_v3 = (v3 is True) or (v3 is None and cfg.get('model_mode') == 'v3_look_through')
    legacy_snapshot = {
        'R_star': R_star, 'R': R, 'GG': GG, 'HH': HH, 'cash_dev': cash_dev,
        'primary': primary, 'r_eff': r_eff, 'II': II, 'JJ': JJ, 'KK': KK,
        'target_buy': target_buy, 'floor_price': floor_price,
        'H': H, 'OE': oe, 'G': G,
    }

    # --- 前瞻盈利校准轨（forward） ---
    # 触发：net_profit_C_fwd 有证据支撑（公司指引/券商一致预期下沿/自建驱动桥）且 > trailing C；
    # 纪律：主评级仍锚定已实现基线；前瞻轨仅输出“成长验证买入区”与升级触发参考（methodology §2.1）。
    C_fwd = cfg.get('net_profit_C_fwd')
    if C_fwd is not None:
        k_fwd = cfg.get('profit_discount_k_fwd', min(k, 0.85))
        M_fwd = cfg.get('payout_M_fwd', M)
        p_dist_fwd = M_fwd + lt_v3['p_buyback']
        retain_fwd = max(0.0, 1.0 - p_dist_fwd)
        eta_fwd = lt_v3['eta'] if (use_v3 and lt_v3['cash_quality_passed']) else 0.0
        retain_denom_fwd = lt_v3.get('retain_denominator', market_cap) if use_v3 else market_cap
        if use_v3:
            R_star_fwd = (
                C_fwd * k_fwd * p_dist_fwd / market_cap
                + C_fwd * k_fwd * retain_fwd * eta_fwd / retain_denom_fwd
            )
        else:
            R_star_fwd = C_fwd * k_fwd * M_fwd / market_cap
        gg_fwd = None
        aa_fwd = cfg.get('aa_fwd')
        if aa_fwd is not None:
            if use_v3:
                gg_fwd = (
                    aa_fwd * p_dist_fwd / market_cap
                    + aa_fwd * retain_fwd * eta_fwd / retain_denom_fwd
                )
            else:
                gg_fwd = aa_fwd * M_fwd / market_cap
        cash_dev_fwd = (R_star_fwd - gg_fwd) if gg_fwd is not None else None
        if cash_dev_fwd is not None and cash_dev_fwd >= 0.02:
            r_eff_fwd = gg_fwd
            primary_fwd = 'R_cash_fwd（现金校验降级）' if use_v3 else 'GG_fwd（现金校验降级）'
        else:
            r_eff_fwd = R_star_fwd
            primary_fwd = 'R_LT_fwd' if use_v3 else 'R*_fwd'
        KK_fwd = r_eff_fwd - II
        target_buy_fwd = price * r_eff_fwd / II
        floor_price_fwd = (price * II / r_eff_fwd) if (r_eff_fwd or 0) > 0 else None
        growth_calib = {
            'enabled': True,
            'C_fwd': C_fwd, 'k_fwd': k_fwd, 'M_fwd': M_fwd,
            'p_dist_fwd': p_dist_fwd, 'eta_fwd': eta_fwd,
            'R_star_fwd': R_star_fwd, 'GG_fwd': gg_fwd, 'cash_dev_fwd': cash_dev_fwd,
            'primary_fwd': primary_fwd, 'r_eff_fwd': r_eff_fwd,
            'KK_fwd': KK_fwd, 'target_buy_fwd': target_buy_fwd, 'floor_price_fwd': floor_price_fwd,
            'ok': bool(r_eff_fwd > II),
            'source': cfg.get('c_fwd_source', ''),
            'verified': bool(cfg.get('c_fwd_verified', False)),
        }
    else:
        growth_calib = {
            'enabled': False, 'C_fwd': None, 'k_fwd': None, 'M_fwd': None,
            'R_star_fwd': None, 'GG_fwd': None, 'cash_dev_fwd': None, 'primary_fwd': None,
            'r_eff_fwd': None, 'KK_fwd': None, 'target_buy_fwd': None, 'floor_price_fwd': None,
            'ok': False, 'source': '', 'verified': False,
        }

    # --- 经营杠杆 λ ---
    lambda_policy = cfg.get('lambda_policy', 'legacy_zero')
    if lambda_policy not in ('legacy_zero', 'historical_mean_reference'):
        raise ValueError('未知lambda_policy')
    lambda_diagnostics = diagnose_lambda(cfg)
    lam = cfg.get('lambda')
    lam_warn = ''
    if lambda_policy == 'historical_mean_reference':
        if lambda_diagnostics['raw_mean'] is None:
            raise ValueError('历史λ参考模式缺少可比收入/结余数据，不得填0')
        lam = lambda_diagnostics['raw_mean']
        lambda_reliable = lambda_diagnostics['reliable'] and cfg.get('lambda_reliable', True) is not False
        lam_warn = '' if lambda_reliable else '历史λ均值仅供条件敏感性参考，可靠性低；不用于盈利预测，k*不输出'
    elif lam is not None and lam == 0:
        lam_warn = '⚠️ λ=0 兜底，结余敏感性不随收入变化；k*无定义'
    if lambda_policy == 'legacy_zero' and lam is None:
        surv = cfg.get('surplus_series') or []
        revs = cfg.get('revenue_series') or []
        if len(surv) >= 2 and len(revs) == len(surv):
            ratios = [
                (surv[i] - surv[i + 1]) / (revs[i] - revs[i + 1])
                for i in range(len(surv) - 1)
                if revs[i] != revs[i + 1]
            ]
            if ratios:
                lam_raw = sum(ratios) / len(ratios)
                signs = {1 if r > 0 else -1 for r in ratios}
                if len(signs) > 1:
                    lam = 0.0
                    lam_warn = '⚠️ Δ结余/Δ收入符号不一致，按λ=0兜底；k*无定义'
                elif any(abs(r) > 1.5 for r in ratios):
                    lam = 0.0
                    lam_warn = '⚠️ λ段值异常，按λ=0兜底；k*无定义'
                else:
                    lam = lam_raw
            else:
                lam = 0.0
                lam_warn = '⚠️ 无有效λ，按0兜底；k*无定义'
        else:
            lam = 0.0
            lam_warn = '⚠️ λ数据不足，按0兜底；k*无定义'

    if lambda_policy == 'legacy_zero':
        lambda_reliable = bool(cfg.get('lambda_reliable', lam != 0))
        if not lambda_reliable and lam != 0:
            lam_warn = '显式λ可靠性低，仅供条件敏感性参考；k*不输出'
    if lam_warn and lam_warn not in warnings:
        warnings.append(lam_warn)

    # --- 敏感性表 ---
    single = []
    for kk in (1.0, 0.9, 0.8, 0.7):
        surplus = aa - lam * revenue * (1 - kk)
        gg = surplus * M / market_cap
        single.append({
            'k': kk, 'surplus': surplus, 'gg': gg,
            'margin': gg - II, 'floor': (price * II / gg) if (gg or 0) > 0 else None,
            'target_buy': price * gg / II,
        })
    cumulative = []
    for n in (1, 2, 3):
        kk = 0.9 ** n
        surplus = aa - lam * revenue * (1 - kk)
        gg = surplus * M / market_cap
        cumulative.append({
            'k': kk, 'surplus': surplus, 'gg': gg,
            'margin': gg - II, 'floor': (price * II / gg) if (gg or 0) > 0 else None,
            'target_buy': price * gg / II,
        })

    # --- G 敏感性网格（维持性Capex系数 G）---
    # oe_yield = OE×M/市值；网格GG仅是兼容别名，不能混同现金AA口径的GG。
    grid_gs = cfg.get('grid_gs', [0.5, 0.7, 0.9])
    g_grid = []
    for g in grid_gs:
        h = D * g
        oe_g = C + D - h
        gg_g = oe_g * M / market_cap
        g_grid.append({
            'G': g, 'H': h, 'OE': oe_g, 'GG': gg_g, 'oe_yield': gg_g, 'basis': 'OE*M/market_cap',
            'target_buy': price * gg_g / II,
            'floor_price': (price * II / gg_g) if (gg_g or 0) > 0 else None,
        })

    # 临界收入倍数 k*：GG(k*) = II
    k_star = None
    if lambda_reliable and lam != 0 and revenue and M > 0:
        k_star = 1 - (aa - II * market_cap / M) / (lam * revenue)

    # --- 绝对估值 ---
    EV = market_cap + net_debt if net_debt is not None else None
    ebitda = cfg.get('ebitda')
    fcf = cfg.get('fcf')
    book_equity = cfg.get('book_equity')
    quote_fx = cfg.get('quote_fx', 1.0)  # statement currency per one quote currency
    if not isinstance(quote_fx, (int, float)) or not math.isfinite(quote_fx) or quote_fx <= 0:
        raise ValueError('quote_fx 必须是有效正汇率')
    anchors = []
    anchor_names = []
    protection = cfg.get('cash_protection')
    if protection is not None:
        if cfg.get('cash_protection_verified') is True and cfg.get('cash_protection_source') and protection > 0:
            anchors.append(protection/shares/quote_fx)
            anchor_names.append('经核实现金保护/股')
        else:
            warnings.append('现金保护锚未核实或非正，已剔除')
    if cfg.get('net_current_assets') is not None:
        warnings.append('旧net_current_assets为营运资本，不作为现金保护锚；请核实后显式填cash_protection')
    if book_equity is not None and book_equity > 0:
        anchors.append(book_equity / shares / quote_fx)
        anchor_names.append('每股净资产')
    if cfg.get('low_10y_close') is not None:
        if cfg.get('low_10y_close_verified') is True and cfg.get('low_10y_close_source') and cfg['low_10y_close']>0:
            anchors.append(cfg['low_10y_close'])
            anchor_names.append('10年最低收盘价')
        else:
            warnings.append('十年低价缺少复权口径/独立核实证据，已剔除价格锚')
    base_price = sum(anchors) / len(anchors) if anchors else None
    premium = price / base_price - 1 if base_price else None

    # --- 价值陷阱 1：现金流趋势 ---
    trap_cash = False
    surv = cfg.get('surplus_series') or []
    if len(surv) >= 3:
        valid = [isinstance(value, (int, float)) and not isinstance(value, bool)
                 and math.isfinite(value) for value in surv]
        if not all(valid):
            warnings.append('现金结余历史含缺失值，连续下滑检查仅覆盖有效相邻年度，不能排除现金流陷阱')
        declines = [valid[i] and valid[i + 1] and surv[i] < surv[i + 1] * 0.85
                    for i in range(len(surv) - 1)]
        streak = 0
        for d in declines:
            streak = streak + 1 if d else 0
            if streak >= 2:
                trap_cash = True
                break

    formal_metrics = {
        'model_mode': 'v3_look_through' if use_v3 else 'legacy_v2_compatible',
        'industry_archetype': lt_v3['industry_archetype'],
        'industry_archetype_label': lt_v3['industry_archetype_label'],
        'net_profit_NP': lt_v3['np_base'],
        'depreciation_DA': D,
        'total_capex_intensity': G,
        'maint_capex_factor_gamma': lt_v3['maint_capex_factor_gamma'],
        'maint_capex_amount': lt_v3['maint_capex_amount'],
        'owner_earnings_OE': lt_v3['owner_earnings_OE'],
        'maint_cash_owner_earnings': lt_v3['maint_cash_owner_earnings'],
        'free_cash_surplus': aa,
        'total_distribution_ratio_p': lt_v3['total_distribution_ratio_p'],
        'dividend_payout_ratio_p_div': lt_v3['p_div'],
        'buyback_payout_ratio_p_buyback': lt_v3['p_buyback'],
        'profit_reliability_alpha': k,
        'effective_capital_return': lt_v3['roic_eff'],
        'reinvestment_efficiency_eta': lt_v3['eta'],
        'direct_distribution_return': lt_v3['r_dist'],
        'retained_compounding_return': lt_v3['r_retain'],
        'look_through_return_R_LT': lt_v3['r_lt'],
        'maint_cash_return_R_cash': lt_v3['r_cash'],
        'effective_look_through_return': lt_v3['r_eff'],
        'required_return_threshold': II,
        'margin_of_safety_MoS': lt_v3['margin_of_safety_KK'],
        'target_buy_price': lt_v3['target_buy'],
        'downside_floor_price': lt_v3['floor_price'],
        'cash_quality_passed': lt_v3['cash_quality_passed'],
        'cash_coverage': lt_v3['cash_coverage'],
    }

    if use_v3:
        H_out = lt_v3['maint_capex_amount']
        oe_out = lt_v3['owner_earnings_OE']
        R_star_out = lt_v3['r_lt']
        GG_out = lt_v3['r_cash']
        cash_dev_out = lt_v3['cash_dev']
        primary_out = lt_v3['primary']
        r_eff_out = lt_v3['r_eff']
        JJ_out = lt_v3['jj']
        KK_out = lt_v3['margin_of_safety_KK']
        target_buy_out = lt_v3['target_buy']
        floor_price_out = lt_v3['floor_price']
    else:
        H_out = H
        oe_out = oe
        R_star_out = R_star
        GG_out = GG
        cash_dev_out = cash_dev
        primary_out = primary
        r_eff_out = r_eff
        JJ_out = JJ
        KK_out = KK
        target_buy_out = target_buy
        floor_price_out = floor_price

    out = {
        'meta': {k: cfg.get(k) for k in ('company', 'code', 'date')},
        'model_mode': 'v3_look_through' if use_v3 else 'legacy_v2',
        'H': H_out, 'OE': oe_out,
        'k': k, 'R_star': R_star_out, 'R': R, 'GG': GG_out, 'HH': HH, 'cash_dev': cash_dev_out,
        'primary': primary_out, 'r_eff': r_eff_out,
        'II': II, 'JJ': JJ_out, 'KK': KK_out,
        'target_buy': target_buy_out, 'floor_price': floor_price_out,
        'lambda': lam, 'lambda_warning': lam_warn,
        'lambda_policy': lambda_policy, 'lambda_reliable': lambda_reliable,
        'lambda_diagnostics': lambda_diagnostics,
        'single_year': single, 'cumulative': cumulative,
        'k_star': k_star,
        'EV': EV, 'cash_balance': cash, 'net_debt': net_debt, 'net_cash_actual': -net_debt if net_debt is not None else None,
        'warnings': warnings, 'g_grid_basis': 'OE*M/market_cap; GG is a legacy alias of oe_yield, not cash-AA GG',
        'ev_ebitda': EV / ebitda if EV is not None and ebitda is not None and ebitda > 0 else None,
        'cash_adj_pe': (market_cap - cash) / aa if cash is not None and aa > 0 else None,
        'fcf_yield': fcf / market_cap if fcf is not None else None,
        'net_debt_ebitda': net_debt / ebitda if net_debt is not None and ebitda is not None and ebitda > 0 else None,
        'goodwill_assets': cfg['goodwill'] / cfg['total_assets'] if cfg.get('goodwill') is not None and cfg.get('total_assets') else None,
        'dividend_yield': cfg.get('dps', 0.0) / price if cfg.get('dps') else None,
        'anchors': list(zip(anchor_names, anchors)) if anchors else [],
        'base_price': base_price, 'premium': premium,
        'trap_cash_triggered': trap_cash,
        'g_grid': g_grid,
        'growth_calib': growth_calib,
        'look_through_v3': lt_v3,
        'formal_metrics': formal_metrics,
        'legacy_v2': legacy_snapshot,
    }
    return out


def render(o: dict, show_grid: bool = True) -> str:
    from chart_numbers import format_amount
    amount = lambda scaled: format_amount(scaled * 1e6)
    m = o['meta']
    fm = o.get('formal_metrics') or {}
    lt = o.get('look_through_v3') or {}
    L = []
    L.append('=' * 66)
    L.append(' 穿透回报率法（Look-Through Return Method v3）估值报告 ｜ {} {} {}'.format(
        m.get('company', ''), m.get('code', ''), m.get('date', '')))
    L.append('=' * 66)
    if fm:
        L.append(' 行业原型：{} ({}) ｜ 模型口径：{}'.format(
            fm.get('industry_archetype_label', '—'), fm.get('industry_archetype', '—'), o.get('model_mode', 'legacy_v2')))
        L.append(' 账面股东盈余 OE = NP + D&A − Capex_maint = {}  (Capex_maint={}，γ_maint={:.2f})'.format(
            amount(fm['owner_earnings_OE']), amount(fm['maint_capex_amount']), fm['maint_capex_factor_gamma']))
        L.append(' 维持性现金底座 OE_cash = {}  ｜ 现金覆盖率 Cov_cash = {:.2f}x ({})'.format(
            amount(lt['maint_cash_owner_earnings']), lt['cash_coverage'],
            '含金量合格' if lt['cash_quality_passed'] else '现金含金量不足'))
        roic_txt = pct(lt['roic_eff']) if lt.get('roic_eff') is not None else '未知'
        L.append(' 广义分配率 p_dist = {} (分红{} + 回购{}) ｜ ROIC_eff = {} ｜ 留存转化率 η = {:.2f}'.format(
            pct(lt['total_distribution_ratio_p']), pct(lt['p_div']), pct(lt['p_buyback']), roic_txt, lt['eta']))
        L.append(' 穿透拆分：直接分配 R_dist = {} + 留存复利 R_retain = {} → 广义穿透 R_LT = {}'.format(
            pct(lt['r_dist']), pct(lt['r_retain']), pct(lt['r_lt'])))
        L.append(' 现金穿透校验 R_cash = {} ｜ 有效穿透回报率 R_eff(v3) = {}  ({})'.format(
            pct(lt['r_cash']), pct(lt['r_eff']), lt['primary']))
        L.append(' v3 参考锚：安全边际 MoS = {} ｜ 穿透目标买入价 = {} 元 ｜ 下行保护价 = {} 元'.format(
            pct2(lt['margin_of_safety_KK']), fmt2(lt['target_buy']), fmt2(lt['floor_price'])))
        L.append('── 现行有效主输出（{}）──'.format(o.get('model_mode', 'v3_look_through')))
        if o.get('model_mode') != 'v3_look_through':
            L.append(' 历史全口径 OE = NP + D&A − H_total = {}  (H_total={})'.format(
                amount(o['OE']), amount(o['H'])))
    else:
        L.append(' 账面股东盈余 OE = NP + D&A − Capex_maint = {}  (Capex_maint={})'.format(
            amount(o['OE']), amount(o['H'])))
    L.append(' 主穿透回报率 R_LT/R* = {}   （确定性系数 α={}）'.format(pct(o['R_star']), o['k']))
    L.append(' 现金校验 R_cash/GG = {}   （现金偏差 Δc = {}；有效口径：{}）'.format(
        pct(o['GG']), pct2(o['cash_dev']), o['primary']))
    L.append(' 账面未折算分红口径 R = {}   （账面-现金偏差 = {}）'.format(pct(o['R']), pct2(o['HH'])))
    L.append(' 要求回报门槛 R_req(II) = {}   （按市场下限与无风险利率加成配置）'.format(pct(o['II'])))
    L.append(' 穿透安全边际 MoS(KK) = {}   （基础利差={}，含周期修正）'.format(pct2(o['KK']), pct2(o['JJ'])))
    L.append(' 穿透目标买入价 P_buy = {} 元   ｜ 下行保护参考价 P_floor = {} 元   （口径：{}）'.format(
        fmt2(o['target_buy']), fmt2(o['floor_price']), o['primary']))
    gc = o.get('growth_calib') or {}
    if gc.get('enabled'):
        src = '（' + gc['source'] + '）' if gc.get('source') else ''
        ver = '已由实际数据验证 → 可升级主轨' if gc.get('verified') else '待实际数据验证（升级条款未触发）'
        L.append('── 穿透回报率轨 · 前瞻盈利校准（forward）──')
        L.append(' NP_fwd = {} ｜ α_fwd = {:.2f} ｜ p_dist_fwd = {:.4f}  {}'.format(
            amount(gc['C_fwd']), gc['k_fwd'], gc['M_fwd'], src))
        L.append(' 前瞻穿透 R_fwd = {}  ｜ 前瞻现金校验 = {}  ｜ 有效口径：{}'.format(
            pct(gc['r_eff_fwd']), pct(gc['GG_fwd']) if gc['GG_fwd'] is not None else '—', gc['primary_fwd']))
        L.append(' 前瞻安全边际 MoS_fwd = {}  ｜ 前瞻目标买入价 = {} 元  ｜ 前瞻保护价 = {} 元'.format(
            pct2(gc['KK_fwd']), fmt2(gc['target_buy_fwd']), fmt2(gc['floor_price_fwd'])))
        L.append(' 前瞻验证买入区间 = [{:.2f}, {:.2f}] 元（即期基线 ~ 前瞻校准上限）｜ 升级：{}'.format(
            o['target_buy'], gc['target_buy_fwd'], ver))
    L.append(' 经营杠杆 λ = {:.4f}  {}'.format(o['lambda'], o['lambda_warning']))
    if not o.get('lambda_reliable', True):
        L.append(' λ低可靠性：情景是给定系数的条件演算，不代表已识别收入与现金的因果关系。')
    L.append('')
    L.append('── 单年收入下滑情景（自由现金结余口径 R_cash(k)，校验维度）──')
    L.append('  情景    现金结余(亿元/万元，逐项标注)   R_cash(k)   vs门槛    保护价')
    for r in o['single_year']:
        L.append('  {:.1f}×     {}     {}   {}   {}'.format(
            r['k'], amount(r['surplus']), pct(r['gg']), pct2(r['margin']), fmt2(r['floor'])))
    L.append('── 逐年累积下滑情景（每年-10%）──')
    for r in o['cumulative']:
        L.append('  {:.3f}×   {}     {}   {}   {}'.format(
            r['k'], amount(r['surplus']), pct(r['gg']), pct2(r['margin']), fmt2(r['floor'])))
    if o['k_star'] is not None:
        note = '（<0：外推失效，解读为安全边际极充裕）' if o['k_star'] < 0 else ''
        L.append(' 临界收入倍数 k* = {:.2f} {}'.format(o['k_star'], note))
    if show_grid and o.get('g_grid'):
        L.append('')
        L.append('── 维持性资本开支系数网格（γ_maint；口径：OE收益率=OE×p_div/市值，与自由现金结余校验并列）──')
        L.append('  γ_maint   Capex_maint     OE          OE收益率   目标买入价   保护价')
        for r in o['g_grid']:
            L.append('   {:.2f}    {}   {}   {}   {:>8}   {:>8}'.format(
                r['G'], amount(r['H']), amount(r['OE']), pct(r['GG']), fmt2(r['target_buy']), fmt2(r['floor_price'])))
    L.append('')
    L.append('── 绝对估值与资产锚 ──')
    L.append(' EV = {}'.format(amount(o['EV']) if o['EV'] is not None else '—'))
    if o['ev_ebitda'] is not None:
        L.append(' EV/EBITDA = {:.2f}x'.format(o['ev_ebitda']))
    L.append(' 扣除现金PE = {}x   （(市值−货币资金)/AA；AA非正时不适用）'.format(fmt2(o['cash_adj_pe'])))
    if o['fcf_yield'] is not None:
        L.append(' FCF收益率 = {}'.format(pct(o['fcf_yield'])))
    if o['net_debt_ebitda'] is not None:
        L.append(' 净负债/EBITDA = {:.2f}x'.format(o['net_debt_ebitda']))
    if o['goodwill_assets'] is not None:
        L.append(' 商誉/总资产 = {}'.format(pct(o['goodwill_assets'])))
    if o['dividend_yield'] is not None:
        L.append(' 股息率 = {}'.format(pct(o['dividend_yield'])))
    if o['anchors']:
        L.append(' 基准价锚: ' + ' ｜ '.join('{}={:.2f}'.format(n, v) for n, v in o['anchors']))
        L.append(' 综合基准价 = {:.2f} 元  ｜ 当前价溢价 = {}'.format(o['base_price'], pct(o['premium'])))
    trap_txt = '是 ⚠️' if o['trap_cash_triggered'] else '否'
    L.append(' 现金流陷阱触发(结余连续≥2年降>15%): ' + trap_txt)
    for warning in o.get('warnings', []):
        L.append(' ⚠️ ' + warning)
    L.append('=' * 66)
    return '\n'.join(L)


def selftest() -> None:
    cfg = {
        'company': '凌霄泵业', 'code': '002884', 'date': '2026-08-07',
        'price': 16.23, 'market_cap': 5805.19, 'shares': 357.68,
        'net_profit_C': 454.91, 'depreciation_D': 32.70, 'capex_ratio_G': 0.9,
        'payout_M': 0.8423, 'profit_discount_k': 0.8, 'aa_2y': 432.41, 'rf': 0.0165,
        'cycle_adjust_pct': 0.0, 'lambda': 0.0603, 'base_revenue': 1722.18,
        'surplus_series': [450.01, 414.80, 329.17, 280.72],
        'cash_balance': 1388.84, 'interest_bearing_debt': 0.0,
        'ebitda': 519.0, 'fcf': 318.7, 'goodwill': 0.0, 'total_assets': 3755.0,
        'dps': 1.00, 'cash_protection': 1388.84, 'cash_protection_verified': True, 'cash_protection_source':'自检隔离样例：已核实现金保护', 'book_equity': 2414.0,
        'low_10y_close': 12.57, 'low_10y_close_verified': True, 'low_10y_close_source':'自检隔离样例：复权核实',
        'net_profit_C_fwd': 500.0, 'payout_M_fwd': 0.8423, 'profit_discount_k_fwd': 0.8,
        'aa_fwd': 450.0, 'c_fwd_source': '自检：前瞻净利 5.00 亿（示例）',
    }
    o = compute(cfg)
    o_v3 = compute(cfg, v3=True)
    checks = [
        ('OE', abs(o['OE'] - 458.18) < 0.01),
        ('R_star', abs(o['R_star'] - 0.0528) < 0.0005),
        ('R', abs(o['R'] - 0.0660) < 0.0005),
        ('GG', abs(o['GG'] - 0.0627) < 0.0005),
        ('cash_dev', abs(o['cash_dev'] + 0.0099) < 0.0005),
        ('primary', o['primary'] == 'R*'),
        ('II', abs(o['II'] - 0.0365) < 1e-9),
        ('KK', abs(o['KK'] - 0.0163) < 0.0005),
        ('target_buy', abs(o['target_buy'] - 23.48) < 0.02),
        ('floor_price', abs(o['floor_price'] - 11.22) < 0.02),
        ('s0.9', abs(o['single_year'][1]['surplus'] - 422.03) < 0.01),
        ('g0.9', abs(o['single_year'][1]['gg'] - 0.0612) < 0.0005),
        ('floor0.9', abs(o['single_year'][1]['floor'] - 9.68) < 0.02),
        ('k_star<0', o['k_star'] is not None and o['k_star'] < 0),
        ('cash_adj_pe', abs(o['cash_adj_pe'] - 10.21) < 0.05),
        ('base_price', abs(o['base_price'] - 7.74) < 0.02),
        ('premium', abs(o['premium'] - 1.098) < 0.005),
        ('div_yield', abs(o['dividend_yield'] - 0.0616) < 0.0005),
        ('trap', o['trap_cash_triggered'] is False),
        # 前瞻校准轨（自检：C_fwd=500, k_fwd=0.8, M_fwd=0.8423）
        ('gc_enabled', o['growth_calib']['enabled'] is True),
        ('gc_Rstar', abs(o['growth_calib']['R_star_fwd'] - 0.05805) < 0.0005),
        ('gc_GG', abs(o['growth_calib']['GG_fwd'] - 0.06532) < 0.0005),
        ('gc_KK', abs(o['growth_calib']['KK_fwd'] - 0.02155) < 0.0005),
        ('gc_target', abs(o['growth_calib']['target_buy_fwd'] - 25.81) < 0.05),
        # G 敏感性网格（凌霄泵业：H=D×G、OE=C+D−H、GG=OE×M/市值）
        ('grid_len', len(o['g_grid']) == 3),
        ('grid_G0.5_H', abs(o['g_grid'][0]['H'] - 16.35) < 0.01),
        ('grid_G0.5_OE', abs(o['g_grid'][0]['OE'] - 471.26) < 0.01),
        ('grid_G0.5_GG', abs(o['g_grid'][0]['GG'] - 0.06838) < 0.0005),
        ('grid_G0.9_OE', abs(o['g_grid'][2]['OE'] - 458.18) < 0.01),
        ('grid_G0.9_GG', abs(o['g_grid'][2]['GG'] - 0.06648) < 0.0005),
        # v3 正式化字段与留存复利核验
        ('v3_formal_keys', o_v3['formal_metrics']['look_through_return_R_LT'] >= o['R_star']),
        ('v3_cash_quality', o_v3['look_through_v3']['cash_quality_passed'] is True),
        ('v3_eta_positive', o_v3['look_through_v3']['eta'] > 0.5),
    ]
    print(render(o_v3))
    failed = [name for name, ok in checks if not ok]
    if failed:
        print('\n❌ 自检失败项: ' + str(failed))
        sys.exit(1)
    print('\n✅ 自检通过：legacy 基准与 v3 正式穿透口径均一致')


def main() -> int:
    ap = argparse.ArgumentParser(description='穿透回报率法（Look-Through Return Method v3）估值计算器')
    ap.add_argument('--config', type=Path, help='输入 JSON 配置')
    ap.add_argument('--v3', action='store_true', help='强制以 v3 广义穿透回报率作为主输出口径')
    ap.add_argument('--legacy', action='store_true', help='强制使用旧版纯分红口径作主输出（历史兼容）')
    ap.add_argument('--json', action='store_true', help='纯 JSON 输出到 stdout（人类可读文本 → stderr）')
    ap.add_argument('--out', type=Path, help='JSON 输出文件路径（推荐，避免 PowerShell `>` 重定向产生 UTF-16 文件）')
    ap.add_argument('--no-grid', action='store_true', help='跳过维持性资本开支敏感性网格的渲染输出（JSON 的 g_grid 恒在）')
    ap.add_argument('--selftest', action='store_true', help='用凌霄泵业数据自检（含 v3 校验）')
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return 0
    if not args.config:
        ap.error('需要 --config 或 --selftest')
    cfg = json.loads(args.config.read_text(encoding='utf-8'))
    v3_flag = True if args.v3 else (False if args.legacy else None)
    out = compute(cfg, v3=v3_flag)
    text = render(out, show_grid=not args.no_grid)
    if args.json:
        # 唯一真值：stdout 只出纯 JSON（可 > 穿透回报率_输出.json 供机器解析）；文本走 stderr 不污染 stdout
        sys.stderr.write(text + '\n')
        payload = json.dumps(out, ensure_ascii=False, indent=2)
        if args.out:
            args.out.write_text(payload, encoding='utf-8')
            sys.stderr.write(f'[OK] JSON 已写入 {args.out}（UTF-8，无需 shell 重定向）\n')
        else:
            print(payload)
    else:
        print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
