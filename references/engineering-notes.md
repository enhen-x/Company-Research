# 工程与运行环境笔记（Engineering Notes）

> 目的：沉淀跨项目复用的工程规则，防止重复踩坑。本文件是"事故记录 + 规则清单"，
> 与 data-source-notes.md（数据源）互补。规则均来自实盘运行（水星家纺 603365 全流程 2026-08）。
> **适用环境**：Windows 11 / PowerShell 5.1 / Python 3.x / akshare + 东财 + 腾讯源。

## 0. 三条铁律（最高优先级）

1. **任何 ≥3 行的 Python 一律写正式脚本到项目 `scripts/` 目录，禁止 PowerShell 内联 `python -c "..."`**
   ——内联引号转义已造成 2 次事故（f-string 嵌套双引号 SyntaxError，调试中断）。
2. **运行任何脚本前先读其头部文档**：输入 JSON 字段定义、flag 语义（`--config`=输入路径、`--json`=输出到 stdout）、输出位置。禁止凭记忆填字段。
3. **计算以脚本输出 JSON 为唯一真值**：报告数字从 JSON 输出复制，禁止手算/口头口径；成稿前做"报告↔JSON 逐字段核对"（G7 门控）。`--json` 模式 stdout 为纯 JSON，人类可读文本走 stderr。

## 1. PowerShell 命令层（PS 5.1 + 中文环境）

| 坑 | 机制 | 解决规则 |
|----|------|---------|
| 内联 Python 引号转义失败 | PS 5.1 无引号保护层级，Python f-string 嵌套引号必炸 | 见铁律 1；调试用 `scripts/debug_*.py`，完事删除或合并 |
| 无 `&&` / `\|\|` 链式 | PS 5.1 语言特性缺失（是脚本、不是 CLI） | `cmd1; if ($?) { cmd2 }`；无条件链用 `;` |
| 无 `??` / `?.` / 三元 | 同上 | 显式 `if/else` 或 `$null -eq` 判断 |
| `2>&1` 重定向 native stderr | 每行 stderr 被包成 ErrorRecord，$? 误判失败 | 不重定向 stderr；工具已自行捕获 |
| `Set-Content`/`Out-File` 默认 ANSI(GBK)/UTF-16 | 跨工具（Python/pandas 默认 utf-8）读取乱码 | 写文件一律显式 `-Encoding utf8` |
| `ConvertFrom-Json` 返回 PSCustomObject | 无 `-AsHashtable`，误当哈希表取键得 $null | 用 `$_.字段名` 属性访问 |
| 控制台代码页 936 | 中文 OK；`⚠️ ✅ ↑` 等扩展符号可能 UnicodeEncodeError | 脚本 print 只用中文/ASCII；确需符号设 `PYTHONIOENCODING=utf-8` |
| `Set-Content -Encoding utf8` 写 BOM（2026-08-15 实测） | PS 5.1 的 `-Encoding utf8` 输出带 BOM 的 UTF-8，JSON/calc 脚本解析失败 | 写无 BOM UTF-8 一律 `[System.IO.File]::WriteAllText($p, $c, [System.Text.UTF8Encoding]::new($false))`（.NET 方法），禁止 `Set-Content/Out-File` 写 JSON/脚本 |
| 中文路径经 stdin 管道传 Python 乱码（2026-08-15 实测） | `$py = @'...'@ \| python -` 中内嵌 `C:\Users\小林\...` 被解码为 `??`，路径失效 | 中文路径写进 .py 脚本文件（UTF-8 无 BOM）再 `python 脚本.py` 运行；或改在 PowerShell 内用 .NET 完成文件操作 |
| Markdown 表格追加行时空行断裂（2026-08-15 实测） | 向 `财报更新验证.md` 追加数据行时在分隔行后留空行，数据行被挤出表格（渲染为普通段落） | 追加行紧贴分隔行/上一数据行，禁止插入空行；改后可用 pandoc 渲染数 <tr> 验证（表头+数据行数 = 记录数+1） |

## 2. Python 文件 I/O 层（已统一，维持即可）

| 场景 | 规则 | 原因 |
|------|------|------|
| CSV 读/写 | `encoding="utf-8-sig"` | 东财导出带 BOM；Excel 打开兼容 |
| JSON 读 | `encoding="utf-8"` | 无 BOM |
| JSON 写 | `json.dumps(ensure_ascii=False, indent=2)` + `write_text(..., encoding="utf-8")` | 中文可读、可 diff |
| 路径定位 | `ROOT = Path(__file__).resolve().parents[1]` | 中文路径实测正常；**禁止硬编码绝对路径** |
| matplotlib | `matplotlib.use("Agg")` + 字体 fallback（Microsoft YaHei/SimHei/SimSun）+ `axes.unicode_minus=False` | Agg 无 GUI；否则中文方块/负号变方块 |
| 长命令 | >2-3 行逻辑不进命令行 | 见铁律 1 |

## 3. 依赖与接口层

| 坑 | 事故 | 规则 |
|----|------|------|
| akshare 接口漂移 | 1.18.84 移除 `stock_shareholder_top10_em`，改用 `stock_gdfx_top_10_em` | 接口失败先查现状再改代码；每次调用记入 `拉取清单.json`（G4 门控） |
| 东财 SSL 异常 | 财报接口握手失败 | 固定降级链：东财→新浪→腾讯→data_pack 提取→WebSearch→标注缺失；probe_sources.py 探测可用源 |
| 数据包过期 | data_pack_market.md >7 天 | 全量重采或 `--refresh-market` 只刷关键节 |

## 4. 工具/流程层

| 坑 | 事故 | 规则 |
|----|------|------|
| `--json` 误当路径参数 | calc_penetration_return.py `--json` 是输出 flag（stdout），`--config` 才是输入路径 | 读脚本头部文档确认 flag 语义（铁律 2） |
| `--json` 纯 JSON 契约 | calc_penetration_return.py 用 `--json` 时 stdout 只出纯 JSON（可 `> 穿透回报率_输出.json` 供机器解析），人类可读文本走 stderr | stdout 有杂音会污染 JSON；`--json` 后禁止 `2>&1`（PS 5.1 把 stderr 包成 ErrorRecord），否则 JSON 文件混入杂讯 |
| 诊断打印未过滤口径 | 资产负债表调试打印含全部报告期，未过滤 `month==12` 曾误导判断 | 诊断脚本先过滤报告期再展示；结论以输出 JSON 为准 |
| 报告↔JSON 数字脱钩 | §6.1 残留旧口径（H=84.2/OE=416.4）与脚本输出（H=101.6/OE=398.7）不一致 | 见铁律 3；成稿前逐字段核对 |
| 图表引用断链 | MD `![图NN](图表/图NN_*.png)` 由 render_report.py 替换为 base64 内嵌 | 生成后验证 HTML 无残留 `![`，计数与 PNG 一致 |

## 5. 验证链（交付前必跑）

1. 报告 ↔ 脚本输出 JSON 逐字段一致（G7）
2. HTML 无残留图引用，base64 计数 = PNG 数
3. 交付清单.md 逐项勾选，缺项必须说明（G12 脚本位置核验）
4. 图表编号连续（analyze_charts.py 全局计数器），每图有编号/标题/数据日期/来源

## 6. 脚本纪律（与 SKILL.md §10.1 / G12 一致）

- 所有 .py/.ipynb/.bat/.ps1 必须位于项目 `scripts/` 内；禁止在 `G:\理财\个股分析\` 根目录或项目外创建
- 调试脚本用 `scripts/debug_*.py`，完成后删除或合并入正式脚本
- 项目完成后 scripts/ 作为复验可复现资产保留


## 7. research_pipeline B1 修复记录（2026-08-21，小商品城批次校准）

| 问题 | 修复 |
|------|------|
| 名称/代码解析仅依赖 akshare 股票列表（底层走 SSE/SZSE/BSE，SSL 故障时全挂，`调研 小商品城`/`调研 600415` 均失败） | resolve_code/resolve_name 降级链：akshare 全列表（精确+包含）→ 腾讯智能提示 smartbox.gtimg.cn/s3（实测可用，返回 ASCII+字面 \uXXXX 转义，需 unicode_escape 解码）→ 腾讯实时行情 qt.gtimg.cn（代码→名称取字段[1]） |
| B1 仅 mkdir scripts/ 却未复制模板脚本，交付清单却标注"已复制"（实测 scripts/ 为空） | 新增 copy_template_scripts()：从本 skill scripts/（三技能合并后同目录；保留 CODEX_HOME / ~/.codex/skills / GUIGUI_SKILL_DIR 外部探测作为向后兼容）自动复制 13 个模板脚本（verification/extract_financials/analyze_charts/chart_qc/format_qc/gate_all/fetch_peers/fetch_supplement/fetch_industry_cost_price/probe_sources/fetch_with_fallback/calc_penetration_return/build_penetration_input），写 scripts/复制清单.json；交付清单 7/8/10 行按实际状态动态标记 |


## 8. 模板回归测试（template_regression.py，2026-08-21 新增）

**目的**：把「每项目 patch 渲染 bug」消灭在 skill 层。analyze_charts.py / chart_qc.py 模板修改或
发布前，必须跑一轮全图 QC 自检。

**用法**（在 skill scripts/ 目录执行）：
```
python template_regression.py              # 合成项目(不联网) -> 出图16张 -> 报告 -> chart_qc
python template_regression.py --selfcheck  # 负向自检：注入旧 bug，断言 chart_qc FAIL（证明门控有牙）
python template_regression.py --keep       # 保留合成项目人工复核
python template_regression.py --out <dir>  # 指定输出目录（默认系统临时目录）
```
退出码：0=通过；1=存在 FAIL；2=运行错误。

**机制**：合成数据刻意复现历史踩坑点（16 年年报触发 12 年窗口、2022 毛利率/净利率接近致标注重叠、
R*<II 负 KK 多行标注越界、lambda=0 平线敏感性、行业成本—价格三序列），把待测模板复制进合成项目
scripts/（chart_qc 的 G8-RENDER 会重载项目内 analyze_charts.py），跑完整出图→报告→chart_qc 链路。

**发布协议**：修改 analyze_charts.py / chart_qc.py / ops 契约后，先跑 `template_regression.py`（含
`--selfcheck`）再发布；模板在实盘项目里的 patch 必须回流主模板并过回归，禁止只改项目副本。

**2026-08-21 修复记录**（本次回归源头）：主模板原带 5 处渲染 bug（图01/02 全历史年拥挤、图04 净利率
标注重叠、图10 多行标注越界、图11 门槛标注越界、chart_qc 清单检查不认 图表豁免.json），已全部移植
修复；回归测试正/负向均通过。


## 9. 龟龟成长校准轨（2026-08-21 新增，小商品城批次校准）

- 问题：保守轨 R* = C_trailing×k×M/市值 用 trailing C，高成长标的（净利 30%+）目标买入价被压到
  远低于合理前瞻价值（小商品城：6.83 vs 现价 12.48）——"永远买不到"。
- 方案：calc_penetration_return.py 提供 net_profit_C_fwd（+可选 payout_M_fwd/profit_discount_k_fwd/
  aa_fwd/c_fwd_source/c_fwd_verified）即输出 growth_calib 块（R*_fwd/KK_fwd/目标买入价_fwd/
  "成长验证买入区"/升级条款）；build_penetration_input.py 加 --c-fwd/--m-fwd/--k-fwd/--aa-fwd/
  --c-fwd-source；口径与纪律见本 skill `references/methodology.md` §2.1、`references/framework.md` B4.4/D0-12。
- 纪律要点：评级锚仍为保守轨 trailing（KK≤0 → 不建仓）；成长校准轨只给买入区与升级参考；
  升级必须由实际数据（中报/季报/合同负债）验证触发，预测本身不构成升级。
- 实测（小商品城）：C_fwd=55亿/M_fwd=0.55/k_fwd=0.8 → R*_fwd 3.54%、目标买入价_fwd 11.99 元、
  成长验证买入区 [6.83, 11.99] 元；KK_fwd -0.14pct 仍 <0 → 评级维持中性/观望。
