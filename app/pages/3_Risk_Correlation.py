"""Trang 3 - Risk & Correlation. Nguồn Gold: mart_risk_metrics, mart_return_summary, mart_correlation_pairs,
mart_technical_indicators (phân phối lợi suất)."""
import numpy as np
import pandas as pd
import streamlit as st

from components import charts, ui
from services import warehouse as wh

ui.require_marts("mart_risk_metrics", "mart_return_summary", "mart_correlation_pairs")

WINDOWS = {60: "60 phiên (~3 tháng)", 120: "120 phiên (~6 tháng)", 252: "252 phiên (~1 năm)"}
with st.sidebar:
    st.header("Bộ lọc")
    window = st.radio("Cửa sổ quan sát", list(WINDOWS), index=2, format_func=WINDOWS.get)
    all_symbols = wh.symbols()
    picks = st.multiselect("Lọc theo mã", all_symbols, placeholder="Tất cả 40 mã")
    only_full = st.checkbox("Chỉ mã đủ cửa sổ", value=True, help="Bỏ các mã chưa đủ số phiên của cửa sổ đã chọn")

risk = wh.query("select * from gold.mart_risk_metrics where window_days = ?", (window,))
if only_full:
    risk = risk[risk.is_full_window]
if picks:
    risk = risk[risk.symbol.isin(picks)]
if risk.empty:
    st.warning("Không có mã nào thỏa bộ lọc.")
    st.stop()
as_of, w_start = risk.as_of_date.max(), risk.window_start_date.min()
rf = float(risk.risk_free_rate_annual.iloc[0])

ui.page_header("Risk & Correlation", "Lợi suất, rủi ro và tương quan của rổ 40 mã trên giá đóng cửa thực.",
               [("Cửa sổ", f"{WINDOWS[window]}"), ("Từ", f"{pd.Timestamp(w_start):%d/%m/%Y}"),
                ("Đến", f"{pd.Timestamp(as_of):%d/%m/%Y}"), ("Risk-free", f"{rf:.1%}/năm (giả định)")])
ui.price_basis_note()

best = risk.loc[risk.sharpe.idxmax()] if risk.sharpe.notna().any() else None
ui.kpi_row([
    dict(label="Số mã trong bảng", value=f"{len(risk)}", tone="lavender", help=f"Cửa sổ {window} phiên"),
    dict(label="Biến động quy năm (trung vị)", value=charts.fmt_pct(risk.annualized_volatility.median(), 1, signed=False),
         tone="yellow", help="Độ lệch chuẩn lợi suất ngày × √252"),
    dict(label="Max drawdown (trung vị)", value=charts.fmt_pct(risk.max_drawdown.median(), 1), tone="blue",
         help="Mức giảm lớn nhất từ đỉnh trong cửa sổ"),
    dict(label="Sharpe cao nhất", value=f"{best.sharpe:.2f}" if best is not None else "–", tone="mint",
         help=f"{best.symbol} · rf {rf:.1%}" if best is not None else None),
])

tab_rr, tab_corr, tab_ret = st.tabs(["Risk–Return", "Tương quan", "Lợi suất theo kỳ"])

# =========================================================================== RISK - RETURN
with tab_rr:
    with st.container(border=True):
        ui.section("Bản đồ rủi ro – lợi suất",
                   "Mỗi chấm là một mã: sang phải = biến động lớn hơn, lên trên = lợi suất quy năm cao hơn.")
        charts.show(charts.risk_return_scatter(risk, "annualized_volatility", "annualized_return", "symbol"), key="rr")
    with st.container(border=True):
        ui.section("Bảng Risk–Return", "Beta so với VN-Index chỉ tính trên ngày giao dịch chung; ô trống = chưa đủ 30 ngày chung.")
        view = risk[["symbol", "annualized_return", "annualized_volatility", "max_drawdown", "var95_daily", "beta",
                     "n_obs_beta", "sharpe", "n_obs"]].sort_values("sharpe", ascending=False)
        charts.table(view, column_config={
            "symbol": "Mã",
            "annualized_return": st.column_config.NumberColumn("Lợi suất quy năm", format="percent"),
            "annualized_volatility": st.column_config.NumberColumn("Biến động quy năm", format="percent"),
            "max_drawdown": st.column_config.NumberColumn("Max drawdown", format="percent"),
            "var95_daily": st.column_config.NumberColumn("VaR95 (1 ngày)", format="percent",
                                                          help="Ngưỡng lỗ một ngày ước lượng ở mức tin cậy 95% từ lịch sử; không phải mức lỗ tối đa"),
            "beta": st.column_config.NumberColumn("Beta", format="%.2f"),
            "n_obs_beta": st.column_config.NumberColumn("Ngày chung với VN-Index", format="%d"),
            "sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f"),
            "n_obs": st.column_config.NumberColumn("Số phiên", format="%d")})
        st.caption(f"Sharpe = (lợi suất quy năm − {rf:.1%}) / biến động quy năm. Lãi suất phi rủi ro là giả định, "
                   "cấu hình ở biến `risk_free_rate_annual` trong dbt_project.yml.")
        if (risk.n_obs_beta < 60).any():
            ui.callout("Một số mã có dưới 60 ngày chung với VN-Index nên beta kém tin cậy.", "warn")
    with st.container(border=True):
        ui.section("Phân phối lợi suất ngày của một mã")
        sym = st.selectbox("Mã", sorted(risk.symbol), key="hist_sym")
        rr = wh.query("select daily_return from gold.mart_technical_indicators where symbol = ? and daily_return is not null "
                      "order by trade_date desc limit ?", (sym, int(window)))
        row = risk[risk.symbol == sym].iloc[0]
        charts.show(charts.histogram(rr.daily_return, f"{sym}: {len(rr)} phiên gần nhất", row.var95_daily), key="hist")
        st.caption("Đường đỏ là ngưỡng VaR95 lịch sử: khoảng 5% số phiên có lợi suất tệ hơn mức này. "
                   "Đây là ước lượng từ quá khứ, không đảm bảo cho tương lai.")

# =========================================================================== CORRELATION
with tab_corr:
    pairs = wh.query("select * from gold.mart_correlation_pairs where window_days = ?", (window,))
    syms = sorted(set(risk.symbol) if picks else set(pairs.symbol_a) | set(pairs.symbol_b))
    if picks and len(syms) < 2:
        st.info("Chọn ít nhất 2 mã để xem tương quan.")
    elif pairs.empty:
        st.info("Chưa có dữ liệu tương quan cho cửa sổ này.")
    else:
        sub = pairs[pairs.symbol_a.isin(syms) & pairs.symbol_b.isin(syms)]
        m = pd.DataFrame(np.nan, index=syms, columns=syms)
        for r in sub.itertuples():
            m.loc[r.symbol_a, r.symbol_b] = m.loc[r.symbol_b, r.symbol_a] = r.correlation
        np.fill_diagonal(m.values, 1.0)
        low = sub[sub.quality_flag == "LOW_OBS"]
        c_win = f"{pd.Timestamp(sub.window_start_date.min()):%d/%m/%Y} → {pd.Timestamp(sub.as_of_date.max()):%d/%m/%Y}"
        iu = np.triu_indices(len(syms), 1)
        ui.kpi_row([
            dict(label="Số cặp", value=f"{len(sub):,}", tone="lavender", help=f"{len(syms)} mã"),
            dict(label="Tương quan trung bình", value=f"{np.nanmean(m.values[iu]):.2f}", tone="mint"),
            dict(label="Số ngày chung (trung vị)", value=f"{int(sub.n_obs.median())}", tone="blue", help=f"Cửa sổ {c_win}"),
            dict(label="Cặp thiếu quan sát", value=f"{len(low)}", tone="yellow", help="Dưới 60 ngày chung"),
        ])
        with st.container(border=True):
            ui.section(f"Heatmap tương quan {len(syms)}×{len(syms)}",
                       f"Pearson trên lợi suất ngày, ngày chung của từng cặp, cửa sổ {c_win}. Ô trống: không có ngày chung.")
            charts.show(charts.corr_heatmap(m, height=max(420, 17 * len(syms) + 120)), key="corr")
        if len(low):
            ui.callout(f"{len(low)} cặp có dưới 60 ngày chung (cờ LOW_OBS); hệ số của các cặp này kém ổn định.", "warn")
        with st.container(border=True):
            ui.section("Cặp tương quan cao nhất / thấp nhất")
            ok = sub[sub.quality_flag == "OK"].dropna(subset=["correlation"])
            a, b = st.columns(2)
            cols = {"symbol_a": "Mã A", "symbol_b": "Mã B",
                    "correlation": st.column_config.NumberColumn("Tương quan", format="%.2f"),
                    "n_obs": st.column_config.NumberColumn("Số ngày chung", format="%d")}
            with a:
                st.markdown("**Cao nhất**")
                charts.table(ok.nlargest(10, "correlation")[["symbol_a", "symbol_b", "correlation", "n_obs"]], column_config=cols)
            with b:
                st.markdown("**Thấp nhất (đa dạng hóa tốt)**")
                charts.table(ok.nsmallest(10, "correlation")[["symbol_a", "symbol_b", "correlation", "n_obs"]], column_config=cols)

# =========================================================================== RETURNS
with tab_ret:
    ret = wh.query("select * from gold.mart_return_summary where period_type in ('TRAIL_20D','TRAIL_60D','TRAIL_252D','YTD','ALL')")
    if picks:
        ret = ret[ret.symbol.isin(picks)]
    with st.container(border=True):
        ui.section("Xếp hạng lợi suất theo kỳ", "Price return trên giá đóng cửa; CAGR chỉ có khi kỳ dài từ 1 năm.")
        LABEL = {"TRAIL_20D": "20 phiên", "TRAIL_60D": "60 phiên", "TRAIL_252D": "252 phiên", "YTD": "Từ đầu năm", "ALL": "Toàn kỳ"}
        kind = st.selectbox("Kỳ", list(LABEL), index=2, format_func=LABEL.get)
        one = ret[ret.period_type == kind].sort_values("price_return", ascending=False)
        charts.show(charts.style(charts.signed_hbar(one, "symbol", "price_return"),
                                 height=max(320, 20 * len(one) + 60), legend=False)
                    .update_xaxes(tickformat="+.0%", showgrid=True, gridcolor=charts.GRID)
                    .update_yaxes(showgrid=False), key="ret_rank")
        charts.table(one[["symbol", "start_date", "end_date", "price_return", "cagr", "n_sessions"]], column_config={
            "symbol": "Mã", "start_date": st.column_config.DateColumn("Từ", format="DD/MM/YYYY"),
            "end_date": st.column_config.DateColumn("Đến", format="DD/MM/YYYY"),
            "price_return": st.column_config.NumberColumn("Lợi suất giá", format="percent"),
            "cagr": st.column_config.NumberColumn("CAGR", format="percent"),
            "n_sessions": st.column_config.NumberColumn("Số phiên", format="%d")})
    with st.container(border=True):
        ui.section("Lợi suất theo tháng")
        sym2 = st.selectbox("Mã", sorted(risk.symbol), key="month_sym")
        mo = wh.query("select period_label, price_return from gold.mart_return_summary "
                      "where symbol = ? and period_type = 'MONTH' order by period_label", (sym2,))
        if mo.empty:
            st.info("Chưa đủ dữ liệu theo tháng.")
        else:
            mo["label"] = mo.period_label.str[:4] + "-" + mo.period_label.str[4:]
            mo["cum"] = (1 + mo.price_return).cumprod() - 1
            import plotly.graph_objects as go
            fig = go.Figure(go.Bar(x=mo.label, y=mo.price_return, marker=dict(
                color=[charts.POSITIVE if v >= 0 else charts.NEGATIVE for v in mo.price_return], line=dict(width=0)),
                hovertemplate="%{x}: %{y:+.1%}<extra>Lợi suất tháng</extra>"))
            charts.show(charts.style(fig, height=300, title=f"{sym2}: lợi suất từng tháng", legend=False,
                                     y_title="Lợi suất tháng", y_format="+.0%").update_xaxes(type="category"), key="month")
            fig2 = go.Figure(go.Scatter(x=mo.label, y=mo.cum, mode="lines", line=dict(color=charts.PURPLE, width=2),
                                        fill="tozeroy", fillcolor="rgba(100,37,254,0.08)",
                                        hovertemplate="%{y:+.1%}<extra>Lũy kế</extra>"))
            charts.show(charts.style(fig2, height=260, title=f"{sym2}: lợi suất lũy kế theo tháng", legend=False,
                                     y_title="Lũy kế", y_format="+.0%").update_xaxes(type="category"), key="cum")
            st.caption("Tháng đầu tiên của mã không có lợi suất tháng vì chưa có đáy kỳ trước.")

ui.limits_expander()
