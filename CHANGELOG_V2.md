# Changelog — 龟龟投资策略 v2

> 本文件记录 v1.1 → v2 的所有变更。当前版本：**v2.1-beta**

---

## P3 增补 (2026-08-15) — AA 经营性质异常规则（贵州茅台校准）

2026-08-15 贵州茅台批次暴露：2025 渠道切换致结余 -33%，原 AA 切换规则仅覆盖一次性损益/大额投融资，未覆盖经营性质结构性变化。

### 规则要点（references/methodology.md §2）

- 经营性质结构性变化（渠道切换、业务重组、会计口径变更、大额减值）致结余同比变动 >±30% → 触发 AA 口径复核
- 先判定异常类型（一次性 vs 经营结构性），再选择 AA_all / 剔除异常年 / 保留 AA_2y 并说明
- **联动 §4 λ 协议**：结构变化年同时扭曲 Δ结余/Δ收入，λ 需剔除该年重估，仍不可靠则 λ=0 兜底
- 报告 Warnings 必须标注 AA 口径选择依据

### 落地文件

- `references/methodology.md` §2（AA 逐年计算）、版本注记 v2.3
- turtle-analysis 副本同步；批次台账迭代日志登记
## P2 增补 (2026-08-15) — λ 失效处理协议（贵州茅台校准）

2026-08-15 贵州茅台批次暴露：λ=3.99（逐年符号不一致，2025 渠道切换致结余 -33%）导致收入敏感性表失真、k*=1.014 失效。

### 协议要点（references/methodology.md §4）

- 触发降级（任一）：λ 逐年符号不一致；|λ|>1.5（需逐项解释）；最近年份结余受结构性/一次性因素扭曲
- 处理流程：剔除异常年重估 λ' → 仍不可靠则 **λ=0 重估**（结余不随收入变动，保守口径），敏感性表以 λ=0 版为准输出，原始 λ 版仅参考
- k* 失效情形：λ=0 无定义不输出；k*≥1 → 输出「现金口径回报率已低于门槛，无正收入下滑空间」定性表述；λ 不可靠仅定性解读
- 敏感性表头必须标注「λ 可靠性低（原因），已按 λ=0 重估」

### 落地文件

- `references/methodology.md` §1（k* 失效行）/ §4（协议+贵州茅台案例）、版本注记 v2.2
- 批次台账迭代日志登记（SH.600519 贵州茅台 2026_08_15）
## P1 增补 (2026-08-15) — 净利润打折口径主指标轮

按视频教程口径新增**净利润打折口径穿透回报率 R\* = C×k×M/市值**作为主估值输入，原现金口径 GG=AA×M/市值 降为校验口径。

### 口径变更

- 新增利润折扣系数 k（默认 0.8；可预测性 高→0.9 / 中→0.8 / 低→0.7，保守方向取小值），对应视频“可线性外推利润还要打折扣（五粮液打8折）”理念
- 主穿透回报率 **R\* = C×k×M/市值**（主估值输入）；**GG = AA×M/市值** 降为现金校验（验证 R\* 有真钱支撑）
- 现金校验偏差 **Δc = R\* − GG**：≥2pct → 现金验证失败，有效口径降级为 GG
- 有效口径 **R_eff**（默认 R\*，降级时 = GG）：安全边际 JJ/KK、目标买入价、门槛价格、仓位全部基于 R_eff
- 情景敏感性表保留现金口径 GG(k) 作校验维度（主口径 R\* 不随收入情景变动）；账面口径 R=C×M/市值 仅作交叉校验

### 凌霄示例重算

- R\*=5.28%（454.91×0.8×0.8423/5805.19），Δc=−0.99pct，KK=1.63pct
- 目标买入价 23.48 元、门槛价格 11.22 元（旧值 27.88/9.45 已全量替换）

### 落地文件

- `scripts/calc_penetration_return.py`（R\*/Δc/R_eff 全链路 + G 网格 + `--selftest`）、`scripts/build_penetration_input.py`（k 判断点）
- `references/methodology.md` §1/§2/§7/§10/§12、`references/report-template.md` 附2/附4/附5/附6、factor2/3/4、phase3 定量与估值 prompt
- §17.11 网格（表A→R\*、表B 新增 Δc/R_eff 列）、`derived_metrics.py`、`akshare_collector.py` 降级输出
- 两套 skill（guigui-valuation-report / turtle-analysis）全量同步，pytest 920 passed / 3 skipped

## v2.1-beta (2026-07-04) — 全面优化轮

一轮跨四轨的速度/精度/流程优化（计划与审计由 Fable 主持，实现由 Opus 子代理完成）。

### 速度：数据管线（feat(perf) b1b83d3）

- 财报类接口（income/balancesheet/cashflow/dividend/fina_indicator 等 20 个）新增 TTL 磁盘缓存：财务 7 天、weekly/yc_cb 24 小时；daily/daily_basic/\*_basic 永不缓存。缓存实现抽取为共享 `scripts/cache_utils.py`（ScreenerCache），筛选器 re-export 兼容
- §13 警告区块改读 `_store`，消除 A 股路径 5 次重复 API 调用
- 限速改为 `TUSHARE_RATE_DELAY` env 可配置（默认 0.5s 不变）；缓存命中不触发限速 sleep
- 新 CLI：`--no-cache` / `--cache-refresh`（财报季 4/8/10 月建议刷新）；valuation_engine 镜像 `--no-cache`
- **实测 600887.SH：冷跑 25.9s → 暖跑 5.7s**，输出逐字节一致（仅时间戳）

### 精度：VIP 中继行序防御（fix(tushare) 258fd8e）

- 发现券商 VIP 中继返回价格行为**最旧在前**（标准 Tushare 为最新在前），导致 §1 显示 1996 年上市首日股价/市值、§2 "最新收盘价"为一年前数据，污染所有市值依赖指标
- `get_basic_info` / `get_market_data`（A股/HK/US 四处）防御性 newest-first 排序 + 回归测试

### 精度：龟龟 §17.10-13 预计算网格（feat(turtle) b3641be）

- §17.10 支付率 M 三重交叉校验（法1 DPS/EPS、法2 现金流、法3 §17.1）+ Python 内裁定 M_rec
- §17.11 税后 R/GG 网格（M候选 × 税率情景 × AA变体），含 HH、GG−II、**目标买入价**列
- §17.12 G 系数网格（0.7-1.8 × 12 档，H/OE 逐行预算）；§17.13 λ 收入敏感性 + 临界收入倍数
- Agent B（phase3_quantitative.md）改为**查表选行 + 说明理由**，新约束 #9"有网格时不做数学"；手算公式保留为降级路径
- factor_interface 新增 target_buy_price / M_source / GG_source

### 精度：定性模块 11 杠杆 P0+P1（feat(qualitative) 1a3c275）

- 杠杆 1：`scripts/quality_control.py` → `computed_metrics.md`（CM§1-5：亿元对照/同比/多年统计/分红率/PE 估值链），LLM 只引用不重算
- 杠杆 2：`[src: ...]` 溯源标注语法 + 材料性规则 + 必备 `## 数字溯源汇总` 节
- 杠杆 5：clean-room 独立重算 agent（与分析并行、禁读草稿、防锚定 + 防注入）
- 杠杆 6：`scripts/report_consistency.py` 跨段数值冲突扫描 + `--gates` 硬门槛校验
- 杠杆 3：numeric_audit 审计门（severity 评级、原文→修正对、AUDIT_RESULT 门控、修复环 max 1 次）
- 杠杆 7：output_schema v1.2 交付硬门槛 + DELIVER ONLY 禁项
- 杠杆 8：`writing_style_rules.md` 权威化（lead-with-numbers、模糊量化词禁用表、**正文单位切换为亿元**、参数表保持百万元）
- 杠杆 9：`industry_metrics_lookup.md` 36 行业关键指标锚点
- 杠杆 4/10/11（P2）遗留未实施

### 流程：v1 存档 + 引用修复（refactor(v2) e69f26d）

- v1 定性模块（agent-team 并行架构 + narrative 变体 + split_data_pack.py）→ `shared/qualitative/legacy/`
- v2 转正改名：coordinator_v2.md → coordinator.md、qualitative_assessment_v2.md → qualitative_assessment.md
- turtle 孤儿归档：phase3_preflight.md、phase1_数据采集.md → `strategies/turtle/legacy/`
- 修复 stale 引用：turtle-analysis 命令 Step 3.0、SKILL.md 入口与流程、PDF 文件名约定统一

### 测试

- 时间炸弹修复：`other_data.py` 抽出可冻结的 `_now()`，TestRepurchase 冻结时钟（fixture 永不过期）
- 测试规模：597 → **920 全绿**（新增缓存/网格/质量脚本/行序防御/prompt 断言共 ~130 项）

---

## v2_beta (2026-04-05)

### PDF-first 架构升级

business-analysis 从 WebSearch-first 升级到 PDF-first 数据流：

- 年报 PDF 作为主数据源，直接载入 1M context，Tushare 仅作历史序列补充
- 单 Agent 模式取代 v2_alpha 的多 Agent 并行拆分（Agent A/B/C + Summary）。实测单 Agent 在交叉验证上更优，所有维度共享同一 context 消除信息孤岛
- 新增 PDF 本地缓存检查：下载前先 glob `output/{code}_{company}/` 中已有 PDF，避免重复下载
- 新增 `coordinator_v2.md` + `qualitative_assessment_v2.md`

### Turtle 策略 Pre-flight 合并

将独立的 `phase3_preflight.md`（数据校验+口径锚定）合并进 `phase3_quantitative.md` 的 Step 0：

- Pipeline 从 3 个串行 Agent（Pre-flight → Agent B → Agent C）缩减为 2 个（Agent B 含 Step 0 → Agent C）
- 每次分析预计节省 2-3 分钟（消除 1 次 Agent 启动 + 9 次文件读取 + 1 次文件写入）
- `phase3_valuation.md` 不再依赖独立的 `phase3_preflight.md`，从 Agent B 输出读取基础信息
- `phase3_preflight.md` 保留为文档参考，不再被 pipeline 调用

### 新增独立估值模块

- `/valuation` slash command：独立于龟龟策略的通用估值分析
- `scripts/valuation_engine.py`：DCF / DDM / 可比估值 / Graham 四种方法
- `strategies/valuation/`：coordinator + phase2_valuation + 参考文件（方法论/分类规则/模板/示例）

### Tushare 模块增强

- `assembly.py`：新增 §17 衍生指标预计算（Factor 2/3/4 加速）
- `--refresh-market` 模式：仅刷新 §1/§2/§11/§14（增量更新，<5秒）
- `financials.py` / `infrastructure.py`：minor fixes
- `report_to_html.py`：支持 `--standalone` 内嵌 CSS 模式
- `tests/test_refresh_market.py`：新增 refresh-market 测试覆盖

### 测试

- 新增 `test_refresh_market.py`：refresh-market 模式测试覆盖
- 总测试数：792（v2_alpha 时为 769）

### 实战验证

完成两只标的的端到端全流程（business-analysis + turtle-analysis）：

| 标的 | 结论 | 关键发现 |
|------|------|---------|
| 美的集团 (000333) | Observe 30% | Gross R 5.69% > 门槛，GG 3.53% < 门槛（SGA proxy 驱动的保守偏差），KUKA 商誉 34.3B 为潜在风险 |
| 海尔智家 (600690) | Observe 50% | 股价低于地板价 7.4%，零价值陷阱信号，但毛利率连降 5ppt + AR 增速远超营收需警惕 |

---

## v2_alpha (2026-03-31)

### 架构重构：模块化拆分

**从 `prompts_v2/` 到 `shared/` + `strategies/`**

v1.x 所有内容（数据采集、preflight、定性、定量、估值）耦合在 `prompts_v2/` 中。v2 将定性分析独立为通用模块：

- `shared/qualitative/` — 通用定性分析模块（6维度商业质量评估）
  - 可独立运行（`/business-analysis` 命令）
  - 可被龟龟策略调用（替代原 phase3_qualitative.md）
  - 可被烟蒂策略、未来其他投资框架调用
- `strategies/turtle/` — 龟龟策略专属模块
  - 数据采集（phase1/phase2）
  - Preflight 数据校验
  - 穿透回报率计算（phase3_quantitative.md）
  - 估值与报告组装（phase3_valuation.md）
- `prompts_v2/` 已删除，文件迁移至上述两个目录
- `prompts/` 保留为 v1 只读遗留

**新增文件**：
| 文件 | 用途 |
|------|------|
| `shared/qualitative/coordinator.md` | 独立定性分析入口 |
| `shared/qualitative/qualitative_assessment.md` | 6维度分析 prompt |
| `shared/qualitative/data_collection.md` | 轻量级 WebSearch 指令 |
| `shared/qualitative/references/output_schema.md` | 结构化参数输出 schema (v1.1) |
| `shared/qualitative/references/framework_guide.md` | 框架说明固定附录 |
| `.claude/commands/business-analysis.md` | `/business-analysis` 命令 |

**变更文件**：
| 文件 | 变更 |
|------|------|
| `strategies/turtle/coordinator.md` | 路径引用从 `{prompts_v2_dir}` 改为 `{shared_dir}` + `{strategy_dir}` |
| `strategies/turtle/references/factor_interface.md` | 新增 shared output_schema 引用和 moat_rating 映射说明 |
| `.claude/commands/turtle-analysis.md` | 入口从 prompts/coordinator.md 改为 strategies/turtle/ |
| `CLAUDE.md` | 反映新目录结构 |

---

### 护城河分析框架升级

**维度二（D2）重大扩展**，灵感来源：太阳纸业护城河深度分析 + Greenwald 竞争优势理论

v1 的 D2 仅有定性的非技术/技术双层护城河评估。v2 扩展为6步结构化分析：

| 步骤 | 新增内容 | 来源灵感 |
|------|---------|---------|
| 2.1 行业地图 | 先定义竞争战场：细分市场、进入壁垒表（5类）、CR4 | Greenwald |
| 2.2 量化验证 | ROE vs 门槛（8/15/25%）、份额稳定性、低谷韧性 | Greenwald |
| 2.3 双框架分析 | 框架A（非技术+技术双层）+ 框架B（供给侧/需求侧/规模经济） | 新增 Greenwald 三维 |
| 2.4 虚假优势辨析 | 品牌≠护城河、运营效率≠结构壁垒等 | 太阳纸业案例 |
| 2.5 竞争对手对比 | vs 前2-3名对手逐维度对比表 + 差距可持续性 | 太阳纸业案例 |
| 2.6 可持续性与监控 | 护城河监控锚点（3个KPI，含当前值和警戒线） | 太阳纸业案例 |

**新增结构化参数**：14个（market_cr4, entry_barrier, roe_5y_avg, moat_existence, moat_framework_primary, supply/demand/scale_ratings, false_advantages, competitor_ranking, advantage_gap_sustainability, moat_sustainability, moat_monitor_kpis）

**judgment_examples.md 拆分**：
- 通用锚点（护城河、MD&A、管理层 + Greenwald 三维示例 + 虚假优势辨析）→ `shared/qualitative/references/`
- 龟龟专属锚点（G系数、分配意愿、λ可靠性）→ `strategies/turtle/references/`

---

### 报告可读性与输出格式

**可读性改进**：
- 新增 **执行摘要**（报告开头半页，结论先行 + 关键指标表）
- 新增 **深度总结与投资启示**（报告末尾2-3页：商业模式本质、优劣势归因表、竞争定位、投资者启示、监控锚点展开、催化剂与风险事件、一句话最终结论）
- 写作风格指令：结论先行、重点加粗、通俗表达、去重、逻辑过渡
- 每个维度开头用加粗一句话结论引导

**HTML 仪表盘报告**：
- `scripts/report_to_html.py`：MD → HTML 转换（Markdown + Jinja2）
- `shared/qualitative/templates/dashboard.html`：IBM Plex 字体、暖色调浅底 + 自动暗色模式、语义色彩标签（绿/琥珀/红）、KPI 卡片、Verdict 横幅、折叠式附录
- 双输出：MD（策略消费）+ HTML（人类阅读 / 打印 PDF）

**固定附录**：
- `shared/qualitative/references/framework_guide.md`：Greenwald 框架说明、飞轮护城河概念、评级标准定义表、量化验证门槛

---

### Agent Team 并行架构

将单 Agent 串行改为多 Agent 并行，提升效率并降低 context 压力：

```
Step 3.0: split_data_pack.py → 按维度切割数据子集 + D6 触发检查
Step 3.1: 并行执行
  Agent A: D1(商业模式) + D2(护城河)  ← 最重的维度，合并消除依赖
  Agent B: D3(外部环境) + D4(管理层) + D5(MD&A)  ← 天然独立
  Agent C: D6(控股结构)  ← 条件触发，大概率跳过
Step 3.2: Summary Agent → 执行摘要 + 深度总结 + 报告组装
Step 4: report_to_html.py → HTML 仪表盘
```

**新增文件**：
| 文件 | 用途 |
|------|------|
| `scripts/split_data_pack.py` | 确定性数据预分发 + D6 触发检查 |
| `shared/qualitative/agents/agent_a_d1d2.md` | Agent A prompt（D1+D2） |
| `shared/qualitative/agents/agent_b_d3d4d5.md` | Agent B prompt（D3+D4+D5） |
| `shared/qualitative/agents/agent_summary.md` | Summary Agent prompt |
| `shared/qualitative/agents/writing_style.md` | 共享写作风格前置指令 |

---

## 待完成（v2_rc 路线图）

### 定性模块
- [x] ~~Agent Team 端到端测试与调优~~ → 改为单 Agent 模式（v2_beta）
- [ ] D2 护城河分析的边界案例处理（如 platform 型企业的框架选择）
- [ ] HTML 模板增加 bar chart（利润率趋势可视化）和 signal dots（风险信号矩阵）

### 龟龟策略（strategies/turtle/）
- [x] coordinator.md 调度改为引用 shared 定性模块（v2_beta 已完成）
- [x] phase3_preflight 合并进 phase3_quantitative Step 0（v2_beta）
- [x] 端到端 `/turtle-analysis` 测试 — 美的集团 + 海尔智家（v2_beta）
- [ ] W2 员工支出 SGA proxy 偏差优化（当前驱动 HH 偏差过大）
- [ ] Agent B + Agent C 进一步合并可行性评估

### 估值模块（strategies/valuation/）
- [x] 新增独立 `/valuation` 命令 + valuation_engine.py（v2_beta）
- [ ] 端到端测试与调优

### 烟蒂策略（strategies/cigarbutt/）
- [ ] 创建 cigarbutt coordinator + 策略专属 prompt
- [ ] 接入 shared 定性模块
- [ ] 端到端 `/cigarbutt-analysis` 测试

---

## 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v1.0 | — | 初始版本：6-phase pipeline, 4 factors |
| v1.1 | — | 17 improvements across 9 files, shared_tables, HK/US support |
| v2.0-alpha | 2026-03-31 | 模块化拆分 + Greenwald 护城河框架 + HTML 仪表盘 + Agent Team |
| v2.0-beta | 2026-04-05 | PDF-first + 单Agent + Pre-flight合并 + 估值模块 + 实战验证 |
| v2.1-beta+P1 | 2026-08-15 | 净利润打折口径主指标 R\*=C×k×M/市值（GG 降为现金校验，Δc≥2pct 降级）；R_eff 驱动 JJ/KK/买入价/门槛价/仓位；凌霄重算 23.48/11.22 |
| v2.1-beta | 2026-07-04 | TTL缓存(冷25.9s→暖5.7s) + §17.10-13网格 + 定性审计门(P0+P1杠杆) + v1存档 + VIP行序防御 + 920测试全绿 |
