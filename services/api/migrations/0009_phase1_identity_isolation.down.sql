ALTER TABLE daily_progress_logs DROP CONSTRAINT fk_daily_progress_plan_owner_revision;
ALTER TABLE study_plan_items DROP CONSTRAINT fk_study_plan_items_owner;
ALTER TABLE study_plans
    DROP CONSTRAINT uq_study_plans_owner_revision,
    DROP CONSTRAINT uq_study_plans_owner;
ALTER TABLE students
    DROP CONSTRAINT ck_students_private_identity,
    DROP CONSTRAINT uq_students_telegram_user;
