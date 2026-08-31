from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
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
    reconciliation_status: str
    reconciliation: dict[str, Any]


class ReconciliationError(RuntimeError):
    def __init__(self, reconciliation: dict[str, Any]) -> None:
        super().__init__("source-to-database reconciliation failed")
        self.reconciliation = reconciliation


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
    reconciliation_status: str,
    reconciliation: dict[str, Any],
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
                reconciliation_status = %s,
                reconciliation = %s::jsonb,
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
                reconciliation_status,
                json.dumps(reconciliation, sort_keys=True),
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
    reconciliation_status: str = "not_run",
    reconciliation: dict[str, Any] | None = None,
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
                reconciliation_status = %s,
                reconciliation = %s::jsonb,
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
                reconciliation_status,
                json.dumps(reconciliation or {}, sort_keys=True),
                str(error),
                json.dumps(failure_summary),
                str(run_id),
            ),
        )
    conn.commit()


def load_market_prices(
    conn,
    rows: pd.DataFrame,
    valid_from: datetime | None = None,
) -> LoadMetrics:
    if rows.empty:
        reconciliation = {
            "status": "passed",
            "source_total_rows": 0,
            "landed_total_rows": 0,
            "per_symbol": {},
        }
        return LoadMetrics(
            rows_loaded=0,
            copy_ms=0,
            upsert_ms=0,
            reconciliation_status="passed",
            reconciliation=reconciliation,
        )

    temp_table = "staging_market_prices"
    valid_from = valid_from or utc_now()
    export_rows = rows[COPY_COLUMNS].copy()
    export_rows["price_ts"] = pd.to_datetime(export_rows["price_ts"], utc=True).dt.strftime(
        "%Y-%m-%dT%H:%M:%S%z"
    )

    csv_buffer = io.StringIO()
    export_rows.to_csv(csv_buffer, index=False, header=False, na_rep="\\N")
    csv_buffer.seek(0)

    with conn.cursor() as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {temp_table}")
        cursor.execute(
            f"""
            CREATE TEMP TABLE {temp_table} (
                source_name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                price_ts TIMESTAMPTZ NOT NULL,
                open_price NUMERIC(18, 6) NOT NULL,
                high_price NUMERIC(18, 6) NOT NULL,
                low_price NUMERIC(18, 6) NOT NULL,
                close_price NUMERIC(18, 6) NOT NULL,
                volume BIGINT NOT NULL,
                adjusted_close NUMERIC(18, 6),
                currency CHAR(3) NOT NULL
            ) ON COMMIT DROP
            """
        )
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
            UPDATE market_prices mp
            SET valid_to = %s,
                updated_at = %s
            FROM {temp_table} s
            WHERE mp.source_name = s.source_name
                AND mp.symbol = s.symbol
                AND mp.price_ts = s.price_ts
                AND mp.valid_to IS NULL
                AND (
                    mp.open_price IS DISTINCT FROM s.open_price
                    OR mp.high_price IS DISTINCT FROM s.high_price
                    OR mp.low_price IS DISTINCT FROM s.low_price
                    OR mp.close_price IS DISTINCT FROM s.close_price
                    OR mp.volume IS DISTINCT FROM s.volume
                    OR mp.adjusted_close IS DISTINCT FROM s.adjusted_close
                    OR mp.currency IS DISTINCT FROM s.currency
                )
            """,
            (valid_from, valid_from),
        )
        cursor.execute(
            f"""
            INSERT INTO market_prices (
                {", ".join(COPY_COLUMNS)},
                ingested_at,
                valid_from
            )
            SELECT
                {", ".join(f"s.{column}" for column in COPY_COLUMNS)},
                %s,
                %s
            FROM {temp_table} s
            LEFT JOIN market_prices active
                ON active.source_name = s.source_name
                AND active.symbol = s.symbol
                AND active.price_ts = s.price_ts
                AND active.valid_to IS NULL
            WHERE active.id IS NULL
            """,
            (valid_from, valid_from),
        )
        upsert_ms = int((perf_counter() - upsert_start) * 1000)
        reconciliation = reconcile_staged_rows(cursor, temp_table)

    if reconciliation["status"] != "passed":
        conn.rollback()
        raise ReconciliationError(reconciliation)

    conn.commit()
    return LoadMetrics(
        rows_loaded=len(rows),
        copy_ms=copy_ms,
        upsert_ms=upsert_ms,
        reconciliation_status="passed",
        reconciliation=reconciliation,
    )


def reconcile_staged_rows(cursor, temp_table: str) -> dict[str, Any]:
    source = _fetch_checksums(cursor, f"SELECT * FROM {temp_table}")
    landed = _fetch_checksums(
        cursor,
        f"""
        SELECT mp.*
        FROM market_prices mp
        INNER JOIN {temp_table} s
            ON mp.source_name = s.source_name
            AND mp.symbol = s.symbol
            AND mp.price_ts = s.price_ts
        WHERE mp.valid_to IS NULL
        """,
    )
    per_symbol: dict[str, Any] = {}
    symbols = sorted(set(source) | set(landed))
    for symbol in symbols:
        source_item = source.get(symbol, {"row_count": 0, "checksum": None})
        landed_item = landed.get(symbol, {"row_count": 0, "checksum": None})
        per_symbol[symbol] = {
            "source_rows": source_item["row_count"],
            "landed_rows": landed_item["row_count"],
            "source_checksum": source_item["checksum"],
            "landed_checksum": landed_item["checksum"],
            "matched": source_item == landed_item,
        }

    source_total = sum(item["row_count"] for item in source.values())
    landed_total = sum(item["row_count"] for item in landed.values())
    passed = source_total == landed_total and all(item["matched"] for item in per_symbol.values())
    return {
        "status": "passed" if passed else "failed",
        "source_total_rows": source_total,
        "landed_total_rows": landed_total,
        "per_symbol": per_symbol,
    }


def _fetch_checksums(cursor, source_sql: str) -> dict[str, dict[str, Any]]:
    cursor.execute(
        f"""
        SELECT
            symbol,
            COUNT(*)::BIGINT AS row_count,
            MD5(STRING_AGG(
                CONCAT_WS(
                    '|',
                    source_name,
                    symbol,
                    TO_CHAR(price_ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
                    open_price::TEXT,
                    high_price::TEXT,
                    low_price::TEXT,
                    close_price::TEXT,
                    volume::TEXT,
                    COALESCE(adjusted_close::TEXT, ''),
                    currency
                ),
                '||'
                ORDER BY source_name, symbol, price_ts
            )) AS checksum
        FROM ({source_sql}) rows_for_reconciliation
        GROUP BY symbol
        ORDER BY symbol
        """
    )
    return {
        symbol: {"row_count": int(row_count), "checksum": checksum}
        for symbol, row_count, checksum in cursor.fetchall()
    }


def recompute_adjusted_close(conn, source_name: str, symbol: str) -> int:
    normalized_symbol = symbol.upper()
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, price_ts::DATE, close_price
            FROM market_prices
            WHERE source_name = %s
                AND symbol = %s
            ORDER BY price_ts
            """,
            (source_name, normalized_symbol),
        )
        price_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT action_date, action_type, split_ratio, dividend_amount
            FROM corporate_actions
            WHERE source_name = %s
                AND symbol = %s
            ORDER BY action_date
            """,
            (source_name, normalized_symbol),
        )
        actions = cursor.fetchall()

        updates: list[tuple[Decimal, int]] = []
        for row_id, price_date, close_price in price_rows:
            adjusted = Decimal(close_price)
            for action_date, action_type, split_ratio, dividend_amount in actions:
                if price_date >= action_date:
                    continue
                if action_type == "split":
                    adjusted = adjusted / Decimal(split_ratio)
                elif action_type == "dividend" and dividend_amount is not None:
                    adjusted = adjusted - Decimal(dividend_amount)
            adjusted = adjusted.quantize(Decimal("0.000001"))
            updates.append((adjusted, row_id))

        cursor.executemany(
            """
            UPDATE market_prices
            SET adjusted_close = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            updates,
        )
    conn.commit()
    return len(updates)


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
