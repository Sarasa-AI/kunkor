-- 0003_daily_progress_and_revisions.up.sql
-- Daily progress logs with append-only immutability and multi-day revision tracking

CREATE TABLE IF NOT EXISTS daily_progress_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    plan_id UUID NOT NULL REFERENCES study_plans(id) ON DELETE CASCADE,
    revision_no INT NOT NULL,
    completed_units JSONB NOT NULL DEFAULT '[]'::jsonb,
    missed_units JSONB NOT NULL DEFAULT '[]'::jsonb,
    duration_spent_minutes INT NOT NULL DEFAULT 0,
    completion_rate NUMERIC(5, 2) NOT NULL DEFAULT 0.0,
    student_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_daily_progress_student ON daily_progress_logs (student_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_daily_progress_plan ON daily_progress_logs (plan_id, created_at DESC);

-- Append-only trigger: Historical progress logs are immutable (ADR-0005)
DROP TRIGGER IF EXISTS trg_daily_progress_logs_append_only ON daily_progress_logs;
CREATE TRIGGER trg_daily_progress_logs_append_only
BEFORE UPDATE OR DELETE ON daily_progress_logs
FOR EACH ROW
EXECUTE FUNCTION prevent_append_only_mutation();
