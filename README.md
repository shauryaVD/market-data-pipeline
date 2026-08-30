# Market Data Pipeline

Personal batch ETL pipeline for ingesting market price CSVs into PostgreSQL.

Repository: https://github.com/shauryaVD/market-data-pipeline

## Portfolio Positioning

- Project only. Never list this under Experience.
- Resume title through May: `Production ETL Pipeline - Market Data Ingestion`.
- Resume title from June onward, including Google: `Market-Data ETL Pipeline`.

## Target Stack

- Python
- pandas
- psycopg2
- PostgreSQL
- Docker
- YAML
- cron
- structured logging

## Technical Scope

1. Batch ETL over market price CSVs with timezone conversion, deduplication, type validation, and business-rule enforcement.
2. Idempotent bulk loads using psycopg2 `COPY` plus PostgreSQL UPSERT, targeting 1,000+ rows/sec and zero duplicate risk on re-runs.
3. `pipeline_runs` monitoring table for duration, throughput, and error rates, with retention policies.
4. Incident-response framework with structured failure summaries and runbook steps for diagnosis, mitigation, and escalation.
5. Docker and cron based execution with YAML-driven configuration so new sources and destinations can be added without code changes.

## What Is Implemented

- YAML-driven source configuration in `configs/pipeline.yml`
- pandas transformation layer for timezone conversion, deduplication, type validation, and business-rule checks
- PostgreSQL schema with `market_prices`, `pipeline_runs`, indexes, constraints, and retention function
- psycopg2 `COPY` into a temporary staging table followed by PostgreSQL UPSERT into `market_prices`
- JSON structured logs to stdout and `logs/pipeline.log`
- rejected-row exports under `data/processed/rejections/`
- incident-response runbook in `docs/RUNBOOK.md`
- Docker Compose PostgreSQL service
- cron example for weekday batch execution
- unit tests for config loading, validation, deduplication, timezone conversion, and failure summaries

## Current Status

Pipeline implementation is complete for a local batch ETL MVP. Docker is not installed on the current machine, so the containerized PostgreSQL smoke test has not been run here.

## Quick Start

Create a virtual environment and install the project:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Start PostgreSQL:

```bash
docker compose up -d postgres
```

Run the pipeline:

```bash
market-data-pipeline init-db --config configs/pipeline.yml
market-data-pipeline run --config configs/pipeline.yml
```

Validate configuration only:

```bash
market-data-pipeline validate-config --config configs/pipeline.yml
```

Run tests:

```bash
pytest
```

## Data Contract

The default sample source expects:

| CSV column | Target column |
|---|---|
| `symbol` | `symbol` |
| `timestamp` | `price_ts` |
| `open` | `open_price` |
| `high` | `high_price` |
| `low` | `low_price` |
| `close` | `close_price` |
| `volume` | `volume` |
| `adjusted_close` | `adjusted_close` |
| `currency` | `currency` |

The natural key is `(source_name, symbol, price_ts)`, which makes re-runs idempotent.

## Operational Notes

- Run metadata lands in `pipeline_runs`.
- Runtime logs are JSON structured.
- Failed runs store a structured failure summary with diagnosis, mitigation, and escalation steps.
- `prune_pipeline_runs(retention_days)` enforces monitoring-table retention.
- `scripts/cron.example` shows a weekday scheduled batch.
- `scripts/benchmark_load.py` generates synthetic CSVs for measuring throughput on a machine with PostgreSQL available.

## Next Step

Run a Docker-backed integration smoke test on a machine with Docker installed, then record the measured throughput from `pipeline_runs.throughput_rows_per_sec`.
