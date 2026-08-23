"""Turtle Investment Framework - Tushare field mapping constants.

All *_MAP dicts used by TushareClient mixins live here.
"""

_VIP_MAP = {
    "income": "income_vip",
    "balancesheet": "balancesheet_vip",
    "cashflow": "cashflow_vip",
    "fina_indicator": "fina_indicator_vip",
    "fina_mainbz": "fina_mainbz_vip",
    "forecast": "forecast_vip",
    "express": "express_vip",
}

# HK line-item field mappings: Tushare column name → HK ind_name (Chinese)
HK_INCOME_MAP = {
    "revenue": "营业额",
    "oper_cost": "营运支出",
    "sell_exp": "销售及分销费用",
    "admin_exp": "行政开支",
    "operate_profit": "经营溢利",
    "invest_income": "应占联营公司溢利",
    "int_income": "利息收入",
    "finance_exp": "融资成本",
    "total_profit": "除税前溢利",
    "income_tax": "税项",
    "n_income": "除税后溢利",
    "n_income_attr_p": "股东应占溢利",
    "minority_gain": "少数股东损益",
    "basic_eps": "每股基本盈利",
    "diluted_eps": "每股摊薄盈利",
}

HK_BALANCE_MAP = {
    "money_cap": "现金及等价物",
    "accounts_receiv": "应收帐款",
    "inventories": "存货",
    "total_cur_assets": "流动资产合计",
    "lt_eqt_invest": "联营公司权益",
    "fix_assets": "物业厂房及设备",
    "cip": "在建工程",
    "intang_assets": "无形资产",
    "total_assets": "总资产",
    "acct_payable": "应付帐款",
    "notes_payable": "应付票据",
    "contract_liab": "递延收入(流动)",
    "st_borr": "短期贷款",
    "total_cur_liab": "流动负债合计",
    "lt_borr": "长期贷款",
    "bond_payable": "应付票据(非流动)",
    "total_liab": "总负债",
    "defer_tax_assets": "递延税项资产",
    "defer_tax_liab": "递延税项负债",
    "total_hldr_eqy_exc_min_int": "股东权益",
    "minority_int": "少数股东权益",
}

HK_CASHFLOW_MAP = {
    "n_cashflow_act": "经营业务现金净额",
    "n_cashflow_inv_act": "投资业务现金净额",
    "n_cash_flows_fnc_act": "融资业务现金净额",
    "c_pay_acq_const_fiolta": "购建无形资产及其他资产",
    "depr_fa_coga_dpba": "折旧及摊销",
    "c_pay_dist_dpcp_int_exp": "已付股息(融资)",
    "c_paid_for_taxes": "已付税项",
    "c_recp_return_invest": "收回投资所得现金",
}

# US line-item field mappings: Tushare column name → US ind_name (Chinese)
US_INCOME_MAP = {
    "revenue": "营业收入",
    "oper_cost": "营业成本",
    "gross_profit": "毛利",
    "sell_exp": "营销费用",
    "rd_exp": "研发费用",
    "operate_profit": "经营利润",
    "n_income": "净利润",
    "n_income_attr_p": "归属于母公司净利润",
    "basic_eps": "基本每股收益",
    "diluted_eps": "稀释每股收益",
}

US_BALANCE_MAP = {
    "money_cap": "现金及等价物",
    "accounts_receiv": "应收帐款",
    "inventories": "存货",
    "total_cur_assets": "流动资产合计",
    "fix_assets": "固定资产",
    "intang_assets": "无形资产",
    "total_assets": "总资产",
    "acct_payable": "应付帐款",
    "st_borr": "短期贷款",
    "total_cur_liab": "流动负债合计",
    "lt_borr": "长期贷款",
    "total_liab": "总负债",
    "defer_tax_assets": "递延税项资产",
    "defer_tax_liab": "递延税项负债",
    "total_hldr_eqy_exc_min_int": "股东权益",
    "minority_int": "少数股东权益",
    "goodwill": "商誉",
    "trad_asset": "交易性金融资产",
}

US_CASHFLOW_MAP = {
    "n_cashflow_act": "经营活动现金净额",
    "n_cashflow_inv_act": "投资活动现金净额",
    "n_cash_flows_fnc_act": "筹资活动现金净额",
    "c_pay_acq_const_fiolta": "资本支出",
    "depr_fa_coga_dpba": "折旧及摊销",
    "c_pay_dist_dpcp_int_exp": "已付股息",
}

# yfinance field mappings: yfinance index name → Tushare column name
# Both CamelCase and space-separated variants included (format varies by yfinance version)
_YF_INCOME_MAP = {
    "Total Revenue": "revenue", "TotalRevenue": "revenue",
    "Cost Of Revenue": "oper_cost", "CostOfRevenue": "oper_cost",
    "Selling General And Administration": "admin_exp",
    "SellingGeneralAndAdministration": "admin_exp",
    "Operating Income": "operate_profit", "OperatingIncome": "operate_profit",
    "Interest Expense": "finance_exp", "InterestExpense": "finance_exp",
    "Pretax Income": "total_profit", "PretaxIncome": "total_profit",
    "Tax Provision": "income_tax", "TaxProvision": "income_tax",
    "Net Income": "n_income", "NetIncome": "n_income",
    "Net Income Common Stockholders": "n_income_attr_p",
    "NetIncomeCommonStockholders": "n_income_attr_p",
    "Basic EPS": "basic_eps", "BasicEPS": "basic_eps",
    "Diluted EPS": "diluted_eps", "DilutedEPS": "diluted_eps",
    "Gross Profit": "gross_profit", "GrossProfit": "gross_profit",
    "Research And Development": "rd_exp", "ResearchAndDevelopment": "rd_exp",
}

_YF_BALANCE_MAP = {
    "Cash And Cash Equivalents": "money_cap",
    "CashAndCashEquivalents": "money_cap",
    "Accounts Receivable": "accounts_receiv", "AccountsReceivable": "accounts_receiv",
    "Inventory": "inventories",
    "Current Assets": "total_cur_assets", "CurrentAssets": "total_cur_assets",
    "Investments And Advances": "lt_eqt_invest",
    "Net PPE": "fix_assets", "NetPPE": "fix_assets",
    "Goodwill And Other Intangible Assets": "intang_assets",
    "Total Assets": "total_assets", "TotalAssets": "total_assets",
    "Accounts Payable": "acct_payable", "AccountsPayable": "acct_payable",
    "Current Debt": "st_borr", "CurrentDebt": "st_borr",
    "Current Liabilities": "total_cur_liab", "CurrentLiabilities": "total_cur_liab",
    "Long Term Debt": "lt_borr", "LongTermDebt": "lt_borr",
    "Total Liabilities Net Minority Interest": "total_liab",
    "Stockholders Equity": "total_hldr_eqy_exc_min_int",
    "StockholdersEquity": "total_hldr_eqy_exc_min_int",
    "Minority Interest": "minority_int", "MinorityInterest": "minority_int",
    "Goodwill": "goodwill",
    "Other Short Term Investments": "trad_asset", "OtherShortTermInvestments": "trad_asset",
}

_YF_CASHFLOW_MAP = {
    "Operating Cash Flow": "n_cashflow_act", "OperatingCashFlow": "n_cashflow_act",
    "Investing Cash Flow": "n_cashflow_inv_act", "InvestingCashFlow": "n_cashflow_inv_act",
    "Financing Cash Flow": "n_cash_flows_fnc_act", "FinancingCashFlow": "n_cash_flows_fnc_act",
    "Capital Expenditure": "c_pay_acq_const_fiolta", "CapitalExpenditure": "c_pay_acq_const_fiolta",
    "Depreciation And Amortization": "depr_fa_coga_dpba",
    "DepreciationAndAmortization": "depr_fa_coga_dpba",
    "Common Stock Dividend Paid": "c_pay_dist_dpcp_int_exp",
    "Income Tax Paid Supplemental Data": "c_paid_for_taxes",
    "Sale Of Investment": "c_recp_return_invest",
}
