---
name: company-research-v3
description: "证券调研 v3 统一流水线：固定研究框架、Markdown 唯一正文源、Markdown 风格 HTML、固定图表和一键成稿门控。用户说‘调研/分析 公司名或代码’或要求数据拉取、审计、研究报告时触发。适用于 A 股、港股、美股。"
---

# Company Research v3 —— 统一证券调研技能

> v3 基于已完成四项修复的 company-research-v2 建立（2026-10-27），使用本目录内的脚本与参考资料独立维护。

> 本技能由三个原技能合并而来：**company-research**（自动化流水线）、**securities-analysis**（券商深度方法论）、**guigui-valuation-report**（龟龟投资框架 v2.1-beta，穿透回报率估值）。
> 合并后不再需要“同时加载三个技能”，本 `SKILL.md` 为唯一入口；原三份 SKILL.md 存档于 `docs/original-skills/`。

## 概述

一句话触发 → 自动拉数 → 数据审计 → 八步分析 → 交叉验证 → 评级结论。

**统一执行契约**：所有批次按 `references/flow-contract.md` 执行。主报告以 Markdown 为唯一正文源，主报告 HTML 统一由 `scripts/md_to_html.py` 生成；`scripts/report_to_html.py` 仅用于 `shared/qualitative/` 的旧版商业质量仪表盘，不得用于统一主报告。批次内不得新增同功能临时脚本。

用户只需给出 `调研 <公司名或股票代码>`（如“调研 温氏股份”“调研 300498”），本技能自动完成 B1-B3 阶段（立项、拉数、审计），再由 Agent 按券商深度标准完成 B4-B6（八步分析、交叉验证、结论输出），并内置龟龟 Phase 3 穿透回报率估值与仓位纪律。

## 合并说明：原三技能 → 本技能三个模块

| 原技能 | 合并后位置 | 职责 |
|--------|-----------|------|
| company-research | 本技能主体（B1-B6 流水线） | 自动化流水线、数据拉取与审计、脚本执行、报告产出物管理 |
| securities-analysis | `references/证券分析方法论.md`、`估值方法详解.md`、`行业与公司分析框架.md`、`财务分析与预测.md`、`report-template.md` | 格雷厄姆/胡克方法论、八步分析框架、四种估值方法（DCF/相对价值/并购/LBO）、统一主报告结构标准 |
| guigui-valuation-report | `strategies/`、`prompts/`、`shared/`、`references/methodology.md`、`scripts/calc_penetration_return.py` 等 | 龟龟穿透回报率估值（Phase 3）、商业质量分析、独立估值、选股器 |

**口径冲突处理（强制）**：合并后所有口径冲突一律按 `references/framework.md` §D0《三技能协同报告标准决议》（2026-08-12 拍板）执行——十部分主干 / R_eff 现金纪律＋行业适用主方法与验证锚 / 三情景+敏感性双轨 / 固定 18 类图号（不适用按原豁免） / G1-G21 + G9-TEMPLATE + G22 门控，不再现场折中。

## 目录结构

```
company-research-v3/
├── SKILL.md                        # ★ 唯一入口（本文件）
├── README.md                       # GitHub 展示文档
├── requirements.txt                # Python 依赖
├── init.sh                         # 一键初始化（venv + 依赖 + Token 校验 + tests）
├── CHANGELOG.md / CHANGELOG_V2.md  # 变更记录
├── agents/openai.yaml              # 技能界面配置与默认提示词
├── references/                     # 方法论与框架（三技能合并，共 15 份）
│   ├── framework.md                # ★ 完整框架 v2：六阶段流水线、Gate 总表、券商深度标准、三技能报告标准决议
│   ├── methodology.md              # ★ 龟龟穿透回报率公式、阈值、决策规则
│   ├── project-standard.md         # ★ 项目标准化手册（目录骨架、报告章节、交付纪律）
│   ├── 证券分析方法论.md            # 格雷厄姆/胡克核心理论
│   ├── 估值方法详解.md              # 四种估值方法
│   └── ...（完整清单见“参考文件索引”）
├── scripts/                        # 数据流水线 + 图表 + 穿透回报率计算器（两技能合并）
│   ├── research_pipeline.py        # B1-B3 自动流水线（解析/拉数/审计）
│   ├── calc_penetration_return.py  # 穿透回报率确定性计算器
│   ├── build_penetration_input.py  # Phase 3B 输入 JSON 生成器
│   ├── analyze_charts.py           # 统一图表生成（PNG + Plotly 双输出）
│   ├── md_to_html.py                # 主报告 Markdown → 自包含 HTML（唯一入口）
│   ├── chart_qc.py                 # 图表质量门（G8/G8-SENS/G8-INDUSTRY/G8-RENDER）
│   ├── tushare_collector.py        # Tushare Pro 数据采集（A/港/美股，24+ API）
│   ├── akshare_collector.py        # AkShare 降级采集
│   ├── screener_core.py            # 龟龟选股器
│   ├── valuation_engine.py         # 独立估值引擎（DCF/DDM/PE Band/PEG/PS）
│   └── templates-extra/            # 行业模板（港股宏观、乳业、白酒、CM 等）
├── prompts/                        # 龟龟全流程协调器与 Phase 1/2/3 提示词
├── strategies/                     # 龟龟策略 / 独立估值策略协调器
├── shared/                         # 商业质量分析共享模块（6 维度定性评估）
├── tests/                          # pytest（Mock 数据，无需 Token 即可运行）
├── notebooks/                      # 选股器 notebook
├── .claude/commands/               # Claude Code 斜杠命令（/turtle-analysis 等）
└── docs/original-skills/           # 原三份 SKILL.md 存档（历史快照）
```

## 触发方式

| 用户请求 | 执行模式 | 入口 |
|---------|---------|------|
| `调研 <公司名或代码>` | 完整统一流水线（B1-B6 + Phase 3） | `scripts/research_pipeline.py` + `references/framework.md` |
| `分析 <公司名或代码>` | 完整龟龟流水线（Phase 0-3） | `strategies/turtle/coordinator.md` |
| `对 <公司/代码> 做龟龟穿透回报率估值` | 龟龟 Phase 3 估值 | `references/methodology.md` + `scripts/calc_penetration_return.py` |
| `对 <公司/代码> 做商业质量分析` | 商业质量分析（PDF-first 6 维度） | `shared/qualitative/coordinator.md` |
| `对 <公司/代码> 做独立估值分析` | 独立估值（DCF/DDM/PE Band/PEG/PS） | `strategies/valuation/coordinator.md` |
| `用龟龟选股器筛选 ...` | 选股器 | `scripts/screener_core.py` |
| 股票分析 / 估值 / 研究报告 / 行业分析 / 财报分析 | securities-analysis 八步框架 | `references/行业与公司分析框架.md` 等 |

### “调研”触发后的执行顺序（强制）

1. 运行 `python scripts/research_pipeline.py "调研 <公司名/代码>"`（自动完成 B1-B3）
2. 按 `references/framework.md` 的 B-E 节完成 B4-B6，直到输出评级结论
3. **成稿前先读取 `references/report-template.md`，只能使用其中的十部分骨架；禁止使用旧的 11 章、八部分或因子 1A/1B/2/3/4 作为主报告结构。**
4. B6.2 完成 `input/运营补充数据.json`、`input/图表豁免.json` 和 SOTP 检测后，**实际运行并等待** `python scripts/gate_all.py --dir . --report reports/<公司>_<代码>_分析报告.md`：先做期间输入和报告模板预检，再重建图表、主报告 HTML 并检查全部成稿门。不得以脚本已复制、命令已给出或旧PNG存在代替执行；不得使用 `report_to_html.py` 生成主报告。
5. 交付时核查本轮 `reports/流水线执行状态.json` 的 `run_id`、阶段退出码/耗时、输入及产物指纹；只有 `status=PASS` 且 `delivery_ready=true` 才表示本轮技术交付可用。默认完整重建；`--incremental` 仅在输入、代码、正文及全部产物哈希匹配时复用图表与HTML，质量门仍重跑。`build_completed=true` / `fully_rebuilt=true` 只表示本轮全部重建。`--check-only`、`--legacy` 不提供交付或完整构建声明。技术PASS与数据证据等级分别披露，不能将技术门通过写成研究质量升级。

**主报告成文契约（强制）**：一级章节固定为 `1 投资摘要 / 2 宏观与行业分析 / 3 公司分析 / 4 财务分析 / 5 盈利预测 / 6 估值分析 / 7 投资建议与目标价 / 8 催化剂与跟踪 / 9 风险与反证条件 / 10 附录`。每章必须有“内容 + 数据依据 + 本节结论”；第 4 章固定包含 `§4.1` 至 `§4.4`，其余旧模板只作历史参考，不得直接复制。

**脚本模板刷新规则（强制，2026-08-22 用户拍板，牧原 2026_08_22 批次校准）**：每次新建/复验批次时，`scripts/` 下模板类脚本（`analyze_charts.py`、`chart_qc.py`、`fetch_peers_financials.py`、`format_qc.py`、`fetch_with_fallback.py`、`probe_sources.py`、`build_penetration_input.py`、`calc_penetration_return.py` 等）**必须从本 skill `scripts/` 复制最新版本**，禁止直接复制/沿用旧批次 scripts/——旧批次脚本可能落后于模板（如 图03 环形饼图、图16 v4 供需面板、图06 增速兜底、G8-RENDER 门控均为后续校准）。批次内只允许在最新模板之上做项目定制（数据/参数/文案），必要的方法改进必须**写回本 skill 模板**（本 skill 是唯一真源）。判定方法：每次复制后在批次 `scripts/` 记录模板来源与复制日期（可写入批次 `交付清单.md`）。

## 快速开始

**金额与显示精度（2026-10-25）**：主报告正文、表格、图注和阅读台账金额只用亿元／万元，股数用亿股／万股；切换单位须同步换算数值，自适应单位逐格标明。每股、吨均元及销量吨保留。所有标准图与体检图共用`scripts/chart_numbers.py`，显示最多2位小数，极小非零值保留正负方向；原始数据和计算JSON不改精度或尺度。模板门与HTML入口拦截旧金额单位，G8/G22审核实际图中文字；细则见`references/report-template.md`和`references/chart-period-contract.md`。

### 环境要求

- Python >= 3.10
- （推荐）Tushare Pro Token：`TUSHARE_TOKEN`；缺失时自动降级 AkShare（A 股）/ yfinance（港美股）
- 依赖见 `requirements.txt`（tushare / pandas / pdfplumber / jinja2 / yfinance / matplotlib 等）

### 安装

```bash
git clone https://github.com/enhen-x/Company-Research.git company-research-v3
cd company-research-v3
bash init.sh        # 一键初始化：创建 venv → 安装依赖 → 校验 Token → 跑 tests/
```

`init.sh` 会自动完成：查找 Python >= 3.10 → 创建 `.venv` → 安装 `requirements.txt` → 校验 `TUSHARE_TOKEN`（缺失提示降级 AkShare）→ 运行 `tests/` 验证环境。

### 数据采集示例

```bash
# Tushare（推荐）
python scripts/tushare_collector.py --code 600887.SH --output output/data_pack_market.md
# AkShare 降级 / 自动后端
python scripts/akshare_collector.py --code 600887 --output output/data_pack_market.md
python scripts/tushare_collector.py --code 600887.SH --backend auto --output output/data_pack_market.md
```

> 完整“调研”流程无需手动跑采集：`research_pipeline.py` 会自动探测数据源并拉数、审计。


## 统一工作流（六阶段 B1-B6）

### B1 解析与立项（自动）

解析公司名/代码 → 推断市场前缀（6/9→SH，0/3→SZ，4/8/92→BJ）→ 创建项目目录。

**文件夹命名规范（强制）**：每次新建项目文件夹必须为 `<市场>.<代码> <公司名>`（如 `SZ.300498 温氏股份`），代码+名称缺一不可；任一缺失由脚本自动解析（akshare 正/反向查询），解析失败则报错退出并提示补充，禁止用代码代替名称。

**标准文件架构（强制，脚本自动创建，不得改变顶层结构）**：

```
<市场>.<代码> <公司名>/
├── 财报更新验证.md        # ★ 跨批次汇总（v2 批次档案版：回测汇总表 + 每批次预测-实际-归因-迭代档案；模板见 references/project-structure-v3.md §3）
├── <YYYY_MM_DD>/          # 每个分析批次（文件夹名=本次分析的实际日期；新财报后新建，旧批次保留）
│   ├── README.md          # 总览：评级/目标价/核心逻辑/风险/交付状态
│   ├── ROADMAP.md         # B4-B6 八步路线图
│   ├── 交付清单.md         # ★ 交付物清单（B6 交付前逐项核对）
│   ├── data/              # 原始数据：拉取清单.json / 审计报告.html / *.csv
│   ├── input/             # 模型输入：穿透回报率_输入.json（calc_penetration_return.py --config）
│   ├── scripts/           # 复验与图表脚本：verification.py / calc_penetration_return.py / analyze_*.py
│   └── reports/           # 主报告 MD+HTML / 图表/ / 穿透回报率_输出.json / 跟踪验证台账.md
└── <YYYY_MM_DD>/          # 下一批次（新财报后重新分析）
```

**放置规则**：数据只进 `data/`、模型输入只进 `input/`、分析脚本只进 `scripts/`、交付报告只进 `reports/`；图表 PNG 统一 `reports/图表/图NN_*.png`，交互图统一 `<公司名>_<代码>_图表.html`。B1 同时生成 `交付清单.md`（第一节：B1-B3 自动产出；第二节：B4-B6 交付物；第三节：成稿门控）。

### B2 数据拉取（自动，akshare）

**核验接口、有限尝试与候选降级（强制）**：

1. B2通过独立worker导入、核验接口并实际拉取；接口存在和HTTP200不能替代有效数据。需要诊断连通性时可额外运行一次 `python scripts/probe_sources.py <代码> --out <项目>/data`，生成 `data/源探测.json`；已有本轮候选尝试记录时不再为同一故障重复探测。
2. B2入口已直接调用 `fetch_with_fallback.fetch_datasets`，与补拉命令 `python scripts/fetch_with_fallback.py <代码> --out <项目>/data` 共用 `fetch_sources.py` 候选表和 `bounded_fetch.py`；不要执行两套重复拉取。每次尝试在可终止的独立进程中运行，默认单次硬超时30秒、最多2次尝试（可设1~3）、整批预算180秒、失败缓存900秒、成功缓存3600秒。成功复用须核股票、报告期、来源实现与文件哈希；支持 `--timeout`、`--retries`、`--fetch-budget`、`--failure-ttl`、`--success-ttl`、`--force-refresh`。接口缺失不做无效重试，失败切换候选并降级，预算耗尽后明确记录缺口。
   `data/拉取清单.json` 持续记录候选、参数、时间、退出码和失败原因；只有成功才原子更新CSV。失败保留旧CSV时必须标记 `old_file_preserved`，不能称为本轮更新成功。十大股东补拉必须显式提供 `--report-date YYYY-MM-DD`，响应期未确认不得当最新披露使用。
3. 已知源坑位（符号格式/接口缺失/SSL 故障/复权口径/单季表语义）见 `references/data-source-notes.md`，每次分析先浏览，遇新坑按第八节协议补充。

拉取范围：资产负债表、利润表、现金流量表（按报告期）、主要财务指标（报告期+单季度）、日线行情（不复权+前复权）、公司概况/股本/总市值、**分红送配记录**。行业特有数据由 Agent 补充并双源交叉验证；网络失败不中断，缺失项在审计报告中标注。

**行业成本—价格数据（B2.2，乳制品等成本驱动行业必做）**：伊利股份等乳企必须运行 `scripts/fetch_industry_cost_price.py --dir . --profile dairy` 生成 `data/行业成本价格.csv`（生鲜乳收购价 role=cost + 鲜奶零售价 role=price，可加 volume 产量/存栏序列与 margin 价差序列，≥3 年真实历史、双源交叉验证）并审计通过；报告 §2 宏观与行业 必须嵌入 **图16 行业成本与价格走势**（analyze_charts.py v3：供需下方面板 + 成本/价格原始值双轴 + 价差示意，每序列只画自身观测点无断点、横坐标稀疏刻度不重合）。

**穿透回报率估值（龟龟 Phase 3）必需数据**：① 分红送配记录（支付率法2与DPS校验，接口 `ak.stock_fhps_detail_em`）；缺失时从公告核实或明确保留未知，**不得直接用含偿付利息的 `ASSIGN_DIVIDEND_PORFIT` 替代支付率**。② 10年复权+不复权行情；未核实十年覆盖与复权口径时低价锚保持null。③ 无风险利率 Rf（中国10年期国债，A股；港股/美股用当地Rf），缺失时用估计值并必须进 Warnings。

### B3 数据审计（自动）

- **完整性**：各表行数、年份覆盖（目标 ≥10 年）、最新报告期 ≤6 个月
- **一致性**：归母净利 vs EPS×股本、归母权益 vs BPS×股本（容差 ±10%）；现金流审计同时检查 OCF/净利、资本开支、营运资本、应付账款和加盟商结算，不能仅以 OCF/净利含金量下结论
- **异常值**：营收/净利同比突变（>50%）或符号反转、BPS≤0、重复报告期、缺失关键字段——每项须有合理解释（口径/重组/周期），无法解释计入 Warnings
- **分红一致性**：近 3 年 DPS×股本（按除权除息日归集）vs 分配股利支付的现金（容差 ±10%）
- **支付率双法校验**：法1 vs 法2 近 3 年均值，偏差 >5pct 排除法1；DPS ≥3 年完全相同才触发“疑似填充错误”（2 年相同+支付率稳定=平滑分红政策，非错误）
- **OCF 季节性集中度**：近 3 年 Q4 单季占比 >80% 标注；连续多年 >80% 判定常态集中（注明原因），单年突升需调查
- **行业成本—价格审计**（行业适用，B2.2）：`data/行业成本价格_审计.json` 无 FAIL（CSV 契约、cost+price 双序列、每序列 ≥3 行、来源/来源日期齐全）；独立来源 <2 计 Warnings 并在报告标注

**门控**：全部通过→继续；有警告→继续但结论标注数据局限；有错误或财报 <3 年→暂停并降级为初筛报告。

### B3.5 本期财报体检证据层（自动，强制）

**图表最新期规则（B3.6 / G8-PERIOD）**：按 `references/chart-period-contract.md` 执行。主要财务图在原图按年份分组，完整年度空心柱加Q1—Q4季度柱，纳入最新实际；流量季度由累计差分，未完年度不画全年柱。增长折线只保留相邻完整财年的年度同比，率类为年度变动（百分点）；取消季度同比和季度环比线，未完年度不画年度同比点。季度比较保留于证据及正文表格。所有已披露年度和季度柱上均标数字、字号分级；图例、绘图区、横轴刻度和注释间距由实际渲染边界自适应，不能靠固定空白。刻度保留最新年，图例顶部横排。分部/同行/分红按各自披露周期核查。流水线与成稿门检查实际折线、数值、标注覆盖、布局间距及源文件/PNG指纹。修改后须跑最新期正负、排版变体测试与模板回归。

B3 完成后自动运行 `scripts/financial_health_check.py`，生成 `reports/本期财报体检.json`、`reports/本期财报体检_证据摘要.md`、`reports/本期财报体检_成文框架.md` 和 `reports/图表/` 下五张固定体检图。JSON 是唯一数字事实来源，成文框架用于复制到主报告；脚本只生成可复算证据、现金流/利润归因、条件性专项检查和管理层原文摘录，不自动输出“造假”等判断。覆盖 A 股、港股、美股的年报、半年报、一季报、三季报；期间不可比、除数为零和字段缺失必须输出 `null + indeterminate`，不得静默填零。

五张体检图与全部标准图共用自适应布局，副标题/图例/坐标/文字面板/来源注释按实际边界排布。体检图测量与PNG指纹保存为`本期财报体检_图表排版审核.json`并纳入G22。成稿必须核对全部图表及主HTML实际内嵌图片，不能只修图01或独立PNG。

报告第 4 部分固定为 `§4.1 盈利与资产负债表`、`§4.2 现金流与盈利质量`、`§4.3 本期财报体检`、`§4.4 同行业比较`。`§4.3` 改为关键问题导向，依次回答：结论先行、现金流是否赚真钱、经营现金流变化原因、利润波动原因、适用时的存货专项检查、非主营投资和金融资产、管理层解释与数据验证、风险信号、全年预测和估值影响。固定五图分别展示现金流与利润趋势、现金流原因、利润桥、条件性专项检查、管理层解释与后续观察。重要数字和结论加粗。正文使用业务语言，不展示 `income.*`、`balance.*`、`cash.*`、`source_fields` 等程序字段；风险信号以检测类型、状态、结论和后续核查呈现，稳定信号 ID/来源字段保留在 JSON 与证据摘要中。

### B4 八步分析（Agent）

宏观 → 行业 → 公司 → 财务 → 预测 → 估值 → 投资建议 → 综合报告。核心论点以 L4（独立来源交叉验证量化）为目标，达不到时明示证据等级与结论限制；关键数字标注来源+日期。先复用本技能脚本和当前批次 JSON，只有已有脚本不能表达本次计算时才补最小可维护脚本，避免分步 HTML、重复数据和临时报告。

**研究专题（行业选型后按需读取）**：先读 `references/research-topics.md` 的行业与章节映射，再加载适用的指引/订单、驱动预测和反方验证规则。统一输入 `input/研究模型.json`，运行 `python scripts/research_topics.py --dir .` 得到 `reports/研究模型_输出.json`，将结果写入现有 §2/§3/§4/§5/§6/§8/§9；不得新增报告章节、小节或图号。未完成项标记 `INCOMPLETE` 并披露影响，不为过门造数；基础报告仍可如实成稿，技术通过不等于研究通过。

> **输出边界（强制）**：B4 八步为**纯计算/分析层**——只产出可复算数字与固定图表；已有脚本优先，专题只维护一份输入和一份 JSON 输出，**不产成文正文**；步骤7 仅出数字表（评级/三情景目标价矩阵/龟龟目标买入价/门槛价格/仓位推导链的数字），禁止写成文句子；步骤8「综合报告」仅为过程终点汇总，不独立成文，归入 B6.2。所有文案级输出（评级/目标价/投资建议/综合报告/摘要）一律在 **B6.2 唯一成文点** 成文（按 framework.md §D1 十部分）。

**八步内容（securities-analysis 方法论，详见 references/）**：

1. **宏观经济评述**：GDP 增长、利率、通胀、汇率等影响目标公司的关键变量，聚焦而非泛泛。
2. **行业分析**：外部因素/需求/供给/获利能力与定价/国际竞争，回答 8 个关键行业问题，判断生命周期阶段（`references/行业与公司分析框架.md`）。
3. **公司分析**：业务描述、产品与市场、生产与分销、竞争、管理层与治理、竞争优势（品牌/成本/网络效应/转换成本/监管壁垒/技术）；**治理与关联交易量化**。
4. **财务分析**：≥5 年（周期型至少一个完整周期）财务数据、关键比率、3~5 家可比公司、会计操纵识别、现金流量表审查（“银行里的现金难以造假”）、六分类法归类（成熟/成长/周期/衰退/转型/先锋）（`references/财务分析与预测.md`）。
5. **财务预测**：七步骤流程、三种情景（乐观/基准/悲观）、长期预测含至少一次经济衰退、周期型基准情景含 1~2 年下行周期、**周期均值窗口敏感性**（5Y/8Y/10Y/最近 2Y/最近半年 × 估值档 9/11/13x 目标价矩阵）、警惕曲棍球棒。
6. **估值**：按主经济模型选择主方法与交叉验证锚，数据与适用性决定是否采用 PE/PB、DCF、NAV、股权回报或其他方法；并购/LBO 仅在交易与资本结构适用时补充（`references/估值方法详解.md`、`references/research-topics.md`）。
7. **投资建议**：估值汇总、评级、12 个月目标价、催化剂、风险因素。
8. **研究报告**：按 `references/report-template.md` 的唯一十部分结构撰写；八步分析结果映射进十部分，不另起因子报告。

**必备分析模块（缺一不可，详见 framework.md B4.2）**：

1. **分部营收**：行业/产品/地区口径收入占比与增速；口径变更时必须新旧口径并列。
2. **单位产出成本**：单票/单吨/单平米/单客单位经济学（≥3 年+最近季度）+ 同行对比，跨公司口径差异标注。
3. **盈利预测历史支撑**：每个假设有历史/同行/外部依据，按行业建立量价、订单履约、单位经济或专用金融资本约束的驱动桥；将公司指引、共识与独立预测分列。非金融业务连接利润与资本投入/现金，核查H1覆盖率、Q4季节性和剩余期隐含要求；周期/修复类补周期窗口敏感性。
4. **估值双锚 + 分阶段估值带**：双锚按行业选主方法与交叉验证方法，PE/PB仅在适用时采用。采用DCF须匹配现金流、折现率和价值桥，并披露终值/有限寿命；金融不套普通企业FCFF。同行统一日期、盈利/权益、币种和业务口径。图13/14只有适用时构建，豁免写入原配置、正文和清单。
5. **目标价分情况展示与安全边际**：悲观/基准/乐观目标价矩阵与概率（说明事件定义与估计方法）；按格雷厄姆框架量化安全边际；PE、PB、DCF、情景估值共用盈利假设时不得宣称“多个独立安全边际”。
6. **治理与关联交易量化**：股权结构、股权纠纷/减持跟踪路径；重大并购量化对价/现金支付/可辨认净资产/新增商誉/占净资产比例/分部影响/整合里程碑，并说明对 FCFE、净债务和商誉减值的影响。
7. **风险概率与资本结构方法学**：每个风险给概率并注明方法（历史频率/情景推演/趋势外推/规模约束/事件驱动）；负债率不能直接等同于高杠杆，拆分有息/租赁/经营性负债；OCF/净利高不直接等同盈利质量高。
8. **预测与估值逻辑审计**：成稿前反向复算“事实 → 假设 → 模型 → 目标价 → 评级”因果链；所有表格最低值、正文尾部目标价、风险回撤和概率加权目标价必须可由同一组输入复算。
9. **穿透回报率估值（龟龟 Phase 3，基本面分析必做）**：见下方“龟龟 Phase 3 穿透回报率估值”章节。**必须运行** `scripts/calc_penetration_return.py --config 输入.json` 复算，禁止手算。

**SOTP 分部估值（B4.6，平台型公司强制）**：运行 `scripts/sotp_valuation.py --detect-only` 自动检测 + 计算，输出 `reports/sotp_输出.json`，产出图18。

**Capex 与分红跃迁引擎（B4.7，重资产/公用事业/高股息等 Capex 周期标的适用）**：运行 `python scripts/capex_dividend_engine.py --dir . --init-template` 初始化 `input/capex_dividend_plan.json` 并结合年报董事会资本开支指引、重大在建转固进度及《股东回报规划》补齐规划期数据后运行 `python scripts/capex_dividend_engine.py --dir .`（`gate_all.py` 在检测到已启用 `input/capex_dividend_plan.json` 时也会自动重建）。输出 `图19_Capex规划与股价联动.png`、`图20_重大在建工程转固时间轴.png`（写入 §4.2）、`图21_分红可行性与造血留存.png`（写入 §6.4）、`reports/capex_dividend_analysis.json` 与 `reports/Capex与分红跃迁专项.md`。口径严格以同合并扣息 **`扣息FCFE/合并净利润 = (OCF - Capex - 费用化利息) / 合并净利润`** 衡量内生分红支撑力，并叠加年报除权实际分红率对照；禁止添加主观六维雷达或 PE 重估 IRR 矩阵。

**可视化标准（按行业适用性生成，全部嵌入 HTML，脚本可复现）**：分部营收图、单位经济学图、行业成本与价格走势图（图16，乳制品等成本驱动行业必配）、预测支撑图、估值带图（图13 PE_TTM、图14 PB，适用者生成，其余走既有豁免）、目标价图、同行估值对比图、敏感性表（实际采用估值方法的参数矩阵、周期均值窗口矩阵及穿透回报率图11）、复验偏差图（复验时）。图06 的 `peers` 数据必须包含恰好一行 `标的=true`（或 `target=true`）的目标公司，目标公司与同行统一进入散点坐标系；禁止用旧版 `高亮` 字段猜测目标身份。图13/14 的 `pe_high/low/mean` 必须按每个历史时点计算（年度日线区间或明确的滚动窗口），禁止把全历史 max/min/mean 复制到所有年份。主报告 HTML 由 `md_to_html.py` 从 MD 单源生成；Plotly HTML 仅是交互图合集，不承担正文渲染。


#### B4.3 图表→报告章节映射表（强制，写报告时逐章嵌入）

> 每张图表必须出现在对应章节正文中，使用 `![图NN 标题](图表/图NN_名称.png)` 嵌入；正文必须有文字解读与结论指向（禁止“见图NN”敷衍）。**图号固定 01–21（映射表见 report-template.md §3；图18=SOTP 分部估值，平台型公司强制；图19–图21=Capex 与分红跃迁引擎，配置 `input/capex_dividend_plan.json` 时生效），禁止自创编号**。

**图表纪律（2026-08 校准，详见 framework.md）**：

- 能可视化的部分全部出图（≥10 张），PNG 嵌入 MD + Plotly 交互 HTML 双输出；每张图有编号/标题/数据日期/来源，正文有解读与结论指向。
- **图16 断点与刻度纪律**：每序列只画自身观测点（禁止跨序列日期 NaN 断线）、横坐标刻度稀疏（≤10 个）且渲染后不重合、缺口月份在报告中说明、禁止线性补齐。
- **全图横坐标刻度纪律（2026-08-17）**：所有图可见刻度 >12 个必须稀疏化（保留 ≈10 个，用 set_xticks/set_xticklabels，禁止只改 Text 文本——draw 会重置），标签 ≥6 字符自动旋转 30°，渲染后不得文字重合。
- **渲染纪律（2026-08-18，G8-RENDER 校准）**：数值型数据标注（1,234 / 56.2% / 7.06x）不得超出坐标区且相对锚点距离一致（≤22px）；图例不得遮挡数据区（自动移至轴外右上）；脚注/来源用 `transform=ax.transAxes` 放轴外；**图06 同行估值对比一律散点（PE/PB × ROE/股息率，按唯一 `标的=true` 行高亮，禁用柱状堆叠）**；柱状+折线双轴注意柱量纲压缩与标注浮空；**高度自适应**：`fig.legend`/轴外脚注会挤压 axes（图高只占 3/5）——用 `_auto_height` 或轴内系列名标注/顶部水平图例，禁止垂直堆叠高图例。
- **图03 分部营收构成一律环形饼图（2026-08-19 顺丰校准）**：≥3 年并列、图例置图上方横向一排（禁止右侧图例）、年份+营收放环心（禁止子图 set_title）、<3.5% 小分段不标百分比、三段式布局 图题→图例→图表。
- **环形图与双轴图例（2026-10-28 新和成校准）**：图03百分比保持与扇区的数据锚点一致，空白/不可见标签不参与坐标扩展；统一图例必须保留右轴等全部有效系列。实现约束与专项回归见 `references/chart-period-contract.md` 的“自适应排版与柱上数字”。
- **图11口径纪律（2026-10-30）**：有有效历史区间时用`lambda_policy=historical_mean_reference`保留逐段斜率均值，另记可靠性；正负混合不强制置0。图11直接绑定计算器`single_year`，缺运营指定时自动生成。非零λ使用收入倍数横轴；低可靠性在图题/图注明示仅条件参考、不用于盈利预测、不输出k*。真实零均值或旧兼容模式才保留平线并解释，不能声称经营弹性为零；主R_eff及主买价不受λ影响。G8-SENS须准确区分`λ=0`与`λ=0.0117`，脚本模式与计算器不一致须FAIL，人工模式偏差WARN。详见`references/methodology.md`§4。
- **图15口径纪律**：有息负债率是有息负债/总资产（%），不得用贷款/现金替代；净现金显式给单位，未知保留`null`并披露，不补零或画成负现金。
- 成稿前必须运行 `scripts/chart_qc.py` 图表质量门（G8/G8-SENS/G8-INDUSTRY/G8-RENDER）。

### B5 交叉验证

- 多源交叉验证：财务数据（东财/腾讯/新浪/公司公告）、行业数据双源、同行财务（腾讯行情+F10 兜底，`scripts/fetch_peers_financials.py`）。
- 估值交叉验证：行业主方法与适用验证锚；共享假设的多个方法不计独立证据。穿透回报率默认R*，现金验证失败降级GG，以R_eff与II执行原纪律；成长校准不推翻保守轨。
- 结论必须可追溯：目标价推导链、估值倍数来源、关键数字来源+日期。

### B6 结论与交付

- **B6.1 交付清单核对**：按 `交付清单.md` 三节逐项核对（B1-B3 自动产出 / B4-B6 交付物 / 成稿门控）。
- **B6.2 唯一成文点**：评级/目标价/投资建议/综合报告/一页摘要在此成文，且必须逐项套用 `references/report-template.md`（十部分：投资摘要/宏观与行业/公司/财务/盈利预测/估值/投资建议与目标价/催化剂与跟踪/风险与反证/附录）。“估值”章节内嵌穿透回报率估值小节；“投资建议”同时给出市场/券商 12 个月目标价与龟龟目标买入价/门槛价格/仓位建议；每章末尾必须有 `**本节结论**` 和 `> 数据依据：`。
- **跟踪闭环（v2 档案版）**：交付时必须有跟踪验证台账（`references/tracking_template.md`）与复验脚本（`scripts/verification.py`）；下次复验（建议 1 个季度后）先读根目录 `财报更新验证.md` 上一批次档案的预测假设，按台账协议刷新数据、逐项对照预测与实际、归因偏差（数据/审计/预测校准/估值/穿透回报率/结论纪律），把方法论问题写回 framework.md/SKILL.md，并回填新批次档案（偏差 >15% 或触发翻转点 → 更新滚动预测与评级）。

### E 成稿前质量审计清单（强制）

- 一页摘要 60 秒可读、核心论点证据级别 ≥L4、同行对标 ≥5 家、尾部情景完成。
- 结论可追溯：目标价推导链、估值倍数来源、关键数字来源+日期。
- 预测禁止曲棍球棒；周期股包含有依据的下行路径；行业驱动连接利润、现金/资本约束，并核查指引版本、订单转化、季节性与剩余期要求；反方证据须能追到假设和动作。
- DCF 必须遵守 FCFE/FCFF 二选一规则；不能将孤立 FCF、混用折现率或高终值占比包装成精确内在价值。
- **穿透回报率纪律**：基本面分析必须包含龟龟 Phase 3 模块并运行计算脚本；结余（AA）口径变化必须说明理由；外推可信度与价值陷阱评级必须有数据/定性证据支撑，不得臆造；Rf 缺失时用估计值并标注影响幅度（±0.5pct → 门槛 II ±0.5pct）。
- **成长校准轨（2026-08-21 新增）**：高成长标的（净利增速 >15% 或保守轨目标买入价 < 现价×0.6）必须并列输出龟龟成长校准轨（forward）——C_fwd/M_fwd/k_fwd → R*_fwd、KK_fwd、目标买入价_fwd 与「成长验证买入区」；评级锚仍为保守轨 trailing，成长校准轨不得推翻保守轨不建仓结论，升级须由实际数据（中报/季报/合同负债）验证触发。
- **市场适用性**：门槛 II=max(3.5%, Rf+2%) 的 3.5% 下限为 A 股校准值；港股/美股用当地 Rf+2% 并标注调整。
- **逻辑审计门控**：因果链、经营闭环、时间口径（H1 覆盖率、Q4 季节性、不混用季度/年度/TTM）、DCF 口径、可比口径、安全边际假设重叠披露、风险复算、并购与财务质量、穿透回报率口径、仓位纪律（“KK → 可信度 → 陷阱风险”完整推导链；GG≤II 不得建仓；目标买入价与券商目标价口径分离标注）。
- **禁止在项目文件夹外写临时脚本**：所有分析/复验/图表/数据清洗/临时调试脚本必须写入项目文件夹下的 `scripts/` 目录，不得在项目根目录或其他非项目目录创建任何 `.py`/`.ipynb`/`.bat`/`.ps1` 等可执行或临时脚本文件。

### 门控总表（G1-G21 + G9-TEMPLATE + G22，详见 framework.md）

报告章节门控单独编号为 **G9-TEMPLATE**，由 `scripts/report_template_qc.py` 执行；它先于图表/格式门控检查唯一十部分结构、固定财务子节、每章结论/数据依据和占位符。

关键门控：G1 数据完整性 / G2 数据一致性 / G3 支付率口径 / G4 AA 口径 / G5 |HH|<2pct / G6 R_eff vs II / G7 脚本复算（含 g_grid）/ **G8 图表质量**（+G8-SENS 图11契约、G8-INDUSTRY 行业图表、G8-OPS 图06/图15 数据契约、G8-VALUATION-BAND PE/PB 逐时点区间契约、G8-RENDER 渲染级门控）/ **G9-TEMPLATE 报告章节完整** / G10 图表 ≥10 张 / G11 关键数字有来源+日期 / G12 脚本全部在 scripts/ 内 / … / G21 / **G22 本期财报体检**。全部无 FAIL 才可交付；WARN 逐条进交付清单。旧批次只能显式使用 `--legacy` 跳过 G9-TEMPLATE/G22。

## 龟龟 Phase 3 穿透回报率估值（核心模块）

### 适用性与例外（必读）

标准穿透回报率公式（主口径 R* = 归母净利 C × 折扣系数 k × 支付率 M / 市值；现金校验 GG = 真实可支配现金 AA × M / 市值）主要适用于**非金融行业**（工业制造、消费品、医药、科技等）且具备明确 Capex、折旧、经营现金流可辨识的公司。

| 行业 | 问题 | 适配方案 |
|------|------|---------|
| **银行** | OCF 含客户存贷款变动；无传统 Capex/折旧；真实可支配现金由监管资本约束 | 以**可持续股息率**替代 R*/GG 链条，股息覆盖率验证；PB-ROE 交叉确认；DDM 辅助估值 |
| **保险** | 保费收入 ≠ 一般企业营收；准备金计提主观；投资收益率波动大 | 以**内含价值（EV）+ 新业务价值（NBV）**替代 OE 框架 |
| **券商** | 盈利高度周期性；自营波动大；资产负债表以金融资产为主 | 以**ROE 周期均值 × PB**锚定，股息率辅助 |
| **房地产（开发型）** | 合同负债→营收确认时滞；土储重估；高杠杆风险 | 使用**NAV（净资产价值）折让**法 |

> ⚠️ 遇到以上行业必须在报告第 1 章“投资摘要”和第 10 章“附录”中明确标注“标准框架不适用，已采用行业适配方案”并说明适配方法。当 `data_pack_market.md` §17 出现 `AA_2y < 0` 且为金融机构、`|HH| > 5pct`、OCF 正负交替且与盈利趋势无关时，自动触发适配流程。

### 核心公式链（详见 references/methodology.md）

- **Owner Earnings**：H = D × G（D=折旧摊销，G 依据近 3 年 Capex/D&A 判断）
- **真实可支配现金 AA**：默认近 2 年均值 AA_2y（5 年均值 AA_all 对比）；现金用**狭义口径**
- **支付率 M**：法2 = 分配现金 / 归母净利润，近 3 年均值；DPS 连续多年相同**禁止用法1**（承诺/公告最低值优先，无承诺取近 3 年最低档）
- **粗算 R** = C × M / 市值（主口径 R* = C × k × M / 市值）
- **精算 GG** = AA × M / 市值（现金校验）
- **粗算偏差 HH** = R − GG，|HH| ≥ 2pct 需专项调查（>5pct 检查行业归属）
- **有效口径 R_eff**：默认主口径 R*；Δc ≥ 2pct 时降级为 GG
- **门槛 II** = max(3.5%, Rf + 2%)（A 股校准值；港股/美股用当地 Rf+2%）
- **安全边际 KK** = GG − II（弱周期不修正）
- **目标买入价** = 股价 × GG / II；**门槛价格** = 股价 × II / GG
- **5 维外推可信度、5 项价值陷阱排查、业绩下滑敏感性表**（单年 ×0.7~×1.0 与逐年 ×0.9^n，含 k*）
- **绝对估值**：EV/EBITDA、扣除现金 PE、FCF 收益率、净负债/EBITDA、商誉/总资产、股息率、基准价三锚
- **仓位推导链（强制）**：KK → 可信度 → 陷阱风险，缺一环必须降档或说明；GG ≤ II 时不建仓，输出观望/卖出

### 计算脚本（确定性，禁止手算）

```bash
python scripts/build_penetration_input.py --data <项目>/data --out <项目>/input --company <名称> --code <代码>
# Phase 3B：自动生成机器字段及判断说明；默认保护已确认输入，重建须显式 --overwrite。
python scripts/calc_penetration_return.py --config input/穿透回报率_输入.json --json > reports/穿透回报率_输出.json
```

- `--json` 输出为**纯 JSON**（人类可读文本走 stderr），写入 `reports/穿透回报率_输出.json`；**G 敏感性网格（g_grid）由脚本默认输出**，报告中 G 网格行禁止手写。
- 输入 JSON 字段与口径见 `scripts/build_penetration_input.py` / `calc_penetration_return.py` 头部文档与 `references/penetration-input-guide.md`（8 个易错点 + 7 个判断点清单）。

## 商业质量分析（PDF-first 6 维度）

入口：`shared/qualitative/coordinator.md`（v2）。以年报 PDF 为主数据源（pdfplumber 预处理 + 附注精提取），单 Agent 完成 D1-D6 全维度定性评估（含 Greenwald 护城河），输出 `qualitative_report.md`。可独立运行或被龟龟策略复用。要点：

- Phase 0 自动下载年报（`.claude/commands/download-annual-report.md` / `scripts/download_report.py`）
- Tushare 历史序列补充（§1–§17）→ 单 Agent 定性分析（PDF 直接载入 1M context）→ report.md + report.html
- 参考：`shared/qualitative/qualitative_assessment.md`（6 维度框架）、`references/industry_metrics_lookup.md`（36 行业关键指标）、`market_rules_hk.md` / `market_rules_us.md`（港美股特别规则）、`output_schema.md`

## 独立估值分析

入口：`strategies/valuation/coordinator.md`。Python 引擎（`scripts/valuation_engine.py`）+ LLM 定性判断，先按 `references/research-topics.md` 核对行业、生命周期和数据适用性，再使用引擎已支持的 DCF / DDM / PE Band / PEG / PS；旧蓝筹/成长/混合自动分类只作提示，不能覆盖行业禁用条件或宣称完整行业引擎（方法详解见 `strategies/valuation/references/valuation_methods.md`）。估值结果作为分析模块写入统一主报告；如形成对外主报告，必须使用 `references/report-template.md` v3，不得使用估值模块旧版独立报告结构。

## 选股器

`scripts/screener_core.py`（配置 `scripts/screener_config.py`，缓存 `output/.screener_cache/`）：

- **Tier 1 批量过滤**：基本面/估值指标快速过滤全市场
- **Tier 2 深度分析**：对候选股做穿透回报率口径的深度分析
- 支持 A 股 / 港股（`notebooks/screener_hk.ipynb`）；Tushare 缺失自动降级 AkShare
- 测试：`tests/test_screener.py`


## 脚本索引

| 脚本 | 职责 | 运行方式 |
|------|------|---------|
| `scripts/research_pipeline.py` | B1-B3 自动流水线（解析/立项/拉数/审计） | `python scripts/research_pipeline.py "调研 <公司名/代码>"` |
| `scripts/probe_sources.py` | 数据源探测 + 符号规范化（B2 强制前置） | `python scripts/probe_sources.py <代码> --out <项目>/data` |
| `scripts/fetch_with_fallback.py` | 统一拉数适配层（候选源自动切换 + 拉取清单） | `python scripts/fetch_with_fallback.py <代码> --out <项目>/data` |
| `scripts/fetch_supplement.py` | 日线/宏观/同行补拉 | 按 framework.md B2.1 |
| `scripts/fetch_peers_financials.py` | 同行财务 v2（腾讯行情+F10 兜底） | 按 framework.md B2 |
| `scripts/fetch_industry_cost_price.py` | 行业成本—价格数据模板与审计器（图16 数据源） | `python scripts/fetch_industry_cost_price.py --dir . --profile dairy` |
| `scripts/extract_financials.py` | 五年财务摘要 + 股价分位 | 按 framework.md |
| `scripts/analyze_charts.py` | 统一图表 PNG + Plotly 双输出（运营数据走 --ops JSON） | 项目内复制后运行 |
| `scripts/chart_qc.py` | 图表质量门（G8/G8-SENS/G8-INDUSTRY/G8-RENDER） | `python scripts/chart_qc.py --dir . --report reports/<报告>.md` |
| `scripts/format_qc.py` | 格式质量门 | 成稿前 |
| `scripts/gate_all.py` | 图表与 HTML 构建、成稿门控汇总 | 成稿前 |
| `scripts/financial_health_check.py` | B3.5 本期财报体检证据生成（JSON + 摘要 + 成文框架 + 五张固定图） | B3 后自动运行；`python scripts/financial_health_check.py --dir .` |
| `scripts/financial_health_qc.py` | G22 本期财报体检门控与复算（含图表和正文可读性） | `python scripts/financial_health_qc.py --dir . --report reports/<报告>.md` |
| `scripts/report_template_qc.py` | 统一主报告模板门控（十部分/固定财务子节/必写内容/结论/元信息/占位符） | `python scripts/report_template_qc.py --report reports/<报告>.md` |
| `scripts/verification.py` | 复验助手（预测 vs 实际对比、验证快照） | 立项时自动复制进项目 |
| `scripts/sotp_valuation.py` | SOTP 分部估值（平台型公司强制，图18） | `python scripts/sotp_valuation.py --detect-only` |
| `scripts/capex_dividend_engine.py` | Capex 规划、在建转固与分红可行性引擎（图19–图21，同合并扣息 `FCFE/合并NP` 口径） | `python scripts/capex_dividend_engine.py --dir . [--init-template]` |
| `scripts/template_regression.py` | 模板回归测试（合成项目→出图16张→chart_qc 全图自检，发布前必跑，含 --selfcheck 负向自检） | `python scripts/template_regression.py` |
| `scripts/calc_penetration_return.py` | 穿透回报率确定性计算器（OE/R/GG/II/KK/目标买入价/敏感性/绝对估值） | `python scripts/calc_penetration_return.py --config 输入.json` |
| `scripts/build_penetration_input.py` | Phase 3B 输入 JSON 生成器 + 判断点说明 + λ 异常年诊断 | Phase 3B 开始时（强制） |
| `scripts/tushare_collector.py` | Tushare Pro 数据采集（A/港/美股，24+ API） | `python scripts/tushare_collector.py --code 600887.SH --output output/data_pack_market.md` |
| `scripts/akshare_collector.py` | AkShare 降级采集 | `python scripts/akshare_collector.py --code 600887 --output output/data_pack_market.md` |
| `scripts/pdf_preprocessor.py` | 年报 PDF 章节定位（7 个目标章节，pdfplumber） | 按 prompts/coordinator.md |
| `scripts/download_report.py` | 年报 PDF 自动下载 | /download-report 命令 |
| `scripts/screener_core.py` | 龟龟选股器（Tier 1 批量 + Tier 2 深度） | `python scripts/screener_core.py` |
| `scripts/valuation_engine.py` | 独立估值引擎（DCF/DDM/PE Band/PEG/PS，先核对行业适用性） | 按 strategies/valuation/coordinator.md |
| `scripts/research_topics.py` | 行业适用性、指引/订单、驱动预测及反方引用的结构化计算与检查 | `python scripts/research_topics.py --dir .` |
| `scripts/quality_control.py` | 报告质量控制 | 按 prompts/coordinator.md |
| `scripts/report_consistency.py` | 报告一致性检查 | 按 prompts/coordinator.md |
| `scripts/md_to_html.py` | 主报告 MD → 自包含 HTML（Pandoc/GFM，图片内嵌，结构一致性校验） | `python scripts/md_to_html.py --input reports/<报告>.md` |
| `scripts/report_to_html.py` | 旧版商业质量 `qualitative_report.md` → 仪表盘 HTML | 仅按 `shared/qualitative/coordinator.md` 使用，不用于主报告 |
| `scripts/templates-extra/` | 行业模板：港股宏观（fetch_hk_macro.py）、汇率/收益率（fetch_fx_hk_yield.py）、乳业（fetch_liquor_industry.py）、CM（build_ops.py/prep_cm_inputs.py/dcf_cm.py/summary_data.py/run_guigui.py） | 按各自头部文档 |

## 参考文件索引

| 文件 | 内容 | 何时加载 |
|------|------|---------|
| **`references/framework.md`** | ★ 完整框架 v2：六阶段流水线、Gate 总表、券商深度标准、必备分析模块、图表规范、跟踪验证闭环、§D0 三技能报告标准决议 | 每次“调研”分析必读 |
| **`references/flow-contract.md`** | ★ 唯一执行链、产物契约、七个人工判断点、冲突裁决顺序 | 每次“调研”立项和成稿前必读 |
| **`references/project-standard.md`** | ★ 项目标准化手册：目录骨架、文件模板、报告章节、图表清单、交付纪律、质量门控 | 项目初始化时 |
| **`references/methodology.md`** | ★ 穿透回报率完整公式、阈值、决策规则、凌霄泵业已校准示例 | 执行穿透回报率计算时 |
| **`references/penetration-input-guide.md`** | ★ 输入生成与口径判断点指南：机器字段口径、8 个易错点、7 个判断点清单 | Phase 3B 输入生成与人工确认时 |
| `references/report-template.md` | ★ 唯一主报告模板 v3：十部分、固定财务体检子节、每节必写内容与结论句式 | B6.2 成稿前必读 |
| `references/research-topics.md` | 行业估值选型、指引版本/订单质量、驱动预测与反方验证；统一研究模型 JSON 与现有章节映射 | B4行业识别后先读选型/映射，再按适用专题读取 |
| `references/checklist-template.md` | 交付清单模板（三节门控） | 项目初始化与交付前 |
| `references/data-source-notes.md` | 数据源避坑清单（接口缺失/符号格式/SSL 故障/复权口径/单季表语义） | 每次分析先浏览 |
| `references/engineering-notes.md` | ★ 工程与运行环境笔记：PowerShell 命令层 / Python I/O 编码 / 接口漂移 / 工具流程坑与规则（实盘事故记录） | 运行任何脚本前必读 |
| `references/tracking_template.md` | 跟踪验证台账模板（预测-实际对比、偏差归因、skill 迭代日志） | 交付与复验时 |
| `references/project-structure-v3.md` | 项目目录结构 v3 规范（跨批次档案版） | B1 立项时 |
| `references/证券分析方法论.md` | 格雷厄姆/胡克核心理论：内在价值、投资vs投机、质的与量的因素、安全边际、心理因素 | 需要理解分析原则时 |
| `references/估值方法详解.md` | 四种估值方法（DCF/相对价值/并购/LBO）公式、步骤、案例；折现率选择 | 进行估值计算时 |
| `references/行业与公司分析框架.md` | 行业分析要素、公司分析框架、六种公司分类体系 | 进行行业和公司分析时 |
| `references/财务分析与预测.md` | 财务比率、会计数据局限性、管理层操纵识别、财务预测七步骤、三种情景 | 进行财务分析和预测时 |
| `references/研究报告模板.md` | 历史兼容说明（不再作为主报告模板） | 仅追溯旧规则时 |
| `prompts/coordinator.md` | 龟龟全流程协调器（Phase 0→3 调度） | 完整龟龟流水线 |
| `strategies/turtle/coordinator.md` | 龟龟策略协调器（前置条件检查 + Step A/B/C 调度） | 龟龟策略 |
| `strategies/turtle/phase3_quantitative.md` | Agent B 定量分析（11 步穿透回报率） | Phase 3 定量 |
| `strategies/turtle/phase3_valuation.md` | Agent C 估值与报告 | Phase 3 估值 |
| `shared/qualitative/coordinator.md` | 商业质量分析协调器 v2 | 商业质量分析 |
| `shared/qualitative/qualitative_assessment.md` | 6 维度定性评估框架 | 商业质量分析 |
| `strategies/valuation/coordinator.md` | 独立估值分析协调器 | 独立估值 |
| `strategies/valuation/references/valuation_methods.md` | DCF/DDM/PE Band/PEG/PS 方法详解 | 独立估值 |

## 环境与依赖

- `TUSHARE_TOKEN`（Tushare Pro）；缺失时自动降级 AkShare（A股）/ yfinance（港美股）
- Python >= 3.10；依赖见 `requirements.txt`（tushare/pandas/pdfplumber/jinja2/yfinance/matplotlib/pytest/pyarrow/tqdm 等）
- 一键初始化：`bash init.sh`（建 venv → 装依赖 → 校验 Token → 跑 `tests/`）
- 数据单位约定：采集数据包和既有计算JSON保留其声明的内部尺度（Tushare原始元转换为百万元的采集契约不改）；主报告、图注、表格及阅读台账必须另按原尺度换算为**亿元／万元**，股数为亿股／万股，不得将内部尺度直接贴入报告。
- 速率限制：Tushare API 调用自动限速（每次请求间隔 ≥0.3 秒，失败指数退避重试）
- 缓存：选股器 Parquet 分层缓存（`output/.screener_cache/`），stock_basic 7 天 / daily_basic 当日 / Tier2 财务 7 天 / 全局 24 小时

## 维护与更新

- **唯一真源**：本 skill 是模板脚本与方法的唯一真源；项目批次内的方法改进必须写回本 skill（framework.md / SKILL.md / scripts/）。
- **财务输入契约**：三表按相同最近5个完整财年对齐；核心字段缺失拒绝生成，其他未知保留null。`cash_balance` 是货币资金；`net_debt=有息负债−cash_balance`；`working_capital` 不能当现金保护。EBITDA=税前利润+费用化利息+D，普通股权益扣其他权益工具；D总额与明细不得重复。现金保护/十年低价锚须同时提供正值、`*_verified=true` 与 `*_source`；G网格字段 `oe_yield` 是OE收益率，不能当现金AA的GG。详见 `references/penetration-input-guide.md`。
- **成稿性能**：保留全部质量门；G8横轴刻度与最终布局共用同一次figure，禁止额外重建全套图。阶段/图表计时写入执行账本和 `reports/图表检查计时.json`，默认每10秒进度、阶段硬超时300秒、整次1200秒，超时终止进程树。同批次由系统锁防止并发覆盖；输入变化使本轮构建失败，必须完整重跑。
- **发布前必跑**：修改 `scripts/analyze_charts.py` / `chart_qc.py` 后，分别运行 `python scripts/template_regression.py` 与 `python scripts/template_regression.py --selfcheck`，检查正常出图及注入缺陷可被门控发现。默认阶段300秒、整次1200秒、每10秒心跳，超时终止进程树；默认项目与临时目录由父进程清理，含失败/超时。仅显式 `--keep` 保留诊断产物；`--out` 必须指向不存在的新目录，已存在目录直接拒绝，防止覆盖。参数细节用 `--help` 查看。
- **测试**：日常回归使用 `python -B -m pytest --rootdir=. tests/ -q -p no:cacheprovider -m "not integration"`，明确排除真实 API/PDF 集成测试；不能把环境中已有 Token 的全量默认 pytest 当作纯离线运行。仅需要联网验收时显式选择 `-m integration`，并由有界进程调度器设置整体预算；联网结果与离线单测分别记录。
- **多股票阶段回放**：`python scripts/v3_regression.py --root <研究目录> --phase topics|valuation|runtime|build|all --stocks 600039,600887,601899 --output <单份汇总JSON>`。`all` 仅含 topics/valuation/runtime，默认离线、单案例300秒；只复制必要CSV/专题输入到临时目录，历史源hash前后核对。`runtime` 连跑两次检查文件集合与TTL缓存；数据缺口单列 `INCOMPLETE`，不能当研究完成。`build` 需显式选择，复制完整历史批次并保留日期目录名，在父进程持有的临时目录同步当前脚本、实际重建图表和HTML、运行全部成稿门；默认每阶段300秒、每股总1200秒，可用 `--build-stage-timeout` / `--build-total-timeout` 调整。单股失败继续，记录退出原因、运行账本、产物指纹、源文件不变与临时目录清理；重跑仅覆盖单份汇总中的对应阶段。可选 `--online-smoke` 仅探测profile，网络预算15秒/股，不等于完整取数。
- **跟踪闭环**：每次复验把偏差归因到环节（数据/审计/预测校准/估值/穿透回报率/结论纪律），方法论问题写回 framework.md/SKILL.md 并回填批次档案。
- **变更记录**：见 `CHANGELOG.md`（本仓库合并记录）与 `CHANGELOG_V2.md`（龟龟 v2 历史）。

---

*Company Research —— 统一证券调研技能 v3.0（三技能合并版）｜ 由 company-research + securities-analysis + guigui-valuation-report（龟龟 v2.1-beta）合并｜ v3 基线 2026-10-27*
