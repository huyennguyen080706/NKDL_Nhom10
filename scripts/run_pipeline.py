"""Chạy pipeline end-to-end: raw extract -> Bronze -> (dbt) Silver -> Gold -> kiểm chứng.

    python scripts/run_pipeline.py                 # nạp mọi run + dbt build + validate
    python scripts/run_pipeline.py --run initial_20261103
    python scripts/run_pipeline.py --skip-bronze   # chỉ chạy lại dbt + validate

Chạy lại nhiều lần cho cùng kết quả (idempotent): Bronze thay thế đúng batch, Silver/Gold dựng lại toàn bộ.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DBT_DIR = ROOT / "dbt_project"
sys.path.insert(0, str(ROOT))

from ingestion import load_bronze, settings  # noqa: E402


def dbt_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("DUCKDB_PATH", str(load_bronze.default_duckdb_path()))
    env["DBT_TARGET"] = settings.dbt_target()
    env["PYTHONUTF8"] = "1"
    return env


def run_dbt(*args: str) -> int:
    cmd = [sys.executable, "-c", "from dbt.cli.main import cli; cli()", *args, "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)]
    print(f"\n$ dbt {' '.join(args)}", flush=True)
    return subprocess.run(cmd, cwd=DBT_DIR, env=dbt_env()).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline Medallion Vnstock: Bronze -> Silver -> Gold")
    parser.add_argument("--run", action="append", dest="runs", help="run_id cần nạp (mặc định: tất cả)")
    parser.add_argument("--raw-runs-dir", type=Path, default=None)
    parser.add_argument("--skip-bronze", action="store_true")
    parser.add_argument("--skip-validate", action="store_true")
    args = parser.parse_args(argv)
    started = time.time()

    if not args.skip_bronze:
        print("=== [1/3] BRONZE: nạp extract Parquet + audit ===", flush=True)
        rc = load_bronze.main(
            (["--raw-runs-dir", str(args.raw_runs_dir)] if args.raw_runs_dir else [])
            + [x for r in (args.runs or []) for x in ("--run", r)]
        )
        if rc != 0:
            print("Bronze có extract lỗi/không khớp -> dừng pipeline.")
            return rc

    print("\n=== [2/3] SILVER + GOLD: dbt build (model + test theo thứ tự phụ thuộc) ===", flush=True)
    rc = run_dbt("build")
    if rc != 0:
        print("dbt build thất bại -> xem log ở trên (dbt_project/logs/dbt.log).")
        return rc

    if not args.skip_validate:
        print("\n=== [3/3] KIỂM CHỨNG độc lập ===", flush=True)
        from scripts import validate_pipeline

        rc = validate_pipeline.main([])
        if rc != 0:
            return rc

    print(f"\nPipeline hoàn tất trong {time.time() - started:.1f}s.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
