# 龟龟投资策略 — 变更日志（Changelog）

> 本文件记录各版本的变更摘要。独立存档，不随 coordinator.md 加载进 context。

---

## v2.0（2026-03-30）

**主题：并行 Agent 架构 + 6大 Prompt 优化 + Thesis Card**

**目录**：`prompts_v2/`（独立于 `prompts/` v1.1，Phase 0/1/2 沿用原 prompts/）

### 架构变更
- **Phase 3 拆分为并行 Agent**：preflight → Agent A(定性) + Agent B(定量) 并行 → Agent C(估值+报告)
- **去除否决门**：所有因子输出客观评估，由 Agent C 做最终裁决
- **总执行时间**：从 ~30分钟降至 ~25分钟（得益于并行）

### D1: 角色隐喻化
- Coordinator → 项目经理
- Pre-flight → 审计助理
- Agent A → 行业研究员（CFA）
- Agent B → 量化分析师（CPA）
- Agent C → 首席分析师（最终裁决权）

### D2: 条件加载
- **新增 market_rules_hk.md**：港股特别规则（HKFRS/审计/分部），仅 .HK 时加载
- **新增 market_rules_us.md**：美股特别规则（60%覆盖/降级），仅 .US 时加载
- A股分析不加载额外文件，context 节省 ~200 行

### D3: 模板去重
- v2 架构拆分 Agent 已自然减少重复
- shared_tables.md 沿用并确保包含完整税率表+跨币种规则

### D4: 指令压缩
- coordinator.md AskUserQuestion 沿用原规则引用（-70行）
- Sub-agent 调用模板化（-100行）

### D5: Few-shot 示例 + 参数 Schema
- **新增 judgment_examples.md**：G系数(6例)/护城河(5例)/分配意愿(3级)/MD&A可信度(3级)/λ可靠性(3级)
- **新增 factor_interface.md**：Pre-flight→A/B(14参数), A→C(14参数), B→C(25参数) 显式 schema + 输出校验块

### D6: Thesis Card（报告新章节）
- **第十章：投资论点卡** 加入 Agent C 报告输出
  - 10.1 投资论点摘要（核心论点+买入理由+催化剂+持有周期）
  - 10.2 基本面止损条件（7项结构化规则 critical/warning + 自然语言条件 + 检查频率）
  - 10.3 事件监控清单（搜索关键词 + 9类事件优先级）
  - 10.4 行业与宏观监控（行业关键词 + 竞争对手 + 4维宏观关注）

**新建文件**：market_rules_hk.md, market_rules_us.md, judgment_examples.md, factor_interface.md
**修改文件**：coordinator.md, phase3_preflight.md, phase3_qualitative.md, phase3_quantitative.md, phase3_valuation.md

---

## v1.1（2026-03-30）

**主题：Prompt 质量优化 — 17 项改进（一致性、完整性、报告质量）**

- **新增 shared_tables.md**：支付率计算、股息税率表、门槛公式、跨币种处理规则集中管理，消除因子2/3间重复
- **新增否决门总览**：Phase 3 执行器前置展示全部 9 个否决门（Rejection Map）
- **新增分析置信度**：报告执行摘要增加数据完整性+外推可信度+Warnings影响三维评级
- **新增关键假设汇总**：报告模板增加影响结论的 6 项核心假设及其敏感性
- **新增数据约定**：金额单位转换表统一管理，Phase 1/2 交叉引用
- **新增 Phase 0 重试规则**：3次指数退避重试，失败后明确进入无 PDF 模式
- **新增阶段超时规则**：各 Phase 最大执行时间和超时行为
- **新增 Phase 3 数据澄清回流**：Phase 3 可触发最多1次补充 WebSearch
- **新增 WebSearch 批量策略**：Phase 1B 按依赖关系分4批执行，减少搜索次数
- **新增季节性行业清单**：Phase 3 年化估算时高季节性行业显式警告
- **新增商誉减值分级**：>30% 降仓50%，20-30% 标注+交叉验证
- **新增控股折价异常处理**：折价 >60% 或溢价时的明确行动规则
- **新增 Factor 2 分配能力独立性说明**：明确与因子1B模块六的独立关系
- **新增 Growth Capex 方法论对比说明**：因子2 G系数 vs 因子3全额扣除的设计意图
- **新增 MD&A 来源验证**：因子1B模块八根据来源（PDF/WebSearch/缺失）设置可信度基线
- **新增美股数据覆盖表**：明确约 60% 覆盖率和各字段降级方案

**修改文件**：coordinator.md, phase1, phase2, phase3, factor1-4, CLAUDE.md + 新建 shared_tables.md
**测试**：766 passed, 1 test updated (tax table → shared_tables cross-ref)

---

## v1.0（2026-03-07）

**主题：v0.16_alpha → v1.0 架构重构**

- **新增 Phase 0**：内置 `/download-report` 命令，自动搜索并下载年报 PDF
- **Phase 1 拆分两步**：Step A = `tushare_collector.py`（Python 脚本采集结构化数据）+ Step B = Agent WebSearch（非结构化信息）
- **Phase 2 拆分两步**：Step A = `pdf_preprocessor.py`（Python 关键词定位 7 章节：P2-P13 + MDA + SUB）+ Step B = Agent 精提取（5+1 项 footnote 数据，SUB 条件触发）
- **Pipeline 重排**：Phase 1A + Phase 2A 并行运行；Phase 1B 在 Phase 1A 完成后立即启动（§10 到达时检查 pdf_sections.json）
- **单位统一**：所有金额单位为 **百万元**（Tushare 原始单位元 ÷ 1e6）
- **新增母公司报表**：§3P/§4P 母公司损益表和资产负债表（Tushare `report_type=4`）
- **yfinance 保留为 fallback**：Tushare 失败时降级使用
- **AskUserQuestion 交互**：结构化收集持股渠道、PDF 处理方式、Tushare Token 等
- **渐进式披露**：Phase 3 精简执行器 + references/ 按需加载
