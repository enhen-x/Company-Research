"""Turtle Investment Framework - OtherDataMixin.

Data methods: segments, holders, audit, risk-free rate, repurchase, pledge.
"""

import sys

import pandas as pd

from format_utils import format_number, format_table, format_header


def _yf():
    """Access yfinance module via tushare_collector for @patch compatibility."""
    return sys.modules["tushare_collector"].yf


def _now() -> pd.Timestamp:
    """Current time — module-level so tests can freeze it (time-window filters)."""
    return pd.Timestamp.now()


class OtherDataMixin:
    """Mixin providing other data methods for TushareClient."""

    def get_segments(self, ts_code: str) -> str:
        """Section 9: Business segment data from fina_mainbz."""
        if self._is_hk(ts_code):
            return format_header(2, "9. 主营业务构成") + "\n\n数据缺失 (港股暂不支持)\n"
        if self._is_us(ts_code):
            return format_header(2, "9. 主营业务构成") + "\n\n数据缺失 (美股暂不支持)\n"

        lines = [format_header(2, "9. 主营业务构成"), ""]
        try:
            df = self._cached_call("fina_mainbz", ts_code=ts_code, type="P",
                                 fields="ts_code,end_date,bz_item,bz_sales,bz_profit,bz_cost")
        except RuntimeError:
            lines.append("数据缺失 (接口可能无权限)\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        # Get latest period
        if "end_date" in df.columns:
            latest_period = df["end_date"].max()
            df = df[df["end_date"] == latest_period]

        headers = ["业务名称", "营业收入 (百万元)", "营业利润 (百万元)", "毛利率 (%)"]
        rows = []
        for _, r in df.iterrows():
            name = r.get("bz_item", "—")
            rev = r.get("bz_sales", None)
            profit = r.get("bz_profit", None)
            margin = r.get("bz_cost", None)
            # Compute gross margin if both revenue and cost available
            gm = "—"
            if rev and margin:
                try:
                    gm = f"{(1 - float(margin)/float(rev)) * 100:.1f}"
                except (ValueError, ZeroDivisionError):
                    gm = "—"
            rows.append([
                str(name),
                format_number(rev),
                format_number(profit),
                gm,
            ])

        table = format_table(headers, rows,
                             alignments=["l", "r", "r", "r"])
        lines.append(table)
        return "\n".join(lines)

    # --- Feature #25: Section 7 (partial) — Top 10 holders + audit ---

    def get_holders(self, ts_code: str) -> str:
        """Section 7 (partial): Top 10 shareholders."""
        if self._is_hk(ts_code):
            return self._get_holders_hk(ts_code)
        if self._is_us(ts_code):
            return self._get_holders_hk(ts_code)  # reuse yfinance-based HK logic

        lines = [format_header(2, "7. 股东与治理 (部分)"), ""]

        try:
            df = self._cached_call("top10_holders", ts_code=ts_code)
        except RuntimeError:
            lines.append("股东数据缺失\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("股东数据缺失\n")
            return "\n".join(lines)

        # Get latest period
        if "end_date" in df.columns:
            latest = df["end_date"].max()
            df = df[df["end_date"] == latest]

        lines.append(f"*截至 {latest}*\n" if "end_date" in df.columns else "")

        headers = ["序号", "股东名称", "持股数量 (万股)", "持股比例 (%)"]
        rows = []
        for i, (_, r) in enumerate(df.head(10).iterrows(), 1):
            rows.append([
                str(i),
                str(r.get("holder_name", "—")),
                format_number(r.get("hold_amount", None), divider=1e4, decimals=2),
                f"{r.get('hold_ratio', 0) or 0:.2f}",
            ])

        table = format_table(headers, rows,
                             alignments=["l", "l", "r", "r"])
        lines.append(table)
        return "\n".join(lines)

    def _get_holders_hk(self, ts_code: str) -> str:
        """Section 7 (HK): Institutional holders via yfinance."""
        lines = [format_header(2, "7. 股东与治理 (部分)"), ""]

        if not self._yf_available:
            lines.append("数据缺失 (yfinance不可用)")
            lines.append("")
            lines.append("*[§7 待Agent WebSearch补充]*")
            return "\n".join(lines)

        try:
            ticker = _yf().Ticker(self._yf_ticker(ts_code))
            major = ticker.major_holders
            inst = ticker.institutional_holders
        except Exception:
            lines.append("数据缺失 (yfinance不可用)")
            lines.append("")
            lines.append("*[§7 待Agent WebSearch补充]*")
            return "\n".join(lines)

        # Major holders summary
        if major is not None and not major.empty:
            lines.append("**持股概况**\n")
            mh_headers = ["项目", "数值"]
            mh_rows = []
            for _, r in major.iterrows():
                vals = list(r)
                if len(vals) >= 2:
                    mh_rows.append([str(vals[1]), str(vals[0])])
            if mh_rows:
                lines.append(format_table(mh_headers, mh_rows, alignments=["l", "r"]))
                lines.append("")

        # Institutional holders
        if inst is not None and not inst.empty:
            lines.append("**主要机构持股**\n")
            ih_headers = ["机构名称", "持股数量", "占比 (%)", "报告日期"]
            ih_rows = []
            for _, r in inst.head(10).iterrows():
                name = str(r.get("Holder", "—"))
                shares = r.get("Shares")
                pct = r.get("pctHeld") or r.get("% Out")
                date_val = r.get("Date Reported")
                shares_str = format_number(shares, divider=1e4, decimals=2) if shares is not None else "—"
                pct_str = f"{float(pct) * 100:.2f}" if pct is not None and pct == pct else "—"
                date_str = str(date_val)[:10] if date_val is not None else "—"
                ih_rows.append([name, shares_str, pct_str, date_str])
            lines.append(format_table(ih_headers, ih_rows, alignments=["l", "r", "r", "l"]))
            lines.append("")

        if (major is None or major.empty) and (inst is None or inst.empty):
            lines.append("数据缺失 (yfinance无持股数据)")
            lines.append("")
            lines.append("*[§7 待Agent WebSearch补充]*")
            return "\n".join(lines)

        lines.append("*数据来源: yfinance*")
        lines.append("")
        lines.append("*[§7 待Agent WebSearch补充: 控股股东、管理层变更、违规记录等定性信息]*")
        return "\n".join(lines)

    def get_audit(self, ts_code: str) -> str:
        """Audit opinion info."""
        if self._is_hk(ts_code):
            return format_header(3, "审计意见") + "\n\n数据缺失 (港股暂不支持)\n"
        if self._is_us(ts_code):
            return format_header(3, "审计意见") + "\n\n数据缺失 (美股暂不支持)\n"

        lines = [format_header(3, "审计意见"), ""]
        try:
            df = self._cached_call("fina_audit", ts_code=ts_code,
                                 fields="ts_code,end_date,audit_result,audit_agency,audit_fees")
        except RuntimeError:
            lines.append("审计数据缺失\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("审计数据缺失\n")
            return "\n".join(lines)

        df = df.sort_values("end_date", ascending=False)
        # Store the full sorted (newest-first) audit history for §13 warnings
        # so the assembly step need not re-fetch fina_audit.
        self._store["fina_audit"] = df
        df = df.head(3)
        headers = ["年度", "审计意见", "会计事务所", "审计费用 (万元)"]
        rows = []
        for _, r in df.iterrows():
            year = str(r.get("end_date", ""))[:4]
            opinion = str(r.get("audit_result", "—"))
            agency = str(r.get("audit_agency", "—")) if r.get("audit_agency") else "—"
            fees = r.get("audit_fees", None)
            if fees is not None and fees == fees:
                fees_str = f"{fees / 10000:.1f}"
            else:
                fees_str = "—"
            rows.append([year, opinion, agency, fees_str])

        table = format_table(headers, rows, alignments=["l", "l", "l", "r"])
        lines.append(table)
        return "\n".join(lines)

    # --- Feature #84: Section 14 — Risk-free rate ---

    def get_risk_free_rate(self, ts_code: str = "") -> str:
        """Section 14: Risk-free rate.

        For A-shares: 中债国债收益率曲线 (yc_cb)
        For US stocks: US 10-year Treasury yield via yfinance (^TNX)
        For HK stocks: 中债曲线 (mainland-listed HK companies report in HKD but reference CNY rates)
        """
        if self._is_us(ts_code):
            return self._get_risk_free_rate_us()
        return self._get_risk_free_rate_cn()

    def _get_risk_free_rate_cn(self) -> str:
        """Risk-free rate from 中债国债收益率曲线 (yc_cb)."""
        lines = [format_header(2, "14. 无风险利率"), ""]
        try:
            today = pd.Timestamp.now().strftime("%Y%m%d")
            # Get recent 10-year government bond yield
            df = self._cached_call("yc_cb", ts_code="1001.CB",
                                 curve_type="0",
                                 curve_term="10",
                                 start_date=(pd.Timestamp.now() - pd.DateOffset(months=1)).strftime("%Y%m%d"),
                                 end_date=today,
                                 fields="trade_date,yield")
        except RuntimeError:
            lines.append("数据缺失 (接口可能无权限)\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df = df.sort_values("trade_date", ascending=False)

        # Store for derived metrics
        self._store["risk_free_rate"] = df

        latest = df.iloc[0]

        table = format_table(
            ["日期", "10年期国债收益率 (%)"],
            [[str(latest.get("trade_date", "—")),
              f"{latest.get('yield', 0):.4f}"]],
            alignments=["l", "r"],
        )
        lines.append(table)
        lines.append("")
        lines.append("*数据来源: 中债国债收益率曲线 (yc_cb)*")
        return "\n".join(lines)

    def _get_risk_free_rate_us(self) -> str:
        """Risk-free rate from US 10-year Treasury yield via yfinance (^TNX)."""
        lines = [format_header(2, "14. 无风险利率"), ""]

        if not self._yf_available:
            lines.append("数据缺失 (yfinance 不可用)\n")
            return "\n".join(lines)

        try:
            tnx = _yf().Ticker("^TNX")
            hist = tnx.history(period="5d")
            if hist.empty:
                lines.append("数据缺失 (无法获取美债收益率)\n")
                return "\n".join(lines)

            latest_yield = float(hist["Close"].dropna().iloc[-1])
            latest_date = hist.index[-1].strftime("%Y%m%d")

            # Store in same format as CN bond for downstream compatibility
            rf_df = pd.DataFrame([{
                "trade_date": latest_date,
                "yield": latest_yield,
            }])
            self._store["risk_free_rate"] = rf_df

            table = format_table(
                ["日期", "美国10年期国债收益率 (%)"],
                [[latest_date, f"{latest_yield:.4f}"]],
                alignments=["l", "r"],
            )
            lines.append(table)
            lines.append("")
            lines.append("*数据来源: US 10-Year Treasury Yield (^TNX via yfinance)*")
        except Exception as e:
            lines.append(f"数据获取失败: {e}\n")

        return "\n".join(lines)

    # --- Feature #85: Section 15 — Share repurchase ---

    def get_repurchase(self, ts_code: str) -> str:
        """Section 15: Share repurchase data from repurchase endpoint."""
        if self._is_hk(ts_code):
            return format_header(2, "15. 股票回购") + "\n\n数据缺失 (港股暂不支持)\n"
        if self._is_us(ts_code):
            return format_header(2, "15. 股票回购") + "\n\n数据缺失 (美股暂不支持)\n"

        lines = [format_header(2, "15. 股票回购"), ""]
        try:
            df = self._cached_call("repurchase", ts_code=ts_code,
                                 fields="ts_code,ann_date,end_date,proc,exp_date,"
                                        "vol,amount,high_limit,low_limit")
        except RuntimeError:
            lines.append("数据缺失 (接口可能无权限)\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("近3年无回购记录\n")
            return "\n".join(lines)

        # Filter to last 3 years
        three_years_ago = (_now() - pd.DateOffset(years=3)).strftime("%Y%m%d")
        if "ann_date" in df.columns:
            df = df[df["ann_date"] >= three_years_ago].copy()

        if df.empty:
            lines.append("近3年无回购记录\n")
            return "\n".join(lines)

        df = df.sort_values("ann_date", ascending=False)

        # Deduplicate: same repurchase plan appears multiple times at
        # different progress stages (董事会预案→股东大会通过→实施→完成).
        # Keep only one record per (ann_date, amount) pair.
        if "amount" in df.columns:
            df = df.drop_duplicates(subset=["ann_date", "amount"], keep="first")

        # Filter to executed repurchases only (align with dividend
        # div_proc=="实施" filtering).  Fall back to deduped full data
        # if no executed records exist.
        if "proc" in df.columns:
            executed = df[df["proc"].isin(["完成", "实施"])]
            if not executed.empty:
                df = executed

        # Cross-date dedup: same repurchase plan may appear on different
        # announcement dates (progress updates).  Deduplicate by plan identity.
        if all(c in df.columns for c in ["high_limit", "amount", "proc"]):
            completed = df[df["proc"] == "完成"].copy()
            executing = df[df["proc"] == "实施"].copy()
            other = df[~df["proc"].isin(["完成", "实施"])].copy()

            if not completed.empty:
                completed = completed.drop_duplicates(
                    subset=["amount", "high_limit"], keep="first")
            if not executing.empty:
                executing = executing.sort_values("amount", ascending=False)
                executing = executing.drop_duplicates(
                    subset=["high_limit"], keep="first")

            # If a plan already has a 完成 record, drop its 实施 records
            if not completed.empty and not executing.empty:
                completed_limits = set(completed["high_limit"].dropna())
                executing = executing[
                    ~executing["high_limit"].isin(completed_limits)]

            df = pd.concat(
                [completed, executing, other]).sort_values(
                    "ann_date", ascending=False)

        # Store filtered/deduped data for derived metrics (§17.2 O)
        self._store["repurchase"] = df

        headers = ["公告日", "进度", "回购金额 (百万元)", "回购股数 (万股)", "价格下限", "价格上限"]
        rows = []
        total_amount = 0
        for _, r in df.iterrows():
            amt = r.get("amount", None)
            vol = r.get("vol", None)
            if amt is not None and amt == amt:
                total_amount += float(amt)
            rows.append([
                str(r.get("ann_date", "—")),
                str(r.get("proc", "—")),
                format_number(amt),
                format_number(vol, divider=1e4, decimals=2) if vol is not None and vol == vol else "—",
                f"{r.get('low_limit', 0):.2f}" if r.get("low_limit") is not None else "—",
                f"{r.get('high_limit', 0):.2f}" if r.get("high_limit") is not None else "—",
            ])

        table = format_table(headers, rows,
                             alignments=["l", "l", "r", "r", "r", "r"])
        lines.append(table)
        lines.append("")
        lines.append(f"近3年累计回购金额（已去重/仅完成+实施）: {format_number(total_amount)} {self._unit_label()}")
        years_span = min(3, max(1, len(set(str(r.get("ann_date", ""))[:4] for _, r in df.iterrows()))))
        lines.append(f"年均回购金额: {format_number(total_amount / years_span)} {self._unit_label()}")
        lines.append("")
        lines.append("> ⚠️ 上述金额包含所有用途（注销/员工持股/市值管理）。"
                     "O 仅计入注销型回购，Phase 3 需核实用途后调整。")
        return "\n".join(lines)

    # --- Feature #86: Section 16 — Share pledge statistics ---

    def get_pledge_stat(self, ts_code: str) -> str:
        """Section 16: Share pledge statistics from pledge_stat endpoint."""
        if self._is_hk(ts_code):
            return format_header(2, "16. 股权质押") + "\n\n不适用 (港股无此制度)\n"
        if self._is_us(ts_code):
            return format_header(2, "16. 股权质押") + "\n\n不适用 (美股无此制度)\n"

        lines = [format_header(2, "16. 股权质押"), ""]
        try:
            df = self._cached_call("pledge_stat", ts_code=ts_code,
                                 fields="ts_code,end_date,pledge_count,"
                                        "unrest_pledge,rest_pledge,"
                                        "total_share,pledge_ratio")
        except RuntimeError:
            lines.append("数据缺失 (接口可能无权限)\n")
            return "\n".join(lines)

        if df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)

        df = df.sort_values("end_date", ascending=False)
        latest = df.iloc[0]

        table = format_table(
            ["项目", "数值"],
            [
                ["统计日期", str(latest.get("end_date", "—"))],
                ["质押笔数", f"{int(latest.get('pledge_count', 0))}"],
                ["无限售质押 (万股)", format_number(latest.get("unrest_pledge"), divider=1e4, decimals=2)],
                ["有限售质押 (万股)", format_number(latest.get("rest_pledge"), divider=1e4, decimals=2)],
                ["总股本 (万股)", format_number(latest.get("total_share"), divider=1e4, decimals=2)],
                ["质押比例 (%)", f"{latest.get('pledge_ratio', 0):.2f}"],
            ],
            alignments=["l", "r"],
        )
        lines.append(table)
        return "\n".join(lines)
