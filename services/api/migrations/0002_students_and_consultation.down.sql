-- 0002_students_and_consultation.down.sql
-- Revert student identity, Telegram linking, consultation intake, and versioned study plans

DROP TABLE IF EXISTS study_plan_items CASCADE;
DROP TABLE IF EXISTS study_plans CASCADE;
DROP TABLE IF EXISTS intake_sessions CASCADE;
DROP TABLE IF EXISTS students CASCADE;
