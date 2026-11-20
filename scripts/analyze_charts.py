#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一图表生成模板（B4.2 可视化标准）：PNG（≥10 张）+ Plotly 交互 HTML 双输出。

图表编号→报告章节映射（以 SKILL.md §B4.3 为准，写报告时按图号嵌入对应章节）：
  图01 → §4 财务分析      | 图02 → §4 财务分析      | 图03 → §3 公司分析
  图04 → §4 财务分析      | 图05 → §4 财务分析      | 图06 → §6 估值
  图07 → §4 财务分析      | 图08 → §6 估值          | 图09 → §7 投资建议
  图10 → §6 估值(穿透)    | 图11 → §6 估值(穿透)    | 图12 → §5 盈利预测
  图13 → §6 估值          | 图14 → §6 估值          | 图15 → §4 财务分析
  图16 → §2 行业分析（宏观与行业：成本与价格走势） | 图17 → 跟踪验证台账（复验时）
  图18 → §6 估值（SOTP 分部估值，平台型公司强制，sotp_valuation.py 输出）

数据来源分两层：
  1. 自动读取 --dir/data/*.csv：利润表/资产负债表/现金流量表/财务指标/日线/分红
     - 字段名自动适配东财emweb（OPERATE_INCOME/PARENT_NETPROFIT/ROEJQ/BPS等）
     或简化名（营业总收入/归母净利/ROE/BPS等）
     - 可生成：图01/02/05/07/08/15（6张，无需ops）
  2. 运营补充数据 JSON（--ops）：分部营收/盈利能力/同行/目标价/穿透回报率/
     敏感性/预测/估值带/杠杆/行业成本价格 —— 缺失则自动跳过对应图并提示
     - 可生成：图03/04/06/09/10/11/12/13/14（9张，需ops）
     - 图16：优先读 data/行业成本价格.csv（fetch_industry_cost_price.py 生成，
       role=cost/price 必选 + volume（产量/存栏，供需面板）+ margin（价差示意，
       须标注“手算/补充”）可选）；画原始值双轴，不用指数化；也可经 ops
       industry_cost_price 键覆盖（字段：labels/series[].values/raw_values/unit/role）

--ops 键名规范（缺失键自动跳过对应图，行业不适用标记为"不适用"）：
{
  "segment": {"标题":"图03 ...", "labels":["2023","2024","2025"], "series":[{"name":"品类A","values":[1,2,3]}],
              "增速":{"合计增速":[10,20,15]}, "注":"口径说明"},
              # 图03 一律渲染为【环形饼图】（≥3 年并列，一年一张；图例置图上方横向一排；
              # 年份+营收总额放环心，禁止子图 set_title——会与顶部图例重叠；<3.5% 小分段不标百分比）。
  "profitability": {"标题":"图04 ...","labels":[...], "毛利率":[...], "净利率":[...], "ROE":[...]},
  "cashflow": {"标题":"图05 ...","labels":[...], "OCF":[...], "Capex":[...], "FCF":[...], "D_A":[...]},
  "target": {"公司":"标的公司","代码":"000000"},
  "peers": [{"公司":"标的公司","代码":"000000","PE":20,"PB":3,"ROE":15,"营收增速":10,"净利增速":12,"净利率":18,"标的":true}],
  "targets": {"labels":["当前价","PE基准",...], "values":[100,150,...], "注":"说明"},
  "penetration": {"labels":["情景A","情景B"], "gg":[2.5,4.2], "ii":3.70, "注":"说明"},
  "sensitivity": {"xlabel":"...","ylabel":"...","x":[0.7,0.8,1.0,1.1,1.2],
                  "系列":[{"name":"GG(情景A)","y":[...]}], "门槛":3.70, "标题":"图11 ..."},
  "forecast": {"标题":"图12 ...","labels_hist":[...],"np_hist":[...],
               "labels_fcast":["2026E","2027E","2028E"], "悲观":[...],"基准":[...],"乐观":[...]},
  "pe_band": {"标题":"图13 ...","labels":[...],"pe_ttm":[...],"pe_high":[...],"pe_low":[...],"pe_mean":[...]},
  "pb_band": {"标题":"图14 ...","labels":[...],"pb":[...],"pb_high":[...],"pb_low":[...]},
  "leverage": {"标题":"图15 ...","labels":[...],"资产负债率":[...],"有息负债率":[...],"净现金":[...]},
  "industry_cost_price": {"labels":["2024-01","2024-06"],"series":[{"name":"生鲜乳收购价",
        "role":"cost","unit":"元/公斤","values":[100,98.5],"raw_values":[3.5,3.45],
        "source":"农业农村部","source_date":"2026-01"},{"name":"鲜奶零售价",
        "role":"price","unit":"元/斤","values":[100,101],"raw_values":[5.72,5.73],
        "source":"中国价格信息网","source_date":"2026-01"},{"name":"全国牛奶产量",
        "role":"volume","unit":"万吨","values":[100,102],"raw_values":[4079,4091],
        "source":"国家统计局","source_date":"2026-01"}]},
  "dps": {"labels":[...], "dps":[...], "支付率":[...], "注":"说明"}
}

用法：
    python analyze_charts.py --dir "项目目录" --code 代码 --name 公司名 [--ops input/运营补充数据.json]

输出：
    PNG -> --out（默认 --dir/reports/图表/图NN_*.png）
    HTML -> --html-out（默认 --dir/reports/<名称>_<代码>_图表.html）
"""
from __future__ import annotations

import argparse, json, math, re, sys
import textwrap
import functools
import hashlib
from pathlib import Path
from chart_numbers import format_number

from chart_periods import (build_period_pack, refresh_period_pack, extend_chart_input, record_integrated_figure,
                          CHART_METRICS, NAMES, RATIOS, STOCKS)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "PingFang SC", "Segoe UI", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _apply_clean_chart_style(ax: plt.Axes, *, grid_axis: str = "y", pad: float = 7, labelpad: float = 10) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#E2E8F0")
    ax.spines["bottom"].set_color("#CBD5E1")
    ax.tick_params(axis="both", pad=pad)
    if grid_axis:
        ax.grid(axis=grid_axis, color="#F1F5F9", linewidth=0.8)
        ax.set_axisbelow(True)


def _apply_clean_twin_style(ax2: plt.Axes, *, pad: float = 7, labelpad: float = 10) -> None:
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.spines["right"].set_color("#E2E8F0")
    ax2.spines["bottom"].set_color("#CBD5E1")
    ax2.tick_params(axis="both", pad=pad)

SRC = "数据：东财/公司公告/行情源 ｜ 生成日以数据日期为准"
LATEST_PACK = {}


def _script_sensitivity(project: Path) -> dict | None:
    """Build Figure 11's cash-surplus series directly from calculator output.

    ``运营补充数据.json`` remains the override for deliberately custom views,
    but a missing sensitivity section should not force a hand-copied chart input
    when the deterministic penetration calculator has already produced the
    required rows.
    """
    output_path = project / "reports" / "穿透回报率_输出.json"
    try:
        output = json.loads(output_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    rows = output.get("single_year")
    if not isinstance(rows, list):
        return None
    points = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            k = float(row["k"])
            gg = float(row["gg"]) * 100.0
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(k) and math.isfinite(gg):
            points.append((k, gg))
    if not points:
        return None
    lam = output.get("lambda")
    try:
        lam_value = float(lam)
        if not math.isfinite(lam_value):
            lam_value = None
    except (TypeError, ValueError):
        lam_value = None
    revenue_response = lam_value is not None and lam_value != 0
    reference = output.get("lambda_policy") == "historical_mean_reference"
    low_reliability = output.get("lambda_reliable") is False
    lam_text = f"λ={lam_value:.6g}" if lam_value is not None else "λ未提供"
    warning = str(output.get("lambda_warning") or "").strip()
    note = f"由 reports/穿透回报率_输出.json 的 single_year 自动生成；{lam_text}。"
    if reference:
        note += "保留历史逐段斜率均值，可靠性单独评估；本图为给定λ的条件演算。"
    if low_reliability:
        note += "λ可靠性低，仅供参考，不用于盈利预测，不输出k*。"
    if not revenue_response:
        note += "λ为零或未提供，平线不表示真实经营弹性为零。"
    if warning:
        note += warning
    return {
        "mode": "script_cash_surplus",
        "xlabel": "收入倍数（×基准）" if revenue_response else "压力情景系数（不代表收入弹性）",
        "ylabel": "GG（%）",
        "x": [x for x, _ in points],
        "系列": [{"name": "GG · 单年下滑情景", "y": [y for _, y in points]}],
        "门槛": float(output["II"]) * 100.0 if output.get("II") is not None else None,
        "标题": ("图11 收入下滑的现金回报敏感性" + ("（低可靠性参考）" if low_reliability else ""))
                if revenue_response else "图11 现金回报敏感性（λ为零或未提供）",
        "注": note,
    }


def _bind_script_sensitivity(project: Path, ops: dict) -> dict:
    """Use calculator output only when the operational input omits Figure 11."""
    if isinstance(ops.get("sensitivity"), dict):
        return ops
    derived = _script_sensitivity(project)
    if derived is None:
        return ops
    bound = dict(ops)
    bound["sensitivity"] = derived
    p("[加载] 图11敏感性：来自 reports/穿透回报率_输出.json（single_year）")
    return bound


def configure_latest(data_dir: Path, write: bool = False):
    global LATEST_PACK
    LATEST_PACK = (refresh_period_pack if write else build_period_pack)(Path(data_dir).parent)
    return LATEST_PACK


def latest_chart(chart_id):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            if LATEST_PACK.get('has_interim_income'):
                from financial_history_charts import fig_history
                ops = args[0] if args and isinstance(args[0],dict) else None
                return fig_history(LATEST_PACK,chart_id,ops)
            if args and LATEST_PACK.get('basis') == 'YTD':
                args = (extend_chart_input(args[0], chart_id, LATEST_PACK), *args[1:])
            return record_integrated_figure(fn(*args, **kwargs), chart_id, LATEST_PACK)
        return wrapped
    return decorate

# ─── helpers ───────────────────────────────────────────────
def p(msg: str) -> None:
    print(msg, flush=True)


def _section_title(raw: object, default: str, section: str) -> str:
    """Normalize a data-supplied title and append its report section once."""
    title = str(raw or default).strip()
    title = re.split(r"\s*→\s*§", title, maxsplit=1)[0].rstrip()
    return f"{title} → {section}"

def load_csv(data_dir: Path, name: str) -> pd.DataFrame | None:
    f = data_dir / name
    if not f.exists():
        return None
    try:
        return pd.read_csv(f, encoding="utf-8-sig")
    except Exception:
        try:
            return pd.read_csv(f, encoding="utf-8")
        except Exception as exc:
            p(f"[WARN] 读取 {name} 失败: {exc}")
            return None

def save(fig, out_dir: Path, name: str) -> None:
    _layout_legend_top(fig)
    if not getattr(fig,'_year_grouped',False):
        fig.tight_layout(rect=(0, 0, 1, .84) if getattr(fig, '_legend_top', False) else None)
    _auto_fix_layout(fig)   # G8-RENDER 自适应（2026-08-18）：标注越界/图例遮挡/双轴标注距离/刻度
    _auto_height(fig)       # G8-RENDER 高度自适应（2026-08-18）：axes 被轴外元素压缩时手动拉满
    fig.savefig(out_dir / name, dpi=150, bbox_inches="tight",
                bbox_extra_artists=[t for t in fig.texts if t.get_visible()]+list(fig.legends))
    plt.close(fig)
    p(f"[OK] {name}")


def _auto_height(fig, min_ratio: float = 0.65):
    """G8-RENDER 高度自适应（2026-08-18，图15 校准）：tight_layout 后若单图
    （含 twinx，≤2 个 axes）的 axes 高度占比 < min_ratio（被轴外脚注/图例挤压），
    手动把主 axes 拉满 figure（bottom=0.10, top=0.88），避免图高只占 3/5。"""
    if getattr(fig, '_legend_top', False) or getattr(fig, '_measured_native_layout', False):
        return False  # reserved title/legend rows are intentional, not squeezed axes
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    fh = fig.bbox.height
    if fh <= 0 or len(fig.axes) > 2:
        return False
    main = None
    for ax in fig.axes:
        if ax.get_window_extent(renderer).height / fh < min_ratio:
            main = ax
            break
    if main is None:
        return False
    pos = main.get_position()
    main.set_position([pos.x0, 0.10, pos.width, 0.78])
    for ax in fig.axes:
        if ax is not main:
            try:
                if ax.get_subplotspec() == main.get_subplotspec():
                    ax.set_position(main.get_position())
            except Exception:
                pass
    fig.canvas.draw()
    return True


def _fix_xtick_overlap(fig) -> None:
    """横坐标刻度后处理（2026-08-17 全图统一）：>12 个可见刻度则用
    set_xticks/set_xticklabels 稀疏化（保留 ≈10 个，draw 不重置——不能只改
    Text 文本，matplotlib 每次 draw 会按 locator 重置标签），标签较长
    （≥6 字符）自动旋转 30°，解决刻度文字重合。"""
    fig.canvas.draw()
    for ax in fig.axes:
        positions = list(ax.get_xticks())
        labels = list(ax.get_xticklabels())
        idx = [i for i, t in enumerate(labels)
               if t.get_visible() and t.get_text().strip()]
        if not idx:
            continue
        if len(idx) > 12:
            step = max(1, math.ceil(len(idx) / 10))
            # Always retain the newest observation and both latest-period labels.
            latest_year=str(getattr(fig,'_latest_period',''))[:4]
            keep = sorted(set(idx[::step] + [idx[-1]] + [i for i in idx if '实际' in labels[i].get_text() or '基期' in labels[i].get_text() or (latest_year and labels[i].get_text()==latest_year)]))
            ax.set_xticks([positions[i] for i in keep])
            ax.set_xticklabels([labels[i].get_text() for i in keep])
            labels = list(ax.get_xticklabels())
        texts = [t.get_text() for t in labels if t.get_text().strip()]
        if texts and max(len(x) for x in texts) >= 6:
            for t in labels:
                if t.get_text().strip():
                    t.set_rotation(30)
                    t.set_ha("right")

def year_rows(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["REPORT_DATE"] = pd.to_datetime(df["REPORT_DATE"])
    return df[df["REPORT_DATE"].dt.month == 12].sort_values("REPORT_DATE")

def num(v):
    try:
        if v is None or str(v).strip() in ("", "nan", "None"):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None

def e8(v):
    n = num(v)
    return n / 1e8 if n is not None else None

def _fnum(v) -> float:
    """估值带数组元素清洗：None/非数 -> np.nan（供 fill_between/plot 安全处理）。
    2026-08-23 中远海控批次：亏损年 PE 为 None 曾使 fill_between 抛 isfinite 异常。"""
    n = num(v)
    return n if n is not None and np.isfinite(n) else np.nan

def _col(df: pd.DataFrame, *candidates: str) -> str | None:
    """Return first matching column name."""
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _dy(vals, frac=0.05, min_dy=0.3):
    """数据标注垂直偏移：按量级自适应，避免固定偏移在小数值上离点过远。"""
    v = [x for x in vals if x is not None and not (isinstance(x, float) and np.isnan(x))]
    if not v:
        return min_dy
    return max(max(v) * frac, min_dy)

def _dy(vals, frac=0.05, min_dy=0.3):
    """数据标注垂直偏移：按量级自适应，避免固定偏移在小数值上离点过远。"""
    v = [x for x in vals if x is not None and not (isinstance(x, float) and np.isnan(x))]
    if not v:
        return min_dy
    return max(max(v) * frac, min_dy)


# ─── G8-RENDER 自适应绘制（2026-08-18 新增，平安批次校准）────────────────
# 统一修复四类渲染问题：① 数据标注越界（扩展 ylim/xlim 容纳）；② 图例遮挡
# 数据区（移到轴外右上）；③ 双轴折线标注离锚点过远/柱被压缩（按锚点统一
# 像素偏移重排）；④ 刻度重合（复用 _fix_xtick_overlap）。chart_qc.py 的
# G8-RENDER 门控用同一函数渲染后校验，保证「保存的 PNG」与「门控校验的图」
# 一致。数值型短标注（如 "1,234" / "56.2%" / "7.06x"）才被当作数据标注；
# 标题/轴外注释/白字（柱内）标注不参与重排。
LABEL_PAD_PX = 7.0          # 数据标注相对锚点的统一像素偏移（修复目标）
MAX_LABEL_DIST_PX = 22.0    # 超过该像素距离 → 判定“标注离点过远”并重排
LEGEND_OVERLAP_RATIO = 0.18  # 图例与数据区重叠比例阈值（超过 → 移出数据区）
_VALUE_LABEL_RE = re.compile(r"^[-+]?[\d,.]{1,}(?:%|x)?$")

def _num_x(ax, v):
    """把轴上的 x 值转成数值坐标：日期（datetime/Timestamp/datetime64）→ matplotlib
    日期数值；数值直接转；字符串分类轴映射为类别序号（经 xtick 标签查找）；
    无法转换返回 None。"""
    from datetime import datetime, date
    if isinstance(v, (datetime, date)) or type(v).__name__ in ("Timestamp", "datetime64"):
        try:
            import matplotlib.dates as mdates
            f = float(mdates.date2num(v))
            return f if np.isfinite(f) else None
        except Exception:
            pass
    try:
        f = float(v)
        return f if np.isfinite(f) else None
    except Exception:
        pass
    try:
        positions = ax.get_xticks()
        labels = [t.get_text() for t in ax.get_xticklabels()]
        for pos, lab in zip(positions, labels):
            if lab == str(v):
                return float(pos)
    except Exception:
        pass
    return None


def _value_texts(ax) -> list:
    """数据坐标（transData）且内容为数值型短标注的 text 列表。"""
    out = []
    for t in ax.texts:
        try:
            if t.get_transform() != ax.transData:
                continue
        except Exception:
            continue
        s = t.get_text().strip()
        if not s:
            continue
        if re.fullmatch(_VALUE_LABEL_RE, s):
            out.append(t)
    return out

def _data_anchor(ax, x_data, y_target, renderer):
    """同一 x 数据坐标下最近的线/柱锚点（数据坐标），返回 (x, y) 或 None。
    同 x 存在多序列（如三情景预测折线同列）时，按 y 距离择优——避免标注重排
    挂错序列（2026-08-18 图12 标注重合校准）。"""
    best, best_d, best_dy = None, None, None
    yt = float(y_target) if y_target is not None else None
    for ln in ax.lines:
        xd, yd = ln.get_xdata(), ln.get_ydata()
        for xx, yy in zip(xd, yd):
            nx = _num_x(ax, xx)
            if nx is None:
                continue
            try:
                ny = float(yy)
                if not np.isfinite(ny):
                    continue
            except (TypeError, ValueError):
                continue
            d = abs(nx - float(x_data))
            dy = abs(ny - yt) if yt is not None else 0.0
            if (best_d is None or d < best_d - 1e-9
                    or (abs(d - best_d) < 1e-9 and dy < best_dy)):
                best_d, best_dy, best = d, dy, (nx, ny)
    for pch in ax.patches:
        try:
            bx = pch.get_x() + pch.get_width() / 2
            by = pch.get_y() + pch.get_height()
        except Exception:
            continue
        d = abs(float(bx) - float(x_data))
        dy = abs(float(by) - yt) if yt is not None else 0.0
        if (best_d is None or d < best_d - 1e-9
                or (abs(d - best_d) < 1e-9 and dy < best_dy)):
            best_d, best_dy, best = d, dy, (float(bx), float(by))
    if best is not None and best_d < 0.75:
        return best
    return None



def _data_window_bbox(ax, renderer):
    """所有线数据点 + 柱角点的窗口包围盒；无数据返回 None。"""
    pts = []
    for ln in ax.lines:
        xd, yd = ln.get_xdata(), ln.get_ydata()
        for xx, yy in zip(xd, yd):
            nx = _num_x(ax, xx)
            if nx is None:
                continue
            try:
                ny = float(yy)
                if not np.isfinite(ny):
                    continue
            except (TypeError, ValueError):
                continue
            pts.append(ax.transData.transform((nx, ny)))
    for pch in ax.patches:
        try:
            for c in pch.get_bbox().corners():
                pts.append(ax.transData.transform(c))
        except Exception:
            pass
    if not pts:
        return None
    xs = [pt[0] for pt in pts]; ys = [pt[1] for pt in pts]
    from matplotlib.transforms import Bbox
    return Bbox.from_extents(min(xs), min(ys), max(xs), max(ys))

def _bb_overlap_ratio(a, b) -> float:
    """a 与 b 的交集面积 / a 面积。"""
    ix = max(0.0, min(a.x1, b.x1) - max(a.x0, b.x0))
    iy = max(0.0, min(a.y1, b.y1) - max(a.y0, b.y0))
    inter = ix * iy
    return inter / max(a.width * a.height, 1e-9)


def _text_bbox_overlap(a, b) -> bool:
    """两个窗口 bbox 是否重叠（用于标注防碰撞）。"""
    ix = min(a.x1, b.x1) - max(a.x0, b.x0)
    iy = min(a.y1, b.y1) - max(a.y0, b.y0)
    return ix > 0 and iy > 0

def _layout_legend_top(fig):
    """One horizontal legend row above the original axes, never a wide right gutter."""
    if getattr(fig, '_legend_top', False) or len(fig.axes) > 2:
        return
    legends = [ax.get_legend() for ax in fig.axes if ax.get_legend() is not None] + list(fig.legends)
    if not legends:
        return
    handles, labels = [], []
    for ax in fig.axes:
        hh, ll = ax.get_legend_handles_labels()
        for h, lab in zip(hh, ll):
            if lab not in labels and not lab.startswith('_'):
                handles.append(h); labels.append(lab)
    if not handles:
        return
    for legend in legends:
        legend.remove()
    title = fig.axes[0].get_title()
    if title:
        fig.axes[0].set_title('')
        fig.suptitle(title, fontsize=13, fontweight='bold', y=.99)
    fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(.5,.94),
               ncol=min(4,len(labels)), frameon=False, fontsize=9,
               columnspacing=1.5, handlelength=2)
    fig.subplots_adjust(left=.10, right=.92, bottom=.23, top=.80)
    fig._legend_top = True


def _resolve_value_collisions(fig):
    """Resolve value/name/comment collisions in their own coordinate systems."""
    fig.canvas.draw()
    for ax in fig.axes:
        texts=[t for t in ax.texts if t.get_visible() and t.get_text().strip()]
        for _ in range(8):
            renderer=fig.canvas.get_renderer(); moved=False
            for i,first in enumerate(texts):
                for second in texts[i+1:]:
                    a,b=first.get_window_extent(renderer),second.get_window_extent(renderer)
                    if not _text_bbox_overlap(a,b):
                        continue
                    chosen=first if a.y0>=b.y0 else second
                    bb=chosen.get_window_extent(renderer)
                    other=b if chosen is first else a
                    bounds=ax.get_window_extent(renderer)
                    shift=other.y1-bb.y0+4
                    if bb.y1+shift>bounds.y1-2:
                        shift=other.y0-bb.y1-4
                    if bb.y0+shift<bounds.y0+2:
                        continue
                    transform=chosen.get_transform()
                    px=transform.transform(chosen.get_position())
                    chosen.set_position(transform.inverted().transform((px[0],px[1]+shift)))
                    fig.canvas.draw(); renderer=fig.canvas.get_renderer()
                    moved=True
            if not moved:
                break
            fig.canvas.draw()


def _auto_fix_layout(fig, max_tries: int = 4):
    """G8-RENDER 自适应绘制后处理（2026-08-18）：在 save() 前调用。

    ① 数据标注越界：数值型数据标注超出坐标区 → 按 span 的 8% 扩展 ylim/xlim
       容纳（循环至多 max_tries 次）；② 数据标注离锚点过远（> MAX_LABEL_DIST_PX）
       → 重排到锚点上方 LABEL_PAD_PX 像素；③ 图例与数据区重叠比例 >
       LEGEND_OVERLAP_RATIO → 移到轴外右上（bbox_to_anchor=(1.02,1.0)）；
       ④ 刻度重合 → 复用 _fix_xtick_overlap。返回 fig（幂等，可重复调用）。
    """
    if getattr(fig, '_year_grouped', False):
        from financial_history_charts import layout_history
        layout_history(fig)
        return fig
    _layout_legend_top(fig)
    _fix_xtick_overlap(fig)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for ax in fig.axes:
        # ① 标注越界 → 扩展坐标范围（全部 transData 文本，防标题/门槛/脚注被裁剪）
        for t in ax.texts:
            # pie() creates empty category labels beyond the outer radius.
            # Empty/invisible labels must not expand limits and displace the
            # percentage labels already anchored in axes coordinates.
            if not t.get_visible() or not t.get_text().strip():
                continue
            try:
                if t.get_transform() != ax.transData:
                    continue
            except Exception:
                continue
            for _ in range(max_tries):
                tb = t.get_window_extent(renderer)
                ab = ax.get_window_extent(renderer)
                y0, y1 = ax.get_ylim()
                x0, x1 = ax.get_xlim()
                span_y = max(y1 - y0, 1e-9); span_x = max(x1 - x0, 1e-9)
                moved = False
                if tb.y1 > ab.y1 + 1:
                    ax.set_ylim(y0, y1 + span_y * 0.08); moved = True
                if tb.y0 < ab.y0 - 1:
                    ax.set_ylim(y0 - span_y * 0.08, y1); moved = True
                if tb.x1 > ab.x1 + 1:
                    ax.set_xlim(x0, x1 + span_x * 0.08); moved = True
                if tb.x0 < ab.x0 - 1:
                    ax.set_xlim(x0 - span_x * 0.08, x1); moved = True
                if not moved:
                    break
                fig.canvas.draw()
                renderer = fig.canvas.get_renderer()
        # ② 标注离锚点过远 → 按原方向（上/下）统一像素偏移重排 + 防与其他标注重叠
        for t in _value_texts(ax):
            try:
                xd, yd = t.get_position()
            except Exception:
                continue
            anchor = _data_anchor(ax, xd, yd, renderer)
            if anchor is None:
                continue
            ap = ax.transData.transform(anchor)
            tb = t.get_window_extent(renderer)
            dist = abs(tb.y0 - ap[1])
            if dist <= MAX_LABEL_DIST_PX:
                continue
            below = (tb.y0 + tb.height / 2) < ap[1]   # 原方向：中心在锚点下方
            off = -LABEL_PAD_PX if below else LABEL_PAD_PX
            for _k in range(8):
                y_data = ax.transData.inverted().transform((ap[0], ap[1] + off))[1]
                t.set_position((anchor[0], y_data))
                fig.canvas.draw()
                renderer = fig.canvas.get_renderer()
                tb2 = t.get_window_extent(renderer)
                hit = False
                for other in _value_texts(ax):
                    if other is t:
                        continue
                    ob = other.get_window_extent(renderer)
                    if _text_bbox_overlap(tb2, ob):
                        hit = True
                        break
                if not hit:
                    break
                off += -12.0 if below else 12.0

        # ③ 图例遮挡数据区 → 移到轴外右上
        leg = ax.get_legend()
        if leg is not None:
            lb = leg.get_window_extent(renderer)
            db = _data_window_bbox(ax, renderer)
            if db is not None and _bb_overlap_ratio(lb, db) > LEGEND_OVERLAP_RATIO:
                leg.set_bbox_to_anchor((1.02, 1.0))
                leg.set_loc("upper left")
                fig.canvas.draw()
                renderer = fig.canvas.get_renderer()
    _resolve_value_collisions(fig)
    from financial_history_charts import layout_native
    layout_native(fig)
    return fig


def _close(df: pd.DataFrame) -> str | None:
    return _col(df, "close", "收盘", "收盘价")

def _date(df: pd.DataFrame) -> str | None:
    return _col(df, "date", "日期", "trade_date")

# ═══════════════ 图01-02：CSV自动（无需ops） ═══════════════

@latest_chart("图01")
def fig_revenue(pl_y: pd.DataFrame) -> plt.Figure | None:
    pl_y = pl_y if '_chart_label' in pl_y else pl_y.tail(12)
    rev_col = _col(pl_y, "OPERATE_INCOME", "营业总收入")
    np_col = _col(pl_y, "PARENT_NETPROFIT", "归母净利")
    if not rev_col:
        return None
    rev = [e8(r.get(rev_col)) for _, r in pl_y.iterrows()]
    np_ = [e8(r.get(np_col)) for _, r in pl_y.iterrows()] if np_col else []
    labels = [r.get('_chart_label', r["REPORT_DATE"].strftime("%Y")) for _, r in pl_y.iterrows()]
    rev = [v if v is not None else np.nan for v in rev]
    np_ = [v if v is not None else np.nan for v in np_]
    fig, ax1 = plt.subplots(figsize=(10, 5.5))
    ax1.bar(labels, rev, color="#4C72B0", alpha=0.85, label="营业总收入（亿元）", width=0.55)
    ax1.set_ylabel("营业总收入（亿元）", color="#4C72B0", fontsize=11)
    for i, v in enumerate(rev):
        if np.isnan(v):
            continue
        ax1.text(i, v + np.nanmax(rev)*0.012, f"{format_number(v)}", ha="center", fontsize=8.5, color="#4C72B0")
    ax2 = ax1.twinx()
    if np_:
        ax2.plot(labels, np_, marker="o", color="#C44E52", lw=2.5, markersize=7, label="归母净利（亿元）")
        ax2.set_ylabel("归母净利（亿元）", color="#C44E52", fontsize=11)
        for i, v in enumerate(np_):
            if np.isnan(v):
                continue
            ax2.text(i, v + np.nanmax(np_)*0.025, f"{format_number(v)}", ha="center", fontsize=8.5, color="#C44E52")
    ax1.set_title("图01 营业总收入与归母净利（历史及最新实际） → §4 财务分析", fontsize=13, fontweight="bold")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)
    ax1.set_xlabel(f"年份 ｜ {SRC}", fontsize=8)
    return fig


@latest_chart("图02")
def fig_roe_bps(fi_y: pd.DataFrame) -> plt.Figure | None:
    fi_y = fi_y if '_chart_label' in fi_y else fi_y.tail(12)
    if not fi_y.columns.intersection(["ROEJQ", "ROE", "BPS"]).size:
        return None
    labels = [r.get('_chart_label', r["REPORT_DATE"].strftime("%Y")) for _, r in fi_y.iterrows()]
    roe_col = _col(fi_y, "ROEJQ", "ROE")
    bps_col = _col(fi_y, "BPS")
    roe_vals = [num(r.get(roe_col)) for _, r in fi_y.iterrows()] if roe_col else []
    bps_vals = [num(r.get(bps_col)) for _, r in fi_y.iterrows()] if bps_col else []
    roe_vals = [v if v is not None else np.nan for v in roe_vals]
    bps_vals = [v if v is not None else np.nan for v in bps_vals]
    fig, ax1 = plt.subplots(figsize=(10, 5.5))
    if roe_vals:
        ax1.bar(labels, roe_vals, color="#55A868", alpha=0.85, label="ROE（%）", width=0.55)
        ax1.set_ylabel("ROE（%）", color="#55A868", fontsize=11)
        for i, v in enumerate(roe_vals):
            if not np.isnan(v):
                ax1.text(i, v + _dy(roe_vals), f"{format_number(v)}%", ha="center", fontsize=9, color="#55A868")
    ax2 = ax1.twinx()
    if bps_vals:
        ax2.plot(labels, bps_vals, marker="s", color="#4C72B0", lw=2.5, markersize=7, label="BPS（元）")
        ax2.set_ylabel("BPS（元）", color="#4C72B0", fontsize=11)
    ax1.set_title("图02 ROE 与每股净资产（历史及最新实际） → §4 财务分析", fontsize=13, fontweight="bold")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)
    ax1.set_xlabel(f"年份 ｜ {SRC}", fontsize=8)
    return fig


# ═══════════════ 图03-15：运营数据（--ops JSON） ═══════════════

def fig_segment(ops: dict) -> plt.Figure | None:
    """图03 分部营收构成 → 环形饼图（≥3 年并列），图例置于图上方。

    2026-08-19 顺丰控股批次校准：原堆叠柱状图+宽图例（右侧/顶部多列）挤占绘图区，
    且子图 set_title 会伸入顶部图例区域 → 一律改为环形饼图：
      ① 每一年一张环形饼图并列（labels 建议 ≥3 年，一年一张）；
      ② 图例统一放图上方：fig.legend(loc="upper center", bbox_to_anchor=(0.5, 0.915), ncol=N, frameon=False)；
      ③ 年份+营收总额放环形图中心（ax.text(0.5,0.5, transAxes)），禁止 axes.set_title（子图标题与顶部图例重叠）；
      ④ 百分比标注在环内，<3.5% 小分段不标注（数值见报告分部表）；
      ⑤ 三段式布局：图题(最上) → 图例(其下) → 环形图(再下)，subplots_adjust(top=0.86, bottom=0.07)。
    兼容原 segment 契约（labels/series[].values），增速/注保留在 ops 供报告引用。
    """
    d = ops.get("segment")
    if not d or not d.get("series"):
        return None
    labels, series = d.get("labels"), d.get("series")
    if not labels or not series:
        p("[SKIP] 图03 segment 缺少 labels/series（请补 input/运营补充数据.json）")
        return None
    colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8B5CF6", "#F59E0B", "#7F7F7F"]
    names = [s["name"] for s in series]
    n = len(labels)
    rows = 2 if n > 3 else 1
    cols = math.ceil(n / rows)
    fig, axes = plt.subplots(rows, cols, figsize=(5.6 * cols, 5.6 * rows))
    axes = np.atleast_1d(axes).ravel()
    for ax in axes[n:]:
        ax.set_visible(False)
    handles = None
    for i, lab in enumerate(labels):
        vals = [float(series[k]["values"][i]) for k in range(len(series))]
        total = sum(vals)
        wedges, categorytexts, autotexts = axes[i].pie(
            vals, colors=colors, startangle=90, counterclock=False,
            autopct=lambda pv: (f"{format_number(pv)}%" if pv >= 3.5 else ""),
            pctdistance=0.80,
            wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1.5),
            textprops=dict(fontsize=8))
        for label in [*categorytexts, *autotexts]:
            if not label.get_text().strip():
                label.remove()
        radius=max(w.r for w in wedges)
        axes[i].set_xlim(-1.03*radius,1.03*radius)
        axes[i].set_ylim(-1.03*radius,1.03*radius)
        for at in autotexts:
            if at.get_text():
                at.set_color("white")
                at.set_fontsize(7.5)
                at.set_fontweight("bold")
                # 转换到 transAxes，避免被 G8-RENDER 当作 transData 数值标注重排（饼图坐标特殊）
                xd, yd = at.get_position()
                xl, yl = axes[i].get_xlim(), axes[i].get_ylim()
                xf = (xd - xl[0]) / (xl[1] - xl[0])
                yf = (yd - yl[0]) / (yl[1] - yl[0])
                at.set_position((xf, yf))
                at.set_transform(axes[i].transAxes)
        # 年份+营收放环形图中心（原 set_title 位于 axes 上方，会与顶部图例重叠）
        axes[i].text(0.5, 0.5, f"{lab}\n{format_number(total)} 亿", ha="center", va="center",
                     transform=axes[i].transAxes, fontsize=11.5, fontweight="bold", color="#333333")
        axes[i].set_aspect("equal")
        if handles is None:
            handles = wedges
    # 三段式布局：图题(最上) → 图例(其下) → 环形图(再下)，避免图例与图题重叠
    fig.suptitle(_section_title(d.get("标题"), "图03 分部营收构成", "§3 公司分析"),
                 fontsize=13, fontweight="bold", y=0.985)
    fig.legend(handles, names, loc="upper center", bbox_to_anchor=(0.5, 0.915),
               ncol=len(names), fontsize=9, frameon=False,
               handlelength=1.1, columnspacing=1.6, handletextpad=0.8,
               borderaxespad=0.0)
    fig.subplots_adjust(top=0.86, bottom=0.07, left=0.02, right=0.98, wspace=0.08)
    note = d.get("注", "")
    if note:
        fig.text(0.5, 0.005, f"注：{note} ｜ {SRC}", ha="center", fontsize=8, color="gray")
    return fig


def load_industry_cost_price(data_dir: Path) -> dict | None:
    """读取标准化行业成本—价格序列，并转换为图16所需结构。"""
    path = data_dir / "行业成本价格.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, dtype=str)
        required = {"date", "series", "value", "unit", "role", "source", "source_date"}
        if not required.issubset(df.columns):
            return None
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["date", "value", "series"])
        if df.empty:
            return None
        labels = sorted(df["date"].dt.strftime("%Y-%m-%d").unique())
        series = []
        for name, sub in df.groupby("series", sort=True):
            lookup = {d.strftime("%Y-%m-%d"): float(v) for d, v in zip(sub["date"], sub["value"])}
            first = next((v for v in lookup.values() if v > 0), None)
            if not first:
                continue
            row = sub.iloc[0]
            role = str(row.get("role", ""))
            series.append({
                "name": str(name), "role": role, "unit": str(row.get("unit", "")),
                "values": [round(lookup.get(d, np.nan) / first * 100, 4) for d in labels],
                "raw_values": [lookup.get(d, np.nan) for d in labels],
                "source": str(row.get("source", "")), "source_date": str(row.get("source_date", "")),
            })
        if not series:
            return None
        return {"labels": labels, "series": series,
                "标题": "图16 行业成本与价格走势与供需",
                "注": "成本/价格按原始值双轴展示（左=成本单位，右=价格单位）；volume 供需序列按下方面板；价差/手算序列须标注口径"}
    except Exception as exc:
        p(f"[WARN] 行业成本—价格数据读取失败: {exc}")
        return None


def fig_industry_cost_price(ops: dict, data_dir: Path) -> plt.Figure | None:
    """图16 v4：供需面板 + 成本/价格原始值双轴 + 价差示意（无断点、刻度不重合、
    来源标注正确）。

    v3（2026-08-17，伊利反馈校准）：①每序列只画自身观测点（独立数值日期 x），
    不再共享全部 labels 导致跨序列日期 NaN 断线；②x 轴数值日期 + 稀疏刻度
    （≤10 个），解决底部横坐标文字重合；③volume 柱宽按频率换算天数。
    v4（2026-08-17，标注修正）：①x 轴来源标注按序列真实数据源（农业农村部/
    中国价格信息网/国家统计局等），不再套用“东财/公司公告/行情源”；②margin
    图例显式标注“手算/补充”；③刻度只从折线序列（cost/price/margin）观测日期
    抽样，避免 volume 年度日期刻度误导折线位置；④x 轴左边界预留柱宽。
    仍保留 v2 要点：raw_values 原始值双轴（左=成本，右=价格/价差）、
    价差虚线标“手算/补充”、不用“首期=100”指数化压平价格曲线。
    """
    d = ops.get("industry_cost_price") or load_industry_cost_price(data_dir)
    if not d or not d.get("series") or len(d.get("labels", [])) < 3:
        return None
    labels = d["labels"]
    roles = [s.get("role", "") for s in d["series"]]
    has_volume = "volume" in roles
    if has_volume:
        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(11, 7.2), sharex=True,
            gridspec_kw={"height_ratios": [2.2, 1], "hspace": 0.12})
    else:
        fig, ax1 = plt.subplots(figsize=(11, 5.8))
    colors = {"cost": "#C44E52", "price": "#4C72B0", "volume": "#55A868", "margin": "#8B5CF6"}
    all_dt = []
    for lab in labels:
        dt = pd.to_datetime(lab, errors="coerce")
        if not pd.isna(dt):
            all_dt.append(dt)
    all_dt = sorted(set(all_dt))
    line_dates = set()
    ax_price = None
    for s in d["series"]:
        role = s.get("role", "")
        vals = np.array(s.get("raw_values") or s["values"], dtype=float)
        xs, ys = _series_xy(labels, vals)
        if len(xs) == 0:
            continue
        if role != "volume":
            for i, v in enumerate(vals):
                if v != v:
                    continue
                dt = pd.to_datetime(labels[i], errors="coerce")
                if not pd.isna(dt):
                    line_dates.add(dt)
        if role == "volume":
            ax2.bar(xs, ys, color=colors["volume"], alpha=0.75,
                    width=_volume_bar_width(str(s.get("frequency", ""))),
                    label=f"{s['name']}（{s.get('unit','')}）")
            ax2.set_ylabel(f"{s.get('unit','')}", fontsize=9)
            continue
        if role in ("price", "margin"):
            if ax_price is None:
                ax_price = ax1.twinx()
            kwargs = {"marker": "o", "lw": 2.4, "markersize": 6} if role == "price" \
                else {"ls": "--", "lw": 1.8, "marker": "s", "markersize": 4}
            label = f"{s['name']}（手算/补充，{s.get('unit','')}）" if role == "margin" \
                else f"{s['name']}（{s.get('unit','')}）"
            ax_price.plot(xs, ys, color=colors[role],
                          label=label, **kwargs)
            continue
        ax1.plot(xs, ys, marker="o", lw=2.4, markersize=6,
                 color=colors.get(role, "#DD8452"),
                 label=f"{s['name']}（{s.get('unit','')}）")
    if not all_dt:
        return None
    vbar_w = 0.0
    for s in d["series"]:
        if s.get("role") == "volume":
            vbar_w = _volume_bar_width(str(s.get("frequency", "")))
            break
    xmin = mdates.date2num(min(all_dt)) - max(15.0, vbar_w / 2 + 5)
    xmax = mdates.date2num(max(all_dt)) + 15
    for ax in fig.axes:
        ax.set_xlim(xmin, xmax)
    ticks = _pick_even_ticks(sorted(line_dates)) if line_dates else _pick_even_ticks(all_dt)
    tick_ax = ax2 if has_volume else ax1
    tick_ax.set_xticks([mdates.date2num(t) for t in ticks])
    tick_ax.set_xticklabels([t.strftime("%Y-%m") for t in ticks],
                            rotation=25 if len(ticks) >= 6 else 0, ha="right", fontsize=8)
    for ax in fig.axes:
        if ax is not tick_ax:
            ax.tick_params(labelbottom=False)
    ax1.set_ylabel("成本（原始值）", fontsize=10)
    if ax_price is not None:
        ax_price.set_ylabel("价格 / 价差（原始值）", fontsize=10)
    ax1.set_title(_section_title(d.get("标题"), "图16 行业成本与价格走势与供需", "§2 宏观与行业"),
                  fontsize=13, fontweight="bold")
    srcs = sorted({str(s.get("source", "")).strip() for s in d["series"] if s.get("source")})
    src_txt = "、".join(srcs) if srcs else SRC
    ax1.set_xlabel(f"观测日期 ｜ 数据：{src_txt} ｜ 数据截至 {max(all_dt).strftime('%Y-%m')}",
                   fontsize=8)
    h1, l1 = ax1.get_legend_handles_labels()
    if ax_price is not None:
        h2, l2 = ax_price.get_legend_handles_labels()
        ax1.legend(h1 + h2, l1 + l2, fontsize=8, loc="best", frameon=False)
        _apply_clean_twin_style(ax_price, pad=7, labelpad=10)
    else:
        ax1.legend(fontsize=8.5, loc="best", frameon=False)
    _apply_clean_chart_style(ax1, grid_axis="both", pad=7, labelpad=10)
    if has_volume:
        ax2.legend(fontsize=8, loc="upper left", frameon=False)
        _apply_clean_chart_style(ax2, grid_axis="y", pad=7, labelpad=10)
    if d.get("注"):
        fig.text(0.5, -0.01, d["注"], ha="center", fontsize=8, color="gray")
    return fig


def _series_xy(labels, vals):
    """图16 辅助：只取该序列自身观测点（数值日期 x），避免跨序列日期 NaN 断点。"""
    xs, ys = [], []
    for i, v in enumerate(vals):
        if v != v:
            continue
        dt = pd.to_datetime(labels[i], errors="coerce")
        if pd.isna(dt):
            continue
        xs.append(mdates.date2num(dt.to_pydatetime()))
        ys.append(float(v))
    return np.array(xs), np.array(ys)


def _volume_bar_width(freq: str) -> float:
    """图16 辅助：volume 柱宽按频率换算为天数（数值日期轴）。"""
    f = (freq or "").lower()
    if "annual" in f or "year" in f:
        return 365 * 0.75
    if "quarter" in f:
        return 92 * 0.75
    if "week" in f:
        return 7 * 0.75
    return 30 * 0.75


def _pick_even_ticks(all_dt, max_ticks: int = 8):
    """图16 辅助：按时间等距抽样 ≤max_ticks 个观测日期作为刻度，并强制相邻刻度最小间隔，
    避免横坐标文字重合（2026-08-23 中远海控批次：月度观测 2026-04/06/08 过密触发 G8 失败）。"""
    if len(all_dt) <= 1:
        return sorted(all_dt)
    t0, t1 = mdates.date2num(min(all_dt)), mdates.date2num(max(all_dt))
    span = t1 - t0
    step = span / max_ticks if span > 0 else 1.0
    min_gap = max(step * 0.5, 1.0)
    picked = []
    for dt in sorted(all_dt):
        if not picked or (mdates.date2num(dt) - mdates.date2num(picked[-1])) >= min_gap:
            picked.append(dt)
    if len(picked) > max_ticks:
        idx = sorted({int(i * (len(picked) - 1) / (max_ticks - 1)) for i in range(max_ticks)})
        picked = [picked[i] for i in idx]
    return picked

@latest_chart("图04")
def fig_profitability(ops: dict) -> plt.Figure | None:
    d = ops.get("profitability")
    if not d:
        return None
    labels = d["labels"]
    fig, ax1 = plt.subplots(figsize=(10.5, 5.8))
    x = range(len(labels))
    gross_label = d.get("毛利率名称", "毛利率（%）")
    net_label = d.get("净利率名称", "净利率（%）")
    profit_series = [d["毛利率"], d["净利率"]]
    ax1.plot(x, d["毛利率"], marker="o", color="#4C72B0", lw=2.4, markersize=6.5, label=gross_label)
    ax1.plot(x, d["净利率"], marker="s", color="#55A868", lw=2.4, markersize=6.5, label=net_label)
    for i, v in enumerate(d["毛利率"]):
        if v is not None and np.isfinite(v):
            ax1.text(i, v + 0.45, f"{format_number(v)}%", ha="center", fontsize=8.5, color="#4C72B0")
    for i, v in enumerate(d["净利率"]):
        if v is not None and np.isfinite(v):
            ax1.text(i, v - 1.15, f"{format_number(v)}%", ha="center", fontsize=8.5, color="#55A868")
    finite_profit = [float(v) for series in profit_series for v in series if v is not None and np.isfinite(v)]
    if finite_profit:
        p_lo, p_hi = min(finite_profit), max(finite_profit)
        p_span = max(p_hi - p_lo, 1.0)
        ax1.set_ylim(p_lo - p_span * 0.15, p_hi + p_span * 0.20)
    ax1.set_ylabel(d.get("利润率轴名称", "比例（%）"), fontsize=11, labelpad=10)
    ax2 = ax1.twinx()
    ax2.bar(x, d["ROE"], color="#DD8452", alpha=0.55, width=0.42, label=d.get('ROE名称', 'ROE（%）'))
    for i, v in enumerate(d["ROE"]):
        if v is not None and np.isfinite(v):
            ax2.text(i, v + _dy(d["ROE"]), f"{format_number(v)}%", ha="center", fontsize=8.5, color="#DD8452")
    finite_roe = [float(v) for v in d["ROE"] if v is not None and np.isfinite(v)]
    if finite_roe:
        r_lo, r_hi = min(0.0, min(finite_roe)), max(finite_roe)
        r_span = max(r_hi - r_lo, 1.0)
        ax2.set_ylim(r_lo - r_span * 0.08, r_hi + r_span * 0.25)
    ax2.set_ylabel(d.get("ROE轴名称", "ROE（%）"), color="#DD8452", fontsize=11, labelpad=10)
    ax1.set_xticks(list(x)); ax1.set_xticklabels(labels)
    ax1.set_title(_section_title(d.get("标题"), "图04 盈利能力趋势", "§4 财务分析"), fontsize=13, fontweight="bold", pad=12)
    _apply_clean_chart_style(ax1, grid_axis="y", pad=7, labelpad=10)
    _apply_clean_twin_style(ax2, pad=7, labelpad=10)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=9, frameon=False)
    fig.subplots_adjust(bottom=0.18)
    ax1.set_xlabel(f"年份 ｜ {SRC}", fontsize=8)
    return fig


@latest_chart("图05")
def fig_cashflow(ops: dict) -> plt.Figure | None:
    d = ops.get("cashflow")
    if not d:
        return None
    need = ["labels", "OCF", "Capex", "FCF"]
    missing = [k for k in need if k not in d]
    if missing:
        p(f"[SKIP] 图05 cashflow 缺少必需键 {missing}（请补 input/运营补充数据.json 或标注不适用）")
        return None
    labels = d["labels"]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(labels)); w = 0.35
    ax.bar(x - w/2, d["OCF"], w, color="#55A868", alpha=0.88, label="经营现金流 OCF（亿元）")
    ax.bar(x + w/2, d["Capex"], w, color="#C44E52", alpha=0.88, label="资本开支 Capex（亿元）")
    ax2 = ax.twinx()
    ax2.plot(x, d["FCF"], marker="D", color="#4C72B0", lw=2.5, markersize=8, label="自由现金流 FCF（亿元）")
    for i, v in enumerate(d["FCF"]):
        if v is not None and np.isfinite(v):
            ax2.text(i, v + max(d["FCF"])*0.05, f"{format_number(v)}", ha="center", fontsize=9, color="#4C72B0", fontweight="bold")
    if d.get("D_A"):
        ax2.plot(x, d["D_A"], marker="^", color="#8B5CF6", lw=1.8, markersize=6, ls="--", label="折旧摊销 D&A（亿元）")
    ax.set_xticks(list(x)); ax.set_xticklabels(labels)
    ax.set_ylabel("金额（亿元）", fontsize=11)
    ax.set_title(_section_title(d.get("标题"), "图05 现金流结构", "§4 财务分析"), fontsize=13, fontweight="bold")
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)
    ax.set_xlabel(f"年份 ｜ {SRC}", fontsize=8)
    return fig



def _fill_peer_growth(peers: list[dict]) -> list[dict]:
    """图06 增速面板兜底：ops 缺营收增速/净利增速时，从 data/同行_财务指标汇总.csv 按公司/代码补齐
    （fetch_peers_financials.py v3 起输出营收增速%/净利增速% 列）。返回新列表，不修改入参。"""
    out = [dict(p) for p in peers]
    if all(isinstance(p.get("营收增速"), (int, float)) and isinstance(p.get("净利增速"), (int, float)) for p in out):
        return out
    csvp = Path(__file__).resolve().parents[1] / "data" / "同行_财务指标汇总.csv"
    if not csvp.exists():
        return out
    try:
        df = pd.read_csv(csvp, encoding="utf-8-sig")
    except Exception:
        return out
    by_name, by_code = {}, {}
    for _, r in df.iterrows():
        nm = str(r.get("公司", "")).strip()
        cd = str(r.get("代码", "")).strip()
        if nm:
            by_name[nm] = r
        if cd:
            by_code[cd] = r
    for p in out:
        if p.get("增长可比") is False:
            continue
        if isinstance(p.get("营收增速"), (int, float)) and isinstance(p.get("净利增速"), (int, float)):
            continue
        r = by_name.get(str(p.get("公司", "")).strip())
        if r is None:
            r = by_code.get(str(p.get("代码", "")).strip())
        if r is None:
            continue
        for key, col in (("营收增速", "营收增速%"), ("净利增速", "净利增速%")):
            if p.get(key) is not None:
                continue
            v = r.get(col)
            try:
                if v is not None and str(v).strip() not in ("", "nan", "None"):
                    p[key] = float(v)
            except (TypeError, ValueError):
                continue
    return out


def fig_peers(ops: dict) -> plt.Figure | None:
    """同行估值与增长对比（含性价比分界线与3年均速/近1年改善走势）。

    左面板估值维度：PE vs ROE（或自动降级 PB vs ROE），含斜线连接左下至右上划分高/低性价比区。
    右面板：3年平均增速基准 + 箭头指向近1年改善走势。
    """
    peers = ops.get("peers")
    if not peers:
        return None
    peers = _fill_peer_growth(peers)  # 增速面板兜底：从同行 CSV 自动补齐营收/净利增速
    period_review = ops.get("peers_period", {}).get("period_review", {})
    financial_basis = period_review.get("basis", "FY")
    has_3y_val = any(r.get("3年平均PE") is not None and r.get("3年平均ROE") is not None for r in peers)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.8))
    
    if has_3y_val:
        xk = "3年平均PE"
        yk = "3年平均ROE"
        xlab = "近3年平均 PE（倍，2023-2025A）"
        ylab = "近3年平均 ROE（%）"
        ttl = "PE vs ROE（3年平均稳态估值与回报）"
    else:
        pe_rows = [r for r in peers if r.get("PE") is not None and r.get("PE", 0) > 0]
        use_pb = len(pe_rows) < 3
        xk = "PB" if use_pb else "PE"
        yk = "ROE"
        basis = ops.get("peer_valuation_basis")
        xlab = f"{xk}（{basis}）" if basis else ("PB（最近披露权益）" if use_pb else "PE (TTM)")
        ylab = "ROE（%；累计非年化）" if financial_basis != "FY" else "ROE（%）"
        ttl = "PB vs ROE（PE 失真，以 PB 替代）" if use_pb else "PE vs ROE（斜线划分性价比）"
        
    n1 = 0
    for row in peers:
        name, xv, roe = row.get("公司","?"), row.get(xk), row.get(yk)
        if xv is None or roe is None:
            continue
        n1 += 1
        hl = row.get("标的") is True or row.get("target") is True
        ax1.scatter(xv, roe, s=260 if hl else 150, c="#C44E52" if hl else "#4C72B0",
                    zorder=3 if hl else 2, edgecolors="white" if hl else "none", lw=1.5)
        offset1 = tuple(row.get("valuation_offset")) if row.get("valuation_offset") else (8, 6)
        ax1.annotate(name, (xv, roe), textcoords="offset points", xytext=offset1,
                     fontsize=9, fontweight="bold" if hl else "normal", color="#C44E52" if hl else "#1e293b",
                     bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="#e2e8f0", alpha=0.85, lw=0.5))
    ax1.set_xlabel(xlab, fontsize=10.5, labelpad=9); ax1.set_ylabel(ylab, fontsize=10.5, labelpad=9)
    ax1.set_title(ttl, fontsize=12, fontweight="bold", pad=10)
    _apply_clean_chart_style(ax1, grid_axis="both", pad=7, labelpad=9)
    
    # 动态绘制连接左下至右上的“性价比分界线”
    xlim1 = ax1.get_xlim()
    ylim1 = ax1.get_ylim()
    if (xlim1[1] > xlim1[0]) and (ylim1[1] > ylim1[0]):
        x_line = np.linspace(xlim1[0], xlim1[1], 100)
        slope1 = (ylim1[1] - ylim1[0]) / (xlim1[1] - xlim1[0])
        y_line = ylim1[0] + slope1 * (x_line - xlim1[0])
        ax1.plot(x_line, y_line, color="#8B5CF6", ls="--", lw=1.5, alpha=0.75, label="性价比基准线", zorder=1)
        ax1.fill_between(x_line, y_line, ylim1[1], color="#4CAF50", alpha=0.06, zorder=0)
        ax1.set_xlim(xlim1); ax1.set_ylim(ylim1)
        ax1.text(0.06, 0.90, "★ 高性价比区 (低PE · 高ROE)", transform=ax1.transAxes,
                 fontsize=9.5, fontweight="bold", color="#2E7D32",
                 bbox=dict(boxstyle="round,pad=0.35", facecolor="#E8F5E9", edgecolor="#A5D6A7", alpha=0.9, lw=0.8), zorder=4)
        ax1.text(0.55, 0.05, "低性价比区 (高PE · 低ROE)", transform=ax1.transAxes,
                 fontsize=8.5, color="#757575", ha="center",
                 bbox=dict(boxstyle="round,pad=0.3", facecolor="#FAFAFA", edgecolor="#E0E0E0", alpha=0.85, lw=0.6), zorder=4)

    if n1 < 2:
        p(f"[WARN] 图06 左面板（{xk} vs ROE）仅 {n1} 个数据点，同行估值对比意义有限，请在报告中说明")
    
    n2 = 0
    for row in peers:
        name = row.get("公司", "?")
        rg_3y = row.get("营收3年均速", row.get("营收增速"))
        ng_3y = row.get("净利3年均速", row.get("净利增速"))
        rg_1y = row.get("营收增速")
        ng_1y = row.get("净利增速")
        r_imp = row.get("营收近1年改善")
        n_imp = row.get("净利近1年改善")
        if rg_3y is None or ng_3y is None:
            continue
        n2 += 1
        hl = row.get("标的") is True or row.get("target") is True
        # 3年平均基准散点
        ax2.scatter(rg_3y, ng_3y, s=240 if hl else 140, c="#C44E52" if hl else "#4C72B0",
                    zorder=4 if hl else 3, edgecolors="white" if hl else "none", lw=1.5)
        # 近1年走势：若存在1年增速且与3年有差异，绘制走势箭头指向近1年改善位置
        if rg_1y is not None and ng_1y is not None and (abs(rg_1y - rg_3y) > 0.05 or abs(ng_1y - ng_3y) > 0.05):
            ax2.annotate("", xy=(rg_1y, ng_1y), xytext=(rg_3y, ng_3y),
                         arrowprops=dict(arrowstyle="->", color="#C44E52" if hl else "#5C6BC0", lw=1.2, ls="--", alpha=0.85),
                         zorder=2)
            ax2.scatter(rg_1y, ng_1y, s=45, facecolors="none", edgecolors="#C44E52" if hl else "#5C6BC0",
                        lw=1.2, zorder=3)
        
        offset2 = tuple(row.get("growth_offset")) if row.get("growth_offset") else (8, 6)
        ax2.annotate(name, (rg_3y, ng_3y), textcoords="offset points", xytext=offset2,
                     fontsize=9, fontweight="bold" if hl else "normal", color="#C44E52" if hl else "#1e293b",
                     bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="#e2e8f0", alpha=0.85, lw=0.5))

    ax2.axhline(0, color="gray", ls="--", lw=0.6); ax2.axvline(0, color="gray", ls="--", lw=0.6)
    has_3y = any(r.get("营收3年均速") is not None for r in peers)
    ax2.set_xlabel("营收3年平均增速 / 复合增速（%）" if has_3y else "营收增速（%）", fontsize=10.5, labelpad=9)
    ax2.set_ylabel("归母净利3年平均增速（%）" if has_3y else "归母净利增速（%）", fontsize=10.5, labelpad=9)
    ax2.set_title("增速对比（3年平均基准至近1年走势(箭头)）" if has_3y else "增速对比", fontsize=12, fontweight="bold", pad=10)
    _apply_clean_chart_style(ax2, grid_axis="both", pad=7, labelpad=9)
    if has_3y:
        ax2.plot([], [], marker='o', color='#4C72B0', ls='none', markersize=7, label='3年平均增速基准')
        ax2.plot([], [], marker='o', markerfacecolor='none', markeredgecolor='#4C72B0', ls='--', color='#4C72B0', label='近1年走势 (箭头终点)')
        ax2.legend(loc="lower right", fontsize=8, framealpha=0.85)

    if n2 < 2:
        p(f"[WARN] 图06 右面板（增速对比）仅 {n2} 个数据点，请在报告中说明数据缺失")
    fig.suptitle("图06 同行估值与增长对比 → §6 估值", fontsize=13, fontweight="bold", y=1.01)
    period_note = f"财务统一期 {period_review.get('period_end', '待核')}（{financial_basis}）；{period_review.get('reason', '')}"
    fig.text(0.5, -0.02, textwrap.fill(period_note, width=100) + "\n" + SRC, ha="center", fontsize=8, color="gray")
    return fig


def fig_dps(div: pd.DataFrame | None, ops: dict) -> plt.Figure | None:
    d = ops.get("dps")
    if not d:
        if div is not None and len(div):
            rows = []
            for _, r in div.iterrows():
                rd = str(r.get("报告期", ""))
                if re.match(r"^\d{4}-12-31$", rd[:10]):
                    rows.append((rd[:4], num(r.get("现金分红-现金分红比例"))))
            if rows:
                labels = [a for a,_ in rows]; dps_vals = [v if v is not None else np.nan for _,v in rows]
                payout = None
            else:
                return None
        else:
            return None
    else:
        labels, dps_vals = d["labels"], d["dps"]
        payout = d.get("支付率")
    fig, ax1 = plt.subplots(figsize=(10.5, 5.8))
    x = range(len(labels))
    ax1.bar(x, dps_vals, color="#55A868", alpha=0.85, width=0.45, label="DPS（元）")
    for i, v in enumerate(dps_vals):
            if not np.isnan(v):
                ax1.text(i, v + 0.05, f"{format_number(v)}", ha="center", fontsize=9, fontweight="bold")
    ax1.set_ylabel("DPS（元）", color="#55A868", fontsize=11, labelpad=10)
    if payout:
        ax2 = ax1.twinx()
        ax2.plot(x, payout, marker="o", color="#C44E52", lw=2.4, markersize=6.5, label="支付率（%）")
        for i, v in enumerate(payout):
            if not np.isnan(v):
                ax2.text(i, v + 1.5, f"{format_number(v)}%", ha="center", fontsize=8.5, color="#C44E52")
        finite_payout = [float(v) for v in payout if v is not None and np.isfinite(v)]
        if finite_payout:
            p_lo, p_hi = min(0.0, min(finite_payout)), max(finite_payout)
            p_span = max(p_hi - p_lo, 1.0)
            ax2.set_ylim(p_lo, p_hi + p_span * 0.35)
        else:
            ax2.set_ylim(0, 100)
        ax2.set_ylabel("支付率（%）", color="#C44E52", fontsize=11, labelpad=10)
        _apply_clean_twin_style(ax2, pad=7, labelpad=10)
    _apply_clean_chart_style(ax1, grid_axis="y", pad=7, labelpad=10)
    ax1.set_xticks(list(x)); ax1.set_xticklabels(labels)
    note = d.get("注","") if d else ""
    ax1.set_title("图07 DPS与支付率 → §4 财务分析", fontsize=13, fontweight="bold", pad=12)
    fig.legend(loc="upper left", bbox_to_anchor=(0.13,0.88), fontsize=9, frameon=False)
    ax1.set_xlabel(f"归属财年 ｜ {SRC}", fontsize=8)
    if note:
        fig.text(.5, -.04, textwrap.fill(note, width=90), ha="center", va="top", fontsize=9, color="#555555")
    return fig


def fig_price(data_dir: Path) -> plt.Figure | None:
    df = load_csv(data_dir, "日线股价_前复权.csv")
    if df is None:
        df = load_csv(data_dir, "日线股价.csv")
    if df is None or len(df) < 20:
        return None
    date_c, close_c = _date(df), _close(df)
    if not date_c or not close_c:
        return None
    df[date_c] = pd.to_datetime(df[date_c])
    df = df.sort_values(date_c)
    # Use a common ten-year observation window regardless of provider history length.
    cutoff = df[date_c].max() - pd.DateOffset(years=10)
    df = df[df[date_c] >= cutoff]
    cur = float(df.iloc[-1][close_c])
    pct_rank = (df[close_c] <= cur).mean() * 100
    fig, ax = plt.subplots(figsize=(12, 5.8))
    ax.plot(df[date_c], df[close_c], color="#4C72B0", lw=1.3)
    ax.fill_between(df[date_c], df[close_c], df[close_c].min(), alpha=0.08, color="#4C72B0")
    ax.axhline(cur, color="#C44E52", ls="--", lw=1.5)
    ax.annotate(f"当前 {format_number(cur)} 元（分位 {format_number(pct_rank)}%）",
                xy=(df.iloc[-1][date_c], cur), xytext=(-180, 30),
                textcoords="offset points", color="#C44E52", fontsize=10, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="#C44E52", lw=1.5))
    ax.set_title(f"图08 十年股价走势（前复权，当前 {format_number(pct_rank)}% 分位） → §6 估值", fontsize=13, fontweight="bold", pad=12)
    ax.set_ylabel("收盘价（元）", fontsize=11, labelpad=10)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=4))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=8)
    _apply_clean_chart_style(ax, grid_axis="both", pad=7, labelpad=10)
    ax.set_xlabel(f"日期 ｜ {SRC}", fontsize=8)
    return fig


def fig_targets(ops: dict) -> plt.Figure | None:
    d = ops.get("targets")
    if not d or not d.get("labels"):
        return None
    labels, vals = d["labels"], d["values"]
    colors = []
    for lab in labels:
        if "穿透" in lab or "龟龟" in lab: colors.append("#DD8452")
        elif "悲观" in lab: colors.append("#C44E52")
        elif "乐观" in lab: colors.append("#55A868")
        elif "当前" in lab: colors.append("#4C72B0")
        else: colors.append("#8B5CF6")
    fig, ax = plt.subplots(figsize=(12, 5.8))
    ax.bar(labels, vals, color=colors, alpha=0.9, width=0.55)
    for i, v in enumerate(vals):
        label = f"{format_number(v)}"
        ax.text(i, v + (1.2 if v >= 0 else -1.0), label, ha="center",
                va="bottom" if v >= 0 else "top", fontsize=10.5, fontweight="bold", color=colors[i])
    ax.set_ylabel("目标价（元）", fontsize=11, labelpad=10)
    ax.set_title("图09 多框架目标价对比 → §7 投资建议", fontsize=13, fontweight="bold", pad=12)
    _apply_clean_chart_style(ax, grid_axis="y", pad=7, labelpad=10)
    ax.text(0.5, -0.14, d.get("注", SRC), ha="center", fontsize=8, color="gray", transform=ax.transAxes)
    return fig


def fig_penetration(ops: dict) -> plt.Figure | None:
    d = ops.get("penetration")
    if not d or not d.get("labels") or not d.get("gg"):
        return None
    labels, gg = d["labels"], d["gg"]
    ii = d.get("ii", 3.70)
    colors = (["#C44E52", "#55A868", "#DD8452", "#4C72B0"] * (len(gg) // 3 + 1))[:len(gg)]
    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    ax.bar(labels, gg, color=colors, width=0.48)
    finite = [float(v) for v in gg + [ii] if v is not None and np.isfinite(v)]
    lo, hi = min([0.0] + finite), max([0.0] + finite)
    span = max(hi - lo, 1.0)
    label_pad = max(0.25, span * 0.05)
    for i, v in enumerate(gg):
        y = v + label_pad if v >= 0 else v - label_pad
        ax.text(i, y, f"{format_number(v)}%", ha="center", va="bottom" if v >= 0 else "top",
                fontsize=10.5, fontweight="bold", color=colors[i])
    ax.axhline(ii, color="#4C72B0", lw=2.2, ls="--")
    ii_y = ii + label_pad if ii >= 0 else ii - label_pad
    ax.text(len(labels)-0.4, ii_y, f"门槛 II = {format_number(ii)}%", fontsize=10, color="#4C72B0",
            fontweight="bold", va="bottom" if ii >= 0 else "top")
    ax.set_ylabel("穿透回报率（%）", fontsize=11, labelpad=10)
    ax.axhline(0, color="#888888", lw=0.9, alpha=0.55)
    ax.set_ylim(lo - max(label_pad, span * 0.12), hi + max(label_pad, span * 0.18))
    ax.set_title(_section_title(d.get("标题"), "图10 穿透回报率 vs 门槛对比", "§6 估值"), fontsize=13, fontweight="bold", pad=12)
    _apply_clean_chart_style(ax, grid_axis="y", pad=7, labelpad=10)
    ax.text(0.5, -0.14, d.get("注", SRC), ha="center", fontsize=8, color="gray", transform=ax.transAxes)
    return fig


def fig_sensitivity(ops: dict) -> plt.Figure | None:
    d = ops.get("sensitivity")
    if not d or not d.get("系列"):
        return None
    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    colors = ["#C44E52", "#55A868", "#DD8452", "#4C72B0"]
    x = d.get("x", [])
    for i, s in enumerate(d["系列"]):
        y = s.get("y", [])
        ax.plot(x, y, marker="o", color=colors[i%len(colors)], lw=2.4, markersize=7.5, label=s["name"])
        if i == 0:  # 仅标注首系列，防多系列近值标签重叠（G8-RENDER；昊华批次校准）
            for j, (xi, yi) in enumerate(zip(x, y)):
                if yi is not None and np.isfinite(yi):
                    near_above = any(
                        j < len(other.get("y", []))
                        and (other_y := other["y"][j]) is not None
                        and np.isfinite(other_y)
                        and 0 < other_y - yi < 0.25
                        for other in d["系列"][1:]
                    )
                    ax.text(xi, yi - 0.08 if near_above else yi + 0.08,
                            f"{format_number(yi)}%", ha="center", va="top" if near_above else "bottom",
                            fontsize=8, color=colors[i%len(colors)])
    all_y = [float(yy) for ss in d["系列"] for yy in ss.get("y", [])
             if yy is not None and np.isfinite(yy)]
    if d.get("门槛") is not None and np.isfinite(d["门槛"]):
        all_y.append(float(d["门槛"]))
    if all_y:
        lo, hi = min(all_y), max(all_y)
        pad = max((hi - lo) * 0.1, 0.2)
        ax.set_ylim(lo - pad, hi + max(pad, (hi - lo) * 0.2))
    if d.get("门槛") is not None:
        ax.axhline(d["门槛"], color="#4C72B0", lw=2, ls="--")
        spread = max(all_y) - min(all_y) if all_y else 1.0
        ax.text(x[0], d["门槛"] + max(spread * 0.05, 0.1),
                f"门槛 II = {format_number(d['门槛'])}%", fontsize=10, color="#4C72B0", fontweight="bold")
    ax.set_xlabel(d.get("xlabel", "情景因子"), fontsize=11, labelpad=9)
    ax.set_ylabel(d.get("ylabel", "回报率（%）"), fontsize=11, labelpad=9)
    ax.set_title(_section_title(d.get("标题"), "图11 敏感性分析", "§6 估值"), fontsize=13, fontweight="bold", pad=12)
    ax.legend(fontsize=9, loc="upper right", frameon=False)
    _apply_clean_chart_style(ax, grid_axis="both", pad=7, labelpad=10)
    ax.set_xlim(min(x)-0.03, max(x)+0.03)
    note = textwrap.fill(str(d.get("注", "")).strip(), width=105)
    ax.text(0.5, -0.14, " ｜ ".join(v for v in (note, SRC) if v),
            ha="center", va="top", fontsize=8, color="gray", transform=ax.transAxes)
    return fig


@latest_chart("图12")
def fig_forecast(ops: dict) -> plt.Figure | None:
    d = ops.get("forecast")
    if not d:
        return None
    fig, ax = plt.subplots(figsize=(10, 5.5))
    hist_x = np.arange(len(d["labels_hist"]))
    ax.bar(hist_x, d["np_hist"], color="#4C72B0", alpha=0.8, width=0.5, label="历史归母净利（亿元）")
    for i, v in enumerate(d["np_hist"]):
        if v is not None and np.isfinite(v):
            ax.text(i, v+0.8, f"{format_number(v)}", ha="center", fontsize=8.5, color="#4C72B0")
    fcast_x = np.arange(len(d["labels_hist"]), len(d["labels_hist"]) + len(d["labels_fcast"]))
    for name, color, ls in [("悲观","#C44E52","--"), ("基准","#4C72B0","-"), ("乐观","#55A868","-.")]:
        if name in d:
            ax.plot(fcast_x, d[name], marker="o", color=color, lw=2.5, ls=ls, markersize=7, label=f"{name}预测")
            for i, v in enumerate(d[name]):
                ax.text(fcast_x[i], v+0.8, f"{format_number(v)}", ha="center", fontsize=8.5, color=color)
    ax.axvline(len(d["labels_hist"])-0.5, color="gray", ls=":", lw=1)
    ax.text(len(d["labels_hist"])-0.48, max(d["np_hist"])*1.05, "← 历史 ｜ 预测 →", fontsize=9, color="gray")
    all_labs = d["labels_hist"] + d["labels_fcast"]
    ax.set_xticks(list(hist_x) + list(fcast_x)); ax.set_xticklabels(all_labs)
    ax.set_ylabel("归母净利（亿元）", fontsize=11)
    ax.set_title(_section_title(d.get("标题"), "图12 盈利预测：历史与三情景", "§5 盈利预测"), fontsize=13, fontweight="bold")
    ax.legend(fontsize=9, loc="upper left")
    ax.set_xlabel(f"年份 ｜ 预测值为估计 ｜ {SRC}", fontsize=8)
    return fig


def _peer_history_panel(ax, data: dict, metric: str) -> None:
    """Optional contemporaneously available peer ratios; do not recompute future FY at old prices."""
    labels = data.get('labels', [])
    x = np.arange(len(labels))
    for s in data.get('series', []):
        vals = [_fnum(v) for v in s.get('values', [])]
        if len(vals) != len(labels):
            raise ValueError('peer_history labels/values length mismatch')
        ax.plot(x, vals, marker='o', lw=2.5 if s.get('target') else 1.5,
                label=s['name'], alpha=1.0 if s.get('target') else .8)
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel(metric, labelpad=9)
    ax.set_title(f'同行历史 {metric}（逐时点已披露口径）', fontsize=11, fontweight='bold', pad=10)
    ax.legend(fontsize=8, loc='best', frameon=False)
    _apply_clean_chart_style(ax, grid_axis="y", pad=7, labelpad=9)
    ax.set_xlabel(data.get('note', 'TTM盈利/最近已披露权益；EPS加总为近似'), fontsize=7)


def fig_pe_band(ops: dict) -> plt.Figure | None:
    d = ops.get("pe_band")
    if not d:
        return None
    labels = d["labels"]
    x = np.arange(len(labels))
    pe_high = np.array([_fnum(v) for v in d["pe_high"]], dtype=float)
    pe_low = np.array([_fnum(v) for v in d["pe_low"]], dtype=float)
    pe_mean = np.array([_fnum(v) for v in d["pe_mean"]], dtype=float)
    pe_ttm = np.array([_fnum(v) for v in d["pe_ttm"]], dtype=float)
    if d.get('peer_history'):
        fig, (ax, peer_ax) = plt.subplots(1, 2, figsize=(16, 5.5))
        _peer_history_panel(peer_ax, d['peer_history'], 'PE(TTM)')
    else:
        fig, ax = plt.subplots(figsize=(10, 5.5))
    band = np.isfinite(pe_low) & np.isfinite(pe_high)
    if band.any():
        pe_low_clean = np.where(band, pe_low, 0.0)
        pe_high_clean = np.where(band, pe_high, 0.0)
        ax.fill_between(x, pe_low_clean, pe_high_clean, where=band, alpha=0.12, color="#4C72B0")
    ax.plot(x, pe_high, color="#C44E52", lw=1.5, ls="--", label="PE 高点")
    ax.plot(x, pe_low, color="#55A868", lw=1.5, ls="--", label="PE 低点")
    ax.plot(x, pe_mean, color="#8B5CF6", lw=1.8, ls="-.", label=d.get("center_label", "PE 均值"))
    # 标注缺失/亏损区间（如2020-2022），避免折线断裂让读者产生困惑
    nan_indices = np.where(~np.isfinite(pe_ttm))[0]
    if len(nan_indices) > 0 and len(x) > 0:
        gap_s, gap_e = nan_indices[0], nan_indices[-1]
        ax.axvspan(gap_s - 0.45, gap_e + 0.45, color="#F3F4F6", alpha=0.55, zorder=0)
        y_max = np.nanmax(pe_high) if np.any(np.isfinite(pe_high)) else 50
        ax.text((gap_s + gap_e) / 2, y_max * 0.35, "亏损/微利期\n不适用PE", ha="center", va="center",
                fontsize=8.5, color="#8E9AA8", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#D1D5DB", alpha=0.9, lw=0.6))
    # Keep the full monthly line and valuation band, but show only sparse
    # markers. A marker at every observation makes long monthly histories look
    # like a row of labels even when only the latest value is annotated.
    finite_idx = np.flatnonzero(np.isfinite(pe_ttm))
    mark_idx = finite_idx[np.unique(np.linspace(0, len(finite_idx) - 1, min(8, len(finite_idx)), dtype=int))] if len(finite_idx) else []
    ax.plot(x, pe_ttm, color="#4C72B0", lw=2.4, marker="o", markersize=4.5,
            markevery=mark_idx, label="PE(TTM)")
    # Dense monthly valuation bands make point labels overlap. Label only the
    # latest finite observation; the line and band retain the full time series.
    if len(finite_idx):
        i = int(finite_idx[-1]); v = pe_ttm[i]
        ax.text(i, v-3.5, f"{format_number(v)}x", ha="center", fontsize=9, color="#4C72B0", fontweight="bold")
    if len(x) <= 15:
        ticks = np.arange(len(x))
    else:
        ticks = np.unique(np.linspace(0, len(x)-1, min(6 if d.get('peer_history') else 9, len(x)), dtype=int)) if len(x) else []
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(labels[i])[:7] for i in ticks], rotation=30, ha="right", fontsize=9)
    ax.set_ylabel("PE (TTM)", fontsize=10.5, labelpad=9)
    ax.set_title(_section_title(d.get("标题"), "图13 PE_TTM 估值带", "§6 估值"), fontsize=13, fontweight="bold", pad=12)
    _apply_clean_chart_style(ax, grid_axis="y", pad=7, labelpad=9)
    if d.get('peer_history'):
        _apply_clean_chart_style(peer_ax, grid_axis="y", pad=7, labelpad=9)
        handles, names = ax.get_legend_handles_labels()
        fig.legend(handles, names, loc='upper center', bbox_to_anchor=(.25, 1.075), ncol=4, fontsize=8, frameon=False)
    else:
        ax.legend(fontsize=9, loc="upper right", frameon=False)
    ax.set_xlabel(f"时点 ｜ {SRC}", fontsize=8)
    return fig


def fig_pb_band(ops: dict) -> plt.Figure | None:
    d = ops.get("pb_band")
    if not d:
        return None
    labels = d["labels"]
    x = np.arange(len(labels))
    pb_high = np.array([_fnum(v) for v in d["pb_high"]], dtype=float)
    pb_low = np.array([_fnum(v) for v in d["pb_low"]], dtype=float)
    pb = np.array([_fnum(v) for v in d["pb"]], dtype=float)
    if d.get('peer_history'):
        fig, (ax, peer_ax) = plt.subplots(1, 2, figsize=(16, 5.5))
        _peer_history_panel(peer_ax, d['peer_history'], 'PB')
    else:
        fig, ax = plt.subplots(figsize=(10, 5.5))
    band = np.isfinite(pb_low) & np.isfinite(pb_high)
    if band.any():
        pb_low_clean = np.where(band, pb_low, 0.0)
        pb_high_clean = np.where(band, pb_high, 0.0)
        ax.fill_between(x, pb_low_clean, pb_high_clean, where=band, alpha=0.12, color="#DD8452")
    ax.plot(x, pb_high, color="#C44E52", lw=1.5, ls="--", label="PB 高点")
    ax.plot(x, pb_low, color="#55A868", lw=1.5, ls="--", label="PB 低点")
    finite_idx = np.flatnonzero(np.isfinite(pb))
    mark_idx = finite_idx[np.unique(np.linspace(0, len(finite_idx) - 1, min(8, len(finite_idx)), dtype=int))] if len(finite_idx) else []
    ax.plot(x, pb, color="#DD8452", lw=2.4, marker="o", markersize=4.5,
            markevery=mark_idx, label="PB")
    if len(finite_idx):
        i = int(finite_idx[-1]); v = pb[i]
        ax.text(i, v+0.15, f"{format_number(v)}x", ha="center", fontsize=9, color="#DD8452", fontweight="bold")
    if len(x) <= 15:
        ticks = np.arange(len(x))
    else:
        ticks = np.unique(np.linspace(0, len(x)-1, min(6 if d.get('peer_history') else 9, len(x)), dtype=int)) if len(x) else []
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(labels[i])[:7] for i in ticks], rotation=30, ha="right", fontsize=9)
    ax.set_ylabel("PB", fontsize=10.5, labelpad=9)
    ax.set_title(_section_title(d.get("标题"), "图14 PB 估值带", "§6 估值"), fontsize=13, fontweight="bold", pad=12)
    _apply_clean_chart_style(ax, grid_axis="y", pad=7, labelpad=9)
    if d.get('peer_history'):
        _apply_clean_chart_style(peer_ax, grid_axis="y", pad=7, labelpad=9)
        handles, names = ax.get_legend_handles_labels()
        fig.legend(handles, names, loc='upper center', bbox_to_anchor=(.25, 1.075), ncol=2, fontsize=8, frameon=False)
    else:
        ax.legend(fontsize=9, loc="upper right", frameon=False)
    ax.set_xlabel(f"时点 ｜ {SRC}", fontsize=8)
    return fig


@latest_chart("图15")
def fig_leverage(ops: dict) -> plt.Figure | None:
    d = ops.get("leverage")
    if not d:
        return None
    labels = d["labels"]
    fig, ax = plt.subplots(figsize=(10.5, 5.8))
    x = np.arange(len(labels))
    ax.plot(x, d["资产负债率"], marker="o", color="#C44E52", lw=2.4, markersize=6.5, label="资产负债率（%）")
    if "有息负债率" in d:
        ax.plot(x, d["有息负债率"], marker="s", color="#DD8452", lw=2.4, markersize=6.5,
                label="有息负债/总资产（%）")
    ax.set_ylabel("资产负债率 / 有息负债占比（%）", fontsize=11, labelpad=10)
    ax2 = ax.twinx()
    net_cash = d.get("净现金", [])
    valid_cash = [(i, v) for i, v in enumerate(net_cash)
                  if v is not None and np.isfinite(v)]
    if valid_cash:
        ax2.bar([i for i, _ in valid_cash], [v for _, v in valid_cash],
                color="#55A868", alpha=0.7, width=0.45,
                label=f"净现金（{d.get('净现金单位', '亿元')}，正=净现金）")
    cash_unit = d.get("净现金单位", "亿元")
    ax2.set_ylabel(f"净现金（{cash_unit}）", color="#55A868", fontsize=11, labelpad=10)
    ax.set_xticks(list(x)); ax.set_xticklabels(labels)
    ax.set_title(_section_title(d.get("标题"), "图15 杠杆与负债结构", "§4 财务分析"), fontsize=13, fontweight="bold", pad=12)
    _apply_clean_chart_style(ax, grid_axis="y", pad=7, labelpad=10)
    _apply_clean_twin_style(ax2, pad=7, labelpad=10)
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9, frameon=False)
    note = textwrap.fill(str(d.get("注", "")).strip(), width=105)
    ax.set_xlabel(f"年份 ｜ {SRC}", fontsize=8)
    if note:
        ax.text(0.5, -0.14, note, ha="center", va="top", fontsize=8, color="gray", transform=ax.transAxes)
    return fig



def fig_sotp(ops: dict) -> plt.Figure | None:
    """图18 分部估值 SOTP（平台型公司强制；数据来自 sotp_valuation.py 输出 → ops["sotp"]）。
    左面板：分部价值贡献（亿元）横向条形 + 调整项（净现金/少数股东/控股折价）；
    右面板：每股 SOTP（基准柱 + 低/高档区间误差条）vs 现价参考线。"""
    d = ops.get("sotp")
    if not d or not d.get("segments"):
        return None
    segs = d["segments"]
    adj = d.get("adjustments", {})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.2),
                                   gridspec_kw=dict(width_ratios=[1.15, 1.0]))
    colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8B5CF6", "#F59E0B", "#7F7F7F"]
    names = [s["name"] for s in segs]
    vals = [float(s["value"]) for s in segs]
    pcts = [s.get("pct", 0.0) for s in segs]
    y = list(range(len(segs)))[::-1]
    ax1.barh(y, vals, color=colors[:len(segs)], alpha=0.9, height=0.55)
    for yi, v, nm, pc in zip(y, vals, names, pcts):
        ax1.text(v + max(vals) * 0.015, yi, f"{nm} {format_number(v)}亿 ({format_number(pc*100)}%)",
                 va="center", fontsize=9, color="#333333")
    ax1.set_yticks([])
    ax1.set_xlabel("分部价值（亿元）", fontsize=10, labelpad=9)
    basis_label = "股权价值" if all(s.get("basis", "net_profit") == "net_profit" for s in segs) else "分部价值"
    ax1.set_title(f"SOTP {basis_label}贡献（合计≈{format_number(sum(vals))} 亿）", fontsize=12, fontweight="bold", pad=10)
    ax1.set_xlim(0, max(vals) * 1.45)
    _apply_clean_chart_style(ax1, grid_axis="")
    # 调整项（净现金/少数股东/控股折价）标注在右面板脚注，避免条形图视觉混乱
    note_adj = []
    if adj.get("net_cash"):
        note_adj.append(f"+净现金 {format_number(adj['net_cash'])} 亿")
    if adj.get("minority"):
        note_adj.append(f"−少数股东 {format_number(adj['minority'])} 亿")
    if adj.get("other"):
        note_adj.append(f"其他调整 {format_number(adj['other'])} 亿")
    if adj.get("holding_discount", 1.0) != 1.0:
        note_adj.append(f"×控股折价 {format_number(adj['holding_discount'])}")
    adj_txt = "，".join(note_adj) if note_adj else "无调整项"
    # 右面板：每股 SOTP vs 现价
    per = float(d["per_share"]); lo = float(d.get("per_share_low", per)); hi = float(d.get("per_share_high", per))
    price = float(d.get("price", 0))
    ax2.bar(["每股 SOTP"], [per], color="#4C72B0", alpha=0.9, width=0.45,
            yerr=[[per - lo], [hi - per]], capsize=8, error_kw=dict(lw=1.6, color="#333333"))
    ax2.text(0, per + (hi - per) * 0.5 + (max(hi, price) - min(lo, price)) * 0.02,
             f"{format_number(per)} 元", ha="center", fontsize=12, fontweight="bold", color="#4C72B0")
    ax2.text(0, lo - (max(hi, price) - min(lo, price)) * 0.06, f"低 {format_number(lo)} ｜ 高 {format_number(hi)}",
             ha="center", fontsize=8.5, color="#555555")
    if price:
        ax2.axhline(price, color="#C44E52", ls="--", lw=2)
        ax2.text(0.35, price, f"现价 {format_number(price)} 元", color="#C44E52", fontsize=10, fontweight="bold", va="bottom")
    ymin = min(lo, price) * 0.75
    ymax = max(hi, price) * 1.25
    ax2.set_ylim(ymin, ymax)
    ax2.set_ylabel("元/股", fontsize=10, labelpad=9)
    ax2.set_title(f"每股 SOTP vs 现价（溢价 {format_number(d.get('premium', 0)*100)}%）",
                  fontsize=12, fontweight="bold", pad=10)
    _apply_clean_chart_style(ax2, grid_axis="y", pad=7, labelpad=9)
    fig.suptitle(_section_title(d.get("标题"), "图18 分部估值 SOTP", "§6 估值"), fontsize=13, fontweight="bold", y=1.00)
    fig.text(0.5, -0.02, f"调整：{adj_txt} ｜ 分部盈利为估算时标注「手算/补充」 ｜ {SRC}",
             ha="center", fontsize=8, color="gray", transform=fig.transFigure)
    return fig



# ═══════════════ 主流程 ═══════════════════

def main() -> int:
    ap = argparse.ArgumentParser(description="统一图表生成（PNG + Plotly HTML，行业无关）")
    ap.add_argument("--dir", required=True, help="项目目录（含 data/）")
    ap.add_argument("--code", required=True, help="标的代码")
    ap.add_argument("--name", default="", help="公司名称")
    ap.add_argument("--ops", default="", help="运营补充数据 JSON（默认 input/运营补充数据.json）")
    ap.add_argument("--out", default="", help="PNG 输出目录（默认 --dir/reports/图表）")
    ap.add_argument("--html-out", default="", help="HTML 输出路径")
    ap.add_argument("--data-date", default="", help="数据截至日期（默认取日线 CSV 最后日期，失败用今天）")
    args = ap.parse_args()

    proj = Path(args.dir)
    data_dir = proj / "data"
    latest_pack = configure_latest(data_dir, write=True)
    ops: dict = {}
    if args.ops:
        ops_f = Path(args.ops)
        if not ops_f.is_absolute():
            ops_f = proj / ops_f
    else:
        ops_f = proj / "input" / "运营补充数据.json"
    if ops_f.exists():
        ops = json.loads(ops_f.read_text(encoding="utf-8-sig"))
        p(f"[加载] 运营补充数据: {ops_f}")
    else:
        p(f"[提示] 无运营补充数据（{ops_f}），使用 CSV 自动图表；运营图按 --ops 补充")
    ops = _bind_script_sensitivity(proj, ops)
    industry_auto = load_industry_cost_price(proj / "data")
    if industry_auto and "industry_cost_price" not in ops:
        ops["industry_cost_price"] = industry_auto
        p("[加载] 行业成本—价格序列: data/行业成本价格.csv")

    # 数据日期（B4.2 每图必须标注）：--data-date 优先，否则取日线 CSV 最后交易日，失败用今天
    global SRC
    data_date = args.data_date
    if not data_date:
        for fname in ("日线股价.csv", "日线股价_前复权.csv"):
            px_f = data_dir / fname
            if px_f.exists():
                try:
                    px = pd.read_csv(px_f, encoding="utf-8-sig")
                    dc = _date(px)
                    if dc is not None and len(px):
                        last_d = pd.to_datetime(px[dc], errors="coerce").dropna()
                        if len(last_d):
                            data_date = last_d.iloc[-1].strftime("%Y-%m-%d")
                            break
                except Exception:
                    continue
    if not data_date:
        data_date = pd.Timestamp.today().strftime("%Y-%m-%d")
    SRC = f"来源：财报CSV/公司公告/行情源 ｜ 财报最新 {latest_pack.get('latest_period') or '未取得'}；行情至 {data_date}"
    p(f"[数据日期] {data_date}")
    out_dir = (proj / args.out if args.out and not Path(args.out).is_absolute()
               else Path(args.out) if args.out else proj / "reports" / "图表")
    out_dir.mkdir(parents=True, exist_ok=True)
    html_out = (proj / args.html_out if args.html_out and not Path(args.html_out).is_absolute()
                else Path(args.html_out) if args.html_out
                else proj / "reports" / f"{args.name or '公司'}_{args.code}_图表.html")
    html_out.parent.mkdir(parents=True, exist_ok=True)

    pl_raw = load_csv(data_dir, "利润表_按报告期.csv")
    fi_raw = load_csv(data_dir, "主要财务指标_按报告期.csv")
    div = load_csv(data_dir, "分红送配记录.csv")
    pl_y = year_rows(pl_raw) if pl_raw is not None else None
    fi_y = year_rows(fi_raw) if fi_raw is not None else None

    jobs = [
        ("图01_营收与归母净利.png",          lambda: fig_revenue(pl_y) if pl_y is not None else None),
        ("图02_ROE与BPS.png",               lambda: fig_roe_bps(fi_y) if fi_y is not None else None),
        ("图03_分部营收构成与增速.png",       lambda: fig_segment(ops)),
        ("图04_盈利能力趋势.png",             lambda: fig_profitability(ops)),
        ("图05_现金流结构.png",               lambda: fig_cashflow(ops)),
        ("图06_同行估值与增长对比.png",       lambda: fig_peers(ops)),
        ("图07_DPS与支付率.png",             lambda: fig_dps(div, ops)),
        ("图08_股价走势与分位.png",           lambda: fig_price(data_dir)),
        ("图09_多框架目标价对比.png",         lambda: fig_targets(ops)),
        ("图10_穿透回报率GGvsII.png",         lambda: fig_penetration(ops)),
        ("图11_敏感性分析.png",               lambda: fig_sensitivity(ops)),
        ("图12_盈利预测历史与三情景.png",     lambda: fig_forecast(ops)),
        ("图13_PE估值带.png",                lambda: fig_pe_band(ops)),
        ("图14_PB估值带.png",                lambda: fig_pb_band(ops)),
        ("图15_杠杆与负债结构.png",           lambda: fig_leverage(ops)),
        ("图16_行业成本与价格走势.png",       lambda: fig_industry_cost_price(ops, data_dir)),
        ("图18_分部估值SOTP.png",            lambda: fig_sotp(ops)),
    ]
    # 图表豁免制（B4.2）：缺图必须声明，否则完整性门 FAIL（禁止静默跳过）
    exempt = {}
    ex_f = proj / "input" / "图表豁免.json"
    try:
        from chart_qc import _chart_exemptions
        valid_exemptions = _chart_exemptions(proj)
        if valid_exemptions:
            for entry in json.loads(ex_f.read_text(encoding="utf-8-sig"))["豁免"]:
                exempt[entry["图"].split("_")[0]] = entry["原因"]
    except (OSError, ValueError) as exc:
        p(f"[FAIL] 图表豁免配置无效: {exc}")
        return 2

    made = skipped = 0
    coverage = {}
    missing_required = []
    # SOTP 触发状态：平台型（input/sotp_触发.json enabled=true）→ 图18 强制；否则图18 可选不 FAIL
    sotp_trig = False
    try:
        _tf = proj / "input" / "sotp_触发.json"
        if _tf.exists():
            sotp_trig = json.loads(_tf.read_text(encoding="utf-8-sig")).get("enabled") is True
    except Exception:
        pass
    for fname, factory in jobs:
        prefix = fname.split("_")[0]
        if prefix in exempt:
            old_output = out_dir / fname
            if old_output.exists():
                p(f"[ERROR] {fname} 已豁免但有旧PNG；请明确移出后重跑，禁止把旧图视为本轮生成")
                missing_required.append(fname)
            else:
                p(f"[SKIP-豁免] {fname}（{exempt[prefix]}）")
            skipped += 1
            continue
        fig = factory()
        if fig is None:
            prefix = fname.split("_")[0]  # 图NN
            if prefix in exempt:
                p(f"[SKIP-豁免] {fname}（{exempt[prefix]}）")
            elif prefix == "图18" and not sotp_trig:
                p(f"[SKIP-可选] {fname}（非平台型公司，SOTP 未触发）")
            else:
                p(f"[ERROR] {fname} 数据缺失且未在 input/图表豁免.json 声明豁免 → 图表完整性门 FAIL")
                missing_required.append(fname)
            skipped += 1
            continue
        save(fig, out_dir, fname)
        prefix = fname.split("_")[0]
        entry = {"file": fname, "png_sha256": hashlib.sha256((out_dir / fname).read_bytes()).hexdigest(),
                 "latest_period": getattr(fig, "_latest_period", None),
                 "basis": latest_pack.get("basis"), "is_forecast": False,
                 "rendered_values": getattr(fig, "_latest_values", {})}
        entry['integrated_original_axes'] = getattr(fig, '_integrated_latest', False)
        entry['layout'] = {'axes_count':len(fig.axes),
            'latest_tick_visible':any(str(latest_pack.get('latest_period',''))[:4] in t.get_text() and (getattr(fig,'_year_grouped',False) or '本期实际' in t.get_text()) for ax in fig.axes for t in ax.get_xticklabels()),
            'grouped_by_year':getattr(fig,'_year_grouped',False),
            'right_gutter_ratio':round(1-max(ax.get_position().x1 for ax in fig.axes),6)}
        entry['layout'].update(getattr(fig, '_layout_audit', {}))
        from financial_history_charts import growth_line_evidence
        entry['growth_lines'] = growth_line_evidence(fig) if getattr(fig,'_year_grouped',False) else {}
        entry['display_basis'] = getattr(fig, '_display_basis', None)
        section = {"图03": "segment", "图06": "peers_period", "图07": "dps"}.get(prefix)
        if section:
            section_data = ops.get(section, {})
            entry["period_review"] = section_data.get("period_review", {})
        coverage[prefix] = entry
        made += 1
    (proj / "reports" / "图表期间覆盖.json").write_text(json.dumps({
        "schema_version": 1, "latest_statement_period": latest_pack.get("latest_period"),
        "ops_sha256": hashlib.sha256(ops_f.read_bytes()).hexdigest() if ops_f.exists() else None,
        "source_sha256": latest_pack.get("source_sha256", {}), "charts": coverage}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    p(f"\n[PNG] 生成 {made}/{len(jobs)} 张，跳过 {skipped} 张 -> {out_dir}")
    if made < 10:
        p("[WARN] 图表不足 10 张！请检查 ops JSON 补充运营数据，或标注行业不适用项")
    if missing_required:
        p("\n[FAIL] 以下必需图因数据缺失未生成（请补 --ops 数据，或在 input/图表豁免.json 声明豁免并说明原因）：")
        for f in missing_required:
            p(f"  - {f}")
        return 2

    # ── 图表质量门（G8，成稿前必须运行）──
    p("\n[QC] 运行图表质量门（图号映射/PNG引用/HTML残留/表格结构）：")
    p("     python scripts/chart_qc.py --dir . --report reports/<报告名>.md [--no-map-check 历史项目]")

    # ---- Plotly 交互 HTML ----
    if latest_pack.get('has_interim_income'):
        from financial_history_charts import write_interactive
        count = write_interactive(latest_pack,ops,html_out,f'{args.name or args.code}（{args.code}）年度与单季度图表｜实际截至{latest_pack["latest_period"]}')
        p(f'[HTML] {html_out}（{count}个图组，年度/Q1—Q4/年度同比）')
        return 0
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        p("[FAIL] 未安装 plotly，无法生成交互图表 HTML")
        return 2

    panels = []
    # The same original series contain the latest actuals in both output formats.
    if latest_pack.get('basis') == 'YTD':
        if pl_y is not None:
            pl_y = extend_chart_input(pl_y, '图01', latest_pack)
        if fi_y is not None:
            fi_y = extend_chart_input(fi_y, '图02', latest_pack)
    segment = ops.get("segment", {})
    if segment.get("period_review", {}).get("period_end"):
        for s in segment['series']:
            panels.append(go.Bar(x=segment['labels'], y=s['values'], name=f"分部 {s['name']}（亿元；H1非全年）", marker_color='#4C72B0'))
    if pl_y is not None:
        rev_col = _col(pl_y, "OPERATE_INCOME", "营业总收入")
        np_col = _col(pl_y, "PARENT_NETPROFIT", "归母净利")
        yrs = [r.get('_chart_label', r["REPORT_DATE"].strftime("%Y")) for _, r in pl_y.iterrows()]
        if rev_col:
            panels.append(go.Bar(x=yrs, y=[e8(r.get(rev_col)) for _, r in pl_y.iterrows()],
                                 name="营业总收入（亿元）", marker_color="#4C72B0"))
        if np_col:
            profit_values = [e8(r.get(np_col)) for _, r in pl_y.iterrows()]
            # Insert a missing connector within the original trace, preserving both periods.
            profit_x = list(yrs)
            if latest_pack.get('basis') == 'YTD':
                profit_values.insert(-3, None); profit_x.insert(-3, '')
            panels.append(go.Scatter(x=profit_x, y=profit_values,
                                     name="归母净利（亿元）", mode="lines+markers", line=dict(color="#C44E52", width=2.5)))
    if fi_y is not None:
        roe_col = _col(fi_y, "ROEJQ", "ROE")
        if roe_col:
            yrs_fi = [r.get('_chart_label', r["REPORT_DATE"].strftime("%Y")) for _, r in fi_y.iterrows()]
            panels.append(go.Bar(x=yrs_fi, y=[num(r.get(roe_col)) for _, r in fi_y.iterrows()],
                                 name="ROE（%）", marker_color="#55A868"))
    for chart_id, section, series_keys in (
        ('图04','profitability',('毛利率','净利率')),
        ('图05','cashflow',('OCF','Capex','FCF')),
        ('图15','leverage',('资产负债率','有息负债率','净现金'))):
        integrated_ops = extend_chart_input(ops, chart_id, latest_pack) if latest_pack.get('basis') == 'YTD' else ops
        d = integrated_ops.get(section, {})
        for key in series_keys:
            if key in d:
                panels.append(go.Bar(x=d['labels'], y=d[key], name=f'{chart_id} {key}（末两列为累计实际/期末值）'))
    ind = ops.get("industry_cost_price")
    if ind:
        for s in ind.get("series", []):
            panels.append(go.Scatter(x=ind["labels"], y=s.get("raw_values") or s["values"], name=f"图16 {s['name']}（{s.get('unit', '原始值')}）", mode="lines+markers"))
    px_df = load_csv(data_dir, "日线股价_前复权.csv")
    if px_df is None:
        px_df = load_csv(data_dir, "日线股价.csv")
    if px_df is not None and len(px_df) > 20:
        dc, cc = _date(px_df), _close(px_df)
        if dc and cc:
            px_df[dc] = pd.to_datetime(px_df[dc])
            panels.append(go.Scatter(x=px_df[dc], y=px_df[cc], name="股价(前复权)",
                                     line=dict(width=1.2, color="#4C72B0")))
    pen = ops.get("penetration")
    if pen:
        panels.append(go.Bar(x=pen["labels"], y=pen["gg"], name="回报率（%）",
                             marker_color=["#C44E52","#55A868","#DD8452"][:len(pen["gg"])],
                             text=[f"{format_number(v)}%" for v in pen["gg"]], textposition="outside"))
    sens = ops.get("sensitivity")
    if sens:
        for s in sens["系列"]:
            panels.append(go.Scatter(x=sens["x"], y=s["y"], name=s["name"], mode="lines+markers"))
    if panels:
        n = len(panels); rows = (n + 1) // 2
        fig = make_subplots(rows=rows, cols=2, subplot_titles=[t.name for t in panels[:rows*2]])
        for i, tr in enumerate(panels):
            fig.add_trace(tr, row=i//2+1, col=i%2+1)
        title_text = f"{args.name or args.code}（{args.code}）交互图表合集 ｜ {SRC}"
        fig.update_layout(title=dict(text=title_text, font=dict(size=16)), height=420*rows,
                          showlegend=False, template="plotly_white", margin=dict(l=65,r=35,t=110,b=65))
        fig.write_html(html_out, include_plotlyjs=True)
        p(f"[HTML] {html_out}（{format_number(html_out.stat().st_size/1024)} KB）")
    else:
        p("[FAIL] 无可用数据，无法生成交互图表 HTML")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
