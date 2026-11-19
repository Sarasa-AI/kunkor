"""Identity service for student authentication, authorization, and profile management."""

import logging
from typing import Any, Optional
from uuid import UUID

import psycopg
from fastapi import HTTPException, status

from app.modules.consultation.service import trusted_plan_view
from app.modules.identity.repository import IdentityRepository

logger = logging.getLogger("kunkor.identity")


class IdentityService:
    """Identity and student profile management service."""

    def __init__(
        self,
        repository: Optional[IdentityRepository] = None,
    ):
        self.repo = repository or IdentityRepository()

    def get_student_by_telegram(
        self,
        conn: psycopg.Connection[Any],
        telegram_user_id: int,
        telegram_chat_id: int,
    ) -> Optional[UUID]:
        """Get student ID by Telegram credentials."""
        return self.repo.get_student_by_telegram_id(conn, telegram_user_id, telegram_chat_id)

    def get_or_create_student(
        self,
        conn: psycopg.Connection[Any],
        telegram_chat_id: int,
        telegram_user_id: Optional[int] = None,
        telegram_username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> UUID:
        """Create or retrieve student from Telegram identity."""
        return self.repo.get_or_create_student(
            conn, telegram_chat_id, telegram_user_id, telegram_username, first_name
        )

    def get_student_profile(
        self,
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> dict[str, Any]:
        """Get student profile with authorization check."""
        profile = self.repo.get_student_profile(conn, student_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Student not found.",
            )
        return profile

    def update_student_profile(
        self,
        conn: psycopg.Connection[Any],
        student_id: UUID,
        grade: Optional[str] = None,
        track: Optional[str] = None,
        guardian_consent: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Update student profile fields with audit logging."""
        # This is a profile assertion, not a backend authorization credential.
        # Validate grade if provided
        if grade is not None:
            valid_grades = {"G10", "G11", "G12"}
            if grade not in valid_grades:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Grade must be one of: {', '.join(valid_grades)}",
                )

        # Validate track if provided
        if track is not None:
            valid_tracks = {"general", "mathematics", "experimental", "humanities"}
            if track not in valid_tracks:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Track must be one of: {', '.join(valid_tracks)}",
                )

        self.repo.update_student_profile(
            conn,
            student_id,
            grade=grade,
            track=track,
            guardian_consent=guardian_consent,
        )

        return self.get_student_profile(conn, student_id)

    def get_student_context(
        self,
        conn: psycopg.Connection[Any],
        student_id: UUID,
    ) -> dict[str, Any]:
        """Load structured Student Context for Orchestrator consumption."""
        context = self.repo.get_student_context(conn, student_id)
        if not context:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Student not found.",
            )
        plan = context.get("active_plan")
        if plan:
            context["active_plan"] = trusted_plan_view(conn, plan)
            if context["active_plan"] is None:
                context["content_status"] = "awaiting_content"
            else:
                context["content_status"] = "available"
        return context

    def list_students(
        self,
        conn: psycopg.Connection[Any],
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List students (admin only)."""
        return self.repo.list_students(conn, limit, offset)
