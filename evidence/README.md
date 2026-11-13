# Bằng chứng nghiệm thu — chạy thật trên Google BigQuery (13/11/2026)

Mọi file trong thư mục này được sinh từ các lần chạy thật; không có số liệu tự điền tay.

## Môi trường

| Mục | Giá trị đã xác minh |
|---|---|
| GCP project | `vnstock-medallion-nhom10` |
| Xác thực | Application Default Credentials (`gcloud auth application-default login`), quota project = project trên; không dùng khóa JSON |
| Location | `asia-southeast1` (cả 3 dataset `bronze`, `silver`, `gold`) |
| Billing | **Chưa bật — project đang ở BigQuery Sandbox**: dataset có `default_table_expiration` = 60 ngày, bảng sẽ tự xóa khoảng **12/01/2027**. Chạy lại `scripts/run_pipeline.py` để dựng lại khi cần. |
| Công cụ | Python 3.13, dbt-core 1.12 + dbt-bigquery 1.12, dagster 1.13, streamlit 1.67 |

## Kết quả

| Hạng mục checklist | Kết quả | File |
|---|---|---|
| Nạp Bronze + đối soát manifest | 126/126 extract, **61.798 / 61.798 dòng**, checksum khớp | `logs/bigquery_run_3.log` |
| dbt build trên BigQuery | 17/17 model, **134 PASS · 1 WARN · 0 ERROR** (135 node) | `logs/bigquery_run_3.log`, `logs/bigquery_dbt_run_results.json` |
| Kiểm chứng độc lập (pandas) trên BigQuery | **21/21 đạt** | `logs/bigquery_run_3.log` |
| BigQuery khớp DuckDB local | 24/24 bảng trùng số dòng tuyệt đối | `logs/bigquery_vs_duckdb_reconciliation.txt` |
| Idempotency | Bronze nạp lại cùng batch 4 lần (3 lần `run_pipeline` + 1 lần Dagster) — vẫn 61.798 dòng, audit 126 dòng | `logs/bigquery_run_*.log`, `logs/dagster_initial_load_job_bigquery.log` |
| Dagster Bronze → Gold | `initial_load_job` **RUN_SUCCESS**: 24 asset materialize, 102 asset check | `logs/dagster_initial_load_job_bigquery.log` |
| Dagster asset graph | `raw_extract → bronze_load → silver_models → gold_marts / observability`; `daily_refresh_job` 25 asset, lịch 18:30 T2–T6 (STOPPED) | `screenshots/dagster_*.png` |
| Streamlit đọc Gold trên BigQuery | 5 trang (trang chủ + 4 trang) không lỗi; thanh bên ghi "Kho: BigQuery · vnstock-medallion-nhom10" | `screenshots/bigquery_*.png`, `logs/streamlit_bigquery_apptest.txt` |
| Hồi quy local DuckDB | 134 PASS · 1 WARN, 21/21 đạt; pytest 7/7 | `logs/duckdb_local_run.log`, `logs/pytest.log` |

Warning duy nhất là test `stg_index_ohlc_consistent`: VN-Index ngày 15/05/2023 có close < low ở nguồn —
bản ghi được giữ và gắn cờ, không trình bày là "0 vấn đề chất lượng".

## Sự cố gặp khi chạy Cloud và cách xử lý (giữ log để minh bạch)

1. `logs/bigquery_run_1.log` — 3 model BCTC lỗi `Illegal input character "\357"`: file `.sql` có BOM UTF-8
   (DuckDB bỏ qua, BigQuery thì không) → gỡ BOM.
2. `logs/bigquery_run_2.log` — `dim_date`, `dim_ticker` lỗi `Expected keyword ALL or keyword DISTINCT`:
   BigQuery không chấp nhận `UNION` trơn → đổi thành `UNION DISTINCT` (DuckDB cũng hỗ trợ).
3. Lần chạy Dagster đầu tiên lỗi 2 test `not_null` của `mart_financial_summary`: một test pytest gọi loader
   không chỉ định backend nên đã nạp dữ liệu giả (mã `AAA`, batch `run_a`) lên Bronze thật khi `.env` đặt
   `WAREHOUSE_BACKEND=bigquery`. Đã xóa batch đó khỏi BigQuery (không dùng DML), sửa test và thêm
   `tests/conftest.py` ép mọi test chạy DuckDB. Lần chạy lại thành công (log hiện tại). dbt test đã chặn được
   dữ liệu bẩn này trước khi đến dashboard.

## Chưa có bằng chứng

- `daily_refresh_job` (thu thập batch mới từ Vnstock): chưa chạy vì máy chưa cài `vnstock` và chưa có
  `VNSTOCK_API_KEY`. Đã kiểm thử phần nạp một batch thứ hai và extract rỗng ở mức unit test.
