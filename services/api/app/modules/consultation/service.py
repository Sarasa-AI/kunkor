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
from fastapi import HTTPException

from app.ai.provider import (
    AiProvider,
    DeterministicRuleFallbackPlanner,
    NineRouterProvider,
)
from app.engines.catalog import get_default_catalog, get_resources_for_stage
from app.engines.validator import (
    TRACK_SUBJECT_ALLOWLIST,
    DeterministicValidationError,
    DeterministicValidator,
)
from app.modules.consultation.repository import ConsultationRepository
from app.schemas.planning import (
    STAGE_CAPACITY_LIMITS,
    GradeCode,
    IntakeSlots,
    StageCode,
    StudyPlan,
    TrackCode,
    split_study_sessions,
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
        lower_grades: list[tuple[list[str], GradeCode]] = [
            (["هفتم", "7"], "G07"),
            (["هشتم", "8"], "G08"),
            (["نهم", "9", "متوسطه"], "G09"),
        ]
        for names, grade in lower_grades:
            if any(w in text_lower for w in names):
                return "lower_secondary", grade
        if any(w in text_lower for w in ["ابتدایی", "دبستان", "پنجم", "ششم"]):
            return "primary_high", "G05"
        raise ValueError("پایه معتبر وارد کنید؛ مثلاً دوازدهم یا یازدهم.")

    def _parse_track(self, text: str) -> TrackCode:
        text_lower = text.lower()
        if any(w in text_lower for w in ["ریاضی", "math"]):
            return "mathematics"
        if any(w in text_lower for w in ["انسانی", "humanities"]):
            return "humanities"
        if any(w in text_lower for w in ["تجربی", "experimental"]):
            return "experimental"
        raise ValueError("رشته معتبر وارد کنید: تجربی، ریاضی یا انسانی.")

    def _parse_capacity(self, text: str, stage_code: StageCode) -> int:
        ceiling = STAGE_CAPACITY_LIMITS.get(stage_code, 360)
        match = re.fullmatch(r"\s*(\d+)\s*(ساعت|hours?|دقیقه|minutes?)?\s*", text.lower())
        if not match:
            raise ValueError(f"زمان مطالعه باید بین ۱۵ و {ceiling} دقیقه باشد.")
        value, unit = int(match[1]), match[2] or ""
        minutes = (
            value * 60 if unit in ("ساعت", "hour", "hours") or (not unit and value <= 12) else value
        )
        if not 15 <= minutes <= ceiling:
            raise ValueError(f"زمان مطالعه باید بین ۱۵ و {ceiling} دقیقه باشد.")
        return minutes

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
        return [subject for subject in found if subject in TRACK_SUBJECT_ALLOWLIST[track]]

    def _parse_goal(self, text: str) -> str:
        goals = {
            "school": "school",
            "مدرسه": "school",
            "exam": "exam",
            "آزمون": "exam",
            "کنکور": "exam",
            "review": "review",
            "مرور": "review",
        }
        if text.strip().lower() not in goals:
            raise ValueError("هدف را انتخاب کنید: مدرسه، آزمون یا مرور.")
        return goals[text.strip().lower()]

    def _parse_days(self, text: str) -> list[int]:
        if text.replace(" ", "") in ("هرروز", "همهروزها"):
            return list(range(7))
        days = {
            "دوشنبه": 0,
            "سهشنبه": 1,
            "چهارشنبه": 2,
            "پنجشنبه": 3,
            "جمعه": 4,
            "شنبه": 5,
            "یکشنبه": 6,
        }
        result = []
        for token in re.split(r"[,،;]+", text):
            token = token.strip().replace(" ", "").replace("\u200c", "")
            day = int(token) if token.isdecimal() else days.get(token, -1)
            if day not in range(7) or day in result:
                raise ValueError("روزهای یکتا را با ویرگول بنویسید؛ مثلاً شنبه،دوشنبه یا هر روز.")
            result.append(day)
        if not result:
            raise ValueError("حداقل یک روز مطالعه لازم است.")
        return result

    def _parse_session(self, text: str, capacity: int) -> int:
        match = re.fullmatch(r"\s*(\d+)\s*(?:دقیقه|minutes?)?\s*", text)
        if not match or not 1 <= int(match[1]) <= capacity:
            raise ValueError(f"حداکثر مدت هر جلسه را بین ۱ و {capacity} دقیقه وارد کنید.")
        return int(match[1])

    def _format_constraints(self, intake: IntakeSlots) -> str:
        goals = {"school": "مدرسه", "exam": "آزمون", "review": "مرور"}
        days = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
        selected_days = ", ".join(days[d] for d in intake.study_days)
        return (
            f"هدف: {goals[intake.goal_code]} | روزهای مطالعه: {selected_days}\n"
            f"حداکثر هر جلسه: {intake.max_session_minutes} دقیقه؛ "
            "برنامه برای یک روز مطالعه است."
        )

    def _format_study_plan_message(self, plan: StudyPlan, intake: IntakeSlots) -> str:
        resources = {r["resource_id"]: r for r in get_resources_for_stage(intake.stage_code)}
        lines = [
            "🎉 برنامه مطالعه شخصی‌سازی شده شما با موفقیت آماده و اعتبارسنجی شد!\n",
            f"🎯 مقطع: {intake.stage_code} | رشته: {intake.track}",
            f"⏱ مدت زمان کل روزانه: {sum(it.duration_minutes for it in plan.items)} دقیقه",
            f"📋 نسخه برنامه: rev-{plan.revision_no}\n",
            self._format_constraints(intake),
            "واحد‌های مطالعاتی پیشنهادی:",
        ]
        for idx, item in enumerate(plan.items, start=1):
            title = resources[item.resource_version_id]["title"]
            chunks = split_study_sessions([item.model_dump()], intake.max_session_minutes or 60)
            session_text = " + ".join(str(chunk["duration_minutes"]) for chunk in chunks)
            lines.append(
                f"{idx}. {title} — {item.duration_minutes} دقیقه\n"
                f"جلسه‌ها (دقیقه): {session_text}\nشناسه گزارش: {item.resource_version_id}"
            )
        lines.append("\nبرای ثبت گزارش پیشرفت روزانه می‌توانید از دستور /progress استفاده کنید.")
        return "\n".join(lines)

    def _format_revision_message(
        self,
        plan: StudyPlan,
        intake: IntakeSlots,
        completion_rate: float,
        missed_units: list[str],
    ) -> str:
        resources = {r["resource_id"]: r for r in get_resources_for_stage(intake.stage_code)}
        lines = [
            f"📊 گزارش پیشرفت شما ثبت شد! درصد تحقق: {completion_rate:.1f}%\n",
            f"🔄 برنامه مطالعاتی جدید (ویرایش {plan.revision_no}) بر اساس عملکرد شما بازتنظیم شد:",
            f"⏱ مدت زمان کل روزانه: {sum(it.duration_minutes for it in plan.items)} دقیقه\n",
            self._format_constraints(intake),
        ]
        if missed_units:
            lines.append(f"⚠️ مباحث جبرانی در اولویت: {', '.join(missed_units)}\n")
        lines.append("واحد‌های مطالعاتی بازنگری‌شده:")
        for idx, item in enumerate(plan.items, start=1):
            title = resources[item.resource_version_id]["title"]
            chunks = split_study_sessions([item.model_dump()], intake.max_session_minutes or 60)
            session_text = " + ".join(str(chunk["duration_minutes"]) for chunk in chunks)
            lines.append(
                f"{idx}. {title} — {item.duration_minutes} دقیقه\n"
                f"جلسه‌ها (دقیقه): {session_text}\nشناسه گزارش: {item.resource_version_id}"
            )
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
        self, conn: psycopg.Connection[Any], update: dict[str, Any], test_mode: bool = False
    ) -> dict[str, Any]:
        message = update.get("message")
        if (
            not isinstance(message, dict)
            or type(update.get("update_id")) is not int
            or update["update_id"] < 0
        ):
            return {"status": "ignored", "reason": "malformed_update"}
        chat = message.get("chat")
        sender = message.get("from")
        text = message.get("text")
        if (
            not isinstance(chat, dict)
            or not isinstance(sender, dict)
            or not isinstance(text, str)
            or len(text) > 4096
        ):
            return {"status": "ignored", "reason": "malformed_message"}
        if (
            chat.get("type") != "private"
            or type(chat.get("id")) is not int
            or chat["id"] <= 0
            or type(sender.get("id")) is not int
            or sender.get("id") != chat["id"]
        ):
            return {"status": "ignored", "reason": "private_identity_required"}
        result = await self._handle_telegram_update(conn, update, test_mode)
        if result.get("response_text") and result.get("status") not in (
            "plan_generated",
            "plan_revised",
            "curriculum_completed",
        ):
            self.repo.enqueue_outbox_event(
                conn,
                UUID(result["student_id"]),
                "TELEGRAM_MESSAGE_REQUESTED",
                "telegram_update",
                str(update["update_id"]),
                {"telegram_chat_id": chat["id"], "message_text": result["response_text"]},
            )
        return result

    async def _handle_telegram_update(
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
        if not message or update_id is None:
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

        if isinstance(self.ai_provider, NineRouterProvider):
            self.ai_provider.bind_student(student_id)

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

        # Invalid answers keep the same persisted step; never silently invent intake.
        try:
            if step == "stage":
                self._parse_stage_and_grade(text)
            elif step == "track":
                self._parse_track(text)
            elif step == "capacity":
                self._parse_capacity(text, slots["stage_code"])
            elif step == "goal":
                self._parse_goal(text)
            elif step == "days":
                self._parse_days(text)
            elif step == "session":
                self._parse_session(text, slots["daily_study_capacity_minutes"])
        except ValueError as exc:
            attempts = slots.get("clarification_attempts", 0) + 1
            slots["clarification_attempts"] = attempts
            exhausted = attempts > 2
            self.repo.update_intake_session(
                conn, session["id"], step, slots, is_completed=exhausted
            )
            return {
                "status": "intake_cancelled" if exhausted else "clarification_required",
                "step": step,
                "student_id": str(student_id),
                "response_text": "برای شروع دوباره /start بفرستید." if exhausted else str(exc),
            }
        slots.pop("clarification_attempts", None)

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
            slots["weak_subjects"] = self._parse_weak_subjects(
                text, slots.get("track", "experimental")
            )
            self.repo.update_intake_session(conn, session["id"], "goal", slots)
            return {
                "status": "intake_in_progress",
                "step": "goal",
                "student_id": str(student_id),
                "response_text": "هدف مطالعه شما چیست؟ مدرسه، آزمون یا مرور",
            }

        if step == "goal":
            slots["goal_code"] = self._parse_goal(text)
            self.repo.update_intake_session(conn, session["id"], "days", slots)
            return {
                "status": "intake_in_progress",
                "step": "days",
                "student_id": str(student_id),
                "response_text": "کدام روزها وقت مطالعه دارید؟ "
                "با ویرگول بنویسید؛ مثلاً شنبه،دوشنبه یا هر روز",
            }

        if step == "days":
            slots["study_days"] = self._parse_days(text)
            self.repo.update_intake_session(conn, session["id"], "session", slots)
            return {
                "status": "intake_in_progress",
                "step": "session",
                "student_id": str(student_id),
                "response_text": "حداکثر چند دقیقه در هر جلسه می‌توانید مطالعه کنید؟",
            }

        if step == "session":
            slots["max_session_minutes"] = self._parse_session(
                text, slots["daily_study_capacity_minutes"]
            )

            # Construct validated IntakeSlots
            intake = IntakeSlots(
                stage_code=slots["stage_code"],
                grade=slots["grade"],
                track=slots["track"],
                daily_study_capacity_minutes=slots["daily_study_capacity_minutes"],
                weak_subjects=slots["weak_subjects"],
                goal_code=slots["goal_code"],
                study_days=slots["study_days"],
                max_session_minutes=slots["max_session_minutes"],
            )

            available_resources = get_resources_for_stage(intake.stage_code)

            if not DeterministicRuleFallbackPlanner.generate_fallback_plan(
                intake, available_resources
            )["items"]:
                self.repo.update_intake_session(conn, session["id"], "session", slots)
                return {
                    "status": "resources_unavailable",
                    "student_id": str(student_id),
                    "response_text": "برای پایه، رشته و زمان انتخابی منبع قابل برنامه‌ریزی نداریم. "
                    "اطلاعات شما حفظ شد؛ برای تغییر آن‌ها /start بفرستید.",
                }

            # Generate plan proposal via Proposer (AI)
            proposal = await self.ai_provider.propose_study_plan(intake, available_resources)

            # Authoritative Deterministic Validator Check
            next_rev = self.repo.get_latest_plan_revision(conn, student_id) + 1
            validated_plan: StudyPlan

            validated_plan, proposal = await self.validate_or_repair(
                proposal, intake, available_resources, student_id, next_rev
            )

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
                intake_slots=intake.model_dump(),
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

        return {
            "status": "unknown_step",
            "student_id": str(student_id),
            "response_text": "دستور نامعتبر است.",
        }

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
        self.repo.lock_student(conn, student_id)
        if isinstance(self.ai_provider, NineRouterProvider):
            self.ai_provider.bind_student(student_id)
        active_plan = self.repo.get_active_study_plan(conn, student_id)
        if not active_plan:
            raise ValueError(f"No active study plan found for student {student_id}")

        plan_id = active_plan["id"]
        current_rev = active_plan["revision_no"]
        next_rev = current_rev + 1

        valid_units = {item["resource_version_id"] for item in active_plan["items"]}
        completed_set, missed_set = set(completed_units), set(missed_units)
        if (
            (not completed_set and not missed_set)
            or len(completed_set) != len(completed_units)
            or len(missed_set) != len(missed_units)
            or completed_set & missed_set
            or not (completed_set | missed_set) <= valid_units
            or not 0 <= duration_spent_minutes <= 1440
        ):
            raise HTTPException(
                422,
                "Progress requires unique, disjoint active-plan units; "
                "duration must be 0 to 1440 minutes.",
            )

        telegram_chat_id = telegram_chat_id or self.repo.get_telegram_chat_id(conn, student_id)

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
        slots = active_plan.get("intake_slots") or (
            intake_session["slots"] if intake_session else {}
        )
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
            "goal_code": slots.get("goal_code", "exam"),
            "study_days": slots.get("study_days", list(range(7))),
            "max_session_minutes": slots.get("max_session_minutes"),
        }
        if "guardian_consent" in slots:
            intake_kwargs["guardian_consent"] = slots["guardian_consent"]

        intake = IntakeSlots(**intake_kwargs)

        # 5. Filter available resources: exclude completed, prioritize missed
        stage_resources = get_resources_for_stage(intake.stage_code)
        uncompleted_resources = [
            r
            for r in stage_resources
            if r["resource_id"] not in all_completed
            and r.get("grade", intake.grade) == intake.grade
            and r.get("subject") in TRACK_SUBJECT_ALLOWLIST[intake.track]
        ]
        if not uncompleted_resources:
            response = "همه مباحث این دوره تکمیل شد؛ برنامه جدیدی لازم نیست."
            if telegram_chat_id:
                self.repo.enqueue_outbox_event(
                    conn,
                    student_id,
                    "TELEGRAM_MESSAGE_REQUESTED",
                    "daily_progress",
                    str(progress_id),
                    {"telegram_chat_id": telegram_chat_id, "message_text": response},
                )
            return {
                "status": "curriculum_completed",
                "student_id": str(student_id),
                "progress_id": str(progress_id),
                "response_text": response,
            }

        missed_set = set(missed_units)
        prioritized_resources = sorted(
            uncompleted_resources,
            key=lambda r: 0 if r["resource_id"] in missed_set else 1,
        )

        # 6. Propose revised plan (AI or deterministic fallback)
        proposal = await self.ai_provider.propose_study_plan(
            intake, prioritized_resources, completed_unit_ids=all_completed
        )
        validated_plan: StudyPlan

        validated_plan, proposal = await self.validate_or_repair(
            proposal, intake, prioritized_resources, student_id, next_rev, all_completed
        )

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
            intake_slots=intake.model_dump(),
        )

        # 8. Enqueue Outbox delivery event
        formatted_message = self._format_revision_message(
            validated_plan, intake, completion_rate, missed_units
        )
        self.repo.enqueue_outbox_event(
            conn=conn,
            student_id=student_id,
            event_type="STUDY_PLAN_REVISION_REQUESTED",
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
            "student_id": str(student_id),
            "progress_id": str(progress_id),
            "plan_id": str(validated_plan.plan_id),
            "revision_no": next_rev,
            "completion_rate": completion_rate,
            "response_text": formatted_message,
        }

    async def validate_or_repair(
        self,
        proposal: dict[str, Any],
        intake: IntakeSlots,
        resources: list[dict[str, Any]],
        student_id: UUID,
        revision_no: int,
        completed: Optional[set[str]] = None,
    ) -> tuple[StudyPlan, dict[str, Any]]:
        catalog = get_default_catalog()
        # ponytail: two fresh proposals; add structured repair feedback with provider support.
        for attempt in range(3):
            try:
                plan = DeterministicValidator.validate_and_parse_proposal(
                    proposal, intake, catalog, student_id, revision_no, completed_unit_ids=completed
                )
                return plan, proposal
            except (ValueError, DeterministicValidationError):
                if attempt < 2:
                    proposal = await self.ai_provider.propose_study_plan(
                        intake, resources, completed_unit_ids=completed
                    )
        fallback = DeterministicRuleFallbackPlanner.generate_fallback_plan(
            intake, resources, completed_unit_ids=completed
        )
        if not fallback["items"]:
            raise HTTPException(
                422, "No trusted resources fit the supplied intake and daily capacity."
            )
        return DeterministicValidator.validate_and_parse_proposal(
            fallback, intake, catalog, student_id, revision_no, completed_unit_ids=completed
        ), fallback
