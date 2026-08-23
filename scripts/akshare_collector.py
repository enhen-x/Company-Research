#!/usr/bin/env python3
"""Turtle Investment Framework - AkShare Data Collector (Phase 1A fallback).

当 Tushare 不可用（未配置 TUSHARE_TOKEN 或 API 调用失败）时，使用 AkShare
（东方财富/新浪财经）作为降级数据源，采集 A 股财务与行情数据，输出与
tushare_collector.py 兼容的 data_pack_market.md（§1-§17，金额单位百万元）。

Usage:
    python scripts/akshare_collector.py --code 600941.SH
    python scripts/akshare_collector.py --code 600941.SH --output output/600941_中国移动/data_pack_market.md

注：本脚本仅支持 A 股；港股/美股请配置 TUSHARE_TOKEN 使用 tushare_collector.py。
"""

import argparse
import os
import time
import re
import sys

import pandas as pd

# ---------------------------------------------------------------
# 网络适配：本机存在系统代理且无法访问财经数据源时，强制直连并跳过
# 证书校验（与 curl -k 行为一致）。必须在导入 akshare 之前设置。
# ---------------------------------------------------------------
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
import ssl
ssl._create_default_https_context = ssl._create_unverified_context
import requests
_orig_session_request = requests.sessions.Session.request


def _patched_request(self, method, url, **kwargs):
    kwargs.setdefault("proxies", {"http": None, "https": None})
    kwargs.setdefault("verify", False)
    return _orig_session_request(self, method, url, **kwargs)


requests.sessions.Session.request = _patched_request

import akshare as ak  # noqa: E402

from format_utils import format_number, format_table, format_header  # noqa: E402

REPORT_YEAR_COL = "REPORT_DATE"


def _num(v):
    """Convert to float or return None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN -> None


def _get(df, row, col):
    if col not in df.columns:
        return None
    v = df.iloc[row].get(col)
    return _num(v)


def _fmt(v, decimals=2):
    return format_number(v, divider=1e6, decimals=decimals)


def _safe(fn, tries=2, label=""):
    """Run fn with retries; return None on persistent failure."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 if i < tries - 1 else 0)
    print(f"  ⚠️ {label} 获取失败: {last}")
    return None


def normalize_code(code: str) -> str:
    """Normalize to Tushare-style code (600941.SH / 000858.SZ)."""
    c = code.strip().upper()
    if c.endswith(".SH") or c.endswith(".SZ") or c.endswith(".BJ"):
        return c
    if re.fullmatch(r"\d{6}", c):
        if c.startswith(("6", "9")):
            return c + ".SH"
        if c.startswith(("0", "3")):
            return c + ".SZ"
        if c.startswith(("4", "8")):
            return c + ".BJ"
        raise ValueError(f"无法判断交易所: {code}")
    raise ValueError(f"无效股票代码: {code}")


def symbol6(ts_code: str) -> str:
    return ts_code.split(".")[0]


def em_symbol(ts_code: str) -> str:
    """East Money symbol with exchange prefix, e.g. SH600941."""
    s6 = symbol6(ts_code)
    return ("SH" if ts_code.endswith(".SH") else "SZ" if ts_code.endswith(".SZ") else "BJ") + s6


def sina_symbol(ts_code: str) -> str:
    return ts_code.replace(".", "").lower()


def annual_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Keep 年报 rows, sort ascending by REPORT_DATE."""
    if df is None or df.empty:
        return pd.DataFrame()
    d = df[df["REPORT_TYPE"] == "年报"].copy()
    if d.empty:
        return pd.DataFrame()
    d[REPORT_YEAR_COL] = d[REPORT_YEAR_COL].astype(str)
    return d.sort_values(REPORT_YEAR_COL).reset_index(drop=True)


class AkshareCollector:
    def __init__(self):
        self.code = None
        self.s6 = None
        self.spot = {}          # 行情快照（市值/PE/PB 等）
        self.daily_1y = None    # 日线（52周）
        self.weekly = None      # 周线（10年）
        self.annual = {}        # 年报 DataFrame by section

    # ---------- 数据获取 ----------

    def _sina_daily(self, start, end, tries=4, pause=2.5):
        """新浪日线（前复权），带重试。返回标准列 DataFrame 或 None。"""
        for i in range(tries):
            try:
                df = ak.stock_zh_a_daily(symbol=sina_symbol(self.code), start_date=start,
                                         end_date=end, adjust="qfq")
                if df is not None and not df.empty and "date" in df.columns:
                    return df.rename(columns={"date": "日期", "open": "开盘", "close": "收盘",
                                              "high": "最高", "low": "最低", "volume": "成交量",
                                              "amount": "成交额"})
            except Exception:
                pass
            time.sleep(pause)
        return None

    def _sina_full(self):
        """新浪日线全量（近10年，逐年拉取），只执行一次并缓存。返回标准列 DataFrame 或 None。"""
        if getattr(self, "_sina_full_df", None) is not None:
            return self._sina_full_df
        frames = []
        now = pd.Timestamp.now()
        for y in range(now.year - 10, now.year + 1):
            d = self._sina_daily(f"{y}0101", f"{y}1231", tries=2, pause=1.5)
            if d is not None:
                frames.append(d)
            time.sleep(0.5)
        if frames:
            daily = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["日期"])
            daily["日期"] = pd.to_datetime(daily["日期"])
            daily = daily[daily["日期"] >= now - pd.DateOffset(years=10)]
            self._sina_full_df = daily
            return daily
        return None

    def _tencent_daily(self, start, end):
        """腾讯日K（前复权）区间拉取，返回标准列 DataFrame 或 None。"""
        try:
            sym = em_symbol(self.code).lower()
            url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
                   f"?param={sym},day,{start},{end},800,qfq")
            r = requests.get(url, timeout=15)
            d = r.json()
            node = d.get("data", {}).get(sym, {})
            arr = node.get("qfqday") or node.get("day") or []
            if not arr:
                return None
            # 个别行可能多出 7 列（成交额等），统一取前 6 列
            df = pd.DataFrame([row[:6] for row in arr],
                              columns=["日期", "开盘", "收盘", "最高", "最低", "成交量"])
            df = df.drop_duplicates(subset=["日期"])
            for col in ("开盘", "收盘", "最高", "最低", "成交量"):
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["日期"] = pd.to_datetime(df["日期"])
            return df
        except Exception:
            return None

    def _tencent_full(self):
        """腾讯日K全量（近10年，按年分页），只执行一次并缓存。"""
        if getattr(self, "_tencent_full_df", None) is not None:
            return self._tencent_full_df
        frames = []
        now = pd.Timestamp.now()
        for y in range(now.year - 10, now.year + 1):
            d = self._tencent_daily(f"{y}-01-01", f"{y}-12-31")
            if d is not None and not d.empty:
                frames.append(d)
            time.sleep(0.4)
        if frames:
            daily = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["日期"])
            daily = daily[daily["日期"] >= now - pd.DateOffset(years=10)]
            self._tencent_full_df = daily
            return daily
        return None

    def fetch_daily_1y(self):
        start = (pd.Timestamp.now() - pd.DateOffset(years=1)).strftime("%Y%m%d")
        end = pd.Timestamp.now().strftime("%Y%m%d")
        df = _safe(lambda: ak.stock_zh_a_hist(
            symbol=self.s6, period="daily", start_date=start, end_date=end, adjust="qfq"),
            tries=4, label="日线行情(东财)")
        if df is None or df.empty:
            print("  → 日线行情降级至腾讯")
            full = self._tencent_full()
            if full is None:
                print("  → 日线行情降级至新浪")
                full = self._sina_full()
            if full is not None:
                cutoff = pd.Timestamp.now() - pd.DateOffset(years=1)
                sub = full[full["日期"] >= cutoff].copy()
                sub["日期"] = sub["日期"].dt.strftime("%Y-%m-%d")
                df = sub.reset_index(drop=True)
        self.daily_1y = df

    def fetch_weekly(self):
        start = (pd.Timestamp.now() - pd.DateOffset(years=10)).strftime("%Y%m%d")
        end = pd.Timestamp.now().strftime("%Y%m%d")
        df = _safe(lambda: ak.stock_zh_a_hist(
            symbol=self.s6, period="weekly", start_date=start, end_date=end, adjust="qfq"),
            tries=4, label="周线行情(东财)")
        if df is None or df.empty:
            print("  → 周线行情降级至腾讯(全量日线聚合)")
            daily = self._tencent_full()
            if daily is None:
                print("  → 周线行情降级至新浪(全量日线聚合)")
                daily = self._sina_full()
            if daily is not None and not daily.empty:
                daily = daily.copy()
                daily["成交量"] = pd.to_numeric(daily["成交量"], errors="coerce")
                wk = daily.set_index("日期").resample("W-FRI").agg(
                    开盘=("开盘", "first"), 收盘=("收盘", "last"),
                    最高=("最高", "max"), 最低=("最低", "min"), 成交量=("成交量", "sum")).dropna()
                wk = wk.reset_index()
                wk["日期"] = wk["日期"].dt.strftime("%Y-%m-%d")
                df = wk
            else:
                print("  ⚠️ 周线行情降级失败（无可用日线数据）")
        self.weekly = df
    def fetch_basic_snapshot(self):
        """市值/价格/PE/PB：优先东财实时行情，失败用日线+总股本+财务数据估算。"""
        spot_df = _safe(lambda: ak.stock_zh_a_spot_em(), tries=2, label="stock_zh_a_spot_em")
        if spot_df is not None and not spot_df.empty:
            row = spot_df[spot_df["代码"] == self.s6]
            if not row.empty:
                r = row.iloc[0]
                self.spot = {
                    "name": r.get("名称"),
                    "price": _num(r.get("最新价")),
                    "total_mv": _num(r.get("总市值")),      # 元
                    "circ_mv": _num(r.get("流通市值")),    # 元
                    "pe": _num(r.get("市盈率-动态")),
                    "pb": _num(r.get("市净率")),
                    "total_share": _num(r.get("总股本")),   # 股
                }
                return
        # Fallback：腾讯实时行情（轻量）→ 日线最新价 → 新浪全市场快照，财务数据估算 PE/PB
        name, price = self._tencent_quote()
        if not price:
            price = self.last_price()
        if not price:
            try:
                all_spot = ak.stock_zh_a_spot()
                hit = all_spot[all_spot["代码"] == self.s6]
                if not hit.empty:
                    name = hit.iloc[0].get("名称") or name
                    price = _num(hit.iloc[0].get("最新价")) or price
            except Exception:
                pass
        ts = self.total_share()
        mv = (price * ts) if (price and ts) else None
        pe, pb = self.estimate_pe_pb(price)
        if not name:
            inc = self.annual.get("income")
            if inc is not None and not inc.empty and "SECURITY_NAME_ABBR" in inc.columns:
                name = str(inc.iloc[0].get("SECURITY_NAME_ABBR", ""))
        self.spot = {"name": name or self.s6, "price": price, "pe": pe, "pb": pb,
                     "total_mv": mv, "circ_mv": None, "total_share": ts,
                     "pe_is_est": True, "pb_is_est": True}

    def _tencent_quote(self):
        """腾讯实时行情兜底（qt.gtimg.cn），返回 (名称, 最新价) 或 (None, None)。"""
        try:
            url = f"https://qt.gtimg.cn/q={em_symbol(self.code).lower()}"
            r = requests.get(url, timeout=10)
            r.encoding = "gbk"
            m = re.search(r'="([^"]+)"', r.text)
            if not m:
                return None, None
            fields = m.group(1).split("~")
            if len(fields) > 3:
                return (fields[1] or None), _num(fields[3])
        except Exception:
            pass
        return None, None

    def estimate_pe_pb(self, price):
        """用报表数据 + 总股本估算 PE/PB（标注为估算，优先于分红详情字段）。"""
        if not price:
            return None, None
        ts = self.total_share()
        pe = pb = None
        income = self.annual.get("income")
        bal = self.annual.get("balance")
        if income is not None and not income.empty and ts:
            np_ = _get(income, len(income) - 1, "PARENT_NETPROFIT")
            if np_:
                eps = np_ / ts
                pe = round(price / eps, 2)
        if bal is not None and not bal.empty and ts:
            equity = _get(bal, len(bal) - 1, "TOTAL_PARENT_EQUITY")
            if equity:
                bvps = equity / ts
                pb = round(price / bvps, 2)
        return pe, pb

    def last_price(self) -> float:
        if self.daily_1y is not None and not self.daily_1y.empty:
            return _num(self.daily_1y.iloc[-1]["收盘"]) or 0.0
        return 0.0

    def total_share(self) -> float:
        div = self._div()
        if div is not None and not div.empty:
            v = _num(div.iloc[0].get("总股本"))
            if v:
                return v
        return None

    def _div(self):
        if not hasattr(self, "_div_df"):
            self._div_df = _safe(lambda: ak.stock_fhps_detail_em(symbol=self.s6),
                                 tries=2, label="分红详情")
        return self._div_df

    def fetch_all(self):
        print(f"Collecting data for {self.code} (AkShare)...")
        self.fetch_statements()
        self.fetch_daily_1y()
        self.fetch_weekly()
        self.fetch_basic_snapshot()
        self.fetch_indicators()
        self.fetch_rate()

    def fetch_statements(self):
        sym = em_symbol(self.code)
        self.annual["income"] = self._last5(_safe(lambda: ak.stock_profit_sheet_by_report_em(symbol=sym),
                                                  tries=2, label="利润表"))
        self.annual["balance"] = self._last5(_safe(lambda: ak.stock_balance_sheet_by_report_em(symbol=sym),
                                                   tries=2, label="资产负债表"))
        self.annual["cashflow"] = self._last5(_safe(lambda: ak.stock_cash_flow_sheet_by_report_em(symbol=sym),
                                                    tries=2, label="现金流量表"))

    @staticmethod
    def _last5(df):
        """仅保留最近 5 个年度报告期。"""
        d = annual_rows(df)
        if d.empty:
            return d
        return d.tail(5).reset_index(drop=True)

    def fetch_indicators(self):
        self.indicators = _safe(lambda: ak.stock_financial_analysis_indicator(
            symbol=self.s6, start_year=str(pd.Timestamp.now().year - 6)), tries=2, label="财务指标")
        if self.indicators is not None and not self.indicators.empty:
            self.indicators["日期"] = self.indicators["日期"].astype(str)

    def fetch_rate(self):
        start = (pd.Timestamp.now() - pd.DateOffset(days=400)).strftime("%Y%m%d")
        self.rates = _safe(lambda: ak.bond_zh_us_rate(start_date=start), tries=2, label="国债利率")
        if self.rates is not None and not self.rates.empty:
            self.rates["日期"] = self.rates["日期"].astype(str)

    # ---------- 输出 ----------

    def build(self) -> str:
        lines = [format_header(1, f"数据包 — {self.code}"), "",
                 f"*生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}*",
                 "*数据来源: AkShare（东方财富/新浪）— Tushare 不可用时自动降级*",
                 "*金额单位: 百万元 (除特殊标注)*", "", "---", ""]
        for builder in (self.s1_basic, self.s2_market, self.s3_income, self.s4_balance,
                        self.s5_cashflow, self.s6_dividend, self.s7_holders,
                        self.s9_segments, self.s11_weekly, self.s12_indicators,
                        self.s13_warnings, self.s14_rate, self.s15_repurchase,
                        self.s16_pledge, self.s17_derived):
            text = builder()
            if text:
                lines.append(text)
                lines.append("")
        lines.append("---")
        lines.append(f"*共 {len(lines)} 行 | AkShare 采集器 v1.0 | 龟龟投资框架*")
        return "\n".join(lines)

    def s1_basic(self) -> str:
        lines = [format_header(2, "1. 基本信息"), ""]
        price = self.spot.get("price")
        ts = self.total_share()
        total_mv = self.spot.get("total_mv")
        if total_mv is None and price and ts:
            total_mv = price * ts
        circ_mv = self.spot.get("circ_mv")
        name = self.spot.get("name") or self.s6
        rows = [["股票代码", self.code], ["公司名称", str(name)],
                ["当前价格 (元)", f"{price:.2f}" if price else "—"]]
        if total_mv:
            rows.append(["总市值 (百万元)", format_number(total_mv, divider=1e6)])
        if circ_mv:
            rows.append(["流通市值 (百万元)", format_number(circ_mv, divider=1e6)])
        pe = self.spot.get("pe"); pb = self.spot.get("pb")
        rows.append(["PE", f"{pe} (估算)" if pe and self.spot.get("pe_is_est") else (f"{pe}" if pe else "—")])
        rows.append(["PB", f"{pb} (估算)" if pb and self.spot.get("pb_is_est") else (f"{pb}" if pb else "—")])
        if ts:
            rows.append(["总股本 (亿股)", f"{ts / 1e8:,.2f}"])
        lines.append(format_table(["项目", "内容"], rows, alignments=["l", "r"]))
        return "\n".join(lines)

    def s2_market(self) -> str:
        lines = [format_header(2, "2. 市场行情"), ""]
        df = self.daily_1y
        if df is None or df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)
        latest = df.iloc[-1]
        high = df["最高"].max()
        low = df["最低"].min()
        hd = df.loc[df["最高"].idxmax(), "日期"]
        ld = df.loc[df["最低"].idxmin(), "日期"]
        avg_vol = df["成交量"].mean()
        price = _num(latest["收盘"])
        chg_low = (price / low - 1) * 100 if price and low else None
        rows = [["最新收盘价", f"{price:.2f}"], ["52周最高", f"{high:.2f} ({hd})"],
                ["52周最低", f"{low:.2f} ({ld})"]]
        if chg_low is not None:
            rows.append(["52周涨跌幅", f"{chg_low:.1f}% (自低点)"])
        rows.append(["日均成交量 (手)", f"{avg_vol:,.0f}"])
        lines.append(format_table(["指标", "数值"], rows, alignments=["l", "r"]))
        lines.append("")
        lines.append("*注: 价格为前复权(qfq)，52周区间基于最近约250个交易日*")
        return "\n".join(lines)

    def s3_income(self) -> str:
        return self._statement_table(
            "3. 合并利润表", "income",
            [("营业总收入", "TOTAL_OPERATE_INCOME"), ("营业收入", "OPERATE_INCOME"),
             ("营业成本", "OPERATE_COST"), ("税金及附加", "OPERATE_TAX_ADD"),
             ("销售费用", "SALE_EXPENSE"), ("管理费用", "MANAGE_EXPENSE"),
             ("研发费用", "RESEARCH_EXPENSE"), ("财务费用", "FINANCE_EXPENSE"),
             ("营业利润", "OPERATE_PROFIT"), ("利润总额", "TOTAL_PROFIT"),
             ("所得税费用", "INCOME_TAX"), ("净利润", "NETPROFIT"),
             ("归母净利润", "PARENT_NETPROFIT"), ("扣非归母净利润", "DEDUCT_PARENT_NETPROFIT"),
             ("少数股东损益", "MINORITY_INTEREST")],
            extra=lambda df, row: [["审计意见", str(df.iloc[row].get("OPINION_TYPE", ""))]])

    def s4_balance(self) -> str:
        return self._statement_table(
            "4. 合并资产负债表", "balance",
            [("货币资金", "MONETARYFUNDS"), ("交易性金融资产", "TRADE_FINASSET"),
             ("流动资产合计", "TOTAL_CURRENT_ASSETS"), ("总资产", "TOTAL_ASSETS"),
             ("流动负债合计", "TOTAL_CURRENT_LIAB"), ("总负债", "TOTAL_LIABILITIES"),
             ("归母权益", "TOTAL_PARENT_EQUITY"), ("少数股东权益", "MINORITY_EQUITY"),
             ("总权益", "TOTAL_EQUITY"), ("商誉", "GOODWILL"),
             ("固定资产", "FIXED_ASSET"), ("无形资产", "INTANGIBLE_ASSET"),
             ("短期借款", "SHORT_LOAN"), ("长期借款", "LONG_LOAN"),
             ("应付债券", "BOND_PAYABLE"), ("应收账款", "ACCOUNTS_RECE"),
             ("应收票据及账款", "NOTE_ACCOUNTS_RECE"), ("存货", "INVENTORY")])

    def s5_cashflow(self) -> str:
        lines = [format_header(2, "5. 现金流量表"), ""]
        df = self.annual.get("cashflow")
        if df is None or df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)
        head = ["项目"] + [str(d)[:4] for d in df[REPORT_YEAR_COL]]
        rows = []
        fields = [("经营活动现金流净额", "NETCASH_OPERATE"),
                  ("购建长期资产支付现金(≈Capex)", "CONSTRUCT_LONG_ASSET"),
                  ("投资活动现金流净额", "NETCASH_INVEST"),
                  ("筹资活动现金流净额", "NETCASH_FINANCE"),
                  ("分配股利/利润/偿付利息支付现金", "ASSIGN_DIVIDEND_PORFIT"),
                  ("期初现金及等价物", "BEGIN_CCE"),
                  ("期末现金及等价物", "END_CCE")]
        for label, col in fields:
            rows.append([label] + [_fmt(_get(df, i, col)) for i in range(len(df))])
        fcf = [_fmt((_get(df, i, "NETCASH_OPERATE") or 0) - (_get(df, i, "CONSTRUCT_LONG_ASSET") or 0))
               for i in range(len(df))]
        rows.append(["自由现金流 FCF (OCF−Capex)"] + fcf)
        lines.append(format_table(head, rows, alignments=["l"] + ["r"] * (len(head) - 1)))
        lines.append("")
        lines.append("*注: Capex 以现金流量表「购建固定资产、无形资产和其他长期资产支付的现金」近似*")
        return "\n".join(lines)

    def s6_dividend(self) -> str:
        lines = [format_header(2, "6. 分红历史"), ""]
        df = self._div()
        if df is None or df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)
        head = ["报告期", "分红方案(每10股)", "股息率", "每股收益(元)", "总股本(亿股)", "除权除息日"]
        rows = []
        for _, r in df.head(8).iterrows():
            ratio = _num(r.get("现金分红-现金分红比例"))
            plan = f"派{ratio:.2f}元" if ratio else str(r.get("现金分红-现金分红比例", ""))
            yield_ = _num(r.get("现金分红-股息率"))
            rows.append([str(r.get("报告期", ""))[:10], plan,
                         f"{yield_ * 100:.2f}%" if yield_ else "—",
                         f"{_num(r.get('每股收益')):.2f}" if _num(r.get("每股收益")) else "—",
                         f"{_num(r.get('总股本')) / 1e8:,.2f}" if _num(r.get("总股本")) else "—",
                         str(r.get("除权除息日", ""))])
        lines.append(format_table(head, rows, alignments=["l"] * len(head)))
        return "\n".join(lines)

    def s7_holders(self) -> str:
        return format_header(2, "7. 股东与治理") + "\n\n⚠️ 占位符：AkShare 采集器未采集，Phase 1B WebSearch 补充\n"

    def s9_segments(self) -> str:
        return format_header(2, "9. 主营业务构成") + "\n\n⚠️ 占位符：AkShare 采集器未采集，Phase 1B WebSearch 补充\n"

    def s11_weekly(self) -> str:
        lines = [format_header(2, "11. 十年周线行情"), ""]
        df = self.weekly
        if df is None or df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)
        lines.append(f"*行数: {len(df)}（{df.iloc[0]['日期']} ~ {df.iloc[-1]['日期']}，前复权）*\n")
        sub = df[["日期", "开盘", "收盘", "最高", "最低", "成交量"]].copy()
        sub["成交量(万手)"] = (sub["成交量"] / 1e4).round(0)
        head = ["日期", "开盘", "收盘", "最高", "最低", "成交量(万手)"]
        rows = [[str(r["日期"]), f"{_num(r['开盘']):.2f}", f"{_num(r['收盘']):.2f}",
                 f"{_num(r['最高']):.2f}", f"{_num(r['最低']):.2f}", f"{_num(r['成交量(万手)']):,.0f}"]
                for _, r in sub.iterrows()]
        lines.append(format_table(head, rows, alignments=["l"] + ["r"] * (len(head) - 1)))
        return "\n".join(lines)

    def s12_indicators(self) -> str:
        lines = [format_header(2, "12. 关键财务指标"), ""]
        df = self.indicators
        if df is None or df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)
        ann = df[df["日期"].str.endswith("-12-31")].tail(6)
        if ann.empty:
            ann = df.tail(6)
        head = ["指标"] + [str(d)[:4] for d in ann["日期"]]
        rows = []
        for label, col in [("净资产收益率(加权,%)", "加权净资产收益率(%)"),
                           ("净资产收益率(%)", "净资产收益率(%)"),
                           ("销售毛利率(%)", "销售毛利率(%)"),
                           ("销售净利率(%)", "销售净利率(%)"),
                           ("每股经营现金流(元)", "每股经营性现金流(元)"),
                           ("净利润增长率(%)", "净利润增长率(%)"),
                           ("摊薄每股收益(元)", "摊薄每股收益(元)")]:
            if col not in df.columns:
                continue
            rows.append([label] + [f"{_num(v):.2f}" if _num(v) is not None else "—"
                                   for v in ann[col]])
        lines.append(format_table(head, rows, alignments=["l"] + ["r"] * (len(head) - 1)))
        return "\n".join(lines)

    def s13_warnings(self) -> str:
        lines = [format_header(2, "13. 风险警告"), ""]
        warns = []
        if self.annual.get("income") is None or self.annual.get("income").empty:
            warns.append("[数据缺失|高] 利润表获取失败")
        if self.annual.get("cashflow") is None or self.annual.get("cashflow").empty:
            warns.append("[数据缺失|高] 现金流量表获取失败")
        if self.spot.get("pe_is_est") or self.spot.get("pb_is_est"):
            warns.append("[数据估算|低] 实时 PE/PB 未获取，使用 价格/EPS(TTM) 与 价格/每股净资产 估算")
        if self.weekly is None or self.weekly.empty:
            warns.append("[数据缺失|中] 十年周线获取失败，股价历史分位不可用")
        # 分红异常检测
        div = self._div()
        if div is not None and len(div) >= 2:
            ratios = [_num(r.get("现金分红-现金分红比例")) for _, r in div.head(3).iterrows()]
            if all(r is not None and r > 0 for r in ratios) and len(set(ratios)) == 1:
                warns.append("[数据异常|低] 连续多年现金分红比例完全相同，疑似数据填充错误，需人工核对")
        warns.append("[数据来源|低] 本数据包由 AkShare 采集器生成（Tushare 未配置），字段口径可能与 Tushare 版存在差异")
        if not warns:
            warns.append("无自动检测到的异常")
        lines.append("\n".join(f"- {w}" for w in warns))
        return "\n".join(lines)

    def s14_rate(self) -> str:
        lines = [format_header(2, "14. 无风险利率"), ""]
        df = self.rates
        if df is None or df.empty or "中国国债收益率10年" not in df.columns:
            lines.append("数据缺失\n")
            return "\n".join(lines)
        r = df.dropna(subset=["中国国债收益率10年"]).iloc[-1]
        lines.append(format_table(["指标", "数值", "日期"],
                                  [["中国国债收益率10年", f"{_num(r['中国国债收益率10年']):.2f}%", str(r["日期"])]],
                                  alignments=["l", "r", "l"]))
        return "\n".join(lines)

    def s15_repurchase(self) -> str:
        return format_header(2, "15. 股票回购") + "\n\n⚠️ 占位符：AkShare 采集器未采集\n"

    def s16_pledge(self) -> str:
        return format_header(2, "16. 股权质押") + "\n\n⚠️ 占位符：AkShare 采集器未采集\n"

    def s17_derived(self) -> str:
        lines = [format_header(2, "17. 衍生指标（Python 预计算）"), "",
                 "> 以下指标基于 §1-§16 原始数据确定性计算。Phase 3 可直接引用，单位: 百万元。", ""]
        price = self.spot.get("price")
        ts = self.total_share()
        mv = self.spot.get("total_mv")
        if mv is None and price and ts:
            mv = price * ts
        rows = [["当前股价 (元)", f"{price:.2f}" if price else "—"]]
        if ts:
            rows.append(["总股本 (亿股)", f"{ts / 1e8:,.2f}"])
        if mv:
            rows.append(["总市值 (百万元)", format_number(mv, divider=1e6)])
            rows.append(["总市值 (亿元)", f"{mv / 1e8:,.0f}"])
        if price:
            rows.append(["PE (估算)", f"{self.spot.get('pe')}" if self.spot.get("pe") else "—"])
            rows.append(["PB (估算)", f"{self.spot.get('pb')}" if self.spot.get("pb") else "—"])
        lines.append(format_table(["指标", "数值"], rows, alignments=["l", "r"]))
        lines.append("")

        # 10年股价分位
        if self.weekly is not None and not self.weekly.empty and price:
            wmin, wmax = self.weekly["最低"].min(), self.weekly["最高"].max()
            pos = (price - wmin) / (wmax - wmin) * 100 if wmax > wmin else None
            lines.append(format_table(["指标", "数值"], [
                ["10年最低价", f"{wmin:.2f}"], ["10年最高价", f"{wmax:.2f}"],
                ["当前价10年分位", f"{pos:.1f}%" if pos is not None else "—"]],
                alignments=["l", "r"]))
            lines.append("")

        # Rf / 门槛 II
        rf = None
        if self.rates is not None and not self.rates.empty and "中国国债收益率10年" in self.rates.columns:
            rf = _num(self.rates.dropna(subset=["中国国债收益率10年"]).iloc[-1]["中国国债收益率10年"])
        if rf is not None:
            ii = max(3.5, rf + 2.0)
            lines.append(format_table(["指标", "数值"], [
                ["Rf (中国10年国债)", f"{rf:.2f}%"],
                ["门槛 II = max(3.5%, Rf+2%)", f"{ii:.2f}%"]], alignments=["l", "r"]))
            lines.append("")

        # 支付率 M（法1: 年度 DPS（中报+年报）/ 年度 EPS，近3个完整财年）
        m_info = self.payout_ratio()
        if m_info:
            lines.append(format_table(["指标", "数值"], [
                ["支付率 M (法1, 近3年均值)", f"{m_info['m'] * 100:.1f}%"],
                ["年度 DPS 序列 (元)", " / ".join(f"{d:.2f}" for d in m_info["dps_list"])],
                ["年度 M 序列", " / ".join(f"{v * 100:.1f}%" for v in m_info["m_list"])]],
                alignments=["l", "r"]))
            lines.append("")

        # 主口径穿透回报率 R*（打折净利润 × 最低支付率）
        r_star_ = None
        income = self.annual.get("income")
        if income is not None and not income.empty and mv and m_info:
            np_ = _get(income, len(income) - 1, "PARENT_NETPROFIT")
            if np_:
                k_ = 0.8  # 利润折扣系数（默认0.8；可预测性高0.9/中0.8/低0.7，保守方向取小值）
                r_star_ = np_ * k_ * m_info["m"] / mv * 100
                r_ = np_ * m_info["m"] / mv * 100
                lines.append(format_table(["指标", "数值"], [
                    ["最新年度归母净利润 (百万元)", format_number(np_, divider=1e6)],
                    ["主口径 R* = 归母净利×k×M/市值（k=0.8 默认）", f"{r_star_:.2f}%"],
                    ["账面口径 R = 归母净利×M/市值（交叉校验）", f"{r_:.2f}%"]], alignments=["l", "r"]))
                lines.append("")

        # 现金校验口径 GG（AA = 真实可支配现金结余，降级代理 = 自由现金流 FCF）
        cf = self.annual.get("cashflow")
        fcf_series = []
        if cf is not None and not cf.empty:
            for i in range(len(cf)):
                ocf = _get(cf, i, "NETCASH_OPERATE")
                capex = _get(cf, i, "CONSTRUCT_LONG_ASSET")
                if ocf is not None and capex is not None:
                    fcf_series.append(ocf - capex)
        if fcf_series and mv and m_info:
            aa_2y = sum(fcf_series[-2:]) / 2
            aa_all = sum(fcf_series) / len(fcf_series)
            gg = aa_2y * m_info["m"] / mv * 100
            rows = [["结余序列 (OCF−Capex, 百万元)", " / ".join(f"{v / 1e6:,.0f}" for v in fcf_series)],
                    ["AA_2y (近2年均值, 百万元)", f"{aa_2y / 1e6:,.0f}"],
                    ["AA_all (全部年份均值, 百万元)", f"{aa_all / 1e6:,.0f}"],
                    ["现金校验 GG = AA_2y×M/市值（校验口径）", f"{gg:.2f}%"]]
            if rf is not None:
                ii = max(3.5, rf + 2.0)
                if r_star_ is not None:
                    delta_c_ = r_star_ - gg
                    r_eff_ = gg if delta_c_ >= 2.0 else r_star_
                    rows.append(["现金校验偏差 Δc = R* − GG", f"{delta_c_:+.2f} pct（≥2pct → 降级为 GG）"])
                    rows.append(["有效口径 R_eff（默认 R*）", f"{r_eff_:.2f}%"])
                    rows.append(["目标买入价 = 股价×R_eff/II", f"{price * r_eff_ / 100 / (ii / 100):.2f} 元" if price else "—"])
                    rows.append(["门槛价格 = 股价×II/R_eff（下行保护参考：跌至此价回报率升至 R_eff²/II）", f"{price * (ii / 100) / (r_eff_ / 100):.2f} 元" if price else "—"])
            lines.append(format_table(["指标", "数值"], rows, alignments=["l", "r"]))
            lines.append("")

        # 净负债
        bal = self.annual.get("balance")
        if bal is not None and not bal.empty:
            sl = _get(bal, len(bal) - 1, "SHORT_LOAN") or 0
            ll = _get(bal, len(bal) - 1, "LONG_LOAN") or 0
            bp = _get(bal, len(bal) - 1, "BOND_PAYABLE") or 0
            cash = _get(bal, len(bal) - 1, "MONETARYFUNDS") or 0
            nd = sl + ll + bp - cash
            lines.append(format_table(["指标", "数值"], [
                ["净负债 (短借+长借+债券−货币资金)", format_number(nd, divider=1e6)]],
                alignments=["l", "r"]))
            lines.append("")

        lines.append("*注: M 三重校验、R/GG 网格、G 系数网格、λ 敏感性等完整 §17 网格由 Tushare 版（tushare_collector.py）"
                     "提供；本降级数据包仅预计算基础衍生指标，Phase 3 按 phase3_quantitative.md 降级路径执行。*")
        return "\n".join(lines)

    def payout_ratio(self):
        """支付率 M（法1: 年度 DPS / 年度 EPS）。返回 dict 或 None。"""
        div = self._div()
        if div is None or div.empty:
            return None
        div = div.copy()
        div["报告期"] = div["报告期"].astype(str)
        full = div[div["报告期"].str.endswith("12-31")]
        if full.empty:
            return None
        full = full.sort_values("报告期")
        yearly = {}
        for _, r in full.iterrows():
            year = r["报告期"][:4]
            dps = (_num(r.get("现金分红-现金分红比例")) or 0) / 10.0
            eps = _num(r.get("每股收益"))
            if year in yearly:
                yearly[year]["dps"] += dps
                if eps:
                    yearly[year]["eps"] = eps
            else:
                yearly[year] = {"dps": dps, "eps": eps}
        # 合并同年度中期分红（报告期为 06-30）
        interim = div[div["报告期"].str.endswith("06-30")]
        for _, r in interim.iterrows():
            year = r["报告期"][:4]
            if year in yearly:
                yearly[year]["dps"] += (_num(r.get("现金分红-现金分红比例")) or 0) / 10.0
        m_list, dps_list = [], []
        for year in sorted(yearly)[-3:]:
            y = yearly[year]
            if y["eps"] and y["dps"] > 0:
                m_list.append(y["dps"] / y["eps"])
                dps_list.append(y["dps"])
        if not m_list:
            return None
        return {"m": sum(m_list) / len(m_list), "m_list": m_list, "dps_list": dps_list}
    def _statement_table(self, title, key, fields, extra=None) -> str:
        lines = [format_header(2, title), ""]
        df = self.annual.get(key)
        if df is None or df.empty:
            lines.append("数据缺失\n")
            return "\n".join(lines)
        head = ["项目"] + [str(d)[:4] for d in df[REPORT_YEAR_COL]]
        rows = []
        for label, col in fields:
            if col not in df.columns:
                continue
            rows.append([label] + [_fmt(_get(df, i, col)) for i in range(len(df))])
        if extra:
            e = extra(df, len(df) - 1)
            if e:
                rows.extend(e)
        lines.append(format_table(head, rows, alignments=["l"] + ["r"] * (len(head) - 1)))
        return "\n".join(lines)


def collect(ts_code: str, refresh_market: bool = False) -> str:
    """AkShare 采集程序化入口：返回 data_pack_market.md 文本（不写文件）。

    Args:
        ts_code: Tushare 风格代码，如 600941.SH / 000858.SZ。
        refresh_market: 是否全量重采（AkShare 降级模式不支持增量刷新）。

    Returns:
        str: 数据包 Markdown 全文。

    Raises:
        ValueError: 代码非法或非 A 股。
    """
    ts_code = normalize_code(ts_code)
    if not ts_code.endswith((".SH", ".SZ", ".BJ")):
        raise ValueError(f"AkShare 采集器目前仅支持 A 股（收到 {ts_code}）。港股/美股请使用 tushare_collector.py（需 TUSHARE_TOKEN）。")
    c = AkshareCollector()
    c.code = ts_code
    c.s6 = symbol6(ts_code)
    if refresh_market:
        print("  ⚠️ AkShare 降级模式不支持增量刷新，执行全量采集")
    c.fetch_all()
    # 行情源（东财/新浪）限流时自动重试，提升降级模式成功率
    for attempt in range(1, 3):
        missing = []
        if c.daily_1y is None or c.daily_1y.empty:
            missing.append("日线")
        if c.weekly is None or c.weekly.empty:
            missing.append("周线")
        if not missing:
            break
        print(f"  ⚠️ 行情缺失（{'、'.join(missing)}），15 秒后重试（第 {attempt}/2 次）...")
        time.sleep(15)
        if c.daily_1y is None or c.daily_1y.empty:
            c.fetch_daily_1y()
        if c.weekly is None or c.weekly.empty:
            c.fetch_weekly()
        if c.spot.get("price") is None:
            c.fetch_basic_snapshot()
    return c.build()


def main():
    ap = argparse.ArgumentParser(description="AkShare data collector (Tushare fallback)")
    ap.add_argument("--code", required=True, help="股票代码，如 600941 / 600941.SH / 000858.SZ")
    ap.add_argument("--output", default=None, help="输出文件路径")
    ap.add_argument("--refresh-market", action="store_true",
                    help="全量重采（AkShare 模式不支持增量刷新）")
    args = ap.parse_args()

    try:
        ts_code = normalize_code(args.code)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        data_pack = collect(ts_code, refresh_market=args.refresh_market)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    out = args.output or f"output/{ts_code}/data_pack_market.md"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(data_pack)
    print(f"Output written to {out}")
    print(f"File size: {os.path.getsize(out):,} bytes")
