"""Dagster điều phối pipeline Medallion: raw extract -> Bronze -> dbt Silver -> dbt Gold.

    dagster dev -m orchestration.definitions        # mở UI tại http://localhost:3000

Asset graph:
    bronze/*  (bronze_load: Python nạp Parquet + audit)
        -> silver/* -> gold/*  (dbt build: mỗi model là một asset, mỗi dbt test là một asset check)

    raw/vnstock_extract (thu thập batch mới từ Vnstock - chỉ có trong daily_refresh_job)
        -> bronze/* -> silver/* -> gold/*

Job:
    initial_load_job   - nạp toàn bộ run có sẵn rồi build Silver/Gold (không gọi API, chạy offline)
    daily_refresh_job  - gọi ingestion/ingest_vnstock.py tạo run `daily_YYYYMMDD` (giá/chỉ số lấy cửa sổ
                         gần nhất có overlap, BCTC/hồ sơ lấy snapshot), rồi nạp Bronze + dbt build.
                         Gắn lịch 18:30 thứ 2-6 (giờ Việt Nam); lịch mặc định STOPPED, bật trong UI
                         khi chạy `dagster dev` (daemon). Cần cài vnstock và đặt VNSTOCK_API_KEY.

Backend lấy theo WAREHOUSE_BACKEND (duckdb | bigquery, đọc cả từ `.env`); dbt dùng target tương ứng.
"""
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Mapping

import dagster as dg
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = ROOT / "dbt_project"
sys.path.insert(0, str(ROOT))

from ingestion import load_bronze, settings  # noqa: E402

# dbt (tiến trình con) dùng cùng kho với bước nạp Bronze.
os.environ.setdefault("DUCKDB_PATH", str(load_bronze.default_duckdb_path()))
os.environ["DBT_TARGET"] = settings.dbt_target()

# Dùng dbt của chính môi trường Python đang chạy (không phụ thuộc việc đã activate venv hay chưa).
_dbt_bin = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
DBT_EXECUTABLE = str(_dbt_bin) if _dbt_bin.exists() else "dbt"

dbt_project = DbtProject(project_dir=DBT_DIR, profiles_dir=DBT_DIR)
dbt_project.prepare_if_dev()
if not dbt_project.manifest_path.exists():
    # Lần đầu sau khi clone (ngoài `dagster dev`): sinh manifest để Dagster đọc được đồ thị dbt.
    subprocess.run(
        [DBT_EXECUTABLE, "parse", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)],
        cwd=DBT_DIR, check=True,
    )

BRONZE_TABLES = [*load_bronze.KIND_TO_TABLE.values(), load_bronze.AUDIT_TABLE]


class MedallionTranslator(DagsterDbtTranslator):
    """Đặt asset key theo tầng (bronze/silver/gold) để lineage dbt nối với asset nạp Bronze."""

    def get_asset_key(self, dbt_resource_props: Mapping[str, Any]) -> dg.AssetKey:
        if dbt_resource_props["resource_type"] == "source":
            return dg.AssetKey([dbt_resource_props["source_name"], dbt_resource_props["name"]])
        layer = dbt_resource_props["fqn"][1]  # vnstock_medallion.<silver|gold>....
        return dg.AssetKey([layer, dbt_resource_props["name"]])

    def get_group_name(self, dbt_resource_props: Mapping[str, Any]) -> str | None:
        fqn = dbt_resource_props["fqn"]
        if dbt_resource_props["name"] in ("dq_issue_log", "mart_pipeline_health"):
            return "observability"
        if fqn[1] == "silver":
            return "silver_models"
        return "gold_marts"


class ExtractConfig(dg.Config):
    """Tham số cho bước thu thập (có thể sửa trong Launchpad của Dagster UI)."""
    run_id: str = ""            # rỗng -> daily_YYYYMMDD theo giờ Việt Nam
    lookback_days: int = 14     # cửa sổ giá/chỉ số; overlap được Silver khử trùng theo bản mới nhất
    scope: str = "all"


@dg.asset(
    key=dg.AssetKey(["raw", "vnstock_extract"]),
    group_name="raw_extract",
    description="Gọi Vnstock (KBS) tạo một run raw bất biến: Parquet + meta.json + manifest.json.",
)
def vnstock_extract(context: dg.AssetExecutionContext, config: ExtractConfig) -> dg.MaterializeResult:
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    run_id = config.run_id or f"daily_{today:%Y%m%d}"
    out_root = load_bronze.default_raw_runs_dir().parents[1]  # <out>/raw/runs/<run_id>
    cmd = [
        sys.executable, str(ROOT / "ingestion" / "ingest_vnstock.py"),
        "--config", str(ROOT / "ingestion" / "config.json"), "--out", str(out_root),
        "--run-id", run_id, "--scope", config.scope,
        "--start", f"{today - timedelta(days=config.lookback_days):%Y-%m-%d}",
    ]
    context.log.info("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONUTF8": "1"})
    context.log.info(proc.stdout[-4000:])
    if proc.returncode != 0:
        raise dg.Failure(description=f"ingest_vnstock.py lỗi (exit {proc.returncode})",
                         metadata={"stderr": dg.MetadataValue.text(proc.stderr[-4000:])})
    return dg.MaterializeResult(metadata={"run_id": run_id, "raw_dir": str(out_root / "raw" / "runs" / run_id)})


@dg.multi_asset(
    name="bronze_load",
    group_name="bronze_load",
    specs=[
        dg.AssetSpec(
            dg.AssetKey(["bronze", table]),
            description=f"Bảng Bronze {table} - nạp append-only theo batch từ extract Parquet.",
            deps=[vnstock_extract],
        )
        for table in BRONZE_TABLES
    ],
)
def bronze_load(context: dg.AssetExecutionContext):
    """Nạp mọi run trong thư mục raw vào Bronze và đối soát với manifest."""
    audit = load_bronze.load_runs()
    summary = load_bronze.summarize(audit)
    context.log.info("\n" + summary.to_string(index=False))
    bad = audit[(~audit["load_status"].isin(load_bronze.OK_STATUSES)) | (~audit["row_count_match"])]
    if len(bad):
        raise dg.Failure(
            description=f"{len(bad)} extract lỗi hoặc không khớp manifest",
            metadata={"extracts": dg.MetadataValue.md(bad[["dataset_key", "error_message"]].to_markdown(index=False))},
        )
    for table in BRONZE_TABLES:
        if table == load_bronze.AUDIT_TABLE:
            meta = {"extracts": len(audit), "batches": int(audit["batch_id"].nunique())}
        else:
            part = audit[audit["target_table"] == table]
            meta = {
                "extracts": len(part),
                "manifest_rows": int(part["manifest_row_count"].sum()),
                "bronze_rows": int(part["loaded_row_count"].sum()),
            }
        yield dg.MaterializeResult(asset_key=dg.AssetKey(["bronze", table]), metadata=meta)


@dbt_assets(manifest=dbt_project.manifest_path, dagster_dbt_translator=MedallionTranslator())
def medallion_dbt_assets(context: dg.AssetExecutionContext, dbt: DbtCliResource):
    """dbt build: dựng Silver/Gold và chạy test theo đúng thứ tự phụ thuộc."""
    yield from dbt.cli(["build"], context=context).stream()


initial_load_job = dg.define_asset_job(
    "initial_load_job",
    selection=dg.AssetSelection.all() - dg.AssetSelection.assets(vnstock_extract),
    description="Nạp Bronze từ các extract có sẵn rồi build + test Silver/Gold (không gọi API).",
)

daily_refresh_job = dg.define_asset_job(
    "daily_refresh_job",
    selection=dg.AssetSelection.all(),
    description="Thu thập batch mới từ Vnstock -> Bronze -> dbt build Silver/Gold.",
)

daily_refresh_schedule = dg.ScheduleDefinition(
    job=daily_refresh_job,
    cron_schedule="30 18 * * 1-5",
    execution_timezone="Asia/Ho_Chi_Minh",
    default_status=dg.DefaultScheduleStatus.STOPPED,
)

defs = dg.Definitions(
    assets=[vnstock_extract, bronze_load, medallion_dbt_assets],
    jobs=[initial_load_job, daily_refresh_job],
    schedules=[daily_refresh_schedule],
    resources={"dbt": DbtCliResource(project_dir=dbt_project, dbt_executable=DBT_EXECUTABLE)},
)
