"""Identity module router for student authentication, profile, and context."""

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StrictBool

from app.core.config import settings
from app.core.db import get_db_connection
from app.modules.identity.auth import require_student_access
from app.modules.identity.service import IdentityService

router = APIRouter(prefix="/api/v1/identity", tags=["identity"])


# -------- Request Models --------


class UpdateProfileRequest(BaseModel):
    """Request to update student profile fields."""

    grade: Optional[str] = Field(default=None, pattern="^(G10|G11|G12)$")
    track: Optional[str] = Field(
        default=None, pattern="^(general|mathematics|experimental|humanities)$"
    )
    guardian_consent: Optional[StrictBool] = None

    @classmethod
    def validate_grade(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"G10", "G11", "G12"}:
            raise ValueError("Grade must be G10, G11, or G12")
        return v

    @classmethod
    def validate_track(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"general", "mathematics", "experimental", "humanities"}:
            raise ValueError("Track must be one of: general, mathematics, experimental, humanities")
        return v


# -------- Endpoints --------


@router.get("/me")
def get_student_profile(
    student_id: UUID = Depends(require_student_access),
) -> dict[str, Any]:
    """Retrieve authenticated student's profile (grade, track, consent)."""
    test_mode = settings.ENVIRONMENT.lower() in ("test", "testing")
    with get_db_connection(test=test_mode) as conn:
        service = IdentityService()
        return service.get_student_profile(conn, student_id)


@router.patch("/me")
def update_student_profile(
    body: UpdateProfileRequest,
    student_id: UUID = Depends(require_student_access),
) -> dict[str, Any]:
    """Update authenticated student's profile with audit logging."""
    test_mode = settings.ENVIRONMENT.lower() in ("test", "testing")
    with get_db_connection(test=test_mode) as conn:
        service = IdentityService()
        result = service.update_student_profile(
            conn,
            student_id,
            grade=body.grade,
            track=body.track,
            guardian_consent=body.guardian_consent,
        )
        conn.commit()
        return result


@router.get("/context")
def get_student_context(
    student_id: UUID = Depends(require_student_access),
) -> dict[str, Any]:
    """Load structured Student Context for Orchestrator consumption.

    Returns combined read-model: profile + latest intake + active plan + progress summary.
    """
    test_mode = settings.ENVIRONMENT.lower() in ("test", "testing")
    with get_db_connection(test=test_mode) as conn:
        service = IdentityService()
        return service.get_student_context(conn, student_id)
