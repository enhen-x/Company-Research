"""数据源连通性探测 + 符号规范化工具（skill 通用资产，水星家纺分析实战沉淀）
用途（每次新分析开始前先运行，避免被动试错）：
1. 探测各行情/财务数据源连通性 -> <out>/源探测.json
2. 检查 akshare 关键接口在当前版本是否存在（接口名会随版本变更）
3. 符号规范化：裸代码 -> emweb 前缀格式 / 腾讯小写格式 / 新浪格式

用法：
    python scripts/probe_sources.py <code> [--out <输出目录>]
示例（输出目录含空格需引号）：
    python scripts/probe_sources.py 603365 --out "G:/理财/个股分析/项目/data"
输出：
    <out>/源探测.json  —— {"端点数": {源: OK/FAIL}, "akshare接口": {名: 存在/缺失}, "符号": {...}}
    （不传 --out 时默认输出到 <脚本所在目录>/../data）
"""
import argparse
import json
import sys
import time
from pathlib import Path

import requests

TIMEOUT = 4  # 秒，短超时避免探测拖慢流程

# 各数据源代表性端点（按 skill 降级链顺序）
ENDPOINTS = {
    "东财行情-日线(push2his)": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
    "东财行情-实时(push2)": "https://push2.eastmoney.com/api/qt/stock/get",
    "东财数据中心(emweb三表)": "https://datacenter-web.eastmoney.com/api/data/v1/get",
    "腾讯行情(qt.gtimg.cn)": "https://qt.gtimg.cn/q=sh600519",
    "腾讯历史K线(ifzq.gtimg.cn)": "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
    "新浪行情(hq.sinajs.cn)": "https://hq.sinajs.cn/list=sh600519",
}

# akshare 关键接口名（随版本可能变更，探测后自动判断）
AK_API = [
    "stock_zh_a_hist",          # 东财日线
    "stock_zh_a_hist_tx",       # 腾讯日线
    "stock_profit_sheet_by_report_em",   # 东财利润表
    "stock_balance_sheet_by_report_em",  # 东财资产负债表
    "stock_cash_flow_sheet_by_report_em",# 东财现金流量表
    "stock_fhps_detail_em",     # 东财分红送配
    "stock_financial_abstract_em",       # 东财财务摘要（1.18.84 已不存在）
    "stock_financial_analysis_indicator_em",
    "stock_shareholder_top10_em",        # 东财十大股东（1.18.84 已不存在）
    "stock_gdfx_top_10_em",              # 东财股东分析（可能替代）
    "stock_zh_a_gdhs",          # 股东户数
]


def norm_symbol(code: str) -> dict:
    """裸股票代码 -> 各源所需格式"""
    c = code.strip().upper()
    if c.startswith(("SH", "SZ", "BJ")):
        c = c[2:]
    if c.startswith(("6", "9")):
        mkt = "SH"
    elif c.startswith(("0", "3")):
        mkt = "SZ"
    elif c.startswith(("4", "8", "92")):
        mkt = "BJ"
    else:
        raise ValueError(f"无法推断市场前缀: {code}")
    return {
        "emweb": f"{mkt}{c}",       # 东财 emweb 三表/财务指标接口（无前缀报"股票代码不合法"）
        "腾讯": f"{mkt.lower()}{c}",  # akshare stock_zh_a_hist_tx
        "新浪": f"{mkt.lower()}{c}",  # 新浪行情符号
        "东财纯代码": c,
        "secucode": f"{c}.{mkt}",   # 东财 F10 指标 HTTP 接口（代码.市场）
    }


def probe() -> dict:
    s = requests.Session()
    result = {}
    for name, url in ENDPOINTS.items():
        try:
            r = s.get(url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            ok = r.status_code == 200 and len(r.content) > 0
            result[name] = "OK" if ok else f"FAIL(HTTP {r.status_code})"
        except requests.exceptions.SSLError:
            result[name] = "FAIL(SSL)"
        except requests.exceptions.ConnectTimeout:
            result[name] = "FAIL(超时)"
        except requests.exceptions.ConnectionError as e:
            result[name] = f"FAIL(连接: {type(e).__name__})"
        except Exception as e:
            result[name] = f"FAIL({type(e).__name__})"
        time.sleep(0.3)  # 温和限速
    return result


def check_ak() -> dict:
    try:
        import akshare as ak
    except ImportError:
        return {"_akshare不可用": "未安装"}
    out = {}
    for name in AK_API:
        out[name] = "存在" if hasattr(ak, name) else "缺失"
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("code", nargs="?", default="603365")
    ap.add_argument("--out", default=None, help="输出目录（默认: 脚本上级目录的 data/）")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else Path(__file__).resolve().parents[1] / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== 探测数据源（{time.strftime('%Y-%m-%d %H:%M')}）===")
    endpoints = probe()
    for k, v in endpoints.items():
        print(f"  [{v}] {k}")
    print("\n=== akshare 接口存在性 ===")
    aks = check_ak()
    for k, v in aks.items():
        print(f"  {v:4s} {k}")
    try:
        sym = norm_symbol(args.code)
        print(f"\n=== 符号 {args.code} ===")
        for k, v in sym.items():
            print(f"  {k}: {v}")
    except ValueError as e:
        print(f"\n符号规范化失败: {e}")
        sym = {}
    payload = {
        "探测时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "代码": args.code,
        "端点数": endpoints,
        "akshare接口": aks,
        "符号": sym,
        "结论": "以探测为 OK 的最高优先级源为准（东财>腾讯>新浪）"
    }
    (out_dir / "源探测.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {out_dir / '源探测.json'}")
