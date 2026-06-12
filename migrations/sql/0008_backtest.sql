-- Backtest runs + their trades (research layer, Phase 1).
CREATE TABLE IF NOT EXISTS backtest_runs (
    id               BIGSERIAL PRIMARY KEY,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    sleeve           TEXT,
    symbols          TEXT[],
    from_dt          DATE,
    to_dt            DATE,
    params           JSONB,
    status           TEXT NOT NULL DEFAULT 'running',  -- running / done / error
    metrics          JSONB,
    error            TEXT,
    finished_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_created ON backtest_runs (created_at DESC);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id         BIGSERIAL PRIMARY KEY,
    run_id     BIGINT REFERENCES backtest_runs (id) ON DELETE CASCADE,
    ts         TIMESTAMPTZ,
    symbol     TEXT,
    sleeve     TEXT,
    setup      TEXT,
    side       TEXT,
    entry      NUMERIC(18, 4),
    exit       NUMERIC(18, 4),
    quantity   BIGINT,
    pnl        NUMERIC(18, 4),
    r_multiple NUMERIC(10, 4),
    fees       NUMERIC(18, 4),
    reason     TEXT
);
CREATE INDEX IF NOT EXISTS idx_backtest_trades_run ON backtest_trades (run_id);
