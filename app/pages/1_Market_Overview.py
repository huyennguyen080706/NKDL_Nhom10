"""Trang 1 - Market Overview. Nguồn Gold: fact_index_daily, fact_price_daily, dim_ticker,
mart_technical_indicators, mart_pipeline_health."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components import charts, ui
from services import warehouse as wh

ilo, ihi = wh.index_date_bounds()
PRESETS = {"3 tháng": 91, "6 tháng": 182, "1 năm": 365, "Toàn bộ": None, "Tùy chọn": -1}
with st.sidebar:
    st.header("Bộ lọc")
    preset = st.radio("Khoảng thời gian", list(PRESETS), index=2)
    if PRESETS[preset] == -1:
        picked = st.date_input("Từ ngày – đến ngày", (ihi - pd.Timedelta(days=365), ihi),
                               min_value=ilo, max_value=ihi, format="DD/MM/YYYY")
        if len(picked) != 2:
            st.info("Chọn đủ ngày bắt đầu và ngày kết thúc.")
            st.stop()
        start, end = map(pd.Timestamp, picked)
    else:
        end = ihi
        start = ilo if PRESETS[preset] is None else max(ilo, ihi - pd.Timedelta(days=PRESETS[preset]))
    st.caption(f"VN-Index có dữ liệu từ {ilo:%d/%m/%Y} đến {ihi:%d/%m/%Y}.")

ui.page_header("Market Overview", "VN-Index, độ rộng thị trường, thanh khoản và lợi suất của rổ 40 mã do nhóm chọn.",
               [("Khoảng xem", f"{start:%d/%m/%Y} → {end:%d/%m/%Y}")])

params = (start.date(), end.date())
idx = wh.query("select trade_date, close, volume from gold.fact_index_daily "
               "where index_code = 'VNINDEX' and trade_date between ? and ? order by trade_date", params)
if len(idx) < 2:
    st.warning("Khoảng ngày đã chọn không đủ dữ liệu VN-Index.")
    st.stop()
first_day, last_day = idx.trade_date.iloc[0], idx.trade_date.iloc[-1]

breadth = wh.query("""
    select sum(case when daily_return > 0 then 1 else 0 end) as up,
           sum(case when daily_return < 0 then 1 else 0 end) as down,
           sum(case when daily_return = 0 then 1 else 0 end) as flat
    from gold.mart_technical_indicators where trade_date = ?""", (last_day.date(),)).iloc[0]
liq = wh.query("select trade_date, sum(traded_value_bn_vnd_est) as value_bn, count(*) as n "
               "from gold.fact_price_daily where trade_date between ? and ? group by 1 order by 1", params)
meta = wh.query("select (select count(*) from gold.dim_ticker where trading_days > 0) as tickers, "
                "(select sum(datasets_loaded) from gold.mart_pipeline_health) as extracts").iloc[0]

idx_ret = idx.close.iloc[-1] / idx.close.iloc[0] - 1
day_ret = idx.close.iloc[-1] / idx.close.iloc[-2] - 1
ui.kpi_row([
    dict(label=f"VN-Index · {last_day:%d/%m/%Y}", value=charts.fmt_num(idx.close.iloc[-1]),
         delta=charts.fmt_pct(day_ret) + " trong phiên", tone="lavender"),
    dict(label="Thay đổi trong khoảng đã chọn", value=charts.fmt_pct(idx_ret), tone="white",
         help=f"{first_day:%d/%m/%Y} → {last_day:%d/%m/%Y}"),
    dict(label="Tăng / Giảm / Đứng giá", value=f"{int(breadth.up)} / {int(breadth.down)} / {int(breadth.flat)}",
         tone="mint", help=f"Trong {int(meta.tickers)} mã theo dõi, phiên {last_day:%d/%m}"),
    dict(label="Giá trị giao dịch ước tính", value=f"{liq.value_bn.iloc[-1]:,.0f} tỷ", tone="yellow",
         help="Close × khối lượng, cộng 40 mã, phiên gần nhất"),
])
st.write("")
ui.kpi_row([
    dict(label="Mã đang theo dõi", value=f"{int(meta.tickers)}", tone="blue", help="Rổ do nhóm chọn, không phải VN30"),
    dict(label="Extract đã nạp", value=f"{int(meta.extracts)}", tone="white", help="Số tập dữ liệu nguồn đã nạp vào Bronze"),
])
ui.price_basis_note()

# ------------------------------------------------------------------ hiệu suất chuẩn hóa gốc 100
all_symbols = wh.symbols()
top_default = wh.query("select symbol from gold.fact_price_daily where trade_date = (select max(trade_date) "
                       "from gold.fact_price_daily) order by traded_value_bn_vnd_est desc limit 5").symbol.tolist()
with st.container(border=True):
    ui.section("Hiệu suất chuẩn hóa (gốc 100) so với VN-Index",
               "Chỉ dùng các ngày giao dịch chung với VN-Index; gốc = phiên đầu tiên trong khoảng xem.")
    picks = st.multiselect("Chọn mã so sánh", all_symbols, default=[s for s in top_default if s in all_symbols])
    if picks:
        ph = ",".join("?" for _ in picks)
        px = wh.query(f"select trade_date, symbol, close from gold.fact_price_daily "
                      f"where symbol in ({ph}) and trade_date between ? and ? order by trade_date",
                      (*picks, *params))
        wide = px.pivot(index="trade_date", columns="symbol", values="close")
        wide = wide.join(idx.set_index("trade_date").close.rename("VN-Index"), how="inner").dropna(how="any")
        if len(wide) < 2:
            st.info("Không đủ ngày chung giữa các mã đã chọn và VN-Index.")
        else:
            norm = wide / wide.iloc[0] * 100
            fig = go.Figure()
            palette = [charts.PURPLE, charts.MINT, charts.YELLOW, charts.BLUE, "#B18CFF", "#7FD8BE", "#F2C14E"]
            for i, c in enumerate([c for c in norm.columns if c != "VN-Index"]):
                fig.add_trace(go.Scatter(x=norm.index, y=norm[c], name=c, mode="lines",
                                         line=dict(color=palette[i % len(palette)], width=2),
                                         hovertemplate=f"%{{y:,.1f}}<extra>{c}</extra>"))
            fig.add_trace(go.Scatter(x=norm.index, y=norm["VN-Index"], name="VN-Index", mode="lines",
                                     line=dict(color=charts.INDEX, width=3, dash="dash"),
                                     hovertemplate="%{y:,.1f}<extra>VN-Index</extra>"))
            fig.add_hline(y=100, line=dict(color=charts.AXIS, width=1, dash="dot"))
            charts.show(charts.style(fig, height=380, y_title="Chỉ số (phiên đầu = 100)", y_format=",.0f"), key="norm")
            st.caption(f"Từ {norm.index[0]:%d/%m/%Y} đến {norm.index[-1]:%d/%m/%Y} · {len(norm)} ngày chung · "
                       "price return, chưa điều chỉnh cổ tức.")
    else:
        st.info("Chọn ít nhất một mã để so sánh.")

# ------------------------------------------------------------------ VN-Index + thanh khoản
c_left, c_right = st.columns(2)
with c_left, st.container(border=True):
    fig = charts.line(idx, "trade_date", {"close": ("VN-Index", charts.INDEX)})
    charts.show(charts.style(fig, height=300, title="Diễn biến VN-Index", legend=False, y_title="Điểm",
                             y_format=",.0f"), key="idx")
with c_right, st.container(border=True):
    fig = go.Figure(go.Bar(x=liq.trade_date, y=liq.value_bn, marker=dict(color=charts.PURPLE, line=dict(width=0)),
                           hovertemplate="%{y:,.0f} tỷ đồng<extra></extra>"))
    charts.show(charts.style(fig, height=300, title="Giá trị giao dịch ước tính của rổ 40 mã", legend=False,
                             y_title="Tỷ đồng", y_format=",.0f"), key="liq")

# ------------------------------------------------------------------ xếp hạng lợi suất
perf = wh.query("""
    with r as (
        select symbol, trade_date, close,
               first_value(close) over (partition by symbol order by trade_date) as first_close,
               row_number() over (partition by symbol order by trade_date desc) as rn,
               count(*) over (partition by symbol) as sessions
        from gold.fact_price_daily where trade_date between ? and ?
    )
    select r.symbol, t.exchange, r.close / r.first_close - 1 as stock_return, r.sessions
    from r join gold.dim_ticker t using (symbol) where rn = 1""", params)
perf["excess"] = perf.stock_return - idx_ret
beat = int((perf.excess > 0).sum())

ui.section("Top tăng / giảm trong khoảng đã chọn",
           f"{beat}/{len(perf)} mã có lợi suất cao hơn VN-Index ({charts.fmt_pct(idx_ret)}).")
ranked = perf.sort_values("stock_return", ascending=False)
g, l = st.columns(2)
with g, st.container(border=True):
    st.markdown("**Top 5 tăng mạnh nhất**")
    charts.show(charts.style(charts.signed_hbar(ranked.head(5), "symbol", "stock_return"), height=230, legend=False)
                .update_xaxes(tickformat="+.0%", showgrid=True, gridcolor=charts.GRID), key="gain")
with l, st.container(border=True):
    st.markdown("**Top 5 giảm mạnh nhất**")
    charts.show(charts.style(charts.signed_hbar(ranked.tail(5), "symbol", "stock_return"), height=230, legend=False)
                .update_xaxes(tickformat="+.0%", showgrid=True, gridcolor=charts.GRID), key="lose")

with st.container(border=True):
    ui.section("Heatmap theo mã (phiên gần nhất)",
               "Kích thước = giá trị giao dịch ước tính; màu = lợi suất phiên. Đây là heatmap theo từng mã, không phải theo ngành.")
    hm = wh.query("""select p.symbol, p.traded_value_bn_vnd_est as value_bn, m.daily_return
                     from gold.fact_price_daily p join gold.mart_technical_indicators m using (ticker_key, date_key)
                     where p.trade_date = ? and p.traded_value_bn_vnd_est > 0""", (last_day.date(),))
    if hm.empty:
        st.info("Không có dữ liệu thanh khoản cho phiên gần nhất.")
    else:
        fig = go.Figure(go.Treemap(
            labels=hm.symbol, parents=[""] * len(hm), values=hm.value_bn,
            customdata=hm.daily_return.fillna(0), marker=dict(
                colors=hm.daily_return.fillna(0), colorscale=[[0, "#E5484D"], [0.5, "#F5F2FA"], [1, "#12A67A"]],
                cmid=0, cmin=-0.07, cmax=0.07, line=dict(color="#ffffff", width=2)),
            texttemplate="<b>%{label}</b><br>%{customdata:+.1%}", textfont=dict(size=13),
            hovertemplate="%{label}<br>Lợi suất: %{customdata:+.2%}<br>GTGD: %{value:,.0f} tỷ<extra></extra>"))
        fig.update_layout(height=420, margin=dict(l=0, r=0, t=8, b=0), paper_bgcolor=charts.SURFACE,
                          font=dict(family=charts.FONT))
        charts.show(fig, key="treemap")

with st.container(border=True):
    ui.section(f"Lợi suất {len(perf)} mã trong khoảng đã chọn", "Đường đứt nét là lợi suất VN-Index trong cùng khoảng.")
    fig = charts.signed_hbar(perf, "symbol", "stock_return")
    fig.add_vline(x=idx_ret, line=dict(color=charts.INDEX, width=2, dash="dash"),
                  annotation_text=f"VN-Index {charts.fmt_pct(idx_ret, 1)}", annotation_position="top",
                  annotation_font=dict(color=charts.INK_2, size=11))
    charts.show(charts.style(fig, height=max(320, 20 * len(perf) + 60), legend=False).update_xaxes(
        tickformat="+.0%", showgrid=True, gridcolor=charts.GRID).update_yaxes(showgrid=False), key="perf")
    with st.expander("Xem dạng bảng"):
        out = ranked.rename(columns={"symbol": "Mã", "exchange": "Sàn", "stock_return": "Lợi suất",
                                     "excess": "Chênh so với VN-Index", "sessions": "Số phiên"})
        charts.table(out, column_config={
            "Lợi suất": st.column_config.NumberColumn(format="percent"),
            "Chênh so với VN-Index": st.column_config.NumberColumn(format="percent")})

ui.limits_expander()
