#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中国移动补充数据：H股(00941)日线(新浪) + 中美国债收益率（B2 补拉）
用法: python fetch_hk_macro.py --dir "项目目录"
输出: data/HK0941日线.csv / HK0941日线_前复权.csv / data/宏观_中美国债收益率.csv
"""
import argparse
import sys
import time
from pathlib import Path

import akshare as ak
import pandas as pd

def p(msg: str) -> None:
    print(msg, flush=True)

def retry(fn, name, tries=3, delay=4.0):
    last = None
    for i in range(1, tries + 1):
        try:
            p(f"[拉取] {name}（第 {i}/{tries} 次）...")
            df = fn()
            if df is None or len(df) == 0:
                raise RuntimeError("空数据")
            return df
        except Exception as exc:
            last = exc
            if i < tries:
                time.sleep(delay)
    raise RuntimeError(f"{name} 连续失败: {last}")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    data_dir = Path(args.dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    fails = []
    for adj, fname in [("", "HK0941日线.csv"), ("qfq", "HK0941日线_前复权.csv")]:
        try:
            df = retry(lambda a=adj: ak.stock_hk_daily(symbol="00941", adjust=a), f"00941 H股日线 adjust={adj or 'none'}")
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df[df["date"] >= "2010-01-01"]
            df.to_csv(data_dir / fname, index=False, encoding="utf-8-sig")
            p(f"[OK] {fname} {len(df)} 行")
        except Exception as exc:
            p(f"[FAIL] {fname}: {exc}")
            fails.append(fname)
    try:
        df = retry(lambda: ak.bond_zh_us_rate(start_date="20150101"), "中美国债收益率")
        df.to_csv(data_dir / "宏观_中美国债收益率.csv", index=False, encoding="utf-8-sig")
        p(f"[OK] 宏观_中美国债收益率.csv {len(df)} 行")
    except Exception as exc:
        p(f"[FAIL] 宏观: {exc}")
        fails.append("宏观")
    p("-" * 50)
    if fails:
        p(f"[WARN] 失败: {fails}")
        return 1
    p("[DONE]")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
