-- =====================================================================
-- 0018_brackets.sql  (P0#7 — harden GTT/OCO + stop handling)
-- A queryable registry of live brackets (GTT id + state + triggers) so a
-- reconciler can find and cancel orphaned GTTs after a position closes, and so a
-- close can re-query before sending a market exit (no duplicate exit).
-- =====================================================================

CREATE TABLE IF NOT EXISTS brackets (
    id                 BIGSERIAL PRIMARY KEY,
    position_id        BIGINT,
    correlation_id     UUID,
    gtt_id             TEXT,
    state              TEXT NOT NULL DEFAULT 'BRACKET_ACTIVE',
    stop_order_type    TEXT,
    lower_trigger      NUMERIC,
    upper_trigger      NUMERIC,
    last_broker_status TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS brackets_active ON brackets (state);
CREATE INDEX IF NOT EXISTS brackets_pos ON brackets (position_id);
