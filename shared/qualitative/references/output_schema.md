# 定性分析结构化参数输出 Schema（v1.2）

> 定义定性分析模块输出的标准化参数。下游投资策略（龟龟、烟蒂等）通过读取该参数表获取定性结论，
> 各策略可在自己的 interface 文件中定义额外的映射规则。
>
> v1.1 更新：D2 新增行业地图、量化验证、Greenwald 三维框架、竞争对手对比、护城河监控锚点。
>
> v1.2 更新：新增"交付硬门槛"表（杠杆7）——章节最小字数 + 必备章节 + 参数完整性，交付前由
> `report_consistency.py --gates` 确定性校验。参数定义本身不变（向后兼容）。

---

## 参数定义

### D1：商业模式与资本特征

| 参数 | 类型 | 值域 | 说明 |
|------|------|------|------|
| business_model_clarity | enum | 清晰且已验证 / 清晰但未充分验证 / 模糊 | 商业模式是否可用一句话概括并经历周期验证 |
| capital_intensity | enum | capital-light / capital-hungry | 维持盈利规模的持续性资本消耗 |
| collection_mode | enum | 先款后货 / 订阅预收 / 先货后款 / 垫资回收 | 典型交易的现金流时间线 |
| cash_impact | enum | 正贡献 / 中性 / 负担 | 收款模式对现金状况的影响 |

### D2：竞争优势与护城河

**D2.1 行业地图**

| 参数 | 类型 | 值域 | 说明 |
|------|------|------|------|
| market_structure | enum | 垄断 / 寡头 / 垄断竞争 / 充分竞争 | 行业竞争格局 |
| market_cr4 | float / null | 百分比 | 前4名市场份额合计（数据可得时填写） |
| entry_barrier | enum | 高 / 中 / 低 | 行业进入壁垒综合评估 |

**D2.2 量化验证**

| 参数 | 类型 | 值域 | 说明 |
|------|------|------|------|
| roe_5y_avg | float | 百分比 | 5年平均ROE |
| moat_existence | enum | 存在 / 可能存在 / 不存在 | 基于量化数据的竞争优势存在性判断 |
| moat_evidence_strength | enum | 强证据 / 中等证据 / 弱证据 | 量化证据的强度 |

**D2.3 护城河来源（双框架）**

| 参数 | 类型 | 值域 | 说明 |
|------|------|------|------|
| moat_type | string | "[非技术] xxx + [技术] xxx" | 框架A：双层护城河描述（技术层可为"不适用"） |
| moat_framework_primary | enum | A / B | 主分析框架：A=双层(科技)，B=Greenwald(传统) |
| supply_side_rating | enum | 强 / 较强 / 中等 / 弱 / 不适用 | 框架B：供给侧优势（成本、资源、垂直整合） |
| demand_side_rating | enum | 强 / 较强 / 中等 / 弱 / 不适用 | 框架B：需求侧优势（品牌、转换成本、网络效应） |
| scale_economy_rating | enum | 强 / 较强 / 中等 / 弱 / 不适用 | 框架B：规模经济效益 |
| moat_flywheel | bool | true / false | 是否形成复合护城河飞轮 |

**D2.4 虚假优势辨析**

| 参数 | 类型 | 值域 | 说明 |
|------|------|------|------|
| false_advantages | list | [string] | 被排除的"虚假优势"列表及理由 |

**D2.5 竞争对手对比**

| 参数 | 类型 | 值域 | 说明 |
|------|------|------|------|
| competitors | list | [{name, ticker}] | 主要竞争对手列表 |
| competitor_ranking | string | 自由文本 | 目标公司 vs 对手的综合排名 |
| advantage_gap_sustainability | enum | 高 / 中 / 低 | 优势差距可持续性 |

**D2.6 可持续性与综合**

| 参数 | 类型 | 值域 | 说明 |
|------|------|------|------|
| pricing_power | enum | 强 / 中 / 弱 | 主动提价能力 |
| human_capital_dep | enum | 系统型 / 人才型 | 竞争优势是否已沉淀为系统性能力 |
| moat_sustainability | enum | 高可持续 / 中等可持续 / 低可持续 | 护城河可持续性判断 |
| moat_rating | enum | 强 / 较强 / 中 / 弱 | 护城河综合评价 |
| moat_monitor_kpis | list | [{kpi, current, threshold}] | 未来3-5年护城河健康度跟踪指标 |

### D3：外部环境

| 参数 | 类型 | 值域 | 说明 |
|------|------|------|------|
| cyclicality | enum | 强周期 / 弱周期 / 非周期 | 收入和盈利波动幅度 |
| cycle_position | enum | 底部 / 中段 / 顶部 / 不适用 | 当前周期位置（仅强周期适用） |
| regulatory_risk | enum | 低 / 中 / 高 | 监管与政策风险 |
| industry_keywords | list | [string] | 行业监控关键词 |

### D4：管理层与治理

| 参数 | 类型 | 值域 | 说明 |
|------|------|------|------|
| governance_flags | list | [{flag_name: status}] | 治理风险逐项标志 |
| management_rating | enum | 优秀 / 合格 / 损害价值 / 观察期 | 管理层综合评价 |
| capital_allocation_record | string | 自由文本 | 资本配置历史简要评价 |
| related_party_risk | enum | 低 / 中 / 高 | 关联交易风险 |

### D5：MD&A 解读

| 参数 | 类型 | 值域 | 说明 |
|------|------|------|------|
| mda_credibility | enum | 高 / 中 / 低 | MD&A 可信度 |
| mda_impact | enum | 正面 / 中性 / 负面 | MD&A 对投资判断的影响 |
| mda_forward_guidance | enum | 有量化 / 仅方向性 / 无 | 前瞻性指引质量 |
| distribution_signal | string | 自由文本 | 从 MD&A 提取的分红/回购意向摘要 |

### D6：控股结构（条件触发）

| 参数 | 类型 | 值域 | 说明 |
|------|------|------|------|
| holding_structure | bool | true / false | 是否适用控股结构分析 |
| sotp_value_mm | float / null | 百万元 | SOTP 估值（不适用时为 null） |
| sotp_discount_pct | float / null | 百分比 | 控股折价率（不适用时为 null） |

---

## 交付硬门槛（杠杆7 · v1.2 新增）

> 报告写盘前必须满足以下**确定性**门槛；由 `scripts/report_consistency.py --gates` 自动校验，
> 不达标即 exit 1，coordinator 须补足后才可交付。字数按**中文字符（CJK）**计正文（不含表格/代码）。

| 门槛项 | 要求 | 校验方式 |
|--------|------|---------|
| 维度一 商业模式 | 正文 **≥600 字** | CJK 字数统计 |
| 维度二 护城河 | 正文 **≥800 字**，且 `moat_rating` / `supply_side_rating` / `demand_side_rating` / `scale_economy_rating` **4 项评级必填** | 字数 + 参数非空 |
| 维度六 控股结构 | **若触发**则正文 **≥300 字**（未触发/不适用可豁免） | 字数（不适用时跳过） |
| 数字溯源汇总 | 报告必须含 `## 数字溯源汇总` 章节 | 章节存在性 |
| 结构化参数 | 报告必须含 `## 结构化参数`，且参数表**无留空**（不可得填 `null` 并注明） | 章节存在性 + 无空格 |

## 使用说明

### 独立运行模式
参数表附在完整分析报告末尾，供阅读者快速定位结论。

### 被策略调用模式
下游策略通过读取参数表获取定性结论，不需要解析报告正文。各策略在自己的 interface 文件中定义映射规则，例如：

- **龟龟策略**：`strategies/turtle/references/factor_interface.md` 定义 output_schema → 龟龟因子参数的映射
- **烟蒂策略**：`strategies/cigarbutt/references/cigarbutt_interface.md` 定义 output_schema → 烟蒂支柱评分的映射

### 版本兼容
- Schema 版本号：v1.2
- v1.0 → v1.1 变更：D2 新增 market_cr4, entry_barrier, roe_5y_avg, moat_existence, moat_evidence_strength, moat_framework_primary, supply_side_rating, demand_side_rating, scale_economy_rating, false_advantages, competitor_ranking, advantage_gap_sustainability, moat_sustainability, moat_monitor_kpis；moat_rating 值域扩展为 强/较强/中/弱
- v1.1 → v1.2 变更：新增"交付硬门槛"表（章节字数/必备章节/参数完整性）；**参数定义无变化**，纯增量
- 新增参数向后兼容（下游策略忽略未知参数）
- 删除/改名参数需同步更新所有策略的 interface 文件

---

*通用定性分析模块 v1.2 | 结构化参数输出 Schema*
