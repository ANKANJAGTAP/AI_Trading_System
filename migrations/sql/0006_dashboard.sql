-- Phase 6b: dashboard (frontend_v2) data-surface additions.

-- Max adverse / favorable excursion, tracked live by the fast loop on each tick.
ALTER TABLE positions ADD COLUMN IF NOT EXISTS mae NUMERIC(18, 4) DEFAULT 0;  -- worst unrealized (<= 0)
ALTER TABLE positions ADD COLUMN IF NOT EXISTS mfe NUMERIC(18, 4) DEFAULT 0;  -- best unrealized  (>= 0)

-- Saved Workspace layouts (operator-configurable multi-pane terminal).
CREATE TABLE IF NOT EXISTS dashboard_layouts (
    name       TEXT PRIMARY KEY,
    layout     JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
