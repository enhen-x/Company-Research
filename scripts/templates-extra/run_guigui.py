#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行 guigui 穿透回报率计算器（A/H 双市场 + k 敏感性），JSON 输出写入 reports/
用法: python run_guigui.py --dir 项目目录
输出: reports/穿透回报率_输出_A.json / _H.json / _A_k09.json（k=0.9 敏感性）
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    root = Path(args.dir)
    calc = root / "scripts" / "calc_penetration_return.py"
    input_dir = root / "input"
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")

    jobs = [
        ("穿透回报率_输出_A.json", input_dir / "穿透回报率_输入_A.json", None),
        ("穿透回报率_输出_H.json", input_dir / "穿透回报率_输入_H.json", None),
        ("穿透回报率_输出_A_k09.json", input_dir / "穿透回报率_输入_A.json", 0.9),
        ("穿透回报率_输出_H_k09.json", input_dir / "穿透回报率_输入_H.json", 0.9),
    ]
    for out_name, cfg_path, k in jobs:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        if k is not None:
            cfg["profit_discount_k"] = k
        tmp = cfg_path.with_name(cfg_path.stem + "_tmp.json")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        r = subprocess.run([sys.executable, str(calc), "--config", str(tmp), "--json"],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        if r.returncode != 0:
            print(f"[FAIL] {out_name}: {r.stderr[-800:]}")
            continue
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError as exc:
            print(f"[FAIL] {out_name} JSON解析失败: {exc}; stdout 前200字符: {r.stdout[:200]}")
            continue
        (reports / out_name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        # 摘要（读主表）
        main = data.get("main", data)
        print(f"[OK] {out_name}: {str(main)[:600]}")
    print("[DONE]")

if __name__ == "__main__":
    main()
