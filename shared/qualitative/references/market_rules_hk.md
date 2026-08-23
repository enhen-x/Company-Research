# 港股市场特别规则

> **条件加载**：仅当股票代码以 `.HK` 结尾时，由协调器指示 Agent A/B 加载本文件。A股分析不加载。

---

## 数据采集补充（Phase 1B）

港股 Tushare 数据覆盖有限，以下数据需 Agent 通过 WebSearch **完整采集**：

| 数据项 | 搜索关键词 | 说明 |
|-------|-----------|------|
| 审计意见 | "{公司名} annual report auditor opinion" / "{公司名} 核数师报告" | 审计师名称、意见类型、5年内是否更换 |
| §9 分部收入 | "{公司名} segment revenue breakdown" / "{公司名} 分部收入" | 各业务分部收入、利润、毛利率 |
| §15 股票回购 | "{公司名} share buyback repurchase" / "{公司名} 股份回购" | 回购金额、股数、用途 |
| §16 股权质押 | — | **不适用**，港股无A股式质押制度 |

### 财务数据验证

当 data_pack_market.md §3-§5 仍有 "—" 标记时，通过 WebSearch 补充：
- 折旧及摊销："{公司名} annual report depreciation amortization"
- 资本开支："{公司名} capital expenditure capex"
- 经营溢利："{公司名} operating profit"
- 应收帐款/存货："{公司名} balance sheet receivables inventory"

在 §13 Warnings 中标注 `[数据补充|中]`。

---

## HKFRS 会计准则差异（Phase 3 分析）

Agent B 定量分析中额外核查：

| 准则差异 | 核查内容 | 影响 |
|---------|---------|------|
| HKFRS 9 预期信用损失 | ECL 计提是否充分 vs 同行 | 影响 AR 质量判断 |
| HKFRS 16 租赁 | 表外租赁负债规模 | 影响真实负债水平 |
| VIE/SPV 合并范围 | 是否有表外实体 | 影响合并报表完整性 |

Agent A 定性分析中额外关注：
- 港股信息披露频率低于A股（半年报+年报，无季报义务）
- 关联交易披露标准不同（港交所 Chapter 14A）
- 独立非执行董事机制 vs A股独立董事

---

## 持股渠道与税率

港股持股渠道影响股息税率（详见 shared_tables.md）：
- 港股通：H股 20%，红筹/开曼 20%
- 直接持有：H股 28%，红筹/开曼 20%

---

*龟龟投资策略 v2.0 | 港股市场规则参考文件*
