# Market Data Pipeline

Personal batch ETL pipeline for ingesting market price CSVs into PostgreSQL.

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

## Current Status

Repository created. ETL implementation has not started yet.

## Next Step

Scaffold the Python package, Docker Compose PostgreSQL service, configuration layout, and first ingestion path for one sample market-price CSV.
