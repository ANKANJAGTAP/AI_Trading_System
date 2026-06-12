-- Meta-label model registry (Phase 4). Stores transparent logistic-regression
-- coefficients + standardization + metrics; one row may be flagged active.
CREATE TABLE IF NOT EXISTS meta_models (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    name        TEXT,
    features    TEXT[],
    params      JSONB,     -- {w, b, mu, sd}
    metrics     JSONB,     -- {n_samples, accuracy, base_rate}
    active      BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_meta_models_active ON meta_models (active, created_at DESC);
