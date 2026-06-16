-- =====================================================================
-- 0017_position_events.sql  (P0#4 — broker-fill truth for live close)
-- Append-only lifecycle log per position: entry, full/partial close, and
-- close-pending events, each carrying the broker fill truth (order id, status,
-- filled qty, avg price, pending qty, fees). Immutable like audit_log.
-- =====================================================================

CREATE TABLE IF NOT EXISTS position_events (
    id              BIGSERIAL PRIMARY KEY,
    position_id     BIGINT,
    correlation_id  UUID,
    event_type      TEXT NOT NULL,         -- entry | full_close | partial_close | close_pending
    broker_order_id TEXT,
    status          TEXT,                  -- COMPLETE | PARTIAL | REJECTED | UNKNOWN
    filled_qty      BIGINT,
    avg_price       NUMERIC,
    pending_qty     BIGINT,
    fees            JSONB,
    detail          JSONB,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS position_events_pos ON position_events (position_id, ts);

-- Append-only: block UPDATE/DELETE (same pattern as audit_log).
CREATE OR REPLACE FUNCTION position_events_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'position_events is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS position_events_no_mod ON position_events;
CREATE TRIGGER position_events_no_mod
    BEFORE UPDATE OR DELETE ON position_events
    FOR EACH ROW EXECUTE FUNCTION position_events_immutable();
