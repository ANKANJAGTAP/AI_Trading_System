-- Instruments master (Kite dump): tradingsymbol <-> token <-> lot <-> expiry <-> strike.
CREATE TABLE IF NOT EXISTS instruments (
    instrument_token  BIGINT PRIMARY KEY,
    exchange_token    BIGINT,
    tradingsymbol     TEXT NOT NULL,
    name              TEXT,
    last_price        NUMERIC(18, 4),
    expiry            DATE,
    strike            NUMERIC(18, 4),
    tick_size         NUMERIC(18, 4),
    lot_size          INTEGER,
    instrument_type   TEXT,            -- EQ / FUT / CE / PE
    segment           TEXT,
    exchange          TEXT,            -- NSE / BSE / NFO / MCX / ...
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_instruments_symbol   ON instruments (tradingsymbol);
CREATE INDEX IF NOT EXISTS idx_instruments_exchange ON instruments (exchange);
CREATE INDEX IF NOT EXISTS idx_instruments_expiry   ON instruments (expiry);
CREATE INDEX IF NOT EXISTS idx_instruments_name     ON instruments (name);
