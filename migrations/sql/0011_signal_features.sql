-- Rich per-signal feature vector for the meta-labeler (Phase 4).
-- Continuous context values (RVOL, ADX/regime, IV-rank, gap, VWAP-distance, DTE, PCR,
-- time-of-day, ...) that actually vary between winners and losers — unlike gate scores.
ALTER TABLE signals ADD COLUMN IF NOT EXISTS features JSONB;
