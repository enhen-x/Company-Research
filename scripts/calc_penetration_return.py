#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''龟龟投资策略 v2 · Phase 3 穿透回报率估值计算器（确定性，仅标准库）

用法：
    python calc_penetration_return.py --config 输入.json
    python calc_penetration_return.py --config 输入.json --json   # 纯 JSON → stdout（人类可读文本 → stderr），可重定向 > 输出.json
    python calc_penetration_return.py --selftest                  # 用凌霄泵业数据自检

输出：
    主穿透回报率 R* = C×k×M/市值（主估值输入）；GG = AA×M/市值 为现金结余校验口径（现金校验偏差 Δc=R*−GG≥2pct 时降级为 GG）；
    成长校准轨（2026-08-21 新增）：提供 net_profit_C_fwd 时输出 forward 口径
        R*_fwd = C_fwd×k_fwd×M_fwd/市值、KK_fwd、目标买入价_fwd（解决高成长标的"永远买不到"，
        纪律：评级锚仍为保守轨 trailing，成长校准轨只给"成长验证买入区"与升级触发，见 methodology §2.1）；
    G 敏感性网格（g_grid）默认输出——维持性Capex系数 G 的敏感性（近3年 Capex/D&A 极差 >1.0 时报告必出，
    methodology §1）。口径：oe_yield=OE×M/市值（随 G 变），与基准 GG=AA×M/市值并列、禁止混用；网格GG仅为兼容别名。
    --no-grid 仅跳过渲染，JSON 的 g_grid 恒在（保证报告数字可脚本复算）。

输入 JSON 字段（金额单位：百万元；比率用小数；每股用元）：
    company / code / date / price / market_cap / shares
    net_profit_C / depreciation_D / capex_ratio_G / profit_discount_k（利润折扣系数，默认0.8，0.7~0.9 按可预测性取档）
    payout_M（支付率保守锚：承诺/公告最低值优先；无承诺取近3年最低档 M_min，均值仅交叉参考）
    net_profit_C_fwd（可选，前瞻盈利，百万元；提供时启用成长校准轨）
    payout_M_fwd（可选，前瞻支付率锚，默认=M） / profit_discount_k_fwd（可选，前瞻折扣，默认=min(k,0.85)）
    aa_fwd（可选，前瞻真实可支配现金，百万元；现金校验） / c_fwd_source（可选，前瞻盈利来源标注）
    c_fwd_verified（可选，bool；是否已由实际数据验证——升级条款触发标记）
    aa_2y（真实可支配现金，默认口径） / aa_all（可选，5年均值对比）
    rf / cycle_adjust_pct（弱周期=0）
    lambda（经营杠杆，可省略：提供 surplus_series+revenue_series 时自动计算）
    base_revenue / surplus_series（由新到旧，可选）/ revenue_series（可选）
    cash_balance（货币资金，未扣债）/ net_debt（有息负债−货币资金，校验字段）/ interest_bearing_debt / ebitda（可选）/ fcf（可选）
    goodwill / total_assets（可选）/ dps / working_capital / book_equity（普通股权益，可选）
    cash_protection / low_10y_close：正值且对应 *_verified=true、*_source非空才启用价格锚

公式与阈值见 ../references/methodology.md；数字示例见该文件 §12。
'''

from __future__ import annotations

import math
import argparse
import json
import sys
from pathlib import Path


def pct(x: float) -> str:
    return '{:.2f}%'.format(x * 100)


def fmt2(x) -> str:
    return '{:.2f}'.format(x) if x is not None else '—'


def pct2(x: float) -> str:
    '''带正负号、保留2位的百分点文本'''
    return '{:+.2f} pct'.format(x * 100)


def compute(cfg: dict) -> dict:
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
    # --- 穿透回报率 ---
    H = D * G
    oe = C + D - H
    k = cfg.get('profit_discount_k', 0.8)   # 利润折扣系数（默认0.8，0.7~0.9，按可预测性取档，保守方向取小值）
    R_star = C * k * M / market_cap         # 主穿透回报率（打折净利润 × 最低支付率）——主估值输入
    R = C * M / market_cap                  # 账面口径（交叉校验）
    GG = aa * M / market_cap                # 现金结余口径（校验：验证 R* 有真钱支撑）
    HH = R - GG                             # 账面-现金偏差（|HH|≥2pct → 专项调查）
    cash_dev = R_star - GG                  # 现金校验偏差：≥2pct → 现金验证失败，有效口径降级为 GG
    if cash_dev >= 0.02:
        primary = 'GG（现金校验降级）'
        r_eff = GG
    else:
        primary = 'R*'
        r_eff = R_star
    ii_floor = cfg.get('ii_floor', 0.035)  # 市场门槛下限：A股0.035 / 港股0.05 / 美股0.04（methodology §1）
    rf_margin = cfg.get('rf_margin', 0.02)  # Rf 加成：A股+2pct / 港股+3pct / 美股+2pct
    II = max(ii_floor, rf + rf_margin)
    JJ = r_eff - II
    KK = JJ + cycle_adj  # 弱周期 cycle_adj=0
    target_buy = price * r_eff / II  # 目标买入价（主口径）：r_eff=II 时的股价（最高可买价/卖出触发参考）
    floor_price = (price * II / r_eff) if (r_eff or 0) > 0 else None  # 门槛价格（下行保护参考）：r_eff<=0（如零派息）时无定义置 None

    # --- 龟龟轨 · 成长校准（forward，2026-08-21 新增）---
    # 触发：net_profit_C_fwd 有证据支撑（公司指引/券商一致预期下沿/自建驱动桥）且 > trailing C；
    # 纪律：评级锚仍为保守轨 trailing；本轨只输出"成长验证买入区"与升级触发参考（methodology §2.1）。
    C_fwd = cfg.get('net_profit_C_fwd')
    if C_fwd is not None:
        k_fwd = cfg.get('profit_discount_k_fwd', min(k, 0.85))
        M_fwd = cfg.get('payout_M_fwd', M)
        R_star_fwd = C_fwd * k_fwd * M_fwd / market_cap
        gg_fwd = None
        aa_fwd = cfg.get('aa_fwd')
        if aa_fwd is not None:
            gg_fwd = aa_fwd * M_fwd / market_cap
        cash_dev_fwd = (R_star_fwd - gg_fwd) if gg_fwd is not None else None
        if cash_dev_fwd is not None and cash_dev_fwd >= 0.02:
            r_eff_fwd = gg_fwd
            primary_fwd = 'GG_fwd（现金校验降级）'
        else:
            r_eff_fwd = R_star_fwd
            primary_fwd = 'R*_fwd'
        KK_fwd = r_eff_fwd - II
        target_buy_fwd = price * r_eff_fwd / II
        floor_price_fwd = (price * II / r_eff_fwd) if (r_eff_fwd or 0) > 0 else None
        growth_calib = {
            'enabled': True,
            'C_fwd': C_fwd, 'k_fwd': k_fwd, 'M_fwd': M_fwd,
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
    lam = cfg.get('lambda')
    lam_warn = ''
    if lam is not None and lam == 0:
        lam_warn = '⚠️ λ=0 兜底，结余敏感性不随收入变化；k*无定义'
    if lam is None:
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

    # --- 敏感性表 ---
    single = []
    for kk in (1.0, 0.9, 0.8, 0.7):
        surplus = aa - lam * revenue * (1 - kk)
        gg = surplus * M / market_cap
        single.append({
            'k': kk, 'surplus': surplus, 'gg': gg,
            'margin': gg - II, 'floor': (price * II / gg) if (gg or 0) > 0 else None,
        })
    cumulative = []
    for n in (1, 2, 3):
        kk = 0.9 ** n
        surplus = aa - lam * revenue * (1 - kk)
        gg = surplus * M / market_cap
        cumulative.append({
            'k': kk, 'surplus': surplus, 'gg': gg,
            'margin': gg - II, 'floor': (price * II / gg) if (gg or 0) > 0 else None,
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
    if lam != 0 and revenue and M > 0:
        k_star = 1 - (aa - II * market_cap / M) / (lam * revenue)

    # --- 绝对估值 ---
    EV = market_cap + net_debt if net_debt is not None else None
    ebitda = cfg.get('ebitda')
    fcf = cfg.get('fcf')
    book_equity = cfg.get('book_equity')
    anchors = []
    anchor_names = []
    protection = cfg.get('cash_protection')
    if protection is not None:
        if cfg.get('cash_protection_verified') is True and cfg.get('cash_protection_source') and protection > 0:
            anchors.append(protection/shares)
            anchor_names.append('经核实现金保护/股')
        else:
            warnings.append('现金保护锚未核实或非正，已剔除')
    if cfg.get('net_current_assets') is not None:
        warnings.append('旧net_current_assets为营运资本，不作为现金保护锚；请核实后显式填cash_protection')
    if book_equity is not None and book_equity > 0:
        anchors.append(book_equity / shares)
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
        declines = [surv[i] < surv[i + 1] * 0.85 for i in range(len(surv) - 1)]
        streak = 0
        for d in declines:
            streak = streak + 1 if d else 0
            if streak >= 2:
                trap_cash = True
                break

    out = {
        'meta': {k: cfg.get(k) for k in ('company', 'code', 'date')},
        'H': H, 'OE': oe,
        'k': k, 'R_star': R_star, 'R': R, 'GG': GG, 'HH': HH, 'cash_dev': cash_dev,
        'primary': primary, 'r_eff': r_eff,
        'II': II, 'JJ': JJ, 'KK': KK,
        'target_buy': target_buy, 'floor_price': floor_price,
        'lambda': lam, 'lambda_warning': lam_warn,
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
    }
    return out


def render(o: dict, show_grid: bool = True) -> str:
    from chart_numbers import format_amount
    amount = lambda scaled: format_amount(scaled * 1e6)
    m = o['meta']
    L = []
    L.append('=' * 62)
    L.append(' 龟龟投资策略 v2 · 穿透回报率估值 ｜ {} {} {}'.format(
        m.get('company', ''), m.get('code', ''), m.get('date', '')))
    L.append('=' * 62)
    L.append(' Owner Earnings = C + D − H = {}  (H={})'.format(amount(o['OE']), amount(o['H'])))
    L.append(' 主穿透回报率 R* = {}   （C×k×M/市值，k={}，主估值输入）'.format(pct(o['R_star']), o['k']))
    L.append(' 现金校验 GG = {}   （AA×M/市值，校验口径）'.format(pct(o['GG'])))
    L.append(' 现金校验偏差 Δc = {}   （≥2pct → 降级为 GG；当前有效口径：{}）'.format(pct2(o['cash_dev']), o['primary']))
    L.append(' 账面口径 R = {}   （C×M/市值，交叉校验）'.format(pct(o['R'])))
    L.append(' 账面-现金偏差 HH = {}   （|HH|≥2pct 需专项调查）'.format(pct2(o['HH'])))
    L.append(' 门槛 II = {}   （max(3.5%, Rf+2%)）'.format(pct(o['II'])))
    L.append(' 安全边际 KK = {}   （JJ={}，基于主口径，含周期修正）'.format(pct2(o['KK']), pct2(o['JJ'])))
    L.append(' 目标买入价 = {} 元   ｜ 门槛价格 = {} 元   （口径：{}）'.format(fmt2(o['target_buy']), fmt2(o['floor_price']), o['primary']))
    gc = o.get('growth_calib') or {}
    if gc.get('enabled'):
        src = '（' + gc['source'] + '）' if gc.get('source') else ''
        ver = '已由实际数据验证 → 可升级主轨' if gc.get('verified') else '待实际数据验证（升级条款未触发）'
        L.append('── 龟龟轨 · 成长校准（forward）──')
        L.append(' C_fwd = {} ｜ k_fwd = {:.2f} ｜ M_fwd = {:.4f}  {}'.format(
            amount(gc['C_fwd']), gc['k_fwd'], gc['M_fwd'], src))
        L.append(' 成长校准 R*_fwd = {}  ｜ 现金校验 GG_fwd = {}  ｜ 有效口径：{}'.format(
            pct(gc['r_eff_fwd']), pct(gc['GG_fwd']) if gc['GG_fwd'] is not None else '—', gc['primary_fwd']))
        L.append(' 成长校准 KK_fwd = {}  ｜ 目标买入价_fwd = {} 元  ｜ 门槛价格_fwd = {} 元'.format(
            pct2(gc['KK_fwd']), fmt2(gc['target_buy_fwd']), fmt2(gc['floor_price_fwd'])))
        L.append(' 成长验证买入区 = [{:.2f}, {:.2f}] 元（保守轨下限 ~ 成长校准轨上限）｜ 升级：{}'.format(
            o['target_buy'], gc['target_buy_fwd'], ver))
    L.append(' 经营杠杆 λ = {:.4f}  {}'.format(o['lambda'], o['lambda_warning']))
    L.append('')
    L.append('── 单年下滑情景（现金结余口径 GG(k)=AA(k)×M/市值，校验维度）──')
    L.append('  情景    结余(亿元/万元，逐项标注)   GG(k)    vs门槛    门槛价格')
    for r in o['single_year']:
        L.append('  {:.1f}×     {}     {}   {}   {}'.format(
            r['k'], amount(r['surplus']), pct(r['gg']), pct2(r['margin']), fmt2(r['floor'])))
    L.append('── 逐年累积情景（每年-10%）──')
    for r in o['cumulative']:
        L.append('  {:.3f}×   {}     {}   {}   {}'.format(
            r['k'], amount(r['surplus']), pct(r['gg']), pct2(r['margin']), fmt2(r['floor'])))
    if o['k_star'] is not None:
        note = '（<0：外推失效，解读为安全边际极充裕）' if o['k_star'] < 0 else ''
        L.append(' 临界收入倍数 k* = {:.2f} {}'.format(o['k_star'], note))
    if show_grid and o.get('g_grid'):
        L.append('')
        L.append('── G 敏感性网格（维持性Capex系数 G；口径：OE收益率=OE×M/市值，随 G 变；现金 GG=AA×M/市值 见上）──')
        L.append('   G      H(亿元/万元)    OE(亿元/万元)     OE收益率  目标买入价  门槛价格')
        for r in o['g_grid']:
            L.append('  {:.2f}   {}   {}   {}   {:>7}   {:>7}'.format(
                r['G'], amount(r['H']), amount(r['OE']), pct(r['GG']), fmt2(r['target_buy']), fmt2(r['floor_price'])))
    L.append('')
    L.append('── 绝对估值 ──')
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
    L.append('=' * 62)
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
        # 成长校准轨（自检：C_fwd=500, k_fwd=0.8, M_fwd=0.8423）
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
    ]
    print(render(o))
    failed = [name for name, ok in checks if not ok]
    if failed:
        print('\n❌ 自检失败项: ' + str(failed))
        sys.exit(1)
    print('\n✅ 自检通过：输出与凌霄泵业分析报告一致')


def main() -> int:
    ap = argparse.ArgumentParser(description='龟龟投资策略 v2 穿透回报率计算器')
    ap.add_argument('--config', type=Path, help='输入 JSON 配置')
    ap.add_argument('--json', action='store_true', help='纯 JSON 输出到 stdout（人类可读文本 → stderr）')
    ap.add_argument('--out', type=Path, help='JSON 输出文件路径（推荐，避免 PowerShell `>` 重定向产生 UTF-16 文件；2026-08-23 中远海控批次事故）')
    ap.add_argument('--no-grid', action='store_true', help='跳过 G 敏感性网格的渲染输出（JSON 的 g_grid 恒在）')
    ap.add_argument('--selftest', action='store_true', help='用凌霄泵业数据自检')
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return 0
    if not args.config:
        ap.error('需要 --config 或 --selftest')
    cfg = json.loads(args.config.read_text(encoding='utf-8'))
    out = compute(cfg)
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
