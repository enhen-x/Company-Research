#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模板回归测试（template_regression.py）——company-research skill 发布前全图 QC 自检。

背景（2026-08-21，小商品城批次校准）：analyze_charts.py / chart_qc.py 模板自带渲染 bug
（图02/04 标注重叠、图10/11 标注越界、图16 豁免与清单检查脱节），导致每个新项目都要
手工 patch。本脚本用合成数据（不联网）跑完整「出图 → 报告 → chart_qc」链路，
把渲染级/契约级问题消灭在 skill 层。

覆盖（合成数据刻意复现历史踩坑点）：
  图01/02：16 年年报（触发 tail(12) 窗口）；ROE 相邻年接近（16.06/16.10 → 标注重叠风险）
  图04：2022 毛利率 15.3 vs 净利率 14.5（同 x 标注重叠风险）
  图10：R* 2.01% < 门槛 3.68%（负 KK 情形，多行标注越界风险）
  图11：lambda=0 平线敏感性 + 门槛标注（越界风险）
  图16：行业成本—价格 CSV（cost/price/volume 三序列 + 3 独立来源）

用法：
    python template_regression.py                       # 合成项目 -> 出图 -> 报告 -> chart_qc
    python template_regression.py --keep                # 保留临时项目（人工复核 PNG/HTML）
    python template_regression.py --out <dir>           # 指定输出目录
    python template_regression.py --templates-dir <dir> # 指定 analyze_charts/chart_qc 所在目录（默认本脚本同目录）
    python template_regression.py --selfcheck           # 负向自检：故意注入旧 bug，断言 chart_qc FAIL

退出码：0=通过（无 FAIL）；1=存在 FAIL；2=运行错误。
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

SKILL_SCRIPTS = Path(__file__).resolve().parent
CODE = "600415"
NAME = "测试公司"
TODAY = "2026-08-21"


# ───────────────────────── 合成数据 ─────────────────────────

def _years(start: int, end: int) -> list[str]:
    return [f"{y}-12-31" for y in range(start, end + 1)]


def write_proj_data(proj: Path) -> None:
    data = proj / "data"
    data.mkdir(parents=True, exist_ok=True)

    yrs = _years(2010, 2025)
    rev = [14, 16, 18, 20, 22, 25, 28, 32, 35.9, 40.4, 37.3, 60.3, 76.2, 113.0, 157.4, 199.3]
    np_ = [3.5, 4.0, 4.8, 5.6, 6.8, 8.0, 10.6, 14.6, 10.8, 12.6, 9.3, 13.3, 11.1, 26.8, 30.7, 42.0]
    kf = [v * 0.92 for v in np_]
    cost = [round(r * 0.68, 2) for r in rev]
    inc = pd.DataFrame({
        "REPORT_DATE": yrs,
        "TOTAL_OPERATE_INCOME": rev, "OPERATE_INCOME": rev,
        "TOTAL_OPERATE_COST": cost, "OPERATE_COST": cost,
        "PARENT_NETPROFIT": np_, "DEDUCT_PARENT_NETPROFIT": kf, "NETPROFIT": np_,
    })
    inc.to_csv(data / "利润表_按报告期.csv", index=False, encoding="utf-8-sig")

    fi = pd.DataFrame({
        "REPORT_DATE": yrs,
        "ROEJQ": [4.5, 5.0, 5.5, 6.0, 6.8, 7.5, 10.8, 13.7, 9.4, 10.0, 6.9, 9.4, 7.3, 16.06, 16.10, 17.5],
        "BPS": [1.20, 1.30, 1.45, 1.60, 1.75, 1.90, 2.06, 2.16, 2.39, 2.47, 2.66, 2.78, 3.23, 3.74, 4.18, 4.35],
        "XSMLL": [48, 47, 46, 45, 44, 43, 43.4, 32.6, 49.4, 58.0, 51.4, 33.3, 15.3, 26.5, 31.4, 31.4],
        "EPSJB": [0.06, 0.07, 0.08, 0.09, 0.11, 0.13, 0.19, 0.27, 0.20, 0.23, 0.17, 0.25, 0.20, 0.49, 0.56, 0.77],
    })
    fi_q = pd.DataFrame({
        "REPORT_DATE": ["2026-03-31"], "ROEJQ": [4.23], "BPS": [4.35],
        "XSMLL": [33.78], "EPSJB": [0.18],
    })
    pd.concat([fi, fi_q], ignore_index=True).to_csv(
        data / "主要财务指标_按报告期.csv", index=False, encoding="utf-8-sig")

    fq = pd.DataFrame({
        "REPORT_DATE": ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31", "2026-03-31"],
        "EPSJB": [0.15, 0.16, 0.32, 0.14, 0.18],
    })
    fq.to_csv(data / "主要财务指标_按单季度.csv", index=False, encoding="utf-8-sig")

    cf = pd.DataFrame({
        "REPORT_DATE": yrs,
        "NETCASH_OPERATE": [5, 6, 7, 8, 9, 10, 11, 2.7, 13.1, -15.4, 8.3, 20.3, 14.0, 18.5, 44.9, 105.3],
        "CONSTRUCT_LONG_ASSET": [3, 3, 4, 4, 5, 5, 7.8, 5.3, 4.4, 9.5, 12.1, 20.4, 41.2, 26.3, 15.0, 21.8],
        "FA_IR_DEPR": [2, 2, 3, 3, 4, 4, 5, 5, 5, 6, 6, 7, 8, 9, 9, 10],
        "IA_AMORTIZE": [0.3] * 16, "LPE_AMORTIZE": [0.2] * 16,
        "USERIGHT_ASSET_AMORTIZE": [0.0] * 12 + [0.3, 0.4, 0.5, 0.6],
    })
    cf.to_csv(data / "现金流量表_按报告期.csv", index=False, encoding="utf-8-sig")

    bs = pd.DataFrame({
        "REPORT_DATE": yrs,
        "TOTAL_ASSETS": [150, 165, 180, 195, 210, 230, 271, 239, 269, 313, 288, 310, 321, 362, 392, 444],
        "TOTAL_LIABILITIES": [75, 82, 90, 98, 106, 115, 166, 123, 151, 182, 152, 164, 168, 185, 186, 214],
        "MONETARYFUNDS": [5, 6, 7, 8, 9, 10, 12, 21, 32, 65, 56, 48, 20, 29, 55, 68],
        "SHORT_LOAN": [3, 3, 4, 4, 5, 5, 6, 31, 39, 42, 13, 9, 11, 16, 1, 0],
        "LONG_LOAN": [5, 5, 6, 6, 7, 7, 8, 8, 8, 5, 3, 8, 4, 9, 7, 5],
        "BOND_PAYABLE": [10, 10, 10, 10, 10, 10, 15, 15, 10, 46, 36, 0, 35, 35, 0, 28],
        "NONCURRENT_LIAB_1YEAR": [2, 2, 2, 3, 3, 3, 4, 4, 5, 5, 4, 4, 5, 5, 3, 4],
    })
    bs.to_csv(data / "资产负债表_按报告期.csv", index=False, encoding="utf-8-sig")

    # 日线（前复权+不复权）：2023-08-21 ~ 2026-08-21，末值 12.48，2025-08 高点约 22.5
    rng = pd.date_range("2023-08-21", "2026-08-21", freq="B")
    rng = rng[rng <= pd.Timestamp("2026-08-21")]
    rs = np.random.default_rng(42)
    drift = np.linspace(0, 1, len(rng)) * 6.0
    wave = 5.5 * np.sin(np.linspace(0, 3.2 * np.pi, len(rng)))
    noise = rs.normal(0, 0.35, len(rng)).cumsum() * 0.15
    close = 9.0 + drift + wave + noise
    close = np.maximum(close, 5.0)
    close[-1] = 12.48
    dly = pd.DataFrame({"date": rng.strftime("%Y-%m-%d"), "close": np.round(close, 2)})
    dly.to_csv(data / "日线股价.csv", index=False, encoding="utf-8-sig")
    dly.to_csv(data / "日线股价_前复权.csv", index=False, encoding="utf-8-sig")

    div = pd.DataFrame({
        "报告期": ["2019-12-31", "2020-12-31", "2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"],
        "业绩披露日期": ["2020-04-30", "2021-04-30", "2022-03-22", "2023-04-12", "2024-04-17", "2025-03-27", "2026-04-09"],
        "现金分红-现金分红比例": [0.7, 0.55, 0.73, 0.65, 2.0, 3.3, 5.0],
        "现金分红-股息率": [0.009, 0.010, 0.014, 0.008, 0.026, 0.018, 0.044],
        "每股收益": [0.23, 0.17, 0.25, 0.20, 0.49, 0.56, 0.77],
        "每股净资产": [2.39, 2.47, 2.66, 2.78, 3.23, 3.74, 4.18],
        "总股本": [5443214176] * 7,
    })
    div.to_csv(data / "分红送配记录.csv", index=False, encoding="utf-8-sig")

    # 行业成本—价格（图16）：cost/price 双序列 + volume 供需 + 3 独立来源
    rows = []
    for d, v in [("2024-01", 3.55), ("2024-06", 3.42), ("2025-01", 3.30),
                 ("2025-06", 3.22), ("2026-01", 3.15), ("2026-06", 3.10)]:
        rows.append({"date": d, "series": "生鲜乳收购价", "value": v, "unit": "元/公斤",
                     "role": "cost", "source": "农业农村部", "source_date": d})
    for d, v in [("2024-01", 5.71), ("2024-06", 5.65), ("2025-01", 5.60),
                 ("2025-06", 5.55), ("2026-01", 5.52), ("2026-06", 5.50)]:
        rows.append({"date": d, "series": "鲜奶平均零售价", "value": v, "unit": "元/斤",
                     "role": "price", "source": "中国价格信息网", "source_date": d})
    for d, v in [("2023", 4079), ("2024", 4091), ("2025", 4110)]:
        rows.append({"date": d, "series": "全国牛奶产量", "value": v, "unit": "万吨",
                     "role": "volume", "source": "国家统计局", "source_date": d})
    pd.DataFrame(rows).to_csv(data / "行业成本价格.csv", index=False, encoding="utf-8-sig")


def write_ops(proj: Path) -> None:
    inp = proj / "input"
    inp.mkdir(parents=True, exist_ok=True)
    ops = {
        "segment": {
            "标题": "图03 分部营收构成（亿元，按行业）",
            "labels": ["2023", "2024", "2025"],
            "series": [
                {"name": "商品销售", "values": [67.9, 92.6, 99.8]},
                {"name": "市场经营", "values": [30.7, 45.8, 52.6]},
                {"name": "数贸配套销售", "values": [0.0, 0.0, 19.5]},
                {"name": "贸易服务", "values": [6.0, 7.4, 15.3]},
                {"name": "配套服务", "values": [4.7, 4.5, 5.4]},
                {"name": "其他及抵销", "values": [3.7, 7.1, 6.7]},
            ],
            "增速": {"合计增速": [48.3, 39.3, 26.6]},
            "注": "合成数据：2023-2025 按行业口径，含分部间抵销差异",
        },
        "profitability": {
            "标题": "图04 盈利能力趋势（毛利率/净利率/ROE）",
            "labels": [str(y) for y in range(2016, 2026)],
            "毛利率": [43.4, 32.6, 49.4, 58.0, 51.4, 33.3, 15.3, 26.5, 31.4, 31.4],
            "净利率": [15.1, 14.6, 30.1, 31.0, 24.9, 22.1, 14.5, 23.7, 19.5, 21.2],
            "ROE": [10.8, 13.7, 9.4, 10.0, 6.9, 9.4, 7.3, 16.06, 16.10, 17.5],
        },
        "cashflow": {
            "标题": "图05 现金流结构（OCF/Capex/FCF）",
            "labels": [str(y) for y in range(2016, 2026)],
            "OCF": [11, 2.7, 13.1, -15.4, 8.3, 20.3, 14.0, 18.5, 44.9, 105.3],
            "Capex": [7.8, 5.3, 4.4, 9.5, 12.1, 20.4, 41.2, 26.3, 15.0, 21.8],
            "FCF": [3.2, -2.6, 8.7, -24.9, -3.8, -0.1, -27.2, -7.8, 29.9, 83.5],
            "D_A": [5.2, 5.2, 5.2, 6.2, 6.2, 7.2, 8.2, 9.2, 9.2, 10.2],
        },
        "peers": [
            {"公司": "轻纺城", "PE": 16.1, "PB": 0.84, "ROE": -0.3, "营收增速": -7.6, "净利增速": -111.5, "净利率": None, "高亮": False},
            {"公司": "海宁皮城", "PE": 102.6, "PB": 0.59, "ROE": 0.8, "营收增速": -3.6, "净利增速": -20.5, "净利率": None, "高亮": False},
            {"公司": "农产品", "PE": 26.1, "PB": 1.32, "ROE": 5.4, "营收增速": 13.4, "净利增速": -3.4, "净利率": None, "高亮": False},
            {"公司": "焦点科技", "PE": 21.8, "PB": 4.02, "ROE": 20.6, "营收增速": 15.1, "净利增速": 11.6, "净利率": None, "高亮": False},
            {"公司": "国联股份", "PE": 9.9, "PB": 1.40, "ROE": 15.6, "营收增速": -4.9, "净利增速": -9.1, "净利率": None, "高亮": False},
            {"公司": "小商品城", "PE": 15.6, "PB": 2.87, "ROE": 17.5, "营收增速": 26.6, "净利增速": 36.8, "净利率": 21.1, "高亮": True},
        ],
        "targets": {
            "labels": ["当前价", "龟龟目标买入价", "悲观PE 12x", "基准PE 14x", "乐观PE 16x", "券商共识参考"],
            "values": [12.48, 6.83, 10.1, 14.0, 17.5, 15.0],
            "注": "合成数据：龟龟目标买入价=现价×R_eff/II=6.83；PE 目标=2026E EPS 1.00×12/14/16x",
        },
        "penetration": {
            "labels": ["R*（主口径）", "R（账面）", "GG（现金校验）", "II（门槛）"],
            "gg": [2.01, 2.52, 4.08, 3.68],
            "ii": 3.68,
            "注": "R*=2.01% < II=3.68%，KK=-1.67pct；GG=AA×M/市值 4.08%",
        },
        "sensitivity": {
            "xlabel": "收入情景（×基准，lambda=0 重估）",
            "ylabel": "现金口径 GG(k)（%）",
            "x": [1.0, 0.9, 0.8, 0.7],
            "系列": [{"name": "GG(k)（lambda=0）", "y": [4.08, 4.08, 4.08, 4.08]}],
            "门槛": 3.68,
            "标题": "图11 穿透回报率敏感性（lambda=0 重估，k* 不输出）",
        },
        "forecast": {
            "标题": "图12 盈利预测：历史与三情景（归母净利，亿元）",
            "labels_hist": [str(y) for y in range(2016, 2026)],
            "np_hist": [10.6, 14.6, 10.8, 12.6, 9.3, 13.3, 11.1, 26.8, 30.7, 42.0],
            "labels_fcast": ["2026E", "2027E", "2028E"],
            "悲观": [46.0, 50.0, 54.0],
            "基准": [55.0, 66.0, 76.0],
            "乐观": [60.0, 76.0, 92.0],
        },
        "pe_band": {
            "标题": "图13 PE_TTM 估值带（2016-2026，5%/95% 分位）",
            "labels": [str(y) for y in range(2016, 2027)],
            "pe_high": [52, 34, 22, 28, 44, 26, 24, 30, 32, 30, 22],
            "pe_low": [16, 12, 8, 10, 14, 12, 10, 14, 16, 14, 10],
            "pe_mean": [30, 22, 15, 18, 26, 18, 16, 22, 24, 21, 16],
            "pe_ttm": [41.2, 22.2, 11.6, 16.8, 32.4, 19.4, 15.9, 22.2, 24.0, 20.7, 15.6],
        },
        "pb_band": {
            "标题": "图14 PB 估值带（2016-2026，5%/95% 分位）",
            "labels": [str(y) for y in range(2016, 2027)],
            "pb_high": [6.5, 4.2, 2.6, 2.8, 3.6, 2.8, 2.6, 3.2, 4.6, 5.0, 3.8],
            "pb_low": [2.2, 1.6, 1.1, 1.2, 1.6, 1.3, 1.3, 1.7, 2.6, 2.8, 2.2],
            "pb": [4.75, 2.87, 1.56, 1.62, 2.23, 1.82, 1.82, 2.32, 3.59, 3.81, 2.87],
        },
        "leverage": {
            "标题": "图15 杠杆与负债结构",
            "labels": [str(y) for y in range(2016, 2026)],
            "资产负债率": [61.2, 51.6, 56.0, 58.2, 52.8, 52.8, 52.4, 51.1, 47.5, 48.1],
            "有息负债率": [17.6, 26.9, 21.4, 18.7, 8.5, 6.1, 16.7, 16.5, 2.1, 7.4],
            "净现金": [-14.6, -21.1, -7.8, 9.6, 29.9, 17.9, -10.2, -6.3, 41.2, 31.0],
        },
        "dps": {
            "labels": [str(y) for y in range(2019, 2026)],
            "dps": [0.07, 0.055, 0.073, 0.065, 0.20, 0.33, 0.50],
            "支付率": [30.4, 32.4, 29.2, 32.5, 40.8, 58.9, 65.2],
            "注": "DPS=每10股派X的X/10；支付率=分红总额/归母净利（法2）",
        },
        "sotp": {
            "标题": "图18 分部估值 SOTP（合成数据）",
            "segments": [
                {"name": "商品销售", "value": 120.0, "pct": 0.42},
                {"name": "市场经营", "value": 90.0, "pct": 0.31},
                {"name": "数贸配套销售", "value": 30.0, "pct": 0.10},
                {"name": "贸易服务", "value": 25.0, "pct": 0.09},
                {"name": "配套服务", "value": 15.0, "pct": 0.05},
                {"name": "其他及抵销", "value": 8.0, "pct": 0.03},
            ],
            "adjustments": {"holding_discount": 1.0, "net_cash": 31.0, "minority": 3.0},
            "per_share": 9.8, "per_share_low": 8.2, "per_share_high": 11.6,
            "price": 12.48, "premium": 0.273,
            "注": "合成数据：分部价值来自 sotp_valuation.py；分部净利为估算（手算/补充）",
        },
    }
    (inp / "运营补充数据.json").write_text(json.dumps(ops, ensure_ascii=False, indent=2), encoding="utf-8")


# ───────────────────────── 报告骨架 ─────────────────────────

_CHART_TITLES = {
    1: "营收与归母净利趋势", 2: "ROE与每股净资产", 3: "分部营收构成与增速",
    4: "盈利能力趋势", 5: "现金流结构", 6: "同行估值与增长对比", 7: "DPS与支付率",
    8: "股价历史位置与关键价格锚", 9: "多框架目标价对比", 10: "穿透回报率 GG vs 门槛 II",
    11: "穿透回报率敏感性分析", 12: "盈利预测：历史与三情景", 13: "PE_TTM 估值带",
    14: "PB 估值带", 15: "杠杆与负债结构", 16: "行业成本与价格走势",
    18: "分部估值SOTP",
}
_SECTION_OF = {1: 4, 2: 4, 3: 3, 4: 4, 5: 4, 6: 6, 7: 4, 8: 6, 9: 7, 10: 6, 11: 6, 12: 5, 13: 6, 14: 6, 15: 4, 16: 2, 18: 6}
_SEC_TITLES = {1: "投资摘要", 2: "行业分析", 3: "公司分析", 4: "财务分析",
               5: "盈利预测", 6: "估值", 7: "投资建议", 8: "催化剂与跟踪", 9: "风险", 10: "附录"}


def build_report(proj: Path) -> Path:
    chart_dir = proj / "reports" / "图表"
    pngs = {int(re.match(r"图(\d{2})", p.name).group(1)): p for p in chart_dir.glob("图*.png")}
    lines = [
        "# 模板回归测试报告（合成数据）",
        "",
        f"> 数据日期：{TODAY} ｜ 用途：skill 模板发布前全图 QC 自检，不构成投资建议",
        "",
    ]
    # 按章节组织
    by_sec: dict[int, list[int]] = {}
    for no in pngs:
        by_sec.setdefault(_SECTION_OF[no], []).append(no)
    for sec in range(1, 11):
        lines.append(f"## {sec} {_SEC_TITLES[sec]}")
        lines.append("")
        if sec == 2:
            lines.append("### 行业成本与价格走势（图16）")
            lines.append("")
            lines.append("**成本与价格解读（合成数据）**：生鲜乳收购价（成本端）自 2024 年初 3.55 元/公斤下行至 2026 年中 3.10 元/公斤，鲜奶平均零售价（价格端）同步缓降，成本降幅大于价格降幅，价差扩大；全国牛奶产量稳中有升，供需宽松支撑成本下行。")
            lines.append("")
        if sec == 4:
            lines.append("### 财务趋势（合成数据）")
            lines.append("")
        for no in sorted(by_sec.get(sec, [])):
            lines.append(f"![图{no:02d} {_CHART_TITLES[no]}](图表/{pngs[no].name})")
            lines.append("")
    # 附录清单
    lines.append("## 10 附录")
    lines.append("")
    lines.append("### 图表清单")
    lines.append("")
    lines.append("| 图号 | 名称 | 章节 | 数据日期 |")
    lines.append("|---|---|---|---|")
    for no in sorted(pngs):
        lines.append(f"| 图{no:02d} | {_CHART_TITLES[no]} | §{_SECTION_OF[no]} | {TODAY} |")
    lines.append("")
    md = proj / "reports" / f"{NAME}_{CODE}_分析报告.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    return md


def render_html(md_path: Path) -> Path:
    md_text = md_path.read_text(encoding="utf-8")
    html = md_text
    chart_dir = md_path.parent / "图表"
    def _repl(m):
        alt, path = m.group(1), m.group(2)
        p = (md_path.parent / path).resolve()
        if not p.exists():
            return f'<p style="color:red">[缺图 {path}]</p>'
        b64 = base64.b64encode(p.read_bytes()).decode()
        return f'<img src="data:image/png;base64,{b64}" alt="{alt}" style="max-width:100%"/>'
    import re
    html = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _repl, html)
    html = f"<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'><title>回归测试报告</title></head><body>{html}</body></html>"
    out = md_path.with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    return out


# ───────────────────────── 主流程 ─────────────────────────

def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("$", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], **kw)


def main() -> int:
    ap = argparse.ArgumentParser(description="模板回归测试：合成项目 -> 出图 -> 报告 -> chart_qc")
    ap.add_argument("--out", default=None, help="项目输出目录（默认系统临时目录）")
    ap.add_argument("--templates-dir", default=None, help="analyze_charts/chart_qc 所在目录（默认本脚本同目录）")
    ap.add_argument("--keep", action="store_true", help="保留临时项目")
    ap.add_argument("--selfcheck", action="store_true", help="负向自检：注入旧 bug，断言 chart_qc FAIL")
    args = ap.parse_args()

    tpl = Path(args.templates_dir) if args.templates_dir else SKILL_SCRIPTS
    ac_src, qc_src = tpl / "analyze_charts.py", tpl / "chart_qc.py"
    if not ac_src.exists() or not qc_src.exists():
        print(f"❌ 模板缺失: {ac_src} / {qc_src}")
        return 2

    if args.selfcheck:
        tmp_tpl = Path(tempfile.mkdtemp(prefix="tpl_neg_"))
        shutil.copy2(ac_src, tmp_tpl / "analyze_charts.py")
        shutil.copy2(qc_src, tmp_tpl / "chart_qc.py")
        broken = (tmp_tpl / "analyze_charts.py").read_text(encoding="utf-8")
        # 注入旧 bug：fig_profitability 净利率标注从"标记点下方"改回"上方"（2022 毛利率 15.3 vs
        # 净利率 14.5 同 x 标注重叠 → G8-RENDER 必 FAIL；小商品城批次实测复现）
        bug_old = "        ax1.text(i, v - 1.1, f\"{v:.1f}%\", ha=\"center\", fontsize=8.5, color=\"#55A868\")"
        bug_new = "        ax1.text(i, v + 0.4, f\"{v:.1f}%\", ha=\"center\", fontsize=8.5, color=\"#55A868\")"
        if bug_old not in broken:
            print("❌ 负向自检：模板已不包含可注入的旧 bug 锚点（fig_profitability 净利率标注下移），请更新 selfcheck 注入逻辑")
            shutil.rmtree(tmp_tpl, ignore_errors=True)
            return 2
        (tmp_tpl / "analyze_charts.py").write_text(broken.replace(bug_old, bug_new, 1), encoding="utf-8")
        tpl = tmp_tpl
        ac_src, qc_src = tpl / "analyze_charts.py", tpl / "chart_qc.py"  # 让后续复制用注入后的模板
        print("[selfcheck] 已注入旧 bug（fig_profitability 净利率标注上移），预期 chart_qc FAIL")
    else:
        tmp_tpl = None

    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="tpl_reg_"))
    proj = out
    print(f"[1/5] 合成项目: {proj}")
    write_proj_data(proj)
    write_ops(proj)
    (proj / "input" / "图表豁免.json").write_text(
        json.dumps({"豁免": []}, ensure_ascii=False), encoding="utf-8")
    # 平台型触发：合成项目 6 分部 → SOTP 强制，验证 图18 生成与门控
    (proj / "input" / "sotp_触发.json").write_text(
        json.dumps({"enabled": True, "reasons": ["合成数据：6 分部，最大占比 50%≤70%（C1）"], "checks": {}},
                   ensure_ascii=False), encoding="utf-8")
    (proj / "data" / "行业成本价格_审计.json").write_text(
        json.dumps({"status": "ok", "profile": "dairy", "note": "模板回归合成数据"}, ensure_ascii=False),
        encoding="utf-8")

    # 把待测模板复制进项目 scripts/（chart_qc 的 G8-RENDER 重载项目内 analyze_charts.py）
    proj_scripts = proj / "scripts"
    proj_scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ac_src, proj_scripts / "analyze_charts.py")
    shutil.copy2(qc_src, proj_scripts / "chart_qc.py")

    print("[2/5] 出图（analyze_charts.py）...")
    r1 = run([sys.executable, proj_scripts / "analyze_charts.py", "--dir", proj,
              "--code", CODE, "--name", NAME, "--ops", proj / "input" / "运营补充数据.json"])
    pngs = list((proj / "reports" / "图表").glob("图*.png"))
    print(f"      生成 PNG {len(pngs)} 张")
    if r1.returncode != 0 or len(pngs) < 15:
        print(f"❌ 出图失败（rc={r1.returncode}，PNG={len(pngs)}）")
        if not args.keep:
            shutil.rmtree(out, ignore_errors=True)
        if tmp_tpl:
            shutil.rmtree(tmp_tpl, ignore_errors=True)
        return 2

    print("[3/5] 生成报告 MD + HTML（嵌入全部图表）...")
    md = build_report(proj)
    render_html(md)

    print("[4/5] 运行 chart_qc.py（G8/G8-RENDER/G8-SENS/G8-INDUSTRY）...")
    r2 = subprocess.run(
        [sys.executable, proj_scripts / "chart_qc.py", "--dir", proj,
         "--report", f"reports/{NAME}_{CODE}_分析报告.md"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r2.stdout:
        print(r2.stdout, end="" if r2.stdout.endswith("\n") else "\n")
    if r2.stderr:
        print(r2.stderr, end="" if r2.stderr.endswith("\n") else "\n")
    out_text = (r2.stdout or "") + (r2.stderr or "")
    passed = "✅ 通过" in out_text and "❌ 未通过" not in out_text
    n_fail = out_text.count("[FAIL]")
    n_warn = out_text.count("[WARN]")

    if args.selfcheck:
        # 负向自检：注入 bug 后必须 FAIL
        ok = r2.returncode != 0 or (not passed and n_fail > 0)
        print("[selfcheck] 结果:", "✅ 负向自检通过（旧 bug 被 chart_qc 抓住）" if ok else "❌ 负向自检失败（注入 bug 未被检出）")
        code = 0 if ok else 1
    else:
        print(f"[5/5] 结论: {'✅ 模板回归通过（无 FAIL）' if passed else '❌ 模板回归失败'}"
              f" ｜ FAIL={n_fail} WARN={n_warn} rc={r2.returncode}")
        code = 0 if passed else 1

    if args.keep:
        print(f"保留项目目录: {proj}")
    elif not args.selfcheck:
        shutil.rmtree(out, ignore_errors=True)
    if tmp_tpl:
        shutil.rmtree(tmp_tpl, ignore_errors=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
