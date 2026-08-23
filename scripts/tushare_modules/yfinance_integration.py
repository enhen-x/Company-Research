"""Turtle Investment Framework - YFinanceMixin.

All yfinance integration methods for HK/US price and financial data fallback.
"""

import sys
import time

import pandas as pd

from tushare_modules.constants import _YF_INCOME_MAP, _YF_BALANCE_MAP, _YF_CASHFLOW_MAP


def _yf():
    """Access yfinance module via tushare_collector for @patch compatibility."""
    return sys.modules["tushare_collector"].yf


class YFinanceMixin:
    """Mixin providing yfinance fallback methods for TushareClient."""

    @staticmethod
    def _yf_ticker(ts_code: str) -> str:
        """Convert Tushare stock code to yfinance ticker symbol."""
        code, suffix = ts_code.rsplit(".", 1)
        suffix = suffix.upper()
        if suffix == "SH":
            return f"{code}.SS"
        elif suffix == "SZ":
            return f"{code}.SZ"
        elif suffix == "HK":
            # Tushare 5-digit → YF 4-digit (e.g., 00700 -> 0700)
            return f"{code.lstrip('0').zfill(4)}.HK"
        elif suffix == "US":
            return code  # yfinance uses plain tickers for US stocks
        return ts_code

    def _yf_fallback_price(self, ts_code: str) -> dict | None:
        """Fetch basic price/market cap via yfinance as fallback."""
        if not self._yf_available:
            return None
        try:
            ticker = _yf().Ticker(self._yf_ticker(ts_code))
            info = ticker.info
            return {
                "close": info.get("regularMarketPrice") or info.get("previousClose"),
                "market_cap": info.get("marketCap"),
                "source": "yfinance (降级)",
            }
        except Exception:
            return None

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

    def _yf_hk_market_data(self, ts_code: str) -> dict | None:
        """Fetch HK stock market data via yfinance (52-week, price, volume)."""
        if not self._yf_available:
            return None
        try:
            ticker = _yf().Ticker(self._yf_ticker(ts_code))
            info = ticker.info
            return {
                "close": info.get("regularMarketPrice") or info.get("previousClose"),
                "high_52w": info.get("fiftyTwoWeekHigh"),
                "low_52w": info.get("fiftyTwoWeekLow"),
                "market_cap": info.get("marketCap"),
                "volume_avg": info.get("averageDailyVolume10Day"),
            }
        except Exception:
            return None

    def _yf_weekly_history(self, ts_code: str) -> pd.DataFrame:
        """Fetch 10-year weekly price history via yfinance."""
        if not self._yf_available:
            return pd.DataFrame()
        try:
            ticker = _yf().Ticker(self._yf_ticker(ts_code))
            df = ticker.history(period="10y", interval="1wk")
            if df.empty:
                return df
            # Normalize column names to match Tushare weekly format
            df = df.reset_index()
            df = df.rename(columns={
                "Date": "trade_date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "vol",
            })
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")
            df["ts_code"] = ts_code
            return df[["ts_code", "trade_date", "open", "high", "low", "close", "vol"]]
        except Exception:
            return pd.DataFrame()

    def _yf_fill_missing_hk(self, pivoted, ts_code, statement_type):
        """Fill NaN fields in pivoted HK DataFrame using yfinance data.

        Args:
            pivoted: DataFrame with Tushare data (one row per period).
            ts_code: Tushare stock code (e.g. '00700.HK').
            statement_type: 'income', 'balance', or 'cashflow'.

        Returns:
            (filled_df, yf_used_flag) tuple.
        """
        if not self._yf_available:
            return pivoted, False

        # Select mapping dict FIRST (before NaN check)
        yf_map = {
            "income": _YF_INCOME_MAP,
            "balance": _YF_BALANCE_MAP,
            "cashflow": _YF_CASHFLOW_MAP,
        }.get(statement_type, {})
        if not yf_map:
            return pivoted, False

        filled = pivoted.copy()

        # Ensure all mapped target columns exist (allows filling completely absent fields)
        mapped_ts_cols = set(yf_map.values())
        for col in mapped_ts_cols - set(filled.columns):
            filled[col] = float("nan")

        # Check if any NaN in numeric columns (after column expansion)
        numeric_cols = filled.select_dtypes(include="number").columns
        if numeric_cols.empty or not filled[numeric_cols].isna().any().any():
            return pivoted, False  # return ORIGINAL (no extra NaN cols)

        # Build reverse map: tushare_col → list of yfinance field names
        reverse = {}
        for yf_name, ts_col in yf_map.items():
            reverse.setdefault(ts_col, []).append(yf_name)

        yf_df = None
        max_yf_retries = 2
        for yf_attempt in range(1, max_yf_retries + 1):
            try:
                ticker = _yf().Ticker(self._yf_ticker(ts_code))
                if statement_type == "income":
                    yf_df = ticker.income_stmt
                elif statement_type == "balance":
                    yf_df = ticker.balance_sheet
                else:
                    yf_df = ticker.cashflow
                break  # success
            except Exception as e:
                if yf_attempt < max_yf_retries:
                    time.sleep(1)
                else:
                    print(f"[yfinance] {ts_code} {statement_type}: fallback failed after {max_yf_retries} retries: {e}", file=sys.stderr)
                    return pivoted, False

        if yf_df is None or yf_df.empty:
            print(f"[yfinance] {ts_code} {statement_type}: no data returned", file=sys.stderr)
            return pivoted, False

        yf_used = False

        for idx, row in filled.iterrows():
            end_date = str(row.get("end_date", ""))
            if len(end_date) < 8:
                continue

            # Match yfinance column by date
            yf_col = None
            for col in yf_df.columns:
                ts = pd.Timestamp(col)
                col_date = ts.strftime("%Y%m%d")
                if col_date == end_date:
                    yf_col = col
                    break
            # Fallback: same year + FY end month
            if yf_col is None and int(end_date[4:6]) == self._fy_end_month:
                for col in yf_df.columns:
                    ts = pd.Timestamp(col)
                    if ts.year == int(end_date[:4]) and ts.month == self._fy_end_month:
                        yf_col = col
                        break
            if yf_col is None:
                continue

            # Fill NaN fields from yfinance
            for ts_col, yf_names in reverse.items():
                if ts_col not in filled.columns:
                    continue
                val = filled.at[idx, ts_col]
                if val is not None and val == val:  # not NaN
                    continue
                for yf_name in yf_names:
                    if yf_name in yf_df.index:
                        yf_val = yf_df.at[yf_name, yf_col]
                        if yf_val is not None and yf_val == yf_val:
                            filled.at[idx, ts_col] = float(yf_val)
                            yf_used = True
                            break

        return filled, yf_used
