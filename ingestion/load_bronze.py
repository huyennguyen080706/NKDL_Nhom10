"""Nạp tầng Bronze từ các extract Vnstock (Parquet + meta.json + manifest).

Nguyên tắc:
- Chỉ đọc Parquet (CSV là bản sao của cùng extract -> không nạp kép, AC01).
- Giữ nguyên cột nghiệp vụ của nguồn; chỉ bổ sung khóa truy vết và metadata:
  symbol, report_period (BCTC), _source, _extracted_at, _ingested_at, _batch_id, _source_file.
- Append-only theo batch: chạy lại cùng một batch sẽ thay thế đúng batch đó (idempotent),
  batch khác được giữ nguyên để Silver chọn phiên bản mới nhất.
- Mỗi extract có một dòng trong bronze.ingestion_audit để đối soát số dòng và checksum.

Backend: DuckDB (mặc định, chạy local/offline) hoặc BigQuery (WAREHOUSE_BACKEND=bigquery).

Ví dụ:
    python ingestion/load_bronze.py                      # nạp mọi run trong thư mục raw
    python ingestion/load_bronze.py --run initial_20261103
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

try:
    from ingestion import settings  # noqa: F401  (nạp .env)
except ImportError:  # chạy trực tiếp `python ingestion/load_bronze.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ingestion import settings  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]

BRONZE_SCHEMA = "bronze"
AUDIT_TABLE = "ingestion_audit"

# kind trong manifest -> bảng Bronze
KIND_TO_TABLE = {
    "prices": "price_daily_raw",
    "indexes": "index_daily_raw",
    "companies": "company_overview_raw",
    "financials/income_statement": "income_statement_raw",
    "financials/balance_sheet": "balance_sheet_raw",
    "financials/cash_flow": "cash_flow_raw",
}
FINANCIAL_KINDS = {k for k in KIND_TO_TABLE if k.startswith("financials/")}
# Trạng thái audit được coi là thành công: "loaded" (đã nạp) và "empty" (nguồn trả về 0 dòng).
OK_STATUSES = ("loaded", "empty")

AUDIT_COLUMNS = [
    "batch_id", "dataset_key", "kind", "symbol", "report_period", "target_table",
    "source_file", "source_actual", "manifest_status", "manifest_row_count",
    "file_row_count", "loaded_row_count", "row_count_match", "checksum_ok",
    "load_status", "error_message", "extracted_at", "ingested_at",
]

AUDIT_DDL = """
    batch_id varchar, dataset_key varchar, kind varchar, symbol varchar, report_period varchar,
    target_table varchar, source_file varchar, source_actual varchar, manifest_status varchar,
    manifest_row_count bigint, file_row_count bigint, loaded_row_count bigint,
    row_count_match boolean, checksum_ok boolean, load_status varchar, error_message varchar,
    extracted_at timestamp with time zone, ingested_at timestamp with time zone
"""


# --------------------------------------------------------------------------- cấu hình
def default_raw_runs_dir() -> Path:
    """Thứ tự ưu tiên: biến môi trường -> data/raw/runs trong repo -> thư mục thu thập gốc của nhóm."""
    env = os.getenv("RAW_RUNS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    in_repo = ROOT / "data" / "raw" / "runs"
    if in_repo.is_dir() and any(in_repo.iterdir()):
        return in_repo
    return (ROOT.parent / "Vnstock_RawData_Ingestion" / "raw" / "runs").resolve()


def default_duckdb_path() -> Path:
    return Path(os.getenv("DUCKDB_PATH", ROOT / "warehouse" / "vnstock.duckdb")).expanduser().resolve()


# --------------------------------------------------------------------------- đọc extract
@dataclass
class RunResult:
    batch_id: str
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    audit: pd.DataFrame | None = None

    @property
    def failed(self) -> int:
        return int((~self.audit["load_status"].isin(OK_STATUSES)).sum())


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Đưa kiểu pandas đặc thù (category, string[python]) về kiểu trung tính để nạp kho."""
    out = df.copy()
    for col in out.columns:
        dtype = out[col].dtype
        if isinstance(dtype, pd.CategoricalDtype):
            out[col] = out[col].astype("object").where(out[col].notna(), None)
        elif pd.api.types.is_string_dtype(dtype) and not pd.api.types.is_object_dtype(dtype):
            out[col] = out[col].astype("object").where(out[col].notna(), None)
    return out


def read_run(run_dir: Path, ingested_at: datetime | None = None) -> RunResult:
    """Đọc toàn bộ extract của một run, kiểm tra checksum/số dòng, trả về DataFrame theo bảng Bronze."""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    batch_id = str(manifest.get("run_id") or run_dir.name)
    ingested_at = ingested_at or datetime.now(timezone.utc)
    ingested_ts = pd.Timestamp(ingested_at)

    frames: dict[str, list[pd.DataFrame]] = {}
    audit_rows: list[dict] = []

    for dataset_key, entry in manifest.get("entries", {}).items():
        kind = entry.get("kind")
        symbol = entry.get("symbol")
        table = KIND_TO_TABLE.get(kind)
        source_file = entry.get("parquet_file")
        extracted_ts = pd.Timestamp(entry["extracted_at_utc"]) if entry.get("extracted_at_utc") else pd.NaT
        row = {
            "batch_id": batch_id, "dataset_key": dataset_key, "kind": kind, "symbol": symbol,
            "report_period": entry.get("report_period"), "target_table": table,
            "source_file": source_file, "source_actual": entry.get("source_actual"),
            "manifest_status": entry.get("status"), "manifest_row_count": entry.get("row_count"),
            "file_row_count": None, "loaded_row_count": 0, "row_count_match": False,
            "checksum_ok": None, "load_status": "failed", "error_message": None,
            "extracted_at": extracted_ts, "ingested_at": ingested_ts,
        }
        try:
            if table is None:
                raise ValueError(f"kind không được hỗ trợ: {kind!r}")
            if entry.get("status") == "empty" and not entry.get("row_count"):
                # nguồn trả về rỗng (vd. cửa sổ nạp tăng dần rơi vào ngày nghỉ): hợp lệ, 0 dòng
                row["load_status"] = "empty"
                audit_rows.append(row)
                continue
            if entry.get("status") != "ok":
                row["load_status"] = "skipped"
                raise ValueError(f"extract có status={entry.get('status')!r} trong manifest")
            parquet_path = run_dir / source_file
            df = pd.read_parquet(parquet_path)
            row["file_row_count"] = len(df)

            meta_path = run_dir / entry["metadata_file"] if entry.get("metadata_file") else None
            if meta_path and meta_path.is_file():
                expected = json.loads(meta_path.read_text(encoding="utf-8")).get("parquet_sha256")
                if expected:
                    row["checksum_ok"] = _sha256(parquet_path) == expected
                    if not row["checksum_ok"]:
                        raise ValueError("parquet_sha256 không khớp meta.json")
            if entry.get("row_count") is not None and len(df) != int(entry["row_count"]):
                raise ValueError(f"số dòng file ({len(df)}) khác manifest ({entry['row_count']})")

            df = _normalize_dtypes(df)
            if "symbol" not in df.columns:
                df.insert(0, "symbol", symbol)
            if kind in FINANCIAL_KINDS:
                df.insert(1, "report_period", entry.get("report_period"))
            df["_source"] = entry.get("source_actual")
            df["_extracted_at"] = extracted_ts
            df["_ingested_at"] = ingested_ts
            df["_batch_id"] = batch_id
            df["_source_file"] = source_file
            frames.setdefault(table, []).append(df)
            row["load_status"] = "loaded"
        except Exception as exc:  # ghi nhận lỗi theo từng extract, không dừng cả batch
            row["error_message"] = f"{type(exc).__name__}: {exc}"
        audit_rows.append(row)

    result = RunResult(batch_id=batch_id)
    result.tables = {t: pd.concat(parts, ignore_index=True) for t, parts in frames.items()}
    audit = pd.DataFrame(audit_rows, columns=AUDIT_COLUMNS)
    audit["manifest_row_count"] = audit["manifest_row_count"].astype("Int64")
    audit["file_row_count"] = audit["file_row_count"].astype("Int64")
    audit["checksum_ok"] = audit["checksum_ok"].astype("boolean")
    for col in ("symbol", "report_period", "target_table", "source_file", "source_actual", "error_message"):
        audit[col] = audit[col].astype("object").where(audit[col].notna(), None)
    result.audit = audit
    return result


def _finalize_audit(audit: pd.DataFrame, loaded_counts: dict[tuple[str, str], int]) -> pd.DataFrame:
    """Điền số dòng thực tế đã nằm trong Bronze (đếm lại từ kho) và cờ đối soát."""
    audit = audit.copy()
    audit["loaded_row_count"] = [
        int(loaded_counts.get((t, f), 0)) if s == "loaded" else 0
        for t, f, s in zip(audit["target_table"], audit["source_file"], audit["load_status"])
    ]
    audit["row_count_match"] = (
        audit["manifest_row_count"].notna()
        & (audit["loaded_row_count"] == audit["manifest_row_count"].fillna(-1))
    ).astype(bool)
    return audit


# --------------------------------------------------------------------------- backend DuckDB
def load_duckdb(result: RunResult, db_path: Path) -> pd.DataFrame:
    import duckdb

    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(f"create schema if not exists {BRONZE_SCHEMA}")
        con.execute("begin transaction")
        counts: dict[tuple[str, str], int] = {}
        for table, df in result.tables.items():
            fq = f"{BRONZE_SCHEMA}.{table}"
            con.register("incoming_df", df)
            con.execute(f"create table if not exists {fq} as select * from incoming_df limit 0")
            con.execute(f"delete from {fq} where _batch_id = ?", [result.batch_id])
            con.execute(f"insert into {fq} by name select * from incoming_df")
            con.unregister("incoming_df")
            for source_file, n in con.execute(
                f"select _source_file, count(*) from {fq} where _batch_id = ? group by 1", [result.batch_id]
            ).fetchall():
                counts[(table, source_file)] = n

        audit = _finalize_audit(result.audit, counts)
        fq_audit = f"{BRONZE_SCHEMA}.{AUDIT_TABLE}"
        con.register("audit_df", audit)
        # DDL tường minh: cột toàn NULL (vd. error_message) không bị suy diễn sai kiểu.
        con.execute(f"create table if not exists {fq_audit} ({AUDIT_DDL})")
        con.execute(f"delete from {fq_audit} where batch_id = ?", [result.batch_id])
        con.execute(f"insert into {fq_audit} by name select * from audit_df")
        con.unregister("audit_df")
        con.execute("commit")
        return audit
    except Exception:
        con.execute("rollback")
        raise
    finally:
        con.close()


# --------------------------------------------------------------------------- backend BigQuery
def _audit_bq_schema():
    from google.cloud import bigquery

    types = {
        "manifest_row_count": "INT64", "file_row_count": "INT64", "loaded_row_count": "INT64",
        "row_count_match": "BOOL", "checksum_ok": "BOOL",
        "extracted_at": "TIMESTAMP", "ingested_at": "TIMESTAMP",
    }
    return [bigquery.SchemaField(c, types.get(c, "STRING")) for c in AUDIT_COLUMNS]


def _bq_safe_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Cột object toàn NULL bị pyarrow suy ra kiểu `null` (BigQuery không nhận) -> ép về STRING."""
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object and out[col].isna().all():
            out[col] = out[col].astype("string")
    return out


def load_bigquery(result: RunResult, project: str, location: str | None = None) -> pd.DataFrame:
    """Nạp Bronze lên BigQuery. Cần `pip install google-cloud-bigquery db-dtypes` và Application
    Default Credentials (gcloud auth application-default login).

    Thay thế batch KHÔNG dùng DML (chạy được cả trên BigQuery Sandbox chưa bật Billing):
    1. query job `select * ... where batch <> @batch` ghi đè (WRITE_TRUNCATE) chính bảng đó;
    2. load job WRITE_APPEND phần dữ liệu của batch.
    Cách này idempotent: chạy lại cùng batch không nhân đôi dòng; batch khác giữ nguyên."""
    from google.api_core.exceptions import NotFound
    from google.cloud import bigquery

    client = bigquery.Client(project=project, location=location)
    dataset = bigquery.Dataset(f"{project}.{BRONZE_SCHEMA}")
    if location:
        dataset.location = location
    client.create_dataset(dataset, exists_ok=True)
    batch_param = [bigquery.ScalarQueryParameter("batch", "STRING", result.batch_id)]

    def replace_batch(table: str, df: pd.DataFrame, batch_col: str, schema=None) -> None:
        fq = f"{project}.{BRONZE_SCHEMA}.{table}"
        try:
            client.get_table(fq)
            client.query(
                f"select * from `{fq}` where coalesce({batch_col}, '') <> @batch",
                job_config=bigquery.QueryJobConfig(
                    query_parameters=batch_param, destination=fq, write_disposition="WRITE_TRUNCATE",
                ),
            ).result()
            exists = True
        except NotFound:
            exists = False
        job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
        if schema is not None:
            job_config.schema = schema
        if exists:
            # batch mới có thể có thêm cột (nguồn đổi schema) -> cho phép thêm cột NULLABLE
            job_config.schema_update_options = [bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]
        client.load_table_from_dataframe(_bq_safe_frame(df), fq, job_config=job_config).result()

    counts: dict[tuple[str, str], int] = {}
    for table, df in result.tables.items():
        replace_batch(table, df, "_batch_id")
        rows = client.query(
            f"select _source_file, count(*) as n from `{project}.{BRONZE_SCHEMA}.{table}` "
            "where _batch_id = @batch group by 1",
            job_config=bigquery.QueryJobConfig(query_parameters=batch_param),
        ).result()
        for r in rows:
            counts[(table, r["_source_file"])] = r["n"]

    audit = _finalize_audit(result.audit, counts)
    replace_batch(AUDIT_TABLE, audit, "batch_id", schema=_audit_bq_schema())
    return audit


# --------------------------------------------------------------------------- điều phối
def list_runs(raw_runs_dir: Path) -> list[Path]:
    if not raw_runs_dir.is_dir():
        raise FileNotFoundError(f"Không tìm thấy thư mục raw runs: {raw_runs_dir}")
    return sorted(p for p in raw_runs_dir.iterdir() if (p / "manifest.json").is_file())


def load_runs(raw_runs_dir: Path | None = None, run_ids: list[str] | None = None,
              backend: str | None = None, db_path: Path | None = None) -> pd.DataFrame:
    """Nạp một hoặc nhiều run vào Bronze, trả về audit gộp."""
    raw_runs_dir = raw_runs_dir or default_raw_runs_dir()
    backend = (backend or settings.backend()).lower()
    runs = list_runs(raw_runs_dir)
    if run_ids:
        wanted = set(run_ids)
        runs = [p for p in runs if p.name in wanted]
        missing = wanted - {p.name for p in runs}
        if missing:
            raise FileNotFoundError(f"Không tìm thấy run: {sorted(missing)} trong {raw_runs_dir}")
    if not runs:
        raise FileNotFoundError(f"Không có run nào (thiếu manifest.json) trong {raw_runs_dir}")

    audits = []
    for run_dir in runs:
        result = read_run(run_dir)
        if backend == "duckdb":
            audit = load_duckdb(result, db_path or default_duckdb_path())
        elif backend == "bigquery":
            project = os.getenv("GCP_PROJECT_ID")
            if not project:
                raise RuntimeError("Thiếu biến môi trường GCP_PROJECT_ID cho backend bigquery")
            audit = load_bigquery(result, project, os.getenv("BQ_LOCATION"))
        else:
            raise ValueError(f"WAREHOUSE_BACKEND không hợp lệ: {backend!r}")
        audits.append(audit)
    return pd.concat(audits, ignore_index=True)


def summarize(audit: pd.DataFrame) -> pd.DataFrame:
    return (
        audit.groupby(["batch_id", "target_table"], dropna=False)
        .agg(
            datasets=("dataset_key", "count"),
            loaded=("load_status", lambda s: int((s == "loaded").sum())),
            manifest_rows=("manifest_row_count", "sum"),
            bronze_rows=("loaded_row_count", "sum"),
            mismatched=("row_count_match", lambda s: int((~s).sum())),
        )
        .reset_index()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Nạp extract Vnstock vào tầng Bronze")
    parser.add_argument("--raw-runs-dir", type=Path, default=None, help="Thư mục chứa các run (mặc định tự dò)")
    parser.add_argument("--run", action="append", dest="runs", help="run_id cần nạp (lặp lại được); mặc định: tất cả")
    parser.add_argument("--backend", choices=["duckdb", "bigquery"], default=None)
    parser.add_argument("--duckdb-path", type=Path, default=None)
    args = parser.parse_args(argv)

    audit = load_runs(args.raw_runs_dir, args.runs, args.backend, args.duckdb_path)
    summary = summarize(audit)
    print(summary.to_string(index=False))
    total_manifest = int(audit["manifest_row_count"].sum())
    total_loaded = int(audit["loaded_row_count"].sum())
    bad = audit[(~audit["load_status"].isin(OK_STATUSES)) | (~audit["row_count_match"])]
    print(f"\nTổng: {len(audit)} extract | manifest {total_manifest:,} dòng | Bronze {total_loaded:,} dòng")
    if len(bad):
        print(f"CẢNH BÁO: {len(bad)} extract lỗi/không khớp:")
        print(bad[["dataset_key", "load_status", "error_message"]].to_string(index=False))
        return 1
    print("Đối soát Bronze: KHỚP 100% với manifest.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
