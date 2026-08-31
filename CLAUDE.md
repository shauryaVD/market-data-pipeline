# Market Data Pipeline - Claude Context

> Primary reference: read `README.md` first. Keep this in sync with `AGENTS.md`.

## Overview

This is a personal portfolio project: a batch ETL pipeline that ingests market price CSVs into PostgreSQL with idempotent bulk loading, monitoring, and operational runbooks.

## Positioning Rules

- Keep this in Projects, never Experience.
- Do not inflate implementation status. The local ETL MVP is implemented and Docker/PostgreSQL throughput is measured in `docs/BENCHMARK.md` on a GitHub Actions runner.
- Do not fabricate benchmarks. Use the measured median steady-state figure from `docs/BENCHMARK.md`, not best-run throughput.
- Never commit secrets or `.env` contents.
- Do not push, publish, or create a remote without Shaurya's explicit approval.

## Expected Stack

- Python with pandas and psycopg2
- PostgreSQL
- Docker and Docker Compose
- YAML configuration
- cron-compatible batch execution
- structured logging

## After Any Task

Update this repo's README if status, setup, or scope changes. Also update the tracking brief in `Cowork OS/Personal/Projects/market-data-pipeline/PROJECT.md` and log the work in `Cowork OS/Personal/Projects/memories/memories.md`.
