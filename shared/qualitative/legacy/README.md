# 定性分析模块 — v1 存档（legacy）

本目录存放定性分析模块的 **v1 架构** 全部构件，仅作历史存档，**不再被任何活跃流程调用**。

## 归档内容

- **`coordinator_v1.md`**：v1 协调器，采用 agent-team 并行架构（先由脚本预分发数据，再启动多个专职 Agent 分工分析）。
- **`agents/`**：v1 的三个专职 Agent prompt——`agent_a_d1d2.md`（维度 1/2）、`agent_b_d3d4d5.md`（维度 3/4/5）、`agent_summary.md`（汇总与交叉验证）。
- **`qualitative_assessment_v1.md`**：v1 的 6 维度分析框架（667 行版本），配合上述 Agent 使用。
- **`scripts/split_data_pack.py`**：v1 的数据包预分发器，把 `data_pack_market.md` 按维度切分后分发给不同 Agent。
- **`variants/narrative/`**：v1 时期的一个叙事体（narrative）分支实验，独立维护了一套 assessment / agents / references。

## 为什么归档

自 2026-04-05 起，定性模块切换为 **v2 PDF-first 单 Agent 管线**：年报 PDF 直接载入 context，Tushare 数据仅作历史序列补充，不再需要脚本预分发，也不再拆分多个 Agent。`/business-analysis` 现在只调用 v2（`shared/qualitative/coordinator.md` + `qualitative_assessment.md`，均由原 `*_v2.md` 转正改名而来）。v1 的 agent-team 并行架构、split_data_pack 预分发器、narrative 变体分支因此全部退役。

## 溯源与删除

所有文件均通过 `git mv` 迁入本目录，完整的修改历史保留在 git log 中（`git log --follow <file>` 可追溯到原路径）。待 v2 管线稳定运行数月、确认无需回退后，本目录可整体删除。
