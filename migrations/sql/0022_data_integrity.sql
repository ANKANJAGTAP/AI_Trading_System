-- P2 #15 + #18: data-integrity constraints + tamper-evident audit digest.
--
-- All CHECK constraints are added NOT VALID: Postgres enforces them on every new
-- INSERT/UPDATE but does NOT scan or lock existing rows, so this migration cannot
-- fail on legacy data and cannot block the running engine. The predicates match
-- exactly what the app writes today (mode is only simulated_fill|live; side is
-- BUY|SELL; quantities/prices are non-negative), so no live write is rejected.

-- ---- #15 orders ----
ALTER TABLE orders ADD CONSTRAINT ck_orders_qty
    CHECK (quantity IS NULL OR quantity >= 0) NOT VALID;
ALTER TABLE orders ADD CONSTRAINT ck_orders_filled
    CHECK (filled_quantity IS NULL OR filled_quantity >= 0) NOT VALID;
ALTER TABLE orders ADD CONSTRAINT ck_orders_price
    CHECK (price IS NULL OR price >= 0) NOT VALID;
ALTER TABLE orders ADD CONSTRAINT ck_orders_mode
    CHECK (mode IN ('simulated_fill', 'live')) NOT VALID;
ALTER TABLE orders ADD CONSTRAINT ck_orders_side
    CHECK (side IS NULL OR side IN ('BUY', 'SELL')) NOT VALID;

-- ---- #15 fills ----
ALTER TABLE fills ADD CONSTRAINT ck_fills_qty
    CHECK (quantity IS NULL OR quantity >= 0) NOT VALID;
ALTER TABLE fills ADD CONSTRAINT ck_fills_price
    CHECK (price IS NULL OR price >= 0) NOT VALID;
ALTER TABLE fills ADD CONSTRAINT ck_fills_side
    CHECK (side IS NULL OR side IN ('BUY', 'SELL')) NOT VALID;

-- ---- #15 positions ----
ALTER TABLE positions ADD CONSTRAINT ck_positions_mode
    CHECK (mode IN ('simulated_fill', 'live')) NOT VALID;
ALTER TABLE positions ADD CONSTRAINT ck_positions_side
    CHECK (side IS NULL OR side IN ('BUY', 'SELL')) NOT VALID;

-- ---- #15 signals ----
ALTER TABLE signals ADD CONSTRAINT ck_signals_side
    CHECK (side IS NULL OR side IN ('BUY', 'SELL')) NOT VALID;
ALTER TABLE signals ADD CONSTRAINT ck_signals_confidence
    CHECK (confidence IS NULL OR confidence >= 0) NOT VALID;

-- ---- #18 tamper-evident audit digest ----
-- One signed digest per trading day: a sha256 hash-chain over that day's
-- audit_log rows, itself chained to the prior day's digest. Tamper-evidence
-- without adding any latency to the audit write path (computed once daily).
CREATE TABLE IF NOT EXISTS audit_digests (
    trade_date  DATE PRIMARY KEY,
    row_count   BIGINT NOT NULL,
    digest      TEXT NOT NULL,
    prev_digest TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
