# Tushare API 参考文档

> Phase 1A `tushare_collector.py` 使用的 Tushare Pro 接口参考。
> 仅收录本项目实际调用或可能调用的接口。

---

## 1. 财务指标数据 (`fina_indicator`)

- **接口**: `fina_indicator`，可通过数据工具调试和查看数据
- **描述**: 获取上市公司财务指标数据，为避免服务器压力，现阶段每次请求最多返回100条记录，可通过设置日期多次请求获取更多数据
- **权限**: 用户需要至少 **2000积分** 才可以调取
- **提示**: 当前接口只能按单只股票获取其历史数据，如需获取某一季度全部上市公司数据，请使用 `fina_indicator_vip` 接口（参数一致），需积攒5000积分

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | Y | TS股票代码, e.g. 600001.SH/000001.SZ |
| ann_date | str | N | 公告日期 |
| start_date | str | N | 报告期开始日期 |
| end_date | str | N | 报告期结束日期 |
| period | str | N | 报告期(每个季度最后一天的日期, 比如20171231表示年报) |

### 输出参数

#### 每股指标

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| ts_code | str | Y | TS代码 |
| ann_date | str | Y | 公告日期 |
| end_date | str | Y | 报告期 |
| eps | float | Y | 基本每股收益 |
| dt_eps | float | Y | 稀释每股收益 |
| total_revenue_ps | float | Y | 每股营业总收入 |
| revenue_ps | float | Y | 每股营业收入 |
| capital_rese_ps | float | Y | 每股资本公积 |
| surplus_rese_ps | float | Y | 每股盈余公积 |
| undist_profit_ps | float | Y | 每股未分配利润 |
| extra_item | float | Y | 非经常性损益 |
| profit_dedt | float | Y | 扣除非经常性损益后的净利润（扣非净利润） |
| gross_margin | float | Y | 毛利 |
| diluted2_eps | float | Y | 期末摊薄每股收益 |
| bps | float | Y | 每股净资产 |
| ocfps | float | Y | 每股经营活动产生的现金流量净额 |
| retainedps | float | Y | 每股留存收益 |
| cfps | float | Y | 每股现金流量净额 |
| ebit_ps | float | Y | 每股息税前利润 |
| fcff_ps | float | Y | 每股企业自由现金流量 |
| fcfe_ps | float | Y | 每股股东自由现金流量 |

#### 流动性指标

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| current_ratio | float | Y | 流动比率 |
| quick_ratio | float | Y | 速动比率 |
| cash_ratio | float | Y | 保守速动比率 |

#### 周转率指标

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| invturn_days | float | N | 存货周转天数 |
| arturn_days | float | N | 应收账款周转天数 |
| inv_turn | float | N | 存货周转率 |
| ar_turn | float | Y | 应收账款周转率 |
| ca_turn | float | Y | 流动资产周转率 |
| fa_turn | float | Y | 固定资产周转率 |
| assets_turn | float | Y | 总资产周转率 |
| turn_days | float | Y | 营业周期 |
| total_fa_trun | float | N | 固定资产合计周转率 |

#### 利润与现金流指标

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| op_income | float | Y | 经营活动净收益 |
| valuechange_income | float | N | 价值变动净收益 |
| interst_income | float | N | 利息费用 |
| daa | float | N | 折旧与摊销 |
| ebit | float | Y | 息税前利润 |
| ebitda | float | Y | 息税折旧摊销前利润 |
| fcff | float | Y | 企业自由现金流量 |
| fcfe | float | Y | 股权自由现金流量 |

#### 资产负债结构

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| current_exint | float | Y | 无息流动负债 |
| noncurrent_exint | float | Y | 无息非流动负债 |
| interestdebt | float | Y | 带息债务 |
| netdebt | float | Y | 净债务 |
| tangible_asset | float | Y | 有形资产 |
| working_capital | float | Y | 营运资金 |
| networking_capital | float | Y | 营运流动资本 |
| invest_capital | float | Y | 全部投入资本 |
| retained_earnings | float | Y | 留存收益 |
| fixed_assets | float | Y | 固定资产合计 |

#### 盈利能力

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| netprofit_margin | float | Y | 销售净利率 |
| grossprofit_margin | float | Y | 销售毛利率 |
| cogs_of_sales | float | Y | 销售成本率 |
| expense_of_sales | float | Y | 销售期间费用率 |
| profit_to_gr | float | Y | 净利润/营业总收入 |
| saleexp_to_gr | float | Y | 销售费用/营业总收入 |
| adminexp_of_gr | float | Y | 管理费用/营业总收入 |
| finaexp_of_gr | float | Y | 财务费用/营业总收入 |
| impai_ttm | float | Y | 资产减值损失/营业总收入 |
| gc_of_gr | float | Y | 营业总成本/营业总收入 |
| op_of_gr | float | Y | 营业利润/营业总收入 |
| ebit_of_gr | float | Y | 息税前利润/营业总收入 |
| profit_to_op | float | Y | 利润总额／营业收入 |

#### 回报率

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| roe | float | Y | 净资产收益率 |
| roe_waa | float | Y | 加权平均净资产收益率 |
| roe_dt | float | Y | 净资产收益率(扣除非经常损益) |
| roa | float | Y | 总资产报酬率 |
| npta | float | Y | 总资产净利润 |
| roic | float | Y | 投入资本回报率 |
| roe_yearly | float | Y | 年化净资产收益率 |
| roa2_yearly | float | Y | 年化总资产报酬率 |
| roe_avg | float | N | 平均净资产收益率(增发条件) |
| roa_yearly | float | Y | 年化总资产净利率 |
| roa_dp | float | Y | 总资产净利率(杜邦分析) |
| roic_yearly | float | N | 年化投入资本回报率 |

#### 利润结构

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| opincome_of_ebt | float | N | 经营活动净收益/利润总额 |
| investincome_of_ebt | float | N | 价值变动净收益/利润总额 |
| n_op_profit_of_ebt | float | N | 营业外收支净额/利润总额 |
| tax_to_ebt | float | N | 所得税/利润总额 |
| dtprofit_to_profit | float | N | 扣除非经常损益后的净利润/净利润 |
| profit_prefin_exp | float | N | 扣除财务费用前营业利润 |
| non_op_profit | float | N | 非营业利润 |
| op_to_ebt | float | N | 营业利润／利润总额 |
| nop_to_ebt | float | N | 非营业利润／利润总额 |

#### 现金流质量

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| salescash_to_or | float | N | 销售商品提供劳务收到的现金/营业收入 |
| ocf_to_or | float | N | 经营活动产生的现金流量净额/营业收入 |
| ocf_to_opincome | float | N | 经营活动产生的现金流量净额/经营活动净收益 |
| capitalized_to_da | float | N | 资本支出/折旧和摊销 |
| ocf_to_profit | float | N | 经营活动产生的现金流量净额／营业利润 |
| cash_to_liqdebt | float | N | 货币资金／流动负债 |
| cash_to_liqdebt_withinterest | float | N | 货币资金／带息流动负债 |
| op_to_liqdebt | float | N | 营业利润／流动负债 |
| op_to_debt | float | N | 营业利润／负债合计 |

#### 杠杆与偿债

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| debt_to_assets | float | Y | 资产负债率 |
| assets_to_eqt | float | Y | 权益乘数 |
| dp_assets_to_eqt | float | Y | 权益乘数(杜邦分析) |
| ca_to_assets | float | Y | 流动资产/总资产 |
| nca_to_assets | float | Y | 非流动资产/总资产 |
| tbassets_to_totalassets | float | Y | 有形资产/总资产 |
| int_to_talcap | float | Y | 带息债务/全部投入资本 |
| eqt_to_talcapital | float | Y | 归属于母公司的股东权益/全部投入资本 |
| currentdebt_to_debt | float | Y | 流动负债/负债合计 |
| longdeb_to_debt | float | Y | 非流动负债/负债合计 |
| ocf_to_shortdebt | float | Y | 经营活动产生的现金流量净额/流动负债 |
| debt_to_eqt | float | Y | 产权比率 |
| eqt_to_debt | float | Y | 归属于母公司的股东权益/负债合计 |
| eqt_to_interestdebt | float | Y | 归属于母公司的股东权益/带息债务 |
| tangibleasset_to_debt | float | Y | 有形资产/负债合计 |
| tangasset_to_intdebt | float | Y | 有形资产/带息债务 |
| tangibleasset_to_netdebt | float | Y | 有形资产/净债务 |
| ocf_to_debt | float | Y | 经营活动产生的现金流量净额/负债合计 |
| ocf_to_interestdebt | float | N | 经营活动产生的现金流量净额/带息债务 |
| ocf_to_netdebt | float | N | 经营活动产生的现金流量净额/净债务 |
| ebit_to_interest | float | N | 已获利息倍数(EBIT/利息费用) |
| longdebt_to_workingcapital | float | N | 长期债务与营运资金比率 |
| ebitda_to_debt | float | N | 息税折旧摊销前利润/负债合计 |

#### 同比增长率

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| basic_eps_yoy | float | Y | 基本每股收益同比增长率(%) |
| dt_eps_yoy | float | Y | 稀释每股收益同比增长率(%) |
| cfps_yoy | float | Y | 每股经营活动产生的现金流量净额同比增长率(%) |
| op_yoy | float | Y | 营业利润同比增长率(%) |
| ebt_yoy | float | Y | 利润总额同比增长率(%) |
| netprofit_yoy | float | Y | 归属母公司股东的净利润同比增长率(%) |
| dt_netprofit_yoy | float | Y | 归属母公司股东的净利润-扣除非经常损益同比增长率(%) |
| ocf_yoy | float | Y | 经营活动产生的现金流量净额同比增长率(%) |
| roe_yoy | float | Y | 净资产收益率(摊薄)同比增长率(%) |
| bps_yoy | float | Y | 每股净资产相对年初增长率(%) |
| assets_yoy | float | Y | 资产总计相对年初增长率(%) |
| eqt_yoy | float | Y | 归属母公司的股东权益相对年初增长率(%) |
| tr_yoy | float | Y | 营业总收入同比增长率(%) |
| or_yoy | float | Y | 营业收入同比增长率(%) |
| equity_yoy | float | Y | 净资产同比增长率 |

#### 单季度指标

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| q_opincome | float | N | 经营活动单季度净收益 |
| q_investincome | float | N | 价值变动单季度净收益 |
| q_dtprofit | float | N | 扣除非经常损益后的单季度净利润 |
| q_eps | float | N | 每股收益(单季度) |
| q_netprofit_margin | float | N | 销售净利率(单季度) |
| q_gsprofit_margin | float | N | 销售毛利率(单季度) |
| q_exp_to_sales | float | N | 销售期间费用率(单季度) |
| q_profit_to_gr | float | N | 净利润／营业总收入(单季度) |
| q_saleexp_to_gr | float | Y | 销售费用／营业总收入(单季度) |
| q_adminexp_to_gr | float | N | 管理费用／营业总收入(单季度) |
| q_finaexp_to_gr | float | N | 财务费用／营业总收入(单季度) |
| q_impair_to_gr_ttm | float | N | 资产减值损失／营业总收入(单季度) |
| q_gc_to_gr | float | Y | 营业总成本／营业总收入(单季度) |
| q_op_to_gr | float | N | 营业利润／营业总收入(单季度) |
| q_roe | float | Y | 净资产收益率(单季度) |
| q_dt_roe | float | Y | 净资产单季度收益率(扣除非经常损益) |
| q_npta | float | Y | 总资产净利润(单季度) |
| q_opincome_to_ebt | float | N | 经营活动净收益／利润总额(单季度) |
| q_investincome_to_ebt | float | N | 价值变动净收益／利润总额(单季度) |
| q_dtprofit_to_profit | float | N | 扣除非经常损益后的净利润／净利润(单季度) |
| q_salescash_to_or | float | N | 销售商品提供劳务收到的现金／营业收入(单季度) |
| q_ocf_to_sales | float | Y | 经营活动产生的现金流量净额／营业收入(单季度) |
| q_ocf_to_or | float | N | 经营活动产生的现金流量净额／经营活动净收益(单季度) |

#### 单季度同比/环比

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| q_gr_yoy | float | N | 营业总收入同比增长率(%)(单季度) |
| q_gr_qoq | float | N | 营业总收入环比增长率(%)(单季度) |
| q_sales_yoy | float | Y | 营业收入同比增长率(%)(单季度) |
| q_sales_qoq | float | N | 营业收入环比增长率(%)(单季度) |
| q_op_yoy | float | N | 营业利润同比增长率(%)(单季度) |
| q_op_qoq | float | Y | 营业利润环比增长率(%)(单季度) |
| q_profit_yoy | float | N | 净利润同比增长率(%)(单季度) |
| q_profit_qoq | float | N | 净利润环比增长率(%)(单季度) |
| q_netprofit_yoy | float | N | 归属母公司股东的净利润同比增长率(%)(单季度) |
| q_netprofit_qoq | float | N | 归属母公司股东的净利润环比增长率(%)(单季度) |

#### 其他

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| rd_exp | float | N | 研发费用 |
| update_flag | str | N | 更新标识 |

### 接口用法

```python
pro = ts.pro_api()

df = pro.fina_indicator(ts_code='600000.SH')
# 或者
df = pro.query('fina_indicator', ts_code='600000.SH', start_date='20170101', end_date='20180801')
```

### 数据样例

```
   ts_code  ann_date  end_date   eps  dt_eps  total_revenue_ps  revenue_ps
0  600000.SH  20180830  20180630  0.95    0.95            2.8024      2.8024
1  600000.SH  20180428  20180331  0.46    0.46            1.3501      1.3501
2  600000.SH  20180428  20171231  1.84    1.84            5.7447      5.7447
```

### 本项目使用的字段

`tushare_collector.py` 中 `get_fina_indicators()` 当前请求的字段：

```
ts_code, end_date, roe, roe_waa, grossprofit_margin, netprofit_margin,
rd_exp, current_ratio, quick_ratio, assets_turn, debt_to_assets
```

---

## 2. 财务审计意见 (`fina_audit`)

- **接口**: `fina_audit`
- **描述**: 获取上市公司定期财务审计意见数据
- **权限**: 用户需要至少 **500积分** 才可以调取

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | Y | 股票代码 |
| ann_date | str | N | 公告日期 |
| start_date | str | N | 公告开始日期 |
| end_date | str | N | 公告结束日期 |
| period | str | N | 报告期(每个季度最后一天的日期, 比如20171231表示年报) |

### 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| ts_code | str | TS股票代码 |
| ann_date | str | 公告日期 |
| end_date | str | 报告期 |
| audit_result | str | 审计结果 |
| audit_fees | float | 审计总费用（元） |
| audit_agency | str | 会计事务所 |
| audit_sign | str | 签字会计师 |

### 接口用法

```python
pro = ts.pro_api()

df = pro.fina_audit(ts_code='600000.SH', start_date='20100101', end_date='20180808')
```

### 数据样例

```
      ts_code  ann_date  end_date    audit_result              audit_agency        audit_sign
0  600000.SH  20180428  20171231  标准无保留意见  普华永道中天会计师事务所      周章,张武
1  600000.SH  20170401  20161231  标准无保留意见  普华永道中天会计师事务所      周章,张武
2  600000.SH  20160407  20151231  标准无保留意见  普华永道中天会计师事务所      胡亮,张武
```

### 本项目使用的字段

`tushare_collector.py` 中 `get_audit()` 当前请求的字段：

```
ts_code, end_date, audit_result, audit_agency, audit_fees
```

---

## 3. 主营业务构成 (`fina_mainbz`)

- **接口**: `fina_mainbz`
- **描述**: 获得上市公司主营业务构成，分地区和产品两种方式
- **权限**: 用户需要至少 **2000积分** 才可以调取
- **提示**: 单次最大2000条，可通过设置日期多次请求获取更多数据

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | Y | 股票代码 |
| period | str | N | 报告期 (如 20171231 表示年报) |
| type | str | N | 类型：P按产品 D按地区 I按行业 |
| start_date | str | N | 报告期开始日期 |
| end_date | str | N | 报告期结束日期 |

### 输出参数

| 名称 | 类型 | 描述 |
|------|------|------|
| ts_code | str | TS代码 |
| end_date | str | 报告期 |
| bz_item | str | 主营业务来源 |
| bz_sales | float | 主营业务收入 (元) |
| bz_profit | float | 主营业务利润 (元) |
| bz_cost | float | 主营业务成本 (元) |
| curr_type | str | 货币代码 |
| update_flag | str | 是否更新 |

### 接口用法

```python
pro = ts.pro_api()

# 按产品分类
df = pro.fina_mainbz(ts_code='000627.SZ', period='20171231', type='P')

# 按地区分类
df = pro.fina_mainbz(ts_code='000627.SZ', period='20171231', type='D')
```

### 数据样例

```
      ts_code  end_date   bz_item      bz_sales     bz_profit      bz_cost  curr_type
0  000627.SZ  20171231   氯碱化工  1.861000e+09  4.700000e+08  1.391000e+09        CNY
1  000627.SZ  20171231   房地产    7.380000e+08  4.880000e+08  2.500000e+08        CNY
2  000627.SZ  20171231   药品      6.320000e+08  3.860000e+08  2.460000e+08        CNY
```

### 本项目使用的字段

`tushare_collector.py` 中 `get_segments()` 当前请求的字段：

```
ts_code, end_date, bz_item, bz_sales, bz_profit, bz_cost
```

**注意**: 本项目使用 `fina_mainbz` 接口（非 `fina_mainbz_ts`），按产品分类 (`type='P'`)。
毛利率通过 `(1 - bz_cost / bz_sales) * 100` 计算得出。

---

## 4. 现金流量表 (`cashflow`)

- **接口**: `cashflow`
- **描述**: 获取上市公司现金流量表
- **权限**: 用户需要至少 **2000积分** 才可以调取
- **提示**: 如需获取某一季度全部上市公司数据，请使用 `cashflow_vip` 接口（需5000积分）

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | Y | 股票代码 |
| ann_date | str | N | 公告日期 |
| f_ann_date | str | N | 实际公告日期 |
| start_date | str | N | 公告开始日期 |
| end_date | str | N | 公告结束日期 |
| period | str | N | 报告期(每个季度最后一天的日期, 比如20171231表示年报) |
| report_type | str | N | 报告类型 |
| comp_type | str | N | 公司类型（1一般工商业 2银行 3保险 4证券） |
| is_calc | int | N | 是否计算报表 |

### 输出参数

#### 经营活动现金流入

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| ts_code | str | Y | TS代码 |
| ann_date | str | Y | 公告日期 |
| f_ann_date | str | Y | 实际公告日期 |
| end_date | str | Y | 报告期 |
| comp_type | str | Y | 公司类型 |
| report_type | str | Y | 报告类型 |
| end_type | str | Y | 报告期类型 |
| net_profit | float | Y | 净利润 |
| finan_exp | float | Y | 财务费用 |
| c_fr_sale_sg | float | Y | 销售商品、提供劳务收到的现金 |
| recp_tax_rends | float | Y | 收到的税费返还 |
| n_depos_incr_fi | float | Y | 客户存款和同业存放款项净增加额 |
| n_incr_loans_cb | float | Y | 向中央银行借款净增加额 |
| n_inc_borr_oth_fi | float | Y | 向其他金融机构拆入资金净增加额 |
| prem_fr_orig_contr | float | Y | 收到原保险合同保费取得的现金 |
| n_incr_insured_dep | float | Y | 保户储金及投资款净增加额 |
| n_reinsur_prem | float | Y | 收到再保业务现金净额 |
| n_incr_disp_tfa | float | Y | 处置交易性金融资产净增加额 |
| ifc_cash_incr | float | Y | 收取利息、手续费及佣金的现金 |
| n_incr_disp_faas | float | Y | 处置可供出售金融资产净增加额 |
| n_incr_loans_oth_bank | float | Y | 拆入资金净增加额 |
| n_cap_incr_repur | float | Y | 回购业务资金净增加额 |
| c_fr_oth_operate_a | float | Y | 收到其他与经营活动有关的现金 |
| c_inf_fr_operate_a | float | Y | 经营活动现金流入小计 |

#### 经营活动现金流出

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| c_paid_goods_s | float | Y | 购买商品、接受劳务支付的现金 |
| c_paid_to_for_empl | float | Y | 支付给职工以及为职工支付的现金 |
| c_paid_for_taxes | float | Y | 支付的各项税费 |
| n_incr_clt_loan_adv | float | Y | 客户贷款及垫款净增加额 |
| n_incr_dep_cbob | float | Y | 存放中央银行和同业款项净增加额 |
| c_pay_claims_orig_inco | float | Y | 支付原保险合同赔付款项的现金 |
| pay_handling_chrg | float | Y | 支付手续费的现金 |
| pay_comm_insur_plcy | float | Y | 支付保单红利的现金 |
| oth_cash_pay_oper_act | float | Y | 支付其他与经营活动有关的现金 |
| st_cash_out_act | float | Y | 经营活动现金流出小计 |
| n_cashflow_act | float | Y | 经营活动产生的现金流量净额 |

#### 投资活动现金流

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| oth_recp_ral_inv_act | float | Y | 收到其他与投资活动有关的现金 |
| c_disp_withdrwl_invest | float | Y | 收回投资收到的现金 |
| c_recp_return_invest | float | Y | 取得投资收益收到的现金 |
| n_recp_disp_fiolta | float | Y | 处置固定资产、无形资产和其他长期资产收回的现金净额 |
| n_recp_disp_sobu | float | Y | 处置子公司及其他营业单位收到的现金净额 |
| stot_inflows_inv_act | float | Y | 投资活动现金流入小计 |
| c_pay_acq_const_fiolta | float | Y | 购建固定资产、无形资产和其他长期资产支付的现金 |
| c_paid_invest | float | Y | 投资支付的现金 |
| n_disp_subs_oth_biz | float | Y | 取得子公司及其他营业单位支付的现金净额 |
| oth_pay_ral_inv_act | float | Y | 支付其他与投资活动有关的现金 |
| n_incr_pledge_loan | float | Y | 质押贷款净增加额 |
| stot_out_inv_act | float | Y | 投资活动现金流出小计 |
| n_cashflow_inv_act | float | Y | 投资活动产生的现金流量净额 |

#### 筹资活动现金流

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| c_recp_borrow | float | Y | 取得借款收到的现金 |
| proc_issue_bonds | float | Y | 发行债券收到的现金 |
| oth_cash_recp_ral_fnc_act | float | Y | 收到其他与筹资活动有关的现金 |
| stot_cash_in_fnc_act | float | Y | 筹资活动现金流入小计 |
| free_cashflow | float | Y | 企业自由现金流量 |
| c_prepay_amt_borr | float | Y | 偿还债务支付的现金 |
| c_pay_dist_dpcp_int_exp | float | Y | 分配股利、利润或偿付利息支付的现金 |
| incl_dvd_profit_paid_sc_ms | float | Y | 其中:子公司支付给少数股东的股利、利润 |
| oth_cashpay_ral_fnc_act | float | Y | 支付其他与筹资活动有关的现金 |
| stot_cashout_fnc_act | float | Y | 筹资活动现金流出小计 |
| n_cash_flows_fnc_act | float | Y | 筹资活动产生的现金流量净额 |
| eff_fx_flu_cash | float | Y | 汇率变动对现金的影响 |
| n_incr_cash_cash_equ | float | Y | 现金及现金等价物净增加额 |
| c_cash_equ_beg_period | float | Y | 期初现金及现金等价物余额 |
| c_cash_equ_end_period | float | Y | 期末现金及现金等价物余额 |
| c_recp_cap_contrib | float | Y | 吸收投资收到的现金 |
| incl_cash_rec_saims | float | Y | 其中:子公司吸收少数股东投资收到的现金 |

#### 间接法补充项目

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| uncon_invest_loss | float | Y | 未确认投资损失 |
| prov_depr_assets | float | Y | 资产减值准备 |
| depr_fa_coga_dpba | float | Y | 固定资产折旧、油气资产折耗、生产性生物资产折旧 |
| amort_intang_assets | float | Y | 无形资产摊销 |
| lt_amort_deferred_exp | float | Y | 长期待摊费用摊销 |
| decr_deferred_exp | float | Y | 待摊费用减少 |
| incr_acc_exp | float | Y | 预提费用增加 |
| loss_disp_fiolta | float | Y | 处置固定资产、无形资产和其他长期资产的损失 |
| loss_scr_fa | float | Y | 固定资产报废损失 |
| loss_fv_chg | float | Y | 公允价值变动损失 |
| invest_loss | float | Y | 投资损失 |
| decr_def_inc_tax_assets | float | Y | 递延所得税资产减少 |
| incr_def_inc_tax_liab | float | Y | 递延所得税负债增加 |
| decr_inventories | float | Y | 存货的减少 |
| decr_oper_payable | float | Y | 经营性应收项目的减少 |
| incr_oper_payable | float | Y | 经营性应付项目的增加 |
| others | float | Y | 其他 |
| im_net_cashflow_oper_act | float | Y | 经营活动产生的现金流量净额(间接法) |
| conv_debt_into_cap | float | Y | 债务转为资本 |
| conv_copbonds_due_within_1y | float | Y | 一年内到期的可转换公司债券 |
| fa_fnc_leases | float | Y | 融资租入固定资产 |
| im_n_incr_cash_equ | float | Y | 现金及现金等价物净增加额(间接法) |
| net_dism_capital_add | float | Y | 拆出资金净增加额 |
| net_cash_rece_sec | float | Y | 代理买卖证券收到的现金净额 |
| credit_impa_loss | float | Y | 信用减值损失 |
| use_right_asset_dep | float | Y | 使用权资产折旧 |
| oth_loss_asset | float | Y | 其他资产减值损失 |
| end_bal_cash | float | Y | 现金的期末余额 |
| beg_bal_cash | float | Y | 现金的期初余额 |
| end_bal_cash_equ | float | Y | 现金等价物的期末余额 |
| beg_bal_cash_equ | float | Y | 现金等价物的期初余额 |
| update_flag | str | Y | 更新标识 |

### 接口用法

```python
pro = ts.pro_api()

df = pro.cashflow(ts_code='600000.SH', start_date='20180101', end_date='20180730')
```

### 本项目使用的字段

`tushare_collector.py` 中 `get_cashflow()` 当前请求的字段：

```
ts_code, end_date, n_cashflow_act, c_pay_acq_const_fiolta,
depr_fa_coga_dpba, amort_intang_assets, lt_amort_deferred_exp,
n_cashflow_inv_act, n_cash_flows_fnc_act, c_cash_equ_end_period,
c_recp_return_invest, n_recp_disp_fiolta, c_paid_invest, n_disp_subs_oth_biz,
free_cashflow, c_pay_dist_dpcp_int_exp
```

---

## 5. 资产负债表 (`balancesheet`)

- **接口**: `balancesheet`
- **描述**: 获取上市公司资产负债表
- **权限**: 用户需要至少 **2000积分** 才可以调取
- **提示**: 如需获取某一季度全部上市公司数据，请使用 `balancesheet_vip` 接口（需5000积分）

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | Y | 股票代码 |
| ann_date | str | N | 公告日期 |
| start_date | str | N | 公告开始日期 |
| end_date | str | N | 公告结束日期 |
| period | str | N | 报告期(每个季度最后一天的日期, 比如20171231表示年报) |
| report_type | str | N | 报告类型（见下方说明） |
| comp_type | str | N | 公司类型（1一般工商业 2银行 3保险 4证券） |

### report_type 说明

| 代码 | 类型 | 描述 |
|------|------|------|
| 1 | 合并报表 | 公司最新报表（默认） |
| 2 | 单季合并 | 单一季度合并报表 |
| 3 | 调整单季合并表 | 调整后单季合并报表 |
| 4 | 调整合并报表 | 上年同期调整后数据 |
| 5 | 调整前合并报表 | 变更前原始数据 |
| 6 | 母公司报表 | 母公司财务数据 |
| 7 | 母公司单季表 | 母公司单季数据 |
| 8 | 母公司调整单季表 | 母公司调整后单季 |
| 9 | 母公司调整表 | 母公司上年同期调整后 |
| 10 | 母公司调整前报表 | 母公司变更前原始数据 |

### 输出参数

#### 资产类

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| ts_code | str | Y | TS代码 |
| ann_date | str | Y | 公告日期 |
| f_ann_date | str | Y | 实际公告日期 |
| end_date | str | Y | 报告期 |
| report_type | str | Y | 报告类型 |
| comp_type | str | Y | 公司类型 |
| end_type | str | Y | 报告期类型 |
| total_share | float | Y | 期末总股本 |
| money_cap | float | Y | 货币资金 |
| trad_asset | float | Y | 交易性金融资产 |
| notes_receiv | float | Y | 应收票据 |
| accounts_receiv | float | Y | 应收账款 |
| oth_receiv | float | Y | 其他应收款 |
| prepayment | float | Y | 预付款项 |
| div_receiv | float | Y | 应收股利 |
| int_receiv | float | Y | 应收利息 |
| inventories | float | Y | 存货 |
| amor_exp | float | Y | 待摊费用 |
| nca_within_1y | float | Y | 一年内到期的非流动资产 |
| sett_rsrv | float | Y | 结算备付金 |
| loanto_oth_bank_fi | float | Y | 拆出资金 |
| premium_receiv | float | Y | 应收保费 |
| reinsur_receiv | float | Y | 应收分保账款 |
| reinsur_res_receiv | float | Y | 应收分保合同准备金 |
| pur_resale_fa | float | Y | 买入返售金融资产 |
| oth_cur_assets | float | Y | 其他流动资产 |
| total_cur_assets | float | Y | 流动资产合计 |
| fa_avail_for_sale | float | Y | 可供出售金融资产 |
| htm_invest | float | Y | 持有至到期投资 |
| lt_eqt_invest | float | Y | 长期股权投资 |
| invest_real_estate | float | Y | 投资性房地产 |
| time_deposits | float | Y | 定期存款 |
| oth_assets | float | Y | 其他资产 |
| lt_rec | float | Y | 长期应收款 |
| fix_assets | float | Y | 固定资产 |
| cip | float | Y | 在建工程 |
| const_materials | float | Y | 工程物资 |
| fixed_assets_disp | float | Y | 固定资产清理 |
| produc_bio_assets | float | Y | 生产性生物资产 |
| oil_and_gas_assets | float | Y | 油气资产 |
| intan_assets | float | Y | 无形资产 |
| r_and_d | float | Y | 开发支出 |
| goodwill | float | Y | 商誉 |
| lt_amor_exp | float | Y | 长期待摊费用 |
| defer_tax_assets | float | Y | 递延所得税资产 |
| decr_in_disbur | float | Y | 发放贷款及垫款 |
| oth_nca | float | Y | 其他非流动资产 |
| total_nca | float | Y | 非流动资产合计 |
| cash_reser_cb | float | Y | 现金及存放中央银行款项 |
| depos_in_oth_bfi | float | Y | 存放同业和其他金融机构款项 |
| prec_metals | float | Y | 贵金属 |
| deriv_assets | float | Y | 衍生金融资产 |
| rr_reins_une_prem | float | Y | 应收分保未到期责任准备金 |
| rr_reins_outstd_cla | float | Y | 应收分保未决赔款准备金 |
| rr_reins_lins_liab | float | Y | 应收分保寿险责任准备金 |
| rr_reins_lthins_liab | float | Y | 应收分保长期健康险责任准备金 |
| refund_depos | float | Y | 存出保证金 |
| ph_pledge_loans | float | Y | 保户质押贷款 |
| refund_cap_depos | float | Y | 存出资本保证金 |
| indep_acct_assets | float | Y | 独立账户资产 |
| client_depos | float | Y | 客户资金存款 |
| client_prov | float | Y | 客户备付金 |
| transac_seat_fee | float | Y | 交易席位费 |
| invest_as_receiv | float | Y | 应收款项类投资 |
| total_assets | float | Y | 资产总计 |

#### 负债类

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| st_borr | float | Y | 短期借款 |
| cb_borr | float | Y | 向中央银行借款 |
| depos_ib_deposits | float | Y | 吸收存款及同业存放 |
| loan_oth_bank | float | Y | 拆入资金 |
| trading_fl | float | Y | 交易性金融负债 |
| notes_payable | float | Y | 应付票据 |
| acct_payable | float | Y | 应付账款 |
| adv_receipts | float | Y | 预收款项 |
| sold_for_repur_fa | float | Y | 卖出回购金融资产款 |
| comm_payable | float | Y | 应付手续费及佣金 |
| payroll_payable | float | Y | 应付职工薪酬 |
| taxes_payable | float | Y | 应交税费 |
| int_payable | float | Y | 应付利息 |
| div_payable | float | Y | 应付股利 |
| oth_payable | float | Y | 其他应付款 |
| acc_exp | float | Y | 预提费用 |
| deferred_inc | float | Y | 递延收益 |
| st_bonds_payable | float | Y | 应付短期债券 |
| payable_to_reinsurer | float | Y | 应付分保账款 |
| rsrv_insur_cont | float | Y | 保险合同准备金 |
| acting_trading_sec | float | Y | 代理买卖证券款 |
| acting_uw_sec | float | Y | 代理承销证券款 |
| non_cur_liab_due_1y | float | Y | 一年内到期的非流动负债 |
| oth_cur_liab | float | Y | 其他流动负债 |
| total_cur_liab | float | Y | 流动负债合计 |
| lt_borr | float | Y | 长期借款 |
| bond_payable | float | Y | 应付债券 |
| lt_payable | float | Y | 长期应付款 |
| specific_payables | float | Y | 专项应付款 |
| estimated_liab | float | Y | 预计负债 |
| defer_tax_liab | float | Y | 递延所得税负债 |
| defer_inc_non_cur_liab | float | Y | 递延收益-非流动负债 |
| oth_ncl | float | Y | 其他非流动负债 |
| total_ncl | float | Y | 非流动负债合计 |
| depos_oth_bfi | float | Y | 同业和其他金融机构存放款项 |
| deriv_liab | float | Y | 衍生金融负债 |
| depos | float | Y | 吸收存款 |
| agency_bus_liab | float | Y | 代理业务负债 |
| oth_liab | float | Y | 其他负债 |
| prem_receiv_adva | float | Y | 预收保费 |
| depos_received | float | Y | 存入保证金 |
| ph_invest | float | Y | 保户储金及投资款 |
| reser_une_prem | float | Y | 未到期责任准备金 |
| reser_outstd_claims | float | Y | 未决赔款准备金 |
| reser_lins_liab | float | Y | 寿险责任准备金 |
| reser_lthins_liab | float | Y | 长期健康险责任准备金 |
| indept_acc_liab | float | Y | 独立账户负债 |
| pledge_borr | float | Y | 质押借款 |
| indem_payable | float | Y | 应付赔付款 |
| policy_div_payable | float | Y | 应付保单红利 |
| total_liab | float | Y | 负债合计 |

#### 所有者权益

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| cap_rese | float | Y | 资本公积金 |
| undistr_porfit | float | Y | 未分配利润 |
| surplus_rese | float | Y | 盈余公积金 |
| special_rese | float | Y | 专项储备 |
| treasury_share | float | Y | 库存股 |
| ordin_risk_reser | float | Y | 一般风险准备 |
| forex_differ | float | Y | 外币报表折算差额 |
| invest_loss_unconf | float | Y | 未确认的投资损失 |
| minority_int | float | Y | 少数股东权益 |
| total_hldr_eqy_exc_min_int | float | Y | 股东权益合计(不含少数股东权益) |
| total_hldr_eqy_inc_min_int | float | Y | 股东权益合计(含少数股东权益) |
| total_liab_hldr_eqy | float | Y | 负债及股东权益总计 |
| lt_payroll_payable | float | Y | 长期应付职工薪酬 |
| oth_comp_income | float | Y | 其他综合收益 |
| oth_eqt_tools | float | Y | 其他权益工具 |
| oth_eqt_tools_p_shr | float | Y | 其他权益工具(优先股) |
| lending_funds | float | Y | 融出资金 |

#### 新准则字段

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| acc_receivable | float | Y | 应收款项 |
| st_fin_payable | float | Y | 应付短期融资款 |
| payables | float | Y | 应付款项 |
| hfs_assets | float | Y | 持有待售资产 |
| hfs_sales | float | Y | 持有待售负债 |
| cost_fin_assets | float | Y | 以摊余成本计量的金融资产 |
| fair_value_fin_assets | float | Y | 以公允价值计量且其变动计入其他综合收益的金融资产 |
| contract_assets | float | Y | 合同资产 |
| contract_liab | float | Y | 合同负债 |
| accounts_receiv_bill | float | Y | 应收票据及应收账款 |
| accounts_pay | float | Y | 应付票据及应付账款 |
| oth_rcv_total | float | Y | 其他应收款(合计) |
| fix_assets_total | float | Y | 固定资产(合计) |
| cip_total | float | Y | 在建工程(合计) |
| oth_pay_total | float | Y | 其他应付款(合计) |
| long_pay_total | float | Y | 长期应付款(合计) |
| debt_invest | float | Y | 债权投资 |
| oth_debt_invest | float | Y | 其他债权投资 |
| oth_eq_invest | float | N | 其他权益工具投资 |
| oth_illiq_fin_assets | float | N | 其他非流动金融资产 |
| oth_eq_ppbond | float | N | 其他权益工具:永续债 |
| receiv_financing | float | N | 应收款项融资 |
| use_right_assets | float | N | 使用权资产 |
| lease_liab | float | N | 租赁负债 |
| update_flag | str | Y | 更新标识 |

### 接口用法

```python
pro = ts.pro_api()

df = pro.balancesheet(ts_code='600000.SH', start_date='20180101', end_date='20180730')
```

### 本项目使用的字段

`tushare_collector.py` 中 `get_balancesheet()` 当前请求的字段：

```
ts_code, end_date, total_assets, total_liab, total_hldr_eqy_exc_min_int,
minority_int, money_cap, accounts_receiv, inventories, fix_assets,
goodwill, lt_borr, st_borr, total_cur_assets, total_cur_liab,
accounts_receiv_bill, contract_liab, adv_receipts
```

---

## 6. 利润表 (`income`)

- **接口**: `income`
- **描述**: 获取上市公司财务利润表数据
- **权限**: 用户需要至少 **2000积分** 才可以调取
- **提示**: 如需获取某一季度全部上市公司数据，请使用 `income_vip` 接口（需5000积分）

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | Y | 股票代码 |
| ann_date | str | N | 公告日期 |
| f_ann_date | str | N | 实际公告日期 |
| start_date | str | N | 公告开始日期 |
| end_date | str | N | 公告结束日期 |
| period | str | N | 报告期(每个季度最后一天的日期, 比如20171231表示年报) |
| report_type | str | N | 报告类型（同 balancesheet） |
| comp_type | str | N | 公司类型（1一般工商业 2银行 3保险 4证券） |

### 输出参数

#### 收入类

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| ts_code | str | Y | TS代码 |
| ann_date | str | Y | 公告日期 |
| f_ann_date | str | Y | 实际公告日期 |
| end_date | str | Y | 报告期 |
| report_type | str | Y | 报告类型 |
| comp_type | str | Y | 公司类型 |
| end_type | str | Y | 报告期类型 |
| basic_eps | float | Y | 基本每股收益 |
| diluted_eps | float | Y | 稀释每股收益 |
| total_revenue | float | Y | 营业总收入 |
| revenue | float | Y | 营业收入 |
| int_income | float | Y | 利息收入 |
| prem_earned | float | Y | 已赚保费 |
| comm_income | float | Y | 手续费及佣金收入 |
| n_commis_income | float | Y | 手续费及佣金净收入 |
| n_oth_income | float | Y | 其他经营净收益 |
| n_oth_b_income | float | Y | 加:其他业务净收益 |
| prem_income | float | Y | 保险业务收入 |
| out_prem | float | Y | 减:分出保费 |
| une_prem_reser | float | Y | 提取未到期责任准备金 |
| reins_income | float | Y | 其中:分保费收入 |
| n_sec_tb_income | float | Y | 代理买卖证券业务净收入 |
| n_sec_uw_income | float | Y | 证券承销业务净收入 |
| n_asset_mg_income | float | Y | 受托客户资产管理业务净收入 |
| oth_b_income | float | Y | 其他业务收入 |
| fv_value_chg_gain | float | Y | 加:公允价值变动净收益 |
| invest_income | float | Y | 加:投资净收益 |
| ass_invest_income | float | Y | 其中:对联营企业和合营企业的投资收益 |
| forex_gain | float | Y | 加:汇兑净收益 |

#### 成本与费用

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| total_cogs | float | Y | 营业总成本 |
| oper_cost | float | Y | 减:营业成本 |
| int_exp | float | Y | 减:利息支出 |
| comm_exp | float | Y | 减:手续费及佣金支出 |
| biz_tax_surchg | float | Y | 减:营业税金及附加 |
| sell_exp | float | Y | 减:销售费用 |
| admin_exp | float | Y | 减:管理费用 |
| fin_exp | float | Y | 减:财务费用 |
| assets_impair_loss | float | Y | 减:资产减值损失 |
| prem_refund | float | Y | 退保金 |
| compens_payout | float | Y | 赔付总支出 |
| reser_insur_liab | float | Y | 提取保险责任准备金 |
| div_payt | float | Y | 保户红利支出 |
| reins_exp | float | Y | 分保费用 |
| oper_exp | float | Y | 营业支出 |
| compens_payout_refu | float | Y | 减:摊回赔付支出 |
| insur_reser_refu | float | Y | 减:摊回保险责任准备金 |
| reins_cost_refund | float | Y | 减:摊回分保费用 |
| other_bus_cost | float | Y | 其他业务成本 |

#### 利润类

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| operate_profit | float | Y | 营业利润 |
| non_oper_income | float | Y | 加:营业外收入 |
| non_oper_exp | float | Y | 减:营业外支出 |
| nca_disploss | float | Y | 其中:减:非流动资产处置净损失 |
| total_profit | float | Y | 利润总额 |
| income_tax | float | Y | 所得税费用 |
| n_income | float | Y | 净利润(含少数股东损益) |
| n_income_attr_p | float | Y | 净利润(归属于母公司股东的净利润) |
| minority_gain | float | Y | 少数股东损益 |
| oth_compr_income | float | Y | 其他综合收益 |
| t_compr_income | float | Y | 综合收益总额 |
| compr_inc_attr_p | float | Y | 归属于母公司(或股东)的综合收益总额 |
| compr_inc_attr_m_s | float | Y | 归属于少数股东的综合收益总额 |
| ebit | float | Y | 息税前利润 |
| ebitda | float | Y | 息税折旧摊销前利润 |
| insurance_exp | float | Y | 保险业务支出 |
| undist_profit | float | Y | 年初未分配利润 |
| distable_profit | float | Y | 可分配利润 |
| rd_exp | float | Y | 研发费用 |
| fin_exp_int_exp | float | Y | 财务费用:利息费用 |
| fin_exp_int_inc | float | Y | 财务费用:利息收入 |

#### 利润分配

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| transfer_surplus_rese | float | Y | 盈余公积转入 |
| transfer_housing_imprest | float | Y | 住房周转金转入 |
| transfer_oth | float | Y | 其他转入 |
| adj_lossgain | float | Y | 年初利润调整 |
| withdra_legal_surplus | float | Y | 提取法定盈余公积 |
| withdra_legal_pubfund | float | Y | 提取法定公益金 |
| withdra_biz_devfund | float | Y | 提取企业发展基金 |
| withdra_rese_fund | float | Y | 提取储备基金 |
| withdra_oth_ersu | float | Y | 提取任意盈余公积金 |
| workers_welfare | float | Y | 职工奖金福利 |
| distr_profit_shrhder | float | Y | 可供股东分配的利润 |
| prfshare_payable_dvd | float | Y | 应付优先股股利 |
| comshare_payable_dvd | float | Y | 应付普通股股利 |
| capit_comstock_div | float | Y | 转作股本的普通股股利 |

#### 新准则与补充字段

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| net_after_nr_lp_correct | float | N | 扣除非经常性损益后的净利润（更正前） |
| credit_impa_loss | float | N | 信用减值损失 |
| net_expo_hedging_benefits | float | N | 净敞口套期收益 |
| oth_impair_loss_assets | float | N | 其他资产减值损失 |
| total_opcost | float | N | 营业总成本（二） |
| amodcost_fin_assets | float | N | 以摊余成本计量的金融资产终止确认收益 |
| oth_income | float | N | 其他收益 |
| asset_disp_income | float | N | 资产处置收益 |
| continued_net_profit | float | N | 持续经营净利润 |
| end_net_profit | float | N | 终止经营净利润 |
| update_flag | str | Y | 更新标识 |

### 接口用法

```python
pro = ts.pro_api()

df = pro.income(ts_code='600000.SH', start_date='20180101', end_date='20180730')
```

### 本项目使用的字段

`tushare_collector.py` 中 `get_income()` 当前请求的字段：

```
ts_code, end_date, revenue, total_revenue, oper_cost, total_cogs,
sell_exp, admin_exp, fin_exp, n_income, n_income_attr_p, minority_gain,
operate_profit, total_profit, income_tax, rd_exp, assets_impair_loss
```

---

---

## 7. 港股列表 (`hk_basic`)

- **接口**: `hk_basic`
- **描述**: 获取港股列表信息
- **权限**: 用户需要至少 **2000积分** 才可以调取
- **提示**: 单次请求即可获取全部可交易的港股列表数据

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | N | TS股票代码, e.g. 00001.HK |
| list_status | str | N | 上市状态: L-上市(默认) D-退市 P-暂停上市 |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| ts_code | str | Y | TS代码, e.g. 00001.HK |
| name | str | Y | 股票名称 |
| fullname | str | Y | 公司全称 |
| enname | str | Y | 英文名称 |
| cn_spell | str | Y | 拼音 |
| market | str | Y | 市场类别（主板等） |
| list_status | str | Y | 上市状态 |
| list_date | str | Y | 上市日期 |
| delist_date | str | Y | 退市日期 |
| trade_unit | float | Y | 交易单位（每手股数） |
| isin | str | Y | ISIN代码 |
| curr_type | str | Y | 货币类型 (HKD) |

### 接口用法

```python
pro = ts.pro_api()

# 获取全部可交易港股基础信息
df = pro.hk_basic()

# 获取单只股票信息
df = pro.hk_basic(ts_code='00700.HK',
                  fields='ts_code,name,fullname,market,list_date,enname')
```

---

## 8. 港股行情 (`hk_daily`)

- **接口**: `hk_daily`
- **描述**: 获取港股每日增量和历史行情，每日18点左右更新当日数据
- **权限**: 需单独开通权限
- **限量**: 单次最大5000条，可多次请求获取更多数据

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | N | 股票代码, e.g. 00001.HK |
| trade_date | str | N | 交易日期 (YYYYMMDD) |
| start_date | str | N | 开始日期 (YYYYMMDD) |
| end_date | str | N | 结束日期 (YYYYMMDD) |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| ts_code | str | Y | 股票代码 |
| trade_date | str | Y | 交易日期 |
| open | float | Y | 开盘价 |
| high | float | Y | 最高价 |
| low | float | Y | 最低价 |
| close | float | Y | 收盘价 |
| pre_close | float | Y | 昨收价 |
| change | float | Y | 涨跌额 |
| pct_chg | float | Y | 涨跌幅 (%) |
| vol | float | Y | 成交量 (股) |
| amount | float | Y | 成交额 (元) |

### 接口用法

```python
pro = ts.pro_api()

# 获取单只股票行情
df = pro.hk_daily(ts_code='00001.HK',
                  start_date='20190101', end_date='20190904')

# 获取某日全部港股行情
df = pro.hk_daily(trade_date='20190904')
```

---

## 9. 港股交易日历 (`hk_tradecal`)

- **接口**: `hk_tradecal`
- **描述**: 获取港股交易日历
- **权限**: 用户需要至少 **2000积分** 才可以调取
- **限量**: 单次最大2000条

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| start_date | str | N | 开始日期 (YYYYMMDD) |
| end_date | str | N | 结束日期 (YYYYMMDD) |
| is_open | str | N | 是否交易: 0-休市 1-交易 |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| cal_date | str | Y | 日历日期 |
| is_open | int | Y | 是否交易: 0-休市 1-交易 |
| pretrade_date | str | Y | 上一交易日 |

### 接口用法

```python
pro = ts.pro_api()

df = pro.hk_tradecal(start_date='20200101', end_date='20200708')
```

---

## 10. 港股利润表 (`hk_income`)

- **接口**: `hk_income`
- **描述**: 获取港股上市公司财务利润表数据
- **权限**: 需单独开通权限或 **15000积分**
- **限量**: 单次最大10000条
- **重要**: 数据采用 **行转列 (pivoted) 格式**，每行一个财务指标 (`ind_name` + `ind_value`)，而非传统的一行一期

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | Y | 股票代码, e.g. 00700.HK |
| period | str | N | 报告期 (YYYYMMDD, e.g. 20241231) |
| ind_name | str | N | 指标名称 (e.g. 营业额) — 用于筛选单个指标跨期数据 |
| start_date | str | N | 报告期开始日期 |
| end_date | str | N | 报告期结束日期 |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| ts_code | str | Y | 股票代码 |
| end_date | str | Y | 报告期 |
| name | str | Y | 股票名称 |
| ind_name | str | Y | 财务指标名称 |
| ind_value | float | Y | 财务指标值 |

### ind_name 常见取值

| ind_name | 含义 |
|----------|------|
| 营业额 | Revenue |
| 营运支出 | Operating expenses |
| 销售及分销费用 | Selling and distribution expenses |
| 行政开支 | Administrative expenses |
| 经营溢利 | Operating profit |
| 利息收入 | Interest income |
| 融资成本 | Finance costs |
| 应占联营公司溢利 | Share of associates' profit |
| 除税前溢利 | Profit before tax |
| 税项 | Tax |
| 除税后溢利 | Profit after tax |
| 少数股东损益 | Minority interests |
| 股东应占溢利 | Profit attributable to shareholders |
| 每股基本盈利 | Basic EPS |
| 每股摊薄盈利 | Diluted EPS |

### 接口用法

```python
pro = ts.pro_api()

# 获取腾讯 2024 年度利润表 (返回多行, 每行一个指标)
df = pro.hk_income(ts_code='00700.HK', period='20241231')

# 获取腾讯历史营业额数据 (返回多期同一指标)
df = pro.hk_income(ts_code='00700.HK', ind_name='营业额')
```

### 本项目使用的字段

`tushare_collector.py` 中 `HK_INCOME_MAP` 定义了 ind_name 到内部字段名的映射关系。

**注意**: 与 A 股不同，HK 利润表将指标名放在 `ind_name` 列中，需 pivot 后使用。值的单位为 HKD 元，使用时需除以 1e6 转为百万。

---

## 11. 港股资产负债表 (`hk_balancesheet`)

- **接口**: `hk_balancesheet`
- **描述**: 获取港股上市公司资产负债表数据
- **权限**: 需单独开通权限或 **15000积分**
- **限量**: 单次最大10000条
- **重要**: 数据采用 **行转列 (pivoted) 格式**，每行一个财务指标 (`ind_name` + `ind_value`)

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | Y | 股票代码, e.g. 00700.HK |
| period | str | N | 报告期 (YYYYMMDD) |
| ind_name | str | N | 指标名称 (e.g. 应收帐款) |
| start_date | str | N | 报告期开始日期 |
| end_date | str | N | 报告期结束日期 |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| ts_code | str | Y | 股票代码 |
| name | str | Y | 股票名称 |
| end_date | str | Y | 报告期 |
| ind_name | str | Y | 财务指标名称 |
| ind_value | float | Y | 财务指标值 |

### ind_name 常见取值

**资产类**:

| ind_name | 含义 |
|----------|------|
| 现金及等价物 | Cash and equivalents |
| 应收帐款 | Accounts receivable |
| 存货 | Inventories |
| 流动资产合计 | Total current assets |
| 物业厂房及设备 | Property, plant and equipment |
| 无形资产 | Intangible assets |
| 在建工程 | Construction in progress |
| 联营公司权益 | Interest in associates |
| 递延税项资产 | Deferred tax assets |
| 总资产 | Total assets |

**负债类**:

| ind_name | 含义 |
|----------|------|
| 应付帐款 | Accounts payable |
| 应付票据 | Notes payable |
| 短期贷款 | Short-term borrowings |
| 递延收入(流动) | Deferred income (current) |
| 流动负债合计 | Total current liabilities |
| 长期贷款 | Long-term borrowings |
| 递延税项负债 | Deferred tax liabilities |
| 应付票据(非流动) | Notes payable (non-current) |
| 总负债 | Total liabilities |

**权益类**:

| ind_name | 含义 |
|----------|------|
| 股东权益 | Shareholders' equity |
| 少数股东权益 | Minority interests |

### 接口用法

```python
pro = ts.pro_api()

# 获取腾讯 2024 年度资产负债表
df = pro.hk_balancesheet(ts_code='00700.HK', period='20241231')
```

### 本项目使用的字段

`tushare_collector.py` 中 `HK_BALANCE_MAP` 定义了 ind_name 到内部字段名的映射关系。

---

## 12. 港股现金流量表 (`hk_cashflow`)

- **接口**: `hk_cashflow`
- **描述**: 获取港股上市公司现金流量表数据
- **权限**: 需单独开通权限或 **15000积分**
- **限量**: 单次最大10000条
- **重要**: 数据采用 **行转列 (pivoted) 格式**，每行一个财务指标 (`ind_name` + `ind_value`)

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | Y | 股票代码, e.g. 00700.HK |
| period | str | N | 报告期 (YYYYMMDD) |
| ind_name | str | N | 指标名称 (e.g. 新增借款) |
| start_date | str | N | 报告期开始日期 |
| end_date | str | N | 报告期结束日期 |

### 输出参数

| 名称 | 类型 | 默认显示 | 描述 |
|------|------|----------|------|
| ts_code | str | Y | 股票代码 |
| end_date | str | Y | 报告期 |
| name | str | Y | 股票名称 |
| ind_name | str | Y | 财务指标名称 |
| ind_value | float | Y | 财务指标值 |

### ind_name 常见取值

**经营活动**:

| ind_name | 含义 |
|----------|------|
| 经营业务现金净额 | Net cash from operating activities |
| 已付税项 | Tax paid |
| 折旧及摊销 | Depreciation and amortization |

**投资活动**:

| ind_name | 含义 |
|----------|------|
| 购建无形资产及其他资产 | Purchase of intangible/other assets (CapEx) |
| 收回投资所得现金 | Cash received from disposal of investments |
| 投资业务现金净额 | Net cash from investing activities |

**融资活动**:

| ind_name | 含义 |
|----------|------|
| 已付股息(融资) | Dividends paid (financing) |
| 回购股份 | Share buyback |
| 融资业务现金净额 | Net cash from financing activities |

### 接口用法

```python
pro = ts.pro_api()

# 获取腾讯 2024 年度现金流量表
df = pro.hk_cashflow(ts_code='00700.HK', period='20241231')
```

### 本项目使用的字段

`tushare_collector.py` 中 `HK_CASHFLOW_MAP` 定义了 ind_name 到内部字段名的映射关系。

---

## 13. 港股财务指标 (`hk_fina_indicator`)

- **接口**: `hk_fina_indicator`
- **描述**: 获取港股上市公司财务指标数据，每次请求最多返回200条记录
- **权限**: 需单独开通权限或 **15000积分**
- **限量**: 单次最大200条
- **重要**: 此接口为 **结构化字段** 格式（与 A 股 `fina_indicator` 类似），不使用 `ind_name/ind_value` 的行转列格式

### 输入参数

| 名称 | 类型 | 必选 | 描述 |
|------|------|------|------|
| ts_code | str | Y | 股票代码, e.g. 00700.HK |
| period | str | N | 报告期 (YYYYMMDD) |
| report_type | str | N | 报告类型: Q1, Q2, Q3, Q4 |
| start_date | str | N | 报告开始日期 |
| end_date | str | N | 报告结束日期 |

### 输出参数

#### 每股指标

| 名称 | 类型 | 描述 |
|------|------|------|
| basic_eps | float | 基本每股收益 (元) |
| diluted_eps | float | 稀释每股收益 (元) |
| eps_ttm | float | 滚动每股收益 (元) |
| bps | float | 每股净资产 (元) |
| dps_hkd | float | 每股股息 (HKD) |

#### 盈利能力

| 名称 | 类型 | 描述 |
|------|------|------|
| roe_avg | float | 平均净资产收益率 (%) |
| roa | float | 总资产报酬率 (%) |
| gross_profit_ratio | float | 毛利率 (%) |
| net_profit_ratio | float | 净利率 (%) |

#### 增长率

| 名称 | 类型 | 描述 |
|------|------|------|
| operate_income_yoy | float | 营收同比增长率 (%) |
| holder_profit_yoy | float | 归属股东净利润同比增长率 (%) |

#### 资产负债

| 名称 | 类型 | 描述 |
|------|------|------|
| debt_asset_ratio | float | 资产负债率 (%) |
| current_ratio | float | 流动比率 (倍) |

#### 估值与分红

| 名称 | 类型 | 描述 |
|------|------|------|
| pe_ttm | float | 滚动市盈率 |
| pb_ttm | float | 滚动市净率 |
| total_market_cap | float | 总市值 |
| hksk_market_cap | float | 港股通市值 |
| divi_ratio | float | 分红率 (%) |
| dividend_rate | float | 股息率 (%) |

### 接口用法

```python
pro = ts.pro_api()

# 获取腾讯 2024 年度财务指标
df = pro.hk_fina_indicator(ts_code='00700.HK', period='20241231')

# 指定返回字段
df = pro.hk_fina_indicator(ts_code='00700.HK',
                            fields='ts_code,end_date,roe_avg,gross_profit_ratio,'
                                   'net_profit_ratio,debt_asset_ratio,'
                                   'pe_ttm,pb_ttm,operate_income_yoy,holder_profit_yoy,'
                                   'bps,total_market_cap,hksk_market_cap')
```

### 本项目使用的字段

`_get_basic_info_hk()` 请求:
```
ts_code,end_date,pe_ttm,pb_ttm,total_market_cap,hksk_market_cap
```

`_get_fina_indicators_hk()` 请求:
```
ts_code,end_date,roe_avg,gross_profit_ratio,net_profit_ratio,debt_asset_ratio,
pe_ttm,pb_ttm,operate_income_yoy,holder_profit_yoy,bps,total_market_cap,hksk_market_cap
```

`_get_dividends_hk()` 请求:
```
ts_code,end_date,dps_hkd,divi_ratio
```

---

### HK vs A-Share API 数据格式对比

| 维度 | A股 (income/balancesheet/cashflow) | 港股 (hk_income/hk_balancesheet/hk_cashflow) |
|------|-------------------------------------|----------------------------------------------|
| 数据格式 | **结构化字段** — 每个指标一列 | **行转列 (pivoted)** — `ind_name` + `ind_value` |
| 指标名称 | 英文字段名 (e.g. `n_income_attr_p`) | 中文字符串 (e.g. `股东应占溢利`) |
| 报告类型 | `report_type` 区分合并/母公司报表 | 默认合并报表，无母公司报表 |
| 金额单位 | 人民币 (元) | 港币 HKD (元) |

| 维度 | A股 (fina_indicator) | 港股 (hk_fina_indicator) |
|------|---------------------|--------------------------|
| 数据格式 | 结构化字段 | 结构化字段 (相同风格) |
| 字段名称 | e.g. `grossprofit_margin` | e.g. `gross_profit_ratio` |
| 估值字段 | 无 (需从 `daily_basic` 获取) | 内含 `pe_ttm`, `pb_ttm`, `total_market_cap` |
| 分红字段 | 无 (需从 `dividend` 获取) | 内含 `dps_hkd`, `divi_ratio`, `dividend_rate` |

---

## 美股接口

### us_basic — 美股基本信息
| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 (如 AAPL) |
| name | str | 公司名称 |
| enname | str | 英文名称 |
| market | str | 交易所 (NASDAQ/NYSE) |
| list_date | str | 上市日期 |

### us_daily — 美股日线行情
| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| trade_date | str | 交易日期 |
| open/high/low/close | float | OHLC |
| vol | float | 成交量 |
| amount | float | 成交额 |
| pe | float | 市盈率 |
| pb | float | 市净率 |
| total_mv | float | 总市值（百万美元） |

### us_income — 美股利润表（行项目格式）
格式: ts_code, end_date, ind_name, ind_value
常见 ind_name: 营业收入, 营业成本, 毛利, 营销费用, 研发费用, 经营利润, 净利润, 归属于母公司净利润, 基本每股收益, 稀释每股收益

### us_balancesheet — 美股资产负债表（行项目格式）
格式: ts_code, end_date, ind_name, ind_value
常见 ind_name: 现金及等价物, 应收帐款, 存货, 流动资产合计, 固定资产, 无形资产, 总资产, 应付帐款, 短期贷款, 流动负债合计, 长期贷款, 总负债, 股东权益, 少数股东权益

### us_cashflow — 美股现金流量表（行项目格式）
格式: ts_code, end_date, ind_name, ind_value
常见 ind_name: 经营活动现金净额, 投资活动现金净额, 筹资活动现金净额, 资本支出, 折旧及摊销, 已付股息

### us_fina_indicator — 美股财务指标（结构化格式）
| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| end_date | str | 报告期 |
| roe_avg | float | 平均ROE (%) |
| gross_profit_ratio | float | 毛利率 (%) |
| net_profit_ratio | float | 净利率 (%) |
| debt_asset_ratio | float | 资产负债率 (%) |
| pe_ttm | float | PE (TTM) |
| pb_ttm | float | PB |
| operate_income_yoy | float | 营收同比 (%) |
| holder_profit_yoy | float | 净利润同比 (%) |
| bps | float | 每股净资产 (USD) |
| total_market_cap | float | 总市值（百万美元） |

---

*龟龟投资策略 v1.0 | Tushare API 参考文档*
