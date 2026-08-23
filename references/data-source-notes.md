# 数据源避坑清单（data-source-notes）

> 实战沉淀：水星家纺（SH.603365）分析（2026-08-12）实测校准。
> 环境：Windows 11 / Python 3.13.5 / akshare 1.18.84 / PowerShell 5.1。
> 每次分析前先跑 `scripts/probe_sources.py <代码>` 刷新实测状态——**本清单是快照，端点可用性会变**。

---

## 一、数据源可用性实测快照（2026-08-12）

| 源 | 端点 | 状态 | 用途 |
|----|------|------|------|
| 东财行情-日线 | push2his.eastmoney.com | ❌ SSL EOF | stock_zh_a_hist 底层 |
| 东财行情-实时 | push2.eastmoney.com | ❌ SSL EOF | 行情推送 |
| 东财数据中心 | datacenter-web.eastmoney.com | ✅ OK | **emweb 三表/财务指标（主力）** |
| 腾讯行情 | qt.gtimg.cn | ✅ OK | 实时行情 |
| 腾讯历史K线 | web.ifzq.gtimg.cn | ✅ OK | **stock_zh_a_hist_tx 日线（降级主力）** |
| 新浪行情 | hq.sinajs.cn | ❌ SSL EOF | 已不可用 |

**当前可用链**：财务三表/指标 → 东财 emweb；日线 → 腾讯。两条都稳。

## 二、akshare 接口存在性（1.18.84 实测）

| 接口 | 状态 | 替代/备注 |
|------|------|-----------|
| stock_zh_a_hist（东财日线） | ✅ 存在 | 但底层 push2his SSL 故障时会抛异常 |
| stock_zh_a_hist_tx（腾讯日线） | ✅ 存在 | **降级主力**，符号必须小写前缀 `sh603365` |
| stock_profit_sheet_by_report_em | ✅ 存在 | symbol 必须带市场前缀 `SH603365` |
| stock_balance_sheet_by_report_em | ✅ 存在 | 同上，无前缀报"股票代码不合法" |
| stock_cash_flow_sheet_by_report_em | ✅ 存在 | 同上 |
| stock_fhps_detail_em（分红送配） | ✅ 存在 | 降级：现金流量表"分配股利支付的现金"列 |
| **stock_financial_abstract_em** | ❌ 缺失 | 用 stock_financial_analysis_indicator_em 替代 |
| stock_financial_analysis_indicator_em | ✅ 存在 | 但底层走新浪，新浪 SSL 故障时也会挂 |
| **stock_shareholder_top10_em** | ❌ 缺失 | 用 stock_gdfx_top_10_em 替代 |
| stock_gdfx_top_10_em | ✅ 存在 | 签名 `(symbol='sh603365', date='20210630')`——symbol 用小写前缀格式；**date 是报告期，默认值较旧，使用时应传最新报告期** |

**规则**：脚本里一律先 `hasattr(ak, name)` 检查再调用，接口缺失不得报错中断，直接标注 MISS。

## 三、符号格式（最容易踩的坑）

| 目标接口 | 格式 | 示例 |
|----------|------|------|
| emweb 三表/指标（datacenter-web） | 市场前缀大写 | `SH603365`、`SZ002293` |
| 东财 F10 指标 HTTP（reportName=RPT_F10_FINANCE_MAINFINADATA） | secucode（代码.市场） | `603365.SH` |
| stock_gdfx_top_10_em（股东） | 小写前缀 | `sh603365` |
| stock_zh_a_hist_tx（腾讯） | 市场前缀小写 | `sh603365`、`sz002293` |
| 东财 stock_zh_a_hist 纯代码 | 裸代码 | `603365` |
| 新浪行情 | 小写前缀 | `sh603365` |
| 市场前缀推断 | 6/9→SH，0/3→SZ，4/8/92→BJ | — |

`norm_symbol()` 已封装在 `scripts/probe_sources.py`，适配层脚本直接复用。

## 四、复权口径纪律（估值结果依赖）

- **PE/PB 估值带**：用**不复权**名义价（与报告期 EPS/BPS 匹配）
- **股价分位、基准价三锚、目标买入价/门槛价格对比**：用**前复权**价
- 两份日线都要拉：`日线股价.csv`（不复权）+ `日线股价_前复权.csv`
- 腾讯源复权基准与东财可能不同：跨时段价格锚对比时注明来源

## 五、财务数据语义（源数据要自己验证）

- **东财单季表 EPSJB 是单季值**（非累计）——TTM EPS 需滚动 4 期求和
- 财务指标表的"报告期"行会重复出现（同一报告期多行）——按日期去重取第一个
- 分红支付率校验：DPS×股本 vs 分配现金（法1 vs 法2），偏差 >5pct 排除法 1
- 2022 式异常年（疫情 OCF 骤降）会主导 λ 回归——λ 需结合业务事件判断可信度，不可机械使用

## 五·五、行业特有数据（白酒批价，2026-08-15 新增）

- 通用接口（akshare/东财/腾讯）**无白酒批价与产量端点**；用 `scripts/templates-extra/fetch_liquor_industry.py` 生成 CSV 骨架后 Agent WebSearch 手工维护
- 批价源：今日酒价（微信平台/酒价数据）——**原箱 vs 散瓶必须分开记录**；口径分离标注：批价 / 出厂价 / 建议零售价
- 产量源：中国酒业协会年度报告 / 国家统计局规模以上企业白酒产量（年度）
- 渠道库存：酒业家/微酒行业报道（定性，标注来源日期）
- ⚠️ 同一数据生产方的转引（如今日酒价/新浪转引同一机构）不算双源，证据级别按 framework.md D2 降为 L3
## 六、工程/环境坑（Windows + PowerShell 5.1）

| 坑 | 现象 | 解决 |
|----|------|------|
| `>` 重定向加 UTF-8 BOM | JSON 解析器不认 | subprocess 捕获 stdout 后 Python 写文件（或 write_text 指定 encoding） |
| 内联 python f-string 转义 | PowerShell 5.1 引号规则导致 SyntaxError | 一律写成正式 .py 脚本文件（同时符合脚本纪律） |
| `&&` / `-join` 语法 | PS 5.1 不支持 / 用法不同 | 用 `;` 和 `if ($?)`；`-join` 需加括号 |
| SSL 错误被吞 | 东财/新浪报 SSL EOF 但详情不清 | 探测脚本区分 SSL/超时/连接错误类型 |

## 七、流水线集成方式

1. 立项后先跑：`python scripts/probe_sources.py <代码> --out <项目>/data` → 源探测.json
2. 拉数统一走：`python scripts/fetch_with_fallback.py <代码> --out <项目>/data` → 自动降级 + 拉取清单.json
3. 拉取清单中 MISS/FAIL 项 → 审计报告逐项标注降级路径，进 Warnings
4. 数据可用性变化时（如东财恢复）重新探测即可，脚本无需改动

## 八、本清单的更新协议

- 每次分析如遇新坑（新接口缺失/新端点故障/新格式要求），按上述分类补充一行
- 更新后同步写进项目 `reports/跟踪验证台账.md` 的 skill 迭代日志
- 探测脚本本身是单文件，无需依赖，直接复制到项目 scripts/ 即可独立使用
