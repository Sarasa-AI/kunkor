"""Administrative and Operations router.

Exposes endpoints for:
- Student consultation review (all plans, items, progress logs).
- Feature flags management and toggles.
- Student entitlements & subscription granting.
- Audit log inspection.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.db import get_db_connection
from app.modules.operations.auth import require_admin_auth
from app.modules.operations.repository import OperationsRepository

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_auth)],
)


class SetFeatureFlagRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    is_enabled: bool
    description: Optional[str] = None
    rules: Optional[dict[str, Any]] = None


class GrantEntitlementRequest(BaseModel):
    student_id: UUID
    feature_key: str = Field(min_length=1, max_length=100)
    is_granted: bool = True
    valid_to: Optional[datetime] = None


@router.get("/students")
def list_students(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List students and their active consultation plan summaries."""
    with get_db_connection() as conn:
        students = OperationsRepository.get_students(conn, limit=limit, offset=offset)
        return {"items": students, "limit": limit, "offset": offset}


@router.get("/students/{student_id}/plans")
def get_student_plans(student_id: UUID) -> dict[str, Any]:
    """Retrieve full revision history of study plans for a student."""
    with get_db_connection() as conn:
        plans = OperationsRepository.get_student_plans(conn, student_id=student_id)
        return {"student_id": str(student_id), "plans": plans}


@router.get("/students/{student_id}/progress")
def get_student_progress(student_id: UUID) -> dict[str, Any]:
    """Retrieve chronological daily progress check-in logs for a student."""
    with get_db_connection() as conn:
        logs = OperationsRepository.get_student_progress_logs(conn, student_id=student_id)
        return {"student_id": str(student_id), "progress_logs": logs}


@router.get("/flags")
def list_feature_flags() -> dict[str, Any]:
    """List all system feature flags."""
    with get_db_connection() as conn:
        flags = OperationsRepository.get_feature_flags(conn)
        return {"flags": flags}


@router.post("/flags")
def set_feature_flag(payload: SetFeatureFlagRequest) -> dict[str, Any]:
    """Create or toggle a feature flag with audit logging."""
    with get_db_connection() as conn:
        flag = OperationsRepository.set_feature_flag(
            conn=conn,
            name=payload.name,
            is_enabled=payload.is_enabled,
            description=payload.description,
            rules=payload.rules,
        )
        OperationsRepository.record_audit_event(
            conn=conn,
            action="feature_flag.update",
            resource_type="feature_flag",
            resource_id=payload.name,
            metadata={"is_enabled": payload.is_enabled},
        )
        conn.commit()
        return flag


@router.get("/entitlements/{student_id}")
def get_student_entitlements(student_id: UUID) -> dict[str, Any]:
    """Retrieve entitlements granted to a student."""
    with get_db_connection() as conn:
        entitlements = OperationsRepository.get_student_entitlements(conn, student_id=student_id)
        return {"student_id": str(student_id), "entitlements": entitlements}


@router.post("/entitlements")
def grant_entitlement(payload: GrantEntitlementRequest) -> dict[str, Any]:
    """Grant or revoke a student feature entitlement with audit logging."""
    with get_db_connection() as conn:
        entitlement = OperationsRepository.grant_or_revoke_entitlement(
            conn=conn,
            student_id=payload.student_id,
            feature_key=payload.feature_key,
            is_granted=payload.is_granted,
            valid_to=payload.valid_to,
        )
        OperationsRepository.record_audit_event(
            conn=conn,
            action="entitlement.update",
            resource_type="entitlement",
            student_id=payload.student_id,
            resource_id=payload.feature_key,
            metadata={
                "feature_key": payload.feature_key,
                "is_granted": payload.is_granted,
                "valid_to": str(payload.valid_to) if payload.valid_to else None,
            },
        )
        conn.commit()
        return entitlement


@router.get("/audit-logs")
def list_audit_events(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    student_id: Optional[UUID] = None,
    action: Optional[str] = None,
) -> dict[str, Any]:
    """Query immutable audit events with optional filtering."""
    with get_db_connection() as conn:
        events = OperationsRepository.get_audit_events(
            conn=conn,
            limit=limit,
            offset=offset,
            student_id=student_id,
            action=action,
        )
        return {"items": events, "limit": limit, "offset": offset}
