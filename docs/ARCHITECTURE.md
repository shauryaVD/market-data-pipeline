# Architecture

## Flow

```text
Vendor CSV
  -> YAML source contract
  -> pandas validation and normalization
  -> optional trading-calendar checks
  -> rejected-row export
  -> psycopg2 COPY into PostgreSQL staging table
  -> temporal merge into market_prices
  -> source reconciliation by row count and per-symbol checksum
  -> pipeline_runs monitoring update
  -> retention policy
```

## Key Design Choices

### Point-In-Time Correctness

Market data can be restated after a backtest or report has already consumed it. `market_prices` therefore stores two timelines:

- Effective time: `price_ts`, when the market bar happened.
- Knowledge time: `ingested_at`, `valid_from`, and `valid_to`, when this pipeline believed a version of that bar was current.

When a correction arrives for the same `(source_name, symbol, price_ts)`, the active version is closed by setting `valid_to`, and a new active version is inserted. This preserves yesterday's belief for audit and backtesting while still exposing the latest active value.

The `market_price_as_of(...)` function answers: what did we believe this close was as of timestamp X?

### Idempotency And Temporal Merge

The active version of `(source_name, symbol, price_ts)` is unique through a partial index where `valid_to IS NULL`. The loader stages every valid row with `COPY`, closes changed active rows, and inserts only missing active versions. Re-running the same file does not create duplicate active rows.

### Transformation Layer

The transform step is explicit and testable:

- timezone conversion from source timezone to target timezone
- symbol and currency normalization
- numeric type validation
- integer volume validation
- positive price validation
- non-negative volume validation
- high and low envelope validation
- future timestamp rejection when configured
- market-hours and holiday rejection when configured
- deduplication by source, symbol, and timestamp

Prices are parsed as decimal values and stored in PostgreSQL `NUMERIC`.

### Source Reconciliation

After a load, the pipeline compares staged source rows with active rows in `market_prices`:

- total row count
- row count per symbol
- checksum per symbol over source, symbol, timestamp, OHLC, volume, adjusted close, and currency

The reconciliation JSON is stored in `pipeline_runs`. A mismatch fails the run.

### Corporate Actions

`corporate_actions` stores split and dividend events. The `recompute-adjusted-close` CLI job recalculates `adjusted_close` for a source/symbol across affected history. Split handling adjusts rows before the split date while leaving later rows unchanged.

### Observability

Every run gets a UUID and a `pipeline_runs` record. Completed runs store row counts, duration, throughput, phase timings, rejection count, duplicate count, error rate, and reconciliation results. Failed runs store a structured incident summary with diagnosis, mitigation, and escalation steps.

### Extensibility

New CSV sources can be added in `configs/pipeline.yml` by adding another source entry with its own file path, timezone, column mappings, required columns, business rules, and optional trading-calendar settings. The current implementation supports the `market_prices` destination table.

### Retention

The PostgreSQL function `prune_pipeline_runs(retention_days)` keeps run history bounded. The pipeline calls this function after successful runs.
