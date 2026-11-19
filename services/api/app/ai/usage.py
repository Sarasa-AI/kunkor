"""Compatibility export; quota persistence belongs to the backend."""

from app.core.ai_usage import reserve_daily_attempt

__all__ = ["reserve_daily_attempt"]
