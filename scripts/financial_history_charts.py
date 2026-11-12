#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Year-grouped annual/quarter financial charts with annual YoY only.

One year is one group: outlined annual bar plus Q1-Q4 blue bars. Incomplete
years have NO annual bar or annual YoY point. Orange lines compare adjacent
complete fiscal years. Flow quarters are differences of cumulative filings.
Stocks are period-end balances; weighted ROE remains cumulative.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.font_manager import FontProperties,fontManager
from matplotlib.transforms import Bbox
from matplotlib.text import Text
from matplotlib.ticker import FuncFormatter, MaxNLocator, MultipleLocator

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'PingFang SC', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

from chart_periods import CHART_METRICS, NAMES, RATIOS, STOCKS, chart_values, annual_growth
from chart_numbers import format_number,valid_number_label,MAX_LABEL_DECIMALS,figure_number_audit,normalize_figure_numbers

TITLES = {'图01':'营业总收入与归母净利','图02':'ROE与每股净资产','图04':'盈利能力趋势',
          '图05':'现金流结构','图12':'盈利历史与三情景预测','图15':'杠杆与负债结构'}
COLORS = ['#1745AF','#3475D7','#6A9EE6','#A5C7EF']


def _place_bar_labels(fig):
    """Keep all labels above their own bars; stagger vertically in display pixels."""
    collisions=[]
    def bounds(label,renderer):
        # Annotation.get_window_extent also includes its leader line. Including
        # that line in collisions makes every vertical move enlarge the box.
        label.update_positions(renderer)
        return Text.get_window_extent(label,renderer)
    for _ in range(4):
        fig.canvas.draw(); renderer=fig.canvas.get_renderer(); expanded=False
        for ax in fig.axes:
            labels=[t for t in ax.texts if getattr(t,'_bar_value_label',False)]
            placed=[]
            labels.sort(key=lambda t:(getattr(t,'_annual_label',False),float(t.xy[1])))
            for label in labels:
                label.set_position(label._initial_offset)
                direction=1 if label.xy[1]>=0 else -1
                for step in range(max(12,len(labels))):
                    box=bounds(label,renderer).expanded(1.06,1.18)
                    hits=[other for other in placed if box.overlaps(bounds(other,renderer).expanded(1.06,1.18))]
                    if not hits:
                        break
                    jump=max((bounds(other,renderer).y1-box.y0+3 if direction>0 else box.y1-bounds(other,renderer).y0+3) for other in hits)
                    dx,dy=label.get_position()
                    label.set_position((dx,dy+direction*max(jump,3)*72/fig.dpi))
                if label.arrow_patch is not None:
                    label.arrow_patch.set_visible(abs(label.get_position()[1]-label._initial_offset[1])>8)
                placed.append(label)
            if placed:
                ab=ax.get_window_extent(renderer)
                hi=max(bounds(t,renderer).y1 for t in placed)
                lo=min(bounds(t,renderer).y0 for t in placed)
                y0,y1=ax.get_ylim()
                if hi>ab.y1-3 or lo<ab.y0+3:
                    inv=ax.transData.inverted()
                    top=inv.transform((ab.x0,max(hi+6,ab.y1)))[1]
                    bottom=inv.transform((ab.x0,min(lo-6,ab.y0)))[1]
                    ax.set_ylim(min(y0,bottom),max(y1,top)); expanded=True
        if not expanded:
            break
    fig.canvas.draw(); renderer=fig.canvas.get_renderer()
    for ax in fig.axes:
        labels=[t for t in ax.texts if getattr(t,'_bar_value_label',False)]
        for i,a in enumerate(labels):
            for b in labels[i+1:]:
                if bounds(a,renderer).overlaps(bounds(b,renderer)):
                    collisions.append([a.get_text(),b.get_text()])
    return collisions


def _wrap_measured(text,renderer,width,size):
    """Wrap against rendered glyph widths (Chinese/Latin/numbers), not char counts."""
    installed={f.name for f in fontManager.ttflist}
    family=next((name for name in plt.rcParams['font.sans-serif'] if name in installed),'DejaVu Sans')
    font=FontProperties(family=family,size=size)
    lines=[]
    for paragraph in str(text).split('\n'):
        current=''
        for char in paragraph:
            candidate=current+char
            measured=renderer.get_text_width_height_descent(candidate,font,False)[0]
            if current and measured > width:
                lines.append(current.rstrip()); current=char.lstrip()
            else:
                current=candidate
        lines.append(current)
    return '\n'.join(lines)


def layout_history(fig):
    """Pack measured decoration boxes, without double-reserving header space.

    All gaps are physical points between rendered boxes, not fractions of a
    particular company's canvas. Twin axes share each row's final position.
    """
    if not getattr(fig,'_year_grouped',False):
        return
    normalize_figure_numbers(fig)
    mains=[ax for ax in fig.axes if hasattr(ax,'_history_title')]
    for ax in mains:
        for label in ax.texts:
            if getattr(label,'_bar_value_label',False):
                label.set_in_layout(False)
    for _ in range(4):
        previous_positions=[ax.get_position().bounds for ax in mains]
        fig.canvas.draw()
        renderer=fig.canvas.get_renderer(); fw,fh=fig.bbox.width,fig.bbox.height
        pt=fig.dpi/72; edge=14*pt; gap=20*pt
        if fig._suptitle:
            fig._suptitle.set_position((.5,1-edge/fh))
            fig._suptitle.set_va('top')
        fig.canvas.draw(); renderer=fig.canvas.get_renderer()
        title_bottom=fig._suptitle.get_window_extent(renderer).y0 if fig._suptitle else fh-edge
        legend=fig.legends[0]
        while True:
            legend.set_bbox_to_anchor((.5,(title_bottom-6*pt)/fh),transform=fig.transFigure)
            fig.canvas.draw(); renderer=fig.canvas.get_renderer()
            if legend.get_window_extent(renderer).width<=fw-2*edge or fig._legend_columns==1:
                break
            fig._legend_columns-=1; legend.remove()
            legend=fig.legend(handles=fig._legend_handles,loc='upper center',
                              ncol=fig._legend_columns,frameon=False,fontsize=8.5,
                              borderaxespad=0,columnspacing=1.6,handletextpad=.8)
        content_top=legend.get_window_extent(renderer).y0-gap
        footer=fig._history_footer
        footer.set_position((.5,edge/fh))
        footer.set_text(_wrap_measured(fig._history_footer_text,renderer,fw-2*edge,8))
        fig.canvas.draw(); renderer=fig.canvas.get_renderer()
        content_bottom=footer.get_window_extent(renderer).y1+gap
        groups=[]; overhangs=[]
        for ax in mains:
            width=ax.get_position().width*fw
            ax.set_title(_wrap_measured(ax._history_title,renderer,width,10.5),loc='left',fontsize=10.5,fontweight='bold',pad=12)
            pair=[ax,ax._history_twin]; groups.append(pair)
        fig.canvas.draw(); renderer=fig.canvas.get_renderer()
        for pair in groups:
            plot=pair[0].get_window_extent(renderer)
            box=Bbox.union([a.get_tightbbox(renderer) for a in pair])
            overhangs.append((plot.x0-box.x0,box.x1-plot.x1,box.y1-plot.y1,plot.y0-box.y0))
        height=(content_top-content_bottom-(len(groups)-1)*gap-sum(v[2]+v[3] for v in overhangs))/len(groups)
        minimum=180*pt
        if height<minimum:
            fig.set_size_inches(fig.get_figwidth(),(fh+(minimum-height)*len(groups))/fig.dpi,forward=True)
            continue
        left=edge+max(v[0] for v in overhangs)
        right=fw-edge-max(v[1] for v in overhangs)
        cursor=content_top
        for pair,(_,_,above,below) in zip(groups,overhangs):
            top=cursor-above; bottom=top-height
            for ax in pair:
                ax.set_position((left/fw,bottom/fh,(right-left)/fw,height/fh))
            cursor=bottom-below-gap
        if max(abs(before-after)*max(fw,fh) for ax,bounds in zip(mains,previous_positions) for before,after in zip(bounds,ax.get_position().bounds))<.2:
            break
    collisions=_place_bar_labels(fig)
    fig.canvas.draw(); renderer=fig.canvas.get_renderer(); pt=fig.dpi/72
    boxes=[Bbox.union([a.get_tightbbox(renderer) for a in (ax,ax._history_twin)]) for ax in mains]
    counts={}
    for ax in mains:
        labels=[t for t in ax.texts if getattr(t,'_bar_value_label',False)]
        counts[ax._metric_key]={'annual':sum(t._annual_label for t in labels),
                              'quarter':sum(not t._annual_label for t in labels),
                              'number_format_valid':all(valid_number_label(t.get_text()) and (t._bar_label_value==0 or t.get_text()!='0') for t in labels),
                              'text_matches_values':all(t.get_text()==format_number(t._bar_label_value) for t in labels)}
    fig._layout_audit={'legend_columns':fig._legend_columns,'measured':True,
                       'annotation_collisions':collisions,
                       'bar_label_counts':counts,
                       'number_format':{'max_decimal_places':MAX_LABEL_DECIMALS,'small_nonzero':'inequality','trim_trailing_zeros':True},
                       'header_gap_pt':(fig.legends[0].get_window_extent(renderer).y0-boxes[0].y1)/pt,
                       'row_gaps_pt':[(a.y0-b.y1)/pt for a,b in zip(boxes,boxes[1:])],
                       'footer_gap_pt':(boxes[-1].y0-fig._history_footer.get_window_extent(renderer).y1)/pt,
                       'minimum_plot_width_ratio':min(ax.get_position().width for ax in fig.axes)}
    fig._layout_audit.update(figure_number_audit(fig))


def layout_native(fig):
    """Measure and pack native chart rows, including square donuts and text.

    The first tight_layout only aligns columns. Final placement packs actual
    row bounds and resizes the canvas, so equal-aspect plots do not leave a
    large empty band and figure subtitles cannot overlap axes legends.
    """
    if getattr(fig,'_year_grouped',False):
        return layout_history(fig)
    normalize_figure_numbers(fig)
    fig._measured_native_layout=True
    active_axes=[ax for ax in fig.axes if ax.get_visible()]
    # Legacy charts attach notes at axes y=-0.14. Move these into the same
    # measured footer flow; otherwise their gap scales with the plot height.
    for ax in active_axes:
        for text in ax.texts:
            if text.get_visible() and text.get_transform()==ax.transAxes and text.get_position()[1]<0:
                fig.text(.5,.01,text.get_text(),ha='center',fontsize=8,color='#6B7280')
                text.set_visible(False)
    if not getattr(fig,'_native_legends_ready',False):
        handles=[]; labels=[]
        for ax in active_axes:
            # A legend on the left axis may include lines owned by its twin.
            # Collect every axis before removing legends so those series remain.
            hh,ll=ax.get_legend_handles_labels()
            for h,label in zip(hh,ll):
                if label not in labels and not label.startswith('_'):
                    handles.append(h); labels.append(label)
            if ax.get_legend() is not None:
                ax.get_legend().remove()
        for legend in list(fig.legends):
            hh=getattr(legend,'legend_handles',[])
            for h,label in zip(hh,[t.get_text() for t in legend.get_texts()]):
                if label not in labels:
                    handles.append(h); labels.append(label)
            legend.remove()
        if handles:
            fig._native_legend_handles=handles
            fig._native_legend_columns=len(handles)
            fig.legend(handles,labels,loc='upper center',ncol=len(handles),frameon=False,fontsize=8.5,
                       borderaxespad=0,columnspacing=1.6,handletextpad=0.8)
        fig._native_legends_ready=True
    if fig._suptitle:
        fig._suptitle.set_in_layout(False)
    for legend in fig.legends:
        legend.set_in_layout(False)
    footers=[t for t in fig.texts if t is not fig._suptitle and t.get_visible() and t.get_position()[1]<=.15]
    if footers and not hasattr(fig,'_native_footer_text'):
        fig._native_footer_text='\n'.join(t.get_text() for t in footers)
        fig._native_footer=footers[0]
        for t in footers[1:]:
            t.set_visible(False)
        fig._native_footer.set_in_layout(False)
    subtitle=getattr(fig,'_layout_subtitle',None)
    if subtitle is not None:
        subtitle.set_in_layout(False)
    for _ in range(2):
        fig.canvas.draw(); renderer=fig.canvas.get_renderer(); fw,fh=fig.bbox.width,fig.bbox.height
        pt=fig.dpi/72; edge=12*pt; gap=16*pt
        top=fh-edge
        if fig._suptitle:
            title=fig._suptitle
            title.set_text(_wrap_measured(title.get_text(),renderer,fw-2*edge,title.get_fontsize()))
            title.set_position((.5,1-edge/fh)); title.set_ha('center'); title.set_va('top')
            fig.canvas.draw(); renderer=fig.canvas.get_renderer()
            top=title.get_window_extent(renderer).y0-gap
        if subtitle is not None:
            raw=getattr(subtitle,'_unwrapped_text',subtitle.get_text()); subtitle._unwrapped_text=raw
            subtitle.set_text(_wrap_measured(raw,renderer,fw-2*edge,subtitle.get_fontsize()))
            subtitle.set_position((edge/fw,top/fh)); subtitle.set_va('top')
            fig.canvas.draw(); renderer=fig.canvas.get_renderer()
            top=subtitle.get_window_extent(renderer).y0-gap
        if fig.legends:
            legend=fig.legends[0]
            while True:
                legend.set_bbox_to_anchor((.5,top/fh),transform=fig.transFigure)
                legend.set_loc('upper center'); legend.set_in_layout(False)
                fig.canvas.draw(); renderer=fig.canvas.get_renderer()
                if legend.get_window_extent(renderer).width<=fw-2*edge or fig._native_legend_columns<=1:
                    break
                fig._native_legend_columns-=1; legend.remove()
                legend=fig.legend(handles=fig._native_legend_handles,loc='upper center',ncol=fig._native_legend_columns,
                                  frameon=False,fontsize=8.5,borderaxespad=0,columnspacing=1.6,handletextpad=0.8)
            top=legend.get_window_extent(renderer).y0-gap
        bottom=edge
        if hasattr(fig,'_native_footer'):
            footer=fig._native_footer
            footer.set_text(_wrap_measured(fig._native_footer_text,renderer,fw-2*edge,8))
            footer.set_position((.5,edge/fh)); footer.set_ha('center'); footer.set_va('bottom')
            fig.canvas.draw(); renderer=fig.canvas.get_renderer()
            bottom=footer.get_window_extent(renderer).y1+gap
        if not getattr(fig,'_flow_text_only',False):
            fig.tight_layout(rect=(0,bottom/fh,1,top/fh),h_pad=1.5)
    fig.canvas.draw(); renderer=fig.canvas.get_renderer(); fh=fig.bbox.height
    # Group columns and twin axes by the actual row center, then compact rows.
    rows=[]
    for ax in sorted(active_axes,key=lambda a:-a.get_position().y1):
        center=(ax.get_position().y0+ax.get_position().y1)/2
        row=next((r for r in rows if abs(r['center']-center)<.025),None)
        if row is None:
            row={'center':center,'axes':[]}; rows.append(row)
        row['axes'].append(ax)
    for row in rows:
        row['box']=Bbox.union([a.get_tightbbox(renderer) for a in row['axes']])
        row['plots']=[a.get_window_extent(renderer).frozen() for a in row['axes']]
    newheight=(fh-top)+sum(row['box'].height for row in rows)+gap*(len(rows)-1)+bottom
    header_positions=[(t,t.get_position()[0],fh*(1-t.get_position()[1])) for t in (fig._suptitle,subtitle) if t is not None]
    fig.set_size_inches(fig.get_figwidth(),newheight/fig.dpi,forward=True)
    for t,x,distance in header_positions:
        t.set_position((x,1-distance/newheight))
    if fig.legends:
        # Preserve the measured legend's top distance from the figure top.
        legend=fig.legends[0]
        # The old anchor is in old pixel coordinates; derive its top distance
        # from the measured legend height and content boundary instead.
        legend_height=legend.get_window_extent(renderer).height
        legend.set_bbox_to_anchor((.5,(newheight-(fh-top-gap-legend_height))/newheight),transform=fig.transFigure)
    if hasattr(fig,'_native_footer'):
        fig._native_footer.set_position((.5,edge/newheight))
    cursor=newheight-(fh-top)
    for row in rows:
        shift=cursor-row['box'].y1
        for ax,plot in zip(row['axes'],row['plots']):
            ax.set_position((plot.x0/fw,(plot.y0+shift)/newheight,plot.width/fw,plot.height/newheight))
        cursor-=row['box'].height+gap
    fig.canvas.draw(); renderer=fig.canvas.get_renderer()
    # Annotation offsets use a display transform, so checking only transData
    # labels misses company names near the right edge of scatter panels.
    # Constrain text after final column widths and row positions are known.
    for ax in active_axes:
        bounds=ax.get_window_extent(renderer)
        inset=2*pt
        for label in ax.texts:
            if not label.get_visible() or not label.get_text().strip():
                continue
            bb=Text.get_window_extent(label,renderer)
            if bb.width>bounds.width-2*inset:
                label.set_text(_wrap_measured(label.get_text(),renderer,bounds.width-2*inset,label.get_fontsize()))
                fig.canvas.draw(); renderer=fig.canvas.get_renderer()
                bb=Text.get_window_extent(label,renderer)
            dx=max(bounds.x0+inset-bb.x0,0)-max(bb.x1-(bounds.x1-inset),0)
            dy=max(bounds.y0+inset-bb.y0,0)-max(bb.y1-(bounds.y1-inset),0)
            if dx or dy:
                transform=label.get_transform()
                anchor=transform.transform(label.get_position())
                label.set_position(transform.inverted().transform((anchor[0]+dx,anchor[1]+dy)))
    fig.canvas.draw(); renderer=fig.canvas.get_renderer()
    boxes=[Bbox.union([a.get_tightbbox(renderer) for a in row['axes']]) for row in rows]
    header=(fig.legends[0].get_window_extent(renderer).y0 if fig.legends else
            subtitle.get_window_extent(renderer).y0 if subtitle is not None else
            fig._suptitle.get_window_extent(renderer).y0 if fig._suptitle else newheight-edge)
    has_header=bool(fig.legends or subtitle is not None or fig._suptitle is not None)
    audit={'measured':True,'native':True,'header_gap_pt':(header-boxes[0].y1)/pt if has_header else None,
           'row_gaps_pt':[(a.y0-b.y1)/pt for a,b in zip(boxes,boxes[1:])],
           'footer_gap_pt':(boxes[-1].y0-fig._native_footer.get_window_extent(renderer).y1)/pt if hasattr(fig,'_native_footer') else None}
    audit['text_collisions']=[]
    audit['text_out_of_bounds']=[]
    for ax in active_axes:
        texts=[t for t in ax.texts if t.get_visible() and t.get_text().strip()]
        bounds=ax.get_window_extent(renderer)
        for label in texts:
            bb=Text.get_window_extent(label,renderer)
            if bb.x0<bounds.x0-.5 or bb.x1>bounds.x1+.5 or bb.y0<bounds.y0-.5 or bb.y1>bounds.y1+.5:
                audit['text_out_of_bounds'].append(label.get_text()[:100])
        for i,first in enumerate(texts):
            for second in texts[i+1:]:
                if Text.get_window_extent(first,renderer).overlaps(Text.get_window_extent(second,renderer)):
                    audit['text_collisions'].append([first.get_text()[:100],second.get_text()[:100]])
    fig._layout_audit=audit
    fig._layout_audit.update(figure_number_audit(fig))


def layout_text_panel(fig,ax):
    """Flow an informational text panel from measured wrapped text heights."""
    fig.canvas.draw(); renderer=fig.canvas.get_renderer(); pt=fig.dpi/72
    width=ax.get_window_extent(renderer).width
    items=[]
    for text in ax.texts:
        x=text.get_position()[0]
        raw=getattr(text,'_unwrapped_text',text.get_text()); text._unwrapped_text=raw
        text.set_text(_wrap_measured(raw,renderer,width*(1-x),text.get_fontsize()))
        text.set_transform(ax.transAxes); text.set_va('top')
        height=Text.get_window_extent(text,renderer).height
        items.append((text,x,height))
    height=sum(v[2] for v in items)+12*pt*max(0,len(items)-1)+12*pt
    position=ax.get_position()
    ax.set_position((position.x0,position.y0,position.width,height/fig.bbox.height))
    cursor=height-6*pt
    for text,x,h in items:
        text.set_position((x,cursor/height)); cursor-=h+12*pt
    fig._flow_text_only=True


def series_data(pack, key):
    rows = pack['history']
    present = sorted({int(r['period'][:4]) for r in rows})
    years = list(range(present[0],present[-1]+1)) if present else []
    q = (pd.Timestamp(pack['latest_period']).month-1)//3+1
    lookup = {r['period']:r for r in rows}
    def value(year, quarter, annual=False):
        month = quarter*3
        date = pd.Timestamp(year,month,1)+pd.offsets.MonthEnd()
        row = lookup.get(str(date.date()))
        if row is None:
            return None
        return row['cumulative_values' if annual else 'values'].get(key)
    annual = [value(y,4,True) for y in years]
    quarters = [[value(y,k) for y in years] for k in (1,2,3,4)]
    # Different metrics can start later (e.g. complete debt components).
    # Trim empty leading years instead of filling half a panel with no data.
    populated=[i for i in range(len(years)) if annual[i] is not None or any(seq[i] is not None for seq in quarters)]
    if populated:
        first=populated[0]
        years=years[first:]; annual=annual[first:]; quarters=[seq[first:] for seq in quarters]
    return {'years':years,'annual':annual,'quarters':quarters,
            'annual_yoy':annual_growth(pack,key,years),'quarter':q}


def growth_line_evidence(fig):
    """Read actual right-axis artists, including unexpected extra growth lines."""
    metrics = {}
    for ax in fig.axes:
        if not hasattr(ax,'_metric_key'):
            continue
        key=ax._metric_key
        years=fig._history_series[key]['years']
        lines=[]
        for line in ax._history_twin.lines:
            if str(line.get_label()).startswith('_'):
                continue
            points=[float(x) for x in line.get_xdata()]
            lines.append({'label':line.get_label(),
                          'years':[years[int(x)] if x.is_integer() and 0<=x<len(years) else None for x in points],
                          'values':[float(v) if v is not None and math.isfinite(float(v)) else None for v in line.get_ydata()],
                          'unit':'pp' if key in RATIOS else '亿元' if key == 'net_cash' else 'percent'})
        metrics[key]=lines
    return {'policy':'annual_yoy_only','metrics':metrics,
            'legend_labels':[t.get_text() for legend in fig.legends for t in legend.get_texts()]}


def growth_line_failures(pack,chart_id,evidence,ops=None):
    """Reject quarter growth lines, wrong FY values, and invented annual points."""
    failures=[]
    if evidence.get('policy')!='annual_yoy_only':
        failures.append('缺少仅年度同比折线契约')
    labels=evidence.get('legend_labels',[])
    if labels.count('年度同比')!=1 or any('环比' in s or ('同比' in s and s!='年度同比') for s in labels):
        failures.append('图例必须仅保留一项年度同比，不得包含季度同比/环比')
    for key in CHART_METRICS[chart_id]:
        years=series_data(pack,key)['years']
        if chart_id=='图12':
            years=years+[int(str(y).rstrip('E')) for y in (ops or {}).get('forecast',{}).get('labels_fcast',[]) if int(str(y).rstrip('E')) not in years]
        expected={'label':'年度同比','years':years,'values':annual_growth(pack,key,years),
                  'unit':'pp' if key in RATIOS else '亿元' if key == 'net_cash' else 'percent'}
        lines=evidence.get('metrics',{}).get(key,[])
        if len(lines)!=1:
            failures.append(f'{key}必须只有一条年度同比增长线')
            continue
        line=lines[0]
        actual=line.get('values',[])
        correct=(len(actual)==len(expected['values']) and all(
            a is None and b is None or isinstance(a,(int,float)) and b is not None and math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-7)
            for a,b in zip(actual,expected['values'])))
        if any(line.get(field)!=expected[field] for field in ('label','years','unit')) or not correct:
            failures.append(f'{key}年度同比须由相邻完整财年计算，未完年/缺失基期留空')
    return failures


def format_growth_axis(ax):
    """Keep small annual changes readable without duplicate rounded tick labels.

    纵向缩减折线波动跨度：增加上下留白缓冲（约 40%~45%），避免折线顶天立地，
    使折线在图表面板中间区域优雅波动，与柱状图更具协调性与呼吸感。
    """
    lower, upper = ax.get_ylim()
    span = upper - lower
    if upper > 500 or (upper - lower) > 800:
        # 极值保护：避免极端离群同比（如+3798%）导致常规变动区间被压扁
        ax.set_yscale('symlog', linthresh=100)
        new_top = upper * 2.5 if upper > 0 else upper
        new_bot = lower * 1.5 if lower < 0 else lower - 50
        ax.set_ylim(new_bot, new_top)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value,_: format_number(0 if abs(value)<1e-10 else value)))
    elif span < .06:
        lower = math.floor(lower * 100) / 100
        upper = math.ceil(upper * 100) / 100
        pad = max((upper - lower) * 0.45, 0.02)
        ax.set_ylim(lower - pad, max(upper + pad, lower + .01))
        ax.yaxis.set_major_locator(MultipleLocator(.01))
    else:
        # 常规线性比例：向上下各扩展 45% 的缓冲空间，将折线纵向跨度压缩至绘图区约 50% 高度
        pad = span * 0.45
        ax.set_ylim(lower - pad, upper + pad)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 5, 10]))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value,_: format_number(0 if abs(value)<1e-10 else value)))


def number_unit(key):
    return ('%',1) if key in RATIOS else ('元',1) if key == 'bps' else ('亿元',1e8)


def metric_name(key):
    if key == 'roe':
        return '加权ROE（报告期累计、未年化）'
    return NAMES[key].replace('累计','单季') if key not in STOCKS else NAMES[key]


def fig_history(pack, chart_id, ops=None):
    keys = CHART_METRICS[chart_id]
    year_count=len({r['period'][:4] for r in pack['history']})
    width=min(18,max(11,4.0+.88*year_count))
    fig, axes = plt.subplots(len(keys),1,figsize=(width,max(6.8,4.8*len(keys))),squeeze=False)
    actual_values, artists, all_series = {}, {}, {}
    for index,key in enumerate(keys):
        ax = axes[index,0]
        ax._metric_key=key
        d = series_data(pack,key)
        forecast = (ops or {}).get('forecast',{}) if chart_id == '图12' else {}
        if forecast:
            future_years = [int(str(v).rstrip('E')) for v in forecast.get('labels_fcast',[])]
            for year in future_years:
                if year not in d['years']:
                    d['years'].append(year)
                    for field in ('annual','annual_yoy'):
                        d[field].append(None)
                    for series in d['quarters']:
                        series.append(None)
        all_series[key] = d
        years, q = d['years'],d['quarter']
        x = np.arange(len(years),dtype=float)
        unit, divisor = number_unit(key)
        scale = lambda vals:[np.nan if v is None else v/divisor for v in vals]
        annual_bars=ax.bar(x,scale(d['annual']),width=.84,facecolor='none',edgecolor='#5774A9',linewidth=1.1,zorder=1,label='年度（空心）')
        for year,bar,val in zip(years,annual_bars,d['annual']):
            if val is None:
                continue
            text=ax.annotate(format_number(val/divisor),(bar.get_x()+bar.get_width()/2,val/divisor),
                             xytext=(0,8 if val>=0 else -8),textcoords='offset points',ha='center',
                             va='bottom' if val>=0 else 'top',fontsize=8.5,fontweight='bold',color='#1e293b',
                             bbox=dict(boxstyle='round,pad=0.2',facecolor='white',edgecolor='#94a3b8',alpha=.92,linewidth=.5),
                             arrowprops=dict(arrowstyle='-',color='#94a3b8',linewidth=.4))
            text._bar_value_label=True; text._annual_label=True; text._initial_offset=text.get_position()
            text._bar_label_value=val/divisor
        rendered = {}
        for k,offset in enumerate((-.27,-.09,.09,.27)):
            bars = ax.bar(x+offset,scale(d['quarters'][k]),width=.14,color=COLORS[k],zorder=3,label=f'Q{k+1}')
            for year,bar in zip(years,bars):
                height = bar.get_height()
                rendered[(year,k+1)] = float(height)*divisor if math.isfinite(height) else None
            for i,p in enumerate(bars):
                val=d['quarters'][k][i]
                if val is not None:
                    text=ax.annotate(format_number(val/divisor),(p.get_x()+p.get_width()/2,val/divisor),
                                     xytext=(0,3 if val>=0 else -3),textcoords='offset points',ha='center',
                                     va='bottom' if val>=0 else 'top',fontsize=6.0,color=COLORS[k],
                                     bbox=dict(facecolor='white',edgecolor='none',alpha=.88,pad=.2),
                                     arrowprops=dict(arrowstyle='-',color='#B1B8C3',linewidth=.3))
                    text._bar_value_label=True; text._annual_label=False; text._initial_offset=text.get_position()
                    text._bar_label_value=val/divisor
        ax.axhline(0,color='#BFC5CD',linewidth=.7)
        ax.grid(axis='y',color='#F1F5F9',linestyle='-',linewidth=.8)
        ax.set_axisbelow(True)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#E2E8F0')
        ax.spines['bottom'].set_color('#CBD5E1')
        ax.set_ylabel(f'{metric_name(key)}（{unit}）',fontsize=9.8,labelpad=12)
        ax.set_xticks(x,[str(y) for y in years],fontsize=9)
        ax.tick_params(axis='x', pad=7, labelsize=8.8)
        ax.tick_params(axis='y', pad=7, labelsize=8.5)
        ax.set_xlim(-.65,len(years)-.35)
        for i,year in enumerate(years):
            if d['annual'][i] is None and all(seq[i] is None for seq in d['quarters']):
                ax.text(i,.03,'未披露',transform=ax.get_xaxis_transform(),ha='center',fontsize=7,color='#8A9099')
        if forecast:
            hist_anchor_year = None
            for y in reversed(years):
                if y < min(future_years):
                    idx = years.index(y)
                    if d['annual'][idx] is not None:
                        hist_anchor_year = y
                        break
            anchor_x = [years.index(hist_anchor_year)] if hist_anchor_year is not None else []
            anchor_val = d['annual'][years.index(hist_anchor_year)] / divisor if hist_anchor_year is not None else None
            for name,color,style in (('悲观','#C44E52','--'),('基准','#4C72B0','-'),('乐观','#55A868','-.')):
                if name in forecast:
                    x_pts = anchor_x + [years.index(y) for y in future_years]
                    y_pts = ([anchor_val] if anchor_val is not None else []) + list(forecast[name])
                    ax.plot(x_pts, y_pts, marker='D', color=color, linestyle=style, linewidth=1.8, label=name+'全年预测')
        ax.margins(y=.28)
        right = ax.twinx()
        ax._history_twin=right
        right.spines['top'].set_visible(False)
        right.spines['left'].set_visible(False)
        right.spines['right'].set_color('#E2E8F0')
        right.spines['bottom'].set_color('#CBD5E1')
        right.plot(x,d['annual_yoy'],color='#D78A16',marker='o',markersize=3,linewidth=1.6,label='年度同比')
        right.set_ylabel('年度变动（百分点）' if key in RATIOS else '年度净变动（亿元）' if key == 'net_cash' else '年度同比（%）',fontsize=9,color='#806634',labelpad=12)
        right.tick_params(axis='y',labelsize=8.5,pad=7)
        right.axhline(0,color='#D6CDBA',linewidth=.5,linestyle='--')
        format_growth_axis(right)
        for label in right.get_yticklabels():
            label.set_color('#806634')
        latest_value=pack['quarter_comparisons'][-1]['values'].get(key)
        formatted='未披露' if latest_value is None else f'{format_number(latest_value/divisor)}{unit}'
        ax._history_title=f"{metric_name(key)}\n最新{pack['quarter_comparisons'][-1]['label']}：{formatted}"
        ax.set_title(ax._history_title,loc='left',fontsize=10.5,fontweight='bold',pad=12)
        # The current year is highlighted; no fictitious annual/YTD-as-FY bar.
        latest_index = years.index(int(pack['latest_period'][:4]))
        ax.axvspan(latest_index-.45,latest_index+.45,color='#FFF1D8',alpha=.40,zorder=0)
        actual_values[key] = [rendered.get((int(r['period'][:4]),(int(r['period'][5:7])-1)//3+1)) for r in pack['quarter_comparisons']]
    handles = [Patch(facecolor='none',edgecolor='#5774A9',label='年度（空心；仅完整年）')]
    handles += [Patch(facecolor=c,label=f'Q{k+1}') for k,c in enumerate(COLORS)]
    handles += [Line2D([],[],color='#D78A16',marker='o',label='年度同比')]
    if chart_id == '图12':
        handles += [Line2D([],[],color=color,marker='D',label=name+'全年预测') for name,color in (('悲观','#C44E52'),('基准','#4C72B0'),('乐观','#55A868'))]
    fig.suptitle(f'{chart_id} {TITLES[chart_id]}｜年度与季度分组',fontsize=14,fontweight='bold',y=.995)
    fig._legend_handles=handles
    fig._legend_columns=len(handles)
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.5,.967),ncol=fig._legend_columns,frameon=False,fontsize=8.5,borderaxespad=0,columnspacing=1.1,handletextpad=.6)
    fig.subplots_adjust(left=.10,right=.90,top=.87,bottom=.10,hspace=.55)
    footer=f"来源：原始三表；最新实际{pack['latest_period']}。橙线仅为相邻完整年度同比，率类/净额类为年度变动（百分点/亿元）；未完年不画年度同比点。\n流量为单季，资产类为期末，季度ROE为累计、未年化；负基数或跨零变动率按|(current-prior)/prior|方向计量。\n数字最多{MAX_LABEL_DECIMALS}位小数；极小非零值用<0.01或>-0.01表示（单位同轴），原始计算不舍入。"
    fig._history_footer_text=footer
    fig._history_footer=fig.text(.5,.012,footer,ha='center',va='bottom',fontsize=8,color='#6B7280')
    fig._latest_period = pack['latest_period']
    fig._latest_chart_id = chart_id
    fig._latest_values = actual_values
    fig._display_basis = 'year_grouped_annual_quarters; flows=single_quarter; stocks=end; ROE=YTD'
    fig._integrated_latest = True
    fig._year_grouped = True
    fig._history_series = all_series
    fig._legend_top = True
    return fig


def write_interactive(pack,ops,out,title):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    panels=[]
    keys = list(dict.fromkeys(k for values in CHART_METRICS.values() for k in values))
    for key in keys:
        d=series_data(pack,key); unit,divisor=number_unit(key)
        fig=make_subplots(specs=[[{'secondary_y':True}]])
        years=d['years']; q=d['quarter']
        fig.add_trace(go.Bar(x=years,y=[None if v is None else v/divisor for v in d['annual']],name='年度（完整年）',marker=dict(color='rgba(70,100,160,.06)',line=dict(color='#5774A9',width=1.2)),width=.84,offset=-.42),secondary_y=False)
        for k,offset in enumerate((-.34,-.16,.02,.20)):
            fig.add_trace(go.Bar(x=years,y=[None if v is None else v/divisor for v in d['quarters'][k]],name=f'Q{k+1}',marker_color=COLORS[k],width=.14,offset=offset),secondary_y=False)
        fig.add_trace(go.Scatter(x=years,y=d['annual_yoy'],name='年度同比',mode='lines+markers',line_color='#D78A16',connectgaps=False),secondary_y=True)
        fig.update_layout(title=f"{metric_name(key)}｜年度同比与季度实际",height=460,
                          template='plotly_white',barmode='overlay',legend=dict(orientation='h',y=1.1,x=.5,xanchor='center'),margin=dict(l=75,r=75,t=110,b=60))
        for trace in fig.data:
            trace.update(customdata=[format_number(v) if v is not None else '未披露' for v in trace.y],
                         hovertemplate='%{x}<br>%{customdata}<extra>%{fullData.name}</extra>')
        fig.update_yaxes(title_text=unit,secondary_y=False)
        growth_axis={'tickformat':',.2~f'}
        finite=[v for v in d['annual_yoy'] if v is not None and math.isfinite(v)]
        if finite and max([0,*finite])-min([0,*finite])<.06:
            lower=math.floor(min([0,*finite])*100)/100
            upper=math.ceil(max([0,*finite])*100)/100
            growth_axis.update(tick0=0,dtick=.01,range=[lower,max(upper,lower+.01)])
        fig.update_yaxes(title_text='百分点' if key in RATIOS else '%',secondary_y=True,**growth_axis)
        fig.update_xaxes(dtick=1,rangeslider_visible=True)
        panels.append(fig)
    for section,value_keys in (('pe_band',('pe_ttm','pe_low','pe_high')),('pb_band',('pb','pb_low','pb_high'))):
        d=ops.get(section,{})
        if d:
            fig=go.Figure()
            for key in value_keys:
                fig.add_trace(go.Scatter(x=d['labels'],y=d[key],name=key))
            for trace in fig.data:
                trace.update(customdata=[format_number(v) if v is not None else '未披露' for v in trace.y],
                             hovertemplate='%{x}<br>%{customdata}<extra>%{fullData.name}</extra>')
            fig.update_layout(title=section,height=420,template='plotly_white',legend=dict(orientation='h'),margin=dict(r=40))
            panels.append(fig)
    html=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+title+'</title><style>body{font-family:Microsoft YaHei,Arial;background:#f6f8fb;color:#182332;margin:24px auto;max-width:1180px;padding:0 20px}section{background:white;border-radius:10px;margin:20px 0;padding:12px}h1{font-size:23px}p{line-height:1.7}</style><h1>'+title+'</h1>',
          '<p>每年一组：完整年度空心柱、Q1—Q4季度蓝柱；未完年度不画全年柱。橙线仅为相邻完整年度同比，率类为年度变动（百分点）；未完年、基期缺失、负基数或跨零不画增长点。季度ROE为累计披露、未年化。显示最多2位小数；极小非零值用&lt;0.01或&gt;-0.01表示（单位同轴），原始计算不舍入。</p>']
    for i,fig in enumerate(panels):
        html.append('<section>'+fig.to_html(full_html=False,include_plotlyjs=True if i==0 else False)+'</section>')
    html.append('</html>')
    Path(out).write_text('\n'.join(html),encoding='utf-8')
    return len(panels)
