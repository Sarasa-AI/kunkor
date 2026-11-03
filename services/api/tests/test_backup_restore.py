"""Automated test for PostgreSQL backup and restoration verification drill."""


from scripts.execute_backup_restore_drill import execute_drill


def test_backup_and_restore_reproducible_drill():
    """
    Executes a real local PostgreSQL backup and restore drill using two separate
    disposable databases (kunkor_backup_source_test and kunkor_backup_target_test).
    Verifies:
    1. Consistent dump generation via pg_dump.
    2. Accurate restoration via pg_restore.
    3. Matching table row counts and SHA-256 row fingerprints.
    4. Exact match of append-only triggers and schema constraints.
    5. Runtime query and append-only trigger enforcement on the restored database.
    """
    result = execute_drill()
    assert result["status"] == "PASS"
    assert result["fingerprint_sha256_match"] is True
    assert result["triggers_verified_match"] is True
    assert result["constraints_verified_match"] is True
    assert result["restored_runtime_query_test"] == "PASS"
    assert result["restored_append_only_enforcement_test"] == "PASS"
