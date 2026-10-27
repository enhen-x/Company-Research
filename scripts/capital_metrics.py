"""Optional, source-linked invested-capital bridges; no data acquisition or files.

Amounts share one explicit unit/currency, consolidated scope and accounting basis.
Operating assets exclude cash/ROU/goodwill where those are separate components;
financing debt excludes leases and non-operating assets exclude all cash.
Only a reconciled, complete bridge supplies capital to ROIC/ROIIC calculations.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from research_models import Context, iso_date, number

PATH = "decision.capital_metrics"
OPERATING_KEYS = (
    "operating_current_assets_ex_cash", "unrestricted_operating_cash", "restricted_operating_cash",
    "operating_current_liabilities_non_interest", "net_ppe_ex_rou", "intangibles_ex_goodwill",
    "goodwill", "lease_rou_assets", "other_operating_noncurrent_assets",
    "operating_noncurrent_liabilities_non_interest",
)
FINANCING_KEYS = (
    "equity_parent", "non_controlling_interests", "interest_bearing_debt_ex_leases",
    "lease_liabilities", "excess_unrestricted_cash", "restricted_non_operating_cash",
    "non_operating_assets_ex_cash",
)
META_KEYS = ("entity", "unit", "currency", "scope", "basis")
POLICIES = {
    "goodwill_policy": ("include", "exclude"),
    "lease_policy": ("capitalized",),
    "non_controlling_interest_policy": ("include_consolidated",),
    "restricted_cash_policy": ("classified_operating_or_non_operating_never_excess",),
    "acquisition_basis": ("none", "reported_total", "organic_adjusted"),
    "nopat_basis": ("consolidated_operating_after_tax",),
}


def _status(ctx: Context, start: int) -> str:
    findings = ctx.findings[start:]
    return "INVALID" if any(f["severity"] == "ERROR" for f in findings) else "INCOMPLETE" if findings else "OK"


def _text(raw: Mapping[str, Any], key: str, ctx: Context, path: str) -> str | None:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        ctx.warn("decision", "capital_metadata_missing", f"投入资本需要明确{key}口径", f"{path}.{key}")
        return None
    return value


def _object(raw: Mapping[str, Any], key: str, ctx: Context, path: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if value is None:
        ctx.warn("decision", "capital_bridge_missing", "已提供投入资本桥但必要部分缺失", f"{path}.{key}")
        return {}
    if not isinstance(value, Mapping):
        ctx.error("decision", "capital_bridge_type", "投入资本桥各部分必须为对象", f"{path}.{key}")
        return {}
    return value


def _refs(raw: Mapping[str, Any], keys: tuple[str, ...], ctx: Context, path: str, inherited: list[str]) -> list[str]:
    literal = any(raw.get(key) is not None and not isinstance(raw[key], Mapping) for key in keys)
    refs = ctx.refs(raw, "decision", path, required=literal and not inherited)
    for key in keys:
        if isinstance(raw.get(key), Mapping) and isinstance(raw[key].get("ref"), str):
            refs.append(raw[key]["ref"])
    return sorted(set(inherited + refs))


def capital_value(raw: Mapping[str, Any], key: str, ctx: Context, path: str,
                  metadata: Mapping[str, Any], period: str | None, *, nonnegative: bool = False, required: bool = True) -> float | int | None:
    value = raw.get(key)
    result = ctx.value(raw, key, "decision", path, nonnegative=nonnegative, required=required,
                       unit=metadata.get("unit"), period=period)
    if isinstance(value, Mapping) and isinstance(value.get("ref"), str):
        record = ctx.registry.get(value["ref"], {})
        for name, expected in (("period", period), *((name, metadata.get(name)) for name in META_KEYS)):
            if record and record.get(name) is None:
                ctx.warn("decision", "capital_reference_metadata_missing", f"资本分项引用缺少{name}口径", f"{path}.{key}")
            elif record and expected is not None and record.get(name) != expected:
                ctx.error("decision", "capital_reference_metadata_mismatch", f"资本分项引用的{name}与桥口径不同", f"{path}.{key}")
                result = None
    return result


def _values(raw: Mapping[str, Any], keys: tuple[str, ...], ctx: Context, path: str,
            metadata: Mapping[str, Any], period: str | None) -> dict[str, Any]:
    result = {}
    for key in keys:
        result[key] = capital_value(raw, key, ctx, path, metadata, period,
                                    nonnegative=key not in {"equity_parent", "non_controlling_interests"})
    return result


def _periods(raw: Mapping[str, Any], ctx: Context, path: str, begin: str | None, end: str | None) -> dict[str, Any]:
    periods = _object(raw, "periods", ctx, path)
    output = {key: _text(periods, key, ctx, f"{path}.periods") for key in ("nopat_period", "prior_nopat_period")}
    for key in ("nopat_start", "nopat_end", "prior_nopat_start", "prior_nopat_end"):
        output[key] = iso_date(periods.get(key))
        if output[key] is None:
            ctx.warn("decision", "capital_period_missing", "NOPAT流量必须给出真实起止日期", f"{path}.periods.{key}")
    dates = [output[key] for key in ("nopat_start", "nopat_end", "prior_nopat_start", "prior_nopat_end")]
    if all(dates) and begin and end:
        current_start, current_end, prior_start, prior_end = map(date.fromisoformat, dates)
        if current_start > current_end or prior_start > prior_end:
            ctx.error("decision", "capital_period_invalid", "NOPAT会计期起止日期倒置", f"{path}.periods")
        elif (current_start != date.fromisoformat(begin) + timedelta(days=1) or output["nopat_end"] != end
              or output["prior_nopat_end"] != begin or abs((current_end-current_start).days - (prior_end-prior_start).days) > 1):
            ctx.warn("decision", "capital_period_incomparable", "NOPAT会计期须与开闭资本匹配，前后NOPAT须为相同长度的可比期间；不自动年化或补期", f"{path}.periods")
        if (current_end-current_start).days not in range(300, 431):
            ctx.warn("decision", "capital_period_not_annual", "本桥仅解释约一年的ROIC；长短期间需另行定义，不能默认年度回报", f"{path}.periods")
    return output


def invested_capital_bridge(metrics: Mapping[str, Any], ctx: Context) -> dict[str, Any] | None:
    """Absent optional bridge preserves legacy inputs; a supplied bridge is strict."""
    if "invested_capital_bridge" not in metrics:
        return None
    start = len(ctx.findings)
    path = f"{PATH}.invested_capital_bridge"
    raw = _object(metrics, "invested_capital_bridge", ctx, PATH)
    metadata = {key: _text(raw, key, ctx, path) for key in META_KEYS}
    entity = ctx.config.get("facts", {}).get("entity", {}) if isinstance(ctx.config.get("facts"), Mapping) else {}
    if isinstance(entity, Mapping) and metadata["entity"] is not None and entity.get("id") != metadata["entity"]:
        ctx.error("decision", "capital_entity_mismatch", "资本桥实体与事实登记主体不同", path)
    if metadata["scope"] is not None and metadata["scope"] != "consolidated":
        ctx.warn("decision", "capital_scope_unsupported", "本桥仅支持合并范围，不能将母公司权益与合并经营资产混算", path)
    for key in META_KEYS:
        if key in metrics and metrics[key] != metadata[key]:
            ctx.error("decision", "capital_metadata_mismatch", f"资本回报输入与资本桥的{key}口径不同", f"{PATH}.{key}")
    policies = {}
    for key, allowed in POLICIES.items():
        policies[key] = _text(raw, key, ctx, path)
        if policies[key] is not None and policies[key] not in allowed:
            ctx.warn("decision", "capital_policy_unsupported", f"{key}尚未建立可计算口径，支持{', '.join(allowed)}", f"{path}.{key}")
    for key in ("classification_note", "acquisition_note", "nopat_adjustment_note"):
        _text(raw, key, ctx, path)
    if raw.get("nopat_lease_consistent") is not True:
        ctx.warn("decision", "capital_lease_nopat_unconfirmed", "需确认NOPAT与资本化租赁一致；不能只加租赁资产/债务而不调整盈利", f"{path}.nopat_lease_consistent")
    tolerance = raw.get("absolute_tolerance", 1e-6)
    if not number(tolerance) or tolerance < 0:
        ctx.error("decision", "capital_tolerance_invalid", "资本桥绝对对账容差必须为有限非负数，单位与资本一致", f"{path}.absolute_tolerance")
        tolerance = None
    inherited = ctx.refs(raw, "decision", path, required=False)
    snapshots = {}
    for label in ("begin", "end"):
        snap_start = len(ctx.findings)
        snapshot = _object(raw, label, ctx, path)
        snap_path = f"{path}.{label}"
        snapshot_date = iso_date(snapshot.get("date"))
        if snapshot_date is None:
            ctx.warn("decision", "capital_snapshot_date_missing", "资本存量必须有有效时点", f"{snap_path}.date")
        elif ctx.as_of is not None and snapshot_date > ctx.as_of:
            ctx.warn("decision", "capital_snapshot_after_as_of", "资本时点晚于研究as_of，不能当作已实现资本", f"{snap_path}.date")
        window = iso_date(metrics.get("window_start" if label == "begin" else "window_end"))
        if window is not None and snapshot_date is not None and window != snapshot_date:
            ctx.error("decision", "capital_window_mismatch", "旧资本窗口与桥时点不同", snap_path)
        for key in META_KEYS:
            if key in snapshot and snapshot[key] != metadata[key]:
                ctx.error("decision", "capital_metadata_mismatch", f"资本快照{key}口径不一致", f"{snap_path}.{key}")
        values, refs = {}, []
        for side, keys in (("operating", OPERATING_KEYS), ("financing", FINANCING_KEYS)):
            side_raw = _object(snapshot, side, ctx, snap_path)
            side_path = f"{snap_path}.{side}"
            for key in META_KEYS:
                if key in side_raw and side_raw[key] != metadata[key]:
                    ctx.error("decision", "capital_metadata_mismatch", f"资本分项{key}口径不一致", f"{side_path}.{key}")
            refs.extend(_refs(side_raw, keys, ctx, side_path, inherited))
            values[side] = _values(side_raw, keys, ctx, side_path, metadata, snapshot_date)
        operating, financing = values["operating"], values["financing"]
        op_total = fin_total = None
        if all(value is not None for value in (*operating.values(), *financing.values())) and policies["goodwill_policy"] in {"include", "exclude"}:
            op_total = (sum(operating[key] for key in OPERATING_KEYS if key not in {"operating_current_liabilities_non_interest", "operating_noncurrent_liabilities_non_interest", "goodwill"})
                        - operating["operating_current_liabilities_non_interest"] - operating["operating_noncurrent_liabilities_non_interest"]
                        + (operating["goodwill"] if policies["goodwill_policy"] == "include" else 0))
            fin_total = (financing["equity_parent"] + financing["non_controlling_interests"] + financing["interest_bearing_debt_ex_leases"] + financing["lease_liabilities"]
                         - financing["excess_unrestricted_cash"] - financing["restricted_non_operating_cash"] - financing["non_operating_assets_ex_cash"]
                         - (operating["goodwill"] if policies["goodwill_policy"] == "exclude" else 0))
            if not number(op_total) or not number(fin_total):
                ctx.error("decision", "capital_calculation_nonfinite", "资本双桥计算溢出，保留null", snap_path)
                op_total = fin_total = None
        residual = op_total-fin_total if op_total is not None and fin_total is not None else None
        if residual is not None and not number(residual):
            ctx.error("decision", "capital_calculation_nonfinite", "资本对账残差溢出，保留null", snap_path)
            residual = None
        if residual is not None and tolerance is not None and abs(residual) > tolerance:
            ctx.error("decision", "capital_bridge_unreconciled", "经营桥与融资桥不相等；检查资产分类、合并范围和重复计入", snap_path)
        snap_status = _status(ctx, snap_start)
        snapshots[label] = {"status": snap_status, "date": snapshot_date, "operating_components": operating, "financing_components": financing,
                            "operating_invested_capital": op_total, "financing_invested_capital": fin_total, "residual": residual,
                            "reconciled_invested_capital": op_total if snap_status == "OK" and residual is not None else None, "evidence_refs": sorted(set(refs))}
    begin, end = snapshots["begin"]["date"], snapshots["end"]["date"]
    if begin and end and begin >= end:
        ctx.error("decision", "capital_window_invalid", "资本桥期初必须早于期末", path)
    periods = _periods(raw, ctx, path, begin, end)
    status = _status(ctx, start)
    if status != "OK":
        for snapshot in snapshots.values():
            snapshot["reconciled_invested_capital"] = None
    return {"status": status, "metadata": metadata, "policies": policies, "periods": periods, "absolute_tolerance": tolerance,
            "tolerance_origin": "explicit" if "absolute_tolerance" in raw else "default_numeric_parameter",
            "evidence_refs": sorted(set(inherited + [ref for snap in snapshots.values() for ref in snap["evidence_refs"]])), **snapshots,
            "limitations": "口径说明与引用可解析不等于底层会计分类已经独立验证；并购口径为reported_total时ROIIC包含并购，不代表有机回报"}


def reinvestment_check(metrics: Mapping[str, Any], ctx: Context, capital: Mapping[str, Any], bridge: Mapping[str, Any] | None,
                       nopat: float | int | None, prior_nopat: float | int | None) -> dict[str, Any] | None:
    if "reinvestment_check" not in metrics:
        return None
    start = len(ctx.findings)
    path = f"{PATH}.reinvestment_check"
    raw = _object(metrics, "reinvestment_check", ctx, PATH)
    refs = _refs(raw, ("net_reinvestment",), ctx, path, [])
    metadata = bridge.get("metadata", {}) if bridge else {}
    periods = bridge.get("periods", {}) if bridge else {}
    net = capital_value(raw, "net_reinvestment", ctx, path, metadata, periods.get("nopat_period"))
    if not bridge or bridge.get("status") != "OK":
        ctx.warn("decision", "reinvestment_capital_basis_missing", "再投资互验需要已核对的资本桥、会计期及调整口径", path)
    if raw.get("steady_state") is not True:
        ctx.warn("decision", "reinvestment_steady_state_unconfirmed", "g≈再投资率×资本回报需要明确稳态及同期间假设", path)
    _text(raw, "assumption_note", ctx, path)
    for key in META_KEYS:
        if key in raw and raw[key] != metadata.get(key):
            ctx.error("decision", "capital_metadata_mismatch", f"再投资的{key}与资本桥口径不同", f"{path}.{key}")
    if "period" in raw and raw["period"] != periods.get("nopat_period"):
        ctx.error("decision", "reinvestment_period_mismatch", "再投资会计期与NOPAT会计期不同，不能跨期互验", f"{path}.period")
    if net is not None and net < 0:
        ctx.warn("decision", "negative_reinvestment", "负再投资代表资本释放，不能套普通扩张稳态增长关系", path)
    method = raw.get("return_metric")
    if not isinstance(method, str) or method not in {"roic", "roiic"}:
        ctx.error("decision", "reinvestment_return_metric_invalid", "互验return_metric必须明确为roic或roiic", path)
        method = None
    tolerance = raw.get("growth_tolerance", 0.01)
    if not number(tolerance) or tolerance < 0:
        ctx.error("decision", "reinvestment_tolerance_invalid", "增长差异容差必须为有限非负小数", path)
        tolerance = None
    if prior_nopat is None or prior_nopat <= 0:
        ctx.warn("decision", "reinvestment_nonpositive_base_nopat", "基期NOPAT缺失或非正，再投资率和增长率不作普通解释", path)
    selected_return = capital.get(method, {}).get("value") if method else None
    rate = net / prior_nopat if net is not None and prior_nopat is not None and prior_nopat > 0 else None
    actual_growth = (nopat-prior_nopat)/prior_nopat if nopat is not None and prior_nopat is not None and prior_nopat > 0 else None
    implied_growth = rate*selected_return if rate is not None and selected_return is not None else None
    gap = actual_growth-implied_growth if actual_growth is not None and implied_growth is not None else None
    if any(value is not None and not number(value) for value in (rate, actual_growth, implied_growth, gap)):
        ctx.error("decision", "reinvestment_calculation_nonfinite", "再投资增长互验计算溢出，保留null", path)
        rate = actual_growth = implied_growth = gap = None
    if gap is not None and tolerance is not None and abs(gap) > tolerance:
        ctx.warn("decision", "reinvestment_growth_mismatch", "稳态增长互验不一致；检查投入时滞、并购、减值和资本效率变化", path)
    status = _status(ctx, start)
    if implied_growth is None and status == "OK":
        ctx.warn("decision", "reinvestment_return_missing", "所选资本回报不可解释，停止增长互验", path)
        status = "INCOMPLETE"
    identity = method == "roiic" and net is not None and net == capital.get("roiic", {}).get("delta_invested_capital")
    return {"status": status, "net_reinvestment": net, "base_nopat": prior_nopat, "reinvestment_rate": rate,
            "metadata": metadata, "period": periods.get("nopat_period"),
            "return_metric": method, "capital_return": selected_return, "actual_nopat_growth": actual_growth,
            "implied_growth": implied_growth if status == "OK" else None, "growth_gap": gap, "growth_tolerance": tolerance,
            "interpretation": "ACCOUNTING_IDENTITY_NOT_INDEPENDENT_VALIDATION" if identity else "STEADY_STATE_DIAGNOSTIC_ONLY",
            "evidence_refs": refs}
