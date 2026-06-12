-- Per-instrument ATM implied-volatility history (Phase 2.2).
-- One row per underlying per trading day; backs a real per-name IV Rank/Percentile
-- instead of the single INDIA VIX proxy used for every symbol.
CREATE TABLE IF NOT EXISTS iv_history (
    name    TEXT NOT NULL,
    ts      DATE NOT NULL,
    atm_iv  NUMERIC(10, 4),
    PRIMARY KEY (name, ts)
);
CREATE INDEX IF NOT EXISTS idx_iv_history_name_ts ON iv_history (name, ts DESC);
