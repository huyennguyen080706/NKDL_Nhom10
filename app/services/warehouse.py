"""Lớp truy vấn kho cho dashboard. Ứng dụng CHỈ đọc tầng Gold/Silver/Bronze đã dựng sẵn,
không gọi Vnstock và không ghi vào kho.

Backend chọn theo WAREHOUSE_BACKEND (đọc cả từ `.env`):
- duckdb   : mỗi truy vấn mở kết nối read-only rồi đóng ngay để không khóa file khi pipeline chạy lại.
- bigquery : đọc dataset bronze/silver/gold trong GCP_PROJECT_ID qua Application Default Credentials;
             SQL dùng tham số vị trí `?` (BigQuery cũng hỗ trợ) nên các trang không phải viết lại.
Kết quả được cache 5 phút (nút "Làm mới dữ liệu" ở thanh bên xóa cache).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ingestion import settings  # noqa: E402  (nạp .env)

BACKEND = settings.backend()
DB_PATH = Path(os.getenv("DUCKDB_PATH", ROOT / "warehouse" / "vnstock.duckdb")).expanduser().resolve()
GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "")
BQ_LOCATION = os.getenv("BQ_LOCATION") or None
DBT_RUN_RESULTS = ROOT / "dbt_project" / "target" / "run_results.json"


def backend_label() -> str:
    return f"BigQuery · {GCP_PROJECT}" if BACKEND == "bigquery" else "DuckDB local"


@st.cache_resource(show_spinner=False)
def _bq_client():
    from google.cloud import bigquery

    return bigquery.Client(project=GCP_PROJECT, location=BQ_LOCATION)


def _bq_param(value):
    from google.cloud import bigquery

    if isinstance(value, bool):
        kind = "BOOL"
    elif isinstance(value, int):
        kind = "INT64"
    elif isinstance(value, float):
        kind = "FLOAT64"
    elif isinstance(value, (pd.Timestamp, dt.datetime)):
        kind = "TIMESTAMP"
    elif isinstance(value, dt.date):
        kind = "DATE"
    else:
        kind = "STRING"
    return bigquery.ScalarQueryParameter(None, kind, value)


def _query_bigquery(sql: str, params: tuple) -> pd.DataFrame:
    from google.cloud import bigquery

    job_config = bigquery.QueryJobConfig(query_parameters=[_bq_param(p) for p in params])
    df = _bq_client().query(sql, job_config=job_config).to_dataframe(create_bqstorage_client=False)
    # Đồng nhất kiểu với DuckDB: DATE -> datetime64, số nguyên nullable -> float khi có NULL
    for col in df.columns:
        if str(df[col].dtype) == "dbdate":
            df[col] = pd.to_datetime(df[col])
    return df


def _query_duckdb(sql: str, params: tuple) -> pd.DataFrame:
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return con.execute(sql, list(params)).df()
    finally:
        con.close()


@st.cache_data(ttl=300, show_spinner=False)
def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    if BACKEND == "bigquery":
        return _query_bigquery(sql, params)
    return _query_duckdb(sql, params)


def require_warehouse() -> None:
    """Dừng trang với hướng dẫn rõ ràng nếu kho chưa được dựng."""
    if BACKEND == "bigquery" and not GCP_PROJECT:
        st.error("WAREHOUSE_BACKEND=bigquery nhưng thiếu GCP_PROJECT_ID (đặt trong `.env`).")
        st.stop()
    if BACKEND != "bigquery" and not DB_PATH.is_file():
        st.error(f"Chưa có kho dữ liệu tại `{DB_PATH}`.")
        st.code("python scripts/run_pipeline.py", language="bash")
        st.stop()
    try:
        query("select 1 from gold.mart_pipeline_health limit 1")
    except Exception as exc:  # kho có nhưng thiếu tầng Gold
        st.error("Kho chưa có tầng Gold. Hãy chạy pipeline trước khi mở dashboard.")
        st.code("python scripts/run_pipeline.py", language="bash")
        st.caption(f"Chi tiết: {exc}")
        st.stop()


def sidebar_footer() -> None:
    """Thông tin nguồn dữ liệu + nút làm mới, dùng chung cho mọi trang."""
    health = query("select max(last_extracted_at) as extracted, max(refreshed_at) as refreshed, "
                   "max(latest_batch_id) as batch from gold.mart_pipeline_health")
    with st.sidebar:
        st.divider()
        st.caption(
            f"Kho: **{backend_label()}**  \n"
            f"Batch: `{health.batch[0]}`  \n"
            f"Trích xuất: {pd.Timestamp(health.extracted[0]).tz_convert('Asia/Ho_Chi_Minh'):%d/%m/%Y %H:%M}  \n"
            f"Dựng Gold: {pd.Timestamp(health.refreshed[0]).tz_convert('Asia/Ho_Chi_Minh'):%d/%m/%Y %H:%M}"
        )
        if st.button("Làm mới dữ liệu", help="Xóa cache truy vấn và đọc lại từ kho"):
            st.cache_data.clear()
            st.rerun()


# ----------------------------------------------------------------------------- dữ liệu dùng chung
def symbols(only_with_financials: bool = False) -> list[str]:
    where = "where has_financials" if only_with_financials else "where trading_days > 0"
    return query(f"select symbol from gold.dim_ticker {where} order by symbol").symbol.tolist()


def price_date_bounds() -> tuple[pd.Timestamp, pd.Timestamp]:
    df = query("select min(trade_date) as lo, max(trade_date) as hi from gold.fact_price_daily")
    return pd.Timestamp(df.lo[0]), pd.Timestamp(df.hi[0])


def index_date_bounds() -> tuple[pd.Timestamp, pd.Timestamp]:
    df = query("select min(trade_date) as lo, max(trade_date) as hi from gold.fact_index_daily")
    return pd.Timestamp(df.lo[0]), pd.Timestamp(df.hi[0])


def dbt_run_results() -> tuple[pd.DataFrame, str | None]:
    """Kết quả lần `dbt build` gần nhất (đọc từ target/run_results.json)."""
    if not DBT_RUN_RESULTS.is_file():
        return pd.DataFrame(), None
    data = json.loads(DBT_RUN_RESULTS.read_text(encoding="utf-8"))
    rows = []
    for r in data.get("results", []):
        uid = r.get("unique_id", "")
        kind = uid.split(".")[0]
        rows.append({
            "loại": {"model": "model", "test": "test"}.get(kind, kind),
            "tên": uid.split(".")[2] if uid.count(".") >= 2 else uid,
            "trạng thái": r.get("status"),
            "số dòng vi phạm": r.get("failures"),
            "thời gian (s)": round(r.get("execution_time") or 0, 2),
            "thông điệp": r.get("message"),
        })
    return pd.DataFrame(rows), data.get("metadata", {}).get("generated_at")
