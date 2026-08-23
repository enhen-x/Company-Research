#!/usr/bin/env python3
"""Convert qualitative_report.md to styled HTML dashboard.

Usage:
    python3 scripts/report_to_html.py \
        --input output/002078_太阳纸业/qualitative_report.md \
        --output output/002078_太阳纸业/qualitative_report.html

Optional:
    --template  Path to Jinja2 HTML template (default: shared/qualitative/templates/dashboard.html)
    --appendix  Path to framework_guide.md (default: shared/qualitative/references/framework_guide.md)
"""

import argparse
import re
import os
import sys
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, BaseLoader


# ---------------------------------------------------------------------------
# Markdown → HTML conversion
# ---------------------------------------------------------------------------

def md_to_html(md_text: str) -> str:
    """Convert markdown text to HTML with tables and fenced code support."""
    return markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
    )


# ---------------------------------------------------------------------------
# Fallback inline CSS for --standalone mode when site CSS not found
# ---------------------------------------------------------------------------

_FALLBACK_CSS = """
:root{--bg:#fafaf7;--bg2:#f0efe9;--bg3:#e8e7e0;--text:#1c1c1a;--text2:#5c5c58;--text3:#8a8a84;--border:rgba(0,0,0,.08);--accent:#1a1a18;--green:#1a7a5a;--green-bg:#e6f4ee;--red:#c0392b;--red-bg:#fceaea;--amber:#a06c1a;--amber-bg:#faf0d8;--blue:#2563a0;--blue-bg:#e8f0fa;--max-width:820px;--padding-x:32px}
@media(prefers-color-scheme:dark){:root{--bg:#141414;--bg2:#1e1e1e;--bg3:#2a2a2a;--text:#e8e8e4;--text2:#a8a8a0;--text3:#6e6e68;--border:rgba(255,255,255,.08);--accent:#e8e8e4;--green:#4ade80;--green-bg:rgba(74,222,128,.1);--red:#f87171;--red-bg:rgba(248,113,113,.1);--amber:#fbbf24;--amber-bg:rgba(251,191,36,.1);--blue:#60a5fa;--blue-bg:rgba(96,165,250,.1)}}
*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Noto Sans SC',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.7;font-size:15px}
.container{max-width:var(--max-width);margin:0 auto;padding:0 var(--padding-x)}.site-nav{display:flex;align-items:center;justify-content:space-between;padding:16px 0;border-bottom:1px solid var(--border)}.nav-logo{color:var(--text);text-decoration:none;font-weight:600;font-size:15px}.nav-links{display:flex;gap:20px}.nav-links a{color:var(--text3);text-decoration:none;font-size:14px}.nav-links a.active{color:var(--text)}
.report-body{max-width:var(--max-width);margin:0 auto;padding:32px var(--padding-x) 64px;font-size:15px;line-height:1.7;color:var(--text)}
.report-body .header{border-bottom:2px solid var(--accent);padding-bottom:24px;margin-bottom:40px}.report-body .header .ticker{font-family:'JetBrains Mono',monospace;font-size:13px;color:var(--text3);letter-spacing:.5px;text-transform:uppercase}.report-body .header h1{font-size:28px;font-weight:600;margin:6px 0 4px;letter-spacing:-.5px}.report-body .header .date{font-size:13px;color:var(--text3)}
.report-body .verdict{display:flex;align-items:center;gap:12px;margin:24px 0;padding:16px 20px;background:var(--bg2);border-radius:8px;border-left:4px solid var(--green)}.verdict.v-green{border-left-color:var(--green)}.verdict.v-amber{border-left-color:var(--amber)}.verdict.v-red{border-left-color:var(--red)}.verdict-label{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--text3);font-weight:500}.verdict-text{font-size:15px;font-weight:500}
.report-body h2{font-size:13px;font-weight:500;text-transform:uppercase;letter-spacing:1.5px;color:var(--text3);margin:48px 0 16px;padding-bottom:8px;border-bottom:1px solid var(--border)}.report-body h2:first-of-type{margin-top:0}.report-body h3{font-size:15px;font-weight:600;color:var(--text);margin:24px 0 10px}.report-body h4{font-size:14px;font-weight:500;color:var(--text2);margin:16px 0 8px}
.report-body p{margin-bottom:14px;color:var(--text2)}.report-body p strong{color:var(--text);font-weight:500}.report-body ul,.report-body ol{margin:8px 0 14px 20px;color:var(--text2)}.report-body li{margin:4px 0}.report-body blockquote{border-left:3px solid var(--border);padding:8px 16px;margin:14px 0;color:var(--text3);font-style:italic;font-size:14px}
.report-body .grid{display:grid;gap:10px;margin:16px 0}.report-body .g4{grid-template-columns:1fr 1fr 1fr 1fr}@media(max-width:600px){.report-body .g4{grid-template-columns:1fr 1fr}}.report-body .metric{background:var(--bg2);border-radius:8px;padding:14px 16px}.report-body .metric .label{font-size:11px;color:var(--text3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}.report-body .metric .value{font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:500}.report-body .metric .sub{font-size:12px;color:var(--text3);margin-top:2px}
.report-body .metric.highlight{background:var(--green-bg);border:1px solid rgba(26,122,90,.15)}.report-body .metric.highlight .value{color:var(--green)}.report-body .metric.warn{background:var(--red-bg);border:1px solid rgba(192,57,43,.15)}.report-body .metric.warn .value{color:var(--red)}.report-body .metric.amber-hl{background:var(--amber-bg);border:1px solid rgba(160,108,26,.15)}.report-body .metric.amber-hl .value{color:var(--amber)}
.report-body .tag{display:inline-block;font-size:11px;padding:2px 8px;border-radius:4px;font-weight:500}.tag-green{background:var(--green-bg);color:var(--green)}.tag-red{background:var(--red-bg);color:var(--red)}.tag-amber{background:var(--amber-bg);color:var(--amber)}
.badge-strong{background:var(--green-bg);color:var(--green)}.badge-fairly-strong{background:var(--green-bg);color:var(--green)}.badge-medium{background:var(--amber-bg);color:var(--amber)}.badge-weak{background:var(--red-bg);color:var(--red)}
.report-body table{width:100%;border-collapse:collapse;margin:16px 0;font-size:13px}.report-body th{text-align:left;padding:8px 10px;font-weight:400;color:var(--text3);border-bottom:1px solid var(--border);font-size:11px;text-transform:uppercase;letter-spacing:.5px}.report-body th:not(:first-child){text-align:right}.report-body td{padding:8px 10px;border-bottom:1px solid var(--border)}.report-body td:not(:first-child){text-align:right;font-family:'JetBrains Mono',monospace;font-size:13px}.report-body tr:last-child td{border-bottom:none}
.report-body .callout{padding:16px 20px;background:var(--bg2);border-radius:8px;margin:20px 0;font-size:14px;color:var(--text2);line-height:1.7}
.report-body details{margin:16px 0}.report-body summary{cursor:pointer;font-size:13px;font-weight:500;text-transform:uppercase;letter-spacing:1px;color:var(--text3);padding:10px 0;border-bottom:1px solid var(--border);user-select:none}.report-body details .details-content{padding:16px 0;font-size:14px;color:var(--text2)}
.report-body .footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--border);font-size:12px;color:var(--text3);line-height:1.8}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
@media print{.site-nav{display:none}.report-body{padding:24px;font-size:12px;max-width:100%}}
"""


# Report parser – splits MD into logical sections
# ---------------------------------------------------------------------------

_RATING_MAP = {
    "强": ("rating-strong", "badge-strong"),
    "较强": ("rating-fairly-strong", "badge-fairly-strong"),
    "中": ("rating-medium", "badge-medium"),
    "中等": ("rating-medium", "badge-medium"),
    "弱": ("rating-weak", "badge-weak"),
    "高可持续": ("rating-strong", "badge-strong"),
    "中等可持续": ("rating-medium", "badge-medium"),
    "低可持续": ("rating-weak", "badge-weak"),
    "优秀": ("rating-strong", "badge-strong"),
    "合格": ("rating-fairly-strong", "badge-fairly-strong"),
    "损害价值": ("rating-weak", "badge-weak"),
    "观察期": ("rating-medium", "badge-medium"),
    "capital-light": ("rating-strong", "badge-strong"),
    "capital-hungry": ("rating-medium", "badge-medium"),
    "存在": ("rating-strong", "badge-strong"),
    "可能存在": ("rating-medium", "badge-medium"),
    "不存在": ("rating-weak", "badge-weak"),
    "正面": ("rating-strong", "badge-strong"),
    "中性": ("rating-medium", "badge-medium"),
    "负面": ("rating-weak", "badge-weak"),
    "低": ("rating-strong", "badge-strong"),
    "高": ("rating-weak", "badge-weak"),
}


def _rating_css(value: str) -> tuple[str, str]:
    """Return (kpi_card_class, badge_class) for a rating value."""
    for key, classes in _RATING_MAP.items():
        if key in value:
            return classes
    return ("rating-neutral", "")


def parse_report(md_text: str) -> dict:
    """Parse the qualitative report MD into structured sections."""
    result = {
        "company_name": "",
        "stock_code": "",
        "generated_date": "",
        "executive_summary": "",
        "dimensions": [],
        "conclusion": "",
        "parameters_table": "",
    }

    # --- Extract title metadata ---
    # Format A: "# 定性分析 — CompanyName (Code)"
    title_match = re.search(r"#\s+定性分析.*?—\s*(.+?)\s*\((.+?)\)", md_text)
    if title_match:
        result["company_name"] = title_match.group(1)
        result["stock_code"] = title_match.group(2)
    else:
        # Format B: "# 美的集团（000333.SZ / 0300.HK）— 商业模式与护城河定性分析"
        title_match_b = re.search(
            r"#\s+(.+?)\s*[（(](.+?)[）)]\s*—", md_text
        )
        if title_match_b:
            result["company_name"] = title_match_b.group(1).strip()
            result["stock_code"] = title_match_b.group(2).strip()

    # Date extraction: try multiple formats
    date_match = re.search(r"\*生成时间:\s*(.+?)\*", md_text)
    if date_match:
        result["generated_date"] = date_match.group(1)
    else:
        # Format B: "> 分析日期：2026-04-05" or footer "分析日期 2026-04-05"
        date_match_b = re.search(r"分析日期[：:\s]+(\d{4}-\d{2}-\d{2})", md_text)
        if date_match_b:
            result["generated_date"] = date_match_b.group(1)

    # --- Split by ## headers ---
    sections = re.split(r"(?=^## )", md_text, flags=re.MULTILINE)

    for section in sections:
        header_match = re.match(r"## (.+?)(?:\n|$)", section)
        if not header_match:
            continue
        title = header_match.group(1).strip()
        body = section[header_match.end():]

        if "执行摘要" in title or "Executive Summary" in title:
            result["executive_summary"] = md_to_html(body)
        elif "总结与投资启示" in title or "深度总结" in title:
            result["conclusion"] = md_to_html(body)
        elif "结构化参数" in title:
            result["parameters_table"] = md_to_html(body)
        elif "交叉验证" in title:
            result["dimensions"].append({
                "title": title,
                "content": md_to_html(body),
                "badge": "",
                "badge_class": "",
            })
        elif "维度" in title:
            # Extract badge from subsection summaries
            badge = ""
            badge_class = ""
            # Try to find the key rating in 小结 section
            summary_match = re.search(
                r"综合评价[：:]\s*\*?\*?(\S+?)\*?\*?(?:\s|$)", body
            )
            if not summary_match:
                summary_match = re.search(
                    r"管理层评价[：:]\s*\*?\*?(\S+?)\*?\*?(?:\s|$)", body
                )
            if not summary_match:
                summary_match = re.search(
                    r"MD&A\s*可信度[：:]\s*\*?\*?(\S+?)\*?\*?(?:\s|$)", body
                )
            if not summary_match:
                summary_match = re.search(
                    r"资本消耗强度[：:]\s*\*?\*?(\S+?)\*?\*?(?:\s|$)", body
                )
            if summary_match:
                badge = summary_match.group(1).strip("*")
                _, badge_class = _rating_css(badge)

            result["dimensions"].append({
                "title": title,
                "content": md_to_html(body),
                "badge": badge,
                "badge_class": badge_class,
            })

    return result


def extract_kpi_cards(md_text: str) -> list[dict]:
    """Extract KPI values from the structured parameters table."""
    cards = []

    def _find_param(name: str) -> str:
        pattern = rf"\|\s*{re.escape(name)}\s*\|\s*(.+?)\s*\|"
        m = re.search(pattern, md_text)
        return m.group(1).strip() if m else ""

    def _to_card_css(value: str) -> str:
        """Map rating text to card CSS class."""
        positive = ["强", "优秀", "存在", "高可持续", "正面", "capital-light"]
        negative = ["弱", "损害价值", "不存在", "低可持续", "负面"]
        neutral = ["中", "中等", "合格", "观察期", "中等可持续", "capital-hungry", "可能存在"]
        for p in positive:
            if p in value:
                return "highlight"
        for n in negative:
            if n in value:
                return "warn"
        for m in neutral:
            if m in value:
                return "amber-hl"
        return ""

    # ROE
    roe = _find_param("roe_5y_avg")
    if roe:
        try:
            roe_val = float(re.search(r"[\d.]+", roe).group())
            css = "highlight" if roe_val >= 15 else ("amber-hl" if roe_val >= 8 else "warn")
        except (ValueError, AttributeError):
            css = ""
        cards.append({"label": "5Y Avg ROE", "value": roe, "css_class": css, "sub": ""})

    # Moat rating
    moat = _find_param("moat_rating")
    if moat:
        cards.append({"label": "护城河评级", "value": moat, "css_class": _to_card_css(moat), "sub": ""})

    # Sustainability
    sust = _find_param("moat_sustainability")
    if sust:
        cards.append({"label": "可持续性", "value": sust, "css_class": _to_card_css(sust), "sub": ""})

    # Management
    mgmt = _find_param("management_rating")
    if mgmt:
        cards.append({"label": "管理层评价", "value": mgmt, "css_class": _to_card_css(mgmt), "sub": ""})

    # Cyclicality
    cyc = _find_param("cyclicality")
    if cyc:
        pos = _find_param("cycle_position")
        cards.append({"label": "周期性", "value": cyc, "css_class": "", "sub": pos if pos else ""})

    # Capital intensity
    cap = _find_param("capital_intensity")
    if cap:
        cards.append({"label": "资本强度", "value": cap, "css_class": _to_card_css(cap), "sub": ""})

    # Entry barrier
    barrier = _find_param("entry_barrier")
    if barrier:
        cards.append({"label": "进入壁垒", "value": barrier, "css_class": _to_card_css(barrier), "sub": ""})

    # Moat existence
    exist = _find_param("moat_existence")
    if exist:
        cards.append({"label": "优势存在性", "value": exist, "css_class": _to_card_css(exist), "sub": ""})

    return cards


def extract_data_pack_info(dp_text: str) -> dict:
    """Extract header-level info from data_pack_market.md."""
    info = {
        "current_price": "",
        "market_cap": "",
        "exchange": "",
        "industry": "",
    }

    price_m = re.search(r"当前价格[|\s]+(\d+\.?\d*)", dp_text)
    if price_m:
        info["current_price"] = price_m.group(1)

    mcap_m = re.search(r"总市值\s*\(万元\)\s*\|\s*([\d,.]+)", dp_text)
    if mcap_m:
        val = mcap_m.group(1).replace(",", "")
        try:
            v = float(val)
            info["market_cap"] = f"{v / 10000:.0f}亿"
        except ValueError:
            info["market_cap"] = mcap_m.group(1)

    exchange_m = re.search(r"交易所\s*\|\s*(\S+)", dp_text)
    if exchange_m:
        info["exchange"] = exchange_m.group(1)

    industry_m = re.search(r"行业\s*\|\s*(\S+)", dp_text)
    if industry_m:
        info["industry"] = industry_m.group(1)

    return info


def build_verdict(md_text: str) -> dict:
    """Build the verdict banner from the report's moat_rating and conclusion."""
    def _find_param(name: str) -> str:
        pattern = rf"\|\s*{re.escape(name)}\s*\|\s*(.+?)\s*\|"
        m = re.search(pattern, md_text)
        return m.group(1).strip() if m else ""

    moat = _find_param("moat_rating")
    sust = _find_param("moat_sustainability")

    # Extract one-line final conclusion if present
    verdict_text = ""
    final_m = re.search(
        r"(?:一句话最终结论|一句话结论)[：:]\s*\*?\*?(.+?)(?:\*?\*?\s*$|\n)",
        md_text, re.MULTILINE,
    )
    if final_m:
        verdict_text = final_m.group(1).strip().strip("*")
    else:
        # Fallback: build from params
        verdict_text = f"护城河评级 {moat}，可持续性 {sust}" if moat else ""

    # Determine color
    tag_map = {
        "强": ("tag-green", "v-green", "STRONG MOAT"),
        "较强": ("tag-green", "v-green", "FAIRLY STRONG"),
        "中": ("tag-amber", "v-amber", "MODERATE"),
        "弱": ("tag-red", "v-red", "WEAK"),
    }
    tag_class, verdict_class, tag_text = tag_map.get(
        moat, ("tag-amber", "v-amber", moat.upper() if moat else "N/A")
    )

    return {
        "verdict_class": verdict_class,
        "verdict_tag_class": tag_class,
        "verdict_tag": tag_text,
        "verdict_text": verdict_text,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Convert qualitative report MD to HTML dashboard")
    parser.add_argument("--input", required=True, help="Path to qualitative_report.md")
    parser.add_argument("--output", required=True, help="Output HTML path")
    parser.add_argument(
        "--template",
        default=None,
        help="Jinja2 template path (default: auto-detect from project root)",
    )
    parser.add_argument(
        "--appendix",
        default=None,
        help="Path to framework_guide.md (default: auto-detect)",
    )
    parser.add_argument(
        "--data-pack",
        default=None,
        help="Path to data_pack_market.md for header stats extraction",
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="Embed CSS inline for local viewing (no external CSS dependencies)",
    )
    args = parser.parse_args()

    # --- Resolve paths ---
    project_root = Path(__file__).resolve().parent.parent
    template_path = Path(args.template) if args.template else project_root / "shared" / "qualitative" / "templates" / "dashboard.html"
    appendix_path = Path(args.appendix) if args.appendix else project_root / "shared" / "qualitative" / "references" / "framework_guide.md"
    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if not template_path.exists():
        print(f"Error: Template not found: {template_path}", file=sys.stderr)
        sys.exit(1)

    # --- Read inputs ---
    md_text = input_path.read_text(encoding="utf-8")
    template_text = template_path.read_text(encoding="utf-8")

    appendix_html = ""
    if appendix_path.exists():
        appendix_md = appendix_path.read_text(encoding="utf-8")
        appendix_html = md_to_html(appendix_md)

    # --- Parse report ---
    report = parse_report(md_text)
    kpi_cards = extract_kpi_cards(md_text)
    verdict = build_verdict(md_text)

    # Try to get data pack info
    dp_info = {"current_price": "", "market_cap": "", "exchange": "", "industry": ""}
    data_pack_path = Path(args.data_pack) if args.data_pack else input_path.parent / "data_pack_market.md"
    if data_pack_path.exists():
        dp_text = data_pack_path.read_text(encoding="utf-8")
        dp_info = extract_data_pack_info(dp_text)

    # --- Load standalone CSS if requested ---
    standalone_css = ""
    if args.standalone:
        # Try to load style.css + report.css from terancejiang.com project
        site_root = Path.home() / "Projects" / "Teracnejiang.com"
        css_parts = []
        for css_file in ["assets/css/style.css", "assets/css/report.css"]:
            css_path = site_root / css_file
            if css_path.exists():
                css_parts.append(css_path.read_text(encoding="utf-8"))
        if css_parts:
            standalone_css = "\n".join(css_parts)
        else:
            # Fallback: minimal inline CSS for local viewing
            standalone_css = _FALLBACK_CSS

    # --- Generate slug ---
    slug = ""
    if report["stock_code"]:
        code = report["stock_code"].replace(".SH", "").replace(".SZ", "").replace(".HK", "").replace(".US", "")
        name = report["company_name"] or ""
        # Simple slug: company-code-qualitative
        slug = f"{name}-{code}-qualitative".lower().replace(" ", "-")

    # --- Render template ---
    env = Environment(loader=BaseLoader())
    template = env.from_string(template_text)
    html = template.render(
        company_name=report["company_name"],
        stock_code=report["stock_code"],
        generated_date=report["generated_date"],
        current_price=dp_info["current_price"],
        market_cap=dp_info["market_cap"],
        exchange=dp_info["exchange"],
        industry=dp_info["industry"],
        slug=slug,
        standalone_css=standalone_css,
        kpi_cards=kpi_cards,
        executive_summary=report["executive_summary"],
        dimensions=report["dimensions"],
        conclusion=report["conclusion"],
        parameters_table=report["parameters_table"],
        framework_guide=appendix_html,
        **verdict,
    )

    # --- Write output ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"HTML report generated: {output_path}")
    print(f"  Sections: {len(report['dimensions'])} dimensions")
    print(f"  KPI cards: {len(kpi_cards)}")
    print(f"  Has executive summary: {bool(report['executive_summary'])}")
    print(f"  Has conclusion: {bool(report['conclusion'])}")
    print(f"  Has appendix: {bool(appendix_html)}")


if __name__ == "__main__":
    main()
