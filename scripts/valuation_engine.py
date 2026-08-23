#!/usr/bin/env python3
"""Valuation Engine — deterministic valuation computations.

Computes company classification, WACC, and multiple valuation methods
(DCF, DDM, PE Band, PEG, PS) with sensitivity tables.

Usage:
    python3 scripts/valuation_engine.py --code 600887 --output-dir output/600887_伊利/
"""

import argparse
import math
import os
import statistics
import sys
from datetime import datetime

import pandas as pd

from config import get_token, validate_stock_code
from format_utils import format_number, format_table, format_header

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Classification thresholds (matching classification_rules.md)
ROE_BLUE_CHIP_THRESHOLD = 15.0       # ROE 5yr avg > 15%
PAYOUT_BLUE_CHIP_THRESHOLD = 30.0    # Dividend payout 3yr avg > 30%
REV_GROWTH_THRESHOLD = 20.0          # Revenue CAGR 5yr
PROFIT_GROWTH_THRESHOLD = 25.0       # Net profit CAGR 5yr

# Method weights by company type
METHOD_WEIGHTS = {
    "蓝筹价值型": {"DCF": 40, "DDM": 30, "PE_Band": 30},
    "成长型": {"PEG": 35, "DCF_Scenarios": 35, "PS": 30},
    "混合型": {"DCF": 35, "PE_Band": 25, "PEG": 25, "DDM": 15},
}

# WACC parameters by market
MARKET_PARAMS = {
    "A": {"erp": 6.0, "rf_default": 2.5, "tax_default": 25.0, "g_terminal": 3.0},
    "HK": {"erp": 5.5, "rf_default": 4.0, "tax_default": 16.5, "g_terminal": 2.5},
    "US": {"erp": 5.0, "rf_default": 4.0, "tax_default": 21.0, "g_terminal": 2.5},
}

# Beta by market cap (百万元)
BETA_BY_CAP = [
    (1_000_000, 0.8),   # > 1000亿 (> 1,000,000 百万元)
    (100_000, 1.0),     # 100-1000亿
    (0, 1.2),           # < 100亿
]


# ---------------------------------------------------------------------------
# ValuationEngine
# ---------------------------------------------------------------------------

class ValuationEngine:
    """Deterministic valuation computation engine.

    Requires a TushareClient with populated _store (call assemble_data_pack first).
    """

    def __init__(self, ts_code: str, output_dir: str, client):
        self.ts_code = ts_code
        self.output_dir = output_dir
        self.client = client

        # Detect market
        if ts_code.endswith(".HK"):
            self.market = "HK"
        elif ts_code.endswith(".US") or (not ts_code.endswith(".SH") and not ts_code.endswith(".SZ")):
            self.market = "US"
        else:
            self.market = "A"

        self.params = MARKET_PARAMS[self.market]
        self._sf = client._safe_float  # shorthand

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _annual_df(self, key: str) -> pd.DataFrame:
        return self.client._get_annual_df(key)

    def _annual_series(self, key: str, col: str) -> list[tuple[str, float | None]]:
        return self.client._get_annual_series(key, col)

    def _unit(self) -> str:
        return self.client._unit_label()

    def _price_unit(self) -> str:
        return self.client._price_unit()

    def _basic_info(self) -> dict:
        """Extract key basic info fields."""
        bi_df = self.client._store.get("basic_info")
        if bi_df is None or bi_df.empty:
            return {}
        row = bi_df.iloc[0]
        close = self._sf(row.get("close"))

        if self.market == "HK":
            total_mv = self._sf(row.get("total_market_cap"))  # 百万港元
            total_shares = (total_mv * 1e6 / close) if (total_mv and close) else None
            mkt_cap_mm = total_mv
        elif self.market == "US":
            total_mv = self._sf(row.get("total_mv"))  # raw USD
            total_shares = (total_mv / close) if (total_mv and close) else None
            mkt_cap_mm = total_mv / 1e6 if total_mv else None
        else:
            total_mv_wan = self._sf(row.get("total_mv"))  # 万元
            total_share_wan = self._sf(row.get("total_share"))  # 万股
            mkt_cap_mm = total_mv_wan / 100 if total_mv_wan else None  # 百万元
            total_shares = total_share_wan * 10000 if total_share_wan else None
            close = close

        return {
            "close": close,
            "pe_ttm": self._sf(row.get("pe_ttm") or row.get("pe")),
            "pb": self._sf(row.get("pb")),
            "mkt_cap_mm": mkt_cap_mm,
            "total_shares": total_shares,
            "name": row.get("name", ""),
        }

    @staticmethod
    def _cagr(vals: list[float | None]) -> float | None:
        """Compute CAGR from a desc-ordered list [latest, ..., oldest]."""
        clean = [v for v in vals if v is not None and v > 0]
        if len(clean) < 2:
            return None
        latest, oldest = clean[0], clean[-1]
        n = len(clean) - 1
        if oldest <= 0:
            return None
        return (latest / oldest) ** (1 / n) - 1

    def _interest_bearing_debt(self, row) -> float:
        total = 0.0
        for c in ("st_borr", "lt_borr", "bond_payable", "non_cur_liab_due_1y"):
            v = self._sf(row.get(c))
            if v is not None:
                total += v
        return total

    # ------------------------------------------------------------------
    # 1. Classification
    # ------------------------------------------------------------------

    def classify(self) -> dict:
        """Classify company and select valuation methods."""
        income_df = self._annual_df("income")
        fi_df = self._annual_df("fina_indicators")

        # ROE 5yr avg
        roe_vals = []
        if not fi_df.empty and "roe_waa" in fi_df.columns:
            for _, r in fi_df.head(5).iterrows():
                v = self._sf(r.get("roe_waa"))
                if v is not None:
                    roe_vals.append(v)
        if not roe_vals and not income_df.empty:
            bs_df = self._annual_df("balance_sheet")
            if not bs_df.empty:
                bs_by_year = {str(r["end_date"])[:4]: r for _, r in bs_df.iterrows()}
                for _, r in income_df.head(5).iterrows():
                    yr = str(r["end_date"])[:4]
                    np_val = self._sf(r.get("n_income_attr_p"))
                    eq = self._sf(bs_by_year.get(yr, {}).get("total_hldr_eqy_exc_min_int"))
                    if np_val and eq and eq > 0:
                        roe_vals.append(np_val / eq * 100)
        roe_avg = statistics.mean(roe_vals) if roe_vals else None

        # Payout 3yr avg
        payout_lookup = self.client._get_payout_by_year()
        years = [str(r["end_date"])[:4] for _, r in income_df.iterrows()] if not income_df.empty else []
        payout_vals = [payout_lookup[y] for y in years[:3] if y in payout_lookup]
        payout_avg = statistics.mean(payout_vals) if payout_vals else None

        # Revenue CAGR 5yr
        rev_series = [self._sf(r.get("revenue")) for _, r in income_df.head(5).iterrows()]
        rev_cagr = self._cagr(rev_series)
        rev_cagr_pct = rev_cagr * 100 if rev_cagr is not None else None

        # Net profit CAGR 5yr
        np_series = [self._sf(r.get("n_income_attr_p")) for _, r in income_df.head(5).iterrows()]
        np_cagr = self._cagr(np_series)
        np_cagr_pct = np_cagr * 100 if np_cagr is not None else None

        # Score
        blue_score = 0
        growth_score = 0
        if roe_avg is not None and roe_avg > ROE_BLUE_CHIP_THRESHOLD:
            blue_score += 1
        if payout_avg is not None and payout_avg > PAYOUT_BLUE_CHIP_THRESHOLD:
            blue_score += 1
        if rev_cagr_pct is not None and rev_cagr_pct < REV_GROWTH_THRESHOLD:
            blue_score += 1
        if rev_cagr_pct is not None and rev_cagr_pct > REV_GROWTH_THRESHOLD:
            growth_score += 1
        if np_cagr_pct is not None and np_cagr_pct > PROFIT_GROWTH_THRESHOLD:
            growth_score += 1

        # Determine type
        if blue_score >= 2 and growth_score == 0:
            company_type = "蓝筹价值型"
        elif growth_score >= 2 and blue_score <= 1:
            company_type = "成长型"
        else:
            company_type = "混合型"

        # Check for loss company override
        latest_np = self._sf(income_df.iloc[0].get("n_income_attr_p")) if not income_df.empty else None
        if latest_np is not None and latest_np < 0:
            company_type = "成长型"  # force growth (PE/PEG N/A, use PS)

        methods = list(METHOD_WEIGHTS.get(company_type, METHOD_WEIGHTS["混合型"]).keys())
        weights = dict(METHOD_WEIGHTS.get(company_type, METHOD_WEIGHTS["混合型"]))

        # DDM supplement for 混合型 if payout > 20%
        if company_type == "混合型" and payout_avg is not None and payout_avg <= 20:
            methods = [m for m in methods if m != "DDM"]
            if "DDM" in weights:
                ddm_w = weights.pop("DDM")
                for m in weights:
                    weights[m] += ddm_w // len(weights)

        return {
            "type": company_type,
            "blue_score": blue_score,
            "growth_score": growth_score,
            "roe_avg": roe_avg,
            "payout_avg": payout_avg,
            "rev_cagr_pct": rev_cagr_pct,
            "np_cagr_pct": np_cagr_pct,
            "methods": methods,
            "weights": weights,
        }

    # ------------------------------------------------------------------
    # 2. WACC
    # ------------------------------------------------------------------

    def compute_wacc(self) -> dict:
        """Compute WACC and return all intermediate values."""
        bi = self._basic_info()
        mkt_cap_mm = bi.get("mkt_cap_mm") or 0

        # Rf
        rf_df = self.client._store.get("risk_free_rate")
        rf = None
        if rf_df is not None and not rf_df.empty:
            rf = self._sf(rf_df.iloc[0].get("yield"))
        if rf is None:
            rf = self.params["rf_default"]

        # Beta by market cap
        beta = 1.0
        for threshold, b in BETA_BY_CAP:
            if mkt_cap_mm > threshold:
                beta = b
                break

        erp = self.params["erp"]
        ke = rf + beta * erp

        # Kd
        income_df = self._annual_df("income")
        bs_df = self._annual_df("balance_sheet")
        finance_exp = None
        if not income_df.empty:
            finance_exp = self._sf(income_df.iloc[0].get("finance_exp"))

        debt_latest = 0.0
        debt_prev = 0.0
        if not bs_df.empty:
            debt_latest = self._interest_bearing_debt(bs_df.iloc[0])
            if len(bs_df) > 1:
                debt_prev = self._interest_bearing_debt(bs_df.iloc[1])
        avg_debt = (debt_latest + debt_prev) / 2 if (debt_latest + debt_prev) > 0 else 0

        if finance_exp and finance_exp > 0 and avg_debt > 0:
            kd_pre = finance_exp / avg_debt * 100
        else:
            kd_pre = rf + 1.0

        # Capital structure (market cap in raw units to match debt)
        # debt is in raw yuan (from _store), mkt_cap_mm is in millions
        debt_mm = debt_latest / 1e6 if self.market == "A" else debt_latest / 1e6
        # For A-share: _store amounts are in raw yuan, mkt_cap_mm is 万元/100
        # Actually _store amounts depend on how they're stored.
        # The balance sheet from tushare returns values in yuan for A-shares.
        # mkt_cap_mm is already in 百万元.
        # So debt needs to be converted to 百万元 too.
        if self.market == "A":
            e_val = mkt_cap_mm  # 百万元
            d_val = debt_latest / 1e6  # raw yuan → 百万元
        elif self.market == "HK":
            e_val = mkt_cap_mm  # 百万港元
            d_val = debt_latest / 1e6  # raw HKD → 百万港元
        else:
            e_val = mkt_cap_mm  # 百万美元
            d_val = debt_latest / 1e6  # raw USD → 百万美元

        total = e_val + d_val
        e_weight = e_val / total * 100 if total > 0 else 100
        d_weight = d_val / total * 100 if total > 0 else 0

        # Tax rate
        tax_rates = []
        for _, r in income_df.head(5).iterrows():
            tax = self._sf(r.get("income_tax"))
            pre_tax = self._sf(r.get("total_profit"))
            if tax is not None and pre_tax and pre_tax > 0:
                tax_rates.append(tax / pre_tax * 100)
        tax_rate = statistics.mean(tax_rates) if tax_rates else self.params["tax_default"]

        # WACC
        if d_val <= 0:
            wacc = ke
        else:
            wacc = ke * e_weight / 100 + kd_pre * (1 - tax_rate / 100) * d_weight / 100

        return {
            "rf": rf, "beta": beta, "erp": erp, "ke": ke,
            "kd_pre": kd_pre, "tax_rate": tax_rate,
            "e_weight": e_weight, "d_weight": d_weight,
            "wacc": wacc,
            "mkt_cap_mm": mkt_cap_mm,
            "debt_mm": d_val,
            "e_val": e_val, "d_val": d_val,
        }

    # ------------------------------------------------------------------
    # 3. DCF (Stable)
    # ------------------------------------------------------------------

    def dcf_stable(self, wacc_data: dict) -> dict | None:
        """DCF for stable companies (蓝筹/混合)."""
        cf_df = self._annual_df("cashflow")
        bi = self._basic_info()
        bs_df = self._annual_df("balance_sheet")

        if cf_df.empty or not bi.get("total_shares"):
            return None

        wacc = wacc_data["wacc"]
        total_shares = bi["total_shares"]

        # FCF series
        fcf_list = []
        for _, r in cf_df.head(5).iterrows():
            ocf = self._sf(r.get("n_cashflow_act"))
            capex = self._sf(r.get("c_pay_acq_const_fiolta"))
            if ocf is not None and capex is not None:
                fcf_list.append(ocf - abs(capex))

        if len(fcf_list) < 2:
            return None

        # FCF base (3yr avg, excluding outlier if any)
        base_pool = fcf_list[:3] if len(fcf_list) >= 3 else fcf_list
        fcf_base = statistics.mean(base_pool)
        all_negative = all(f <= 0 for f in fcf_list)

        # Growth assumptions
        fcf_cagr = self._cagr(fcf_list)
        if fcf_cagr is not None and fcf_cagr > 0:
            g_hist = fcf_cagr * 100
        else:
            # Fallback to revenue CAGR
            rev_series = [self._sf(r.get("revenue")) for _, r in self._annual_df("income").head(5).iterrows()]
            rev_cagr = self._cagr(rev_series)
            g_hist = rev_cagr * 100 if rev_cagr is not None else 5.0

        g_conservative = g_hist * 0.8
        g_terminal = self.params["g_terminal"]

        # Ensure g_terminal < WACC
        if g_terminal >= wacc:
            g_terminal = wacc - 2.0

        g_fade = (g_conservative + g_terminal) / 2
        g_fade2 = (g_fade + g_terminal) / 2

        # Project FCF
        growth_rates = [g_conservative, g_conservative, g_fade, g_fade2, g_terminal]
        projected = []
        prev = fcf_base
        for g in growth_rates:
            prev = prev * (1 + g / 100)
            projected.append(prev)

        # Terminal value
        tv = projected[-1] * (1 + g_terminal / 100) / (wacc / 100 - g_terminal / 100)

        # Present values
        pv_fcf = sum(f / (1 + wacc / 100) ** (i + 1) for i, f in enumerate(projected))
        pv_tv = tv / (1 + wacc / 100) ** 5
        ev = pv_fcf + pv_tv
        tv_pct = pv_tv / ev * 100 if ev > 0 else 0

        # Cash and debt
        cash = self._sf(bs_df.iloc[0].get("money_cap")) if not bs_df.empty else 0
        cash = cash or 0
        debt_raw = self._interest_bearing_debt(bs_df.iloc[0]) if not bs_df.empty else 0

        equity_value = ev + cash - debt_raw
        intrinsic = equity_value / total_shares if total_shares > 0 else 0

        # Sensitivity matrix 5x5
        wacc_range = [wacc - 2, wacc - 1, wacc, wacc + 1, wacc + 2]
        g_range = [g_terminal - 1, g_terminal - 0.5, g_terminal, g_terminal + 0.5, g_terminal + 1]
        sensitivity = []
        for w in wacc_range:
            row = []
            for g in g_range:
                if g >= w:
                    row.append(None)
                    continue
                # Simplified: re-project with same cash flows but different TV
                tv_s = projected[-1] * (1 + g / 100) / (w / 100 - g / 100)
                pv_fcf_s = sum(f / (1 + w / 100) ** (i + 1) for i, f in enumerate(projected))
                pv_tv_s = tv_s / (1 + w / 100) ** 5
                ev_s = pv_fcf_s + pv_tv_s
                eq_s = ev_s + cash - debt_raw
                row.append(eq_s / total_shares if total_shares > 0 else 0)
            sensitivity.append(row)

        return {
            "method": "DCF",
            "intrinsic": intrinsic,
            "fcf_base": fcf_base,
            "g_conservative": g_conservative,
            "g_terminal": g_terminal,
            "tv_pct": tv_pct,
            "all_negative": all_negative,
            "projected_fcf": projected,
            "growth_rates": growth_rates,
            "pv_fcf": pv_fcf,
            "pv_tv": pv_tv,
            "ev": ev,
            "cash": cash,
            "debt_raw": debt_raw,
            "equity_value": equity_value,
            "sensitivity": sensitivity,
            "wacc_range": wacc_range,
            "g_range": g_range,
        }

    # ------------------------------------------------------------------
    # 4. DCF (Scenarios)
    # ------------------------------------------------------------------

    def dcf_scenarios(self, wacc_data: dict) -> dict | None:
        """DCF with 3 scenarios for growth companies."""
        cf_df = self._annual_df("cashflow")
        income_df = self._annual_df("income")
        bi = self._basic_info()
        bs_df = self._annual_df("balance_sheet")

        if cf_df.empty or income_df.empty or not bi.get("total_shares"):
            return None

        wacc = wacc_data["wacc"]
        total_shares = bi["total_shares"]
        g_terminal = self.params["g_terminal"]
        if g_terminal >= wacc:
            g_terminal = wacc - 2.0

        # Historical metrics
        rev_series = [self._sf(r.get("revenue")) for _, r in income_df.head(5).iterrows()]
        rev_cagr = self._cagr(rev_series)
        rev_cagr_pct = rev_cagr * 100 if rev_cagr is not None else 10.0

        # Latest financials
        latest_inc = income_df.iloc[0]
        latest_cf = cf_df.iloc[0]
        revenue = self._sf(latest_inc.get("revenue")) or 0
        np_val = self._sf(latest_inc.get("n_income_attr_p")) or 0
        net_margin = np_val / revenue * 100 if revenue > 0 else 5.0

        ocf = self._sf(latest_cf.get("n_cashflow_act")) or 0
        capex = abs(self._sf(latest_cf.get("c_pay_acq_const_fiolta")) or 0)
        capex_rev = capex / revenue if revenue > 0 else 0.05

        da_components = [
            self._sf(latest_cf.get("depr_fa_coga_dpba")) or 0,
            self._sf(latest_cf.get("amort_intang_assets")) or 0,
            self._sf(latest_cf.get("lt_amort_deferred_exp")) or 0,
        ]
        da = sum(da_components)

        cash = self._sf(bs_df.iloc[0].get("money_cap")) if not bs_df.empty else 0
        cash = cash or 0
        debt_raw = self._interest_bearing_debt(bs_df.iloc[0]) if not bs_df.empty else 0

        def _project_scenario(rev_g_factors, margin_adj, capex_factor):
            projected = []
            rev = revenue
            for i in range(5):
                g = rev_g_factors[i] if i < len(rev_g_factors) else rev_g_factors[-1]
                rev = rev * (1 + g / 100)
                margin = net_margin + margin_adj * (i + 1)
                np_s = rev * margin / 100
                capex_s = rev * capex_rev * capex_factor
                fcf_s = np_s + da - capex_s
                projected.append(fcf_s)
            return projected

        # Optimistic: historical CAGR maintained, margin improves
        opt_g = [rev_cagr_pct] * 5
        opt_fcf = _project_scenario(opt_g, 0.5, 1.0)

        # Base: CAGR × 0.7, margin flat
        base_g = [rev_cagr_pct * 0.7] * 5
        base_fcf = _project_scenario(base_g, 0.0, 1.0)

        # Pessimistic: CAGR × 0.4 for 2yr, 0% after, margin compresses
        pess_g = [rev_cagr_pct * 0.4, rev_cagr_pct * 0.4, 0, 0, 0]
        pess_fcf = _project_scenario(pess_g, -0.3, 1.2)

        def _dcf_value(projected_fcf):
            if not projected_fcf or projected_fcf[-1] <= 0:
                tv = 0
            else:
                tv = projected_fcf[-1] * (1 + g_terminal / 100) / (wacc / 100 - g_terminal / 100)
            pv_fcf = sum(f / (1 + wacc / 100) ** (i + 1) for i, f in enumerate(projected_fcf))
            pv_tv = tv / (1 + wacc / 100) ** 5
            ev = pv_fcf + pv_tv
            eq = ev + cash - debt_raw
            return eq / total_shares if total_shares > 0 else 0

        v_opt = _dcf_value(opt_fcf)
        v_base = _dcf_value(base_fcf)
        v_pess = _dcf_value(pess_fcf)

        weighted = 0.25 * v_opt + 0.50 * v_base + 0.25 * v_pess

        return {
            "method": "DCF_Scenarios",
            "intrinsic": weighted,
            "v_optimistic": v_opt,
            "v_base": v_base,
            "v_pessimistic": v_pess,
            "rev_cagr_pct": rev_cagr_pct,
            "net_margin": net_margin,
            "scenarios": {
                "optimistic": {"growth": opt_g, "fcf": opt_fcf, "value": v_opt},
                "base": {"growth": base_g, "fcf": base_fcf, "value": v_base},
                "pessimistic": {"growth": pess_g, "fcf": pess_fcf, "value": v_pess},
            },
        }

    # ------------------------------------------------------------------
    # 5. DDM
    # ------------------------------------------------------------------

    def _aggregate_annual_dps(self) -> list[tuple[str, float]]:
        """Aggregate DPS by fiscal year, summing interim + final dividends.

        Returns list of (year, total_dps) sorted desc by year.
        Also cross-validates against cash flow dividends paid (§5).
        """
        div_df = self.client._store.get("dividends")
        if div_df is None or div_df.empty:
            return []

        # Sum cash_div_tax per fiscal year
        yearly = {}
        for _, r in div_df.iterrows():
            year = str(r.get("end_date", ""))[:4]
            if not year:
                continue
            dps = self._sf(r.get("cash_div_tax")) or 0
            yearly[year] = yearly.get(year, 0) + dps

        # Cross-validate against §5 dividends paid; fix incomplete years
        cf_df = self._annual_df("cashflow")
        bi = self._basic_info()
        total_shares = bi.get("total_shares")
        if not cf_df.empty and total_shares and total_shares > 0:
            cf_by_year = {str(r["end_date"])[:4]: r for _, r in cf_df.iterrows()}
            for year in list(yearly.keys()):
                cf_row = cf_by_year.get(year)
                if cf_row is None:
                    continue
                div_paid = self._sf(cf_row.get("c_pay_dist_dpcp_int_exp"))
                if not div_paid or div_paid <= 0:
                    continue
                # Tushare reports div_paid as positive (absolute outflow)
                dps_total = yearly[year]
                implied = dps_total * total_shares
                ratio = implied / div_paid if div_paid > 0 else 0
                if 0 < ratio < 0.5:
                    # DPS from dividend API is significantly less than CF shows
                    # → likely incomplete (interim only). Estimate from CF instead.
                    dps_from_cf = div_paid / total_shares
                    print(f"  [DDM fix] {year}: DPS {dps_total:.2f} → {dps_from_cf:.2f} "
                          f"(corrected from CF dividends_paid)", file=sys.stderr)
                    yearly[year] = dps_from_cf
                elif ratio > 2.0:
                    print(f"  [DDM warning] {year}: DPS×shares={implied/1e6:.0f}M vs "
                          f"CF={div_paid/1e6:.0f}M (ratio={ratio:.2f})", file=sys.stderr)

        result = sorted(yearly.items(), key=lambda x: x[0], reverse=True)
        return [(y, v) for y, v in result if v > 0]

    def ddm(self, ke: float) -> dict | None:
        """Dividend Discount Model (Gordon or 2-stage)."""
        income_df = self._annual_df("income")

        # Aggregate annual DPS (fixes interim+final double-counting bug)
        annual_dps = self._aggregate_annual_dps()
        if len(annual_dps) < 3:
            return None

        dps_latest = annual_dps[0][1]
        dps_list = [v for _, v in annual_dps]

        # Payout ratio stats
        payout_lookup = self.client._get_payout_by_year()
        payout_vals = list(payout_lookup.values())[:3]
        payout_avg = statistics.mean(payout_vals) if payout_vals else None
        payout_std = statistics.stdev(payout_vals) if len(payout_vals) >= 2 else 0

        # DPS CAGR
        dps_cagr = self._cagr(dps_list)
        dps_cagr_pct = dps_cagr * 100 if dps_cagr is not None else 2.0

        # ROE for sustainable growth
        fi_df = self._annual_df("fina_indicators")
        roe_avg = None
        if not fi_df.empty and "roe_waa" in fi_df.columns:
            roe_vals = [self._sf(r.get("roe_waa")) for _, r in fi_df.head(5).iterrows()]
            roe_clean = [v for v in roe_vals if v is not None]
            roe_avg = statistics.mean(roe_clean) if roe_clean else None

        g_terminal = self.params["g_terminal"]

        # Model selection
        cv = payout_std / payout_avg if payout_avg and payout_avg > 0 else 0
        use_gordon = dps_cagr_pct < 5 and cv < 0.20

        if use_gordon:
            g_sustainable = roe_avg * (1 - payout_avg / 100) if (roe_avg and payout_avg) else dps_cagr_pct
            g = min(dps_cagr_pct, g_sustainable)
            if g >= ke:
                use_gordon = False  # fallback to 2-stage

        if use_gordon:
            intrinsic = dps_latest * (1 + g / 100) / (ke / 100 - g / 100)
            model_type = "Gordon"
            g_used = g
        else:
            # Two-stage
            g1 = dps_cagr_pct
            g2 = min(g_terminal, ke - 1.0)  # ensure g2 < ke
            pv_phase1 = 0
            dps_t = dps_latest
            for t in range(1, 6):
                dps_t = dps_t * (1 + g1 / 100)
                pv_phase1 += dps_t / (1 + ke / 100) ** t
            dps_6 = dps_t * (1 + g2 / 100)
            pv_phase2 = (dps_6 / (ke / 100 - g2 / 100)) / (1 + ke / 100) ** 5
            intrinsic = pv_phase1 + pv_phase2
            model_type = "Two-stage"
            g_used = g1

        # Sensitivity 5x5
        ke_range = [ke - 2, ke - 1, ke, ke + 1, ke + 2]
        g_sens_range = [g_used - 1, g_used - 0.5, g_used, g_used + 0.5, g_used + 1]
        sensitivity = []
        for k in ke_range:
            row = []
            for gs in g_sens_range:
                if gs >= k:
                    row.append(None)
                    continue
                if use_gordon:
                    v = dps_latest * (1 + gs / 100) / (k / 100 - gs / 100)
                else:
                    pv1 = 0
                    d = dps_latest
                    for t in range(1, 6):
                        d = d * (1 + gs / 100)
                        pv1 += d / (1 + k / 100) ** t
                    d6 = d * (1 + g2 / 100)
                    pv2 = (d6 / (k / 100 - g2 / 100)) / (1 + k / 100) ** 5
                    v = pv1 + pv2
                row.append(v)
            sensitivity.append(row)

        return {
            "method": "DDM",
            "intrinsic": intrinsic,
            "model_type": model_type,
            "dps_latest": dps_latest,
            "dps_cagr_pct": dps_cagr_pct,
            "g_used": g_used,
            "payout_avg": payout_avg,
            "payout_std": payout_std,
            "sensitivity": sensitivity,
            "ke_range": ke_range,
            "g_range": g_sens_range,
        }

    # ------------------------------------------------------------------
    # 6. PE Band
    # ------------------------------------------------------------------

    def pe_band(self) -> dict | None:
        """Historical PE range analysis."""
        income_df = self._annual_df("income")
        wp_df = self.client._store.get("weekly_prices")
        bi = self._basic_info()

        if income_df.empty or wp_df is None or wp_df.empty:
            return None

        # Build year-end price lookup
        wp_sorted = wp_df.sort_values("trade_date", ascending=False)
        year_end_prices = {}
        for _, r in wp_sorted.iterrows():
            yr = str(r["trade_date"])[:4]
            if yr not in year_end_prices:
                close = self._sf(r.get("close"))
                if close:
                    year_end_prices[yr] = close

        # Compute PE series
        pe_series = []
        eps_vals = []
        for _, r in income_df.iterrows():
            yr = str(r["end_date"])[:4]
            eps = self._sf(r.get("basic_eps"))
            if eps and eps > 0 and yr in year_end_prices:
                pe = year_end_prices[yr] / eps
                if 0 < pe < 100:
                    pe_series.append(pe)
            if eps and eps > 0:
                eps_vals.append(eps)

        if len(pe_series) < 3:
            return None

        pe_sorted = sorted(pe_series)
        n = len(pe_sorted)

        def _percentile(data, p):
            k = (len(data) - 1) * p / 100
            f = math.floor(k)
            c = math.ceil(k)
            if f == c:
                return data[int(k)]
            return data[f] * (c - k) + data[c] * (k - f)

        pe_stats = {
            "min": pe_sorted[0],
            "p25": _percentile(pe_sorted, 25),
            "median": _percentile(pe_sorted, 50),
            "p75": _percentile(pe_sorted, 75),
            "max": pe_sorted[-1],
            "avg": statistics.mean(pe_series),
        }

        # Normalized EPS (3yr avg)
        eps_norm = statistics.mean(eps_vals[:3]) if len(eps_vals) >= 3 else eps_vals[0] if eps_vals else None
        if eps_norm is None:
            return None

        intrinsic = pe_stats["median"] * eps_norm
        low = pe_stats["p25"] * eps_norm
        high = pe_stats["p75"] * eps_norm

        # Current PE percentile
        current_pe = bi.get("pe_ttm")
        current_pct = None
        if current_pe and current_pe > 0:
            below = sum(1 for p in pe_series if p <= current_pe)
            current_pct = below / len(pe_series) * 100

        return {
            "method": "PE_Band",
            "intrinsic": intrinsic,
            "low": low,
            "high": high,
            "pe_stats": pe_stats,
            "eps_norm": eps_norm,
            "current_pe": current_pe,
            "current_pct": current_pct,
            "pe_count": len(pe_series),
        }

    # ------------------------------------------------------------------
    # 7. PEG
    # ------------------------------------------------------------------

    def peg(self) -> dict | None:
        """PEG ratio analysis."""
        bi = self._basic_info()
        income_df = self._annual_df("income")

        pe = bi.get("pe_ttm")
        if pe is None or pe <= 0:
            return None

        # Earnings growth (3yr CAGR first, fallback to 5yr)
        np_series = [self._sf(r.get("n_income_attr_p")) for _, r in income_df.head(4).iterrows()]
        g = self._cagr(np_series)
        if g is None or g <= 0:
            np_series_5 = [self._sf(r.get("n_income_attr_p")) for _, r in income_df.head(5).iterrows()]
            g = self._cagr(np_series_5)
        if g is None or g <= 0:
            return None

        g_pct = g * 100
        if g_pct > 80:
            np_series_5 = [self._sf(r.get("n_income_attr_p")) for _, r in income_df.head(5).iterrows()]
            g5 = self._cagr(np_series_5)
            if g5 is not None and g5 > 0:
                g_pct = g5 * 100

        peg_val = pe / g_pct if g_pct > 0 else None
        if peg_val is None:
            return None

        # Fair price at PEG = 1
        eps_ttm = bi.get("close", 0) / pe if pe > 0 else None
        fair_pe = g_pct * 1.0
        fair_price = fair_pe * eps_ttm if eps_ttm else None

        # Sensitivity
        sensitivity = []
        for g_adj in [-10, -5, 0, 5, 10]:
            g_s = g_pct + g_adj
            if g_s <= 0:
                sensitivity.append({"g": g_s, "peg": None, "fair_pe": None, "fair_price": None})
                continue
            peg_s = pe / g_s
            fp_s = g_s * eps_ttm if eps_ttm else None
            sensitivity.append({"g": g_s, "peg": peg_s, "fair_pe": g_s, "fair_price": fp_s})

        return {
            "method": "PEG",
            "intrinsic": fair_price,
            "peg_value": peg_val,
            "pe": pe,
            "g_pct": g_pct,
            "eps_ttm": eps_ttm,
            "fair_pe": fair_pe,
            "fair_price": fair_price,
            "sensitivity": sensitivity,
        }

    # ------------------------------------------------------------------
    # 8. PS
    # ------------------------------------------------------------------

    def ps(self) -> dict | None:
        """Price-to-Sales analysis."""
        income_df = self._annual_df("income")
        wp_df = self.client._store.get("weekly_prices")
        bi = self._basic_info()

        if income_df.empty or not bi.get("total_shares") or not bi.get("mkt_cap_mm"):
            return None

        total_shares = bi["total_shares"]
        mkt_cap_mm = bi["mkt_cap_mm"]

        # Current PS
        latest_rev = self._sf(income_df.iloc[0].get("revenue"))
        if not latest_rev or latest_rev <= 0:
            return None

        rev_mm = latest_rev / 1e6 if self.market == "A" else latest_rev / 1e6
        ps_current = mkt_cap_mm / rev_mm if rev_mm > 0 else None

        # Historical PS
        year_end_prices = {}
        if wp_df is not None and not wp_df.empty:
            for _, r in wp_df.sort_values("trade_date", ascending=False).iterrows():
                yr = str(r["trade_date"])[:4]
                if yr not in year_end_prices:
                    close = self._sf(r.get("close"))
                    if close:
                        year_end_prices[yr] = close

        ps_series = []
        for _, r in income_df.iterrows():
            yr = str(r["end_date"])[:4]
            rev = self._sf(r.get("revenue"))
            if rev and rev > 0 and yr in year_end_prices:
                mc_yr = year_end_prices[yr] * total_shares
                rev_yr = rev
                ps_yr = mc_yr / rev_yr if rev_yr > 0 else None
                if ps_yr and ps_yr > 0:
                    ps_series.append(ps_yr)

        if len(ps_series) < 3:
            return None

        ps_sorted = sorted(ps_series)

        def _pctl(data, p):
            k = (len(data) - 1) * p / 100
            f = math.floor(k)
            c = math.ceil(k)
            if f == c:
                return data[int(k)]
            return data[f] * (c - k) + data[c] * (k - f)

        ps_stats = {
            "min": ps_sorted[0],
            "p25": _pctl(ps_sorted, 25),
            "median": _pctl(ps_sorted, 50),
            "p75": _pctl(ps_sorted, 75),
            "max": ps_sorted[-1],
        }

        fair_value_mm = ps_stats["median"] * rev_mm
        fair_price = fair_value_mm * 1e6 / total_shares if total_shares > 0 else None
        low_price = ps_stats["p25"] * rev_mm * 1e6 / total_shares if total_shares > 0 else None
        high_price = ps_stats["p75"] * rev_mm * 1e6 / total_shares if total_shares > 0 else None

        return {
            "method": "PS",
            "intrinsic": fair_price,
            "low": low_price,
            "high": high_price,
            "ps_current": ps_current,
            "ps_stats": ps_stats,
            "revenue_mm": rev_mm,
        }

    # ------------------------------------------------------------------
    # 9. Reverse Valuation (反向估值)
    # ------------------------------------------------------------------

    def reverse_valuation(self, wacc_data: dict, classification: dict) -> dict:
        """Reverse-engineer what growth the current price implies."""
        bi = self._basic_info()
        close = bi.get("close")
        pe = bi.get("pe_ttm")
        mkt_cap_mm = bi.get("mkt_cap_mm")
        if not close or not mkt_cap_mm or mkt_cap_mm <= 0:
            return {}

        wacc = wacc_data["wacc"]
        ke = wacc_data["ke"]

        # Actual growth rates (from classification)
        actual_np_cagr = classification.get("np_cagr_pct")
        actual_rev_cagr = classification.get("rev_cagr_pct")

        # --- Method 1: Reverse perpetual DCF ---
        # Market_Cap = FCF / (WACC - g) → g = WACC - FCF/Market_Cap
        cf_df = self._annual_df("cashflow")
        fcf_list = []
        for _, r in cf_df.head(3).iterrows():
            ocf = self._sf(r.get("n_cashflow_act"))
            capex = self._sf(r.get("c_pay_acq_const_fiolta"))
            if ocf is not None and capex is not None:
                fcf_list.append(ocf - abs(capex))
        fcf_base_mm = (statistics.mean(fcf_list) / 1e6) if fcf_list else None

        implied_g_fcf = None
        fcf_yield = None
        if fcf_base_mm and mkt_cap_mm > 0:
            fcf_yield = fcf_base_mm / mkt_cap_mm * 100
            implied_g_fcf = wacc - fcf_yield

        # --- Method 2: Reverse PE (E/P = Ke - g) ---
        implied_g_earnings = None
        ep_ratio = None
        if pe and pe > 0:
            ep_ratio = 1 / pe * 100
            implied_g_earnings = ke - ep_ratio

        # --- Method 3: Reverse DDM (P = DPS*(1+g)/(Ke-g)) ---
        annual_dps = self._aggregate_annual_dps()
        implied_g_dividend = None
        dps_latest = None
        div_yield = None
        if annual_dps and close > 0:
            dps_latest = annual_dps[0][1]
            div_yield = dps_latest / close * 100
            # P = DPS*(1+g)/(Ke-g) → g = (P*Ke - DPS) / (P + DPS)
            implied_g_dividend = (close * ke / 100 - dps_latest) / (close + dps_latest) * 100

        # --- Method 4: Implied WACC (if actual growth is achieved) ---
        actual_fcf_growth = classification.get("np_cagr_pct")  # proxy
        implied_wacc = None
        if fcf_yield is not None and actual_fcf_growth is not None:
            implied_wacc = fcf_yield + actual_fcf_growth

        return {
            "fcf_yield": fcf_yield,
            "implied_g_fcf": implied_g_fcf,
            "ep_ratio": ep_ratio,
            "implied_g_earnings": implied_g_earnings,
            "div_yield": div_yield,
            "implied_g_dividend": implied_g_dividend,
            "implied_wacc": implied_wacc,
            "actual_np_cagr": actual_np_cagr,
            "actual_rev_cagr": actual_rev_cagr,
            "dps_latest": dps_latest,
            "wacc": wacc,
            "ke": ke,
        }

    # ------------------------------------------------------------------
    # 10. Cross-validation
    # ------------------------------------------------------------------

    def cross_validate(self, results: list[dict], weights: dict) -> dict:
        """Cross-validate results from multiple methods."""
        valid = [(r["method"], r["intrinsic"]) for r in results
                 if r is not None and r.get("intrinsic") is not None and r["intrinsic"] > 0]

        if not valid:
            return {"weighted_avg": None, "cv": None, "consistency": "N/A", "range": {}}

        # Redistribute weights to available methods
        available_methods = {m for m, _ in valid}
        active_weights = {m: w for m, w in weights.items() if m in available_methods}
        total_w = sum(active_weights.values())
        if total_w > 0:
            active_weights = {m: w / total_w * 100 for m, w in active_weights.items()}

        # Weighted average
        weighted_sum = sum(v * active_weights.get(m, 100 / len(valid)) / 100 for m, v in valid)

        # CV
        values = [v for _, v in valid]
        mean_v = statistics.mean(values)
        std_v = statistics.stdev(values) if len(values) >= 2 else 0
        cv = std_v / mean_v * 100 if mean_v > 0 else 0

        if cv < 15:
            consistency = "高"
        elif cv < 30:
            consistency = "中"
        else:
            consistency = "低"

        return {
            "weighted_avg": weighted_sum,
            "cv": cv,
            "consistency": consistency,
            "methods": valid,
            "active_weights": active_weights,
            "range": {
                "conservative": min(values),
                "central": weighted_sum,
                "optimistic": max(values),
            },
        }

    # ------------------------------------------------------------------
    # 10. Markdown Output
    # ------------------------------------------------------------------

    def _fmt(self, val, divider=1, decimals=2) -> str:
        """Format a number for display."""
        if val is None:
            return "—"
        return f"{val / divider:,.{decimals}f}"

    def _fmt_pct(self, val) -> str:
        if val is None:
            return "—"
        return f"{val:.2f}%"

    def _render_sensitivity(self, matrix, row_labels, col_labels, row_name, col_name) -> str:
        """Render a sensitivity matrix as markdown table."""
        headers = [f"{row_name}\\{col_name}"] + [self._fmt_pct(c) for c in col_labels]
        rows = []
        for i, r_label in enumerate(row_labels):
            row = [self._fmt_pct(r_label)]
            for j in range(len(col_labels)):
                val = matrix[i][j] if i < len(matrix) and j < len(matrix[i]) else None
                row.append(self._fmt(val) if val else "N/A")
            rows.append(row)
        return format_table(headers, rows, alignments=["l"] + ["r"] * len(col_labels))

    def generate_output(self, classification, wacc_data, method_results, xval, reverse) -> str:
        """Generate valuation_computed.md."""
        bi = self._basic_info()
        lines = []

        lines.append(f"# 估值计算结果 — {bi.get('name', '')}（{self.ts_code}）")
        lines.append("")
        lines.append(f"*计算时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        lines.append(f"*计算引擎: valuation_engine.py v1.0*")
        lines.append("")
        lines.append("---")
        lines.append("")

        # --- Section 1: Classification ---
        lines.append(format_header(2, "一、公司分类"))
        lines.append("")

        cls = classification
        cls_rows = [
            ["ROE_5yr_avg", self._fmt_pct(cls["roe_avg"]), "> 15%", "✓" if cls.get("roe_avg") and cls["roe_avg"] > ROE_BLUE_CHIP_THRESHOLD else "✗",
             "—", "—"],
            ["Payout_3yr_avg", self._fmt_pct(cls["payout_avg"]), "> 30%", "✓" if cls.get("payout_avg") and cls["payout_avg"] > PAYOUT_BLUE_CHIP_THRESHOLD else "✗",
             "—", "—"],
            ["Revenue_CAGR_5yr", self._fmt_pct(cls["rev_cagr_pct"]),
             f"< {REV_GROWTH_THRESHOLD}%", "✓" if cls.get("rev_cagr_pct") is not None and cls["rev_cagr_pct"] < REV_GROWTH_THRESHOLD else "✗",
             f"> {REV_GROWTH_THRESHOLD}%", "✓" if cls.get("rev_cagr_pct") is not None and cls["rev_cagr_pct"] > REV_GROWTH_THRESHOLD else "✗"],
            ["Net_Profit_CAGR_5yr", self._fmt_pct(cls["np_cagr_pct"]), "—", "—",
             f"> {PROFIT_GROWTH_THRESHOLD}%", "✓" if cls.get("np_cagr_pct") is not None and cls["np_cagr_pct"] > PROFIT_GROWTH_THRESHOLD else "✗"],
        ]
        lines.append(format_table(
            ["指标", "值", "蓝筹条件", "达标", "成长条件", "达标"],
            cls_rows, alignments=["l", "r", "l", "c", "l", "c"]))
        lines.append("")
        lines.append(f"**蓝筹得分**: {cls['blue_score']}/3 | **成长得分**: {cls['growth_score']}/2")
        lines.append(f"**分类结果**: {cls['type']}")
        lines.append("")

        method_rows = []
        for m in cls["methods"]:
            w = cls["weights"].get(m, 0)
            method_rows.append([m, f"{w}%"])
        lines.append(format_table(["方法", "权重"], method_rows, alignments=["l", "r"]))
        lines.append("")
        lines.append("---")
        lines.append("")

        # --- Section 2: WACC ---
        lines.append(format_header(2, "二、WACC 计算"))
        lines.append("")
        w = wacc_data
        wacc_rows = [
            ["Rf (无风险利率)", self._fmt_pct(w["rf"]), "§14"],
            ["Beta", f"{w['beta']:.1f}", "市值分档"],
            ["ERP (股权风险溢价)", self._fmt_pct(w["erp"]), f"{self.market}市场默认"],
            ["**Ke (权益成本)**", f"**{self._fmt_pct(w['ke'])}**", "CAPM"],
            ["Kd (税前债务成本)", self._fmt_pct(w["kd_pre"]), "§3/§4"],
            ["有效税率", self._fmt_pct(w["tax_rate"]), "§3 五年均值"],
            ["E/(D+E)", self._fmt_pct(w["e_weight"]), "市值权重"],
            ["D/(D+E)", self._fmt_pct(w["d_weight"]), "债务权重"],
            ["**WACC**", f"**{self._fmt_pct(w['wacc'])}**", "加权平均"],
        ]
        lines.append(format_table(["参数", "值", "来源"], wacc_rows, alignments=["l", "r", "l"]))
        lines.append("")
        lines.append("---")
        lines.append("")

        # --- Section 3: Method Details ---
        lines.append(format_header(2, "三、估值方法详情"))
        lines.append("")

        for i, result in enumerate(method_results):
            if result is None:
                continue
            method_name = result["method"]
            lines.append(format_header(3, f"方法 {i+1}: {method_name}"))
            lines.append("")

            if method_name == "DCF":
                lines.append(f"- FCF基线 (3yr均值): {format_number(result['fcf_base'])}")
                lines.append(f"- 保守增长率: {self._fmt_pct(result['g_conservative'])}")
                lines.append(f"- 永续增长率: {self._fmt_pct(result['g_terminal'])}")
                lines.append(f"- 终值占比: {result['tv_pct']:.1f}%")
                if result.get("all_negative"):
                    lines.append("> ⚠️ FCF历史均为负值，DCF可靠性低")
                lines.append("")
                lines.append(f"**内在价值: {self._fmt(result['intrinsic'])} {self._price_unit()}/股**")
                lines.append("")
                lines.append("#### 敏感性分析 (WACC × g_terminal)")
                lines.append("")
                lines.append(self._render_sensitivity(
                    result["sensitivity"], result["wacc_range"], result["g_range"],
                    "WACC", "g_terminal"))

            elif method_name == "DCF_Scenarios":
                lines.append(f"- 历史营收CAGR: {self._fmt_pct(result['rev_cagr_pct'])}")
                lines.append(f"- 当前净利率: {self._fmt_pct(result['net_margin'])}")
                lines.append("")
                sc = result["scenarios"]
                sc_rows = [
                    ["乐观 (25%)", self._fmt_pct(sc["optimistic"]["growth"][0]),
                     self._fmt(sc["optimistic"]["value"])],
                    ["基准 (50%)", self._fmt_pct(sc["base"]["growth"][0]),
                     self._fmt(sc["base"]["value"])],
                    ["悲观 (25%)", self._fmt_pct(sc["pessimistic"]["growth"][0]),
                     self._fmt(sc["pessimistic"]["value"])],
                ]
                lines.append(format_table(["情景", "营收增速", "每股价值"], sc_rows, alignments=["l", "r", "r"]))
                lines.append("")
                lines.append(f"**概率加权内在价值: {self._fmt(result['intrinsic'])} {self._price_unit()}/股**")

            elif method_name == "DDM":
                lines.append(f"- 模型: {result['model_type']}")
                lines.append(f"- 最新DPS: {result['dps_latest']:.2f}")
                lines.append(f"- DPS CAGR: {self._fmt_pct(result['dps_cagr_pct'])}")
                lines.append(f"- 增长率假设: {self._fmt_pct(result['g_used'])}")
                lines.append("")
                lines.append(f"**内在价值: {self._fmt(result['intrinsic'])} {self._price_unit()}/股**")
                lines.append("")
                lines.append("#### 敏感性分析 (Ke × g)")
                lines.append("")
                lines.append(self._render_sensitivity(
                    result["sensitivity"], result["ke_range"], result["g_range"],
                    "Ke", "g"))

            elif method_name == "PE_Band":
                ps = result["pe_stats"]
                lines.append(f"- 历史PE范围: {ps['min']:.1f} - {ps['max']:.1f}")
                lines.append(f"- PE中位数: {ps['median']:.1f}")
                lines.append(f"- 正常化EPS: {result['eps_norm']:.2f}")
                if result.get("current_pe"):
                    lines.append(f"- 当前PE: {result['current_pe']:.1f} (分位: {result['current_pct']:.0f}%)")
                lines.append("")
                pe_rows = [
                    ["PE_25 (低估)", f"{ps['p25']:.1f}", self._fmt(result['low'])],
                    ["PE_median (合理)", f"{ps['median']:.1f}", self._fmt(result['intrinsic'])],
                    ["PE_75 (高估)", f"{ps['p75']:.1f}", self._fmt(result['high'])],
                ]
                lines.append(format_table(["分位", "PE", "对应股价"], pe_rows, alignments=["l", "r", "r"]))
                lines.append("")
                lines.append(f"**内在价值: {self._fmt(result['intrinsic'])} {self._price_unit()}/股**")

            elif method_name == "PEG":
                lines.append(f"- PE (TTM): {result['pe']:.1f}")
                lines.append(f"- 盈利增速G: {self._fmt_pct(result['g_pct'])}")
                lines.append(f"- PEG: {result['peg_value']:.2f}")
                lines.append(f"- PEG=1合理PE: {result['fair_pe']:.1f}")
                lines.append("")
                peg_judge = "显著低估" if result["peg_value"] < 0.5 else \
                    "低估" if result["peg_value"] < 1.0 else \
                    "合理" if result["peg_value"] < 1.5 else \
                    "偏高" if result["peg_value"] < 2.0 else "高估"
                lines.append(f"PEG判断: **{peg_judge}**")
                lines.append("")
                sens_rows = []
                for s in result["sensitivity"]:
                    sens_rows.append([
                        self._fmt_pct(s["g"]),
                        f"{s['peg']:.2f}" if s["peg"] else "—",
                        self._fmt(s["fair_price"]) if s["fair_price"] else "—",
                    ])
                lines.append(format_table(["G假设", "PEG", "合理股价"], sens_rows, alignments=["r", "r", "r"]))
                lines.append("")
                lines.append(f"**内在价值 (PEG=1): {self._fmt(result['intrinsic'])} {self._price_unit()}/股**")

            elif method_name == "PS":
                ps = result["ps_stats"]
                lines.append(f"- 当前PS: {result['ps_current']:.2f}" if result.get("ps_current") else "- 当前PS: —")
                lines.append(f"- 历史PS范围: {ps['min']:.2f} - {ps['max']:.2f}")
                lines.append(f"- PS中位数: {ps['median']:.2f}")
                lines.append("")
                ps_rows = [
                    ["PS_25 (低估)", f"{ps['p25']:.2f}", self._fmt(result['low'])],
                    ["PS_median (合理)", f"{ps['median']:.2f}", self._fmt(result['intrinsic'])],
                    ["PS_75 (高估)", f"{ps['p75']:.2f}", self._fmt(result['high'])],
                ]
                lines.append(format_table(["分位", "PS", "对应股价"], ps_rows, alignments=["l", "r", "r"]))
                lines.append("")
                lines.append(f"**内在价值: {self._fmt(result['intrinsic'])} {self._price_unit()}/股**")

            lines.append("")
            lines.append("---")
            lines.append("")

        # --- Section 4: Cross-validation ---
        lines.append(format_header(2, "四、交叉验证"))
        lines.append("")

        xv = xval
        if xv.get("methods"):
            xv_rows = []
            for m, v in xv["methods"]:
                w = xv["active_weights"].get(m, 0)
                xv_rows.append([m, self._fmt(v), f"{w:.0f}%", self._fmt(v * w / 100)])
            xv_rows.append(["**加权平均**", "—", "100%", f"**{self._fmt(xv['weighted_avg'])}**"])
            lines.append(format_table(
                ["方法", f"内在价值 ({self._price_unit()}/股)", "权重", "加权贡献"],
                xv_rows, alignments=["l", "r", "r", "r"]))
            lines.append("")
            lines.append(f"- 变异系数 (CV): {xv['cv']:.1f}%")
            lines.append(f"- 一致性: **{xv['consistency']}**")
        lines.append("")

        # Range
        rng = xv.get("range", {})
        current = bi.get("close", 0)
        if rng.get("conservative"):
            rng_rows = [
                ["保守", self._fmt(rng["conservative"]),
                 f"{(rng['conservative'] / current - 1) * 100:+.1f}%" if current else "—"],
                ["中性", self._fmt(rng["central"]),
                 f"{(rng['central'] / current - 1) * 100:+.1f}%" if current else "—"],
                ["乐观", self._fmt(rng["optimistic"]),
                 f"{(rng['optimistic'] / current - 1) * 100:+.1f}%" if current else "—"],
            ]
            lines.append(format_table(
                ["情景", f"内在价值 ({self._price_unit()}/股)", "vs 当前股价"],
                rng_rows, alignments=["l", "r", "r"]))
            lines.append("")

            safety = (rng["central"] / current - 1) * 100 if current else 0
            if safety > 30:
                judgment = "显著低估"
            elif safety > 10:
                judgment = "低估"
            elif safety > -10:
                judgment = "合理"
            elif safety > -30:
                judgment = "偏高"
            else:
                judgment = "高估"
            lines.append(f"**初步判断（未经定性调整）: {judgment}**")
            lines.append(f"**安全边际: {safety:+.1f}%**")
        lines.append("")
        lines.append("---")
        lines.append("")

        # --- Section 5: Reverse Valuation ---
        lines.append(format_header(2, "五、反向估值：当前价格隐含了什么？"))
        lines.append("")
        lines.append("> 用当前股价反推市场隐含的增长假设，揭示市场定价中包含了多少增长预期。")
        lines.append("")

        rv = reverse
        if rv:
            rv_rows = []

            # Row 1: Implied earnings growth
            ig_e = rv.get("implied_g_earnings")
            actual_np = rv.get("actual_np_cagr")
            rv_rows.append([
                "盈利增长 (E/P法)",
                self._fmt_pct(ig_e) if ig_e is not None else "—",
                self._fmt_pct(actual_np) if actual_np is not None else "—",
                f"{actual_np - ig_e:+.1f} pct" if ig_e is not None and actual_np is not None else "—",
            ])

            # Row 2: Implied dividend growth
            ig_d = rv.get("implied_g_dividend")
            rv_rows.append([
                "分红增长 (DDM反解)",
                self._fmt_pct(ig_d) if ig_d is not None else "—",
                "DPS 历史高增长（支付率扩张期）",
                "—",
            ])

            # Row 3: Implied FCF growth
            ig_f = rv.get("implied_g_fcf")
            rv_rows.append([
                "FCF增长 (永续DCF反解)",
                self._fmt_pct(ig_f) if ig_f is not None else "—",
                f"FCF收益率 {self._fmt_pct(rv.get('fcf_yield'))}",
                f"WACC({self._fmt_pct(rv.get('wacc'))}) - FCF收益率" if rv.get("fcf_yield") else "—",
            ])

            lines.append(format_table(
                ["维度", "市场隐含增长率", "实际/参考值", "备注"],
                rv_rows, alignments=["l", "r", "l", "l"]))
            lines.append("")

            # Implied WACC
            iw = rv.get("implied_wacc")
            if iw is not None:
                lines.append(f"**隐含要求回报率**: 若实际盈利增速 {self._fmt_pct(actual_np)} 兑现，"
                             f"市场隐含要求回报率 ≈ {iw:.2f}%（vs 模型 WACC {self._fmt_pct(rv.get('wacc'))}）")
                lines.append("")

            # Growth discount summary
            if ig_e is not None and actual_np is not None:
                gap = actual_np - ig_e
                if gap > 5:
                    lines.append(f"**结论**: 当前价格几乎未对增长定价。市场隐含盈利增长 {self._fmt_pct(ig_e)}，"
                                 f"远低于实际 {self._fmt_pct(actual_np)}，增长折价约 **{gap:.0f} 个百分点**。")
                elif gap > 0:
                    lines.append(f"**结论**: 当前价格部分反映了增长。市场隐含盈利增长 {self._fmt_pct(ig_e)}，"
                                 f"低于实际 {self._fmt_pct(actual_np)}，存在 **{gap:.0f} 个百分点**温和折价。")
                else:
                    lines.append(f"**结论**: 当前价格已充分定价增长。市场隐含盈利增长 {self._fmt_pct(ig_e)} "
                                 f"≈ 实际增速，无明显增长折价。")
                lines.append("")

        lines.append("---")
        lines.append("")

        # --- Section 6: Assumptions list ---
        lines.append(format_header(2, "六、关键假设清单（待定性调整）"))
        lines.append("")
        lines.append("> LLM 分析师：请根据定性报告（qualitative_report.md）调整以下假设，")
        lines.append("> 并从上方敏感性矩阵中选择最合理的情景坐标。")
        lines.append("")

        assumption_rows = [
            ["1", "FCF增长率", self._fmt_pct(method_results[0]["g_conservative"]) if method_results and method_results[0] and "g_conservative" in (method_results[0] or {}) else "—",
             "↓/→/↑", "D1 收入质量 + 核心利润分解"],
            ["2", "永续增长率", self._fmt_pct(self.params["g_terminal"]),
             "↓/→", "D2 护城河评级 + 可持续性"],
            ["3", "Beta", f"{wacc_data['beta']:.1f}",
             "↑/→", "D3 周期性"],
            ["4", "ERP溢价", self._fmt_pct(wacc_data["erp"]),
             "↑/→", "D4 管理层 + 治理风险"],
            ["5", "DPS增长率", "见DDM敏感性表",
             "↓/→/↑", "D5 分红信号"],
            ["6", "控股折价", "0%",
             "0-30%", "D6 控股结构"],
        ]
        lines.append(format_table(
            ["#", "假设", "Python默认值", "调整方向", "定性依据"],
            assumption_rows, alignments=["c", "l", "r", "c", "l"]))
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 11. Orchestrator
    # ------------------------------------------------------------------

    def run(self) -> str:
        """Execute full pipeline and return markdown output."""
        # 1. Classify
        cls = self.classify()
        print(f"  分类: {cls['type']} (蓝筹{cls['blue_score']}/成长{cls['growth_score']})", file=sys.stderr)

        # 2. WACC
        wacc_data = self.compute_wacc()
        print(f"  WACC: {wacc_data['wacc']:.2f}%", file=sys.stderr)

        # 3. Run selected methods
        method_map = {
            "DCF": lambda: self.dcf_stable(wacc_data),
            "DCF_Scenarios": lambda: self.dcf_scenarios(wacc_data),
            "DDM": lambda: self.ddm(wacc_data["ke"]),
            "PE_Band": lambda: self.pe_band(),
            "PEG": lambda: self.peg(),
            "PS": lambda: self.ps(),
        }

        results = []
        for method_name in cls["methods"]:
            fn = method_map.get(method_name)
            if fn:
                try:
                    result = fn()
                    if result:
                        print(f"  {method_name}: {result['intrinsic']:.2f}/股", file=sys.stderr)
                    else:
                        print(f"  {method_name}: 跳过 (数据不足)", file=sys.stderr)
                    results.append(result)
                except Exception as e:
                    print(f"  {method_name}: 失败 ({e})", file=sys.stderr)
                    results.append(None)

        # 4. Cross-validate
        xval = self.cross_validate(
            [r for r in results if r is not None],
            cls["weights"])

        # 5. Reverse valuation
        reverse = self.reverse_valuation(wacc_data, cls)
        if reverse.get("implied_g_earnings") is not None:
            print(f"  反向估值: 市场隐含盈利增长 {reverse['implied_g_earnings']:.1f}% "
                  f"(实际 {cls.get('np_cagr_pct', 0):.1f}%)", file=sys.stderr)

        # 6. Generate output
        return self.generate_output(cls, wacc_data, results, xval, reverse)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Valuation computation engine")
    parser.add_argument("--code", required=True, help="Stock code (e.g., 600887)")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the TTL disk cache for financial endpoints (always fetch live)",
    )
    args = parser.parse_args()

    ts_code = validate_stock_code(args.code)
    token = get_token()

    # Import TushareClient here to keep module importable without tushare for testing
    from tushare_collector import TushareClient

    print(f"[valuation_engine] 正在采集 {ts_code} 数据...", file=sys.stderr)
    client = TushareClient(token)
    if args.no_cache:
        client._cache_enabled = False
    client.assemble_data_pack(ts_code)

    print(f"[valuation_engine] 正在计算估值...", file=sys.stderr)
    engine = ValuationEngine(ts_code, args.output_dir, client)
    output_md = engine.run()

    os.makedirs(args.output_dir, exist_ok=True)
    out_path = os.path.join(args.output_dir, "valuation_computed.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output_md)

    print(f"[valuation_engine] 完成: {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
