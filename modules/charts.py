"""plotly 차트 생성 함수 (PRD F5).

디자인 규칙 (dataviz):
- 단일 y축만 사용 (이중 축 금지). 달성률은 hover·직접 라벨·KPI로 전달한다.
- 리스크 등급은 상태 색상(config.RISK_COLORS) + 범례 라벨, 품목은 범주형 슬롯을 고정 순서로 배정.
- 얇은 막대(모서리 4px), 2px 선, 8px 이상 마커, 막대/조각 사이 2px 표면색 간격, 옅은 실선 격자.
- 모든 함수는 dark 인자로 라이트/다크 팔레트를 고른다. st.plotly_chart(theme=None)로 렌더링한다.
"""

import pandas as pd
import plotly.graph_objects as go

import config as C
from modules import metrics as M
from modules import risk as R


def palette(dark: bool = False) -> dict:
    return C.CHART_THEMES["dark" if dark else "light"]


def item_colors(items: list[str], dark: bool = False) -> dict[str, str]:
    """품목 → 범주형 색. 전체 품목 목록(정렬) 기준 고정 배정 → 필터해도 색이 바뀌지 않는다."""
    series = palette(dark)["series"]
    return {item: series[i % len(series)] for i, item in enumerate(sorted(items))}


def _style(fig: go.Figure, p: dict, title: str | None, height: int, legend: bool = True) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=p["ink"]), x=0, xanchor="left", y=0.97) if title else None,
        height=height,
        margin=dict(l=64, r=24, t=72 if title else 16, b=48),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=C.CHART_FONT, size=12, color=p["ink2"]),
        showlegend=legend,
        legend=dict(orientation="h", x=0, xanchor="left", y=1.0, yanchor="bottom", bgcolor="rgba(0,0,0,0)",
                    font=dict(color=p["ink2"])),
        hoverlabel=dict(bgcolor=p["surface"], bordercolor=p["axis"], font=dict(family=C.CHART_FONT, color=p["ink"])),
        barcornerradius=4,
        separators=".,",
    )
    axis = dict(gridcolor=p["grid"], griddash="solid", linecolor=p["axis"], zerolinecolor=p["axis"],
                tickfont=dict(color=p["muted"]), title_font=dict(color=p["ink2"]))
    fig.update_xaxes(**axis, showgrid=False, automargin=True)
    fig.update_yaxes(**axis, showgrid=True, automargin=True)
    return fig


def _empty(msg: str = "표시할 데이터가 없습니다", dark: bool = False, height: int = 300) -> go.Figure:
    p = palette(dark)
    fig = go.Figure()
    fig.add_annotation(text=msg, showarrow=False, font=dict(size=14, color=p["muted"]))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return _style(fig, p, None, height, legend=False)


def trend_chart(monthly: pd.DataFrame, title: str = "월별 입고량 vs 목표량", dark: bool = False) -> go.Figure:
    """월별 입고량(막대) vs 목표량(선). 달성률은 hover와 최근월 직접 라벨로 표시(단일 축)."""
    if monthly.empty:
        return _empty(dark=dark)
    p = palette(dark)
    x = monthly[C.COL_MONTH].dt.strftime("%Y-%m")
    ach = monthly[M.M_ACH]
    fig = go.Figure()
    fig.add_bar(
        x=x, y=monthly[C.COL_ACTUAL], name="입고량", marker=dict(color=p["series"][0], line=dict(width=0)),
        customdata=ach, hovertemplate="입고량 %{y:,.0f}톤 · 달성률 %{customdata:.1f}%<extra></extra>",
    )
    fig.add_scatter(
        x=x, y=monthly[C.COL_TARGET], name="목표량", mode="lines+markers",
        line=dict(color=p["reference"], width=2), marker=dict(size=8, color=p["reference"],
                                                              line=dict(width=2, color=p["surface"])),
        hovertemplate="목표량 %{y:,.0f}톤<extra></extra>",
    )
    last = monthly.iloc[-1]
    if pd.notna(last[M.M_ACH]):
        fig.add_annotation(
            x=x.iloc[-1], y=max(last[C.COL_ACTUAL], last[C.COL_TARGET]), yshift=14, showarrow=False,
            text=f"<b>{last[M.M_ACH]:.1f}%</b>", font=dict(color=p["ink"], size=12),
        )
    fig.update_layout(hovermode="x unified", bargap=0.5)
    fig.update_xaxes(type="category")
    fig.update_yaxes(tickformat=",.0f", rangemode="tozero")
    return _style(fig, p, f"{title} (톤)", 380)


def risk_donut(classified: pd.DataFrame, dark: bool = False) -> go.Figure:
    """리스크 등급 분포 도넛 (부분-전체, 3조각)."""
    if classified.empty:
        return _empty(dark=dark)
    p = palette(dark)
    counts = classified[R.RISK_LEVEL].value_counts().reindex(C.RISK_LEVELS, fill_value=0)
    counts = counts[counts > 0]  # 결과에 없는 등급은 조각·범례에서 제외
    fig = go.Figure(go.Pie(
        labels=list(counts.index), values=counts.values, hole=0.62, sort=False,
        direction="clockwise", marker=dict(colors=[C.RISK_COLORS[l] for l in counts.index],
                                           line=dict(color=p["surface"], width=2)),
        textinfo="value", texttemplate="%{value}개", textposition="outside", textfont=dict(color=p["ink"]),
        hovertemplate="%{label}: %{value}개 (%{percent})<extra></extra>", automargin=True,
    ))
    fig.add_annotation(text=f"<b>{int(counts.sum())}</b><br>협력사", showarrow=False,
                       font=dict(size=16, color=p["ink"]))
    fig = _style(fig, p, "리스크 등급 분포", 380)
    fig.update_layout(margin=dict(l=24, r=24, t=96, b=24))
    return fig


def category_bar(rows: pd.DataFrame, by: str, dark: bool = False) -> go.Figure:
    """지역별/품목별 목표량(회색) vs 입고량(파랑), 달성률은 입고량 막대 끝에 라벨. rows는 기준월 원천 행."""
    if rows.empty:
        return _empty(dark=dark)
    p = palette(dark)
    g = M.category_totals(rows, by).sort_values(C.COL_ACTUAL, ascending=False)
    fig = go.Figure()
    fig.add_bar(x=g[by], y=g[C.COL_TARGET], name="목표량", marker=dict(color=p["target_fill"]),
                hovertemplate="%{x} 목표량 %{y:,.0f}톤<extra></extra>")
    fig.add_bar(
        x=g[by], y=g[C.COL_ACTUAL], name="입고량", marker=dict(color=p["series"][0]),
        text=g[M.M_ACH].map(lambda v: f"{v:.0f}%" if pd.notna(v) else "N/A"), textposition="outside",
        textfont=dict(color=p["ink2"]), cliponaxis=False, customdata=g[M.M_ACH],
        hovertemplate="%{x} 입고량 %{y:,.0f}톤 · 달성률 %{customdata:.1f}%<extra></extra>",
    )
    fig.update_layout(barmode="group", bargap=0.45, bargroupgap=0.12)
    fig.update_yaxes(tickformat=",.0f")
    return _style(fig, p, f"{by}별 입고량 (톤) · 달성률", 360)


def quadrant_scatter(classified: pd.DataFrame, thresholds: dict, dark: bool = False) -> go.Figure:
    """달성률 × 과거평균 대비 증감률 4분면 산점도 (버블 = 연간 계약량). 고위험만 이름 직접 라벨."""
    d = classified.dropna(subset=[M.M_ACH, M.M_CHG])
    if d.empty:
        return _empty("달성률·증감률을 계산할 수 있는 협력사가 없습니다", dark=dark, height=460)
    p = palette(dark)
    t = {**C.DEFAULT_THRESHOLDS, **thresholds}
    x0, y0 = t["achievement_min"], t["change_max"]
    size_ref = max(d[M.M_CONTRACT].max(), 1)

    x_lo, x_hi = min(d[M.M_ACH].min(), x0) - 10, max(d[M.M_ACH].max(), 100) + 10
    y_lo, y_hi = min(d[M.M_CHG].min(), y0) - 10, max(d[M.M_CHG].max(), 0) + 10

    fig = go.Figure()
    fig.add_shape(type="rect", x0=x_lo, x1=x0, y0=y_lo, y1=y0, fillcolor=p["risk_zone"], line_width=0, layer="below")
    for lvl in C.RISK_LEVELS:
        s = d[d[R.RISK_LEVEL] == lvl]
        if s.empty:
            continue
        fig.add_scatter(
            x=s[M.M_ACH], y=s[M.M_CHG], mode="markers", name=lvl,
            marker=dict(size=s[M.M_CONTRACT].fillna(0) / size_ref * 32 + 10, color=C.RISK_COLORS[lvl], opacity=0.85,
                        line=dict(width=2, color=p["surface"])),
            customdata=s[[C.COL_NAME, R.RISK_REASON, M.M_CONTRACT]],
            hovertemplate="<b>%{customdata[0]}</b><br>달성률 %{x:.1f}% · 증감률 %{y:+.1f}%"
                          "<br>계약량 %{customdata[2]:,.0f}톤<br>%{customdata[1]}<extra></extra>",
        )
    # 고위험만 이름 직접 라벨. 가까이 모인 점은 하나의 라벨로 묶어 겹침 방지.
    tol_x, tol_y = (x_hi - x_lo) * 0.06, (y_hi - y_lo) * 0.06
    clusters: list[list] = []
    for _, r in d[d[R.RISK_LEVEL] == C.RISK_HIGH].sort_values(M.M_ACH).iterrows():
        for c in clusters:
            if abs(c[0][M.M_ACH] - r[M.M_ACH]) < tol_x and abs(c[0][M.M_CHG] - r[M.M_CHG]) < tol_y:
                c.append(r)
                break
        else:
            clusters.append([r])
    for c in clusters:
        names = [r[C.COL_NAME] for r in c]
        text = names[0] if len(names) == 1 else f"{names[0]} 외 {len(names) - 1}개사"
        fig.add_annotation(x=c[0][M.M_ACH], y=c[0][M.M_CHG], text=text, showarrow=False, xanchor="left",
                           xshift=16, font=dict(size=11, color=p["ink"]),
                           hovertext="<br>".join(names))
    for kw in (dict(x=x0), dict(y=y0)):
        (fig.add_vline if "x" in kw else fig.add_hline)(**kw, line=dict(color=p["muted"], width=1, dash="dash"))
    corner = dict(showarrow=False, font=dict(size=11, color=p["muted"]))
    fig.add_annotation(x=x0, y=y_lo, xanchor="right", yanchor="bottom", text="<b>목표 미달 · 입고 감소</b>",
                       **{**corner, "font": dict(size=11, color=C.RISK_COLORS[C.RISK_HIGH])})
    fig.add_annotation(x=x_hi, y=y_lo, xanchor="right", yanchor="bottom", text="목표 달성 · 입고 감소", **corner)
    fig.add_annotation(x=x_lo, y=y_hi, xanchor="left", yanchor="top", text="목표 미달 · 입고 유지", **corner)
    fig.add_annotation(x=x_hi, y=y_hi, xanchor="right", yanchor="top", text="목표 달성 · 입고 유지", **corner)
    fig.update_xaxes(title_text="목표 달성률(%)", range=[x_lo, x_hi], ticksuffix="%", showgrid=True, zeroline=False)
    fig.update_yaxes(title_text="과거평균 대비 증감률(%)", range=[y_lo, y_hi], ticksuffix="%")
    return _style(fig, p, "달성률 × 과거평균 대비 증감률", 480)


def ranking_bar(classified: pd.DataFrame, thresholds: dict | None = None, dark: bool = False) -> go.Figure:
    """협력사 달성률 순위 가로 막대 (낮은 순이 위). 리스크 업체만 값 직접 라벨."""
    d = classified.dropna(subset=[M.M_ACH]).sort_values(M.M_ACH, ascending=False)
    if d.empty:
        return _empty(dark=dark)
    p = palette(dark)
    t = {**C.DEFAULT_THRESHOLDS, **(thresholds or {})}
    fig = go.Figure()
    for lvl in C.RISK_LEVELS:  # 등급별 trace → 범례에 라벨 표시
        s = d[d[R.RISK_LEVEL] == lvl]
        if s.empty:
            continue
        fig.add_bar(
            x=s[M.M_ACH], y=s[C.COL_NAME], orientation="h", name=lvl,
            marker=dict(color=C.RISK_COLORS[lvl]),
            text=s[M.M_ACH].map(lambda v: f"{v:.1f}%") if lvl != C.RISK_NORMAL else None,
            textposition="outside", textfont=dict(color=p["ink2"]), cliponaxis=False,
            hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
        )
    fig.add_vline(x=100, line=dict(color=p["reference"], width=1))
    fig.add_vline(x=t["achievement_min"], line=dict(color=p["muted"], width=1, dash="dash"))
    fig.update_layout(bargap=0.3)
    fig.update_yaxes(type="category", categoryorder="array", categoryarray=list(d[C.COL_NAME]), showgrid=False)
    fig.update_xaxes(title_text="목표 달성률(%)", ticksuffix="%", showgrid=True)
    return _style(fig, p, "협력사 달성률 순위", max(320, 24 * len(d) + 110))


def supplier_detail_charts(rows: pd.DataFrame, supplier_code: str, ref_month: pd.Timestamp,
                           colors: dict[str, str] | None = None, dark: bool = False) -> dict[str, go.Figure]:
    """협력사 상세: 입고 vs 목표 추이, 품목별 구성(누적 막대), 품목별 단가 추이."""
    d = rows[(rows[C.COL_CODE] == supplier_code) & (rows[C.COL_MONTH] <= pd.Timestamp(ref_month))]
    if d.empty:
        return {k: _empty(dark=dark) for k in ("trend", "items", "price")}
    p = palette(dark)
    colors = colors or item_colors(d[C.COL_ITEM].unique().tolist(), dark)

    trend = trend_chart(M.monthly_totals(d), title="월별 입고량 vs 목표량", dark=dark)

    by_item = d.groupby([C.COL_MONTH, C.COL_ITEM], as_index=False)[C.COL_ACTUAL].sum()
    items = go.Figure()
    for item in sorted(by_item[C.COL_ITEM].unique()):
        s = by_item[by_item[C.COL_ITEM] == item]
        items.add_bar(x=s[C.COL_MONTH].dt.strftime("%Y-%m"), y=s[C.COL_ACTUAL], name=item,
                      marker=dict(color=colors.get(item), line=dict(color=p["surface"], width=2)),
                      hovertemplate=f"{item} " + "%{y:,.0f}톤<extra></extra>")
    items.update_layout(barmode="stack", bargap=0.5, hovermode="x unified")
    items.update_xaxes(type="category")
    items.update_yaxes(tickformat=",.0f")
    items = _style(items, p, "품목별 입고 구성 (톤)", 340)

    price = go.Figure()
    for item in sorted(d[C.COL_ITEM].unique()):
        s = d[d[C.COL_ITEM] == item].groupby(C.COL_MONTH, as_index=False)[C.COL_PRICE].mean()
        price.add_scatter(x=s[C.COL_MONTH].dt.strftime("%Y-%m"), y=s[C.COL_PRICE], name=item, mode="lines+markers",
                          line=dict(color=colors.get(item), width=2),
                          marker=dict(size=8, color=colors.get(item), line=dict(width=2, color=p["surface"])),
                          hovertemplate=f"{item} " + "%{y:,.0f}원/톤<extra></extra>")
    price.update_layout(hovermode="x unified")
    price.update_xaxes(type="category")
    price.update_yaxes(tickformat=",.0f")
    price = _style(price, p, "품목별 단가 추이 (원/톤)", 340)

    return {"trend": trend, "items": items, "price": price}
