from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from market_data_pipeline.db import (
    apply_schema,
    connect,
    load_market_prices,
    recompute_adjusted_close,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is required for PostgreSQL integration tests",
)


@pytest.fixture()
def conn():
    connection = connect(os.environ["DATABASE_URL"])
    apply_schema(connection, Path("db/schema.sql"))
    with connection.cursor() as cursor:
        cursor.execute(
            "TRUNCATE TABLE market_prices, corporate_actions, pipeline_runs RESTART IDENTITY"
        )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def test_point_in_time_correction_preserves_prior_belief(conn):
    first_load_time = datetime(2026, 4, 2, 12, tzinfo=UTC)
    correction_time = datetime(2026, 4, 3, 12, tzinfo=UTC)
    price_ts = pd.Timestamp("2026-04-01T13:30:00Z")

    load_market_prices(
        conn,
        _price_rows(close_price=Decimal("100.000000"), price_ts=price_ts),
        valid_from=first_load_time,
    )
    load_market_prices(
        conn,
        _price_rows(close_price=Decimal("101.250000"), price_ts=price_ts),
        valid_from=correction_time,
    )

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT close_price
            FROM market_price_as_of(%s, %s, %s, %s)
            """,
            ("integration_feed", "AAPL", price_ts.to_pydatetime(), first_load_time),
        )
        prior_belief = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT close_price
            FROM market_price_as_of(%s, %s, %s, %s)
            """,
            ("integration_feed", "AAPL", price_ts.to_pydatetime(), correction_time),
        )
        corrected_belief = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*), COUNT(*) FILTER (WHERE valid_to IS NULL)
            FROM market_prices
            WHERE source_name = 'integration_feed'
            """
        )
        total_versions, active_versions = cursor.fetchone()

    assert prior_belief == Decimal("100.000000")
    assert corrected_belief == Decimal("101.250000")
    assert total_versions == 2
    assert active_versions == 1


def test_stock_split_recomputes_adjusted_close_across_history(conn):
    load_market_prices(
        conn,
        pd.concat(
            [
                _price_rows(
                    close_price=Decimal("100.000000"),
                    price_ts=pd.Timestamp("2026-04-01T13:30:00Z"),
                ),
                _price_rows(
                    close_price=Decimal("110.000000"),
                    price_ts=pd.Timestamp("2026-04-04T13:30:00Z"),
                ),
            ],
            ignore_index=True,
        ),
        valid_from=datetime(2026, 4, 5, 12, tzinfo=UTC),
    )

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO corporate_actions (
                source_name,
                symbol,
                action_date,
                action_type,
                split_ratio
            )
            VALUES ('integration_feed', 'AAPL', '2026-04-03', 'split', 2)
            """
        )
    conn.commit()

    rows_updated = recompute_adjusted_close(conn, "integration_feed", "AAPL")

    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT price_ts::DATE, close_price, adjusted_close
            FROM market_prices
            WHERE source_name = 'integration_feed'
                AND symbol = 'AAPL'
            ORDER BY price_ts
            """
        )
        rows = cursor.fetchall()

    assert rows_updated == 2
    assert rows[0][1:] == (Decimal("100.000000"), Decimal("50.000000"))
    assert rows[1][1:] == (Decimal("110.000000"), Decimal("110.000000"))


def test_load_reconciliation_matches_source_rows_by_symbol(conn):
    metrics = load_market_prices(
        conn,
        pd.concat(
            [
                _price_rows(
                    symbol="AAPL",
                    close_price=Decimal("100.000000"),
                    price_ts=pd.Timestamp("2026-04-01T13:30:00Z"),
                ),
                _price_rows(
                    symbol="MSFT",
                    close_price=Decimal("200.000000"),
                    price_ts=pd.Timestamp("2026-04-01T13:30:00Z"),
                ),
            ],
            ignore_index=True,
        ),
        valid_from=datetime(2026, 4, 2, 12, tzinfo=UTC),
    )

    assert metrics.reconciliation_status == "passed"
    assert metrics.reconciliation["source_total_rows"] == 2
    assert metrics.reconciliation["landed_total_rows"] == 2
    assert metrics.reconciliation["per_symbol"]["AAPL"]["matched"] is True
    assert metrics.reconciliation["per_symbol"]["MSFT"]["matched"] is True


def _price_rows(
    *,
    symbol: str = "AAPL",
    close_price: Decimal,
    price_ts: pd.Timestamp,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "source_name": "integration_feed",
                "symbol": symbol,
                "price_ts": price_ts,
                "open_price": close_price,
                "high_price": close_price,
                "low_price": close_price,
                "close_price": close_price,
                "volume": 1000,
                "adjusted_close": close_price,
                "currency": "USD",
            }
        ]
    )
