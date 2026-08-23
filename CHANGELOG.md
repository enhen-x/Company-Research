# Changelog

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
