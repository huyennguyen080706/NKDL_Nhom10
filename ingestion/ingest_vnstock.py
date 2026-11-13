#!/usr/bin/env python3
"""Reproducible raw-data ingestion for a Vietnamese stock market Medallion project.

Python 3.10+, vnstock 5.x. Intended for Colab/local execution.
Raw snapshots are immutable per run_id; validation NEVER alters API outputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

DEFAULT_CONFIG = Path(__file__).resolve().parent / "config.json"
REPORTS = {"income_statement", "balance_sheet", "cash_flow"}
SCOPES = {"all", "prices", "financials", "companies", "indexes"}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Vnstock → immutable Bronze-ready raw snapshots")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--scope", choices=sorted(SCOPES), default="all")
    parser.add_argument("--start", help="Price start date YYYY-MM-DD; overrides config")
    parser.add_argument("--end", help="Price end date YYYY-MM-DD; default today in Vietnam")
    parser.add_argument("--run-id", help="Reuse the SAME id to resume a partially completed run")
    parser.add_argument("--offset", type=int, default=0, help="Offset in each configured symbol list")
    parser.add_argument("--limit", type=int, default=0, help="Max symbols per list; 0 means all")
    parser.add_argument("--sleep", type=float, help="Seconds between API calls (default from config)")
    return parser.parse_args(argv)


def as_json(value: Any):
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, (pd.Series, pd.Index)):
        return value.tolist()
    return str(value)


def atomic_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=as_json), encoding="utf-8")
    temporary.replace(path)


def select_symbols(values, offset, limit):
    values = list(dict.fromkeys(str(x).strip().upper() for x in values if str(x).strip()))
    if offset < 0 or limit < 0:
        raise ValueError("--offset and --limit must be >= 0")
    return values[offset:offset + limit] if limit else values[offset:]


def is_source_block(error: Exception) -> bool:
    """Stop, do not retry/rotate provider on access denials or quota errors."""
    name = type(error).__name__.lower()
    msg = str(error).lower()
    return (
        any(key in name for key in ("accessdenied", "ratelimit", "entitlement", "quota", "challenge"))
        or any(key in msg for key in ("http 403", "http 429", "rate limit", "quota exceeded", "vượt hạn mức"))
    )


def data_profile(data: pd.DataFrame) -> dict:
    result = {
        "row_count": int(len(data)),
        "column_count": int(len(data.columns)),
        "columns": list(map(str, data.columns)),
        "dtypes": {str(k): str(v) for k, v in data.dtypes.items()},
        "null_count": {str(k): int(v) for k, v in data.isnull().sum().items()},
        "full_row_duplicates": int(data.duplicated().sum()),
    }
    if "time" in data.columns and not data.empty:
        dates = pd.to_datetime(data["time"], errors="coerce", utc=True)
        good = dates.dropna()
        result["first_time_utc"] = good.min().isoformat() if len(good) else None
        result["last_time_utc"] = good.max().isoformat() if len(good) else None
        result["invalid_times"] = int(dates.isna().sum())
        result["duplicate_times"] = int(dates.duplicated().sum())
    if "period" in data.columns:
        result["report_periods"] = sorted(data["period"].dropna().astype(str).unique().tolist())
    if {"open", "high", "low", "close", "volume"}.issubset(set(data.columns)):
        o, h, l, c, v = [pd.to_numeric(data[col], errors="coerce") for col in ("open", "high", "low", "close", "volume")]
        result["potential_ohlc_logic_errors"] = int(((h < pd.concat([o, c, l], axis=1).max(axis=1)) | (l > pd.concat([o, c, h], axis=1).min(axis=1))).sum())
        result["nonpositive_ohlc_prices"] = int(((pd.concat([o, h, l, c], axis=1) <= 0).any(axis=1)).sum())
        result["negative_volume"] = int((v < 0).sum())
    return result


class Collector:
    def __init__(self, config: dict, args):
        self.config, self.args = config, args
        self.provider = config.get("provider", "kbs").lower()
        if self.provider not in ("kbs", "vci"):
            raise ValueError("Only an explicitly configured authorized provider kbs or vci is supported")
        self.start = args.start or config.get("start_date", "2021-01-01")
        self.end = args.end or config.get("end_date") or datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d")
        self.sleep = float(args.sleep if args.sleep is not None else config.get("sleep_seconds", 2))
        if self.sleep < 0:
            raise ValueError("sleep_seconds cannot be negative")
        for value in (self.start, self.end):
            datetime.strptime(value, "%Y-%m-%d")
        if self.start > self.end:
            raise ValueError("start date must be <= end date")
        self.run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.run_id):
            raise ValueError("run-id permits letters, digits, _ and - only")
        self.root = args.out.resolve() / "raw" / "runs" / self.run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_file = self.root / "manifest.json"
        self.manifest = json.loads(self.manifest_file.read_text(encoding="utf-8")) if self.manifest_file.exists() else {}
        # Preserve the original end date when resuming later with the same run_id.
        if args.end is None and not config.get("end_date") and self.manifest.get("request_end"):
            self.end = self.manifest["request_end"]
        # One immutable request definition per run_id; only scope/offset/limit may change.
        for field, current in (("request_start", self.start), ("request_end", self.end),
                               ("provider_requested", self.provider),
                               ("interval", config.get("interval", "1D"))):
            previous = self.manifest.get(field)
            if previous is not None and previous != current:
                raise ValueError(f"Run ID {self.run_id} already exists with {field}={previous}. "
                                 "Reuse identical parameters or create a NEW --run-id.")
        self.entries = self.manifest.get("entries", {})
        self.manifest.update({
            "run_id": self.run_id,
            "project_name": self.config.get("project_name", "Vnstock Medallion"),
            "provider_requested": self.provider,
            "request_start": self.start,
            "request_end": self.end,
            "interval": config.get("interval", "1D"),
            "started_at_utc": self.manifest.get("started_at_utc") or datetime.now(timezone.utc).isoformat(),
            "entries": self.entries,
        })
        self._write_manifest()
        self.api = None

    def _write_manifest(self):
        self.manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_json(self.manifest_file, self.manifest)
        summary = []
        for key, value in sorted(self.entries.items()):
            summary.append({"dataset_key": key, **{k: value.get(k) for k in (
                "status", "kind", "symbol", "report_period", "row_count", "source_actual",
                "csv_file", "parquet_file", "error_type", "error_message")}})
        pd.DataFrame(summary, columns=[
            "dataset_key", "status", "kind", "symbol", "report_period", "row_count",
            "source_actual", "csv_file", "parquet_file", "error_type", "error_message",
        ]).to_csv(self.root / "manifest.csv", index=False, encoding="utf-8-sig")

    def connect(self):
        import vnstock
        api_key = os.environ.get("VNSTOCK_API_KEY", "").strip()
        if api_key:
            vnstock.login(api_key)
            try:
                print("Vnstock tier:", vnstock.status().get("tier", "unknown"))
            except Exception:
                print("Vnstock login invoked; tier not available")
        else:
            print("WARNING: VNSTOCK_API_KEY is not set; guest tier may block financial statements")
        self.api = vnstock

    def _capture(self, kind, symbol, fetch, period=None):
        key = ":".join(str(x) for x in [kind, symbol, period] if x)
        subpath = Path(kind) / (period or "") / f"{symbol}"
        csv_path = self.root / f"{subpath}.csv"
        parquet_path = self.root / f"{subpath}.parquet"
        meta_path = self.root / f"{subpath}.meta.json"
        if csv_path.is_file() and parquet_path.is_file() and meta_path.is_file():
            print(f"[SKIP] {key} (already saved for run_id={self.run_id})")
            return "skipped"
        print(f"[GET] {key}")
        now = datetime.now(timezone.utc).isoformat()
        try:
            data = fetch()
            if not isinstance(data, pd.DataFrame):
                raise TypeError(f"Expected pandas DataFrame; received {type(data).__name__}")
            if data.empty:
                self.entries[key] = {"status": "empty", "kind": kind, "symbol": symbol,
                                     "report_period": period, "row_count": 0, "extracted_at_utc": now}
                self._write_manifest()
                print(f"[EMPTY] {key}")
                return "empty"
            # Do not normalize, deduplicate, fill NULLs, or adjust stock prices at Bronze extraction.
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_csv = csv_path.with_name(csv_path.name + ".tmp")
            tmp_parquet = parquet_path.with_name(parquet_path.name + ".tmp")
            data.to_csv(tmp_csv, index=False, encoding="utf-8-sig")
            data.to_parquet(tmp_parquet, index=False, engine="pyarrow")
            tmp_csv.replace(csv_path)
            tmp_parquet.replace(parquet_path)
            source_actual = data.attrs.get("source") or self.provider
            metadata = {
                "run_id": self.run_id, "kind": kind, "symbol": symbol,
                "report_period": period, "extracted_at_utc": now,
                "source_requested": self.provider, "source_actual": source_actual,
                "raw_vnstock_attrs": dict(data.attrs),
                "request": {"start": self.start, "end": self.end, "interval": self.config.get("interval", "1D")}
                   if kind in ("prices", "indexes") else {"period": period},
                "profile": data_profile(data),
                "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                "parquet_sha256": hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
                "storage": {"csv": str(csv_path.relative_to(self.root)),
                            "parquet": str(parquet_path.relative_to(self.root))},
            }
            atomic_json(meta_path, metadata)
            self.entries[key] = {
                "status": "ok", "kind": kind, "symbol": symbol, "report_period": period,
                "row_count": len(data), "source_actual": str(source_actual),
                "csv_file": str(csv_path.relative_to(self.root)),
                "parquet_file": str(parquet_path.relative_to(self.root)),
                "metadata_file": str(meta_path.relative_to(self.root)), "extracted_at_utc": now,
            }
            self._write_manifest()
            print(f"[OK] {key}: {len(data):,} rows")
            return "ok"
        except Exception as exc:
            self.entries[key] = {
                "status": "error", "kind": kind, "symbol": symbol, "report_period": period,
                "row_count": 0, "error_type": type(exc).__name__,
                "error_message": str(exc)[:800], "extracted_at_utc": now,
            }
            self._write_manifest()
            print(f"[ERROR] {key}: {type(exc).__name__}: {exc}", file=sys.stderr)
            if is_source_block(exc):
                raise RuntimeError("Provider denied access or quota reached; stopped without retry. "
                                   "Verify account/source and resume later with the SAME --run-id.") from exc
            return "error"
        finally:
            if self.sleep:
                time.sleep(self.sleep)

    def run(self):
        self.connect()
        from vnstock import Market, Fundamental, Reference
        market = Market()
        reference = Reference()
        tasks = []
        if self.args.scope in ("all", "prices"):
            for symbol in select_symbols(self.config["prices"], self.args.offset, self.args.limit):
                tasks.append(("prices", symbol, None,
                              lambda s=symbol: market.equity(s).ohlcv(
                                  start=self.start, end=self.end,
                                  interval=self.config.get("interval", "1D"), source=self.provider)))
        if self.args.scope in ("all", "financials"):
            for symbol in select_symbols(self.config["financial_symbols"], self.args.offset, self.args.limit):
                for period in self.config.get("financial_periods", ["quarter"]):
                    for report in self.config.get("reports", sorted(REPORTS)):
                        if report not in REPORTS:
                            raise ValueError("Unsupported financial report: " + report)
                        tasks.append((f"financials/{report}", symbol, period,
                                      lambda s=symbol, r=report, p=period:
                                          getattr(Fundamental().equity(s), r)(
                                              period=p, format="long", source=self.provider)))
        if self.args.scope in ("all", "companies"):
            for symbol in select_symbols(self.config["prices"], self.args.offset, self.args.limit):
                tasks.append(("companies", symbol, None,
                              lambda s=symbol: reference.company(s).overview(source=self.provider)))
        if self.args.scope in ("all", "indexes"):
            for symbol in self.config.get("index_symbols", ["VNINDEX"]):
                tasks.append(("indexes", symbol, None,
                              lambda s=symbol: market.index(s).ohlcv(
                                  start=self.start, end=self.end,
                                  interval=self.config.get("interval", "1D"), source=self.provider)))
        print(f"Run: {self.run_id} | Scope: {self.args.scope} | Planned calls: {len(tasks)}")
        print(f"Range: {self.start} -> {self.end} | Provider: {self.provider}")
        summary = {"ok": 0, "skipped": 0, "empty": 0, "error": 0}
        try:
            for kind, symbol, period, fetch in tasks:
                result = self._capture(kind, symbol, fetch, period)
                summary[result] += 1
        finally:
            self._write_manifest()
            print("Summary:", summary)
            print("Manifest:", self.manifest_file)
        return 0 if summary["error"] == 0 else 1


def main(argv=None):
    args = parse_args(argv)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    return Collector(config, args).run()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
