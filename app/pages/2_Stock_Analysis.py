"""Trang 2 - Phân tích một mã. Nguồn Gold: fact_price_daily, mart_technical_indicators,
mart_stock_vs_index, dim_ticker."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from components import charts
from services import warehouse as wh

st.set_page_config(page_title="Stock Analysis", page_icon="🕯️", layout="wide")
wh.require_warehouse()
st.title("Stock Analysis")

lo, hi = wh.price_date_bounds()
symbols = wh.symbols()
PRESETS = {"3 tháng": 91, "6 tháng": 182, "1 năm": 365, "3 năm": 1096, "Toàn bộ": None}
with st.sidebar:
    st.header("Bộ lọc")
    symbol = st.selectbox("Mã cổ phiếu", symbols, index=symbols.index("FPT") if "FPT" in symbols else 0)
    preset = st.radio("Khoảng thời gian", list(PRESETS), index=2)
    start = lo if PRESETS[preset] is None else max(lo, hi - pd.Timedelta(days=PRESETS[preset]))
    show_sma = st.checkbox("Hiện SMA20 / SMA50", value=True)

df = wh.query("""
    select p.trade_date, p.open, p.high, p.low, p.close, p.volume,
           m.daily_return, m.sma20, m.sma50, m.rsi14, m.volatility_20d_annualized, m.drawdown,
           m.return_20d, m.volume_ratio_20d
    from gold.fact_price_daily p
    join gold.mart_technical_indicators m using (ticker_key, date_key)
    where p.symbol = ? and p.trade_date between ? and ?
    order by p.trade_date""", (symbol, start.date(), hi.date()))
if df.empty:
    st.warning("Không có dữ liệu giá trong khoảng đã chọn.")
    st.stop()
last = df.iloc[-1]
info = wh.query("select * from gold.dim_ticker where symbol = ?", (symbol,)).iloc[0]

st.caption(f"**{symbol}** · sàn {info.exchange or '–'} · niêm yết {pd.Timestamp(info.listing_date):%d/%m/%Y} · "
           f"phiên gần nhất {last.trade_date:%d/%m/%Y} · giá đơn vị nghìn đồng")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Giá đóng cửa", charts.fmt_num(last.close), charts.fmt_pct(last.daily_return) + " trong phiên")
c2.metric("Lợi suất 20 phiên", charts.fmt_pct(last.return_20d))
c3.metric("RSI14", charts.fmt_num(last.rsi14, 1),
          help="Trung bình đơn giản 14 phiên. Trên 70: vùng quá mua; dưới 30: vùng quá bán.")
c4.metric("Độ biến động 20 phiên", charts.fmt_pct(last.volatility_20d_annualized, 1, signed=False),
          help="Độ lệch chuẩn lợi suất ngày, quy năm (×√252)")
c5.metric("So với đỉnh", charts.fmt_pct(last.drawdown, 1), help="Mức giảm từ giá đóng cửa cao nhất kể từ 04/01/2021")

# ------------------------------------------------------------------ giá + khối lượng + RSI (3 khung, chung trục ngày)
fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.58, 0.18, 0.24])
fig.add_trace(go.Candlestick(
    x=df.trade_date, open=df.open, high=df.high, low=df.low, close=df.close, name=symbol,
    increasing=dict(line=dict(color=charts.AQUA, width=1), fillcolor=charts.AQUA),
    decreasing=dict(line=dict(color=charts.NEGATIVE, width=1), fillcolor=charts.NEGATIVE),
    showlegend=False), row=1, col=1)
if show_sma:
    for col, name, color in (("sma20", "SMA20", charts.SMA20), ("sma50", "SMA50", charts.SMA50)):
        fig.add_trace(go.Scatter(x=df.trade_date, y=df[col], name=name, mode="lines",
                                 line=dict(color=color, width=2),
                                 hovertemplate=f"%{{y:,.2f}}<extra>{name}</extra>"), row=1, col=1)
fig.add_trace(go.Bar(x=df.trade_date, y=df.volume, name="Khối lượng", showlegend=False,
                     marker=dict(color=charts.NEUTRAL, line=dict(width=0)),
                     hovertemplate="%{y:,.0f} cp<extra>Khối lượng</extra>"), row=2, col=1)
fig.add_trace(go.Scatter(x=df.trade_date, y=df.rsi14, name="RSI14", mode="lines", showlegend=False,
                         line=dict(color=charts.STOCK, width=2),
                         hovertemplate="%{y:.1f}<extra>RSI14</extra>"), row=3, col=1)
for level, label in ((70, "Quá mua 70"), (30, "Quá bán 30")):
    fig.add_hline(y=level, line=dict(color=charts.AXIS, width=1, dash="dot"), row=3, col=1,
                  annotation_text=label, annotation_position="top left",
                  annotation_font=dict(color=charts.MUTED, size=10))
charts.style(fig, height=640, legend=show_sma)
fig.update_layout(xaxis_rangeslider_visible=False)
fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
axis_title = dict(font=dict(color=charts.MUTED, size=11))
fig.update_yaxes(title=dict(text="Giá (nghìn đồng)", **axis_title), row=1, col=1)
fig.update_yaxes(title=dict(text="Khối lượng", **axis_title), tickformat=".2s", row=2, col=1)
fig.update_yaxes(title=dict(text="RSI14", **axis_title), range=[0, 100], tickvals=[0, 30, 50, 70, 100], row=3, col=1)
charts.show(fig, key="price")
st.caption("Nến xanh: đóng cửa cao hơn mở cửa; nến đỏ: thấp hơn. Ba khung dùng chung trục ngày, mỗi khung một thang đo riêng.")

# ------------------------------------------------------------------ so với VN-Index
ilo, _ = wh.index_date_bounds()
rel = wh.query("""
    select trade_date, stock_close, index_close, beta_60d
    from gold.mart_stock_vs_index
    where symbol = ? and index_code = 'VNINDEX' and trade_date between ? and ?
    order by trade_date""", (symbol, start.date(), hi.date()))
st.subheader("So với VN-Index")
if len(rel) < 2:
    st.info(f"Không đủ dữ liệu chung với VN-Index (chỉ số có từ {ilo:%d/%m/%Y}).")
else:
    rel["stock_cum"] = rel.stock_close / rel.stock_close.iloc[0] - 1
    rel["index_cum"] = rel.index_close / rel.index_close.iloc[0] - 1
    base = rel.trade_date.iloc[0]
    k1, k2, k3 = st.columns(3)
    k1.metric(f"Lợi suất {symbol}", charts.fmt_pct(rel.stock_cum.iloc[-1], 1))
    k2.metric("Lợi suất VN-Index", charts.fmt_pct(rel.index_cum.iloc[-1], 1))
    k3.metric("Chênh lệch", charts.fmt_pct(rel.stock_cum.iloc[-1] - rel.index_cum.iloc[-1], 1),
              help="Beta 60 phiên gần nhất: " + charts.fmt_num(rel.beta_60d.iloc[-1]))
    fig = charts.line(rel, "trade_date", {"stock_cum": (symbol, charts.STOCK), "index_cum": ("VN-Index", charts.INDEX)},
                      hover_format="+.1%")
    charts.show(charts.style(fig, height=320, title=f"Lợi suất lũy kế tính từ {base:%d/%m/%Y}", y_format="+.0%"), key="rel")
    if start < ilo:
        st.caption(f"Khoảng so sánh bắt đầu từ {base:%d/%m/%Y} vì VN-Index không có dữ liệu trước đó.")

with st.expander("Hồ sơ doanh nghiệp"):
    a, b, c = st.columns(3)
    a.metric("Số nhân viên", f"{int(info.num_employees):,}" if pd.notna(info.num_employees) else "–")
    b.metric("Vốn điều lệ", f"{info.charter_capital_bn_vnd:,.0f} tỷ" if pd.notna(info.charter_capital_bn_vnd) else "–")
    c.metric("Số phiên có dữ liệu", f"{int(info.trading_days):,}")
    st.write(info.business_profile or "Nguồn không có mô tả.")
    if info.website:
        st.caption(f"Website: {info.website} · Nguồn không cung cấp tên công ty và mã ngành.")

with st.expander("Xem dạng bảng"):
    out = df[["trade_date", "open", "high", "low", "close", "volume", "daily_return", "sma20", "sma50", "rsi14"]]
    charts.table(out.sort_values("trade_date", ascending=False), column_config={
        "trade_date": st.column_config.DateColumn("Ngày", format="DD/MM/YYYY"),
        "daily_return": st.column_config.NumberColumn("Lợi suất ngày", format="percent"),
        "volume": st.column_config.NumberColumn("Khối lượng", format="localized"),
    })

wh.sidebar_footer()
