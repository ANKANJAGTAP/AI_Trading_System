-- Performance + lifecycle: missing hot-path indexes, drop a redundant index, and
-- add TimescaleDB compression/retention so ticks/candles don't grow without bound.

-- Hot dashboard / engine queries that previously seq-scanned:
--   positions WHERE opened_at >= $ / closed_at >= $ (pnl, eod, snapshot)
--   positions WHERE correlation_id = $ (reconstruct, F&O meta)
--   signals  WHERE instrument_token = $ ORDER BY ts DESC (market scanner, chart)
CREATE INDEX IF NOT EXISTS idx_positions_opened ON positions (opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_positions_closed ON positions (closed_at DESC);
CREATE INDEX IF NOT EXISTS idx_positions_corr   ON positions (correlation_id);
CREATE INDEX IF NOT EXISTS idx_signals_token_ts ON signals (instrument_token, ts DESC);

-- Redundant: duplicates the candles PRIMARY KEY (instrument_token, interval, ts).
DROP INDEX IF EXISTS idx_candles_token_interval_ts;

-- Compression + retention. Wrapped so a non-TimescaleDB target or a permission/
-- version difference logs a NOTICE instead of bricking the whole migration run.
DO $$
BEGIN
    BEGIN
        ALTER TABLE candles SET (
            timescaledb.compress,
            timescaledb.compress_orderby = 'ts DESC',
            timescaledb.compress_segmentby = 'instrument_token, interval'
        );
        PERFORM add_compression_policy('candles', INTERVAL '14 days', if_not_exists => TRUE);
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'candles compression policy skipped: %', SQLERRM;
    END;

    BEGIN
        ALTER TABLE ticks SET (
            timescaledb.compress,
            timescaledb.compress_orderby = 'ts DESC',
            timescaledb.compress_segmentby = 'instrument_token'
        );
        PERFORM add_compression_policy('ticks', INTERVAL '7 days', if_not_exists => TRUE);
        -- Raw ticks are a bulky optional archive; drop chunks older than 30 days.
        PERFORM add_retention_policy('ticks', INTERVAL '30 days', if_not_exists => TRUE);
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'ticks compression/retention policy skipped: %', SQLERRM;
    END;

    BEGIN
        -- Keep the audit trail long (compliance) but bound it so disk can't fill.
        PERFORM add_retention_policy('audit_log', INTERVAL '730 days', if_not_exists => TRUE);
    EXCEPTION WHEN OTHERS THEN
        RAISE NOTICE 'audit_log retention policy skipped: %', SQLERRM;
    END;
END $$;
