-- 0002_students_and_consultation.up.sql
-- Student identity, Telegram linking, consultation intake, and versioned study plans

CREATE TABLE IF NOT EXISTS students (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_chat_id BIGINT UNIQUE NOT NULL,
    telegram_user_id BIGINT,
    telegram_username VARCHAR(100),
    first_name VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_students_tg_chat ON students (telegram_chat_id);

CREATE TABLE IF NOT EXISTS intake_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    current_step VARCHAR(50) NOT NULL DEFAULT 'stage',
    slots JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_completed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intake_sessions_student_active
ON intake_sessions (student_id) WHERE is_completed = FALSE;

CREATE TABLE IF NOT EXISTS study_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    revision_no INT NOT NULL DEFAULT 1,
    stage_code VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    engine_version VARCHAR(50) NOT NULL DEFAULT '0.5.0',
    rule_set_version VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    raw_proposal JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_study_plans_student_revision UNIQUE (student_id, revision_no)
);

CREATE INDEX IF NOT EXISTS idx_study_plans_student ON study_plans (student_id, revision_no DESC);

CREATE TABLE IF NOT EXISTS study_plan_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    item_order INT NOT NULL,
    resource_version_id VARCHAR(100) NOT NULL,
    stage_code VARCHAR(50) NOT NULL,
    duration_minutes INT NOT NULL,
    prerequisites JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_study_plan_items_plan ON study_plan_items (plan_id, item_order ASC);
CREATE INDEX IF NOT EXISTS idx_study_plan_items_student ON study_plan_items (student_id);
