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


def backend() -> str:
    return os.getenv("WAREHOUSE_BACKEND", "duckdb").strip().lower()


def dbt_target() -> str:
    return os.getenv("DBT_TARGET") or ("bigquery" if backend() == "bigquery" else "local")


load_dotenv()
