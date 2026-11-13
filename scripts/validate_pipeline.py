"""Kiểm chứng độc lập kho dữ liệu sau khi build (bổ sung cho dbt test).

Tính lại bằng pandas, KHÔNG dùng lại SQL của dbt, để đối chiếu chéo:
  AC01  Số dòng Bronze = manifest gốc (không nạp kép CSV/Parquet)
  AC02  Mọi dòng Bronze truy vết được batch và file nguồn
  AC03  Khóa nghiệp vụ Silver không trùng; Silver = số khóa phân biệt của Bronze
  AC04  Chỉ báo Gold (lợi suất, SMA20/50, RSI14, drawdown, lợi suất lũy kế so với chỉ số) khớp pandas
  INV   Đủ 23 đối tượng logic (7 Bronze + 6 Silver + 10 Gold)

    python scripts/validate_pipeline.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion import load_bronze, settings  # noqa: E402

TOL = 1e-9

EXPECTED_OBJECTS = {
    "bronze": ["price_daily_raw", "income_statement_raw", "balance_sheet_raw", "cash_flow_raw",
               "company_overview_raw", "index_daily_raw", "ingestion_audit"],
    "silver": ["stg_price_daily", "stg_income_statement", "stg_balance_sheet", "stg_cash_flow",
               "stg_company", "stg_index_daily"],
    "gold": ["dim_ticker", "dim_date", "fact_price_daily", "fact_financial_metric", "fact_index_daily",
             "mart_technical_indicators", "mart_stock_vs_index", "mart_financial_summary",
             "mart_stock_alerts", "mart_pipeline_health"],
}

SILVER_KEYS = {
    "stg_price_daily": ("price_daily_raw", ["symbol", "trade_date"]),
    "stg_index_daily": ("index_daily_raw", ["index_code", "trade_date"]),
    "stg_company": ("company_overview_raw", ["symbol"]),
    "stg_income_statement": ("income_statement_raw", ["symbol", "period", "metric_id"]),
    "stg_balance_sheet": ("balance_sheet_raw", ["symbol", "period", "metric_id"]),
    "stg_cash_flow": ("cash_flow_raw", ["symbol", "period", "metric_id"]),
}
# biểu thức khóa tương ứng trên Bronze (cột nguồn chưa đổi tên)
BRONZE_KEY_SQL = {
    "price_daily_raw": 'symbol, "time"',
    "index_daily_raw": 'symbol, "time"',
    "company_overview_raw": "symbol",
    "income_statement_raw": "symbol, period, id",
    "balance_sheet_raw": "symbol, period, id",
    "cash_flow_raw": "symbol, period, id",
}


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, bool, str]] = []

    def add(self, code: str, name: str, ok: bool, detail: str = "") -> None:
        self.rows.append((code, name, bool(ok), detail))

    def print(self) -> bool:
        width = max(len(r[1]) for r in self.rows)
        for code, name, ok, detail in self.rows:
            print(f"  [{'PASS' if ok else 'FAIL'}] {code:<5} {name:<{width}}  {detail}")
        failed = [r for r in self.rows if not r[2]]
        print(f"\n  {len(self.rows) - len(failed)}/{len(self.rows)} kiểm chứng đạt.")
        return not failed


def manifest_totals(raw_runs_dir: Path) -> dict[str, int]:
    totals: dict[str, int] = {}
    for run_dir in load_bronze.list_runs(raw_runs_dir):
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["entries"].values():
            table = load_bronze.KIND_TO_TABLE.get(entry["kind"])
            if table and entry.get("status") == "ok":
                totals[table] = totals.get(table, 0) + int(entry["row_count"])
    return totals


def recompute_indicators(px: pd.DataFrame) -> pd.DataFrame:
    px = px.sort_values(["symbol", "trade_date"]).copy()
    g = px.groupby("symbol", sort=False)
    px["daily_return"] = g["close"].pct_change()
    px["sma20"] = g["close"].transform(lambda s: s.rolling(20).mean())
    px["sma50"] = g["close"].transform(lambda s: s.rolling(50).mean())
    delta = g["close"].diff()
    px["_gain"] = delta.clip(lower=0)
    px["_loss"] = (-delta).clip(lower=0)
    avg_gain = px.groupby("symbol", sort=False)["_gain"].transform(lambda s: s.rolling(14).mean())
    avg_loss = px.groupby("symbol", sort=False)["_loss"].transform(lambda s: s.rolling(14).mean())
    rsi = 100 - 100 / (1 + avg_gain / avg_loss)
    rsi = rsi.where(avg_loss != 0, 100.0).where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    px["rsi14"] = rsi.where(avg_gain.notna())
    px["volatility_20d"] = px.groupby("symbol", sort=False)["daily_return"].transform(lambda s: s.rolling(20).std())
    px["drawdown"] = px["close"] / g["close"].cummax() - 1
    return px


def max_abs_diff(a: pd.Series, b: pd.Series) -> tuple[float, int]:
    """Sai khác tuyệt đối lớn nhất và số vị trí lệch NULL giữa hai chuỗi."""
    null_mismatch = int((a.isna() != b.isna()).sum())
    diff = (a - b).abs().max()
    return (0.0 if pd.isna(diff) else float(diff)), null_mismatch


class Warehouse:
    """Kết nối chỉ đọc tới DuckDB local hoặc BigQuery (theo WAREHOUSE_BACKEND)."""

    def __init__(self) -> None:
        self.backend = settings.backend()
        if self.backend == "bigquery":
            from google.cloud import bigquery

            self.project = os.environ["GCP_PROJECT_ID"]
            self.client = bigquery.Client(project=self.project, location=os.getenv("BQ_LOCATION"))
            self.con = None
        else:
            import duckdb

            db_path = load_bronze.default_duckdb_path()
            if not db_path.is_file():
                raise FileNotFoundError(f"Chưa có kho DuckDB tại {db_path}. Hãy chạy scripts/run_pipeline.py trước.")
            self.con = duckdb.connect(str(db_path), read_only=True)

    def q(self, sql: str) -> pd.DataFrame:
        if self.con is not None:
            return self.con.execute(sql).df()
        df = self.client.query(sql.replace('"time"', "`time`")).to_dataframe()
        # DATE của BigQuery về dạng dbdate -> đưa về datetime64 như DuckDB để so khớp/merge
        for col in df.columns:
            if str(df[col].dtype) == "dbdate":
                df[col] = pd.to_datetime(df[col])
        return df

    def scalar(self, sql: str):
        return self.q(sql).iloc[0, 0]

    def existing_tables(self) -> set[tuple[str, str]]:
        if self.con is not None:
            return {(s, t) for s, t in self.con.execute(
                "select table_schema, table_name from information_schema.tables").fetchall()}
        found = set()
        for schema in EXPECTED_OBJECTS:
            try:
                found |= {(schema, t.table_id) for t in self.client.list_tables(f"{self.project}.{schema}")}
            except Exception:  # dataset chưa tồn tại
                pass
        return found

    def close(self) -> None:
        if self.con is not None:
            self.con.close()


def main(argv: list[str] | None = None) -> int:
    try:
        wh = Warehouse()
    except (FileNotFoundError, KeyError) as exc:
        print(f"Không kết nối được kho: {exc}")
        return 1
    print(f"Backend: {wh.backend}")
    rep = Report()
    q, scalar = wh.q, wh.scalar

    # ---------------------------------------------------------------- INV
    existing = wh.existing_tables()
    missing = [f"{s}.{t}" for s, ts in EXPECTED_OBJECTS.items() for t in ts if (s, t) not in existing]
    n_expected = sum(len(v) for v in EXPECTED_OBJECTS.values())
    rep.add("INV", "Đủ đối tượng Bronze/Silver/Gold", not missing,
            f"{n_expected - len(missing)}/{n_expected}" + (f" thiếu: {missing}" if missing else ""))
    if missing:
        rep.print()
        return 1

    # ---------------------------------------------------------------- AC01
    expected = manifest_totals(load_bronze.default_raw_runs_dir())
    actual = {t: scalar(f"select count(*) from bronze.{t}") for t in expected}
    rep.add("AC01", "Bronze khớp số dòng manifest gốc", expected == actual,
            f"manifest {sum(expected.values()):,} | bronze {sum(actual.values()):,}")
    audit = q("select count(*) as n, sum(case when load_status in ('loaded', 'empty') and row_count_match then 1 else 0 end) as ok "
              "from bronze.ingestion_audit")
    rep.add("AC01", "Audit: mọi extract nạp đủ và khớp", int(audit.n[0]) == int(audit.ok[0]),
            f"{int(audit.ok[0])}/{int(audit.n[0])} extract")
    csv_loaded = sum(scalar(f"select count(*) from bronze.{t} where lower(_source_file) not like '%.parquet'")
                     for t in expected)
    rep.add("AC01", "Không nạp kép CSV (chỉ Parquet)", csv_loaded == 0, f"{csv_loaded} dòng từ file không phải parquet")

    # ---------------------------------------------------------------- AC02
    untraceable = sum(scalar(
        f"select count(*) from bronze.{t} where _batch_id is null or _source_file is null "
        "or _extracted_at is null or _ingested_at is null or _source is null") for t in expected)
    rep.add("AC02", "Bronze đủ metadata truy vết", untraceable == 0, f"{untraceable} dòng thiếu metadata")
    files = sum(scalar(f"select count(distinct _batch_id || '/' || _source_file) from bronze.{t}") for t in expected)
    rep.add("AC02", "Số file nguồn trong Bronze = số extract audit", files == int(audit.n[0]),
            f"{files} file | {int(audit.n[0])} extract")

    # ---------------------------------------------------------------- AC03
    for model, (bronze_table, keys) in SILVER_KEYS.items():
        n = scalar(f"select count(*) from silver.{model}")
        n_keys = scalar(f"select count(*) from (select distinct {', '.join(keys)} from silver.{model})")
        n_bronze_keys = scalar(f"select count(*) from (select distinct {BRONZE_KEY_SQL[bronze_table]} from bronze.{bronze_table})")
        rep.add("AC03", f"{model}: khóa duy nhất, đủ khóa Bronze", n == n_keys == n_bronze_keys,
                f"{n:,} dòng | {n_keys:,} khóa | {n_bronze_keys:,} khóa Bronze")

    # ---------------------------------------------------------------- AC04
    px = q("select symbol, trade_date, close from gold.fact_price_daily")
    mart = q("select symbol, trade_date, daily_return, sma20, sma50, rsi14, volatility_20d, drawdown "
             "from gold.mart_technical_indicators")
    merged = recompute_indicators(px).merge(mart, on=["symbol", "trade_date"], suffixes=("_py", "_sql"), how="outer")
    rep.add("AC04", "Mart chỉ báo đủ dòng so với fact giá", len(merged) == len(px) == len(mart),
            f"fact {len(px):,} | mart {len(mart):,}")
    for col in ["daily_return", "sma20", "sma50", "rsi14", "volatility_20d", "drawdown"]:
        diff, null_mismatch = max_abs_diff(merged[f"{col}_py"], merged[f"{col}_sql"])
        rep.add("AC04", f"{col} khớp pandas", diff < TOL * 1e3 and null_mismatch == 0,
                f"lệch lớn nhất {diff:.2e} | lệch NULL {null_mismatch}")

    svi = q("select symbol, trade_date, stock_close, index_close, stock_cum_return, index_cum_return "
            "from gold.mart_stock_vs_index order by symbol, trade_date")
    first = svi.groupby("symbol", sort=False)[["stock_close", "index_close"]].transform("first")
    d1, _ = max_abs_diff(svi.stock_close / first.stock_close - 1, svi.stock_cum_return)
    d2, _ = max_abs_diff(svi.index_close / first.index_close - 1, svi.index_cum_return)
    idx_dates = set(q("select trade_date from gold.fact_index_daily").trade_date)
    outside = int((~svi.trade_date.isin(idx_dates)).sum())
    rep.add("AC04", "Lợi suất lũy kế cổ phiếu/chỉ số khớp pandas", max(d1, d2) < TOL * 1e3 and outside == 0,
            f"lệch lớn nhất {max(d1, d2):.2e} | {outside} dòng ngoài khoảng ngày chỉ số")

    orphan = scalar("select count(*) from gold.fact_price_daily f left join gold.dim_ticker t using (ticker_key) "
                    "left join gold.dim_date d using (date_key) where t.ticker_key is null or d.date_key is null")
    rep.add("AC04", "Fact giá join đủ dim_ticker và dim_date", orphan == 0, f"{orphan} dòng mồ côi")

    # ---------------------------------------------------------------- tổng hợp
    print("\nSố dòng theo đối tượng:")
    for schema, tables in EXPECTED_OBJECTS.items():
        extra = ["dq_issue_log"] if schema == "silver" else []
        for t in tables + extra:
            print(f"  {schema + '.' + t:<36} {scalar(f'select count(*) from {schema}.{t}'):>8,}")
    print("\nKết quả kiểm chứng:")
    ok = rep.print()
    wh.close()
    return 0 if ok else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
