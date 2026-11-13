"""Trang 4 - Financials & Signals. Nguồn Gold: mart_financial_summary, mart_stock_alerts."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components import charts, ui
from services import warehouse as wh

ui.page_header("Financials & Signals", "Chỉ tiêu tài chính theo quý (15 doanh nghiệp có dữ liệu) và tín hiệu kỹ thuật theo quy tắc.")

RULES = {
    "GOLDEN_CROSS": "SMA20 cắt lên SMA50",
    "DEATH_CROSS": "SMA20 cắt xuống SMA50",
    "RSI_OVERBOUGHT": "RSI vào vùng quá mua",
    "RSI_OVERSOLD": "RSI vào vùng quá bán",
    "VOLUME_SPIKE": "Khối lượng đột biến",
    "LARGE_MOVE_UP": "Tăng mạnh trong phiên",
    "LARGE_MOVE_DOWN": "Giảm mạnh trong phiên",
    "DEEP_DRAWDOWN": "Giảm sâu so với đỉnh",
}
SIGNALS = {"bullish": "▲ Tích cực", "bearish": "▼ Tiêu cực", "neutral": "● Trung tính"}
TEMPLATES = {"bank": "ngân hàng", "securities": "chứng khoán", "corporate": "doanh nghiệp"}

tab_fin, tab_alert = st.tabs(["Financial Performance", "Signals & Alerts"])

# =========================================================================== TÀI CHÍNH
with tab_fin:
    fin = wh.query("select * from gold.mart_financial_summary order by symbol, period_end_date")
    fin_symbols = sorted(fin.symbol.unique())
    suspect_periods = sorted(fin.loc[fin.is_period_suspect, "period"].unique())
    if suspect_periods:
        ui.callout(
            f"Kỳ {', '.join(suspect_periods)} bị gắn cờ nghi vấn ở {fin.loc[fin.is_period_suspect, 'symbol'].nunique()}"
            f"/{len(fin_symbols)} mã: quy mô lệch nhiều lần so với các kỳ khác (nghi nguồn trả số cộng dồn). "
            "Kỳ này mặc định bị ẩn, không dùng làm bằng chứng tăng trưởng và không dùng để tính tăng trưởng so với quý trước.",
            "warn")

    left, right = st.columns([1, 3])
    with left:
        symbol = st.selectbox("Mã cổ phiếu", fin_symbols, index=fin_symbols.index("FPT") if "FPT" in fin_symbols else 0)
        hide_suspect = st.checkbox("Ẩn kỳ nghi vấn", value=True, help="Bỏ chọn để xem kèm cảnh báo")
    one = fin[fin.symbol == symbol].copy()
    if hide_suspect:
        one = one[~one.is_period_suspect]
    if one.empty:
        st.info("Không còn kỳ nào sau khi ẩn kỳ nghi vấn.")
    else:
        latest = one.iloc[-1]
        revenue_label = "Tổng thu nhập hoạt động" if latest.revenue_basis == "total_operating_income" else "Doanh thu thuần"
        with right:
            st.caption(f"**{symbol}** · mẫu báo cáo {TEMPLATES.get(latest.financial_template, '–')} · kỳ gần nhất "
                       f"{latest.period} · đơn vị tỷ đồng · ROE/ROA tính cho một quý, chưa quy năm")
            nd = "Không có dữ liệu"
            money = lambda v: nd if pd.isna(v) else f"{v / 1e9:,.0f} tỷ"  # noqa: E731
            pct = lambda v, d=1: nd if pd.isna(v) else charts.fmt_pct(v, d, signed=False)  # noqa: E731
            qoq = lambda v: charts.fmt_pct(v, 1) + " so với quý trước" if pd.notna(v) else None  # noqa: E731
            if latest.is_period_suspect:
                ui.callout(f"Đang xem kỳ {latest.period} bị gắn cờ nghi vấn: số liệu có thể là số cộng dồn.", "warn")
            ui.kpi_row([
                dict(label=revenue_label, value=money(latest.revenue), delta=qoq(latest.revenue_growth_qoq), tone="lavender"),
                dict(label="Lợi nhuận sau thuế", value=money(latest.net_profit_after_tax),
                     delta=qoq(latest.net_profit_growth_qoq), tone="mint"),
                dict(label="Biên lợi nhuận ròng", value=pct(latest.net_margin), tone="yellow"),
                dict(label="ROE quý", value=pct(latest.roe_quarter, 2), tone="blue",
                     help="Một quý, chưa quy năm; chưa xác minh mẫu số"),
            ])

        fig = go.Figure()
        for col, name, color in (("revenue", revenue_label, charts.PURPLE),
                                 ("net_profit_after_tax", "Lợi nhuận sau thuế", charts.MINT)):
            fig.add_trace(go.Bar(x=one.period, y=one[col] / 1e9, name=name,
                                 marker=dict(color=color, line=dict(color=charts.SURFACE, width=2)),
                                 hovertemplate=f"%{{y:,.0f}} tỷ<extra>{name}</extra>"))
        fig.update_layout(barmode="group")
        charts.show(charts.style(fig, height=320, title=f"{symbol}: {revenue_label.lower()} và lợi nhuận sau thuế theo quý (tỷ đồng)",
                                 y_format=",.0f").update_xaxes(type="category"), key="fin_bar")

        view = one.assign(**{c: one[c] / 1e9 for c in ["revenue", "gross_profit", "net_profit_after_tax", "total_assets",
                                                        "total_liabilities", "equity", "net_cash_from_operating"]})
        view = view[["period", "revenue", "gross_profit", "net_profit_after_tax", "total_assets", "total_liabilities",
                     "equity", "net_cash_from_operating", "net_margin", "debt_to_equity", "roe_quarter",
                     "is_period_suspect"]]
        pct = st.column_config.NumberColumn(format="percent")
        bn = lambda label: st.column_config.NumberColumn(label, format="%,.0f")  # noqa: E731
        charts.table(view, column_config={
            "period": "Kỳ", "revenue": bn(revenue_label), "gross_profit": bn("LN gộp"),
            "net_profit_after_tax": bn("LNST"), "total_assets": bn("Tổng tài sản"),
            "total_liabilities": bn("Nợ phải trả"), "equity": bn("Vốn CSH"),
            "net_cash_from_operating": bn("LCTT từ HĐKD"),
            "net_margin": st.column_config.NumberColumn("Biên ròng", format="percent"),
            "debt_to_equity": st.column_config.NumberColumn("Nợ/Vốn", format="%.2f"),
            "roe_quarter": st.column_config.NumberColumn("ROE quý", format="percent"),
            "is_period_suspect": st.column_config.CheckboxColumn("Nghi vấn"),
        })
        st.caption("Ô trống là chỉ tiêu NULL ở nguồn: hiển thị là không có dữ liệu, không quy về 0. Tổng tài sản lấy từ "
                   "tổng nguồn vốn vì `BS_TOTAL_ASSETS` không có giá trị ở nguồn. Dashboard không tự tính P/E, P/B, EPS "
                   "vì thiếu số cổ phiếu và ngày công bố báo cáo.")

    st.subheader("So sánh giữa các mã")
    METRICS = {"ROE quý": ("roe_quarter", ".1%"), "Biên lợi nhuận ròng": ("net_margin", ".1%"),
               "Nợ phải trả / Vốn chủ sở hữu": ("debt_to_equity", ".2f"),
               "Tăng trưởng LNST so với quý trước": ("net_profit_growth_qoq", "+.1%")}
    a, b = st.columns(2)
    periods = sorted(fin.loc[~fin.is_period_suspect, "period"].unique(), reverse=True)
    period = a.selectbox("Kỳ", periods)
    metric_name = b.selectbox("Chỉ tiêu", list(METRICS))
    col, fmt = METRICS[metric_name]
    cmp_df = fin[(fin.period == period) & fin[col].notna()][["symbol", col]]
    if cmp_df.empty:
        st.info("Kỳ này không có giá trị cho chỉ tiêu đã chọn.")
    else:
        fig = charts.signed_hbar(cmp_df, "symbol", col, hover_format=fmt)
        charts.show(charts.style(fig, height=max(300, 24 * len(cmp_df) + 70), title=f"{metric_name} – kỳ {period}",
                                 legend=False).update_xaxes(tickformat=fmt, showgrid=True, gridcolor=charts.GRID)
                    .update_yaxes(showgrid=False), key="fin_cmp")
        st.caption("Ngân hàng, công ty chứng khoán và doanh nghiệp có cấu trúc báo cáo khác nhau; "
                   "nên so sánh trong cùng nhóm.")

# =========================================================================== CẢNH BÁO
with tab_alert:
    ui.callout("Đây là tín hiệu minh họa sinh từ các quy tắc cố định trên dữ liệu lịch sử (rule-based educational signals), "
               "không phải khuyến nghị mua bán. Ví dụ RSI quá bán chỉ nghĩa là giá đã giảm nhanh, không có nghĩa nên mua.", "info")
    lo, hi = wh.price_date_bounds()
    f1, f2, f3, f4 = st.columns([1.2, 1.5, 2, 1.3])
    days = f1.selectbox("Khoảng thời gian", [7, 30, 90, 365], index=1, format_func=lambda d: f"{d} ngày gần nhất")
    pick_symbols = f2.multiselect("Mã", wh.symbols(), placeholder="Tất cả")
    pick_rules = f3.multiselect("Quy tắc", list(RULES), format_func=RULES.get, placeholder="Tất cả")
    pick_signal = f4.multiselect("Chiều tín hiệu", list(SIGNALS), format_func=SIGNALS.get, placeholder="Tất cả")

    alerts = wh.query("select trade_date, symbol, rule_code, signal, observed_value, threshold_value, reason, close "
                      "from gold.mart_stock_alerts where trade_date >= ? order by trade_date desc, symbol",
                      ((hi - pd.Timedelta(days=days)).date(),))
    if pick_symbols:
        alerts = alerts[alerts.symbol.isin(pick_symbols)]
    if pick_rules:
        alerts = alerts[alerts.rule_code.isin(pick_rules)]
    if pick_signal:
        alerts = alerts[alerts.signal.isin(pick_signal)]

    n_bull, n_bear = int((alerts.signal == "bullish").sum()), int((alerts.signal == "bearish").sum())
    n_neu = int((alerts.signal == "neutral").sum())
    assert n_bull + n_bear + n_neu == len(alerts), "Tổng tín hiệu không khớp (có giá trị signal ngoài 3 loại)"
    ui.kpi_row([
        dict(label="Tổng số tín hiệu", value=f"{len(alerts):,}", tone="lavender", help=f"Tính đến {hi:%d/%m/%Y}"),
        dict(label=SIGNALS["bullish"], value=f"{n_bull:,}", tone="mint",
             help=f"{n_bull / len(alerts):.0%} tổng" if len(alerts) else None),
        dict(label=SIGNALS["bearish"], value=f"{n_bear:,}", tone="yellow",
             help=f"{n_bear / len(alerts):.0%} tổng" if len(alerts) else None),
        dict(label=SIGNALS["neutral"], value=f"{n_neu:,}", tone="blue",
             help=f"{n_neu / len(alerts):.0%} tổng" if len(alerts) else None),
        dict(label="Số mã có tín hiệu", value=f"{alerts.symbol.nunique()}", tone="white"),
    ])
    st.caption("Tích cực + Tiêu cực + Trung tính = Tổng số tín hiệu.")

    if alerts.empty:
        st.info("Không có tín hiệu nào khớp bộ lọc.")
    else:
        by_rule = alerts.groupby("rule_code").size().reindex(list(RULES)).dropna().astype(int).reset_index(name="n")
        by_rule["label"] = by_rule.rule_code.map(RULES)
        fig = go.Figure(go.Bar(x=by_rule.n, y=by_rule.label, orientation="h", text=by_rule.n, textposition="outside",
                               marker=dict(color=charts.PURPLE, line=dict(width=0)), cliponaxis=False,
                               hovertemplate="%{y}: %{x} tín hiệu<extra></extra>"))
        fig.update_layout(hovermode="closest")
        charts.show(charts.style(fig, height=60 + 34 * len(by_rule), title="Số tín hiệu theo quy tắc", legend=False)
                    .update_yaxes(autorange="reversed", showgrid=False).update_xaxes(showticklabels=False), key="al_rule")

        view = alerts.assign(rule=alerts.rule_code.map(RULES), signal=alerts.signal.map(SIGNALS))
        charts.table(view[["trade_date", "symbol", "rule", "signal", "reason", "observed_value", "threshold_value", "close"]],
                     column_config={
                         "trade_date": st.column_config.DateColumn("Ngày", format="DD/MM/YYYY"),
                         "symbol": "Mã", "rule": "Quy tắc", "signal": "Chiều",
                         "reason": st.column_config.TextColumn("Giải thích điều kiện", width="large"),
                         "observed_value": st.column_config.NumberColumn("Giá trị quan sát", format="%.3f"),
                         "threshold_value": st.column_config.NumberColumn("Ngưỡng", format="%.3f"),
                         "close": st.column_config.NumberColumn("Giá đóng cửa", format="%.2f"),
                     })
        with st.expander("Điều kiện của từng quy tắc"):
            st.markdown("""
| Quy tắc | Điều kiện phát tín hiệu |
|---|---|
| SMA20 cắt lên / cắt xuống SMA50 | SMA20 đổi vị trí so với SMA50 giữa hai phiên liên tiếp |
| RSI vào vùng quá mua / quá bán | RSI14 vừa vượt lên 70 hoặc vừa rơi xuống 30 |
| Khối lượng đột biến | Khối lượng ≥ 2,5 lần trung bình 20 phiên trước |
| Tăng / giảm mạnh trong phiên | Giá đóng cửa thay đổi từ 5% trở lên so với phiên trước |
| Giảm sâu so với đỉnh | Giá vừa giảm quá 20% so với đỉnh đóng cửa kể từ 04/01/2021 |

Ngưỡng đặt trong `dbt_project/dbt_project.yml` (mục `vars`).
""")

