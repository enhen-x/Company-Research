# 备用模板（templates-extra）— 项目特化脚本

> 来源：`G:\理财\个股分析\SH.600941 中国移动`（2026-08-15 中报后复评）沉淀的**项目特化脚本**。
> 通用模板（`fetch_with_fallback.py / research_pipeline.py / analyze_charts.py / chart_qc.py / verification.py / extract_financials.py / fetch_peers_financials.py / fetch_supplement.py / probe_sources.py`）在 `../`，本目录只放通用模板不覆盖的场景。

## 适用场景与用法

| 脚本 | 场景 | 用法 | 关键点 |
|------|------|------|--------|
| `fetch_hk_macro.py` | A+H 双上市标的：港股日线 + 中美国债收益率 | `python fetch_hk_macro.py --dir 项目目录` | akshare 1.18.84 `stock_hk_daily` 签名=`(symbol, adjust)`，无 start_date；返回中文列名；港股新浪源 |
| `fetch_fx_hk_yield.py` | 港币汇率（央行中间价）+ 香港 10Y 政府债收益率 | `python fetch_fx_hk_yield.py --dir 项目目录` | 输出 `data/汇率_港币人民币.json`；HK 10Y 无免费稳定接口，用 TradingEconomics/HKMA 手动核对后写入 |
| `prep_cm_inputs.py` | **红筹 A+H 股**穿透回报率输入组装（中国移动类） | `python prep_cm_inputs.py --dir 项目目录` | ⚠️ `build_penetration_input.py`（通用模板）遇红筹 `SHARE_CAPITAL` 为空会算出错误市值（45.7 万亿）——红筹标的用本脚本；显式指定股本；C/D/营收用 TTM 口径 |
| `build_ops.py` | 运营补充数据 JSON 组装（`input/运营补充数据.json`） | `python build_ops.py --dir 项目目录` | 键名规范见 `analyze_charts.py` 头部；生成 segment/profitability/cashflow/peers/targets/penetration/sensitivity/forecast/pe_band/pb_band/leverage/dps |
| `run_guigui.py` | A/H 双口径穿透回报率批量重跑（k 敏感性） | `python run_guigui.py --dir 项目目录` | 包装 `calc_penetration_return.py --config`；输出 `reports/穿透回报率_输出_{A,H}{_k09}.json` |
| `dcf_cm.py` | FCFF DCF 模板（三情景 FCF 路径 + WACC×g 敏感性 + 终值占比） | `python dcf_cm.py --config input/dcf_cm_input.json`（输出 `reports/dcf_cm_output.json`） | **2026-08-15 参数化**：公司/股本/净现金/FCF 路径/WACC×g 网格全部由 --config JSON 驱动（字段见文件头部）；金额统一亿元；终值占比 ~80% 需在报告披露 |
| `summary_data.py` | 关键指标汇总（五年序列/分红/DPS/TTM） | `python summary_data.py --dir 项目目录` | 输出 `data/关键指标计算.json`，供报告引用 |
| `fetch_liquor_industry.py` | 白酒行业特有数据（批价/产量，2026-08-15 贵州茅台批次新增） | `python fetch_liquor_industry.py --dir 项目目录` | 无免费公开接口；生成 CSV 骨架 + 数据源指引，批价由 Agent WebSearch 核实后手工维护（今日酒价，区分原箱/散瓶） |

## 同步补丁（2026-08-15 已同步到官方模板）

| 模板 | 补丁 | 说明 |
|------|------|------|
| `scripts/calc_penetration_return.py` | `ii_floor` / `rf_margin` 配置项 | 原硬编码 `II=max(0.035, Rf+2%)` 只支持 A 股；现支持港股 `max(5%, Rf+3%)`、美股 `max(4%, Rf+2%)`（methodology §1），输入 JSON 加 `ii_floor`/`rf_margin` 字段 |
| `scripts/analyze_charts.py` | ①`fig_price` DataFrame `or` 真值 bug ②`fig_penetration` 四柱配色 ③✅/❌ 字形 → 达标/未达标 | ①pandas DataFrame 布尔值歧义修复 ②3 色只够 3 柱、A/H 4 柱需 4 色 ③Windows 控制台字形缺失 |

## 迭代待办（写回 skill 时注意）

- `fetch_hk_macro.py` 依赖新浪源；东财日线 ProxyError 时降级链：东财→腾讯（A股）→新浪（港股）。
- 港股 II 口径（Rf+3%）显著高于 A 股（Rf+2%），A/H 双上市标的必须双口径并列披露。
