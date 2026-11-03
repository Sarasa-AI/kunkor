"""Consultation router for Telegram webhooks and student web portal.

Exposes endpoints for:
- Telegram Bot webhook processing.
- Active study plan inspection (/active-plan).
- Daily progress submission & dynamic plan revision (/progress).
- Consultation history & progress tracking (/history).
- Web intake and plan generation (/intake).
- Student consultation profile (/me).
"""

import hashlib
from secrets import compare_digest
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, model_validator

from app.ai.provider import DeterministicRuleFallbackPlanner, NineRouterProvider
from app.core.config import settings
from app.core.db import get_db_connection
from app.engines.catalog import get_resources_for_stage
from app.engines.validator import DeterministicValidationError, DeterministicValidator
from app.modules.consultation.auth import require_student_access
from app.modules.consultation.repository import ConsultationRepository
from app.modules.consultation.service import ConsultationService
from app.schemas.planning import GradeCode, IntakeSlots, StageCode, TrackCode, Weekday

router = APIRouter(tags=["consultation"])


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
    if not expected or not compare_digest(x_telegram_bot_api_secret_token or "", expected):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret token.")
    return True


# Mark dependency for authz matrix checker compliance (SEC-05 / ADR-0003)
setattr(verify_telegram_webhook, "__authz_enforcing__", True)


class SubmitProgressRequest(BaseModel):
    completed_units: list[str] = Field(default_factory=list)
    missed_units: list[str] = Field(default_factory=list)
    duration_spent_minutes: int = Field(default=0, ge=0, le=1440)
    student_notes: Optional[str] = None


class WebIntakeRequest(BaseModel):
    stage_code: StageCode = "konkur"
    grade: GradeCode = "G12"
    track: TrackCode = "experimental"
    daily_study_capacity_minutes: int = Field(default=180, ge=15, le=720)
    weak_subjects: list[str] = Field(default_factory=list)
    goal_code: Literal["school", "exam", "review"] = "exam"
    study_days: list[Weekday] = Field(
        default_factory=lambda: list(range(7)), min_length=1, max_length=7
    )
    max_session_minutes: Optional[int] = Field(default=None, gt=0, strict=True)

    @model_validator(mode="after")
    def validate_intake(self) -> "WebIntakeRequest":
        intake = IntakeSlots(**self.model_dump())
        try:
            DeterministicValidator.validate_track_subjects(intake)
        except DeterministicValidationError as exc:
            raise ValueError("Weak subjects must belong to the selected track.") from exc
        return self


@router.post("/api/v1/telegram/webhook", dependencies=[Depends(verify_telegram_webhook)])
async def telegram_webhook(
    update: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    """Receive and process Telegram Bot updates."""
    service = ConsultationService()
    test_mode = settings.ENVIRONMENT.lower() in ("test", "testing")

    with get_db_connection(test=test_mode) as conn:
        result = await service.handle_telegram_update(conn, update)
        conn.commit()

    return result


@router.get("/api/v1/consultation/active-plan")
@router.get("/active-plan")
def get_active_study_plan(
    student_id: UUID = Depends(require_student_access),
) -> dict[str, Any]:
    """Retrieve the student's currently active study plan and assigned units."""
    test_mode = settings.ENVIRONMENT.lower() in ("test", "testing")
    with get_db_connection(test=test_mode) as conn:
        plan = ConsultationRepository.get_active_study_plan(conn, student_id)
        if not plan:
            return {
                "status": "not_found",
                "student_id": str(student_id),
                "plan": None,
                "message": "No active study plan found.",
            }

        total_duration = sum(it.get("duration_minutes", 0) for it in plan.get("items", []))
        return {
            "status": "active",
            "student_id": str(student_id),
            "total_duration_minutes": total_duration,
            "total_items": len(plan.get("items", [])),
            "plan": plan,
        }


@router.post("/api/v1/consultation/progress")
@router.post("/progress")
async def submit_daily_progress(
    body: SubmitProgressRequest,
    student_id: UUID = Depends(require_student_access),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
) -> dict[str, Any]:
    """
    Record daily progress and trigger deterministic Rev N+1 plan revision.
    """
    service = ConsultationService()
    test_mode = settings.ENVIRONMENT.lower() in ("test", "testing")

    with get_db_connection(test=test_mode) as conn:
        request_key = "progress:" + idempotency_key
        cached = ConsultationRepository.begin_request(
            conn,
            student_id,
            request_key,
            hashlib.sha256(body.model_dump_json().encode()).hexdigest(),
        )
        if cached is not None:
            return cached
        # Entitlement Gating Check (FR-S1 / Phase 5)
        if ConsultationRepository.is_feature_enabled(conn, "enforce_subscription_entitlements"):
            if not ConsultationRepository.check_student_entitlement(
                conn, student_id, "ai_consultant"
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "🔒 دسترسی به مشاور هوشمند نیازمند اشتراک فعال است. "
                        "لطفاً جهت فعال‌سازی حساب کاربری خود با پشتیبانی تماس بگیرید."
                    ),
                )

        # Active plan check
        active_plan = ConsultationRepository.get_active_study_plan(conn, student_id)
        if not active_plan:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active study plan found for student. Please start a consultation first.",
            )

        # Require at least one unit reported
        if not body.completed_units and not body.missed_units:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Must report at least one completed or missed unit.",
            )

        duration = body.duration_spent_minutes
        if duration <= 0:
            duration = (
                sum(
                    it["duration_minutes"]
                    for it in active_plan.get("items", [])
                    if it["resource_version_id"] in body.completed_units
                )
                or 60
            )

        result = await service.handle_progress_and_revision(
            conn=conn,
            student_id=student_id,
            completed_units=body.completed_units,
            missed_units=body.missed_units,
            duration_spent_minutes=duration,
            student_notes=body.student_notes,
        )
        ConsultationRepository.finish_request(conn, student_id, request_key, result)
        conn.commit()

    return result


@router.get("/api/v1/consultation/history")
@router.get("/history")
def get_progress_history(
    student_id: UUID = Depends(require_student_access),
) -> dict[str, Any]:
    """Retrieve chronological log of student progress and revisions."""
    test_mode = settings.ENVIRONMENT.lower() in ("test", "testing")
    with get_db_connection(test=test_mode) as conn:
        logs = ConsultationRepository.get_student_historical_progress(conn, student_id)
        return {
            "student_id": str(student_id),
            "total_logs": len(logs),
            "logs": logs,
        }


@router.post("/api/v1/consultation/intake")
@router.post("/intake")
async def initialize_web_intake(
    req: WebIntakeRequest,
    student_id: UUID = Depends(require_student_access),
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128),
) -> dict[str, Any]:
    """Initialize or reset consultation plan directly from the web client."""
    service = ConsultationService()
    if isinstance(service.ai_provider, NineRouterProvider):
        service.ai_provider.bind_student(student_id)
    test_mode = settings.ENVIRONMENT.lower() in ("test", "testing")

    with get_db_connection(test=test_mode) as conn:
        request_key = "intake:" + idempotency_key
        cached = ConsultationRepository.begin_request(
            conn,
            student_id,
            request_key,
            hashlib.sha256(req.model_dump_json().encode()).hexdigest(),
        )
        if cached is not None:
            return cached
        # Entitlement check
        if ConsultationRepository.is_feature_enabled(conn, "enforce_subscription_entitlements"):
            if not ConsultationRepository.check_student_entitlement(
                conn, student_id, "ai_consultant"
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "🔒 دسترسی به مشاور هوشمند نیازمند اشتراک فعال است. "
                        "لطفاً جهت فعال‌سازی حساب کاربری خود با پشتیبانی تماس بگیرید."
                    ),
                )

        next_rev = ConsultationRepository.get_latest_plan_revision(conn, student_id) + 1
        intake = IntakeSlots(
            stage_code=req.stage_code,
            grade=req.grade,
            track=req.track,
            daily_study_capacity_minutes=req.daily_study_capacity_minutes,
            weak_subjects=req.weak_subjects,
            goal_code=req.goal_code,
            study_days=req.study_days,
            max_session_minutes=req.max_session_minutes,
        )
        # Record intake session for historical slot persistence and revision awareness
        session = ConsultationRepository.create_intake_session(conn, student_id)
        ConsultationRepository.update_intake_session(
            conn,
            session_id=session["id"],
            current_step="completed",
            slots=intake.model_dump(),
            is_completed=True,
        )

        resources = get_resources_for_stage(req.stage_code)
        if not DeterministicRuleFallbackPlanner.generate_fallback_plan(intake, resources)["items"]:
            detail = "No trusted resources fit the supplied intake and daily capacity."
            ConsultationRepository.finish_request(
                conn, student_id, request_key, {"_error_detail": detail}
            )
            conn.commit()
            raise HTTPException(422, detail)
        proposal = await service.ai_provider.propose_study_plan(intake, resources)

        validated_plan, proposal = await service.validate_or_repair(
            proposal, intake, resources, student_id, next_rev
        )

        items_data = [item.model_dump() for item in validated_plan.items]
        ConsultationRepository.save_study_plan(
            conn=conn,
            plan_id=validated_plan.plan_id,
            student_id=student_id,
            revision_no=next_rev,
            stage_code=req.stage_code,
            engine_version=validated_plan.engine_version,
            rule_set_version=validated_plan.rule_set_version,
            raw_proposal=proposal,
            items=items_data,
            intake_slots=intake.model_dump(),
        )

        ConsultationRepository.enqueue_outbox_event(
            conn=conn,
            student_id=student_id,
            event_type="STUDY_PLAN_DELIVERY_REQUESTED",
            aggregate_type="study_plan",
            aggregate_id=str(validated_plan.plan_id),
            payload={
                "student_id": str(student_id),
                "plan_id": str(validated_plan.plan_id),
                "revision_no": next_rev,
                "source": "web_portal",
                "telegram_chat_id": ConsultationRepository.get_telegram_chat_id(conn, student_id),
                "message_text": service._format_study_plan_message(validated_plan, intake),
            },
        )

        plan = ConsultationRepository.get_active_study_plan(conn, student_id)
        result = {
            "status": "plan_generated",
            "student_id": str(student_id),
            "plan_id": str(validated_plan.plan_id),
            "revision_no": next_rev,
            "plan": plan,
        }
        ConsultationRepository.finish_request(conn, student_id, request_key, result)
        conn.commit()
        return result


@router.get("/api/v1/consultation/me")
@router.get("/me")
def get_student_profile(
    student_id: UUID = Depends(require_student_access),
) -> dict[str, Any]:
    """Retrieve basic profile details and active plan status for authenticated student."""
    test_mode = settings.ENVIRONMENT.lower() in ("test", "testing")
    with get_db_connection(test=test_mode) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT id, telegram_chat_id, telegram_username, first_name, created_at
                FROM students
                WHERE id = %s;
                """,
                (student_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Student not found.",
                )

            active_plan = ConsultationRepository.get_active_study_plan(conn, student_id)
            data = dict(row)
            data["has_active_plan"] = active_plan is not None
            data["active_revision_no"] = active_plan["revision_no"] if active_plan else None
            return data
