"""Cross-industry & formal terminology regression tests for Look-Through Return v3.

Compatible with both ``python -m unittest`` and ``pytest``.
"""

from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

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
        self.assertGreater(r_bank["eta"], 0.15)
        self.assertLessEqual(r_bank["eta"], 0.25)
        self.assertTrue(r_bank["pb_discount_applied"])
        self.assertEqual(r_bank["retain_denominator"], 1180000.0)
        self.assertGreater(r_bank["r_lt"], r_bank["r_dist"])
        self.assertLess(r_bank["r_retain"], 0.02)

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
        self.assertLess(r_cib["eta"], 0.02)
        self.assertLess(r_cib["r_retain"], 0.001)

        broker_peak = _base_cfg(
            company="国泰海通",
            depreciation_D=0.0,
            capex_ratio_G=0.0,
            net_profit_C=28000.0,  # Bull-market peak vs 5Y avg 15000
            aa_2y=21000.0,
            aa_all=15000.0,
            payout_M=0.32,
            book_equity=330000.0,
            market_cap=290000.0,
            cash_balance=None,
            interest_bearing_debt=None,
        )
        self.assertEqual(infer_industry_archetype(broker_peak), "non_bank_fin")
        r_brk = compute(broker_peak, v3=True)["look_through_v3"]
        # Normalized base must damp 28000 down to 1.25 * 15000 = 18750 (ROE_norm=5.68% < Ke=9.5% -> eta=0)
        self.assertAlmostEqual(r_brk["np_base"], 18750.0, places=2)
        self.assertEqual(r_brk["eta"], 0.0)
        self.assertEqual(r_brk["r_retain"], 0.0)

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
