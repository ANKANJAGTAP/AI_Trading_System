-- =====================================================================
-- 0013_dataplatform.sql
-- Curated point-in-time F&O data platform (Pillar 1) tables, created in the
-- SAME TimescaleDB the live engine uses so research/backtest/ML and the live
-- app share one data layer. dataplatform's OperationalStore writes `eod_fno`
-- here when TIMESCALE_DSN points at this database (else it falls back to a local
-- SQLite mirror for dev).
--
-- Mirrors dataplatform/storage/schema.sql, with ONE deliberate difference: the
-- app already owns an `iv_history` table (0009_iv_history.sql) with a different
-- shape, so we DO NOT recreate it here. dataplatform's OperationalStore only
-- writes `eod_fno`; the other tables are additive and currently unused by the
-- live path, so there is no behavioural overlap with existing app tables.
-- =====================================================================

-- timescaledb is already enabled by 0001_extensions.sql; harmless if re-run.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------- EOD F&O (bhavcopy / Kite-capture spine) ----------
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
CREATE INDEX IF NOT EXISTS eod_fno_underlying_date ON eod_fno (underlying, trade_date DESC);

-- ---------- intraday option snapshots (vendor / live capture) ----------
CREATE TABLE IF NOT EXISTS option_snapshot (
    ts TIMESTAMPTZ NOT NULL, underlying TEXT, expiry DATE, strike NUMERIC,
    opt_type TEXT, ltp NUMERIC, bid NUMERIC, ask NUMERIC,
    bid_qty INT, ask_qty INT, volume BIGINT, oi BIGINT,
    iv NUMERIC, delta NUMERIC, gamma NUMERIC, theta NUMERIC, vega NUMERIC,
    source TEXT
);
SELECT create_hypertable('option_snapshot', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS option_snapshot_underlying_ts ON option_snapshot (underlying, ts DESC);

-- ---------- 1-min candles (underlying / futures / per-option) ----------
CREATE TABLE IF NOT EXISTS candles_1m (
    ts TIMESTAMPTZ NOT NULL, symbol TEXT, underlying TEXT,
    o NUMERIC, h NUMERIC, l NUMERIC, c NUMERIC, volume BIGINT, oi BIGINT,
    source TEXT
);
SELECT create_hypertable('candles_1m', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS candles_1m_symbol_ts ON candles_1m (symbol, ts DESC);

-- ---------- effective-dated reference data (verified seed, Pillar 1) ----------
-- These mirror the in-code SEED_SPECS / SEED_EXPIRY_RULES so a DB-only consumer
-- (a dashboard, an external report) can read the same contract/expiry truth.
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
