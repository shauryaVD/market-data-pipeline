#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate synthetic market prices for load testing."
    )
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--output", default="data/raw/benchmark_market_prices.csv")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    symbols = ["AAPL", "MSFT", "NVDA", "GOOGL", "TSLA", "AMZN", "META", "JPM", "V", "MA"]
    start = datetime(2026, 4, 1, 9, 30)  # noqa: DTZ001 - source CSV timestamps are local.

    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "symbol",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "adjusted_close",
                "currency",
            ]
        )
        for index in range(args.rows):
            symbol = symbols[index % len(symbols)]
            ts = start + timedelta(minutes=index // len(symbols))
            base = 100 + (index % 500) / 10
            open_price = round(base, 2)
            high_price = round(base + 1.25, 2)
            low_price = round(base - 0.85, 2)
            close_price = round(base + 0.35, 2)
            writer.writerow(
                [
                    symbol,
                    ts.strftime("%Y-%m-%d %H:%M:%S"),
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    100_000 + index,
                    close_price,
                    "USD",
                ]
            )

    print(f"wrote {args.rows} rows to {output}")
    print(
        "Point configs/pipeline.yml at this file, then run the pipeline and inspect pipeline_runs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
