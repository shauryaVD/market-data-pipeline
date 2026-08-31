from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import UUID

import pandas as pd

try:
    import psycopg2
except ImportError:  # pragma: no cover - import guard for static inspection only
    psycopg2 = None


COPY_COLUMNS = [
    "source_name",
    "symbol",
    "price_ts",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "adjusted_close",
    "currency",
]


@dataclass(frozen=True)
class LoadMetrics:
    rows_loaded: int
    copy_ms: int
    upsert_ms: int


def connect(dsn: str):
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed")
    return psycopg2.connect(dsn)


def apply_schema(conn, schema_path: Path) -> None:
    with schema_path.open("r", encoding="utf-8") as handle:
        sql = handle.read()
    with conn.cursor() as cursor:
        cursor.execute(sql)
    conn.commit()


def insert_run_start(
    conn,
    *,
    run_id: UUID,
    source_name: str,
    file_path: Path,
    started_at: datetime,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO pipeline_runs (
                run_id,
                source_name,
                file_path,
                status,
                started_at
            )
            VALUES (%s, %s, %s, 'running', %s)
            """,
            (str(run_id), source_name, str(file_path), started_at),
        )
    conn.commit()


def mark_run_completed(
    conn,
    *,
    run_id: UUID,
    finished_at: datetime,
    duration_ms: int,
    rows_read: int,
    rows_valid: int,
    rows_loaded: int,
    rows_rejected: int,
    duplicates_dropped: int,
    csv_parse_ms: int,
    transform_ms: int,
    copy_ms: int,
    upsert_ms: int,
) -> None:
    throughput = rows_loaded / max(duration_ms / 1000, 0.001)
    error_rate = round(rows_rejected / rows_read, 6) if rows_read else 0
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE pipeline_runs
            SET status = 'completed',
                finished_at = %s,
                duration_ms = %s,
                rows_read = %s,
                rows_valid = %s,
                rows_loaded = %s,
                rows_rejected = %s,
                duplicates_dropped = %s,
                throughput_rows_per_sec = %s,
                error_rate = %s,
                csv_parse_ms = %s,
                transform_ms = %s,
                copy_ms = %s,
                upsert_ms = %s,
                error_message = NULL,
                failure_summary = '{}'::jsonb
            WHERE run_id = %s
            """,
            (
                finished_at,
                duration_ms,
                rows_read,
                rows_valid,
                rows_loaded,
                rows_rejected,
                duplicates_dropped,
                throughput,
                error_rate,
                csv_parse_ms,
                transform_ms,
                copy_ms,
                upsert_ms,
                str(run_id),
            ),
        )
    conn.commit()


def mark_run_failed(
    conn,
    *,
    run_id: UUID,
    finished_at: datetime,
    duration_ms: int,
    rows_read: int,
    rows_valid: int,
    rows_rejected: int,
    duplicates_dropped: int,
    error: BaseException,
    csv_parse_ms: int = 0,
    transform_ms: int = 0,
    copy_ms: int = 0,
    upsert_ms: int = 0,
) -> None:
    failure_summary = build_failure_summary(error)
    error_rate = round(rows_rejected / rows_read, 6) if rows_read else 0
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE pipeline_runs
            SET status = 'failed',
                finished_at = %s,
                duration_ms = %s,
                rows_read = %s,
                rows_valid = %s,
                rows_rejected = %s,
                duplicates_dropped = %s,
                error_rate = %s,
                csv_parse_ms = %s,
                transform_ms = %s,
                copy_ms = %s,
                upsert_ms = %s,
                error_message = %s,
                failure_summary = %s::jsonb
            WHERE run_id = %s
            """,
            (
                finished_at,
                duration_ms,
                rows_read,
                rows_valid,
                rows_rejected,
                duplicates_dropped,
                error_rate,
                csv_parse_ms,
                transform_ms,
                copy_ms,
                upsert_ms,
                str(error),
                json.dumps(failure_summary),
                str(run_id),
            ),
        )
    conn.commit()


def load_market_prices(conn, rows: pd.DataFrame) -> LoadMetrics:
    if rows.empty:
        return LoadMetrics(rows_loaded=0, copy_ms=0, upsert_ms=0)

    temp_table = "staging_market_prices"
    export_rows = rows[COPY_COLUMNS].copy()
    export_rows["price_ts"] = pd.to_datetime(export_rows["price_ts"], utc=True).dt.strftime(
        "%Y-%m-%dT%H:%M:%S%z"
    )

    csv_buffer = io.StringIO()
    export_rows.to_csv(csv_buffer, index=False, header=False, na_rep="\\N")
    csv_buffer.seek(0)

    with conn.cursor() as cursor:
        cursor.execute(f"CREATE TEMP TABLE {temp_table} (LIKE market_prices INCLUDING DEFAULTS)")
        copy_start = perf_counter()
        cursor.copy_expert(
            f"""
            COPY {temp_table} ({", ".join(COPY_COLUMNS)})
            FROM STDIN WITH (FORMAT CSV, NULL '\\N')
            """,
            csv_buffer,
        )
        copy_ms = int((perf_counter() - copy_start) * 1000)
        upsert_start = perf_counter()
        cursor.execute(
            f"""
            INSERT INTO market_prices ({", ".join(COPY_COLUMNS)})
            SELECT {", ".join(COPY_COLUMNS)}
            FROM {temp_table}
            ON CONFLICT (source_name, symbol, price_ts)
            DO UPDATE SET
                open_price = EXCLUDED.open_price,
                high_price = EXCLUDED.high_price,
                low_price = EXCLUDED.low_price,
                close_price = EXCLUDED.close_price,
                volume = EXCLUDED.volume,
                adjusted_close = EXCLUDED.adjusted_close,
                currency = EXCLUDED.currency,
                updated_at = NOW()
            WHERE market_prices.open_price IS DISTINCT FROM EXCLUDED.open_price
                OR market_prices.high_price IS DISTINCT FROM EXCLUDED.high_price
                OR market_prices.low_price IS DISTINCT FROM EXCLUDED.low_price
                OR market_prices.close_price IS DISTINCT FROM EXCLUDED.close_price
                OR market_prices.volume IS DISTINCT FROM EXCLUDED.volume
                OR market_prices.adjusted_close IS DISTINCT FROM EXCLUDED.adjusted_close
                OR market_prices.currency IS DISTINCT FROM EXCLUDED.currency
            """
        )
        upsert_ms = int((perf_counter() - upsert_start) * 1000)
    conn.commit()
    return LoadMetrics(rows_loaded=len(rows), copy_ms=copy_ms, upsert_ms=upsert_ms)


def apply_retention_policy(conn, retention_days: int) -> int:
    with conn.cursor() as cursor:
        cursor.execute("SELECT prune_pipeline_runs(%s)", (retention_days,))
        deleted = cursor.fetchone()[0]
    conn.commit()
    return int(deleted)


def build_failure_summary(error: BaseException) -> dict[str, Any]:
    return {
        "error_type": type(error).__name__,
        "summary": str(error),
        "diagnosis": [
            "Check the JSON log event for source_name, file_path, and run_id.",
            "Inspect rejected rows under data/processed/rejections if the run reached validation.",
            "Verify PostgreSQL connectivity and schema state if the failure happened during load.",
        ],
        "mitigation": [
            "Fix malformed source rows or adjust YAML column mappings.",
            "Re-run the same command. Loads are idempotent through the source_name, symbol, price_ts key.",
            "If database constraints failed, compare transform business rules with db/schema.sql.",
        ],
        "escalation": [
            "Capture the run_id, traceback, input filename, and latest pipeline_runs row.",
            "Escalate only after one corrected re-run fails with the same error signature.",
        ],
    }


def utc_now() -> datetime:
    return datetime.now(UTC)
