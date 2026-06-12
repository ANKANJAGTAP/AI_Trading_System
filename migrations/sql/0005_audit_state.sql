-- Audit log (immutable), daily PnL, and runtime config state.

-- Immutable, append-only audit trail. Hypertable for volume; a trigger blocks
-- UPDATE/DELETE so the trail cannot be rewritten.
CREATE TABLE IF NOT EXISTS audit_log (
    id             BIGSERIAL,
    ts             TIMESTAMPTZ NOT NULL DEFAULT now(),
    correlation_id UUID,
    event_type     TEXT NOT NULL,
    component      TEXT,
    message        TEXT,
    payload        JSONB,
    PRIMARY KEY (id, ts)
);
SELECT create_hypertable('audit_log', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_audit_corr  ON audit_log (correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log (event_type, ts DESC);

CREATE OR REPLACE FUNCTION ats_prevent_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is immutable (% blocked)', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log;
CREATE TRIGGER audit_log_immutable
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION ats_prevent_mutation();

-- Daily PnL vs kill-switch line, per mode.
CREATE TABLE IF NOT EXISTS daily_pnl (
    trade_date          DATE NOT NULL,
    mode                TEXT NOT NULL,        -- simulated_fill / live
    starting_capital    NUMERIC(18, 4),
    realized_pnl        NUMERIC(18, 4) DEFAULT 0,
    unrealized_pnl      NUMERIC(18, 4) DEFAULT 0,
    fees                NUMERIC(18, 4) DEFAULT 0,
    max_loss_limit      NUMERIC(18, 4),       -- daily_max_loss_pct * starting_capital
    kill_switch_tripped BOOLEAN DEFAULT FALSE,
    num_trades          INTEGER DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (trade_date, mode)
);

-- Runtime-mutable operator state (mode, pause, kill-switch, sleeve toggles, ...).
CREATE TABLE IF NOT EXISTS config_state (
    key        TEXT PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by TEXT
);
INSERT INTO config_state (key, value, updated_by) VALUES
    ('execution_mode',     '"simulated_fill"', 'system'),
    ('engine_paused',      'false',            'system'),
    ('kill_switch_active', 'false',            'system')
ON CONFLICT (key) DO NOTHING;
