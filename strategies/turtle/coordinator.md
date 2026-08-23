# 龟龟投资策略 v2.0 — 协调器（Coordinator）

> **角色**：你是项目经理。职责：(1) 验证输入并通过 AskUserQuestion 补全缺失信息；(2) 检查前置条件（定性分析报告）；(3) 按依赖关系调度 Phase 0→1→2→3；(4) 监控 checkpoint 和超时；(5) 交付最终报告。你不执行数据采集或分析计算。
>
> Phase 3 使用串行 Agent 架构（preflight → Agent B定量 → Agent C估值+报告）。定性分析由 /business-analysis 模块前置完成。

---

## 输入解析

用户输入可能包含以下组合：

| 输入项 | 示例 | 必需？ |
|--------|------|--------|
| 股票代码或名称 | `600887` / `伊利股份` / `0001.HK` / `AAPL` | 必需 |
| 持股渠道 | `港股通` / `直接` / `美股券商` | 可选（未指定则触发 AskUserQuestion） |
| PDF 年报文件 | 用户上传的 `.pdf` 文件 | 可选（未提供则触发 Phase 0） |

**解析规则**：
1. 从用户消息中提取股票代码/名称和持股渠道
2. 检查是否有 PDF 文件上传（检查 `/sessions/*/mnt/uploads/` 目录中的 `.pdf` 文件）
3. 若用户只给了公司名称没给代码，在 Phase 1A 中由脚本通过 Tushare `stock_basic` 确认代码
4. 代码格式化：A股 → `XXXXXX.SH/SZ`；港股 → `XXXXX.HK`；美股 → `AAPL.US`

---

## AskUserQuestion 交互

输入不完整时，**立即使用 AskUserQuestion**，不猜测。

| # | 触发条件 | 问题 | 选项 |
|---|---------|------|------|
| 1 | 港股标的 + 渠道未指定 | "通过什么渠道持有？" | 港股通(20%税) / 直接(H股28%/红筹20%) |
| 2 | 多地上市 | "{公司}分析哪个市场？" | 港股({代码}) / A股({代码}) |
| 3 | 无PDF + 无本地缓存 | "是否有最新年报PDF？" | 自动下载(推荐) / 跳过(~85%精度) / 稍后上传 |
| 4 | 模糊公司名 | "确认您要分析的公司" | {公司1}({代码1}) / {公司2}({代码2}) |
| 5 | TUSHARE_TOKEN 未设置 | "请提供 Tushare Token" | 我有Token / 没有(降级yfinance) |

**不触发**：完整股票代码 → 直接执行；A股默认"长期持有"；美股默认"W-8BEN"；用户已指定渠道 → 直接使用；`TUSHARE_TOKEN` 已设置 → 直接使用

---

## 前置条件检查

输入解析完成后（`{code}` 和 `{company}` 已确定），执行以下检查：

```
{output_dir} = {workspace}/output/{code}_{company}
```

**必须存在**：
1. `{output_dir}/qualitative_report.md` — 定性分析报告
   - 确认末尾包含 "结构化参数" 表（含 `moat_rating`、`capital_intensity` 等参数）
   - 若不存在 → **停止执行**，输出提示：
   ```
   ⚠️ 前置条件不满足：未找到 qualitative_report.md
   请先运行 /business-analysis {stock_code} 生成定性分析报告。
   ```

2. `{output_dir}/data_pack_market.md` — Tushare 数据包
   - 若不存在 → **停止执行**，同上提示
   - 若存在 → 检查时效性，通过 `--refresh-market` 刷新市场数据（§1/§2/§11/§14）

**可选**：
3. `{output_dir}/data_pack_report.md` — PDF 附注数据（由 /business-analysis Step 1C 生成）
   - 若存在 → Agent B 使用完整数据（P2/P3/P4/P6/P13/SUB）
   - 若不存在 → Agent B 使用降级方案（无附注数据）

> 定性分析和 PDF 附注提取已从龟龟策略中解耦，由 `/business-analysis` 独立完成。
> 龟龟策略直接读取其输出，不再内嵌定性分析或 PDF 提取流程。

---

## 阶段调度

```
┌─────────────────────────────────────────────────┐
│              用户输入解析                          │
│   股票代码 = {code}                               │
│   持股渠道 = {channel | AskUserQuestion}          │
│   Tushare Token = {有 | 无 → yfinance fallback}  │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│  前置条件检查                                      │
│  qualitative_report.md 存在？ → 必须               │
│  data_pack_market.md 存在？ → 必须                 │
│  data_pack_report.md 存在？ → 可选（降级方案）      │
│    不满足 → 提示运行 /business-analysis，停止       │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│  Step A: 市场数据刷新                              │
│  tushare_collector.py --refresh-market            │
│  → 更新 §1/§2/§11/§14（股价/市值/周线/Rf）        │
│  → 超过7天自动降级为全量采集                        │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│     Phase 3: 分析与报告                             │
│                                                    │
│  Step 3.1: Agent B（数据校验 + 穿透回报率）         │
│      含 Step 0 口径锚定（原 pre-flight 已合并）     │
│      ↓                                             │
│  Step 3.2: Agent C（估值 + 报告组装）               │
│      输入：qualitative_report.md + Agent B 输出     │
│      ↓                                             │
│  输出：{公司名}_{代码}_分析报告.md                   │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│           协调器交付                               │
│  确认报告文件已生成，返回给用户                      │
└─────────────────────────────────────────────────┘
```

---

## Sub-agent 调用指令

### 环境准备（首次运行）

```bash
bash init.sh   # 创建 .venv 并安装依赖（pandas / tushare / pdfplumber 等）
```

> 优先使用 `.venv/bin/python` 执行下方脚本；无 venv 时回退 `python3`。

### Step A：市场数据刷新

```
# === 使用 --refresh-market 模式刷新市场敏感数据 ===
# data_pack_market.md 已由 /business-analysis 生成，仅刷新 §1/§2/§11/§14
# 超过 7 天自动降级为全量采集

Bash(
  command = "python3 scripts/tushare_collector.py --code {ts_code} --output {output_dir}/data_pack_market.md --refresh-market",
  description = "StepA 市场数据刷新"
)
```

### Phase 3：分析与报告

等待 Step A 完成后启动。

**条件加载规则**（协调器在启动 Agent B 时根据股票代码判断）：
- 港股 (.HK) → Agent B prompt 中额外指令：`同时加载 {shared_dir}/qualitative/references/market_rules_hk.md`
- 美股 (.US) → Agent B prompt 中额外指令：`同时加载 {shared_dir}/qualitative/references/market_rules_us.md`
- A股 → 无额外加载（默认路径，节省 context）

**Agent B（定量）加载**：
- `{strategy_dir}/phase3_quantitative.md` — 穿透回报率计算
- `{strategy_dir}/references/judgment_examples_turtle.md` — 龟龟专属锚点（G系数、分配意愿、λ可靠性）
- `{strategy_dir}/references/factor_interface.md` — 参数传递 schema

```
# === Step 3.1: Agent B（数据校验 + 定量分析）===
# Pre-flight 已合并到 phase3_quantitative.md 的 Step 0
# Agent B 先做数据校验与口径锚定，然后直接执行 11 步穿透回报率计算
# 若 Step 0 裁决为 SUPPLEMENT_NEEDED → Agent B 输出补救请求后停止
#   协调器解析 SUPPLEMENT_REQUEST，启动 WebSearch 补充后重新运行 Agent B（最多1次）
# 若 Step 0 裁决为 ABORT → Agent B 输出原因后停止，协调器通知用户

Task(
  subagent_type = "general-purpose",
  prompt = """
  请阅读 {strategy_dir}/phase3_quantitative.md 中的完整指令（含 Step 0 数据校验）。
  同时加载 {strategy_dir}/references/judgment_examples_turtle.md 作为龟龟专属判断锚点参考。

  数据包文件：
    - {strategy_dir}/references/shared_tables.md（税率/门槛/公式）
    - {output_dir}/data_pack_market.md
    - {output_dir}/data_pack_report.md（若存在）
    - {output_dir}/data_pack_report_interim.md（若存在）

  将定量分析输出写入：{output_dir}/phase3_quantitative.md
  """,
  description = "Phase3 Agent B 数据校验+定量分析"
)

# 等待 Agent B 完成
# 检查 Agent B 输出中的 Step 0 裁决：
#   PROCEED → 正常完成，继续 Agent C
#   SUPPLEMENT_NEEDED → 解析补救请求，WebSearch 补充后重跑（最多1次）
#   ABORT → 通知用户，停止

# === Step 3.2: Agent C（估值 + 报告组装）===
Task(
  subagent_type = "general-purpose",
  prompt = """
  请阅读 {strategy_dir}/phase3_valuation.md 中的完整指令。

  输入文件：
    - {output_dir}/qualitative_report.md（定性分析报告，由 /business-analysis 生成）
    - {output_dir}/phase3_quantitative.md（Agent B 输出，含 Step 0 基础信息 + 定量分析）
    - {output_dir}/data_pack_market.md（§11 历史价格、§17 预计算值）

  定性参数提取：从 qualitative_report.md 末尾 "结构化参数" 表读取，
  按 {strategy_dir}/references/factor_interface.md 的值域映射规则转换。

  将最终报告写入：{output_dir}/{company}_{code}_分析报告.md
  """,
  description = "Phase3 Agent C 估值与报告"
)
```

### 当 data_pack_report.md 不存在时（无 PDF 附注）

```
# /business-analysis 未提取 PDF 附注（用户未提供 PDF 或 PDF 为扫描件）
# Phase 3 的 Agent B 自动处理缺失的 data_pack_report.md
# Agent B 使用降级方案：P2/P3/P4/P6/P13 附注数据不可用
```

---

## 数据时效性规则

**支付率等关键指标必须基于同币种数据计算**（股息总额与归母净利润均取报表币种），不依赖 yfinance 的 payoutRatio 等衍生字段。

### --refresh-market 时效控制

| data_pack_market.md 年龄 | 行为 |
|--------------------------|------|
| ≤ 7 天 | --refresh-market 模式：仅刷新 §1/§2/§11/§14 |
| > 7 天 | 自动降级为全量采集（可能有新季报发布） |

> 中报时效性、PDF 下载等均由 `/business-analysis` 负责。龟龟策略不再管理 PDF 流程。

---

## 阶段超时规则

| 阶段 | 最大执行时间 | 超时行为 |
|------|------------|---------|
| Step A 市场数据刷新 | 1分钟 | --refresh-market 仅4个section，极快 |
| Phase 3.1 Agent B（含Step 0） | 10分钟 | 已完成步骤保留 |
| Phase 3.2 Agent C | 5分钟 | 输出已有结论 |

超时后，协调器应立即推进下一阶段，不等待。总管线预计最大执行时间 ≤ 16分钟。

---

## 异常处理

| 异常情况 | 处理方式 |
|---------|---------|
| qualitative_report.md 不存在 | 停止，提示用户运行 /business-analysis |
| data_pack_market.md 不存在 | 停止，提示用户运行 /business-analysis |
| data_pack_report.md 不存在 | 继续（Agent B 降级方案：无附注数据） |
| Tushare Token 无效或未配置 | --refresh-market 降级使用 yfinance fallback |
| Step A --refresh-market 失败 | 检查 Python 环境和依赖，提示安装 |
| Phase 3 context 接近上限 | 中间结果已持久化到文件（preflight/quantitative） |
| §13 warnings 非空 | Phase 3 读取 warnings 区块，影响分析策略 |

---

## 文件路径约定

每个标的的运行时输出放在独立文件夹中，避免多次分析互相覆盖。

**变量定义**：
- `{workspace}` = 项目根目录
- `{shared_dir}` = `{workspace}/shared`
- `{strategy_dir}` = `{workspace}/strategies/turtle`
- `{output_dir}` = `{workspace}/output/{代码}_{公司}`（如 `output/600887_伊利股份`、`output/00001_长和`）

```
{workspace}/
├── shared/                                     ← 通用模块（只读）
│   └── qualitative/                            ← 定性分析模块
│       ├── coordinator.md                      ← 定性模块独立入口（/business-analysis）
│       ├── qualitative_assessment.md           ← 6维度定性分析
│       ├── data_collection.md                  ← 轻量级 WebSearch 指令
│       └── references/
│           ├── output_schema.md                ← 结构化参数输出 schema
│           ├── judgment_examples.md            ← 通用判断锚点
│           ├── market_rules_hk.md              ← 港股规则（条件加载）
│           └── market_rules_us.md              ← 美股规则（条件加载）
├── strategies/turtle/                          ← 龟龟策略（只读）
│   ├── coordinator.md                          ← 本文件（调度逻辑）
│   ├── phase2_PDF解析.md                        ← PDF 附注提取格式规范（BA Step 1C 引用）
│   ├── phase3_quantitative.md                  ← Step 3.1 Agent B（含 Step 0 数据校验 + 定量分析）
│   ├── phase3_valuation.md                     ← Step 3.2 Agent C 估值+报告
│   └── references/
│       ├── shared_tables.md                    ← 税率/门槛/公式（龟龟专属）
│       ├── factor_interface.md                 ← 因子间参数传递 schema
│       └── judgment_examples_turtle.md         ← G系数/分配意愿/λ锚点（龟龟专属）
├── scripts/                                    ← 预处理脚本（只读）
│   ├── tushare_collector.py                    ← 数据采集脚本（支持 --refresh-market）
│   ├── pdf_preprocessor.py                     ← PDF 预处理脚本（BA 扫描件 fallback 用）
│   ├── config.py                               ← Token 管理
│   └── requirements.txt                        ← Python 依赖
└── output/                                     ← 运行时输出（按标的隔离）
    └── {code}_{company}/
        ├── qualitative_report.md               ← 前置条件：/business-analysis 输出（只读）
        ├── data_pack_market.md                 ← /business-analysis 输出 → Step A 刷新市场数据
        ├── data_pack_report.md                 ← /business-analysis Step 1C 输出（可选，PDF 附注）
        ├── phase3_quantitative.md              ← Agent B 输出（含 Step 0 数据校验 + 定量分析）
        └── {company}_{code}_分析报告.md          ← 最终报告
```

**协调器职责**：在 Phase 1 启动前，创建 `{output_dir}` 目录：
```bash
mkdir -p {workspace}/output/{code}_{company}
```

---

## 数据约定

### 金额单位转换

所有阶段（Phase 1/2/3）的金额统一为 **百万元**（Tushare 原始单位元 ÷ 1e6）。

| 原始单位 | 转换方法 | 示例 |
|---------|---------|------|
| 元 | ÷ 1,000,000 | 96,886,000,000 元 → 96,886.00 百万元 |
| 千元 | ÷ 1,000 | 96,886,000 千元 → 96,886.00 百万元 |
| 万元 | ÷ 100 | 9,688,600 万元 → 96,886.00 百万元 |
| 亿元 | × 100 | 968.86 亿元 → 96,886.00 百万元 |

显示格式：使用千位逗号分隔（如 96,886.00），百分比保留2位小数。

### Phase 0 重试规则

PDF 下载最多重试 **3次**（指数退避：3s / 6s / 9s）。3次均失败：
- 在 §13 中生成 `[数据缺失|中] PDF年报下载失败，已使用3次重试`
- 进入无 PDF 模式（跳过 Phase 2，Phase 3 使用降级方案）
- 不尝试替代 URL（仅使用 `/download-annual-report` 返回的首选 URL）

---

*龟龟投资策略 v2.0 | 协调器 | Coordinator*
