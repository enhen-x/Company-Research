"""Empty pie category labels must not displace visible ring percentages."""
import math

import matplotlib.pyplot as plt
import pytest

from analyze_charts import fig_segment, _auto_fix_layout


@pytest.mark.parametrize('labels', [['2023','2024','2025'],['2023','2024','2025','2026H1']])
def test_ring_percentages_keep_their_data_anchor(labels):
    ops={'segment':{'labels':labels,'series':[
        {'name':name,'values':[value]*len(labels)}
        for name,value in [('营养品',66),('香料',18),('材料',10),('其他',6)]
    ]}}
    fig=fig_segment(ops)
    fig.tight_layout()
    _auto_fix_layout(fig)
    fig.canvas.draw()
    for ax in fig.axes:
        for label in ax.texts:
            assert label.get_text().strip()
            if '%' in label.get_text():
                x,y=ax.transData.inverted().transform(label.get_transform().transform(label.get_position()))
                assert math.hypot(x,y)==pytest.approx(.8,abs=.001)
    plt.close(fig)


def test_native_legend_keeps_series_owned_by_twin_axis():
    from financial_history_charts import layout_native
    fig,ax=plt.subplots(figsize=(10,5))
    twin=ax.twinx()
    cost=ax.plot([0,1],[7,8],label='Cost')[0]
    price=twin.plot([0,1],[40,50],label='Price')[0]
    ax.legend([cost,price],['Cost','Price'])
    layout_native(fig)
    assert {t.get_text() for t in fig.legends[0].get_texts()}=={'Cost','Price'}
    plt.close(fig)
