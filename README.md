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
| Capex与分红跃迁引擎 *(预期差维度)* | 新增 `scripts/capex_dividend_engine.py`（图19–图21）：聚焦周期拐点预期差，以同合并扣息 **`扣息FCFE/合并净利润 = (OCF - Capex - 费用化利息) / 合并净利润`** 与 `(1 - Capex/OCF)` 评估未来资本开支回落与分红跃迁 |
| 穿透回报率法 v3（全行业+术语正式化） | 废除“龟龟”称谓与 Excel 列号；以**维持性现金底座 $OE_{\text{cash}}$ + 分红与注销回购 $p_{\text{dist}}$ + 经 ROIC 校验留存复利 $\eta$** 升级 `calc_penetration_return.py`（v3），适配银行/非银/互联网/制造/消费/公用事业 |

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
| 选股 | `用穿透回报率选股器筛选……` |

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

## 最近更新

### 2026-11-20：穿透回报率法（Look-Through Return Method v3）重构、底层术语正式化与多行业全适配

1. **全面正式化方法论与底层术语（废除“龟龟”与 Excel 列号缩写）**：
   - 将原「龟龟轨 / 龟龟策略」正式定名为 **「穿透回报率法（Look-Through Return Method v3）」** 与 **「穿透回报率轨」**；
   - 底层计算输出新增 `formal_metrics` 与 `look_through_v3`（标准金融符号：$NP, D\&A, \gamma_{\text{maint}}, OE_{\text{cash}}, p_{\text{dist}}, \alpha, \text{ROIC}_{\text{eff}}, \eta, R_{\text{dist}}, R_{\text{retain}}, R_{\text{LT}}, R_{\text{cash}}, R_{\text{eff}}, R_{\text{req}}, MoS, P_{\text{buy}}, P_{\text{floor}}$），同时兼容既有顶层键名与 `report_template_qc.py` 双术语契约；
   - 明确将 **Capex 与分红跃迁引擎（阶段 2）** 划归**预期差维度**另行统筹，不混入内生基础穿透模型。
2. **打破“仅适用成熟零增长纯红利股”的局限**：
   - **剥离扩张性 Capex 错杀**：现金含金量校验由全口径 $AA_{2y}$ 升级为 **维持性现金股东盈余 $OE_{\text{cash}} = \text{OCF}_{\text{扣息}} - D\&A \times \gamma_{\text{maint}}$**；扩产期企业只要维持性现金充足即不再被误判降级；
   - **纳入回购与有效留存复利**：$R_{\text{LT}} = R_{\text{dist}}(\text{分红+注销回购}) + R_{\text{retain}}(\text{经现金含金量与 }\text{ROIC}_{\text{eff}} > R_{\text{req}}\text{ 双重校验的留存复利 } \times \eta)$；含金量不合格或低效留存则强制 $\eta = 0$，守住价值陷阱防线；
   - **六大行业原型全打通**：针对商业银行（监管可分配盈余 + $K_{e,\text{fin}}=7.5\%$ 权益成本底线、近 5 年利润增速兑现度 $\rho_g$ 与 $\eta_{\max}=0.25$）、非银金融（5 年备考平滑 + 并购首年全期年化 + $K_{e,\text{fin}}=6.5\%$ 底线 + 增速兑现度 $\rho_g$ + 破净 $\max(\text{市值},\text{净资产})$ 折价约束）、互联网科技（回购+高ROIC）、制造业/消费（维持性Capex上限+超额净现金调节）与公用事业分别设定严谨校验规则。

### 2026-11-13：阶段 2 Capex 与分红跃迁引擎（预期差维度）正式集成

1. **打通前瞻 Capex 与分红可行性模块（`scripts/capex_dividend_engine.py`）**：
   - 运行 `python scripts/capex_dividend_engine.py --dir . --init-template` 一键生成 `input/capex_dividend_plan.json` 骨架，结合年报/公告补齐未来 3 年资本开支规划、重大在建项目投产节点及《股东回报规划》保底分红承诺后，随 `gate_all.py` 自动重建并与 `chart_qc.py` 门控打通。
2. **彻底修复双重口径错配（合并与扣息一致性）**：
   - 摒弃将 100% 合并现金流 `(OCF - Capex)` 直接除以归母净利润导致的少数股东权益失真及 A 股 `OCF` 未扣费用化利息虚高，统一升级为 **同合并扣息自由现金流覆盖倍数 `(OCF - Capex - 费用化利息) / 合并净利润`**；历年实际分红率则严格由 `分红送配记录.csv` 除权日与分红方案刚性计算锁定。
3. **三张硬核图表与精炼结论模板（图19—图21）**：
   - **图19（§4.2）**：资本开支历史与规划全景曲线 + 前复权股价与历年除权分红节点下联动；
   - **图20（§4.2）**：重大在建工程已投/待投资本开支进度与预计转固达产时间轴；
   - **图21（§6.4）**：`扣息FCFE/合并净利润`（叠加历年实际分红率、本公司个性化保底线及 70%/100% 门槛，支持深度负谷区间分段压缩）与 `(1 - Capex/OCF)` 自主现金留存率；并移除主观六维雷达与 PE 重估 IRR 矩阵，只保留基于财务图表的客观判断。

## 估值与仓位口径

研究结合行业适用方法、三情景预测、敏感性分析及穿透回报率现金纪律。DCF、PE/PB、SOTP 等按行业选择；共用经营假设的多种估值不算独立证据；Capex 规划与分红跃迁（图19–图21）作为周期拐点预期差另行并列。金融及特殊行业按 [方法论](references/methodology.md) 适配。

穿透回报率法（Look-Through Return Method v3）的主要关系为：

| 指标 | 口径 |
| --- | --- |
| 维持性现金底座 $OE_{\text{cash}}$ | 非金融 $\text{OCF}_{\text{扣息}} - D\&A \times \gamma_{\text{maint}}$；银行 $\min(NP, AA_{2y})$；非银采用周期平滑底座 |
| 直接分配回报 $R_{\text{dist}}$ | $(NP_{\text{base}} \times \alpha \times p_{\text{dist}}) \div \text{市值}$（含现金分红与注销式回购） |
| 留存复利回报 $R_{\text{retain}}$ | $[NP_{\text{base}} \times \alpha \times (1 - p_{\text{dist}})_+ \times \eta] \div \text{retain\_denom}$（须通过现金含金量与效率门槛校验；金融须 $\text{ROE} > K_{e,\text{fin}}$ $[7.5\%/6.5\%]$、乘以近 5 年利润增速兑现度 $\rho_g = \text{clip}(g_{\text{actual}}/g_{\text{theo}}, 0, 1)$、$\eta_{\max}=0.25$ 且分母取 $\max(\text{市值},\text{净资产})$，否则 $\eta=0$） |
| 广义穿透 $R_{\text{LT}}$ / 有效 $R_{\text{eff}}$ | $R_{\text{LT}} = R_{\text{dist}} + R_{\text{retain}}$；现金校验合格取 $R_{\text{LT}}$，含金量不足降级为现金分配口径 $R_{\text{cash\_dist}}$ |
| 要求回报门槛 $R_{\text{req}}(II)$ | A股 $\max(3.5\%, R_f+2\%)$；港股 $\max(5.0\%, R_f+3\%)$；美股 $\max(4.0\%, R_f+2\%)$ |
| 穿透安全边际 $MoS(KK)$ | $R_{\text{eff}} - R_{\text{req}}$，再加有依据的周期调整 |
| 穿透目标买入价 $P_{\text{buy}}$ | 当前价 $\times R_{\text{eff}} \div R_{\text{req}}$ |
| 下行保护参考价 $P_{\text{floor}}$ | 当前价 $\times R_{\text{req}} \div R_{\text{eff}}$（$R_{\text{eff}} \le R_{\text{req}}$ 时无效） |

Rf 取当地十年期国债收益率；分红承诺与保守锚选择须有证据。$R_{\text{eff}} \le R_{\text{req}}$ 不建仓，完整仓位还需考虑可预测性、价值陷阱风险、商业质量和集中度约束。12个月目标价与穿透目标买入价分别解释。

### 穿透回报率法五步确定性流程

1. **Step 1｜行业原型识别与盈利基数 $NP_{\text{base}}$**：由 `industry_archetype` 或公司/财报特征自动匹配六大行业原型；若存在重大吸收合并/外源扩表跃迁，按加权净资产口径将并购首年利润年化为全期并表盈利，并将前序单家 5 年均值按净资产或营收体量倍率还原为同口径备考均值；非银金融再据 $\min(NP_{\text{pf}}, 1.25 \times 5\text{Y备考均值})$ 抑制牛市顶点虚高。
2. **Step 2｜维持性现金底座 $OE_{\text{cash}}$ 与现金含金量体检**：非金融采用 $\text{OCF}_{\text{扣息}} - D\&A \times \gamma_{\text{maint}}$（$\gamma_{\text{maint}} = \min(\gamma_{\text{total}}, \gamma_{\text{cap}})$）剥离扩张性 Capex 错杀；商业银行采用监管可分配盈余底座 $\min(NP, AA_{2y})$；非银采用周期平滑稳态盈余。校验覆盖率 $Cov_{\text{cash}} = OE_{\text{cash}} / (NP_{\text{base}} \cdot \alpha) \ge 0.85$ 且分配偏差 $< 2\%$。
3. **Step 3｜广义股东分配率 $p_{\text{dist}}$ 与直接分配回报 $R_{\text{dist}}$**：将现金分红率 $p_{\text{div}}$（历史股本变动 $>10\%$ 时自动按当期股本配比防虚增）与注销式股份回购率 $p_{\text{buyback}}$ 合并计入 $p_{\text{dist}} = \min(1.25, p_{\text{div}} + p_{\text{buyback}})$，核算 $R_{\text{dist}} = (NP_{\text{base}} \cdot \alpha \cdot p_{\text{dist}}) / \text{市值}$。
4. **Step 4｜双重校验计算留存转化率 $\eta$ 与 $R_{\text{retain}}$**：仅当现金含金量合格且资本效率越过门槛（非金融 $\text{ROIC}_{\text{eff}} \ge R_{\text{req}}+2\%$；金融 $\text{ROE} > K_{e,\text{fin}}$）时分段赋予 $\eta$（金融额外刚性乘以近 5 年利润增速兑现度 $\rho_g = \text{clip}(\min(g_{4y}, 0.6 g_{2y}+0.4 g_{4y}) / g_{\text{theo}}, 0, 1)$，负增长直接归零），否则 $\eta$ **强制归零**。非金融以市值作分母；金融对留存项采用 $\max(\text{市值}, \text{净资产})$ 作分母，消除破净股（$\text{PB}<1$）按 $1/\text{PB}$ 虚增复利悖论。
5. **Step 5｜合成有效穿透回报率 $R_{\text{eff}}$ 并锚定买价**：现金校验通过时主取 $R_{\text{LT}} = R_{\text{dist}} + R_{\text{retain}}$，含金量不足则直接降级为现金分配口径 $R_{\text{cash\_dist}}$；对照 $R_{\text{req}}$ 给出安全边际 $MoS$、穿透目标买入价 $P_{\text{buy}}$ 与下行保护参考价 $P_{\text{floor}}$（阶段 2 Capex 与分红跃迁另作预期差分析，不混入内生底座）。

### 六大行业分类及参数适配体系

| 行业原型 (`industry_archetype`) | 维持性底座 $OE_{\text{cash}}$ / $\gamma_{\text{cap}}$ | 资本效率指标 | 留存触发门槛 | 留存上限 $\eta_{\max}$ / 斜率尺度 | 留存项分母 `retain_denom` | 专项边界与交叉锚 |
| --- | --- | --- | --- | --- | --- | --- |
| **互联网与轻资产科技 (`internet_tech`)** | $\text{OCF}_{\text{扣息}} - \min(\gamma_{\text{total}}, 0.80) \cdot D\&A$ | $\text{ROIC}_{\text{eff}}$ | $\ge R_{\text{req}} + 2\%$ | `0.80` / `15%` | $\text{MarketCap}$ | 注销回购计入 $p_{\text{dist}}$，AI/算力扩张 Capex 不误杀 |
| **消费品与零售 (`consumer`)** | $\text{OCF}_{\text{扣息}} - \min(\gamma_{\text{total}}, 0.80) \cdot D\&A$ | $\text{ROIC}_{\text{eff}}$ | $\ge R_{\text{req}} + 2\%$ | `0.80` / `15%` | $\text{MarketCap}$ | 扣减超额净现金衡量真实经营投入资本 |
| **制造业与工业 (`manufacturing`)** | $\text{OCF}_{\text{扣息}} - \min(\gamma_{\text{total}}, 0.90) \cdot D\&A$ | $\text{ROIC}_{\text{eff}}$ | $\ge R_{\text{req}} + 2\%$ | `0.80` / `15%` | $\text{MarketCap}$ | 扩产期不误杀，保留 $\gamma_{\text{maint}}$ 敏感性网格 |
| **公用事业与基础设施 (`utility_infra`)** | $\text{OCF}_{\text{扣息}} - \min(\gamma_{\text{total}}, 0.90) \cdot D\&A$ | $\text{ROIC}_{\text{eff}}$ | $\ge R_{\text{req}} + 2\%$ | `0.55` / `12%` | $\text{MarketCap}$ | 未来 Capex 退坡与分红跃迁单列于预期差 B4.7（图19–21） |
| **商业银行 (`bank`)** | 监管可分配盈余 $\min(NP, AA_{2y})$（$\gamma=0$） | $\text{ROE}$ | $> K_{e,\text{fin}} = \max(7.5\%, R_{\text{req}}+2\%)$ | `0.25 × ρ_g` / `6.5%` | $\max(\text{MarketCap}, \text{BookEquity})$ | 5 年利润增速兑现度 $\rho_g$ 刚性防息差承压高估；叠加 PB-ROE |
| **非银金融 (`non_bank_fin`)** | 周期平滑 $\min(NP_{\text{pf}}, 1.25 \cdot 5\text{Y备考均值})$（$\gamma=0$） | 平滑后 $\text{ROE}$ | $> K_{e,\text{fin}} = \max(6.5\%, R_{\text{req}}+2\%)$ | `0.25 × ρ_g` / `6.5%` | $\max(\text{MarketCap}, \text{BookEquity})$ | 保险参考 P/EV 与 NBV；券商防牛市泡沫与并购错配；受 $\rho_g$ 约束 |
| **防守降级（任一原型不达标）** | $Cov_{\text{cash}} < 0.85$ 或 $\Delta c_{\text{dist}} \ge 2\%$ | 未过上述效率门槛 | — | **强制 $\eta = 0.0$** | — | 现金含金量不足时直接降级现金分配口径 $R_{\text{cash\_dist}}$ |

### 适用边界与方法局限性

穿透回报率法 v3 的核心优势在于**低假设自由度、全锚定已实现报表与铁血现金防守纪律**，但必须清晰界定其真实定位与数学边界——**它是一把针对“已过盈利拐点、现金流可验证的主流成熟/稳态行业”的左侧安全底线尺，而不是一把覆盖所有商业模式的万能成长股公式**。

1. **行业适用边界（6 类盲区须依赖行业专属主锚，v3 仅作辅助或禁用）**：
   - **强周期上游资源、航运与养殖**（煤炭、油气、铜金矿、强周期化工、集运/油运、生猪养殖等）：当前代码对非银金融做了 5 年平滑，但尚未为强周期工业品设置独立的跨周期 5–7 年盈利中枢原型（`矿业 / 海油 / 轮船` 目前暂归 `utility_infra`），若直接在景气顶点或谷底套用当期 $NP$ 与高派息率，会在顶点误判极高安全边际（接飞刀）、在谷底算成 0 元。此类标的主定价须采用跨周期盈利中枢与 PB/重置成本锚。
   - **未盈利或高研发前置型科技与创新药**（Biotech、早期 AI/大模型、先进制程半导体设备、早期 SaaS 等）：模型依赖当期归母净利润 $NP > 0$，且会计准则将研发费用全额费用化，无法靠维持性 $D\&A$ 刻画研发资本积累，须改用管线 rNPV、PS/ARR、EV/Sales 或远期稳态利润折现。
   - **房地产开发与 REITs**：房企预收款与拿地周期导致 OCF 与会计利润大幅错配，“停止拿地缩表躺平”年份 OCF 反而暴增，不可直接套用工业 OCF 含金量规则；REITs 须使用 FFO/AFFO 与底层资产 Cap Rate 体系。
   - **寿险企业的公允价值波动与利差损风险**：IFRS 17/9 准则下险企归母净利润受权益市场短期公允价值波动影响大，单靠利润表与 5 年序列无法捕获保单内含价值（EV）、新业务价值（NBV）与长端利率下行的利差损隐患，须以 P/EV 与精算敏感性为主锚交叉印证。
   - **高股权激励（SBC）的美港股科技公司**：当前非金融 `OE_cash = OCF_扣息 − Capex_maint` 尚未自动扣除 SBC 隐性稀释成本，套用时须在输入阶段手动扣除 SBC 或剔除仅为对冲稀释而非净注销的股份回购。
   - **高超额净现金与控股型投资集团**：模型在计算 $\text{ROIC}_{\text{eff}}$ 时已剥离冗余现金以公允衡量主业效率，但最终按 `Price × R_eff / R_req` 推算目标买价时，**尚未把账面巨额超额净现金或庞大的非并表投资组合直接加回每股估值**；多元控股平台与投资型企业须叠加 SOTP 分部加总。

2. **反映企业增长的三项结构性局限**：
   - **留存转换封顶导致的“重分红、轻高增长”静态偏差**：当非金融现金含金量合格时，目标市值数学等价于 $\frac{NP_{\text{base}} \cdot \alpha \cdot [p_{\text{dist}} + (1-p_{\text{dist}})_+ \cdot \eta]}{R_{\text{req}}}$；由于留存转化上限锁死在 $\eta \le 0.80 < 1.0$，公式本质上将 1 元高 ROIC 留存视为“折价 0.80 元的即期分配”，且用较低的 $R_{\text{req}}$ 封顶估值倍数（通常将 A 股高成长股封顶在 ~18–22x PE、港股 ~13–16x PE），因此必然系统性压低持续 20%+ 复利真成长股的理论买价。
   - **非金融板块尚未检验增速真实兑现度（$\rho_g$）**：金融板块已实装近 5 年利润增速兑现度 $\rho_g$，但消费、制造与互联网等非金融板块目前仍仅检验**存量静态 ROIC**。若老牌成熟企业历史 ROIC 很高，但近 3–5 年利润实际已停滞甚至下滑、新增留存缺乏有效再投资出路，模型仍可能给出偏乐观的 $\eta = 0.80$（需人工结合行业需求拐点与增量 ROIIC 复核，已列入下步阶段 3.5 演进计划）。
   - **单期静态快照缺少多期增长斜率 $g$ 与护城河持续期 $T$**：主公式无法区分“未来 5 年复合增速 20%”与“未来 5 年复合增速 3%”的两家同静态 ROIC 企业；现有 `growth_calib` 仅提供 +1 年可见盈利前瞻参考。因此，对于景气扩张期与真成长标的，必须将穿透目标买价作为**左侧防守底线**，并与 DCF 三情景及后续预期差模块联动定价。

确定性计算示例，在批次目录执行：

```bash
python scripts/calc_penetration_return.py --config "input/穿透回报率_输入.json" --v3 --out "reports/穿透回报率_输出.json" --json
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

2026-11-20 穿透回报率法 v3 与六大行业校准验证：`calc_penetration_return.py --selftest` 通过；`python -m unittest tests/test_look_through_v3_multi_industry.py -v` **7 项核心回归全部通过**（含金融近 5 年利润增速兑现度 $\rho_g$、企业并购/吸收合并跨期体量校准及历史股本分红率配比校验）；全图正向模板回归 `template_regression.py` 通过（`FAIL=0 WARN=4 rc=0`，`report_template_qc.py` `FAIL 0 | WARN 0`）；覆盖银行、非银、互联网、制造、消费与公用事业 6 大行业 11 家典型标的实测收敛。

模板以本仓库为真源。修复应回写 `scripts/`，补充有意义的回归检查，再同步至研究批次；不能只修单份 PNG 或项目副本。工程约束见 [engineering-notes.md](references/engineering-notes.md)，最新期间和排版契约见 [chart-period-contract.md](references/chart-period-contract.md)。

## 仓库导航

| 路径 | 内容 |
| --- | --- |
| [SKILL.md](SKILL.md) | 技能入口、触发规则与执行要求 |
| [references/](references/) | 框架、方法论、报告模板、交付与跟踪规范 |
| [scripts/](scripts/) | 数据、体检、图表、估值、成稿和复验工具 |
| [strategies/](strategies/) / [shared/qualitative/](shared/qualitative/) | 穿透回报率策略、独立估值及商业质量分析流程 |
| [tests/](tests/) | 单元测试、契约检查及离线回归 |
| [CHANGELOG.md](CHANGELOG.md) | 版本与修复记录 |

## License

[MIT](LICENSE)
