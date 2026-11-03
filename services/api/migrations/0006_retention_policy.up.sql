-- 0006_retention_policy.up.sql
-- Narrowly scoped PostgreSQL privileged deletion function & independent authorization table
-- for GDPR/privacy compliance (ADR-0005, Phase 6).
--
-- Defense-in-depth architecture:
-- 1. Explicit authorization table (retention_erasure_authorizations) strictly non-modifiable by app role.
-- 2. Cryptographic token commitment (stores SHA-256 hash of 256-bit secret token; raw token required for execution).
-- 3. Transaction-bound authorization check using txid_current() in the trigger.
-- 4. Dedicated SECURITY DEFINER deletion function with locked search_path = public, pg_temp.
-- 5. Standard SQLSTATE error codes: 42501 (insufficient_privilege), 22023 (age invalid), P0002 (not found).
-- 6. Full foreign-key and append-only trigger enforcement preserved.

-- 1. Explicit authorization table for retention deletions
-- Note: student_id is UUID NOT NULL without ON DELETE CASCADE so that the authorization
-- audit log survives student deletion without foreign-key conflict or cascade-deletion.
CREATE TABLE IF NOT EXISTS retention_erasure_authorizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL,
    authorized_by VARCHAR(100) NOT NULL,
    authorization_token_hash VARCHAR(64) NOT NULL,
    inactivity_cutoff_days INT NOT NULL CHECK (inactivity_cutoff_days >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    active_in_transaction_id BIGINT
);

CREATE INDEX IF NOT EXISTS idx_retention_auth_lookup
ON retention_erasure_authorizations (student_id, authorization_token_hash)
WHERE consumed_at IS NULL;

-- Strict least-privilege: Revoke ALL permissions on retention authorizations from PUBLIC
REVOKE ALL ON TABLE retention_erasure_authorizations FROM PUBLIC;

-- 2. Prevent tampering, deletion, or forging of retention authorizations
CREATE OR REPLACE FUNCTION prevent_retention_auth_tampering()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    -- 1. DELETE is prohibited unconditionally on retention_erasure_authorizations
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Table % is an immutable audit log. DELETE is prohibited.', TG_TABLE_NAME
        USING ERRCODE = '42501';
    END IF;

    -- 2. INSERT restrictions
    IF TG_OP = 'INSERT' THEN
        IF NEW.active_in_transaction_id IS NOT NULL THEN
            RAISE EXCEPTION 'active_in_transaction_id cannot be set on creation.'
            USING ERRCODE = '42501';
        END IF;

        IF NEW.consumed_at IS NOT NULL THEN
            RAISE EXCEPTION 'consumed_at cannot be set on creation.'
            USING ERRCODE = '42501';
        END IF;

        IF NEW.expires_at <= NOW() THEN
            RAISE EXCEPTION 'expires_at must be in the future.'
            USING ERRCODE = '22023';
        END IF;

        RETURN NEW;
    END IF;

    -- 3. UPDATE restrictions
    IF TG_OP = 'UPDATE' THEN
        -- Consumed authorizations are permanently sealed
        IF OLD.consumed_at IS NOT NULL THEN
            RAISE EXCEPTION 'Consumed authorizations are sealed. Replay and modification are prohibited.'
            USING ERRCODE = '42501';
        END IF;

        -- Immutable fields: student_id, authorized_by, authorization_token_hash, inactivity_cutoff_days, created_at, expires_at
        IF NEW.student_id <> OLD.student_id
           OR NEW.authorized_by <> OLD.authorized_by
           OR NEW.authorization_token_hash <> OLD.authorization_token_hash
           OR NEW.inactivity_cutoff_days <> OLD.inactivity_cutoff_days
           OR NEW.created_at <> OLD.created_at
           OR NEW.expires_at <> OLD.expires_at
           OR NEW.id <> OLD.id THEN
            RAISE EXCEPTION 'Authorization parameters are immutable once created.'
            USING ERRCODE = '42501';
        END IF;

        -- State transition validation:
        -- Transition A: Activation: NULL -> txid_current()
        -- Transition B: Consumption: txid_current() -> NULL with consumed_at set
        IF NOT (
            (OLD.active_in_transaction_id IS NULL AND NEW.active_in_transaction_id = txid_current() AND NEW.consumed_at IS NULL)
            OR
            (OLD.active_in_transaction_id = txid_current() AND NEW.active_in_transaction_id IS NULL AND NEW.consumed_at IS NOT NULL)
        ) THEN
            RAISE EXCEPTION 'Invalid authorization state transition or unauthorized transaction binding.'
            USING ERRCODE = '42501';
        END IF;

        RETURN NEW;
    END IF;

    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_retention_auth_tampering ON retention_erasure_authorizations;
CREATE TRIGGER trg_retention_auth_tampering
BEFORE INSERT OR UPDATE OR DELETE ON retention_erasure_authorizations
FOR EACH ROW
EXECUTE FUNCTION prevent_retention_auth_tampering();

-- 3. Update trigger function with transaction-bound authorization verification
CREATE OR REPLACE FUNCTION prevent_append_only_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'DELETE' AND TG_TABLE_NAME = 'daily_progress_logs' THEN
        -- Verify that this exact PostgreSQL transaction holds an authorized, active erasure
        -- explicitly registered for OLD.student_id
        IF EXISTS (
            SELECT 1 FROM retention_erasure_authorizations
            WHERE student_id = OLD.student_id
              AND active_in_transaction_id = txid_current()
              AND consumed_at IS NULL
              AND expires_at >= NOW()
        ) THEN
            RETURN OLD;
        END IF;

        RAISE EXCEPTION 'Table % is append-only. DELETE requires active authorized retention erasure transaction.', TG_TABLE_NAME
        USING ERRCODE = '42501';
    END IF;

    -- All other deletions and all updates on append-only tables are strictly forbidden
    RAISE EXCEPTION 'Table % is append-only. UPDATE and DELETE operations are prohibited.', TG_TABLE_NAME
    USING ERRCODE = '42501';
END;
$$;

-- 3. Dedicated privileged deletion function
-- Requires plaintext raw token; verifies against stored SHA-256 hash.
CREATE OR REPLACE FUNCTION execute_student_retention_erasure(
    p_student_id UUID,
    p_retention_days INT,
    p_raw_authorization_token TEXT
)
RETURNS JSONB
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
LANGUAGE plpgsql
AS $$
DECLARE
    v_student_exists BOOLEAN;
    v_latest_activity TIMESTAMPTZ;
    v_latest_progress TIMESTAMPTZ;
    v_actual_latest TIMESTAMPTZ;
    v_cutoff_time TIMESTAMPTZ;
    v_auth_id UUID;
    v_auth_cutoff INT;
    v_computed_hash TEXT;
    v_count_students INT;
    v_count_sessions INT;
    v_count_plans INT;
    v_count_items INT;
    v_count_logs INT;
    v_count_outbox INT;
    v_count_keys INT;
    v_count_entitlements INT;
    v_erased_summary JSONB;
BEGIN
    -- 1. Input Validation
    IF p_student_id IS NULL THEN
        RAISE EXCEPTION 'student_id cannot be null' USING ERRCODE = '22004';
    END IF;
    IF p_retention_days < 0 THEN
        RAISE EXCEPTION 'retention_days must be non-negative' USING ERRCODE = '22023';
    END IF;
    IF p_raw_authorization_token IS NULL OR length(p_raw_authorization_token) < 32 THEN
        RAISE EXCEPTION 'Valid raw authorization token required (minimum 32 characters)' USING ERRCODE = '42501';
    END IF;

    -- Compute SHA-256 of provided raw token
    v_computed_hash := encode(sha256(p_raw_authorization_token::bytea), 'hex');

    -- 2. Lock target student row to prevent concurrent mutations
    SELECT (id IS NOT NULL), COALESCE(updated_at, created_at)
    INTO v_student_exists, v_latest_activity
    FROM students
    WHERE id = p_student_id
    FOR UPDATE;

    IF NOT COALESCE(v_student_exists, false) THEN
        RAISE EXCEPTION 'Student % not found for erasure.', p_student_id USING ERRCODE = 'P0002';
    END IF;

    -- 3. Verify independently verified authorization record
    SELECT id, inactivity_cutoff_days
    INTO v_auth_id, v_auth_cutoff
    FROM retention_erasure_authorizations
    WHERE student_id = p_student_id
      AND authorization_token_hash = v_computed_hash
      AND consumed_at IS NULL
      AND expires_at >= NOW()
    FOR UPDATE;

    IF v_auth_id IS NULL THEN
        RAISE EXCEPTION 'Unauthorized erasure: no valid, unexpired authorization token for student %.', p_student_id
        USING ERRCODE = '42501';
    END IF;

    IF p_retention_days < v_auth_cutoff THEN
        RAISE EXCEPTION 'Requested retention days (%) less than authorized cutoff (%).', p_retention_days, v_auth_cutoff
        USING ERRCODE = '42501';
    END IF;

    -- 4. Verify age cutoff against latest activity and latest progress log
    SELECT MAX(created_at) INTO v_latest_progress
    FROM daily_progress_logs
    WHERE student_id = p_student_id;

    v_actual_latest := v_latest_activity;
    IF v_latest_progress IS NOT NULL AND v_latest_progress > v_actual_latest THEN
        v_actual_latest := v_latest_progress;
    END IF;

    v_cutoff_time := NOW() - (p_retention_days || ' days')::INTERVAL;
    IF v_actual_latest > v_cutoff_time THEN
        RAISE EXCEPTION 'Student activity too recent for retention erasure. Latest activity: %, cutoff: %',
            v_actual_latest, v_cutoff_time
        USING ERRCODE = '22023';
    END IF;

    -- 5. Take exact inventory of data to be erased
    SELECT COUNT(*) INTO v_count_sessions FROM intake_sessions WHERE student_id = p_student_id;
    SELECT COUNT(*) INTO v_count_plans FROM study_plans WHERE student_id = p_student_id;
    SELECT COUNT(*) INTO v_count_items FROM study_plan_items spi JOIN study_plans sp ON spi.plan_id = sp.id WHERE sp.student_id = p_student_id;
    SELECT COUNT(*) INTO v_count_logs FROM daily_progress_logs WHERE student_id = p_student_id;
    SELECT COUNT(*) INTO v_count_outbox FROM outbox_events WHERE student_id = p_student_id;
    SELECT COUNT(*) INTO v_count_keys FROM idempotency_keys WHERE student_id = p_student_id;
    SELECT COUNT(*) INTO v_count_entitlements FROM entitlements WHERE student_id = p_student_id;
    v_count_students := 1;

    v_erased_summary := jsonb_build_object(
        'students', v_count_students,
        'intake_sessions', v_count_sessions,
        'study_plans', v_count_plans,
        'study_plan_items', v_count_items,
        'daily_progress_logs', v_count_logs,
        'outbox_events', v_count_outbox,
        'idempotency_keys', v_count_keys,
        'entitlements', v_count_entitlements
    );

    -- 6. Bind current transaction ID to the authorization record to activate trigger exception
    UPDATE retention_erasure_authorizations
    SET active_in_transaction_id = txid_current()
    WHERE id = v_auth_id;

    -- 7. Execute deletion in strict foreign-key dependency order
    DELETE FROM study_plan_items WHERE plan_id IN (SELECT id FROM study_plans WHERE student_id = p_student_id);
    DELETE FROM study_plans WHERE student_id = p_student_id;
    DELETE FROM daily_progress_logs WHERE student_id = p_student_id;
    DELETE FROM intake_sessions WHERE student_id = p_student_id;
    DELETE FROM outbox_events WHERE student_id = p_student_id;
    DELETE FROM idempotency_keys WHERE student_id = p_student_id;
    DELETE FROM entitlements WHERE student_id = p_student_id;
    DELETE FROM students WHERE id = p_student_id;

    -- 8. Mark authorization consumed and clear active transaction ID
    UPDATE retention_erasure_authorizations
    SET consumed_at = NOW(),
        active_in_transaction_id = NULL
    WHERE id = v_auth_id;

    -- 9. Append non-identifying erasure receipt to audit_events
    INSERT INTO audit_events (
        actor_user_id, student_id, action, resource_type,
        resource_id, metadata
    ) VALUES (
        NULL, NULL, 'student.retention_erasure', 'student',
        'REDACTED', jsonb_build_object(
            'retention_policy_days', p_retention_days,
            'erased_counts', v_erased_summary,
            'policy_version', '5.0_preimage_sha256',
            'authorization_id', v_auth_id,
            'occurred_at', NOW()
        )
    );

    RETURN v_erased_summary;
END;
$$;

-- Strict least-privilege: Revoke execution on privileged functions from PUBLIC
REVOKE EXECUTE ON FUNCTION execute_student_retention_erasure(UUID, INT, TEXT) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION prevent_retention_auth_tampering() FROM PUBLIC;

-- Dynamic role configuration: configure kunkor_operator and kunkor without hardcoded credentials
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kunkor_operator') THEN
        GRANT USAGE ON SCHEMA public TO kunkor_operator;
        GRANT ALL ON TABLE retention_erasure_authorizations TO kunkor_operator;
        GRANT EXECUTE ON FUNCTION execute_student_retention_erasure(UUID, INT, TEXT) TO kunkor_operator;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'kunkor') THEN
        REVOKE ALL ON TABLE retention_erasure_authorizations FROM kunkor;
        REVOKE EXECUTE ON FUNCTION execute_student_retention_erasure(UUID, INT, TEXT) FROM kunkor;
    END IF;
END $$;


