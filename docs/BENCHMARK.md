# Benchmark Results

Generated at: `2026-08-31T06:09:35.496826+00:00`

## Environment

| Field | Value |
|---|---|
| CPU | AMD EPYC 7763 64-Core Processor |
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
| 100k | 1 | cold insert | `a83b74f3-d9d1-4592-a799-380c22489d7a` | 100000 | 100000 | 0 | 0 | 4522 | 22114.11 | 80 | 610 | 181 | 2504 |
| 100k | 2 | full-conflict upsert | `21776cd4-652d-4691-94ad-62ae4cb7bdd7` | 100000 | 100000 | 0 | 0 | 4848 | 20627.06 | 79 | 598 | 182 | 2839 |
| 100k | 3 | full-conflict upsert | `97e0dd7f-9297-4d29-bc7f-067b2ea99ad9` | 100000 | 100000 | 0 | 0 | 4832 | 20695.36 | 82 | 591 | 185 | 2818 |
| 500k | 1 | cold insert | `99074089-701f-4e5e-9b39-ac2e3254116b` | 500000 | 500000 | 0 | 0 | 22644 | 22080.9 | 374 | 2934 | 927 | 12846 |
| 500k | 2 | full-conflict upsert | `0b561ace-d74a-458c-bd54-5ebf2bbdfec7` | 500000 | 500000 | 0 | 0 | 23944 | 20882.06 | 373 | 2927 | 896 | 14144 |
| 500k | 3 | full-conflict upsert | `1366198b-98c1-48ed-bc1f-24af5e8f23b2` | 500000 | 500000 | 0 | 0 | 24076 | 20767.57 | 369 | 2985 | 902 | 14201 |
| 1m | 1 | cold insert | `6f3f800a-32bc-4f88-9408-ec92cf55ca51` | 1000000 | 1000000 | 0 | 0 | 47452 | 21073.93 | 738 | 5881 | 1796 | 27736 |
| 1m | 2 | full-conflict upsert | `b97c9c0f-0d62-48f3-908a-cb3b38d6facc` | 1000000 | 1000000 | 0 | 0 | 42775 | 23378.14 | 725 | 5952 | 1803 | 23324 |
| 1m | 3 | full-conflict upsert | `ed630a82-f9ac-49dd-ac88-ad900d1b41cf` | 1000000 | 1000000 | 0 | 0 | 42705 | 23416.46 | 714 | 5930 | 1833 | 23143 |

## Summary

| Dataset | Median duration ms | p95 duration ms | Median rows/sec | p95 rows/sec | Median steady-state rows/sec |
|---|---:|---:|---:|---:|---:|
| 100k | 4832.0 | 4846.4 | 20695.36 | 21972.235 | 20661.21 |
| 500k | 23944.0 | 24062.8 | 20882.06 | 21961.016 | 20824.815 |
| 1m | 42775.0 | 46984.3 | 23378.14 | 23412.628 | 23397.3 |

## Dominant Phase

The benchmark was dominated by UPSERT merge time; median phase timings were CSV parse 373.0 ms, transform 2934.0 ms, COPY 902.0 ms, and UPSERT merge 14144.0 ms.

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
