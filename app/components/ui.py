"""Thành phần giao diện dùng chung (Fox Stocks Light): theme, header, KPI card, badge, chú thích, độ mới dữ liệu."""
from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import streamlit as st

from services import warehouse as wh

CSS_PATH = Path(__file__).resolve().parents[1] / "styles" / "theme.css"
TONES = ("white", "lavender", "mint", "yellow", "blue")
TZ = "Asia/Ho_Chi_Minh"


def inject_theme() -> None:
    try:
        css = CSS_PATH.read_text(encoding="utf-8")
    except OSError:  # thiếu file CSS thì vẫn chạy với theme mặc định
        return
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def _e(x) -> str:
    return html.escape(str(x))


def badge(text: str, kind: str = "info") -> str:
    return f'<span class="vs-badge {kind}">{_e(text)}</span>'


def brand_bar() -> None:
    """Thanh trên cùng: logo chữ, nhãn nguồn dữ liệu thật (BigQuery Gold hay DuckDB local)."""
    label = "BigQuery Gold" if wh.BACKEND == "bigquery" else "DuckDB local Gold"
    st.markdown(
        f'<div class="vs-brand"><div class="vs-logo">VNStock Intelligence<small>2.0 · Financial Analytics</small></div>'
        f'<div>{badge(label, "primary")} {badge("Rổ 40 mã · không phải VN30", "info")}</div></div>',
        unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner=False)
def _fresh() -> dict:
    h = wh.query("select max(last_extracted_at) as extracted, max(refreshed_at) as refreshed, "
                 "max(latest_batch_id) as batch from gold.mart_pipeline_health").iloc[0]
    lo, hi = wh.price_date_bounds()
    return {"data_as_of": hi, "extracted": pd.Timestamp(h.extracted), "refreshed": pd.Timestamp(h.refreshed),
            "batch": str(h.batch)}


def freshness_chips() -> str:
    """Ba mốc thời gian KHÁC NHAU: ngày dữ liệu, thời điểm trích xuất, thời điểm dựng Gold."""
    f = _fresh()
    chips = [("Dữ liệu đến ngày", f"{f['data_as_of']:%d/%m/%Y}"),
             ("Trích xuất", f"{f['extracted'].tz_convert(TZ):%d/%m/%Y %H:%M}"),
             ("Dựng Gold", f"{f['refreshed'].tz_convert(TZ):%d/%m/%Y %H:%M}"),
             ("Batch", f["batch"])]
    return '<div class="vs-chips">' + "".join(f'<span class="vs-chip">{_e(k)}: <b>{_e(v)}</b></span>' for k, v in chips) + "</div>"


def page_header(title: str, subtitle: str | None = None, extra_chips: list[tuple[str, str]] | None = None) -> None:
    st.markdown(f'<div class="vs-title">{_e(title)}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="vs-sub">{_e(subtitle)}</div>', unsafe_allow_html=True)
    chips = freshness_chips()
    if extra_chips:
        extra = "".join(f'<span class="vs-chip">{_e(k)}: <b>{_e(v)}</b></span>' for k, v in extra_chips)
        chips = chips.replace("</div>", extra + "</div>")
    st.markdown(chips, unsafe_allow_html=True)


def kpi(col, label: str, value: str, delta: str | None = None, tone: str = "white", help: str | None = None,
        direction: str | None = None) -> None:
    """Thẻ KPI. direction: 'pos' | 'neg' | 'neu' hoặc None (tự suy ra từ dấu của delta). Delta luôn kèm ▲/▼."""
    tone = tone if tone in TONES else "white"
    d_html = ""
    if delta:
        if direction is None:
            s = delta.strip()
            direction = "neg" if s.startswith(("-", "−", "–")) else "pos" if s.startswith("+") else "neu"
        arrow = {"pos": "▲ ", "neg": "▼ ", "neu": ""}[direction]
        d_html = f'<div class="d {direction}">{arrow}{_e(delta)}</div>'
    h_html = f'<div class="h">{_e(help)}</div>' if help else ""
    col.markdown(f'<div class="vs-kpi {tone}"><div class="l">{_e(label)}</div><div class="v">{_e(value)}</div>'
                 f'{d_html}{h_html}</div>', unsafe_allow_html=True)


def kpi_row(items: list[dict]) -> None:
    cols = st.columns(len(items))
    for col, it in zip(cols, items):
        kpi(col, **it)


def callout(text: str, kind: str = "info") -> None:
    """kind: info | warn | err. Nội dung được escape; dùng **...** không được hỗ trợ (giữ an toàn)."""
    icon = {"info": "ℹ️", "warn": "⚠️", "err": "⛔"}.get(kind, "ℹ️")
    st.markdown(f'<div class="vs-callout {kind}">{icon} {_e(text)}</div>', unsafe_allow_html=True)


def section(title: str, caption: str | None = None) -> None:
    st.markdown(f"### {title}")
    if caption:
        st.caption(caption)


def price_basis_note() -> None:
    callout("Lợi suất là PRICE return tính trên giá đóng cửa (nghìn đồng), chưa xác minh đã điều chỉnh cổ tức/chia tách; "
            "không phải total return và không phản ánh lợi nhuận thực nhận của nhà đầu tư.", "info")


def missing_mart(name: str) -> None:
    st.error(f"Chưa có bảng Gold `{name}` trong kho đang kết nối.")
    st.code("python scripts/run_pipeline.py --skip-bronze   # hoặc: dbt build --select " + name, language="bash")
    st.stop()


def require_marts(*names: str) -> None:
    for n in names:
        try:
            wh.query(f"select 1 from gold.{n} limit 1")
        except Exception:
            missing_mart(n)


def limits_expander() -> None:
    lo, hi = wh.index_date_bounds()
    with st.expander("Giới hạn của dữ liệu cần biết khi đọc dashboard"):
        st.markdown(
            f"""
- Giá ở đơn vị **nghìn đồng**; chưa xác minh đã điều chỉnh cổ tức/chia tách nên chỉ dùng **price return**.
- VN-Index chỉ có từ **{lo:%d/%m/%Y}**; mọi so sánh, beta và tương quan với chỉ số dùng **ngày giao dịch chung**.
- Báo cáo tài chính chỉ có 15 doanh nghiệp, khoảng 4 quý; kỳ `2025-Q4` bị gắn cờ nghi vấn.
- Nguồn không có ngày công bố báo cáo tài chính nên **không ghép tài chính với giá để backtest**.
- Chưa có bảng phân ngành chuẩn nên **không có dashboard theo ngành**; heatmap là theo từng mã.
- Cảnh báo RSI/MA/khối lượng là **tín hiệu minh họa theo quy tắc**, không phải khuyến nghị mua bán.
""")
