# Company Research —— 统一证券调研技能

> **一句话触发**：`调研 <公司名或股票代码>` → 自动拉数 → 数据审计 → 券商深度八步分析 → 穿透回报率估值 → 交叉验证 → 评级结论。
> 适用于 **A 股 / 港股 / 美股**。

---

## 目录

- [核心能力](#核心能力)
- [快速开始](#快速开始)
- [使用示例](#使用示例)
- [统一工作流](#统一工作流)
- [穿透回报率估值](#穿透回报率估值龟龟框架)
- [目录结构](#目录结构)
- [测试](#测试)
- [环境与数据源](#环境与数据源)
- [常见问题](#常见问题)
- [License](#license)

---

## 核心能力

| 模块 | 能力 | 入口 |
|------|------|------|
| 📊 数据流水线 | 解析公司/代码 → 探测数据源 → 带兜底的拉数 → 三表审计 | `scripts/research_pipeline.py` |
| 🏛️ 券商深度分析 | 宏观→行业→公司→财务→预测→估值→建议→报告 八步框架（格雷厄姆/胡克方法论、四种估值方法） | `references/framework.md` |
| 🐢 穿透回报率估值 | OE / R\* / GG / II / KK / 目标买入价 / 仓位建议 | `references/methodology.md` + `scripts/calc_penetration_return.py` |
| 🏭 商业质量分析 | PDF-first 6 维度定性评估（Greenwald 护城河） | `shared/qualitative/coordinator.md` |
| 💰 独立估值 | DCF / DDM / PE Band / PEG / PS | `strategies/valuation/coordinator.md` |
| 🔍 选股器 | Tier 1 批量过滤 + Tier 2 深度分析 | `scripts/screener_core.py` |
| 📈 图表与门控 | 图 01–18 固定映射、PNG+Plotly 双输出、G8 渲染级质量门 | `scripts/analyze_charts.py` / `chart_qc.py` |
| 📋 跟踪闭环 | 预测-实际台账、季度复验、偏差归因、方法回写 | `scripts/verification.py` + `references/tracking_template.md` |

## 快速开始

### 环境要求

- Python >= 3.10
- （推荐）[Tushare Pro](https://tushare.pro/) Token：`TUSHARE_TOKEN`；缺失时自动降级 **AkShare**（A 股）/ **yfinance**（港美股）
- 依赖见 [`requirements.txt`](requirements.txt)

### 安装

```bash
# 1. 克隆本仓库（或作为 Codex/Claude skill 安装到 ~/.codex/skills/company-research）
git clone <repo-url> company-research
cd company-research

# 2. 一键初始化：创建 venv → 安装依赖 → 校验 Token → 运行测试
bash init.sh
```

### 第一次分析

```bash
# 自动完成 B1-B3（立项、拉数、审计）
python scripts/research_pipeline.py "调研 温氏股份"

# 查看数据包（也可用 Tushare 直接采集）
python scripts/tushare_collector.py --code 300498.SZ --output output/data_pack_market.md
```

## 使用示例

| 你想做什么 | 输入 |
|-----------|------|
| 完整调研（推荐） | `调研 温氏股份` / `调研 300498` |
| 完整分析流水线 | `分析 温氏股份` |
| 穿透回报率估值 | `对 温氏股份 做穿透回报率估值` |
| 商业质量分析 | `对 温氏股份 做商业质量分析` |
| 独立估值 | `对 温氏股份 做独立估值分析` |
| 选股 | `用选股器筛选 ...` |

## 统一工作流

```
调研 <公司名/代码>
   │
   ├─ B1 解析与立项 ──► <市场>.<代码> <公司名>/ + <YYYY_MM_DD>/ 批次目录
   ├─ B2 数据拉取 ────► probe_sources → fetch_with_fallback（东财/腾讯/新浪多源兜底）
   ├─ B3 数据审计 ────► 三表勾稽 / 异常值 / 分红一致性 / 支付率双法 / OCF 季节性
   ├─ B4 八步分析 ────► 宏观→行业→公司→财务→预测→估值→建议→报告（9 必备模块）
   │                     └─ 穿透回报率估值（calc_penetration_return.py）
   ├─ B5 交叉验证 ────► 多源 / 多方法估值交叉验证 / 逻辑审计
   ├─ B6 结论与交付 ──► 十部分报告 + 交付清单核对 + 跟踪验证台账
   └─ E   成稿审计 ────► G1-G21 门控 + chart_qc 图表质量门
```

## 穿透回报率估值（龟龟框架）

**主口径 R\* = 归母净利 C × 折扣系数 k × 支付率 M / 市值**；**现金校验 GG = 真实可支配现金 AA × M / 市值**。

- **门槛 II** = max(3.5%, Rf + 2%)（A 股校准；港/美股用当地 Rf+2%）
- **安全边际 KK** = GG − II
- **目标买入价** = 股价 × GG / II；**门槛价格** = 股价 × II / GG
- **仓位推导链**：KK → 外推可信度 → 价值陷阱风险（缺环降档；GG≤II 不建仓）

银行/保险/券商/地产等金融行业自动触发**行业适配方案**（可持续股息率 / EV+NBV / ROE×PB / NAV 折让），详见 `references/methodology.md`。

```bash
python scripts/build_penetration_input.py <项目>            # 生成输入 JSON
python scripts/calc_penetration_return.py --config input/穿透回报率_输入.json --json
```

## 目录结构

```
company-research/
├── SKILL.md                      # ★ 技能唯一入口
├── README.md                     # 本文件
├── init.sh / requirements.txt    # 环境
├── agents/openai.yaml            # 技能界面配置
├── references/                   # 方法论与框架（framework / methodology / 证券分析方法论等）
├── scripts/                      # 数据流水线 / 图表 / 估值计算器 / 选股器
├── prompts/                      # 全流程协调器与 Phase 1/2/3 提示词
├── strategies/                   # 分析策略 / 独立估值策略
├── shared/                       # 商业质量分析共享模块
├── tests/                        # pytest 测试（Mock 数据，无需 Token）
├── notebooks/                    # 选股器 notebook
└── .claude/commands/             # Claude Code 斜杠命令
```

## 测试

```bash
.venv/bin/python -m pytest tests/ -v          # 全部测试（Mock 数据，无需 Token）
.venv/bin/python -m pytest tests/test_screener.py -v   # 单文件
.venv/bin/python -m pytest tests/ -x -q       # 快速模式
```

覆盖：Tushare 采集 + 衍生指标、PDF 预处理、Phase 提示词、协调器、输出格式、年报下载、选股器、增量刷新、报告一致性等（当前 920 passed / 3 skipped）。

## 环境与数据源

| 数据源 | 用途 | 说明 |
|--------|------|------|
| Tushare Pro | 财务三表 / 行情 / 指标 / 分红（A/港/美股） | 需 `TUSHARE_TOKEN`，自动限速 ≥0.3s/次 |
| AkShare | 降级采集（A 股） | Tushare 缺失时自动启用 |
| yfinance | 降级采集（港/美股） | 同上 |
| 东财 / 腾讯 / 新浪 | 拉数多源兜底（数据流水线 B2） | `fetch_with_fallback.py` 自动切换 |

- 金额统一为**百万元（RMB）**（Tushare 原始数据自动 ÷1,000,000）
- 选股器 Parquet 分层缓存：`output/.screener_cache/`
- 所有脚本运行前先读 `references/engineering-notes.md`（实盘事故记录）

## 常见问题

**Q：没有 Tushare Token 能用吗？**
可以。自动降级 AkShare / yfinance；完整“调研”流水线（research_pipeline.py）走东财/腾讯/新浪多源兜底。

**Q：这个技能在 Codex / Claude 里怎么用？**
将本仓库复制到 `~/.codex/skills/company-research/`（或按你的 skill 安装方式），然后直接说“调研 某某公司”。

**Q：图表质量门是什么？**
成稿前运行 `scripts/chart_qc.py`，自动检查图号映射、PNG 引用、横坐标刻度渲染、数据标注越界、图例遮挡、图16 行业成本—价格契约等（G8/G8-SENS/G8-INDUSTRY/G8-RENDER），FAIL 项必须修复后才能交付。

## License

[MIT](LICENSE)

---

*Company Research —— 统一证券调研技能 v1.0 ｜ 2026-08-23*
