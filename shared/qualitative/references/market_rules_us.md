# 美股市场特别规则

> **条件加载**：仅当股票代码以 `.US` 结尾时，由协调器指示 Agent A/B 加载本文件。A股分析不加载。

---

## 数据覆盖局限

Tushare us_* 接口约 **60%** 覆盖率：

| 数据项 | 状态 | 降级方案 |
|-------|------|---------|
| §3P/§4P 母公司报表 | ❌ 不适用 | US GAAP 不区分母公司/合并 |
| §6 股息历史 | ⚠️ us_dividend 有限 | WebSearch 补充完整股息记录 |
| §9 主营业务构成 | ❌ Tushare 无 us 版 | WebSearch 获取 10-K segment 数据 |
| §12 部分财务指标 | ⚠️ q_opincome 等缺失 | 从 §3/§5 手动计算 |
| §15 股票回购 | ❌ Tushare 无 us 版 | WebSearch 获取回购计划和执行情况 |
| §16 股权质押 | ❌ 不适用 | — |
| §17 部分衍生指标 | ⚠️ 因 §12 缺失而无法计算 | Phase 3 手动计算或降级 |

在 §13 Warnings 中生成：`[数据覆盖|中] 美股数据覆盖约60%，部分分析使用降级方案`

---

## 数据采集补充（Phase 1B）

以下章节需 Agent 通过 WebSearch 补充：
- §8 行业与竞争
- §9 业务构成（10-K segment disclosure）
- §10 MD&A（Management Discussion & Analysis）

默认持股渠道：W-8BEN（中美税收协定，10% 预扣税）。

---

## US GAAP 分析注意事项

Agent B 定量分析中注意：
- 无母公司单体报表，不执行模块九（SOTP/控股折价）
- Stock-based compensation 需从现金流中识别并还原
- Goodwill impairment testing 按 ASC 350（年度测试，非季度）
- Revenue recognition 按 ASC 606

Agent A 定性分析中注意：
- SEC 10-K/10-Q 信息披露更详细
- Proxy statement (DEF 14A) 包含管理层薪酬和治理信息
- Insider trading 通过 Form 4 公开披露

---

*龟龟投资策略 v2.0 | 美股市场规则参考文件*
