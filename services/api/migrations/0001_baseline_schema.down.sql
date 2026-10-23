-- 0001_baseline_schema.down.sql
-- Rollback baseline schema

DROP TABLE IF EXISTS entitlements CASCADE;
DROP TABLE IF EXISTS feature_flags CASCADE;
DROP TABLE IF EXISTS idempotency_keys CASCADE;
DROP TABLE IF EXISTS outbox_events CASCADE;
DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;
DROP TABLE IF EXISTS audit_events CASCADE;
DROP FUNCTION IF EXISTS prevent_append_only_mutation();
