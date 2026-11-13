# Vnstock Medallion Warehouse — Nhóm 10

Kho dữ liệu chứng khoán Việt Nam theo kiến trúc **Medallion (Bronze → Silver → Gold)**, dựng từ
126 extract Vnstock/KBS của lần thu thập `initial_20261103` (61.798 bản ghi).

```
Vnstock/KBS ──► ingest_vnstock.py ──► Parquet + meta.json + manifest      (đã có)
                                          │
                    ingestion/load_bronze.py   (đối soát số dòng + checksum)
                                          ▼
   BRONZE  7 bảng   price_daily_raw · index_daily_raw · company_overview_raw
                    income_statement_raw · balance_sheet_raw · cash_flow_raw · ingestion_audit
                                          │  dbt (chuẩn hóa, khử trùng theo khóa, quality test)
                                          ▼
   SILVER  6 model  stg_price_daily · stg_index_daily · stg_company
                    stg_income_statement · stg_balance_sheet · stg_cash_flow   (+ dq_issue_log)
                                          │  dbt (Star Schema + marts)
                                          ▼
   GOLD   10 model  dim_ticker · dim_date · fact_price_daily · fact_index_daily · fact_financial_metric
                    mart_technical_indicators · mart_stock_vs_index · mart_financial_summary
                    mart_stock_alerts · mart_pipeline_health

   Dagster (orchestration/definitions.py) điều phối toàn bộ: bronze_load → dbt build (model + test).
```

## Chạy nhanh (local, offline, không cần cloud)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python scripts\run_pipeline.py
```

`run_pipeline.py` làm 3 bước: nạp Bronze → `dbt build` (Silver + Gold + toàn bộ test) → kiểm chứng
độc lập bằng pandas. Kho nằm ở `warehouse/vnstock.duckdb`. Chạy lại bao nhiêu lần cũng cho cùng kết
quả (Bronze thay thế đúng batch; Silver/Gold dựng lại toàn bộ).

Raw data được tự dò theo thứ tự: biến `RAW_RUNS_DIR` → `data/raw/runs` →
`../Vnstock_RawData_Ingestion/raw/runs`.

Các lệnh riêng lẻ:

| Việc | Lệnh |
|---|---|
| Chỉ nạp Bronze | `python ingestion/load_bronze.py [--run initial_20261103]` |
| Chỉ dựng lại Silver/Gold | `python scripts/run_pipeline.py --skip-bronze` |
| Chỉ kiểm chứng | `python scripts/validate_pipeline.py` |
| dbt trực tiếp | `cd dbt_project; dbt build --profiles-dir .` |
| Tài liệu + lineage dbt | `cd dbt_project; dbt docs generate --profiles-dir .; dbt docs serve --profiles-dir .` |
| Dagster UI | `dagster dev -m orchestration.definitions` → job `initial_load_job` (offline) / `daily_refresh_job` (thu thập + nạp) |
| Dashboard | `streamlit run app/streamlit_app.py` → http://localhost:8501 |
| Truy vấn thử | `python -c "import duckdb; print(duckdb.connect('warehouse/vnstock.duckdb').sql('select * from gold.mart_pipeline_health'))"` |

## Dashboard Streamlit

Bốn trang, chỉ đọc kho đã dựng (không gọi Vnstock khi mở trang), cache truy vấn 5 phút:

| Trang | Nội dung | Nguồn |
|---|---|---|
| 1 · Market Overview | VN-Index, tăng/giảm, thanh khoản, lợi suất 40 mã so với chỉ số, lọc theo khoảng ngày | fact_index_daily, fact_price_daily, mart_technical_indicators |
| 2 · Stock Analysis | Nến + SMA20/50, khối lượng, RSI14, lợi suất lũy kế so với VN-Index, hồ sơ | fact_price_daily, mart_technical_indicators, mart_stock_vs_index, dim_ticker |
| 3 · Financials & Alerts | Chỉ tiêu theo quý, so sánh giữa các mã, tín hiệu theo quy tắc kèm giải thích | mart_financial_summary, mart_stock_alerts |
| 4 · Pipeline Health | Đối soát nạp, trạng thái từng bảng, kết quả dbt test, nhật ký sai lệch, audit | mart_pipeline_health, dq_issue_log, ingestion_audit, target/run_results.json |

Chạy lệnh từ thư mục gốc của repo để nhận cấu hình giao diện trong `.streamlit/config.toml`. Lớp truy vấn
`app/services/warehouse.py` đọc DuckDB local hoặc BigQuery tùy `WAREHOUSE_BACKEND`; thanh bên mỗi trang ghi rõ
kho đang đọc.

## Thiết kế từng tầng

**Bronze** — giữ nguyên cột nghiệp vụ của nguồn, chỉ thêm `symbol`, `report_period` (BCTC) và
metadata `_source, _extracted_at, _ingested_at, _batch_id, _source_file`. Chỉ nạp **Parquet** (CSV là
bản sao của cùng extract). Append-only theo batch; `ingestion_audit` có 1 dòng/extract với số dòng
manifest, số dòng thực nạp và kết quả checksum `parquet_sha256`.

**Silver** — đổi tên/ép kiểu, `time` → `trade_date` theo giờ Việt Nam, tách `period` thành
năm/quý/ngày cuối kỳ, chuẩn hóa đơn vị. Khi một khóa nghiệp vụ có ở nhiều batch thì giữ bản trích
xuất **mới nhất** (đây là cơ chế cho nạp tăng dần có overlap). Bản ghi nghi vấn không bị xóa mà ghi
vào `silver.dq_issue_log` (error / warn / info). Quy tắc hiện có: lệch bao OHLC, giá ≤ 0, khối lượng âm/bằng 0,
thiếu phiên so với lịch thị trường, biến động vượt biên độ sàn, chỉ tiêu cốt lõi NULL, sai đẳng thức kế toán,
bất thường quy mô kỳ báo cáo, kỳ sai định dạng, đơn vị lạ.

**Gold** — Star Schema: `fact_price_daily` (ticker_key + date_key), `fact_financial_metric`
(mã / kỳ / báo cáo / chỉ tiêu), `fact_index_daily`, cùng `dim_ticker`, `dim_date`. Năm data mart phục
vụ dashboard; ngưỡng cảnh báo đặt ở `vars` trong `dbt_project.yml`.

## Kết quả profiling đã dùng để chốt thiết kế

- Giá: 40 mã × 1.453 phiên (04/01/2021 → 03/11/2026), không trùng khóa, không lỗi logic OHLC,
  không NULL. Riêng **VND thiếu 6 phiên** so với lịch thị trường. Đơn vị giá: **nghìn đồng**.
- VN-Index: 1.000 phiên, chỉ từ **28/10/2022** → mọi so sánh với chỉ số giới hạn trong khoảng chung.
- BCTC: 15 mã, **chỉ 4 quý** (2025-Q4 → 2026-Q3), dạng long, đơn vị VNĐ, không trùng
  (mã, kỳ, chỉ tiêu). Có 3 mẫu báo cáo: ngân hàng (ACB, MBB, TCB, VCB), chứng khoán (SSI), doanh nghiệp.
- `BS_TOTAL_ASSETS` **luôn NULL** ở nguồn → tổng tài sản lấy từ `BS_TOTAL_LIABILITIES_AND_EQUITY`
  (ghi rõ ở cột `total_assets_basis`). Nhiều chỉ tiêu lưu chuyển tiền tệ NULL ở 2 quý gần nhất.
- **Kỳ `2025-Q4` có quy mô gấp ~4 lần các quý 2026 ở cả 15 mã** (kể cả số dư bảng cân đối), và 11/15 mã
  vi phạm đẳng thức Nợ + Vốn = Tổng nguồn vốn ở kỳ này → nghi nguồn trả số cộng dồn cả năm dưới nhãn Q4.
  Kỳ này được gắn `is_period_suspect` trong `mart_financial_summary` và không dùng để tính QoQ.
- VN-Index ngày **15/05/2023** có close (1065,71) < low (1067,15) ở nguồn → giữ bản ghi, gắn cờ
  `is_ohlc_consistent = false`, test dbt tương ứng ở mức `warn`.
- Hồ sơ: không có tên công ty và mã ngành; 6 mã thiếu `founded_date`; 1 snapshot/mã (chưa đủ cho SCD2).

## Giới hạn cần nêu trong báo cáo

- Chưa xác minh giá đã điều chỉnh cổ tức/chia tách; các phiên biến động vượt biên độ sàn được ghi ở
  `dq_issue_log` (`RETURN_EXCEEDS_PRICE_LIMIT`).
- Nguồn không có ngày công bố BCTC (`published_at`) → không ghép BCTC với giá để backtest.
- RSI14 dùng trung bình đơn giản 14 phiên (Cutler), không phải làm mượt Wilder.
- ROE/ROA tính theo một quý trên số dư cuối kỳ, chưa quy năm.
- Cảnh báo là tín hiệu minh họa theo quy tắc, không phải khuyến nghị giao dịch.

## Chạy trên Google BigQuery

Model dbt viết theo cú pháp chung, các khác biệt DuckDB/BigQuery gom trong `macros/cross_db.sql`;
`generate_schema_name` giữ đúng tên dataset `bronze` / `silver` / `gold` (không ghép tiền tố target).

```powershell
gcloud auth application-default login          # ADC, không lưu khóa JSON trong repo
copy .env.example .env                          # sửa: WAREHOUSE_BACKEND=bigquery, GCP_PROJECT_ID=...
.venv\Scripts\python scripts\run_pipeline.py    # Bronze -> dbt build (target bigquery) -> kiểm chứng
streamlit run app/streamlit_app.py              # dashboard đọc Gold trên BigQuery
```

Mọi script (loader, dbt, validate, Dagster, Streamlit) đọc `.env` ở gốc repo; biến môi trường đặt sẵn được
ưu tiên. Loader **không dùng DML**: thay thế batch bằng query job ghi đè (`WRITE_TRUNCATE`, lọc bỏ batch
cũ) rồi load job `WRITE_APPEND`, nên chạy được cả trên BigQuery Sandbox chưa bật Billing (lưu ý Sandbox
tự xóa bảng sau 60 ngày). Dataset `bronze` được tạo đúng `BQ_LOCATION`; dbt tạo `silver`/`gold` cùng location.

**Đã chạy thật ngày 13/11/2026** trên project `vnstock-medallion-nhom10` (`asia-southeast1`, Sandbox): Bronze
61.798/61.798 dòng, dbt 134 PASS · 1 WARN · 0 ERROR, kiểm chứng 21/21, Dagster `initial_load_job` thành công,
Streamlit 4 trang đọc Gold trên BigQuery, 24/24 bảng khớp số dòng với DuckDB. Log và ảnh ở `evidence/`.

## Thu thập batch mới (incremental)

Cách 1 — Dagster: job `daily_refresh_job` gồm asset `raw/vnstock_extract` (gọi `ingest_vnstock.py`, tạo
run `daily_YYYYMMDD`, giá/chỉ số lấy cửa sổ `lookback_days` = 14 ngày gần nhất) → Bronze → dbt build.
Lịch 18:30 thứ 2–6 (giờ VN) mặc định STOPPED, bật trong UI. Cần cài vnstock và đặt `VNSTOCK_API_KEY`.
Run mới được ghi vào cùng thư mục raw mà loader đang đọc nên lịch sử `initial_20261103` được giữ.

Cách 2 — thủ công:

```powershell
python ingestion\ingest_vnstock.py --config ingestion\config.json --out ..\Vnstock_RawData_Ingestion --run-id daily_YYYYMMDD --start YYYY-MM-DD
python scripts\run_pipeline.py
```

Mỗi lần thu thập dùng `run_id` mới; Bronze giữ mọi batch, Silver tự chọn phiên bản mới nhất theo khóa
(overlap giữa các batch được khử trùng). Extract nguồn trả về rỗng (vd. cửa sổ rơi vào ngày nghỉ) được ghi
audit với trạng thái `empty` — hợp lệ, không làm dừng pipeline. Khi `data/raw/runs` tồn tại, loader đọc ở
đó thay vì thư mục gốc của nhóm — đặt `RAW_RUNS_DIR` để cố định.

## Cấu trúc thư mục

```
ingestion/      ingest_vnstock.py, config.json (có sẵn) · load_bronze.py (nạp Bronze + audit)
dbt_project/    models/sources.yml · models/silver · models/gold/{dimensions,facts,marts} · macros
orchestration/  definitions.py (Dagster: asset, job, schedule)
app/            streamlit_app.py (điều hướng) · pages/ (6 trang) · styles/theme.css · services/warehouse.py · components/charts.py
scripts/        run_pipeline.py · validate_pipeline.py
warehouse/      vnstock.duckdb (sinh ra khi chạy, không commit)
```


## Nâng cấp VNStock Intelligence 2.0
Giao diện Fox Stocks Light, 6 trang, mart return/risk/correlation và Portfolio Lab: xem [docs/ui_upgrade_and_analytics.md](docs/ui_upgrade_and_analytics.md).
