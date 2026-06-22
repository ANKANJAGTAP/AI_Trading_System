-- =====================================================================
-- 0023_meta_model_stage.sql  (§10 Phase 2 — model promotion ladder)
-- A meta-model is promoted dev -> shadow -> paper -> live as evidence
-- accumulates, separate from the single `active` flag. Safe-on-live: adds a
-- defaulted column (no table rewrite on PG 11+), no scan/lock of existing rows.
-- =====================================================================

ALTER TABLE meta_models ADD COLUMN IF NOT EXISTS stage TEXT NOT NULL DEFAULT 'dev';

CREATE INDEX IF NOT EXISTS idx_meta_models_stage ON meta_models (stage, created_at DESC);
