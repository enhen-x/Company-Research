# Turtle Investment Framework — Skill Definition

## Skill Info
- **Name**: turtle-analysis
- **Description**: Run a full 龟龟投资策略 (Turtle Investment Framework) fundamental analysis on Chinese A-share, HK, or US stocks
- **Entry Point**: `strategies/turtle/coordinator.md`
- **Slash Command**: `/turtle-analysis <stock_code>`

## Dependencies
- **/business-analysis (prerequisite)**: Produces `qualitative_report.md` + `data_pack_market.md` (and optional `data_pack_report.md`). PDF acquisition and qualitative analysis now live in `/business-analysis`, not in this skill.
- **Python venv**: `.venv/` with `tushare`, `pandas`, `pdfplumber` (created by `bash init.sh`; prefer `.venv/bin/python`, fall back to `python3`)
- **Tushare Pro API**: Requires `TUSHARE_TOKEN` environment variable

## Required Environment Variables
| Variable | Description | Required |
|----------|-------------|----------|
| `TUSHARE_TOKEN` | Tushare Pro API token | Yes |

## Pipeline Phases
1. **Prerequisite check**: Verify `output/{code}_{company}/qualitative_report.md` and `data_pack_market.md` exist (outputs of `/business-analysis`). If missing, tell the user to run `/business-analysis {stock_code}` first, then stop. `data_pack_report.md` is optional (Agent B degrades gracefully without PDF footnote data).
2. **Step A — market data refresh**: `scripts/tushare_collector.py --refresh-market` refreshes §1/§2/§11/§14 (price/market cap, 52-week range, weekly prices, risk-free rate). If the data pack is >7 days old, it auto-falls back to full collection.
3. **Phase 3.1 — Agent B (quantitative)**: Read `strategies/turtle/phase3_quantitative.md`. Runs Step 0 data validation + accounting anchoring, then the 11-step penetrating return rate calculation. Output: `phase3_quantitative.md`.
4. **Phase 3.2 — Agent C (valuation + report)**: Read `strategies/turtle/phase3_valuation.md`. Reads `qualitative_report.md` (from `/business-analysis`) and Agent B's output, then assembles the final report.

## Output
- `output/{code}_{company}/` — all intermediate and final files
- Final report: `{company}_{code}_分析报告.md`
