-- What did we believe the close was as of a given knowledge-time timestamp?
--
-- Effective time is price_ts: when the market event happened.
-- Knowledge time is valid_from/valid_to: when the pipeline believed a version
-- of that market event was current.

SELECT
    source_name,
    symbol,
    price_ts,
    close_price,
    adjusted_close,
    valid_from,
    valid_to,
    ingested_at
FROM market_price_as_of(
    'benchmark_100k',
    'AAPL',
    '2026-04-01 13:30:00+00'::timestamptz,
    '2026-04-02 00:00:00+00'::timestamptz
);
