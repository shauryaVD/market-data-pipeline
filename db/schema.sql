CREATE TABLE IF NOT EXISTS market_prices (
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_name, symbol, price_ts),
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

CREATE INDEX IF NOT EXISTS idx_market_prices_symbol_ts
    ON market_prices (symbol, price_ts DESC);

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
    error_message TEXT,
    failure_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE pipeline_runs
    ADD COLUMN IF NOT EXISTS csv_parse_ms BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS transform_ms BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS copy_ms BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS upsert_ms BIGINT NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started_at
    ON pipeline_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_source_status
    ON pipeline_runs (source_name, status);

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
