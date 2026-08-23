#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇率与香港国债收益率探测（B2 补充）：尝试 akshare 币种接口 + 输出参考值
用法: python fetch_fx_hk_yield.py --dir 项目目录
输出: data/汇率_港币人民币.json + 控制台
"""
import argparse
import json
from pathlib import Path

import akshare as ak
import pandas as pd

def try_fn(fn):
    try:
        df = fn()
        if df is not None and len(df) > 0:
            return df
    except Exception as exc:
        return f"FAIL: {exc}"
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    out = {}
    for name, fn in [
        ("currency_boc_safe", lambda: ak.currency_boc_safe(symbol="港币", start_date="20260801", end_date="20260815")),
        ("currency_boc_sina", lambda: ak.currency_boc_sina(symbol="港币", start_date="20260801", end_date="20260815")),
        ("currency_hist", lambda: ak.currency_hist(symbol="港币", start_date="20260801", end_date="20260815")),
    ]:
        r = try_fn(fn)
        if isinstance(r, pd.DataFrame):
            rec = r.tail(3).copy()
            for c in rec.columns:
                if pd.api.types.is_datetime64_any_dtype(rec[c]) or rec[c].dtype == object:
                    rec[c] = rec[c].astype(str)
            out[name] = rec.to_dict("records")
            print(f"[OK] {name}: {r.tail(2).to_string()}")
        else:
            out[name] = r
            print(f"[--] {name}: {r}")
    data_dir = Path(args.dir) / "data"
    (data_dir / "汇率_港币人民币.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
