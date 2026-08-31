CREATE TABLE IF NOT EXISTS market_prices (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    price_ts TIMESTAMPTZ NOT NULL,
    open_price NUMERIC(18, 6) NOT NULL,
    high_price NUMERIC(18, 6) NOT NULL,
    low_price NUMERIC(18, 6) NOT NULL,
    close_price NUMERIC(18, 6) NOT NULL,
    volume BIGINT NOT NULL,
    adjusted_close NUMERIC(18, 6),
    currency CHAR(3) NOT NULL DEFAULT 'USD',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT market_prices_valid_window CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT market_prices_positive_prices CHECK (
        open_price > 0
        AND high_price > 0
        AND low_price > 0
        AND close_price > 0
        AND (adjusted_close IS NULL OR adjusted_close > 0)
    ),
    CONSTRAINT market_prices_non_negative_volume CHECK (volume >= 0),
    CONSTRAINT market_prices_high_low_envelope CHECK (
        high_price >= open_price
        AND high_price >= close_price
        AND high_price >= low_price
        AND low_price <= open_price
        AND low_price <= close_price
        AND low_price <= high_price
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_market_prices_current
    ON market_prices (source_name, symbol, price_ts)
    WHERE valid_to IS NULL;

CREATE INDEX IF NOT EXISTS idx_market_prices_symbol_effective
    ON market_prices (symbol, price_ts DESC);

CREATE INDEX IF NOT EXISTS idx_market_prices_as_of
    ON market_prices (source_name, symbol, price_ts, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS corporate_actions (
    id BIGSERIAL PRIMARY KEY,
    source_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action_date DATE NOT NULL,
    action_type TEXT NOT NULL CHECK (action_type IN ('split', 'dividend')),
    split_ratio NUMERIC(18, 8),
    dividend_amount NUMERIC(18, 6),
    currency CHAR(3) NOT NULL DEFAULT 'USD',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT corporate_actions_split_ratio CHECK (
        action_type <> 'split' OR (split_ratio IS NOT NULL AND split_ratio > 0)
    ),
    CONSTRAINT corporate_actions_dividend_amount CHECK (
        action_type <> 'dividend' OR (dividend_amount IS NOT NULL AND dividend_amount >= 0)
    ),
    UNIQUE (source_name, symbol, action_date, action_type)
);

CREATE INDEX IF NOT EXISTS idx_corporate_actions_symbol_date
    ON corporate_actions (source_name, symbol, action_date);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL UNIQUE,
    source_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    duration_ms BIGINT,
    rows_read BIGINT NOT NULL DEFAULT 0,
    rows_valid BIGINT NOT NULL DEFAULT 0,
    rows_loaded BIGINT NOT NULL DEFAULT 0,
    rows_rejected BIGINT NOT NULL DEFAULT 0,
    duplicates_dropped BIGINT NOT NULL DEFAULT 0,
    throughput_rows_per_sec NUMERIC(18, 2) NOT NULL DEFAULT 0,
    error_rate NUMERIC(9, 6) NOT NULL DEFAULT 0,
    csv_parse_ms BIGINT NOT NULL DEFAULT 0,
    transform_ms BIGINT NOT NULL DEFAULT 0,
    copy_ms BIGINT NOT NULL DEFAULT 0,
    upsert_ms BIGINT NOT NULL DEFAULT 0,
    reconciliation_status TEXT NOT NULL DEFAULT 'not_run'
        CHECK (reconciliation_status IN ('not_run', 'passed', 'failed')),
    reconciliation JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    failure_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE pipeline_runs
    ADD COLUMN IF NOT EXISTS csv_parse_ms BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS transform_ms BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS copy_ms BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS upsert_ms BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reconciliation_status TEXT NOT NULL DEFAULT 'not_run',
    ADD COLUMN IF NOT EXISTS reconciliation JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started_at
    ON pipeline_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_source_status
    ON pipeline_runs (source_name, status);

CREATE OR REPLACE FUNCTION market_price_as_of(
    p_source_name TEXT,
    p_symbol TEXT,
    p_price_ts TIMESTAMPTZ,
    p_as_of TIMESTAMPTZ
)
RETURNS TABLE (
    source_name TEXT,
    symbol TEXT,
    price_ts TIMESTAMPTZ,
    open_price NUMERIC(18, 6),
    high_price NUMERIC(18, 6),
    low_price NUMERIC(18, 6),
    close_price NUMERIC(18, 6),
    volume BIGINT,
    adjusted_close NUMERIC(18, 6),
    currency CHAR(3),
    ingested_at TIMESTAMPTZ,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        mp.source_name,
        mp.symbol,
        mp.price_ts,
        mp.open_price,
        mp.high_price,
        mp.low_price,
        mp.close_price,
        mp.volume,
        mp.adjusted_close,
        mp.currency,
        mp.ingested_at,
        mp.valid_from,
        mp.valid_to
    FROM market_prices mp
    WHERE mp.source_name = p_source_name
        AND mp.symbol = UPPER(p_symbol)
        AND mp.price_ts = p_price_ts
        AND mp.valid_from <= p_as_of
        AND (mp.valid_to IS NULL OR mp.valid_to > p_as_of)
    ORDER BY mp.valid_from DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION prune_pipeline_runs(retention_days INTEGER)
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM pipeline_runs
    WHERE created_at < NOW() - make_interval(days => retention_days);

    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
