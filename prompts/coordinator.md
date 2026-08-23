# 龟龟投资策略 v2.0 — 协调器（Coordinator）

> **角色**：你是项目经理。职责：(1) 验证输入并通过 AskUserQuestion 补全缺失信息；(2) 按依赖关系调度 Phase 0→1→2→3；(3) 监控 checkpoint 和超时；(4) 交付最终报告。你不执行数据采集或分析计算。
>
> 变更日志见 `prompts/CHANGELOG.md`（不加载进 context）

---

## 输入解析

用户输入可能包含以下组合：

| 输入项 | 示例 | 必需？ |
|--------|------|--------|
| 股票代码或名称 | `600887` / `伊利股份` / `0001.HK` / `长和` / `AAPL` / `AAPL.US` | 必需 |
| 持股渠道 | `港股通` / `直接` / `美股券商` | 可选（未指定则触发 AskUserQuestion） |
| PDF 年报文件 | 用户上传的 `.pdf` 文件 | 可选（未提供则触发 Phase 0 自动下载） |

**解析规则**：
1. 从用户消息中提取股票代码/名称和持股渠道
2. 检查是否有 PDF 文件上传（检查 `/sessions/*/mnt/uploads/` 目录中的 `.pdf` 文件）
3. 若用户只给了公司名称没给代码，在 Phase 1 Step A 中由脚本通过 Tushare `stock_basic` 确认代码
4. 股票代码格式化：A 股 → `XXXXXX.SH` 或 `XXXXXX.SZ`；港股 → `XXXXX.HK`；美股 → `AAPL.US`

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

## 阶段调度

```
┌─────────────────────────────────────────────────┐
│              用户输入解析                          │
│   股票代码 = {code}                               │
│   持股渠道 = {channel | AskUserQuestion}          │
│   PDF年报 = {有 | 无 | 自动下载}                  │
│   Tushare Token = {有 | 无 → yfinance fallback}  │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│  Phase 0：PDF 自动获取（仅当需要时）               │
│  /download-report 命令                            │
│                                                   │
│  ⚠️ 触发条件：                                    │
│     用户未上传 PDF + 选择了"自动下载"               │
│  跳过条件：                                       │
│     用户已上传 PDF / 选择了"跳过" / "稍后上传"     │
│                                                   │
│  输出：annual_report.pdf（或下载失败 Warning）     │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌─────────── Step A: Python 脚本（并行启动）──────────┐
│                                                    │
│  ┌────────────────────────┐  ┌──────────────────┐  │
│  │  Phase 1A: Tushare采集  │  │  Phase 2A: PDF解析│  │
│  │                         │  │  ⚠️ 仅当有PDF时   │  │
│  │  Bash 运行              │  │                   │  │
│  │  tushare_collector.py   │  │  Bash 运行        │  │
│  │  → data_pack_market.md  │  │  pdf_preprocessor │  │
│  │    (§1-§6, §7部分,      │  │  → pdf_sections   │  │
│  │     §9, §11, §12,      │  │    .json          │  │
│  │     §14, §15, §16,     │  │  (P2-P13+MDA+SUB) │  │
│  │     §3P, §4P,          │  │                   │  │
│  │     审计意见, §13.1)    │  └──────────────────┘  │
│  │  → available_fields.json│                        │
│  └────────────────────────┘                        │
│                                                    │
└───────────┬────────────────────────────────────────┘
            │  Phase 1A 完成后立即启动 Phase 1B
            │  Phase 2A 可与 Phase 1B 并行运行
            ▼
┌─────────── Step B: Agent（Phase 1A 完成后启动）────┐
│                                                    │
│  ┌────────────────────────┐                        │
│  │  Phase 1B: WebSearch   │                        │
│  │  补充 §7, §8, §10, §13│                        │
│  │  ⚠️ §7/§8/§9B 不依赖   │                        │
│  │    pdf_sections.json   │                        │
│  │  ⚠️ §10 到达时检查      │                        │
│  │    pdf_sections.json   │                        │
│  │    是否已生成           │                        │
│  │  → 追加到              │                        │
│  │    data_pack_market.md │                        │
│  └────────┬───────────────┘                        │
│           │                                        │
│  ┌────────────────────────┐                        │
│  │  Phase 2B: PDF精提取    │                        │
│  │  ⚠️ 仅当有PDF时         │                        │
│  │  ⚠️ 等待 Phase 2A 完成  │                        │
│  │  精提取5+1项footnote   │                        │
│  │  (SUB条件触发)          │                        │
│  │  → data_pack_report.md │                        │
│  └────────┬───────────────┘                        │
│           │                                        │
└───────────┼────────────────────────────────────────┘
            │     等待全部完成
            ▼
┌─────────────────────────────────────────────────┐
│           Phase 3: 分析与报告                      │
│           Task Agent                              │
│                                                    │
│  输入：data_pack_market.md                         │
│        data_pack_report.md（若有）                  │
│        phase3_分析与报告.md（精简执行器）            │
│        references/ 目录（按需加载）                 │
│                                                    │
│  渐进式披露：                                      │
│     执行器仅含工作流+报告模板                       │
│     各因子详细规则按需从 references/ 读取            │
│                                                    │
│  输出：{output_dir}/{公司名}_{代码}_分析报告.md     │
│                                                    │
│  ⚠️ 不调用任何外部数据源                            │
│  ⚠️ 内部设置 checkpoint：                          │
│     每完成一个因子 → 将结论追加写入报告文件          │
│     防止 Phase 3 自身 context compact               │
└──────────┬──────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────┐
│           协调器交付                               │
│  1. 确认报告文件已生成                              │
│  2. 返回报告文件链接给用户                          │
└─────────────────────────────────────────────────┘
```

---

## Sub-agent 调用指令

### 环境准备

```bash
pip install tushare pandas pdfplumber --break-system-packages
```

### Phase 0：PDF 自动获取

```
/download-report {stock_code} {year} 年报
# 成功 → pdf_path = 文件路径 | 失败 → pdf_path = None，无 PDF 模式
# 中报（条件触发）：仅当 Phase 1A 输出含 H1 列时下载
```

### Step A：Python 脚本（Phase 1A + Phase 2A 并行）

```
# Phase 1A：Tushare 采集
Bash("python3 scripts/tushare_collector.py --code {ts_code} --output {output_dir}/data_pack_market.md")
# → data_pack_market.md (§1-§6,§7部分,§9,§11-§16,§3P,§4P,审计意见,§13.1) + available_fields.json

# Phase 2A.5（可选，有PDF时）：TOC 定位
Task("读取 {pdf_path} 前10页，提取 SUB/MDA 章节页码 → {output_dir}/toc_hints.json")

# Phase 2A：PDF 预处理（有PDF时，等待2A.5）
Bash("python3 scripts/pdf_preprocessor.py --pdf {pdf_path} --output {output_dir}/pdf_sections.json --hints {output_dir}/toc_hints.json")
# → pdf_sections.json (P2/P3/P4/P6/P13/MDA/SUB)
# 中报（条件触发）：同命令，输入中报PDF，输出 pdf_sections_interim.json
```

### Step B：Agent（Phase 1A 完成后启动）

```
# Phase 1B：WebSearch 补充（Phase 1A 完成后立即启动，不等 Phase 2A）
Task(prompt="""
  阅读 {prompts_dir}/phase1_数据采集.md 完整指令。
  目标：{stock_code}（{company_name}），渠道：{channel}
  补充 §7(定性)/§8/§9B(条件)/§10/§13.2 → 替换 data_pack_market.md 占位符
  §10 优先用 pdf_sections.json MDA 字段，不可用则 WebSearch
""")

# Phase 2B：PDF 精提取（有PDF时，等待 Phase 2A）
Task(prompt="""
  阅读 {prompts_dir}/phase2_PDF解析.md 完整指令。
  输入：{output_dir}/pdf_sections.json（+ pdf_sections_interim.json 若有中报）
  输出：{output_dir}/data_pack_report.md（+ data_pack_report_interim.md 若有中报）
""")
```

### Phase 3：分析与报告（等待全部完成）

```
Task(prompt="""
  阅读 {prompts_dir}/phase3_分析与报告.md 完整指令。
  数据包：{output_dir}/data_pack_market.md + data_pack_report.md(若有) + data_pack_report_interim.md(若有)
  参考文件：{prompts_dir}/references/
  输出：{output_dir}/{company}_{code}_分析报告.md
  规则：百万元+千位逗号 | §3P/§4P 母公司报表 | 无PDF→降级方案 | 中报数据优先用于P2/P3/P6
""")
```

---

## 报表时效性规则

协调器在启动 Phase 0 前，应确定目标年报年份：

- 若当前日期在 1-3月，最新年报可能尚未发布，使用上一财年年报
- 若当前日期在 4月及以后，最新财年年报通常已发布

Tushare 数据自动覆盖最近 5 个财年，无需手动指定年份。

**支付率等关键指标必须基于同币种数据计算**（股息总额与归母净利润均取报表币种），不依赖 yfinance 的 payoutRatio 等衍生字段。

### 中报时效性规则（双PDF触发）

当 Phase 1A 的输出 data_pack_market.md 中出现 "YYYYH1" 列（如 "2025H1"），
说明该公司已发布比最新年报更新的中报（半年报）。此时：

1. Phase 0 应下载**两份** PDF：最新年报 + 最新中报
2. Phase 2A 应对两份 PDF 分别运行 pdf_preprocessor.py
3. Phase 2B 应分别处理两份 pdf_sections.json
4. Phase 3 应同时参考两份 data_pack_report

判断方法：Phase 1A 完成后，检查 data_pack_market.md 的 §3 损益表表头。
若第一列为 "YYYYH1" 格式 → 触发双 PDF 流程。

示例：
  表头为 ["2025H1", "2024", "2023", ...] → 下载 2024年报 + 2025中报
  表头为 ["2024", "2023", ...]           → 仅下载 2024年报

执行顺序调整：
```
Phase 1A + Phase 0-年报 (并行)
    ↓
检查 Phase 1A 输出是否包含 H1 列
    ↓ (若有)
Phase 0-中报 (补充下载)
    ↓
Phase 2A (处理全部 PDF)
```

---

## 阶段超时规则

| 阶段 | 最大执行时间 | 超时行为 |
|------|------------|---------|
| Phase 0 PDF下载 | 3分钟 | 标注 Warning，进入无 PDF 模式 |
| Phase 1A Tushare采集 | 2分钟 | 检查已获取的数据，部分降级继续 |
| Phase 1B WebSearch | 5分钟 | 已完成的 §N 保留，未完成的标注 "⚠️ 超时未完成" |
| Phase 2A PDF预处理 | 3分钟 | 跳过 Phase 2，进入无 PDF 模式 |
| Phase 2B PDF精提取 | 3分钟 | 已提取项保留，未提取项标注 null |
| Phase 3 分析 | 15分钟 | 输出已完成因子的部分报告 |

超时后，协调器应立即推进下一阶段，不等待。总管线预计最大执行时间 ≤ 30分钟。

---

## Phase 3 数据澄清回流

Phase 3 Agent 在分析过程中，若发现关键数据歧义或缺失，可触发数据回流。

### 触发条件（仅限以下情况）
1. 关键计算所需数据在 data_pack 中为 "—" 且无法降级（如支付率分母为零）
2. 数据存在但数值异常（如支付率 > 200%），需要交叉验证
3. 控股结构中某上市子公司市值/持股比例缺失

### 回流机制

Phase 3 在报告文件中写入 clarification request 标记：
```
<!-- CLARIFICATION_REQUEST
type: [missing_data | verify_anomaly | subsidiary_lookup]
target: [§N 具体字段]
question: [具体问题]
-->
```

协调器在 Phase 3 第一个 checkpoint（因子1A完成后）检查报告文件：
- 若包含 `CLARIFICATION_REQUEST` → 暂停 Phase 3，启动补充 WebSearch
- 补充结果追加到 `data_pack_market.md` 对应章节
- 重启 Phase 3（从上次 checkpoint 继续）

### 限制
- 最多触发 **1次** 回流（防止循环）
- 仅限 WebSearch 补充，不重新运行 Tushare/PDF 脚本
- 回流超时：5分钟（超时则 Phase 3 使用降级方案继续）

---

## 异常处理

| 异常情况 | 处理方式 |
|---------|---------  |
| Tushare Token 无效或未配置 | 全程降级使用 yfinance MCP，标注数据源 |
| Phase 0 PDF 下载失败 | 标注 Warning，跳过 Phase 2，进入无 PDF 模式 |
| Phase 1 Step A 脚本执行失败 | 检查 Python 环境和依赖，提示安装 |
| Phase 1 Tushare 某端点返回空 | 脚本内置 yfinance fallback，标注来源 |
| Phase 1 财报数据不足5年 | 继续执行，在 data_pack 中标注实际覆盖年份 |
| Phase 2 Step A PDF 无法解析 | 跳过 Phase 2，Phase 3 使用降级方案 |
| Phase 2 关键词未命中 | 对应项返回 null，data_pack_report 标注 Warning |
| Phase 3 某因子触发否决 | 按框架规则停止后续因子，输出否决报告 |
| Phase 3 context 接近上限 | 通过 checkpoint 机制已将中间结果持久化到文件 |
| Phase 1 warnings 非空 | Phase 3 读取 warnings 区块，影响分析策略 |

---

## 文件路径约定

每个标的的运行时输出放在独立文件夹中，避免多次分析互相覆盖。

**变量定义**：
- `{workspace}` = 龟龟投资策略 根目录
- `{prompts_dir}` = `{workspace}/prompts`
- `{output_dir}` = `{workspace}/output/{代码}_{公司}`（如 `output/600887_伊利股份`、`output/00001_长和`）

```
{workspace}/
├── prompts/                                    ← 策略逻辑（只读，不随标的变化）
│   ├── coordinator.md                          ← 本文件（调度逻辑）
│   ├── phase1_数据采集.md                       ← Phase 1 Step B prompt（WebSearch）
│   ├── phase2_PDF解析.md                        ← Phase 2 Step B prompt（5项精提取）
│   ├── phase3_分析与报告.md                      ← Phase 3 精简执行器
│   └── references/                              ← 因子详细规则（按需加载）
│       ├── shared_tables.md                     ← 共享参数表（支付率/税率/门槛/跨币种）
│       ├── factor_interface.md                  ← 因子间参数传递 schema（v2.0 新增）
│       ├── judgment_examples.md                 ← 关键判断锚点示例（v2.0 新增）
│       ├── market_rules_hk.md                   ← 港股特别规则（条件加载，v2.0 新增）
│       ├── market_rules_us.md                   ← 美股特别规则（条件加载，v2.0 新增）
│       ├── factor1_资产质量与商业模式.md
│       ├── factor2_穿透回报率粗算.md
│       ├── factor3_穿透回报率精算.md
│       └── factor4_估值与安全边际.md
├── scripts/                                    ← 预处理脚本（只读，不随标的变化）
│   ├── tushare_collector.py                    ← Phase 1 Step A 数据采集脚本
│   ├── pdf_preprocessor.py                     ← Phase 2 Step A PDF 预处理脚本
│   ├── config.py                               ← Token 管理
│   └── requirements.txt                        ← Python 依赖
└── output/                                     ← 运行时输出（按标的隔离）
    ├── 600887_伊利股份/                          ← 示例：伊利股份
    │   ├── data_pack_market.md                  ← Phase 1 输出
    │   ├── available_fields.json                ← Phase 1 输出（可用字段清单）
    │   ├── 600887_2024_年报.pdf                  ← Phase 0 下载（年报）
    │   ├── 600887_2025_中报.pdf                  ← Phase 0 下载（中报，条件触发）
    │   ├── pdf_sections.json                    ← Phase 2A 输出（年报）
    │   ├── pdf_sections_interim.json            ← Phase 2A 输出（中报，条件触发）
    │   ├── data_pack_report.md                  ← Phase 2B 输出（年报附注）
    │   ├── data_pack_report_interim.md          ← Phase 2B 输出（中报附注，条件触发）
    │   └── 伊利股份_600887_分析报告.md             ← Phase 3 输出（最终报告）
    ├── 00001_长和/                               ← 示例：长和
    │   └── ...
    └── .../
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
- 不尝试替代 URL（仅使用 `/download-report` 返回的首选 URL）

---

*龟龟投资策略 v2.0 | 多阶段 Sub-agent 架构 | Coordinator*
