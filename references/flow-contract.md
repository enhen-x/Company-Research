# 统一调研流水线契约

本文件是 `company-research-v3` 的执行契约，解决历史模板、脚本入口和人工判断点不一致的问题。除特殊行业适配外，每个批次都必须按同一条链路执行，不在批次目录新增临时脚本。

## 1. 唯一执行链

```text
research_pipeline.py
  B1 解析/立项/复制模板脚本
  B2 探测数据源/拉取数据/记录拉取清单
  B3 三表审计/生成审计报告
  B3.5 financial_health_check.py 生成本期财报体检证据
  B3.6 chart_periods.py 识别最新实际财报，生成图表最新期数据.json
        ↓
Agent 只补充 input/*.json、input/判断记录.md，并按 report-template.md 写唯一主报告 MD
        ↓
gate_all.py 每次启动建立新run_id与RUNNING账本，校验豁免及SOTP状态；
先做期间输入预检和报告模板门，再调用 analyze_charts.py 生成固定图号 PNG + 离线 Plotly HTML；
调用 md_to_html.py 从 MD 生成主报告 HTML，执行完整G22/G8-PERIOD/G8/G9/SOTP门控
```

### 固定入口

```powershell
python scripts/research_pipeline.py "调研 <公司名或代码>" --root "<工作区>"
python scripts/gate_all.py --dir . --report reports/<公司>_<代码>_分析报告.md
```

`report_to_html.py` 只服务 `shared/qualitative/` 的旧版 `qualitative_report.md` 仪表盘，不得用于统一主报告。
单独检查现有产物时用 `gate_all.py --check-only`。完整成稿默认重建图表和 HTML；图表输入固定为 `input/运营补充数据.json`，图表数据日期优先取行情 CSV 最后日期。

必须等待进程退出，查本轮 `reports/流水线执行状态.json`：各阶段开始/结束时间、真实退出码、耗时、输入/代码/正文及产物SHA-256齐全。`status=PASS` 且 `delivery_ready=true` 才表示本轮技术交付可用；`build_completed=true` / `fully_rebuilt=true` 仅表示本轮重新构建全部产物。默认完整重建；可用 `--incremental` 在输入、代码、正文以及全部既有产物哈希均匹配时复用图表与HTML，质量门仍重跑，账本记录来源run_id及REUSED，不能声称本轮全部重建。任何失败使后续阶段BLOCKED，运行中输入变化亦失败。`--check-only`、`--legacy` 不提供交付或完整构建声明。同批次成稿由系统锁排斥并发，异常退出自动释放。每阶段默认硬超时300秒、全流程1200秒、每10秒心跳，可用 `--stage-timeout` / `--total-timeout` / `--heartbeat` 调整；超时终止进程树并保留本轮失败状态。G8横轴与布局检查共用最终figure，保留完整检查规则；分图耗时写入 `reports/图表检查计时.json`。

B2主入口与补拉命令共用 `fetch_with_fallback.py` → `fetch_sources.py` → `bounded_fetch.py`。单次默认硬超时30秒、总尝试2次（最多3次）、整批拉取预算180秒、失败TTL900秒、成功TTL3600秒；成功复用须核股票、报告期、来源实现及文件哈希，缓存键包含参数与实现版本。`--force-refresh` 可显式重试，`--fetch-budget` / `--success-ttl` 可调预算与有效期；预算耗尽后记录缺口并继续后续降级步骤。失败保留旧文件时清单标记失败及 `old_file_preserved`，审计必须保留WARN，不能当更新成功。拉取清单最多保留20次运行摘要。补拉股东需指定并确认报告期。

`input/图表豁免.json` 只接受 `{"豁免":[{"图":"图16","原因":"可核实的具体原因"}]}`；`input/sotp_触发.json` 必须有布尔字段 `enabled`，由 `sotp_valuation.py --detect-only` 生成，人工覆盖须在判断记录中说明。缺失或无效的 SOTP 状态使成稿门 FAIL。运行成稿门之前先完成 SOTP 检测。

财务图的最新期从三表独立识别，不能拿行情日期代替财报覆盖。具体见 `chart-period-contract.md`。

财务组合图（图01、02、04、05、12、15）及交互财务面板的增长折线**只保留年度同比**，取消全部季度同比和季度环比线（包括Q3）；以相邻完整财年计算，率类用年度变动百分点。最新季度实际仍整合在原图季度柱中，未完年度不绘制全年柱或年度同比点。静态图、交互图、标题、图例和图注遵守同一规则；正文季度比较表保留。G8-PERIOD与G8-RENDER检查实际折线的条数、年份、单位和值，拒绝季度增长线和伪全年点；后续生成与复验必须使用skill当前模板。

显示金额以`report-template.md`为准：对外正文、表格、图注及阅读台账换算为亿元／万元，自适应单位逐格写明；原始数据与机器JSON保留原尺度。流水线复制`chart_numbers.py`共享模块，全部标准图和体检图在测量布局前格式化数字注释（最多2位小数），G8/G22复核实际文字。模板门与HTML入口发现旧金额单位即拒绝，不自动只替换单位。

## 2. 唯一产物契约

| 层 | 唯一事实/产物 | 规则 |
|---|---|---|
| 原始数据 | `data/*.csv`、`data/拉取清单.json` | 只由 B2 写入，不在报告中手改数字 |
| 审计 | `data/审计报告.html`、`data/审计报告.json` | HTML供阅读，JSON供门控和复算；WARN不得静默消除 |
| 体检 | `reports/本期财报体检.json` | JSON是唯一数字事实源，摘要和成文框架只供写作 |
| 判断 | `input/判断记录.md`、适配配置 JSON | 所有人工选择必须记录理由、证据、影响和复核条件 |
| 研究专题 | `input/研究模型.json` → `reports/研究模型_输出.json` | 行业选型、指引版本、订单桥、预测驱动、反方及决策集中复算；事实引用与假设分开，不新建平行主报告 |
| 预测复验 | 首次 `input/预测基线.json`、当前 `data/验证快照.json` | `verification.py --freeze` 仅创建一次基线，不覆盖；后续按同口径观察值复验，固定文件覆盖更新，不生成逐次副本 |
| 图表 | `reports/图表/图01~图18*.png`、`reports/<公司>_<代码>_图表.html` | 只能由模板 `analyze_charts.py` 生成 |
| 主报告 | `reports/<公司>_<代码>_分析报告.md/.html` | MD是正文唯一源文件；HTML必须由 `md_to_html.py` 生成 |
| 质量门 | `reports/流水线执行状态.json`、实际运行日志 | 任一FAIL不得标记构建完成；`technical_pass`只代表技术门。专题`STRUCTURE_CHECKED`仅表示计算与原小节引用检查，人工研究判断始终`NOT_ASSESSED`；WARN进入交付清单和报告限制 |

存在 `input/研究模型.json` 时成稿门自动复算并检查其与原小节的 `report_bindings`；`--require-research` 额外要求全部适用模块完整。缺少模型的历史批次可进行技术回放，但不能称为完成新版研究。直接 `research_topic_qc.py --check-only` 只验证已保存结果，输入、实现或正文变化都须重算，不会写文件。未知行业或缺披露保留INCOMPLETE，不以零值补齐。19类行业配置是方法选择与禁用规则；尚无专用数值引擎的方法须补外部可追溯计算，不能宣称已自动估值。

`research_pipeline.py --sync-scripts <批次>` 只同步当前模板脚本；常规立项与同步均保留已有人工输入、正文及清单内容，同内容文件不改写。图表豁免在构图前生效，明确不适用的图不消耗构图时间；豁免图存在旧PNG时报告冲突，须审阅并处理旧产物后重跑，脚本不删除用户文件。

## 3. 人工判断点（固定七项）

Agent 可以判断，但不得临时改变框架或新增脚本；每项写入 `input/判断记录.md`：

1. **证券身份**：公司名、市场、代码和最新报告期；无法确认则停止。
2. **行业适用性**：行业成本—价格图、存货专项、金融机构适配；不适用必须写理由，禁止用假数据填图。
3. **分部与单位经济学**：披露不足时选择“缺失/合并代理/可靠补充”，并标记估计口径。
4. **预测假设**：量、价、成本、费用、税率、股本、三情景概率和跟踪指标；每项必须有历史锚。
5. **龟龟口径**：M、AA、G、k、周期修正和 Rf；必须引用计算输出，不能手算替换。
6. **SOTP触发**：由检测脚本初判，Agent确认是否存在多估值锚；确认结果写入 `input/sotp_触发.json`。
7. **最终决策**：市场/券商轨与龟龟轨分别给出评级、目标价、目标买入价和仓位；冲突时遵守双轨句式，不得折中成单一买入结论。

## 4. 冲突裁决顺序

发生不同文件或不同模块口径冲突时，按以下优先级裁决：

1. `references/report-template.md` v3（主报告结构）；
2. 本文件（执行链和产物）；
3. `references/framework.md` D0/D1及G1-G22；
4. skill `scripts/` 当前模板脚本的机器输出；
5. 其他旧模板、案例和 `report_to_html.py` 仅作历史参考。

冲突不能自动裁决时，暂停成稿并记录为 WARN；不得在批次内新建同功能脚本绕过门控。

## 5. 版本和复验

模板脚本只从 skill `scripts/` 复制。方法改进先修改 skill 模板，再在新批次复制；批次脚本不接受孤立修补。每批次 `scripts/复制清单.json` 记录来源、复制时间和 SHA-256；`交付清单.md` 记录成稿门的执行结果。
