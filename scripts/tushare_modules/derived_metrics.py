"""Turtle Investment Framework - DerivedMetricsMixin.

Section 17 derived metrics: financial trends, Factor 2/3/4 computations.
"""

import pandas as pd

from format_utils import format_number, format_table, format_header


class DerivedMetricsMixin:
    """Mixin providing derived metrics computation for TushareClient."""

    def _compute_financial_trends(self) -> str | None:
        """Compute §17.1: Financial trend summary (CAGR, debt ratios, net cash, payout)."""
        income_df = self._get_annual_df("income")
        bs_df = self._get_annual_df("balance_sheet")

        if income_df.empty or len(income_df) < 2:
            return None

        years_labels = [str(r["end_date"])[:4] for _, r in income_df.iterrows()]
        n_years = len(years_labels)

        lines = [format_header(3, "17.1 财务趋势速览"), ""]

        # --- Revenue & Net Profit series ---
        rev_series = [(y, self._safe_float(r.get("revenue"))) for y, (_, r) in zip(years_labels, income_df.iterrows())]
        np_series = [(y, self._safe_float(r.get("n_income_attr_p"))) for y, (_, r) in zip(years_labels, income_df.iterrows())]

        # CAGR calculation
        def _cagr(series: list[tuple[str, float | None]]) -> str:
            vals = [v for _, v in series if v is not None and v > 0]
            if len(vals) < 2:
                return "—"
            # series is desc order: [latest, ..., oldest]
            latest, oldest = vals[0], vals[-1]
            n = len(vals) - 1
            if oldest <= 0:
                return "—"
            cagr = (latest / oldest) ** (1 / n) - 1
            return f"{cagr * 100:.2f}%"

        rev_cagr = _cagr(rev_series)
        np_cagr = _cagr(np_series)

        # --- Interest-bearing debt per year ---
        def _interest_bearing_debt(row) -> float | None:
            components = ["st_borr", "lt_borr", "bond_payable", "non_cur_liab_due_1y"]
            total = 0.0
            any_valid = False
            for c in components:
                v = self._safe_float(row.get(c))
                if v is not None:
                    total += v
                    any_valid = True
            return total if any_valid else None

        debt_series = []  # (year, debt_raw)
        debt_ratio_series = []  # (year, ratio_pct)
        net_cash_series = []  # (year, net_cash_raw)
        if not bs_df.empty:
            for _, r in bs_df.iterrows():
                year = str(r["end_date"])[:4]
                debt = _interest_bearing_debt(r)
                ta = self._safe_float(r.get("total_assets"))
                cash = self._safe_float(r.get("money_cap"))
                debt_series.append((year, debt))
                if debt is not None and ta and ta > 0:
                    debt_ratio_series.append((year, debt / ta * 100))
                else:
                    debt_ratio_series.append((year, None))
                if cash is not None and debt is not None:
                    net_cash_series.append((year, cash - debt))
                else:
                    net_cash_series.append((year, None))

        # --- Payout ratio per year ---
        payout_lookup = self._get_payout_by_year()
        payout_series = [(y, payout_lookup.get(y)) for y, _ in np_series]

        # --- Build table ---
        # Use income years as primary (most complete)
        def _fmt_val(val: float | None, divider: float = 1e6, is_pct: bool = False) -> str:
            if val is None:
                return "—"
            if is_pct:
                return f"{val:.2f}"
            return format_number(val, divider=divider)

        def _lookup(series: list[tuple[str, float | None]], year: str) -> float | None:
            for y, v in series:
                if y == year:
                    return v
            return None

        headers = ["指标"] + years_labels + ["5年CAGR"]
        rows = []

        # Revenue
        row = [f"营业收入（{self._unit_label()}）"]
        for y, v in rev_series:
            row.append(_fmt_val(v))
        row.append(rev_cagr)
        rows.append(row)

        # Net profit
        row = [f"归母净利润（{self._unit_label()}）"]
        for y, v in np_series:
            row.append(_fmt_val(v))
        row.append(np_cagr)
        rows.append(row)

        # Interest-bearing debt
        row = [f"有息负债（{self._unit_label()}）"]
        for y in years_labels:
            row.append(_fmt_val(_lookup(debt_series, y)))
        row.append("—")
        rows.append(row)

        # Debt/total_assets ratio
        row = ["有息负债/总资产（%）"]
        for y in years_labels:
            row.append(_fmt_val(_lookup(debt_ratio_series, y), is_pct=True))
        row.append("—")
        rows.append(row)

        # Net cash
        row = [f"广义净现金（{self._unit_label()}）"]
        for y in years_labels:
            row.append(_fmt_val(_lookup(net_cash_series, y)))
        row.append("—")
        rows.append(row)

        # Payout ratio
        row = ["股息支付率（%）"]
        for y in years_labels:
            row.append(_fmt_val(_lookup(payout_series, y), is_pct=True))
        row.append("—")
        rows.append(row)

        table = format_table(headers, rows, alignments=["l"] + ["r"] * (n_years + 1))
        lines.append(table)
        return "\n".join(lines)

    def _compute_factor2_inputs(self, ts_code: str) -> str | None:
        """Compute §17.2: Factor 2 input parameters (OE components, payout, threshold)."""
        income_df = self._get_annual_df("income")
        cf_df = self._get_annual_df("cashflow")

        if income_df.empty:
            return None

        years_labels = [str(r["end_date"])[:4] for _, r in income_df.iterrows()]
        n_years = len(years_labels)
        lines = [format_header(3, "17.2 因子2输入参数"), ""]

        # --- Per-year table: C, B, minority%, D&A, Capex, Capex/D&A, FCF ---
        headers = ["变量"] + years_labels
        rows = []

        # C = n_income_attr_p (already in millions after format_number)
        c_row = ["C 归母净利润"]
        b_row = ["B 少数股东损益"]
        min_pct_row = ["少数股东占比（%）"]
        for _, r in income_df.iterrows():
            c = self._safe_float(r.get("n_income_attr_p"))
            b = self._safe_float(r.get("minority_gain"))
            ni = self._safe_float(r.get("n_income"))
            c_row.append(format_number(c))
            b_row.append(format_number(b))
            if b is not None and ni and ni != 0:
                min_pct_row.append(f"{b / ni * 100:.2f}")
            else:
                min_pct_row.append("—")
        rows.extend([c_row, b_row, min_pct_row])

        # D&A and Capex from cashflow
        da_row = ["D 折旧与摊销"]
        capex_row = ["E 资本开支"]
        capex_da_row = ["Capex/D&A"]
        fcf_row = ["FCF = OCF - |Capex|"]
        da_vals = []  # for median calculation
        capex_vals = []  # for median calculation
        capex_da_vals = []

        if not cf_df.empty:
            # Align cashflow by year
            cf_by_year = {}
            for _, r in cf_df.iterrows():
                y = str(r["end_date"])[:4]
                cf_by_year[y] = r

            for y in years_labels:
                r = cf_by_year.get(y)
                if r is None:
                    da_row.append("—"); capex_row.append("—")
                    capex_da_row.append("—"); fcf_row.append("—")
                    continue

                depr = self._safe_float(r.get("depr_fa_coga_dpba"))
                amort_i = self._safe_float(r.get("amort_intang_assets"))
                amort_d = self._safe_float(r.get("lt_amort_deferred_exp"))
                da_components = [v for v in [depr, amort_i, amort_d] if v is not None]
                da = sum(da_components) if da_components else None

                capex = self._safe_float(r.get("c_pay_acq_const_fiolta"))
                ocf = self._safe_float(r.get("n_cashflow_act"))

                da_row.append(format_number(da) if da is not None else "—")
                capex_row.append(format_number(capex))
                if da and da > 0 and capex is not None:
                    ratio = abs(capex) / da
                    capex_da_row.append(f"{ratio:.2f}")
                    da_vals.append(da)
                    capex_vals.append(abs(capex))
                    capex_da_vals.append(ratio)
                else:
                    capex_da_row.append("—")
                if ocf is not None and capex is not None:
                    fcf_row.append(format_number(ocf - abs(capex)))
                else:
                    fcf_row.append("—")
        else:
            for _ in years_labels:
                da_row.append("—"); capex_row.append("—")
                capex_da_row.append("—"); fcf_row.append("—")

        rows.extend([da_row, capex_row, capex_da_row, fcf_row])

        table = format_table(headers, rows, alignments=["l"] + ["r"] * n_years)
        lines.append(table)
        lines.append("")

        # --- Summary variables ---
        summary_rows = []

        # F = Capex/D&A 5-year median
        if capex_da_vals:
            sorted_vals = sorted(capex_da_vals)
            mid = len(sorted_vals) // 2
            f_median = sorted_vals[mid] if len(sorted_vals) % 2 else (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
            summary_rows.append(["F（Capex/D&A 5年中位数）", f"{f_median:.2f}", "—"])
        else:
            summary_rows.append(["F（Capex/D&A 5年中位数）", "—", "数据不足"])

        # Payout ratio: M, N
        payout_lookup = self._get_payout_by_year()
        payout_ratios = [payout_lookup[y] for y in years_labels[:3] if y in payout_lookup]

        if payout_ratios:
            m_mean = sum(payout_ratios) / len(payout_ratios)
            if len(payout_ratios) > 1:
                variance = sum((x - m_mean) ** 2 for x in payout_ratios) / (len(payout_ratios) - 1)
                n_std = variance ** 0.5
            else:
                n_std = 0
            m_min = min(payout_ratios)
            summary_rows.append(["M（支付率3年均值）", f"{m_mean:.2f}%", f"基于 {len(payout_ratios)} 年"])
            summary_rows.append(["M_min（近3年最低档，保守锚）", f"{m_min:.2f}%", "无承诺/无稳定规律时优先于均值"])
            summary_rows.append(["N（支付率3年标准差）", f"{n_std:.2f}%", "—"])
        else:
            summary_rows.append(["M（支付率3年均值）", "—", "分红数据不足"])
            summary_rows.append(["N（支付率3年标准差）", "—", "—"])

        # O = buyback annual average (cancellation-type only)
        # Tushare does not provide repurchase purpose; default to 0.
        # Phase 3 should determine cancellation amount from annual report.
        rep_df = self._store.get("repurchase")
        if rep_df is not None and not rep_df.empty:
            summary_rows.append(["O（年均回购金额）", "0.00 百万",
                                 "默认0（无法区分注销型），Phase 3 从年报确认后填入"])
        else:
            summary_rows.append(["O（年均回购金额）", "0.00 百万", "无回购记录"])

        # Rf and II (threshold)
        rf_df = self._store.get("risk_free_rate")
        rf_val = None
        if rf_df is not None and not rf_df.empty:
            rf_val = self._safe_float(rf_df.iloc[0].get("yield"))

        if rf_val is not None:
            summary_rows.append(["Rf（无风险利率）", f"{rf_val:.4f}%", "来自 §14"])
            # Determine market type from ts_code
            if ts_code.endswith(".HK"):
                ii = max(5.0, rf_val + 3.0)
                summary_rows.append(["II（门槛值）", f"{ii:.2f}%", f"港股: max(5%, {rf_val:.2f}%+3%)"])
            elif ts_code.endswith(".US"):
                ii = max(4.0, rf_val + 2.0)
                summary_rows.append(["II（门槛值）", f"{ii:.2f}%", f"美股: max(4%, {rf_val:.2f}%+2%)"])
            else:  # A-share default
                ii = max(3.5, rf_val + 2.0)
                summary_rows.append(["II（门槛值）", f"{ii:.2f}%", f"A股: max(3.5%, {rf_val:.2f}%+2%)"])
        else:
            summary_rows.append(["Rf（无风险利率）", "—", "数据缺失"])
            summary_rows.append(["II（门槛值）", "—", "需Rf"])

        # OE base case (G=1.0)
        latest_c = self._safe_float(income_df.iloc[0].get("n_income_attr_p"))
        if latest_c is not None:
            summary_rows.append(["OE_base（G=1.0）", f"{format_number(latest_c)} 百万",
                                 "OE = C + D×(1-G); LLM 选 G 后代入"])

        summary_table = format_table(["汇总变量", "值", "说明"], summary_rows,
                                     alignments=["l", "r", "l"])
        lines.append(summary_table)
        return "\n".join(lines)

    def _compute_factor4_inputs(self) -> str | None:
        """Compute §17.6: Price percentiles from 10yr weekly data."""
        wp_df = self._store.get("weekly_prices")
        basic_df = self._store.get("basic_info")

        if wp_df is None or wp_df.empty:
            return None

        lines = [format_header(3, "17.6 因子4·股价分位"), ""]

        closes = wp_df["close"].dropna().tolist()
        if not closes:
            return None

        nn = len(closes)
        current_price = closes[-1] if closes else None  # latest (sorted ascending)

        # Also try from basic_info
        if basic_df is not None and not basic_df.empty:
            bp = self._safe_float(basic_df.iloc[0].get("close"))
            if bp is not None:
                current_price = bp

        if current_price is None:
            return None

        # Current price percentile
        below_count = sum(1 for c in closes if c < current_price)
        current_percentile = below_count / nn * 100

        # Key percentile prices
        sorted_closes = sorted(closes)

        def _percentile_price(pct: float) -> float:
            idx = int(pct / 100 * (nn - 1))
            return sorted_closes[min(idx, nn - 1)]

        rows = [
            ["10年数据点数", str(nn)],
            ["当前股价", f"{current_price:.2f}"],
            ["当前股价历史分位", f"{current_percentile:.1f}%"],
            ["10%分位价格", f"{_percentile_price(10):.2f}"],
            ["25%分位价格", f"{_percentile_price(25):.2f}"],
            ["50%分位价格（中位数）", f"{_percentile_price(50):.2f}"],
            ["75%分位价格", f"{_percentile_price(75):.2f}"],
            ["90%分位价格", f"{_percentile_price(90):.2f}"],
        ]

        table = format_table(["指标", "值"], rows, alignments=["l", "r"])
        lines.append(table)
        return "\n".join(lines)

    def _compute_sotp_inputs(self) -> str | None:
        """Compute §17.7: SOTP holding company structure inputs from parent/consolidated BS."""
        bs_df = self._get_annual_df("balance_sheet")
        bs_parent_df = self._get_annual_df("balance_sheet_parent")

        if bs_df.empty or bs_parent_df.empty:
            return None

        lines = [format_header(3, "17.7 控股结构辅助"), ""]

        latest_consol = bs_df.iloc[0]
        latest_parent = bs_parent_df.iloc[0]

        def _debt(row):
            components = ["st_borr", "lt_borr", "bond_payable", "non_cur_liab_due_1y"]
            total = 0.0
            for c in components:
                v = self._safe_float(row.get(c))
                if v:
                    total += v
            return total

        consol_debt = _debt(latest_consol)
        parent_debt = _debt(latest_parent)
        consol_cash = self._safe_float(latest_consol.get("money_cap")) or 0
        parent_cash = self._safe_float(latest_parent.get("money_cap")) or 0

        rows = [
            ["有息负债", format_number(consol_debt), format_number(parent_debt)],
            ["现金", format_number(consol_cash), format_number(parent_cash)],
            ["净现金", format_number(consol_cash - consol_debt), format_number(parent_cash - parent_debt)],
        ]

        if consol_debt > 0:
            sub_ratio = (consol_debt - parent_debt) / consol_debt * 100
            rows.append(["子公司层面负债占比", f"{sub_ratio:.1f}%", "—"])

        table = format_table(["指标", "合并口径", "母公司口径"], rows,
                             alignments=["l", "r", "r"])
        lines.append(table)
        return "\n".join(lines)

    # --- Feature #94: §17.8 EV baseline + "买入就是胜利"基准价 ---

    def _compute_factor4_ev_baseline(self, ts_code: str) -> str | None:
        """Compute §17.8: Valuation dashboard + floor-price baseline.

        Requires basic_info in _store (provides close, total_mv, total_share).
        All amounts in 百万元 unless stated otherwise.
        """
        basic_df = self._store.get("basic_info")
        if basic_df is None or basic_df.empty:
            return None

        bi = basic_df.iloc[0]
        close = self._safe_float(bi.get("close"))

        if self._is_us(ts_code):
            # US: total_mv is raw USD
            total_mv_raw = self._safe_float(bi.get("total_mv"))
            if not close or not total_mv_raw:
                return None
            mkt_cap_yuan = total_mv_raw  # raw USD (same unit as financial statements)
            mkt_cap = total_mv_raw / 1e6  # 百万美元
            total_shares = total_mv_raw / close  # shares
        elif self._is_hk(ts_code):
            # HK: total_market_cap already in 百万港元 from hk_daily
            total_market_cap = self._safe_float(bi.get("total_market_cap"))
            if not close or not total_market_cap:
                return None
            mkt_cap = total_market_cap  # 百万港元
            mkt_cap_yuan = mkt_cap * 1e6  # raw HKD
            total_shares = mkt_cap_yuan / close  # shares
        else:
            # A-share: total_mv in 万元
            total_mv_wan = self._safe_float(bi.get("total_mv"))
            total_share_wan = self._safe_float(bi.get("total_share"))
            if not close or not total_mv_wan or not total_share_wan or total_share_wan <= 0:
                return None
            mkt_cap_yuan = total_mv_wan * 10000  # yuan
            mkt_cap = mkt_cap_yuan / 1e6  # 百万元
            total_shares = total_share_wan * 10000  # 股

        # --- Gather data from _store ---
        income_df = self._get_annual_df("income")
        bs_df = self._get_annual_df("balance_sheet")
        cf_df = self._get_annual_df("cashflow")

        if income_df.empty or bs_df.empty or cf_df.empty:
            return None

        latest_inc = income_df.iloc[0]
        latest_bs = bs_df.iloc[0]
        latest_cf = cf_df.iloc[0]

        # Helper: interest-bearing debt components (yuan)
        def _ibd_yuan(row):
            total = 0.0
            for c in ["st_borr", "lt_borr", "bond_payable", "non_cur_liab_due_1y"]:
                v = self._safe_float(row.get(c))
                if v:
                    total += v
            return total

        ibd_yuan = _ibd_yuan(latest_bs)
        cash_yuan = self._safe_float(latest_bs.get("money_cap")) or 0
        trad_yuan = self._safe_float(latest_bs.get("trad_asset")) or 0
        goodwill_yuan = self._safe_float(latest_bs.get("goodwill")) or 0
        total_assets_yuan = self._safe_float(latest_bs.get("total_assets")) or 0
        equity_yuan = self._safe_float(latest_bs.get("total_hldr_eqy_exc_min_int")) or 0

        oper_profit_yuan = self._safe_float(latest_inc.get("operate_profit")) or 0
        finance_exp_yuan = self._safe_float(latest_inc.get("finance_exp")) or 0
        np_parent_yuan = self._safe_float(latest_inc.get("n_income_attr_p")) or 0

        da_yuan = 0.0
        for c in ["depr_fa_coga_dpba", "amort_intang_assets", "lt_amort_deferred_exp"]:
            v = self._safe_float(latest_cf.get(c))
            if v:
                da_yuan += v

        ocf_yuan = self._safe_float(latest_cf.get("n_cashflow_act")) or 0
        capex_yuan = self._safe_float(latest_cf.get("c_pay_acq_const_fiolta")) or 0
        fcf_yuan = ocf_yuan - capex_yuan

        # Convert to 百万元
        ibd = ibd_yuan / 1e6
        cash = cash_yuan / 1e6
        trad = trad_yuan / 1e6
        goodwill = goodwill_yuan / 1e6
        ta = total_assets_yuan / 1e6
        equity = equity_yuan / 1e6
        oper_profit = oper_profit_yuan / 1e6
        fin_exp = finance_exp_yuan / 1e6
        np_parent = np_parent_yuan / 1e6
        da = da_yuan / 1e6
        fcf = fcf_yuan / 1e6

        # ===== Part A: Valuation indicators =====
        # Manual calculations (fallback)
        ebitda = oper_profit + fin_exp + da
        net_debt = ibd - cash  # positive = net debt, negative = net cash

        # Prefer fina_indicator pre-computed values when available
        fi_df = self._store.get("fina_indicators")
        if fi_df is not None and not fi_df.empty:
            fy_month_str = f"{self._fy_end_month:02d}"
            fi_annual = fi_df[fi_df["end_date"].str[4:6] == fy_month_str].sort_values(
                "end_date", ascending=False)
            if not fi_annual.empty:
                fi_row = fi_annual.iloc[0]
                v = self._safe_float(fi_row.get("ebitda"))
                if v is not None:
                    ebitda = v / 1e6
                v = self._safe_float(fi_row.get("netdebt"))
                if v is not None:
                    net_debt = v / 1e6
                v = self._safe_float(fi_row.get("fcff"))
                if v is not None:
                    fcf = v / 1e6

        ev = mkt_cap + net_debt
        net_cash = -net_debt

        ev_ebitda = f"{ev / ebitda:.2f}x" if ebitda > 0 else "—"
        cash_pe = f"{(mkt_cap - net_cash) / np_parent:.2f}x" if np_parent > 0 else "—"
        fcf_yield = f"{fcf / mkt_cap * 100:.2f}%" if mkt_cap > 0 else "—"
        pb = f"{mkt_cap / equity:.2f}x" if equity > 0 else "—"
        net_debt_ebitda = f"{net_debt / ebitda:.2f}x" if ebitda > 0 else "—"
        goodwill_ratio = f"{goodwill / ta * 100:.2f}%" if ta > 0 else "—"
        ibd_ratio = f"{ibd / ta * 100:.2f}%" if ta > 0 else "—"

        # Dividend yield: latest DPS / close
        div_yield_str = "—"
        div_df = self._store.get("dividends")
        latest_dps = None
        if div_df is not None and not div_df.empty:
            sorted_div = div_df.sort_values("end_date", ascending=False)
            latest_dps = self._safe_float(sorted_div.iloc[0].get("cash_div_tax"))
            if latest_dps is not None and close > 0:
                div_yield_str = f"{latest_dps / close * 100:.2f}%"

        lines = [format_header(3, '17.8 因子4·绝对估值与"买入就是胜利"基准价'), ""]

        # Valuation table
        lines.append("#### 估值指标")
        lines.append("")
        fmt = lambda v: format_number(v, divider=1)
        val_rows = [
            [f"总市值（{self._unit_label()}）", fmt(mkt_cap), "—"],
            [f"企业价值 EV（{self._unit_label()}）", fmt(ev), "市值+有息负债-现金"],
            [f"EBITDA（{self._unit_label()}）", fmt(ebitda), "营业利润+财务费用+D&A"],
            ["EV/EBITDA", ev_ebitda, "—"],
            ["扣除现金PE", cash_pe, "(市值-净现金)/归母净利润"],
            ["FCF收益率", fcf_yield, "FCF/市值"],
            ["P/B", pb, "市值/归母权益"],
            ["净负债/EBITDA", net_debt_ebitda, "(有息负债-现金)/EBITDA，负值=净现金"],
            ["商誉/总资产", goodwill_ratio, "—"],
            ["有息负债率", ibd_ratio, "有息负债/总资产"],
            ["股息率", div_yield_str, "最新DPS/当前股价"],
        ]
        lines.append(format_table(["指标", "值", "说明"], val_rows,
                                  alignments=["l", "r", "l"]))
        lines.append("")

        # ===== Part B: "买入就是胜利" baselines =====
        lines.append('#### "买入就是胜利"基准价')
        lines.append("")

        baselines = []  # (name, value_yuan_per_share, logic)

        # ① Net liquid assets / share
        nla = (cash_yuan + trad_yuan - ibd_yuan) / total_shares
        baselines.append(("① 净流动资产/股", nla, "(现金+交易性金融资产-有息负债)/总股本"))

        # ② BVPS
        bvps = equity_yuan / total_shares
        baselines.append(("② 每股净资产", bvps, "归母权益/总股本"))

        # ③ 10-year low from weekly prices
        wp_df = self._store.get("weekly_prices")
        if wp_df is not None and not wp_df.empty:
            min_close = wp_df["close"].dropna().min()
            if min_close is not None and min_close == min_close:  # NaN check
                baselines.append(("③ 10年最低价", float(min_close), "周线最低收盘价"))

        # ④ Dividend yield implied price: 3yr avg DPS / max(Rf, 3%)
        rf_df = self._store.get("risk_free_rate")
        rf_pct = None
        if rf_df is not None and not rf_df.empty:
            rf_pct = self._safe_float(rf_df.iloc[0].get("yield"))

        if div_df is not None and not div_df.empty and rf_pct is not None:
            sorted_div = div_df.sort_values("end_date", ascending=False)
            recent_dps = []
            for _, row in sorted_div.head(3).iterrows():
                v = self._safe_float(row.get("cash_div_tax"))
                if v is not None:
                    recent_dps.append(v)
            if recent_dps:
                avg_dps = sum(recent_dps) / len(recent_dps)
                discount = max(rf_pct / 100, 0.03)
                implied_price = avg_dps / discount
                baselines.append(("④ 股息隐含价", implied_price,
                                  f"3年均DPS÷max(Rf,3%)"))

        # ⑤ Pessimistic FCF capitalization: min(5yr FCF) / Rf / total_shares
        if rf_pct is not None and rf_pct > 0:
            fcf_list = []
            for _, row in cf_df.iterrows():
                ocf_v = self._safe_float(row.get("n_cashflow_act"))
                cap_v = self._safe_float(row.get("c_pay_acq_const_fiolta"))
                if ocf_v is not None and cap_v is not None:
                    fcf_list.append(ocf_v - cap_v)
            if fcf_list and min(fcf_list) <= 0:
                lines.append("> ⑤ 悲观FCF资本化：跳过（存在负FCF年份）")
                lines.append("")
            if fcf_list and min(fcf_list) > 0:
                min_fcf = min(fcf_list)
                cap_price = min_fcf / (rf_pct / 100) / total_shares
                baselines.append(("⑤ 悲观FCF资本化", cap_price,
                                  "min(5年FCF)÷Rf÷总股本"))

        # Build baseline table
        bl_rows = []
        valid_prices = []
        for name, val, logic in baselines:
            bl_rows.append([name, f"{val:.2f}", logic])
            valid_prices.append(val)

        lines.append(format_table(["方法", f"基准价（{self._price_unit()}）", "计算逻辑"], bl_rows,
                                  alignments=["l", "r", "l"]))
        lines.append("")

        # ===== Part C: Composite baseline =====
        if valid_prices:
            composite = sum(valid_prices) / len(valid_prices)

            lines.append(f"**综合基准价（算术平均）= {composite:.2f} {self._price_unit()}**")

            if len(valid_prices) < 3:
                lines.append("*数据不足（有效方法<3），仅供参考*")

            # ===== Part D: Premium analysis =====
            premium = (close / composite - 1) * 100
            lines.append(f"当前股价 {close:.2f} {self._price_unit()}，较基准价溢价 **{premium:.1f}%**")

            if premium <= 0:
                verdict = "低于基准线 — 买入就是胜利"
            elif premium <= 30:
                verdict = "接近基准线 — 安全边际充足"
            elif premium <= 80:
                verdict = "合理溢价 — 需确认成长性"
            elif premium <= 150:
                verdict = "较高溢价 — 依赖持续成长"
            else:
                verdict = "显著溢价 — 高成长预期已定价"

            lines.append(f"→ {verdict}")

        return "\n".join(lines)

    # --- Feature #96: §17.9 Factor 4 earnings decline sensitivity ---

    def _compute_factor4_sensitivity(self, ts_code: str) -> str | None:
        """Compute §17.9: Earnings decline sensitivity tables.

        Shows how 穿透回报率 and 情景目标买入价（GG=II 的股价）change under AA decline scenarios.
        Requires factor3_sensitivity (AA), basic_info (market cap, shares),
        risk_free_rate (II), dividends+income (M payout ratio).
        """
        # Read AA from factor3_sensitivity stored by _compute_factor3_sensitivity_base
        f3s = self._store.get("factor3_sensitivity")
        if not f3s:
            return None
        aa = f3s.get("aa_selected")
        if aa is None or aa == 0:
            return None

        # Read basic_info for market cap and total shares
        basic_df = self._store.get("basic_info")
        if basic_df is None or basic_df.empty:
            return None
        bi = basic_df.iloc[0]
        close = self._safe_float(bi.get("close"))
        if self._is_us(ts_code):
            total_mv_raw = self._safe_float(bi.get("total_mv"))  # raw USD
            if not total_mv_raw:
                return None
            mkt_cap = total_mv_raw  # raw USD (same unit as aa)
            total_shares = total_mv_raw / close if close else 0
        elif self._is_hk(ts_code):
            total_market_cap = self._safe_float(bi.get("total_market_cap"))  # 百万港元
            if not total_market_cap:
                return None
            mkt_cap = total_market_cap * 1e6  # raw HKD (same unit as aa)
            total_shares = mkt_cap / close if close else 0
        else:
            total_mv_wan = self._safe_float(bi.get("total_mv"))  # 万元
            total_share_wan = self._safe_float(bi.get("total_share"))  # 万股
            if not total_mv_wan or not total_share_wan or total_share_wan <= 0:
                return None
            mkt_cap = total_mv_wan * 10000  # 元（与 aa 同单位）
            total_shares = total_share_wan * 10000  # 股

        # Read II (threshold) from risk_free_rate
        rf_df = self._store.get("risk_free_rate")
        if rf_df is None or rf_df.empty:
            return None
        rf_val = self._safe_float(rf_df.iloc[0].get("yield"))
        if rf_val is None:
            return None
        if ts_code.endswith(".HK"):
            ii = max(5.0, rf_val + 3.0)
        elif ts_code.endswith(".US"):
            ii = max(4.0, rf_val + 2.0)
        else:
            ii = max(3.5, rf_val + 2.0)

        # Read M (payout ratio) — uses _get_payout_by_year helper
        income_df = self._get_annual_df("income")
        payout_lookup = self._get_payout_by_year()
        years_labels = [str(r["end_date"])[:4] for _, r in income_df.iterrows()] if not income_df.empty else []
        payout_ratios = [payout_lookup[y] for y in years_labels[:3] if y in payout_lookup]
        m_pct = sum(payout_ratios) / len(payout_ratios) if payout_ratios else None
        if m_pct is None:
            return None

        # O = repurchase annual average (default 0, same as §17.2)
        o_val = 0.0

        # Base 穿透回报率
        gg_base = (aa * m_pct / 100 + o_val) / mkt_cap * 100  # percent
        scenario_buy_base = (aa * m_pct / 100 + o_val) / (ii / 100 * total_shares)  # 情景目标买入价（基准）：GG=II 的股价

        def _row(label: str, factor: float):
            aa_new = aa * factor
            gg = (aa_new * m_pct / 100 + o_val) / mkt_cap * 100
            vs_threshold = gg - ii
            scenario_buy = (aa_new * m_pct / 100 + o_val) / (ii / 100 * total_shares)  # 情景目标买入价(k)
            vs_price = (scenario_buy / close - 1) * 100 if close and close > 0 else 0
            return [
                label,
                format_number(aa_new),
                f"{gg:.2f}%",
                f"{vs_threshold:+.2f} pct",
                f"{scenario_buy:.2f}",
                f"{vs_price:+.1f}%",
            ]

        lines = [format_header(3, "17.9 因子4·业绩下滑敏感性"), ""]
        lines.append(f"> AA（真实可支配现金结余）= {format_number(aa)} {self._unit_label()}，"
                     f"M = {m_pct:.2f}%，O = {format_number(o_val)}，"
                     f"II = {ii:.2f}%，市值 = {format_number(mkt_cap)} {self._unit_label()}")
        lines.append("")

        # Table 1: cumulative 10%/year decline over 1-3 years
        lines.append("#### 表1：逐年累积下滑（每年-10%）")
        lines.append("")
        headers1 = ["情景", "真实可支配现金结余", "穿透回报率", "vs 门槛", f"情景目标买入价（{self._price_unit()}）", "vs当前股价"]
        rows1 = [
            _row("基准", 1.0),
            _row("下滑1年 (×0.9)", 0.9),
            _row("下滑2年 (×0.9²)", 0.81),
            _row("下滑3年 (×0.9³)", 0.729),
        ]
        lines.append(format_table(headers1, rows1, alignments=["l", "r", "r", "r", "r", "r"]))
        lines.append("")

        # Table 2: single-year different decline magnitudes
        lines.append("#### 表2：单年不同下滑幅度")
        lines.append("")
        headers2 = ["下滑幅度", "真实可支配现金结余", "穿透回报率", f"情景目标买入价（{self._price_unit()}）", "vs当前股价"]
        rows2 = []
        for pct, factor in [("-10%", 0.9), ("-20%", 0.8), ("-30%", 0.7)]:
            r = _row(pct, factor)
            rows2.append([r[0], r[1], r[2], r[4], r[5]])
        lines.append(format_table(headers2, rows2, alignments=["l", "r", "r", "r", "r"]))

        return "\n".join(lines)

    # --- Feature #92: §17.3-17.5 Factor 3 base case computations ---

    def _compute_factor3_step1(self) -> str | None:
        """Compute §17.3: True cash revenue (步骤1).

        Conservative base case:
        - Deduct AR increases (revenue not yet collected as cash)
        - Deduct contract liability decreases (consumed pre-collected cash)
        - Do NOT add back AR decreases or CL increases (conservative)
        Stores results in self._store["_true_cash_rev"] for §17.5.
        """
        income_df = self._get_annual_df("income")
        bs_df = self._get_annual_df("balance_sheet")

        if income_df.empty or bs_df.empty or len(income_df) < 2:
            return None

        # Build year-indexed lookups from balance sheet
        bs_by_year = {}
        for _, r in bs_df.iterrows():
            year = str(r["end_date"])[:4]
            bs_by_year[year] = r

        # Income years (desc order)
        income_years = [str(r["end_date"])[:4] for _, r in income_df.iterrows()]

        # Compute changes — need year and prior year in BS
        results = []  # (year, S, T, U, true_cash_rev, collection_ratio) in raw yuan
        true_cash_rev_store = {}

        for i, year in enumerate(income_years):
            # Find prior year in income (next in list since desc)
            prior_year = str(int(year) - 1)
            if year not in bs_by_year or prior_year not in bs_by_year:
                continue

            bs_cur = bs_by_year[year]
            bs_prev = bs_by_year[prior_year]

            # S = revenue (raw yuan)
            filtered = income_df[income_df["end_date"].str.startswith(year)]
            if filtered.empty:
                continue
            s = self._safe_float(filtered.iloc[0].get("revenue"))
            if s is None:
                continue

            # T = AR change (increase positive)
            ar_cur = self._safe_float(bs_cur.get("accounts_receiv")) or 0
            ar_prev = self._safe_float(bs_prev.get("accounts_receiv")) or 0
            t = ar_cur - ar_prev

            # U = contract_liab change (increase positive)
            cl_cur = self._safe_float(bs_cur.get("contract_liab")) or 0
            cl_prev = self._safe_float(bs_prev.get("contract_liab")) or 0
            u = cl_cur - cl_prev

            # Conservative: deduct AR increases, deduct CL decreases
            true_cash = s - max(0, t) - max(0, -u)
            ratio = true_cash / s if s > 0 else None

            results.append((year, s, t, u, true_cash, ratio))
            true_cash_rev_store[year] = true_cash

        if not results:
            return None

        # Store for §17.5
        self._store["_true_cash_rev"] = true_cash_rev_store

        # Build output
        lines = [format_header(3, "17.3 因子3·步骤1 真实现金收入（保守基准）"), ""]
        lines.append("> AR增加扣除，CL增加不加回。LLM 可根据例外规则（如白酒预收）调整。")
        lines.append("")

        headers = ["年份", "S 营业收入", "T 应收变动", "U 合同负债变动",
                   "真实现金收入", "收款比率"]
        rows = []
        for year, s, t, u, tcr, ratio in results:
            rows.append([
                year,
                format_number(s),
                format_number(t),
                format_number(u),
                format_number(tcr),
                f"{ratio * 100:.2f}%" if ratio is not None else "—",
            ])
        table = format_table(headers, rows,
                             alignments=["l"] + ["r"] * 5)
        lines.append(table)

        # Null-value warnings for AR / contract_liab
        warnings = []
        for year, s, t, u, tcr, ratio in results:
            if year in bs_by_year:
                bs_cur = bs_by_year[year]
                prior_year = str(int(year) - 1)
                bs_prev = bs_by_year.get(prior_year)
                if bs_prev is not None:
                    ar_cur = self._safe_float(bs_cur.get("accounts_receiv"))
                    ar_prev = self._safe_float(bs_prev.get("accounts_receiv"))
                    if ar_cur is None and ar_prev is None and s > 0:
                        warnings.append(f"{year}: accounts_receiv 为空，AR变动=0 可能高估现金收入")
                    cl_cur = self._safe_float(bs_cur.get("contract_liab"))
                    cl_prev = self._safe_float(bs_prev.get("contract_liab"))
                    if cl_cur is None and cl_prev is None and s > 0:
                        warnings.append(f"{year}: contract_liab 为空，CL变动=0 可能影响现金收入")
        if warnings:
            lines.append("")
            for wm in warnings:
                lines.append(f"> ⚠️ {wm}")

        return "\n".join(lines)

    def _compute_factor3_step4(self) -> str | None:
        """Compute §17.4: Operating cash outflows (步骤4).

        W1 = oper_cost + max(0, -AP_change)
        W2 = c_pay_to_staff (from cashflow)
        W3 = income_tax - deferred_tax_net_change
        W4 = finance_exp
        Stores results in self._store["_w_total"] for §17.5.
        """
        income_df = self._get_annual_df("income")
        bs_df = self._get_annual_df("balance_sheet")
        cf_df = self._get_annual_df("cashflow")

        if income_df.empty or bs_df.empty or cf_df.empty or len(income_df) < 2:
            return None

        # Build lookups
        bs_by_year = {}
        for _, r in bs_df.iterrows():
            bs_by_year[str(r["end_date"])[:4]] = r
        cf_by_year = {}
        for _, r in cf_df.iterrows():
            cf_by_year[str(r["end_date"])[:4]] = r
        inc_by_year = {}
        for _, r in income_df.iterrows():
            inc_by_year[str(r["end_date"])[:4]] = r

        income_years = [str(r["end_date"])[:4] for _, r in income_df.iterrows()]

        results = []  # (year, W1, W2, W3, W4, W)
        w_total_store = {}

        for year in income_years:
            prior_year = str(int(year) - 1)
            if year not in bs_by_year or prior_year not in bs_by_year:
                continue
            if year not in cf_by_year or year not in inc_by_year:
                continue

            inc = inc_by_year[year]
            bs_cur = bs_by_year[year]
            bs_prev = bs_by_year[prior_year]
            cf = cf_by_year[year]

            # W1: supplier = oper_cost + max(0, -AP_change)
            oper_cost = self._safe_float(inc.get("oper_cost")) or 0
            ap_cur = self._safe_float(bs_cur.get("acct_payable")) or 0
            ap_prev = self._safe_float(bs_prev.get("acct_payable")) or 0
            ap_change = ap_cur - ap_prev
            w1 = oper_cost + max(0, -ap_change)

            # W2: employee = c_pay_to_staff (fallback to SGA if null)
            w2_raw = self._safe_float(cf.get("c_pay_to_staff"))
            w2_is_fallback = False
            if w2_raw is None or w2_raw == 0:
                # Fallback: SGA from income statement as proxy
                selling = self._safe_float(inc.get("sell_exp")) or 0
                admin = self._safe_float(inc.get("admin_exp")) or 0
                rd = self._safe_float(inc.get("rd_exp")) or 0
                w2 = selling + admin + rd
                w2_is_fallback = w2 > 0  # only mark fallback if SGA produced a value
            else:
                w2 = w2_raw

            # W3: cash tax = income_tax - (DTA_change - DTL_change)
            income_tax = self._safe_float(inc.get("income_tax")) or 0
            dta_cur = self._safe_float(bs_cur.get("defer_tax_assets")) or 0
            dta_prev = self._safe_float(bs_prev.get("defer_tax_assets")) or 0
            dtl_cur = self._safe_float(bs_cur.get("defer_tax_liab")) or 0
            dtl_prev = self._safe_float(bs_prev.get("defer_tax_liab")) or 0
            deferred_net_change = (dta_cur - dta_prev) - (dtl_cur - dtl_prev)
            w3 = income_tax - deferred_net_change

            # W4: interest = finance_exp
            w4 = self._safe_float(inc.get("finance_exp")) or 0

            w = w1 + w2 + w3 + w4
            results.append((year, w1, w2, w3, w4, w, w2_is_fallback))
            w_total_store[year] = w

        if not results:
            return None

        # Store for §17.5
        self._store["_w_total"] = w_total_store

        # Build output
        lines = [format_header(3, "17.4 因子3·步骤4 经营性现金支出"), ""]

        headers = ["年份", "W1 供应商", "W2 员工", "W3 现金税", "W4 利息", "W 合计"]
        rows = []
        has_w2_fallback = False
        for year, w1, w2, w3, w4, w, w2_fb in results:
            w2_display = format_number(w2)
            if w2_fb:
                w2_display += "†"
                has_w2_fallback = True
            rows.append([
                year,
                format_number(w1),
                w2_display,
                format_number(w3),
                format_number(w4),
                format_number(w),
            ])
        table = format_table(headers, rows,
                             alignments=["l"] + ["r"] * 5)
        lines.append(table)

        # Footnote for W2 fallback
        if has_w2_fallback:
            lines.append("")
            lines.append("> † W2: c_pay_to_staff 为空，已用利润表 SGA（销售+管理+研发费用）替代，偏保守。")

        # Null-value warnings
        warnings = []
        for year, w1, w2, w3, w4, w, w2_fb in results:
            inc = inc_by_year.get(year)
            cf = cf_by_year.get(year)
            if inc is not None:
                if (self._safe_float(inc.get("oper_cost")) or 0) == 0:
                    warnings.append(f"{year}: oper_cost 为空，W1 可能偏低")
                total_profit = self._safe_float(inc.get("total_profit")) or 0
                if (self._safe_float(inc.get("income_tax")) or 0) == 0 and total_profit > 0:
                    warnings.append(f"{year}: income_tax 为空但利润总额>0，W3 可能偏低")
        if warnings:
            lines.append("")
            for wm in warnings:
                lines.append(f"> ⚠️ {wm}")

        return "\n".join(lines)

    def _compute_factor3_sensitivity_base(self) -> str | None:
        """Compute §17.5: Base surplus + sensitivity inputs.

        Base surplus = true_cash_revenue - W - Capex (per year, no V/X adjustments).
        Also computes: AA_incl, AA_excl, revenue CV, λ, λ reliability.
        Requires _compute_factor3_step1() and _compute_factor3_step4() to have run first.
        """
        true_cash_rev = self._store.get("_true_cash_rev")
        w_total = self._store.get("_w_total")
        if not true_cash_rev or not w_total:
            return None

        cf_df = self._get_annual_df("cashflow")
        income_df = self._get_annual_df("income")
        if cf_df.empty or income_df.empty:
            return None

        # Capex by year
        capex_by_year = {}
        for _, r in cf_df.iterrows():
            year = str(r["end_date"])[:4]
            capex_by_year[year] = self._safe_float(r.get("c_pay_acq_const_fiolta")) or 0

        # Revenue by year (for CV and λ)
        rev_by_year = {}
        for _, r in income_df.iterrows():
            year = str(r["end_date"])[:4]
            rev_by_year[year] = self._safe_float(r.get("revenue")) or 0

        # Compute base surplus per year (only years with all data)
        common_years = sorted(
            set(true_cash_rev.keys()) & set(w_total.keys()) & set(capex_by_year.keys()),
            reverse=True
        )
        if not common_years:
            return None

        surplus_data = []  # (year, tcr, w, capex, base_surplus)
        for year in common_years:
            tcr = true_cash_rev[year]
            w = w_total[year]
            capex = capex_by_year.get(year, 0)
            base = tcr - w - capex
            surplus_data.append((year, tcr, w, capex, base))

        surpluses = [s[4] for s in surplus_data]

        # AA_all: mean of all years (was aa_incl)
        aa_all = sum(surpluses) / len(surpluses)

        # AA_2y: mean of most recent 2 years (surplus_data sorted descending)
        aa_2y = sum(surpluses[:2]) / min(2, len(surpluses)) if surpluses else aa_all

        # AA_excl: exclude years where base_surplus < 0
        positive_surpluses = [s for s in surpluses if s >= 0]
        aa_excl = sum(positive_surpluses) / len(positive_surpluses) if positive_surpluses else aa_all

        # Default: use AA_2y; fallback to AA_all if <2 years of data
        aa_selected = aa_2y if len(surpluses) >= 2 else aa_all

        # Store AA values for downstream use (§17.9 sensitivity)
        self._store["factor3_sensitivity"] = {
            "aa_incl": aa_all,  # legacy key for backward compatibility
            "aa_all": aa_all,
            "aa_2y": aa_2y,
            "aa_excl": aa_excl,
            "aa_selected": aa_selected,
        }

        # Revenue CV (all available years, not just change-computed years)
        all_revenues = [rev_by_year[y] for y in sorted(rev_by_year.keys()) if rev_by_year[y] > 0]
        cv = None
        if len(all_revenues) >= 2:
            import statistics
            rev_mean = statistics.mean(all_revenues)
            rev_stdev = statistics.pstdev(all_revenues)  # population stdev
            cv = rev_stdev / rev_mean if rev_mean > 0 else None

        # λ: median(ΔSurplus/ΔRevenue) over latest 3 year-pairs
        lambda_vals = []
        sorted_years_asc = sorted(common_years)
        for i in range(1, len(sorted_years_asc)):
            y_cur = sorted_years_asc[i]
            y_prev = sorted_years_asc[i - 1]
            delta_s = rev_by_year.get(y_cur, 0) - rev_by_year.get(y_prev, 0)
            surplus_cur = next((s[4] for s in surplus_data if s[0] == y_cur), None)
            surplus_prev = next((s[4] for s in surplus_data if s[0] == y_prev), None)
            if surplus_cur is not None and surplus_prev is not None and delta_s != 0:
                delta_surplus = surplus_cur - surplus_prev
                lambda_vals.append(delta_surplus / delta_s)

        # Use latest 3 pairs
        lambda_vals = lambda_vals[-3:] if len(lambda_vals) > 3 else lambda_vals
        import statistics
        lambda_median = statistics.median(lambda_vals) if lambda_vals else None

        # λ reliability checks
        lambda_warnings = []
        if len(all_revenues) >= 3:
            # Check 1: revenue amplitude over years used for λ
            lambda_rev_years = sorted(common_years)
            lambda_revs = [rev_by_year.get(y, 0) for y in lambda_rev_years if rev_by_year.get(y, 0) > 0]
            if lambda_revs and min(lambda_revs) > 0:
                amplitude = max(lambda_revs) / min(lambda_revs) - 1
                if amplitude < 0.10:
                    lambda_warnings.append("历史收入波幅不足10%，λ外推可靠性低")

        # Check 2: sign consistency
        if lambda_vals:
            signs = [1 if v >= 0 else -1 for v in lambda_vals]
            if len(set(signs)) > 1:
                lambda_warnings.append("ΔSurplus/ΔRevenue符号不一致，成本结构可能变化")

        # Check 3: λ range
        if lambda_median is not None and (lambda_median > 3 or lambda_median < 0):
            lambda_warnings.append(f"λ={lambda_median:.2f}异常，建议人工核查")

        lambda_reliability = "正常"
        if len(lambda_warnings) >= 2 or (lambda_median is not None and (lambda_median > 3 or lambda_median < 0)):
            lambda_reliability = "多项警告或异常"
        elif len(lambda_warnings) == 1:
            lambda_reliability = "有一项警告"

        # Augment stored dict with λ / CV fields for §17.13 (rendered output unchanged)
        self._store["factor3_sensitivity"].update({
            "lambda_median": lambda_median,
            "lambda_reliability": lambda_reliability,
            "lambda_warnings": lambda_warnings,
            "cv": cv,
        })

        # Build output
        lines = [format_header(3, "17.5 因子3·步骤7 基准可支配结余 + 敏感性输入"), ""]
        lines.append("> 不含 V1/V5/-V_deduct/-X1/-X2 调整。LLM 需在此基础上加减调整项。")
        lines.append("")

        # Per-year table
        headers = ["年份", "真实现金收入", "- W 经营支出", "- E 资本开支", "= 基准结余"]
        rows = []
        for year, tcr, w, capex, base in surplus_data:
            rows.append([
                year,
                format_number(tcr),
                format_number(w),
                format_number(capex),
                format_number(base),
            ])
        table = format_table(headers, rows, alignments=["l"] + ["r"] * 4)
        lines.append(table)
        lines.append("")

        # Summary
        lines.append(f"- AA_2y（近2年均值，默认基准）= {format_number(aa_2y)} {self._unit_label()}")
        lines.append(f"- AA_all（全部年份均值）= {format_number(aa_all)} {self._unit_label()}")
        lines.append(f"- AA_excl（剔除负值年份均值）= {format_number(aa_excl)} {self._unit_label()}")
        diff_2y_all_pct = abs(aa_2y - aa_all) / abs(aa_all) * 100 if aa_all != 0 else 0
        if diff_2y_all_pct > 30:
            lines.append(f"  ⚠️ AA_2y 与 AA_all 差异 {diff_2y_all_pct:.1f}% > 30%，请审核近2年是否存在非经常性高峰")
        lines.append(f"- 收入波动率 CV = {cv * 100:.2f}%" if cv is not None else "- 收入波动率 CV = —")
        lines.append(f"- 经营杠杆系数 λ = {lambda_median:.4f}" if lambda_median is not None else "- 经营杠杆系数 λ = —")
        lines.append(f"- λ可靠性 = {lambda_reliability}")
        for w_msg in lambda_warnings:
            lines.append(f"  ⚠️ {w_msg}")

        # Capex null-value warnings
        capex_warnings = []
        for _, r in cf_df.iterrows():
            year = str(r["end_date"])[:4]
            if year in common_years:
                if self._safe_float(r.get("c_pay_acq_const_fiolta")) is None:
                    capex_warnings.append(f"{year}: capex（c_pay_acq_const_fiolta）为空，基准结余可能偏高")
        if capex_warnings:
            lines.append("")
            for wm in capex_warnings:
                lines.append(f"> ⚠️ {wm}")

        # AA vs OCF cross-validation
        ocf_values = []
        for _, r in cf_df.iterrows():
            year = str(r["end_date"])[:4]
            if year in [s[0] for s in surplus_data]:
                ocf = self._safe_float(r.get("n_cashflow_act"))
                if ocf is not None:
                    ocf_values.append(ocf)
        if ocf_values:
            ocf_avg = sum(ocf_values) / len(ocf_values)
            if aa_selected > 0 and ocf_avg > 0 and aa_selected / ocf_avg > 2.0:
                lines.append("")
                lines.append(
                    f"> ⚠️ AA/OCF = {aa_selected / ocf_avg:.1f}x，"
                    f"基准结余远超经营现金流（均值 {format_number(ocf_avg)} {self._unit_label()}），"
                    f"可能存在数据缺失导致 W 偏低"
                )

        return "\n".join(lines)

    # --- Phase 3: §17.10-17.13 pre-computation grids ---
    # Design invariant: G does NOT enter R/GG (因子2基准=C 报表利润, 因子3基准=AA).
    # These sections pre-compute the manual arithmetic of phase3_quantitative steps
    # 1 / 10a / 10b / 10c so Agent B selects rows/cells instead of computing.

    def _get_mktcap_shares(self, ts_code: str):
        """Return (mkt_cap_yuan, total_shares, close), replicating §17.9's market-cap
        branching (A股 total_mv 万元, HK total_market_cap 百万, US total_mv raw).

        mkt_cap is in raw currency units (matching financial statements / AA / C).
        Returns None if basic_info or required fields are missing.
        """
        basic_df = self._store.get("basic_info")
        if basic_df is None or basic_df.empty:
            return None
        bi = basic_df.iloc[0]
        close = self._safe_float(bi.get("close"))
        if not close:
            return None
        if self._is_us(ts_code):
            total_mv_raw = self._safe_float(bi.get("total_mv"))  # raw USD
            if not total_mv_raw:
                return None
            mkt_cap = total_mv_raw
            total_shares = total_mv_raw / close
        elif self._is_hk(ts_code):
            total_market_cap = self._safe_float(bi.get("total_market_cap"))  # 百万港元
            if not total_market_cap:
                return None
            mkt_cap = total_market_cap * 1e6  # raw HKD
            total_shares = mkt_cap / close
        else:
            total_mv_wan = self._safe_float(bi.get("total_mv"))  # 万元
            total_share_wan = self._safe_float(bi.get("total_share"))  # 万股
            if not total_mv_wan or not total_share_wan or total_share_wan <= 0:
                return None
            mkt_cap = total_mv_wan * 10000  # 元
            total_shares = total_share_wan * 10000  # 股
        return mkt_cap, total_shares, close

    def _get_rf_ii(self, ts_code: str):
        """Return (rf_val_pct, ii_pct) using the same max() thresholds as §17.2/§17.9.

        港股 max(5, Rf+3)；A股 max(3.5, Rf+2)；美股 max(4, Rf+2).
        Returns (None, None) if risk-free rate is unavailable.
        """
        rf_df = self._store.get("risk_free_rate")
        if rf_df is None or rf_df.empty:
            return None, None
        rf_val = self._safe_float(rf_df.iloc[0].get("yield"))
        if rf_val is None:
            return None, None
        if ts_code.endswith(".HK"):
            ii = max(5.0, rf_val + 3.0)
        elif ts_code.endswith(".US"):
            ii = max(4.0, rf_val + 2.0)
        else:
            ii = max(3.5, rf_val + 2.0)
        return rf_val, ii

    def _tax_scenarios(self, ts_code: str):
        """Return (scenarios, default_rate) encoding shared_tables.md 股息税率表.

        scenarios: list of (label, rate_pct). default_rate: the default channel's rate.
        A股默认持有>1年 0%；港股默认港股通 20%；美股默认 W-8BEN 10%。
        """
        if self._is_hk(ts_code):
            scenarios = [("H股直接", 28.0), ("港股通", 20.0), ("红筹/开曼", 20.0)]
            default_rate = 20.0
        elif self._is_us(ts_code):
            scenarios = [("直接持有", 30.0), ("W-8BEN", 10.0)]
            default_rate = 10.0
        else:
            scenarios = [("持有>1年", 0.0), ("持有1月-1年", 10.0), ("持有<1月", 20.0)]
            default_rate = 0.0
        return scenarios, default_rate

    def _unique_tax_rates(self, ts_code: str):
        """Return (unique_rates, default_rate) — dedup scenario rates preserving order."""
        scenarios, default_rate = self._tax_scenarios(ts_code)
        seen = []
        for _, r in scenarios:
            if r not in seen:
                seen.append(r)
        return seen, default_rate

    @staticmethod
    def _mean_first3(lookup: dict, years: list) -> float | None:
        """Mean of a {year: value} lookup over the first up-to-3 of the given years."""
        vals = [lookup[y] for y in years[:3] if y in lookup]
        return sum(vals) / len(vals) if vals else None

    @staticmethod
    def _min_first3(lookup: dict, years: list) -> float | None:
        """Min of a {year: value} lookup over the first up-to-3 of the given years."""
        vals = [lookup[y] for y in years[:3] if y in lookup]
        return min(vals) if vals else None

    def _compute_payout_crosscheck(self) -> str | None:
        """Compute §17.10: M (payout ratio) three-method cross-check + recommendation.

        法1 §6 逐年 DPS/EPS（港股加静态币种不一致注释，不换算）
        法2 §5 逐年 c_pay_dist_dpcp_int_exp / 归母净利润（含利息及少数股东股利，系上界）
        法3 §17.1 payout 口径（_get_payout_by_year）

        Recommendation (Python):
          三种方法 3 年均值两两相对偏差 > 15% → M_rec=法2 + warning
          A股逐年 DPS 在 ≥3 年完全相同 → 填充错误 warning + M_rec=法2
          否则 → M_rec=法3

        Stores self._store["payout_crosscheck"]. Returns None only if all methods lack data.
        """
        income_df = self._get_annual_df("income")
        if income_df.empty:
            return None
        years = [str(r["end_date"])[:4] for _, r in income_df.iterrows()]  # desc

        np_by_year = {}
        eps_by_year = {}
        for _, r in income_df.iterrows():
            y = str(r["end_date"])[:4]
            np_by_year[y] = self._safe_float(r.get("n_income_attr_p"))
            eps_by_year[y] = self._safe_float(r.get("basic_eps"))

        # --- 法1: DPS / EPS ---
        m1_by_year = {}
        dps_by_year = {}
        currency_note = False
        div_df = self._store.get("dividends")
        hk_df = self._store.get("dividends_hk")
        if div_df is not None and not div_df.empty:
            for _, r in div_df.iterrows():
                y = str(r.get("end_date", ""))[:4]
                v = self._safe_float(r.get("cash_div_tax"))
                if v is not None:
                    dps_by_year[y] = dps_by_year.get(y, 0.0) + v
            for y, dps in dps_by_year.items():
                eps = eps_by_year.get(y)
                if eps and eps > 0:
                    m1_by_year[y] = dps / eps * 100
        elif hk_df is not None and not hk_df.empty:
            currency_note = True
            for _, r in hk_df.iterrows():
                y = str(r.get("end_date", ""))[:4]
                dps = self._safe_float(r.get("dps_hkd"))
                eps = eps_by_year.get(y)
                if dps and eps and eps > 0:
                    m1_by_year[y] = dps / eps * 100

        # --- 法2: cashflow distribution / net profit ---
        m2_by_year = {}
        cf_df = self._get_annual_df("cashflow")
        if not cf_df.empty:
            for _, r in cf_df.iterrows():
                y = str(r["end_date"])[:4]
                dist = self._safe_float(r.get("c_pay_dist_dpcp_int_exp"))
                npv = np_by_year.get(y)
                if dist is not None and npv and npv > 0:
                    m2_by_year[y] = dist / npv * 100

        # --- 法3: §17.1 payout series ---
        m3_by_year = self._get_payout_by_year()

        if not m1_by_year and not m2_by_year and not m3_by_year:
            return None

        m1 = self._mean_first3(m1_by_year, years)
        m2 = self._mean_first3(m2_by_year, years)
        m3 = self._mean_first3(m3_by_year, years)
        m1_min = self._min_first3(m1_by_year, years)
        m2_min = self._min_first3(m2_by_year, years)
        m3_min = self._min_first3(m3_by_year, years)

        # --- Recommendation logic ---
        warnings = []
        means = [(lab, v) for lab, v in [("法1", m1), ("法2", m2), ("法3", m3)] if v is not None]
        max_dev = 0.0
        max_pair = None
        for i in range(len(means)):
            for j in range(i + 1, len(means)):
                a, b = means[i][1], means[j][1]
                denom = (abs(a) + abs(b)) / 2
                if denom > 0:
                    dev = abs(a - b) / denom
                    if dev > max_dev:
                        max_dev = dev
                        max_pair = (means[i][0], means[j][0])

        identical_dps = False
        if div_df is not None and not div_df.empty and dps_by_year:
            dps_vals = [dps_by_year[y] for y in years if y in dps_by_year]
            if len(dps_vals) >= 3 and len({round(v, 6) for v in dps_vals}) == 1:
                identical_dps = True

        def _pick(label):
            return {"法1": m1, "法2": m2, "法3": m3}.get(label)

        if max_dev > 0.15 and m2 is not None:
            m_rec_label = "法2"
            reason = (f"三种方法3年均值两两相对偏差最大 {max_dev * 100:.1f}%"
                      f"（{max_pair[0]} vs {max_pair[1]}）> 15%，采用法2（现金流最可靠）")
            warnings.append(reason)
        elif identical_dps and m2 is not None:
            m_rec_label = "法2"
            reason = "A股逐年 DPS 在 ≥3 年完全相同，高度疑似 Tushare 数据填充错误，采用法2"
            warnings.append(reason)
        elif m3 is not None:
            m_rec_label = "法3"
            reason = "三法一致（偏差 ≤ 15%），采用法3（§17.1 同币种口径）"
        elif m2 is not None:
            m_rec_label = "法2"
            reason = "法3 不可用，回退至法2（现金流口径）"
        else:
            m_rec_label = "法1"
            reason = "仅法1可用"
        m_rec = _pick(m_rec_label)

        if currency_note:
            warnings.append("港股 DPS(HKD) 与 EPS 可能币种不一致，法1 未做汇率换算，仅供参考")

        m_min_rec = {"法1": m1_min, "法2": m2_min, "法3": m3_min}.get(m_rec_label)

        self._store["payout_crosscheck"] = {
            "m1": m1, "m2": m2, "m3": m3,
            "m1_min": m1_min, "m2_min": m2_min, "m3_min": m3_min,
            "m_rec": m_rec, "m_rec_label": m_rec_label,
            "m_min_rec": m_min_rec,
            "m_rec_reason": reason, "warnings": warnings,
        }

        # --- Build output ---
        lines = [format_header(3, "17.10 支付率 M 三重校验"), ""]
        lines.append("> 法2 含利息及少数股东股利，系支付率上界；法3 为 §17.1 同币种口径。"
                     "推荐规则已在 Python 内裁定，LLM 直接引用 M_rec。")
        lines.append("")

        def _pf(v):
            return f"{v:.2f}%" if v is not None else "—"

        headers = ["方法"] + years + ["3年均值", "3年最低档"]
        rows = [
            ["法1 §6 DPS/EPS"] + [_pf(m1_by_year.get(y)) for y in years] + [_pf(m1), _pf(m1_min)],
            ["法2 §5 分配现金/归母"] + [_pf(m2_by_year.get(y)) for y in years] + [_pf(m2), _pf(m2_min)],
            ["法3 §17.1 口径"] + [_pf(m3_by_year.get(y)) for y in years] + [_pf(m3), _pf(m3_min)],
        ]
        lines.append(format_table(headers, rows, alignments=["l"] + ["r"] * (len(years) + 1)))
        lines.append("")
        lines.append(f"- **M_rec = {_pf(m_rec)}（{m_rec_label}）** — {reason}")
        lines.append(f"- **M_min（保守锚，推荐方法近3年最低档）= {_pf(m_min_rec)}** — "
                     "无章程/公告承诺、无稳定规律时，穿透回报率用 M_min 而非均值")
        if currency_note:
            lines.append("- ⚠️ 港股 DPS(HKD)/EPS 币种可能不一致，法1 未换算，仅供参考")
        for wm in warnings:
            lines.append(f"  ⚠️ {wm}")

        return "\n".join(lines)

    def _compute_penetration_grid(self, ts_code: str) -> str | None:
        """Compute §17.11: penetrating return-rate grid (税后).

        表A 主口径 R* = C×k×M候选 × Q列（基准值 C = 最新年归母净利润，k 默认 0.8）。
        表B 现金校验 GG = AA变体 × M候选 × Q列 + HH + Δc + GG−II + 目标买入价（默认Q，R_eff 口径）。
        ★ 标注推荐 M；O=0 默认（加法修正注释）；脚注声明 §17.9 为税前口径、以本节为准。
        """
        f3s = self._store.get("factor3_sensitivity")
        if not f3s:
            return None
        income_df = self._get_annual_df("income")
        if income_df.empty:
            return None
        c = self._safe_float(income_df.iloc[0].get("n_income_attr_p"))
        if c is None:
            return None

        ms = self._get_mktcap_shares(ts_code)
        if ms is None:
            return None
        mkt_cap, total_shares, close = ms
        rf_val, ii = self._get_rf_ii(ts_code)
        if ii is None:
            return None

        # M candidates from §17.10, else fallback to §17.1 3yr mean
        pc = self._store.get("payout_crosscheck")
        raw_ms = []
        rec_label = None
        if pc:
            for lab, key in [("法1", "m1"), ("法2", "m2"), ("法3", "m3")]:
                v = pc.get(key)
                if v is not None:
                    raw_ms.append((lab, v))
            rec_label = pc.get("m_rec_label")
        else:
            years = [str(r["end_date"])[:4] for _, r in income_df.iterrows()]
            m3v = self._mean_first3(self._get_payout_by_year(), years)
            if m3v is not None:
                raw_ms.append(("法3", m3v))
                rec_label = "法3"
        if not raw_ms:
            return None
        if rec_label not in [lab for lab, _ in raw_ms]:
            rec_label = raw_ms[0][0]
        m_min_rec = pc.get("m_min_rec") if pc else None
        if m_min_rec is not None and rec_label:
            raw_ms.append(("M_min(保守)", m_min_rec))

        # Reorder recommended first, dedup within 0.5 pct
        ordered = [e for e in raw_ms if e[0] == rec_label] + [e for e in raw_ms if e[0] != rec_label]
        m_candidates = []
        for lab, v in ordered:
            if any(abs(v - kv) < 0.5 for _, kv in m_candidates):
                continue
            m_candidates.append((lab, v))

        # AA variants (dedup identical values)
        aa_raw = [("AA_2y", f3s.get("aa_2y")), ("AA_all", f3s.get("aa_all")),
                  ("AA_excl", f3s.get("aa_excl"))]
        aa_variants = []
        for lab, v in aa_raw:
            if v is None:
                continue
            if any(abs(v - kv) < 1e4 for _, kv in aa_variants):
                continue
            aa_variants.append((lab, v))
        if not aa_variants:
            return None

        q_rates, q_default = self._unique_tax_rates(ts_code)
        o_val = 0.0
        mkt_cap_mm = mkt_cap / 1e6
        o_increment = 100.0 / mkt_cap_mm * 100 if mkt_cap_mm > 0 else 0.0

        lines = [format_header(3, "17.11 穿透回报率网格（税后）"), ""]
        lines.append(f"> 基准值 C（最新年归母净利润）= {format_number(c)} {self._unit_label()}，"
                     f"市值 = {format_number(mkt_cap)} {self._unit_label()}，"
                     f"当前股价 = {close:.2f} {self._price_unit()}，"
                     f"门槛 II = {ii:.2f}%，O = 0（默认）。")
        lines.append(f"> O 加法修正：每确认 100 {self._unit_label()} 年均注销型回购，"
                     f"穿透回报率 +{o_increment:.4f} pct（= 100/市值×100）。")
        lines.append("")

        def _qlabel(q):
            tag = "（默认）" if q == q_default else ""
            return f"Q={q:g}%{tag}"

        # --- Table A: 主口径 R*（C×k×M/市值，k 默认 0.8）---
        k_default = 0.8  # 利润折扣系数（默认0.8；可预测性 高0.9/中0.8/低0.7，保守方向取小值）
        lines.append("#### 表A：主口径穿透回报率 R*（基准值 = C 归母净利润 × 折扣系数 k，默认 k=0.8）")
        lines.append("")
        headers_a = ["支付率 M"] + [_qlabel(q) for q in q_rates]
        rows_a = []
        for lab, m in m_candidates:
            star = " ★" if lab == rec_label else ""
            row = [f"{lab} {m:.2f}%{star}"]
            for q in q_rates:
                r = (c * k_default * m / 100 * (1 - q / 100) + o_val) / mkt_cap * 100
                row.append(f"{r:.2f}%")
            rows_a.append(row)
        lines.append(format_table(headers_a, rows_a, alignments=["l"] + ["r"] * len(q_rates)))
        lines.append("")
        lines.append("> k 档位：可预测性 高→0.9 / 中→0.8（默认）/ 低→0.7，保守方向取小值；"
                     f"k 每 ±0.1 → R* 按 C×0.1×M×(1−Q)/市值 线性调整（表内为 k=0.8 默认列）。"
                     "账面口径 R（k=1）= 表A 对应值 ÷ 0.8，交叉校验用。")
        lines.append("")

        # --- Table B: 现金校验 GG + 有效口径 R_eff ---
        lines.append("#### 表B：现金校验口径 GG（基准值 = AA 真实可支配现金结余）+ 有效口径 R_eff")
        lines.append("")
        headers_b = (["AA×M"] + [f"GG {_qlabel(q)}" for q in q_rates]
                     + ["HH(默认Q) pct", "Δc(默认Q) pct", "GG−II(默认Q) pct",
                        f"目标买入价（{self._price_unit()}，R_eff 口径）"])
        rows_b = []
        for aalab, aa in aa_variants:
            for mlab, m in m_candidates:
                star = " ★" if mlab == rec_label else ""
                row = [f"{aalab}×{mlab}{star}"]
                gg_default = None
                for q in q_rates:
                    gg = (aa * m / 100 * (1 - q / 100) + o_val) / mkt_cap * 100
                    if q == q_default:
                        gg_default = gg
                    row.append(f"{gg:.2f}%")
                r_default = (c * m / 100 * (1 - q_default / 100) + o_val) / mkt_cap * 100
                r_star_default = (c * k_default * m / 100 * (1 - q_default / 100) + o_val) / mkt_cap * 100
                hh = r_default - (gg_default if gg_default is not None else 0.0)
                delta_c = r_star_default - (gg_default if gg_default is not None else 0.0)
                r_eff = gg_default if delta_c >= 2.0 else r_star_default
                row.append(f"{hh:+.2f}")
                row.append(f"{delta_c:+.2f}")
                row.append(f"{(gg_default - ii):+.2f}")
                tbp = close * r_eff / ii if ii > 0 else 0.0
                row.append(f"{tbp:.2f}")
                rows_b.append(row)
        lines.append(format_table(headers_b, rows_b,
                                  alignments=["l"] + ["r"] * (len(q_rates) + 4)))
        lines.append("")
        lines.append("> 目标买入价 = 当前股价 × R_eff / II（默认 Q、k=0.8）；Δc ≥ 2pct → 现金验证失败，"
                     "R_eff = GG；否则 R_eff = R*。HH = R − GG 为账面-现金偏差。★ 为推荐 M。")
        lines.append("> 脚注：§17.9 的穿透回报率为**税前**口径（快速敏感性）；含税结果以本节 §17.11 为准。")

        return "\n".join(lines)

    def _compute_g_grid(self, ts_code: str = "") -> str | None:
        """Compute §17.12: standalone G→维持性Capex 网格（12 行）。

        G = 0.7 … 1.8 步长 0.1；H = D×G；OE = C + D − H = C + D(1−G)。
        附 F 参考值（Capex/D&A 5年中位数）与档位标签（轻/轻中/中/中重/重）。
        LLM 仅选行，禁止自算。
        """
        income_df = self._get_annual_df("income")
        cf_df = self._get_annual_df("cashflow")
        if income_df.empty or cf_df.empty:
            return None
        c = self._safe_float(income_df.iloc[0].get("n_income_attr_p"))
        if c is None:
            return None

        latest_cf = cf_df.iloc[0]
        da = 0.0
        any_da = False
        for col in ["depr_fa_coga_dpba", "amort_intang_assets", "lt_amort_deferred_exp"]:
            v = self._safe_float(latest_cf.get(col))
            if v is not None:
                da += v
                any_da = True
        if not any_da or da <= 0:
            return None
        d = da

        # F reference: Capex/D&A 5yr median
        capex_da_vals = []
        for _, r in cf_df.iterrows():
            dep = self._safe_float(r.get("depr_fa_coga_dpba"))
            ai = self._safe_float(r.get("amort_intang_assets"))
            ad = self._safe_float(r.get("lt_amort_deferred_exp"))
            comps = [x for x in [dep, ai, ad] if x is not None]
            day = sum(comps) if comps else None
            cap = self._safe_float(r.get("c_pay_acq_const_fiolta"))
            if day and day > 0 and cap is not None:
                capex_da_vals.append(abs(cap) / day)
        f_ref = None
        if capex_da_vals:
            sv = sorted(capex_da_vals)
            mid = len(sv) // 2
            f_ref = sv[mid] if len(sv) % 2 else (sv[mid - 1] + sv[mid]) / 2

        def _band(g):
            if g <= 0.95:
                return "轻"
            if g <= 1.15:
                return "轻中"
            if g <= 1.35:
                return "中"
            if g <= 1.55:
                return "中重"
            return "重"

        lines = [format_header(3, "17.12 G 系数网格（维持性 Capex）"), ""]
        lines.append(f"> C 归母净利润 = {format_number(c)} {self._unit_label()}，"
                     f"D 折旧摊销 = {format_number(d)} {self._unit_label()}，"
                     f"F（Capex/D&A 5年中位数）= {f_ref:.2f}"
                     if f_ref is not None else
                     f"> C 归母净利润 = {format_number(c)} {self._unit_label()}，"
                     f"D 折旧摊销 = {format_number(d)} {self._unit_label()}，F = —")
        lines.append("> OE = C + D − H = C + D×(1−G)。**LLM 仅选行，禁止自算。**")
        lines.append("")
        headers = ["G", f"维持性Capex H = D×G（{self._unit_label()}）",
                   f"Owner Earnings OE（{self._unit_label()}）", "档位"]
        rows = []
        for i in range(12):
            g = round(0.7 + 0.1 * i, 1)
            h = d * g
            oe = c + d - h
            rows.append([f"{g:.1f}", format_number(h), format_number(oe), _band(g)])
        lines.append(format_table(headers, rows, alignments=["r", "r", "r", "c"]))

        return "\n".join(lines)

    def _compute_revenue_sensitivity(self, ts_code: str) -> str | None:
        """Compute §17.13: λ revenue sensitivity on the DEFAULT combo.

        结余(k) = AA_default + λ×(k−1)×S_latest；m′ = M_rec/100×(1−Q_default/100)；
        GG(k) = 结余(k)×m′ / 市值 × 100；临界收入倍数 k* 令 GG(k)=II。
        λ 缺失/≈0 或 m′≤0 → 降级段（"—" + ⚠️）。
        """
        f3s = self._store.get("factor3_sensitivity")
        if not f3s:
            return None
        aa_default = f3s.get("aa_selected")
        if aa_default is None:
            return None
        lam = f3s.get("lambda_median")
        lam_reliability = f3s.get("lambda_reliability")
        lam_warnings = f3s.get("lambda_warnings") or []

        income_df = self._get_annual_df("income")
        if income_df.empty:
            return None
        s_latest = self._safe_float(income_df.iloc[0].get("revenue"))
        if s_latest is None or s_latest <= 0:
            return None

        ms = self._get_mktcap_shares(ts_code)
        if ms is None:
            return None
        mkt_cap, total_shares, close = ms
        rf_val, ii = self._get_rf_ii(ts_code)
        if ii is None:
            return None

        # M_rec + default Q
        pc = self._store.get("payout_crosscheck")
        m_rec = pc.get("m_rec") if pc else None
        if m_rec is None:
            years = [str(r["end_date"])[:4] for _, r in income_df.iterrows()]
            m_rec = self._mean_first3(self._get_payout_by_year(), years)
        if m_rec is None:
            return None
        q_rates, q_default = self._unique_tax_rates(ts_code)
        m_prime = m_rec / 100 * (1 - q_default / 100)

        lines = [format_header(3, "17.13 收入敏感性（λ 外推）"), ""]
        lines.append(f"> AA_default = {format_number(aa_default)} {self._unit_label()}，"
                     f"S 最新年收入 = {format_number(s_latest)} {self._unit_label()}，"
                     f"M_rec = {m_rec:.2f}%，默认 Q = {q_default:g}%，"
                     f"m′ = M_rec×(1−Q) = {m_prime * 100:.2f}%，II = {ii:.2f}%。")
        lines.append("> 本表为**现金校验口径 GG(k)**（校验维度；主口径 R* 不随收入情景变动）。"
                     "基于**默认组合**（M_rec × 默认Q × AA_default）计算；"
                     "其他 M/Q 选择按 M×(1−Q) 比例缩放 GG。")
        lines.append("")

        degraded = lam is None or abs(lam) < 1e-9 or m_prime <= 0
        if degraded:
            reason = ("λ 缺失" if lam is None else
                      ("λ≈0（收入变动不传导至结余）" if abs(lam) < 1e-9 else "m′≤0"))
            lines.append(f"- ⚠️ 降级：{reason}，无法外推收入敏感性。")
            headers = ["收入情景", "结余", "现金口径 GG(k)", "vs 门槛"]
            rows = [[f"{k:.1f}×", "—", "—", "—"] for k in [1.0, 0.9, 0.8, 0.7]]
            lines.append(format_table(headers, rows, alignments=["l", "r", "r", "r"]))
            lines.append("- 临界收入倍数 k* = —")
            return "\n".join(lines)

        lines.append(f"- 经营杠杆 λ = {lam:.4f}（可靠性：{lam_reliability or '—'}）")
        for wm in lam_warnings:
            lines.append(f"  ⚠️ {wm}")
        lines.append("")

        headers = ["收入情景", f"结余（{self._unit_label()}）", "现金口径 GG(k)", "vs 门槛 pct"]
        rows = []
        for k in [1.0, 0.9, 0.8, 0.7]:
            bal = aa_default + lam * (k - 1) * s_latest
            gg = bal * m_prime / mkt_cap * 100
            rows.append([f"{k:.1f}×", format_number(bal), f"{gg:.2f}%", f"{(gg - ii):+.2f}"])
        lines.append(format_table(headers, rows, alignments=["l", "r", "r", "r"]))
        lines.append("")

        # Critical revenue multiple k* solving GG(k)=II
        denom = lam * s_latest
        if abs(denom) > 0:
            k_star = 1 + (ii / 100 * mkt_cap / m_prime - aa_default) / denom
            lines.append(f"- 临界收入倍数 k* = {k_star:.2f}（令 GG(k) = II 反解，现金口径校验维度）")
            if k_star >= 0.85:
                resilience = "敏感（k* ≥ 0.85）"
            elif k_star >= 0.70:
                resilience = "中等（0.70 ≤ k* < 0.85）"
            else:
                resilience = "强（k* < 0.70）"
            lines.append(f"- 安全边际韧性：{resilience}")
        else:
            lines.append("- 临界收入倍数 k* = —（λ×S ≈ 0）")

        return "\n".join(lines)
