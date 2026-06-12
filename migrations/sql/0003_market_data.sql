-- Time-series market data: ticks and aggregated candles (TimescaleDB hypertables).

-- Raw ticks (optional archive). No unique constraint: multiple ticks may share a
-- timestamp; we partition by time and index by (token, ts).
CREATE TABLE IF NOT EXISTS ticks (
    ts                TIMESTAMPTZ NOT NULL,
    instrument_token  BIGINT NOT NULL,
    last_price        NUMERIC(18, 4),
    last_quantity     BIGINT,
    average_price     NUMERIC(18, 4),
    volume            BIGINT,
    buy_quantity      BIGINT,
    sell_quantity     BIGINT,
    oi                BIGINT,
    bid               NUMERIC(18, 4),
    ask               NUMERIC(18, 4),
    raw               JSONB
);
SELECT create_hypertable('ticks', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_ticks_token_ts ON ticks (instrument_token, ts DESC);

-- Closed candles, client-side aggregated. OI attached at close for F&O/MCX.
-- Row order mirrors the standard payload: ts, open, high, low, close, volume, oi.
CREATE TABLE IF NOT EXISTS candles (
    ts                TIMESTAMPTZ NOT NULL,
    instrument_token  BIGINT NOT NULL,
    interval          TEXT NOT NULL,           -- 1m / 3m / 5m / 15m / day
    open              NUMERIC(18, 4) NOT NULL,
    high              NUMERIC(18, 4) NOT NULL,
    low               NUMERIC(18, 4) NOT NULL,
    close             NUMERIC(18, 4) NOT NULL,
    volume            BIGINT NOT NULL DEFAULT 0,
    oi                BIGINT,
    PRIMARY KEY (instrument_token, interval, ts)
);
SELECT create_hypertable('candles', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_candles_token_interval_ts
    ON candles (instrument_token, interval, ts DESC);
