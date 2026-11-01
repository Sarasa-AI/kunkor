"""Telegram consultation webhook router.

Exposes the secure endpoint for receiving Telegram bot updates.
Enforces webhook secret verification and links updates to the ConsultationService.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.core.config import settings
from app.core.db import get_db_connection
from app.modules.consultation.service import ConsultationService

router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])


def verify_telegram_webhook(
    x_telegram_bot_api_secret_token: Optional[str] = Header(
        None, alias="X-Telegram-Bot-Api-Secret-Token"
    ),
) -> bool:
    """
    Verify incoming Telegram webhook authenticity.
    Guards endpoint against forged updates.
    """
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    if expected:
        if x_telegram_bot_api_secret_token != expected:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Telegram webhook secret token.",
            )
    return True


# Mark dependency for authz matrix checker compliance (SEC-05 / ADR-0003)
setattr(verify_telegram_webhook, "__authz_enforcing__", True)


@router.post("/webhook", dependencies=[Depends(verify_telegram_webhook)])
async def telegram_webhook(
    update: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """
    Receive and process Telegram Bot updates.
    """
    service = ConsultationService()
    test_mode = settings.ENVIRONMENT.lower() in ("test", "testing")

    with get_db_connection(test=test_mode) as conn:
        with conn.transaction():
            result = await service.handle_telegram_update(conn, update)

    return result
