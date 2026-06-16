-- =====================================================================
-- 0016_position_exit_fields.sql  (P0#3 — live exit product handling)
-- Persist the fields a correct live exit needs ON the position, so market_exit()
-- can derive product/exchange/variety instead of hardcoding MIS. Backfill open
-- rows from their order row (product + order_type are known there).
-- =====================================================================

ALTER TABLE positions
  ADD COLUMN IF NOT EXISTS product         TEXT,
  ADD COLUMN IF NOT EXISTS exchange        TEXT,
  ADD COLUMN IF NOT EXISTS variety         TEXT DEFAULT 'regular',
  ADD COLUMN IF NOT EXISTS order_type      TEXT,
  ADD COLUMN IF NOT EXISTS instrument_type TEXT;

UPDATE positions p SET
  product    = COALESCE(p.product, o.product),
  order_type = COALESCE(p.order_type, o.order_type)
FROM orders o
WHERE o.correlation_id = p.correlation_id
  AND p.product IS NULL;
