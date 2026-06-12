-- Trading domain: signals, gate trail, orders, fills, positions.
-- correlation_id ties a signal -> its gates -> orders -> fills -> position so any
-- trade can be fully reconstructed (spec §9 audit requirement).

CREATE TABLE IF NOT EXISTS signals (
    id               BIGSERIAL PRIMARY KEY,
    correlation_id   UUID NOT NULL DEFAULT gen_random_uuid(),
    ts               TIMESTAMPTZ NOT NULL DEFAULT now(),
    sleeve           TEXT NOT NULL,
    instrument_token BIGINT,
    tradingsymbol    TEXT,
    setup            TEXT,
    side             TEXT,                    -- BUY / SELL
    entry_price      NUMERIC(18, 4),
    stop_price       NUMERIC(18, 4),
    target_price     NUMERIC(18, 4),
    confidence       NUMERIC(6, 4),           -- 0..1
    decision         TEXT,                    -- PASS / REJECT
    reason           TEXT,
    raw              JSONB
);
CREATE INDEX IF NOT EXISTS idx_signals_corr ON signals (correlation_id);
CREATE INDEX IF NOT EXISTS idx_signals_ts   ON signals (ts DESC);

CREATE TABLE IF NOT EXISTS gate_results (
    id             BIGSERIAL PRIMARY KEY,
    signal_id      BIGINT REFERENCES signals (id) ON DELETE CASCADE,
    correlation_id UUID,
    ts             TIMESTAMPTZ NOT NULL DEFAULT now(),
    gate_name      TEXT NOT NULL,
    passed         BOOLEAN,
    score          NUMERIC(6, 4),             -- 0..1
    detail         JSONB
);
CREATE INDEX IF NOT EXISTS idx_gate_signal ON gate_results (signal_id);

CREATE TABLE IF NOT EXISTS orders (
    id               BIGSERIAL PRIMARY KEY,
    correlation_id   UUID,
    signal_id        BIGINT REFERENCES signals (id),
    broker_order_id  TEXT,
    mode             TEXT NOT NULL,           -- simulated_fill / live
    sleeve           TEXT,
    instrument_token BIGINT,
    tradingsymbol    TEXT,
    side             TEXT,
    order_type       TEXT,
    product          TEXT,                    -- MIS / CNC / NRML
    quantity         BIGINT,
    filled_quantity  BIGINT DEFAULT 0,
    price            NUMERIC(18, 4),
    trigger_price    NUMERIC(18, 4),
    status           TEXT,                    -- PENDING/OPEN/COMPLETE/PARTIAL/REJECTED/CANCELLED
    reason           TEXT,
    placed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw              JSONB
);
CREATE INDEX IF NOT EXISTS idx_orders_corr   ON orders (correlation_id);
CREATE INDEX IF NOT EXISTS idx_orders_broker ON orders (broker_order_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status);

CREATE TABLE IF NOT EXISTS fills (
    id               BIGSERIAL PRIMARY KEY,
    order_id         BIGINT REFERENCES orders (id),
    correlation_id   UUID,
    broker_order_id  TEXT,
    instrument_token BIGINT,
    tradingsymbol    TEXT,
    side             TEXT,
    quantity         BIGINT,
    price            NUMERIC(18, 4),
    fees             JSONB,                   -- itemised cost model breakdown
    mode             TEXT,
    ts               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fills_order ON fills (order_id);

CREATE TABLE IF NOT EXISTS positions (
    id               BIGSERIAL PRIMARY KEY,
    correlation_id   UUID,
    mode             TEXT NOT NULL,
    sleeve           TEXT,
    instrument_token BIGINT,
    tradingsymbol    TEXT,
    side             TEXT,
    quantity         BIGINT,
    average_price    NUMERIC(18, 4),
    entry_price      NUMERIC(18, 4),
    stop_price       NUMERIC(18, 4),
    target_price     NUMERIC(18, 4),
    r_rupees         NUMERIC(18, 4),          -- R risked on this position (₹)
    status           TEXT NOT NULL DEFAULT 'open',  -- open / closed / flagged
    realized_pnl     NUMERIC(18, 4) DEFAULT 0,
    unrealized_pnl   NUMERIC(18, 4) DEFAULT 0,
    opened_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at        TIMESTAMPTZ,
    raw              JSONB
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions (status);
CREATE INDEX IF NOT EXISTS idx_positions_token  ON positions (instrument_token);
