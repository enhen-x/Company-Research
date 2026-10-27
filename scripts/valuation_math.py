"""Shared deterministic valuation math and accounting definitions.

The helpers in this module deliberately return ``None`` for unavailable
observations.  They do not turn missing inputs into zero or an estimated
default, because that would make a valuation appear more certain than its
source data supports.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Iterable, Sequence


def _period_number(label) -> float | None:
    """Return a comparable year value for annual/date labels."""
    if label is None:
        return None
    text = str(label)
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) >= 8:
        try:
            parsed = datetime.strptime(digits[:8], "%Y%m%d")
            # A financial year label represents one annual period.  Keeping
            # the fiscal month also handles a changed year end without making
            # an ordinary leap year alter a two-year CAGR.
            return parsed.year + (parsed.month - 1) / 12
        except ValueError:
            pass
    match = re.search(r"(\d{4})", text)
    return float(match.group(1)) if match else None


def cagr(series: Sequence, *, positive_only: bool = True) -> float | None:
    """Compute CAGR while preserving the actual distance between periods.

    Items may be values (legacy behavior) or ``(period, value)`` pairs.  With
    period labels, missing observations in the middle do not compress the
    elapsed time.  Non-positive endpoints cannot support a normal CAGR.
    """
    records: list[tuple[object | None, float, int]] = []
    labelled = True
    for index, item in enumerate(series):
        if isinstance(item, (tuple, list)) and len(item) == 2:
            label, value = item
        else:
            labelled = False
            label, value = None, item
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        records.append((label, number, index))
    if len(records) < 2:
        return None

    latest_label, latest, latest_index = records[0]
    oldest_label, oldest, oldest_index = records[-1]
    if oldest <= 0 or latest <= 0:
        return None
    periods = oldest_index - latest_index
    if labelled:
        latest_period = _period_number(latest_label)
        oldest_period = _period_number(oldest_label)
        if latest_period is None or oldest_period is None:
            return None
        periods = abs(latest_period - oldest_period)
    if periods <= 0:
        return None
    return (latest / oldest) ** (1.0 / periods) - 1.0


def canonical_ebitda(
    total_profit: float | None,
    interest_expense: float | None,
    depreciation_amortization: float | None,
) -> float | None:
    """Return EBITDA on the shared pre-tax-profit definition.

    ``TOTAL_PROFIT + FE_INTEREST_EXPENSE + D&A`` is the canonical source
    definition used by the input builder and derived metrics.  A missing
    component remains unavailable; operating profit is not substituted.
    """
    values = (total_profit, interest_expense, depreciation_amortization)
    if any(value is None for value in values):
        return None
    try:
        numbers = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in numbers):
        return None
    return sum(numbers)


def validate_discount_pair(discount_rate: float, terminal_growth: float) -> tuple[float, float]:
    """Validate decimal discount/growth rates and reject an invalid terminal."""
    try:
        discount = float(discount_rate)
        growth = float(terminal_growth)
    except (TypeError, ValueError) as exc:
        raise ValueError("discount rate and terminal growth must be numeric") from exc
    if not math.isfinite(discount) or not math.isfinite(growth):
        raise ValueError("discount rate and terminal growth must be finite")
    if discount <= growth:
        raise ValueError(f"discount rate ({discount}) must be greater than terminal growth ({growth})")
    if discount <= 0:
        raise ValueError("discount rate must be positive")
    if growth <= -1:
        raise ValueError("terminal growth must be greater than -100%")
    return discount, growth


def enterprise_dcf(cash_flows: Iterable[float], discount_rate: float, terminal_growth: float) -> dict:
    """Discount a stream; the caller must apply its FCFF/FCFE value bridge.

    The historical name is retained, but this pure formula is equally valid
    for FCFF/WACC and FCFE/Ke.  It does not itself add cash or subtract debt.
    """
    discount, growth = validate_discount_pair(discount_rate, terminal_growth)
    flows = []
    for value in cash_flows:
        if value is None or not math.isfinite(float(value)):
            raise ValueError("cash flows must be finite and non-missing")
        flows.append(float(value))
    if not flows:
        raise ValueError("cash flow stream cannot be empty")
    if flows[-1] <= 0:
        raise ValueError("terminal cash flow must be positive")
    pv_fcf = sum(value / (1 + discount) ** (index + 1) for index, value in enumerate(flows))
    terminal_value = flows[-1] * (1 + growth) / (discount - growth)
    pv_terminal = terminal_value / (1 + discount) ** len(flows)
    return {
        "ev": pv_fcf + pv_terminal,
        "pv_fcf": pv_fcf,
        "terminal_value": terminal_value,
        "pv_terminal": pv_terminal,
        "terminal_share": pv_terminal / (pv_fcf + pv_terminal),
    }


def stable_cashflow_path(base: float, growth: float, terminal_growth: float) -> list[float]:
    """Five-year fade used by both the forward stable DCF and its inverse.

    Rates are decimals. Years 1–2 retain growth, then fade to terminal growth.
    This is a conditional model assumption, not an estimate of market consensus.
    """
    numbers = (base, growth, terminal_growth)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in numbers):
        raise ValueError("base and growth rates must be finite numbers")
    if base <= 0 or growth <= -1 or terminal_growth <= -1:
        raise ValueError("base must be positive and growth rates must exceed -100%")
    fade = (growth + terminal_growth) / 2
    rates = (growth, growth, fade, (fade + terminal_growth) / 2, terminal_growth)
    projected, previous = [], base
    for rate in rates:
        previous *= 1 + rate
        if not math.isfinite(previous):
            raise ValueError("projected cash flow overflow")
        projected.append(previous)
    return projected


def implied_stable_growth(base: float, target_value: float, discount_rate: float,
                          terminal_growth: float, bounds=(-.99, 3.0)) -> dict:
    """Bounded inverse of the exact five-year forward DCF, solving only growth.

    The caller uses the same EV/equity bridge as its forward valuation. Terminal
    growth, base cash flow, discount rate, horizon and fade convention stay fixed.
    No bracketing expansion or optimizer dependency; at most 100 bisections.
    """
    discount, terminal = validate_discount_pair(discount_rate, terminal_growth)
    if isinstance(target_value, bool) or not isinstance(target_value, (int, float)) or not math.isfinite(target_value) or target_value <= 0:
        raise ValueError("target value must be positive and finite")
    if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
        raise ValueError("growth bounds must contain exactly two values")
    low, high = bounds
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bounds) or not -1 < low < high:
        raise ValueError("growth bounds must be finite, ordered and greater than -100%")

    def forward(growth):
        return enterprise_dcf(stable_cashflow_path(base, growth, terminal), discount, terminal)["ev"]

    lower_value, upper_value = forward(low), forward(high)
    if not all(math.isfinite(value) for value in (lower_value, upper_value)):
        raise ValueError("valuation overflow at supplied growth bounds")
    common = {"model": "five_year_stable_dcf_v1", "variable": "initial_growth",
              "bounds": [low, high], "value_at_bounds": [lower_value, upper_value],
              "target_value": target_value, "base_cashflow": base,
              "discount_rate": discount, "terminal_growth": terminal,
              "fixed_assumptions": ["base_cashflow", "discount_rate", "terminal_growth", "five_year_horizon", "fade_convention"]}
    tolerance = max(abs(target_value) * 1e-10, 1e-8)
    if target_value < lower_value - tolerance or target_value > upper_value + tolerance:
        return {**common, "status": "NO_SOLUTION", "implied_growth": None, "iterations": 0,
                "reason": "target outside value range of declared growth bounds"}
    candidate = low if abs(target_value - lower_value) <= tolerance else high
    reconstructed = forward(candidate)
    iterations = 0
    while abs(reconstructed - target_value) > tolerance and iterations < 100:
        candidate = (low + high) / 2
        reconstructed = forward(candidate)
        if reconstructed < target_value:
            low = candidate
        else:
            high = candidate
        iterations += 1
    passed = abs(reconstructed - target_value) <= tolerance
    return {**common, "status": "COMPUTED" if passed else "NO_CONVERGENCE",
            "implied_growth": candidate if passed else None, "iterations": iterations,
            "reconstructed_value": reconstructed, "absolute_error": abs(reconstructed - target_value),
            "projected_cashflows": stable_cashflow_path(base, candidate, terminal) if passed else None}


def perpetuity_value(last_cash_flow: float, discount_rate: float, growth: float) -> float:
    """Gordon value when ``last_cash_flow`` is period-zero cash flow."""
    discount, terminal_growth = validate_discount_pair(discount_rate, growth)
    if not math.isfinite(float(last_cash_flow)) or last_cash_flow <= 0:
        raise ValueError("perpetual cash flow must be positive and finite")
    return last_cash_flow * (1 + terminal_growth) / (discount - terminal_growth)


def implied_perpetual_growth(last_cash_flow: float, value: float, discount_rate: float) -> float:
    """Exact inverse of :func:`perpetuity_value`, holding other inputs fixed."""
    if not all(math.isfinite(float(item)) for item in (last_cash_flow, value, discount_rate)):
        raise ValueError("perpetuity inputs must be finite")
    if last_cash_flow <= 0 or value <= 0:
        raise ValueError("perpetual cash flow and value must be positive")
    growth = (value * discount_rate - last_cash_flow) / (value + last_cash_flow)
    validate_discount_pair(discount_rate, growth)
    if growth <= -1:
        raise ValueError("implied perpetual growth is outside the valid domain")
    return growth
