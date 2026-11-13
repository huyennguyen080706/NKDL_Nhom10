"""Quy ước trình bày biểu đồ dùng chung cho dashboard.

- Màu gán theo VAI TRÒ và theo thực thể (cổ phiếu luôn tím #6425FE, VN-Index luôn cam), không theo thứ hạng.
- Mỗi biểu đồ một trục giá trị; hai thước đo khác đơn vị đặt ở hai khung riêng dùng chung trục thời gian.
- Màu trạng thái (OK/WARN/FAIL) tách riêng khỏi màu chuỗi và luôn đi kèm biểu tượng + nhãn chữ.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Chuỗi phân loại (thứ tự cố định). Tím = thực thể chính (cổ phiếu), cam = VN-Index.
PURPLE, ORANGE, MINT, YELLOW, BLUE = "#6425FE", "#F08A24", "#19B38A", "#EDA100", "#4A90E2"
STOCK, INDEX = PURPLE, ORANGE        # thực thể
SMA20, SMA50, SMA200 = ORANGE, BLUE, "#292929"     # đường trung bình trên nền nến
# Phân cực (tăng/giảm, dương/âm): xanh lá <-> đỏ, luôn kèm dấu +/- ở nhãn
POSITIVE, NEGATIVE, NEUTRAL = "#12A67A", "#E5484D", "#A59EB5"
AQUA = MINT
# Trạng thái (cố định, không dùng làm màu chuỗi)
STATUS = {"OK": "#0ca30c", "WARN": "#fab219", "FAIL": "#d03b3b"}
STATUS_ICON = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}
# Dải màu tuần tự cho heatmap tương quan: xanh dương - trắng - tím đậm
DIVERGING = [[0, "#4A90E2"], [0.5, "#FFFFFF"], [1, "#6425FE"]]
# Mực và khung
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#292929", "#4B4560", "#756D84", "#EFEAF8", "#D9D3E6", "#FFFFFF"
FONT = 'Inter, "Segoe UI", system-ui, -apple-system, sans-serif'


def style(fig: go.Figure, height: int = 360, title: str | None = None, legend: bool = True,
          y_title: str | None = None, y_format: str | None = None) -> go.Figure:
    fig.update_layout(
        height=height,
        title=dict(text=title or "", font=dict(size=15, color=INK), x=0, xanchor="left"),
        font=dict(family=FONT, size=12, color=INK_2),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        margin=dict(l=8, r=8, t=48 if title else 16, b=8),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#ffffff", bordercolor="#D9D3E6", font=dict(family=FONT, size=12, color=INK)),
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


# ------------------------------------------------------------------ biểu đồ phân tích (P1/P2)
def corr_heatmap(m: pd.DataFrame, height: int = 720) -> go.Figure:
    """Ma trận tương quan đối xứng, thang cố định [-1, 1]. Ô NaN (thiếu ngày chung) để trống."""
    fig = go.Figure(go.Heatmap(
        z=m.values, x=m.columns, y=m.index, zmin=-1, zmax=1, colorscale=DIVERGING, xgap=1, ygap=1,
        colorbar=dict(title="Pearson", thickness=12, len=0.7),
        hovertemplate="%{y} – %{x}: %{z:.2f}<extra></extra>"))
    fig.update_layout(hovermode="closest")
    style(fig, height=height, legend=False)
    fig.update_yaxes(autorange="reversed", showgrid=False, tickfont=dict(size=10))
    fig.update_xaxes(showgrid=False, tickangle=-90, tickfont=dict(size=10), side="bottom")
    return fig


def risk_return_scatter(df: pd.DataFrame, x: str, y: str, label: str, size_hint: str | None = None) -> go.Figure:
    """Mỗi chấm một mã: trục X rủi ro (biến động quy năm), trục Y lợi suất quy năm."""
    fig = go.Figure(go.Scatter(
        x=df[x], y=df[y], mode="markers+text", text=df[label], textposition="top center",
        textfont=dict(size=10, color=MUTED),
        marker=dict(size=11, color=[POSITIVE if v >= 0 else NEGATIVE for v in df[y]], opacity=0.85,
                    line=dict(color="#ffffff", width=1)),
        hovertemplate="<b>%{text}</b><br>Biến động: %{x:.1%}<br>Lợi suất: %{y:+.1%}<extra></extra>"))
    fig.update_layout(hovermode="closest")
    style(fig, height=460, legend=False)
    fig.update_xaxes(title=dict(text="Biến động quy năm (độ lệch chuẩn × √252)", font=dict(color=MUTED, size=11)),
                     tickformat=".0%", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(title=dict(text="Lợi suất quy năm (price return)", font=dict(color=MUTED, size=11)),
                     tickformat="+.0%", zeroline=True, zerolinecolor=AXIS)
    return fig


def histogram(values: pd.Series, name: str, var_line: float | None = None) -> go.Figure:
    fig = go.Figure(go.Histogram(x=values, nbinsx=40, marker=dict(color=PURPLE, line=dict(width=0)), opacity=0.85,
                                 hovertemplate="%{x:.2%}: %{y} phiên<extra></extra>"))
    fig.update_layout(hovermode="closest", bargap=0.05)
    if var_line is not None:
        fig.add_vline(x=-var_line, line=dict(color=NEGATIVE, width=2, dash="dash"),
                      annotation_text=f"−VaR95 {var_line:.1%}", annotation_position="top left",
                      annotation_font=dict(color=INK_2, size=11))
    style(fig, height=300, legend=False, title=name)
    fig.update_xaxes(tickformat=".1%", title=dict(text="Lợi suất ngày", font=dict(color=MUTED, size=11)))
    fig.update_yaxes(title=dict(text="Số phiên", font=dict(color=MUTED, size=11)))
    return fig


def donut(labels, values, title: str | None = None) -> go.Figure:
    palette = [PURPLE, MINT, YELLOW, BLUE, ORANGE, "#B18CFF", "#7FD8BE", "#F2C14E", "#8DB8F0", "#F6A96A"]
    fig = go.Figure(go.Pie(labels=labels, values=values, hole=0.58, sort=False, textinfo="label+percent",
                           marker=dict(colors=palette[: len(labels)], line=dict(color="#ffffff", width=2)),
                           hovertemplate="%{label}: %{percent}<extra></extra>"))
    fig.update_layout(hovermode="closest")
    style(fig, height=320, legend=False, title=title)
    return fig
