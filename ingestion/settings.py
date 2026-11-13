"""Cấu hình dùng chung: nạp file `.env` ở gốc repo (nếu có) và xác định backend kho.

Không phụ thuộc python-dotenv. Biến đã đặt sẵn trong môi trường luôn được ưu tiên hơn `.env`.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    path = path or ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _absolutize_paths() -> None:
    """Đường dẫn tương đối (từ `.env` hoặc môi trường) tính theo gốc repo, không theo thư mục hiện hành,
    để dbt (chạy trong dbt_project/) và các script dùng chung một file kho."""
    for key in ("DUCKDB_PATH", "RAW_RUNS_DIR"):
        value = os.getenv(key)
        if value and not Path(value).expanduser().is_absolute():
            os.environ[key] = str((ROOT / value).resolve())


def backend() -> str:
    return os.getenv("WAREHOUSE_BACKEND", "duckdb").strip().lower()


def dbt_target() -> str:
    return os.getenv("DBT_TARGET") or ("bigquery" if backend() == "bigquery" else "local")


load_dotenv()
_absolutize_paths()
