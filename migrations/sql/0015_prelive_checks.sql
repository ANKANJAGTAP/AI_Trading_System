-- =====================================================================
-- 0015_prelive_checks.sql  (P0#2 — real pre-live checks)
-- Persist each pre-live verification run + its per-check results with evidence,
-- so a go-live attempt leaves an auditable record of what was actually verified.
-- =====================================================================

CREATE TABLE IF NOT EXISTS prelive_check_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    operator        TEXT,
    overall_status  TEXT NOT NULL          -- pass | fail
);

CREATE TABLE IF NOT EXISTS prelive_check_results (
    id        BIGSERIAL PRIMARY KEY,
    run_id    BIGINT NOT NULL REFERENCES prelive_check_runs(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    status    TEXT NOT NULL,               -- pass | warn | fail
    detail    TEXT,
    evidence  JSONB,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS prelive_results_run ON prelive_check_results (run_id);
