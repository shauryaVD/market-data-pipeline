from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from market_data_pipeline.config import PipelineConfig, SourceConfig, load_config
from market_data_pipeline.db import (
    ReconciliationError,
    apply_retention_policy,
    apply_schema,
    connect,
    insert_run_start,
    load_market_prices,
    mark_run_completed,
    mark_run_failed,
    utc_now,
)
from market_data_pipeline.logging_config import configure_logging, log_event
from market_data_pipeline.transform import read_market_csv, transform_market_data

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineRunResult:
    run_id: str
    source_name: str
    rows_read: int
    rows_valid: int
    rows_loaded: int
    rows_rejected: int
    duplicates_dropped: int
    duration_ms: int
    throughput_rows_per_sec: float
    csv_parse_ms: int
    transform_ms: int
    copy_ms: int
    upsert_ms: int
    reconciliation_status: str
    reconciliation: dict
    rejection_path: Path | None


def initialize_database(config_path: str | Path) -> None:
    config = load_config(config_path)
    configure_logging(config.logging)
    conn = connect(config.database.dsn)
    try:
        apply_schema(conn, config.database.schema_path)
        log_event(
            logger,
            logging.INFO,
            "schema_applied",
            "database schema applied",
            schema_path=str(config.database.schema_path),
        )
    finally:
        conn.close()


def run_from_config(
    config_path: str | Path, source_name: str | None = None
) -> list[PipelineRunResult]:
    config = load_config(config_path)
    configure_logging(config.logging)

    selected_sources = _select_sources(config, source_name)
    results: list[PipelineRunResult] = []
    for source in selected_sources:
        results.append(run_source(config, source))
    return results


def run_source(config: PipelineConfig, source: SourceConfig) -> PipelineRunResult:
    run_id = uuid4()
    started_at = utc_now()
    start = perf_counter()
    conn = connect(config.database.dsn)
    rows_read = 0
    rows_valid = 0
    rows_rejected = 0
    duplicates_dropped = 0
    csv_parse_ms = 0
    transform_ms = 0
    copy_ms = 0
    upsert_ms = 0
    reconciliation_status = "not_run"
    reconciliation: dict = {}

    log_event(
        logger,
        logging.INFO,
        "run_started",
        "pipeline run started",
        run_id=str(run_id),
        source_name=source.name,
        file_path=str(source.path),
    )

    try:
        apply_schema(conn, config.database.schema_path)
        insert_run_start(
            conn,
            run_id=run_id,
            source_name=source.name,
            file_path=source.path,
            started_at=started_at,
        )

        csv_parse_start = perf_counter()
        raw = read_market_csv(source)
        csv_parse_ms = int((perf_counter() - csv_parse_start) * 1000)

        transform_start = perf_counter()
        transformed = transform_market_data(raw, source)
        transform_ms = int((perf_counter() - transform_start) * 1000)
        rows_read = transformed.rows_read
        rows_valid = transformed.rows_valid
        rows_rejected = transformed.rows_rejected
        duplicates_dropped = transformed.duplicates_dropped

        rejection_path = write_rejections(config.base_dir, source.name, str(run_id), transformed)
        load_metrics = load_market_prices(conn, transformed.valid_rows)
        rows_loaded = load_metrics.rows_loaded
        copy_ms = load_metrics.copy_ms
        upsert_ms = load_metrics.upsert_ms
        reconciliation_status = load_metrics.reconciliation_status
        reconciliation = load_metrics.reconciliation
        deleted_runs = apply_retention_policy(conn, config.retention.pipeline_runs_days)

        duration_ms = int((perf_counter() - start) * 1000)
        throughput = round(rows_loaded / max(duration_ms / 1000, 0.001), 2)
        mark_run_completed(
            conn,
            run_id=run_id,
            finished_at=utc_now(),
            duration_ms=duration_ms,
            rows_read=rows_read,
            rows_valid=rows_valid,
            rows_loaded=rows_loaded,
            rows_rejected=rows_rejected,
            duplicates_dropped=duplicates_dropped,
            csv_parse_ms=csv_parse_ms,
            transform_ms=transform_ms,
            copy_ms=copy_ms,
            upsert_ms=upsert_ms,
            reconciliation_status=reconciliation_status,
            reconciliation=reconciliation,
        )
        log_event(
            logger,
            logging.INFO,
            "run_completed",
            "pipeline run completed",
            run_id=str(run_id),
            source_name=source.name,
            rows_read=rows_read,
            rows_valid=rows_valid,
            rows_loaded=rows_loaded,
            rows_rejected=rows_rejected,
            duplicates_dropped=duplicates_dropped,
            throughput_rows_per_sec=throughput,
            csv_parse_ms=csv_parse_ms,
            transform_ms=transform_ms,
            copy_ms=copy_ms,
            upsert_ms=upsert_ms,
            reconciliation_status=reconciliation_status,
            reconciliation=reconciliation,
            retention_rows_deleted=deleted_runs,
            rejection_path=str(rejection_path) if rejection_path else None,
        )
        return PipelineRunResult(
            run_id=str(run_id),
            source_name=source.name,
            rows_read=rows_read,
            rows_valid=rows_valid,
            rows_loaded=rows_loaded,
            rows_rejected=rows_rejected,
            duplicates_dropped=duplicates_dropped,
            duration_ms=duration_ms,
            throughput_rows_per_sec=throughput,
            csv_parse_ms=csv_parse_ms,
            transform_ms=transform_ms,
            copy_ms=copy_ms,
            upsert_ms=upsert_ms,
            reconciliation_status=reconciliation_status,
            reconciliation=reconciliation,
            rejection_path=rejection_path,
        )
    except Exception as error:
        duration_ms = int((perf_counter() - start) * 1000)
        if isinstance(error, ReconciliationError):
            reconciliation_status = "failed"
            reconciliation = error.reconciliation
        try:
            mark_run_failed(
                conn,
                run_id=run_id,
                finished_at=utc_now(),
                duration_ms=duration_ms,
                rows_read=rows_read,
                rows_valid=rows_valid,
                rows_rejected=rows_rejected,
                duplicates_dropped=duplicates_dropped,
                csv_parse_ms=csv_parse_ms,
                transform_ms=transform_ms,
                copy_ms=copy_ms,
                upsert_ms=upsert_ms,
                reconciliation_status=reconciliation_status,
                reconciliation=reconciliation,
                error=error,
            )
        except Exception:
            logger.exception(
                "failed to write failure state", extra={"_event": "failure_state_error"}
            )
        log_event(
            logger,
            logging.ERROR,
            "run_failed",
            "pipeline run failed",
            run_id=str(run_id),
            source_name=source.name,
            error_type=type(error).__name__,
            error_message=str(error),
        )
        raise
    finally:
        conn.close()


def write_rejections(base_dir: Path, source_name: str, run_id: str, transformed) -> Path | None:
    if transformed.rejected_rows.empty:
        return None

    rejection_dir = base_dir / "data" / "processed" / "rejections"
    rejection_dir.mkdir(parents=True, exist_ok=True)
    rejection_path = rejection_dir / f"{source_name}_{run_id}.csv"
    transformed.rejected_rows.to_csv(rejection_path, index=False)
    return rejection_path


def _select_sources(config: PipelineConfig, source_name: str | None) -> list[SourceConfig]:
    if source_name is None:
        return config.sources
    selected = [source for source in config.sources if source.name == source_name]
    if not selected:
        available = ", ".join(source.name for source in config.sources)
        raise ValueError(f"unknown source {source_name!r}; available sources: {available}")
    return selected
