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


class PermanentDeliveryError(RuntimeError):
    pass


def send_message(chat_id: int | None, text: str | None) -> int:
    if not settings.TELEGRAM_DELIVERY_ENABLED:
        raise DeliveryDisabled()
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Telegram token missing")
    if (
        type(chat_id) is not int
        or chat_id <= 0
        or not isinstance(text, str)
        or not 0 < len(text) <= 4096
    ):
        raise PermanentDeliveryError("Invalid Telegram message")
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
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {400, 403}:
            raise PermanentDeliveryError("Telegram rejected the message or recipient") from None
        raise RuntimeError("Telegram delivery failed; acceptance unconfirmed") from None
    except (httpx.RequestError, ValueError, AttributeError):
        raise RuntimeError("Telegram delivery failed; acceptance unconfirmed") from None
