"""Trang 5 - Portfolio Lab (Research simulation, price-only returns).
Nguồn Gold: mart_technical_indicators (lợi suất ngày), fact_index_daily (VN-Index). Tối ưu bằng analytics.portfolio_optimizer.
Trọng số chỉ ước lượng từ giai đoạn TRAIN; giai đoạn TEST (sau train) dùng để đánh giá."""
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from analytics import portfolio_optimizer as po  # noqa: E402
from analytics import risk  # noqa: E402
from components import charts, ui  # noqa: E402
from services import warehouse as wh  # noqa: E402

NAMES = {"equal_weight": "Equal Weight", "min_variance": "Minimum Variance", "max_sharpe": "Maximum Sharpe"}
COLORS = {"equal_weight": charts.BLUE, "min_variance": charts.MINT, "max_sharpe": charts.PURPLE}
lo, hi = wh.price_date_bounds()
symbols = wh.symbols()
defaults = [s for s in ("FPT", "VCB", "HPG", "VNM", "MWG") if s in symbols][:5] or symbols[:5]

with st.sidebar:
    st.header("Thiết lập danh mục")
    picks = st.multiselect("Chọn 2–10 mã", symbols, default=defaults, max_selections=10)
    picked = st.date_input("Khoảng dữ liệu", (max(lo, hi - pd.Timedelta(days=365 * 3)), hi), min_value=lo, max_value=hi,
                           format="DD/MM/YYYY")
    if len(picked) != 2:
        st.info("Chọn đủ ngày bắt đầu và ngày kết thúc.")
        st.stop()
    start, end = picked
    test_pct = st.slider("Tỷ lệ giai đoạn TEST (phía sau)", 20, 50, 30, 5, format="%d%%")
    max_w = st.slider("Trọng số tối đa mỗi mã", 10, 100, 35, 5, format="%d%%")
    rf = st.number_input("Lãi suất phi rủi ro (%/năm)", 0.0, 15.0, 4.0, 0.5)
    fee = st.number_input("Phí mua giả định (điểm cơ bản, một chiều)", 0.0, 100.0, 15.0, 5.0,
                          help="Chỉ tính một lần khi mua đầu kỳ test; chưa gồm thuế, trượt giá, thanh khoản")
    run = st.button("Chạy mô phỏng", type="primary")

ui.page_header("Portfolio Lab", "So sánh Equal Weight, Minimum Variance và Maximum Sharpe, tách train/test theo thời gian.",
               [("Trạng thái", "Research simulation"), ("Dữ liệu", "Price-only returns")])
ui.callout("Simulation · price-only returns. Đây là mô phỏng nghiên cứu trên lợi suất giá lịch sử, long-only, không tính cổ tức, "
           "thuế, trượt giá. Kết quả quá khứ không đảm bảo tương lai và đây không phải khuyến nghị đầu tư hay giao dịch tự động.",
           "warn")

if len(picks) < 2:
    st.info("Chọn ít nhất 2 mã ở thanh bên.")
    st.stop()
try:
    po.validate_constraints(len(picks), max_w / 100)
except po.PortfolioError as e:
    ui.callout(str(e), "err")
    st.stop()
if not run and "pl_ran" not in st.session_state:
    st.info("Chọn tham số rồi bấm **Chạy mô phỏng** ở thanh bên.")
    st.stop()
st.session_state["pl_ran"] = True

# ------------------------------------------------------------------ dữ liệu: ngày chung của mọi mã
ph = ",".join("?" for _ in picks)
raw = wh.query(f"select trade_date, symbol, daily_return from gold.mart_technical_indicators "
               f"where symbol in ({ph}) and trade_date between ? and ? and daily_return is not null",
               (*picks, pd.Timestamp(start).date(), pd.Timestamp(end).date()))
wide = raw.pivot(index="trade_date", columns="symbol", values="daily_return").sort_index()
n_before = len(wide)
wide = wide.dropna(how="any")
short = [s for s in picks if s not in raw.symbol.unique()]
if short:
    ui.callout(f"Không có dữ liệu trong khoảng đã chọn: {', '.join(short)}.", "err")
    st.stop()
try:
    train, test = po.split_train_test(wide, test_pct / 100)
except po.PortfolioError as e:
    ui.callout(str(e), "err")
    st.stop()
if n_before > len(wide):
    st.caption(f"Chỉ dùng {len(wide)} ngày giao dịch chung của {len(picks)} mã (bỏ {n_before - len(wide)} ngày thiếu dữ liệu ở ít nhất một mã).")

results, errors = {}, {}
for m in po.METHODS:
    try:
        results[m] = po.optimize(train, m, max_w / 100, rf / 100)
    except po.PortfolioError as e:
        errors[m] = str(e)
for m, msg in errors.items():
    ui.callout(f"{NAMES[m]}: {msg}", "err")
if not results:
    st.stop()

idx = wh.query("select trade_date, close from gold.fact_index_daily where index_code = 'VNINDEX' order by trade_date")
idx_ret = idx.set_index("trade_date").close.pct_change().dropna()
bench_test = idx_ret.reindex(test.index).dropna()
has_bench = len(bench_test) >= po.MIN_TEST_OBS and len(bench_test) >= 0.8 * len(test)

ui.kpi_row([
    dict(label="Giai đoạn TRAIN (ước lượng trọng số)", value=f"{len(train)} phiên", tone="lavender",
         help=f"{train.index.min():%d/%m/%Y} → {train.index.max():%d/%m/%Y}"),
    dict(label="Giai đoạn TEST (đánh giá)", value=f"{len(test)} phiên", tone="mint",
         help=f"{test.index.min():%d/%m/%Y} → {test.index.max():%d/%m/%Y}"),
    dict(label="Số mã", value=f"{len(picks)}", tone="yellow", help=f"Trần trọng số {max_w}%"),
    dict(label="Phí giả định", value=f"{fee:.0f} bps", tone="blue", help="Mua một lần, giữ nguyên, không cân bằng lại"),
])

# ------------------------------------------------------------------ đánh giá OUT-OF-SAMPLE
rows, curves = [], {}
for m, res in results.items():
    port_ret = test[res.weights.index] @ res.weights
    curves[NAMES[m]] = po.buy_and_hold_curve(test, res.weights, fee)
    rows.append({"Phương pháp": NAMES[m],
                 "Lợi suất TEST (tích lũy)": curves[NAMES[m]].iloc[-1] / 100 - 1,
                 "Lợi suất quy năm": risk.annualized_return(port_ret),
                 "Biến động quy năm": risk.annualized_volatility(port_ret),
                 "Max drawdown": risk.max_drawdown(curves[NAMES[m]]),
                 "Sharpe": risk.sharpe(port_ret, rf / 100),
                 "VaR95 (1 ngày)": risk.var_historical(port_ret)})
if has_bench:
    bench_curve = 100 * (1 + bench_test).cumprod()
    curves["VN-Index"] = bench_curve
    rows.append({"Phương pháp": "VN-Index (benchmark)", "Lợi suất TEST (tích lũy)": bench_curve.iloc[-1] / 100 - 1,
                 "Lợi suất quy năm": risk.annualized_return(bench_test),
                 "Biến động quy năm": risk.annualized_volatility(bench_test),
                 "Max drawdown": risk.max_drawdown(bench_curve), "Sharpe": risk.sharpe(bench_test, rf / 100),
                 "VaR95 (1 ngày)": risk.var_historical(bench_test)})
else:
    ui.callout("Không đủ ngày chung giữa giai đoạn TEST và VN-Index (chỉ số bắt đầu muộn hơn) nên tắt phần so sánh benchmark.", "warn")
perf = pd.DataFrame(rows)

with st.container(border=True):
    ui.section("Kết quả trên giai đoạn TEST (out-of-sample)",
               "Trọng số được tìm chỉ từ TRAIN; số liệu dưới đây tính trên dữ liệu phía sau mà thuật toán chưa thấy.")
    cols = st.columns(len(results))
    for col, (m, res) in zip(cols, results.items()):
        r = perf[perf["Phương pháp"] == NAMES[m]].iloc[0]
        ui.kpi(col, NAMES[m], charts.fmt_pct(r["Lợi suất TEST (tích lũy)"], 1), tone="white",
               delta=f"Sharpe {r['Sharpe']:.2f} · biến động {r['Biến động quy năm']:.0%}" if pd.notna(r["Sharpe"]) else None,
               direction="neu")
    charts.table(perf, column_config={
        c: st.column_config.NumberColumn(c, format="percent") for c in perf.columns
        if c not in ("Phương pháp", "Sharpe")} | {"Sharpe": st.column_config.NumberColumn("Sharpe", format="%.2f")})

with st.container(border=True):
    ui.section("Giá trị danh mục trên giai đoạn TEST (đầu kỳ = 100)",
               "Mua một lần đầu kỳ test theo trọng số của TRAIN, giữ nguyên, đã trừ phí giả định.")
    fig = go.Figure()
    for name, c in curves.items():
        color = charts.INDEX if name == "VN-Index" else COLORS[[k for k, v in NAMES.items() if v == name][0]]
        fig.add_trace(go.Scatter(x=c.index, y=c, name=name, mode="lines",
                                 line=dict(color=color, width=2.5, dash="dash" if name == "VN-Index" else "solid"),
                                 hovertemplate=f"%{{y:,.1f}}<extra>{name}</extra>"))
    fig.add_hline(y=100, line=dict(color=charts.AXIS, width=1, dash="dot"))
    charts.show(charts.style(fig, height=380, y_title="Giá trị (đầu kỳ = 100)", y_format=",.0f"), key="equity")

left, right = st.columns(2)
with left, st.container(border=True):
    ui.section("Phân bổ trọng số (ước lượng từ TRAIN)")
    method = st.radio("Phương pháp", list(results), format_func=NAMES.get, horizontal=True, key="alloc_m")
    w = results[method].weights
    charts.show(charts.donut(w.index, w.values), key="donut")
    charts.table(pd.DataFrame({"Mã": w.index, "Trọng số": w.values}).sort_values("Trọng số", ascending=False),
                 column_config={"Trọng số": st.column_config.NumberColumn(format="percent")})
with right, st.container(border=True):
    ui.section("So sánh rủi ro trên TEST")
    p2 = perf.melt(id_vars="Phương pháp", value_vars=["Biến động quy năm", "Max drawdown", "VaR95 (1 ngày)"],
                   var_name="Chỉ tiêu", value_name="v")
    p2["v"] = p2["v"].abs()
    fig = go.Figure()
    pal = {"Biến động quy năm": charts.PURPLE, "Max drawdown": charts.NEGATIVE, "VaR95 (1 ngày)": charts.YELLOW}
    for k, g in p2.groupby("Chỉ tiêu"):
        fig.add_trace(go.Bar(x=g["Phương pháp"], y=g.v, name=k, marker=dict(color=pal[k], line=dict(width=0)),
                             hovertemplate="%{y:.1%}<extra>" + k + "</extra>"))
    fig.update_layout(barmode="group")
    charts.show(charts.style(fig, height=360, y_title="Độ lớn (%)", y_format=".0%").update_xaxes(tickangle=-15), key="riskcmp")

with st.container(border=True):
    ui.section("Biên hiệu quả (in-sample, trên TRAIN)",
               "Đường cong là danh mục có phương sai thấp nhất cho từng mức lợi suất mục tiêu; đây là ước lượng trong mẫu huấn luyện, "
               "không phải kết quả kiểm chứng.")
    try:
        ef = po.efficient_frontier(train, max_w / 100)
        fig = go.Figure(go.Scatter(x=ef.volatility, y=ef["return"], mode="lines", name="Biên hiệu quả",
                                   line=dict(color=charts.PURPLE, width=3),
                                   hovertemplate="Biến động %{x:.1%}<br>Lợi suất %{y:+.1%}<extra></extra>"))
        for m, res in results.items():
            fig.add_trace(go.Scatter(x=[res.train_volatility], y=[res.train_return], mode="markers+text", name=NAMES[m],
                                     text=[NAMES[m]], textposition="top center",
                                     marker=dict(size=13, color=COLORS[m], line=dict(color="#fff", width=2)),
                                     hovertemplate=f"{NAMES[m]}<br>Biến động %{{x:.1%}}<br>Lợi suất %{{y:+.1%}}<extra></extra>"))
        for s in picks:
            fig.add_trace(go.Scatter(x=[train[s].std() * 252 ** 0.5], y=[train[s].mean() * 252], mode="markers+text", text=[s],
                                     textposition="bottom center", showlegend=False, textfont=dict(size=10, color=charts.MUTED),
                                     marker=dict(size=7, color=charts.NEUTRAL), hovertemplate=f"{s}<extra></extra>"))
        fig.update_layout(hovermode="closest")
        charts.style(fig, height=420)
        fig.update_xaxes(title=dict(text="Biến động quy năm", font=dict(color=charts.MUTED, size=11)), tickformat=".0%",
                         showgrid=True, gridcolor=charts.GRID)
        fig.update_yaxes(title=dict(text="Lợi suất kỳ vọng quy năm (trung bình ngày × 252)", font=dict(color=charts.MUTED, size=11)),
                         tickformat="+.0%")
        charts.show(fig, key="frontier")
    except po.PortfolioError as e:
        ui.callout(f"Không dựng được biên hiệu quả: {e}", "warn")

with st.expander("Phương pháp, giả định và hạn chế"):
    st.markdown(f"""
- **Dữ liệu**: lợi suất ngày của {len(picks)} mã trên các ngày giao dịch chung; giá đóng cửa chưa xác minh điều chỉnh cổ tức.
- **Tách thời gian**: {len(train)} phiên đầu là TRAIN, {len(test)} phiên sau là TEST; trọng số chỉ dùng TRAIN, không dùng giá hay báo cáo tài chính tương lai.
- **Ràng buộc**: long-only, tổng trọng số = 100%, mỗi mã tối đa {max_w}%; solver SLSQP, kiểm tra hội tụ và ràng buộc sau khi giải.
- **Max Sharpe / Min Variance** dùng trung bình và hiệp phương sai của TRAIN (quy năm ×252); lợi suất kỳ vọng ước lượng từ quá khứ rất nhiễu.
- **Phí**: {fee:.0f} bps một chiều khi mua đầu kỳ test; không cân bằng lại, không tính thuế, trượt giá, giới hạn thanh khoản.
- Danh sách mã hiện tại có thể thiên lệch sống sót; không dùng kết quả này để ra quyết định đầu tư.
""")
