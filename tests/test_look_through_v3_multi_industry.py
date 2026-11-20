"""Cross-industry & formal terminology regression tests for Look-Through Return v3.

Compatible with both ``python -m unittest`` and ``pytest``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from calc_penetration_return import compute, infer_industry_archetype, render  # noqa: E402
from report_template_qc import check_report  # noqa: E402


def _base_cfg(**overrides) -> dict:
    cfg = {
        "company": "测试制造",
        "code": "600999",
        "date": "2026-11-20",
        "price": 20.0,
        "market_cap": 2000.0,
        "shares": 100.0,
        "net_profit_C": 200.0,
        "depreciation_D": 50.0,
        "capex_ratio_G": 1.0,
        "profit_discount_k": 0.8,
        "payout_M": 0.50,
        "aa_2y": 150.0,
        "aa_all": 140.0,
        "rf": 0.017,
        "ii_floor": 0.035,
        "rf_margin": 0.02,
        "cycle_adjust_pct": 0.0,
        "base_revenue": 1000.0,
        "book_equity": 1000.0,
        "cash_balance": 200.0,
        "interest_bearing_debt": 200.0,
    }
    cfg.update(overrides)
    return cfg


def _sample_report_text(*, formal: bool = True) -> str:
    if formal:
        return """# 测试科技（600999.SH）分析报告

> 分析日期：2026-11-20 ｜ 当前价：20.00元 ｜ 总市值：20亿元 ｜ 最新财报：2025-12-31

### 报告元信息

| 项目 | 内容 |
|:---|:---|
| 当前价 | 20.00元 |
| 总市值 | 20亿元 |
| 最新财报 | 2025-12-31 |
| Rf | 1.70% |
| 数据审计状态 | PASS |

## 1. 投资摘要
**最终结论**：市场轨推荐；穿透回报率轨推荐。12个月目标价25元，最大优势是高ROIC，最大风险是需求波动。
**本节结论**：具备安全边际。
> 数据依据：2025年报；截至2026-11-20。

## 2. 宏观与行业分析
宏观利率稳定，行业生命周期处于成长期，需求稳健，供给有序，政策支持。
**本节结论**：行业景气度良好。
> 数据依据：行业统计；截至2026-11-20。

## 3. 公司分析
商业模式清晰，分部稳定，护城河显著，管理层治理规范。
**本节结论**：竞争优势稳固。
> 数据依据：年报；截至2026-11-20。

## 4. 财务分析
### §4.1 盈利与资产负债表
盈利与资产负债表稳健。
**小节结论**：盈利良好。
> 数据依据：三表；截至2026-11-20。

### §4.2 现金流与盈利质量
现金流与盈利质量匹配。
**小节结论**：现金充足。
> 数据依据：现金流量表；截至2026-11-20。

### §4.3 本期财报体检
本期财报体检.json 为唯一数字来源：4.3.1 结论 4.3.2 现金 4.3.3 原因 4.3.4 利润 4.3.5 存货 4.3.6 非主营 4.3.7 解释 4.3.8 信号 4.3.9 预测影响。
**小节结论**：体检正常。
> 数据依据：reports/本期财报体检.json；截至2026-11-20。

### §4.4 同行业比较
同行业比较显示估值处于合理区间。
**小节结论**：同业占优。
> 数据依据：同行CSV；截至2026-11-20。

**本节结论**：财务质量优秀。
> 数据依据：三表；截至2026-11-20。

## 5. 盈利预测
关键假设合理，悲观、基准、乐观三情景概率明确，敏感性与跟踪指标清晰。
**本节结论**：基准预测可信。
> 数据依据：预测模型；截至2026-11-20。

## 6. 估值分析
SOTP不适用。采用穿透回报率法：R_eff=6.80%，R_req=3.70%，MoS=+3.10pct，穿透目标买入价36.76元。
**本节结论**：估值具备明显折价。
> 数据依据：穿透回报率_输出.json；截至2026-11-20。

## 7. 投资建议与目标价
市场/券商轨与穿透回报率轨均建议配置，概率加权目标价25元，建议仓位20%，下行保护价格10.88元。
**本节结论**：建议按仓位建仓。
> 数据依据：估值汇总；截至2026-11-20。

## 8. 催化剂与跟踪
催化剂与跟踪验证台账明确，验证触发条件完备。
**本节结论**：按季跟踪验证。
> 数据依据：跟踪台账；截至2026-11-20。

## 9. 风险与反证条件
风险矩阵包含概率及方法、尾部压力情景、反证与待验证事项。
**本节结论**：风险可控。
> 数据依据：风险审计；截至2026-11-20。

## 10. 附录
数据来源、方法、图表清单、复验与免责声明完整。
**本节结论**：附录完备。
> 数据依据：全流程归档；截至2026-11-20。
"""
    return (
        _sample_report_text(formal=True)
        .replace("穿透回报率轨", "龟龟轨")
        .replace("穿透回报率法", "龟龟穿透回报率")
        .replace("R_req", "II")
        .replace("MoS", "KK")
        .replace("下行保护价格", "门槛价格")
    )


class TestLookThroughV3MultiIndustry(unittest.TestCase):
    def test_legacy_v2_compatibility_and_formal_metrics_populated(self):
        cfg = _base_cfg()
        res = compute(cfg)
        self.assertEqual(res["model_mode"], "legacy_v2")
        # Legacy formula: 200 * 0.8 * 0.5 / 2000 = 0.04
        self.assertAlmostEqual(res["R_star"], 0.04, places=6)
        self.assertIn("formal_metrics", res)
        self.assertIn("look_through_v3", res)
        self.assertGreater(res["formal_metrics"]["look_through_return_R_LT"], res["R_star"])

    def test_expansion_capex_not_penalized_when_maint_cash_covers_earnings(self):
        # Expansion Capex = 1.6x D&A crushes aa_2y to 20M (so v2 GG = 20*0.5/2000 = 0.5%),
        # while actual OCF is healthy (220M) and maintenance Capex = 0.9*50 = 45M -> OE_cash = 175M > 200*0.8=160M.
        cfg = _base_cfg(
            industry_archetype="manufacturing",
            capex_ratio_G=1.6,
            aa_2y=140.0,  # 220 - 50*1.6 = 140
            ocf_latest=220.0,
            net_profit_C=200.0,
            book_equity=1000.0,  # ROIC = 20%
        )
        res_v3 = compute(cfg, v3=True)
        lt = res_v3["look_through_v3"]
        self.assertTrue(lt["cash_quality_passed"])
        self.assertAlmostEqual(lt["maint_capex_factor_gamma"], 0.90, places=4)
        self.assertAlmostEqual(lt["maint_cash_owner_earnings"], 175.0, places=4)
        self.assertGreater(lt["eta"], 0.70)
        self.assertGreater(res_v3["r_eff"], res_v3["legacy_v2"]["r_eff"])

    def test_internet_buyback_and_roic_recognized_while_weak_cash_traps_forced_zero(self):
        # Healthy internet giant with cancellation buyback
        tx = _base_cfg(
            company="腾讯示例",
            industry_archetype="internet_tech",
            market_cap=2660000.0,
            net_profit_C=224842.0,
            depreciation_D=66028.0,
            capex_ratio_G=1.41,
            payout_M=39907.0 / 224842.0,
            buyback_amount=78181.0,
            ocf_latest=280787.0,
            fe_interest_expense=12937.0,
            aa_2y=176325.0,
            roic=0.1525,
            ii_floor=0.05,
            rf_margin=0.03,
            rf=0.02,
        )
        r_tx = compute(tx, v3=True)["look_through_v3"]
        self.assertAlmostEqual(r_tx["total_distribution_ratio_p"], 0.5252, places=3)
        self.assertTrue(r_tx["cash_quality_passed"])
        self.assertGreater(r_tx["r_eff"], 0.05)

        # Weak cash trap: high accounting NP (200) & high ROIC, but real OCF only 60M -> Cov_cash < 0.85
        trap = _base_cfg(
            industry_archetype="internet_tech",
            net_profit_C=200.0,
            depreciation_D=40.0,
            capex_ratio_G=1.0,
            ocf_latest=60.0,
            aa_2y=20.0,
            payout_M=0.80,
            book_equity=500.0,
        )
        r_trap = compute(trap, v3=True)["look_through_v3"]
        self.assertFalse(r_trap["cash_quality_passed"])
        self.assertEqual(r_trap["eta"], 0.0)
        self.assertIn("降级", r_trap["primary"])

        # Low ROIC value-destruction hoarding cash: passed cash quality, but ROIC = 4% < R_req + 2% (5.7%) -> eta = 0
        hoarder = _base_cfg(
            industry_archetype="manufacturing",
            net_profit_C=100.0,
            book_equity=2500.0,  # ROIC = 4.0%
            ocf_latest=150.0,
            aa_2y=100.0,
            payout_M=0.20,
        )
        r_hoard = compute(hoarder, v3=True)["look_through_v3"]
        self.assertTrue(r_hoard["cash_quality_passed"])
        self.assertEqual(r_hoard["eta"], 0.0)
        self.assertAlmostEqual(r_hoard["r_retain"], 0.0, places=6)

    def test_bank_and_non_bank_cycle_smoothing_archetypes(self):
        bank = _base_cfg(
            company="招商银行",
            depreciation_D=0.0,
            capex_ratio_G=0.0,
            net_profit_C=150000.0,
            aa_2y=149000.0,
            aa_all=140000.0,
            payout_M=0.34,
            book_equity=1180000.0,
            market_cap=1080000.0,
            cash_balance=None,
            interest_bearing_debt=None,
        )
        self.assertEqual(infer_industry_archetype(bank), "bank")
        r_bank = compute(bank, v3=True)["look_through_v3"]
        self.assertTrue(r_bank["cash_quality_passed"])
        self.assertEqual(r_bank["growth_realization_rho"], 1.0)
        self.assertGreater(r_bank["eta"], 0.15)
        self.assertLessEqual(r_bank["eta"], 0.25)
        self.assertTrue(r_bank["pb_discount_applied"])
        self.assertEqual(r_bank["retain_denominator"], 1180000.0)
        self.assertGreater(r_bank["r_lt"], r_bank["r_dist"])
        self.assertLess(r_bank["r_retain"], 0.02)

        # Real 5-year series CMB: NIM compression (2Y CAGR ~1.21% vs theoretical ~8.40%) pulls rho_g ~0.36
        bank_real_series = _base_cfg(
            company="招商银行实证",
            industry_archetype="bank",
            depreciation_D=0.0,
            capex_ratio_G=0.0,
            price=43.12,
            market_cap=1087479.74,
            shares=25219.845601,
            net_profit_C=150181.0,
            aa_2y=149286.0,
            aa_all=140621.6,
            payout_M=0.3385,
            rf=0.016055,
            book_equity=1181997.0,
            net_profit_series=[150181.0, 148391.0, 146602.0, 138012.0, 119922.0],
            cash_balance=None,
            interest_bearing_debt=None,
        )
        r_bank_real = compute(bank_real_series, v3=True)["look_through_v3"]
        self.assertGreater(r_bank_real["growth_realization_rho"], 0.34)
        self.assertLess(r_bank_real["growth_realization_rho"], 0.39)
        self.assertGreater(r_bank_real["eta"], 0.06)
        self.assertLess(r_bank_real["eta"], 0.09)
        self.assertGreaterEqual(r_bank_real["target_buy"], 49.5)
        self.assertLessEqual(r_bank_real["target_buy"], 51.5)

        broken_pb_bank = _base_cfg(
            company="兴业银行示例",
            industry_archetype="bank",
            depreciation_D=0.0,
            capex_ratio_G=0.0,
            net_profit_C=75000.0,
            aa_2y=75000.0,
            aa_all=75000.0,
            payout_M=0.30,
            roe=0.0915,
            book_equity=820000.0,   # PB = 0.47x < 1.0
            market_cap=385400.0,
            cash_balance=None,
            interest_bearing_debt=None,
        )
        r_cib = compute(broken_pb_bank, v3=True)["look_through_v3"]
        self.assertTrue(r_cib["pb_discount_applied"])
        self.assertEqual(r_cib["retain_denominator"], 820000.0)
        self.assertLess(r_cib["eta"], 0.10)
        self.assertLess(r_cib["r_retain"], 0.005)

        # Negative 5-year profit growth -> rho_g == 0.0 and eta == 0.0 (pure dividend fallback)
        neg_growth_bank = _base_cfg(
            company="兴业负增长示例",
            industry_archetype="bank",
            depreciation_D=0.0,
            capex_ratio_G=0.0,
            net_profit_C=77469.0,
            aa_2y=77337.0,
            aa_all=81169.4,
            payout_M=0.30,
            roe=0.0945,
            book_equity=820000.0,
            market_cap=385400.0,
            surplus_series=[77469.0, 77205.0, 77116.0, 91377.0, 82680.0],
            cash_balance=None,
            interest_bearing_debt=None,
        )
        r_cib_neg = compute(neg_growth_bank, v3=True)["look_through_v3"]
        self.assertEqual(r_cib_neg["growth_realization_rho"], 0.0)
        self.assertEqual(r_cib_neg["eta"], 0.0)
        self.assertAlmostEqual(r_cib_neg["r_retain"], 0.0, places=6)

        broker_peak = _base_cfg(
            company="纯周期高点券商",
            industry_archetype="non_bank_fin",
            depreciation_D=0.0,
            capex_ratio_G=0.0,
            net_profit_C=28000.0,  # Pure cyclical peak vs 5Y avg 15000 (flat equity)
            aa_2y=21000.0,
            aa_all=15000.0,
            payout_M=0.32,
            book_equity=330000.0,
            book_equity_series=[330000.0, 315000.0, 305000.0, 298000.0, 290000.0],
            net_profit_series=[28000.0, 14000.0, 10000.0, 11000.0, 12000.0],
            market_cap=290000.0,
            cash_balance=None,
            interest_bearing_debt=None,
        )
        r_brk = compute(broker_peak, v3=True)["look_through_v3"]
        self.assertFalse(r_brk["ma_scale_adjusted"])
        # Normalized base must damp 28000 down to 1.25 * 15000 = 18750 (ROE_norm=5.68% < Ke=6.50% -> eta=0)
        self.assertAlmostEqual(r_brk["np_base"], 18750.0, places=2)
        self.assertEqual(r_brk["eta"], 0.0)
        self.assertEqual(r_brk["r_retain"], 0.0)

        # Scenario B: M&A share-swap merger (Guotai Haitong style) with balance sheet series (Path A)
        broker_ma_bs = _base_cfg(
            company="国泰海通",
            depreciation_D=0.0,
            capex_ratio_G=0.0,
            price=16.54,
            market_cap=290791.0,
            shares=17581.0746,
            net_profit_C=27809.2,
            aa_2y=20416.65,
            aa_all=15345.94,
            payout_M=0.316,
            rf=0.0175,
            book_equity=330416.8,
            book_equity_series=[320441.5, 155828.4, 147050.6, 141671.4, 136052.0],
            shares_series=[17628.9, 8903.7, 8903.7, 8904.5, 8906.7],
            net_profit_series=[27809.2, 13024.1, 9374.1, 11508.8, 15013.5],
            revenue_series=[63107.4, 33675.5, 36141.3, 35471.3, 42817.1],
            cash_balance=None,
            interest_bearing_debt=None,
        )
        self.assertEqual(infer_industry_archetype(broker_ma_bs), "non_bank_fin")
        r_ma = compute(broker_ma_bs, v3=True)["look_through_v3"]
        self.assertTrue(r_ma["ma_scale_adjusted"])
        self.assertGreater(r_ma["np_base"], 30000.0)
        self.assertGreater(r_ma["aa_all_pro_forma"], 25000.0)
        # Combined full-year pro-forma ROE ~9.66% > Ke_fin 6.50% -> rho_g=1.0, eta > 0.10, buy price in [14.5, 15.5] (> 14.38 pre-924 low)
        self.assertEqual(r_ma["growth_realization_rho"], 1.0)
        self.assertGreater(r_ma["eta"], 0.10)
        self.assertGreaterEqual(r_ma["target_buy"], 14.5)
        self.assertLessEqual(r_ma["target_buy"], 15.5)

        # Scenario C: M&A fallback via revenue step + goodwill/scale ROE (Path B without book_equity_series)
        broker_ma_rev = _base_cfg(
            company="国泰海通",
            depreciation_D=0.0,
            capex_ratio_G=0.0,
            price=16.54,
            market_cap=290791.0,
            shares=17581.0746,
            net_profit_C=27809.2,
            aa_2y=20416.65,
            aa_all=15345.94,
            payout_M=0.316,
            rf=0.0175,
            book_equity=330416.8,
            goodwill=4052.4,
            revenue_series=[63107.4, 33675.5, 36141.3, 35471.3, 42817.1],
            cash_balance=None,
            interest_bearing_debt=None,
        )
        r_ma_rev = compute(broker_ma_rev, v3=True)["look_through_v3"]
        self.assertTrue(r_ma_rev["ma_scale_adjusted"])
        self.assertGreater(r_ma_rev["np_base"], 30000.0)
        self.assertTrue(r_ma_rev["cash_quality_passed"])
        self.assertEqual(r_ma_rev["growth_realization_rho"], 1.0)
        self.assertGreater(r_ma_rev["eta"], 0.10)
        self.assertGreaterEqual(r_ma_rev["target_buy"], 14.5)
        self.assertLessEqual(r_ma_rev["target_buy"], 15.5)

    def test_build_penetration_input_avoids_ma_share_inflation_on_historical_payout(self):
        with tempfile.TemporaryDirectory() as tmp:
            tpath = Path(tmp)
            data = tpath / "data"
            out = tpath / "input"
            data.mkdir()
            dates = [f"{y}-12-31" for y in range(2021, 2026)]
            # Share count & book equity double in 2025 due to M&A, while per-share DPS stays stable (~30% payout)
            pd.DataFrame({
                "REPORT_DATE": dates,
                "OPERATE_INCOME": [350e8, 350e8, 360e8, 340e8, 650e8],
                "PARENT_NETPROFIT": [110e8, 110e8, 100e8, 130e8, 270e8],
                "BASIC_EPS": [1.10, 1.10, 1.00, 1.30, 1.50],
                "TOTAL_PROFIT": [130e8, 130e8, 120e8, 150e8, 320e8],
                "FE_INTEREST_EXPENSE": [0.0] * 5,
            }).to_csv(data / "利润表_按报告期.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame({
                "REPORT_DATE": dates,
                "NETCASH_OPERATE": [120e8, 120e8, 120e8, 150e8, 300e8],
                "CONSTRUCT_LONG_ASSET": [20e8] * 5,
                "DEPR_AMORT": [30e8] * 5,
            }).to_csv(data / "现金流量表_按报告期.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame({
                "REPORT_DATE": dates,
                "SHARE_CAPITAL": [100e8, 100e8, 100e8, 100e8, 200e8],
                "MONETARYFUNDS": [500e8] * 5,
                "SHORT_LOAN": [100e8] * 5,
                "LONG_LOAN": [100e8] * 5,
                "TOTAL_CURRENT_ASSETS": [800e8] * 5,
                "TOTAL_CURRENT_LIAB": [400e8] * 5,
                "TOTAL_PARENT_EQUITY": [1500e8, 1520e8, 1550e8, 1600e8, 3250e8],
                "OTHER_EQUITY_TOOL": [100e8] * 5,
            }).to_csv(data / "资产负债表_按报告期.csv", index=False, encoding="utf-8-sig")
            # Annual DPS: 2021..2023 = 0.30/sh, 2024 = 0.40/sh (on 10B sh -> 30.8%), 2025 = 0.45/sh (on 20B sh -> 33.3%)
            pd.DataFrame({
                "报告期": dates,
                "现金分红-现金分红比例": [3.0, 3.0, 3.0, 4.0, 4.5],
            }).to_csv(data / "分红送配记录.csv", index=False, encoding="utf-8-sig")
            pd.DataFrame({
                "日期": ["2026-10-19", "2026-10-18"],
                "收盘": [16.5, 16.4],
            }).to_csv(data / "日线股价.csv", index=False, encoding="utf-8-sig")

            out.mkdir(parents=True, exist_ok=True)
            res = subprocess.run(
                [sys.executable, str(SCRIPTS / "build_penetration_input.py"),
                 "--data", str(data), "--out", str(out), "--company", "并购测试证券", "--code", "609999"],
                capture_output=True, text=True, encoding="utf-8",
            )
            self.assertEqual(res.returncode, 0, msg=res.stderr)
            cfg = json.loads((out / "穿透回报率_输入.json").read_text(encoding="utf-8"))
            self.assertIn("book_equity_series", cfg)
            self.assertIn("shares_series", cfg)
            # Without historical-share matching, 2023/2024 payouts would blow up to 60%/61.5%; with fix, mean stays ~0.31
            self.assertLess(cfg["payout_M_mean"], 0.40)
            self.assertAlmostEqual(cfg["payout_M"], 0.30, places=2)

    def test_formal_render_no_colloquial_or_million_tokens(self):
        cfg = _base_cfg()
        res = compute(cfg, v3=True)
        snap = copy.deepcopy(res)
        txt = render(res)
        self.assertEqual(res, snap)
        self.assertNotIn("龟龟", txt)
        self.assertNotIn("百万", txt)
        self.assertIn("穿透回报率法（Look-Through Return Method v3）", txt)
        self.assertIn("OE_cash", txt)

    def test_report_template_qc_supports_both_formal_and_legacy_terminology(self):
        f_new, _ = check_report(_sample_report_text(formal=True))
        self.assertEqual(f_new, [], f"Formal report failed template QC: {f_new}")
        f_old, _ = check_report(_sample_report_text(formal=False))
        self.assertEqual(f_old, [], f"Legacy report failed template QC: {f_old}")


if __name__ == "__main__":
    unittest.main()
