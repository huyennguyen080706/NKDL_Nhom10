"""Cô lập kiểm thử khỏi cấu hình thật trong `.env`: test KHÔNG BAO GIỜ được ghi lên BigQuery."""
import pytest


@pytest.fixture(autouse=True)
def _force_local_backend(monkeypatch):
    monkeypatch.setenv("WAREHOUSE_BACKEND", "duckdb")
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.setenv("DBT_TARGET", "local")
