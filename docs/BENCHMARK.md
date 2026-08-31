# Benchmark Results

Generated at: `2026-08-31T06:29:41.160123+00:00`

## Environment

| Field | Value |
|---|---|
| CPU | AMD EPYC 9V74 80-Core Processor |
| Core count | 4 |
| RAM | 15.61 GiB |
| OS | Linux-6.17.0-1022-azure-x86_64-with-glibc2.39 |
| Docker | Docker version 28.0.4, build b8034c0 |
| Docker Compose | Docker Compose version v2.38.2 |
| PostgreSQL | PostgreSQL 16.15 on x86_64-pc-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit |
| Python | 3.13.15 |
| pandas | 3.0.5 |
| psycopg2 | 2.9.12 (dt dec pq3 ext lo64) |

## Row Width

Average bytes per row is measured from the generated CSV data bytes, excluding the header.

| Dataset | Column count | Average bytes per row | File bytes |
|---|---:|---:|---:|
| 100k | 9 | 70.482 | 7048269 |
| 500k | 9 | 70.482 | 35241069 |
| 1m | 9 | 70.5819 | 70582069 |

## Runs

| Dataset | Run | Mode | Run ID | Rows read | Rows loaded | Rows rejected | Duplicates dropped | Duration ms | Rows/sec | CSV parse ms | Transform ms | COPY ms | UPSERT ms |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100k | 1 | cold insert | `affeda66-a569-47a2-8256-5ed744493ffe` | 100000 | 100000 | 0 | 0 | 7363 | 13581.42 | 78 | 4557 | 168 | 871 |
| 100k | 2 | full-conflict upsert | `091f9fd6-f9b2-45d3-990a-1ab881048382` | 100000 | 100000 | 0 | 0 | 6626 | 15092.06 | 78 | 4452 | 168 | 225 |
| 100k | 3 | full-conflict upsert | `3bc6e76e-c6b7-4a75-969f-18628c169c88` | 100000 | 100000 | 0 | 0 | 6771 | 14768.87 | 78 | 4552 | 169 | 320 |
| 500k | 1 | cold insert | `6947ae5e-1dca-41cd-a8ad-13711e76bcb3` | 500000 | 500000 | 0 | 0 | 36580 | 13668.67 | 354 | 22477 | 842 | 4664 |
| 500k | 2 | full-conflict upsert | `3964b761-83da-4db9-9cfc-982722f501c8` | 500000 | 500000 | 0 | 0 | 33452 | 14946.79 | 363 | 22444 | 830 | 1628 |
| 500k | 3 | full-conflict upsert | `6d252f9e-98cd-48dc-801a-d893ed5a60b4` | 500000 | 500000 | 0 | 0 | 33126 | 15093.88 | 352 | 22254 | 838 | 1565 |
| 1m | 1 | cold insert | `b19a9a74-7680-4b5f-b72e-e41e6c19aa90` | 1000000 | 1000000 | 0 | 0 | 76651 | 13046.14 | 705 | 44586 | 1675 | 13254 |
| 1m | 2 | full-conflict upsert | `cc93d290-ac53-4561-a1be-71688d911edb` | 1000000 | 1000000 | 0 | 0 | 68969 | 14499.27 | 701 | 45069 | 1686 | 3508 |
| 1m | 3 | full-conflict upsert | `c1149195-64f3-43d0-b11d-0dbd861cfcf2` | 1000000 | 1000000 | 0 | 0 | 69108 | 14470.1 | 713 | 45221 | 1680 | 3466 |

## Summary

| Dataset | Median duration ms | p95 duration ms | Median rows/sec | p95 rows/sec | Median steady-state rows/sec |
|---|---:|---:|---:|---:|---:|
| 100k | 6771.0 | 7303.8 | 14768.87 | 15059.741 | 14930.465 |
| 500k | 33452.0 | 36267.2 | 14946.79 | 15079.1709 | 15020.335 |
| 1m | 69108.0 | 75896.7 | 14470.1 | 14496.353 | 14484.685 |

## Dominant Phase

The benchmark was dominated by transform time; median phase timings were CSV parse 354.0 ms, transform 22444.0 ms, COPY 838.0 ms, and UPSERT merge 1628.0 ms.

## Reproduction Commands

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d
until [ "$(docker inspect -f '{{.State.Health.Status}}' market-data-postgres)" = healthy ]; do sleep 2; done
market-data-pipeline init-db --config configs/pipeline.yml
python scripts/benchmark_load.py --rows 100000 --output data/raw/benchmark_100k.csv
python scripts/benchmark_load.py --rows 500000 --output data/raw/benchmark_500k.csv
python scripts/benchmark_load.py --rows 1000000 --output data/raw/benchmark_1m.csv
python scripts/run_benchmark.py --reset-db
```

For each dataset, run 1 is a cold insert and runs 2 and 3 are full-conflict UPSERT re-runs against the same natural keys.
