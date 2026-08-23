---
name: company-research
description: "统一证券调研技能（原 company-research + securities-analysis + guigui-valuation-report 三技能合并）：一句话触发 → 自动拉数 → 数据审计 → 券商深度八步分析 → 龟龟穿透回报率估值 → 交叉验证 → 评级结论。内置：自动化数据流水线（akshare 拉数 / 三表审计 / 图表门控）、格雷厄姆/胡克证券分析方法论与四种估值法、龟龟 Phase 3 穿透回报率估值（R*/GG/II/KK/目标买入价/仓位建议）、商业质量分析、独立估值（DCF/DDM/PE Band/PEG/PS）、选股器。用户说‘调研/分析 公司名或代码’、‘对 X 做龟龟穿透回报率估值/商业质量分析/独立估值/选股’或要求数据拉取、审计、研究报告时触发。适用于 A 股、港股、美股。"
---

# Company Research —— 统一证券调研技能（三技能合并版）

> 本技能由三个原技能合并而来：**company-research**（自动化流水线）、**securities-analysis**（券商深度方法论）、**guigui-valuation-report**（龟龟投资框架 v2.1-beta，穿透回报率估值）。
> 合并后不再需要“同时加载三个技能”，本 `SKILL.md` 为唯一入口；原三份 SKILL.md 存档于 `docs/original-skills/`。

## 概述

一句话触发 → 自动拉数 → 数据审计 → 八步分析 → 交叉验证 → 评级结论。

用户只需给出 `调研 <公司名或股票代码>`（如“调研 温氏股份”“调研 300498”），本技能自动完成 B1-B3 阶段（立项、拉数、审计），再由 Agent 按券商深度标准完成 B4-B6（八步分析、交叉验证、结论输出），并内置龟龟 Phase 3 穿透回报率估值与仓位纪律。

## 合并说明：原三技能 → 本技能三个模块

| 原技能 | 合并后位置 | 职责 |
|--------|-----------|------|
| company-research | 本技能主体（B1-B6 流水线） | 自动化流水线、数据拉取与审计、脚本执行、报告产出物管理 |
| securities-analysis | `references/证券分析方法论.md`、`估值方法详解.md`、`行业与公司分析框架.md`、`财务分析与预测.md`、`研究报告模板.md` | 格雷厄姆/胡克方法论、八步分析框架、四种估值方法（DCF/相对价值/并购/LBO）、研究报告结构标准 |
| guigui-valuation-report | `strategies/`、`prompts/`、`shared/`、`references/methodology.md`、`scripts/calc_penetration_return.py` 等 | 龟龟穿透回报率估值（Phase 3）、商业质量分析、独立估值、选股器 |

**口径冲突处理（强制）**：合并后所有口径冲突一律按 `references/framework.md` §D0《三技能协同报告标准决议》（2026-08-12 拍板）执行——十部分主干 / GG 主导+双锚 / 三情景+敏感性双轨 / 并集 18 张图表 / G1-G21 门控，不再现场折中。

## 目录结构

```
company-research/
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
3. 成稿前过 E 节《成稿前质量审计清单》与 G1-G21 门控

**脚本模板刷新规则（强制，2026-08-22 用户拍板，牧原 2026_08_22 批次校准）**：每次新建/复验批次时，`scripts/` 下模板类脚本（`analyze_charts.py`、`chart_qc.py`、`fetch_peers_financials.py`、`format_qc.py`、`fetch_with_fallback.py`、`probe_sources.py`、`build_penetration_input.py`、`calc_penetration_return.py` 等）**必须从本 skill `scripts/` 复制最新版本**，禁止直接复制/沿用旧批次 scripts/——旧批次脚本可能落后于模板（如 图03 环形饼图、图16 v4 供需面板、图06 增速兜底、G8-RENDER 门控均为后续校准）。批次内只允许在最新模板之上做项目定制（数据/参数/文案），必要的方法改进必须**写回本 skill 模板**（本 skill 是唯一真源）。判定方法：每次复制后在批次 `scripts/` 记录模板来源与复制日期（可写入批次 `交付清单.md`）。

## 快速开始

### 环境要求

- Python >= 3.10
- （推荐）Tushare Pro Token：`TUSHARE_TOKEN`；缺失时自动降级 AkShare（A 股）/ yfinance（港美股）
- 依赖见 `requirements.txt`（tushare / pandas / pdfplumber / jinja2 / yfinance / matplotlib 等）

### 安装

```bash
git clone <本仓库>  # 或直接作为 Codex skill 安装到 ~/.codex/skills/company-research
cd company-research
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

**先探测后拉取（强制）**：

1. 立项后先运行 `python scripts/probe_sources.py <代码> --out <项目>/data`（约 2 分钟）→ 生成 `data/源探测.json`，列出各数据源（东财/腾讯/新浪）实时连通性与 akshare 接口存在性；
2. 拉数统一走适配层 `python scripts/fetch_with_fallback.py <代码> --out <项目>/data`——每个数据项按候选源自动切换（如日线：东财 stock_zh_a_hist 失败自动换腾讯 stock_zh_a_hist_tx），每次调用记录（源/状态/行数/失败原因）自动写入 `data/拉取清单.json`；接口在当前 akshare 版本缺失的直接标注 MISS，不报错中断；
3. 已知源坑位（符号格式/接口缺失/SSL 故障/复权口径/单季表语义）见 `references/data-source-notes.md`，每次分析先浏览，遇新坑按第八节协议补充。

拉取范围：资产负债表、利润表、现金流量表（按报告期）、主要财务指标（报告期+单季度）、日线行情（不复权+前复权）、公司概况/股本/总市值、**分红送配记录**。行业特有数据由 Agent 补充并双源交叉验证；网络失败不中断，缺失项在审计报告中标注。

**行业成本—价格数据（B2.2，乳制品等成本驱动行业必做）**：伊利股份等乳企必须运行 `scripts/fetch_industry_cost_price.py --dir . --profile dairy` 生成 `data/行业成本价格.csv`（生鲜乳收购价 role=cost + 鲜奶零售价 role=price，可加 volume 产量/存栏序列与 margin 价差序列，≥3 年真实历史、双源交叉验证）并审计通过；报告 §2 宏观与行业 必须嵌入 **图16 行业成本与价格走势**（analyze_charts.py v3：供需下方面板 + 成本/价格原始值双轴 + 价差示意，每序列只画自身观测点无断点、横坐标稀疏刻度不重合）。

**穿透回报率估值（龟龟 Phase 3）必需数据**：① 分红送配记录（支付率法2与DPS校验，接口 `ak.stock_fhps_detail_em`，失败时用现金流量表“分配股利支付的现金”降级）；② 10年复权+不复权行情（股价分位与基准价锚）；③ 无风险利率 Rf（中国10年期国债，A股；港股/美股用当地Rf），缺失时用估计值并必须进 Warnings。

### B3 数据审计（自动）

- **完整性**：各表行数、年份覆盖（目标 ≥10 年）、最新报告期 ≤6 个月
- **一致性**：归母净利 vs EPS×股本、归母权益 vs BPS×股本（容差 ±10%）；现金流审计同时检查 OCF/净利、资本开支、营运资本、应付账款和加盟商结算，不能仅以 OCF/净利含金量下结论
- **异常值**：营收/净利同比突变（>50%）或符号反转、BPS≤0、重复报告期、缺失关键字段——每项须有合理解释（口径/重组/周期），无法解释计入 Warnings
- **分红一致性**：近 3 年 DPS×股本（按除权除息日归集）vs 分配股利支付的现金（容差 ±10%）
- **支付率双法校验**：法1 vs 法2 近 3 年均值，偏差 >5pct 排除法1；DPS ≥3 年完全相同才触发“疑似填充错误”（2 年相同+支付率稳定=平滑分红政策，非错误）
- **OCF 季节性集中度**：近 3 年 Q4 单季占比 >80% 标注；连续多年 >80% 判定常态集中（注明原因），单年突升需调查
- **行业成本—价格审计**（行业适用，B2.2）：`data/行业成本价格_审计.json` 无 FAIL（CSV 契约、cost+price 双序列、每序列 ≥3 行、来源/来源日期齐全）；独立来源 <2 计 Warnings 并在报告标注

**门控**：全部通过→继续；有警告→继续但结论标注数据局限；有错误或财报 <3 年→暂停并降级为初筛报告。

### B4 八步分析（Agent）

宏观 → 行业 → 公司 → 财务 → 预测 → 估值 → 投资建议 → 综合报告。核心论点证据级别 ≥ L4（多来源交叉验证量化）；沿用项目模式 `scripts/analyze_*.py` + `reports/*.html`；关键数字标注来源+日期。

> **输出边界（强制）**：B4 八步为**纯计算/分析层**——只产出可复算数字、图表与 `scripts/analyze_*.py`/`reports/*.html` 分析文件，**不产成文正文**；步骤7 仅出数字表（评级/三情景目标价矩阵/龟龟目标买入价/门槛价格/仓位推导链的数字），禁止写成文句子；步骤8「综合报告」仅为过程终点汇总，不独立成文，归入 B6.2。所有文案级输出（评级/目标价/投资建议/综合报告/摘要）一律在 **B6.2 唯一成文点** 成文（按 framework.md §D1 十部分）。

**八步内容（securities-analysis 方法论，详见 references/）**：

1. **宏观经济评述**：GDP 增长、利率、通胀、汇率等影响目标公司的关键变量，聚焦而非泛泛。
2. **行业分析**：外部因素/需求/供给/获利能力与定价/国际竞争，回答 8 个关键行业问题，判断生命周期阶段（`references/行业与公司分析框架.md`）。
3. **公司分析**：业务描述、产品与市场、生产与分销、竞争、管理层与治理、竞争优势（品牌/成本/网络效应/转换成本/监管壁垒/技术）；**治理与关联交易量化**。
4. **财务分析**：≥5 年（周期型至少一个完整周期）财务数据、关键比率、3~5 家可比公司、会计操纵识别、现金流量表审查（“银行里的现金难以造假”）、六分类法归类（成熟/成长/周期/衰退/转型/先锋）（`references/财务分析与预测.md`）。
5. **财务预测**：七步骤流程、三种情景（乐观/基准/悲观）、长期预测含至少一次经济衰退、周期型基准情景含 1~2 年下行周期、**周期均值窗口敏感性**（5Y/8Y/10Y/最近 2Y/最近半年 × 估值档 9/11/13x 目标价矩阵）、警惕曲棍球棒。
6. **估值**：DCF（FCFE/FCFF 二选一）+ 相对价值（3~5 家可比）+ 并购价值 + LBO 交叉验证（`references/估值方法详解.md`）。
7. **投资建议**：估值汇总、评级、12 个月目标价、催化剂、风险因素。
8. **研究报告**：按十部分/八部分结构撰写。

**必备分析模块（缺一不可，详见 framework.md B4.2）**：

1. **分部营收**：行业/产品/地区口径收入占比与增速；口径变更时必须新旧口径并列。
2. **单位产出成本**：单票/单吨/单平米/单客单位经济学（≥3 年+最近季度）+ 同行对比，跨公司口径差异标注。
3. **盈利预测历史支撑**：每个假设有历史数据锚、同行对标与业绩预告交叉验证；模型必须形成“件量 × 单票收入 = 收入；单票成本/净利率、期间费用、税率、股本 → 归母净利 → EPS”驱动桥；H1 覆盖率、Q4 季节性复核；周期/修复类必须加“周期均值窗口敏感性”。
4. **估值双锚 + 分阶段估值带**：PE（仅盈利正常期）+ PB（跨周期）双指标；历史估值带按成长/出清/修复/成熟分段标注；DCF 必须先明确 FCFE 或 FCFF，FCF 桥接三表，披露终值占比；同行对比统一估值日期/盈利年度/TTM-静态-前瞻/归母-扣非/PB 净资产日期/跨市场汇率，附同行历史估值对比图。
5. **目标价分情况展示与安全边际**：悲观/基准/乐观目标价矩阵与概率（说明事件定义与估计方法）；按格雷厄姆框架量化安全边际；PE、PB、DCF、情景估值共用盈利假设时不得宣称“多个独立安全边际”。
6. **治理与关联交易量化**：股权结构、股权纠纷/减持跟踪路径；重大并购量化对价/现金支付/可辨认净资产/新增商誉/占净资产比例/分部影响/整合里程碑，并说明对 FCFE、净债务和商誉减值的影响。
7. **风险概率与资本结构方法学**：每个风险给概率并注明方法（历史频率/情景推演/趋势外推/规模约束/事件驱动）；负债率不能直接等同于高杠杆，拆分有息/租赁/经营性负债；OCF/净利高不直接等同盈利质量高。
8. **预测与估值逻辑审计**：成稿前反向复算“事实 → 假设 → 模型 → 目标价 → 评级”因果链；所有表格最低值、正文尾部目标价、风险回撤和概率加权目标价必须可由同一组输入复算。
9. **穿透回报率估值（龟龟 Phase 3，基本面分析必做）**：见下方“龟龟 Phase 3 穿透回报率估值”章节。**必须运行** `scripts/calc_penetration_return.py --config 输入.json` 复算，禁止手算。

**SOTP 分部估值（B4.6，平台型公司强制）**：运行 `scripts/sotp_valuation.py --detect-only` 自动检测 + 计算，输出 `reports/sotp_输出.json`，产出图18。

**可视化标准（每份报告必须输出，全部嵌入 HTML，脚本可复现）**：分部营收图、单位经济学图、行业成本与价格走势图（图16，乳制品等成本驱动行业必配）、预测支撑图、估值带图（PE_TTM + PB 各一张）、目标价图、同行估值对比图、敏感性表（DCF 敏感性矩阵 + 周期均值窗口矩阵 + 穿透回报率图11）、复验偏差图（复验时）。


#### B4.3 图表→报告章节映射表（强制，写报告时逐章嵌入）

> 每张图表必须出现在对应章节正文中，使用 `![图NN 标题](图表/图NN_名称.png)` 嵌入；正文必须有文字解读与结论指向（禁止“见图NN”敷衍）。**图号固定 01–18（映射表见 framework.md §B4.3；图18=SOTP 分部估值，平台型公司强制），禁止自创编号**。

**图表纪律（2026-08 校准，详见 framework.md）**：

- 能可视化的部分全部出图（≥10 张），PNG 嵌入 MD + Plotly 交互 HTML 双输出；每张图有编号/标题/数据日期/来源，正文有解读与结论指向。
- **图16 断点与刻度纪律**：每序列只画自身观测点（禁止跨序列日期 NaN 断线）、横坐标刻度稀疏（≤10 个）且渲染后不重合、缺口月份在报告中说明、禁止线性补齐。
- **全图横坐标刻度纪律（2026-08-17）**：所有图可见刻度 >12 个必须稀疏化（保留 ≈10 个，用 set_xticks/set_xticklabels，禁止只改 Text 文本——draw 会重置），标签 ≥6 字符自动旋转 30°，渲染后不得文字重合。
- **渲染纪律（2026-08-18，G8-RENDER 校准）**：数值型数据标注（1,234 / 56.2% / 7.06x）不得超出坐标区且相对锚点距离一致（≤22px）；图例不得遮挡数据区（自动移至轴外右上）；脚注/来源用 `transform=ax.transAxes` 放轴外；**图06 同行估值对比一律散点（PE/PB × ROE/股息率，标的公司高亮，禁用柱状堆叠）**；柱状+折线双轴注意柱量纲压缩与标注浮空；**高度自适应**：`fig.legend`/轴外脚注会挤压 axes（图高只占 3/5）——用 `_auto_height` 或轴内系列名标注/顶部水平图例，禁止垂直堆叠高图例。
- **图03 分部营收构成一律环形饼图（2026-08-19 顺丰校准）**：≥3 年并列、图例置图上方横向一排（禁止右侧图例）、年份+营收放环心（禁止子图 set_title）、<3.5% 小分段不标百分比、三段式布局 图题→图例→图表。
- 成稿前必须运行 `scripts/chart_qc.py` 图表质量门（G8/G8-SENS/G8-INDUSTRY/G8-RENDER）。

### B5 交叉验证

- 多源交叉验证：财务数据（东财/腾讯/新浪/公司公告）、行业数据双源、同行财务（腾讯行情+F10 兜底，`scripts/fetch_peers_financials.py`）。
- 估值交叉验证：DCF + 相对价值 + 并购 + LBO（securities-analysis 四法）+ 龟龟穿透回报率（GG 主导，券商/双锚参考）。
- 结论必须可追溯：目标价推导链、估值倍数来源、关键数字来源+日期。

### B6 结论与交付

- **B6.1 交付清单核对**：按 `交付清单.md` 三节逐项核对（B1-B3 自动产出 / B4-B6 交付物 / 成稿门控）。
- **B6.2 唯一成文点**：评级/目标价/投资建议/综合报告/一页摘要在此成文（framework.md §D1 十部分：投资摘要/行业/公司/财务/盈利预测/估值/投资建议/催化剂与跟踪/风险/附录）。“估值”章节内嵌穿透回报率估值小节；“投资建议”同时给出券商目标价（12 个月）与龟龟目标买入价/门槛价格/仓位建议。
- **跟踪闭环（v2 档案版）**：交付时必须有跟踪验证台账（`references/tracking_template.md`）与复验脚本（`scripts/verification.py`）；下次复验（建议 1 个季度后）先读根目录 `财报更新验证.md` 上一批次档案的预测假设，按台账协议刷新数据、逐项对照预测与实际、归因偏差（数据/审计/预测校准/估值/穿透回报率/结论纪律），把方法论问题写回 framework.md/SKILL.md，并回填新批次档案（偏差 >15% 或触发翻转点 → 更新滚动预测与评级）。

### E 成稿前质量审计清单（强制）

- 一页摘要 60 秒可读、核心论点证据级别 ≥L4、同行对标 ≥5 家、尾部情景完成。
- 结论可追溯：目标价推导链、估值倍数来源、关键数字来源+日期。
- 预测禁止曲棍球棒；周期股基准情景须含 1~2 年下行周期；预测有件量/价格/成本/费用/税率/股本驱动桥和 H1、季节性复核。
- DCF 必须遵守 FCFE/FCFF 二选一规则；不能将孤立 FCF、混用折现率或高终值占比包装成精确内在价值。
- **穿透回报率纪律**：基本面分析必须包含龟龟 Phase 3 模块并运行计算脚本；结余（AA）口径变化必须说明理由；外推可信度与价值陷阱评级必须有数据/定性证据支撑，不得臆造；Rf 缺失时用估计值并标注影响幅度（±0.5pct → 门槛 II ±0.5pct）。
- **成长校准轨（2026-08-21 新增）**：高成长标的（净利增速 >15% 或保守轨目标买入价 < 现价×0.6）必须并列输出龟龟成长校准轨（forward）——C_fwd/M_fwd/k_fwd → R*_fwd、KK_fwd、目标买入价_fwd 与「成长验证买入区」；评级锚仍为保守轨 trailing，成长校准轨不得推翻保守轨不建仓结论，升级须由实际数据（中报/季报/合同负债）验证触发。
- **市场适用性**：门槛 II=max(3.5%, Rf+2%) 的 3.5% 下限为 A 股校准值；港股/美股用当地 Rf+2% 并标注调整。
- **逻辑审计门控**：因果链、经营闭环、时间口径（H1 覆盖率、Q4 季节性、不混用季度/年度/TTM）、DCF 口径、可比口径、安全边际假设重叠披露、风险复算、并购与财务质量、穿透回报率口径、仓位纪律（“KK → 可信度 → 陷阱风险”完整推导链；GG≤II 不得建仓；目标买入价与券商目标价口径分离标注）。
- **禁止在项目文件夹外写临时脚本**：所有分析/复验/图表/数据清洗/临时调试脚本必须写入项目文件夹下的 `scripts/` 目录，不得在项目根目录或其他非项目目录创建任何 `.py`/`.ipynb`/`.bat`/`.ps1` 等可执行或临时脚本文件。

### 门控总表（G1-G21，详见 framework.md）

关键门控：G1 数据完整性 / G2 数据一致性 / G3 支付率口径 / G4 AA 口径 / G5 |HH|<2pct / G6 R_eff vs II / G7 脚本复算（含 g_grid）/ **G8 图表质量**（+G8-SENS 图11契约、G8-INDUSTRY 行业图表、G8-RENDER 渲染级门控）/ G9 报告章节完整 / G10 图表 ≥10 张 / G11 关键数字有来源+日期 / G12 脚本全部在 scripts/ 内 / … / G21。全部无 FAIL 才可交付；WARN 逐条进交付清单。

## 龟龟 Phase 3 穿透回报率估值（核心模块）

### 适用性与例外（必读）

标准穿透回报率公式（主口径 R* = 归母净利 C × 折扣系数 k × 支付率 M / 市值；现金校验 GG = 真实可支配现金 AA × M / 市值）主要适用于**非金融行业**（工业制造、消费品、医药、科技等）且具备明确 Capex、折旧、经营现金流可辨识的公司。

| 行业 | 问题 | 适配方案 |
|------|------|---------|
| **银行** | OCF 含客户存贷款变动；无传统 Capex/折旧；真实可支配现金由监管资本约束 | 以**可持续股息率**替代 R*/GG 链条，股息覆盖率验证；PB-ROE 交叉确认；DDM 辅助估值 |
| **保险** | 保费收入 ≠ 一般企业营收；准备金计提主观；投资收益率波动大 | 以**内含价值（EV）+ 新业务价值（NBV）**替代 OE 框架 |
| **券商** | 盈利高度周期性；自营波动大；资产负债表以金融资产为主 | 以**ROE 周期均值 × PB**锚定，股息率辅助 |
| **房地产（开发型）** | 合同负债→营收确认时滞；土储重估；高杠杆风险 | 使用**NAV（净资产价值）折让**法 |

> ⚠️ 遇到以上行业必须在报告 Warnings 和 Executive Summary 中明确标注“标准框架不适用，已采用行业适配方案”并说明适配方法。当 `data_pack_market.md` §17 出现 `AA_2y < 0` 且为金融机构、`|HH| > 5pct`、OCF 正负交替且与盈利趋势无关时，自动触发适配流程。

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
python scripts/build_penetration_input.py <项目>   # Phase 3B 强制：从三表/分红/日线 CSV 自动计算机器字段 + 生成判断点说明
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

入口：`strategies/valuation/coordinator.md`。Python 引擎（`scripts/valuation_engine.py`）+ LLM 定性判断，按公司自动分类（`strategies/valuation/references/classification_rules.md`）选择方法：DCF / DDM / PE Band / PEG / PS（方法详解见 `strategies/valuation/references/valuation_methods.md`），输出独立估值报告（`strategies/valuation/references/report_template.md`）。

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
| `scripts/gate_all.py` | 门控汇总 | 成稿前 |
| `scripts/verification.py` | 复验助手（预测 vs 实际对比、验证快照） | 立项时自动复制进项目 |
| `scripts/sotp_valuation.py` | SOTP 分部估值（平台型公司强制，图18） | `python scripts/sotp_valuation.py --detect-only` |
| `scripts/template_regression.py` | 模板回归测试（合成项目→出图16张→chart_qc 全图自检，发布前必跑，含 --selfcheck 负向自检） | `python scripts/template_regression.py` |
| `scripts/calc_penetration_return.py` | 穿透回报率确定性计算器（OE/R/GG/II/KK/目标买入价/敏感性/绝对估值） | `python scripts/calc_penetration_return.py --config 输入.json` |
| `scripts/build_penetration_input.py` | Phase 3B 输入 JSON 生成器 + 判断点说明 + λ 异常年诊断 | Phase 3B 开始时（强制） |
| `scripts/tushare_collector.py` | Tushare Pro 数据采集（A/港/美股，24+ API） | `python scripts/tushare_collector.py --code 600887.SH --output output/data_pack_market.md` |
| `scripts/akshare_collector.py` | AkShare 降级采集 | `python scripts/akshare_collector.py --code 600887 --output output/data_pack_market.md` |
| `scripts/pdf_preprocessor.py` | 年报 PDF 章节定位（7 个目标章节，pdfplumber） | 按 prompts/coordinator.md |
| `scripts/download_report.py` | 年报 PDF 自动下载 | /download-report 命令 |
| `scripts/screener_core.py` | 龟龟选股器（Tier 1 批量 + Tier 2 深度） | `python scripts/screener_core.py` |
| `scripts/valuation_engine.py` | 独立估值引擎（DCF/DDM/PE Band/PEG/PS） | 按 strategies/valuation/coordinator.md |
| `scripts/quality_control.py` | 报告质量控制 | 按 prompts/coordinator.md |
| `scripts/report_consistency.py` | 报告一致性检查 | 按 prompts/coordinator.md |
| `scripts/report_to_html.py` | MD → HTML 报告（Jinja2，暗色模式/KPI 卡片） | 按 prompts/coordinator.md |
| `scripts/templates-extra/` | 行业模板：港股宏观（fetch_hk_macro.py）、汇率/收益率（fetch_fx_hk_yield.py）、乳业（fetch_liquor_industry.py）、CM（build_ops.py/prep_cm_inputs.py/dcf_cm.py/summary_data.py/run_guigui.py） | 按各自头部文档 |

## 参考文件索引

| 文件 | 内容 | 何时加载 |
|------|------|---------|
| **`references/framework.md`** | ★ 完整框架 v2：六阶段流水线、Gate 总表、券商深度标准、必备分析模块、图表规范、跟踪验证闭环、§D0 三技能报告标准决议 | 每次“调研”分析必读 |
| **`references/project-standard.md`** | ★ 项目标准化手册：目录骨架、文件模板、报告章节、图表清单、交付纪律、质量门控 | 项目初始化时 |
| **`references/methodology.md`** | ★ 穿透回报率完整公式、阈值、决策规则、凌霄泵业已校准示例 | 执行穿透回报率计算时 |
| **`references/penetration-input-guide.md`** | ★ 输入生成与口径判断点指南：机器字段口径、8 个易错点、7 个判断点清单 | Phase 3B 输入生成与人工确认时 |
| `references/report-template.md` | 11 章报告模板（龟龟），每章格式与内容要求 | 撰写报告时 |
| `references/checklist-template.md` | 交付清单模板（三节门控） | 项目初始化与交付前 |
| `references/data-source-notes.md` | 数据源避坑清单（接口缺失/符号格式/SSL 故障/复权口径/单季表语义） | 每次分析先浏览 |
| `references/engineering-notes.md` | ★ 工程与运行环境笔记：PowerShell 命令层 / Python I/O 编码 / 接口漂移 / 工具流程坑与规则（实盘事故记录） | 运行任何脚本前必读 |
| `references/tracking_template.md` | 跟踪验证台账模板（预测-实际对比、偏差归因、skill 迭代日志） | 交付与复验时 |
| `references/project-structure-v3.md` | 项目目录结构 v3 规范（跨批次档案版） | B1 立项时 |
| `references/证券分析方法论.md` | 格雷厄姆/胡克核心理论：内在价值、投资vs投机、质的与量的因素、安全边际、心理因素 | 需要理解分析原则时 |
| `references/估值方法详解.md` | 四种估值方法（DCF/相对价值/并购/LBO）公式、步骤、案例；折现率选择 | 进行估值计算时 |
| `references/行业与公司分析框架.md` | 行业分析要素、公司分析框架、六种公司分类体系 | 进行行业和公司分析时 |
| `references/财务分析与预测.md` | 财务比率、会计数据局限性、管理层操纵识别、财务预测七步骤、三种情景 | 进行财务分析和预测时 |
| `references/研究报告模板.md` | 研究报告八部分结构、撰写指南、格式要求 | 撰写研究报告时 |
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
- 数据单位约定：所有金额统一为**百万元（RMB）**（Tushare 原始数据（元）采集时自动 ÷1,000,000）
- 速率限制：Tushare API 调用自动限速（每次请求间隔 ≥0.3 秒，失败指数退避重试）
- 缓存：选股器 Parquet 分层缓存（`output/.screener_cache/`），stock_basic 7 天 / daily_basic 当日 / Tier2 财务 7 天 / 全局 24 小时

## 维护与更新

- **唯一真源**：本 skill 是模板脚本与方法的唯一真源；项目批次内的方法改进必须写回本 skill（framework.md / SKILL.md / scripts/）。
- **发布前必跑**：修改 `scripts/analyze_charts.py` / `chart_qc.py` 后，运行 `python scripts/template_regression.py`（合成项目 → 出图16张 → chart_qc 全图自检，含 `--selfcheck` 负向自检）。
- **测试**：`.venv/bin/python -m pytest tests/ -v`（Mock 数据，无需 Token；覆盖 Tushare 采集、PDF 预处理、提示词、协调器、输出格式、选股器等）。
- **跟踪闭环**：每次复验把偏差归因到环节（数据/审计/预测校准/估值/穿透回报率/结论纪律），方法论问题写回 framework.md/SKILL.md 并回填批次档案。
- **变更记录**：见 `CHANGELOG.md`（本仓库合并记录）与 `CHANGELOG_V2.md`（龟龟 v2 历史）。

---

*Company Research —— 统一证券调研技能 v1.0（三技能合并版）｜ 由 company-research + securities-analysis + guigui-valuation-report（龟龟 v2.1-beta）合并｜ 2026-08-23*
