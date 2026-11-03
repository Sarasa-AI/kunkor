-- 0006_retention_policy.down.sql
-- Revert privileged retention function and restore strict append-only trigger.

DROP TRIGGER IF EXISTS trg_retention_auth_tampering ON retention_erasure_authorizations;
DROP FUNCTION IF EXISTS execute_student_retention_erasure(UUID, INT, TEXT);
DROP FUNCTION IF EXISTS prevent_retention_auth_tampering();

CREATE OR REPLACE FUNCTION prevent_append_only_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'Table % is append-only. UPDATE and DELETE operations are prohibited.', TG_TABLE_NAME
    USING ERRCODE = '42501';
END;
$$;

DROP TABLE IF EXISTS retention_erasure_authorizations CASCADE;
