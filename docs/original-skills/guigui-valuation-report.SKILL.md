---
name: guigui-valuation-report
description: 龟龟投资框架（Turtle Investment Framework）v2.1-beta 完整版：AI 辅助的 A股/港股/美股基本面分析系统（Python 确定性数据采集 + LLM 定性分析与多因子评估）。涵盖完整龟龟策略流水线（Phase 0 年报下载 → Phase 1 Tushare/WebSearch 数据采集 → Phase 2 PDF 年报解析 → Phase 3 定性+定量+穿透回报率估值与报告）、独立商业质量分析（PDF-first 6维度）、独立估值分析（DCF/DDM/PE Band/PEG/PS）、龟龟选股器与报告双输出。Use when the user asks to 调研/分析某只股票、运行龟龟策略完整分析、生成穿透回报率估值报告（粗算R/精算GG/门槛II/安全边际KK/目标买入价/仓位建议）、商业质量分析、独立估值、选股，或按《凌霄泵业_002884_分析报告.md》同款格式输出投资报告。入口：strategies/turtle/coordinator.md（龟龟策略）、prompts/coordinator.md（全流程）、shared/qualitative/coordinator.md（商业分析）、strategies/valuation/coordinator.md（估值）、scripts/screener_core.py（选股器）。需要 TUSHARE_TOKEN（缺失自动降级 AkShare，见 scripts/akshare_collector.py / tushare_collector.py --backend auto）与 Python 3.10+（见 requirements.txt / init.sh）。
---

# 龟龟投资框架 v2.1-beta（Turtle Investment Framework）

> 混合架构：Python 脚本完成确定性数据采集与预计算，LLM 提示词驱动定性分析与多因子评估。
> 本 skill 即完整框架：`prompts/`、`strategies/`、`shared/`、`scripts/`、`tests/` 均来自上游仓库，原有 Phase 3 专属资产（`references/methodology.md`、`references/report-template.md`、`scripts/calc_penetration_return.py`）继续保留。

---

## 〇、适用性与例外（必读）

### 适用范围

本框架的**标准穿透回报率公式（主口径 R* = 归母净利 C × 折扣系数 k × 支付率 M / 市值；现金校验 GG = 真实可支配现金 AA × M / 市值）**主要适用于：
- 工业制造、消费品、医药、科技等**非金融行业**公司
- 具备明确 Capex、折旧、经营现金流可辨识的公司

### 不适用 / 需适配调整的行业

| 行业 | 问题 | 适配方案 |
|------|------|---------|
| **银行** | OCF 含客户存贷款变动（波动巨大无经济意义）；无传统 Capex/折旧概念；真实可支配现金由监管资本约束而非 FCF 约束 | 以**可持续股息率**替代 R*/GG 链条，股息覆盖率验证；PB-ROE 交叉确认；DDM 辅助估值 |
| **保险** | 保费收入 ≠ 一般企业营收；准备金计提主观性强；投资收益率波动大 | 以**内含价值（EV）+ 新业务价值（NBV）**替代 OE 框架 |
| **券商** | 盈利高度周期性；自营业务波动大；资产负债表以金融资产为主 | 以**ROE 周期均值 × PB**锚定，股息率辅助 |
| **房地产（开发型）** | 合同负债→营收确认时滞；土储价值重估；高杠杆特殊风险 | 使用**NAV（净资产价值）折让**法，标准 OE 框架不适用 |

> ⚠️ **遇到以上行业时，必须在报告 Warnings 和 Executive Summary 中明确标注"标准框架不适用，已采用行业适配方案"，并说明具体适配方法。**

### 特殊情况的识别

当 data_pack_market.md §17 出现以下信号时，自动触发适配流程：
- `AA_2y < 0` 且公司为金融机构 → 银行/保险适配
- `|HH| > 5pct` → 非正常偏差，检查行业归属
- `OCF 序列` 正负交替且与盈利趋势无关 → 疑似金融/地产行业

---

## 一、触发方式

### 1.1 直接触发（独立使用）

```
分析 <公司名或股票代码>
```

或更具体的：

```
对 <公司名/代码> 做龟龟穿透回报率估值
对 <公司名/代码> 做商业质量分析
对 <公司名/代码> 做独立估值分析
```

### 1.2 协同触发（与 company-research 联用）

当用户说 `调研 <公司名或股票代码>` 时：
- company-research 负责 B1-B3（解析、拉数、审计）+ B4-B6（八步分析、交叉验证、结论）
- **本技能负责 Phase 3 穿透回报率估值模块**——Owner Earnings、真实可支配现金 AA、主口径 R*（C×k×M/市值）/ 现金校验 GG、有效口径 R_eff、门槛 II、安全边际 KK、目标买入价/门槛价格、仓位建议
- 由 company-research 的 B4.4 节调用本技能的方法论与计算脚本

### 1.3 触发后行为

触发后执行（按模式选择入口）：

| 模式 | 入口文件 | 说明 |
|------|---------|------|
| 完整龟龟流水线 | `strategies/turtle/coordinator.md` | Phase 0→1→2→3 全流程 |
| 全流程协调器 | `prompts/coordinator.md` | 输入解析、AskUserQuestion、阶段调度 |
| 商业质量分析 | `shared/qualitative/coordinator.md` | PDF-first 6 维度定性评估 |
| 独立估值分析 | `strategies/valuation/coordinator.md` | DCF/DDM/PE Band/PEG/PS 多方法 |
| 选股器 | `scripts/screener_core.py` | Tier 1 批量过滤 + Tier 2 深度分析 |

---

## 二、工作流程（龟龟策略完整流水线）

### 流水线总览

```
用户输入（股票代码 + 可选年报PDF）
  │
  ├─ Phase 0   年报自动下载
  │            └─ Gate P0: PDF 存在或已标注"无PDF"
  │
  ├─ Phase 1A  Tushare/AkShare 结构化数据采集
  │            └─ Gate P1A: 所有强制数据文件已产出（见 §2.2）
  │
  ├─ Phase 1B  WebSearch 非结构化信息补充
  │            └─ Gate P1B: 治理/行业/股东/关联交易四类信息已补全
  │
  ├─ Phase 2   PDF 年报解析（有 PDF 时）
  │            └─ Gate P2: 关键附注数据已提取（无 PDF 则跳过）
  │
  ├─ Phase 3A  商业质量分析（6 维度定性）
  │            └─ Gate P3A: qualitative_report.md 已生成
  │
  ├─ Phase 3B  穿透回报率定量分析
  │            └─ Gate P3B: 穿透回报率_输出.json 与报告一致
  │
  └─ Phase 3C  估值 + 报告 + 图表
               └─ Gate P3C（最终门控）: 交付清单全部 ✅
```

### 2.1 各阶段强制交付物与门控标准

#### Phase 1A：结构化数据采集

| # | 交付物 | 位置 | 强制？ | 数据来源 | 最低要求 |
|---|--------|------|--------|---------|---------|
| 1 | **data_pack_market.md** | data/ | ✅ 强制 | tushare_collector.py / akshare_collector.py | §1-§17 完整，≥5 年财务数据 |
| 2 | **利润表.csv** | data/ | ✅ 强制 | akshare `stock_profit_sheet_by_report_em` | ≥5 个报告期（年报），含营业收入/归母净利润/EPS |
| 3 | **资产负债表.csv** | data/ | ✅ 强制 | akshare `stock_balance_sheet_by_report_em` | ≥5 个报告期，含总资产/总负债/归母权益 |
| 4 | **现金流量表.csv** | data/ | ✅ 强制 | akshare `stock_cash_flow_sheet_by_report_em` | ≥5 个报告期，含 OCF/投资活动/筹资活动现金流 |
| 5 | **主要财务指标.csv** | data/ | ✅ 强制 | akshare `stock_financial_abstract_em` | ROE/ROA/EPS/每股净资产 等核心指标 |
| 6 | **日线行情_前复权.csv** | data/ | ✅ 强制 | akshare `stock_zh_a_hist` period="daily" adjust="qfq" | 至少 3 年完整日线，用于 PE/PB 估值带和历史分位 |
| 7 | **分红历史.csv** | data/ | ✅ 强制 | akshare `stock_dividents_detail_em` | 覆盖 ≥5 年，含每股股利/除权日/支付率校验 |
| 8 | **十大股东.csv** | data/ | ✅ 强制 | akshare `stock_shareholder_top10_em` | 最新一期 + 前一期对比 |
| 9 | **available_fields.json** | data/ | ✅ 强制 | 采集器自动生成 | 记录所有成功/失败的接口 |
| 10 | **拉取清单.json** | data/ | ✅ 强制 | 采集器自动生成 | 每个接口：成功/失败/重试次数/数据日期 |
| 11 | **审计报告.md** | data/ | ✅ 强制 | Phase 1A 完成后生成 | 三表勾稽/完整性/异常值/缺失项说明 |

**🔴 Phase 1A 门控（必须全部满足方可进入 Phase 1B）**：

| 门控项 | 标准 | 不通过时的处理 |
|--------|------|---------------|
| **P1A-G1 数据年限** | 财务数据 ≥5 个完整财年 | 若仅 3-4 年：标注 Warning，降级继续；<3 年：**硬阻断，停止分析** |
| **P1A-G2 时效性** | 最新财报 ≤6 个月 | 若 >6 个月：标注 Warning，继续但提示数据陈旧风险 |
| **P1A-G3 CSV 覆盖率** | #1-#8 至少 5/8 成功 | 若仅 3-4 项：必须逐项说明降级替代方案；<3 项：**硬阻断** |
| **P1A-G4 接口记录** | 拉取清单.json 完整记录每次调用 | 缺失时必须补充，禁止"忘记记录了" |
| **P1A-G5 三表勾稽** | 资产=负债+权益 容差 ±5% | 容差 >5%：专项排查（口径/币种/合并范围），结论写入审计报告 |

**拉取失败降级策略**（按优先级）：
```
0. 先探测后拉取（强制）：运行 ~/.codex/skills/company-research/scripts/probe_sources.py <代码> --out <项目>/data
   生成可用源清单（东财/腾讯/新浪端点实时连通性 + akshare 接口存在性），避免盲目试错；
   拉数统一走 ~/.codex/skills/company-research/scripts/fetch_with_fallback.py（候选源自动切换、
   调用记录写入 data/拉取清单.json）。已知源坑位见 ~/.codex/skills/company-research/references/data-source-notes.md
1. AkShare 东方财富接口（默认）→ 失败
2. AkShare 腾讯接口（stock_zh_a_hist_tx，符号小写前缀如 sh603365；东财 push2* SSL 故障时的可靠替代，
   2026-08 实测可用）→ 失败
3. AkShare 新浪接口（2026-08 实测 SSL 故障，底层接口 stock_financial_analysis_indicator_em 依赖它）→ 失败
4. 手工从 data_pack_market.md 提取表格写入 CSV → 标注"从 data_pack_market.md 提取"
5. WebSearch 补充关键数字 → 标注"来自 WebSearch，精度受限"
6. 标注为缺失，计入 Warnings → 说明对分析结论的影响
```

#### Phase 1B：非结构化信息补充

| # | 信息类别 | 强制？ | 最低要求 |
|---|---------|--------|---------|
| 1 | 股东与治理结构 | ✅ | 十大股东/实控人/股权质押/关联交易 |
| 2 | 行业竞争格局 | ✅ | 3-5 家可比公司 + 市场份额/排名 |
| 3 | 主营业务构成 | ✅ | 按产品/地区的营收与利润拆分 |
| 4 | 近期重大事件 | 推荐 | 并购/融资/人事变动/监管处罚 |
| 5 | 券商研报观点 | 推荐 | 至少 2 家券商最新评级与目标价 |

**🔴 Phase 1B 门控**：前三类信息（股东/行业/主营）必须补全，缺一不可进入 Phase 2。

#### Phase 2：PDF 年报解析

- **有 PDF 时**：提取 P2/P3/P4/P6/P13/MDA/SUB 七个目标章节 → `data_pack_report.md`
- **无 PDF 时**：标注"无 PDF，Phase 2 跳过"，不阻断流水线

**🔴 Phase 2 门控**（有 PDF 时）：关键附注数据（折旧摊销明细、关联交易、子公司清单）至少提取 2/3。

#### Phase 3A：商业质量分析

- 入口：`shared/qualitative/coordinator.md`
- 交付物：`reports/qualitative_report.md`
- **🔴 门控**：6 个维度全部有结论，不得跳过任何维度；定性结论必须有数据支撑（不能凭空编造）

#### Phase 3B：穿透回报率定量分析

- 入口：`strategies/turtle/phase3_quantitative.md`
- 交付物：`reports/穿透回报率_输出.json`（由 `scripts/calc_penetration_return.py` 确定性计算）
- **输入生成（强制，禁止手填）**：先运行 `scripts/build_penetration_input.py --data <项目>/data --out <项目>/input --company <名称> --code <代码>`，自动生成 `穿透回报率_输入.json` + `输入_判断点说明.md`；**人工逐项确认判断点**（G/M/k/AA/net_cash/rf/cycle_adjust/λ——建议值、依据、影响幅度见 `references/penetration-input-guide.md`），不采纳机器建议必须写明理由与替代值；手填值曾致市值/货币资金 10 倍错与 AA 口径不自洽（水星家纺实战教训）
- **🔴 门控**：脚本输出与报告数字一致（G7），\|HH\| 偏差已解释（G5）；输入必须由生成器产出或人工判断点全部确认（禁止无依据手填）

#### Phase 3C：估值 + 报告 + 图表（最终阶段）

| # | 交付物 | 强制？ | 说明 |
|---|--------|--------|------|
| 1 | 分析报告 MD | ✅ | 11 章完整，见 report-template.md |
| 2 | 分析报告 HTML | ✅ | MD 的 HTML 渲染版 |
| 3 | 图表 PNG | ✅ | **≥10 张**，每张编号/标题/日期/来源 |
| 4 | 图表 HTML | ✅ | Plotly 交互版合集 |
| 5 | 穿透回报率_输入.json | ✅ | 计算器输入参数 |
| 6 | 穿透回报率_输出.json | ✅ | 计算器输出，与报告数字一致 |
| 7 | 跟踪验证台账.md | ✅ | 预测台账 + 验证协议 |
| 8 | analyze_charts.py | ✅ | 可复现的图表生成脚本 |
| 9 | README.md 更新 | ✅ | 评级/目标价/核心逻辑/风险 |
| 10 | 财报更新验证.md 追加一行 | ✅ | 项目根目录跨批次汇总（分析日期/财报期/股价/12M三情景/评级/要点） |

**🔴 最终门控（P3C-Final）**：交付清单 20 项全部 ✅ 方可宣称"分析完成"。

### 2.2 数据分析与审计标准（Phase 1A → 审计报告.md 必须覆盖）

| 审计项 | 方法 | 合格标准 | 不合格处理 |
|--------|------|---------|-----------|
| **三表勾稽** | 资产=负债+权益；净利润→留存收益衔接 | 偏差 ≤±5% | 排查口径差异，标注 Warning |
| **数据完整性** | 检查各表字段空值率 | 核心字段（营收/净利/总资产/权益）空值率 = 0 | 缺失字段逐项标注替代来源 |
| **异常值检测** | 同比变动 >50% 或符号反转 | 每项异常有合理解释 | 无法解释的计入 Warnings |
| **分红一致性** | DPS × 总股本 vs 分配股利现金流 | 偏差 ≤±10% | 标注口径差异（如中期+末期合并） |
| **支付率校验** | 法1（DPS/EPS）vs 法2（分配现金/归母净利） | 两法偏差 >5pct 时排除法1 | 优先使用法2，法1 标注"仅供参考" |

### 2.3 流水线执行纪律

- **禁止跳相**：Phase 1 未完成门控 → 不得进入 Phase 3（Phase 2 有 PDF 时同样）
- **禁止编造数据**：任何缺失数据必须标注来源和降级路径，不得凭空填写
- **禁止跳过图表**：图表 ≥10 张是硬性要求，不得以"数据不足"为由跳过；数据不足时用行业均值或合理估计代替，但必须标注"估计"
- **Phase 3 串行**：3A 定性 → 3B 定量 → 3C 估值与报告。Agent C 是唯一有权签发买入/观察/排除的角色
- **数据包过期**：data_pack_market.md >7 天自动触发全量重采（`--refresh-market` 只刷 §1/§2/§11/§14）
- **脚本纪律**：所有 .py 文件必须放在项目 `scripts/` 目录内，项目外禁止创建脚本文件

---

## 三、项目文件夹规范（强制）

> 本规范与 company-research 技能 B1 节完全对齐。独立触发本技能时按此规范创建项目目录；与 company-research 协同时，项目目录已由 company-research 创建，本技能直接使用。

### 3.1 文件夹命名规范

每次新建项目目录必须为：

```
<市场>.<代码> <公司名>
```

**示例**：`SH.601319 中国人保`、`SZ.002884 凌霄泵业`、`SH.600887 伊利股份`

**规则**：
- 代码+名称缺一不可；任一缺失由脚本/Agent 自动解析（akshare 正/反向查询）
- 解析失败则报错退出并提示补充
- **禁止用代码代替名称**（如 `SH.601319 601319`）
- 市场前缀推断：6/9→SH，0/3→SZ，4/8/92→BJ；港股→HK，美股→US

### 3.2 标准文件架构（强制，不得改变批次与顶层结构）

```
<市场>.<代码> <公司名>/
├── <YYYY_MM_DD>/                # ★ 批次目录：文件夹名=本次分析实际日期（如 2026_08_15 仅为示例），每次分析新建一批次
│   ├── README.md                    # 总览：公司/代码/状态/评级/目标价/核心逻辑/风险/交付状态
│   ├── ROADMAP.md                   # 分析路线图（Phase 0-3 阶段计划）
│   ├── 交付清单.md                   # ★ 交付物清单（批次初始化时生成，交付前逐项核对）
│   ├── data/                        # 原始数据
│   │   ├── data_pack_market.md      #   Phase 1 市场数据包（§1-§17）
│   │   ├── available_fields.json    #   Tushare 可用字段清单
│   │   ├── data_pack_report.md      #   Phase 2 PDF 附注数据（有 PDF 时）
│   │   ├── 拉取清单.json             #   数据接口拉取记录
│   │   ├── 审计报告.md               #   数据审计结果
│   │   └── *.csv                    #   行业补充数据
│   ├── input/                       # 模型输入
│   │   └── 穿透回报率_输入.json      #   calc_penetration_return.py --config
│   ├── scripts/                     # 可复现脚本（★ 所有脚本必须放此目录，见第十节）
│   │   ├── calc_penetration_return.py  # 穿透回报率计算器（从 skill 复制）
│   │   ├── verification.py             # 复验脚本
│   │   ├── analyze_charts.py           # 图表统一生成脚本
│   │   └── analyze_*.py                # 各分析模块脚本
│   ├── reports/                     # 交付报告
│   │   ├── {公司名}_{代码}_分析报告.md   # 龟龟主报告（MD）
│   │   ├── {公司名}_{代码}_分析报告.html # 龟龟主报告（HTML）
│   │   ├── {公司名}_{代码}_图表.html    # Plotly 交互图表合集
│   │   ├── 穿透回报率_输出.json        # calc_penetration_return.py --json 输出
│   │   ├── 跟踪验证台账.md              # 预测台账 + 验证协议 + 迭代日志
│   │   ├── qualitative_report.md       # 商业质量分析报告
│   │   └── 图表/                       # PNG 图表（图NN_<名称>.png）
│   └── output/                      # （可选）临时输出 / 中间产物
└── 财报更新验证.md             # ★ 跨批次汇总：每次分析追加一行（分析日期/财报期/当前股价/12M三情景范围/评级/财报要点），支持新财报发布后迭代验证
```

### 3.3 放置规则

| 文件类型 | 必须放置 | 禁止放置 |
|---------|---------|---------|
| 原始数据（财务/行情/行业） | `data/`（批次目录内） | 项目根目录 |
| 模型输入 JSON | `input/` | data/ 或 reports/ |
| 分析/图表/复验脚本 | `scripts/` | **项目外任何位置** |
| 交付报告（MD/HTML/台账） | `reports/`（批次目录内） | data/ 或项目根目录 |
| 图表 PNG | `reports/图表/` | reports/ 根目录 |
| 交互图表 HTML | `reports/`（命名为 `<公司名>_<代码>_图表.html`，批次目录内） | 项目根目录 |
| PDF 年报 | 批次目录（命名为 `<代码>_<年份>_年报.pdf`） | data/ 或 reports/ |

---

## 四、交付清单与交付纪律

### 4.1 交付清单

批次初始化时必须创建 `交付清单.md`（批次目录内），分三节列出所有交付物。**交付时按清单逐项核对并勾选**。

#### 第一节：Phase 0-2 自动产出（数据与预处理）

| # | 交付物 | 位置 | 必需？ | 说明 |
|---|--------|------|--------|------|
| 1 | README.md | 批次目录 | ✓ | 总览信息 |
| 2 | ROADMAP.md | 批次目录 | ✓ | 分析路线图 |
| 3 | data_pack_market.md | data/ | ✓ | §1-§17 市场数据包 |
| 4 | available_fields.json | data/ | ✓ | 可用字段清单 |
| 5 | data_pack_report.md | data/ | 有PDF时 | PDF 附注数据 |
| 6 | 拉取清单.json | data/ | ✓ | 接口拉取记录 |
| 7 | 审计报告.md | data/ | ✓ | 数据审计结果 |
| 8 | qualitative_report.md | reports/ | ✓ | 商业质量分析报告 |
| 9 | calc_penetration_return.py | scripts/ | ✓ | 从 skill 复制 |
| 10 | verification.py | scripts/ | ✓ | 复验脚本（从 skill 复制） |

#### 第二节：Phase 3 分析交付物

| # | 交付物 | 位置 | 必需？ | 说明 |
|---|--------|------|--------|------|
| 11 | {公司名}_{代码}_分析报告.md | reports/ | ✓ | 龟龟主报告（11 章） |
| 12 | {公司名}_{代码}_分析报告.html | reports/ | ✓ | 主报告 HTML 版 |
| 13 | {公司名}_{代码}_图表.html | reports/ | ✓ | Plotly 交互图表合集 |
| 14 | 图表/ 目录（≥10 张 PNG） | reports/图表/ | ✓ | 每张图编号/标题/日期/来源 |
| 15 | 穿透回报率_输入.json | input/ | ✓ | 计算器输入 |
| 16 | 穿透回报率_输出.json | reports/ | ✓ | 计算器输出（与报告一致） |
| 17 | 跟踪验证台账.md | reports/ | ✓ | 预测台账+验证协议+迭代日志 |
| 18 | analyze_charts.py | scripts/ | ✓ | 图表生成脚本（可复现） |
| 19 | README.md 更新 | 批次目录 | ✓ | 评级/目标价/核心逻辑/风险/催化剂 |
| 19.1 | 财报更新验证.md 追加一行 | 项目根目录 | ✓ | 分析日期/财报期/当前股价/12M三情景范围/评级/财报要点 |

#### 第三节：成稿门控确认项（交付前逐项确认）

| # | 确认项 | 标准 |
|---|--------|------|
| G1 | 数据完整性 | 财报 ≥5 年、最新期 ≤6 个月 |
| G2 | 数据一致性 | 三表勾稽容差 ±10% |
| G3 | 支付率口径 | 承诺/公告最低值优先；无承诺取近3年最低档（法2），均值仅交叉参考；DPS 连续相同禁用法1 |
| G4 | AA 口径 | 默认 AA_2y，现金用狭义口径 |
| G5 | \|HH\| < 2pct | 账面-现金偏差已校验，≥2pct 已专项调查 |
| G6 | R_eff vs II | KK 已计算，周期性修正有依据（R_eff 默认主口径 R*；Δc≥2pct 时已降级为 GG） |
| G7 | 脚本复算 | `calc_penetration_return.py` 运行结果与报告一致（**含 G 网格 g_grid**）；手写补充行必须标注「手算/补充」 |
| G8 | 仓位推导链完整 | KK → 可信度 → 陷阱风险，缺环已降档 |
| G9 | 报告 11 章节完整 | 无省略、无合并 |
| G10 | 图表 ≥10 张 | 每张有编号/标题/数据日期/来源 |
| G11 | 关键数字有来源+日期 | 估计值进 Warnings |
| G12 | 脚本全部在 scripts/ 内 | 项目外无任何 .py/.ipynb/.bat/.ps1 |

### 4.2 交付纪律

- **必须按交付清单逐项输出**（含缺失项说明），清单未勾选项不得宣称"已完成"
- 对话中给出结论摘要（评级、目标买入价、仓位建议、核心逻辑 ≤5 条、关键风险）
- 目标买入价与券商目标价口径分离标注（前者是 R_eff 降至门槛对应的最高买价，后者是 12 个月盈利与倍数外推）
- R_eff ≤ II 时不建仓，输出观望/卖出；仓位推导链（含商业模式上限/行业余量/水位/价格）缺一环必须降档或说明

---

## 五、报告格式与内容要求

### 5.1 报告标准

报告严格按 `references/report-template.md` 输出，**11 章节固定，不可调换、不可合并**：

| # | 章节 | 内容要点 |
|---|------|---------|
| 1 | 报告元信息 | 分析日期/框架版本/股价/市值/股本/Rf/上市结构/数据来源/Warnings |
| 2 | Executive Summary | 一句话结论 + 核心数字速览表（OE/R*/GG/Δc/R_eff/II/KK/陷阱/可信度/仓位/置信度）+ 最大优势/风险 |
| 3 | 关键假设 | 7 项假设表（G/支付率/利润折扣系数k/利润口径/现金口径/税率/基准值），每项标注选定值/替代值/敏感性 |
| 4 | 财务趋势速览 | 5 年表（营收/净利/OCF/ROE/有息负债率/DPS/支付率/净现金），含 CAGR |
| 5 | 商业质量分析（6 维摘要） | 商业模式/护城河/外部环境/管理层/MD&A/控股结构，每维结论文 + 输出评级 |
| 6 | 穿透回报率分析 | OE 计算/分配能力/真实可支配现金/主口径 R*+现金校验 GG+有效口径 R_eff/分配意愿/收入敏感性/可信度评级 |
| 7 | 估值与定价 | 门槛与安全边际/仓位决策/价值陷阱排查/股价位置/业绩下滑敏感性/绝对估值 |
| 8 | 综合结论 | 框架汇总框（商业质量/穿透回报率/估值/优势/风险） |
| 9 | 投资论点卡 | 核心论点/买入理由 ≤5 条/预期催化剂/持有周期/止损条件/事件监控/行业与宏观监控 |
| 10 | 风险提示 | 特定风险（描述+量化+对结论影响）+ 待验证事项表 |
| 11 | 数据来源与免责 | 数据来源汇总表 + 免责声明 |

### 5.2 数据与计算要求

- **金额单位**：百万元（人民币），千位逗号分隔（如 96,886.00）
- **每股单位**：元
- **百分比**：保留 2 位小数
- **默认口径**：GAAP 归母、狭义现金、支付率取承诺最低/历史最低档（法2），均值仅交叉参考
- **计算工具**：必须运行 `scripts/calc_penetration_return.py --config input/穿透回报率_输入.json` 复算，**禁止手算**；输入 JSON 字段与口径见该脚本头部文档。**输出契约**：`--json` 时 stdout 只出纯 JSON（人类可读文本走 stderr），`> reports/穿透回报率_输出.json` 作为数字唯一真值；G 敏感性网格 `g_grid` 由脚本默认输出（近3年 Capex/D&A 极差>1.0 时报告必出，见 methodology §1），报告中 G 网格行**禁止手写/手抄**
- **关键数字**：标注来源与日期；估计值（如 Rf）进 Warnings 并说明影响幅度（±0.5pct → 门槛 II ±0.5pct）

### 5.3 图表要求（强制，≥10 张）

| # | 图表 | 类型 | 说明 |
|---|------|------|------|
| 1 | 营收与净利趋势 | 双轴折线 | 营收 + 归母/扣非净利 |
| 2 | 盈利质量 | 多线折线 | 毛利率/净利率/ROE |
| 3 | OCF / Capex / 结余序列 | 柱状图 | 标注连续为负区间 |
| 4 | 杠杆结构 | 柱状/折线 | 有息负债/广义净现金/净负债 |
| 5 | DPS 与支付率趋势 | 双轴折线 | DPS 柱 + 支付率%折线 |
| 6 | 穿透回报率 vs 门槛 | 柱/线组合 | GG vs II + 敏感性情景曲线 |
| 7 | 股价位置 | K 线/折线 | 10 年周线 + 当前价/目标买入价/门槛价格/历史高低点 |
| 8 | 双轨目标价对比 | 柱状图 | 券商目标价 vs 龟龟目标买入价 vs 现价 |
| 9 | 收入敏感性情景 | 分组柱状/热力图 | GG(k) 多情景 vs 门槛 |
| 10 | 外推可信度雷达图 | 雷达图 | 5 维度 |
| 11 | 业绩下滑敏感性 | 热力图/表格图 | 单年 ×0.7~×1.0 / 逐年 ×0.9^n |
| 12 | 绝对估值对标 | 柱状图 | EV/EBITDA / 扣除现金PE / FCF收益率 / 股息率 |

**双输出格式**：
- MD 报告内嵌 PNG（`reports/图表/图NN_<名称>.png`，按章节顺序编号）
- 交互版 Plotly HTML（`reports/<公司>_<代码>_图表.html`）
- 统一由 `scripts/analyze_charts.py` 生成，**必须可复现**

### 5.4 引用规范

- 关键数字标注来源（如 `§3 利润表，2024FY`）+ 日期
- 估计值必须标注"估计"并说明影响幅度
- 不得把股价低/估值高直接当买卖理由
- 安全边际必须来自 GG vs II；仓位建议给出完整推导链（KK → 可信度 → 陷阱风险 → 商业模式上限 → 行业余量 → 水位/价格），缺环降档
- 写作纪律：结论先行、每句断言可溯源、禁用绝对化措辞、不确定处标注"估计/假设/待验证"

---

## 六、Phase 3 核心（穿透回报率估值）

> 详细公式、阈值与决策规则见 `references/methodology.md`。报告组装顺序见 `references/report-template.md`。
> 
> ⚠️ **行业适配**：以下公式为**标准版（适用于工业/消费/科技等非金融行业）**。银行/保险/券商/房地产需按 §〇 的适配方案执行，并在报告中标注"银行适配版"/"保险适配版"等。

### 6.1 核心公式（标准版，非金融行业）

```text
维持性Capex H  = 折旧摊销D × G系数
Owner Earnings  = 归母净利C + D − H
主口径 R*       = C × 折扣系数k × 支付率M / 市值    （k：高0.9/中0.8/低0.7，默认0.8，主估值输入）
账面口径 R      = C × 支付率M / 市值               （交叉校验）
现金校验 GG     = 真实可支配现金AA × M / 市值       （校验口径，验证 R* 有真钱支撑）
现金校验偏差 Δc = R* − GG                          （≥2pct → 现金验证失败，有效口径降级为 GG）
有效口径 R_eff  = R*（默认）；Δc≥2pct 时 = GG       （最终估值输入）
账面-现金偏差 HH = R − GG                          （|HH| ≥ 2pct → 专项调查）
门槛 II         = max(3.5%, Rf + 2%)        （A股；港股 max(5%, Rf+3%)；美股 max(4%, Rf+2%)）
安全边际 JJ     = R_eff − II
修正安全边际 KK = JJ + 周期性修正            （弱周期=0）
目标买入价      = 股价 × R_eff / II
门槛价格        = 股价 × II / R_eff
```

### 6.2 关键口径

| 参数 | 默认值 | 替代方案 |
|------|--------|---------|
| 支付率 M | 承诺/公告最低值优先；无承诺取近3年最低档（法2） | 均值仅交叉参考；DPS 连续多年相同（疑似填充错误）禁用法1 |
| 利润折扣系数 k | 0.8（默认）；可预测性高0.9/中0.8/低0.7 | 保守方向取小值，存疑降档 |
| 真实可支配现金 AA | AA_2y（近2年均值） | AA_all（5年均值）作对比 |
| 现金口径 | 狭义现金 | 广义（差异标注） |
| G 系数 | 轻资产 0.7~0.9；需给依据（近3年 Capex/D&A） | — |
| Rf | 中国10年期国债（A股）；当地Rf（港股/美股） | 缺失时估计，标注影响幅度 |

### 6.3 仓位决策锚点

```text
单股仓位上限 = min(① 商业模式上限, ② KK 候选档, ③ 行业集中度余量) × ④ 市场水位系数
实际仓位     = min(单股仓位上限, ⑤ 价格档位折算)
```

① 商业模式上限（硬顶）：尾部风险/法律边缘 ≤5%；强周期（纸/油/煤/航运/地产链）≤10%；稳定公用/顶级模式 20~30%（保守默认20%）；一般公司从严归类。
② KK 候选档（安全边际驱动）：

| KK | 可信度 | 陷阱风险 | 候选档 |
|----|--------|---------|------|
| ≥1.5pct | 中 | 低 | 70% |
| 1.0~1.5pct | 中 | 低 | 50% |
| <1.0pct 或 可信度低 或 陷阱中/高 | — | — | ≤30%（或观望） |

③ 行业集中度：单一行业合计 ≤30~40%，达上限只建观察仓。
④ 市场水位（弹性差）：低水位（上证≤3000/恒指≤16000）取高档；高水位（上证>3500/恒指>24000）上限×0.7；中水位正常。
⑤ 价格档位：现价 < 买入价×0.8 → 推满；0.8~1.0× → 上限一半；≥ 买入价 → 不买/观察。

R_eff ≤ II 时 → 不建仓，输出观望/卖出。报告必须写出完整推导链：`KK档 → min(候选,商业模式上限,行业余量)×水位 → 价格折算 → 目标仓位`。


### 6.4 §17 预计算优先

§17.10 M 三重校验、§17.11 R*/GG 网格（含目标买入价列）、§17.13 λ 收入敏感性——有网格时查表选行并说明理由，不做手算；仅缺失时走降级手算公式。**§17.12 G 系数网格仅作口径交叉校验，报告内 G 网格行一律以脚本 `g_grid` 输出为准（禁止手抄 §17.12 或手写）**。

独立校验必须运行 `scripts/calc_penetration_return.py --config input/穿透回报率_输入.json`。

---

## 七、质量门控（Gate）

### 7.1 否决门总览

| 阶段 | 否决门 | 判据 | 行为 |
|------|--------|------|------|
| 因子1A | 审计/造假/看不懂/未验证/大股东 | 6 项任一触发 | 停止全部后续分析 |
| 因子1B-M6 | 管理层损害价值 | 模块六判定"损害价值" | 停止后续分析 |
| 因子2-S2 | 分配能力 | FCF 长期为负 + 持续借债 | 一票否决 |
| 因子2-S4① | 主口径 R* < Rf | 连无风险利率都跑不赢 | 否决，不进入因子3 |
| 因子2-S4② | 主口径 R* < II×0.5 | 不足门槛一半 | 否决，不进入因子3 |
| 因子3-S11 | 交叉验证背离 | 因子3 弱于因子1 预期且无法解释 | 大幅折扣或否决 |
| 因子4-S1 | 门槛不达标 | R_eff < II 且成长性占比 < 30% | 排除 |
| 因子4-S2 | 价值陷阱 | 陷阱特征 ≥2 项 且 R_eff < II×1.5 | 排除 |

### 7.2 成稿前质量审计清单（交付前必须逐项确认）

| # | 审计项 | 标准 |
|---|--------|------|
| 1 | 支付率口径 | 承诺/公告最低值或近3年最低档（法2），DPS 连续相同已排除法1 |
| 2 | AA 口径 | 默认 AA_2y，现金狭义口径，口径变化有说明 |
| 3 | \|HH\| 校验 | 账面-现金偏差 <2pct 正常；≥2pct 已专项调查 |
| 4 | 脚本复算 | `calc_penetration_return.py` 输出与报告数字一致 |
| 5 | 仓位推导链 | KK → 可信度 → 陷阱风险 + 商业模式上限 + 行业余量 + 水位/价格 完整，缺环已降档 |
| 6 | R_eff ≤ II 纪律 | 不建仓，输出观望/卖出（R_eff 默认 R*，Δc≥2pct 降级 GG） |
| 7 | Rf 来源标注 | 缺失时估计并标注影响幅度 |
| 8 | k* < 0 处理 | 仅定性解读，不引用精确临界点 |
| 9 | 报告 11 章节 | 无省略、无合并 |
| 10 | 图表 ≥10 张 | 每张有编号/标题/数据日期/来源 |
| 11 | 关键数字有来源+日期 | 估计值进 Warnings |

---

## 八、与 company-research / securities-analysis 的配合

三个技能同时触发时必须按以下分工协作：

| 职责 | company-research | securities-analysis | **guigui-valuation-report（本技能）** |
|------|:---:|:---:|:---:|
| 项目目录创建与管理 | ✓ | — | 独立触发时自行创建 |
| 数据拉取（akshare/东财） | ✓ | — | Tushare/AkShare（独立数据源） |
| 数据审计（三表勾稽） | ✓ | — | 定性分析数据校验 |
| 八步分析框架 | — | ✓ | — |
| DCF/相对价值/并购/LBO | — | ✓ | — |
| 券商深度报告标准 | ✓ | ✓ | — |
| 商业质量分析（6 维） | — | — | ✓ |
| **穿透回报率估值** | 调用本技能 | — | ✓（核心职责） |
| 仓位建议 | — | — | ✓（核心职责） |
| 目标买入价/门槛价格 | — | — | ✓（核心职责） |
| 估值双锚（PE+PB） | — | ✓ | — |
| 研究报告撰写 | ✓（模板+HTML） | ✓（八部分结构） | ✓（11 章龟龟报告） |

**分工原则**：
- **数据与执行**走 company-research
- **券商方法与报告标准**走 securities-analysis
- **穿透回报率与仓位纪律**走本技能

**口径冲突处理**：三者口径冲突时，以各自方法论文件为准，在报告中并列披露。

**报告标准冲突处理（强制）**：协同分析时按 company-research `references/framework.md` §D0《三技能协同报告标准决议》（2026-08-12 拍板）执行——主报告结构=CR 十部分主干（本 skill 11 章映射见决议表）、估值主导权归本 skill（GG 定仓纪律，券商/双锚为参考）、三情景+敏感性双轨、并集 18 张图表、门控统一 G1-G21。

### 与 company-research 协作时的数据流

```
company-research B1-B3（立项/拉数/审计）
    │
    ├── 项目目录已创建（<市场>.<代码> <公司名>/）
    ├── data/ 已有财务数据
    ├── scripts/ 已有 verification.py
    │
    └── company-research B4.4（穿透回报率估值模块）
            │
            ├── 调用本技能 methodology.md 方法论
            ├── 运行 calc_penetration_return.py --config input/穿透回报率_输入.json
            ├── 结果写入 reports/穿透回报率_输出.json
            └── 嵌入主报告（证券分析研究报告.md）的"穿透回报率估值"小节
```

---

## 九、模块与入口速查

| 模块 | 入口 | 说明 |
|------|------|------|
| 龟龟策略（完整流水线） | `strategies/turtle/coordinator.md` | 穿透回报率 + 估值，四因子分析 → 买入/观察/规避 |
| 全流程协调器（Phase 0→3） | `prompts/coordinator.md` | 输入解析、AskUserQuestion、阶段调度、Checkpoint |
| 商业质量分析（PDF-first 单 Agent） | `shared/qualitative/coordinator.md` | 年报 PDF 主数据源 + Greenwald 护城河，6 维度定性评估 |
| 独立估值分析 | `strategies/valuation/coordinator.md` | 自动分类 + DCF/DDM/PE Band/PEG/PS 多方法 |
| 龟龟选股器 | `scripts/screener_core.py` | Tier 1 批量过滤 + Tier 2 深度分析（A/港股 notebook 见 `notebooks/`） |
| 年报自动下载 | `scripts/download_report.py` | Phase 0，失败自动降级 |

---

## 十、注意事项（脚本纪律与强制规则）

### 10.1 脚本纪律（★ 最高优先级）

> **所有分析脚本、复验脚本、图表脚本、数据清洗脚本、临时调试脚本，必须写入项目文件夹下的 `scripts/` 目录。**

- **禁止**在 `G:\理财\个股分析\` 根目录或其他非项目目录下创建任何 `.py` / `.ipynb` / `.bat` / `.ps1` 等可执行或临时脚本文件
- **禁止**在 skill 目录（`C:\Users\小林\.codex\skills\guigui-valuation-report\`）内创建临时脚本
- 项目完成后，`scripts/` 内的脚本作为复验可复现资产保留，不得遗留在项目外
- 若需调试，在项目 `scripts/` 内创建 `debug_*.py`，调试完成后删除或合并入正式脚本

### 10.2 数据与计算纪律

- 关键数字标注来源与日期；估计值（如 Rf）进 Warnings 并说明影响幅度
- 安全边际必须来自 R_eff vs II（R_eff 默认主口径 R*，Δc≥2pct 降级为 GG）；仓位建议给出推导链（KK → 可信度 → 陷阱风险），缺环降档
- 所有脚本结果可复算；`tests/`（920 项）覆盖采集/缓存/网格/一致性/提示词断言
- 金额统一百万元，每股元，比率统一 %；默认口径：GAAP 归母、狭义现金、支付率取承诺最低/历史最低档（法2），均值仅交叉参考
- 支付率等关键指标必须基于同币种数据计算（股息总额与归母净利润均取报表币种），不依赖 yfinance payoutRatio 等衍生字段

### 10.3 市场适用性

- 门槛 II = max(3.5%, Rf+2%) 的 3.5% 下限为 **A 股校准值**
- 港股/美股用当地 Rf+2% 并标注调整，3.5% 下限仅作参考
- 跨市场同行市值统一折算（注明汇率与日期）

### 10.4 分析纪律

- 预测禁止曲棍球棒现象（为证明投资建议而突然提高未来盈利预测）
- 周期股基准情景须含 1~2 年下行周期
- 不得把股价低/估值高直接当买卖理由
- DCF 必须遵守 FCFE/FCFF 二选一规则
- 所有图表由 `scripts/analyze_charts.py` 统一生成、可复现

---

## 十一、参考资料索引

### 核心参考（Phase 3 + 项目标准化）

| 文件 | 内容 | 何时加载 |
|------|------|---------|
| **`references/project-standard.md`** | **★ 项目标准化手册**：目录骨架、文件模板、报告章节、图表清单、交付纪律、质量门控、脚本职责。**每次分析必读** | 项目初始化时 |
| `references/methodology.md` | 穿透回报率完整公式、阈值、决策规则、凌霄泵业已校准示例 | 执行穿透回报率计算时 |
| `references/report-template.md` | 11 章报告模板，每章格式与内容要求 | 撰写报告时 |
| `references/checklist-template.md` | 交付清单模板（三节18项门控） | 项目初始化与交付前 |
| `references/penetration-input-guide.md` | **★ 输入生成与口径判断点指南**：机器字段口径、8 个易错点（EPS单位/分红÷10/序列方向/NaN/理财列名/季报陷阱）、7 个判断点清单（G/M/AA/net_cash/rf/λ）+ 验证对齐清单 | Phase 3B 输入生成与人工确认判断点时 |
| `references/engineering-notes.md`（位于 `~/.codex/skills/company-research/references/engineering-notes.md`） | ★ 工程与运行环境笔记：PowerShell 命令层 / Python I/O 编码 / 接口漂移 / 工具流程坑与规则（实盘事故记录，与 company-research 共享） | 运行/编写任何脚本前必读 |
| `scripts/calc_penetration_return.py` | 确定性计算器，`--config` 输入 JSON，`--json` 输出 JSON，`--selftest` 自检 | 计算 R*/GG/Δc/R_eff/II/KK/目标买入价时 |
| `scripts/build_penetration_input.py` | 输入 JSON 生成器：从三表/分红/日线 CSV 自动计算全部机器字段 + 生成判断点说明 + λ 异常年诊断 | Phase 3B 开始时（强制） |

### 流水线参考

| 文件 | 内容 |
|------|------|
| `prompts/coordinator.md` | 全流程协调器（Phase 0→3 调度） |
| `prompts/phase1_数据采集.md` | Phase 1B WebSearch 补充指令 |
| `prompts/phase2_PDF解析.md` | Phase 2B PDF 精提取指令 |
| `prompts/phase3_分析与报告.md` | Phase 3 精简执行器（因子 1-4 工作流） |
| `prompts/references/factor1_资产质量与商业模式.md` | 因子 1 详细规则 |
| `prompts/references/factor2_穿透回报率粗算.md` | 因子 2 详细规则 |
| `prompts/references/factor3_穿透回报率精算.md` | 因子 3 详细规则 |
| `prompts/references/factor4_估值与安全边际.md` | 因子 4 详细规则 |
| `prompts/references/shared_tables.md` | 共享参数表（支付率/税率/门槛/跨币种） |

### 龟龟策略参考

| 文件 | 内容 |
|------|------|
| `strategies/turtle/coordinator.md` | 龟龟策略协调器（前置条件检查 + Step A/B/C 调度） |
| `strategies/turtle/phase3_quantitative.md` | Agent B 定量分析（11 步穿透回报率） |
| `strategies/turtle/phase3_valuation.md` | Agent C 估值与报告 |
| `strategies/turtle/references/shared_tables.md` | 税率/门槛/公式表 |
| `strategies/turtle/references/factor_interface.md` | 因子间参数传递 schema |

### 定性分析参考

| 文件 | 内容 |
|------|------|
| `shared/qualitative/coordinator.md` | 商业质量分析协调器 v2 |
| `shared/qualitative/qualitative_assessment.md` | 6 维度定性评估框架 |
| `shared/qualitative/references/output_schema.md` | 定性分析输出 schema |
| `shared/qualitative/references/judgment_examples.md` | 关键判断锚点示例 |
| `shared/qualitative/references/industry_metrics_lookup.md` | 36 行业关键指标 |
| `shared/qualitative/references/market_rules_hk.md` | 港股特别规则 |
| `shared/qualitative/references/market_rules_us.md` | 美股特别规则 |

### 估值分析参考

| 文件 | 内容 |
|------|------|
| `strategies/valuation/coordinator.md` | 独立估值分析协调器 |
| `strategies/valuation/references/valuation_methods.md` | DCF/DDM/PE Band/PEG/PS 方法详解 |
| `strategies/valuation/references/classification_rules.md` | 公司自动分类规则 |

### 其他

| 文件 | 内容 |
|------|------|
| `CHANGELOG_V2.md` | v2 变更记录 |
| `qualitative_module_improvements.md` | 定性模块改进记录 |
| `requirements.txt` | Python 依赖 |
| `init.sh` | 一键初始化脚本 |

---

## 十二、环境与依赖

- `TUSHARE_TOKEN`（Tushare Pro）；缺失时自动降级 AkShare（A股）/ yfinance（港美股）
- Python >= 3.10；依赖见 `requirements.txt`（tushare/pandas/pdfplumber/jinja2/yfinance 等）
- 一键初始化：`bash init.sh`（建 venv → 装依赖 → 校验 Token → 跑 `tests/`）
- 运行示例：`python scripts/tushare_collector.py --code 600887.SH --output output/data_pack_market.md`

---

*龟龟投资策略 v2.1-beta | Phase 0–3 完整框架 | 2026-08-11*
