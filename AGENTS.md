# Market Data Pipeline - Codex / OpenAI Agent Context

> Primary reference: read `README.md` first. This file mirrors `CLAUDE.md` for Codex/OpenAI agents.

## Overview

This is a personal portfolio project: a batch ETL pipeline that ingests market price CSVs into PostgreSQL with idempotent bulk loading, monitoring, and operational runbooks.

## Positioning Rules

- Keep this in Projects, never Experience.
- Do not inflate implementation status. The local ETL MVP is implemented; Docker-backed throughput still needs to be measured on a machine with Docker/PostgreSQL available.
- Do not fabricate benchmarks. The target claim is 1,000+ rows/sec only after it is implemented and measured locally.
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
