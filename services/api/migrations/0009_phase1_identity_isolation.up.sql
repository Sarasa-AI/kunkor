-- Fail on conflicting legacy data; never infer or rewrite identity ownership.
ALTER TABLE students
    ADD CONSTRAINT uq_students_telegram_user UNIQUE (telegram_user_id),
    ADD CONSTRAINT ck_students_private_identity CHECK (
        telegram_user_id IS NOT NULL AND telegram_user_id > 0
        AND telegram_chat_id = telegram_user_id
    );

ALTER TABLE study_plans
    ADD CONSTRAINT uq_study_plans_owner UNIQUE (id, student_id),
    ADD CONSTRAINT uq_study_plans_owner_revision UNIQUE (id, student_id, revision_no);

ALTER TABLE study_plan_items
    ADD CONSTRAINT fk_study_plan_items_owner
    FOREIGN KEY (plan_id, student_id) REFERENCES study_plans(id, student_id)
    ON DELETE CASCADE;

ALTER TABLE daily_progress_logs
    ADD CONSTRAINT fk_daily_progress_plan_owner_revision
    FOREIGN KEY (plan_id, student_id, revision_no)
    REFERENCES study_plans(id, student_id, revision_no) ON DELETE CASCADE;
