-- =====================================================================
-- 0014_runtime_mode.sql  (P0#1 — atomic execution mode)
-- Seed the single RuntimeModeState row that the executor, kill-switch, capital
-- reader and risk engine now read lazily. Safe default = paper (simulated_fill);
-- a live flip only ever happens through common.mode_transition. DO NOTHING on
-- conflict so a re-run never clobbers an operator-set state.
-- =====================================================================

INSERT INTO config_state (key, value, updated_by)
VALUES (
  'runtime_mode',
  '{"mode":"simulated_fill","broker_account_id":null,"capital_source":"paper_static","risk_profile":"paper","kill_switch_mode":"block_all","position_namespace":"simulated_fill","updated_by":"migration","updated_at":"","version":0}'::jsonb,
  'migration'
)
ON CONFLICT (key) DO NOTHING;
