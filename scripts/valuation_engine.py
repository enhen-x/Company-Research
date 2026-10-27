#!/usr/bin/env python3
"""Valuation Engine — deterministic valuation computations.

Computes company classification, WACC, and multiple valuation methods
(DCF, DDM, PE Band, PEG, PS) with sensitivity tables.

Usage:
    python3 scripts/valuation_engine.py --code 600887 --output-dir output/600887_伊利/
"""

import argparse
import json
import math
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

# Bound optional provider collection, including dependency import, as one process tree.
if __name__ == "__main__" and "--_valuation-worker" not in sys.argv:
    from run_support import run_process
    guard = argparse.ArgumentParser(add_help=False)
    guard.add_argument("--total-timeout", type=float, default=180)
    options, _ = guard.parse_known_args()
    try:
        outcome = run_process([sys.executable, "-u", str(Path(__file__).resolve()),
                               *sys.argv[1:], "--_valuation-worker"],
                              timeout=options.total_timeout, heartbeat=15, label="独立估值")
    except ValueError as exc:
        guard.error(str(exc))
    raise SystemExit(124 if outcome["status"] == "TIMEOUT" else outcome.get("exit_code") or (0 if outcome["status"] == "PASS" else 1))

import pandas as pd

from config import get_token, validate_stock_code
from format_utils import format_number, format_table, format_header
from valuation_math import (cagr, enterprise_dcf, implied_perpetual_growth, perpetuity_value,
                            implied_stable_growth, stable_cashflow_path)

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
    (100_000, 0.8),     # > 1000亿 (> 100,000 百万元)
    (10_000, 1.0),      # 100-1000亿
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
        self.method_status = {}

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

        pe = self._sf(row.get("pe_ttm"))
        if pe is None:
            pe = self._sf(row.get("pe"))
        return {
            "close": close,
            "pe_ttm": pe,
            "pb": self._sf(row.get("pb")),
            "mkt_cap_mm": mkt_cap_mm,
            "total_shares": total_shares,
            "name": row.get("name", ""),
        }

    @staticmethod
    def _cagr(vals: list[float | None]) -> float | None:
        """Compute CAGR from values or ``(period, value)`` pairs."""
        return cagr(vals)

    def _interest_bearing_debt(self, row) -> float:
        values = []
        for c in ("st_borr", "lt_borr", "bond_payable", "non_cur_liab_due_1y"):
            v = self._sf(row.get(c))
            if v is not None:
                values.append(v)
        return sum(values) if len(values) == 4 else None

    def _unavailable(self, method: str, reason: str):
        self.method_status[method] = {"status": "INSUFFICIENT_DATA", "reason": reason}
        return None

    def _valuation_contract(self) -> dict:
        """Optional explicit cash-flow/valuation bridge contract, no defaults."""
        value = self.client._store.get("valuation_contract")
        return value if isinstance(value, dict) else {}

    def _dcf_context(self, wacc_data: dict, method: str) -> dict | None:
        contract = self._valuation_contract()
        basis = contract.get("cashflow_basis")
        if basis not in ("FCFF", "FCFE"):
            return self._unavailable(method, "cashflow_basis must explicitly be FCFF or FCFE")
        if contract.get("currency") != {"A": "CNY", "HK": "HKD", "US": "USD"}[self.market]:
            return self._unavailable(method, "cash-flow currency must match the market price currency; convert with evidence first")
        unit = contract.get("amount_unit")
        if unit not in ("raw", "million"):
            return self._unavailable(method, "amount_unit must explicitly be raw or million")
        scale = 1e6 if unit == "million" else 1.0
        bi = self._basic_info()
        shares = bi.get("total_shares")
        if shares is None or shares <= 0:
            return self._unavailable(method, "positive total shares are required")
        rate_key = "wacc" if basis == "FCFF" else "ke"
        rate = self._sf(wacc_data.get(rate_key))
        explicit_rates = contract.get("discount_rates", {})
        if isinstance(explicit_rates, dict) and explicit_rates.get("evidence_id"):
            explicit_rate = self._sf(explicit_rates.get(rate_key + "_pct"))
            if explicit_rate is not None:
                rate = explicit_rate
        if rate is None or rate <= 0:
            return self._unavailable(method, f"a positive {rate_key} is required")
        cash = debt = other = 0.0
        if basis == "FCFF":
            bridge = contract.get("equity_bridge", {})
            if not isinstance(bridge, dict) or not bridge.get("evidence_id"):
                return self._unavailable(method, "FCFF requires an evidenced equity_bridge")
            values = [self._sf(bridge.get(key)) for key in ("cash", "debt", "other_equity_adjustment")]
            if any(value is None for value in values):
                return self._unavailable(method, "equity_bridge must specify cash, debt and other_equity_adjustment, including explicit zeros")
            cash, debt, other = [value * scale for value in values]
        elif contract.get("cashflow_scope") != "parent_common":
            return self._unavailable(method, "FCFE must explicitly be attributable to parent common equity")
        return {"contract": contract, "basis": basis, "rate": rate, "rate_basis": rate_key.upper(),
                "scale": scale, "shares": shares, "cash": cash, "debt": debt, "other": other}

    def _contract_cashflows(self, context: dict, method: str) -> list[tuple[str, float]] | None:
        """Read explicit cash flows, provider FCFF/FCFE, or evidenced CFO conversion."""
        contract, scale = context["contract"], context["scale"]
        source = contract.get("historical_source")
        if source == "explicit":
            values = []
            for row in contract.get("historical_cashflows", []):
                value = self._sf(row.get("value"))
                period = str(row.get("period", ""))
                if value is None or not period or not row.get("evidence_id"):
                    return self._unavailable(method, "every historical cash flow requires period, finite value and evidence_id")
                values.append((period, value * scale))
            if len({period for period, _ in values}) != len(values):
                raise ValueError("historical cash-flow periods must be unique")
            return sorted(values, key=lambda row: row[0], reverse=True)
        if source == "provider":
            field = context["basis"].lower()
            rows = self._annual_df("fina_indicators")
            return [(str(row.get("end_date", ""))[:8], value)
                    for _, row in rows.iterrows()
                    if (value := self._sf(row.get(field))) is not None]
        if source != "ocf":
            return self._unavailable(method, "historical_source must explicitly be explicit, provider or ocf")
        classification = contract.get("ocf_interest_classification")
        if classification not in ("within_operating", "outside_operating"):
            return self._unavailable(method, "CFO interest classification is required; market labels do not prove it")
        adjustments = contract.get("ocf_adjustments", {})
        records = []
        for _, row in self._annual_df("cashflow").head(5).iterrows():
            period = str(row.get("end_date", ""))[:8]
            ocf = self._sf(row.get("n_cashflow_act"))
            capex = self._sf(row.get("c_pay_acq_const_fiolta"))
            if ocf is None or capex is None:
                continue
            adjustment = adjustments.get(period, {})
            flow = ocf - abs(capex)
            needs_interest = ((context["basis"] == "FCFF" and classification == "within_operating")
                              or (context["basis"] == "FCFE" and classification == "outside_operating"))
            if needs_interest:
                interest = self._sf(adjustment.get("after_tax_interest"))
                if interest is None or not adjustment.get("evidence_id"):
                    return self._unavailable(method, f"{period}: evidenced after_tax_interest is required")
                flow += interest * scale * (1 if context["basis"] == "FCFF" else -1)
            if context["basis"] == "FCFE":
                borrowing = self._sf(adjustment.get("net_borrowing"))
                if borrowing is None or not adjustment.get("evidence_id"):
                    return self._unavailable(method, f"{period}: evidenced net_borrowing is required for FCFE")
                flow += borrowing * scale
            records.append((period, flow))
        return records

    @staticmethod
    def _cashflow_value(projected: list[float], context: dict, terminal_growth: float) -> dict:
        result = enterprise_dcf(projected, context["rate"] / 100, terminal_growth / 100)
        value = result["ev"]
        equity = (value + context["cash"] - context["debt"] + context["other"]
                  if context["basis"] == "FCFF" else value)
        return {**result, "equity_value": equity, "intrinsic": equity / context["shares"]}

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
        rev_series = [(str(r.get("end_date", ""))[:8], self._sf(r.get("revenue")))
                      for _, r in income_df.head(5).iterrows()]
        rev_cagr = self._cagr(rev_series)
        rev_cagr_pct = rev_cagr * 100 if rev_cagr is not None else None

        # Net profit CAGR 5yr
        np_series = [(str(r.get("end_date", ""))[:8], self._sf(r.get("n_income_attr_p")))
                     for _, r in income_df.head(5).iterrows()]
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
        estimation_date = datetime.now().strftime("%Y-%m-%d")
        sources = {"erp": f"market-default assumption ({estimation_date})",
                   "beta": "market-cap proxy; not a statistically estimated beta"}

        # Rf
        rf_df = self.client._store.get("risk_free_rate")
        rf = None
        if rf_df is not None and not rf_df.empty:
            rf = self._sf(rf_df.iloc[0].get("yield"))
        if rf is None:
            rf = self.params["rf_default"]
            sources["rf"] = f"market-default assumption ({estimation_date})"
        else:
            sources["rf"] = "risk_free_rate provider observation; verify quote date"

        # Beta by market cap
        beta = 1.0
        for threshold, b in BETA_BY_CAP:
            if mkt_cap_mm > threshold or (threshold == 10_000 and mkt_cap_mm == threshold):
                beta = b
                break

        erp = self.params["erp"]
        ke = rf + beta * erp

        # Kd
        income_df = self._annual_df("income")
        bs_df = self._annual_df("balance_sheet")
        finance_exp = None
        if not income_df.empty:
            finance_exp = self._sf(income_df.iloc[0].get("int_exp"))
            if finance_exp is None:
                finance_exp = self._sf(income_df.iloc[0].get("interest_expense"))

        debt_latest = None
        debt_prev = None
        if not bs_df.empty:
            debt_latest = self._interest_bearing_debt(bs_df.iloc[0])
            if len(bs_df) > 1:
                debt_prev = self._interest_bearing_debt(bs_df.iloc[1])
        avg_debt = ((debt_latest + debt_prev) / 2
                    if debt_latest is not None and debt_prev is not None
                    and (debt_latest + debt_prev) > 0 else 0)

        if finance_exp and finance_exp > 0 and avg_debt > 0:
            kd_pre = finance_exp / avg_debt * 100
            sources["kd_pre"] = "reported interest expense / average interest-bearing debt; verify coverage"
        else:
            kd_pre = rf + 1.0
            sources["kd_pre"] = f"Rf+1 percentage point assumption ({estimation_date}); no financing-cost observation"

        # Capital structure (market cap in raw units to match debt)
        # debt is in raw yuan (from _store), mkt_cap_mm is in millions
        debt_mm = debt_latest / 1e6 if debt_latest is not None else None
        # For A-share: _store amounts are in raw yuan, mkt_cap_mm is 万元/100
        # Actually _store amounts depend on how they're stored.
        # The balance sheet from tushare returns values in yuan for A-shares.
        # mkt_cap_mm is already in 百万元.
        # So debt needs to be converted to 百万元 too.
        if self.market == "A":
            e_val = mkt_cap_mm  # 百万元
            d_val = debt_latest / 1e6 if debt_latest is not None else None  # raw yuan → 百万元
        elif self.market == "HK":
            e_val = mkt_cap_mm  # 百万港元
            d_val = debt_latest / 1e6 if debt_latest is not None else None  # raw HKD → 百万港元
        else:
            e_val = mkt_cap_mm  # 百万美元
            d_val = debt_latest / 1e6 if debt_latest is not None else None  # raw USD → 百万美元

        total = e_val + d_val if d_val is not None else None
        e_weight = e_val / total * 100 if total is not None and total > 0 else None
        d_weight = d_val / total * 100 if total is not None and total > 0 else None

        # Tax rate
        tax_rates = []
        for _, r in income_df.head(5).iterrows():
            tax = self._sf(r.get("income_tax"))
            pre_tax = self._sf(r.get("total_profit"))
            if tax is not None and pre_tax and pre_tax > 0:
                tax_rates.append(tax / pre_tax * 100)
        tax_rate = statistics.mean(tax_rates) if tax_rates else self.params["tax_default"]
        sources["tax_rate"] = ("historical reported income tax / pre-tax profit"
                               if tax_rates else f"market-default assumption ({estimation_date})")

        # WACC
        if d_val is None or e_weight is None or d_weight is None:
            wacc = None
            sources["wacc"] = "insufficient debt coverage; not assumed to be zero"
        elif d_val <= 0:
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
            "parameter_sources": sources,
            "parameter_as_of": estimation_date,
        }

    # ------------------------------------------------------------------
    # 3. DCF (Stable)
    # ------------------------------------------------------------------

    def dcf_stable(self, wacc_data: dict) -> dict | None:
        """Stable DCF with an explicit FCFF/WACC or FCFE/Ke contract."""
        method = "DCF"
        context = self._dcf_context(wacc_data, method)
        if context is None:
            return None
        records = self._contract_cashflows(context, method)
        if records is None:
            return None
        records = records[:5]
        if len(records) < 2:
            return self._unavailable(method, "at least two comparable annual cash-flow observations are required")
        fcf_list = [value for _, value in records]
        fcf_base = statistics.mean(fcf_list[:3])
        growth = self._sf(context["contract"].get("stable_growth_pct"))
        growth_source = "explicit assumption"
        if growth is None:
            historical_growth = self._cagr(records)
            if historical_growth is None:
                return self._unavailable(method, "cash-flow CAGR is undefined; provide a supported stable_growth_pct assumption")
            growth = historical_growth * 100 * 0.8
            growth_source = "80% of historical cash-flow CAGR (heuristic assumption)"
        terminal = self._sf(context["contract"].get("terminal_growth_pct"))
        terminal_source = "explicit assumption"
        if terminal is None:
            terminal = self.params["g_terminal"]
            terminal_source = "market default assumption"
        rate = context["rate"]
        if rate <= terminal:
            raise ValueError(f"{context['rate_basis']} ({rate}) must be greater than terminal growth ({terminal})")
        fade = (growth + terminal) / 2
        rates = [growth, growth, fade, (fade + terminal) / 2, terminal]
        if fcf_base <= 0:
            return self._unavailable(method, "a non-positive terminal cash flow cannot support a Gordon terminal")
        projected = stable_cashflow_path(fcf_base, growth / 100, terminal / 100)
        value = self._cashflow_value(projected, context, terminal)
        rate_range = [rate - 2, rate - 1, rate, rate + 1, rate + 2]
        growth_range = [terminal - 1, terminal - 0.5, terminal, terminal + 0.5, terminal + 1]
        sensitivity = []
        for discount in rate_range:
            row = []
            for growth_s in growth_range:
                try:
                    row.append(self._cashflow_value(projected, {**context, "rate": discount}, growth_s)["intrinsic"])
                except ValueError:
                    row.append(None)
            sensitivity.append(row)
        self.method_status[method] = {"status": "COMPUTED", "basis": context["basis"]}
        return {
            "method": method, "intrinsic": value["intrinsic"],
            "cashflow_basis": context["basis"], "discount_rate_basis": context["rate_basis"],
            "value_bridge": ("EV + cash - debt + other equity adjustment" if context["basis"] == "FCFF"
                             else "discounted FCFE = parent common equity; no cash/debt bridge"),
            "fcf_base": fcf_base, "g_conservative": growth, "g_terminal": terminal,
            "growth_source": growth_source, "terminal_growth_source": terminal_source,
            "tv_pct": value["terminal_share"] * 100, "all_negative": all(v <= 0 for v in fcf_list),
            "projected_fcf": projected, "growth_rates": rates, "pv_fcf": value["pv_fcf"],
            "pv_tv": value["pv_terminal"], "ev": value["ev"] if context["basis"] == "FCFF" else None,
            "cash": context["cash"], "debt_raw": context["debt"], "other_equity_adjustment": context["other"],
            "equity_value": value["equity_value"], "sensitivity": sensitivity,
            "wacc_range": rate_range, "g_range": growth_range,
        }

    # ------------------------------------------------------------------
    # 4. DCF (Scenarios)
    # ------------------------------------------------------------------

    def dcf_scenarios(self, wacc_data: dict) -> dict | None:
        """Discount evidenced scenario paths; never invent an NI-to-FCF bridge."""
        method = "DCF_Scenarios"
        context = self._dcf_context(wacc_data, method)
        if context is None:
            return None
        contract = context["contract"]
        scenarios_input = contract.get("scenarios")
        names = ("optimistic", "base", "pessimistic")
        if not isinstance(scenarios_input, dict) or any(name not in scenarios_input for name in names):
            return self._unavailable(method, "explicit optimistic/base/pessimistic cash-flow scenarios are required")
        terminal = self._sf(contract.get("terminal_growth_pct"))
        if terminal is None:
            terminal = self.params["g_terminal"]
        if context["rate"] <= terminal:
            raise ValueError(f"{context['rate_basis']} must be greater than terminal growth")
        scenarios = {}
        probabilities = []
        for name in names:
            item = scenarios_input[name]
            if not isinstance(item, dict) or not item.get("evidence_id"):
                return self._unavailable(method, f"{name}: scenario assumptions need evidence_id")
            probability = self._sf(item.get("probability"))
            if probability is None or not 0 <= probability <= 1:
                raise ValueError(f"{name}: probability must be in [0,1]")
            raw_flows = item.get("cashflows")
            if not isinstance(raw_flows, list) or not raw_flows:
                return self._unavailable(method, f"{name}: explicit projected cashflows are required")
            flows = [self._sf(value) for value in raw_flows]
            if any(value is None for value in flows):
                return self._unavailable(method, f"{name}: projected cash flows cannot contain missing values")
            flows = [value * context["scale"] for value in flows]
            if flows[-1] <= 0:
                return self._unavailable(method, f"{name}: a non-positive terminal cash flow cannot support a Gordon terminal")
            result = self._cashflow_value(flows, context, terminal)
            revenue_growth = item.get("revenue_growth_pct")
            if not isinstance(revenue_growth, list) or not revenue_growth:
                revenue_growth = [None]
            scenarios[name] = {"growth": revenue_growth, "fcf": flows, "value": result["intrinsic"],
                               "probability": probability, "evidence_id": item["evidence_id"]}
            probabilities.append(probability)
        if not math.isclose(sum(probabilities), 1.0, abs_tol=1e-9):
            raise ValueError("scenario probabilities must sum to 1")
        if len({len(item["fcf"]) for item in scenarios.values()}) != 1:
            raise ValueError("scenario forecast horizons must match")
        weighted = sum(item["probability"] * item["value"] for item in scenarios.values())
        income_df = self._annual_df("income")
        rev_series = [(str(row.get("end_date", ""))[:8], self._sf(row.get("revenue")))
                      for _, row in income_df.head(5).iterrows()]
        historical_growth = self._cagr(rev_series)
        net_margin = None
        if not income_df.empty:
            revenue = self._sf(income_df.iloc[0].get("revenue"))
            profit = self._sf(income_df.iloc[0].get("n_income_attr_p"))
            if revenue is not None and revenue > 0 and profit is not None:
                net_margin = profit / revenue * 100
        self.method_status[method] = {"status": "COMPUTED", "basis": context["basis"]}
        return {
            "method": method, "intrinsic": weighted, "cashflow_basis": context["basis"],
            "discount_rate_basis": context["rate_basis"],
            "value_bridge": ("EV + cash - debt + other equity adjustment" if context["basis"] == "FCFF"
                             else "discounted FCFE = parent common equity; no cash/debt bridge"),
            "v_optimistic": scenarios["optimistic"]["value"], "v_base": scenarios["base"]["value"],
            "v_pessimistic": scenarios["pessimistic"]["value"],
            "rev_cagr_pct": historical_growth * 100 if historical_growth is not None else None,
            "net_margin": net_margin, "scenarios": scenarios,
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
            dps = self._sf(r.get("cash_div_tax"))
            if dps is None or dps < 0:
                continue
            yearly[year] = yearly.get(year, 0) + dps

        # Cross-check only: cash payments may include interest and different
        # ownership/timing, so they can never replace the observed DPS.
        cf_df = self._annual_df("cashflow")
        bi = self._basic_info()
        total_shares = bi.get("total_shares")
        if not cf_df.empty and total_shares and total_shares > 0:
            cf_by_year = {str(r["end_date"])[:4]: r for _, r in cf_df.iterrows()}
            for year in list(yearly.keys()):
                cf_row = cf_by_year.get(year)
                if cf_row is None:
                    continue
                # The *_int_exp field mixes dividends, profits and interest;
                # only a dividends-only field may validate a DPS series.
                div_paid = self._sf(cf_row.get("c_pay_dist_dpcp"))
                mixed = False
                if div_paid is None:
                    div_paid = self._sf(cf_row.get("c_pay_dist_dpcp_int_exp"))
                    mixed = True
                if not div_paid or div_paid <= 0:
                    continue
                # Tushare reports div_paid as positive (absolute outflow)
                dps_total = yearly[year]
                implied = dps_total * total_shares
                ratio = implied / div_paid if div_paid > 0 else 0
                if 0 < ratio < 0.5:
                    # Validate completeness when a separate dividends-only cash
                    # flow field exists, but never overwrite observed DPS with
                    # an inferred value.
                    dps_from_cf = div_paid / total_shares
                    print(f"  [DDM warning] {year}: DPS {dps_total:.2f} vs "
                          f"cash outflow {dps_from_cf:.2f} ({'mixed dividends/profits/interest' if mixed else 'dividends-only'}); retained DPS series", file=sys.stderr)
                elif ratio > 2.0:
                    print(f"  [DDM warning] {year}: DPS×shares={implied/1e6:.0f}M vs "
                          f"CF={div_paid/1e6:.0f}M (ratio={ratio:.2f})", file=sys.stderr)

        result = sorted(yearly.items(), key=lambda x: x[0], reverse=True)
        return [(y, v) for y, v in result if v >= 0]

    def ddm(self, ke: float) -> dict | None:
        """Dividend Discount Model (Gordon or 2-stage)."""
        income_df = self._annual_df("income")

        # Aggregate annual DPS (fixes interim+final double-counting bug)
        annual_dps = self._aggregate_annual_dps()
        if len(annual_dps) < 3:
            return None

        dps_latest = annual_dps[0][1]
        if dps_latest <= 0:
            return self._unavailable("DDM", "latest observed fiscal-year DPS is zero")

        # Payout ratio stats
        payout_lookup = self.client._get_payout_by_year()
        payout_vals = list(payout_lookup.values())[:3]
        payout_avg = statistics.mean(payout_vals) if payout_vals else None
        payout_std = statistics.stdev(payout_vals) if len(payout_vals) >= 2 else 0

        # DPS CAGR
        dps_cagr = self._cagr(annual_dps)
        if dps_cagr is None:
            return None
        dps_cagr_pct = dps_cagr * 100

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
            g2 = g_terminal
            if ke <= g2:
                raise ValueError("Ke must be greater than terminal dividend growth")
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
        np_series = [(str(r.get("end_date", ""))[:8], self._sf(r.get("n_income_attr_p")))
                     for _, r in income_df.head(4).iterrows()]
        g = self._cagr(np_series)
        if g is None or g <= 0:
            np_series_5 = [(str(r.get("end_date", ""))[:8], self._sf(r.get("n_income_attr_p")))
                          for _, r in income_df.head(5).iterrows()]
            g = self._cagr(np_series_5)
        if g is None or g <= 0:
            return None

        g_pct = g * 100
        if g_pct > 80:
            np_series_5 = [(str(r.get("end_date", ""))[:8], self._sf(r.get("n_income_attr_p")))
                          for _, r in income_df.head(5).iterrows()]
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
        """Conditioned five-year DCF inverse and separately labelled Gordon diagnostic."""
        bi = self._basic_info()
        close, cap = bi.get("close"), bi.get("mkt_cap_mm")
        if close is None or close <= 0 or cap is None or cap <= 0:
            return {"status": "INSUFFICIENT_DATA", "reason": "positive price and market cap are required"}
        ke = wacc_data["ke"]
        result = {
            "fcf_yield": None, "implied_g_fcf": None, "implied_wacc": None,
            "ep_ratio": None, "implied_g_earnings": None,
            "div_yield": None, "implied_g_dividend": None, "dps_latest": None,
            "actual_np_cagr": classification.get("np_cagr_pct"),
            "actual_rev_cagr": classification.get("rev_cagr_pct"),
            "actual_fcf_cagr": None, "wacc": wacc_data["wacc"], "ke": ke,
            "reverse_model": "Gordon period-zero cash-flow diagnostic; not a five-year DCF inverse",
            "earnings_growth_status": "not identified: payout and reinvestment assumptions are not supplied",
        }
        pe = bi.get("pe_ttm")
        if pe is not None and pe > 0:
            result["ep_ratio"] = 100 / pe
        context = self._dcf_context(wacc_data, "Reverse_DCF")
        if context is not None:
            records = self._contract_cashflows(context, "Reverse_DCF")
            if records:
                records = records[:3]
                base = statistics.mean([value for _, value in records])
                market_value = cap * 1e6
                if context["basis"] == "FCFF":
                    market_value = market_value - context["cash"] + context["debt"] - context["other"]
                if base > 0 and market_value > 0:
                    growth = implied_perpetual_growth(base, market_value, context["rate"] / 100)
                    # Forward reconstruction uses the same Gordon function.
                    reconstructed = perpetuity_value(base, context["rate"] / 100, growth)
                    result.update({
                        "fcf_yield": base / market_value * 100,
                        "implied_g_fcf": growth * 100,
                        "cashflow_basis": context["basis"], "discount_rate_basis": context["rate_basis"],
                        "cashflow_base": base, "reference_value": market_value,
                        "reconstructed_value": reconstructed,
                    })
                    terminal = self._sf(context["contract"].get("terminal_growth_pct"))
                    if terminal is None:
                        result["five_year_dcf"] = {"status": "INSUFFICIENT_DATA", "reason": "explicit terminal_growth_pct required for five-year inverse"}
                    else:
                        bounds_pct = context["contract"].get("reverse_growth_bounds_pct", [-99, 300])
                        if not isinstance(bounds_pct, list) or len(bounds_pct) != 2 or any(self._sf(v) is None or isinstance(v, bool) for v in bounds_pct):
                            raise ValueError("reverse_growth_bounds_pct must contain two finite numbers")
                        solved = implied_stable_growth(base, market_value, context["rate"] / 100, terminal / 100,
                                                       bounds=[float(v) / 100 for v in bounds_pct])
                        independent = self._sf(context["contract"].get("stable_growth_pct"))
                        solved.update(cashflow_basis=context["basis"], discount_rate_basis=context["rate_basis"],
                                      implied_growth_pct=solved["implied_growth"] * 100 if solved.get("implied_growth") is not None else None,
                                      independent_growth_pct=independent,
                                      gap_pct_points=independent - solved["implied_growth"] * 100 if independent is not None and solved.get("implied_growth") is not None else None,
                                      value_bridge="same FCFF/FCFE bridge as forward stable DCF")
                        result["five_year_dcf"] = solved
                        result["reverse_model"] = "five-year stable DCF inverse (one variable); separate Gordon diagnostic"
                    actual = self._cagr(records)
                    if actual is not None and actual > -1:
                        result["actual_fcf_cagr"] = actual * 100
                        result["implied_wacc"] = (base * (1 + actual) / market_value + actual) * 100
        annual_dps = self._aggregate_annual_dps()
        if annual_dps:
            dps = annual_dps[0][1]
            if dps > 0 and ke is not None and ke > 0:
                result["dps_latest"] = dps
                result["div_yield"] = dps / close * 100
                result["implied_g_dividend"] = implied_perpetual_growth(dps, close, ke / 100) * 100
        result["status"] = ("COMPUTED" if result["implied_g_fcf"] is not None
                            else "PARTIAL" if result["implied_g_dividend"] is not None else "INSUFFICIENT_DATA")
        return result

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
            ["Rf (无风险利率)", self._fmt_pct(w["rf"]), w.get("parameter_sources", {}).get("rf", "§14")],
            ["Beta", f"{w['beta']:.1f}", w.get("parameter_sources", {}).get("beta", "市值分档代理")],
            ["ERP (股权风险溢价)", self._fmt_pct(w["erp"]), w.get("parameter_sources", {}).get("erp", f"{self.market}市场默认假设")],
            ["**Ke (权益成本)**", f"**{self._fmt_pct(w['ke'])}**", "CAPM"],
            ["Kd (税前债务成本)", self._fmt_pct(w["kd_pre"]), w.get("parameter_sources", {}).get("kd_pre", "§3/§4")],
            ["有效税率", self._fmt_pct(w["tax_rate"]), w.get("parameter_sources", {}).get("tax_rate", "§3 五年均值")],
            ["E/(D+E)", self._fmt_pct(w["e_weight"]), "市值权重"],
            ["D/(D+E)", self._fmt_pct(w["d_weight"]), "债务权重"],
            ["**WACC**", f"**{self._fmt_pct(w['wacc'])}**", w.get("parameter_sources", {}).get("wacc", "加权平均")],
        ]
        lines.append(format_table(["参数", "值", "来源"], wacc_rows, alignments=["l", "r", "l"]))
        lines.append("")
        lines.append("---")
        lines.append("")

        # --- Section 3: Method Details ---
        lines.append(format_header(2, "三、估值方法详情"))
        lines.append("")
        if self.method_status:
            lines.append(format_table(["方法", "状态", "口径或缺口"],
                                      [[name, state["status"], state.get("reason", state.get("basis", ""))]
                                       for name, state in self.method_status.items()]))
            lines.append("")

        for i, result in enumerate(method_results):
            if result is None:
                continue
            method_name = result["method"]
            lines.append(format_header(3, f"方法 {i+1}: {method_name}"))
            lines.append("")

            if method_name == "DCF":
                lines.append(f"- 现金流/折现率: {result.get('cashflow_basis')} / {result.get('discount_rate_basis')}")
                lines.append(f"- 价值桥: {result.get('value_bridge')}")
                lines.append(f"- FCF基线 (3yr均值): {format_number(result['fcf_base'])}")
                lines.append(f"- 保守增长率: {self._fmt_pct(result['g_conservative'])}")
                lines.append(f"- 增长率依据: {result.get('growth_source')}; 终值依据: {result.get('terminal_growth_source')}")
                lines.append(f"- 永续增长率: {self._fmt_pct(result['g_terminal'])}")
                lines.append(f"- 终值占比: {result['tv_pct']:.1f}%")
                if result.get("all_negative"):
                    lines.append("> ⚠️ FCF历史均为负值，DCF可靠性低")
                lines.append("")
                lines.append(f"**内在价值: {self._fmt(result['intrinsic'])} {self._price_unit()}/股**")
                lines.append("")
                lines.append(f"#### 敏感性分析 ({result.get('discount_rate_basis')} × g_terminal)")
                lines.append("")
                lines.append(self._render_sensitivity(
                    result["sensitivity"], result["wacc_range"], result["g_range"],
                    result.get("discount_rate_basis", "WACC"), "g_terminal"))

            elif method_name == "DCF_Scenarios":
                lines.append(f"- 历史营收CAGR: {self._fmt_pct(result['rev_cagr_pct'])}")
                lines.append(f"- 当前净利率: {self._fmt_pct(result['net_margin'])}")
                lines.append("")
                sc = result["scenarios"]
                sc_rows = [
                    [f"乐观 ({sc['optimistic']['probability']:.0%})", self._fmt_pct(sc["optimistic"]["growth"][0]),
                     self._fmt(sc["optimistic"]["value"])],
                    [f"基准 ({sc['base']['probability']:.0%})", self._fmt_pct(sc["base"]["growth"][0]),
                     self._fmt(sc["base"]["value"])],
                    [f"悲观 ({sc['pessimistic']['probability']:.0%})", self._fmt_pct(sc["pessimistic"]["growth"][0]),
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
            lines.append(f"- 反解范围: {rv.get('reverse_model', 'unavailable')}")
            lines.append(f"- 盈利增长识别限制: {rv.get('earnings_growth_status', 'unavailable')}")
            solved = rv.get("five_year_dcf", {})
            if solved:
                lines.append(f"- 五年DCF反解状态: {solved.get('status')}; 初始现金流增速 {self._fmt_pct(solved.get('implied_growth_pct'))}; 独立假设 {self._fmt_pct(solved.get('independent_growth_pct'))}; 差异 {self._fmt(solved.get('gap_pct_points'))} 个百分点。")
                lines.append("- 固定现金流基期、折现率、终值增长、五年期限与渐降路径；反解仅识别一个变量，不能唯一识别量、价与利润率。")
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
                "以当前DPS为期初现金流，其余假设固定",
                "—",
            ])

            # Row 3: Implied FCF growth
            ig_f = rv.get("implied_g_fcf")
            rv_rows.append([
                f"{rv.get('cashflow_basis', 'FCF')}增长 (Gordon诊断)",
                self._fmt_pct(ig_f) if ig_f is not None else "—",
                f"FCF收益率 {self._fmt_pct(rv.get('fcf_yield'))}",
                "g=(V×r−CF0)/(V+CF0)，同口径价值桥" if rv.get("fcf_yield") is not None else "—",
            ])

            lines.append(format_table(
                ["维度", "市场隐含增长率", "实际/参考值", "备注"],
                rv_rows, alignments=["l", "r", "l", "l"]))
            lines.append("")

            # Implied WACC
            iw = rv.get("implied_wacc")
            if iw is not None:
                lines.append(f"**隐含要求回报率（条件诊断）**: 若历史现金流CAGR {self._fmt_pct(rv.get('actual_fcf_cagr'))} 持续，"
                             f"市场隐含要求回报率为 {iw:.2f}%；历史增长不代表未来预测。")
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
        print(f"  WACC: {self._fmt_pct(wacc_data['wacc'])}", file=sys.stderr)

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
                    self.method_status[method_name] = {"status": "INVALID_INPUT", "reason": str(e)}
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

def main(argv=None):
    parser = argparse.ArgumentParser(description="Valuation computation engine")
    parser.add_argument("--code", help="Stock code (required for provider collection; optional consistency check with --dir)")
    parser.add_argument("--output-dir", help="Provider-mode output directory; --dir uses the batch reports directory")
    parser.add_argument("--dir", help="Current B2 batch directory; strictly offline A-share CSV reuse")
    parser.add_argument("--contract", help="JSON cash-flow basis, projections and equity bridge contract")
    parser.add_argument("--total-timeout", type=float, default=180)
    parser.add_argument("--_valuation-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the TTL disk cache for financial endpoints (always fetch live)",
    )
    args = parser.parse_args(argv)
    if not args.dir and (not args.code or not args.output_dir):
        parser.error("provider mode requires --code and --output-dir; use --dir for offline batch reuse")
    from valuation_snapshot import SnapshotError, ValuationSnapshot, load_json_object
    try:
        contract = None
        if args.contract:
            contract_path = Path(args.contract)
            if args.dir and not contract_path.is_absolute():
                contract_path = Path(args.dir) / contract_path
            contract = load_json_object(contract_path)
        ts_code = validate_stock_code(args.code) if args.code else None
        if args.dir:
            batch = Path(args.dir).resolve()
            output_dir = batch / "reports"
            if args.output_dir and Path(args.output_dir).resolve() != output_dir:
                raise SnapshotError("OUTPUT_SCOPE", "--dir writes only reports/valuation_computed.md in the current batch")
            client = ValuationSnapshot(batch, ts_code, contract)
            ts_code = client.ts_code
            print(f"[valuation_engine] 离线复用 {ts_code} 当前批次 CSV...", file=sys.stderr)
        else:
            output_dir = Path(args.output_dir)
            token = get_token()
            # Keep the provider dependency and all credential access on this branch.
            from tushare_collector import TushareClient
            print(f"[valuation_engine] 正在采集 {ts_code} 数据...", file=sys.stderr)
            client = TushareClient(token)
            if args.no_cache:
                client._cache_enabled = False
            client.assemble_data_pack(ts_code)
            if contract is not None:
                client._store["valuation_contract"] = contract
        print("[valuation_engine] 正在计算估值...", file=sys.stderr)
        engine = ValuationEngine(ts_code, str(output_dir), client)
        output_md = engine.run()
        if args.dir:
            # Do not rewrite an unchanged calculation solely for wall-clock seconds.
            import re
            output_md = re.sub(r"(?m)^\*计算时间:.*?\*$", f"*数据快照采集时间: {client.collected_at.isoformat()}*", output_md)
            output_md += "\n\n" + client.provenance_markdown()
        out_path = output_dir / "valuation_computed.md"
        from run_support import atomic_text
        changed = atomic_text(out_path, output_md)
        if args.dir:
            print(json.dumps({"status": "COMPLETE_WITH_LIMITATIONS" if client.limitations else "COMPLETE",
                              "mode": "offline_batch", "stock": ts_code, "output": str(out_path),
                              "changed": changed, "limitations": client.limitations,
                              "method_status": engine.method_status}, ensure_ascii=False, allow_nan=False))
        print(f"[valuation_engine] 完成: {out_path}", file=sys.stderr)
        return 0
    except SnapshotError as exc:
        print(json.dumps(exc.payload, ensure_ascii=False, allow_nan=False))
        return 3 if exc.payload["status"] == "INSUFFICIENT_DATA" else 2
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({"status": "INVALID_INPUT", "code": "VALUATION_INPUT_ERROR", "detail": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
