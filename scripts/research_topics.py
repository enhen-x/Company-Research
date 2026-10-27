#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Source-linked, deterministic V3 research topics; no network or implied inputs.

Input: input/研究模型.json (schema_version=1).
Output: reports/研究模型_输出.json.  See evaluate_topics for the pure entry point.
All rates are decimal fractions.  Numeric drivers may be explicit numbers/null
with a registered source_ref, or {"ref": "registered fact/assumption id"}.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from research_models import ALIASES, PROFILES, Context, build_registry, canonical_method, iso_date, number, scan_nonfinite
from capital_metrics import capital_value, invested_capital_bridge, reinvestment_check
from run_support import atomic_json

SCHEMA_VERSION = 1
MAX_INPUT_BYTES = 10_000_000
MAX_INPUT_DEPTH = 128
MODULE_NAMES = ("industry", "guidance", "orders", "forecast", "theses", "decision")
COMPARABLE_FIELDS = ("entity", "scope", "period", "metric", "unit", "currency", "basis")


def validate_json_depth(value: Any, *, max_depth: int, label: str) -> None:
    """Iterative depth validation, independent of the process recursion limit."""
    iterators = [iter((value,))]
    while iterators:
        try:
            value = next(iterators[-1])
        except StopIteration:
            iterators.pop()
            continue
        if isinstance(value, (dict, list)):
            if len(iterators) > max_depth:
                raise ValueError(f"{label}嵌套超过{max_depth}层；请简化结构")
            iterators.append(iter(value.values() if isinstance(value, dict) else value))


def read_json_bounded(path: Path, *, max_bytes: int, max_depth: int, label: str) -> tuple[bytes, Any]:
    """Bound bytes before parsing, then enforce an explicit JSON depth contract."""
    error = f"{label}超过{max_bytes / 1_000_000:g}MB；请引用原始数据，勿嵌入全量历史"
    if path.stat().st_size > max_bytes:
        raise ValueError(error)
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(error)
    config = json.loads(raw.decode("utf-8-sig"))
    validate_json_depth(config, max_depth=max_depth, label=label)
    return raw, config


def read_input(path: Path) -> tuple[bytes, Any]:
    """Keep the research-input contract at 10 MB and 128 container levels."""
    return read_json_bounded(path, max_bytes=MAX_INPUT_BYTES, max_depth=MAX_INPUT_DEPTH, label="研究模型输入")


def _object(config: Mapping[str, Any], key: str, ctx: Context) -> Mapping[str, Any]:
    raw = config.get(key)
    if raw is None:
        ctx.warn(key, f"{key}_missing", "专题输入缺失", key)
        return {}
    if not isinstance(raw, Mapping):
        ctx.error(key, f"{key}_type", "专题输入必须为对象", key)
        return {}
    return raw


def _array(raw: Mapping[str, Any], key: str, ctx: Context, topic: str, path: str) -> list[Any]:
    value = raw.get(key)
    if value is None:
        ctx.warn(topic, f"{key}_missing", "列表输入缺失", f"{path}.{key}")
        return []
    if not isinstance(value, list):
        ctx.error(topic, f"{key}_type", "该字段必须为数组", f"{path}.{key}")
        return []
    return value


def _metadata(raw: Mapping[str, Any], fields: tuple[str, ...], ctx: Context, topic: str, path: str) -> bool:
    ok = True
    for key in fields:
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            ctx.warn(topic, "metadata_missing", f"缺少明确的{key}口径", f"{path}.{key}")
            ok = False
    return ok


def _driver_refs(raw: Mapping[str, Any], keys: tuple[str, ...], ctx: Context, topic: str, path: str) -> list[str]:
    """Any literal driver needs a registered provenance reference."""
    literal = any(key in raw and raw[key] is not None and not isinstance(raw[key], Mapping) for key in keys)
    refs = ctx.refs(raw, topic, path, required=literal)
    for key in keys:
        if isinstance(raw.get(key), Mapping) and isinstance(raw[key].get("ref"), str):
            refs.append(raw[key]["ref"])
    return sorted(set(refs))


def _range_rate(value: float | int | None, ctx: Context, topic: str, path: str) -> bool:
    if value is not None and not 0 <= value <= 1:
        ctx.error(topic, "rate_out_of_range", "比率采用小数且必须在[0,1]内", path)
        return False
    return value is not None


def _industry(config: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    raw = _object(config, "industry", ctx)
    name = raw.get("profile", raw.get("type", raw.get("name")))
    key = ALIASES.get(str(name).strip().lower(), str(name).strip().lower()) if name is not None else None
    order_based = raw.get("order_based")
    if order_based is None:
        order_applicability = "UNKNOWN"
        ctx.warn("industry", "order_applicability_unknown", "必须明确order_based，未填不等于非订单业务", "industry.order_based")
    elif not isinstance(order_based, bool):
        order_applicability = "UNKNOWN"
        ctx.error("industry", "order_flag_type", "order_based必须为布尔值或null", "industry.order_based")
    else:
        order_applicability = "APPLICABLE" if order_based else "NOT_APPLICABLE"
    if key not in PROFILES:
        ctx.warn("industry", "profile_unknown", "未知经济模型，不能默认普通企业DCF", "industry.profile")
        return ctx.finish("industry", profile=key, applicability="UNKNOWN", primary_method=None,
                          validation_method=None, allowed_primary_methods=[], allowed_validation_methods=[],
                          disabled_methods=[], order_applicability=order_applicability, financial=None)
    primary, validation, disabled, financial = PROFILES[key]
    selected_primary = canonical_method(raw.get("primary_method", primary[0]))
    selected_validation = canonical_method(raw.get("validation_method", validation[0]))
    for field, selected, allowed in (("primary_method", selected_primary, primary), ("validation_method", selected_validation, validation)):
        if selected in disabled:
            ctx.error("industry", "disabled_method_selected", "选中了该经济模型禁用的方法", f"industry.{field}")
        elif selected not in allowed:
            ctx.warn("industry", "method_outside_matrix", "方法未在该画像的已定义范围内，需要单独论证/建模", f"industry.{field}")
    return ctx.finish("industry", profile=key, applicability="FINANCIAL" if financial else "NON_FINANCIAL",
                      financial=financial, primary_method=selected_primary, validation_method=selected_validation,
                      allowed_primary_methods=list(primary), allowed_validation_methods=list(validation),
                      disabled_methods=list(disabled), order_applicability=order_applicability)


def _guidance_identity(record: Mapping[str, Any]) -> tuple[str, ...]:
    series = record.get("guidance_id", record.get("series_id"))
    core = tuple(str(record.get(key, "")) for key in ("entity", "scope", "period", "metric"))
    return ("series", str(series), *core) if series is not None else tuple(str(record.get(key, "")) for key in COMPARABLE_FIELDS)


def _comparable(a: Mapping[str, Any], b: Mapping[str, Any]) -> tuple[bool, list[str]]:
    differences = [key for key in COMPARABLE_FIELDS if not isinstance(a.get(key), str) or not a[key].strip()
                   or not isinstance(b.get(key), str) or not b[key].strip() or a[key] != b[key]]
    return not differences, differences


def _guidance(config: Mapping[str, Any], ctx: Context, as_of: str | None) -> dict[str, Any]:
    raw = _object(config, "guidance", ctx)
    if raw.get("disclosed") is not None and not isinstance(raw["disclosed"], bool):
        ctx.error("guidance", "guidance_disclosed_type", "disclosed必须是布尔值", "guidance.disclosed")
    if raw.get("disclosed") is False:
        if not isinstance(raw.get("reason"), str) or not raw["reason"].strip():
            ctx.warn("guidance", "nondisclosure_reason_missing", "未披露需说明查询范围/原因", "guidance.reason")
        refs = ctx.refs(raw, "guidance", "guidance", required=False)
        return ctx.finish("guidance", status="NOT_APPLICABLE", evidence_refs=refs, applicability="NOT_DISCLOSED", versions=[], series=[], actual_evaluation=[], initial_vs_last_valid=None)
    versions_raw = _array(raw, "versions", ctx, "guidance", "guidance")
    actuals_raw = raw.get("actuals", [raw["actual"]] if isinstance(raw.get("actual"), Mapping) else [])
    if not isinstance(actuals_raw, list):
        ctx.error("guidance", "actuals_type", "actuals必须为数组", "guidance.actuals")
        actuals_raw = []
    versions: list[dict[str, Any]] = []
    actuals: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    refs: list[str] = []
    ids: set[str] = set()
    for index, item in enumerate(versions_raw):
        path = f"guidance.versions[{index}]"
        if not isinstance(item, Mapping):
            ctx.error("guidance", "guidance_record_type", "指引版本必须为对象", path)
            continue
        record = dict(item)
        rid = record.get("id")
        if not isinstance(rid, str) or not rid or rid in ids:
            ctx.error("guidance", "guidance_id_invalid", "版本id必须为非空唯一字符串", path)
            continue
        ids.add(rid)
        published = iso_date(record.get("published_at"))
        if published is None:
            ctx.warn("guidance", "guidance_date_missing", "缺少有效发布日期", path)
        if as_of is not None and published is not None and published > as_of:
            excluded.append({"id": rid, "reason": "AFTER_AS_OF", "published_at": published})
            continue
        status = str(record.get("status", "")).lower()
        status = {"撤回": "withdrawn", "初始": "initial", "上调": "raised", "下调": "lowered", "维持": "maintained"}.get(status, status)
        if status not in {"initial", "raised", "lowered", "maintained", "withdrawn", "supplemental"}:
            ctx.error("guidance", "guidance_status_invalid", "指引版本状态不在规定枚举中", path)
        record["status"] = status
        record["published_at"] = published
        metadata_ok = _metadata(record, COMPARABLE_FIELDS, ctx, "guidance", path)
        record["metadata_complete"] = metadata_ok
        refs += ctx.refs(record, "guidance", path)
        refs += _driver_refs(record, ("lower", "upper"), ctx, "guidance", path)
        for key in ("lower", "upper"):
            record[key] = ctx.value(record, key, "guidance", path, required=status != "withdrawn", unit=record.get("unit"), period=record.get("period"))
        if record["lower"] is not None and record["upper"] is not None and record["lower"] > record["upper"]:
            ctx.error("guidance", "guidance_bounds_order", "指引下沿不能大于上沿", path)
        previous = record.get("previous_version_id")
        if previous is not None and (not isinstance(previous, str) or previous == rid):
            ctx.error("guidance", "guidance_previous_invalid", "previous_version_id必须指向其他已登记版本", path)
        end = iso_date(record.get("period_end"))
        record["timing"] = "POST_PERIOD" if end is not None and published is not None and published > end else "ADVANCE_OR_UNSPECIFIED"
        versions.append(record)
    for record in versions:
        previous = record.get("previous_version_id")
        if previous is not None and previous not in ids:
            ctx.error("guidance", "guidance_previous_unresolved", "前版本引用不存在", f"guidance.versions.{record['id']}")
    for index, item in enumerate(actuals_raw):
        path = f"guidance.actuals[{index}]"
        if not isinstance(item, Mapping):
            ctx.error("guidance", "actual_type", "实际结果必须为对象", path)
            continue
        record = dict(item)
        published = iso_date(record.get("published_at"))
        if published is None:
            ctx.warn("guidance", "actual_publication_missing", "实际值缺少公布日，不能证明as_of前可用", path)
            continue
        if as_of is not None and published > as_of:
            excluded.append({"id": record.get("id"), "reason": "ACTUAL_AFTER_AS_OF", "published_at": published})
            continue
        _metadata(record, COMPARABLE_FIELDS, ctx, "guidance", path)
        refs += _driver_refs(record, ("value",), ctx, "guidance", path)
        record["value"] = ctx.value(record, "value", "guidance", path, unit=record.get("unit"), period=record.get("period"))
        record["published_at"] = published
        actuals.append(record)
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for record in versions:
        groups.setdefault(_guidance_identity(record), []).append(record)
    series: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []
    for identity, group in sorted(groups.items()):
        ordered = sorted(group, key=lambda r: (r.get("published_at") or "", str(r["id"])))
        initial = next((r for r in ordered if r["status"] == "initial"), next((r for r in ordered if r["status"] != "withdrawn"), None))
        matching_actuals = [a for a in actuals if _guidance_identity(a) == identity or
                           (_guidance_identity(a)[0] != "series" and identity[0] != "series" and _comparable(group[0], a)[0])]
        actual = sorted(matching_actuals, key=lambda a: a["published_at"])[0] if matching_actuals else None
        events = [r for r in ordered if r.get("published_at") is not None and (actual is None or r["published_at"] < actual["published_at"])]
        last_event = events[-1] if events else None
        last_valid = last_event if last_event is not None and last_event["status"] != "withdrawn" else None
        current = ordered[-1] if ordered else None
        series_record = {"series_key": list(identity), "initial_id": initial["id"] if initial else None,
                         "last_valid_id": last_valid["id"] if last_valid else None,
                         "current_status": current["status"] if current else "UNAVAILABLE",
                         "withdrawn": bool(current and current["status"] == "withdrawn")}
        series.append(series_record)
        for label, record in (("initial", initial), ("last_valid", last_valid)):
            item = {"series_key": list(identity), "label": label, "version_id": record["id"] if record else None,
                    "actual": actual.get("value") if actual else None, "status": "UNAVAILABLE", "range": None}
            if record is None:
                item["status"] = "WITHDRAWN" if last_event and last_event["status"] == "withdrawn" else "UNAVAILABLE"
            elif actual is not None:
                comparable, differences = _comparable(record, actual)
                if record.get("published_at") is None or record["published_at"] >= actual["published_at"]:
                    ctx.warn("guidance", "guidance_post_results", "指引在实际结果公布时或之后发布，不作为提前预测兑现", f"guidance.{record['id']}")
                elif not comparable:
                    item["status"] = "INCOMPARABLE"
                    ctx.warn("guidance", "guidance_incomparable", "指引与实际值元数据未全齐或不一致: " + ",".join(differences), f"guidance.{record['id']}")
                elif record["lower"] is not None and record["upper"] is not None and actual["value"] is not None:
                    item["range"] = [record["lower"], record["upper"]]
                    item["status"] = "MET" if record["lower"] <= actual["value"] <= record["upper"] else "MISSED"
            if item["status"] in {"UNAVAILABLE", "INCOMPARABLE"}:
                ctx.warn("guidance", "guidance_evaluation_unavailable", "没有可比、可用的指引兑现评价", f"guidance.{label}")
            evaluations.append(item)
    if not groups:
        ctx.warn("guidance", "guidance_no_available_versions", "as_of前没有可评价版本", "guidance.versions")
    return ctx.finish("guidance", evidence_refs=sorted(set(refs)), versions=versions, excluded=excluded, series=series,
                      initial_vs_last_valid={"initial_id": series[0]["initial_id"], "last_valid_id": series[0]["last_valid_id"]} if len(series) == 1 else None,
                      actual_evaluation=evaluations)


def _order_bridge(raw: Mapping[str, Any], basis: str, ctx: Context, path: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("opening", "new_included", "fx_scope_adjustment", "fulfilled", "cancelled", "closing")
    values: dict[str, Any] = {}
    new_is_net = raw.get("new_is_net", basis == "net")
    if not isinstance(new_is_net, bool):
        ctx.error("orders", "new_is_net_type", "new_is_net必须为布尔值", path)
        new_is_net = None
    elif (basis == "net" and not new_is_net) or (basis == "gross" and new_is_net):
        ctx.error("orders", "gross_net_basis_conflict", "桥名称与new_is_net定义冲突", path)
    refs = _driver_refs(raw, keys, ctx, "orders", path)
    for key in ("unit", "currency", "scope", "period", "definition"):
        if key in raw and raw[key] != metadata.get(key):
            ctx.error("orders", "order_metadata_mismatch", "同一订单桥的口径不一致", f"{path}.{key}")
    for key in keys:
        source = dict(raw)
        if key == "new_included" and key not in source:
            for alias in ("new", "new_orders"):
                if alias in source:
                    source[key] = source[alias]
                    break
        values[key] = ctx.value(source, key, "orders", path, required=key != "cancelled" or new_is_net is not True,
                                nonnegative=key != "fx_scope_adjustment", unit=metadata.get("unit"))
    # No missing term is replaced by 0.  A known subtotal is labelled partial.
    signed = [("opening", 1), ("new_included", 1), ("fx_scope_adjustment", 1), ("fulfilled", -1)]
    if new_is_net is not True:
        signed.append(("cancelled", -1))
    unknown = [key for key, _ in signed if values[key] is None]
    known_subtotal = sum(sign * values[key] for key, sign in signed if values[key] is not None)
    expected = known_subtotal if not unknown else None
    residual = values["closing"] - expected if expected is not None and values["closing"] is not None else None
    residual_unexplained = values["closing"] - known_subtotal if unknown and values["closing"] is not None else None
    tolerance = ctx.value(raw, "residual_tolerance", "orders", path, required=False, nonnegative=True)
    tolerance = 1e-9 if tolerance is None else tolerance
    if residual is not None and abs(residual) > tolerance:
        ctx.warn("orders", "order_residual_unexplained", "完整订单桥残差超过已定义容差", path)
    return {**values, "new_is_net": new_is_net, "known_subtotal": known_subtotal,
            "unknown_components": unknown, "expected_closing": expected, "residual": residual,
            "residual_unexplained": residual_unexplained, "residual_tolerance": tolerance,
            "evidence_refs": refs}


def _orders(config: Mapping[str, Any], ctx: Context, industry: Mapping[str, Any]) -> dict[str, Any]:
    if industry.get("order_applicability") == "NOT_APPLICABLE":
        return ctx.finish("orders", status="NOT_APPLICABLE", applicability="NOT_APPLICABLE", bridges=[], cash_links=[])
    raw = _object(config, "orders", ctx)
    if industry.get("order_applicability") == "UNKNOWN":
        ctx.warn("orders", "order_applicability_unknown", "行业订单适用性未知", "industry.order_based")
    bridges_raw = _array(raw, "bridges", ctx, "orders", "orders")
    if not bridges_raw:
        ctx.warn("orders", "order_bridges_empty", "适用业务没有订单滚动桥", "orders.bridges")
    bridges: list[dict[str, Any]] = []
    refs: list[str] = []
    for index, item in enumerate(bridges_raw):
        path = f"orders.bridges[{index}]"
        if not isinstance(item, Mapping):
            ctx.error("orders", "order_bridge_type", "订单桥必须为对象", path)
            continue
        metadata = {key: item.get(key, raw.get(key)) for key in ("period", "definition", "unit", "currency", "scope", "fulfillment_definition")}
        _metadata(metadata, tuple(metadata), ctx, "orders", path)
        if "tax_included" not in item and "tax_included" not in raw:
            ctx.warn("orders", "order_tax_basis_missing", "订单需明确是否含税", path)
        elif not isinstance(item.get("tax_included", raw.get("tax_included")), bool):
            ctx.error("orders", "order_tax_basis_type", "tax_included必须为布尔值", path)
        record = {**metadata, "tax_included": item.get("tax_included", raw.get("tax_included"))}
        nested = False
        for basis in ("gross", "net"):
            if basis not in item:
                continue
            nested = True
            if not isinstance(item[basis], Mapping):
                ctx.error("orders", "order_basis_type", "gross/net桥必须为对象", f"{path}.{basis}")
                continue
            source = {**item[basis]}
            if "source_ref" not in source and item.get("source_ref") is not None:
                source["source_ref"] = item["source_ref"]
            record[basis] = _order_bridge(source, basis, ctx, f"{path}.{basis}", metadata)
            refs += record[basis]["evidence_refs"]
        if not nested:
            net = item.get("new_is_net")
            if not isinstance(net, bool):
                ctx.error("orders", "new_is_net_type", "单桥必须显式声明new_is_net布尔值", path)
            basis = "net" if net is True else "gross"
            record[basis] = _order_bridge(item, basis, ctx, path, metadata)
            refs += record[basis]["evidence_refs"]
        bridges.append(record)
    links_raw = raw.get("cash_links", [])
    if not isinstance(links_raw, list):
        ctx.error("orders", "cash_links_type", "cash_links必须为数组", "orders.cash_links")
        links_raw = []
    links: list[dict[str, Any]] = []
    cash_keys = ("recognized_revenue", "cost", "gross_profit", "gross_margin", "advance", "milestone_receipt", "cash_received", "receivable", "contract_asset", "refunds")
    for index, link in enumerate(links_raw):
        path = f"orders.cash_links[{index}]"
        if not isinstance(link, Mapping):
            ctx.error("orders", "cash_link_type", "利润/现金联系必须为对象", path)
            continue
        refs += _driver_refs(link, cash_keys, ctx, "orders", path)
        values = {key: ctx.value(link, key, "orders", path, required=False, nonnegative=key not in {"gross_profit", "gross_margin"}) for key in cash_keys}
        if values["recognized_revenue"] is None:
            ctx.warn("orders", "order_recognized_revenue_missing", "缺少履约到会计收入的联系", path)
        if all(values[key] is None for key in ("cost", "gross_profit", "gross_margin")):
            ctx.warn("orders", "order_profit_link_missing", "缺少成本或毛利证据，不能声称已完成利润联系", path)
        if all(values[key] is None for key in ("advance", "milestone_receipt", "cash_received", "receivable", "contract_asset", "refunds")):
            ctx.warn("orders", "order_cash_link_missing", "缺少实际回款/预收/应收/合同资产联系", path)
        if values["gross_margin"] is not None and values["gross_margin"] > 1:
            ctx.warn("orders", "order_abnormal_gross_margin", "毛利率超过1，需解释成本口径或冲回", path)
        if values["gross_profit"] is None and values["recognized_revenue"] is not None and values["cost"] is not None:
            values["gross_profit"] = values["recognized_revenue"] - values["cost"]
        values["period"] = link.get("period")
        values["refund_risk"] = link.get("refund_risk")
        links.append(values)
    if not links:
        ctx.warn("orders", "order_profit_cash_link_missing", "缺少订单到履约收入、利润和现金的证据联系", "orders.cash_links")
    return ctx.finish("orders", applicability="APPLICABLE", evidence_refs=sorted(set(refs)), bridges=bridges,
                      cash_links=links, cash_revenue_warning="订单不是收入、利润或现金；残差未知不补零；纳入现金流的订单不再额外加EV")


def _after_tax(income: float | int | None, rate: float | int | None,
               raw: Mapping[str, Any], ctx: Context, path: str) -> float | None:
    policy = raw.get("loss_tax_benefit")
    if policy is not None and not isinstance(policy, bool):
        ctx.error("forecast", "loss_tax_policy_type", "loss_tax_benefit必须是布尔值", path)
        return None
    if income is None or rate is None:
        return None
    if income < 0 and rate > 0:
        if policy is None:
            ctx.warn("forecast", "loss_tax_policy_missing", "亏损不得自动确认税收抵扣，需显式loss_tax_benefit", path)
            return None
        if policy is False:
            return income
    return income * (1 - rate)


def _financial_forecast(raw: Mapping[str, Any], ctx: Context, profile: str) -> dict[str, Any]:
    constraints = raw.get("capital_constraints")
    if not isinstance(constraints, Mapping):
        ctx.warn("forecast", "financial_capital_constraints_missing", "金融预测缺少专用资本约束", "forecast.capital_constraints")
        return {"applicability": "FINANCIAL_CAPITAL_CONSTRAINTS_MISSING", "bridge": None}
    if profile != "banks":
        ctx.warn("forecast", "financial_profile_engine_unavailable", "该金融画像没有已验证的专用预测引擎，不能套银行或工业模型", "forecast")
        return {"applicability": "FINANCIAL_SPECIALISED_MODEL_REQUIRED", "bridge": None, "capital_constraints": dict(constraints)}
    operation_keys = ("earning_assets", "asset_yield", "interest_bearing_liabilities", "funding_cost", "loan_balance", "credit_cost", "fees", "opex", "tax_rate")
    capital_keys = ("risk_weighted_assets", "cet1_capital", "minimum_cet1_ratio", "dividend_payout")
    refs = _driver_refs(raw, operation_keys, ctx, "forecast", "forecast") + _driver_refs(constraints, capital_keys, ctx, "forecast", "forecast.capital_constraints")
    values = {key: ctx.value(raw, key, "forecast", "forecast", nonnegative=True, unit="fraction" if key in {"asset_yield", "funding_cost", "credit_cost", "tax_rate"} else None) for key in operation_keys}
    capital = {key: ctx.value(constraints, key, "forecast", "forecast.capital_constraints", nonnegative=True, unit="fraction" if key in {"minimum_cet1_ratio", "dividend_payout"} else None) for key in capital_keys}
    for key in ("asset_yield", "funding_cost", "credit_cost", "tax_rate"):
        _range_rate(values[key], ctx, "forecast", f"forecast.{key}")
    for key in ("minimum_cet1_ratio", "dividend_payout"):
        _range_rate(capital[key], ctx, "forecast", f"forecast.capital_constraints.{key}")
    income = values["earning_assets"] * values["asset_yield"] if values["earning_assets"] is not None and values["asset_yield"] is not None else None
    interest_cost = values["interest_bearing_liabilities"] * values["funding_cost"] if values["interest_bearing_liabilities"] is not None and values["funding_cost"] is not None else None
    nii = income - interest_cost if income is not None and interest_cost is not None else None
    provision = values["loan_balance"] * values["credit_cost"] if values["loan_balance"] is not None and values["credit_cost"] is not None else None
    pretax = nii + values["fees"] - provision - values["opex"] if all(v is not None for v in (nii, values["fees"], provision, values["opex"])) else None
    net_profit = _after_tax(pretax, values["tax_rate"], raw, ctx, "forecast.loss_tax_benefit")
    requirement = capital["risk_weighted_assets"] * capital["minimum_cet1_ratio"] if capital["risk_weighted_assets"] is not None and capital["minimum_cet1_ratio"] is not None else None
    headroom = capital["cet1_capital"] - requirement if capital["cet1_capital"] is not None and requirement is not None else None
    if headroom is not None and headroom < 0:
        ctx.warn("forecast", "bank_capital_shortfall", "预测资本低于最低CET1要求，需要融资/降风险资产/削减分配方案", "forecast.capital_constraints")
    payout = min(max(net_profit, 0) * capital["dividend_payout"], max(headroom, 0)) if net_profit is not None and capital["dividend_payout"] is not None and headroom is not None else None
    return {"applicability": "BANKS", "bridge": {**values, "interest_income": income, "interest_cost": interest_cost,
            "net_interest_income": nii, "credit_provision": provision, "pretax_profit": pretax, "net_profit": net_profit},
            "capital_constraints": {**capital, "required_cet1": requirement, "capital_headroom": headroom,
                                    "capital_limited_distribution": payout}, "evidence_refs": refs}


def _scenarios(raw: Mapping[str, Any], ctx: Context) -> dict[str, Any]:
    scenarios_raw = raw.get("scenarios")
    if scenarios_raw is None:
        return {"scenarios": [], "weighted_value": None, "probability_sum": None}
    if not isinstance(scenarios_raw, list) or not scenarios_raw:
        ctx.error("forecast", "scenarios_type", "提供scenarios时必须为非空数组", "forecast.scenarios")
        return {"scenarios": [], "weighted_value": None, "probability_sum": None}
    scenarios: list[dict[str, Any]] = []
    ok = True
    for index, record in enumerate(scenarios_raw):
        path = f"forecast.scenarios[{index}]"
        if not isinstance(record, Mapping):
            ctx.error("forecast", "scenario_type", "情景必须为对象", path)
            ok = False
            continue
        _driver_refs(record, ("probability", "value"), ctx, "forecast", path)
        probability = ctx.value(record, "probability", "forecast", path)
        value = ctx.value(record, "value", "forecast", path)
        if not _range_rate(probability, ctx, "forecast", f"{path}.probability") or value is None:
            ok = False
        scenarios.append({"name": record.get("name"), "probability": probability, "value": value})
    total = sum(record["probability"] for record in scenarios if record["probability"] is not None)
    if abs(total - 1) > 1e-9:
        ctx.error("forecast", "scenario_probability_sum", "情景概率必须合计1，禁止自动归一或输出错误加权值", "forecast.scenarios")
        ok = False
    return {"scenarios": scenarios, "weighted_value": sum(record["probability"] * record["value"] for record in scenarios) if ok else None,
            "probability_sum": total}


def _forecast(config: Mapping[str, Any], ctx: Context, industry: Mapping[str, Any]) -> dict[str, Any]:
    raw = _object(config, "forecast", ctx)
    _metadata(raw, ("period", "unit", "currency", "scope", "basis"), ctx, "forecast", "forecast")
    if industry.get("financial"):
        data = _financial_forecast(raw, ctx, industry["profile"])
        return ctx.finish("forecast", **data, **_scenarios(raw, ctx))
    if industry.get("financial") is None:
        ctx.warn("forecast", "forecast_industry_unknown", "行业模型未知，不能自动计算非金融现金流", "industry.profile")
        return ctx.finish("forecast", applicability="UNKNOWN", bridge=None, **_scenarios(raw, ctx))
    refs: list[str] = []
    mode = raw.get("revenue_mode")
    revenue = None
    revenue_inputs: dict[str, Any] = {"mode": mode}
    if mode == "quantity_price":
        refs += _driver_refs(raw, ("quantity", "price"), ctx, "forecast", "forecast")
        _metadata(raw, ("quantity_unit", "price_quantity_unit"), ctx, "forecast", "forecast")
        quantity = ctx.value(raw, "quantity", "forecast", "forecast", nonnegative=True, unit=raw.get("quantity_unit"))
        price = ctx.value(raw, "price", "forecast", "forecast", nonnegative=True)
        compatible = raw.get("quantity_unit") is not None and raw.get("quantity_unit") == raw.get("price_quantity_unit")
        if not compatible:
            ctx.warn("forecast", "price_quantity_unit_mismatch", "量与单位价格的物量单位不一致，禁止隐式换算", "forecast")
        revenue = quantity * price if compatible and quantity is not None and price is not None else None
        revenue_inputs.update(quantity=quantity, price=price)
    elif mode == "order_conversion":
        batches = _array(raw, "order_batches", ctx, "forecast", "forecast")
        results: list[dict[str, Any]] = []
        all_available = bool(batches)
        for index, record in enumerate(batches):
            path = f"forecast.order_batches[{index}]"
            if not isinstance(record, Mapping):
                ctx.error("forecast", "order_batch_type", "订单转化批次必须为对象", path)
                all_available = False
                continue
            refs += _driver_refs(record, ("amount", "conversion_rate"), ctx, "forecast", path)
            amount = ctx.value(record, "amount", "forecast", path, nonnegative=True, unit=raw.get("unit"))
            rate = ctx.value(record, "conversion_rate", "forecast", path)
            valid = _range_rate(rate, ctx, "forecast", f"{path}.conversion_rate")
            delivery = record.get("delivery_period")
            if not isinstance(delivery, str) or delivery != raw.get("period"):
                ctx.warn("forecast", "order_delivery_period_mismatch", "订单需明确落在预测期间的交付批次，禁止全额当期确认", path)
                valid = False
            if amount is None or rate is None or not valid:
                all_available = False
            recognized = amount * rate if amount is not None and rate is not None and valid else None
            results.append({"id": record.get("id"), "amount": amount, "conversion_rate": rate, "delivery_period": delivery, "revenue": recognized})
        revenue = sum(record["revenue"] for record in results) if all_available else None
        revenue_inputs["order_batches"] = results
    elif mode == "direct":
        refs += _driver_refs(raw, ("revenue",), ctx, "forecast", "forecast")
        revenue = ctx.value(raw, "revenue", "forecast", "forecast", nonnegative=True, unit=raw.get("unit"), period=raw.get("period"))
    else:
        ctx.warn("forecast", "revenue_driver_missing", "须显式选quantity_price/order_conversion/direct并给证据", "forecast.revenue_mode")
    keys = ("gross_margin", "opex", "da", "tax_rate", "capex", "delta_nwc")
    refs += _driver_refs(raw, (*keys, "cogs_da", "opex_da"), ctx, "forecast", "forecast")
    values = {key: ctx.value(raw, key, "forecast", "forecast", nonnegative=key not in {"delta_nwc", "gross_margin"}, unit="fraction" if key in {"gross_margin", "tax_rate"} else raw.get("unit")) for key in keys}
    _range_rate(values["tax_rate"], ctx, "forecast", "forecast.tax_rate")
    if values["gross_margin"] is not None and values["gross_margin"] > 1:
        ctx.warn("forecast", "abnormal_gross_margin", "毛利率超过1需说明成本口径/冲回", "forecast.gross_margin")
    convention = raw.get("opex_excludes_da")
    gm_convention = raw.get("gross_margin_excludes_da")
    for key, flag in (("opex_excludes_da", convention), ("gross_margin_excludes_da", gm_convention)):
        if flag is None:
            ctx.warn("forecast", "da_convention_missing", "须明确毛利和费用是否已含DA，避免重复扣减", f"forecast.{key}")
        elif not isinstance(flag, bool):
            ctx.error("forecast", "da_convention_type", "DA口径标志必须是布尔值", f"forecast.{key}")
    gross_profit = revenue * values["gross_margin"] if revenue is not None and values["gross_margin"] is not None else None
    ebit = None
    da_deduction = None
    if isinstance(convention, bool) and isinstance(gm_convention, bool):
        if convention and gm_convention:
            da_deduction = values["da"]
        elif not convention and not gm_convention:
            da_deduction = 0  # explicit inclusive presentation, not a missing-data fallback
        else:
            split_key = "opex_da" if convention else "cogs_da"
            da_deduction = ctx.value(raw, split_key, "forecast", "forecast", nonnegative=True, unit=raw.get("unit"))
            if da_deduction is not None and values["da"] is not None and da_deduction > values["da"]:
                ctx.error("forecast", "da_split_exceeds_total", "分部DA不能高于全量DA", f"forecast.{split_key}")
                da_deduction = None
    if gross_profit is not None and values["opex"] is not None and da_deduction is not None:
        ebit = gross_profit - values["opex"] - da_deduction
    nopat = _after_tax(ebit, values["tax_rate"], raw, ctx, "forecast.loss_tax_benefit")
    fcff = nopat + values["da"] - values["capex"] - values["delta_nwc"] if all(value is not None for value in (nopat, values["da"], values["capex"], values["delta_nwc"])) else None
    return ctx.finish("forecast", evidence_refs=sorted(set(refs)), applicability="NON_FINANCIAL",
                      bridge={**revenue_inputs, **values, "revenue": revenue, "gross_profit": gross_profit,
                              "ebit": ebit, "nopat": nopat, "fcff": fcff, "opex_excludes_da": convention,
                              "gross_margin_excludes_da": gm_convention, "additional_da_deduction": da_deduction},
                      **_scenarios(raw, ctx))


def _theses(config: Mapping[str, Any], ctx: Context, as_of: str | None) -> dict[str, Any]:
    raw = _object(config, "theses", ctx)
    items = _array(raw, "items", ctx, "theses", "theses")
    if not items:
        ctx.warn("theses", "theses_empty", "缺少承重论点和反方验证", "theses.items")
    claims: list[dict[str, Any]] = []
    for index, claim in enumerate(items):
        path = f"theses.items[{index}]"
        if not isinstance(claim, Mapping):
            ctx.error("theses", "thesis_type", "论点必须为对象", path)
            continue
        _metadata(claim, ("id", "text"), ctx, "theses", path)
        counters = _array(claim, "counterarguments", ctx, "theses", path)
        if not counters:
            ctx.warn("theses", "counterarguments_empty", "承重论点缺少最强反方证据，不能以空表通过", path)
        output: list[dict[str, Any]] = []
        for cindex, counter in enumerate(counters):
            cpath = f"{path}.counterarguments[{cindex}]"
            if not isinstance(counter, Mapping):
                ctx.error("theses", "counterargument_type", "反方论据必须为对象", cpath)
                continue
            refs = ctx.refs(counter, "theses", cpath)
            resolved = bool(refs) and all(ref in ctx.registry for ref in refs)
            _metadata(counter, ("text", "disposition", "reason", "action"), ctx, "theses", cpath)
            if counter.get("disposition") not in {"accepted", "partially_accepted", "rejected", "unresolved", "接纳", "部分接纳", "暂不采纳", "未解决"}:
                ctx.error("theses", "counterargument_disposition_invalid", "反方处置枚举非法", cpath)
            changed = counter.get("changed_assumption_ids")
            if not isinstance(changed, list) or any(not isinstance(x, str) for x in changed):
                ctx.error("theses", "changed_assumptions_type", "changed_assumption_ids必须为字符串ID数组，可显式为空", cpath)
                changed = []
            for rid in changed:
                if rid not in ctx.registry or ctx.registry[rid]["kind"] != "assumption":
                    ctx.error("theses", "changed_assumption_unresolved", "受影响假设ID不存在或不是假设", cpath)
            verify = iso_date(counter.get("verify_date"))
            if verify is None:
                ctx.warn("theses", "verify_date_missing", "反方验证需明确有效复核日期", cpath)
            output.append({**counter, "refs": refs, "changed_assumption_ids": changed, "verify_date": verify,
                           "citation_status": "RESOLVED_REFERENCE" if resolved else "UNRESOLVED_REFERENCE"})
        claims.append({"id": claim.get("id"), "text": claim.get("text"), "counterarguments": output})
    return ctx.finish("theses", claims=claims, citation_note="引用可解析不等于事实已独立验证")


def _decision(config: Mapping[str, Any], ctx: Context, industry: Mapping[str, Any]) -> dict[str, Any]:
    raw = _object(config, "decision", ctx)
    metrics = raw.get("capital_metrics", {})
    if not isinstance(metrics, Mapping):
        ctx.error("decision", "capital_metrics_type", "capital_metrics必须为对象", "decision.capital_metrics")
        metrics = {}
    capital: dict[str, Any] = {}
    financial = industry.get("financial")
    if financial is True:
        capital["invested_capital_bridge"] = {"status": "NOT_APPLICABLE", "reason": "该金融模型不套普通企业经营/融资投入资本双桥"}
        capital["roic"] = {"status": "NOT_APPLICABLE", "value": None, "reason": "该金融模型不套普通企业ROIC"}
        capital["roiic"] = {"status": "NOT_APPLICABLE", "value": None, "reason": "该金融模型不套普通企业ROIIC"}
        if "reinvestment_check" in metrics:
            capital["reinvestment_check"] = {"status": "NOT_APPLICABLE", "reason": "金融模型需要资本充足及可分配资本口径，不能套普通企业再投资率×ROIC"}
    elif financial is False and metrics:
        bridge = invested_capital_bridge(metrics, ctx)
        capital["invested_capital_bridge"] = bridge if bridge is not None else {"status": "NOT_ASSESSED", "reason": "沿用显式旧资本输入，未提供可选双桥；未完成双桥对账"}
        metadata = bridge.get("metadata", {}) if bridge else {}
        periods = bridge.get("periods", {}) if bridge else {}
        capital_input_start = len(ctx.findings)
        _driver_refs(metrics, ("invested_capital_begin", "invested_capital_end", "nopat", "prior_nopat"), ctx, "decision", "decision.capital_metrics")
        if bridge:
            begin = capital_value(metrics, "invested_capital_begin", ctx, "decision.capital_metrics", metadata, bridge.get("begin", {}).get("date"), required=False)
            end = capital_value(metrics, "invested_capital_end", ctx, "decision.capital_metrics", metadata, bridge.get("end", {}).get("date"), required=False)
            nopat = capital_value(metrics, "nopat", ctx, "decision.capital_metrics", metadata, periods.get("nopat_period"))
            prior = capital_value(metrics, "prior_nopat", ctx, "decision.capital_metrics", metadata, periods.get("prior_nopat_period"))
            input_findings = ctx.findings[capital_input_start:]
            if any(item["severity"] == "ERROR" for item in input_findings):
                bridge["status"] = "INVALID"
            elif input_findings and bridge["status"] == "OK":
                bridge["status"] = "INCOMPLETE"
        else:
            begin = ctx.value(metrics, "invested_capital_begin", "decision", "decision.capital_metrics")
            end = ctx.value(metrics, "invested_capital_end", "decision", "decision.capital_metrics")
            nopat = ctx.value(metrics, "nopat", "decision", "decision.capital_metrics")
            prior = ctx.value(metrics, "prior_nopat", "decision", "decision.capital_metrics")
        start_date = iso_date(metrics.get("window_start"))
        end_date = iso_date(metrics.get("window_end"))
        if bridge:
            if bridge["status"] == "OK":
                verified_begin = bridge["begin"]["reconciled_invested_capital"]
                verified_end = bridge["end"]["reconciled_invested_capital"]
                tolerance = bridge["absolute_tolerance"]
                for key, supplied, verified in (("invested_capital_begin", begin, verified_begin), ("invested_capital_end", end, verified_end)):
                    if supplied is not None and abs(supplied-verified) > tolerance:
                        ctx.error("decision", "capital_legacy_bridge_mismatch", "显式旧投入资本与已核对双桥不同，停止资本回报计算", f"decision.capital_metrics.{key}")
                        bridge["status"] = "INVALID"
                begin, end = (verified_begin, verified_end) if bridge["status"] == "OK" else (None, None)
            else:
                begin = end = None
            start_date = start_date or bridge.get("begin", {}).get("date")
            end_date = end_date or bridge.get("end", {}).get("date")
        if start_date is None or end_date is None or start_date >= end_date:
            ctx.warn("decision", "capital_window_missing", "ROIC/ROIIC需要真实起止日期；不按年距缩放ROIIC", "decision.capital_metrics")
        invalid_capital_fields: set[str] = set()
        def finite_capital(value, field):
            if value is not None and not number(value):
                invalid_capital_fields.add(field)
                ctx.error("decision", "capital_calculation_nonfinite", "资本回报中间值或结果不可表示，保留null并停止该指标解释", f"decision.capital_metrics.{field}")
                return None
            return value
        average = None
        if begin is not None and end is not None:
            # Same-sign difference cannot overflow; opposite-sign sum cannot
            # overflow. Unlike half-plus-half this also preserves subnormals.
            average = begin + (end-begin)/2 if (begin >= 0) == (end >= 0) else (begin+end)/2
        average = finite_capital(average, "average_invested_capital")
        delta_ic = finite_capital(end-begin if begin is not None and end is not None else None, "delta_invested_capital")
        delta_nopat = finite_capital(nopat-prior if nopat is not None and prior is not None else None, "delta_nopat")
        roic = finite_capital(nopat / average if nopat is not None and average is not None and average > 0 else None, "roic")
        roiic = finite_capital(delta_nopat / delta_ic if delta_nopat is not None and delta_ic is not None and delta_ic > 0 and start_date and end_date and start_date < end_date else None, "roiic")
        if average is not None and average <= 0:
            ctx.warn("decision", "nonpositive_average_ic", "平均投入资本非正，ROIC仅保留诊断，不能正常解释", "decision.capital_metrics")
        if delta_ic is not None and delta_ic <= 0:
            ctx.warn("decision", "nonpositive_incremental_ic", "增量投入资本非正，ROIIC不可正常解释", "decision.capital_metrics")
        capital_status = "INVALID" if bridge and bridge["status"] == "INVALID" else None
        roic_status = "INVALID" if invalid_capital_fields & {"average_invested_capital", "roic"} else capital_status
        roiic_status = "INVALID" if invalid_capital_fields & {"delta_invested_capital", "delta_nopat", "roiic"} else capital_status
        capital["roic"] = {"status": roic_status or ("OK" if roic is not None else "INCOMPLETE"), "value": roic, "nopat": nopat, "average_invested_capital": average}
        capital["roiic"] = {"status": roiic_status or ("OK" if roiic is not None else "INCOMPLETE"), "value": roiic, "delta_nopat": delta_nopat,
                            "delta_invested_capital": delta_ic, "window_start": start_date, "window_end": end_date,
                            "window_years": (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days / 365.2425 if start_date and end_date and start_date < end_date else None}
        reinvestment = reinvestment_check(metrics, ctx, capital, bridge, nopat, prior)
        if reinvestment is not None:
            capital["reinvestment_check"] = reinvestment
    elif metrics:
        ctx.warn("decision", "capital_industry_unknown", "行业未知，不能解释通用企业资本回报", "decision.capital_metrics")
    if industry.get("profile") == "banks" and metrics:
        _driver_refs(metrics, ("ptbv", "ke", "g"), ctx, "decision", "decision.capital_metrics")
        ptbv = ctx.value(metrics, "ptbv", "decision", "decision.capital_metrics", nonnegative=True)
        ke = ctx.value(metrics, "ke", "decision", "decision.capital_metrics", nonnegative=True)
        growth = ctx.value(metrics, "g", "decision", "decision.capital_metrics")
        valid = ptbv is not None and ke is not None and growth is not None and ke > growth
        if ke is not None and growth is not None and ke <= growth:
            ctx.error("decision", "bank_ke_g_invalid", "稳态反推要求Ke>g", "decision.capital_metrics")
        implied_rotce = ptbv * (ke-growth) + growth if valid else None
        rotce_status = "OK" if valid else "INCOMPLETE"
        if implied_rotce is not None and not number(implied_rotce):
            ctx.error("decision", "capital_calculation_nonfinite", "隐含ROTCE结果不可表示，保留null", "decision.capital_metrics.implied_rotce")
            implied_rotce, rotce_status = None, "INVALID"
        capital["implied_rotce"] = {"status": rotce_status, "value": implied_rotce,
                                    "ptbv": ptbv, "ke": ke, "g": growth,
                                    "assumptions": "稳态清洁盈余、可持续ROTCE和g、同口径P/TBV，单一未知数"}
    if not raw:
        ctx.warn("decision", "decision_missing", "缺少决策输入", "decision")
    return ctx.finish("decision", capital_metrics=capital, recommendation=raw.get("recommendation"), valuation=raw.get("valuation"))


def _empty(status: str, findings: list[dict[str, Any]], as_of: str | None = None) -> dict[str, Any]:
    module_status = "INVALID" if status == "INVALID" else "INCOMPLETE"
    return {"schema_version": SCHEMA_VERSION, "generated_at": as_of, "as_of": as_of, "status": status,
            "findings": findings, "registry": {"status": status, "records": []},
            "modules": {name: {"status": module_status, "findings": [], "evidence_refs": []} for name in MODULE_NAMES},
            "assumptions_used": [], "input_fingerprint": None}


def _replace_nonfinite(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _replace_nonfinite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_nonfinite(item) for item in value]
    return None if isinstance(value, float) and not number(value) else value


def evaluate_topics(config: Mapping[str, Any], as_of: str | date | None = None) -> dict[str, Any]:
    """Pure calculation. Invalid JSON-type inputs return INVALID, never NaN output."""
    if not isinstance(config, Mapping):
        return _empty("INVALID", [{"id": "input_type", "severity": "ERROR", "topic": "input", "message": "根节点必须为对象", "field": "input", "refs": []}])
    ctx = Context(config)
    if type(config.get("schema_version")) is not int or config["schema_version"] != SCHEMA_VERSION:
        ctx.error("input", "schema_version_invalid", "schema_version必须为整数1", "schema_version")
    for path in scan_nonfinite(config):
        ctx.error("input", "nonfinite_input", "任意位置均禁止NaN/Infinity", path)
    as_of_value = as_of if as_of is not None else config.get("as_of")
    as_of_date = iso_date(as_of_value)
    if as_of_value is not None and as_of_date is None:
        ctx.error("input", "as_of_invalid", "as_of必须为有效ISO日期", "as_of")
    if any(item["severity"] == "ERROR" for item in ctx.findings):
        return _empty("INVALID", ctx.findings, as_of_date)
    try:
        canonical = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        ctx.error("input", "input_not_json_serializable", f"输入必须只包含合法JSON类型: {exc}", "input")
        return _empty("INVALID", ctx.findings, as_of_date)
    if as_of_date is None:
        ctx.warn("input", "as_of_missing", "未提供as_of，无法保证未来信息过滤", "as_of")
    ctx.as_of = as_of_date
    for key in ("facts", "assumptions", *MODULE_NAMES):
        if key not in config:
            ctx.warn("input", "top_level_missing", f"缺少顶层字段{key}", key)
    registry = build_registry(ctx)
    industry = _industry(config, ctx)
    modules = {"industry": industry, "guidance": _guidance(config, ctx, as_of_date), "orders": _orders(config, ctx, industry),
               "forecast": _forecast(config, ctx, industry), "theses": _theses(config, ctx, as_of_date),
               "decision": _decision(config, ctx, industry)}
    for name, module in modules.items():
        for path in scan_nonfinite(module, f"modules.{name}"):
            ctx.error(name, "calculation_nonfinite", "有限输入产生不可表示的计算结果，保留null并判INVALID", path)
        if any(item["severity"] == "ERROR" for item in ctx.findings if item["topic"] == name):
            module["status"] = "INVALID"
        module["findings"] = [item for item in ctx.findings if item["topic"] == name]
        modules[name] = _replace_nonfinite(module)
    # Sources and calculations may not be equivalent; INVALID in any module wins.
    statuses = [registry["status"], *(module["status"] for module in modules.values())]
    if "INVALID" in statuses or any(item["severity"] == "ERROR" for item in ctx.findings):
        status = "INVALID"
    elif "INCOMPLETE" in statuses or any(item["severity"] == "WARN" for item in ctx.findings if item["topic"] == "input"):
        status = "INCOMPLETE"
    else:
        status = "OK"
    return {"schema_version": SCHEMA_VERSION, "generated_at": as_of_date, "as_of": as_of_date, "status": status,
            "registry": registry, "findings": ctx.findings, "modules": modules,
            "assumptions_used": [ctx.registry[rid] for rid in sorted(ctx.used_assumptions)],
            "input_fingerprint": {"algorithm": "sha256", "digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}}


def write_output(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_json(path, payload)


def run(project_dir: Path, as_of: str | None = None) -> tuple[dict[str, Any], int]:
    input_path = Path(project_dir) / "input" / "研究模型.json"
    output_path = Path(project_dir) / "reports" / "研究模型_输出.json"
    try:
        _, config = read_input(input_path)
    except FileNotFoundError:
        payload = _empty("INCOMPLETE", [{"id": "input_missing", "severity": "WARN", "topic": "input", "message": "input/研究模型.json不存在", "field": "input", "refs": []}], iso_date(as_of))
        write_output(output_path, payload)
        return payload, 2
    except (ValueError, OSError, RecursionError) as exc:
        payload = _empty("INVALID", [{"id": "input_json_invalid", "severity": "ERROR", "topic": "input", "message": str(exc), "field": "input", "refs": []}], iso_date(as_of))
        write_output(output_path, payload)
        return payload, 3
    try:
        payload = evaluate_topics(config, as_of)
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError, OverflowError) as exc:
        payload = _empty("INVALID", [{"id": "input_model_invalid", "severity": "ERROR", "topic": "input", "message": f"研究模型结构无效：{type(exc).__name__}: {exc}", "field": "input", "refs": []}], iso_date(as_of))
    write_output(output_path, payload)
    return payload, 3 if payload["status"] == "INVALID" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate source-linked V3 research topics")
    parser.add_argument("--dir", default=".")
    parser.add_argument("--as-of", default=None)
    args = parser.parse_args(argv)
    result, code = run(Path(args.dir), args.as_of)
    print(json.dumps({"status": result["status"], "output": str(Path(args.dir) / "reports" / "研究模型_输出.json")}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
