-- Fail migration on conflicting legacy active rows; never silently discard data.
CREATE UNIQUE INDEX uq_student_active_plan ON study_plans(student_id) WHERE status = 'active';
CREATE UNIQUE INDEX uq_student_active_intake ON intake_sessions(student_id) WHERE NOT is_completed;
ALTER TABLE study_plans ADD COLUMN intake_slots JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE outbox_events ADD COLUMN next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE outbox_events ADD COLUMN last_error TEXT;
ALTER TABLE outbox_events ADD COLUMN telegram_message_id BIGINT;
