"""Trang 6 - Data Pipeline (trước đây Pipeline Health). Nguồn: gold.mart_pipeline_health, bronze.ingestion_audit,
silver.dq_issue_log và kết quả dbt (target/run_results.json)."""
import pandas as pd
import streamlit as st

import os

from components import charts, ui
from services import warehouse as wh

ui.page_header("Data Pipeline", "Luồng Vnstock → Bronze → Silver → Gold → Dashboard: đối soát nạp, độ mới, dbt test và sai lệch dữ liệu.")

TABLE_LABEL = {
    "price_daily_raw": "Giá cổ phiếu", "index_daily_raw": "VN-Index", "company_overview_raw": "Hồ sơ doanh nghiệp",
    "income_statement_raw": "Kết quả kinh doanh", "balance_sheet_raw": "Cân đối kế toán",
    "cash_flow_raw": "Lưu chuyển tiền tệ",
}
SEVERITY = {"error": "❌ Lỗi", "warn": "⚠️ Cảnh báo", "info": "ℹ️ Ghi nhận"}
RULE_LABEL = {
    "OHLC_INCONSISTENT": "High/low không bao trùm open/close",
    "NON_POSITIVE_PRICE": "Giá ≤ 0 hoặc NULL",
    "NEGATIVE_VOLUME": "Khối lượng âm hoặc NULL",
    "ZERO_VOLUME": "Phiên không có khối lượng",
    "MULTIPLE_VERSIONS": "Khóa có ở nhiều batch",
    "RETURN_EXCEEDS_PRICE_LIMIT": "Biến động vượt biên độ sàn",
    "MISSING_TRADING_DAY": "Thiếu phiên so với lịch thị trường",
    "INVALID_PERIOD": "Kỳ báo cáo sai định dạng",
    "CORE_METRIC_MISSING": "Chỉ tiêu cốt lõi NULL",
    "BALANCE_IDENTITY_VIOLATED": "Nợ + Vốn khác Tổng nguồn vốn",
    "PERIOD_SCALE_ANOMALY": "Quy mô kỳ báo cáo bất thường",
    "UNEXPECTED_UNIT": "Đơn vị khác VND",
}

health = wh.query("select * from gold.mart_pipeline_health")
health["order"] = health.bronze_table.map({t: i for i, t in enumerate(TABLE_LABEL)})
health = health.sort_values("order")

# ------------------------------------------------------------------ sơ đồ luồng dữ liệu (số liệu thật từ kho)
gold_rows = wh.query("""select
    (select count(*) from gold.fact_price_daily) + (select count(*) from gold.fact_index_daily)
  + (select count(*) from gold.fact_financial_metric) + (select count(*) from gold.dim_ticker)
  + (select count(*) from gold.dim_date) as n""").n[0]
flow = [("Vnstock / KBS", f"{int(health.datasets_expected.sum())} extract dự kiến", "ok"),
        ("Bronze", f"{int(health.bronze_rows.sum()):,} dòng · {int(health.datasets_loaded.sum())} extract", "ok"),
        ("Silver", f"{int(health.silver_rows.sum()):,} dòng đã chuẩn hóa", "ok"),
        ("Gold", f"{int(gold_rows):,} dòng ở dim/fact", "ok"),
        ("Dashboard", "6 trang · chỉ đọc Gold", "info")]
nodes = []
for i, (name, sub, kind) in enumerate(flow):
    nodes.append(f'<div class="node"><div class="n">{ui._e(name)}</div><div class="s">{ui._e(sub)}</div></div>')
    if i < len(flow) - 1:
        nodes.append('<div class="arrow">→</div>')
st.markdown('<div class="vs-flow">' + "".join(nodes) + "</div>", unsafe_allow_html=True)
dagster_url = os.getenv("DAGSTER_URL") or (wh._SECRETS.get("DAGSTER_URL") if hasattr(wh, "_SECRETS") else None)
if dagster_url:
    st.link_button("Mở Dagster UI", str(dagster_url))
else:
    st.caption("Điều phối bằng Dagster (asset graph trong `orchestration/definitions.py`). "
               "Đặt `DAGSTER_URL` để hiện liên kết tới Dagster UI.")
st.write("")

# ------------------------------------------------------------------ tổng quan
total_manifest, total_bronze = int(health.manifest_rows.sum()), int(health.bronze_rows.sum())
lag = health.data_lag_days.dropna()
match = total_bronze == total_manifest
ui.kpi_row([
    dict(label="Extract đã nạp", value=f"{int(health.datasets_loaded.sum())}/{int(health.datasets_expected.sum())}", tone="lavender"),
    dict(label="Bản ghi Bronze / manifest", value=f"{total_bronze:,}", tone="mint" if match else "yellow",
         delta="khớp 100%" if match else f"lệch {total_bronze - total_manifest:+,}", direction="pos" if match else "neg",
         help="Đối soát số dòng nạp với manifest"),
    dict(label="Batch mới nhất", value=str(health.latest_batch_id.iloc[0]), tone="blue",
         help=f"Tổng số batch: {int(health.total_batches.max())}"),
    dict(label="Độ trễ dữ liệu giá", value=f"{int(lag.max())} ngày" if len(lag) else "Không có dữ liệu", tone="yellow",
         help="Từ phiên giao dịch mới nhất đến lúc trích xuất"),
])
st.write("")

st.subheader("Trạng thái theo bảng nguồn")
cols = st.columns(len(health))
for col, row in zip(cols, health.itertuples()):
    with col.container(border=True):
        st.markdown(f"**{TABLE_LABEL.get(row.bronze_table, row.bronze_table)}**")
        st.markdown(f"{charts.STATUS_ICON[row.status]} **{row.status}**")
        st.caption(f"{int(row.bronze_rows):,} dòng · {int(row.dq_warn_count)} cảnh báo · {int(row.dq_error_count)} lỗi")
st.caption("OK: nạp đủ, khớp manifest, không có sai lệch · WARN: có cảnh báo chất lượng dữ liệu nguồn · "
           "FAIL: nạp thiếu, lệch số dòng/checksum hoặc có lỗi chất lượng.")

view = health[["bronze_table", "silver_model", "status", "datasets_loaded", "manifest_rows", "bronze_rows",
               "is_reconciled", "silver_rows", "entities", "min_business_date", "max_business_date",
               "data_lag_days", "dq_error_count", "dq_warn_count", "dq_info_count"]].copy()
view["status"] = view.status.map(lambda s: f"{charts.STATUS_ICON[s]} {s}")
charts.table(view, column_config={
    "bronze_table": "Bảng Bronze", "silver_model": "Model Silver", "status": "Trạng thái",
    "datasets_loaded": "Extract", "manifest_rows": st.column_config.NumberColumn("Dòng manifest", format="localized"),
    "bronze_rows": st.column_config.NumberColumn("Dòng Bronze", format="localized"),
    "is_reconciled": st.column_config.CheckboxColumn("Đối soát khớp"),
    "silver_rows": st.column_config.NumberColumn("Dòng Silver", format="localized"), "entities": "Số mã",
    "min_business_date": st.column_config.DateColumn("Từ ngày", format="DD/MM/YYYY"),
    "max_business_date": st.column_config.DateColumn("Đến ngày", format="DD/MM/YYYY"),
    "data_lag_days": "Trễ (ngày)", "dq_error_count": "Lỗi", "dq_warn_count": "Cảnh báo", "dq_info_count": "Ghi nhận",
})

# ------------------------------------------------------------------ dbt
st.subheader("Kết quả dbt build gần nhất")
results, generated_at = wh.dbt_run_results()
if results.empty:
    st.info("Không có dữ liệu giám sát dbt: chưa có `dbt_project/target/run_results.json`. "
            "Chạy `python scripts/run_pipeline.py` để sinh kết quả.")
else:
    tests = results[results["loại"] == "test"]
    models = results[results["loại"] == "model"]
    n_pass, n_warn = int((tests["trạng thái"] == "pass").sum()), int((tests["trạng thái"] == "warn").sum())
    n_bad = len(tests) - n_pass - n_warn
    ui.kpi_row([
        dict(label="Model dựng thành công", value=f"{int((models['trạng thái'] == 'success').sum())}/{len(models)}", tone="lavender"),
        dict(label="✅ Test đạt", value=f"{n_pass}/{len(tests)}", tone="mint"),
        dict(label="⚠️ Test cảnh báo", value=f"{n_warn}", tone="yellow"),
        dict(label="❌ Test lỗi", value=f"{n_bad}", tone="white"),
    ])
    if generated_at:
        st.caption(f"Sinh lúc {pd.Timestamp(generated_at).tz_convert('Asia/Ho_Chi_Minh'):%d/%m/%Y %H:%M} · "
                   f"tổng thời gian chạy {results['thời gian (s)'].sum():.1f}s")
    not_pass = results[~results["trạng thái"].isin(["pass", "success"])]
    if len(not_pass):
        st.markdown("**Mục không đạt hoặc có cảnh báo**")
        charts.table(not_pass)
    with st.expander("Toàn bộ model và test"):
        charts.table(results.sort_values(["loại", "tên"]))

# ------------------------------------------------------------------ sai lệch dữ liệu
st.subheader("Nhật ký sai lệch dữ liệu")
dq = wh.query("select rule_code, severity, source_table, symbol, business_date, business_key, observed_value, detail "
              "from silver.dq_issue_log")
if dq.empty:
    st.success("Không có sai lệch nào được ghi nhận.", icon="✅")
else:
    summary = (dq.groupby(["severity", "rule_code", "source_table"])
               .agg(n=("symbol", "size"), symbols=("symbol", "nunique")).reset_index())
    summary["sev_order"] = summary.severity.map({"error": 0, "warn": 1, "info": 2})
    summary = summary.sort_values(["sev_order", "n"], ascending=[True, False])
    charts.table(pd.DataFrame({
        "Mức độ": summary.severity.map(SEVERITY), "Quy tắc": summary.rule_code.map(lambda r: RULE_LABEL.get(r, r)),
        "Bảng nguồn": summary.source_table.map(lambda t: TABLE_LABEL.get(t, t)),
        "Số bản ghi": summary.n, "Số mã": summary.symbols,
    }))
    st.caption("Bản ghi nghi vấn được giữ nguyên trong kho và gắn cờ, không bị xóa.")
    with st.expander("Chi tiết từng bản ghi"):
        rule = st.selectbox("Quy tắc", sorted(dq.rule_code.unique()), format_func=lambda r: RULE_LABEL.get(r, r))
        detail = dq[dq.rule_code == rule].sort_values(["symbol", "business_date"])
        charts.table(detail[["symbol", "business_date", "business_key", "observed_value", "detail"]], column_config={
            "symbol": "Mã", "business_date": st.column_config.DateColumn("Ngày / cuối kỳ", format="DD/MM/YYYY"),
            "business_key": "Khóa", "observed_value": st.column_config.NumberColumn("Giá trị", format="%.4f"),
            "detail": st.column_config.TextColumn("Mô tả", width="large"),
        })

# ------------------------------------------------------------------ audit
with st.expander("Nhật ký nạp Bronze (ingestion_audit)"):
    audit = wh.query("select batch_id, dataset_key, target_table, source_file, manifest_row_count, loaded_row_count, "
                     "row_count_match, checksum_ok, load_status, error_message, extracted_at, ingested_at "
                     "from bronze.ingestion_audit order by batch_id, target_table, dataset_key")
    charts.table(audit)

