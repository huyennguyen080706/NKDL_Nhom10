"""Trang 2 - Stock Explorer. Nguồn Gold: fact_price_daily, mart_technical_indicators, mart_stock_vs_index, dim_ticker.
SMA200 tính tại trang từ chuỗi giá Gold và chỉ có khi mã đủ 200 phiên."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from components import charts, ui
from services import warehouse as wh

lo, hi = wh.price_date_bounds()
symbols = wh.symbols()
PRESETS = {"3 tháng": 91, "6 tháng": 182, "1 năm": 365, "3 năm": 1096, "Toàn bộ": None}
with st.sidebar:
    st.header("Bộ lọc")
    symbol = st.selectbox("Mã cổ phiếu", symbols, index=symbols.index("FPT") if "FPT" in symbols else 0)
    preset = st.radio("Khoảng thời gian", list(PRESETS), index=2)
    start = lo if PRESETS[preset] is None else max(lo, hi - pd.Timedelta(days=PRESETS[preset]))
    st.markdown("**Chỉ báo**")
    show_sma20 = st.checkbox("SMA20", value=True)
    show_sma50 = st.checkbox("SMA50", value=True)
    show_sma200 = st.checkbox("SMA200", value=False, help="Chỉ có khi mã đã có tối thiểu 200 phiên")
    show_vol = st.checkbox("Khối lượng", value=True)
    show_rsi = st.checkbox("RSI14", value=True)

# Lấy toàn bộ lịch sử của mã để SMA200 đủ 200 phiên ngay ở đầu khoảng xem, rồi cắt theo khoảng đã chọn
full = wh.query("""
    select p.trade_date, p.open, p.high, p.low, p.close, p.volume,
           m.daily_return, m.sma20, m.sma50, m.rsi14, m.volatility_20d_annualized, m.drawdown,
           m.return_20d, m.volume_ratio_20d
    from gold.fact_price_daily p
    join gold.mart_technical_indicators m using (ticker_key, date_key)
    where p.symbol = ? order by p.trade_date""", (symbol,))
full["sma200"] = full.close.rolling(200, min_periods=200).mean()
df = full[full.trade_date >= start].reset_index(drop=True)
info = wh.query("select * from gold.dim_ticker where symbol = ?", (symbol,)).iloc[0]

ui.page_header("Stock Explorer", f"{symbol} · sàn {info.exchange or '–'} · niêm yết {pd.Timestamp(info.listing_date):%d/%m/%Y} · "
               "giá đơn vị nghìn đồng")
if df.empty:
    st.warning("Không có dữ liệu giá trong khoảng đã chọn.")
    st.stop()
last = df.iloc[-1]

ilo, _ = wh.index_date_bounds()
rel = wh.query("""
    select trade_date, stock_close, index_close, beta_60d from gold.mart_stock_vs_index
    where symbol = ? and index_code = 'VNINDEX' and trade_date >= ? order by trade_date""", (symbol, start.date()))
has_rel = len(rel) >= 2
if has_rel:
    rel["stock_cum"] = rel.stock_close / rel.stock_close.iloc[0] - 1
    rel["index_cum"] = rel.index_close / rel.index_close.iloc[0] - 1
gap = rel.stock_cum.iloc[-1] - rel.index_cum.iloc[-1] if has_rel else None

ui.kpi_row([
    dict(label="Giá đóng cửa", value=charts.fmt_num(last.close), delta=charts.fmt_pct(last.daily_return) + " trong phiên",
         tone="lavender", help=f"Phiên {last.trade_date:%d/%m/%Y}"),
    dict(label="Lợi suất 20 phiên", value=charts.fmt_pct(last.return_20d), tone="mint"),
    dict(label="Biến động 20 phiên (quy năm)", value=charts.fmt_pct(last.volatility_20d_annualized, 1, signed=False),
         tone="yellow", help="Độ lệch chuẩn lợi suất ngày × √252"),
    dict(label="RSI14", value=charts.fmt_num(last.rsi14, 1), tone="blue",
         help=">70 vùng quá mua · <30 vùng quá bán (không phải khuyến nghị)"),
    dict(label="So với đỉnh (drawdown)", value=charts.fmt_pct(last.drawdown, 1), tone="white",
         help="Từ giá đóng cửa cao nhất kể từ 04/01/2021"),
    dict(label="Chênh lệch so với VN-Index", value=charts.fmt_pct(gap, 1) if gap is not None else "–", tone="white",
         help="Lợi suất lũy kế trên ngày chung với chỉ số" if has_rel else f"Chỉ số có từ {ilo:%d/%m/%Y}"),
])
if show_sma200 and full.sma200.notna().sum() == 0:
    ui.callout(f"{symbol} chưa đủ 200 phiên nên không có SMA200.", "warn")
ui.price_basis_note()

# ------------------------------------------------------------------ nến + (khối lượng) + (RSI)
rows = [("price", 0.58)] + ([("vol", 0.18)] if show_vol else []) + ([("rsi", 0.24)] if show_rsi else [])
fig = make_subplots(rows=len(rows), cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[h for _, h in rows])
row_of = {name: i + 1 for i, (name, _) in enumerate(rows)}
fig.add_trace(go.Candlestick(
    x=df.trade_date, open=df.open, high=df.high, low=df.low, close=df.close, name=symbol,
    increasing=dict(line=dict(color=charts.POSITIVE, width=1), fillcolor=charts.POSITIVE),
    decreasing=dict(line=dict(color=charts.NEGATIVE, width=1), fillcolor=charts.NEGATIVE),
    showlegend=False), row=1, col=1)
for on, col, name, color in ((show_sma20, "sma20", "SMA20", charts.SMA20), (show_sma50, "sma50", "SMA50", charts.SMA50),
                             (show_sma200, "sma200", "SMA200", charts.SMA200)):
    if on:
        fig.add_trace(go.Scatter(x=df.trade_date, y=df[col], name=name, mode="lines", line=dict(color=color, width=2),
                                 hovertemplate=f"%{{y:,.2f}}<extra>{name}</extra>"), row=1, col=1)
if show_vol:
    fig.add_trace(go.Bar(x=df.trade_date, y=df.volume, name="Khối lượng", showlegend=False,
                         marker=dict(color=charts.NEUTRAL, line=dict(width=0)),
                         hovertemplate="%{y:,.0f} cp<extra>Khối lượng</extra>"), row=row_of["vol"], col=1)
if show_rsi:
    fig.add_trace(go.Scatter(x=df.trade_date, y=df.rsi14, name="RSI14", mode="lines", showlegend=False,
                             line=dict(color=charts.PURPLE, width=2),
                             hovertemplate="%{y:.1f}<extra>RSI14</extra>"), row=row_of["rsi"], col=1)
    for level, label in ((70, "Quá mua 70"), (30, "Quá bán 30")):
        fig.add_hline(y=level, line=dict(color=charts.AXIS, width=1, dash="dot"), row=row_of["rsi"], col=1,
                      annotation_text=label, annotation_position="top left",
                      annotation_font=dict(color=charts.MUTED, size=10))
charts.style(fig, height=420 + 140 * (len(rows) - 1), legend=True)
fig.update_layout(xaxis_rangeslider_visible=False)
fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
t = dict(font=dict(color=charts.MUTED, size=11))
fig.update_yaxes(title=dict(text="Giá (nghìn đồng)", **t), row=1, col=1)
if show_vol:
    fig.update_yaxes(title=dict(text="Khối lượng (cp)", **t), tickformat=".2s", row=row_of["vol"], col=1)
if show_rsi:
    fig.update_yaxes(title=dict(text="RSI14 (0-100)", **t), range=[0, 100], tickvals=[0, 30, 50, 70, 100],
                     row=row_of["rsi"], col=1)
with st.container(border=True):
    charts.show(fig, key="price")
    st.caption("Nến xanh: đóng cửa cao hơn mở cửa; nến đỏ: thấp hơn. Các khung dùng chung trục ngày, mỗi khung một thang đo.")

# ------------------------------------------------------------------ so với VN-Index và so sánh mã
with st.container(border=True):
    ui.section("So với VN-Index và mã khác", "Lợi suất lũy kế chuẩn hóa, chỉ tính các ngày giao dịch chung.")
    others = st.multiselect("So sánh thêm mã", [s for s in symbols if s != symbol], max_selections=4)
    if not has_rel:
        st.info(f"Không đủ dữ liệu chung với VN-Index (chỉ số có từ {ilo:%d/%m/%Y}).")
    else:
        series = {symbol: rel.set_index("trade_date").stock_close,
                  "VN-Index": rel.set_index("trade_date").index_close}
        if others:
            ph = ",".join("?" for _ in others)
            ox = wh.query(f"select trade_date, symbol, close from gold.fact_price_daily where symbol in ({ph}) "
                          f"and trade_date >= ? order by trade_date", (*others, rel.trade_date.iloc[0].date()))
            for s, g in ox.groupby("symbol"):
                series[s] = g.set_index("trade_date").close
        wide = pd.concat(series, axis=1, join="inner").dropna()
        if len(wide) < 2:
            st.info("Không đủ ngày chung giữa các chuỗi đã chọn.")
        else:
            cum = wide / wide.iloc[0] - 1
            fig = go.Figure()
            pal = [charts.MINT, charts.YELLOW, charts.BLUE, "#B18CFF"]
            for i, c in enumerate(cum.columns):
                color = charts.STOCK if c == symbol else charts.INDEX if c == "VN-Index" else pal[(i - 2) % len(pal)]
                fig.add_trace(go.Scatter(x=cum.index, y=cum[c], name=c, mode="lines",
                                         line=dict(color=color, width=3 if c == symbol else 2,
                                                   dash="dash" if c == "VN-Index" else "solid"),
                                         hovertemplate=f"%{{y:+.1%}}<extra>{c}</extra>"))
            charts.show(charts.style(fig, height=320, title=f"Lợi suất lũy kế từ {cum.index[0]:%d/%m/%Y}",
                                     y_title="Lợi suất lũy kế", y_format="+.0%"), key="rel")
            if has_rel:
                st.caption("Beta 60 phiên gần nhất: " + charts.fmt_num(rel.beta_60d.iloc[-1]) +
                           " (tính trên ngày chung với VN-Index).")

with st.expander("Hồ sơ doanh nghiệp"):
    a, b, c = st.columns(3)
    a.metric("Số nhân viên", f"{int(info.num_employees):,}" if pd.notna(info.num_employees) else "–")
    b.metric("Vốn điều lệ", f"{info.charter_capital_bn_vnd:,.0f} tỷ" if pd.notna(info.charter_capital_bn_vnd) else "–")
    c.metric("Số phiên có dữ liệu", f"{int(info.trading_days):,}")
    st.write(info.business_profile or "Nguồn không có mô tả.")
    if info.website:
        st.caption(f"Website: {info.website} · Nguồn không cung cấp tên công ty và mã ngành.")

with st.expander("Xem dạng bảng"):
    out = df[["trade_date", "open", "high", "low", "close", "volume", "daily_return", "sma20", "sma50", "sma200", "rsi14"]]
    charts.table(out.sort_values("trade_date", ascending=False), column_config={
        "trade_date": st.column_config.DateColumn("Ngày", format="DD/MM/YYYY"),
        "daily_return": st.column_config.NumberColumn("Lợi suất ngày", format="percent"),
        "volume": st.column_config.NumberColumn("Khối lượng", format="localized")})
