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
from uuid import UUID

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
            lines.append(f"{idx}. منبع: {item.resource_version_id} — {item.duration_minutes} دقیقه")
        lines.append("\nبرای ثبت گزارش پیشرفت روزانه می‌توانید از دستور /progress استفاده کنید.")
        return "\n".join(lines)

    def _format_revision_message(
        self,
        plan: StudyPlan,
        intake: IntakeSlots,
        completion_rate: float,
        missed_units: list[str],
    ) -> str:
        lines = [
            f"📊 گزارش پیشرفت شما ثبت شد! درصد تحقق: {completion_rate:.1f}%\n",
            f"🔄 برنامه مطالعاتی جدید (ویرایش {plan.revision_no}) بر اساس عملکرد شما بازتنظیم شد:",
            f"⏱ مدت زمان کل روزانه: {sum(it.duration_minutes for it in plan.items)} دقیقه\n",
        ]
        if missed_units:
            lines.append(f"⚠️ مباحث جبرانی در اولویت: {', '.join(missed_units)}\n")
        lines.append("واحد‌های مطالعاتی بازنگری‌شده:")
        for idx, item in enumerate(plan.items, start=1):
            lines.append(f"{idx}. منبع: {item.resource_version_id} — {item.duration_minutes} دقیقه")
        return "\n".join(lines)

    def _parse_progress_report(
        self,
        text: str,
        active_plan_items: list[dict[str, Any]],
    ) -> tuple[list[str], list[str], int, Optional[str]]:
        # ponytail: regex progress parser. Upgrade if free-form NLP needed.
        valid_resource_ids = {it["resource_version_id"] for it in active_plan_items}
        clean = text
        if clean.lower().startswith("/progress"):
            clean = clean[len("/progress") :].strip()

        completed: list[str] = []
        missed: list[str] = []
        duration = 0
        notes: Optional[str] = None

        kv_pairs = dict(re.findall(r"(\w+)=((?:(?!\s+\w+=).)+)", clean))
        if any(
            k in kv_pairs
            for k in ("completed", "done", "missed", "incomplete", "time", "duration", "notes")
        ):
            for k, val in kv_pairs.items():
                k_lower = k.lower()
                if k_lower in ("completed", "done"):
                    completed = [tok.strip() for tok in re.split(r"[,;]+", val) if tok.strip()]
                elif k_lower in ("missed", "incomplete", "skip"):
                    missed = [tok.strip() for tok in re.split(r"[,;]+", val) if tok.strip()]
                elif k_lower in ("time", "duration"):
                    nums = re.findall(r"\d+", val)
                    if nums:
                        duration = int(nums[0])
                elif k_lower in ("notes", "note"):
                    notes = val.strip()

            return completed, missed, duration or 60, notes

        segments = re.split(r"[|\n;]", clean)
        notes_parts: list[str] = []

        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            seg_lower = seg.lower()

            if any(k in seg_lower for k in ("completed", "done", "تکمیل", "خوانده")):
                val = re.split(r"[:=]", seg, maxsplit=1)[-1]
                found = [r for r in valid_resource_ids if r in val]
                if found:
                    for r in found:
                        if r not in completed:
                            completed.append(r)
                else:
                    tokens = [t.strip() for t in re.split(r"[,،\s]+", val) if t.strip()]
                    completed.extend(tokens)

            elif any(
                k in seg_lower for k in ("missed", "incomplete", "skip", "نرسیدم", "عقب", "مانده")
            ):
                val = re.split(r"[:=]", seg, maxsplit=1)[-1]
                found = [r for r in valid_resource_ids if r in val]
                if found:
                    for r in found:
                        if r not in missed:
                            missed.append(r)
                else:
                    tokens = [t.strip() for t in re.split(r"[,،\s]+", val) if t.strip()]
                    missed.extend(tokens)

            elif any(k in seg_lower for k in ("duration", "time", "زمان", "مدت", "ساعت", "دقیقه")):
                nums = re.findall(r"\d+", seg)
                if nums:
                    val_num = int(nums[0])
                    if any(h in seg_lower for h in ("ساعت", "hour", "h")):
                        duration = val_num * 60
                    elif val_num <= 12:
                        duration = val_num * 60
                    else:
                        duration = val_num

            elif any(k in seg_lower for k in ("note", "notes", "یادداشت", "توضیح")):
                val = re.split(r"[:=]", seg, maxsplit=1)[-1].strip()
                if val:
                    notes_parts.append(val)
            else:
                found_res = [r for r in valid_resource_ids if r in seg]
                if found_res:
                    for r in found_res:
                        if r not in completed and r not in missed:
                            completed.append(r)
                elif any(c.isalnum() for c in seg):
                    notes_parts.append(seg)

        if not completed and not missed:
            for rid in valid_resource_ids:
                if rid in clean:
                    completed.append(rid)
            if completed:
                for it in active_plan_items:
                    r_id = it["resource_version_id"]
                    if r_id not in completed:
                        missed.append(r_id)

        if duration == 0:
            if completed:
                duration = sum(
                    it["duration_minutes"]
                    for it in active_plan_items
                    if it["resource_version_id"] in completed
                )
            else:
                duration = 60

        if notes_parts:
            notes = " ".join(notes_parts)

        return completed, missed, duration, notes

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

        # Entitlement Gating Check (FR-S1 / Phase 5)
        if self.repo.is_feature_enabled(conn, "enforce_subscription_entitlements"):
            if not self.repo.check_student_entitlement(conn, student_id, "ai_consultant"):
                return {
                    "status": "subscription_required",
                    "student_id": str(student_id),
                    "response_text": (
                        "🔒 دسترسی به مشاور هوشمند نیازمند اشتراک فعال است.\n"
                        "لطفاً جهت فعال‌سازی حساب کاربری خود با پشتیبانی تماس بگیرید."
                    ),
                }

        # 3. Check for progress reporting command
        if text.lower().startswith("/progress") or text in ("گزارش", "پیشرفت"):
            active_plan = self.repo.get_active_study_plan(conn, student_id)
            if not active_plan:
                return {
                    "status": "no_active_plan",
                    "student_id": str(student_id),
                    "response_text": (
                        "هنوز برنامه مطالعه‌ای برای شما ثبت نشده است. "
                        "لطفاً ابتدا با ارسال /start برنامه خود را دریافت کنید."
                    ),
                }

            completed, missed, duration, notes = self._parse_progress_report(
                text, active_plan["items"]
            )

            # If user sent just "/progress" or "گزارش" with no items
            if (
                not completed
                and not missed
                and text.strip().lower() in ("/progress", "گزارش", "پیشرفت")
            ):
                item_lines = "\n".join(
                    f"- {it['resource_version_id']} ({it['duration_minutes']} دقیقه)"
                    for it in active_plan["items"]
                )
                guide_msg = (
                    "📝 لطفاً گزارش مطالعه خود را در قالب زیر ارسال کنید:\n"
                    "/progress تکمیل: <شناسه مباحث> | نرسیدم: <شناسه مباحث> | زمان: <دقیقه>\n\n"
                    f"مباحث برنامه فعلی شما:\n{item_lines}"
                )
                return {
                    "status": "progress_prompt",
                    "student_id": str(student_id),
                    "response_text": guide_msg,
                }

            rev_result = await self.handle_progress_and_revision(
                conn=conn,
                student_id=student_id,
                completed_units=completed,
                missed_units=missed,
                duration_spent_minutes=duration,
                student_notes=notes,
                telegram_chat_id=telegram_chat_id,
            )
            return rev_result

        # 4. Retrieve or initiate intake session
        session = self.repo.get_active_intake_session(conn, student_id)
        if not session:
            active_plan = self.repo.get_active_study_plan(conn, student_id)
            if active_plan and text.lower() not in ("/start", "/restart", "شروع"):
                completed, missed, duration, notes = self._parse_progress_report(
                    text, active_plan["items"]
                )
                if completed or missed:
                    return await self.handle_progress_and_revision(
                        conn=conn,
                        student_id=student_id,
                        completed_units=completed,
                        missed_units=missed,
                        duration_spent_minutes=duration,
                        student_notes=notes,
                        telegram_chat_id=telegram_chat_id,
                    )
                else:
                    return {
                        "status": "active_plan_info",
                        "student_id": str(student_id),
                        "response_text": (
                            f"شما دارای برنامه فعال (ویرایش {active_plan['revision_no']}) هستید.\n"
                            "برای ثبت گزارش مطالعه از دستور /progress "
                            "و برای شروع دوباره از دستور /start استفاده کنید."
                        ),
                    }

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
        elif text.lower() in ("/start", "/restart", "شروع"):
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
                    "روزانه چند ساعت یا دقیقه برای مطالعه زمان دارید؟ (مثلاً: ۴ ساعت یا ۲۴۰ دقیقه)"
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
                "روزانه چند ساعت یا دقیقه برای مطالعه زمان دارید؟ (مثلاً: ۴ ساعت یا ۲۴۰ دقیقه)"
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

    async def handle_progress_and_revision(
        self,
        conn: psycopg.Connection[Any],
        student_id: UUID,
        completed_units: list[str],
        missed_units: list[str],
        duration_spent_minutes: int,
        student_notes: Optional[str] = None,
        telegram_chat_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Record immutable daily progress and generate deterministic revised study plan (Rev N+1).
        """
        active_plan = self.repo.get_active_study_plan(conn, student_id)
        if not active_plan:
            raise ValueError(f"No active study plan found for student {student_id}")

        plan_id = active_plan["id"]
        current_rev = active_plan["revision_no"]
        next_rev = current_rev + 1

        # 1. Record immutable daily progress log
        progress_id = self.repo.record_daily_progress(
            conn=conn,
            student_id=student_id,
            plan_id=plan_id,
            revision_no=current_rev,
            completed_units=completed_units,
            missed_units=missed_units,
            duration_spent_minutes=duration_spent_minutes,
            student_notes=student_notes,
        )

        total_units = len(completed_units) + len(missed_units)
        completion_rate = (len(completed_units) / max(1, total_units)) * 100.0

        # 2. Mark current plan superseded
        self.repo.supersede_plan(conn, plan_id)

        # 3. Retrieve student's completed unit IDs from history
        all_completed = self.repo.get_completed_unit_ids_for_student(conn, student_id)

        # 4. Reconstruct student intake slots
        intake_session = self.repo.get_latest_intake_session(conn, student_id)
        slots = intake_session["slots"] if intake_session else {}
        stage = active_plan["stage_code"]
        grade = slots.get("grade")
        if not grade:
            grade = "G12" if stage == "konkur" else ("G11" if stage == "upper_secondary" else "G09")
        track = slots.get("track")
        if not track or stage not in ("upper_secondary", "konkur"):
            track = "general" if stage not in ("upper_secondary", "konkur") else "experimental"

        capacity = slots.get("daily_study_capacity_minutes", 180)
        ceiling = STAGE_CAPACITY_LIMITS.get(stage, 180)
        capacity = min(capacity, ceiling)

        intake_kwargs: dict[str, Any] = {
            "stage_code": stage,
            "grade": grade,
            "track": track,
            "daily_study_capacity_minutes": capacity,
            "weak_subjects": slots.get("weak_subjects", []),
        }
        if "guardian_consent" in slots:
            intake_kwargs["guardian_consent"] = slots["guardian_consent"]
        elif stage in ("primary_low", "primary_high"):
            intake_kwargs["guardian_consent"] = True

        intake = IntakeSlots(**intake_kwargs)

        # 5. Filter available resources: exclude completed, prioritize missed
        catalog = get_default_catalog()
        stage_resources = get_resources_for_stage(intake.stage_code)
        uncompleted_resources = [
            r for r in stage_resources if r["resource_id"] not in all_completed
        ]
        if not uncompleted_resources:
            uncompleted_resources = stage_resources

        missed_set = set(missed_units)
        prioritized_resources = sorted(
            uncompleted_resources,
            key=lambda r: 0 if r["resource_id"] in missed_set else 1,
        )

        # 6. Propose revised plan (AI or deterministic fallback)
        proposal = await self.ai_provider.propose_study_plan(intake, prioritized_resources)
        validated_plan: StudyPlan

        try:
            validated_plan = DeterministicValidator.validate_and_parse_proposal(
                proposal=proposal,
                intake=intake,
                catalog=catalog,
                student_id=student_id,
                revision_no=next_rev,
                completed_unit_ids=all_completed,
            )
        except Exception as val_exc:
            logger.warning(
                "AI proposal for revision %s failed deterministic validation (%s). "
                "Triggering fallback.",
                next_rev,
                val_exc,
            )
            fallback_proposal = DeterministicRuleFallbackPlanner.generate_fallback_plan(
                intake, prioritized_resources, completed_unit_ids=all_completed
            )
            validated_plan = DeterministicValidator.validate_and_parse_proposal(
                proposal=fallback_proposal,
                intake=intake,
                catalog=catalog,
                student_id=student_id,
                revision_no=next_rev,
                completed_unit_ids=all_completed,
            )
            proposal = fallback_proposal

        # 7. Persist revised study plan
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

        # 8. Enqueue Outbox delivery event
        formatted_message = self._format_revision_message(
            validated_plan, intake, completion_rate, missed_units
        )
        self.repo.enqueue_outbox_event(
            conn=conn,
            student_id=student_id,
            event_type="STUDY_PLAN_REVISION_DELIVERED",
            aggregate_type="study_plan",
            aggregate_id=str(validated_plan.plan_id),
            payload={
                "student_id": str(student_id),
                "telegram_chat_id": telegram_chat_id,
                "plan_id": str(validated_plan.plan_id),
                "revision_no": next_rev,
                "progress_id": str(progress_id),
                "completion_rate": completion_rate,
                "message_text": formatted_message,
            },
        )

        return {
            "status": "plan_revised",
            "progress_id": str(progress_id),
            "plan_id": str(validated_plan.plan_id),
            "revision_no": next_rev,
            "completion_rate": completion_rate,
            "response_text": formatted_message,
        }
