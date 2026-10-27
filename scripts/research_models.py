"""Strict input primitives and an explicit economic-model method matrix (stdlib)."""
from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

PROFILES = {
    "industrials": (("normalized_ev_ebitda", "fcff_dcf"), ("mid_cycle_earnings", "reverse_dcf"), ("peak_earnings_peak_multiple",), False),
    "construction": (("project_cash_flow", "normalized_ev_ebitda", "sotp"), ("order_cash_conversion", "mid_cycle_earnings"), ("backlog_plus_ev", "perpetuity_after_concession"), False),
    "consumer": (("normalized_pe", "fcff_dcf"), ("unit_economics", "reverse_dcf"), ("peak_margin_perpetuity",), False),
    "saas": (("fcff_dcf", "reverse_dcf"), ("ev_arr_margin_constrained", "retention_unit_economics"), ("epv_for_loss_making_growth", "unadjusted_sbc_fcf"), False),
    "platform": (("sotp", "fcff_dcf"), ("reverse_operating_assumptions", "sbc_adjusted_fcf"), ("single_pe_for_mixed_businesses",), False),
    "banks": (("ptbv_rotce", "equity_residual_income", "ddm"), ("normalized_pe", "implied_rotce"), ("fcff_dcf", "fcff", "wacc", "ev_ebitda", "roic"), True),
    "life_insurance": (("adjusted_embedded_value", "vnb"), ("distributable_equity_cash", "embedded_value_sensitivity"), ("fcff_dcf", "ev_ebitda", "bank_rotce", "enterprise_ev_for_embedded_value"), True),
    "property_insurance": (("pb_normalized_roe", "equity_residual_income", "ddm"), ("underwriting_reserve_stress", "normalized_pe"), ("fcff_dcf", "ev_ebitda", "bank_rotce"), True),
    "insurance_broker": (("service_fcf_dcf", "normalized_pe"), ("ev_ebitda", "commission_unit_economics"), ("insurer_embedded_value", "bank_rotce"), False),
    "equity_reit": (("property_nav", "p_affo"), ("affo_dcf", "transaction_cap_rate"), ("net_income_pe", "dividend_yield_as_valuation", "mortgage_book_value"), False),
    "mreit": (("pb_duration_adjusted",), ("net_interest_duration_stress",), ("p_affo", "affo_dcf", "property_nav", "fcff_dcf"), True),
    "mining_production": (("finite_mine_nav",), ("mid_cycle_ev_ebitda", "p_nav", "replacement_value"), ("perpetuity", "perpetual_growth", "exploration_in_base_nav"), False),
    "mining_exploration": (("risked_exploration_option",), ("resource_transaction_comps",), ("production_mine_dcf", "perpetuity", "normalized_pe"), False),
    "utilities_regulated": (("rate_base_equity_dcf", "ddm"), ("pb_actual_roe", "normalized_pe"), ("allowed_roe_equals_actual_roe", "merchant_perpetuity"), False),
    "power_merchant": (("plant_cash_flow", "sotp"), ("normalized_pe", "replacement_capacity_value"), ("regulated_allowed_roe", "guaranteed_perpetuity"), False),
    "energy_upstream": (("asset_nav",), ("mid_cycle_cash_flow", "reverse_nav"), ("perpetuity", "perpetual_growth", "refining_multiple"), False),
    "energy_refining": (("mid_cycle_cash_flow",), ("normalized_ev_ebitda", "spread_sensitivity"), ("upstream_nav_multiple",), False),
    "energy_midstream": (("contract_cash_flow",), ("normalized_ev_ebitda", "throughput_fee_sensitivity"), ("upstream_nav_multiple",), False),
    "property_developer": (("sales_collection_nav",), ("asset_debt_repayment_stress",), ("p_affo", "affo_dcf", "equity_reit_nav"), False),
}

ALIASES = {
    "manufacturing": "industrials", "industrial": "industrials", "制造业": "industrials", "工业制造": "industrials",
    "施工": "construction", "工程施工": "construction", "消费品": "consumer", "消费": "consumer",
    "bank": "banks", "银行": "banks", "寿险": "life_insurance", "财险": "property_insurance", "保险经纪": "insurance_broker",
    "reit": "equity_reit", "权益reit": "equity_reit", "生产矿山": "mining_production", "勘探": "mining_exploration",
    "受监管公用事业": "utilities_regulated", "竞争性发电": "power_merchant", "上游能源": "energy_upstream",
}

METHOD_ALIASES = {
    "fcff-dcf": "fcff_dcf", "fcff/dcf": "fcff_dcf", "dcf": "fcff_dcf", "ev/ebitda": "ev_ebitda",
    "p/tbv-rotce": "ptbv_rotce", "p/tbv": "ptbv_rotce", "普通企业roic": "roic", "ddm": "ddm",
    "永续增长终值": "perpetual_growth", "永续": "perpetuity", "银行rotce": "bank_rotce",
}


def canonical_method(value: Any) -> str:
    key = str(value).strip().lower().replace(" ", "")
    return METHOD_ALIASES.get(key, key)


def number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def iso_date(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def scan_nonfinite(value: Any, path: str = "input") -> list[str]:
    if isinstance(value, Mapping):
        return [p for key, item in value.items() for p in scan_nonfinite(item, f"{path}.{key}")]
    if isinstance(value, list):
        return [p for index, item in enumerate(value) for p in scan_nonfinite(item, f"{path}[{index}]")]
    return [path] if isinstance(value, float) and not math.isfinite(value) else []


class Context:
    def __init__(self, config: Mapping[str, Any]):
        self.config = config
        self.findings: list[dict[str, Any]] = []
        self.registry: dict[str, dict[str, Any]] = {}
        self.used_assumptions: set[str] = set()
        self.as_of: str | None = None

    def add(self, topic: str, fid: str, severity: str, message: str, field: str | None = None,
            refs: list[str] | None = None) -> None:
        item = {"id": fid, "severity": severity, "topic": topic, "message": message,
                "field": field, "refs": refs or []}
        if item not in self.findings:
            self.findings.append(item)

    def warn(self, topic: str, fid: str, message: str, field: str | None = None) -> None:
        self.add(topic, fid, "WARN", message, field)

    def error(self, topic: str, fid: str, message: str, field: str | None = None) -> None:
        self.add(topic, fid, "ERROR", message, field)

    def refs(self, obj: Mapping[str, Any], topic: str, path: str, *, required: bool = True) -> list[str]:
        refs: list[str] = []
        for key in ("source_ref", "evidence_ref"):
            if key in obj and obj[key] is not None:
                if not isinstance(obj[key], str):
                    self.error(topic, "reference_type", "引用必须是已登记的字符串ID", f"{path}.{key}")
                else:
                    refs.append(obj[key])
        for key in ("refs", "source_refs"):
            if key in obj and obj[key] is not None:
                if not isinstance(obj[key], list) or any(not isinstance(x, str) for x in obj[key]):
                    self.error(topic, "reference_type", "引用列表必须只包含字符串ID", f"{path}.{key}")
                else:
                    refs.extend(obj[key])
        for ref in refs:
            if ref not in self.registry:
                self.error(topic, "reference_unresolved", "引用未解析到合格事实/假设登记", path,)
        if required and not refs:
            self.warn(topic, "reference_missing", "缺少已登记事实/假设引用", path)
        return sorted(set(refs))

    def value(self, obj: Mapping[str, Any], key: str, topic: str, path: str, *,
              required: bool = True, nonnegative: bool = False, unit: str | None = None,
              period: str | None = None) -> float | int | None:
        value = obj.get(key)
        if isinstance(value, Mapping):
            ref = value.get("ref")
            if not isinstance(ref, str) or ref not in self.registry:
                self.error(topic, "driver_reference_unresolved", "数值引用未解析到合格登记ID", f"{path}.{key}")
                return None
            record = self.registry[ref]
            if record["kind"] == "assumption":
                self.used_assumptions.add(ref)
            for name, expected in (("unit", unit), ("period", period)):
                supplied = value[name] if name in value else expected
                if (name in value or expected is not None) and record.get(name) != supplied:
                    self.error(topic, "driver_metadata_mismatch", f"数值引用的{name}与模型口径不一致", f"{path}.{key}")
                    return None
            value = record.get("value")
        if value is None:
            if required:
                self.warn(topic, "numeric_missing", "必要数值缺失，保留null", f"{path}.{key}")
            return None
        if not number(value):
            self.error(topic, "numeric_type", "数值必须为有限数字或null，布尔值/数字字符串不接受", f"{path}.{key}")
            return None
        if nonnegative and value < 0:
            self.error(topic, "numeric_negative", "该数值采用正向流量/存量约定，不得为负", f"{path}.{key}")
            return None
        return value

    def finish(self, topic: str, *, status: str | None = None, evidence_refs: list[str] | None = None,
               **data: Any) -> dict[str, Any]:
        findings = [item for item in self.findings if item["topic"] == topic]
        if any(item["severity"] == "ERROR" for item in findings):
            status = "INVALID"
        elif status is None:
            status = "INCOMPLETE" if any(item["severity"] == "WARN" for item in findings) else "OK"
        elif status in {"OK", "NOT_APPLICABLE"} and any(item["severity"] == "WARN" for item in findings):
            status = "INCOMPLETE"
        return {"status": status, "findings": findings, "evidence_refs": evidence_refs or [], **data}


def _records(raw: Any, reserved: tuple[str, ...] = ()) -> list[tuple[str | None, Any]] | None:
    if isinstance(raw, list):
        return [(None, item) for item in raw]
    if isinstance(raw, Mapping):
        if "records" in raw:
            return _records(raw["records"])
        return [(str(key), item) for key, item in raw.items() if key not in reserved]
    return None


def build_registry(ctx: Context) -> dict[str, Any]:
    facts = ctx.config.get("facts")
    if not isinstance(facts, Mapping):
        if facts is not None:
            ctx.error("registry", "facts_type", "facts必须为对象", "facts")
        else:
            ctx.warn("registry", "facts_missing", "缺少事实登记", "facts")
        facts = {}
    entity = facts.get("entity")
    if not isinstance(entity, Mapping) or not all(isinstance(entity.get(key), str) and entity[key].strip() for key in ("id", "name")):
        ctx.warn("registry", "entity_missing", "facts.entity须给出稳定id和公司name", "facts.entity")
    pending_assumptions: list[tuple[str, dict[str, Any], str]] = []
    for kind, raw, reserved in (("fact", facts, ("entity",)), ("assumption", ctx.config.get("assumptions"), ())):
        records = _records(raw, reserved)
        if records is None:
            if raw is None:
                ctx.warn("registry", f"{kind}_missing", "缺少登记列表", kind)
            else:
                ctx.error("registry", f"{kind}_type", "登记必须为数组、records对象或ID映射", kind)
            continue
        if kind == "fact" and not records:
            ctx.warn("registry", "facts_empty", "事实登记为空", "facts.records")
        for index, (map_id, record) in enumerate(records):
            path = f"{kind}s[{index}]"
            if not isinstance(record, Mapping):
                ctx.error("registry", "record_type", "登记记录必须为对象", path)
                continue
            rid = record.get("id", map_id)
            if not isinstance(rid, str) or not rid.strip():
                ctx.error("registry", "record_id_missing", "登记必须有非空字符串ID", path)
                continue
            if rid in ctx.registry:
                ctx.error("registry", "record_id_duplicate", "事实/假设ID必须全局唯一", path)
                continue
            if map_id and record.get("id") is not None and record["id"] != map_id:
                ctx.error("registry", "record_id_mismatch", "ID映射键与记录id不一致", path)
                continue
            ok = True
            for key in ("value", "unit", "period"):
                if key not in record or (key != "value" and (not isinstance(record[key], str) or not record[key].strip())):
                    ctx.warn("registry", "record_metadata_missing", f"登记缺少显式{key}", f"{path}.{key}")
                    ok = False
            if kind == "fact":
                source = record.get("source")
                external = record.get("external_ref")
                sourced = isinstance(source, Mapping) and all(isinstance(source.get(x), str) and source[x].strip() for x in ("title", "locator"))
                external_ok = isinstance(external, Mapping) and any(isinstance(external.get(x), str) and external[x].strip() for x in ("path", "uri")) and isinstance(external.get("locator"), str) and external["locator"].strip()
                if not sourced and not external_ok:
                    ctx.warn("registry", "fact_source_missing", "事实需source.title/locator或external_ref路径/URI及locator", path)
                    ok = False
                if record.get("published_at") is not None:
                    published = iso_date(record["published_at"])
                    if published is None:
                        ctx.warn("registry", "fact_publication_invalid", "事实发布日期无效", path)
                        ok = False
                    elif ctx.as_of is not None and published > ctx.as_of:
                        ctx.warn("registry", "fact_after_as_of", "事实在as_of之后发布，不进入可用引用登记", path)
                        ok = False
            else:
                reason = record.get("reason", record.get("rationale"))
                if not isinstance(reason, str) or not reason.strip():
                    ctx.warn("registry", "assumption_reason_missing", "假设须说明reason", path)
                    ok = False
            if ok:
                ctx.registry[rid] = {**record, "id": rid, "kind": kind}
                if kind == "assumption":
                    pending_assumptions.append((rid, dict(record), path))
    for rid, record, path in pending_assumptions:
        for ref in ctx.refs(record, "registry", path, required=False):
            if ref in ctx.registry and ctx.registry[ref]["kind"] != "fact":
                ctx.error("registry", "assumption_source_not_fact", "假设来源须指向事实登记", path)
    return ctx.finish("registry", entity=dict(entity) if isinstance(entity, Mapping) else None,
                      records=[dict(value) for _, value in sorted(ctx.registry.items())])
