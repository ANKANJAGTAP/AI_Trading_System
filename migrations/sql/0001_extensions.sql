-- TimescaleDB extension (hypertables for ticks/candles/audit_log).
-- gen_random_uuid() is in core Postgres >= 13, no pgcrypto needed.
CREATE EXTENSION IF NOT EXISTS timescaledb;
