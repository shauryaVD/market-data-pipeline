# Market Data Pipeline Runbook

## Purpose

This runbook covers the batch ETL that loads market price CSVs into PostgreSQL.

## Normal Operation

1. Place source CSV files under `data/raw/` or update `configs/pipeline.yml` with the source path.
2. Start PostgreSQL:

   ```bash
   docker compose up -d postgres
   ```

3. Install the package:

   ```bash
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -e ".[dev]"
   ```

4. Apply schema:

   ```bash
   market-data-pipeline init-db --config configs/pipeline.yml
   ```

5. Run the batch:

   ```bash
   market-data-pipeline run --config configs/pipeline.yml
   ```

## Monitoring

Each run writes to `pipeline_runs` with:

- status
- duration
- rows read
- rows valid
- rows loaded
- rows rejected
- duplicates dropped
- throughput rows per second
- error rate
- structured failure summary

Useful query:

```sql
SELECT
    run_id,
    source_name,
    status,
    started_at,
    duration_ms,
    rows_read,
    rows_valid,
    rows_loaded,
    rows_rejected,
    duplicates_dropped,
    throughput_rows_per_sec,
    error_rate
FROM pipeline_runs
ORDER BY started_at DESC
LIMIT 10;
```

## Incident Response

### Diagnosis

1. Find the failed run:

   ```sql
   SELECT run_id, error_message, failure_summary
   FROM pipeline_runs
   WHERE status = 'failed'
   ORDER BY started_at DESC
   LIMIT 1;
   ```

2. Check `logs/pipeline.log` for the matching `run_id`.
3. Check `data/processed/rejections/` for rejected-row CSVs.
4. Validate the YAML mapping:

   ```bash
   market-data-pipeline validate-config --config configs/pipeline.yml
   ```

### Mitigation

1. If rows are rejected, fix the source CSV or adjust the YAML column mapping.
2. If the database load fails, compare validation rules in `src/market_data_pipeline/transform.py` with constraints in `db/schema.sql`.
3. Re-run the same command. The load is idempotent because `market_prices` uses `(source_name, symbol, price_ts)` as the primary key and PostgreSQL UPSERT handles repeats.

### Escalation

Escalate only after one corrected re-run fails with the same error. Capture:

- `run_id`
- command used
- input CSV path
- latest `pipeline_runs` row
- matching JSON log events
- traceback

## Retention

The `prune_pipeline_runs(retention_days)` PostgreSQL function deletes old `pipeline_runs` records. The pipeline calls it after successful runs using `retention.pipeline_runs_days` from `configs/pipeline.yml`.

## Benchmarking

Generate a synthetic file:

```bash
python scripts/benchmark_load.py --rows 100000 --output data/raw/benchmark_market_prices.csv
```

Point a YAML source at the generated file, run the pipeline, then use `pipeline_runs.throughput_rows_per_sec` as the measured benchmark. Do not claim a throughput number until this is measured on the target machine.
