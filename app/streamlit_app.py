"""Dashboard kho dữ liệu chứng khoán Việt Nam - Nhóm 10.

    streamlit run app/streamlit_app.py

Ứng dụng chỉ đọc tầng Gold của kho (DuckDB local), không gọi Vnstock khi mở trang.
"""
import pandas as pd
import streamlit as st

from components import charts
from services import warehouse as wh

st.set_page_config(page_title="Vnstock Medallion Warehouse", page_icon="📈", layout="wide")
wh.require_warehouse()

st.title("Kho dữ liệu chứng khoán Việt Nam")
st.caption("Kiến trúc Medallion (Bronze → Silver → Gold) · Nguồn Vnstock/KBS · Đồ án Nhà kho dữ liệu và tích hợp – Nhóm 10")

lo, hi = wh.price_date_bounds()
ilo, ihi = wh.index_date_bounds()
counts = wh.query("""
    select
        (select count(*) from gold.dim_ticker where trading_days > 0)        as tickers,
        (select count(*) from gold.dim_ticker where has_financials)          as fin_tickers,
        (select count(*) from gold.fact_price_daily)                         as price_rows,
        (select count(distinct period) from gold.fact_financial_metric)      as periods,
        (select sum(bronze_rows) from gold.mart_pipeline_health)             as bronze_rows,
        (select count(*) from gold.mart_stock_alerts)                        as alerts
""").iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Mã cổ phiếu", f"{int(counts.tickers)}", help="Rổ mẫu do nhóm chọn, không phải VN30")
c2.metric("Bản ghi giá ngày", f"{int(counts.price_rows):,}", help=f"{lo:%d/%m/%Y} → {hi:%d/%m/%Y}")
c3.metric("Mã có báo cáo tài chính", f"{int(counts.fin_tickers)}", help=f"{int(counts.periods)} kỳ quý")
c4.metric("Bản ghi nguồn (Bronze)", f"{int(counts.bronze_rows):,}")

st.subheader("Các trang")
p1, p2 = st.columns(2)
with p1:
    st.page_link("pages/1_Market_Overview.py", label="**1 · Market Overview**", icon="🌐")
    st.caption("VN-Index, độ rộng thị trường, thanh khoản và lợi suất 40 mã so với chỉ số.")
    st.page_link("pages/2_Stock_Analysis.py", label="**2 · Stock Analysis**", icon="🕯️")
    st.caption("Biểu đồ nến, SMA20/50, RSI14, khối lượng và lợi suất so với VN-Index của từng mã.")
with p2:
    st.page_link("pages/3_Financials_Alerts.py", label="**3 · Financials & Alerts**", icon="📑")
    st.caption("Chỉ tiêu tài chính theo quý và tín hiệu cảnh báo theo quy tắc kèm giải thích.")
    st.page_link("pages/4_Pipeline_Health.py", label="**4 · Pipeline Health**", icon="🩺")
    st.caption("Đối soát nạp, độ mới dữ liệu, kết quả dbt test và nhật ký sai lệch.")

st.subheader("Trạng thái dữ liệu")
health = wh.query("select bronze_table, status, bronze_rows, silver_rows, max_business_date, "
                  "dq_warn_count, dq_error_count from gold.mart_pipeline_health order by bronze_table")
n_ok = int((health.status == "OK").sum())
worst = "FAIL" if (health.status == "FAIL").any() else "WARN" if (health.status == "WARN").any() else "OK"
st.markdown(
    f"{charts.STATUS_ICON[worst]} **{n_ok}/{len(health)} bảng nguồn ở trạng thái OK** · "
    f"{int(health.dq_warn_count.sum())} cảnh báo và {int(health.dq_error_count.sum())} lỗi chất lượng đã ghi nhận. "
    "Chi tiết ở trang Pipeline Health."
)

with st.expander("Giới hạn của dữ liệu cần biết khi đọc dashboard", expanded=True):
    st.markdown(
        f"""
- Giá ở đơn vị **nghìn đồng**; chưa xác minh đã điều chỉnh cổ tức/chia tách.
- VN-Index chỉ có từ **{ilo:%d/%m/%Y}**, nên mọi so sánh với chỉ số giới hạn trong khoảng ngày chung.
- Báo cáo tài chính chỉ có **{int(counts.periods)} kỳ**; kỳ `2025-Q4` có quy mô bất thường ở mọi mã và được gắn cờ nghi vấn.
- Nguồn không có ngày công bố báo cáo tài chính, vì vậy không ghép số liệu tài chính với giá để kiểm thử chiến lược.
- Cảnh báo là **tín hiệu minh họa theo quy tắc**, không phải khuyến nghị giao dịch.
"""
    )

wh.sidebar_footer()
