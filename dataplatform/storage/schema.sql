-- =====================================================================
-- TimescaleDB schema for the operational (hot/warm) store.
-- Run against a Postgres+TimescaleDB instance:  psql "$TIMESCALE_DSN" -f schema.sql
-- The dev fallback (storage/timescale.py with no TIMESCALE_DSN) mirrors the
-- eod_fno table in SQLite so the pipeline runs without a database.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------- EOD F&O (bhavcopy-derived spine) ----------
CREATE TABLE IF NOT EXISTS eod_fno (
    trade_date  DATE        NOT NULL,
    underlying  TEXT        NOT NULL,
    exchange    TEXT        NOT NULL,
    instrument  TEXT        NOT NULL,   -- 'FUT' | 'OPT'
    opt_type    TEXT        NOT NULL,   -- 'CE' | 'PE' | ''
    expiry      DATE        NOT NULL,
    strike      NUMERIC     NOT NULL,
    open        NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC, settle NUMERIC,
    volume      BIGINT, oi BIGINT, oi_change BIGINT,
    source      TEXT,
    PRIMARY KEY (trade_date, underlying, instrument, opt_type, expiry, strike)
);
SELECT create_hypertable('eod_fno', 'trade_date', if_not_exists => TRUE);

-- ---------- intraday option snapshots (vendor / live capture) ----------
CREATE TABLE IF NOT EXISTS option_snapshot (
    ts TIMESTAMPTZ NOT NULL, underlying TEXT, expiry DATE, strike NUMERIC,
    opt_type TEXT, ltp NUMERIC, bid NUMERIC, ask NUMERIC,
    bid_qty INT, ask_qty INT, volume BIGINT, oi BIGINT,
    iv NUMERIC, delta NUMERIC, gamma NUMERIC, theta NUMERIC, vega NUMERIC,
    source TEXT
);
SELECT create_hypertable('option_snapshot', 'ts', if_not_exists => TRUE);

-- ---------- 1-min candles (underlying / futures / per-option) ----------
CREATE TABLE IF NOT EXISTS candles_1m (
    ts TIMESTAMPTZ NOT NULL, symbol TEXT, underlying TEXT,
    o NUMERIC, h NUMERIC, l NUMERIC, c NUMERIC, volume BIGINT, oi BIGINT,
    source TEXT
);
SELECT create_hypertable('candles_1m', 'ts', if_not_exists => TRUE);

-- ---------- IV history (per underlying/expiry) ----------
CREATE TABLE IF NOT EXISTS iv_history (
    ts TIMESTAMPTZ NOT NULL, underlying TEXT, expiry DATE,
    atm_iv NUMERIC, rr_25 NUMERIC, bf_25 NUMERIC, iv_rank NUMERIC, iv_pct NUMERIC
);
SELECT create_hypertable('iv_history', 'ts', if_not_exists => TRUE);

-- ---------- effective-dated reference data ----------
CREATE TABLE IF NOT EXISTS contract_spec (
    underlying TEXT, attribute TEXT, value TEXT,
    valid_from DATE, valid_to DATE, source TEXT, verify BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (underlying, attribute, valid_from)
);

CREATE TABLE IF NOT EXISTS expiry_calendar (
    underlying TEXT, expiry_date DATE, expiry_type TEXT, is_settlement BOOLEAN,
    PRIMARY KEY (underlying, expiry_date)
);

CREATE TABLE IF NOT EXISTS market_holidays (
    exchange TEXT, holiday_date DATE, segment TEXT DEFAULT 'FO',
    PRIMARY KEY (exchange, holiday_date, segment)
);

-- compression policy example (uncomment in prod):
-- ALTER TABLE eod_fno SET (timescaledb.compress, timescaledb.compress_segmentby = 'underlying');
-- SELECT add_compression_policy('eod_fno', INTERVAL '90 days');
