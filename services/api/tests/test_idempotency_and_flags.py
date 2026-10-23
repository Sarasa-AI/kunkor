import os

import psycopg
import pytest

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://kunkor:kunkor_dev_password@localhost:5435/kunkor_test",
)


def test_idempotency_unique_constraint():
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO idempotency_keys (key, request_hash)
                VALUES (%s, %s);
                """,
                ("req-abc-123", "hash12345"),
            )
        conn.commit()

        # Duplicate insert with same key and null student_id must raise unique violation
        with conn.cursor() as cur:
            with pytest.raises(psycopg.Error) as exc_info:
                cur.execute(
                    """
                    INSERT INTO idempotency_keys (key, request_hash)
                    VALUES (%s, %s);
                    """,
                    ("req-abc-123", "hash67890"),
                )
            err_msg = str(exc_info.value).lower()
            assert "idx_idempotency_keys_unique" in err_msg or "unique" in err_msg
        conn.rollback()


def test_feature_flags_and_entitlements():
    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feature_flags (name, description, is_enabled)
                VALUES (%s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET is_enabled = EXCLUDED.is_enabled
                RETURNING is_enabled;
                """,
                ("konkur_mock_exam", "Konkur exam mock simulator", True),
            )
            assert cur.fetchone()[0] is True

            cur.execute(
                """
                INSERT INTO entitlements (feature_key, is_granted)
                VALUES (%s, %s)
                RETURNING is_granted;
                """,
                ("all_access", True),
            )
            assert cur.fetchone()[0] is True
        conn.commit()
