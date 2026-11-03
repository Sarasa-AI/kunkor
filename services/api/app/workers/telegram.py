"""Telegram Bot API transport. Successful return means API acceptance only."""

import logging
import re

import httpx

from app.core.config import settings


class _TelegramTokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = re.sub(r"/bot[^/\s]+/", "/bot[REDACTED]/", record.getMessage())
        record.args = ()
        return True


# httpx logs request URLs at INFO, including Telegram's token-bearing path.
logging.getLogger("httpx").addFilter(_TelegramTokenFilter())


class DeliveryDisabled(Exception):
    pass


def send_message(chat_id: int, text: str) -> int:
    if not settings.TELEGRAM_DELIVERY_ENABLED:
        raise DeliveryDisabled()
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Telegram token missing")
    if not isinstance(chat_id, int) or chat_id <= 0 or not text or len(text) > 4096:
        raise ValueError("Invalid Telegram message")
    # Never log request URLs: Telegram embeds the secret token in the URL.
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        message_id = data.get("result", {}).get("message_id")
        if data.get("ok") is not True or not isinstance(message_id, int):
            raise ValueError("Telegram did not accept message")
        return message_id
    except Exception:
        raise RuntimeError("Telegram delivery failed; acceptance unconfirmed") from None
