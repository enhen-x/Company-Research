"""Turtle Investment Framework - FinancialsMixin.

Financial statement get_* methods: basic info, market data, income, balance sheet,
cashflow, dividends, weekly prices, financial indicators. Each with CN/HK/US variants.
"""

import sys

import pandas as pd

from format_utils import format_number, format_table, format_header


def _yf():
    """Access yfinance module via tushare_collector for @patch compatibility."""
    return sys.modules["tushare_collector"].yf
from tushare_modules.constants import (
    HK_INCOME_MAP, HK_BALANCE_MAP, HK_CASHFLOW_MAP,
    US_INCOME_MAP, US_BALANCE_MAP, US_CASHFLOW_MAP,
)


class FinancialsMixin:
    """Mixin providing financial statement methods for TushareClient."""

    # --- Feature #14: Section 1 — Basic company info ---

    def get_basic_info(self, ts_code: str) -> str:
        """Section 1: Basic company info from stock_basic/hk_basic/us_basic + daily_basic."""
        if self._is_hk(ts_code):
            return self._get_basic_info_hk(ts_code)
        if self._is_us(ts_code):
            return self._get_basic_info_us(ts_code)

        basic = self._cached_basic_call("stock_basic", ts_code=ts_code,
                                       fields="ts_code,name,industry,area,market,exchange,list_date,fullname")
        if basic.empty:
            return format_header(2, "1. 基本信息") + "\n\n数据缺失\n"

        row = basic.iloc[0]

        # Get latest daily_basic for valuation
        daily = self._safe_call("daily_basic", ts_code=ts_code,
                                fields="ts_code,trade_date,close,pe_ttm,pb,total_mv,circ_mv,total_share,float_share")
        val_rows = []
        if not daily.empty:
            # Broker VIP relays may return rows oldest-first; enforce newest-first
            # so iloc[0] (and every downstream _store["basic_info"] consumer) is the latest.
            if "trade_date" in daily.columns:
                daily = daily.sort_values("trade_date", ascending=False).reset_index(drop=True)
            self._store["basic_info"] = daily
            d = daily.iloc[0]
            val_rows = [
                ["当前价格", f"{d.get('close', '—')}"],
                ["PE (TTM)", f"{d.get('pe_ttm', '—')}"],
                ["PB", f"{d.get('pb', '—')}"],
                ["总市值 (万元)", format_number(d.get('total_mv', None), divider=1, decimals=2)],
                ["流通市值 (万元)", format_number(d.get('circ_mv', None), divider=1, decimals=2)],
            ]

        lines = [format_header(2, "1. 基本信息"), ""]
        info_table = format_table(
            ["项目", "内容"],
            [
                ["股票代码", str(row.get("ts_code", ""))],
                ["公司名称", str(row.get("name", ""))],
                ["全称", str(row.get("fullname", ""))],
                ["行业", str(row.get("industry", ""))],
                ["地区", str(row.get("area", ""))],
                ["交易所", str(row.get("exchange", ""))],
                ["上市日期", str(row.get("list_date", ""))],
            ] + val_rows,
            alignments=["l", "r"],
        )
        lines.append(info_table)
        return "\n".join(lines)

    def _get_basic_info_hk(self, ts_code: str) -> str:
        """Section 1 (HK): Basic info from hk_basic + hk_fina_indicator."""
        basic = self._cached_basic_call("hk_basic", ts_code=ts_code,
                                       fields="ts_code,name,fullname,market,list_date,enname")
        if basic.empty:
            return format_header(2, "1. 基本信息") + "\n\n数据缺失\n"

        row = basic.iloc[0]

        # Get PE/PB/market_cap from hk_fina_indicator
        val_rows = []
        try:
            fina = self._safe_call("hk_fina_indicator", ts_code=ts_code,
                                   fields="ts_code,end_date,pe_ttm,pb_ttm,total_market_cap,hksk_market_cap")
            if not fina.empty:
                # Broker VIP relays may return rows oldest-first; enforce newest-first
                if "end_date" in fina.columns:
                    fina = fina.sort_values("end_date", ascending=False).reset_index(drop=True)
                self._store["basic_info"] = fina
                d = fina.iloc[0]
                # Try yfinance for current price
                close_price = "—"
                yf_data = self._yf_hk_market_data(ts_code)
                if yf_data and yf_data.get("close"):
                    close_price = f"{yf_data['close']:.2f}"
                    # Store close for downstream
                    fina_copy = fina.copy()
                    fina_copy["close"] = yf_data["close"]
                    self._store["basic_info"] = fina_copy
                val_rows = [
                    ["当前价格 (HKD)", close_price],
                    ["PE (TTM)", f"{d.get('pe_ttm', '—')}"],
                    ["PB", f"{d.get('pb_ttm', '—')}"],
                    ["总市值 (百万港元)", format_number(d.get('total_market_cap', None), divider=1, decimals=2)],
                ]
        except RuntimeError:
            pass

        lines = [format_header(2, "1. 基本信息"), ""]
        info_table = format_table(
            ["项目", "内容"],
            [
                ["股票代码", str(row.get("ts_code", ""))],
                ["公司名称", str(row.get("name", ""))],
                ["全称", str(row.get("fullname", ""))],
                ["英文名", str(row.get("enname", ""))],
                ["市场", str(row.get("market", ""))],
                ["上市日期", str(row.get("list_date", ""))],
            ] + val_rows,
            alignments=["l", "r"],
        )
        lines.append(info_table)
        return "\n".join(lines)

    def _get_basic_info_us(self, ts_code: str) -> str:
        """Section 1 (US): Basic info from us_basic + us_daily."""
        api_code = self._us_api_code(ts_code)
        basic = self._cached_basic_call("us_basic", ts_code=api_code,
                                       fields="ts_code,name,enname,market,list_date")
        if basic.empty:
            return format_header(2, "1. 基本信息") + "\n\n数据缺失\n"

        row = basic.iloc[0]
        name = str(row.get("name", "")) or ""
        if (not name or name == "None") and self._yf_available:
            try:
                info = _yf().Ticker(self._yf_ticker(ts_code)).info
                name = info.get("longName") or info.get("shortName") or str(row.get("enname", ""))
            except Exception:
                name = str(row.get("enname", ""))
        if not name or name == "None":
            name = str(row.get("enname", ""))

        # Get latest us_daily for price/PE/PB/market_cap
        val_rows = []
        try:
            daily = self._cached_us_daily(ts_code=api_code)
            if not daily.empty:
                # Enforce newest-first (bulk cache / relay ordering not guaranteed)
                if "trade_date" in daily.columns:
                    daily = daily.sort_values("trade_date", ascending=False).reset_index(drop=True)
                self._store["basic_info"] = daily
                d = daily.iloc[0]
                val_rows = [
                    ["当前价格 (USD)", f"{d.get('close', '—')}"],
                    ["PE", f"{d.get('pe', '—')}"],
                    ["PB", f"{d.get('pb', '—')}"],
                    ["总市值 (百万美元)", format_number(d.get('total_mv', None), divider=1e6, decimals=2)],
                ]
        except RuntimeError:
            pass

        lines = [format_header(2, "1. 基本信息"), ""]
        info_table = format_table(
            ["项目", "内容"],
            [
                ["股票代码", ts_code],
                ["公司名称", name],
                ["英文名", str(row.get("enname", ""))],
                ["市场", str(row.get("market", "")) or "US"],
                ["上市日期", str(row.get("list_date", ""))],
            ] + val_rows,
            alignments=["l", "r"],
        )
        lines.append(info_table)
        return "\n".join(lines)

    # --- Feature #15: Section 2 — Market data ---

    def get_market_data(self, ts_code: str) -> str:
        """Section 2: Current price and 52-week range."""
        if self._is_hk(ts_code):
            return self._get_market_data_hk(ts_code)
        if self._is_us(ts_code):
            return self._get_market_data_us(ts_code)

        today = pd.Timestamp.now().strftime("%Y%m%d")
        year_ago = (pd.Timestamp.now() - pd.DateOffset(years=1)).strftime("%Y%m%d")

        df = self._safe_call("daily", ts_code=ts_code,
                             start_date=year_ago, end_date=today,
                             fields="ts_code,trade_date,open,high,low,close,vol,amount")
        lines = [format_header(2, "2. 市场行情"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        # Broker VIP relays may return rows oldest-first; enforce newest-first
        if "trade_date" in df.columns:
            df = df.sort_values("trade_date", ascending=False).reset_index(drop=True)
        latest_close = df.iloc[0]["close"]
        high_52w = df["high"].max()
        low_52w = df["low"].min()
        high_date = df.loc[df["high"].idxmax(), "trade_date"]
        low_date = df.loc[df["low"].idxmin(), "trade_date"]
        avg_vol = df["vol"].mean()

        table = format_table(
            ["指标", "数值"],
            [
                ["最新收盘价", f"{latest_close:.2f}"],
                ["52周最高", f"{high_52w:.2f} ({high_date})"],
                ["52周最低", f"{low_52w:.2f} ({low_date})"],
                ["52周涨跌幅", f"{(latest_close / low_52w - 1) * 100:.1f}% (自低点)"],
                ["日均成交量 (手)", f"{avg_vol:,.0f}"],
            ],
            alignments=["l", "r"],
        )
        lines.append(table)
        return "\n".join(lines)

    def _get_market_data_hk(self, ts_code: str) -> str:
        """Section 2 (HK): Market data via yfinance (primary) or hk_daily fallback."""
        lines = [format_header(2, "2. 市场行情"), ""]

        # Primary: yfinance
        yf_data = self._yf_hk_market_data(ts_code)
        if yf_data and yf_data.get("close"):
            rows = [["最新价格 (HKD)", f"{yf_data['close']:.2f}"]]
            if yf_data.get("high_52w"):
                rows.append(["52周最高", f"{yf_data['high_52w']:.2f}"])
            if yf_data.get("low_52w"):
                rows.append(["52周最低", f"{yf_data['low_52w']:.2f}"])
            if yf_data.get("market_cap"):
                rows.append(["总市值", format_number(yf_data["market_cap"], divider=1e6)])
            if yf_data.get("volume_avg"):
                rows.append(["10日均量", f"{yf_data['volume_avg']:,.0f}"])
            table = format_table(["指标", "数值"], rows, alignments=["l", "r"])
            lines.append(table)
            return "\n".join(lines)

        # Fallback: hk_daily (requires broker permission)
        df = pd.DataFrame()
        try:
            today = pd.Timestamp.now().strftime("%Y%m%d")
            year_ago = (pd.Timestamp.now() - pd.DateOffset(years=1)).strftime("%Y%m%d")
            df = self._safe_call("hk_daily", ts_code=ts_code,
                                 start_date=year_ago, end_date=today,
                                 fields="ts_code,trade_date,open,high,low,close,vol,amount")
        except RuntimeError:
            pass

        if not df.empty:
            # Broker VIP relays may return rows oldest-first; enforce newest-first
            if "trade_date" in df.columns:
                df = df.sort_values("trade_date", ascending=False).reset_index(drop=True)
            latest_close = df.iloc[0]["close"]
            high_52w = df["high"].max()
            low_52w = df["low"].min()
            high_date = df.loc[df["high"].idxmax(), "trade_date"]
            low_date = df.loc[df["low"].idxmin(), "trade_date"]
            avg_vol = df["vol"].mean()

            lines.append("*来源: Tushare hk_daily*\n")
            table = format_table(
                ["指标", "数值"],
                [
                    ["最新收盘价 (HKD)", f"{latest_close:.2f}"],
                    ["52周最高", f"{high_52w:.2f} ({high_date})"],
                    ["52周最低", f"{low_52w:.2f} ({low_date})"],
                    ["52周涨跌幅", f"{(latest_close / low_52w - 1) * 100:.1f}% (自低点)"],
                    ["日均成交量 (股)", f"{avg_vol:,.0f}"],
                ],
                alignments=["l", "r"],
            )
            lines.append(table)
            return "\n".join(lines)

        lines.append("数据缺失\n")
        return "\n".join(lines)

    def _get_market_data_us(self, ts_code: str) -> str:
        """Section 2 (US): Market data via yfinance (52-week history)."""
        lines = [format_header(2, "2. 市场行情"), ""]

        # Use yfinance for 52-week history (avoids us_daily API limit)
        yf_data = self._yf_hk_market_data(ts_code)
        if yf_data and yf_data.get("close"):
            rows = [["最新价格 (USD)", f"{yf_data['close']:.2f}"]]
            if yf_data.get("high_52w"):
                rows.append(["52周最高", f"{yf_data['high_52w']:.2f}"])
            if yf_data.get("low_52w"):
                rows.append(["52周最低", f"{yf_data['low_52w']:.2f}"])
            if yf_data.get("market_cap"):
                rows.append(["总市值", format_number(yf_data["market_cap"], divider=1e6)])
            table = format_table(["指标", "数值"], rows, alignments=["l", "r"])
            lines.append(table)
            lines.append("\n*来源: yfinance*")
            return "\n".join(lines)

        lines.append("数据缺失\n")
        return "\n".join(lines)

    # --- Feature #16: Section 3 — Consolidated income statement ---

    def get_income(self, ts_code: str, report_type: str = "1") -> str:
        """Section 3: Five-year consolidated income statement."""
        if self._is_hk(ts_code):
            return self._get_income_hk(ts_code)
        if self._is_us(ts_code):
            return self._get_income_us(ts_code)

        df = self._cached_call("income", ts_code=ts_code,
                             report_type=report_type,
                             fields="ts_code,end_date,report_type,"
                                    "revenue,oper_cost,biz_tax_surchg,"
                                    "sell_exp,admin_exp,rd_exp,fin_exp,"
                                    "assets_impair_loss,credit_impa_loss,"
                                    "fv_value_chg_gain,invest_income,asset_disp_income,"
                                    "operate_profit,non_oper_income,non_oper_exp,"
                                    "total_profit,income_tax,"
                                    "n_income,n_income_attr_p,minority_gain,"
                                    "basic_eps,diluted_eps,dt_eps")
        # Map Tushare API field names → project internal names
        _INCOME_RENAME = {
            "biz_tax_surchg": "biz_tax_surch",
            "fin_exp": "finance_exp",
            "credit_impa_loss": "credit_impair_loss",
        }
        if not df.empty:
            df.rename(columns=_INCOME_RENAME, inplace=True)
        section_label = "3P. 母公司利润表" if report_type == "6" else "3. 合并利润表"
        lines = [format_header(2, section_label), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df, years = self._prepare_display_periods(df)

        # Store for derived metrics
        store_key = "income_parent" if report_type == "6" else "income"
        self._store[store_key] = df
        self._store[store_key + "_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        fields = [
            ("营业收入", "revenue"),
            ("营业成本", "oper_cost"),
            ("税金及附加", "biz_tax_surch"),
            ("销售费用", "sell_exp"),
            ("管理费用", "admin_exp"),
            ("研发费用", "rd_exp"),
            ("财务费用", "finance_exp"),
            ("资产减值损失", "assets_impair_loss"),
            ("信用减值损失", "credit_impair_loss"),
            ("公允价值变动收益", "fv_value_chg_gain"),
            ("投资收益", "invest_income"),
            ("资产处置收益", "asset_disp_income"),
            ("营业利润", "operate_profit"),
            ("营业外收入", "non_oper_income"),
            ("营业外支出", "non_oper_exp"),
            ("利润总额", "total_profit"),
            ("所得税费用", "income_tax"),
            ("净利润", "n_income"),
            ("归母净利润", "n_income_attr_p"),
            ("少数股东损益", "minority_gain"),
            ("基本EPS", "basic_eps"),
            ("稀释EPS", "diluted_eps"),
        ]

        if report_type == "6":
            _exclude = {"minority_gain", "basic_eps", "diluted_eps", "credit_impair_loss"}
            fields = [(label, col) for label, col in fields if col not in _exclude]

        headers = ["项目 (百万元)"] + years
        rows = []
        for label, col in fields:
            row = [label]
            for _, r in df.iterrows():
                val = r.get(col)
                if col in ("basic_eps", "diluted_eps", "dt_eps"):
                    row.append(f"{val:.2f}" if val is not None and val == val else "—")
                else:
                    row.append(format_number(val))
            rows.append(row)

        table = format_table(headers, rows,
                             alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")
        lines.append("*单位: 百万元 (原始数据 / 1,000,000), EPS为元/股*")
        return "\n".join(lines)

    def _get_income_hk(self, ts_code: str) -> str:
        """Section 3 (HK): Income statement via hk_income line-item pivot."""
        df = self._cached_call("hk_income", ts_code=ts_code,
                             fields="ts_code,end_date,ind_name,ind_value")
        lines = [format_header(2, "3. 合并利润表"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        pivoted = self._pivot_hk_line_items(df, HK_INCOME_MAP)
        if pivoted.empty:
            lines.append("数据缺失 (无法匹配行项目)\n")
            return "\n".join(lines)

        pivoted, yf_used = self._yf_fill_missing_hk(pivoted, ts_code, "income")

        pivoted, years = self._prepare_display_periods(pivoted)
        self._store["income"] = pivoted
        self._store["income_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        fields = [
            ("营业额", "revenue"),
            ("营运支出", "oper_cost"),
            ("销售及分销费用", "sell_exp"),
            ("行政开支", "admin_exp"),
            ("经营溢利", "operate_profit"),
            ("应占联营公司溢利", "invest_income"),
            ("融资成本", "finance_exp"),
            ("除税前溢利", "total_profit"),
            ("税项", "income_tax"),
            ("除税后溢利", "n_income"),
            ("股东应占溢利", "n_income_attr_p"),
            ("少数股东损益", "minority_gain"),
            ("每股基本盈利 (HKD)", "basic_eps"),
            ("每股摊薄盈利 (HKD)", "diluted_eps"),
        ]

        headers = ["项目 (百万港元)"] + years
        rows = []
        for label, col in fields:
            row = [label]
            for _, r in pivoted.iterrows():
                val = r.get(col)
                if col in ("basic_eps", "diluted_eps"):
                    row.append(f"{val:.2f}" if val is not None and val == val else "—")
                else:
                    row.append(format_number(val))
            rows.append(row)

        table = format_table(headers, rows, alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")
        lines.append("*单位: 百万港元 (原始数据 / 1,000,000), EPS为港元/股*")
        if yf_used:
            lines.append("\n*部分缺失数据由 yfinance 补充*")
        return "\n".join(lines)

    def _get_income_us(self, ts_code: str) -> str:
        """Section 3 (US): Income statement via us_income line-item pivot."""
        api_code = self._us_api_code(ts_code)
        df = self._cached_call("us_income", ts_code=api_code,
                             fields="ts_code,end_date,ind_name,ind_value")
        lines = [format_header(2, "3. 合并利润表"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        pivoted = self._pivot_hk_line_items(df, US_INCOME_MAP)
        if pivoted.empty:
            lines.append("数据缺失 (无法匹配行项目)\n")
            return "\n".join(lines)

        # Detect fiscal year end month BEFORE yfinance fill so fallback date
        # matching uses the correct month (e.g., 9 for AAPL, not default 12)
        if self._is_us(ts_code) and self._fy_end_month == 12:
            self._fy_end_month = self._detect_fy_end_month(pivoted)

        pivoted, yf_used = self._yf_fill_missing_hk(pivoted, ts_code, "income")

        pivoted, years = self._prepare_display_periods(pivoted)
        self._store["income"] = pivoted
        self._store["income_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        fields = [
            ("营业收入", "revenue"),
            ("营业成本", "oper_cost"),
            ("毛利", "gross_profit"),
            ("营销费用", "sell_exp"),
            ("研发费用", "rd_exp"),
            ("经营利润", "operate_profit"),
            ("净利润", "n_income"),
            ("归母净利润", "n_income_attr_p"),
            ("基本EPS (USD)", "basic_eps"),
            ("稀释EPS (USD)", "diluted_eps"),
        ]

        headers = ["项目 (百万美元)"] + years
        rows = []
        for label, col in fields:
            row = [label]
            for _, r in pivoted.iterrows():
                val = r.get(col)
                if col in ("basic_eps", "diluted_eps"):
                    row.append(f"{val:.2f}" if val is not None and val == val else "—")
                else:
                    row.append(format_number(val))
            rows.append(row)

        table = format_table(headers, rows, alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")
        lines.append("*单位: 百万美元 (原始数据 / 1,000,000), EPS为美元/股*")
        if yf_used:
            lines.append("\n*部分缺失数据由 yfinance 补充*")
        return "\n".join(lines)

    # --- Feature #17: Section 3P — Parent company income ---

    def get_income_parent(self, ts_code: str) -> str:
        """Section 3P: Five-year parent-company income statement."""
        if self._is_hk(ts_code):
            return format_header(2, "3P. 母公司利润表") + "\n\n数据缺失 (港股HKFRS不区分母/合并)\n"
        if self._is_us(ts_code):
            return format_header(2, "3P. 母公司利润表") + "\n\n数据缺失 (US GAAP不区分母/合并)\n"
        return self.get_income(ts_code, report_type="6")

    # --- Feature #18: Section 4 — Consolidated balance sheet ---

    def get_balance_sheet(self, ts_code: str, report_type: str = "1") -> str:
        """Section 4: Five-year consolidated balance sheet."""
        if self._is_hk(ts_code):
            return self._get_balance_sheet_hk(ts_code)
        if self._is_us(ts_code):
            return self._get_balance_sheet_us(ts_code)

        df = self._cached_call("balancesheet", ts_code=ts_code,
                             report_type=report_type,
                             fields="ts_code,end_date,report_type,"
                                    "money_cap,trad_asset,notes_receiv,"
                                    "accounts_receiv,oth_receiv,inventories,"
                                    "oth_cur_assets,total_cur_assets,"
                                    "lt_eqt_invest,fix_assets,cip,"
                                    "intang_assets,goodwill,total_assets,"
                                    "st_borr,notes_payable,acct_payable,"
                                    "contract_liab,adv_receipts,"
                                    "payroll_payable,taxes_payable,oth_payable,"
                                    "non_cur_liab_due_1y,oth_cur_liab,"
                                    "total_cur_liab,lt_borr,bond_payable,"
                                    "lt_payable,lease_liab,provisions,defer_inc_non_cur_liab,"
                                    "total_liab,defer_tax_assets,defer_tax_liab,"
                                    "total_hldr_eqy_exc_min_int,minority_int")
        section_label = "4P. 母公司资产负债表" if report_type == "6" else "4. 合并资产负债表"
        lines = [format_header(2, section_label), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df, years = self._prepare_display_periods(df)

        # Store for derived metrics
        store_key = "balance_sheet_parent" if report_type == "6" else "balance_sheet"
        self._store[store_key] = df
        self._store[store_key + "_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        fields = [
            ("货币资金", "money_cap"),
            ("交易性金融资产", "trad_asset"),
            ("应收票据", "notes_receiv"),
            ("应收账款", "accounts_receiv"),
            ("其他应收款", "oth_receiv"),
            ("存货", "inventories"),
            ("其他流动资产", "oth_cur_assets"),
            ("流动资产合计", "total_cur_assets"),
            ("长期股权投资", "lt_eqt_invest"),
            ("固定资产", "fix_assets"),
            ("在建工程", "cip"),
            ("无形资产", "intang_assets"),
            ("商誉", "goodwill"),
            ("总资产", "total_assets"),
            ("短期借款", "st_borr"),
            ("应付票据", "notes_payable"),
            ("应付账款", "acct_payable"),
            ("合同负债", "contract_liab"),
            ("预收款项", "adv_receipts"),
            ("应付职工薪酬", "payroll_payable"),
            ("应交税费", "taxes_payable"),
            ("其他应付款", "oth_payable"),
            ("一年内到期非流动负债", "non_cur_liab_due_1y"),
            ("其他流动负债", "oth_cur_liab"),
            ("流动负债合计", "total_cur_liab"),
            ("长期借款", "lt_borr"),
            ("应付债券", "bond_payable"),
            ("长期应付款", "lt_payable"),
            ("租赁负债", "lease_liab"),
            ("预计负债", "provisions"),
            ("递延收益", "defer_inc_non_cur_liab"),
            ("总负债", "total_liab"),
            ("递延所得税资产", "defer_tax_assets"),
            ("递延所得税负债", "defer_tax_liab"),
            ("归母所有者权益", "total_hldr_eqy_exc_min_int"),
            ("少数股东权益", "minority_int"),
        ]

        # Feature #81: For parent company, use subset of fields
        if report_type == "6":
            fields = [
                ("货币资金", "money_cap"),
                ("长期股权投资", "lt_eqt_invest"),
                ("总资产", "total_assets"),
                ("短期借款", "st_borr"),
                ("长期借款", "lt_borr"),
                ("应付债券", "bond_payable"),
                ("一年内到期非流动负债", "non_cur_liab_due_1y"),
                ("总负债", "total_liab"),
                ("归母权益", "total_hldr_eqy_exc_min_int"),
            ]

        headers = ["项目 (百万元)"] + years
        rows = []
        for label, col in fields:
            row = [label]
            for _, r in df.iterrows():
                row.append(format_number(r.get(col)))
            rows.append(row)

        table = format_table(headers, rows,
                             alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")
        lines.append("*单位: 百万元*")
        return "\n".join(lines)

    def _get_balance_sheet_hk(self, ts_code: str) -> str:
        """Section 4 (HK): Balance sheet via hk_balancesheet line-item pivot."""
        df = self._cached_call("hk_balancesheet", ts_code=ts_code,
                             fields="ts_code,end_date,ind_name,ind_value")
        lines = [format_header(2, "4. 合并资产负债表"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        pivoted = self._pivot_hk_line_items(df, HK_BALANCE_MAP)
        if pivoted.empty:
            lines.append("数据缺失 (无法匹配行项目)\n")
            return "\n".join(lines)

        pivoted, yf_used = self._yf_fill_missing_hk(pivoted, ts_code, "balance")

        pivoted, years = self._prepare_display_periods(pivoted)
        self._store["balance_sheet"] = pivoted
        self._store["balance_sheet_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        fields = [
            ("现金及等价物", "money_cap"),
            ("应收帐款", "accounts_receiv"),
            ("存货", "inventories"),
            ("流动资产合计", "total_cur_assets"),
            ("联营公司权益", "lt_eqt_invest"),
            ("物业厂房及设备", "fix_assets"),
            ("无形资产", "intang_assets"),
            ("总资产", "total_assets"),
            ("应付帐款", "acct_payable"),
            ("短期贷款", "st_borr"),
            ("流动负债合计", "total_cur_liab"),
            ("长期贷款", "lt_borr"),
            ("总负债", "total_liab"),
            ("递延税项资产", "defer_tax_assets"),
            ("递延税项负债", "defer_tax_liab"),
            ("股东权益", "total_hldr_eqy_exc_min_int"),
            ("少数股东权益", "minority_int"),
        ]

        headers = ["项目 (百万港元)"] + years
        rows = []
        for label, col in fields:
            row = [label]
            for _, r in pivoted.iterrows():
                row.append(format_number(r.get(col)))
            rows.append(row)

        table = format_table(headers, rows, alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")
        lines.append("*单位: 百万港元*")
        if yf_used:
            lines.append("\n*部分缺失数据由 yfinance 补充*")
        return "\n".join(lines)

    def _get_balance_sheet_us(self, ts_code: str) -> str:
        """Section 4 (US): Balance sheet via us_balancesheet line-item pivot."""
        api_code = self._us_api_code(ts_code)
        df = self._cached_call("us_balancesheet", ts_code=api_code,
                             fields="ts_code,end_date,ind_name,ind_value")
        lines = [format_header(2, "4. 合并资产负债表"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        pivoted = self._pivot_hk_line_items(df, US_BALANCE_MAP)
        if pivoted.empty:
            lines.append("数据缺失 (无法匹配行项目)\n")
            return "\n".join(lines)

        pivoted, yf_used = self._yf_fill_missing_hk(pivoted, ts_code, "balance")

        pivoted, years = self._prepare_display_periods(pivoted)
        self._store["balance_sheet"] = pivoted
        self._store["balance_sheet_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        fields = [
            ("现金及等价物", "money_cap"),
            ("应收帐款", "accounts_receiv"),
            ("存货", "inventories"),
            ("流动资产合计", "total_cur_assets"),
            ("固定资产", "fix_assets"),
            ("无形资产", "intang_assets"),
            ("总资产", "total_assets"),
            ("应付帐款", "acct_payable"),
            ("短期贷款", "st_borr"),
            ("流动负债合计", "total_cur_liab"),
            ("长期贷款", "lt_borr"),
            ("总负债", "total_liab"),
            ("递延税项资产", "defer_tax_assets"),
            ("递延税项负债", "defer_tax_liab"),
            ("股东权益", "total_hldr_eqy_exc_min_int"),
            ("少数股东权益", "minority_int"),
        ]

        headers = ["项目 (百万美元)"] + years
        rows = []
        for label, col in fields:
            row = [label]
            for _, r in pivoted.iterrows():
                row.append(format_number(r.get(col)))
            rows.append(row)

        table = format_table(headers, rows, alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")
        lines.append("*单位: 百万美元*")
        if yf_used:
            lines.append("\n*部分缺失数据由 yfinance 补充*")
        return "\n".join(lines)

    # --- Feature #19: Section 4P — Parent company balance sheet ---

    def get_balance_sheet_parent(self, ts_code: str) -> str:
        """Section 4P: Five-year parent-company balance sheet."""
        if self._is_hk(ts_code):
            return format_header(2, "4P. 母公司资产负债表") + "\n\n数据缺失 (港股HKFRS不区分母/合并)\n"
        if self._is_us(ts_code):
            return format_header(2, "4P. 母公司资产负债表") + "\n\n数据缺失 (US GAAP不区分母/合并)\n"
        return self.get_balance_sheet(ts_code, report_type="6")

    # --- Feature #20: Section 5 — Cash flow statement ---

    def get_cashflow(self, ts_code: str) -> str:
        """Section 5: Five-year cash flow statement with FCF calculation."""
        if self._is_hk(ts_code):
            return self._get_cashflow_hk(ts_code)
        if self._is_us(ts_code):
            return self._get_cashflow_us(ts_code)

        df = self._cached_call("cashflow", ts_code=ts_code,
                             report_type="1",
                             fields="ts_code,end_date,report_type,"
                                    "n_cashflow_act,n_cashflow_inv_act,"
                                    "n_cash_flows_fnc_act,c_pay_acq_const_fiolta,"
                                    "depr_fa_coga_dpba,amort_intang_assets,"
                                    "lt_amort_deferred_exp,"
                                    "c_pay_dist_dpcp_int_exp,"
                                    "c_pay_to_staff,c_paid_for_taxes,"
                                    "n_recp_disp_fiolta,receiv_tax_refund,"
                                    "c_recp_return_invest")
        lines = [format_header(2, "5. 现金流量表"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df, years = self._prepare_display_periods(df)

        # Store for derived metrics
        self._store["cashflow"] = df
        self._store["cashflow_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        headers = ["项目 (百万元)"] + years
        rows = []

        simple_fields = [
            ("经营活动现金流 (OCF)", "n_cashflow_act"),
            ("投资活动现金流", "n_cashflow_inv_act"),
            ("筹资活动现金流", "n_cash_flows_fnc_act"),
            ("资本支出(购建固定资产等)", "c_pay_acq_const_fiolta"),
            ("支付给职工现金", "c_pay_to_staff"),
            ("支付的各项税费", "c_paid_for_taxes"),
            ("处置固定资产收回现金", "n_recp_disp_fiolta"),
            ("收到税费返还", "receiv_tax_refund"),
            ("取得投资收益收到现金", "c_recp_return_invest"),
            ("分配股利偿付利息", "c_pay_dist_dpcp_int_exp"),
        ]
        for label, col in simple_fields:
            row = [label]
            for _, r in df.iterrows():
                row.append(format_number(r.get(col)))
            rows.append(row)

        # D&A = 固定资产折旧 + 无形资产摊销 + 长期待摊费用摊销
        da_row = ["折旧与摊销 (D&A)"]
        for _, r in df.iterrows():
            depr = r.get("depr_fa_coga_dpba")
            amort_intang = r.get("amort_intang_assets")
            amort_deferred = r.get("lt_amort_deferred_exp")
            vals = [v for v in [depr, amort_intang, amort_deferred]
                    if v is not None and v == v]
            if vals:
                da_row.append(format_number(sum(float(v) for v in vals)))
            else:
                da_row.append("—")
        rows.append(da_row)

        # FCF = OCF - |Capex| (values are in raw yuan, format_number divides by 1e6)
        fcf_row = ["自由现金流 (FCF)"]
        for _, r in df.iterrows():
            ocf = r.get("n_cashflow_act")
            capex = r.get("c_pay_acq_const_fiolta")
            if ocf is not None and capex is not None:
                fcf = float(ocf) - abs(float(capex))
                fcf_row.append(format_number(fcf))
            else:
                fcf_row.append("—")
        rows.append(fcf_row)

        table = format_table(headers, rows,
                             alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")
        lines.append("*单位: 百万元; FCF = OCF - |Capex|*")
        return "\n".join(lines)

    def _get_cashflow_hk(self, ts_code: str) -> str:
        """Section 5 (HK): Cash flow via hk_cashflow line-item pivot."""
        df = self._cached_call("hk_cashflow", ts_code=ts_code,
                             fields="ts_code,end_date,ind_name,ind_value")
        lines = [format_header(2, "5. 现金流量表"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        pivoted = self._pivot_hk_line_items(df, HK_CASHFLOW_MAP)
        if pivoted.empty:
            lines.append("数据缺失 (无法匹配行项目)\n")
            return "\n".join(lines)

        pivoted, yf_used = self._yf_fill_missing_hk(pivoted, ts_code, "cashflow")

        pivoted, years = self._prepare_display_periods(pivoted)
        self._store["cashflow"] = pivoted
        self._store["cashflow_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        headers = ["项目 (百万港元)"] + years
        rows = []

        simple_fields = [
            ("经营业务现金净额 (OCF)", "n_cashflow_act"),
            ("投资业务现金净额", "n_cashflow_inv_act"),
            ("融资业务现金净额", "n_cash_flows_fnc_act"),
            ("购建无形资产及其他资产", "c_pay_acq_const_fiolta"),
            ("已付税项", "c_paid_for_taxes"),
            ("收回投资所得现金", "c_recp_return_invest"),
            ("已付股息(融资)", "c_pay_dist_dpcp_int_exp"),
        ]
        for label, col in simple_fields:
            row = [label]
            for _, r in pivoted.iterrows():
                row.append(format_number(r.get(col)))
            rows.append(row)

        # D&A: single combined line for HK (no separate amort_intang_assets)
        da_row = ["折旧及摊销 (D&A)"]
        for _, r in pivoted.iterrows():
            da = r.get("depr_fa_coga_dpba")
            if da is not None and da == da:
                da_row.append(format_number(da))
            else:
                da_row.append("—")
        rows.append(da_row)

        # FCF = OCF - |Capex|
        fcf_row = ["自由现金流 (FCF)"]
        for _, r in pivoted.iterrows():
            ocf = r.get("n_cashflow_act")
            capex = r.get("c_pay_acq_const_fiolta")
            if ocf is not None and capex is not None:
                fcf = float(ocf) - abs(float(capex))
                fcf_row.append(format_number(fcf))
            else:
                fcf_row.append("—")
        rows.append(fcf_row)

        table = format_table(headers, rows, alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")
        lines.append("*单位: 百万港元; FCF = OCF - |Capex|; c_pay_to_staff 港股不可用*")
        if yf_used:
            lines.append("\n*部分缺失数据由 yfinance 补充*")
        return "\n".join(lines)

    def _get_cashflow_us(self, ts_code: str) -> str:
        """Section 5 (US): Cash flow via us_cashflow line-item pivot."""
        api_code = self._us_api_code(ts_code)
        df = self._cached_call("us_cashflow", ts_code=api_code,
                             fields="ts_code,end_date,ind_name,ind_value")
        lines = [format_header(2, "5. 现金流量表"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        pivoted = self._pivot_hk_line_items(df, US_CASHFLOW_MAP)
        if pivoted.empty:
            lines.append("数据缺失 (无法匹配行项目)\n")
            return "\n".join(lines)

        pivoted, yf_used = self._yf_fill_missing_hk(pivoted, ts_code, "cashflow")

        pivoted, years = self._prepare_display_periods(pivoted)
        self._store["cashflow"] = pivoted
        self._store["cashflow_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        headers = ["项目 (百万美元)"] + years
        rows = []

        simple_fields = [
            ("经营活动现金净额 (OCF)", "n_cashflow_act"),
            ("投资活动现金净额", "n_cashflow_inv_act"),
            ("筹资活动现金净额", "n_cash_flows_fnc_act"),
            ("资本支出", "c_pay_acq_const_fiolta"),
            ("已付股息", "c_pay_dist_dpcp_int_exp"),
        ]
        for label, col in simple_fields:
            row = [label]
            for _, r in pivoted.iterrows():
                row.append(format_number(r.get(col)))
            rows.append(row)

        # D&A: single combined line
        da_row = ["折旧及摊销 (D&A)"]
        for _, r in pivoted.iterrows():
            da = r.get("depr_fa_coga_dpba")
            if da is not None and da == da:
                da_row.append(format_number(da))
            else:
                da_row.append("—")
        rows.append(da_row)

        # FCF = OCF - |Capex|
        fcf_row = ["自由现金流 (FCF)"]
        for _, r in pivoted.iterrows():
            ocf = r.get("n_cashflow_act")
            capex = r.get("c_pay_acq_const_fiolta")
            if ocf is not None and capex is not None:
                fcf = float(ocf) - abs(float(capex))
                fcf_row.append(format_number(fcf))
            else:
                fcf_row.append("—")
        rows.append(fcf_row)

        table = format_table(headers, rows, alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        lines.append("")
        lines.append("*单位: 百万美元; FCF = OCF - |Capex|; c_pay_to_staff 美股不可用*")
        if yf_used:
            lines.append("\n*部分缺失数据由 yfinance 补充*")
        return "\n".join(lines)

    # --- Feature #21: Section 6 — Dividend history ---

    def get_dividends(self, ts_code: str) -> str:
        """Section 6: Dividend history."""
        if self._is_hk(ts_code):
            return self._get_dividends_hk(ts_code)
        if self._is_us(ts_code):
            return self._get_dividends_us(ts_code)

        df = self._cached_call("dividend", ts_code=ts_code,
                             fields="ts_code,end_date,ann_date,div_proc,"
                                    "stk_div,cash_div_tax,record_date,"
                                    "ex_date,base_share")
        lines = [format_header(2, "6. 分红历史"), ""]

        if df.empty:
            lines.append("暂无分红数据\n")
            return "\n".join(lines)

        # Filter for completed dividends
        df = df[df["div_proc"] == "实施"].copy()
        df = df.drop_duplicates(subset=["end_date"])
        df = df.sort_values("end_date", ascending=False)
        # Limit by year count (not row count) — a company may pay multiple dividends per year
        df["_year"] = df["end_date"].astype(str).str[:4]
        top_years = df["_year"].drop_duplicates().head(5).tolist()
        df = df[df["_year"].isin(top_years)].drop(columns=["_year"])

        # Store for derived metrics
        self._store["dividends"] = df

        if df.empty:
            lines.append("暂无已实施分红\n")
            return "\n".join(lines)

        headers = ["年度", "每股现金分红(税前)", "每股送股", "登记日", "除权日", "总分红 (百万元)"]
        rows = []
        for _, r in df.iterrows():
            year = str(r.get("end_date", ""))[:4]
            cash_div = r.get("cash_div_tax", 0) or 0
            stk_div = r.get("stk_div", 0) or 0
            base_share = r.get("base_share", 0) or 0
            total_div = cash_div * base_share * 10000  # base_share is 万股, convert to shares
            rows.append([
                year,
                f"{cash_div:.4f}",
                f"{stk_div:.2f}" if stk_div else "—",
                str(r.get("record_date", "—")),
                str(r.get("ex_date", "—")),
                format_number(total_div),
            ])

        table = format_table(headers, rows,
                             alignments=["l", "r", "r", "l", "l", "r"])
        lines.append(table)
        return "\n".join(lines)

    def _get_yf_annual_dividends(self, ts_code: str) -> dict[str, float] | None:
        """Fetch annual DPS from yfinance, grouped by fiscal year. Returns {year: total_dps} or None."""
        if not self._yf_available:
            return None
        try:
            ticker = _yf().Ticker(self._yf_ticker(ts_code))
            divs = ticker.dividends
            if divs is None or divs.empty:
                return None
            divs_df = divs.reset_index()
            divs_df.columns = ["date", "dividend"]
            # Map to fiscal year: interim (Jul-Dec) → current FY, final (Jan-Jun) → previous FY
            dates = pd.to_datetime(divs_df["date"])
            divs_df["fy"] = dates.apply(lambda d: d.year if d.month >= 7 else d.year - 1)
            annual = divs_df.groupby("fy")["dividend"].sum()
            return {str(int(y)): v for y, v in annual.items() if v > 0}
        except Exception:
            return None

    def _get_dividends_hk(self, ts_code: str) -> str:
        """Section 6 (HK): Dividend history from hk_fina_indicator + yfinance cross-validation."""
        lines = [format_header(2, "6. 分红历史"), ""]
        try:
            df = self._cached_call("hk_fina_indicator", ts_code=ts_code,
                                 fields="ts_code,end_date,dps_hkd,divi_ratio")
        except RuntimeError:
            lines.append("数据缺失 (接口可能无权限)\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("暂无分红数据\n")
            return "\n".join(lines)

        df = df.drop_duplicates(subset=["end_date"])
        df = df.sort_values("end_date", ascending=False)
        df["_year"] = df["end_date"].astype(str).str[:4]
        top_years = df["_year"].drop_duplicates().head(5).tolist()
        df = df[df["_year"].isin(top_years)].drop(columns=["_year"])

        # --- yfinance cross-validation for stuck DPS bug ---
        # Detect suspicious pattern: all dps_hkd values identical
        dps_values = [self._safe_float(r.get("dps_hkd")) for _, r in df.iterrows()
                      if self._safe_float(r.get("dps_hkd")) is not None and self._safe_float(r.get("dps_hkd")) > 0]
        dps_looks_stuck = (len(dps_values) >= 3
                           and len(set(round(v, 4) for v in dps_values)) == 1)

        yf_annual: dict[str, float] | None = None
        dps_source = "tushare"
        if dps_looks_stuck:
            yf_annual = self._get_yf_annual_dividends(ts_code)
            if yf_annual:
                # Only keep annual (Dec) rows from df, overwrite dps_hkd with yfinance
                df = df[df["end_date"].astype(str).str[4:8] == "1231"].copy()
                for idx, r in df.iterrows():
                    year = str(r["end_date"])[:4]
                    if year in yf_annual:
                        df.at[idx, "dps_hkd"] = yf_annual[year]
                dps_source = "yfinance"
                self._store["_dividend_warning"] = (
                    f"Tushare dps_hkd 疑似数据填充错误（所有期间值相同={dps_values[0]:.4f}），"
                    f"已使用 yfinance 股息数据替代"
                )

        # Store for derived metrics
        self._store["dividends_hk"] = df

        # Build a compatible dividends store for downstream (§17)
        div_records = []
        for _, r in df.iterrows():
            dps = self._safe_float(r.get("dps_hkd"))
            if dps is not None and dps > 0:
                div_records.append({
                    "end_date": r.get("end_date"),
                    "cash_div_tax": dps,
                    "base_share": 1,  # DPS is per-share already
                    "div_proc": "实施",
                })
        if div_records:
            self._store["dividends"] = pd.DataFrame(div_records)

        # Build EPS lookup for cross-validation
        income_df = self._get_annual_df("income")
        eps_lookup: dict[str, float] = {}
        if not income_df.empty and "basic_eps" in income_df.columns:
            for _, r2 in income_df.iterrows():
                y = str(r2["end_date"])[:4]
                eps = self._safe_float(r2.get("basic_eps"))
                if eps and eps > 0:
                    eps_lookup[y] = eps

        headers = ["年度", "每股股息 (HKD)", "派息率 (%)"]
        rows = []
        for _, r in df.iterrows():
            year = str(r.get("end_date", ""))[:4]
            dps = r.get("dps_hkd")
            ts_ratio = self._safe_float(r.get("divi_ratio"))
            dps_f = self._safe_float(dps)
            eps = eps_lookup.get(year)
            payout = self._resolve_hk_payout(ts_ratio, dps_f, eps)
            rows.append([
                year,
                f"{dps:.4f}" if dps is not None and dps == dps else "—",
                f"{payout:.2f}" if payout is not None else "—",
            ])

        table = format_table(headers, rows, alignments=["l", "r", "r"])
        lines.append(table)
        if dps_source == "yfinance":
            lines.append(f"\n*⚠️ DPS 数据来源: yfinance（Tushare dps_hkd 数据异常已替换）*")
        return "\n".join(lines)

    def _get_dividends_us(self, ts_code: str) -> str:
        """Section 6 (US): Dividend history from yfinance."""
        lines = [format_header(2, "6. 分红历史"), ""]
        if not self._yf_available:
            lines.append("数据缺失 (yfinance不可用)\n")
            return "\n".join(lines)

        try:
            ticker = _yf().Ticker(self._yf_ticker(ts_code))
            divs = ticker.dividends
        except Exception:
            lines.append("数据缺失 (yfinance获取失败)\n")
            return "\n".join(lines)

        if divs is None or divs.empty:
            lines.append("暂无分红数据\n")
            return "\n".join(lines)

        # Group by year, sum annual dividends
        divs_df = divs.reset_index()
        divs_df.columns = ["date", "dividend"]
        divs_df["year"] = pd.to_datetime(divs_df["date"]).dt.year
        annual = divs_df.groupby("year")["dividend"].sum().reset_index()
        annual = annual.sort_values("year", ascending=False).head(5)

        # Build compatible dividend store for downstream
        div_records = []
        for _, r in annual.iterrows():
            div_records.append({
                "end_date": f"{int(r['year'])}1231",
                "cash_div_tax": r["dividend"],
                "base_share": 1,
                "div_proc": "实施",
            })
        if div_records:
            self._store["dividends"] = pd.DataFrame(div_records)

        headers = ["年度", "每股股息 (USD)"]
        rows = [[str(int(r["year"])), f"{r['dividend']:.4f}"] for _, r in annual.iterrows()]
        table = format_table(headers, rows, alignments=["l", "r"])
        lines.append(table)
        lines.append("\n*数据来源: yfinance*")
        return "\n".join(lines)

    # --- Feature #22: Section 11 + Appendix A — 10-year weekly prices ---

    def get_weekly_prices(self, ts_code: str) -> str:
        """Section 11 + Appendix A: 10-year weekly price history."""
        if self._is_hk(ts_code):
            return self._get_weekly_prices_hk(ts_code)
        if self._is_us(ts_code):
            return self._get_weekly_prices_us(ts_code)

        today = pd.Timestamp.now().strftime("%Y%m%d")
        ten_years_ago = (pd.Timestamp.now() - pd.DateOffset(years=10)).strftime("%Y%m%d")

        df = self._cached_call("weekly", ts_code=ts_code,
                             start_date=ten_years_ago, end_date=today,
                             fields="ts_code,trade_date,open,high,low,close,vol,amount")
        lines = [format_header(2, "11. 十年周线行情"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df = df.sort_values("trade_date", ascending=True)

        # Store for derived metrics
        self._store["weekly_prices"] = df

        # 10-year summary
        high_10y = df["high"].max()
        low_10y = df["low"].min()
        high_date = df.loc[df["high"].idxmax(), "trade_date"]
        low_date = df.loc[df["low"].idxmin(), "trade_date"]
        latest_close = df.iloc[-1]["close"]

        summary_table = format_table(
            ["指标", "数值"],
            [
                ["10年最高", f"{high_10y:.2f} ({high_date})"],
                ["10年最低", f"{low_10y:.2f} ({low_date})"],
                ["最新收盘", f"{latest_close:.2f}"],
                ["距最高回撤", f"{(1 - latest_close / high_10y) * 100:.1f}%"],
                ["距最低涨幅", f"{(latest_close / low_10y - 1) * 100:.1f}%"],
            ],
            alignments=["l", "r"],
        )
        lines.append(summary_table)
        lines.append("")

        # Annual summary
        df["year"] = df["trade_date"].str[:4]
        annual = df.groupby("year").agg(
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            avg_vol=("vol", "mean"),
        ).reset_index()
        annual = annual.sort_values("year", ascending=False)

        lines.append(format_header(3, "年度行情汇总"))
        lines.append("")
        annual_table = format_table(
            ["年度", "最高", "最低", "年末收盘", "周均成交量(手)"],
            [[
                r["year"],
                f"{r['high']:.2f}",
                f"{r['low']:.2f}",
                f"{r['close']:.2f}",
                f"{r['avg_vol']:,.0f}",
            ] for _, r in annual.iterrows()],
            alignments=["l", "r", "r", "r", "r"],
        )
        lines.append(annual_table)
        return "\n".join(lines)

    def _get_weekly_prices_hk(self, ts_code: str) -> str:
        """Section 11 (HK): Weekly prices via yfinance (primary) or hk_daily fallback."""
        lines = [format_header(2, "11. 十年周线行情"), ""]

        # Primary: yfinance
        df = self._yf_weekly_history(ts_code)

        # Fallback: hk_daily → resample to weekly
        if df.empty:
            try:
                today = pd.Timestamp.now().strftime("%Y%m%d")
                ten_years_ago = (pd.Timestamp.now() - pd.DateOffset(years=10)).strftime("%Y%m%d")
                daily = self._safe_call("hk_daily", ts_code=ts_code,
                                        start_date=ten_years_ago, end_date=today,
                                        fields="ts_code,trade_date,open,high,low,close,vol,amount")
                if not daily.empty:
                    daily["trade_date"] = pd.to_datetime(daily["trade_date"])
                    daily = daily.sort_values("trade_date")
                    weekly = daily.resample("W-FRI", on="trade_date").agg({
                        "open": "first", "high": "max", "low": "min",
                        "close": "last", "vol": "sum",
                    }).dropna(subset=["close"])
                    weekly = weekly.reset_index()
                    weekly["trade_date"] = weekly["trade_date"].dt.strftime("%Y%m%d")
                    weekly["ts_code"] = ts_code
                    df = weekly
                    if not df.empty:
                        lines.append("*来源: Tushare hk_daily*\n")
            except RuntimeError:
                pass

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df = df.sort_values("trade_date", ascending=True)
        self._store["weekly_prices"] = df

        # 10-year summary (same logic as A-share)
        high_10y = df["high"].max()
        low_10y = df["low"].min()
        high_date = df.loc[df["high"].idxmax(), "trade_date"]
        low_date = df.loc[df["low"].idxmin(), "trade_date"]
        latest_close = df.iloc[-1]["close"]

        summary_table = format_table(
            ["指标", "数值"],
            [
                ["10年最高 (HKD)", f"{high_10y:.2f} ({high_date})"],
                ["10年最低 (HKD)", f"{low_10y:.2f} ({low_date})"],
                ["最新收盘 (HKD)", f"{latest_close:.2f}"],
                ["距最高回撤", f"{(1 - latest_close / high_10y) * 100:.1f}%"],
                ["距最低涨幅", f"{(latest_close / low_10y - 1) * 100:.1f}%"],
            ],
            alignments=["l", "r"],
        )
        lines.append(summary_table)
        lines.append("")

        # Annual summary
        df["year"] = df["trade_date"].str[:4]
        annual = df.groupby("year").agg(
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            avg_vol=("vol", "mean"),
        ).reset_index()
        annual = annual.sort_values("year", ascending=False)

        lines.append(format_header(3, "年度行情汇总"))
        lines.append("")
        annual_table = format_table(
            ["年度", "最高", "最低", "年末收盘", "周均成交量"],
            [[
                r["year"],
                f"{r['high']:.2f}",
                f"{r['low']:.2f}",
                f"{r['close']:.2f}",
                f"{r['avg_vol']:,.0f}",
            ] for _, r in annual.iterrows()],
            alignments=["l", "r", "r", "r", "r"],
        )
        lines.append(annual_table)
        return "\n".join(lines)

    def _get_weekly_prices_us(self, ts_code: str) -> str:
        """Section 11 (US): Weekly prices via yfinance."""
        lines = [format_header(2, "11. 十年周线行情"), ""]

        df = self._yf_weekly_history(ts_code)

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df = df.sort_values("trade_date", ascending=True)
        self._store["weekly_prices"] = df

        high_10y = df["high"].max()
        low_10y = df["low"].min()
        high_date = df.loc[df["high"].idxmax(), "trade_date"]
        low_date = df.loc[df["low"].idxmin(), "trade_date"]
        latest_close = df.iloc[-1]["close"]

        summary_table = format_table(
            ["指标", "数值"],
            [
                ["10年最高 (USD)", f"{high_10y:.2f} ({high_date})"],
                ["10年最低 (USD)", f"{low_10y:.2f} ({low_date})"],
                ["最新收盘 (USD)", f"{latest_close:.2f}"],
                ["距最高回撤", f"{(1 - latest_close / high_10y) * 100:.1f}%"],
                ["距最低涨幅", f"{(latest_close / low_10y - 1) * 100:.1f}%"],
            ],
            alignments=["l", "r"],
        )
        lines.append(summary_table)
        lines.append("")

        df["year"] = df["trade_date"].str[:4]
        annual = df.groupby("year").agg(
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            avg_vol=("vol", "mean"),
        ).reset_index()
        annual = annual.sort_values("year", ascending=False)

        lines.append(format_header(3, "年度行情汇总"))
        lines.append("")
        annual_table = format_table(
            ["年度", "最高", "最低", "年末收盘", "周均成交量"],
            [[
                r["year"],
                f"{r['high']:.2f}",
                f"{r['low']:.2f}",
                f"{r['close']:.2f}",
                f"{r['avg_vol']:,.0f}",
            ] for _, r in annual.iterrows()],
            alignments=["l", "r", "r", "r", "r"],
        )
        lines.append(annual_table)
        return "\n".join(lines)

    # --- Feature #23: Section 12 — Financial indicators ---

    def get_fina_indicators(self, ts_code: str) -> str:
        """Section 12: Key financial indicators from fina_indicator/hk_fina_indicator/us_fina_indicator."""
        if self._is_hk(ts_code):
            return self._get_fina_indicators_hk(ts_code)
        if self._is_us(ts_code):
            return self._get_fina_indicators_us(ts_code)

        df = self._cached_call("fina_indicator", ts_code=ts_code,
                             fields="ts_code,end_date,roe,roe_waa,"
                                    "grossprofit_margin,netprofit_margin,"
                                    "rd_exp,current_ratio,quick_ratio,"
                                    "assets_turn,debt_to_assets,"
                                    "revenue_yoy,netprofit_yoy,"
                                    "ocfps,bps,profit_dedt,"
                                    "ebitda,fcff,netdebt,interestdebt")
        lines = [format_header(2, "12. 关键财务指标"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df, years = self._prepare_display_periods(df)

        # Store for derived metrics
        self._store["fina_indicators"] = df
        self._store["fina_indicators_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        pct_fields = [
            ("ROE (%)", "roe"),
            ("加权ROE (%)", "roe_waa"),
            ("毛利率 (%)", "grossprofit_margin"),
            ("净利率 (%)", "netprofit_margin"),
            ("资产负债率 (%)", "debt_to_assets"),
        ]
        ratio_fields = [
            ("流动比率", "current_ratio"),
            ("速动比率", "quick_ratio"),
            ("总资产周转率", "assets_turn"),
        ]
        growth_fields = [
            ("营收同比增长率 (%)", "revenue_yoy"),
            ("净利润同比增长率 (%)", "netprofit_yoy"),
        ]
        per_share_fields = [
            ("每股经营现金流", "ocfps"),
            ("每股净资产", "bps"),
        ]

        headers = ["指标"] + years
        rows = []
        for label, col in pct_fields:
            row = [label]
            for _, r in df.iterrows():
                val = r.get(col)
                row.append(f"{val:.2f}" if val is not None and val == val else "—")
            rows.append(row)
        for label, col in ratio_fields:
            row = [label]
            for _, r in df.iterrows():
                val = r.get(col)
                row.append(f"{val:.2f}" if val is not None and val == val else "—")
            rows.append(row)
        for label, col in growth_fields:
            row = [label]
            for _, r in df.iterrows():
                val = r.get(col)
                row.append(f"{val:.2f}" if val is not None and val == val else "—")
            rows.append(row)
        for label, col in per_share_fields:
            row = [label]
            for _, r in df.iterrows():
                val = r.get(col)
                row.append(f"{val:.2f}" if val is not None and val == val else "—")
            rows.append(row)
        # Quality: 扣非净利润 (in millions)
        profit_dedt_row = ["扣非净利润 (百万元)"]
        for _, r in df.iterrows():
            val = r.get("profit_dedt")
            profit_dedt_row.append(format_number(val))
        rows.append(profit_dedt_row)

        table = format_table(headers, rows,
                             alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        return "\n".join(lines)

    def _get_fina_indicators_hk(self, ts_code: str) -> str:
        """Section 12 (HK): Financial indicators from hk_fina_indicator (structured)."""
        df = self._cached_call("hk_fina_indicator", ts_code=ts_code,
                             fields="ts_code,end_date,roe_avg,gross_profit_ratio,"
                                    "net_profit_ratio,debt_asset_ratio,"
                                    "pe_ttm,pb_ttm,operate_income_yoy,holder_profit_yoy,"
                                    "bps,total_market_cap,hksk_market_cap")
        lines = [format_header(2, "12. 关键财务指标"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df, years = self._prepare_display_periods(df)
        self._store["fina_indicators"] = df
        self._store["fina_indicators_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        pct_fields = [
            ("ROE (%)", "roe_avg"),
            ("毛利率 (%)", "gross_profit_ratio"),
            ("净利率 (%)", "net_profit_ratio"),
            ("资产负债率 (%)", "debt_asset_ratio"),
        ]
        growth_fields = [
            ("营收同比增长率 (%)", "operate_income_yoy"),
            ("净利润同比增长率 (%)", "holder_profit_yoy"),
        ]
        per_share_fields = [
            ("每股净资产 (HKD)", "bps"),
            ("PE (TTM)", "pe_ttm"),
            ("PB", "pb_ttm"),
        ]

        headers = ["指标"] + years
        rows = []
        for label, col in pct_fields + growth_fields + per_share_fields:
            row = [label]
            for _, r in df.iterrows():
                val = r.get(col)
                row.append(f"{val:.2f}" if val is not None and val == val else "—")
            rows.append(row)

        table = format_table(headers, rows, alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        return "\n".join(lines)

    def _get_fina_indicators_us(self, ts_code: str) -> str:
        """Section 12 (US): Financial indicators from us_fina_indicator (structured)."""
        api_code = self._us_api_code(ts_code)
        df = self._cached_call("us_fina_indicator", ts_code=api_code,
                             fields="ts_code,end_date,roe_avg,gross_profit_ratio,"
                                    "net_profit_ratio,debt_asset_ratio,"
                                    "pe_ttm,pb_ttm,operate_income_yoy,holder_profit_yoy,"
                                    "bps,total_market_cap")
        lines = [format_header(2, "12. 关键财务指标"), ""]

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        # Compute missing fields from stored data before display
        if not df.empty:
            for idx, row in df.iterrows():
                end_date = str(row.get("end_date", ""))
                # bps: equity / shares
                if pd.isna(row.get("bps")):
                    bs = self._store.get("balance_sheet")
                    if bs is not None and not bs.empty:
                        eq_row = bs[bs["end_date"] == end_date]
                        if not eq_row.empty:
                            equity = self._safe_float(eq_row.iloc[0].get("total_hldr_eqy_exc_min_int"))
                            bi = self._store.get("basic_info")
                            if equity and bi is not None and not bi.empty:
                                close_price = self._safe_float(bi.iloc[0].get("close"))
                                tmv = self._safe_float(bi.iloc[0].get("total_mv"))
                                if close_price and tmv and close_price > 0:
                                    shares = tmv / close_price
                                    if shares > 0:
                                        df.at[idx, "bps"] = equity / shares

                # holder_profit_yoy: YoY net income growth
                if pd.isna(row.get("holder_profit_yoy")):
                    inc = self._store.get("income")
                    if inc is not None and not inc.empty:
                        curr = inc[inc["end_date"] == end_date]
                        year = int(end_date[:4])
                        prior_dates = inc[inc["end_date"].str[:4] == str(year - 1)]
                        if not curr.empty and not prior_dates.empty:
                            curr_np = self._safe_float(curr.iloc[0].get("n_income"))
                            prior_np = self._safe_float(prior_dates.iloc[0].get("n_income"))
                            if curr_np is not None and prior_np and prior_np != 0:
                                df.at[idx, "holder_profit_yoy"] = (curr_np - prior_np) / abs(prior_np) * 100

                # pe_ttm / pb_ttm: from us_daily (latest period only)
                if pd.isna(row.get("pe_ttm")) or pd.isna(row.get("pb_ttm")):
                    bi = self._store.get("basic_info")
                    if bi is not None and not bi.empty:
                        d = bi.iloc[0]
                        if pd.isna(row.get("pe_ttm")):
                            df.at[idx, "pe_ttm"] = self._safe_float(d.get("pe"))
                        if pd.isna(row.get("pb_ttm")):
                            df.at[idx, "pb_ttm"] = self._safe_float(d.get("pb"))

        df, years = self._prepare_display_periods(df)
        self._store["fina_indicators"] = df
        self._store["fina_indicators_years"] = years

        if not years:
            lines.append("无年报数据\n")
            return "\n".join(lines)

        pct_fields = [
            ("ROE (%)", "roe_avg"),
            ("毛利率 (%)", "gross_profit_ratio"),
            ("净利率 (%)", "net_profit_ratio"),
            ("资产负债率 (%)", "debt_asset_ratio"),
        ]
        growth_fields = [
            ("营收同比增长率 (%)", "operate_income_yoy"),
            ("净利润同比增长率 (%)", "holder_profit_yoy"),
        ]
        per_share_fields = [
            ("每股净资产 (USD)", "bps"),
            ("PE (TTM)", "pe_ttm"),
            ("PB", "pb_ttm"),
        ]

        headers = ["指标"] + years
        rows = []
        for label, col in pct_fields + growth_fields + per_share_fields:
            row = [label]
            for _, r in df.iterrows():
                val = r.get(col)
                row.append(f"{val:.2f}" if val is not None and val == val else "—")
            rows.append(row)

        table = format_table(headers, rows, alignments=["l"] + ["r"] * len(years))
        lines.append(table)
        return "\n".join(lines)

    # --- Feature #24: Section 9 — Business segments ---

