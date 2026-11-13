# Company Research v3

面向 A 股、港股和美股的统一证券调研技能，将数据采集、财报核查、公司研究、盈利预测、估值、报告成稿和后续复验连接为一套可追溯流程。

**本仓库默认分支现维护 v3，技能入口为 `$company-research-v3`。** 在支持技能的 AI 助手中输入“调研 公司名或股票代码”，即可按 [SKILL.md](SKILL.md) 执行完整研究。

## v3 的主要变化

| 变化 | 实际行为 |
| --- | --- |
| 统一报告 | 固定十章结构，Markdown 是唯一正文源；主报告 HTML 由 `md_to_html.py` 生成并内嵌图片 |
| 本期财报体检 | 生成可复算 JSON、证据摘要和五张固定体检图，检查增长、现金化、营运资本及非主营贡献 |
| 最新期间图表 | 完整年度与季度实际分别展示，累计流量差分为单季，避免半年冒充全年、预测冒充实际 |
| 有界数据采集 | 候选源切换、硬超时、有限重试和缓存；保留旧数据时明确标记本轮更新失败 |
| 研究专题计算 | 指引、经营驱动、预测、反方及估值结果集中于结构化输入与输出，缺口保留 `INCOMPLETE` |
| 成稿执行记录 | 每轮记录 `run_id`、阶段状态、退出码、耗时和输入/产物哈希；技术结果与研究证据等级分别披露 |
| 图表修复 | 环形图清理空标签，保持百分比与扇区一致；双轴图合并全部有效系列，保留右轴价格图例 |
| Capex与分红跃迁引擎 | 新增 `scripts/capex_dividend_engine.py`（图19–图21）：融合未来资本开支规划与前复权股价/除权分红节点、重大在建工程转固时间轴，以及同合并扣息口径 **`扣息FCFE/合并净利润 = (OCF - Capex - 费用化利息) / 合并净利润`** 与 `(1 - Capex/OCF)` 现金留存率走势 |

版本变更见 [CHANGELOG.md](CHANGELOG.md)，完整执行规则见 [流水线契约](references/flow-contract.md)。

## 安装

环境要求：

- Python 3.10 或更高版本，依赖见 [requirements.txt](requirements.txt)。
- [Pandoc 3.x](https://pandoc.org/installing.html)，用于生成自包含主报告 HTML；安装后确认 `pandoc --version` 可运行。
- 中文图表需要可用的中文字体，例如 Microsoft YaHei、SimHei；按运行环境配置。
- Tushare Pro Token 可选；缺少 Token 时，支持的数据项使用 AkShare / yfinance 等候选源，实际覆盖以拉取清单为准。

克隆并安装 Python 依赖，建议在虚拟环境中执行：

```bash
git clone https://github.com/enhen-x/Company-Research.git company-research-v3
cd company-research-v3
python -m pip install -r requirements.txt
pandoc --version
```

在 Codex 中使用时，将仓库放在 `~/.codex/skills/company-research-v3/`。其他支持技能的助手按各自安装方式加载本仓库的 `SKILL.md`；Claude Code 命令入口位于 `.claude/commands/`。

可选配置：复制 `.env.sample` 为 `.env`，填入自己的 `TUSHARE_TOKEN`；也可通过同名环境变量提供。`.env` 已被 Git 忽略。Linux / macOS 可使用 `bash init.sh` 创建虚拟环境、安装依赖并运行初始化检查；Windows PowerShell 可直接使用上面的 Python 命令。

## 快速使用

### 在 AI 助手中发起研究

```text
$company-research-v3 调研 新和成（002001）
```

也可使用以下请求：

| 任务 | 示例 |
| --- | --- |
| 完整公司研究 | `调研 新和成` / `分析 002001` |
| 穿透回报率估值 | `对 新和成 做穿透回报率估值` |
| 商业质量分析 | `对 新和成 做商业质量分析` |
| 独立估值 | `对 新和成 做独立估值分析` |
| 选股 | `用龟龟选股器筛选……` |

### 仅运行数据流水线

在仓库根目录执行：

```bash
python scripts/research_pipeline.py "调研 新和成" --root "./research"
```

该命令完成立项、候选源拉数、审计、财报体检和最新期间证据，并建立研究批次。行业补证、商业判断、预测假设及正文由 AI 助手继续按框架完成；单次拉数命令不代表完整研究已完成。

### 完成模型与正文后成稿

在对应批次目录执行：

```bash
python scripts/gate_all.py --dir . --report "reports/新和成_002001_分析报告.md"
```

统一入口先做期间和模板预检，再重建固定图表、交互图表 HTML 与主报告 HTML，执行财报体检、图表、格式和适用的 SOTP 检查。模型输入、图表豁免与 SOTP 触发状态须按技能契约准备齐全。

## 研究流程与产物

```text
B1 立项：公司目录、日期批次、复制最新脚本
 ↓
B2—B3：有界拉数、三表与分红审计、缺口记录
 ↓
B3.5—B3.6：财报体检证据、最新实际期间
 ↓
B4—B5：宏观行业 → 公司质量 → 财务 → 预测 → 估值 → 交叉验证
 ↓
B6：形成唯一 Markdown 正文，重建图表与 HTML，核查交付状态
 ↓
后续批次：预测与实际对照、归因、修正与跟踪
```

主报告固定为十章：投资摘要、宏观与行业分析、公司分析、财务分析、盈利预测、估值分析、投资建议与目标价、催化剂与跟踪、风险与反证条件、附录。正文模板见 [report-template.md](references/report-template.md)。

每家公司按日期保留批次，典型结构如下：

```text
SZ.002001 新和成/
├── 财报更新验证.md                 # 跨批次预测与实际档案
└── YYYY_MM_DD/
    ├── README.md / ROADMAP.md / 交付清单.md
    ├── data/                      # 原始数据、拉取清单、审计报告
    ├── input/                     # 模型、判断、运营补充及豁免输入
    ├── scripts/                   # 本批次使用的模板和复验脚本
    └── reports/
        ├── 新和成_002001_分析报告.md
        ├── 新和成_002001_分析报告.html
        ├── 新和成_002001_图表.html
        ├── 图表/                  # 按适用性生成的标准图与五张体检图
        ├── 本期财报体检.json
        ├── 穿透回报率_输出.json
        ├── 流水线执行状态.json
        └── 跟踪验证台账.md
```

标准图号固定为图01—图18（适用平台型触发图18；启用 `input/capex_dividend_plan.json` 时额外生成图19—图21 嵌入 §4.2 与 §6.4），适用性、期间、来源与豁免须明示；图表数量随公司和批次而变。首次研究没有事前预测样本时，不凭空生成历史预测胜率。

## 最近更新（2026-11-13：阶段 2 Capex 与分红跃迁引擎正式集成）

1. **打通前瞻 Capex 与分红可行性模块（`scripts/capex_dividend_engine.py`）**：
   - 运行 `python scripts/capex_dividend_engine.py --dir . --init-template` 一键生成 `input/capex_dividend_plan.json` 骨架，结合年报/公告补齐未来 3 年资本开支规划、重大在建项目投产节点及《股东回报规划》保底分红承诺后，随 `gate_all.py` 自动重建并与 `chart_qc.py` 门控打通。
2. **彻底修复双重口径错配（合并与扣息一致性）**：
   - 摒弃将 100% 合并现金流 `(OCF - Capex)` 直接除以归母净利润导致的少数股东权益失真及 A 股 `OCF` 未扣费用化利息虚高，统一升级为 **同合并扣息自由现金流覆盖倍数 `(OCF - Capex - 费用化利息) / 合并净利润`**；历年实际分红率则严格由 `分红送配记录.csv` 除权日与分红方案刚性计算锁定。
3. **三张硬核图表与精炼结论模板（图19—图21）**：
   - **图19（§4.2）**：资本开支历史与规划全景曲线 + 前复权股价与历年除权分红节点下联动；
   - **图20（§4.2）**：重大在建工程已投/待投资本开支进度与预计转固达产时间轴；
   - **图21（§6.4）**：`扣息FCFE/合并净利润`（叠加历年实际分红率、本公司个性化保底线及 70%/100% 门槛，支持深度负谷区间分段压缩）与 `(1 - Capex/OCF)` 自主现金留存率；并移除主观六维雷达与 PE 重估 IRR 矩阵，只保留基于财务图表的客观判断。

## 估值与仓位口径

研究结合行业适用方法、三情景预测、敏感性分析及龟龟现金纪律。DCF、PE/PB、SOTP 等按行业选择；共用经营假设的多种估值不算独立证据。金融及特殊行业按 [方法论](references/methodology.md) 适配。

龟龟框架的主要关系为：

| 指标 | 口径 |
| --- | --- |
| R* | 归母净利 C × 利润折扣 k × 支付率 M ÷ 市值 |
| GG | 真实可支配现金 AA × 支付率 M ÷ 市值，作为现金校验 |
| R_eff | 默认 R*；R*−GG≥2个百分点时，现金校验失败，降级为 GG |
| 门槛 II | A股 max(3.5%, Rf+2%)；港股 max(5%, Rf+3%)；美股 max(4%, Rf+2%) |
| 安全边际 KK | R_eff−II，再加有依据的周期调整 |
| 目标买入价 | 当前价 × R_eff ÷ II |
| 门槛价格 | 当前价 × II ÷ R_eff；R_eff≤0时无定义，R_eff≤II时不作为下行保护 |

Rf 取当地十年期国债收益率；M 的承诺、历史分红及保守锚选择须有证据。R_eff≤II 不建仓，完整仓位还需考虑可预测性、价值陷阱风险、商业质量和集中度约束。12个月目标价与龟龟目标买入价分别解释。

确定性计算示例，在批次目录执行：

```bash
python scripts/calc_penetration_return.py --config "input/穿透回报率_输入.json" --out "reports/穿透回报率_输出.json"
```

原始数据和计算 JSON 保留各脚本定义的单位与精度；对读者展示的金额统一亿元／万元，股数统一亿股／万股，数字最多两位小数。每股价格、单价和实物数量按其自身单位展示，切换单位须同步换算。

## 如何判断交付完成

检查**本轮** `reports/流水线执行状态.json`：

- `status=PASS` 且 `delivery_ready=true`：本轮技术交付可用。
- `fully_rebuilt=true`：本轮完整重建图表和 HTML。
- `run_id`、阶段状态/退出码/耗时、输入和产物 SHA256：用于复核执行过程和文件版本；进程内检查不补造子进程退出码。
- `research_quality`、证据等级和披露的研究缺口：与技术结果分别判断，技术 PASS 不等于研究完整或证据升级。

`--check-only` 只检查现有文件，不提供交付或重建声明；`--incremental` 仅在输入、代码、正文和全部产物指纹匹配时复用构建，质量门仍重跑；`--legacy` 仅用于显式兼容历史批次。阶段与全流程预算可用 `--stage-timeout` / `--total-timeout` 调整，失败后应按执行账本定位原因。

## 数据源与限制

| 数据来源 | 主要用途 | 使用边界 |
| --- | --- | --- |
| 公司公告、原版年报与中报 | 业务、附注、分红、管理层解释 | 公司自述与独立证据分开标注 |
| Tushare Pro | 支持市场的三表、行情、指标与分红 | 需要 Token 及相应权限 |
| AkShare / 东财 / 腾讯 / 新浪等候选 | A股数据流水线及替代来源 | 按数据项切换，成功以有效数据和报告期核验为准 |
| yfinance | 港美股采集的候选来源 | 覆盖、字段及历史长度以实际获取结果为准 |
| 行业公开资料 | 供需、价格、成本与同行比较 | 核对规格、日期和独立性，同源转载不计为独立双源 |

网络失败、期间不可比或字段缺失均须留痕，不静默填零或把旧文件称为本轮更新成功。不能取得的单品量价、维持性资本开支、现金流桥等，保留未知并说明对结论的影响。

## 测试与维护

在仓库根目录运行：

```bash
# 不调用在线集成测试
python -m pytest tests/ -q -m "not integration"

# 环形图百分比与双轴图例专项
python -m pytest tests/test_segment_label_layout.py -q

# 合成数据的全图模板回归，以及注入旧布局错误的负向自检
python scripts/template_regression.py
python scripts/template_regression.py --selfcheck
```

在线集成测试使用 `python -m pytest tests/ -m integration -v`，需配置相应 Token、权限和测试资料。

2026-10-28 本次发布验证：离线测试 **1611 项通过**，3 项在线集成测试未执行；README 的本地链接与 Pandoc 渲染检查通过。

2026-11-13 阶段 2 集成验证：新增与管线定向测试（`test_capex_dividend_engine.py`、`test_chart_exemptions.py`、`test_report_build_pipeline.py`、`test_gate_incremental.py`、`test_v3_regression.py`）**90 项全部通过**，全图正向模板回归 `template_regression.py` 通过（`FAIL=0 WARN=4 rc=0`）；全量离线套件实测 **1615 项通过**（另有 9 项源自原基线 `test_chart_periods.py` / `test_pipeline_repairs.py` / `test_valuation_repairs.py` 的既有用例失败，本次改动未引入回归）。

模板以本仓库为真源。修复应回写 `scripts/`，补充有意义的回归检查，再同步至研究批次；不能只修单份 PNG 或项目副本。工程约束见 [engineering-notes.md](references/engineering-notes.md)，最新期间和排版契约见 [chart-period-contract.md](references/chart-period-contract.md)。

## 仓库导航

| 路径 | 内容 |
| --- | --- |
| [SKILL.md](SKILL.md) | 技能入口、触发规则与执行要求 |
| [references/](references/) | 框架、方法论、报告模板、交付与跟踪规范 |
| [scripts/](scripts/) | 数据、体检、图表、估值、成稿和复验工具 |
| [strategies/](strategies/) / [shared/qualitative/](shared/qualitative/) | 龟龟、独立估值及商业质量分析流程 |
| [tests/](tests/) | 单元测试、契约检查及离线回归 |
| [CHANGELOG.md](CHANGELOG.md) | 版本与修复记录 |

## License

[MIT](LICENSE)
