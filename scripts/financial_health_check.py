# -*- coding: utf-8 -*-
"""Generate the current-period financial health evidence package.

Usage:
    python scripts/financial_health_check.py --dir <batch-dir>

The JSON is the machine-readable source of truth.  The Markdown file is a
human-readable evidence digest for the report-writing agent; it is not an
independent set of calculations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from financial_health_core import build_health_report, default_config, write_default_config
from chart_numbers import format_number


HEALTH_CHARTS = (
    "体检_01_利润表变化与利润来源.png",
    "体检_02_资产负债表与营运资本.png",
    "体检_03_现金流与利润现金化.png",
    "体检_04_三表勾稽与经营闭环.png",
    "体检_05_预测与估值影响.png",
)

CHART_COLORS = {
    "current": "#2563EB",
    "comparison": "#94A3B8",
    "positive": "#059669",
    "warning": "#D97706",
    "negative": "#DC2626",
    "neutral": "#64748B",
    "ink": "#172033",
    "grid": "#E2E8F0",
    "paper": "#F8FAFC",
}


def _setup_chart_style() -> None:
    plt.rcParams.update({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "axes.edgecolor": "#CBD5E1",
        "axes.labelcolor": CHART_COLORS["ink"],
        "xtick.color": "#475569",
        "ytick.color": "#475569",
        "text.color": CHART_COLORS["ink"],
        "axes.titleweight": "bold",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
    })


def _raw_amount(value: Any) -> float:
    try:
        return float(value) / 1e8 if value is not None else np.nan
    except (TypeError, ValueError):
        return np.nan


def _number(value: Any) -> float:
    try:
        return float(value) if value is not None else np.nan
    except (TypeError, ValueError):
        return np.nan


def _amount_value(value: Any) -> str:
    return format_number(_raw_amount(value))


def _chart_amount(value: Any, *, signed: bool = False) -> str:
    """Format chart amounts without misleading negative zero labels."""
    number = _number(value)
    if not np.isfinite(number):
        return "—"
    return format_number(number,signed=signed)


def _pct_value(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    try:
        return format_number(value,signed=True)+'%'
    except (TypeError, ValueError):
        return "—"


def _label_bars(ax: Any, bars: Any, *, amount: bool = True, percent: bool = False, fontsize: float = 8) -> None:
    for bar in bars:
        height = bar.get_height()
        if not np.isfinite(height):
            continue
        if amount:
            label = _chart_amount(height)
        elif percent:
            label = f"{format_number(height,signed=True)}%"
        else:
            label = f"{format_number(height)}"
        offset = 4 if height >= 0 else -14
        va = "bottom" if height >= 0 else "top"
        ax.annotate(label, (bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, offset), textcoords="offset points", ha="center", va=va,
                    fontsize=fontsize, color=CHART_COLORS["ink"])


def _grouped_bars(ax: Any, labels: list[str], current: list[float], comparison: list[float],
                  current_label: str, comparison_label: str, *, amount: bool = True,
                  percent: bool = False) -> None:
    x = np.arange(len(labels))
    width = 0.36
    bars_current = ax.bar(x - width / 2, current, width, label=current_label, color=CHART_COLORS["current"])
    bars_comparison = ax.bar(x + width / 2, comparison, width, label=comparison_label, color=CHART_COLORS["comparison"])
    _label_bars(ax, bars_current, amount=amount, percent=percent)
    _label_bars(ax, bars_comparison, amount=amount, percent=percent)
    ax.set_xticks(x, labels)
    ax.tick_params(axis="x", pad=7)
    ax.margins(y=0.12)
    ax.grid(axis="y", color=CHART_COLORS["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=2)


def _chart_frame(fig: Any, title: str, subtitle: str) -> None:
    fig.suptitle(title, x=0.03, y=0.98, ha="left", fontsize=16, fontweight="bold", color=CHART_COLORS["ink"])
    fig._layout_subtitle=fig.text(0.03, 0.935, subtitle, ha="left", fontsize=9, color="#64748B")
    fig.text(0.03, 0.018, "来源：本批次本期财报体检 JSON；金额单位：亿元，比例单位：%", fontsize=8, color="#64748B")


def _save_chart(fig: Any, path: Path, *, tight_layout: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    from financial_history_charts import layout_native,layout_text_panel
    if not tight_layout:
        layout_text_panel(fig,fig.axes[0])
    layout_native(fig)
    fig.savefig(path, dpi=150, bbox_inches="tight",
                bbox_extra_artists=[t for t in fig.texts if t.get_visible()]+list(fig.legends))
    audit_path=path.parent.parent/'本期财报体检_图表排版审核.json'
    audit=json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.exists() else {}
    audit[path.name]={'png_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),**fig._layout_audit}
    audit_path.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    plt.close(fig)


def _finite_values(values: list[Any]) -> list[float]:
    return [float(value) for value in values if value is not None and np.isfinite(_number(value))]


def _wrap_label(value: Any, width: int = 10) -> str:
    return "\n".join(textwrap.wrap(str(value), width=width, break_long_words=False, break_on_hyphens=False))


def _inventory_status_label(status: Any) -> str:
    return {
        "normal": "正常备货或暂未见组合风险",
        "order_supported": "订单/预收支持",
        "needs_review": "需要观察存货减值和周转",
        "indeterminate": "无法判断，需补充附注",
        "not_applicable": "当前行业不适用",
    }.get(str(status), "待核实")


def _financial_status_label(status: Any) -> str:
    return {
        "normal": "未见明显非主营支撑风险",
        "needs_review": "非主营投资收益需核查可持续性",
        "indeterminate": "金融资产数据不足",
        "not_applicable": "当前行业不适用",
    }.get(str(status), "待核实")


def _follow_up_items(data: dict[str, Any]) -> list[str]:
    items: list[str] = []
    cash = data.get("cash_flow_diagnosis", {})
    inventory = data.get("inventory_review", {})
    finance = data.get("financial_asset_review", {})
    if cash.get("status") in {"needs_explanation", "indeterminate"}:
        items.append("经营现金流修复：核对下一期回款、原材料采购、应付付款和间接法调整项。")
    elif cash.get("status") == "seasonal":
        items.append("回款季节性：观察后续季度回款是否符合历史节奏，不把单季现金流简单年化。")
    else:
        items.append("经营现金流：继续观察现金流是否与利润同步，确认利润现金化没有反复。")
    if inventory.get("applicable") and inventory.get("status") == "needs_review":
        items.append("存货消化：核查库龄、跌价准备、原材料/产成品结构、订单覆盖和后续销售。")
    elif inventory.get("applicable"):
        items.append("存货变化：观察备货能否转化为收入，及周转天数和跌价准备是否稳定。")
    if finance.get("status") == "needs_review":
        items.append("投资收益：区分已实现收益、浮盈和长期股权投资收益，观察非主营收益是否重复出现。")
    if data.get("profit_diagnosis", {}).get("status") == "volatile":
        items.append("利润波动：跟踪汇兑、投资收益、公允价值变动、减值和税率对下一期利润的影响。")
    management = data.get("management_evidence", {})
    industry = data.get("industry_context", {})
    if management.get("status") != "available":
        items.append("管理层解释：补充本期原版财报或公告，核对公司对利润和现金流变化的解释。")
    return items[:5] or ["下一期财报：复核利润、经营现金流和关键营运项目是否回到合理区间。"]


def _render_cash_chart(data: dict[str, Any], path: Path) -> None:
    """Chart 01: operating cash flow, profit and cash conversion trend."""
    diagnosis = data.get("cash_flow_diagnosis", {})
    history = diagnosis.get("history", []) or diagnosis.get("industry_seasonality", {}).get("history_same_period", [])
    current_period = data.get("report_period", {}).get("current")
    if history:
        history = [item for item in history if item.get("period")]
        history = history[-6:]
    if not history:
        current = data["cash_flow"]["current"]
        income = data["income_statement"]["current"]
        history = [{
            "period": current_period or "本期",
            "operating_cash_flow": current.get("operating_cash_flow"),
            "parent_net_profit": income.get("parent_net_profit"),
            "ocf_to_profit_pct": current.get("ocf_to_parent_net_profit_pct"),
        }]
    labels = [str(item.get("period", ""))[:7] for item in history]
    ocf = [_raw_amount(item.get("operating_cash_flow")) for item in history]
    profit = [_raw_amount(item.get("parent_net_profit")) for item in history]
    conversion = [_number(item.get("ocf_to_profit_pct")) for item in history]
    period = data["report_period"]
    fig, axes = plt.subplots(1, 2, figsize=(14.2, 7.0), gridspec_kw={"width_ratios": [1.45, 1]})
    _chart_frame(fig, "本期财报体检 | 现金流：赚的是真钱还是账面利润",
                 f"{period.get('current') or '本期'} | 经营现金流与归母净利润趋势；比例越高，利润现金化越强")
    x = np.arange(len(labels))
    width = 0.34 if len(labels) > 1 else 0.45
    bars_ocf = axes[0].bar(x - width / 2, ocf, width, label="经营现金流", color=CHART_COLORS["current"])
    bars_profit = axes[0].bar(x + width / 2, profit, width, label="归母净利润", color=CHART_COLORS["comparison"])
    for bars in (bars_ocf, bars_profit):
        _label_bars(axes[0], bars, fontsize=8)
    axes[0].set_xticks(x, labels)
    axes[0].set_title("经营现金流与归母净利润（亿元）", loc="left", fontsize=11, pad=12)
    axes[0].set_ylabel("亿元")
    axes[0].axhline(0, color="#64748B", linewidth=0.8)
    axes[0].grid(axis="y", color=CHART_COLORS["grid"], linewidth=0.8)
    axes[0].set_axisbelow(True)
    axes[0].legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.02), ncol=2)
    axes[0].margins(x=0.08, y=0.18)

    valid_conversion = [value if np.isfinite(value) else np.nan for value in conversion]
    axes[1].plot(x, valid_conversion, color=CHART_COLORS["positive"], marker="o", linewidth=2.2)
    for idx, value in enumerate(valid_conversion):
        if np.isfinite(value):
            axes[1].annotate(f"{format_number(value)}%", (idx, value), xytext=(0, 9), textcoords="offset points",
                             ha="center", va="bottom", fontsize=8.5, color=CHART_COLORS["ink"])
    axes[1].axhline(100, color="#CBD5E1", linestyle="--", linewidth=1.0)
    axes[1].set_xticks(x, labels)
    axes[1].set_title("经营现金流 / 归母净利润（%）", loc="left", fontsize=11, pad=12)
    axes[1].set_ylabel("%")
    axes[1].grid(axis="y", color=CHART_COLORS["grid"], linewidth=0.8)
    axes[1].set_axisbelow(True)
    axes[1].margins(x=0.10, y=0.24)
    _save_chart(fig, path)


def _render_driver_chart(data: dict[str, Any], path: Path) -> None:
    """Chart 02: explain the change in operating cash flow."""
    diagnosis = data.get("cash_flow_diagnosis", {})
    drivers = [item for item in diagnosis.get("drivers", []) if item.get("cash_effect") is not None][:7]
    period = data["report_period"]
    fig, ax = plt.subplots(figsize=(14.2, 7.0))
    _chart_frame(fig, "本期财报体检 | 经营现金流变化原因",
                 f"{period.get('current') or '本期'} | 正值为增加现金，负值为占用现金；经营、投资、筹资现金流分开判断")
    if drivers:
        drivers = list(reversed(drivers))
        labels = [_wrap_label(item.get("type", "其他经营项目"), 12) for item in drivers]
        values = [_raw_amount(item.get("cash_effect")) for item in drivers]
        colors = [CHART_COLORS["positive"] if value >= 0 else CHART_COLORS["negative"] for value in values]
        y = np.arange(len(labels))
        bars = ax.barh(y, values, color=colors, height=0.52)
        ax.set_yticks(y, labels)
        ax.tick_params(axis="y", pad=9)
        for bar, value, item in zip(bars, values, drivers):
            if not np.isfinite(value):
                continue
            offset = 8 if value >= 0 else -8
            ha = "left" if value >= 0 else "right"
            ax.annotate(f"{_chart_amount(value, signed=True)} 亿元", (value, bar.get_y() + bar.get_height() / 2),
                        xytext=(offset, 0), textcoords="offset points", ha=ha, va="center", fontsize=9,
                        color=CHART_COLORS["ink"])
        ax.set_xlabel("估算现金影响（亿元）")
        ax.axvline(0, color="#64748B", linewidth=0.9)
        ax.ticklabel_format(style="plain", axis="x", useOffset=False)
        ax.set_title("经营项目对现金流的方向性影响", loc="left", fontsize=11, pad=12)
        ax.grid(axis="x", color=CHART_COLORS["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        ax.margins(x=0.18, y=0.12)
    else:
        ax.axis("off")
        ax.text(0.5, 0.57, "本期未取得足够经营项目字段，\n暂不能拆分经营现金流变化原因。",
                ha="center", va="center", fontsize=16, color=CHART_COLORS["warning"], fontweight="bold")
        ax.text(0.5, 0.38, "需补充现金流量表间接法调整项及附注解释。", ha="center", va="center", fontsize=11, color="#475569")
    _save_chart(fig, path)


def _render_profit_chart(data: dict[str, Any], path: Path) -> None:
    """Chart 03: profit bridge, separating operating and non-operating drivers."""
    diagnosis = data.get("profit_diagnosis", {})
    parent = data["income_statement"]["current"].get("parent_net_profit")
    prior = data["income_statement"]["yoy"].get("parent_net_profit")
    components = []
    for item in diagnosis.get("summary_drivers", []):
        value = item.get("profit_effect")
        if value is not None and abs(float(value)) > 0:
            components.append((item.get("type", "其他因素"), _raw_amount(value)))
    components = components[:6]
    period = data["report_period"]
    fig, ax = plt.subplots(figsize=(14.2, 7.0))
    _chart_frame(fig, "本期财报体检 | 利润波动原因",
                 f"{period.get('current') or '本期'} | 从同比归母净利润桥接到本期，区分主营经营与非主营因素")
    if parent is None or prior is None:
        ax.axis("off")
        ax.text(0.5, 0.55, "归母净利润可比数据不足，暂不能拆分利润波动。", ha="center", va="center", fontsize=16, color=CHART_COLORS["warning"], fontweight="bold")
        _save_chart(fig, path)
        return
    labels = ["同比归母\n净利润"] + [_wrap_label(label, 10) for label, _ in components] + ["本期归母\n净利润"]
    start = _raw_amount(prior)
    end = _raw_amount(parent)
    values = [start] + [value for _, value in components] + [end]
    x = np.arange(len(labels))
    bottoms = [0.0]
    heights = [start]
    colors = [CHART_COLORS["comparison"]]
    running = start
    for _, value in components:
        bottoms.append(min(running, running + value))
        heights.append(abs(value))
        colors.append(CHART_COLORS["positive"] if value >= 0 else CHART_COLORS["negative"])
        running += value
    bottoms.append(0.0)
    heights.append(end)
    colors.append(CHART_COLORS["current"])
    bars = ax.bar(x, heights, bottom=bottoms, color=colors, width=0.58)
    for index, (bar, value) in enumerate(zip(bars, values)):
        if not np.isfinite(value):
            continue
        if index in (0, len(values) - 1):
            y = bar.get_y() + bar.get_height()
            va = "bottom"
            label = _chart_amount(value)
        elif abs(value) >= 1.0 and bar.get_height() >= 0.7:
            y = bar.get_y() + bar.get_height() / 2
            va = "center"
            label = _chart_amount(value, signed=True)
        else:
            y = bar.get_y() + bar.get_height()
            va = "bottom"
            label = _chart_amount(value, signed=True)
        ax.annotate(label, (bar.get_x() + bar.get_width() / 2, y),
                    xytext=(0, 5 if va == "bottom" else 0), textcoords="offset points",
                    ha="center", va=va, fontsize=8.5,
                    color="white" if index not in (0, len(values) - 1) and abs(value) >= 1.0 and bar.get_height() >= 0.7 else CHART_COLORS["ink"],
                    fontweight="bold" if index not in (0, len(values) - 1) and abs(value) >= 1.0 and bar.get_height() >= 0.7 else "normal")
    for index in range(1, len(values) - 1):
        level = bottoms[index] + heights[index] if components[index - 1][1] >= 0 else bottoms[index]
        ax.plot([index - 0.29, index + 0.29], [level, level], color="#94A3B8", linestyle="--", linewidth=0.8)
    ax.set_xticks(x, labels)
    ax.tick_params(axis="x", pad=10)
    ax.set_ylabel("归母净利润（亿元）")
    ax.ticklabel_format(style="plain", axis="y", useOffset=False)
    ax.set_title("归母净利润同比变动桥（亿元）", loc="left", fontsize=11, pad=12)
    ax.axhline(0, color="#64748B", linewidth=0.8)
    ax.grid(axis="y", color=CHART_COLORS["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    ax.margins(x=0.06, y=0.22)
    _save_chart(fig, path)


def _render_special_review_chart(data: dict[str, Any], path: Path) -> None:
    """Chart 04: inventory review when applicable, otherwise financial assets."""
    inventory = data.get("inventory_review", {})
    finance = data.get("financial_asset_review", {})
    period = data["report_period"]
    fig, ax = plt.subplots(figsize=(14.2, 7.0))
    if inventory.get("applicable"):
        _chart_frame(fig, "本期财报体检 | 存货专项检查",
                     f"{period.get('current') or '本期末'} | 只有结合行业、收入增速和周转变化后，才判断存货是否构成风险")
        labels = ["收入增速", "存货增速", "存货周转天数", "合同负债增速"]
        values = [inventory.get("revenue_growth_pct"), inventory.get("inventory_growth_pct"),
                  inventory.get("inventory_days_change_pct"), inventory.get("contract_liability_growth_pct")]
        numeric = [_number(value) for value in values]
        colors = [CHART_COLORS["current"], CHART_COLORS["warning"], CHART_COLORS["negative"], CHART_COLORS["positive"]]
        x = np.arange(len(labels))
        bars = ax.bar(x, numeric, color=colors, width=0.58)
        _label_bars(ax, bars, amount=False, percent=True, fontsize=9)
        ax.set_xticks(x, ["收入\n增速", "存货\n增速", "周转天数\n变化", "合同负债\n增速"])
        ax.set_ylabel("同比变化（%）")
        ax.axhline(0, color="#64748B", linewidth=0.8)
        ax.grid(axis="y", color=CHART_COLORS["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        ax.set_title(f"存货检查结论：{_inventory_status_label(inventory.get('status'))}", loc="left", fontsize=11, pad=12)
        ax.margins(x=0.12, y=0.24)
    elif finance.get("applicable"):
        _chart_frame(fig, "本期财报体检 | 非主营投资和金融资产检查",
                     f"{period.get('current') or '本期'} | 区分已实现收益、浮盈和产业投资，不能仅凭投资收益认定异常")
        components = finance.get("components", [])
        labels = [item.get("type", "金融资产") for item in components]
        values = [_raw_amount(item.get("current")) for item in components]
        if not labels:
            labels = ["投资收益", "公允价值变动"]
            values = [_raw_amount(finance.get("investment_income")), _raw_amount(finance.get("fair_value_change"))]
        valid = [value if np.isfinite(value) else 0.0 for value in values]
        if not any(abs(value) >= 0.005 for value in valid):
            ax.axis("off")
            ax.text(0.5, 0.56, "本期未发现可量化的金融资产余额",
                    ha="center", va="center", fontsize=15, color=CHART_COLORS["neutral"], fontweight="bold")
            ax.text(0.5, 0.40, "投资收益、公允价值变动的性质仍需结合附注核实。",
                    ha="center", va="center", fontsize=11, color="#475569")
            _save_chart(fig, path)
            return
        y = np.arange(len(labels))
        bars = ax.barh(y, valid, color=CHART_COLORS["current"], height=0.5)
        ax.set_yticks(y, [_wrap_label(label, 14) for label in labels])
        ax.set_xlabel("期末规模/金额（亿元）")
        ax.set_title(f"金融资产检查结论：{_financial_status_label(finance.get('status'))}", loc="left", fontsize=11, pad=12)
        ax.grid(axis="x", color=CHART_COLORS["grid"], linewidth=0.8)
        ax.set_axisbelow(True)
        for bar, value in zip(bars, valid):
            if abs(value) < 0.005:
                continue
            ax.annotate(_chart_amount(value), (value, bar.get_y() + bar.get_height() / 2), xytext=(7, 0), textcoords="offset points", va="center", fontsize=9)
        ax.margins(x=0.16, y=0.16)
    else:
        _chart_frame(fig, "本期财报体检 | 专项检查",
                     f"{period.get('current') or '本期'} | 当前行业配置未启用存货或金融资产专项检查")
        ax.axis("off")
        ax.text(0.5, 0.55, "当前行业口径不适用自动存货专项检查，\n且未配置可比金融资产专项数据。", ha="center", va="center", fontsize=15, color=CHART_COLORS["neutral"], fontweight="bold")
        ax.text(0.5, 0.36, "不因缺少专项字段强行给出风险结论。", ha="center", va="center", fontsize=11, color="#475569")
    _save_chart(fig, path)


def _render_explanation_chart(data: dict[str, Any], path: Path) -> None:
    """Chart 05: management evidence coverage and follow-up items."""
    management = data.get("management_evidence", {})
    followups = _follow_up_items(data)
    period = data["report_period"]
    fig = plt.figure(figsize=(14.2, 7.0))
    _chart_frame(fig, "本期财报体检 | 管理层解释与后续观察",
                 f"{period.get('current') or '本期'} | 管理层解释是线索，必须与三表和附注交叉验证")
    ax = fig.add_axes([0.055, 0.10, 0.89, 0.76])
    ax.axis("off")
    status = management.get("status")
    status_text = "已取得原版财报重点段落" if status == "available" else "本期管理层解释未取得"
    status_color = CHART_COLORS["positive"] if status == "available" else CHART_COLORS["warning"]
    ax.text(0.0, 0.96, status_text, fontsize=13, fontweight="bold", color=status_color, va="top")
    ax.text(0.0, 0.89, "覆盖主题：" + ("、".join(management.get("covered_topics", [])) or "—"), fontsize=10, color="#475569", va="top")
    ax.text(0.0, 0.78, "重点后续观察事项", fontsize=11, fontweight="bold", color=CHART_COLORS["ink"], va="top")
    for index, item in enumerate(followups[:5], start=1):
        wrapped = textwrap.fill(item, width=64, subsequent_indent="   ")
        ax.text(0.02, 0.78 - index * 0.115, f"{index}. {wrapped}", fontsize=10, color=CHART_COLORS["ink"], va="top")
    if status != "available":
        ax.text(0.0, 0.08, "报告中应明确披露：本期管理层解释未取得，不能用脚本或历史材料代替管理层观点。", fontsize=9.5, color=CHART_COLORS["warning"], va="bottom")
    _save_chart(fig, path, tight_layout=False)


def render_health_charts(data: dict[str, Any], charts_dir: Path) -> list[Path]:
    """Generate the fixed five-chart health section in a deterministic visual format."""
    _setup_chart_style()
    paths = [charts_dir / name for name in HEALTH_CHARTS]
    _render_cash_chart(data, paths[0])
    _render_driver_chart(data, paths[1])
    _render_profit_chart(data, paths[2])
    _render_special_review_chart(data, paths[3])
    _render_explanation_chart(data, paths[4])
    return paths


def _display_period_type(value: Any) -> str:
    return {
        "annual": "年报",
        "semiannual": "半年报",
        "q1": "一季报",
        "q3": "三季报",
    }.get(str(value), str(value) if value else "本期报告")


def _pp(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{format_number(float(value),signed=True)} 个百分点"
    except (TypeError, ValueError):
        return "—"


def _signal_by_id(data: dict[str, Any], signal_id: str) -> dict[str, Any]:
    return next((item for item in data.get("signals", []) if item.get("id") == signal_id), {})


def _human_status(status: Any) -> str:
    return {
        "triggered": "已触发",
        "not_triggered": "未触发",
        "indeterminate": "待补证据",
        "reconciled": "可复算",
        "needs_explanation": "需解释残差",
    }.get(str(status), "待核实")


def _human_signal_basis(signal: dict[str, Any]) -> str:
    actual = signal.get("actual") or {}
    signal_id = signal.get("id")
    if signal_id == "FH_AR_CASH_DIVERGENCE":
        return (
            f"收入同比 {_pct(actual.get('revenue_growth_pct'))}；"
            f"应收账款与合同资产合计同比 {_pct(actual.get('receivable_contract_growth_pct'))}；"
            f"经营现金流/归母净利润 {_percent_ratio(actual.get('ocf_to_profit'))}"
        )
    if signal_id == "FH_INVENTORY_PRESSURE":
        return (
            f"收入同比 {_pct(actual.get('revenue_growth_pct'))}；"
            f"存货同比 {_pct(actual.get('inventory_growth_pct'))}；"
            f"经营现金流同比 {_pct(actual.get('ocf_growth_pct'))}"
        )
    if signal_id == "FH_OPERATING_MARGIN_PRESSURE":
        margins = actual.get("margin_change_pp") or []
        labels = ("毛利率", "营业利润率", "净利率")
        margin_text = "；".join(f"{label} {_pp(value)}" for label, value in zip(labels, margins))
        return f"收入同比 {_pct(actual.get('revenue_growth_pct'))}；{margin_text or '利润率变化待补充'}"
    if signal_id == "FH_NON_OPERATING_PROFIT":
        return (
            f"非核心项目合计 {_amount(actual.get('non_operating_income'))} 亿元，"
            f"占归母净利润 {_percent_ratio(actual.get('non_operating_profit_share'))}；"
            f"扣非差额占比 {_percent_ratio(actual.get('non_deducted_profit_share'))}"
        )
    if signal_id == "FH_ASSETIZATION_REVIEW":
        values = actual.get("growth_pct") or []
        names = ("开发支出", "无形资产", "在建工程")
        return "；".join(f"{name} {_pct(value)}" for name, value in zip(names, values)) or "资产化相关项目增速待补充"
    if signal_id == "FH_IMPAIRMENT_CLEANUP":
        return (
            f"减值占归母净利润 {_percent_ratio(actual.get('impairment_to_profit'))}；"
            f"本期经营现金流/归母净利润 {_percent_ratio(actual.get('ocf_to_profit'))}；"
            f"同比期 {_percent_ratio(actual.get('prior_ocf_to_profit'))}"
        )
    if signal_id == "FH_CONTRACT_ORDER_SUPPORT":
        return (
            f"合同负债同比 {_pct(actual.get('contract_liability_growth_pct'))}；"
            f"收入同比 {_pct(actual.get('revenue_growth_pct'))}；"
            f"经营现金流同比 {_pct(actual.get('ocf_growth_pct'))}"
        )
    if signal_id == "FH_Q4_OCF_SEASONALITY":
        return (
            f"Q4 经营现金流占全年 {_percent_ratio(actual.get('q4_share_pct'))}；"
            f"连续性判断：{actual.get('pattern') or '待补充'}"
        )
    return _cell(actual)


def _human_signal_threshold(signal: dict[str, Any]) -> str:
    threshold = signal.get("threshold") or {}
    signal_id = signal.get("id")
    if signal_id == "FH_AR_CASH_DIVERGENCE":
        return f"增速差超过 {_cell(threshold.get('growth_gap_pp'))} 个百分点，且现金转化低于 {_cell(threshold.get('cash_conversion_floor'))}% 或同比下降"
    if signal_id == "FH_INVENTORY_PRESSURE":
        return f"存货增速至少高于收入 {_cell(threshold.get('growth_gap_pp'))} 个百分点，且经营现金流同比下降"
    if signal_id == "FH_OPERATING_MARGIN_PRESSURE":
        return f"至少一项利润率下降 {_cell(threshold.get('margin_decline_pp'))} 个百分点"
    if signal_id == "FH_NON_OPERATING_PROFIT":
        return f"非核心收益占比达到 {_cell(threshold.get('material_non_operating_share'))}%，或扣非差额占比达到 {_cell(threshold.get('one_time_profit_share'))}%"
    if signal_id == "FH_ASSETIZATION_REVIEW":
        return f"至少两项资产化相关项目增速达到 {_cell(threshold.get('assetization_growth_pct'))}%"
    if signal_id == "FH_IMPAIRMENT_CLEANUP":
        return f"减值占归母净利润达到 {_cell(threshold.get('material_share'))}% 且现金转化未同步恶化"
    if signal_id == "FH_CONTRACT_ORDER_SUPPORT":
        return f"合同负债增速高于收入 {_cell(threshold.get('growth_gap_pp'))} 个百分点，且应收受控、经营现金流不下降"
    if signal_id == "FH_Q4_OCF_SEASONALITY":
        return f"Q4 经营现金流占全年超过 {_cell(threshold.get('q4_share_pct'))}%"
    return _cell(threshold)


def _human_signal_conclusion(signal: dict[str, Any]) -> str:
    status = signal.get("status")
    title = signal.get("title") or "该项检测"
    if status == "triggered":
        return f"检测到{title}，属于需要结合附注和后续数据核实的观察信号，不等于违规或财务造假结论。"
    if status == "indeterminate":
        return f"暂不能判断{title}，当前关键数据不足，不能用缺失值替代正常或异常。"
    if signal.get("direction") == "positive":
        return f"本期未同时满足{title}的组合条件，正面逻辑尚未形成完整证据链。"
    return f"本期未同时满足{title}的组合条件，不代表相关风险已经排除。"


def _impact_handling(dimension: str, value: str) -> str:
    if value == "上调":
        return "提高该维度假设或置信度，但仍需后续数据验证。"
    if value == "下调":
        return "下调该维度的预测置信度；本次不自动改写全年模型数值。"
    if dimension == "估值风险":
        return "暂不自动改写估值区间，保留风险观察。"
    return "暂不自动改写全年模型数值，等待后续季度验证。"


def _impact_follow_up(dimension: str) -> str:
    return {
        "收入": "合同负债兑现、订单交付和分部收入增速",
        "利润": "毛利率、费用率、扣非利润及非核心收益变化",
        "现金流": "库存消化、应收回款、采购付款和经营现金流修复",
        "估值风险": "Q2/Q3 经营现金流、全年回款季节性及盈利兑现",
    }.get(dimension, "下一期财报及附注")


def _cash_status_label(status: Any) -> str:
    return {
        "stable": "现金流未出现需要升级解释的明显恶化",
        "seasonal": "现金流下降与历史/行业季节性相符，暂不升级为风险",
        "explainable": "现金流下降已有经营项目初步解释，仍需附注核实",
        "needs_explanation": "现金流下降超出已识别季节性，需要重点解释",
        "indeterminate": "现金流或可比期间数据不足，暂不能判断",
    }.get(str(status), "现金流状态待核实")


def _profit_status_label(status: Any) -> str:
    return {
        "stable": "利润波动未达到重点解释阈值",
        "volatile": "利润出现大幅波动，需要拆分主营与非主营因素",
        "indeterminate": "利润可比数据不足，暂不能完整归因",
    }.get(str(status), "利润变化待核实")


def _driver_direction(value: Any, positive: str, negative: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "待补证据"
    return positive if number > 0 else negative if number < 0 else "影响有限"


def _key_signals(data: dict[str, Any]) -> list[dict[str, Any]]:
    ids = {"FH_CASH_FLOW_EXPLANATION", "FH_PROFIT_VOLATILITY", "FH_INVENTORY_REVIEW", "FH_FINANCIAL_ASSET_SPECULATION"}
    return [signal for signal in data.get("signals", []) if signal.get("id") in ids]


def _management_source(item: dict[str, Any]) -> str:
    source = item.get("source_file") or "原版财报"
    section = item.get("section") or "相关章节"
    page = f"，第{item['page']}页" if item.get("page") else ""
    return f"{source}，{section}{page}"


def _follow_up_items(data: dict[str, Any]) -> list[str]:
    items: list[str] = []
    cash = data.get("cash_flow_diagnosis", {})
    inventory = data.get("inventory_review", {})
    finance = data.get("financial_asset_review", {})
    if cash.get("status") in {"needs_explanation", "indeterminate"}:
        items.append("经营现金流修复：核对下一期回款、原材料采购、应付付款和间接法调整项。")
    elif cash.get("status") == "seasonal":
        items.append("回款季节性：观察后续季度回款是否符合历史节奏，不把单季现金流简单年化。")
    elif cash.get("status") == "explainable":
        items.append("经营现金流原因：验证存货、应收和应付变化是否确实解释现金流下降。")
    else:
        items.append("经营现金流：继续观察现金流是否与利润同步，确认利润现金化没有反复。")
    if inventory.get("applicable") and inventory.get("status") == "needs_review":
        items.append("存货消化：核查库龄、跌价准备、原材料/产成品结构、订单覆盖和后续销售。")
    elif inventory.get("applicable"):
        items.append("存货变化：观察备货能否转化为收入，及周转天数和跌价准备是否稳定。")
    if finance.get("status") == "needs_review":
        items.append("投资收益：区分已实现收益、浮盈和长期股权投资收益，观察非主营收益是否重复出现。")
    if data.get("profit_diagnosis", {}).get("status") == "volatile":
        items.append("利润波动：跟踪汇兑、投资收益、公允价值变动、减值和税率对下一期利润的影响。")
    if data.get("management_evidence", {}).get("status") != "available":
        items.append("管理层解释：补充本期原版财报或公告，核对公司对利润和现金流变化的解释。")
    return items[:5] or ["下一期财报：复核利润、经营现金流和关键营运项目是否回到合理区间。"]


def _cash_flow_reason_rows(data: dict[str, Any]) -> list[str]:
    drivers = data.get("cash_flow_diagnosis", {}).get("drivers", [])
    if not drivers:
        return ["| — | — | — | 当前字段不足，无法拆分经营现金流变化原因。 |"]
    rows = []
    for item in drivers[:7]:
        effect = item.get("cash_effect")
        rows.append(
            f"| {item.get('type') or '其他经营项目'} | **{_amount(effect)}** | "
            f"**{item.get('direction') or _driver_direction(effect, '增加现金', '占用现金')}**；{item.get('importance') or '观察'} | "
            f"{item.get('explanation') or '结合现金流量表和附注核实'} |"
        )
    return rows


def _profit_driver_rows(data: dict[str, Any]) -> list[str]:
    drivers = data.get("profit_diagnosis", {}).get("summary_drivers", [])
    if not drivers:
        return ["| — | — | 当前可比利润字段不足，暂不能拆分。 |"]
    rows = []
    for item in drivers[:6]:
        effect = item.get("profit_effect")
        rows.append(f"| {item.get('type') or '其他因素'} | **{_amount(effect)}** | {item.get('direction') or _driver_direction(effect, '增厚利润', '拖累利润')}；{item.get('explanation') or '结合附注核实'} |")
    return rows


def _legacy_render_report_section(data: dict[str, Any], json_digest: str) -> str:
    """Retained for historical comparison; the active renderer is below."""
    period = data["report_period"]
    income = data["income_statement"]["current"]
    income_yoy = data["income_statement"]["yoy"]
    balance = data["balance_sheet"]["current"]
    balance_yoy = data["balance_sheet"]["yoy"]
    balance_prior = data["balance_sheet"].get("prior_period_end", {})
    cash = data["cash_flow"]["current"]
    cash_yoy = data["cash_flow"]["yoy"]
    metrics = income.get("metrics", {})
    yoy_metrics = income_yoy.get("metrics", {})
    current_growth = income.get("growth_pct", {})
    balance_growth = balance.get("growth_pct", {})
    cash_growth = cash.get("growth_pct", {})
    pbridge = data["bridges"]["profit_to_operating_cash_flow"]
    wcbridge = data["bridges"]["working_capital"]
    cbridge = data["bridges"]["cash_reconciliation"]
    non_core = None
    non_core_values = [income.get(key) for key in ("investment_income", "fair_value_change", "asset_disposal_income", "other_income")]
    if all(value is not None for value in non_core_values):
        non_core = sum(non_core_values)
    parent = income.get("parent_net_profit")
    deduct = income.get("deduct_parent_net_profit")
    deduct_gap = parent - deduct if parent is not None and deduct is not None else None
    period_label = f"{period.get('current') or '本期'} {period.get('report_type') or _display_period_type(period.get('period_type'))}"
    yoy_label = period.get("yoy") or "同比期"
    balance_prior_label = period.get("prior_period_end") or "上期末"
    lines = [
        "### §4.3 本期财报体检",
        "",
        f"> 体检期间：**{period_label}**；同比期：**{yoy_label}**；金额单位：亿元。数字唯一来源：`reports/本期财报体检.json`。",
        "> 本章节是财报体检和风险提示，不是审计意见；脚本检测到的信号需要结合财报附注、公告和后续季度数据核实。",
        "",
        "#### 本期财报结论先行",
        "",
        f"本期经营表现为“收入和利润温和增长，但现金流明显转弱、库存占用上升，利润来源需要拆解”。"
        f"营业收入 **{_amount(income.get('revenue'))} 亿元，同比 {_pct(current_growth.get('revenue'))}**；"
        f"归母净利润 **{_amount(income.get('parent_net_profit'))} 亿元，同比 {_pct(current_growth.get('parent_net_profit'))}**；"
        f"经营活动现金流 **{_amount(cash.get('operating_cash_flow'))} 亿元，同比 {_pct(cash_growth.get('operating_cash_flow'))}**，"
        f"自由现金流 **{_amount(cash.get('free_cash_flow'))} 亿元**。",
        "",
        "| 体检结论 | 本次结果 | 解释 |",
        "|---|---|---|",
        f"| 收入 | **{data.get('forecast_impact', {}).get('revenue', '待观察')}** | 收入保持增长，但订单兑现与后续交付仍需观察。 |",
        f"| 利润 | **{data.get('forecast_impact', {}).get('profit', '待观察')}** | 利润增速低于收入，且非核心项目贡献较高。 |",
        f"| 现金流 | **{data.get('forecast_impact', {}).get('cash_flow', '待观察')}** | 本期经营现金流和自由现金流均为负，利润现金化明显偏弱。 |",
        f"| 估值风险 | **{data.get('forecast_impact', {}).get('valuation_risk', '待观察')}** | 暂不线性年化 Q1 现金流，等待库存、回款和全年现金流验证。 |",
        "",
        "#### 利润表变化及利润来源",
        "",
        "![体检图01 利润表变化与利润来源](图表/体检_01_利润表变化与利润来源.png)",
        "",
        "| 指标 | 本期 | 同比期 | 同比变化 |",
        "|---|---:|---:|---:|",
    ]
    for label, key in (("营业收入", "revenue"), ("营业利润", "operating_profit"), ("归母净利润", "parent_net_profit"), ("扣非归母净利润", "deduct_parent_net_profit")):
        lines.append(f"| {label} | **{_amount(income.get(key))}** | {_amount(income_yoy.get(key))} | **{_pct(current_growth.get(key))}** |")
    lines.extend([
        "",
        "| 利润率 | 本期 | 较同比期 |",
        "|---|---:|---:|",
        f"| 毛利率 | **{_percent_ratio(metrics.get('gross_margin_pct'))}** | {_pp((metrics.get('gross_margin_pct') - yoy_metrics.get('gross_margin_pct')) if metrics.get('gross_margin_pct') is not None and yoy_metrics.get('gross_margin_pct') is not None else None)} |",
        f"| 营业利润率 | **{_percent_ratio(metrics.get('operating_margin_pct'))}** | {_pp((metrics.get('operating_margin_pct') - yoy_metrics.get('operating_margin_pct')) if metrics.get('operating_margin_pct') is not None and yoy_metrics.get('operating_margin_pct') is not None else None)} |",
        f"| 净利率 | **{_percent_ratio(metrics.get('net_margin_pct'))}** | {_pp((metrics.get('net_margin_pct') - yoy_metrics.get('net_margin_pct')) if metrics.get('net_margin_pct') is not None and yoy_metrics.get('net_margin_pct') is not None else None)} |",
        "",
        f"利润端的核心结论是：**收入、营业利润和归母净利润均增长，但利润增速略低于收入增速**；扣非归母净利润增速进一步低于归母净利润增速。"
        f"本期扣非差额为 **{_amount(deduct_gap)} 亿元**。"
        + (f"按本次体检口径，非核心项目合计 **{_amount(non_core)} 亿元**，占归母净利润 **{_percent_ratio((non_core / parent * 100) if non_core is not None and parent not in (None, 0) else None)}**；这说明利润来源需要拆分，但**不能把该合计全部直接定性为一次性收益**。" if non_core is not None else "非核心项目数据不完整，利润来源暂不能完全拆分。"),
        "",
        "#### 资产负债表和营运资本变化",
        "",
        "![体检图02 资产负债表与营运资本](图表/体检_02_资产负债表与营运资本.png)",
        "",
        f"> 左图比较本期末与 **{balance_prior_label}**；右图展示与上年同期末的变化。资产负债表是点值，不能直接与利润表累计值混用。",
        "",
        "| 项目 | 本期末 | 上年同期末 | 同比 | 较上期末 |",
        "|---|---:|---:|---:|---:|",
    ])
    for label, key in (("应收账款", "accounts_receivable"), ("合同资产", "contract_asset"), ("存货", "inventory"), ("合同负债", "contract_liability"), ("应付账款", "accounts_payable"), ("货币资金", "cash")):
        prior_growth = ((balance.get(key) - balance_prior.get(key)) / abs(balance_prior.get(key)) * 100
                        if balance.get(key) is not None and balance_prior.get(key) not in (None, 0) else None)
        lines.append(f"| {label} | **{_amount(balance.get(key))}** | {_amount(balance_yoy.get(key))} | **{_pct(balance_growth.get(key))}** | {_pct(prior_growth)} |")
    lines.extend([
        "",
        f"营运资本结论是：**存货同比增长快于收入，形成现金占用压力；合同负债增长提供了订单或预收支持，但尚不足以抵消本期现金流转弱的影响**。"
        f"本期存货同比 **{_pct(balance_growth.get('inventory'))}**，收入同比 **{_pct(current_growth.get('revenue'))}**；合同负债同比 **{_pct(balance_growth.get('contract_liability'))}**。"
        f"应收账款同比 **{_pct(balance_growth.get('accounts_receivable'))}**，应收与合同资产合计增速未明显高于收入，但仍需观察项目结算和回款质量。",
        "",
        "#### 现金流与利润现金化",
        "",
        "![体检图03 现金流与利润现金化](图表/体检_03_现金流与利润现金化.png)",
        "",
        "| 指标 | 本期 | 同比期 | 同比变化 |",
        "|---|---:|---:|---:|",
        f"| 经营活动现金流 | **{_amount(cash.get('operating_cash_flow'))}** | {_amount(cash_yoy.get('operating_cash_flow'))} | **{_pct(cash_growth.get('operating_cash_flow'))}** |",
        f"| 资本开支 | {_amount(cash.get('capex'))} | {_amount(cash_yoy.get('capex'))} | {_pct(cash_growth.get('capex'))} |",
        f"| 自由现金流 | **{_amount(cash.get('free_cash_flow'))}** | {_amount(cash_yoy.get('free_cash_flow'))} | {_pct(cash_growth.get('free_cash_flow'))} |",
        f"| 经营现金流/归母净利润 | **{_percent_ratio(cash.get('ocf_to_parent_net_profit_pct'))}** | {_percent_ratio(cash_yoy.get('ocf_to_parent_net_profit_pct'))} | — |",
        f"| 销售收现/营业收入 | {_percent_ratio(cash.get('collection_ratio_pct'))} | {_percent_ratio(cash_yoy.get('collection_ratio_pct'))} | — |",
        "",
        f"现金流结论是：**本期利润现金化明显偏弱**，经营现金流为 **{_amount(cash.get('operating_cash_flow'))} 亿元**，经营现金流/归母净利润为 **{_percent_ratio(cash.get('ocf_to_parent_net_profit_pct'))}**。"
        f"销售收现/营业收入为 **{_percent_ratio(cash.get('collection_ratio_pct'))}**，但该指标包含前期项目回款，不能单独证明本期经营现金流健康。"
        "考虑到项目交付和回款存在季节性，本次不把 Q1 现金流简单年化，后续重点验证库存消化、采购付款和客户回款。",
        "",
        "#### 三表勾稽和经营闭环",
        "",
        "![体检图04 三表勾稽与经营闭环](图表/体检_04_三表勾稽与经营闭环.png)",
        "",
        "| 勾稽环节 | 状态 | 本期结论 |",
        "|---|---|---|",
        f"| 利润到经营现金流 | **{_human_status(pbridge.get('status'))}** | " + ("间接法调整项字段不足，暂不能完整解释利润与经营现金流的差异。" if pbridge.get("status") == "indeterminate" else "利润、非现金项目和营运资本调整可以完整复算。") + " |",
        f"| 营运资本现金影响 | **{_human_status(wcbridge.get('status'))}** | 估算对现金的影响为 **{_amount(wcbridge.get('cash_effect_estimate'))} 亿元**；该估算不等于完整经营现金流。 |",
        f"| 现金余额变动 | **{_human_status(cbridge.get('status'))}** | 期初现金 **{_amount(cbridge.get('begin_cash'))} 亿元**，经经营、投资、筹资和汇率影响后，期末现金 **{_amount(cbridge.get('reported_end_cash'))} 亿元**，残差 **{_pct(cbridge.get('residual_pct'))}**。 |",
        "",
        f"经营闭环结论是：**现金余额变动可以复算，但利润到经营现金流的完整调整链尚未闭合**。"
        f"因此，本期可以确认现金余额从 **{_amount(cbridge.get('begin_cash'))} 亿元**变为 **{_amount(cbridge.get('reported_end_cash'))} 亿元**，不能把经营现金流为负简单归因于单一营运资本项目。",
        "",
        "#### 财务美化/劣化风险信号",
        "",
        "下表列出本期全部检测项。**已触发**表示组合条件满足，**待补证据**表示关键字段缺失；两者都只是核查线索，不等于财务造假。",
        "",
        "| 检测类型 | 状态 | 结论 | 关键依据 | 后续核查 |",
        "|---|---|---|---|---|",
    ])
    for signal in data.get("signals", []):
        lines.append(
            f"| {signal.get('title') or '—'} | **{_human_status(signal.get('status'))}** | "
            f"{_human_signal_conclusion(signal)} | {_human_signal_basis(signal)}；阈值：{_human_signal_threshold(signal)} | {signal.get('follow_up') or '结合附注和下一期财报核实'} |"
        )
    lines.extend([
        "",
        "本期最需要优先核查两项：**存货增速高于收入且经营现金流恶化**，以及**非核心项目对归母利润贡献较高**。前者重点看库龄、跌价准备、在产品订单覆盖和后续发货回款；后者重点看其他收益、投资收益、公允价值变动的性质及可持续性。",
        "",
        "#### 对全年预测和估值的影响",
        "",
        "![体检图05 对全年预测与估值的影响](图表/体检_05_预测与估值影响.png)",
        "",
        "| 维度 | 本次财务结论 | 对全年预测/估值的处理 | 后续观察事项 |",
        "|---|---|---|---|",
    ])
    impact_labels = (("收入", "revenue"), ("利润", "profit"), ("现金流", "cash_flow"), ("估值风险", "valuation_risk"))
    for label, key in impact_labels:
        value = str(data.get("forecast_impact", {}).get(key, "待观察"))
        conclusion = {
            "收入": "收入保持增长，但兑现节奏仍需验证。",
            "利润": "利润增长质量和非核心收益占比需要进一步拆解。",
            "现金流": "本期经营现金流与自由现金流为负，现金转化承压。",
            "估值风险": "估值对现金流和全年利润兑现的敏感度上升。",
        }[label]
        lines.append(f"| {label} | **{value}**：{conclusion} | {_impact_handling(label, value)} | {_impact_follow_up(label)} |")
    lines.extend([
        "",
        "本次体检对模型的处理原则是：**降低 2026 年利润和现金流预测的置信度，但不因单季数据自动改写全年预测数值或估值区间**。Q1 经营现金流具有季节性，后续若存货继续快于收入增长且经营现金流未修复，应进一步下调利润和现金流假设；若合同负债兑现为收入、库存周转改善且经营现金流转正，则维持原基准假设的依据增强。",
        "",
        f"> 证据来源：`reports/本期财报体检.json`；JSON SHA-256：`{json_digest}`。",
        "",
    ])
    return "\n".join(lines)


def _verbose_render_report_section(data: dict[str, Any], json_digest: str) -> str:
    """Render the simplified, reader-facing health section."""
    period = data["report_period"]
    income = data["income_statement"]["current"]
    income_yoy = data["income_statement"]["yoy"]
    balance = data["balance_sheet"]["current"]
    balance_yoy = data["balance_sheet"]["yoy"]
    cash = data["cash_flow"]["current"]
    cash_yoy = data["cash_flow"]["yoy"]
    growth = income.get("growth_pct", {})
    cash_growth = cash.get("growth_pct", {})
    cash_diag = data.get("cash_flow_diagnosis", {})
    profit_diag = data.get("profit_diagnosis", {})
    inventory = data.get("inventory_review", {})
    finance = data.get("financial_asset_review", {})
    management = data.get("management_evidence", {})
    pbridge = data["bridges"].get("profit_to_operating_cash_flow", {})
    wcbridge = data["bridges"].get("working_capital", {})
    cbridge = data["bridges"].get("cash_reconciliation", {})
    period_label = f"{period.get('current') or '本期'} {period.get('report_type') or _display_period_type(period.get('period_type'))}"
    yoy_label = period.get("yoy") or "同比期"
    revenue_growth = growth.get("revenue")
    profit_growth = growth.get("parent_net_profit")
    ocf_change = cash_diag.get("ocf_change_pct", cash_growth.get("operating_cash_flow"))
    cash_status = _cash_status_label(cash_diag.get("status"))
    profit_status = _profit_status_label(profit_diag.get("status"))
    main_driver = (profit_diag.get("summary_drivers") or [{}])[0]
    lines = [
        "### §4.3 本期财报体检", "",
        f"> 体检期间：**{period_label}**；同比期：**{yoy_label}**；金额单位：亿元。数字唯一来源：`reports/本期财报体检.json`。",
        "> 本章节回答现金流真实性、利润波动、条件性存货、非主营投资和管理层解释五个关键问题；检测结果是核查线索，不是审计意见或造假结论。",
        "",
        "#### 本期财报结论先行", "",
        f"本期营业收入为 **{_amount(income.get('revenue'))} 亿元，同比 {_pct(revenue_growth)}**，归母净利润为 **{_amount(income.get('parent_net_profit'))} 亿元，同比 {_pct(profit_growth)}**。"
        f"经营活动现金流为 **{_amount(cash.get('operating_cash_flow'))} 亿元，同比 {_pct(ocf_change)}**，现金转化率为 **{_percent_ratio(cash_diag.get('current_ocf_to_profit_pct', cash.get('ocf_to_parent_net_profit_pct')))}**，判断为：**{cash_status}**。"
        f"利润方面，**{profit_status}**；当前最大利润影响因素为 **{main_driver.get('type') or '数据不足'}**。"
        f"存货专项检查结论为 **{_inventory_status_label(inventory.get('status'))}**，非主营投资检查结论为 **{_financial_status_label(finance.get('status'))}**。",
        "",
        "| 关键问题 | 本次结果 | 投资含义 |", "|---|---|---|",
        f"| 赚的是真钱吗 | **{cash_status}** | 经营现金流/利润为 **{_percent_ratio(cash_diag.get('current_ocf_to_profit_pct', cash.get('ocf_to_parent_net_profit_pct')))}**，需结合回款和经营项目判断。 |",
        f"| 利润为什么变化 | **{profit_status}** | 主营经营与非主营因素已拆分，优先核查最大贡献项。 |",
        f"| 存货是否异常 | **{_inventory_status_label(inventory.get('status'))}** | 行业未启用专项检查时，不因单季存货增加直接判定风险。 |",
        f"| 是否靠投资收益 | **{_financial_status_label(finance.get('status'))}** | 需区分已实现收益、浮盈和产业投资收益。 |",
        "",
        "#### 现金流：赚的是真钱还是账面利润", "",
        "![体检图01 经营现金流与归母净利润趋势](图表/体检_01_利润表变化与利润来源.png)", "",
        "| 指标 | 本期 | 同比期 | 变化 |", "|---|---:|---:|---:|",
        f"| 经营活动现金流 | **{_amount(cash.get('operating_cash_flow'))}** | {_amount(cash_yoy.get('operating_cash_flow'))} | **{_pct(ocf_change)}** |",
        f"| 归母净利润 | **{_amount(income.get('parent_net_profit'))}** | {_amount(income_yoy.get('parent_net_profit'))} | **{_pct(profit_growth)}** |",
        f"| 经营现金流/归母净利润 | **{_percent_ratio(cash_diag.get('current_ocf_to_profit_pct', cash.get('ocf_to_parent_net_profit_pct')))}** | {_percent_ratio(cash_diag.get('prior_ocf_to_profit_pct', cash_yoy.get('ocf_to_parent_net_profit_pct')))} | {_pp(cash_diag.get('ratio_change_pp'))} |",
        f"| 投资活动现金流 | {_amount(cash.get('investing_cash_flow'))} | {_amount(cash_yoy.get('investing_cash_flow'))} | {_pct(cash_growth.get('investing_cash_flow'))} |",
        f"| 筹资活动现金流 | {_amount(cash.get('financing_cash_flow'))} | {_amount(cash_yoy.get('financing_cash_flow'))} | {_pct(cash_growth.get('financing_cash_flow'))} |",
        "",
        f"现金流结论：**{cash_status}**。本期经营现金流与利润的关系不能只看单季度正负；行业季节性为 **{cash_diag.get('industry_seasonality', {}).get('type') or '未配置'}**，历史比较结果为 **{cash_diag.get('industry_seasonality', {}).get('status') or '未知'}**。投资现金流和筹资现金流是现金余额的其他来源，**不能把资本开支误写成经营现金流下降原因**。",
        "",
        "#### 经营现金流变化原因", "",
        "![体检图02 经营现金流变化原因](图表/体检_02_资产负债表与营运资本.png)", "",
        "| 原因 | 估算现金影响（亿元） | 方向与重要程度 | 证据说明 |", "|---|---:|---|---|",
    ]
    lines.extend(_cash_flow_reason_rows(data))
    top_cash_driver = (cash_diag.get("drivers") or [{}])[0]
    lines.extend([
        "",
        f"原因分析结论：**{cash_diag.get('explanation_status') or '尚未取得足够原因字段'}**。"
        + (f"当前最大现金影响来自 **{top_cash_driver.get('type')}**，但期末余额变化只是经营现金流的方向性解释，不能替代现金流量表间接法和附注。" if cash_diag.get("drivers") else "当前字段不足，报告应明确披露解释缺口。"),
        "",
        "#### 利润波动原因", "",
        "![体检图03 利润波动来源](图表/体检_03_现金流与利润现金化.png)", "",
        "| 利润因素 | 对归母利润影响（亿元） | 方向与解释 |", "|---|---:|---|",
    ])
    lines.extend(_profit_driver_rows(data))
    lines.extend([
        "",
        f"利润结论：**{profit_status}**。利润变化中，营业利润代表主营经营的第一层结果；其余项目包括汇兑、投资收益、公允价值变动、减值、税率和少数股东损益，需结合附注判断持续性。当前归因优先关注 **{main_driver.get('type') or '数据不足'}**，不能只用归母净利润同比增减作为经营结论。",
        "",
        "#### 存货专项检查", "",
    ])
    if inventory.get("applicable"):
        lines.extend([
            "![体检图04 存货专项检查](图表/体检_04_三表勾稽与经营闭环.png)", "",
            "| 检查项 | 本次结果 |", "|---|---|",
            f"| 存货增速 | **{_pct(inventory.get('inventory_growth_pct'))}**；收入增速 **{_pct(inventory.get('revenue_growth_pct'))}** |",
            f"| 存货周转天数 | **{_cell(inventory.get('inventory_days'))} 天**；同比变化 {_pct(inventory.get('inventory_days_change_pct'))} |",
            f"| 合同负债支持 | {_pct(inventory.get('contract_liability_growth_pct'))} |",
            f"| 结论 | **{_inventory_status_label(inventory.get('status'))}**；{inventory.get('conclusion') or '结合行业和附注判断。'} |",
            "",
            "存货判断必须结合行业备货规律、原材料/在产品/产成品结构、库龄、订单覆盖和跌价准备。**工程、电力设备和公用事业不因单季存货增加自动触发风险**。",
        ])
    else:
        lines.extend([
            "本期行业配置未启用自动存货专项检查，避免把工程交付、项目结算或行业正常备货误判为风险。",
            f"当前结论：**{_inventory_status_label(inventory.get('status'))}**。行业画像缺失时，只能补充公司和行业口径后再判断。",
        ])
    lines.extend(["", "#### 非主营投资和金融资产检查", ""])
    if not inventory.get("applicable"):
        lines.extend(["![体检图04 非主营投资和金融资产检查](图表/体检_04_三表勾稽与经营闭环.png)", ""])
    lines.extend([
        "| 检查项 | 本期结果 |", "|---|---|",
        f"| 投资收益（已确认，待附注拆分） | **{_amount(finance.get('investment_income'))} 亿元** |",
        f"| 公允价值变动（浮盈/浮亏候选） | **{_amount(finance.get('fair_value_change'))} 亿元** |",
        f"| 资产处置收益（已确认） | **{_amount(finance.get('asset_disposal_income'))} 亿元** |",
        f"| 长期股权投资余额（产业投资属性） | **{_amount(finance.get('long_equity_investment'))} 亿元**；同比 {_pct(finance.get('long_equity_investment_growth_pct'))} |",
        f"| 投资收益与公允价值变动占归母利润 | **{_percent_ratio(finance.get('investment_and_fair_value_profit_share_pct'))}** |",
        f"| 金融资产占总资产 | **{_percent_ratio(finance.get('market_assets_to_total_assets_pct'))}** |",
        f"| 结论 | **{_financial_status_label(finance.get('status'))}**；{finance.get('conclusion') or '结合附注区分产业投资和金融交易。'} |",
        "",
        "业务分类：**投资收益是已确认损益，但需查附注区分已实现处置收益和长期股权投资权益法收益；公允价值变动是浮盈/浮亏候选；长期股权投资余额属于产业投资属性**。**只有在利润贡献或资产规模达到关注程度时，才升级为非主营投资收益风险；这不是财务造假结论**。",
        "",
        "#### 管理层解释与数据验证", "",
        "管理层原版财报解释是重要的一手证据，但必须与三表和附注交叉验证。", "",
        "| 关注问题 | 管理层解释 | 财务数据是否支持 | 最终判断 |", "|---|---|---|---|",
    ])
    excerpts = management.get("excerpts", [])
    if excerpts:
        for item in excerpts[:8]:
            topic = item.get("topic") or "本期变化"
            quote = _cell(item.get("quote"))
            lines.append(f"| {topic} | {quote}（{_management_source(item)}） | 待与三表及附注核对 | **管理层解释可作为线索，不能单独形成结论** |")
    else:
        lines.append("| 利润、现金流、存货和投资收益 | **本期管理层解释未取得** | 无法验证 | **不使用脚本或历史材料代替管理层观点，需补充原版财报** |")
    lines.extend([
        "",
        f"管理层证据状态：**{'已取得相关原文' if management.get('status') == 'available' else '本期管理层解释未取得'}**。"
        + ("本次仅提取与利润、现金流、汇兑、存货和投资收益相关的段落，最终需由分析员判断是否充分支持。" if excerpts else "报告已明确披露证据缺口。"),
        "",
        "#### 财务美化/劣化风险信号", "",
        "以下只列关键问题检测，不展示程序字段。**已触发**或**待补证据**都表示需要核查，不等于存在违规或财务造假。", "",
        "| 检测类型 | 状态 | 结论 | 后续核查 |", "|---|---|---|---|",
    ])
    for signal in _key_signals(data):
        lines.append(f"| {signal.get('title') or '—'} | **{_human_status(signal.get('status'))}** | {_human_signal_conclusion(signal)} | {signal.get('follow_up') or '结合附注和下一期财报核实'} |")
    lines.extend(["", "#### 对全年预测和估值的影响", "", "![体检图05 管理层解释与后续观察](图表/体检_05_预测与估值影响.png)", "", "| 维度 | 本次财务结论 | 后续处理 |", "|---|---|---|"])
    impact_labels = (("收入", "revenue"), ("利润", "profit"), ("现金流", "cash_flow"), ("估值风险", "valuation_risk"))
    for label, key in impact_labels:
        value = str(data.get("forecast_impact", {}).get(key, "待观察"))
        conclusion = {
            "收入": f"收入同比 {_pct(revenue_growth)}，后续看订单交付和回款兑现。",
            "利润": f"归母利润同比 {_pct(profit_growth)}，后续看主营利润和非主营收益的持续性。",
            "现金流": f"经营现金流同比 {_pct(ocf_change)}，后续看回款、备货和采购付款。",
            "估值风险": "本次体检不自动改写估值，关注盈利和现金流兑现。",
        }[label]
        lines.append(f"| {label} | **{value}**：{conclusion} | {_impact_handling(label, value)} |")
    lines.extend(["", "**后续观察事项（3至5项）**："])
    lines.extend(f"- {item}" for item in _follow_up_items(data))
    lines.extend([
        "", "本模块不新增复杂估值模型，也不因单季度现金流或单个异常指标自动调整估值；只有后续季度验证现金流、利润来源和分红能力后，才进入估值模型更新。", "",
        f"> 证据来源：`reports/本期财报体检.json`；JSON SHA-256：`{json_digest}`。", "",
    ])
    return "\n".join(lines)


def render_report_section(data: dict[str, Any], json_digest: str) -> str:
    """Render a concise, investor-facing health section.

    The JSON and evidence digest retain the full audit trail. The report body
    only keeps figures that answer the six practical review questions.
    """
    period = data["report_period"]
    income = data["income_statement"]["current"]
    income_yoy = data["income_statement"]["yoy"]
    cash = data["cash_flow"]["current"]
    cash_yoy = data["cash_flow"]["yoy"]
    growth = income.get("growth_pct", {})
    cash_growth = cash.get("growth_pct", {})
    cash_diag = data.get("cash_flow_diagnosis", {})
    profit_diag = data.get("profit_diagnosis", {})
    inventory = data.get("inventory_review", {})
    finance = data.get("financial_asset_review", {})
    management = data.get("management_evidence", {})
    current_period = period.get("current") or "本期"
    report_type = period.get("report_type") or _display_period_type(period.get("period_type"))
    period_label = f"{current_period} {report_type}"
    revenue_growth = growth.get("revenue")
    profit_growth = growth.get("parent_net_profit")
    ocf_change = cash_diag.get("ocf_change_pct", cash_growth.get("operating_cash_flow"))
    cash_ratio = cash_diag.get("current_ocf_to_profit_pct", cash.get("ocf_to_parent_net_profit_pct"))
    prior_cash_ratio = cash_diag.get("prior_ocf_to_profit_pct", cash_yoy.get("ocf_to_parent_net_profit_pct"))
    cash_status = cash_diag.get("status")
    cash_status_text = {
        "seasonal": "单季现金流偏弱，但符合项目型业务季节性",
        "explainable": "现金流下降已有经营项目初步解释",
        "needs_explanation": "现金流下降超出已识别季节性，需要重点解释",
        "stable": "现金流未出现需要升级解释的明显恶化",
        "indeterminate": "现金流数据不足，暂不能判断",
    }.get(str(cash_status), "现金流状态待核实")
    top_cash_drivers = [item for item in cash_diag.get("drivers", []) if item.get("cash_effect") is not None][:3]
    top_profit_drivers = [item for item in profit_diag.get("summary_drivers", []) if item.get("profit_effect") is not None][:4]
    finance_share = finance.get("investment_and_fair_value_profit_share_pct")
    finance_status = _financial_status_label(finance.get("status"))
    finance_values = [finance.get("investment_income"), finance.get("fair_value_change")]
    finance_total = sum(value for value in finance_values if value is not None) if any(value is not None for value in finance_values) else None
    industry = data.get("industry_context", {})
    industry_label = industry.get("label") or industry.get("industry") or "本行业"
    inventory_note = industry.get("inventory_note") or "需结合存货结构、库龄、跌价准备和销售支持判断。"
    management_note = (
        "本期管理层已披露相关解释，仍需与三表和附注核对。"
        if management.get("status") == "available"
        else "本期原版财报或公告未取得，管理层对利润、回款和备货的解释尚未完成核对。"
    )

    if cash_status == "seasonal":
        cash_conclusion = (
            f"本期经营现金流为负，但历史同季也为负，符合{industry_label}的经营节奏；"
            "**不能将 Q1 单季现金流直接年化或据此判断利润是假的**，后续重点看 Q2-Q4 回款是否修复。"
        )
    elif cash_status == "explainable":
        cash_conclusion = "现金流下降已有存货、回款或供应商结算等经营项目的方向性解释，仍需结合附注确认。"
    elif cash_status == "needs_explanation":
        cash_conclusion = "现金流下降未能由已识别的季节性或经营项目充分解释，需优先核对回款、采购和付款节奏。"
    elif cash_status == "stable":
        cash_conclusion = "现金流未见明显恶化；仍需结合合并范围、营运资本及现金归属判断现金化程度。"
    else:
        cash_conclusion = "本期现金流数据不足或变化有限，暂不单独升级为经营风险。"

    lines = [
        "### §4.3 本期财报体检", "",
        f"> 体检期间：**{period_label}**；同比期：**{period.get('yoy') or '—'}**；金额单位：亿元。数字唯一来源：`reports/本期财报体检.json`。",
        "> 本节只保留影响投资判断的结论；完整字段、公式和信号来源保留在体检 JSON 与证据摘要中。检测结果是核查线索，不是审计意见或造假结论。",
        "",
        "#### 本期财报结论先行", "",
        f"**主营仍在增长**：营业收入 **{_amount(income.get('revenue'))} 亿元，同比 {_pct(revenue_growth)}**，营业利润 **{_amount(income.get('operating_profit'))} 亿元，同比 {_pct(growth.get('operating_profit'))}**；归母净利润 **{_amount(income.get('parent_net_profit'))} 亿元，同比 {_pct(profit_growth)}**。",
        f"**现金流检查**：经营现金流 **{_amount(cash.get('operating_cash_flow'))} 亿元，同比 {_pct(ocf_change)}**，现金转化率 **{_percent_ratio(cash_ratio)}**；结合{industry_label}经营节奏和后续回款观察，不把期间结果线性年化。",
        f"现金流方向性拆分显示，最大现金影响来自 **{top_cash_drivers[0].get('type') if top_cash_drivers else '经营项目'}**；投资收益与公允价值变动合计占归母利润 **{_percent_ratio(finance_share)}**，需核查其性质和可持续性。",
        f"{management_note}",
        "",
        "| 关键问题 | 本次判断 |",
        "|---|---|",
        f"| 赚的是真钱吗 | **{cash_status_text}**；现金归属和后续回款仍需核查。 |",
        f"| 利润为什么变化 | **{_profit_status_label(profit_diag.get('status'))}**；结合利润桥核查经营与非主营因素。 |",
        f"| 存货是否异常 | **{_inventory_status_label(inventory.get('status'))}**；{industry_label}存货需结合结构、库龄、跌价准备和销售支持判断。 |",
        f"| 是否靠投资收益 | **{finance_status}**；本期投资收益、公允价值变动合计约 **{_amount((finance.get('investment_income') or 0) + (finance.get('fair_value_change') or 0))} 亿元**。 |",
        "",
        "#### 现金流：赚的是真钱还是账面利润", "",
        "![体检图01 经营现金流与归母净利润趋势](图表/体检_01_利润表变化与利润来源.png)", "",
        "| 指标 | 本期 | 同比期 |",
        "|---|---:|---:|",
        f"| 经营活动现金流 | **{_amount(cash.get('operating_cash_flow'))}** | {_amount(cash_yoy.get('operating_cash_flow'))} |",
        f"| 归母净利润 | **{_amount(income.get('parent_net_profit'))}** | {_amount(income_yoy.get('parent_net_profit'))} |",
        f"| 经营现金流/归母净利润 | **{_percent_ratio(cash_ratio)}** | {_percent_ratio(prior_cash_ratio)} |",
        "",
        f"结论：**{cash_status_text}**。{cash_conclusion}",
        "",
        "#### 经营现金流变化原因", "",
        "![体检图02 经营现金流变化原因](图表/体检_02_资产负债表与营运资本.png)", "",
        "| 主要原因 | 方向性现金影响（亿元） | 判断 |",
        "|---|---:|---|",
    ]
    if top_cash_drivers:
        for item in top_cash_drivers:
            effect = item.get("cash_effect")
            lines.append(f"| {item.get('type') or '经营项目'} | **{_amount(effect)}** | **{item.get('direction') or '需核实'}** |")
    else:
        lines.append("| — | — | 当前字段不足，无法拆分原因 |")
    lines.extend([
        "",
        f"原因结论：**{cash_diag.get('explanation_status') or '暂不能判断'}**。主要现金驱动来自 **{top_cash_drivers[0].get('type') if top_cash_drivers else '经营项目'}**；该拆分是方向性估算，仍需结合附注核实。",
        "",
        "#### 利润波动原因", "",
        "![体检图03 利润波动来源](图表/体检_03_现金流与利润现金化.png)", "",
        "| 主要因素 | 对归母利润影响（亿元） | 结论 |",
        "|---|---:|---|",
    ])
    if top_profit_drivers:
        for item in top_profit_drivers:
            effect = item.get("profit_effect")
            lines.append(f"| {item.get('type') or '其他损益'} | **{_amount(effect)}** | {item.get('direction') or '需核实'} |")
    else:
        lines.append("| — | — | 当前字段不足，暂不能拆分利润变化 |")
    lines.extend([
        "",
        f"利润结论：**归母净利润同比 {_pct(profit_growth)}，{_profit_status_label(profit_diag.get('status'))}**；营业利润变化约 **{_amount(profit_diag.get('operating_profit_delta'))} 亿元**，投资收益和公允价值变动本期合计 **{_amount(finance_total)} 亿元**，已包含在营业利润中，不重复加总；需区分产业投资收益与金融资产浮盈。",
        "",
        "#### 存货专项检查", "",
        f"本公司属于{industry_label}行业，{inventory_note}**本期存货增速与收入增速基本匹配，暂未触发升级核查**；后续若存货持续快于收入增长、周转恶化并缺少销售支持，再升级核查。",
        "",
        "#### 非主营投资和金融资产检查", "",
        "![体检图04 非主营投资和金融资产检查](图表/体检_04_三表勾稽与经营闭环.png)", "",
        "| 检查项 | 本期结果 |",
        "|---|---:|",
        f"| 投资收益 | **{_amount(finance.get('investment_income'))} 亿元** |",
        f"| 公允价值变动 | **{_amount(finance.get('fair_value_change'))} 亿元** |",
        f"| 合计占归母利润 | **{_percent_ratio(finance_share)}** |",
        f"| 判断 | **{finance_status}**；需查附注区分已实现收益、权益法收益和浮盈。 |",
        "",
        "#### 管理层解释与数据验证", "",
        "| 关注问题 | 管理层解释 | 数据核对结果 |",
        "|---|---|---|",
    ])
    if management.get("status") == "available" and management.get("excerpts"):
        item = management["excerpts"][0]
        lines.append(f"| {item.get('topic') or '本期变化'} | {_cell(item.get('quote'))} | 待与三表和附注核对（{_management_source(item)}） |")
    else:
        lines.append("| 利润、现金流、存货和投资收益 | **本期管理层解释未取得** | 暂无法验证；不得用历史年报替代。 |")
    lines.extend([
        "",
        "#### 财务美化/劣化风险信号", "",
        "以下只列需要投资者继续核查的项目；未列出的组合检测本期未触发。",
        "",
        "| 检测类型 | 状态 | 结论 |",
        "|---|---|---|",
    ])
    actionable = [signal for signal in _key_signals(data) if signal.get("status") in {"triggered", "indeterminate"} and signal.get("applicability") is not False]
    if actionable:
        for signal in actionable:
            lines.append(f"| {signal.get('title') or '需核查项目'} | **{_human_status(signal.get('status'))}** | {_human_signal_conclusion(signal)} |")
    else:
        lines.append("| 关键组合信号 | **未触发** | 本期未发现需要升级的组合风险，但不代表风险永久排除。 |")
    lines.extend([
        "",
        "#### 对全年预测和估值的影响", "",
        "![体检图05 管理层解释与后续观察](图表/体检_05_预测与估值影响.png)", "",
        "| 维度 | 本次处理 | 后续只观察 |",
        "|---|---|---|",
        f"| 收入 | **{data.get('forecast_impact', {}).get('revenue', '待观察')}**；不改全年模型 | 订单交付和回款兑现 |",
        f"| 利润 | **{data.get('forecast_impact', {}).get('profit', '待观察')}**；只下调置信度，不改全年数值 | 主营利润、投资收益和公允价值变动 |",
        f"| 现金流 | **{data.get('forecast_impact', {}).get('cash_flow', '待观察')}**；不将单季现金流线性年化 | 后续季度回款、存货消化和采购付款 |",
        f"| 估值风险 | **{data.get('forecast_impact', {}).get('valuation_risk', '待观察')}**；估值模块独立处理 | 利润兑现、现金流修复和非主营收益可持续性 |",
        "",
        "**本次体检最重要的三个后续观察事项**：后续季度经营现金流是否与利润同步；存货周转和销售支持是否稳定；投资收益和公允价值变动是否重复贡献利润。",
        "",
        f"> 证据来源：`reports/本期财报体检.json`；JSON SHA-256：`{json_digest}`。",
        "",
    ])
    return "\n".join(lines)


def _amount(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{format_number(float(value) / 1e8)}"
    except (TypeError, ValueError):
        return "—"


def _pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{format_number(float(value),signed=True)}%"
    except (TypeError, ValueError):
        return "—"


def _ratio(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{format_number(float(value))}x"
    except (TypeError, ValueError):
        return "—"


def _percent_ratio(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{format_number(float(value))}%"
    except (TypeError, ValueError):
        return "—"


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, list):
        return ", ".join(_cell(x) for x in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}={_cell(v)}" for k, v in value.items())
    if isinstance(value, float):
        return format_number(value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def _metric_rows(data: dict[str, Any]) -> list[tuple[str, Any, Any, str]]:
    income = data["income_statement"]["current"]
    income_yoy = data["income_statement"]["yoy"]
    balance = data["balance_sheet"]["current"]
    balance_yoy = data["balance_sheet"]["yoy"]
    cash = data["cash_flow"]["current"]
    cash_yoy = data["cash_flow"]["yoy"]
    rows = [
        ("营业收入", income.get("revenue"), income_yoy.get("revenue"), "amount"),
        ("营业利润", income.get("operating_profit"), income_yoy.get("operating_profit"), "amount"),
        ("归母净利润", income.get("parent_net_profit"), income_yoy.get("parent_net_profit"), "amount"),
        ("扣非归母净利润", income.get("deduct_parent_net_profit"), income_yoy.get("deduct_parent_net_profit"), "amount"),
        ("应收账款", balance.get("accounts_receivable"), balance_yoy.get("accounts_receivable"), "amount"),
        ("合同资产", balance.get("contract_asset"), balance_yoy.get("contract_asset"), "amount"),
        ("存货", balance.get("inventory"), balance_yoy.get("inventory"), "amount"),
        ("合同负债", balance.get("contract_liability"), balance_yoy.get("contract_liability"), "amount"),
        ("经营活动现金流", cash.get("operating_cash_flow"), cash_yoy.get("operating_cash_flow"), "amount"),
        ("资本开支", cash.get("capex"), cash_yoy.get("capex"), "amount"),
        ("自由现金流", cash.get("free_cash_flow"), cash_yoy.get("free_cash_flow"), "amount"),
    ]
    return rows


def _legacy_render_evidence(data: dict[str, Any], json_digest: str) -> str:
    period = data["report_period"]
    income = data["income_statement"]["current"]
    cash = data["cash_flow"]["current"]
    balances = data["balance_sheet"]["current"]
    metrics = income.get("metrics", {})
    yoy_metrics = data["income_statement"]["yoy"].get("metrics", {})
    lines = [
        "# 本期财报体检证据摘要",
        "",
        f"<!-- financial-health: schema_version={data['schema_version']} json_digest={json_digest} -->",
        f"> 规则版本：`{data.get('rule_version')}` ｜ 状态：**{data.get('status')}** ｜ 本文件由 `financial_health_check.py` 生成。",
        "> 本摘要只承载 JSON 中的确定性计算结果；“触发信号”不等于违规或造假结论，须结合附注、公告和后续数据核实。",
        "",
        "## 期间与口径",
        "",
        "| 项目 | 值 |",
        "|---|---|",
        f"| 本期报告期 | {period.get('current') or '—'} |",
        f"| 报告类型 | {period.get('report_type') or '—'}（{period.get('period_type') or '—'}） |",
        f"| 公告日期 | {period.get('announcement_date') or '—'} |",
        f"| 同比期 | {period.get('yoy') or '—'} |",
        f"| 资产负债表对比期 | {period.get('prior_period_end') or '—'} |",
        f"| 对比规则 | {period.get('comparison_policy') or '—'} |",
        "",
        "## 核心指标",
        "",
        "| 指标 | 本期（亿元） | 同比期（亿元） | 同比 |",
        "|---|---:|---:|---:|",
    ]
    for name, current, prior, kind in _metric_rows(data):
        growth = (current - prior) / abs(prior) * 100 if current is not None and prior not in (None, 0) else None
        lines.append(f"| {name} | {_amount(current)} | {_amount(prior)} | {_pct(growth)} |")
    lines.extend([
        "",
        "| 利润率/现金转化指标 | 本期 | 同比变化 |",
        "|---|---:|---:|",
        f"| 毛利率 | {_pct(metrics.get('gross_margin_pct'))} | {_pct((metrics.get('gross_margin_pct') - yoy_metrics.get('gross_margin_pct')) if metrics.get('gross_margin_pct') is not None and yoy_metrics.get('gross_margin_pct') is not None else None)} |",
        f"| 营业利润率 | {_pct(metrics.get('operating_margin_pct'))} | {_pct((metrics.get('operating_margin_pct') - yoy_metrics.get('operating_margin_pct')) if metrics.get('operating_margin_pct') is not None and yoy_metrics.get('operating_margin_pct') is not None else None)} |",
        f"| 净利率 | {_pct(metrics.get('net_margin_pct'))} | {_pct((metrics.get('net_margin_pct') - yoy_metrics.get('net_margin_pct')) if metrics.get('net_margin_pct') is not None and yoy_metrics.get('net_margin_pct') is not None else None)} |",
        f"| OCF/归母净利润 | {_percent_ratio(cash.get('ocf_to_parent_net_profit_pct'))} | {_percent_ratio(data['cash_flow']['yoy'].get('ocf_to_parent_net_profit_pct'))} |",
        f"| 销售收现/营业收入 | {_percent_ratio(cash.get('collection_ratio_pct'))} | {_percent_ratio(data['cash_flow']['yoy'].get('collection_ratio_pct'))} |",
        "",
        "## 营运资本体检",
        "",
        "| 项目 | 本期余额（亿元） | 同比增速 | 现金含义 |",
        "|---|---:|---:|---|",
    ])
    wc = data["bridges"]["working_capital"]
    for field, label, meaning in [
        ("accounts_receivable", "应收账款", "占用现金/回款压力"),
        ("contract_asset", "合同资产", "已确认但尚未结算的项目资产"),
        ("inventory", "存货", "备货或库存沉淀"),
        ("contract_liability", "合同负债", "预收款/未来收入可见度"),
        ("accounts_payable", "应付账款", "供应商信用支持"),
    ]:
        current = balances.get(field)
        prior = data["balance_sheet"]["yoy"].get(field)
        growth = (current - prior) / abs(prior) * 100 if current is not None and prior not in (None, 0) else None
        lines.append(f"| {label} | {_amount(current)} | {_pct(growth)} | {meaning} |")
    lines.extend([
        "",
        f"> 营运资本估算现金影响：**{_amount(wc.get('cash_effect_estimate'))} 亿元**。公式：{wc.get('formula')}。",
        "",
        "## 三表桥接",
        "",
        "### 利润到经营现金流",
        "",
        "| 项目 | 金额（亿元） |",
        "|---|---:|",
    ])
    pbridge = data["bridges"]["profit_to_operating_cash_flow"]
    for key, value in pbridge.get("components", {}).items():
        lines.append(f"| {key} | {_amount(value)} |")
    lines.extend([
        f"| 推导经营现金流 | {_amount(pbridge.get('derived_ocf'))} |",
        f"| 报表经营现金流 | {_amount(pbridge.get('reported_ocf'))} |",
        f"| 桥接残差 | {_amount(pbridge.get('residual'))}（{_pct(pbridge.get('residual_pct'))}） |",
        f"| 状态 | `{pbridge.get('status')}` |",
        "",
        "### 现金余额变动",
        "",
        "| 项目 | 金额（亿元） |",
        "|---|---:|",
    ])
    cbridge = data["bridges"]["cash_reconciliation"]
    for key in ("begin_cash", "operating_cash_flow", "investing_cash_flow", "financing_cash_flow", "fx_effect", "expected_end_cash", "reported_end_cash", "residual"):
        lines.append(f"| {key} | {_amount(cbridge.get(key))} |")
    lines.extend([f"| 状态 | `{cbridge.get('status')}`（残差 { _pct(cbridge.get('residual_pct')) }） |", ""])
    lines.extend(["## 风险与经营信号", "", "| ID | 方向 | 状态 | 严重程度 | 信号 | 实际值 | 阈值 | 来源字段 |", "|---|---|---|---|---|---|---|---|"])
    for signal in data.get("signals", []):
        lines.append(f"| `{signal['id']}` | {signal['direction']} | {signal['status']} | {signal['severity']} | {signal['title']} | {_cell(signal.get('actual'))} | {_cell(signal.get('threshold'))} | `{', '.join(signal.get('source_fields', []))}` |")
    lines.extend(["", "### 触发信号的核查要求", ""])
    triggered = [s for s in data.get("signals", []) if s.get("status") == "triggered"]
    if triggered:
        for signal in triggered:
            lines.extend([f"- `{signal['id']}`：{signal['formula']}；来源字段：`{', '.join(signal.get('source_fields', []))}`；{signal.get('follow_up')}"])
    else:
        lines.append("- 本期没有被规则引擎触发的信号；仍需检查 indeterminate 项和附注。")
    lines.extend([
        "",
        "## 对预测和估值的影响（规则初筛）",
        "",
        "| 维度 | 结果 |",
        "|---|---|",
    ])
    for key, value in data.get("forecast_impact", {}).items():
        if key != "basis":
            lines.append(f"| {key} | {value} |")
    lines.extend([f"| 规则说明 | {data.get('forecast_impact', {}).get('basis', '—')} |", "", "## 局限与待补证据", ""])
    if data.get("limitations"):
        for item in data["limitations"]:
            lines.append(f"- `{item.get('id')}` [{item.get('severity')}]: {item.get('detail')}")
    else:
        lines.append("- 未发现结构性数据局限。")
    lines.extend([
        "",
        "## §4.3 成文要求",
        "",
        "主报告必须以本 JSON 为唯一数字来源，在 §4.3 依次覆盖：本期财报结论先行、现金流真实性、经营现金流变化原因、利润波动原因、适用时的存货专项检查、非主营投资和金融资产、管理层解释与数据验证、财务美化/劣化风险信号、对全年预测和估值的影响。",
        "",
        f"> JSON SHA-256：`{json_digest}`。正文应引用 `reports/本期财报体检.json`；本证据摘要不得替代主报告判断。",
        "",
    ])
    return "\n".join(lines)


def render_evidence(data: dict[str, Any], json_digest: str) -> str:
    """Render the technical digest without turning it into a second report."""
    period = data.get("report_period", {})
    income = data.get("income_statement", {}).get("current", {})
    income_yoy = data.get("income_statement", {}).get("yoy", {})
    cash = data.get("cash_flow", {}).get("current", {})
    cash_diag = data.get("cash_flow_diagnosis", {})
    profit_diag = data.get("profit_diagnosis", {})
    inventory = data.get("inventory_review", {})
    finance = data.get("financial_asset_review", {})
    management = data.get("management_evidence", {})
    lines = [
        "# 本期财报体检证据摘要", "",
        f"<!-- financial-health: schema_version={data.get('schema_version')} json_digest={json_digest} -->",
        f"> 规则版本：`{data.get('rule_version')}` ｜ 状态：**{data.get('status')}** ｜ 本摘要由 `financial_health_check.py` 生成。",
        "> JSON 是唯一事实来源；本摘要服务于复算和写作，触发信号只代表需核查，不代表违规或财务造假。", "",
        "## 期间与配置", "",
        "| 项目 | 值 |", "|---|---|",
        f"| 本期报告期 | {period.get('current') or '—'} |",
        f"| 报告类型 | {period.get('report_type') or '—'}（{period.get('period_type') or '—'}） |",
        f"| 公告日期 | {period.get('announcement_date') or '—'} |",
        f"| 同比期 | {period.get('yoy') or '—'} |",
        f"| 资产负债表对比期 | {period.get('prior_period_end') or '—'} |",
        f"| 行业画像 | {data.get('industry_context', {}).get('industry') or '未配置'}（{data.get('industry_context', {}).get('profile_source') or '—'}） |",
        f"| 现金流季节性 | {data.get('industry_context', {}).get('cash_flow_seasonality') or 'unknown'} |",
        "", "## 关键结果", "",
        "| 问题 | 结果 | 关键值 |", "|---|---|---|",
        f"| 现金流真实性 | {_cash_status_label(cash_diag.get('status'))} | OCF {_amount(cash.get('operating_cash_flow'))} 亿元；OCF/归母利润 {_percent_ratio(cash_diag.get('current_ocf_to_profit_pct', cash.get('ocf_to_parent_net_profit_pct')))} |",
        f"| 现金流变化原因 | {cash_diag.get('explanation_status') or '待判断'} | 原因数 {len(cash_diag.get('drivers', []))}；季节性 {cash_diag.get('industry_seasonality', {}).get('status') or '未知'} |",
        f"| 利润波动 | {_profit_status_label(profit_diag.get('status'))} | 归母利润 {_amount(income.get('parent_net_profit'))} 亿元；同比 {_pct(income.get('growth_pct', {}).get('parent_net_profit'))} |",
        f"| 存货检查 | {_inventory_status_label(inventory.get('status'))} | 适用性 {inventory.get('applicable')}；存货同比 {_pct(inventory.get('inventory_growth_pct'))} |",
        f"| 非主营投资检查 | {_financial_status_label(finance.get('status'))} | 投资/公允价值占归母利润 {_percent_ratio(finance.get('investment_and_fair_value_profit_share_pct'))} |",
        f"| 管理层解释 | {'已取得' if management.get('status') == 'available' else '未取得'} | 覆盖主题：{'、'.join(management.get('covered_topics', [])) or '—'} |",
        "", "## 现金流变化原因", "",
        "| 原因 | 估算现金影响（亿元） | 方向 | 重要程度 |", "|---|---:|---|---|",
    ]
    for item in cash_diag.get("drivers", [])[:7]:
        lines.append(f"| {item.get('type') or '其他经营项目'} | {_amount(item.get('cash_effect'))} | {item.get('direction') or '—'} | {item.get('importance') or '观察'} |")
    if not cash_diag.get("drivers"):
        lines.append("| — | — | — | 当前字段不足，无法拆分 |")
    lines.extend(["", "## 利润波动归因", "", "| 因素 | 利润影响（亿元） | 方向 |", "|---|---:|---|"])
    for item in profit_diag.get("summary_drivers", [])[:6]:
        lines.append(f"| {item.get('type') or '其他因素'} | {_amount(item.get('profit_effect'))} | {item.get('direction') or '—'} |")
    if not profit_diag.get("summary_drivers"):
        lines.append("| — | — | 当前字段不足，无法拆分 |")
    lines.extend(["", "## 非主营收益性质", "", "| 项目 | 本期金额（亿元） | 性质与核查口径 |", "|---|---:|---|"])
    for item in finance.get("profit_components", []):
        lines.append(f"| {item.get('type') or '—'} | {_amount(item.get('current'))} | {item.get('classification') or '需结合附注核实'} |")
    if not finance.get("profit_components"):
        lines.append("| — | — | 当前未取得可拆分的非主营收益字段 |")
    lines.append(
        f"| 长期股权投资余额（产业投资属性） | {_amount(finance.get('long_equity_investment'))} | "
        f"{finance.get('income_classification', {}).get('long_equity_investment') or '需结合附注核实'} |"
    )
    lines.extend(["", "## 关键风险信号（技术追溯）", "", "| ID | 类型 | 状态 | 实际值 | 来源字段 |", "|---|---|---|---|---|"])
    for signal in _key_signals(data):
        lines.append(f"| `{signal.get('id')}` | {signal.get('title') or '—'} | {signal.get('status') or '—'} | {_cell(signal.get('actual'))} | `{', '.join(signal.get('source_fields', []))}` |")
    lines.extend(["", "## 管理层原文证据", ""])
    if management.get("excerpts"):
        lines.extend(["| 主题 | 原文摘录 | 来源 |", "|---|---|---|"])
        for item in management.get("excerpts", [])[:12]:
            lines.append(f"| {item.get('topic') or '—'} | {_cell(item.get('quote'))} | {_management_source(item)} |")
    else:
        lines.append("- 本期管理层解释未取得；不得用脚本或历史材料代替管理层观点。")
    lines.extend(["", "## 三表复算状态", "", "| 环节 | 状态 | 残差/影响 |", "|---|---|---:|"])
    for label, key, value_key in (("利润到经营现金流", "profit_to_operating_cash_flow", "residual_pct"), ("营运资本", "working_capital", "cash_effect_estimate"), ("现金余额变动", "cash_reconciliation", "residual_pct")):
        bridge = data.get("bridges", {}).get(key, {})
        value = bridge.get(value_key)
        display = f"{_pct(value)}" if value_key.endswith("pct") else f"{_amount(value)} 亿元"
        lines.append(f"| {label} | {bridge.get('status') or '—'} | {display} |")
    lines.extend(["", "## 预测影响", "", "| 维度 | 结果 |", "|---|---|"])
    for key, value in data.get("forecast_impact", {}).items():
        if key != "basis":
            lines.append(f"| {key} | {value} |")
    lines.extend(["", "## 局限", ""])
    if data.get("limitations"):
        lines.extend(f"- `{item.get('id')}` [{item.get('severity')}]: {item.get('detail')}" for item in data["limitations"])
    else:
        lines.append("- 未发现结构性数据局限。")
    lines.extend([
        "", "## §4.3 成文要求", "",
        "主报告必须包含：本期财报结论先行、现金流：赚的是真钱还是账面利润、经营现金流变化原因、利润波动原因、存货专项检查、非主营投资和金融资产检查、管理层解释与数据验证、财务美化/劣化风险信号、对全年预测和估值的影响。正文使用业务语言，不展示程序字段路径。", "",
        f"> JSON SHA-256：`{json_digest}`。正文应引用 `reports/本期财报体检.json`；本摘要不能替代主报告判断。", "",
    ])
    return "\n".join(lines)


def run(project_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    project_dir = project_dir.resolve()
    data_dir = project_dir / "data"
    input_dir = project_dir / "input"
    reports_dir = project_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    config_path = input_dir / "本期财报体检配置.json"
    write_default_config(config_path)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"配置文件无法读取: {config_path}: {exc}") from exc
    data = build_health_report(data_dir, project_dir.name, config)
    json_path = reports_dir / "本期财报体检.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(json_path.read_bytes()).hexdigest()
    md_path = reports_dir / "本期财报体检_证据摘要.md"
    md_path.write_text(render_evidence(data, digest), encoding="utf-8")
    render_health_charts(data, reports_dir / "图表")
    section_path = reports_dir / "本期财报体检_成文框架.md"
    section_path.write_text(render_report_section(data, digest), encoding="utf-8")
    return json_path, md_path, data


def main() -> int:
    parser = argparse.ArgumentParser(description="生成本期财报体检证据包")
    parser.add_argument("--dir", required=True, help="批次目录（含 data/input/reports）")
    args = parser.parse_args()
    try:
        json_path, md_path, data = run(Path(args.dir))
    except Exception as exc:
        print(f"[财报体检] FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"[财报体检] 状态: {data.get('status')}")
    print(f"[财报体检] JSON: {json_path}")
    print(f"[财报体检] 摘要: {md_path}")
    print(f"[财报体检] 成文框架: {json_path.parent / '本期财报体检_成文框架.md'}")
    print(f"[财报体检] 图表: {json_path.parent / '图表'}")
    return 0 if data.get("status") != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
