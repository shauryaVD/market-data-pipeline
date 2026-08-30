-- Latest pipeline runs.
SELECT
    run_id,
    source_name,
    status,
    started_at,
    duration_ms,
    rows_read,
    rows_valid,
    rows_loaded,
    rows_rejected,
    duplicates_dropped,
    throughput_rows_per_sec,
    error_rate,
    error_message
FROM pipeline_runs
ORDER BY started_at DESC
LIMIT 20;

-- Daily throughput and data-quality trend.
SELECT
    date_trunc('day', started_at) AS run_day,
    source_name,
    COUNT(*) AS runs,
    SUM(rows_read) AS rows_read,
    SUM(rows_loaded) AS rows_loaded,
    SUM(rows_rejected) AS rows_rejected,
    ROUND(AVG(throughput_rows_per_sec), 2) AS avg_throughput_rows_per_sec,
    ROUND(AVG(error_rate), 6) AS avg_error_rate
FROM pipeline_runs
GROUP BY 1, 2
ORDER BY run_day DESC, source_name;

-- Most recent failed run with structured incident details.
SELECT
    run_id,
    source_name,
    started_at,
    error_message,
    failure_summary
FROM pipeline_runs
WHERE status = 'failed'
ORDER BY started_at DESC
LIMIT 1;
