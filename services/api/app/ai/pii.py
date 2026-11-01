"""PII Masking and Sanitization module.

Enforces D-11 (Principle 2):
Zero personal identifiable information (name, phone, national ID, Telegram ID)
may be sent to external AI providers.
"""

import re
from typing import Any

from app.schemas.planning import IntakeSlots

# Regular expressions for sensitive personal identifiers
_IRAN_PHONE_REGEX = re.compile(r"(?:\+98|0098|0)?9\d{9}\b")
_EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_NATIONAL_ID_REGEX = re.compile(r"\b\d{10}\b")
_TELEGRAM_HANDLE_REGEX = re.compile(r"@[a-zA-Z0-9_]{4,32}\b")
_TELEGRAM_USER_ID_REGEX = re.compile(r"\b(tg_user_|telegram_id:?)\s*\d{5,15}\b", re.IGNORECASE)


def mask_pii_text(text: str) -> str:
    """Mask any PII occurrences in a free-text string."""
    masked = _IRAN_PHONE_REGEX.sub("[MASKED_PHONE]", text)
    masked = _EMAIL_REGEX.sub("[MASKED_EMAIL]", masked)
    masked = _NATIONAL_ID_REGEX.sub("[MASKED_NATIONAL_ID]", masked)
    masked = _TELEGRAM_HANDLE_REGEX.sub("[MASKED_HANDLE]", masked)
    masked = _TELEGRAM_USER_ID_REGEX.sub("[MASKED_TG_ID]", masked)
    return masked


def sanitize_intake_for_ai(intake: IntakeSlots) -> dict[str, Any]:
    """
    Extract strictly anonymous educational parameters for AI proposal prompt.
    Guarantees no student identity, user ID, or contact information is leaked.
    """
    # Sanitize weak_subjects strings if any free text is entered
    sanitized_weak_subjects = [
        mask_pii_text(str(subject)) for subject in intake.weak_subjects
    ]

    sanitized_target_exam = (
        mask_pii_text(str(intake.target_exam)) if intake.target_exam else None
    )

    return {
        "stage_code": intake.stage_code,
        "grade": intake.grade,
        "track": intake.track,
        "daily_study_capacity_minutes": intake.daily_study_capacity_minutes,
        "weak_subjects": sanitized_weak_subjects,
        "target_exam": sanitized_target_exam,
    }
