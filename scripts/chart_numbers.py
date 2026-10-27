"""Shared display-only precision for all research charts and health tables.

Keep raw arrays and calculation outputs unchanged. Apply this formatter only
when producing reader-facing text. Small nonzero values retain their sign.
"""
from __future__ import annotations

import math
import re

MAX_LABEL_DECIMALS=2
NUMBER_FORMAT_POLICY={'max_decimal_places':2,'small_nonzero':'inequality','trim_trailing_zeros':True}


def format_number(value, *, signed=False, missing='—'):
    try:
        number=float(value)
    except (TypeError,ValueError):
        return missing
    if not math.isfinite(number):
        return missing
    if number==0:
        return '0'
    if abs(number)<.01:
        return '<0.01' if number>0 else '>-0.01'
    result=f'{number:,.2f}'.rstrip('0').rstrip('.')
    return '+'+result if signed and number>0 else result


def valid_number_label(text):
    return bool(re.fullmatch(r'(?:[<>])?[-+]?\d+(?:,\d{3})*(?:\.\d{1,2})?',text))


def format_amount(yuan, *, signed=False):
    """Reader-facing RMB amounts use 亿元 or 万元, selected from raw yuan."""
    try:
        number=float(yuan)
    except (TypeError,ValueError):
        return '—'
    if not math.isfinite(number):
        return '—'
    divisor,unit=(1e8,'亿元') if abs(number)>=1e8 else (1e4,'万元')
    return format_number(number/divisor,signed=signed)+unit


def report_amount_unit_violations(text):
    """Reject legacy money/share units, allowing nonfinancial population counts."""
    pattern = re.compile(
        r'百万(?:元|股|美元|港元|人民币)|百万(?=[\s|（()）:：，。/／]|$)'
        r'|(?:RMB|CNY|USD|HKD|US\$|HK\$)\s*millions?\b'
        r'|\bmillions?\s*(?:RMB|CNY|USD|HKD|yuan|dollars?)\b', re.I)
    return [{'line': text.count('\n', 0, match.start())+1, 'unit': match.group(0)}
            for match in pattern.finditer(text)]


def format_chart_text(text):
    """Apply display precision to numeric prose, preserving dotted dates/versions."""
    decimal = re.compile(r'(?<![\d.])[-+]?\d[\d,]*\.(\d{3,})(?![\d.])')
    return decimal.sub(lambda match: format_number(float(match.group().replace(',','')),
                                                   signed=match.group().startswith('+')), text)


def normalize_figure_numbers(fig):
    """Format data-driven prose before measuring its actual rendered bounds."""
    labels=list(fig.texts)
    for name in ('_history_footer_text','_native_footer_text'):
        if hasattr(fig,name):
            setattr(fig,name,format_chart_text(getattr(fig,name)))
    for ax in fig.axes:
        labels.extend(ax.texts)
        labels.extend([ax.title,ax._left_title,ax._right_title])
        if hasattr(ax,'_history_title'):
            ax._history_title=format_chart_text(ax._history_title)
    for label in labels:
        if label.get_visible():
            label.set_text(format_chart_text(label.get_text()))


def figure_number_audit(fig):
    """Audit actual rendered annotation/title text, excluding dates and codes."""
    labels=list(fig.texts)
    for ax in fig.axes:
        if ax.get_visible():
            labels.extend(ax.texts)
            labels.extend([ax.title,ax._left_title,ax._right_title])
    errors=[]
    decimal=re.compile(r'(?<![\d.])[-+<>]?\d[\d,]*\.(\d+)(?![\d.])')
    for label in labels:
        if not label.get_visible():
            continue
        text=label.get_text()
        if any(len(match.group(1))>2 for match in decimal.finditer(text)):
            errors.append(text[:160])
    return {'number_format':dict(NUMBER_FORMAT_POLICY),'number_format_violations':errors}
