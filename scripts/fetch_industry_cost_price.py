#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行业成本—价格数据模板与审计器（company-research B2.2/G8-INDUSTRY）。

设计目标：行业数据没有统一稳定的免费接口时，不臆造数据；生成可审计的 CSV 契约、来源指引和审计 JSON。
用法：
  python fetch_industry_cost_price.py --dir <项目目录> --profile dairy
  python fetch_industry_cost_price.py --dir <项目目录> --profile dairy --input-csv <外部CSV>
  python fetch_industry_cost_price.py --dir <项目目录> --profile dairy --optional

标准 CSV（data/行业成本价格.csv）：
  date,series,value,unit,role,source,source_date,frequency,scope,evidence_level,note

role 只能为 cost / price / volume / margin；图16至少需要一个 cost 和一个 price 序列。
value 必须是正数；date 使用 YYYY-MM-DD；同一 series+date 不得重复。

本脚本同时生成 input/行业成本价格配置.json（required=true/false），
chart_qc.py 的 G8-INDUSTRY 门控据此决定是否强制图16 与双序列审计；
审计结果写入 data/行业成本价格_审计.json，供 B3 审核与 G8-INDUSTRY 读取。
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

REQUIRED = [
    "date", "series", "value", "unit", "role", "source", "source_date",
    "frequency", "scope", "evidence_level", "note",
]
PROFILES = {
    "dairy": {
        "name": "乳制品",
        "required_roles": ["cost", "price"],
        "cost_guidance": "生鲜乳收购价/原料奶粉价格（农业农村部、全国畜牧总站或独立行业生产方）",
        "price_guidance": "鲜奶/奶粉零售价、乳制品PPI或产品价格指数（中国价格信息网、国家统计局或独立数据生产方）",
        "volume_guidance": "全国牛奶产量（国家统计局，年度，万吨）或奶牛存栏（农业农村部，月度，万头）——体现供需与产能去化",
        "margin_guidance": "价差示意（零售价−收购价折斤）必须标注“手算/补充”，并注明未含加工/包装/运输费用",
        "unit_guidance": "成本端常用元/公斤；零售价常用元/斤；图16 画原始值双轴（左=成本单位，右=价格单位），不再用指数化压平价格曲线",
    },
    "generic": {
        "name": "通用行业",
        "required_roles": ["cost", "price"],
        "cost_guidance": "单位成本、原材料价格或成本指数",
        "price_guidance": "产品价格、出厂价、零售价或价格指数",
        "volume_guidance": "产量/销量/库存/产能等供需序列（优先国家统计局/行业协会）",
        "margin_guidance": "价差/单吨毛利等派生指标必须标注口径与“手算/补充”",
        "unit_guidance": "跨单位时画原始值双轴并标注单位；报告中同时保留原始单位",
    },
}

SKELETON_ROWS = {
    "dairy": [
        ["", "生鲜乳收购价", "", "元/公斤", "cost", "农业农村部/全国畜牧总站", "", "monthly", "中国奶业主产省份", "L3", "待补原始数据；不得填预测值"],
        ["", "鲜奶平均零售价", "", "元/斤", "price", "中国价格信息网", "", "monthly", "全国监测城市", "L3", "待补原始数据；不得填预测值"],
        ["", "全国牛奶产量", "", "万吨", "volume", "国家统计局", "", "annual", "全国", "L3", "待补原始数据；供需面板（体现供大于求/产能去化）"],
        ["", "价差示意（零售−收购折斤）", "", "元/斤", "margin", "手算/补充", "", "monthly", "全国监测城市", "L3", "手算/补充：零售价−收购价/2，未含加工费用"],
    ],
    "generic": [
        ["", "单位成本", "", "", "cost", "", "", "", "", "L3", "待补原始数据"],
        ["", "产品价格", "", "", "price", "", "", "", "", "L3", "待补原始数据"],
        ["", "产量/销量", "", "", "volume", "", "", "", "", "L3", "待补原始数据；供需面板"],
        ["", "价差示意", "", "", "margin", "手算/补充", "", "", "", "L3", "手算/补充；须标注口径"],
    ],
}


def write_skeleton(path: Path, profile: str, force: bool) -> None:
    if path.exists() and not force:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(REQUIRED)
        writer.writerows(SKELETON_ROWS[profile])


def audit(path: Path, profile: str) -> dict:
    result = {
        "profile": profile,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "file": str(path),
        "status": "pass",
        "errors": [],
        "warnings": [],
        "series": {},
        "source_producers": [],
    }
    if not path.exists():
        result["status"] = "fail"
        result["errors"].append("missing_file")
        return result
    try:
        df = pd.read_csv(path, dtype=str)
    except Exception as exc:
        result["status"] = "fail"
        result["errors"].append(f"read_error:{exc}")
        return result
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        result["status"] = "fail"
        result["errors"].append({"missing_columns": missing})
        return result
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value_num"] = pd.to_numeric(df["value"], errors="coerce")
    if df["date"].isna().any():
        result["errors"].append("invalid_date")
    if df["value_num"].isna().any() or (df["value_num"] <= 0).any():
        result["errors"].append("value_not_positive_or_numeric")
    bad_roles = sorted(set(df["role"].dropna()) - {"cost", "price", "volume", "margin"})
    if bad_roles:
        result["errors"].append({"invalid_roles": bad_roles})
    dup = df.duplicated(["date", "series"], keep=False)
    if dup.any():
        result["errors"].append("duplicate_date_series")
    valid = df.dropna(subset=["date", "value_num", "series"])
    for series, sub in valid.groupby("series"):
        roles = sorted(set(sub["role"]))
        sub_sorted = sub.sort_values("date")
        gaps = sub_sorted["date"].diff().dt.days.dropna()
        cadence = {"daily": 1, "weekly": 7, "monthly": 31, "quarterly": 92, "annual": 370}.get(
            str(sub["frequency"].iloc[0]).strip().lower(), 31)
        max_gap = int(gaps.max()) if len(gaps) else 0
        result["series"][str(series)] = {
            "rows": int(len(sub)),
            "date_min": str(sub["date"].min().date()),
            "date_max": str(sub["date"].max().date()),
            "roles": roles,
            "sources": sorted(set(sub["source"].dropna())),
            "evidence_levels": sorted(set(sub["evidence_level"].dropna())),
            "max_gap_days": max_gap,
            "cadence_days": cadence,
        }
        if len(sub) < 3:
            result["warnings"].append(f"series_too_short:{series}")
        if max_gap > cadence * 2:
            result["warnings"].append(
                f"series_observation_gap:{series}:{max_gap}d(基准{cadence}d)——图16 该线将出现长缺口线段，报告须说明缺口月份，禁止线性补齐")
        if not sub["source"].astype(str).str.strip().all():
            result["warnings"].append(f"missing_source:{series}")
        if not sub["source_date"].astype(str).str.strip().all():
            result["warnings"].append(f"missing_source_date:{series}")
    roles = set(valid["role"])
    for role in PROFILES[profile]["required_roles"]:
        if role not in roles:
            result["errors"].append(f"missing_required_role:{role}")
    # 断点风险：cost 与 price 共同观测日期过少 → 图16 双线错位、线段过长
    if {"cost", "price"} <= roles:
        cost_dates = set(valid.loc[valid["role"] == "cost", "date"])
        price_dates = set(valid.loc[valid["role"] == "price", "date"])
        common = len(cost_dates & price_dates)
        min_rows = min(len(cost_dates), len(price_dates))
        result["cost_price_common_dates"] = common
        if common < max(3, int(min_rows * 0.5)):
            result["warnings"].append(
                f"low_cost_price_date_overlap:{common}个共同观测日（双序列共{min_rows}点）——图16 断点风险，报告须说明错位口径")
    # 刻度重合风险：日期网格过密
    unique_dates = len(valid["date"].unique())
    result["unique_dates"] = unique_dates
    if unique_dates > 16:
        result["warnings"].append(
            f"dense_date_grid:{unique_dates}个观测日期——图16 横坐标刻度存在重合风险，须稀疏刻度并过 chart_qc 刻度检查")
    result["source_producers"] = sorted(set(valid["source"].astype(str)))
    if len(result["source_producers"]) < 2:
        result["warnings"].append("less_than_two_named_sources")
    if result["errors"]:
        result["status"] = "fail"
    elif result["warnings"]:
        result["status"] = "warn"
    return result


def write_guidance(path: Path, profile: str) -> None:
    p = PROFILES[profile]
    text = f"""# 行业成本—价格数据源指引（{p['name']}）

## 必备序列

- `role=cost`：{p['cost_guidance']}
- `role=price`：{p['price_guidance']}
- `role=volume`（供需面板）：{p['volume_guidance']}
- `role=margin`（价差示意）：{p['margin_guidance']}
- {p['unit_guidance']}

## 采集纪律

1. 只记录已发生的历史值；预测值必须另列并标记 `note=forecast`，不能混入图16历史线。
2. 每行必须有来源名称、来源日期、频率、区域/样本口径和证据等级。
3. 至少使用两个独立数据生产方或一手公告交叉验证核心趋势；同一生产方转载不算独立双源。
4. 成本线与价格线单位不同时，图16 画原始值双轴（左=成本单位，右=价格单位）并标注单位；不再用“首期=100”指数化（会压平价格曲线、掩盖成本—价格关系）。
5. 季度/月份不齐时不得线性补齐；只能保留观测点并在报告说明缺口。
6. 供需序列（产量/存栏）必须与价格序列同期展示，说明供大于求/产能去化背景；价差/派生指标必须标注“手算/补充”与未含费用口径。

## 当前状态

运行 `python scripts/fetch_industry_cost_price.py --dir <项目目录> --profile {profile}` 生成/审计 `data/行业成本价格.csv`。

## 门控与嵌入

- 本脚本自动生成 `input/行业成本价格配置.json`（required=true）；
  chart_qc.py 的 G8-INDUSTRY 门控将要求：CSV 存在且审计通过、
  cost+price 双序列、≥2 个独立来源、图16 已嵌入报告 §2 宏观与行业。
- 报告图16 由 analyze_charts.py 自动读取本 CSV（跨单位指数化首期=100）；
  若 `--optional` 则配置 required=false，G8-INDUSTRY 跳过。
"""
    path.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="行业成本—价格数据模板与审计器")
    ap.add_argument("--dir", required=True, help="项目目录（含 data/ 与 input/）")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="generic")
    ap.add_argument("--input-csv", default="", help="外部CSV；字段必须符合标准契约")
    ap.add_argument("--force", action="store_true", help="覆盖生成空白骨架；不会覆盖 --input-csv")
    ap.add_argument("--optional", action="store_true",
                    help="行业数据为非强制项（配置 required=false，G8-INDUSTRY 跳过）")
    args = ap.parse_args()
    project = Path(args.dir)
    data_dir = project / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    config_dir = project / "input"
    config_dir.mkdir(parents=True, exist_ok=True)
    out = data_dir / "行业成本价格.csv"
    if args.input_csv:
        src = Path(args.input_csv)
        if not src.is_absolute():
            src = project / src
        if not src.exists():
            raise SystemExit(f"input csv not found: {src}")
        shutil.copy2(src, out)
        print(f"[COPY] {src} -> {out}")
    else:
        write_skeleton(out, args.profile, args.force)
        if not out.exists():
            write_skeleton(out, args.profile, True)
            print(f"[SKELETON] {out}")
    audit_result = audit(out, args.profile)
    (data_dir / "行业成本价格_审计.json").write_text(
        json.dumps(audit_result, ensure_ascii=False, indent=2), encoding="utf-8")
    (config_dir / "行业成本价格配置.json").write_text(
        json.dumps({
            "profile": args.profile,
            "required": not args.optional,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[CONFIG] {config_dir / '行业成本价格配置.json'}（required={not args.optional}）")
    write_guidance(data_dir / "行业成本价格_数据源指引.md", args.profile)
    print(json.dumps(audit_result, ensure_ascii=False, indent=2))
    return 0 if audit_result["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
