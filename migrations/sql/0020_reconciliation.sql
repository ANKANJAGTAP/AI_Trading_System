-- =====================================================================
-- 0020_reconciliation.sql  (P1#11 — first-class broker reconciliation)
-- Persist each reconciliation run's severity + findings so book/broker drift is
-- auditable over time.
-- =====================================================================

CREATE TABLE IF NOT EXISTS reconciliation_snapshots (
    id        BIGSERIAL PRIMARY KEY,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    severity  TEXT NOT NULL,         -- info | trading_blocked | flatten_required | manual
    findings  JSONB
);
CREATE INDEX IF NOT EXISTS reconciliation_ts ON reconciliation_snapshots (ts DESC);
