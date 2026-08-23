# Changelog

## [1.0.1] - 2026-08-23 — 中远海控批次事故修复（模板回写）

### 修复（流水线/模板/审核/门控）

- **fetch_peers_financials.py**：港股同行支持（`代码.市场:名称`，如 `00316.HK:东方海外国际`）；港股行情取腾讯（PE/市值），PB/财务数据提示手工补齐；不再误判为深市。
- **build_penetration_input.py**：股本/市值优先取 `data/公司概况.csv`（腾讯实时，含回购注销），>3% 偏差告警，消除历史口径股本导致的市值偏差。
- **analyze_charts.py**：
  - 图13/14 估值带：新增 `_fnum` 清洗（None→NaN），亏损年 PE 不再使 `fill_between` 崩溃；
  - 图16 行业成本—价格：`_pick_even_ticks` 强制相邻刻度最小间隔并超限抽稀，刻度 ≥6 自动旋转 25°，消除月度观测过密的刻度重合 G8 FAIL；
  - 图04 盈利能力：图例移至图下，消除与数据区重叠。
- **sotp_valuation.py**：实现 `--force`；`运营补充数据.json` 支持 `sotp_trigger`（growth / listed_subsidiaries）作为 C4 多估值锚直接触发，覆盖"单一收入主导但多估值锚"平台型（如中远海控：集运营收 >70% 但东方海外/中远海运港口为上市子公司）。
- **format_qc.py**：F7 标记闭合先剔除代码围栏/行内代码，单星计数排除 `R*` 等术语字面量，消除误报。
- **calc_penetration_return.py**：新增 `--out` 直接写 UTF-8 JSON，规避 PowerShell `>` 重定向 UTF-16 事故。
- **templates-extra/dcf_cm.py**：新增输入校验（每股 0.5~500 元硬门槛 + 可选 `price` 的价/现值比 0.2~5 WARN），拦截 shares_mm 单位 10x 错误。
- **verification.py**：股本优先取 `data/公司概况.csv` 总股本，与净资产/BPS 推算偏差 >2% 告警。

### 验证

- `pytest tests/ -q`：920 passed, 3 skipped。
- `template_regression.py`：✅ 通过（FAIL=0 WARN=0）；`--selfcheck` 负向自检 ✅ 通过。
- 功能验证：图13 含 None、图16 过密刻度、港股同行解析、SOTP 多估值锚触发、穿透 JSON UTF-8、F7 术语不误报、DCF 单位校验，全部通过。


## [1.0.0] - 2026-08-23 — 三技能合并发布

### 合并

- 将三个原技能合并为一个自包含技能仓库：
  - **company-research**（自动化证券调研流水线：解析/拉数/审计/交付）
  - **securities-analysis**（格雷厄姆/胡克证券分析方法论：八步分析、四种估值、报告标准）
  - **guigui-valuation-report**（龟龟投资框架 v2.1-beta：穿透回报率估值、商业质量分析、独立估值、选股器）
- 新增合并后的唯一入口 `SKILL.md`，不再需要同时加载三个技能。
- 原三份 SKILL.md 存档于 `docs/original-skills/`（历史快照，不再维护）。
- 新增 `README.md`（GitHub 展示文档）、`LICENSE`（MIT）、`CHANGELOG.md`。
- 修复文档与脚本中指向 `~/.codex/skills/<技能名>/...` 的跨技能绝对路径，改为本仓库内相对路径。
- `scripts/research_pipeline.py`：`_guigui_scripts_dir()` 优先使用本仓库 `scripts/`（合并后 `calc_penetration_return.py` / `build_penetration_input.py` 同目录），保留外部安装目录探测作为向后兼容。

### 目录合并说明

- `references/`：三技能 15 份参考文件合并（无命名冲突）。
- `scripts/`：company-research 流水线脚本 + guigui 采集/估值/选股器脚本合并；`templates-extra/`、`tushare_modules/` 子目录保留。
- `prompts/`、`strategies/`、`shared/`、`tests/`、`notebooks/`、`.claude/commands/` 来自 guigui-valuation-report。

### 行为不变

- 分析口径、门控（G1-G21）、图表规范（图 01-18）、穿透回报率公式与决策阈值均与原三技能一致。
- 测试套件完整保留（Mock 数据，无需 Token）。

---

历史变更记录：龟龟投资框架 v2 变更见 `CHANGELOG_V2.md`。
