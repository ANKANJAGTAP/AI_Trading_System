-- Daily operations journal (black-box recorder). One row per trading day with the
-- full markdown journal: trades, anomalies (bug signatures like stop-overruns),
-- risk events, ML learning status. Survives container rebuilds and is included in
-- the nightly pg_dump backups — the raw material for every periodic system review.
CREATE TABLE IF NOT EXISTS daily_journal (
    day        DATE PRIMARY KEY,
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
