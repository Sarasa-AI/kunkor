"""Authenticate student requests using short-lived, signed Telegram Mini App data."""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import Header, HTTPException

from app.core.config import settings
from app.core.db import get_db_connection


def require_student_access(authorization: str | None = Header(None)) -> UUID:
    denied = HTTPException(401, "Invalid or missing signed Telegram credentials.")
    scheme, _, raw = (authorization or "").partition(" ")
    if scheme.lower() != "tma" or not raw or len(raw) > 8192 or not settings.TELEGRAM_BOT_TOKEN:
        raise denied
    try:
        pairs = parse_qsl(raw, strict_parsing=True, max_num_fields=20, errors="strict")
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError("Duplicate fields")
        signature = fields.pop("hash")
        check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", settings.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256)
        expected = hmac.new(secret.digest(), check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid signature")
        age = time.time() - int(fields["auth_date"])
        if not -30 <= age <= 300:
            raise ValueError("Expired credentials")
        user_id = json.loads(fields["user"])["id"]
        if type(user_id) is not int or not 0 < user_id < 2**63:
            raise ValueError("Invalid identity")
    except (KeyError, ValueError, TypeError, UnicodeError, RecursionError):
        raise denied from None

    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM students WHERE telegram_user_id = %s AND telegram_chat_id = %s;",
            (user_id, user_id),
        )
        row = cur.fetchone()
        if row:
            return UUID(str(row["id"]))
    raise denied


setattr(require_student_access, "__authz_enforcing__", True)
