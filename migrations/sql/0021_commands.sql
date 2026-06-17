-- =====================================================================
-- 0021_commands.sql  (P1#12 — durable commands)
-- Replace the fire-and-forget Redis list with a durable, replay-able command
-- table: a flatten/kill/close survives an engine crash and is re-run on restart.
-- =====================================================================

CREATE TABLE IF NOT EXISTS commands (
    id              BIGSERIAL PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    type            TEXT NOT NULL,
    payload         JSONB,
    status          TEXT NOT NULL DEFAULT 'CREATED',   -- CREATED|CLAIMED|EXECUTING|SUCCEEDED|FAILED|RETRYING|DEAD_LETTER
    claimed_by      TEXT,
    attempts        INT NOT NULL DEFAULT 0,
    last_error      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS commands_pending ON commands (status, created_at);
