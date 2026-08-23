"""Turtle Investment Framework - AssemblyMixin + WarningsCollector.

Data pack assembly, derived metrics orchestration, and warning collection.
"""

import re

import pandas as pd

from format_utils import format_number, format_table, format_header


class AssemblyMixin:
    """Mixin providing data pack assembly for TushareClient."""

    def compute_derived_metrics(self, ts_code: str) -> str:
        """Compute §17: Derived metrics from stored DataFrames.

        Must be called after all get_* methods have populated self._store.
        """
        lines = [
            format_header(2, "17. 衍生指标（Python 预计算）"),
            "",
            f"> 以下指标基于 §1-§16 原始数据确定性计算，无 LLM 判断成分。Phase 3 可直接引用。{self._unit_label()}。",
            "",
        ]

        sub_methods = [
            self._compute_financial_trends,
            lambda: self._compute_factor2_inputs(ts_code),
            self._compute_factor3_step1,
            self._compute_factor3_step4,
            self._compute_factor3_sensitivity_base,
            self._compute_factor4_inputs,
            self._compute_sotp_inputs,
            lambda: self._compute_factor4_ev_baseline(ts_code),
            lambda: self._compute_factor4_sensitivity(ts_code),
            # §17.10-17.13 grids (run after §17.5 which populates factor3_sensitivity;
            # §17.10 must precede §17.11/§17.13 which read _store["payout_crosscheck"])
            self._compute_payout_crosscheck,
            lambda: self._compute_penetration_grid(ts_code),
            self._compute_g_grid,
            lambda: self._compute_revenue_sensitivity(ts_code),
        ]

        for method in sub_methods:
            try:
                result = method()
                if result:
                    lines.append(result)
                    lines.append("")
            except Exception as e:
                name = getattr(method, "__name__", str(method))
                lines.append(f"*{name} 计算失败: {e}*")
                lines.append("")

        return "\n".join(lines)

    # --- Refresh-market helpers ---

    @staticmethod
    def _parse_sections(content: str):
        """Split data_pack_market.md content into header, sections list, and footer.

        Returns:
            (header_str, sections_list, footer_str)
            - header_str: everything before the first ``## `` line
            - sections_list: list of (key, content) tuples preserving original order.
              key is the section ID string (e.g., "1", "2", "3P", "9B", "17", "13").
              content is the full text from ``## N.`` to just before the next ``## ``.
            - footer_str: trailing ``---`` line and completion summary (if any)
        """
        # Pattern: ## <digits><optional uppercase letter(s)>. <title>
        section_re = re.compile(r"^(## (\d+[A-Z]?)\. .*)$", re.MULTILINE)

        matches = list(section_re.finditer(content))
        if not matches:
            return content, [], ""

        header = content[: matches[0].start()]

        sections = []
        for i, m in enumerate(matches):
            key = m.group(2)
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            sections.append((key, content[start:end]))

        # Separate footer from the last section: look for trailing "---\n*共" pattern
        footer = ""
        if sections:
            last_key, last_text = sections[-1]
            footer_re = re.compile(r"\n---\n\*共 .+$", re.DOTALL)
            fm = footer_re.search(last_text)
            if fm:
                footer = last_text[fm.start():]
                sections[-1] = (last_key, last_text[: fm.start()])

        return header, sections, footer

    def _build_header(self, ts_code: str) -> str:
        """Build the data pack header block (title, timestamp, source, unit).

        Returns:
            Header string ending with a blank line (ready to be followed by sections).
        """
        timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        currency = self._detect_currency(ts_code)
        self._currency = currency
        unit_label = {"HKD": "百万港元", "USD": "百万美元"}.get(currency, "百万元")
        lines = [
            format_header(1, f"数据包 — {ts_code}"),
            "",
            f"*生成时间: {timestamp}*",
            f"*数据来源: Tushare Pro*",
            f"*金额单位: {unit_label} (除特殊标注)*",
        ]
        if currency == "HKD":
            lines.append("*报表币种: HKD*")
        elif currency == "USD":
            lines.append("*报表币种: USD*")
        lines.extend(["", "---", ""])
        return "\n".join(lines)

    @staticmethod
    def _check_staleness(content: str) -> int:
        """Return the number of days since the data pack was generated.

        Parses ``*生成时间: YYYY-MM-DD HH:MM:SS*`` from the content header.
        Returns 999 if the timestamp cannot be found or parsed.
        """
        m = re.search(r"\*生成时间:\s*(\d{4}-\d{2}-\d{2})", content)
        if not m:
            return 999
        try:
            gen_date = pd.Timestamp(m.group(1))
            now = pd.Timestamp.now().normalize()
            return (now - gen_date.normalize()).days
        except Exception:
            return 999

    # Map section IDs to the fetch methods and their display names
    _REFRESH_SECTIONS = {"1", "2", "11", "14"}

    def refresh_market_sections(self, ts_code: str, existing_content: str) -> str:
        """Re-fetch market-sensitive sections and merge with existing data pack.

        Only sections 1 (基本信息), 2 (市场行情), 11 (十年周线行情), and 14 (无风险利率)
        are refreshed. All other sections are preserved unchanged.

        Args:
            ts_code: Stock code (e.g., '600887.SH').
            existing_content: Full text of the existing data_pack_market.md.

        Returns:
            Complete markdown string with refreshed header and market sections.
        """
        _header, sections, footer = self._parse_sections(existing_content)

        # Build mapping from section ID to fetch callable
        fetch_map = {
            "1": ("1. 基本信息", self.get_basic_info),
            "2": ("2. 市场行情", self.get_market_data),
            "11": ("11. 十年周线行情", self.get_weekly_prices),
            "14": ("14. 无风险利率", self.get_risk_free_rate),
        }

        # Detect currency for formatting (needed by get_* methods)
        currency = self._detect_currency(ts_code)
        self._currency = currency

        # Re-fetch each refreshable section; keep old on failure
        new_sections = []
        for key, text in sections:
            if key in fetch_map:
                name, method = fetch_map[key]
                try:
                    print(f"  Refreshing {name}...")
                    fresh_md = method(ts_code)
                    # Ensure section text ends with a newline for clean joining
                    if not fresh_md.endswith("\n"):
                        fresh_md += "\n"
                    new_sections.append((key, fresh_md))
                except Exception as e:
                    print(f"  ⚠️ Failed to refresh {name}: {e}, keeping old data")
                    new_sections.append((key, text))
            else:
                new_sections.append((key, text))

        # Build new header with refresh-mode annotation
        new_header = self._build_header(ts_code)
        new_header += "*刷新模式: --refresh-market（仅更新 §1/§2/§11/§14）*\n"
        new_header += "\n"

        # Reassemble
        parts = [new_header]
        for _key, text in new_sections:
            parts.append(text)

        result = "".join(parts)

        # Re-attach footer
        if footer:
            result = result.rstrip("\n") + footer
        else:
            result = result.rstrip("\n") + "\n"

        return result

    # --- Feature #28: Full data_pack_market.md assembly ---

    def assemble_data_pack(self, ts_code: str) -> str:
        """Assemble complete data_pack_market.md combining all sections."""
        timestamp = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
        currency = self._detect_currency(ts_code)
        self._currency = currency
        unit_label = {"HKD": "百万港元", "USD": "百万美元"}.get(currency, "百万元")
        lines = [
            format_header(1, f"数据包 — {ts_code}"),
            "",
            f"*生成时间: {timestamp}*",
            f"*数据来源: Tushare Pro*",
            f"*金额单位: {unit_label} (除特殊标注)*",
        ]
        if currency == "HKD":
            lines.append(f"*报表币种: HKD*")
        elif currency == "USD":
            lines.append(f"*报表币种: USD*")
        lines.extend(["", "---", ""])

        if self._is_us(ts_code):
            sections = [
                ("1. 基本信息", self.get_basic_info),
                ("2. 市场行情", self.get_market_data),
                ("3. 合并利润表", self.get_income),
                # No §3P for US (US GAAP: no parent/consolidated split)
                ("4. 合并资产负债表", self.get_balance_sheet),
                # No §4P for US
                ("5. 现金流量表", self.get_cashflow),
                ("6. 分红历史", self.get_dividends),
                ("7. 股东与治理", self.get_holders),
                ("9. 主营业务构成", self.get_segments),
                ("11. 十年周线行情", self.get_weekly_prices),
                ("12. 关键财务指标", self.get_fina_indicators),
                ("15. 股票回购", self.get_repurchase),
                ("16. 股权质押", self.get_pledge_stat),
            ]
        elif self._is_hk(ts_code):
            sections = [
                ("1. 基本信息", self.get_basic_info),
                ("2. 市场行情", self.get_market_data),
                ("3. 合并利润表", self.get_income),
                # No §3P for HK (HKFRS does not split parent/consolidated)
                ("4. 合并资产负债表", self.get_balance_sheet),
                # No §4P for HK
                ("5. 现金流量表", self.get_cashflow),
                ("6. 分红历史", self.get_dividends),
                ("7. 股东与治理", self.get_holders),       # placeholder
                ("9. 主营业务构成", self.get_segments),      # placeholder
                ("11. 十年周线行情", self.get_weekly_prices),
                ("12. 关键财务指标", self.get_fina_indicators),
                ("15. 股票回购", self.get_repurchase),       # placeholder
                ("16. 股权质押", self.get_pledge_stat),      # placeholder
            ]
        else:
            sections = [
                ("1. 基本信息", self.get_basic_info),
                ("2. 市场行情", self.get_market_data),
                ("3. 合并利润表", self.get_income),
                ("3P. 母公司利润表", self.get_income_parent),
                ("4. 合并资产负债表", self.get_balance_sheet),
                ("4P. 母公司资产负债表", self.get_balance_sheet_parent),
                ("5. 现金流量表", self.get_cashflow),
                ("6. 分红历史", self.get_dividends),
                ("7. 股东与治理", self.get_holders),
                ("9. 主营业务构成", self.get_segments),
                ("11. 十年周线行情", self.get_weekly_prices),
                ("12. 关键财务指标", self.get_fina_indicators),
                ("15. 股票回购", self.get_repurchase),
                ("16. 股权质押", self.get_pledge_stat),
            ]

        completed = 0
        for name, method in sections:
            try:
                print(f"  Collecting {name}...")
                section_md = method(ts_code)
                lines.append(section_md)
                lines.append("")
                completed += 1
            except Exception as e:
                # Attempt yfinance fallback for market data sections
                yf_data = self._yf_fallback_price(ts_code)
                if yf_data and name in ("1. 基本信息", "2. 市场行情"):
                    lines.append(format_header(2, name))
                    lines.append(f"\n*来源: yfinance (降级)*")
                    if yf_data.get("close"):
                        lines.append(f"- 当前价格: {yf_data['close']}")
                    if yf_data.get("market_cap"):
                        lines.append(f"- 总市值: {format_number(yf_data['market_cap'], divider=1e6)}")
                    lines.append("")
                    completed += 1
                else:
                    lines.append(format_header(2, name))
                    lines.append(f"\n数据获取失败: {e}\n")

        # Audit info (sub-section of 7)
        try:
            audit_md = self.get_audit(ts_code)
            lines.append(audit_md)
            lines.append("")
        except Exception:
            pass

        # Risk-free rate
        try:
            print("  Collecting 14. 无风险利率...")
            rf_md = self.get_risk_free_rate(ts_code)
            lines.append(rf_md)
            lines.append("")
        except Exception as e:
            lines.append(format_header(2, "14. 无风险利率"))
            lines.append(f"\n数据获取失败: {e}\n")

        # Agent-only placeholder sections (§8, §10)
        for sec_num, sec_name in [
            ("8", "行业与竞争"),
            ("10", "管理层讨论与分析 (MD&A)"),
        ]:
            lines.append(format_header(2, f"{sec_num}. {sec_name}"))
            lines.append("")
            lines.append(f"*[§{sec_num} 待Agent WebSearch补充]*")
            lines.append("")

        # §17 Derived metrics (pre-computed from stored DataFrames)
        try:
            print("  Computing 17. 衍生指标...")
            derived_md = self.compute_derived_metrics(ts_code)
            lines.append(derived_md)
            lines.append("")
        except Exception as e:
            lines.append(format_header(2, "17. 衍生指标（Python 预计算）"))
            lines.append(f"\n计算失败: {e}\n")

        # §13 Warnings: auto-detect + agent placeholder
        wc = WarningsCollector()
        try:
            if self._is_us(ts_code) or self._is_hk(ts_code):
                # HK: use stored data instead of re-calling A-share-only APIs
                for label, store_key in [
                    ("合并利润表", "income"),
                    ("合并资产负债表", "balance_sheet"),
                    ("现金流量表", "cashflow"),
                ]:
                    stored = self._store.get(store_key)
                    wc.check_missing_data(label, stored if stored is not None else pd.DataFrame())
            else:
                # A-share: Check missing data + YoY anomaly for core financial
                # statements. Read from _store (populated by get_income/
                # get_balance_sheet/get_cashflow) instead of re-fetching, which
                # eliminates redundant API calls. YoY scan window is the ~5y
                # display window (consistent with the HK/US branch above).
                for label, store_key, cols in [
                    ("合并利润表", "income", ["revenue", "n_income_attr_p"]),
                    ("合并资产负债表", "balance_sheet", ["total_assets"]),
                    ("现金流量表", "cashflow", ["n_cashflow_act"]),
                ]:
                    df = self._store.get(store_key)
                    if df is None:
                        df = pd.DataFrame()
                    wc.check_missing_data(label, df)
                    if not df.empty and "end_date" in df.columns:
                        # Filter to annual reports only (end_date ending in "1231")
                        annual = df[df["end_date"].astype(str).str.endswith("1231")].copy()
                        annual = annual.sort_values("end_date", ascending=False)
                        if not annual.empty:
                            dates = annual["end_date"].astype(str).str[:4].tolist()
                            for col in cols:
                                if col in annual.columns:
                                    wc.check_yoy_change(label, col, annual[col].tolist(), dates=dates)

                # Audit risk check — read stored fina_audit (newest-first)
                audit_df = self._store.get("fina_audit")
                if audit_df is not None and not audit_df.empty and "audit_result" in audit_df.columns:
                    wc.check_audit_risk(str(audit_df.iloc[0].get("audit_result", "")))

            # Balance sheet risk checks (goodwill, debt ratio) — use stored data
            # (store rows are newest-first, so iloc[0] is the latest period).
            bs_df = self._store.get("balance_sheet")
            if bs_df is not None and not bs_df.empty:
                latest = bs_df.iloc[0]
                gw = latest.get("goodwill", 0) or 0
                ta = latest.get("total_assets", 0) or 0
                tl = latest.get("total_liab", 0) or 0
                wc.check_goodwill_ratio(float(gw), float(ta))
                wc.check_debt_ratio(float(tl), float(ta))
            # Dividend data correction warning (from _get_dividends_hk)
            div_warn = self._store.get("_dividend_warning")
            if div_warn:
                wc.warnings.append({
                    "type": "DATA_CORRECTION",
                    "severity": "中",
                    "message": div_warn,
                })
        except Exception:
            pass  # warnings are best-effort; don't block assembly

        # Build §13 with two sub-sections
        lines.append(format_header(2, "13. 风险警示"))
        lines.append("")
        lines.append("### 13.1 脚本自动检测")
        lines.append("")
        if wc.warnings:
            high = [w for w in wc.warnings if w["severity"] == "高"]
            medium = [w for w in wc.warnings if w["severity"] == "中"]
            low = [w for w in wc.warnings if w["severity"] == "低"]
            for sev_label, items in [("高风险", high), ("中风险", medium), ("低风险", low)]:
                if items:
                    lines.append(f"**{sev_label}:**")
                    for w in items:
                        lines.append(f"- [{w['type']}|{w['severity']}] {w['message']}")
                    lines.append("")
        else:
            lines.append("未检测到异常。")
            lines.append("")
        if self._is_us(ts_code):
            lines.append("")
            lines.append("> 美股数据覆盖有限：§9业务构成/§15回购 暂缺，"
                         "§16质押不适用（美股无此制度），"
                         "§3P/§4P母公司报表在US GAAP体系下不适用，c_pay_to_staff 不可用。")
            lines.append("")
        elif self._is_hk(ts_code):
            lines.append("")
            lines.append("> 港股数据覆盖有限：§9业务构成/§15回购 暂缺，"
                         "§16质押不适用（港股无此制度），"
                         "§3P/§4P母公司报表在HKFRS体系下不适用，c_pay_to_staff 不可用。")
            lines.append("")

        lines.append("### 13.2 Agent WebSearch 补充")
        lines.append("")
        lines.append("*[§13.2 待Agent WebSearch补充]*")
        lines.append("")

        lines.append("---")
        lines.append(f"*共 {completed}/{len(sections)} 个数据板块成功获取*")

        return "\n".join(lines)


class WarningsCollector:
    """Auto-detect anomalies during data collection (Feature #30)."""

    def __init__(self):
        self.warnings = []

    def check_missing_data(self, section_name: str, df: pd.DataFrame):
        """Warn if a data section returned empty."""
        if df is None or (isinstance(df, pd.DataFrame) and df.empty):
            self.warnings.append({
                "type": "DATA_MISSING",
                "severity": "中",
                "message": f"{section_name} 数据缺失",
            })

    def check_yoy_change(self, section_name: str, field_name: str,
                         values: list, threshold: float = 3.0,
                         dates: list = None):
        """Warn if year-over-year change exceeds threshold (e.g., 300%)."""
        for i in range(len(values) - 1):
            curr, prev = values[i], values[i + 1]
            if prev is not None and curr is not None and float(prev) != 0:
                try:
                    change = abs(float(curr) / float(prev) - 1)
                    if change > threshold:
                        period = ""
                        if dates and i + 1 < len(dates):
                            period = f"{dates[i+1]}→{dates[i]} "
                        self.warnings.append({
                            "type": "YOY_ANOMALY",
                            "severity": "高",
                            "message": f"{section_name}/{field_name}: "
                                       f"{period}同比变化 {change*100:.0f}% 超过 {threshold*100:.0f}% 阈值",
                        })
                except (ValueError, ZeroDivisionError):
                    pass

    def check_audit_risk(self, audit_opinion: str):
        """Warn if audit opinion is not clean."""
        if audit_opinion and audit_opinion not in ("标准无保留意见", "—", ""):
            self.warnings.append({
                "type": "AUDIT_RISK",
                "severity": "高",
                "message": f"审计意见非标准: {audit_opinion}",
            })

    def check_goodwill_ratio(self, goodwill: float, total_assets: float):
        """Warn if goodwill/total_assets > 20%."""
        if goodwill and total_assets and total_assets > 0:
            ratio = float(goodwill) / float(total_assets)
            if ratio > 0.20:
                self.warnings.append({
                    "type": "GOODWILL_RISK",
                    "severity": "高",
                    "message": f"商誉占总资产比例 {ratio*100:.1f}% 超过 20%",
                })

    def check_debt_ratio(self, total_liab: float, total_assets: float):
        """Warn if debt ratio > 70%."""
        if total_liab and total_assets and total_assets > 0:
            ratio = float(total_liab) / float(total_assets)
            if ratio > 0.70:
                self.warnings.append({
                    "type": "LEVERAGE_RISK",
                    "severity": "中",
                    "message": f"资产负债率 {ratio*100:.1f}% 超过 70%",
                })

    def format_warnings(self) -> str:
        """Format all collected warnings as section 13 markdown."""
        lines = [format_header(2, "13. 风险警示 (脚本自动生成)"), ""]

        if not self.warnings:
            lines.append("未检测到异常。")
            return "\n".join(lines)

        # Group by severity
        high = [w for w in self.warnings if w["severity"] == "高"]
        medium = [w for w in self.warnings if w["severity"] == "中"]
        low = [w for w in self.warnings if w["severity"] == "低"]

        if high:
            lines.append("**高风险:**")
            for w in high:
                lines.append(f"- [{w['type']}] {w['message']}")
            lines.append("")
        if medium:
            lines.append("**中风险:**")
            for w in medium:
                lines.append(f"- [{w['type']}] {w['message']}")
            lines.append("")
        if low:
            lines.append("**低风险:**")
            for w in low:
                lines.append(f"- [{w['type']}] {w['message']}")
            lines.append("")

        lines.append(f"*共 {len(self.warnings)} 条自动警示*")
        return "\n".join(lines)
