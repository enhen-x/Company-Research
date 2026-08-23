"""Turtle Investment Framework - InfrastructureMixin.

Utility methods: market detection, display formatting, HK pivot, store helpers.
"""

import pandas as pd

from format_utils import format_number


class InfrastructureMixin:
    """Mixin providing infrastructure utilities for TushareClient."""

    @staticmethod
    def _detect_currency(ts_code: str) -> str:
        """Detect reporting currency based on stock code suffix."""
        upper = ts_code.upper()
        if upper.endswith(".HK"):
            return "HKD"
        elif upper.endswith(".US"):
            return "USD"
        return "CNY"

    @staticmethod
    def _is_hk(ts_code: str) -> bool:
        """Check if stock code is a Hong Kong listing."""
        return ts_code.upper().endswith(".HK")

    @staticmethod
    def _is_us(ts_code: str) -> bool:
        """Check if stock code is a US listing."""
        return ts_code.upper().endswith(".US")

    def _unit_label(self) -> str:
        """Return currency-appropriate unit label for display."""
        return {"HKD": "百万港元", "USD": "百万美元"}.get(self._currency, "百万元")

    def _price_unit(self) -> str:
        """Return currency-appropriate price unit for display."""
        return {"HKD": "港元", "USD": "美元"}.get(self._currency, "元")

    def _detect_fy_end_month(self, df: pd.DataFrame) -> int:
        """Infer fiscal-year end month from end_date column.

        Groups by month, finds the month appearing in most distinct years.
        For calendar-year companies -> 12. For AAPL (Sep FY) -> 9.
        """
        if df.empty or "end_date" not in df.columns:
            return 12
        months = df["end_date"].astype(str).str[4:6].astype(int)
        years = df["end_date"].astype(str).str[:4]
        temp = pd.DataFrame({"month": months, "year": years})
        counts = temp.groupby("month")["year"].nunique()
        if counts.empty:
            return 12
        return int(counts.idxmax())

    @staticmethod
    def _us_api_code(ts_code: str) -> str:
        """Strip .US suffix for Tushare US API calls (Tushare uses plain tickers)."""
        return ts_code.rsplit(".", 1)[0]

    @staticmethod
    def _pivot_hk_line_items(df: pd.DataFrame, field_map: dict) -> pd.DataFrame:
        """Pivot HK ind_name/ind_value rows into one-row-per-period columns.

        HK financial APIs return data in line-item format:
            end_date | ind_name   | ind_value
            20241231 | 营业额     | 60000
            20241231 | 除税后溢利 | 10000
        This pivots them into columnar format matching A-share structure.
        """
        if df.empty or "ind_name" not in df.columns:
            return pd.DataFrame()

        reverse_map = {v: k for k, v in field_map.items() if v is not None}
        df_mapped = df[df["ind_name"].isin(reverse_map)].copy()
        if df_mapped.empty:
            return pd.DataFrame()

        df_mapped["field"] = df_mapped["ind_name"].map(reverse_map)

        # Convert ind_value to numeric
        df_mapped["ind_value"] = pd.to_numeric(df_mapped["ind_value"], errors="coerce")

        pivoted = df_mapped.pivot_table(
            index=["end_date", "ts_code"], columns="field",
            values="ind_value", aggfunc="first"
        ).reset_index()
        pivoted.columns.name = None
        return pivoted

    def _prepare_display_periods(self, df, max_annual=5):
        """Select up to max_annual annual reports + any newer interim reports.

        Returns (display_df, column_labels) where column_labels are like:
        ["2025Q3", "2025H1", "2025Q1", "2024", "2023", "2022", "2021", "2020"]
        """
        if df.empty:
            return df, []

        df = df.drop_duplicates(subset=["end_date"])

        fy_month_str = f"{self._fy_end_month:02d}"

        # Split into annual (FY end month) and non-annual
        annual = df[df["end_date"].str[4:6] == fy_month_str].copy()
        non_annual = df[df["end_date"].str[4:6] != fy_month_str].copy()

        # Sort annual descending, take top max_annual
        annual = annual.sort_values("end_date", ascending=False).head(max_annual)

        latest_annual_date = annual["end_date"].max() if not annual.empty else "00000000"

        # Keep only non-annual entries strictly newer than latest annual
        interim = non_annual[non_annual["end_date"] > latest_annual_date].copy()
        interim = interim.sort_values("end_date", ascending=False)

        # Build labels
        fy_month = self._fy_end_month

        def _label(end_date):
            mm = end_date[4:6]
            mmdd = end_date[4:]
            year = end_date[:4]
            if mm == fy_month_str:
                return year
            elif mmdd == "0630":
                return f"{year}H1"
            elif mmdd == "0331":
                return f"{year}Q1"
            elif mmdd == "0930":
                return f"{year}Q3"
            else:
                return f"{year}_{mmdd}"

        # Combine: interim (desc) + annual (desc)
        display_df = pd.concat([interim, annual], ignore_index=True)
        if display_df.empty:
            return display_df, []

        labels = [_label(d) for d in display_df["end_date"]]
        return display_df, labels

    # --- Feature #90-92: Derived metrics (Section 17) ---

    @staticmethod
    def _safe_float(val) -> float | None:
        """Convert a value to float, returning None for NaN/None."""
        if val is None:
            return None
        try:
            f = float(val)
            return None if f != f else f  # NaN check
        except (TypeError, ValueError):
            return None

    def _get_annual_df(self, store_key: str) -> pd.DataFrame:
        """Get stored DataFrame filtered to annual periods only."""
        df = self._store.get(store_key)
        if df is None or df.empty:
            return pd.DataFrame()
        fy_month_str = f"{self._fy_end_month:02d}"
        annual = df[df["end_date"].str[4:6] == fy_month_str].copy()
        return annual.sort_values("end_date", ascending=False)

    def _get_annual_series(self, store_key: str, col: str) -> list[tuple[str, float | None]]:
        """Extract (year_label, value) pairs for annual periods, sorted desc."""
        df = self._get_annual_df(store_key)
        if df.empty or col not in df.columns:
            return []
        result = []
        for _, r in df.iterrows():
            year = str(r["end_date"])[:4]
            result.append((year, self._safe_float(r.get(col))))
        return result

    @staticmethod
    def _resolve_hk_payout(ts_ratio: float | None, dps: float | None, eps: float | None) -> float | None:
        """Resolve HK payout ratio (%) with Tushare fix + DPS/EPS cross-validation.

        Steps:
        1. Fix Tushare divi_ratio if < 1 (dirty data: decimal instead of %).
        2. Self-compute from DPS / EPS × 100 if both available.
        3. Cross-validate: prefer Tushare if diff < 20%, else use computed.
        4. Fall back to whichever is available; None if neither.
        """
        # Step 1: fix Tushare divi_ratio if < 1
        if ts_ratio is not None and ts_ratio < 1:
            ts_ratio *= 100

        # Step 2: self-compute from DPS / EPS
        computed = None
        if dps is not None and dps > 0 and eps is not None and eps > 0:
            computed = dps / eps * 100

        # Step 3: cross-validate and pick
        if ts_ratio is not None and computed is not None:
            diff = abs(ts_ratio - computed) / computed
            return ts_ratio if diff < 0.2 else computed
        if computed is not None:
            return computed
        if ts_ratio is not None:
            return ts_ratio
        return None

    def _get_payout_by_year(self) -> dict[str, float]:
        """Get payout ratio (%) by year from stored dividend data.

        HK path: Tushare divi_ratio fix + DPS/EPS cross-validation.
        A-share path: computes from cash_div × base_share × 10000 / net_income × 100.
        """
        # HK path: Tushare divi_ratio fix + DPS/EPS cross-validation
        hk_df = self._store.get("dividends_hk")
        if hk_df is not None and not hk_df.empty:
            # Build EPS lookup from income statement
            income_df = self._get_annual_df("income")
            eps_lookup: dict[str, float] = {}
            if not income_df.empty and "basic_eps" in income_df.columns:
                for _, r in income_df.iterrows():
                    year = str(r["end_date"])[:4]
                    eps = self._safe_float(r.get("basic_eps"))
                    if eps and eps > 0:
                        eps_lookup[year] = eps

            result: dict[str, float] = {}
            for _, r in hk_df.iterrows():
                year = str(r.get("end_date", ""))[:4]
                if not year:
                    continue
                ts_ratio = self._safe_float(r.get("divi_ratio"))
                dps = self._safe_float(r.get("dps_hkd"))
                eps = eps_lookup.get(year)
                resolved = self._resolve_hk_payout(ts_ratio, dps, eps)
                if resolved is not None:
                    result[year] = resolved
            return result

        # A-share path: compute from _store["dividends"] + _store["income"]
        div_df = self._store.get("dividends")
        income_df = self._get_annual_df("income")
        if div_df is None or div_df.empty or income_df.empty:
            return {}

        # Build dividend total lookup by year (sum multiple payments per year)
        div_lookup: dict[str, float] = {}
        for _, r in div_df.iterrows():
            year = str(r.get("end_date", ""))[:4]
            cash_div = self._safe_float(r.get("cash_div_tax")) or 0
            base_share = self._safe_float(r.get("base_share")) or 0
            payment = cash_div * base_share * 10000  # base_share is 万股
            div_lookup[year] = div_lookup.get(year, 0) + payment

        # Build net income lookup by year
        np_lookup = {}
        for _, r in income_df.iterrows():
            year = str(r["end_date"])[:4]
            np_lookup[year] = self._safe_float(r.get("n_income_attr_p"))

        result = {}
        for year, div_total in div_lookup.items():
            np_val = np_lookup.get(year)
            if div_total and np_val and np_val > 0:
                result[year] = div_total / np_val * 100
        return result
