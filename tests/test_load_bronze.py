"""Kiểm thử loader Bronze trên một run tổng hợp nhỏ (không cần dữ liệu thật)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion import load_bronze  # noqa: E402


def _write_extract(run_dir: Path, kind: str, symbol: str, df: pd.DataFrame, report_period: str | None = None) -> dict:
    sub = f"{kind}/{report_period}" if report_period else kind
    (run_dir / sub).mkdir(parents=True, exist_ok=True)
    parquet = run_dir / sub / f"{symbol}.parquet"
    df.to_parquet(parquet, index=False)
    sha = hashlib.sha256(parquet.read_bytes()).hexdigest()
    (run_dir / sub / f"{symbol}.meta.json").write_text(json.dumps({"parquet_sha256": sha}), encoding="utf-8")
    return {
        "status": "ok", "kind": kind, "symbol": symbol, "report_period": report_period,
        "row_count": len(df), "source_actual": "kbs",
        "csv_file": f"{sub}/{symbol}.csv", "parquet_file": f"{sub}/{symbol}.parquet",
        "metadata_file": f"{sub}/{symbol}.meta.json", "extracted_at_utc": "2026-11-03T05:00:00+00:00",
    }


def _make_run(runs_dir: Path, run_id: str, close: float = 10.5) -> Path:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    prices = pd.DataFrame({
        "time": pd.to_datetime(["2026-11-02", "2026-11-03"]).tz_localize("Asia/Ho_Chi_Minh"),
        "open": [10.0, 10.2], "high": [10.6, 10.9], "low": [9.9, 10.1], "close": [10.4, close],
        "volume": [1000, 2000],
    })
    income = pd.DataFrame({
        "period": pd.Categorical(["2026-Q3", "2026-Q3"]), "id": ["IS_NET_REVENUE", "IS_NET_PROFIT_AFTER_TAX"],
        "name": ["Doanh thu thuần", "LNST"], "order": [1, 2], "level": [1, 1],
        "unit": pd.Categorical(["VNĐ", "VNĐ"]), "value": [100.0, None],
    })
    entries = {
        "prices:AAA": _write_extract(run_dir, "prices", "AAA", prices),
        "financials/income_statement:AAA:quarter": _write_extract(
            run_dir, "financials/income_statement", "AAA", income, "quarter"),
    }
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": run_id, "entries": entries}), encoding="utf-8")
    return run_dir


def _count(db: Path, table: str) -> int:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute(f"select count(*) from bronze.{table}").fetchone()[0]
    finally:
        con.close()


def test_load_adds_metadata_and_reconciles(tmp_path: Path):
    runs = tmp_path / "runs"
    _make_run(runs, "run_a")
    db = tmp_path / "wh.duckdb"

    audit = load_bronze.load_runs(runs, backend="duckdb", db_path=db)

    assert len(audit) == 2
    assert (audit["load_status"] == "loaded").all()
    assert audit["row_count_match"].all()
    assert audit["checksum_ok"].all()

    con = duckdb.connect(str(db), read_only=True)
    row = con.execute(
        "select symbol, _batch_id, _source_file, _source from bronze.price_daily_raw limit 1").fetchone()
    assert row == ("AAA", "run_a", "prices/AAA.parquet", "kbs")
    fin = con.execute("select symbol, report_period, period, unit, value from bronze.income_statement_raw "
                      "order by id").fetchall()
    con.close()
    assert fin[0][:4] == ("AAA", "quarter", "2026-Q3", "VNĐ")
    assert fin[0][4] is None  # NULL của nguồn được giữ nguyên, không quy về 0


def test_rerun_same_batch_is_idempotent(tmp_path: Path):
    runs = tmp_path / "runs"
    _make_run(runs, "run_a")
    db = tmp_path / "wh.duckdb"

    load_bronze.load_runs(runs, backend="duckdb", db_path=db)
    load_bronze.load_runs(runs, backend="duckdb", db_path=db)

    assert _count(db, "price_daily_raw") == 2
    assert _count(db, "income_statement_raw") == 2
    assert _count(db, "ingestion_audit") == 2


def test_new_batch_is_appended_not_overwritten(tmp_path: Path):
    runs = tmp_path / "runs"
    _make_run(runs, "run_a")
    _make_run(runs, "run_b", close=11.0)
    db = tmp_path / "wh.duckdb"

    load_bronze.load_runs(runs, backend="duckdb", db_path=db)

    assert _count(db, "price_daily_raw") == 4  # Bronze giữ cả hai phiên bản để Silver chọn bản mới nhất
    assert _count(db, "ingestion_audit") == 4


def test_checksum_mismatch_is_recorded_and_not_loaded(tmp_path: Path):
    runs = tmp_path / "runs"
    run_dir = _make_run(runs, "run_a")
    meta = run_dir / "prices" / "AAA.meta.json"
    meta.write_text(json.dumps({"parquet_sha256": "0" * 64}), encoding="utf-8")
    db = tmp_path / "wh.duckdb"

    audit = load_bronze.load_runs(runs, backend="duckdb", db_path=db)

    bad = audit[audit["dataset_key"] == "prices:AAA"].iloc[0]
    assert bad["load_status"] == "failed"
    assert "sha256" in bad["error_message"]
    assert not bad["row_count_match"]
    con = duckdb.connect(str(db), read_only=True)
    tables = {r[0] for r in con.execute(
        "select table_name from information_schema.tables where table_schema = 'bronze'").fetchall()}
    con.close()
    assert "price_daily_raw" not in tables


def test_unknown_run_raises(tmp_path: Path):
    runs = tmp_path / "runs"
    _make_run(runs, "run_a")
    with pytest.raises(FileNotFoundError):
        load_bronze.load_runs(runs, run_ids=["khong_ton_tai"], backend="duckdb", db_path=tmp_path / "wh.duckdb")


def test_empty_extract_is_ok_with_zero_rows(tmp_path: Path):
    runs = tmp_path / "runs"
    run_dir = _make_run(runs, "run_a")
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["entries"]["indexes:VNINDEX"] = {
        "status": "empty", "kind": "indexes", "symbol": "VNINDEX", "report_period": None,
        "row_count": 0, "extracted_at_utc": "2026-11-03T05:00:00+00:00",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    db = tmp_path / "wh.duckdb"

    audit = load_bronze.load_runs(runs, backend="duckdb", db_path=db)

    empty = audit[audit["dataset_key"] == "indexes:VNINDEX"].iloc[0]
    assert empty["load_status"] == "empty"
    assert empty["loaded_row_count"] == 0
    assert empty["row_count_match"]
    assert load_bronze.main(["--raw-runs-dir", str(runs), "--duckdb-path", str(db)]) == 0


def test_bq_safe_frame_casts_all_null_object_columns():
    df = pd.DataFrame({"a": [None, None], "b": ["x", None], "c": [1.0, None]})
    out = load_bronze._bq_safe_frame(df)
    assert str(out["a"].dtype) == "string"
    assert out["b"].dtype == object and out["c"].dtype == float
