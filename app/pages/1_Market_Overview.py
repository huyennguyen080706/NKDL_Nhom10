"""Trang 1 - Tổng quan thị trường. Nguồn Gold: fact_index_daily, fact_price_daily,
mart_technical_indicators, mart_stock_vs_index."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components import charts
from services import warehouse as wh

st.set_page_config(page_title="Market Overview", page_icon="🌐", layout="wide")
wh.require_warehouse()
st.title("Market Overview")

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

params = (start.date(), end.date())
idx = wh.query("select trade_date, close, volume from gold.fact_index_daily "
               "where index_code = 'VNINDEX' and trade_date between ? and ? order by trade_date", params)
if len(idx) < 2:
    st.warning("Khoảng ngày đã chọn không đủ dữ liệu VN-Index.")
    st.stop()
first_day, last_day = idx.trade_date.iloc[0], idx.trade_date.iloc[-1]

# ------------------------------------------------------------------ chỉ số chính
breadth = wh.query("""
    select
        sum(case when daily_return > 0 then 1 else 0 end) as up,
        sum(case when daily_return < 0 then 1 else 0 end) as down,
        sum(case when daily_return = 0 then 1 else 0 end) as flat
    from gold.mart_technical_indicators where trade_date = ?""", (last_day.date(),)).iloc[0]
liq = wh.query("select trade_date, sum(traded_value_bn_vnd_est) as value_bn, count(*) as n "
               "from gold.fact_price_daily where trade_date between ? and ? group by 1 order by 1", params)

idx_ret = idx.close.iloc[-1] / idx.close.iloc[0] - 1
day_ret = idx.close.iloc[-1] / idx.close.iloc[-2] - 1
c1, c2, c3, c4 = st.columns(4)
c1.metric(f"VN-Index ({last_day:%d/%m/%Y})", charts.fmt_num(idx.close.iloc[-1]), charts.fmt_pct(day_ret) + " trong phiên")
c2.metric("Thay đổi trong khoảng đã chọn", charts.fmt_pct(idx_ret), help=f"{first_day:%d/%m/%Y} → {last_day:%d/%m/%Y}")
c3.metric("Tăng / Giảm / Đứng giá", f"{int(breadth.up)} / {int(breadth.down)} / {int(breadth.flat)}",
          help="Số mã trong rổ 40 mã theo lợi suất phiên gần nhất")
c4.metric("Giá trị giao dịch phiên gần nhất", f"{liq.value_bn.iloc[-1]:,.0f} tỷ",
          help="Ước tính = giá đóng cửa × khối lượng, cộng trên 40 mã của rổ")

# ------------------------------------------------------------------ diễn biến chỉ số
fig = charts.line(idx, "trade_date", {"close": ("VN-Index", charts.INDEX)})
charts.show(charts.style(fig, height=340, title="Diễn biến VN-Index (điểm)", legend=False, y_format=",.0f"), key="idx")

# ------------------------------------------------------------------ thanh khoản
fig = go.Figure(go.Bar(x=liq.trade_date, y=liq.value_bn, marker=dict(color=charts.BLUE, line=dict(width=0)),
                       hovertemplate="%{y:,.0f} tỷ đồng<extra></extra>"))
charts.show(charts.style(fig, height=260, title="Giá trị giao dịch ước tính của rổ 40 mã (tỷ đồng)", legend=False,
                         y_format=",.0f"), key="liq")

# ------------------------------------------------------------------ lợi suất từng mã so với chỉ số
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

st.subheader("Lợi suất 40 mã trong khoảng đã chọn")
st.caption(f"{beat}/{len(perf)} mã có lợi suất cao hơn VN-Index ({charts.fmt_pct(idx_ret)}). "
           "Đường đứt nét là lợi suất của VN-Index trong cùng khoảng.")
fig = charts.signed_hbar(perf, "symbol", "stock_return")
fig.add_vline(x=idx_ret, line=dict(color=charts.INDEX, width=2, dash="dash"),
              annotation_text=f"VN-Index {charts.fmt_pct(idx_ret, 1)}", annotation_position="top",
              annotation_font=dict(color=charts.INK_2, size=11))
charts.show(charts.style(fig, height=max(320, 20 * len(perf) + 60), legend=False, y_format=None).update_xaxes(
    tickformat="+.0%", showgrid=True, gridcolor=charts.GRID).update_yaxes(showgrid=False), key="perf")

with st.expander("Xem dạng bảng"):
    out = perf.sort_values("stock_return", ascending=False).rename(columns={
        "symbol": "Mã", "exchange": "Sàn", "stock_return": "Lợi suất", "excess": "Chênh so với VN-Index",
        "sessions": "Số phiên"})
    charts.table(out, column_config={
        "Lợi suất": st.column_config.NumberColumn(format="percent"),
        "Chênh so với VN-Index": st.column_config.NumberColumn(format="percent"),
    })

wh.sidebar_footer()
