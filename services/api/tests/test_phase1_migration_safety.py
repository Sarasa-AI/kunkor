"""P1-C03 migration safety: fresh synthetic databases, original constraints intact."""

import os
import subprocess
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from scripts import execute_backup_restore_drill as drill
from scripts.migrate import apply_migrations, rollback_migrations
from scripts.migrate_check import require_test_database
from scripts.verify_restore import fingerprint


@pytest.fixture
def private_database():
    """Create, never reuse, a UUID-named database on the explicit test host."""
    test_dsn = os.environ["TEST_DATABASE_URL"]
    require_test_database(test_dsn)
    info = conninfo_to_dict(test_dsn)
    assert info["host"] in {"localhost", "127.0.0.1", "::1"}
    name = f"kunkor_migration_{uuid4().hex}_test"
    admin_dsn = make_conninfo(test_dsn, dbname="postgres")
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(test_dsn, dbname=name)
    yield dsn
    # Only this fixture's fresh database is removed; never terminate connections.
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))


def seed_valid(dsn):
    with psycopg.connect(dsn) as conn:
        students = conn.execute(
            "INSERT INTO students(telegram_chat_id,telegram_user_id,grade,track) "
            "VALUES(11001,11001,'G10','general'),(11002,11002,'G12','experimental') "
            "RETURNING id"
        ).fetchall()
        a, b = students[0][0], students[1][0]
        plan = conn.execute(
            "INSERT INTO study_plans(student_id,stage_code) "
            "VALUES(%s,'upper_secondary') RETURNING id",
            (a,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO study_plan_items(plan_id,student_id,item_order,"
            "resource_version_id,stage_code,duration_minutes) "
            "VALUES(%s,%s,1,'synthetic','upper_secondary',15)",
            (plan, a),
        )
        conn.execute(
            "INSERT INTO daily_progress_logs(student_id,plan_id,revision_no) "
            "VALUES(%s,%s,1)",
            (a, plan),
        )
    return a, b, plan


@pytest.mark.parametrize("conflict", ["duplicate_user", "non_private", "item_owner", "revision"])
def test_0009_conflicts_stop_without_partial_constraints_or_data_changes(
    private_database, conflict
):
    dsn = private_database
    assert apply_migrations(dsn, steps=8) == 8
    a, b, plan = seed_valid(dsn)
    with psycopg.connect(dsn) as conn:
        if conflict == "duplicate_user":
            conn.execute(
                "INSERT INTO students(telegram_chat_id,telegram_user_id) VALUES(11003,11001)"
            )
        elif conflict == "non_private":
            conn.execute("UPDATE students SET telegram_chat_id=11003 WHERE id=%s", (b,))
        elif conflict == "item_owner":
            conn.execute("UPDATE study_plan_items SET student_id=%s WHERE plan_id=%s", (b, plan))
        else:
            conn.execute(
                "INSERT INTO daily_progress_logs(student_id,plan_id,revision_no) "
                "VALUES(%s,%s,99)",
                (a, plan),
            )
    before = fingerprint(dsn)
    with pytest.raises(psycopg.IntegrityError):
        apply_migrations(dsn, steps=1)
    # Full row hashes, migration versions, triggers and constraints remain exact.
    assert fingerprint(dsn) == before


def business_fingerprint(dsn):
    result = fingerprint(dsn)
    return {k: v for k, v in result.items() if not k.startswith("_") and k != "schema_migrations"}


def test_0009_valid_legacy_up_down_up_preserves_rows(private_database):
    dsn = private_database
    assert apply_migrations(dsn, steps=8) == 8
    seed_valid(dsn)
    before = fingerprint(dsn)
    rows = business_fingerprint(dsn)
    assert apply_migrations(dsn, steps=1) == 1
    after_up = fingerprint(dsn)
    assert business_fingerprint(dsn) == rows
    assert rollback_migrations(dsn, steps=1) == 1
    after_down = fingerprint(dsn)
    # Existing 0001-0008 ledger timestamps and entire schema are unchanged.
    assert after_down == before
    assert apply_migrations(dsn, steps=1) == 1
    assert business_fingerprint(dsn) == rows
    after_reapply = fingerprint(dsn)
    assert after_reapply["_constraints"] == after_up["_constraints"]
    assert after_reapply["_triggers"] == after_up["_triggers"]


def test_0010_up_down_up_preserves_values_and_original_constraints(private_database):
    dsn = private_database
    assert apply_migrations(dsn, steps=9) == 9
    seed_valid(dsn)
    before = fingerprint(dsn)
    rows = business_fingerprint(dsn)
    assert apply_migrations(dsn, steps=1) == 1
    canonical = fingerprint(dsn)["_constraints"]
    assert business_fingerprint(dsn) == rows
    with psycopg.connect(dsn) as conn:
        for column, invalid in (("grade", "G09"), ("track", "unapproved")):
            with pytest.raises(psycopg.IntegrityError), conn.transaction():
                conn.execute(
                    sql.SQL("UPDATE students SET {}=%s").format(sql.Identifier(column)),
                    (invalid,),
                )
        for grade in (None, "G10", "G11", "G12"):
            for track in (None, "general", "mathematics", "experimental", "humanities"):
                with conn.transaction(force_rollback=True):
                    conn.execute("UPDATE students SET grade=%s,track=%s", (grade, track))
    assert rollback_migrations(dsn, steps=1) == 1
    assert fingerprint(dsn) == before
    assert apply_migrations(dsn, steps=1) == 1
    assert business_fingerprint(dsn) == rows
    assert fingerprint(dsn)["_constraints"] == canonical


def test_restore_rejects_nonzero_host_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(drill.shutil, "which", lambda name: f"/fake/{name}")
    monkeypatch.setattr(drill, "is_pg16_binary", lambda path: True)
    monkeypatch.setattr(
        drill.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, 1)
    )
    with pytest.raises(RuntimeError, match="pg_restore"):
        drill.run_restore(Path(tmp_path / "synthetic.dump"), "synthetic_test", {})


def test_backup_requires_explicit_test_database(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="explicit"):
        drill.get_base_dsn()


def test_backup_rejects_remote_base_host(monkeypatch):
    monkeypatch.setenv("TEST_PG_HOST_DSN", "postgresql://db.production.internal/postgres")
    with pytest.raises(ValueError, match="loopback"):
        drill.get_base_dsn()
