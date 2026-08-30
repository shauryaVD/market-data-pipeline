# Architecture

## Flow

```text
CSV source
  -> config-driven extraction
  -> pandas validation and transformation
  -> rejected-row export
  -> psycopg2 COPY into PostgreSQL staging table
  -> UPSERT into market_prices
  -> pipeline_runs monitoring update
  -> retention policy
```

## Key Design Choices

### Idempotency

`market_prices` uses `(source_name, symbol, price_ts)` as the primary key. The loader stages every valid row with `COPY`, then inserts into the final table with `ON CONFLICT DO UPDATE`. Re-running the same file cannot create duplicate market-price rows.

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
- deduplication by source, symbol, and timestamp

### Observability

Every run gets a UUID and a `pipeline_runs` record. Completed runs store row counts, duration, throughput, rejection count, duplicate count, and error rate. Failed runs store a structured incident summary with diagnosis, mitigation, and escalation steps.

### Extensibility

New CSV sources can be added in `configs/pipeline.yml` by adding another source entry with its own file path, timezone, column mappings, required columns, and business rules. The current implementation supports the `market_prices` destination table.

### Retention

The PostgreSQL function `prune_pipeline_runs(retention_days)` keeps run history bounded. The pipeline calls this function after successful runs.
