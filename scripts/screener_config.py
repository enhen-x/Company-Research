"""Configuration for Turtle Screener (龟龟选股器).

Defines ScreenerConfig dataclass with all tunable thresholds, scoring weights,
and cache settings for Tier 1 / Tier 2 screening pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ScreenerConfig:
    """All tunable parameters for the screener pipeline.

    Tier 1 filters (market data only, applied to full A-share universe):
    - Excludes ST/PT/退市整理 stocks
    - Requires listing age >= min_listing_years
    - Requires market cap >= min_market_cap_yi (亿元)
    - Requires daily turnover >= min_turnover_pct (%)
    - Requires 0 < PB <= max_pb
    - Requires dividend yield > 0

    Tier 1 dual-channel PE:
    - Main channel: 0 < PE_TTM <= max_pe
    - Observation channel: PE_TTM < 0, top obs_channel_limit by market cap

    Tier 1 ranking:
    - Composite score = dv_weight * dv_ttm + pe_weight * (1/PE) + pb_weight * (1/PB)
    - Main channel takes top tier2_main_limit
    - Total into Tier 2: tier2_main_limit + obs_channel_limit

    Tier 2 hard vetoes:
    - Pledge ratio > max_pledge_pct → reject
    - Non-standard audit opinion → reject

    Tier 2 financial quality:
    - ROE(weighted) >= min_roe (%)
    - Gross margin >= min_gross_margin (%)
    - Debt-to-assets <= max_debt_ratio (%)

    Scoring weights (must sum to 1.0):
    - ROE, FCF yield, penetration R, EV/EBITDA (inverse), floor premium (inverse)
    """

    # --- Tier 1: Hard filters ---
    min_listing_years: int = 3
    min_market_cap_yi: float = 5.0  # 亿元
    min_turnover_pct: float = 0.1   # %
    max_pb: float = 10.0
    max_pe: float = 50.0
    include_bank: bool = False  # 是否包含银行股

    # --- Tier 1: Dual-channel PE ---
    obs_channel_limit: int = 50

    # --- Tier 1: Ranking & cutoff ---
    tier2_main_limit: int = 150
    dv_weight: float = 0.4
    pe_weight: float = 0.3
    pb_weight: float = 0.3

    # --- Tier 2: Hard vetoes ---
    max_pledge_pct: float = 70.0

    # --- Tier 2: Financial quality ---
    min_roe: float = 8.0             # %
    min_gross_margin: float = 15.0   # %
    max_debt_ratio: float = 70.0     # %

    # --- Tier 2: Observation channel quality (relaxed vs main) ---
    min_roe_obs: float = 0.0                # vs 8% for main channel
    min_fcf_margin_obs: float = 0.0         # FCF/Revenue >= 0%
    min_fcf_positive_years_obs: int = 2     # FCF positive in >= 2 of 5 years
    obs_require_ocf_positive: bool = True   # Latest year OCF > 0

    # --- Scoring weights ---
    weight_roe: float = 0.20
    weight_fcf_yield: float = 0.20
    weight_penetration_r: float = 0.25
    weight_ev_ebitda: float = 0.15
    weight_floor_premium: float = 0.20

    # --- Cache ---
    cache_dir: str = "output/.screener_cache"
    cache_stock_basic_ttl_days: int = 7
    cache_daily_basic_ttl_days: int = 0  # 0 = same-day only
    cache_rf_ttl_days: int = 1
    cache_tier2_ttl_hours: int = 24
    cache_tier2_financial_ttl_hours: int = 168  # 7天，年报类数据
    cache_tier2_market_ttl_hours: int = 24      # 1天，周线行情
    cache_tier2_global_ttl_hours: int = 24      # 1天，yc_cb 无风险利率

    @property
    def tier2_max_stocks(self) -> int:
        """Total stocks entering Tier 2 = main + observation."""
        return self.tier2_main_limit + self.obs_channel_limit

    @property
    def scoring_weights(self) -> dict[str, float]:
        """Return scoring weights as a dict."""
        return {
            "roe": self.weight_roe,
            "fcf_yield": self.weight_fcf_yield,
            "penetration_r": self.weight_penetration_r,
            "ev_ebitda": self.weight_ev_ebitda,
            "floor_premium": self.weight_floor_premium,
        }

    def validate(self) -> list[str]:
        """Validate configuration. Returns list of error messages (empty = OK)."""
        errors = []
        w_sum = (self.weight_roe + self.weight_fcf_yield +
                 self.weight_penetration_r + self.weight_ev_ebitda +
                 self.weight_floor_premium)
        if abs(w_sum - 1.0) > 0.01:
            errors.append(f"Scoring weights must sum to 1.0, got {w_sum:.3f}")
        if self.min_listing_years < 0:
            errors.append("min_listing_years must be >= 0")
        if self.min_market_cap_yi < 0:
            errors.append("min_market_cap_yi must be >= 0")
        if self.tier2_main_limit < 1:
            errors.append("tier2_main_limit must be >= 1")
        if self.obs_channel_limit < 0:
            errors.append("obs_channel_limit must be >= 0")
        if self.min_fcf_positive_years_obs < 0 or self.min_fcf_positive_years_obs > 5:
            errors.append("min_fcf_positive_years_obs must be 0-5")
        return errors

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for display/serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScreenerConfig":
        """Create from dict, ignoring unknown keys."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)
