-- 0001_baseline_schema.up.sql
-- Base database schema: extensions, append-only trigger, and core infrastructure tables

CREATE EXTENSION IF NOT EXISTS "btree_gist";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Reusable append-only trigger function to reject UPDATE and DELETE
CREATE OR REPLACE FUNCTION prevent_append_only_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Table % is append-only. UPDATE and DELETE operations are prohibited.', TG_TABLE_NAME
    USING ERRCODE = '23505';
END;
$$ LANGUAGE plpgsql;

-- 1. AuditEvent table (WP-13 / Section 2.3)
CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id UUID,
    student_id UUID,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100) NOT NULL,
    resource_id VARCHAR(100),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    request_id VARCHAR(100),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_student ON audit_events (student_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor ON audit_events (actor_user_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events (action, occurred_at);

DROP TRIGGER IF EXISTS trg_audit_events_append_only ON audit_events;
CREATE TRIGGER trg_audit_events_append_only
BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW
EXECUTE FUNCTION prevent_append_only_mutation();

-- 2. OutboxEvent table (Section 2.3 transactional domain events)
CREATE TABLE IF NOT EXISTS outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID,
    event_type VARCHAR(100) NOT NULL,
    aggregate_type VARCHAR(100) NOT NULL,
    aggregate_id VARCHAR(100) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    retry_count INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_outbox_events_unprocessed ON outbox_events (occurred_at) WHERE processed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_outbox_events_student ON outbox_events (student_id, occurred_at);

-- 3. IdempotencyKey table (Section 2.3)
CREATE TABLE IF NOT EXISTS idempotency_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID,
    key VARCHAR(255) NOT NULL,
    request_hash VARCHAR(64) NOT NULL,
    response_code INT,
    response_body JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_until TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_idempotency_keys_unique
ON idempotency_keys (key, COALESCE(student_id, '00000000-0000-0000-0000-000000000000'::uuid));

-- 4. FeatureFlag table (Section 2.3)
CREATE TABLE IF NOT EXISTS feature_flags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    rules JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5. Entitlement table (FR-S1 / Section 2.3)
CREATE TABLE IF NOT EXISTS entitlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feature_key VARCHAR(100) NOT NULL,
    user_id UUID,
    student_id UUID,
    is_granted BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entitlements_student ON entitlements (student_id, feature_key);
CREATE INDEX IF NOT EXISTS idx_entitlements_user ON entitlements (user_id, feature_key);
