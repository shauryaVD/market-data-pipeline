# Market Data Pipeline

A production-style batch ETL project for loading market price CSV files into PostgreSQL with validation, idempotent writes, run monitoring, and operational documentation.

Repository: https://github.com/shauryaVD/market-data-pipeline

## Overview

This project simulates a common data engineering workflow: market price files arrive as CSVs, the pipeline validates and normalizes the data, then loads clean records into PostgreSQL without creating duplicates on repeat runs.

The goal is not to build a trading platform. The goal is to show reliable batch ingestion mechanics: clear data contracts, configurable sources, defensible validation, database constraints, observability, and a runbook for failures.

## What It Demonstrates

- Python ETL structure with separated config, transform, database, logging, and CLI layers
- pandas-based validation and transformation
- timezone conversion from source market time to UTC
- deduplication by natural key before loading
- type checks for timestamps, prices, volume, symbols, and currency codes
- business-rule enforcement for positive prices, non-negative volume, and high/low price envelopes
- PostgreSQL bulk loading through psycopg2 `COPY`
- idempotent UPSERT into the final `market_prices` table
- `pipeline_runs` monitoring table for duration, throughput, rejected rows, duplicate counts, and error rates
- structured JSON logging for local debugging and operational review
- rejected-row exports for data-quality triage
- Docker Compose PostgreSQL setup
- YAML-driven source configuration
- cron-compatible batch execution
- runbook and architecture documentation

## Architecture

```text
CSV source
  -> YAML source config
  -> pandas validation and transformation
  -> rejected-row export
  -> psycopg2 COPY into PostgreSQL staging table
  -> UPSERT into market_prices
  -> pipeline_runs monitoring update
  -> retention policy
```

The natural key is:

```text
(source_name, symbol, price_ts)
```

That key is enforced as the primary key in PostgreSQL, which means re-running the same file updates existing rows instead of creating duplicates.

## Tech Stack

- Python
- pandas
- psycopg2
- PostgreSQL
- Docker Compose
- YAML
- cron
- pytest
- Ruff

## Repository Structure

```text
.
|-- configs/
|   `-- pipeline.yml              # source, timezone, column, and rule config
|-- data/
|   `-- raw/
|       `-- sample_market_prices.csv
|-- db/
|   |-- schema.sql                # market_prices, pipeline_runs, indexes, retention
|   `-- monitoring_queries.sql    # operational SQL examples
|-- docs/
|   |-- ARCHITECTURE.md
|   `-- RUNBOOK.md
|-- scripts/
|   |-- benchmark_load.py         # synthetic CSV generator for throughput testing
|   |-- cron.example
|   `-- run_pipeline.sh
|-- src/
|   `-- market_data_pipeline/
|       |-- cli.py
|       |-- config.py
|       |-- db.py
|       |-- logging_config.py
|       |-- pipeline.py
|       `-- transform.py
`-- tests/
```

## Quick Start

Create a virtual environment and install the project:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

Validate the YAML config:

```bash
market-data-pipeline validate-config --config configs/pipeline.yml
```

Start PostgreSQL:

```bash
docker compose up -d postgres
```

Apply the database schema:

```bash
market-data-pipeline init-db --config configs/pipeline.yml
```

Run the sample ingestion:

```bash
market-data-pipeline run --config configs/pipeline.yml
```

Run tests:

```bash
pytest -q
```

Run lint and formatting checks:

```bash
ruff check .
ruff format --check .
```

## Configuration

Sources are defined in `configs/pipeline.yml`. A source controls:

- input CSV path
- source and target timezone
- destination table
- CSV-to-canonical column mappings
- required columns
- business rules

Example source:

```yaml
sources:
  - name: "sample_daily_prices"
    path: "data/raw/sample_market_prices.csv"
    timezone:
      source: "America/New_York"
      target: "UTC"
    destination_table: "market_prices"
```

## Data Contract

The default sample source expects:

| CSV column | Target field |
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

Rows that fail validation are excluded from the load and written to `data/processed/rejections/` with rejection reasons.

## Observability

Every run writes a record to `pipeline_runs`.

Tracked fields include:

- run ID
- source name
- input file path
- status
- start and finish timestamps
- duration
- rows read
- rows valid
- rows loaded
- rows rejected
- duplicates dropped
- throughput rows per second
- error rate
- structured failure summary

Failed runs include diagnosis, mitigation, and escalation steps in `failure_summary`.

## Idempotent Loading

The loader uses a two-step PostgreSQL pattern:

1. Bulk copy valid rows into a temporary staging table with psycopg2 `COPY`.
2. Insert into `market_prices` with `ON CONFLICT (source_name, symbol, price_ts) DO UPDATE`.

This makes repeat runs safe. If the same file is loaded again, rows are matched by key and updated instead of duplicated.

## Benchmarking

The repo includes a synthetic data generator:

```bash
python scripts/benchmark_load.py --rows 100000 --output data/raw/benchmark_market_prices.csv
```

After pointing `configs/pipeline.yml` at the generated file, run the pipeline and inspect:

```sql
SELECT run_id, rows_loaded, duration_ms, throughput_rows_per_sec
FROM pipeline_runs
ORDER BY started_at DESC
LIMIT 5;
```

Throughput should be claimed only after measuring it against a running PostgreSQL instance on the target machine.

## Current Verification

Verified locally:

- unit tests for config loading, CLI config validation, transformation, deduplication, timezone conversion, business rules, and failure summaries
- Ruff lint and format checks
- Python compile check
- CLI config validation

Not yet verified in the current environment:

- Docker-backed PostgreSQL smoke test, because Docker is not installed on this machine
- measured PostgreSQL throughput benchmark

## Next Improvements

- Add an integration test profile that runs against Docker Compose PostgreSQL
- Record a measured throughput benchmark in `pipeline_runs`
- Add multiple source configs for different vendors or market data formats
- Add a small dashboard query export for recent pipeline health
