"""VNStock Intelligence 2.0 - dashboard kho dữ liệu chứng khoán Việt Nam (Nhóm 10).

    streamlit run app/streamlit_app.py

Tệp này là điểm vào + thanh điều hướng 6 trang. Ứng dụng chỉ ĐỌC tầng Gold của kho
(BigQuery hoặc DuckDB local), không gọi Vnstock khi mở trang.
"""
import streamlit as st

st.set_page_config(page_title="VNStock Intelligence", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

from components import ui  # noqa: E402  (sau set_page_config)
from services import warehouse as wh  # noqa: E402

ui.inject_theme()
wh.require_warehouse()
ui.brand_bar()

pages = [
    st.Page("pages/1_Market_Overview.py", title="Market Overview", icon=":material/dashboard:",
            url_path="Market_Overview", default=True),
    st.Page("pages/2_Stock_Explorer.py", title="Stock Explorer", icon=":material/candlestick_chart:",
            url_path="Stock_Explorer"),
    st.Page("pages/3_Risk_Correlation.py", title="Risk & Correlation", icon=":material/shield:",
            url_path="Risk_Correlation"),
    st.Page("pages/4_Financials_Signals.py", title="Financials & Signals", icon=":material/receipt_long:",
            url_path="Financials_Signals"),
    st.Page("pages/5_Portfolio_Lab.py", title="Portfolio Lab", icon=":material/pie_chart:",
            url_path="Portfolio_Lab"),
    # Giữ nguyên đường dẫn cũ /Pipeline_Health để không gãy liên kết đã chia sẻ
    st.Page("pages/6_Data_Pipeline.py", title="Data Pipeline", icon=":material/account_tree:",
            url_path="Pipeline_Health"),
]
pg = st.navigation(pages)
pg.run()
wh.sidebar_footer()
