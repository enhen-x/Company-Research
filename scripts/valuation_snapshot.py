"""Strict, offline adapter for the known A-share B2 CSV export contract.

No provider clients are imported. Eastmoney statement amounts are raw CNY;
B2 profile values are raw CNY, CNY/share and shares. Unsupported schemas are
rejected rather than inferred from numeric magnitudes.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import re

import pandas as pd


MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_CSV_BYTES = 32 * 1024 * 1024
MAX_ROWS = 20000
SOURCES = {
    "利润表_按报告期.csv": {"利润表", "akshare.stock_profit_sheet_by_report_em"},
    "资产负债表_按报告期.csv": {"资产负债表", "akshare.stock_balance_sheet_by_report_em"},
    "现金流量表_按报告期.csv": {"现金流量表", "akshare.stock_cash_flow_sheet_by_report_em"},
    "主要财务指标_按报告期.csv": {"主要财务指标（按报告期）", "akshare.stock_financial_analysis_indicator_em", "fetch_sources.emweb_indicators"},
    "公司概况.csv": {"公司概况/现价/股本", "公司概况/现价/股本（腾讯实时降级）", "akshare.stock_individual_info_em", "fetch_sources.tencent_info"},
    "日线股价.csv": {"日线行情（不复权）", "日线行情（不复权）（腾讯降级）", "akshare.stock_zh_a_hist", "akshare.stock_zh_a_hist_tx"},
    "分红送配记录.csv": {"分红送配记录", "akshare.stock_fhps_detail_em"},
}
STATEMENTS = {
    "income": ("利润表_按报告期.csv", {
        "revenue": "OPERATE_INCOME", "n_income_attr_p": "PARENT_NETPROFIT",
        "basic_eps": "BASIC_EPS", "total_profit": "TOTAL_PROFIT", "income_tax": "INCOME_TAX",
        "int_exp": "FE_INTEREST_EXPENSE",
    }),
    "balance_sheet": ("资产负债表_按报告期.csv", {
        "st_borr": "SHORT_LOAN", "lt_borr": "LONG_LOAN", "bond_payable": "BOND_PAYABLE",
        "non_cur_liab_due_1y": "NONCURRENT_LIAB_1YEAR", "total_hldr_eqy_exc_min_int": "TOTAL_PARENT_EQUITY",
    }),
    "cashflow": ("现金流量表_按报告期.csv", {
        "n_cashflow_act": "NETCASH_OPERATE", "c_pay_acq_const_fiolta": "CONSTRUCT_LONG_ASSET",
        "c_pay_dist_dpcp_int_exp": "ASSIGN_DIVIDEND_PORFIT",
    }),
    "fina_indicators": ("主要财务指标_按报告期.csv", {"roe_waa": "ROEJQ"}),
}


class SnapshotError(ValueError):
    def __init__(self, code, detail, *, status="INVALID_INPUT", file=None):
        super().__init__(detail)
        self.payload = {"status": status, "code": code, "detail": detail}
        if file:
            self.payload["file"] = str(file)


def _bytes(path: Path, limit: int) -> bytes:
    if not path.is_file():
        raise SnapshotError("MISSING_FILE", "Required snapshot file is missing", status="INSUFFICIENT_DATA", file=path)
    if path.stat().st_size > limit:
        raise SnapshotError("READ_LIMIT", f"File exceeds {limit} bytes", file=path)
    with path.open("rb") as handle:
        content = handle.read(limit + 1)
    if len(content) > limit:
        raise SnapshotError("READ_LIMIT", f"File exceeds {limit} bytes", file=path)
    return content


def load_json_object(path: Path) -> dict:
    try:
        obj = json.loads(_bytes(Path(path), MAX_JSON_BYTES).decode("utf-8-sig"),
                         parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except SnapshotError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise SnapshotError("INVALID_JSON", str(exc), file=path) from exc
    if not isinstance(obj, dict):
        raise SnapshotError("INVALID_JSON_ROOT", "JSON root must be an object", file=path)
    pending = [(obj, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise SnapshotError("JSON_DEPTH", f"JSON exceeds {MAX_JSON_DEPTH} nesting levels", file=path)
        if isinstance(value, (dict, list)):
            children = value.values() if isinstance(value, dict) else value
            pending.extend((child, depth + 1) for child in children)
        elif isinstance(value, float) and not math.isfinite(value):
            raise SnapshotError("INVALID_JSON", "JSON numbers must be finite", file=path)
    return obj


def _number(value, field, *, required=False):
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise SnapshotError("MISSING_NUMBER", f"Missing {field}", status="INSUFFICIENT_DATA")
        return None
    if isinstance(value, bool):
        raise SnapshotError("INVALID_NUMBER", f"Boolean {field}")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise SnapshotError("INVALID_NUMBER", f"Non-numeric {field}: {value!r}") from exc
    if not math.isfinite(result):
        raise SnapshotError("INVALID_NUMBER", f"Non-finite {field}")
    return result


def _dates(values, field):
    try:
        result = pd.to_datetime(values, errors="coerce")
    except (TypeError, ValueError, OverflowError) as exc:
        raise SnapshotError("INVALID_PERIOD", f"Missing or invalid {field}") from exc
    if result.isna().any() or not pd.api.types.is_datetime64_dtype(result.dtype):
        raise SnapshotError("INVALID_PERIOD", f"Missing or invalid {field}")
    return result


class ValuationSnapshot:
    """Minimal valuation client backed solely by a current B2 batch directory."""

    def __init__(self, batch_dir, ts_code=None, contract=None):
        self.batch_dir = Path(batch_dir).resolve()
        self._store = {}
        self.limitations = []
        self.files = {}
        self._currency = "CNY"
        self._fy_end_month = 12
        manifest = load_json_object(self.batch_dir / "data" / "拉取清单.json")
        stock = manifest.get("stock")
        if not isinstance(stock, dict) or not re.fullmatch(r"(?:SH|SZ)\.[0-9]{6}", str(stock.get("symbol", ""))):
            raise SnapshotError("UNSUPPORTED_MARKET_OR_IDENTITY", "Known SH/SZ A-share B2 stock identity is required")
        market, code = stock["symbol"].split(".")
        self.ts_code = code + "." + market
        if str(stock.get("code", "")) != code or (ts_code and ts_code != self.ts_code):
            raise SnapshotError("STOCK_MISMATCH", "Requested stock and B2 manifest disagree")
        if not ((market == "SH" and code.startswith("6")) or (market == "SZ" and code.startswith(("0", "3")))):
            raise SnapshotError("UNSUPPORTED_MARKET_OR_IDENTITY", "Only known SH/SZ ordinary A-share prefixes are supported")
        self.name = stock.get("name", "")
        try:
            timestamp = manifest["started_at"]
            if not isinstance(timestamp, str) or not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T|\s)", timestamp):
                raise ValueError("an explicit ISO collection timestamp is required")
            self.collected_at = pd.Timestamp(timestamp)
            if pd.isna(self.collected_at):
                raise ValueError("missing timestamp")
            self.asof = self.collected_at.tz_localize(None).normalize()
        except (KeyError, TypeError, ValueError) as exc:
            raise SnapshotError("UNKNOWN_SNAPSHOT_DATE", "B2 started_at must identify the collection date") from exc
        datasets = manifest.get("datasets")
        if not isinstance(datasets, list) or any(not isinstance(row, dict) for row in datasets):
            raise SnapshotError("INVALID_MANIFEST", "datasets must be a list of objects")
        self._datasets = {}
        for row in datasets:
            filename = row.get("file")
            if not isinstance(filename, str) or not filename:
                raise SnapshotError("INVALID_MANIFEST", "Every dataset requires a nonempty string filename")
            if filename in self._datasets:
                raise SnapshotError("DUPLICATE_DATASET", f"Duplicate manifest file: {filename}")
            self._datasets[filename] = row
        for key, (filename, fields) in STATEMENTS.items():
            frame = self._statement(filename, fields, optional=key == "fina_indicators")
            self._store[key] = frame
        annual = [set(self._get_annual_df(key).get("end_date", [])) for key in ("income", "balance_sheet", "cashflow")]
        if not all(annual) or len({max(periods) for periods in annual if periods}) != 1:
            raise SnapshotError("ANNUAL_PERIOD_MISMATCH", "Three statements require the same latest annual period", status="INSUFFICIENT_DATA")
        self.latest_annual = max(annual[0])
        self._profile()
        self._prices()
        self._dividends()
        self._store["risk_free_rate"] = pd.DataFrame()
        if contract is not None:
            if not isinstance(contract, dict):
                raise SnapshotError("INVALID_CONTRACT", "Valuation contract must be an object")
            self._store["valuation_contract"] = contract
        self.limitations.append("Risk-free rate, ERP and beta are engine assumptions unless an explicit evidenced contract overrides the relevant discount rate.")
        self.limitations.append("Eastmoney FCFF_FORWARD/FCFF_BACK are not mapped to FCFF: their provider formula is not the explicit valuation cash-flow contract.")

    def _csv(self, filename, columns, *, optional=False):
        entry = self._datasets.get(filename)
        if entry is None or not isinstance(entry.get("status"), str) or entry.get("status") not in {"success", "cached"}:
            if optional:
                self.limitations.append(f"{filename}: no successful B2 dataset; unavailable, not zero.")
                return None
            raise SnapshotError("UNVERIFIED_DATASET", f"{filename}: successful B2 source is required", status="INSUFFICIENT_DATA")
        if not isinstance(entry.get("source"), str) or entry.get("source") not in SOURCES[filename]:
            raise SnapshotError("UNSUPPORTED_SOURCE", f"{filename}: source schema and units are not supported")
        path = self.batch_dir / "data" / filename
        content = _bytes(path, MAX_CSV_BYTES)
        digest = hashlib.sha256(content).hexdigest()
        if entry.get("sha256") and entry["sha256"] != digest:
            raise SnapshotError("HASH_MISMATCH", "CSV differs from its B2 manifest hash", file=path)
        if not entry.get("sha256"):
            self.limitations.append(f"{filename}: legacy manifest has no origin SHA-256; the current input fingerprint is recorded, but historical byte identity cannot be verified.")
        try:
            frame = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False,
                                usecols=lambda name: name in columns, nrows=MAX_ROWS + 1)
        except (ValueError, UnicodeError, pd.errors.ParserError) as exc:
            raise SnapshotError("INVALID_CSV", str(exc), file=path) from exc
        if frame.empty or len(frame) > MAX_ROWS:
            raise SnapshotError("CSV_SIZE_OR_SCHEMA", "Empty, unrecognized or excessive-row CSV", file=path)
        self.files[filename] = {"sha256": digest, "source": entry["source"], "rows": len(frame)}
        return frame

    def _statement(self, filename, fields, optional=False):
        metadata = {"SECUCODE", "SECURITY_CODE", "SECURITY_NAME_ABBR", "CURRENCY", "REPORT_DATE", "UNIT", "金额单位"}
        frame = self._csv(filename, set(fields.values()) | metadata, optional=optional)
        if frame is None:
            return pd.DataFrame(columns=["end_date", *fields])
        required = {"SECUCODE", "SECURITY_CODE", "CURRENCY", "REPORT_DATE"}
        if not required.issubset(frame.columns):
            raise SnapshotError("UNKNOWN_STATEMENT_IDENTITY_OR_UNITS", f"{filename}: missing identity, currency or report-period columns")
        code = self.ts_code.split(".")[0]
        if not frame["SECUCODE"].eq(self.ts_code).all() or not frame["SECURITY_CODE"].eq(code).all():
            raise SnapshotError("STOCK_MISMATCH", f"{filename}: mixed or conflicting stock identity")
        if not frame["CURRENCY"].eq("CNY").all():
            raise SnapshotError("CURRENCY_MISMATCH", f"{filename}: every statement row must explicitly be CNY")
        for column in ("UNIT", "金额单位"):
            if column in frame and not frame[column].isin(["元", "CNY", "raw"]).all():
                raise SnapshotError("UNKNOWN_AMOUNT_UNIT", f"{filename}: non-raw or missing explicit amount unit")
        dates = _dates(frame["REPORT_DATE"], filename + ".REPORT_DATE")
        if not dates.dt.strftime("%m%d").isin(["0331", "0630", "0930", "1231"]).all() or (dates > self.asof).any():
            raise SnapshotError("INVALID_PERIOD", f"{filename}: non-quarter or future report period")
        result = pd.DataFrame({"end_date": dates.dt.strftime("%Y%m%d")})
        for target, source in fields.items():
            result[target] = frame[source].map(lambda value: _number(value, filename + "." + source)) if source in frame else None
        if result["end_date"].duplicated().any():
            raise SnapshotError("DUPLICATE_PERIOD", f"{filename}: ambiguous duplicate report periods")
        if not self.name and "SECURITY_NAME_ABBR" in frame:
            self.name = frame["SECURITY_NAME_ABBR"].iloc[0]
        for column in fields:
            if result[column].isna().any():
                self.limitations.append(f"{filename}.{fields[column]}: missing values preserved as unknown; no zero or alternative subtotal used.")
        return result.sort_values("end_date", ascending=False).reset_index(drop=True)

    def _profile(self):
        frame = self._csv("公司概况.csv", {"item", "value"})
        if set(frame.columns) != {"item", "value"} or frame["item"].duplicated().any():
            raise SnapshotError("UNKNOWN_PROFILE_SCHEMA", "Known B2 item/value profile with unique labels is required")
        values = dict(zip(frame["item"], frame["value"]))
        for label in ("股票代码",):
            if label in values and values[label] != self.ts_code.split(".")[0]:
                raise SnapshotError("STOCK_MISMATCH", "Company profile stock code conflicts")
        basic = {"name": self.name}
        for target, label, divisor in (("close", "最新价", 1), ("total_mv", "总市值", 10000), ("total_share", "总股本", 10000)):
            value = _number(values.get(label), "公司概况.csv." + label, required=True)
            if value <= 0:
                raise SnapshotError("INVALID_PROFILE_VALUE", label + " must be positive")
            basic[target] = value / divisor
        for target, label in (("pe_ttm", "市盈率(TTM)"), ("pb", "市净率")):
            basic[target] = _number(values.get(label), "公司概况.csv." + label)
        self._store["basic_info"] = pd.DataFrame([basic])
        self.limitations.append(f"Profile collection date {self.asof.date()}; B2 profile does not echo the quote timestamp. Profile values are not promoted to an independently verified quote date.")
        source = self.files["公司概况.csv"]["source"]
        if "腾讯" in source or source == "fetch_sources.tencent_info":
            self.limitations.append("Tencent fallback profile total shares are derived upstream from rounded market cap / price; share-count precision is limited and is not an audited share-register observation.")

    def _prices(self):
        frame = self._csv("日线股价.csv", {"date", "close", "日期", "收盘", "股票代码"}, optional=True)
        if frame is None:
            self._store["weekly_prices"] = pd.DataFrame(columns=["trade_date", "close"])
            return
        if {"date", "close"}.issubset(frame):
            date_col, price_col = "date", "close"
        elif {"日期", "收盘", "股票代码"}.issubset(frame):
            date_col, price_col = "日期", "收盘"
            if not frame["股票代码"].eq(self.ts_code.split(".")[0]).all():
                raise SnapshotError("STOCK_MISMATCH", "Price CSV contains another stock")
        else:
            raise SnapshotError("UNKNOWN_PRICE_SCHEMA", "Unadjusted B2 price schema is required")
        dates = _dates(frame[date_col], "price.date")
        if (dates > self.asof).any() or dates.duplicated().any():
            raise SnapshotError("INVALID_PRICE_PERIOD", "Future or duplicate price dates")
        prices = frame[price_col].map(lambda value: _number(value, "price.close", required=True))
        if (prices <= 0).any():
            raise SnapshotError("INVALID_PRICE", "Prices must be positive")
        self._store["weekly_prices"] = pd.DataFrame({"trade_date": dates.dt.strftime("%Y%m%d"), "close": prices}).sort_values("trade_date", ascending=False)

    def _dividends(self):
        columns = {"报告期", "现金分红-现金分红比例", "总股本", "方案进度", "除权除息日"}
        frame = self._csv("分红送配记录.csv", columns, optional=True)
        rows = []
        if frame is not None:
            if not columns.issubset(frame):
                raise SnapshotError("UNKNOWN_DIVIDEND_SCHEMA", "Known per-ten-share B2 dividend schema is required")
            for _, row in frame.iterrows():
                if row["方案进度"] != "实施分配":
                    continue
                per_ten = _number(row["现金分红-现金分红比例"], "dividend.per_ten")
                if per_ten is None:
                    self.limitations.append("Implemented dividend record has no cash ratio; its cash distribution remains unknown and is excluded.")
                    continue
                period = _dates(pd.Series([row["报告期"]]), "dividend.fiscal_period").iloc[0]
                exdate = _dates(pd.Series([row["除权除息日"]]), "dividend.ex_date").iloc[0]
                if exdate > self.asof:
                    continue
                if period > exdate:
                    raise SnapshotError("INVALID_DIVIDEND_PERIOD", "Dividend ex-date precedes its fiscal period")
                if per_ten < 0:
                    raise SnapshotError("INVALID_DIVIDEND", "Cash DPS cannot be negative")
                shares = _number(row["总股本"], "dividend.shares")
                if shares is not None and shares <= 0:
                    raise SnapshotError("INVALID_DIVIDEND", "Dividend base shares must be positive when present")
                rows.append({"end_date": period.strftime("%Y%m%d"), "ex_date": exdate.strftime("%Y%m%d"), "cash_div_tax": per_ten / 10, "base_share": shares / 10000 if shares is not None else None})
        result = pd.DataFrame(rows, columns=["end_date", "ex_date", "cash_div_tax", "base_share"])
        if not result.empty and result.duplicated(["end_date", "ex_date"]).any():
            raise SnapshotError("DUPLICATE_DIVIDEND", "Ambiguous duplicate implemented dividend")
        self._store["dividends"] = result.sort_values("end_date", ascending=False)
        self.limitations.append("Only implemented dividends with an observed ex-date no later than collection date are used; B2 cash dividend per ten shares is divided by ten. Missing dividend rows do not establish zero distributions.")

    @staticmethod
    def _safe_float(value):
        if value is None or isinstance(value, bool):
            return None
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (ValueError, TypeError):
            return None

    def _get_annual_df(self, key):
        frame = self._store.get(key)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return pd.DataFrame()
        return frame.loc[frame["end_date"].str.endswith("1231")].sort_values("end_date", ascending=False).copy()

    def _get_annual_series(self, key, field):
        frame = self._get_annual_df(key)
        return [(str(row["end_date"])[:4], self._safe_float(row.get(field))) for _, row in frame.iterrows()]

    def _get_payout_by_year(self):
        payments = {}
        unknown = set()
        for _, row in self._store["dividends"].iterrows():
            year = row["end_date"][:4]
            dps, shares = self._safe_float(row["cash_div_tax"]), self._safe_float(row["base_share"])
            if dps is None or shares is None:
                unknown.add(year)
            else:
                payments[year] = payments.get(year, 0) + dps * shares * 10000
        profits = dict(self._get_annual_series("income", "n_income_attr_p"))
        return {year: payment / profits[year] * 100 for year, payment in sorted(payments.items(), reverse=True)
                if year not in unknown and profits.get(year) is not None and profits[year] > 0}

    def _unit_label(self):
        return "百万元"

    def _price_unit(self):
        return "元"

    def provenance_markdown(self):
        lines = ["## 当前批次离线快照", "", f"- 股票：{self.ts_code}；报表金额：原币 CNY 元；最近共同年报：{self.latest_annual}。",
                 f"- 复用 data/拉取清单.json 及 {len(self.files)} 个已识别 CSV；没有调用凭证或供应商接口。",
                 "- 公司概况映射：总市值元÷10000→万元，总股本股÷10000→万股；价格仍为元/股。", "",
                 "### 数据缺口与口径限制", ""]
        lines.extend("- " + text for text in self.limitations)
        lines.extend(["", "### 输入指纹", "", "| 文件 | SHA-256 | B2来源 |", "|---|---|---|"])
        lines.extend(f"| {name} | {entry['sha256']} | {entry['source']} |" for name, entry in sorted(self.files.items()))
        return "\n".join(lines) + "\n\n"
