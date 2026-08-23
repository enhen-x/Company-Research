#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据补拉模板（B2 备用/增量）：A股日线(腾讯) + 宏观国债 + A股同行日线(腾讯) + 港股日线(新浪)。

适用场景：东财 push2his SSL 不可用或 research_pipeline 日线拉取失败时，用本脚本补齐。
来源说明（2026-08 实测）：
  - A 股日线：ak.stock_zh_a_hist_tx（腾讯源，可用，含不复权/前复权）
  - 港股日线：ak.stock_hk_daily（新浪源，可用）
  - 宏观：ak.bond_zh_us_rate（中美国债收益率，可用）
  - 东财 stock_individual_info_em / stock_info_a_code_name 不可用时，股本由财务指标 CSV 提取

用法：
    python fetch_supplement.py --dir "G:\\理财\\个股分析\\SH.601319 中国人保" \
        --code 601319 --market sh --start 20181101 \
        --peers "601318:中国平安,000858:五粮液,600519:贵州茅台"   # 同行市场前缀按代码自动推断（6/9→SH，0/3→SZ，4/8/92→BJ） \
        --hk-peers "02328:中国财险,01339:中国人保H"

输出（写入 --dir/data/）：
    日线股价.csv / 日线股价_前复权.csv / 宏观_中美国债收益率.csv /
    同行_<代码>_<名称>_日线.csv / <名称>_<H代码>_H股_日线.csv
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import akshare as ak
import pandas as pd


def p(msg: str) -> None:
    print(msg, flush=True)


def save(df: pd.DataFrame, out: Path) -> None:
    df.to_csv(out, index=False, encoding="utf-8-sig")
    p(f"[OK] {out.name}  {len(df)} 行 -> {out}")


def fetch_retry(fn, name: str, retries: int = 3, delay: float = 4.0):
    last = None
    for i in range(1, retries + 1):
        try:
            p(f"[拉取] {name}（第 {i}/{retries} 次）...")
            frame = fn()
            if frame is None or len(frame) == 0:
                raise RuntimeError("空数据")
            return frame
        except Exception as exc:
            last = exc
            if i < retries:
                time.sleep(delay)
    raise RuntimeError(f"{name} 连续失败: {last}")


def infer_market(code: str) -> str:
    """按代码推断市场前缀：6/9→SH，0/3→SZ，4/8/92→BJ"""
    c = code.strip()
    if c.startswith(("4", "8")) or c.startswith("92"):
        return "BJ"
    if c.startswith(("6", "9")):
        return "SH"
    return "SZ"

def parse_peers(s: str) -> list[tuple[str, str]]:
    """'601318:中国平安,601628:中国人寿' -> [('601318','中国平安'), ...]"""
    out = []
    for item in (s or "").split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            code, name = item.split(":", 1)
        else:
            code, name = item, item
        out.append((code.strip(), name.strip()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="数据补拉模板（日线/宏观/同行）")
    ap.add_argument("--dir", required=True, help="项目目录（含 data/）")
    ap.add_argument("--code", required=True, help="标的代码，如 601319")
    ap.add_argument("--market", default="sh", choices=["sh", "sz", "bj"], help="A股市场前缀")
    ap.add_argument("--start", default="20181101", help="日线起始日 YYYYMMDD")
    ap.add_argument("--peers", default="", help='A股同行 "代码:名称,代码:名称"')
    ap.add_argument("--hk-peers", default="", help='港股同行 "代码:名称,代码:名称"')
    ap.add_argument("--skip-daily", action="store_true", help="跳过标的自身日线")
    ap.add_argument("--skip-macro", action="store_true", help="跳过宏观国债")
    args = ap.parse_args()

    data_dir = Path(args.dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    failures = []

    if not args.skip_daily:
        for adjust, fname in [("", "日线股价.csv"), ("qfq", "日线股价_前复权.csv")]:
            try:
                df = fetch_retry(
                    lambda a=adjust: ak.stock_zh_a_hist_tx(
                        symbol=f"{args.market}{args.code}", start_date=args.start,
                        end_date="20991231", adjust=a),
                    f"{args.code} 日线(腾讯) adjust={adjust or 'none'}")
                save(df, data_dir / fname)
            except Exception as exc:
                p(f"[FAIL] {fname}: {exc}")
                failures.append(fname)

    if not args.skip_macro:
        try:
            df = fetch_retry(lambda: ak.bond_zh_us_rate(start_date="20150101"),
                             "中美国债收益率")
            save(df, data_dir / "宏观_中美国债收益率.csv")
        except Exception as exc:
            p(f"[FAIL] 宏观_中美国债收益率.csv: {exc}")
            failures.append("宏观_中美国债收益率.csv")

    for code, name in parse_peers(args.peers):
        try:
            mkt = infer_market(code)
            df = fetch_retry(
                lambda c=code, m=mkt: ak.stock_zh_a_hist_tx(
                    symbol=f"{m.lower()}{c}", start_date=args.start,
                    end_date="20991231", adjust="qfq"),
                f"{code} {name} 日线(腾讯)")
            save(df, data_dir / f"同行_{code}_{name}_日线.csv")
        except Exception as exc:
            p(f"[FAIL] 同行 {code} {name}: {exc}")
            failures.append(f"同行_{code}_{name}_日线.csv")

    for code, name in parse_peers(args.hk_peers):
        try:
            df = fetch_retry(
                lambda c=code: ak.stock_hk_daily(
                    symbol=c, start_date=args.start, adjust="qfq"),
                f"{code} {name} 日线(新浪)")
            save(df, data_dir / f"同行_{code}_{name}_日线.csv")
        except Exception as exc:
            p(f"[FAIL] 港股 {code} {name}: {exc}")
            failures.append(f"同行_{code}_{name}_日线.csv")

    p("-" * 50)
    if failures:
        p(f"[WARN] 失败 {len(failures)} 项: {failures}")
        p("提示：东财/公司概况等接口不可用时，股本/名称由 主要财务指标_按报告期.csv 提取。")
        return 1
    p("[DONE] 全部补拉完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
