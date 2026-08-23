#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""白酒行业特有数据模板（2026-08-15 新增，贵州茅台批次校准）。

背景：白酒分析需要批价（飞天/普五/国窖1573）与行业产量数据，通用拉数脚本不覆盖。
公开免费接口（akshare/东财/腾讯）均无白酒批价与产量端点，本模板：
  1. 生成 data/行业_白酒批价.csv 与 data/行业_白酒产量.csv 骨架（表头+格式说明）；
  2. 输出数据源指引（见下），由 Agent 用 WebSearch 核实后手工维护（fetch_peers 同款"公告搜索兜底"模式）；
  3. 已存在的 CSV 不清空，仅补骨架（--force 可重建）。

CSV 结构：
  行业_白酒批价.csv：日期,品名,规格,批价_元,环比,来源
      示例：2026-08-14,飞天茅台(原箱),53° 500ml,1700,0,今日酒价
  行业_白酒产量.csv：年份,白酒产量_万千升,同比_%
      来源：国家统计局/中国酒业协会（年度公告）

数据源指引（WebSearch 关键词）：
  - 批价：今日酒价（微信平台/酒价数据），原箱 vs 散瓶必须分开记录；批价 vs 出厂价 vs 建议零售价口径分离标注
  - 产量：中国酒业协会年度报告 / 国家统计局规模以上企业白酒产量
  - 渠道库存：酒业家/微酒行业报道（定性，标注来源日期）
  - ⚠️ 同一数据生产方的转引（如今日酒价/新浪转引同一机构）不算双源，证据级别按 framework.md D2 降为 L3
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

PRICE_HEADER = ["日期", "品名", "规格", "批价_元", "环比", "来源"]
PRICE_SAMPLE = [
    [datetime.now().strftime("%Y-%m-%d"), "飞天茅台(原箱)", "53° 500ml", "", "", "今日酒价"],
    [datetime.now().strftime("%Y-%m-%d"), "飞天茅台(散瓶)", "53° 500ml", "", "", "今日酒价"],
    [datetime.now().strftime("%Y-%m-%d"), "普五", "52° 500ml", "", "", "今日酒价"],
    [datetime.now().strftime("%Y-%m-%d"), "国窖1573", "52° 500ml", "", "", "今日酒价"],
]
OUTPUT_HEADER = ["年份", "白酒产量_万千升", "同比_%"]


def ensure_csv(path: Path, header: list[str], sample_rows: list[list], force: bool) -> None:
    if path.exists() and not force:
        print(f"[SKIP] {path.name} 已存在（--force 重建；缺数据行请手工补齐）")
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(sample_rows)
    print(f"[OK] {path.name} 骨架已生成（{len(sample_rows)} 行占位，请用 WebSearch 补批价后填写）")


def main() -> int:
    ap = argparse.ArgumentParser(description="白酒行业特有数据模板")
    ap.add_argument("--dir", required=True, help="项目目录（含 data/）")
    ap.add_argument("--force", action="store_true", help="覆盖重建骨架 CSV")
    args = ap.parse_args()

    data_dir = Path(args.dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    ensure_csv(data_dir / "行业_白酒批价.csv", PRICE_HEADER, PRICE_SAMPLE, args.force)
    ensure_csv(data_dir / "行业_白酒产量.csv", OUTPUT_HEADER, [], args.force)

    print("\n[指引] 批价数据源：今日酒价（微信平台）；产量：中酒协/国家统计局。")
    print("       批价必须区分原箱/散瓶，并标注 批价/出厂价/建议零售价 口径与来源日期。")
    print("       同一生产方转引不算双源（framework.md D2，实为 L3）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())