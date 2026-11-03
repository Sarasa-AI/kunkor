ALTER TABLE outbox_events DROP COLUMN telegram_message_id, DROP COLUMN last_error, DROP COLUMN next_attempt_at;
ALTER TABLE study_plans DROP COLUMN intake_slots;
DROP INDEX uq_student_active_intake;
DROP INDEX uq_student_active_plan;
