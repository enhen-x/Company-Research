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
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from run_support import run_process

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
            {"公司": "轻纺城", "PE": 16.1, "PB": 0.84, "ROE": -0.3, "营收增速": -7.6, "净利增速": -111.5, "净利率": None, "标的": False},
            {"公司": "海宁皮城", "PE": 102.6, "PB": 0.59, "ROE": 0.8, "营收增速": -3.6, "净利增速": -20.5, "净利率": None, "标的": False},
            {"公司": "农产品", "PE": 26.1, "PB": 1.32, "ROE": 5.4, "营收增速": 13.4, "净利增速": -3.4, "净利率": None, "标的": False},
            {"公司": "焦点科技", "PE": 21.8, "PB": 4.02, "ROE": 20.6, "营收增速": 15.1, "净利增速": 11.6, "净利率": None, "标的": False},
            {"公司": "国联股份", "PE": 9.9, "PB": 1.40, "ROE": 15.6, "营收增速": -4.9, "净利增速": -9.1, "净利率": None, "标的": False},
            {"公司": "小商品城", "PE": 15.6, "PB": 2.87, "ROE": 17.5, "营收增速": 26.6, "净利增速": 36.8, "净利率": 21.1, "标的": True},
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
_SEC_TITLES = {1: "投资摘要", 2: "宏观与行业分析", 3: "公司分析", 4: "财务分析",
               5: "盈利预测", 6: "估值分析", 7: "投资建议与目标价",
               8: "催化剂与跟踪", 9: "风险与反证条件", 10: "附录"}


def build_report(proj: Path) -> Path:
    chart_dir = proj / "reports" / "图表"
    pngs = {int(re.match(r"图(\d{2})", p.name).group(1)): p for p in chart_dir.glob("图*.png")}
    lines = [
        "# 测试公司（600415.SH）分析报告",
        "",
        f"> 分析日期：{TODAY} ｜ 当前价：12.48元 ｜ 总市值：10亿元 ｜ 最新财报：{TODAY}",
        f"> 框架版本：company-research report-template v3 ｜ 数据截至：{TODAY}",
        "",
        "### 报告元信息",
        "",
        "| 项目 | 内容 |",
        "|---|---|",
        f"| 上市结构 | A股；直接持股；股息税率Q=0% |",
        f"| 总股本 | 8000万股 |",
        f"| 无风险利率 Rf | 1.70%（合成数据，{TODAY}） |",
        "| 数据来源 | 合成财务序列、模型 JSON、行业成本价格数据 |",
        "| 数据审计状态 | PASS |",
        "| 报告限制 | 合成数据，仅用于模板回归测试 |",
        "",
    ]
    # 按章节组织
    by_sec: dict[int, list[int]] = {}
    for no in pngs:
        by_sec.setdefault(_SECTION_OF[no], []).append(no)
    for sec in range(1, 11):
        lines.extend([f"## {sec}. {_SEC_TITLES[sec]}", ""])
        if sec == 1:
            lines.extend(["### 1.1 结论先行", "", "**最终结论**：市场轨与龟龟轨同向，合成标的可观察。", "",
                           "### 1.2 核心数字", "", "12个月目标价、龟龟目标买入价、R_eff、II、KK、仓位与价值陷阱风险均已列入核心数字表。", "",
                           "### 1.3 核心逻辑、最大优势与最大风险", "", "核心逻辑是需求稳定；最大优势是商业模式；最大风险是估值回撤。", "",
                           "### 1.4 本节结论", "", "**本节结论**：合成数据支持继续观察。", f"> 数据依据：合成数据序列；截至{TODAY}。", ""])
        elif sec == 2:
            lines.extend(["### 2.1 宏观环境", "", "宏观需求、利率和政策通过行业供给与需求影响公司。", "",
                           "### 2.2 行业空间、生命周期与竞争格局", "", "行业处于成熟生命周期，供给、需求和竞争格局保持稳定。", "",
                           "### 2.3 量价结构、议价力与政策", "", "价格与成本传导、议价力和政策约束保持可跟踪。", "",
                           "### 2.4 行业关键跟踪指标", "", "需求、供给和政策指标按月跟踪。", ""])
        elif sec == 3:
            lines.extend(["### 3.1 商业模式与公司定位", "", "商业模式清晰，客户、产品、收费、成本与现金回收路径可解释。", "",
                           "### 3.2 业务分部与单位经济学", "", "分部收入、占比、增速、毛利率和单位经济学已拆分。", "",
                           "### 3.3 护城河与竞争优势", "", "护城河以规模和成本证据验证。", "",
                           "### 3.4 管理层、治理与资本配置", "", "管理层、治理和资本配置可追溯。", ""])
        elif sec == 4:
            lines.extend([
                "### §4.1 盈利与资产负债表", "", "盈利、资产负债表和异常项已按年度重建。",
                "", "**小节结论**：盈利趋势稳定，资产负债表可承受。", f"> 数据依据：合成财务序列；截至{TODAY}。", "",
                "### §4.2 现金流与盈利质量", "", "现金流、应收、存货、应付、资本开支和自由现金流已分析。",
                "", "**小节结论**：现金流质量处于可接受区间。", f"> 数据依据：合成现金流序列；截至{TODAY}。", "",
                "### §4.3 本期财报体检", "",
                "本期财报体检.json 是本期数字唯一来源。",
                "#### 4.3.1 本期财报结论先行", "经营改善。",
                "#### 4.3.2 现金流：赚的是真钱还是账面利润", "现金流与利润同步。",
                "#### 4.3.3 经营现金流变化原因", "营运资本变化可解释。",
                "#### 4.3.4 利润波动原因", "利润桥显示费用和收入共同影响。",
                "#### 4.3.5 存货专项检查", "不适用（合成服务业）。",
                "#### 4.3.6 非主营投资和金融资产检查", "未发现异常。",
                "#### 4.3.7 管理层解释与数据验证", "管理层解释与数据一致。",
                "#### 4.3.8 财务美化/劣化风险信号", "风险信号仅作待核查线索。",
                "#### 4.3.9 对全年预测和估值的影响", "维持预测。",
                "", "**小节结论**：本期财报不改变基准判断。", f"> 数据依据：合成体检 JSON 与证据摘要；截至{TODAY}。", "",
                "### §4.4 同行业比较", "", "同行业比较统一口径并解释差异。",
                "", "**小节结论**：标的相对同行处于中位。", f"> 数据依据：合成同行数据；截至{TODAY}。", "",
            ])
        elif sec == 5:
            lines.extend(["### 5.1 预测方法与驱动桥", "", "事实、假设、模型、结果和跟踪指标形成收入到 EPS 的驱动桥。", "",
                           "### 5.2 关键假设与可跟踪指标", "", "假设均有历史依据和跟踪指标。", "",
                           "### 5.3 三情景预测", "", "悲观、基准、乐观三情景带概率。", "",
                           "### 5.4 现实检查与敏感性", "", "敏感性检查不存在曲棍球棒。", ""])
        elif sec == 6:
            lines.extend(["### 6.1 市场估值与双锚", "", "PE、PB、DCF 双锚与适用性已说明。", "",
                           "### 6.2 SOTP 分部估值（适用时）", "", "SOTP 估值不适用时保留原因。", "",
                           "### 6.3 龟龟穿透回报率", "", "R_eff、II、KK、龟龟目标买入价和现金校验已引用 JSON。", "",
                           "### 6.4 估值结论与安全边际", "", "目标价、目标买入价和门槛价格口径分离。", ""])
        elif sec == 7:
            lines.extend(["### 7.1 双轨评级", "", "市场/券商轨与龟龟轨并列，门槛价格单独列示。", "",
                           "### 7.2 12个月三情景目标价", "", "悲观、基准、乐观概率加权目标价已列示。", "",
                           "### 7.3 仓位与执行条件", "", "仓位由 KK、可信度、陷阱风险和价格条件推导。", ""])
        elif sec == 8:
            lines.extend(["### 8.1 催化剂", "", "催化剂有时间窗口和兑现指标。", "",
                           "### 8.2 跟踪验证台账", "", "跟踪验证台账有基线、验证时点和触发动作。", ""])
        elif sec == 9:
            lines.extend(["### 9.1 风险矩阵", "", "风险概率及方法、影响路径和量化影响已列示。", "",
                           "### 9.2 尾部压力测试", "", "尾部情景评估回撤。", "",
                           "### 9.3 待验证事项与数据局限", "", "反证条件和待验证事项已列示。", ""])
        elif sec == 10:
            lines.extend(["### 10.1 数据来源与口径", "", "数据来源已列示。", "",
                           "### 10.2 方法与公式", "", "方法与公式已列示。", "",
                           "### 10.3 图表清单", ""])
        for no in sorted(by_sec.get(sec, [])):
            lines.append(f"![图{no:02d} {_CHART_TITLES[no]}](图表/{pngs[no].name})")
            lines.append("")
        if 2 <= sec <= 9:
            lines.extend([f"**本节结论**：第 {sec} 章结论已由合成证据支持。", f"> 数据依据：合成数据与脚本输出；截至{TODAY}。", ""])
        if sec == 10:
            lines.extend(["| 图号 | 名称 | 章节 | 数据日期 |", "|---|---|---|---|"])
            for no in sorted(pngs):
                lines.append(f"| 图{no:02d} | {_CHART_TITLES[no]} | §{_SECTION_OF[no]} | {TODAY} |")
            lines.extend(["", "### 10.4 复验与版本记录", "", "复验计划和模板版本已记录。", "",
                           "### 10.5 免责声明", "", "本报告仅用于模板回归测试，不构成投资建议。", "",
                           "### 10.6 本节结论", "", "**本节结论**：模板回归报告结构完整。", f"> 数据依据：合成数据和脚本输出；截至{TODAY}。", ""])
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

def run(cmd: list[str], *, timeout=300, heartbeat=10, label="模板回归阶段") -> subprocess.CompletedProcess:
    print("$", " ".join(str(c) for c in cmd), flush=True)
    command = [str(c) for c in cmd]
    result = run_process(command, timeout=timeout, heartbeat=heartbeat, label=label)
    if result["status"] == "TIMEOUT":
        raise TimeoutError(f"{label} exceeded {timeout:g}s")
    code = result.get("exit_code")
    return subprocess.CompletedProcess(command, code if code is not None else 2,
                                       stdout=result.get("output", ""), stderr="")


def injected_layout_bug_detected(returncode: int, output: str) -> bool:
    """Only the intended QC finding counts; an import/runtime crash is no evidence."""
    return (returncode == 1 and "Traceback (most recent call last)" not in output
            and bool(re.search(r"\[FAIL\].*G8-RENDER: 图04.*(?:重叠|不合格)", output)))


def selfcheck_new_data_contracts(proj: Path, qc_src: Path) -> bool:
    """负向验证本次新增门控：旧版错误标的 + 静态估值边界必须被拦截。"""
    import importlib.util

    ops_path = proj / "input" / "运营补充数据.json"
    original = ops_path.read_text(encoding="utf-8")
    try:
        ops = json.loads(original)
        for row in ops.get("peers", []):
            row.pop("标的", None)
            row.pop("target", None)
        # 模拟旧版：把任意同行误标为高亮，并把全历史边界复制到每个时点。
        if ops.get("peers"):
            ops["peers"][1]["高亮"] = True
        pe = ops.get("pe_band", {})
        if pe.get("pe_high") and pe.get("pe_low"):
            pe["pe_high"] = [max(pe["pe_high"])] * len(pe["pe_high"])
            pe["pe_low"] = [min(pe["pe_low"])] * len(pe["pe_low"])
        pb = ops.get("pb_band", {})
        if pb.get("pb_high") and pb.get("pb_low"):
            pb["pb_high"] = [max(pb["pb_high"])] * len(pb["pb_high"])
            pb["pb_low"] = [min(pb["pb_low"])] * len(pb["pb_low"])
        ops_path.write_text(json.dumps(ops, ensure_ascii=False), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("_negative_qc", qc_src)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _, peer_fail = mod.check_ops_contract(proj)
        _, band_fail = mod.check_valuation_band_contract(proj)
        return bool(peer_fail) and bool(band_fail)
    finally:
        ops_path.write_text(original, encoding="utf-8")


def _run_project(args, proj: Path, scratch: Path, tpl: Path) -> int:
    """Child owns computation; the supervising parent owns every temporary path."""
    ac_src, qc_src = tpl / "analyze_charts.py", tpl / "chart_qc.py"
    rt_src = tpl / "report_template_qc.py"
    if not ac_src.exists() or not qc_src.exists() or not rt_src.exists():
        print(f"❌ 模板缺失: {ac_src} / {qc_src} / {rt_src}")
        return 2

    if args.selfcheck:
        tmp_tpl = scratch / "negative_templates"
        tmp_tpl.mkdir()
        shutil.copy2(ac_src, tmp_tpl / "analyze_charts.py")
        shutil.copy2(qc_src, tmp_tpl / "chart_qc.py")
        broken = (tmp_tpl / "analyze_charts.py").read_text(encoding="utf-8")
        # 注入旧 bug：fig_profitability 净利率标注从"标记点下方"改回"上方"（2022 毛利率 15.3 vs
        # 净利率 14.5 同 x 标注重叠 → G8-RENDER 必 FAIL；小商品城批次实测复现）
        bug_old = "        ax1.text(i, v - 1.1, f\"{format_number(v)}%\", ha=\"center\", fontsize=8.5, color=\"#55A868\")"
        bug_new = "        ax1.text(i, v + 0.4, f\"{format_number(v)}%\", ha=\"center\", fontsize=8.5, color=\"#55A868\")"
        if bug_old not in broken:
            print("❌ 负向自检：模板已不包含可注入的旧 bug 锚点（fig_profitability 净利率标注下移），请更新 selfcheck 注入逻辑")
            return 2
        broken=broken.replace(bug_old, bug_new, 1).replace('    _resolve_value_collisions(fig)\n','    # disabled in negative regression\n')
        (tmp_tpl / "analyze_charts.py").write_text(broken, encoding="utf-8")
        tpl = tmp_tpl
        ac_src, qc_src = tpl / "analyze_charts.py", tpl / "chart_qc.py"  # 让后续复制用注入后的模板
        print("[selfcheck] 已注入旧 bug（fig_profitability 净利率标注上移），预期 chart_qc FAIL")
    else:
        tmp_tpl = None

    print(f"[1/6] 合成项目: {proj}")
    write_proj_data(proj)
    write_ops(proj)
    # Latest-period contracts are mandatory even in synthetic regression batches.
    op_path = proj / "input" / "运营补充数据.json"
    op = json.loads(op_path.read_text(encoding="utf-8"))
    review = {"checked_through": "2025-12-31", "period_end": "2025-12-31", "basis": "FY", "source": "合成回归数据"}
    op["segment"]["period_review"] = dict(review)
    op["peers_period"] = {"period_review": dict(review)}
    for peer in op["peers"]:
        peer["报告期"] = "2025-12-31"
    op["dps"]["period_review"] = {**review, "current_fiscal_year_status": "合成样本已披露"}
    op_path.write_text(json.dumps(op, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.selfcheck:
        contract_ok = selfcheck_new_data_contracts(proj, qc_src)
        print("[selfcheck] 新增 G8 数据契约:",
              "✅ 错误标的/静态估值带均被拦截" if contract_ok else "❌ 新增契约未拦截旧版数据")
        if not contract_ok:
            return 1
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
    shutil.copy2(rt_src, proj_scripts / "report_template_qc.py")
    for dependency in ("chart_periods.py", "chart_period_qc.py", "financial_history_charts.py", "chart_numbers.py", "run_support.py"):
        shutil.copy2(SKILL_SCRIPTS / dependency, proj_scripts / dependency)

    print("[2/6] 出图（analyze_charts.py）...")
    r1 = run([sys.executable, proj_scripts / "analyze_charts.py", "--dir", proj,
              "--code", CODE, "--name", NAME, "--ops", proj / "input" / "运营补充数据.json"],
             timeout=args.stage_timeout, heartbeat=args.heartbeat, label="出图")
    pngs = list((proj / "reports" / "图表").glob("图*.png"))
    print(f"      生成 PNG {len(pngs)} 张")
    if r1.returncode != 0 or len(pngs) < 15:
        print(f"❌ 出图失败（rc={r1.returncode}，PNG={len(pngs)}）")
        return 2

    print("[3/6] 生成报告 MD + HTML（嵌入全部图表）...")
    md = build_report(proj)
    render_html(md)

    print("[4/6] 运行 report_template_qc.py（统一十部分报告契约）...")
    r_template = run(
        [sys.executable, proj_scripts / "report_template_qc.py", "--report", md],
        timeout=args.stage_timeout, heartbeat=args.heartbeat, label="报告模板门")
    if r_template.returncode != 0:
        print("❌ 报告模板门失败")
        return 1

    print("[5/6] 运行 chart_qc.py（G8/G8-RENDER/G8-SENS/G8-INDUSTRY）...")
    r2 = run(
        [sys.executable, proj_scripts / "chart_qc.py", "--dir", proj,
         "--report", f"reports/{NAME}_{CODE}_分析报告.md"],
        timeout=args.stage_timeout, heartbeat=args.heartbeat, label="图表门")
    out_text = (r2.stdout or "") + (r2.stderr or "")
    passed = "✅ 通过" in out_text and "❌ 未通过" not in out_text
    n_fail = out_text.count("[FAIL]")
    n_warn = out_text.count("[WARN]")

    if args.selfcheck:
        # 负向自检：注入 bug 后必须 FAIL
        ok = injected_layout_bug_detected(r2.returncode, out_text)
        print("[selfcheck] 结果:", "✅ 负向自检通过（旧 bug 被 chart_qc 抓住）" if ok else "❌ 负向自检失败（注入 bug 未被检出）")
        code = 0 if ok else 1
    else:
        print(f"[6/6] 结论: {'✅ 模板回归通过（无 FAIL）' if passed else '❌ 模板回归失败'}"
              f" ｜ FAIL={n_fail} WARN={n_warn} rc={r2.returncode}")
        code = 0 if passed else 1

    return code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="模板回归测试：合成项目 -> 出图 -> 报告 -> chart_qc")
    ap.add_argument("--out", default=None, help="新建项目输出目录（默认系统临时目录；仅 --keep 保留）")
    ap.add_argument("--templates-dir", default=None, help="analyze_charts/chart_qc 所在目录（默认本脚本同目录）")
    ap.add_argument("--keep", action="store_true", help="保留临时项目，包括失败或超时的部分输出")
    ap.add_argument("--selfcheck", action="store_true", help="负向自检：注入旧 bug，断言 chart_qc FAIL")
    ap.add_argument("--stage-timeout", type=float, default=300, help="单阶段超时秒数（默认 300）")
    ap.add_argument("--total-timeout", type=float, default=1200, help="整体超时秒数（默认 1200）")
    ap.add_argument("--heartbeat", type=float, default=10, help="运行状态间隔秒数（默认 10）")
    ap.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--_scratch", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    for key in ("stage_timeout", "total_timeout", "heartbeat"):
        value = getattr(args, key)
        if not math.isfinite(value) or value <= 0:
            ap.error(f"--{key.replace('_', '-')} must be finite and positive")
    tpl = Path(args.templates_dir).resolve() if args.templates_dir else SKILL_SCRIPTS
    try:
        if args._worker:
            if not args.out or not args._scratch:
                ap.error("internal worker requires --out and --_scratch")
            return _run_project(args, Path(args.out).resolve(), Path(args._scratch).resolve(), tpl)

        # Refuse pre-existing user directories before allocating or deleting anything.
        explicit = Path(args.out).resolve() if args.out else None
        if explicit is not None and explicit.exists():
            raise ValueError("--out must name a new directory; existing contents are preserved")
        for filename in ("analyze_charts.py", "chart_qc.py", "report_template_qc.py"):
            if not (tpl / filename).is_file():
                raise ValueError(f"模板缺失: {tpl / filename}")
        with tempfile.TemporaryDirectory(prefix="tpl_reg_runtime_") as temporary:
            scratch = Path(temporary).resolve()
            if explicit is not None:
                project = explicit
                project.mkdir(parents=True)
            elif args.keep:
                project = Path(tempfile.mkdtemp(prefix="tpl_reg_")).resolve()
            else:
                project = scratch / "project"
                project.mkdir()
            try:
                command = [sys.executable, str(Path(__file__).resolve()), "--_worker",
                           "--out", str(project), "--_scratch", str(scratch),
                           "--templates-dir", str(tpl), "--stage-timeout", str(float(args.stage_timeout)),
                           "--heartbeat", str(float(args.heartbeat))]
                if args.selfcheck:
                    command.append("--selfcheck")
                result = run_process(command, timeout=args.total_timeout, heartbeat=args.heartbeat,
                                     label="模板回归整体")
                if result["status"] == "TIMEOUT":
                    return 2
                code = result.get("exit_code")
                return code if code in (0, 1, 2) else 2
            finally:
                if args.keep:
                    print(f"保留项目目录: {project}", flush=True)
                elif explicit is not None:
                    # This exact absolute path was created above and did not exist before.
                    if project.resolve() != explicit or project == Path(project.anchor):
                        raise ValueError("Refusing cleanup outside the owned output path")
                    shutil.rmtree(project)
    except (OSError, ValueError, TimeoutError) as exc:
        print(f"❌ 模板回归运行错误: {exc}", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
