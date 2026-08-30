from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from market_data_pipeline.config import load_config
from market_data_pipeline.transform import transform_market_data


def _source():
    return load_config("configs/pipeline.yml").sources[0]


def test_transform_converts_timezone_and_deduplicates_valid_rows():
    raw = pd.DataFrame(
        [
            {
                "symbol": "aapl",
                "timestamp": "2026-03-13 09:30:00",
                "open": "172.10",
                "high": "173.20",
                "low": "171.84",
                "close": "172.95",
                "volume": "1482200",
                "adjusted_close": "172.95",
                "currency": "usd",
            },
            {
                "symbol": "AAPL",
                "timestamp": "2026-03-13 09:30:00",
                "open": "172.10",
                "high": "173.20",
                "low": "171.84",
                "close": "172.95",
                "volume": "1482200",
                "adjusted_close": "172.95",
                "currency": "USD",
            },
        ]
    )

    result = transform_market_data(raw, _source(), now=datetime(2026, 3, 14, tzinfo=UTC))

    assert result.rows_read == 2
    assert result.rows_valid == 1
    assert result.rows_rejected == 0
    assert result.duplicates_dropped == 1
    row = result.valid_rows.iloc[0]
    assert row["symbol"] == "AAPL"
    assert row["currency"] == "USD"
    assert row["price_ts"].isoformat() == "2026-03-13T13:30:00+00:00"


def test_transform_rejects_type_and_business_rule_violations():
    raw = pd.DataFrame(
        [
            {
                "symbol": "MSFT",
                "timestamp": "bad-date",
                "open": "421.45",
                "high": "423.88",
                "low": "420.12",
                "close": "422.57",
                "volume": "862100",
                "adjusted_close": "422.57",
                "currency": "USD",
            },
            {
                "symbol": "NVDA",
                "timestamp": "2026-03-13 09:30:00",
                "open": "901.00",
                "high": "895.00",
                "low": "900.00",
                "close": "899.75",
                "volume": "-10",
                "adjusted_close": "899.75",
                "currency": "USD",
            },
        ]
    )

    result = transform_market_data(raw, _source(), now=datetime(2026, 3, 14, tzinfo=UTC))

    assert result.rows_valid == 0
    assert result.rows_rejected == 2
    reasons = " ".join(result.rejected_rows["rejection_reason"].tolist())
    assert "invalid_timestamp" in reasons
    assert "negative_volume" in reasons
    assert "invalid_high_low_envelope" in reasons


def test_transform_rejects_future_timestamp():
    raw = pd.DataFrame(
        [
            {
                "symbol": "TSLA",
                "timestamp": "2026-03-15 09:30:00",
                "open": "178.25",
                "high": "179.30",
                "low": "176.44",
                "close": "177.82",
                "volume": "1102400",
                "adjusted_close": "177.82",
                "currency": "USD",
            },
        ]
    )

    result = transform_market_data(raw, _source(), now=datetime(2026, 3, 14, tzinfo=UTC))

    assert result.rows_valid == 0
    assert result.rows_rejected == 1
    assert "future_timestamp" in result.rejected_rows.loc[0, "rejection_reason"]
