#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import statistics
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2

BENCHMARKS = [
    ("100k", "benchmark_100k", 100_000, Path("data/raw/benchmark_100k.csv")),
    ("500k", "benchmark_500k", 500_000, Path("data/raw/benchmark_500k.csv")),
    ("1m", "benchmark_1m", 1_000_000, Path("data/raw/benchmark_1m.csv")),
]

RESULT_COLUMNS = [
    "run_id",
    "rows_read",
    "rows_loaded",
    "rows_rejected",
    "duplicates_dropped",
    "duration_ms",
    "throughput_rows_per_sec",
    "csv_parse_ms",
    "transform_ms",
    "copy_ms",
    "upsert_ms",
]


@dataclass(frozen=True)
class BenchmarkRun:
    size_label: str
    source_name: str
    row_count: int
    run_number: int
    mode: str
    run_id: str
    rows_read: int
    rows_loaded: int
    rows_rejected: int
    duplicates_dropped: int
    duration_ms: int
    throughput_rows_per_sec: float
    csv_parse_ms: int
    transform_ms: int
    copy_ms: int
    upsert_ms: int

    @classmethod
    def from_db_row(
        cls,
        *,
        size_label: str,
        source_name: str,
        row_count: int,
        run_number: int,
        row: dict[str, Any],
    ) -> BenchmarkRun:
        return cls(
            size_label=size_label,
            source_name=source_name,
            row_count=row_count,
            run_number=run_number,
            mode="cold insert" if run_number == 1 else "full-conflict upsert",
            run_id=str(row["run_id"]),
            rows_read=int(row["rows_read"]),
            rows_loaded=int(row["rows_loaded"]),
            rows_rejected=int(row["rows_rejected"]),
            duplicates_dropped=int(row["duplicates_dropped"]),
            duration_ms=int(row["duration_ms"]),
            throughput_rows_per_sec=float(row["throughput_rows_per_sec"]),
            csv_parse_ms=int(row["csv_parse_ms"]),
            transform_ms=int(row["transform_ms"]),
            copy_ms=int(row["copy_ms"]),
            upsert_ms=int(row["upsert_ms"]),
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Docker/PostgreSQL throughput benchmarks and write BENCHMARK.md."
    )
    parser.add_argument("--config", default="configs/pipeline.yml")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--output-json", default="docs/benchmark-results.json")
    parser.add_argument("--output-md", default="docs/BENCHMARK.md")
    parser.add_argument("--reset-db", action="store_true")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL must be set or passed with --database-url")

    root = Path.cwd()
    generated_files = generate_datasets(root)
    row_widths = measure_row_widths(root, generated_files)

    if args.reset_db:
        reset_database(args.database_url)

    runs: list[BenchmarkRun] = []
    for size_label, source_name, row_count, _path in BENCHMARKS:
        for run_number in (1, 2, 3):
            run_id = run_pipeline(args.config, source_name)
            row = fetch_pipeline_run(args.database_url, run_id)
            runs.append(
                BenchmarkRun.from_db_row(
                    size_label=size_label,
                    source_name=source_name,
                    row_count=row_count,
                    run_number=run_number,
                    row=row,
                )
            )

    env = collect_environment(args.database_url)
    result_payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": env,
        "row_widths": row_widths,
        "runs": [run.__dict__ for run in runs],
        "summary": build_summary(runs),
        "dominant_phase": dominant_phase(runs),
    }

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result_payload, indent=2, sort_keys=True), encoding="utf-8")

    output_md = Path(args.output_md)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(result_payload), encoding="utf-8")

    print(json.dumps(result_payload["summary"], indent=2, sort_keys=True))
    return 0


def generate_datasets(root: Path) -> dict[str, Path]:
    generated: dict[str, Path] = {}
    for size_label, _source_name, row_count, path in BENCHMARKS:
        subprocess.run(
            [
                sys.executable,
                "scripts/benchmark_load.py",
                "--rows",
                str(row_count),
                "--output",
                str(path),
            ],
            cwd=root,
            check=True,
        )
        generated[size_label] = path
    return generated


def measure_row_widths(root: Path, generated_files: dict[str, Path]) -> dict[str, dict[str, Any]]:
    widths: dict[str, dict[str, Any]] = {}
    for size_label, path in generated_files.items():
        absolute = root / path
        with absolute.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
        content = absolute.read_bytes()
        first_newline = content.find(b"\n")
        data_bytes = len(content[first_newline + 1 :]) if first_newline >= 0 else 0
        row_count = next(item[2] for item in BENCHMARKS if item[0] == size_label)
        widths[size_label] = {
            "column_count": len(header),
            "average_bytes_per_row": truncate(data_bytes / row_count, 4),
            "file_bytes": len(content),
        }
    return widths


def reset_database(database_url: str) -> None:
    with psycopg2.connect(database_url) as conn, conn.cursor() as cursor:
        cursor.execute("TRUNCATE TABLE market_prices, pipeline_runs RESTART IDENTITY")


def run_pipeline(config_path: str, source_name: str) -> str:
    completed = subprocess.run(
        [
            "market-data-pipeline",
            "run",
            "--config",
            config_path,
            "--source",
            source_name,
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    output = json.loads(completed.stdout)
    return str(output["runs"][0]["run_id"])


def fetch_pipeline_run(database_url: str, run_id: str) -> dict[str, Any]:
    query = f"""
        SELECT {", ".join(RESULT_COLUMNS)}
        FROM pipeline_runs
        WHERE run_id = %s
    """
    with psycopg2.connect(database_url) as conn, conn.cursor() as cursor:
        cursor.execute(query, (run_id,))
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"pipeline_runs row not found for run_id={run_id}")
    return dict(zip(RESULT_COLUMNS, row, strict=True))


def collect_environment(database_url: str) -> dict[str, Any]:
    return {
        "cpu_model": cpu_model(),
        "core_count": os.cpu_count(),
        "ram": ram_total(),
        "os": platform.platform(),
        "docker_version": command_output(["docker", "--version"]),
        "docker_compose_version": command_output(["docker", "compose", "version"]),
        "postgres_version": postgres_version(database_url),
        "python_version": platform.python_version(),
        "pandas_version": pd.__version__,
        "psycopg2_version": psycopg2.__version__,
    }


def cpu_model() -> str:
    if Path("/proc/cpuinfo").exists():
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    if platform.system() == "Darwin":
        value = command_output(["sysctl", "-n", "machdep.cpu.brand_string"])
        if value != "unavailable":
            return value
    return platform.processor() or "unavailable"


def ram_total() -> str:
    if Path("/proc/meminfo").exists():
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                kb = int(line.split()[1])
                return f"{truncate(kb / 1024 / 1024, 2)} GiB"
    if platform.system() == "Darwin":
        value = command_output(["sysctl", "-n", "hw.memsize"])
        if value.isdigit():
            return f"{truncate(int(value) / 1024 / 1024 / 1024, 2)} GiB"
    return "unavailable"


def postgres_version(database_url: str) -> str:
    with psycopg2.connect(database_url) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT version()")
        return str(cursor.fetchone()[0])


def command_output(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=True, text=True, capture_output=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unavailable"
    return completed.stdout.strip()


def build_summary(runs: list[BenchmarkRun]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for size_label in [item[0] for item in BENCHMARKS]:
        size_runs = [run for run in runs if run.size_label == size_label]
        steady_runs = [run for run in size_runs if run.run_number in {2, 3}]
        summary[size_label] = {
            "median_duration_ms_all_runs": truncate(
                median(run.duration_ms for run in size_runs), 4
            ),
            "p95_duration_ms_all_runs": truncate(
                percentile((run.duration_ms for run in size_runs), 95), 4
            ),
            "median_rows_per_sec_all_runs": truncate(
                median(run.throughput_rows_per_sec for run in size_runs), 4
            ),
            "p95_rows_per_sec_all_runs": truncate(
                percentile((run.throughput_rows_per_sec for run in size_runs), 95), 4
            ),
            "median_steady_state_rows_per_sec": truncate(
                median(run.throughput_rows_per_sec for run in steady_runs), 4
            ),
        }
    return summary


def dominant_phase(runs: list[BenchmarkRun]) -> dict[str, Any]:
    phases = {
        "CSV parse": [run.csv_parse_ms for run in runs],
        "transform": [run.transform_ms for run in runs],
        "COPY": [run.copy_ms for run in runs],
        "UPSERT merge": [run.upsert_ms for run in runs],
    }
    phase_medians = {name: median(values) for name, values in phases.items()}
    dominant = max(phase_medians, key=phase_medians.get)
    return {
        "phase": dominant,
        "median_ms": truncate(phase_medians[dominant], 4),
        "phase_medians_ms": {name: truncate(value, 4) for name, value in phase_medians.items()},
    }


def median(values: Any) -> float:
    return float(statistics.median(list(values)))


def percentile(values: Any, percentile_value: int) -> float:
    sorted_values = sorted(float(value) for value in values)
    if not sorted_values:
        raise ValueError("cannot calculate percentile of empty values")
    rank = (percentile_value / 100) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * weight


def truncate(value: float, digits: int) -> float:
    factor = 10**digits
    return int(value * factor) / factor


def render_markdown(payload: dict[str, Any]) -> str:
    env = payload["environment"]
    row_widths = payload["row_widths"]
    runs = payload["runs"]
    summary = payload["summary"]
    dominant = payload["dominant_phase"]

    lines = [
        "# Benchmark Results",
        "",
        f"Generated at: `{payload['generated_at']}`",
        "",
        "## Environment",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| CPU | {env['cpu_model']} |",
        f"| Core count | {env['core_count']} |",
        f"| RAM | {env['ram']} |",
        f"| OS | {env['os']} |",
        f"| Docker | {env['docker_version']} |",
        f"| Docker Compose | {env['docker_compose_version']} |",
        f"| PostgreSQL | {env['postgres_version']} |",
        f"| Python | {env['python_version']} |",
        f"| pandas | {env['pandas_version']} |",
        f"| psycopg2 | {env['psycopg2_version']} |",
        "",
        "## Row Width",
        "",
        "Average bytes per row is measured from the generated CSV data bytes, excluding the header.",
        "",
        "| Dataset | Column count | Average bytes per row | File bytes |",
        "|---|---:|---:|---:|",
    ]
    for size_label in row_widths:
        width = row_widths[size_label]
        lines.append(
            f"| {size_label} | {width['column_count']} | "
            f"{width['average_bytes_per_row']} | {width['file_bytes']} |"
        )

    lines.extend(
        [
            "",
            "## Runs",
            "",
            (
                "| Dataset | Run | Mode | Run ID | Rows read | Rows loaded | Rows rejected | "
                "Duplicates dropped | Duration ms | Rows/sec | CSV parse ms | Transform ms | "
                "COPY ms | UPSERT ms |"
            ),
            "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for run in runs:
        lines.append(
            f"| {run['size_label']} | {run['run_number']} | {run['mode']} | `{run['run_id']}` | "
            f"{run['rows_read']} | {run['rows_loaded']} | {run['rows_rejected']} | "
            f"{run['duplicates_dropped']} | {run['duration_ms']} | "
            f"{run['throughput_rows_per_sec']} | {run['csv_parse_ms']} | "
            f"{run['transform_ms']} | {run['copy_ms']} | {run['upsert_ms']} |"
        )

    lines.extend(
        [
            "",
            "## Summary",
            "",
            (
                "| Dataset | Median duration ms | p95 duration ms | Median rows/sec | "
                "p95 rows/sec | Median steady-state rows/sec |"
            ),
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for size_label in summary:
        item = summary[size_label]
        lines.append(
            f"| {size_label} | {item['median_duration_ms_all_runs']} | "
            f"{item['p95_duration_ms_all_runs']} | {item['median_rows_per_sec_all_runs']} | "
            f"{item['p95_rows_per_sec_all_runs']} | "
            f"{item['median_steady_state_rows_per_sec']} |"
        )

    lines.extend(
        [
            "",
            "## Dominant Phase",
            "",
            (
                f"The benchmark was dominated by {dominant['phase']} time; median phase timings were "
                f"CSV parse {dominant['phase_medians_ms']['CSV parse']} ms, "
                f"transform {dominant['phase_medians_ms']['transform']} ms, "
                f"COPY {dominant['phase_medians_ms']['COPY']} ms, and "
                f"UPSERT merge {dominant['phase_medians_ms']['UPSERT merge']} ms."
            ),
            "",
            "## Reproduction Commands",
            "",
            "```bash",
            "python3 -m venv .venv",
            ". .venv/bin/activate",
            'pip install -e ".[dev]"',
            "docker compose up -d",
            "until [ \"$(docker inspect -f '{{.State.Health.Status}}' market-data-postgres)\" = healthy ]; do sleep 2; done",
            "market-data-pipeline init-db --config configs/pipeline.yml",
            "python scripts/benchmark_load.py --rows 100000 --output data/raw/benchmark_100k.csv",
            "python scripts/benchmark_load.py --rows 500000 --output data/raw/benchmark_500k.csv",
            "python scripts/benchmark_load.py --rows 1000000 --output data/raw/benchmark_1m.csv",
            "python scripts/run_benchmark.py --reset-db",
            "```",
            "",
            "For each dataset, run 1 is a cold insert and runs 2 and 3 are full-conflict UPSERT re-runs against the same natural keys.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
