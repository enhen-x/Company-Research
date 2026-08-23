Run a Valuation Analysis (估值分析) on stock: $ARGUMENTS

## Input Validation
- Stock code must be a valid A-share (e.g., 600887, 000858.SZ), HK stock (00700.HK), or US stock (AAPL)
- If $ARGUMENTS is empty or invalid, ask the user for a valid stock code before proceeding
- If only digits are given, the code will be normalized by scripts/config.py

## Prerequisite Check
Before executing, verify these files exist in output/{code}_{company}/:
- **qualitative_report.md** — required. If missing, inform user to run `/business-analysis {stock_code}` first, then stop.
- **data_pack_market.md** — required. If missing, same as above.

## Execution Instructions

Read strategies/valuation/coordinator.md for the full pipeline specification, then execute each step:

### Step 1: Python Valuation Computation
```bash
python3 scripts/valuation_engine.py --code $ARGUMENTS --output-dir output/{code}_{company}/
```
- Collects fresh data via Tushare, computes classification + WACC + all valuation methods
- Outputs: output/{code}_{company}/valuation_computed.md
- Contains: company type, WACC, each method's result + 5×5 sensitivity tables, cross-validation

### Step 2: LLM Qualitative Adjustment + Report
- Read strategies/valuation/phase2_valuation.md for qualitative adjustment instructions
- Read strategies/valuation/references/valuation_methods.md for methodology reference
- Read strategies/valuation/references/report_template.md for output format
- Read output/{code}_{company}/qualitative_report.md for qualitative insights (D1-D6)
- Read output/{code}_{company}/valuation_computed.md for all computed numbers
- Apply qualitative adjustments: D1 revenue quality → growth rate, D2 moat → terminal growth, D3 cycle → scenario weights, D4 management → governance discount
- Select adjusted scenarios from sensitivity tables (no arithmetic needed)
- Output: output/{code}_{company}/{company}_{code}_估值报告.md

## Error Recovery
- Missing qualitative_report.md → stop and prompt user to run /business-analysis first
- valuation_engine.py fails → check TUSHARE_TOKEN, retry
- Classification ambiguous → Python defaults to 混合型
- A valuation method fails → Python skips it, weights redistributed
- qualitative_report.md has no structured parameters → skip qualitative adjustments, use Python defaults
- Always produce a final report even with partial data

## Output
Final report: output/{code}_{company}/{company}_{code}_估值报告.md

Usage: /valuation 600887 or /valuation 00700.HK or /valuation AAPL
