#!/usr/bin/env python3
"""Turtle Investment Framework - Tushare Data Collector (Phase 1A).

Facade module: re-exports all public names and defines TushareClient
which inherits from mixin classes in tushare_modules/.

Collects 5 years of financial data from Tushare Pro API and outputs
a structured data_pack_market.md file.

Usage:
    python3 scripts/tushare_collector.py --code 600887.SH
    python3 scripts/tushare_collector.py --code 600887.SH --output output/data_pack.md
    python3 scripts/tushare_collector.py --code 600887.SH --dry-run
"""

import argparse
import functools
import os
import sys
import time

import pandas as pd
import tushare as ts

try:
    import yfinance as yf
    _yf_available = True
except ImportError:
    _yf_available = False

from config import get_token, get_api_url, validate_stock_code
from format_utils import format_number, format_table, format_header

# Re-export all constants and mixin classes for backward compatibility.
# Tests and external code import these from tushare_collector directly:
#   from tushare_collector import TushareClient, WarningsCollector, rate_limit
#   from tushare_collector import _VIP_MAP, HK_INCOME_MAP, US_INCOME_MAP
from tushare_modules import (
    _VIP_MAP,
    HK_INCOME_MAP, HK_BALANCE_MAP, HK_CASHFLOW_MAP,
    US_INCOME_MAP, US_BALANCE_MAP, US_CASHFLOW_MAP,
    _YF_INCOME_MAP, _YF_BALANCE_MAP, _YF_CASHFLOW_MAP,
    InfrastructureMixin, YFinanceMixin, FinancialsMixin,
    OtherDataMixin, DerivedMetricsMixin, AssemblyMixin,
    WarningsCollector,
)

# ============================================================
# TTL cache configuration for heavy (non-market) endpoints
# ============================================================
# Map endpoint (logical name, before VIP mapping) → TTL tier.
#   "financial": statements & indicators — refresh only a few times/year
#   "market":    price/rate series — refresh daily
# Endpoints NOT listed here are never cached (e.g. daily/daily_basic/
# hk_daily/us_daily intraday prices; *_basic use their own file cache).
_CACHE_TTL_CATEGORY = {
    # --- Financial statements & indicators (168h / 7-day TTL) ---
    "income": "financial",
    "balancesheet": "financial",
    "cashflow": "financial",
    "dividend": "financial",
    "fina_indicator": "financial",
    "fina_audit": "financial",
    "fina_mainbz": "financial",
    "top10_holders": "financial",
    "repurchase": "financial",
    "pledge_stat": "financial",
    "hk_income": "financial",
    "hk_balancesheet": "financial",
    "hk_cashflow": "financial",
    "hk_fina_indicator": "financial",
    "us_income": "financial",
    "us_balancesheet": "financial",
    "us_cashflow": "financial",
    "us_fina_indicator": "financial",
    # --- Market data (24h TTL) ---
    "weekly": "market",
    "yc_cb": "market",
}

_CACHE_TTL_HOURS = {"financial": 168, "market": 24}


def rate_limit(func):
    """Decorator to enforce a delay between Tushare API calls.

    The delay (seconds) is read from the ``TUSHARE_RATE_DELAY`` env var at
    call time (default ``0.5``). Set to ``0`` to disable throttling entirely
    (useful when a broker/VIP endpoint has no rate limit). ``time.sleep`` is
    called through the module-level ``time`` import so tests can patch it.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            delay = float(os.environ.get("TUSHARE_RATE_DELAY", "0.5"))
        except ValueError:
            delay = 0.5
        if delay > 0:
            time.sleep(delay)
        return func(*args, **kwargs)
    return wrapper


class TushareClient(
    InfrastructureMixin,
    YFinanceMixin,
    FinancialsMixin,
    OtherDataMixin,
    DerivedMetricsMixin,
    AssemblyMixin,
):
    """Client for Tushare Pro API with rate limiting and retry logic."""

    MAX_RETRIES = 5
    RETRY_DELAY = 2.0  # seconds between retries

    BASIC_CACHE_TTL = 7 * 86400  # 7 days in seconds

    def __init__(self, token: str):
        ts.set_token(token)
        self.pro = ts.pro_api(timeout=30)
        self.token = token
        self._store = {}  # {key: pd.DataFrame} for derived metrics computation
        self._yf_available = _yf_available
        self._cache_dir = os.path.join("output", ".collector_cache")
        self._cache_enabled = True  # TTL cache for heavy financial endpoints
        self._ttl_cache = None       # lazily constructed ScreenerCache
        self._fy_end_month: int = 12  # default: calendar year
        self._currency: str = "CNY"
        # Broker API support: route calls through custom URL + enable VIP endpoints
        api_url = get_api_url()
        self._vip_mode = bool(api_url)
        if api_url:
            self.pro._DataApi__token = token
            self.pro._DataApi__http_url = api_url

    @rate_limit
    def _safe_call(self, api_name: str, **kwargs) -> pd.DataFrame:
        """Call a Tushare API endpoint with retry logic.

        Auto-upgrades to VIP endpoints when broker is active.

        Args:
            api_name: The API endpoint name (e.g., 'stock_basic').
            **kwargs: Parameters passed to the API call.

        Returns:
            DataFrame with results.

        Raises:
            RuntimeError: After MAX_RETRIES failures.
        """
        # Auto-upgrade to VIP endpoint when broker is active
        effective_name = api_name
        if self._vip_mode and api_name in _VIP_MAP:
            effective_name = _VIP_MAP[api_name]

        last_err = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                api_func = getattr(self.pro, effective_name)
                df = api_func(**kwargs)
                return df
            except Exception as e:
                last_err = e
                if attempt < self.MAX_RETRIES:
                    is_conn_err = isinstance(e, (ConnectionError, OSError)) or \
                        "RemoteDisconnected" in type(e).__name__ or \
                        "ConnectionAborted" in str(e) or \
                        "RemoteDisconnected" in str(e)
                    if is_conn_err:
                        print(f"[retry {attempt}/{self.MAX_RETRIES}] {effective_name}: connection error, re-creating API client...", file=sys.stderr)
                        self.pro = ts.pro_api(timeout=30)
                        # Re-apply broker hacks after re-creating client
                        api_url = get_api_url()
                        if api_url:
                            self.pro._DataApi__token = self.token
                            self.pro._DataApi__http_url = api_url
                    else:
                        print(f"[retry {attempt}/{self.MAX_RETRIES}] {effective_name}: {e}", file=sys.stderr)
                    time.sleep(self.RETRY_DELAY * attempt)
        raise RuntimeError(
            f"Tushare API '{effective_name}' failed after {self.MAX_RETRIES} retries: {last_err}"
        )

    def _cached_basic_call(self, api_name: str, **kwargs) -> pd.DataFrame:
        """Call stock_basic/hk_basic with 7-day file cache."""
        ts_code = kwargs.get("ts_code", "all")
        cache_file = os.path.join(self._cache_dir, f"{api_name}_{ts_code}.json")
        if os.path.exists(cache_file):
            mtime = os.path.getmtime(cache_file)
            if time.time() - mtime < self.BASIC_CACHE_TTL:
                return pd.read_json(cache_file)
        df = self._safe_call(api_name, **kwargs)
        if not df.empty:
            os.makedirs(self._cache_dir, exist_ok=True)
            df.to_json(cache_file, orient="records", force_ascii=False)
        return df

    def _cached_us_daily(self, ts_code: str = None) -> pd.DataFrame:
        """Fetch us_daily with same-day file cache (bulk all-stock fetch).

        First call fetches ALL US stocks (limit=6000) and caches to Parquet.
        Subsequent same-day calls read from cache and filter by ts_code.
        """
        cache_file = os.path.join(self._cache_dir, "us_daily_all.parquet")
        today = pd.Timestamp.now().strftime("%Y%m%d")

        # Check cache: file exists AND was created today
        if os.path.exists(cache_file):
            mtime = os.path.getmtime(cache_file)
            cache_date = pd.Timestamp.fromtimestamp(mtime).strftime("%Y%m%d")
            if cache_date == today:
                df = pd.read_parquet(cache_file)
                if ts_code:
                    df = df[df["ts_code"] == ts_code]
                return df

        # Bulk fetch all US stocks
        df = self._safe_call("us_daily", limit=6000,
                             fields="ts_code,trade_date,open,high,low,close,"
                                    "vol,amount,pe,pb,total_mv")
        if not df.empty:
            os.makedirs(self._cache_dir, exist_ok=True)
            df.to_parquet(cache_file, index=False)

        if ts_code and not df.empty:
            df = df[df["ts_code"] == ts_code]
        return df

    # --- Phase 2.3: TTL cache for heavy financial endpoints ---

    def _get_ttl_cache(self):
        """Lazily build a ScreenerCache rooted at ``{self._cache_dir}/ttl``.

        Re-derives from the current ``self._cache_dir`` at call time; if the
        directory changed since the last build (e.g. tests override
        ``_cache_dir`` after construction), a fresh cache object is created.
        """
        from cache_utils import ScreenerCache
        ttl_dir = os.path.join(self._cache_dir, "ttl")
        if self._ttl_cache is None or self._ttl_cache.cache_dir != ttl_dir:
            self._ttl_cache = ScreenerCache(ttl_dir)
        return self._ttl_cache

    @staticmethod
    def _ttl_cache_key(api_name: str, kwargs: dict) -> str:
        """Build a deterministic cache key for a cacheable endpoint call.

        Keyed on the LOGICAL api_name (stable across VIP/non-VIP), the ts_code
        (so per-stock invalidation via ``collector_{ts_code}_`` works), and a
        deterministic signature of the sorted kwargs (so report_type=1 vs 6 are
        cached separately).
        """
        ts_code = kwargs.get("ts_code", "global")
        sig = ";".join(f"{k}={kwargs[k]}" for k in sorted(kwargs))
        return f"collector_{ts_code}_{api_name}_{sig}"

    def _cached_call(self, api_name: str, **kwargs) -> pd.DataFrame:
        """Call a Tushare endpoint through the TTL disk cache when eligible.

        Non-cacheable endpoints (or when ``_cache_enabled`` is False) pass
        straight through to ``_safe_call``. On a cache hit the cached DataFrame
        is returned with no ``_safe_call`` (hence no rate-limit sleep). Empty
        results are never cached.
        """
        category = _CACHE_TTL_CATEGORY.get(api_name)
        if category is None or not self._cache_enabled:
            return self._safe_call(api_name, **kwargs)

        cache = self._get_ttl_cache()
        ttl_seconds = _CACHE_TTL_HOURS[category] * 3600
        key = self._ttl_cache_key(api_name, kwargs)

        cached = cache.get(key, ttl_seconds)
        if cached is not None:
            return cached

        df = self._safe_call(api_name, **kwargs)
        if df is not None and not df.empty:
            cache.put(key, df)
        return df


def parse_args():
    parser = argparse.ArgumentParser(
        description="Collect financial data from Tushare Pro API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --code 600887.SH
  %(prog)s --code 600887 --output output/data_pack_market.md
  %(prog)s --code 00700.HK --extra-fields balancesheet.defer_tax_assets
  %(prog)s --code 600887.SH --cache-refresh   # 财报季（4/8/10月）建议刷新

Note: 财报接口结果会缓存 7 天（行情/利率 24 小时）。财报季（4/8/10 月）
建议加 --cache-refresh 以获取最新披露的财报数据。
        """,
    )
    parser.add_argument(
        "--code",
        required=True,
        help="Stock code (e.g., 600887.SH, 000858.SZ, 00700.HK, or plain digits)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Tushare API token (defaults to TUSHARE_TOKEN env var)",
    )
    parser.add_argument(
        "--output",
        default="output/data_pack_market.md",
        help="Output file path (default: output/data_pack_market.md)",
    )
    parser.add_argument(
        "--extra-fields",
        nargs="*",
        help="Additional fields to fetch (format: endpoint.field_name)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print parsed arguments and exit without calling API",
    )
    parser.add_argument(
        "--refresh-market",
        action="store_true",
        help="Only refresh market-sensitive sections (§1/§2/§11/§14) in existing data pack",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the TTL disk cache for financial endpoints (always fetch live)",
    )
    parser.add_argument(
        "--cache-refresh",
        action="store_true",
        help="Invalidate this stock's cached financial data before collecting "
             "(recommended during earnings season: 4/8/10 月)",
    )
    parser.add_argument(
        "--backend",
        default="auto",
        choices=["auto", "tushare", "akshare"],
        help="Data backend: auto (Tushare first, auto-fallback to AkShare), "
             "tushare (Tushare only), akshare (AkShare only). Default: auto",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Validate and normalize stock code
    try:
        ts_code = validate_stock_code(args.code)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    backend = (args.backend or "auto").lower()

    if args.dry_run:
        print("=== Dry Run ===")
        print(f"  Stock code: {args.code} -> {ts_code}")
        print(f"  Backend: {backend} (auto = Tushare 优先，失败自动降级 AkShare)")
        print(f"  Token: {'provided via --token' if args.token else 'from TUSHARE_TOKEN env (无则降级 AkShare)'}")
        print(f"  Output: {args.output}")
        print(f"  Extra fields: {args.extra_fields or 'none'}")
        return

    data_pack = None
    used_backend = None

    # ========== Tushare 优先 ==========
    if backend in ("auto", "tushare"):
        try:
            # Get token
            token = args.token or get_token()
            client = TushareClient(token)

            # TTL cache controls
            if args.no_cache:
                client._cache_enabled = False
            if args.cache_refresh:
                client._get_ttl_cache().invalidate_prefix(f"collector_{ts_code}_")
                print(f"Cache invalidated for {ts_code}")

            if args.refresh_market:
                from pathlib import Path
                output_path = Path(args.output)
                if not output_path.exists():
                    print(f"⚠️ {output_path} does not exist, falling back to full collection")
                    print(f"Collecting data for {ts_code} (Tushare)...")
                    data_pack = client.assemble_data_pack(ts_code)
                else:
                    existing = output_path.read_text(encoding="utf-8")
                    age_days = client._check_staleness(existing)
                    if age_days > 7:
                        print(f"⚠️ Data pack is {age_days} days old, falling back to full collection")
                        print(f"Collecting data for {ts_code} (Tushare)...")
                        data_pack = client.assemble_data_pack(ts_code)
                    else:
                        print(f"Refreshing market data for {ts_code} (data pack is {age_days} day(s) old)...")
                        data_pack = client.refresh_market_sections(ts_code, existing)
            else:
                print(f"Collecting data for {ts_code} (Tushare)...")
                data_pack = client.assemble_data_pack(ts_code)
            used_backend = "tushare"

            # Handle extra fields (Tushare backend only)
            if args.extra_fields:
                extra_lines = ["\n", format_header(2, "附加字段"), ""]
                for field_spec in args.extra_fields:
                    parts = field_spec.split(".", 1)
                    if len(parts) != 2:
                        extra_lines.append(f"- 无效字段格式: {field_spec} (应为 endpoint.field_name)")
                        continue
                    endpoint, field_name = parts
                    try:
                        df = client._safe_call(endpoint, ts_code=ts_code, fields=f"ts_code,end_date,{field_name}")
                        if not df.empty:
                            extra_lines.append(f"**{endpoint}.{field_name}**:")
                            extra_lines.append(df.to_markdown(index=False))
                            extra_lines.append("")
                        else:
                            extra_lines.append(f"- {endpoint}.{field_name}: 无数据")
                    except Exception as e:
                        extra_lines.append(f"- {endpoint}.{field_name}: 获取失败 ({e})")
                data_pack += "\n".join(extra_lines)
        except Exception as e:
            data_pack = None
            print(f"⚠️ Tushare 采集失败: {e}")
            if backend == "tushare":
                print("Error: 指定 --backend tushare 且 Tushare 不可用，中止。", file=sys.stderr)
                print("可用 --backend auto（自动降级 AkShare）或 --backend akshare。", file=sys.stderr)
                sys.exit(1)
            print("  自动降级至 AkShare 采集...")

    # ========== AkShare 降级 ==========
    if data_pack is None and backend in ("auto", "akshare"):
        if not ts_code.endswith((".SH", ".SZ", ".BJ")):
            print(f"Error: AkShare 降级目前仅支持 A 股（收到 {ts_code}）。"
                  f"港股/美股请配置 TUSHARE_TOKEN 使用 Tushare。", file=sys.stderr)
            sys.exit(1)
        if args.extra_fields:
            print("  ⚠️ --extra-fields 仅在 Tushare 后端支持，AkShare 降级模式忽略")
        if args.no_cache or args.cache_refresh:
            print("  ⚠️ --no-cache/--cache-refresh 仅在 Tushare 后端生效")
        try:
            from akshare_collector import collect as ak_collect
            data_pack = ak_collect(ts_code, refresh_market=args.refresh_market)
            used_backend = "akshare"
        except Exception as e:
            print(f"Error: AkShare 降级采集失败: {e}", file=sys.stderr)
            sys.exit(1)

    if data_pack is None:
        print("Error: 所有数据后端均不可用", file=sys.stderr)
        sys.exit(1)

    # Write output
    import os
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(data_pack)
    print(f"Output written to {args.output} (backend: {used_backend})")
    print(f"File size: {os.path.getsize(args.output):,} bytes")

if __name__ == "__main__":
    main()
