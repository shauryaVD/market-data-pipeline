from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_data_pipeline.config import load_config
from market_data_pipeline.pipeline import initialize_database, run_from_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="market-data-pipeline",
        description="Batch ETL for loading market price CSV files into PostgreSQL.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate-config", help="validate YAML config")
    validate_parser.add_argument("--config", default="configs/pipeline.yml")

    init_parser = subparsers.add_parser("init-db", help="apply PostgreSQL schema")
    init_parser.add_argument("--config", default="configs/pipeline.yml")

    run_parser = subparsers.add_parser("run", help="run one or more configured sources")
    run_parser.add_argument("--config", default="configs/pipeline.yml")
    run_parser.add_argument("--source", help="optional source name from the YAML config")

    args = parser.parse_args(argv)

    if args.command == "validate-config":
        config = load_config(Path(args.config))
        print(
            json.dumps(
                {
                    "status": "ok",
                    "sources": [source.name for source in config.sources],
                    "schema_path": str(config.database.schema_path),
                },
                indent=2,
            )
        )
        return 0

    if args.command == "init-db":
        initialize_database(Path(args.config))
        print(json.dumps({"status": "ok", "action": "init-db"}))
        return 0

    if args.command == "run":
        results = run_from_config(Path(args.config), args.source)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "runs": [
                        {
                            "run_id": result.run_id,
                            "source_name": result.source_name,
                            "rows_read": result.rows_read,
                            "rows_valid": result.rows_valid,
                            "rows_loaded": result.rows_loaded,
                            "rows_rejected": result.rows_rejected,
                            "duplicates_dropped": result.duplicates_dropped,
                            "duration_ms": result.duration_ms,
                            "throughput_rows_per_sec": result.throughput_rows_per_sec,
                            "rejection_path": str(result.rejection_path)
                            if result.rejection_path
                            else None,
                        }
                        for result in results
                    ],
                },
                indent=2,
            )
        )
        return 0

    parser.error(f"unsupported command {args.command}")
    return 2
