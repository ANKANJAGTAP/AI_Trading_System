-- =====================================================================
-- 0019_position_scope.sql  (P1#8 — scope positions by mode + account)
-- positions.mode already exists; add account_id + broker so risk/P&L reads can
-- be scoped to the ACTIVE namespace (paper and live never mix). Backfill paper
-- rows to a literal 'paper' account; live rows get their account going forward.
-- =====================================================================

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS account_id TEXT,
  ADD COLUMN IF NOT EXISTS broker     TEXT;

UPDATE positions SET broker = 'kite' WHERE broker IS NULL;
UPDATE positions SET account_id = 'paper' WHERE account_id IS NULL AND mode <> 'live';

CREATE INDEX IF NOT EXISTS positions_scope ON positions (mode, account_id, status);
CREATE INDEX IF NOT EXISTS positions_mode_status ON positions (mode, status);
