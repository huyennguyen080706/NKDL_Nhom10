"""Quy ước trình bày biểu đồ dùng chung cho dashboard.

- Màu gán theo VAI TRÒ và theo thực thể (cổ phiếu luôn xanh dương, VN-Index luôn cam), không theo thứ hạng.
- Mỗi biểu đồ một trục giá trị; hai thước đo khác đơn vị đặt ở hai khung riêng dùng chung trục thời gian.
- Màu trạng thái (OK/WARN/FAIL) tách riêng khỏi màu chuỗi và luôn đi kèm biểu tượng + nhãn chữ.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Chuỗi phân loại (thứ tự cố định)
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
STOCK, INDEX = BLUE, ORANGE          # thực thể
SMA20, SMA50 = ORANGE, "#6250d6"     # đường trung bình trên nền nến
# Phân cực (tăng/giảm, dương/âm) - cặp diverging xanh dương <-> đỏ
POSITIVE, NEGATIVE, NEUTRAL = "#2a78d6", "#e34948", "#898781"
# Trạng thái (cố định, không dùng làm màu chuỗi)
STATUS = {"OK": "#0ca30c", "WARN": "#fab219", "FAIL": "#d03b3b"}
STATUS_ICON = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}
# Mực và khung
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#fcfcfb"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def style(fig: go.Figure, height: int = 360, title: str | None = None, legend: bool = True,
          y_title: str | None = None, y_format: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height,
        title=dict(text=title or "", font=dict(size=15, color=INK), x=0, xanchor="left"),
        font=dict(family=FONT, size=12, color=INK_2),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        margin=dict(l=8, r=8, t=48 if title else 16, b=8),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#ffffff", font=dict(family=FONT, size=12, color=INK)),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, title=None),
        bargap=0.25,
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickcolor=AXIS, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=SURFACE, tickfont=dict(color=MUTED))
    # Chỉ áp cho biểu đồ một khung; biểu đồ nhiều khung tự đặt tiêu đề trục theo từng hàng.
    if y_title:
        fig.update_yaxes(title=dict(text=y_title, font=dict(color=MUTED, size=11)))
    if y_format:
        fig.update_yaxes(tickformat=y_format)
    return fig


def show(fig: go.Figure, key: str | None = None) -> None:
    st.plotly_chart(fig, width="stretch", key=key, config={"displaylogo": False, "modeBarButtonsToRemove": [
        "lasso2d", "select2d", "autoScale2d"]})


def table(df: pd.DataFrame, **kwargs) -> None:
    st.dataframe(df, width="stretch", hide_index=True, **kwargs)


def line(df: pd.DataFrame, x: str, series: dict[str, tuple[str, str]], hover_format: str = ",.2f") -> go.Figure:
    """series: {cột: (tên hiển thị, màu)}"""
    fig = go.Figure()
    for col, (name, color) in series.items():
        fig.add_trace(go.Scatter(
            x=df[x], y=df[col], name=name, mode="lines", line=dict(color=color, width=2),
            hovertemplate=f"%{{y:{hover_format}}}<extra>{name}</extra>",
        ))
    return fig


def signed_hbar(df: pd.DataFrame, label: str, value: str, hover_format: str = "+.1%",
                highlight: str | None = None) -> go.Figure:
    """Thanh ngang theo dấu: dương xanh dương, âm đỏ. Chiều cao tự giãn theo số dòng."""
    d = df.sort_values(value)
    colors = [POSITIVE if v >= 0 else NEGATIVE for v in d[value]]
    fig = go.Figure(go.Bar(
        x=d[value], y=d[label], orientation="h", marker=dict(color=colors, line=dict(width=0)),
        hovertemplate=f"%{{y}}: %{{x:{hover_format}}}<extra></extra>",
    ))
    fig.update_layout(hovermode="closest")
    return fig


def fmt_pct(v, digits: int = 2, signed: bool = True) -> str:
    if v is None or pd.isna(v):
        return "–"
    return f"{v * 100:{'+' if signed else ''}.{digits}f}%"


def fmt_num(v, digits: int = 2) -> str:
    if v is None or pd.isna(v):
        return "–"
    return f"{v:,.{digits}f}"
