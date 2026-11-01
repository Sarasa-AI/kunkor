"""Consultation service orchestrating Telegram conversational intake and planning.

Enforces:
- D-11 (Proposer-Validator, PII protection, Outbox delivery).
- ADR-0004 (isolated deterministic validation before persistence).
- ADR-0008 (denormalized student_id).
- Idempotent update deduplication.
"""

import logging
import re
from typing import Any, Optional

import psycopg

from app.ai.provider import (
    AiProvider,
    DeterministicRuleFallbackPlanner,
    NineRouterProvider,
)
from app.engines.catalog import get_default_catalog, get_resources_for_stage
from app.engines.validator import DeterministicValidator
from app.modules.consultation.repository import ConsultationRepository
from app.schemas.planning import (
    STAGE_CAPACITY_LIMITS,
    GradeCode,
    IntakeSlots,
    StageCode,
    StudyPlan,
    TrackCode,
)

logger = logging.getLogger("kunkor.consultation")


class ConsultationService:
    """End-to-end educational consultation service for Telegram student interaction."""

    def __init__(
        self,
        ai_provider: Optional[AiProvider] = None,
        repository: Optional[ConsultationRepository] = None,
    ):
        self.ai_provider = ai_provider or NineRouterProvider()
        self.repo = repository or ConsultationRepository()

    def _parse_stage_and_grade(self, text: str) -> tuple[StageCode, GradeCode]:
        text_lower = text.lower()
        if any(w in text_lower for w in ["دوازدهم", "12", "کنکور", "konkur"]):
            return "konkur", "G12"
        if any(w in text_lower for w in ["یازدهم", "11"]):
            return "upper_secondary", "G11"
        if any(w in text_lower for w in ["دهم", "10"]):
            return "upper_secondary", "G10"
        if any(w in text_lower for w in ["نهم", "9", "هشتم", "8", "هفتم", "7", "متوسطه"]):
            return "lower_secondary", "G09"
        if any(w in text_lower for w in ["ابتدایی", "دبستان", "پنجم", "ششم"]):
            return "primary_high", "G05"
        # Default fallback to konkur
        return "konkur", "G12"

    def _parse_track(self, text: str) -> TrackCode:
        text_lower = text.lower()
        if any(w in text_lower for w in ["ریاضی", "math"]):
            return "mathematics"
        if any(w in text_lower for w in ["انسانی", "humanities"]):
            return "humanities"
        # Default to experimental
        return "experimental"

    def _parse_capacity(self, text: str, stage_code: StageCode) -> int:
        ceiling = STAGE_CAPACITY_LIMITS.get(stage_code, 360)
        # Check for hours or minutes pattern
        numbers = re.findall(r"\d+", text)
        minutes = 180  # default
        if numbers:
            val = int(numbers[0])
            if "ساعت" in text or "hour" in text.lower():
                minutes = val * 60
            elif val <= 12:  # Assume hours if <= 12
                minutes = val * 60
            else:
                minutes = val

        return max(15, min(minutes, ceiling))

    def _parse_weak_subjects(self, text: str, track: TrackCode) -> list[str]:
        # Simple extraction of common subjects
        known_subjects: dict[str, str] = {
            "زیست": "biology",
            "شیمی": "chemistry",
            "فیزیک": "physics",
            "ریاضی": "mathematics",
            "حسابان": "calculus",
            "هندسه": "geometry",
            "گسسته": "discrete_math",
            "ادبیات": "literature",
            "جامعه": "sociology",
            "فلسفه": "philosophy_logic",
            "علوم": "science",
            "فارسی": "reading_fluency",
        }
        found: list[str] = []
        for kw, subj in known_subjects.items():
            if kw in text:
                found.append(subj)
        if not found:
            # Fallback based on track
            if track == "experimental":
                found = ["biology", "chemistry"]
            elif track == "mathematics":
                found = ["calculus", "physics"]
            elif track == "humanities":
                found = ["literature", "sociology"]
            else:
                found = ["mathematics"]
        return found

    def _format_study_plan_message(self, plan: StudyPlan, intake: IntakeSlots) -> str:
        lines = [
            "🎉 برنامه مطالعه شخصی‌سازی شده شما با موفقیت آماده و اعتبارسنجی شد!\n",
            f"🎯 مقطع: {intake.stage_code} | رشته: {intake.track}",
            f"⏱ مدت زمان کل روزانه: {sum(it.duration_minutes for it in plan.items)} دقیقه",
            f"📋 نسخه برنامه: rev-{plan.revision_no}\n",
            "واحد‌های مطالعاتی پیشنهادی:",
        ]
        for idx, item in enumerate(plan.items, start=1):
            lines.append(
                f"{idx}. منبع: {item.resource_version_id} — {item.duration_minutes} دقیقه"
            )
        lines.append("\nبرای ثبت گزارش پیشرفت روزانه می‌توانید از دستور /progress استفاده کنید.")
        return "\n".join(lines)

    async def handle_telegram_update(
        self,
        conn: psycopg.Connection[Any],
        update: dict[str, Any],
        test_mode: bool = False,
    ) -> dict[str, Any]:
        """
        Process an incoming Telegram update transactionally and idempotently.
        """
        update_id = update.get("update_id")
        message = update.get("message") or update.get("edited_message")
        if not message or not update_id:
            return {"status": "ignored", "reason": "non_message_update"}

        chat = message.get("chat", {})
        from_user = message.get("from", {})
        telegram_chat_id = chat.get("id")
        if not telegram_chat_id:
            return {"status": "ignored", "reason": "missing_chat_id"}

        text = (message.get("text") or "").strip()

        # 1. Idempotency Check & Deduplication
        idempotency_key = f"tg_update_{update_id}"
        is_new_update = self.repo.check_and_record_idempotency_key(
            conn,
            key=idempotency_key,
            student_id=None,
            request_hash=f"hash_{update_id}",
        )
        if not is_new_update:
            logger.info("Duplicate Telegram update %s ignored.", update_id)
            return {"status": "duplicate", "response_text": None}

        # 2. Get or create student identity
        student_id = self.repo.get_or_create_student(
            conn,
            telegram_chat_id=telegram_chat_id,
            telegram_user_id=from_user.get("id"),
            telegram_username=from_user.get("username"),
            first_name=from_user.get("first_name"),
        )

        # 3. Retrieve or initiate intake session
        session = self.repo.get_active_intake_session(conn, student_id)
        if not session or text.lower() in ("/start", "/restart", "شروع"):
            session = self.repo.create_intake_session(conn, student_id)
            welcome_msg = (
                "سلام! به کنکور خوش آمدید 🎓\n"
                "من مشاور هوشمند برنامه‌ریزی تحصیلی شما هستم.\n\n"
                "لطفاً پایه یا مقطع تحصیلی خود را مشخص کنید:\n"
                "۱. دوازدهم (کنکور)\n"
                "۲. یازدهم\n"
                "۳. دهم\n"
                "۴. متوسطه اول\n"
                "۵. ابتدایی"
            )
            self.repo.update_intake_session(
                conn,
                session_id=session["id"],
                current_step="stage",
                slots={},
            )
            return {
                "status": "intake_in_progress",
                "step": "stage",
                "student_id": str(student_id),
                "response_text": welcome_msg,
            }

        step = session["current_step"]
        slots = session["slots"]

        # 4. State Machine Progression
        if step == "stage":
            stage_code, grade = self._parse_stage_and_grade(text)
            slots["stage_code"] = stage_code
            slots["grade"] = grade

            if stage_code in ("konkur", "upper_secondary"):
                next_step = "track"
                prompt_msg = "رشته تحصیلی شما چیست؟\n- تجربی\n- ریاضی\n- انسانی"
            else:
                slots["track"] = "general"
                next_step = "capacity"
                prompt_msg = (
                    "روزانه چند ساعت یا دقیقه برای مطالعه زمان دارید؟ "
                    "(مثلاً: ۴ ساعت یا ۲۴۰ دقیقه)"
                )

            self.repo.update_intake_session(
                conn,
                session_id=session["id"],
                current_step=next_step,
                slots=slots,
            )
            return {
                "status": "intake_in_progress",
                "step": next_step,
                "student_id": str(student_id),
                "response_text": prompt_msg,
            }

        if step == "track":
            track = self._parse_track(text)
            slots["track"] = track
            next_step = "capacity"
            prompt_msg = (
                "روزانه چند ساعت یا دقیقه برای مطالعه زمان دارید؟ "
                "(مثلاً: ۴ ساعت یا ۲۴۰ دقیقه)"
            )

            self.repo.update_intake_session(
                conn,
                session_id=session["id"],
                current_step=next_step,
                slots=slots,
            )
            return {
                "status": "intake_in_progress",
                "step": next_step,
                "student_id": str(student_id),
                "response_text": prompt_msg,
            }

        if step == "capacity":
            capacity = self._parse_capacity(text, slots.get("stage_code", "konkur"))
            slots["daily_study_capacity_minutes"] = capacity
            next_step = "weak_subjects"
            prompt_msg = (
                "در چه درس‌هایی احساس ضعف یا نیاز به تمرین بیشتر دارید؟ "
                "(مثلاً: زیست‌شناسی، شیمی، ریاضی)"
            )

            self.repo.update_intake_session(
                conn,
                session_id=session["id"],
                current_step=next_step,
                slots=slots,
            )
            return {
                "status": "intake_in_progress",
                "step": next_step,
                "student_id": str(student_id),
                "response_text": prompt_msg,
            }

        if step == "weak_subjects":
            track = slots.get("track", "experimental")
            weak_subjects = self._parse_weak_subjects(text, track)
            slots["weak_subjects"] = weak_subjects

            # Construct validated IntakeSlots
            intake = IntakeSlots(
                stage_code=slots["stage_code"],
                grade=slots["grade"],
                track=slots["track"],
                daily_study_capacity_minutes=slots["daily_study_capacity_minutes"],
                weak_subjects=slots["weak_subjects"],
            )

            catalog = get_default_catalog()
            available_resources = get_resources_for_stage(intake.stage_code)

            # Generate plan proposal via Proposer (AI)
            proposal = await self.ai_provider.propose_study_plan(intake, available_resources)

            # Authoritative Deterministic Validator Check
            next_rev = self.repo.get_latest_plan_revision(conn, student_id) + 1
            validated_plan: StudyPlan

            try:
                validated_plan = DeterministicValidator.validate_and_parse_proposal(
                    proposal=proposal,
                    intake=intake,
                    catalog=catalog,
                    student_id=student_id,
                    revision_no=next_rev,
                )
            except Exception as val_exc:
                logger.warning(
                    "AI proposal failed deterministic validation (%s). Triggering fallback.",
                    val_exc,
                )
                fallback_proposal = DeterministicRuleFallbackPlanner.generate_fallback_plan(
                    intake, available_resources
                )
                validated_plan = DeterministicValidator.validate_and_parse_proposal(
                    proposal=fallback_proposal,
                    intake=intake,
                    catalog=catalog,
                    student_id=student_id,
                    revision_no=next_rev,
                )
                proposal = fallback_proposal

            # Persist Study Plan in PostgreSQL
            items_data = [item.model_dump() for item in validated_plan.items]
            self.repo.save_study_plan(
                conn=conn,
                plan_id=validated_plan.plan_id,
                student_id=student_id,
                revision_no=next_rev,
                stage_code=intake.stage_code,
                engine_version=validated_plan.engine_version,
                rule_set_version=validated_plan.rule_set_version,
                raw_proposal=proposal,
                items=items_data,
            )

            # Enqueue Outbox Event for delivery
            formatted_message = self._format_study_plan_message(validated_plan, intake)
            self.repo.enqueue_outbox_event(
                conn=conn,
                student_id=student_id,
                event_type="STUDY_PLAN_DELIVERY_REQUESTED",
                aggregate_type="study_plan",
                aggregate_id=str(validated_plan.plan_id),
                payload={
                    "student_id": str(student_id),
                    "telegram_chat_id": telegram_chat_id,
                    "plan_id": str(validated_plan.plan_id),
                    "revision_no": next_rev,
                    "message_text": formatted_message,
                },
            )

            # Mark intake completed
            self.repo.update_intake_session(
                conn,
                session_id=session["id"],
                current_step="completed",
                slots=slots,
                is_completed=True,
            )

            return {
                "status": "plan_generated",
                "step": "completed",
                "student_id": str(student_id),
                "plan_id": str(validated_plan.plan_id),
                "revision_no": next_rev,
                "response_text": formatted_message,
            }

        return {"status": "unknown_step", "response_text": "دستور نامعتبر است."}
