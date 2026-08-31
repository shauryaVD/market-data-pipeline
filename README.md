# Market Data Pipeline

[![CI](https://github.com/shauryaVD/market-data-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/shauryaVD/market-data-pipeline/actions/workflows/ci.yml)

Fintech-oriented market data ETL pipeline for loading vendor-style price files into PostgreSQL with point-in-time history, idempotent ingestion, source reconciliation, corporate-action adjustment, and run-level observability.

Repository: https://github.com/shauryaVD/market-data-pipeline

## 90-Second Review

This project handles a practical market-data problem: price files can arrive late, get restated, or conflict with what was already loaded. Instead of overwriting history, the pipeline stores both effective time (`price_ts`) and knowledge time (`valid_from`, `valid_to`, `ingested_at`) so a backtest or audit can answer: what did we believe the close was as of date X?

Measured throughput is recorded in [`docs/BENCHMARK.md`](docs/BENCHMARK.md). The benchmark is run through Docker/PostgreSQL and reads results back from `pipeline_runs`; do not claim a new number unless that file is regenerated.

## Architecture

```text
Vendor CSV
  -> YAML source contract
  -> pandas validation and normalization
  -> trading-calendar checks
  -> rejected-row export
  -> psycopg2 COPY into PostgreSQL staging
  -> temporal merge into market_prices
  -> source reconciliation by row count and per-symbol checksum
  -> pipeline_runs observability record
  -> retention policy
```

## Two-Command Setup

```bash
make install
docker compose up -d postgres && make init-db && make run
```

The default `make run` command loads `sample_daily_prices`. Benchmark sources are explicit so a reviewer does not accidentally generate or load large files.

## Data Contract

Default source columns:

| CSV column | Target field | Notes |
|---|---|---|
| `symbol` | `symbol` | normalized uppercase |
| `timestamp` | `price_ts` | source timezone converted to UTC |
| `open` | `open_price` | PostgreSQL `NUMERIC`, not float |
| `high` | `high_price` | PostgreSQL `NUMERIC`, not float |
| `low` | `low_price` | PostgreSQL `NUMERIC`, not float |
| `close` | `close_price` | PostgreSQL `NUMERIC`, not float |
| `volume` | `volume` | integer, non-negative |
| `adjusted_close` | `adjusted_close` | recomputed after corporate actions |
| `currency` | `currency` | three-letter ISO-style code |

Natural market-data key:

```text
(source_name, symbol, price_ts)
```

The active version of that key is unique. Corrections close the previous version by setting `valid_to` and insert a new current version with a later `valid_from`.

## Point-In-Time Query

Market data gets corrected. Backtests and audits need the historical belief, not only the latest corrected value.

```sql
SELECT close_price, adjusted_close, valid_from, valid_to, ingested_at
FROM market_price_as_of(
    'sample_daily_prices',
    'AAPL',
    '2026-03-13 13:30:00+00'::timestamptz,
    '2026-03-14 00:00:00+00'::timestamptz
);
```

Effective time is when the market event happened. Knowledge time is when the pipeline believed a specific version was current.

## Fintech/Data Engineering Features

- CI on every push and pull request with Ruff, pytest, and a PostgreSQL service container
- point-in-time price history with `ingested_at`, `valid_from`, and `valid_to`
- as-of SQL function for backtesting and audit reads
- idempotent loads through staging plus temporal merge
- prices stored in PostgreSQL `NUMERIC`; transformation avoids float-derived price values
- source reconciliation after each load using row counts and per-symbol checksums
- run failure when reconciliation does not match
- `pipeline_runs` table with duration, throughput, phase timing, rejection counts, duplicate counts, error rate, and reconciliation JSON
- corporate-actions table for splits and dividends
- adjusted-close recomputation job for affected symbol history
- configurable market-hours and holiday validation per source
- structured JSON logs and rejected-row exports
- benchmark workflow for 100k, 500k, and 1M generated datasets

## Commands

Install:

```bash
make install
```

Validate config:

```bash
make validate
```

Run the sample source:

```bash
docker compose up -d postgres
make init-db
make run
```

Run a specific source:

```bash
make run SOURCE=benchmark_100k
```

Recompute adjusted close after loading a corporate action:

```bash
market-data-pipeline recompute-adjusted-close --config configs/pipeline.yml --source sample_daily_prices --symbol AAPL
```

Run tests:

```bash
pytest -q
```

Run lint:

```bash
ruff check .
ruff format --check .
```

Run the full benchmark:

```bash
docker compose up -d
market-data-pipeline init-db --config configs/pipeline.yml
python scripts/run_benchmark.py --reset-db
```

## Repository Map

```text
configs/pipeline.yml        YAML source contracts and validation rules
db/schema.sql               temporal prices, corporate actions, pipeline runs
db/as_of_query.sql          point-in-time query example
db/monitoring_queries.sql   operational checks
docs/ARCHITECTURE.md        design notes
docs/RUNBOOK.md             incident response and operations
docs/BENCHMARK.md           measured throughput report
scripts/run_benchmark.py    benchmark harness
src/market_data_pipeline/   Python ETL package
tests/                      unit and PostgreSQL integration tests
```
