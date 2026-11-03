"""Executable PostgreSQL backup and restoration verification drill.

Executes a complete, reproducible backup-and-restore drill between two
isolated, disposable loopback test databases:
1. Provisions kunkor_backup_source_test and kunkor_backup_target_test.
2. Applies migrations 0001 through 0006 on source database.
3. Seeds representative synthetic data across all required tables.
4. Dumps source database using pg_dump.
5. Restores dump into target database using pg_restore.
6. Verifies exact SHA-256 fingerprints, triggers, and constraints using verify_restore.
7. Executes application queries on restored database to verify runtime functionality.
8. Verifies append-only triggers remain active and enforced on restored database.
"""

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from scripts.migrate import apply_migrations
from scripts.verify_restore import fingerprint


def get_base_dsn() -> str:
    if os.getenv("TEST_PG_HOST_DSN"):
        return os.environ["TEST_PG_HOST_DSN"]
    test_db = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://kunkor:kunkor_dev_password@127.0.0.1:5435/kunkor_test",
    )
    info = conninfo_to_dict(test_db)
    user = info.get("user", "kunkor")
    password = info.get("password", "kunkor_dev_password")
    host = info.get("host", "127.0.0.1")
    port = info.get("port", "5435")
    return f"postgresql://{user}:{password}@{host}:{port}/postgres"


def build_db_url(base_dsn: str, dbname: str) -> str:
    info = conninfo_to_dict(base_dsn)
    user = info.get("user", "kunkor")
    password = info.get("password", "kunkor_dev_password")
    host = info.get("host", "127.0.0.1")
    port = info.get("port", "5435")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def recreate_database(base_dsn: str, dbname: str) -> None:
    if not dbname.endswith("_test"):
        raise ValueError("Only disposable databases named *_test can be dropped/recreated.")
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE);").format(
                    sql.Identifier(dbname)
                )
            )
            cur.execute(sql.SQL("CREATE DATABASE {};").format(sql.Identifier(dbname)))


def seed_synthetic_data(db_url: str) -> dict[str, int]:
    student_a = uuid4()
    student_b = uuid4()
    plan_a = uuid4()
    plan_b = uuid4()
    now = datetime.now(timezone.utc)

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            # 1. Students
            cur.execute(
                """
                INSERT INTO students (
                    id, telegram_chat_id, telegram_user_id, first_name, created_at, updated_at
                )
                VALUES (%s, 111111101, 111111101, 'دانش‌آموز الف', %s, %s),
                       (%s, 111111102, 111111102, 'دانش‌آموز ب', %s, %s);
                """,
                (student_a, now, now, student_b, now, now),
            )

            # 2. Intake sessions
            cur.execute(
                """
                INSERT INTO intake_sessions
                    (student_id, current_step, slots, is_completed, created_at)
                VALUES (%s, 'completed',
                        '{"stage_code": "konkur", "grade": "G12"}'::jsonb, TRUE, %s),
                       (%s, 'completed',
                        '{"stage_code": "upper_secondary", "grade": "G10"}'::jsonb, TRUE, %s);
                """,
                (student_a, now, student_b, now),
            )

            # 3. Study plans
            cur.execute(
                """
                INSERT INTO study_plans
                    (id, student_id, revision_no, stage_code, status, intake_slots, created_at)
                VALUES (%s, %s, 1, 'konkur', 'active', '{"grade": "G12"}'::jsonb, %s),
                       (%s, %s, 1, 'upper_secondary', 'active', '{"grade": "G10"}'::jsonb, %s);
                """,
                (plan_a, student_a, now, plan_b, student_b, now),
            )

            # 4. Study plan items
            cur.execute(
                """
                INSERT INTO study_plan_items
                    (id, plan_id, student_id, item_order, resource_version_id,
                     stage_code, duration_minutes)
                VALUES (gen_random_uuid(), %s, %s, 1, 'konkur_bio_g12_ch1', 'konkur', 60),
                       (gen_random_uuid(), %s, %s, 2, 'konkur_chem_g12_ch1', 'konkur', 60),
                       (gen_random_uuid(), %s, %s, 1, 'upper_math_g10_ch1', 'upper_secondary', 45),
                       (gen_random_uuid(), %s, %s, 2, 'upper_phys_g10_ch1', 'upper_secondary', 45);
                """,
                (plan_a, student_a, plan_a, student_a, plan_b, student_b, plan_b, student_b),
            )

            # 5. Daily progress logs
            cur.execute(
                """
                INSERT INTO daily_progress_logs
                    (student_id, plan_id, revision_no, completed_units, missed_units,
                     duration_spent_minutes, created_at)
                VALUES (%s, %s, 1, '["konkur_bio_g12_ch1"]'::jsonb, '[]'::jsonb, 60, %s),
                       (%s, %s, 1, '["upper_math_g10_ch1"]'::jsonb, '[]'::jsonb, 45, %s);
                """,
                (student_a, plan_a, now, student_b, plan_b, now),
            )

            # 6. Outbox events
            cur.execute(
                """
                INSERT INTO outbox_events
                    (student_id, event_type, aggregate_type, aggregate_id, payload, occurred_at)
                VALUES (%s, 'STUDY_PLAN_DELIVERY_REQUESTED', 'study_plan', %s,
                        '{"chat_id": 111111101}'::jsonb, %s),
                       (%s, 'STUDY_PLAN_DELIVERY_REQUESTED', 'study_plan', %s,
                        '{"chat_id": 111111102}'::jsonb, %s);
                """,
                (student_a, str(plan_a), now, student_b, str(plan_b), now),
            )

            # 7. Idempotency keys
            cur.execute(
                """
                INSERT INTO idempotency_keys (student_id, key, request_hash, created_at)
                VALUES (%s, 'seed_key_a', 'hash_seed_a', %s),
                       (%s, 'seed_key_b', 'hash_seed_b', %s);
                """,
                (student_a, now, student_b, now),
            )

            # 8. Entitlements
            cur.execute(
                """
                INSERT INTO entitlements (student_id, feature_key, is_granted, created_at)
                VALUES (%s, 'ai_consultant', TRUE, %s),
                       (%s, 'ai_consultant', TRUE, %s);
                """,
                (student_a, now, student_b, now),
            )

            # 9. Audit events
            cur.execute(
                """
                INSERT INTO audit_events (action, resource_type, metadata, occurred_at)
                VALUES ('seed.initialization', 'database', '{"seed_run": true}'::jsonb, %s),
                       ('consultation.started', 'student', '{"test": true}'::jsonb, %s);
                """,
                (now, now),
            )

            # 10. AI daily usage
            cur.execute(
                """
                INSERT INTO ai_daily_usage (usage_day, scope_key, attempts, reserved_usd)
                VALUES (CURRENT_DATE, 'global', 2, 0.01000000);
                """
            )

            # 11. Feature flags
            cur.execute(
                """
                INSERT INTO feature_flags (name, is_enabled, description)
                VALUES ('seed_flag_active', TRUE, 'Flag created during backup drill')
                ON CONFLICT (name) DO NOTHING;
                """
            )
        conn.commit()

    return {
        "students": 2,
        "study_plans": 2,
        "study_plan_items": 4,
        "daily_progress_logs": 2,
        "outbox_events": 2,
        "audit_events": 2,
    }


def is_pg16_binary(bin_path: str | None) -> bool:
    if not bin_path or not Path(bin_path).is_file():
        return False
    try:
        out = subprocess.check_output([bin_path, "--version"], text=True)
        return " 16." in out
    except Exception:
        return False


def run_dump(dump_file: Path, db_name: str, conn_info: dict) -> None:
    env = os.environ.copy()
    if conn_info.get("password"):
        env["PGPASSWORD"] = conn_info["password"]
    host_bin = shutil.which("pg_dump") or "/opt/homebrew/bin/pg_dump"
    if is_pg16_binary(host_bin):
        cmd = [
            host_bin,
            "-h", str(conn_info.get("host", "127.0.0.1")),
            "-p", str(conn_info.get("port", "5435")),
            "-U", str(conn_info.get("user", "kunkor")),
            "-F", "c",
            "-b",
            "-v",
            "-f", str(dump_file),
            db_name,
        ]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if proc.returncode == 0:
            return

    container = os.getenv("DOCKER_PG_CONTAINER", "kunkor-stage0-test-pg")
    docker_bin = shutil.which("docker")
    if docker_bin:
        container_tmp = f"/tmp/dump_{db_name}.dump"
        cmd = [
            docker_bin,
            "exec",
            "-e", f"PGPASSWORD={conn_info.get('password', 'kunkor_dev_password')}",
            container,
            "pg_dump",
            "-U", str(conn_info.get("user", "kunkor")),
            "-F", "c",
            "-b",
            "-f", container_tmp,
            db_name,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"docker pg_dump failed: {proc.stderr}")
        # Copy to host
        cp_proc = subprocess.run(
            [docker_bin, "cp", f"{container}:{container_tmp}", str(dump_file)],
            capture_output=True,
            text=True,
        )
        subprocess.run([docker_bin, "exec", container, "rm", "-f", container_tmp])
        if cp_proc.returncode != 0:
            raise RuntimeError(f"docker cp failed: {cp_proc.stderr}")
        return
    raise RuntimeError("Neither compatible host pg_dump nor docker pg_dump succeeded.")


def run_restore(dump_file: Path, db_name: str, conn_info: dict) -> None:
    env = os.environ.copy()
    if conn_info.get("password"):
        env["PGPASSWORD"] = conn_info["password"]
    host_bin = shutil.which("pg_restore") or "/opt/homebrew/bin/pg_restore"
    if is_pg16_binary(host_bin):
        cmd = [
            host_bin,
            "-h", str(conn_info.get("host", "127.0.0.1")),
            "-p", str(conn_info.get("port", "5435")),
            "-U", str(conn_info.get("user", "kunkor")),
            "-d", db_name,
            "-v",
            str(dump_file),
        ]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if proc.returncode in (0, 1):
            return

    container = os.getenv("DOCKER_PG_CONTAINER", "kunkor-stage0-test-pg")
    docker_bin = shutil.which("docker")
    if docker_bin:
        container_tmp = f"/tmp/restore_{db_name}.dump"
        # Copy dump to container
        cp_proc = subprocess.run(
            [docker_bin, "cp", str(dump_file), f"{container}:{container_tmp}"],
            capture_output=True,
            text=True,
        )
        if cp_proc.returncode != 0:
            raise RuntimeError(f"docker cp failed: {cp_proc.stderr}")
        cmd = [
            docker_bin,
            "exec",
            "-e", f"PGPASSWORD={conn_info.get('password', 'kunkor_dev_password')}",
            container,
            "pg_restore",
            "-U", str(conn_info.get("user", "kunkor")),
            "-d", db_name,
            container_tmp,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        subprocess.run([docker_bin, "exec", container, "rm", "-f", container_tmp])
        if proc.returncode in (0, 1):
            return
        raise RuntimeError(f"docker pg_restore failed: {proc.stderr}")
    raise RuntimeError("Neither compatible host pg_restore nor docker pg_restore succeeded.")


def execute_drill() -> dict:
    base_dsn = get_base_dsn()
    source_db = "kunkor_backup_source_test"
    target_db = "kunkor_backup_target_test"
    source_url = build_db_url(base_dsn, source_db)
    target_url = build_db_url(base_dsn, target_db)

    # Step 1: Recreate source and target DBs
    recreate_database(base_dsn, source_db)
    recreate_database(base_dsn, target_db)

    # Step 2: Apply migrations on source
    applied_migrations = apply_migrations(source_url)
    assert applied_migrations >= 5, (
        f"Expected at least 5 migrations applied, got {applied_migrations}"
    )

    # Step 3: Seed representative synthetic data
    seed_stats = seed_synthetic_data(source_url)

    # Step 4: Dump source database using pg_dump
    temp_dir = tempfile.mkdtemp(prefix="kunkor_backup_drill_")
    dump_file = Path(temp_dir) / "kunkor_source.dump"

    src_info = conninfo_to_dict(source_url)
    run_dump(dump_file, source_db, src_info)

    dump_size_bytes = dump_file.stat().st_size
    assert dump_size_bytes > 0, "Dump file is empty!"

    # Step 5: Restore into target database using pg_restore
    tgt_info = conninfo_to_dict(target_url)
    run_restore(dump_file, target_db, tgt_info)

    # Step 6: Verify exact fingerprints using verify_restore.fingerprint()
    source_fp = fingerprint(source_url)
    target_fp = fingerprint(target_url)

    assert source_fp == target_fp, (
        f"Fingerprint mismatch between source and restored databases!\n"
        f"Source: {source_fp}\nTarget: {target_fp}"
    )

    # Step 7: Verify runtime functionality on restored database
    with psycopg.connect(target_url) as conn:
        with conn.cursor() as cur:
            # Query students
            cur.execute("SELECT COUNT(*) FROM students;")
            assert cur.fetchone()[0] == 2

            # Query study plans
            cur.execute("SELECT COUNT(*) FROM study_plans;")
            assert cur.fetchone()[0] == 2

            # Test insert on restored audit_events
            cur.execute(
                """
                INSERT INTO audit_events (action, resource_type, metadata)
                VALUES ('restore_drill.verification', 'system', '{"verified": true}'::jsonb)
                RETURNING id;
                """
            )
            inserted_id = cur.fetchone()[0]
            assert inserted_id is not None

            # Verify append-only trigger still active and rejects UPDATE on restored DB
            try:
                cur.execute(
                    "UPDATE audit_events SET action = 'tampered' WHERE id = %s;",
                    (inserted_id,),
                )
                assert False, "Append-only trigger failed to reject UPDATE on restored database!"
            except psycopg.Error as exc:
                assert "append-only" in str(exc).lower()

        conn.commit()

    # Clean up dump file and temp dir
    shutil.rmtree(temp_dir, ignore_errors=True)

    return {
        "status": "PASS",
        "drill_timestamp": datetime.now(timezone.utc).isoformat(),
        "source_database": source_db,
        "target_database": target_db,
        "dump_format": "pg_dump -Fc (custom compressed)",
        "dump_size_bytes": dump_size_bytes,
        "applied_migrations": applied_migrations,
        "seeded_records": seed_stats,
        "tables_fingerprinted": len(source_fp) - 2,
        "fingerprint_sha256_match": True,
        "triggers_verified_match": source_fp["_triggers"] == target_fp["_triggers"],
        "constraints_verified_match": source_fp["_constraints"] == target_fp["_constraints"],
        "restored_runtime_query_test": "PASS",
        "restored_append_only_enforcement_test": "PASS",
    }


if __name__ == "__main__":
    result = execute_drill()
    print(json.dumps(result, indent=2, ensure_ascii=False))
