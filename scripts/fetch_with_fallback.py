"""统一数据拉取适配层：候选源自动切换 + 调用记录（skill 通用资产，水星家纺分析实战沉淀）
用法:
    python fetch_with_fallback.py <code> --out <输出目录> [--items daily,sheets,indicators,dividends,top10]
    默认拉取全部五项，输出 日线股价.csv/日线股价_前复权.csv/资产负债表_按报告期.csv/利润表_按报告期.csv/
    现金流量表_按报告期.csv/主要财务指标_按报告期.csv/主要财务指标_按单季度.csv/分红送配记录.csv/
    十大股东.csv 与 拉取清单.json（调用记录）
设计原则:
    1. 每个数据项有候选源列表，按顺序尝试，成功即停，全部失败则标注缺失（不报错中断）
    2. 所有调用记录（源/状态/行数/失败原因）写入 <out>/拉取清单.json
    3. 接口缺失（hasattr 检查）直接跳过并标注，不抛异常
    4. 符号统一由 norm_symbol() 生成（emweb 前缀 / 腾讯小写格式）
候选源链（2026-08-12 实测校准，详见 references/data-source-notes.md）:
    日线:     stock_zh_a_hist(东财) -> stock_zh_a_hist_tx(腾讯, 符号 sh603365)
    三表:     emweb 三接口（仅此一路，必须带市场前缀如 SH603365）
    财务指标: emweb 指标接口（带市场前缀）
    分红:     stock_fhps_detail_em -> 现金流量表"分配股利支付的现金"列
    十大股东: stock_shareholder_top10_em -> stock_gdfx_top_10_em -> 标注缺失(建议 WebSearch 兜底)
"""
import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_sources import norm_symbol  # noqa: E402


def make_recorder(out_dir: Path) -> dict:
    """拉取清单：已存在则续写，否则新建"""
    p = out_dir / "拉取清单.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def record(log: dict, item: str, status: str, source: str, rows: int = 0, note: str = "") -> None:
    log[item] = {"状态": status, "源": source, "行数": rows, "时间": time.strftime("%Y-%m-%d %H:%M:%S"), "备注": note}


def fetch_daily(ak, sym: dict, out_dir: Path, log: dict) -> None:
    """日线：东财 -> 腾讯 自动切换（复权/不复权两份）
    注意：两个源的函数签名不同——东财有 period 参数，腾讯没有（签名:
    stock_zh_a_hist_tx(symbol, start_date, end_date, adjust)），必须按源分支传参
    """
    for adjust, fname in [("", "日线股价.csv"), ("qfq", "日线股价_前复权.csv")]:
        source = "stock_zh_a_hist(东财)"
        try:
            if hasattr(ak, "stock_zh_a_hist"):
                df = ak.stock_zh_a_hist(symbol=sym["东财纯代码"], period="daily",
                                        start_date="20100101", adjust=adjust)
                if df is not None and len(df) > 0:
                    df.to_csv(out_dir / fname, index=False, encoding="utf-8-sig")
                    record(log, f"日线({adjust or '不复权'})", "OK", source, len(df))
                    continue
            raise RuntimeError("东财源无数据")
        except Exception as e:
            # 降级: 腾讯源（符号 sh603365；adjust 传 "" / "qfq"；无 period 参数）
            source = f"stock_zh_a_hist_tx(腾讯)[东财失败: {type(e).__name__}]"
            try:
                df = ak.stock_zh_a_hist_tx(symbol=sym["腾讯"],
                                           start_date="20100101", adjust=adjust)
                if df is not None and len(df) > 0:
                    df.to_csv(out_dir / fname, index=False, encoding="utf-8-sig")
                    record(log, f"日线({adjust or '不复权'})", "OK", source, len(df))
                    continue
                raise RuntimeError("腾讯源无数据")
            except Exception as e2:
                record(log, f"日线({adjust or '不复权'})", "FAIL", source, note=f"{type(e2).__name__}: {e2}")
    return


def fetch_three_sheets(ak, sym: dict, out_dir: Path, log: dict) -> None:
    """三表：东财 emweb 接口（必须带市场前缀，无前缀报'股票代码不合法'）"""
    specs = [
        ("stock_profit_sheet_by_report_em", "利润表_按报告期.csv", "利润表"),
        ("stock_balance_sheet_by_report_em", "资产负债表_按报告期.csv", "资产负债表"),
        ("stock_cash_flow_sheet_by_report_em", "现金流量表_按报告期.csv", "现金流量表"),
    ]
    for api, fname, label in specs:
        if not hasattr(ak, api):
            record(log, label, "MISS", "接口缺失", note=f"{api} 在当前 akshare 版本不存在")
            continue
        try:
            df = getattr(ak, api)(symbol=sym["emweb"])
            if df is not None and len(df) > 0:
                df.to_csv(out_dir / fname, index=False, encoding="utf-8-sig")
                record(log, label, "OK", f"{api}(emweb)", len(df))
            else:
                record(log, label, "FAIL", f"{api}(emweb)", note="返回空")
        except Exception as e:
            record(log, label, "FAIL", f"{api}(emweb)", note=f"{type(e).__name__}: {e}")


def derive_single_quarter(dates, eps):
    """累计 EPSJB -> 单季值：Q1=一季报累计；其余=本期累计-上期累计（东财报告期指标为累计口径）"""
    out = []
    prev_year, prev_eps = None, None
    for dt, e in zip(dates, eps):
        y = dt.year
        out.append(e if y != prev_year else e - prev_eps)
        prev_year, prev_eps = y, e
    return out


def fetch_indicators(ak, sym: dict, out_dir: Path, log: dict) -> None:
    """主要财务指标（报告期 + 单季度）
    候选链:
      1. stock_financial_abstract_em（1.18.84 已移除 -> 跳过）
      2. stock_financial_analysis_indicator_em（底层走新浪，新浪 SSL 故障时挂）
      3. emweb HTTP RPT_F10_FINANCE_MAINFINADATA（不依赖 akshare/新浪，2026-08 验证可用）
         单季度由报告期累计 EPS 差分推导（EPSJB 单季值，与 analyze_valuation.py 滚动4期用法兼容）
    """
    done = False
    for api in ["stock_financial_abstract_em", "stock_financial_analysis_indicator_em"]:
        if done or not hasattr(ak, api):
            continue
        try:
            df = getattr(ak, api)(symbol=sym["emweb"])
            if df is not None and len(df) > 0:
                df.to_csv(out_dir / "主要财务指标_按报告期.csv", index=False, encoding="utf-8-sig")
                record(log, "财务指标(报告期)", "OK", f"{api}(emweb)", len(df))
                done = True
            else:
                record(log, "财务指标(报告期)", "FAIL", f"{api}(emweb)", note="返回空")
        except Exception as e:
            record(log, "财务指标(报告期)", "FAIL", f"{api}(emweb)",
                   note=f"{type(e).__name__}: {e}（可能底层新浪源故障）")
    if done:
        return
    # 第 3 档: emweb HTTP 核心指标接口 + 单季差分（自给自足）
    try:
        import requests
        u = (f"https://datacenter-web.eastmoney.com/api/data/v1/get"
             f"?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL&pageNumber=1&pageSize=500"
             f"&sortColumns=REPORT_DATE&sortTypes=-1&filter=(SECUCODE%3D%22{sym['secucode']}%22)")
        r = requests.get(u, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        rows = (r.json().get("result") or {}).get("data") or []
        if rows:
            df = pd.DataFrame(rows)
            df.to_csv(out_dir / "主要财务指标_按报告期.csv", index=False, encoding="utf-8-sig")
            record(log, "财务指标(报告期)", "OK", "emweb HTTP RPT_F10_FINANCE_MAINFINADATA", len(rows))
            # 差分单季（仅 EPSJB 用于 TTM 计算；列名与 analyze_valuation.py 兼容）
            dq = df[["REPORT_DATE", "EPSJB"]].dropna(subset=["EPSJB"]).copy()
            dq["REPORT_DATE"] = pd.to_datetime(dq["REPORT_DATE"])
            dq = dq.sort_values("REPORT_DATE")
            dq["EPSJB"] = derive_single_quarter(dq["REPORT_DATE"], dq["EPSJB"].values)
            dq.to_csv(out_dir / "主要财务指标_按单季度.csv", index=False, encoding="utf-8-sig")
            record(log, "财务指标(单季度)", "OK", "报告期累计EPS差分推导", len(dq))
            return
        record(log, "财务指标(报告期)", "FAIL", "emweb HTTP", note="返回空")
    except Exception as e:
        record(log, "财务指标(报告期)", "FAIL", "emweb HTTP", note=f"{type(e).__name__}: {e}")
    return


def fetch_dividends(ak, code: str, out_dir: Path, log: dict, sheets_ok: bool = False) -> None:
    """分红送配：stock_fhps_detail_em -> 现金流量表'分配股利支付的现金'降级（标注口径）"""
    if hasattr(ak, "stock_fhps_detail_em"):
        try:
            df = ak.stock_fhps_detail_em(symbol=code)
            if df is not None and len(df) > 0:
                df.to_csv(out_dir / "分红送配记录.csv", index=False, encoding="utf-8-sig")
                record(log, "分红送配", "OK", "stock_fhps_detail_em(东财)", len(df))
                return
        except Exception as e:
            record(log, "分红送配", "FAIL", "stock_fhps_detail_em", note=f"{type(e).__name__}: {e}")
            return
    record(log, "分红送配", "MISS", "接口缺失",
           note="用现金流量表'分配股利支付的现金'列计算支付率法2（口径变更已标注）")


def fetch_top10(ak, code: str, sym: dict, out_dir: Path, log: dict) -> None:
    """十大股东：候选接口循环，全部失败则标注缺失（建议 WebSearch 兜底）
    stock_shareholder_top10_em（1.18.84 已移除）-> stock_gdfx_top_10_em（存在，
    签名: (symbol='sh688686', date='20210630')——date 是报告期，不传则用默认值）
    """
    cands = [("stock_shareholder_top10_em", dict(symbol=sym["东财纯代码"])),
             ("stock_gdfx_top_10_em", dict(symbol=sym["腾讯"]))]
    for api, kwargs in cands:
        if not hasattr(ak, api):
            continue
        try:
            df = getattr(ak, api)(**kwargs)
            if df is not None and len(df) > 0:
                df.to_csv(out_dir / "十大股东.csv", index=False, encoding="utf-8-sig")
                record(log, "十大股东", "OK", f"{api}(东财)", len(df))
                return
        except Exception as e:
            record(log, "十大股东", "FAIL", f"{api}(东财)", note=f"{type(e).__name__}: {e}")
    record(log, "十大股东", "MISS", "候选接口均不可用",
           note="治理信息用 WebSearch 补全（精度受限，进审计报告标注）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code", help="股票代码（裸代码即可）")
    ap.add_argument("--out", required=True, help="输出目录（项目 data/）")
    ap.add_argument("--items", default="daily,sheets,indicators,dividends,top10")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sym = norm_symbol(args.code)
    log = make_recorder(out_dir)
    items = args.items.split(",")

    try:
        import akshare as ak
    except ImportError:
        print("akshare 未安装"); sys.exit(1)

    if "daily" in items:
        fetch_daily(ak, sym, out_dir, log)
    if "sheets" in items:
        fetch_three_sheets(ak, sym, out_dir, log)
    if "indicators" in items:
        fetch_indicators(ak, sym, out_dir, log)
    if "dividends" in items:
        fetch_dividends(ak, sym["东财纯代码"], out_dir, log)
    if "top10" in items:
        fetch_top10(ak, sym["东财纯代码"], sym, out_dir, log)

    log["拉取时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
    log["结论"] = "各数据项以 OK 的最高优先级源为准；MISS/FAIL 项需在审计报告标注降级路径"
    (out_dir / "拉取清单.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print("=== 拉取结果 ===")
    for k, v in log.items():
        if isinstance(v, dict) and "状态" in v:
            print(f"  [{v['状态']:4s}] {k:16s} 源={v['源']} 行数={v['行数']} {v['备注']}")
    print(f"输出目录: {out_dir}")


if __name__ == "__main__":
    main()
