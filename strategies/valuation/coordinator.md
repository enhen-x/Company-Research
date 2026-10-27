# 独立估值计算协调器（V3适配）

本模块是可选计算入口。V3常规调研继续使用同一批次的 data/input/reports 和十章主报告；不要求先生成旧版商业分析报告，也不另建 output 目录或平行主报告。先读 `references/research-topics.md` 和 `references/估值方法详解.md` 选择行业主方法与交叉方法。19类行业配置负责适用性路由，不能解释为19套完整数值引擎。

## 1. 复用已有输入

先检查本批次的 `input/研究模型.json`、`reports/研究模型_输出.json`、现有估值计算及原始披露。专题脚本可复算经营驱动、现金桥及选型规则，不能将订单总额或管理层目标直接当作收入与独立预测。已存在并可核验的计算优先引用，不重复抓取同一份财务数据。

`scripts/valuation_engine.py --dir <批次>` 可离线复用已验证来源与标的的 A 股 B2 CSV，通过 `valuation_snapshot.py` 适配已支持的东财三表、财务指标及概况/行情/分红格式，不读取Token、不导入供应商、不联网。未知来源、单位、币种、标的或格式拒绝推断；缺失债务或现金流项目仍保留缺失。港美股、其他CSV格式和行业专用引擎尚未接入这一适配。旧 `--code/--output-dir` 供应商入口保留兼容，仅在当前批次确无数据且需要受支持方法时使用，不为运行该入口重复生成数据包。特殊行业没有实现的NAV、AFFO、寿险EV等，需引用单独可复算的计算与证据；禁止强套一般工业DCF。

## 2. 显式现金流契约

需要独立引擎的DCF/EPV/反向DCF时，将本次估值约定保存在批次唯一 `input/估值口径.json`，通过 `--contract` 读取。至少明确：

- `cashflow_basis`: FCFF或FCFE；`currency`: CNY/HKD/USD；`amount_unit`: raw或million。
- `discount_rates`: `wacc_pct` / `ke_pct`（百分数，如8表示8%）与 `evidence_id`。FCFF对应WACC，FCFE对应Ke。
- FCFF的 `equity_bridge` 明确 cash、debt、other_equity_adjustment、evidence_id；FCFE必须 `cashflow_scope=parent_common`，不能重复加现金减债务。
- `historical_source=explicit` 时提供 `historical_cashflows`，每项含 period、value、evidence_id；provider/ocf路径必须满足实现中的口径校验。OCF路径还需显式 `ocf_interest_classification` 及逐期 `ocf_adjustments`，不能默认经营现金流减资本开支就是FCFF。
- `stable_growth_pct` / `terminal_growth_pct`；终值增长率必须低于对应折现率。三情景提供 optimistic/base/pessimistic，各含 cashflows、probability、evidence_id，不以净利润增长率代替现金流预测。

缺少口径或关键数值返回 INSUFFICIENT_DATA，保留限制，不补零或自动猜测。财务费用净额不能替代费用化利息；EBITDA采用税前利润＋明确利息＋折旧摊销。

## 3. 执行与结果核对

```powershell
python <skill>/scripts/valuation_engine.py --dir <批次> --contract input/估值口径.json --total-timeout 180
```

外层在导入供应商与数据处理库之前启动180秒硬预算，终止超时进程树；失败保留已有结果但不能标记本轮更新成功。唯一辅助输出 `reports/valuation_computed.md` 同内容不重复改写。不递归重试；缺口应回到原始披露与输入契约。

核对计算采用的期间、币种、股本、现金流范围、债务及少数股东权益。情景和概率必须来自本次独立假设，不能事后选择最接近现价的情景。定性调整须写明证据、变更参数与重算结果，禁止用文字覆盖脚本数值。

`reverse_valuation.five_year_dcf` 与稳定DCF共用五年现金流路径、折现函数和FCFF/FCFE价值桥，仅固定其他条件反解初始增长率；必须显式给出 `terminal_growth_pct`。`reverse_growth_bounds_pct` 可设两个有序增长边界，默认[-99,300]，最多100次二分，不自动扩界。越界/未收敛分别显示 `NO_SOLUTION` / `NO_CONVERGENCE`，输出正算重建值及误差。Gordon永续反解仍单列为稳态诊断，不解释为五年驱动或多变量反解。该能力不替代银行、矿山或订单转化的行业专用反向模型。

## 4. 回填原章节

结果写入原 §6.1–§6.4，与 §5 的经营预测勾稽，更新 §1 摘要、§7 双轨结论、§8 触发阈值及 §9 反方验证。各章、各小节和图号保持 `references/report-template.md` 原结构。报告引用实际计算路径及数据限制。

完成后使用本批次 `scripts/gate_all.py`，必要时加 `--require-research`；技术PASS与专题结构检查不等于人工投资判断已完成。完整交付规则以 `references/flow-contract.md` 为准。
