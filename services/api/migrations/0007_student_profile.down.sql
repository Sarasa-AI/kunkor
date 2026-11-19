-- 0007_student_profile.down.sql
-- Remove grade, track, and guardian_consent columns from students table

DROP INDEX IF EXISTS idx_students_grade;
DROP INDEX IF EXISTS idx_students_track;

ALTER TABLE students
    DROP CONSTRAINT IF EXISTS chk_students_grade,
    DROP CONSTRAINT IF EXISTS chk_students_track,
    DROP COLUMN IF EXISTS grade,
    DROP COLUMN IF EXISTS track,
    DROP COLUMN IF EXISTS guardian_consent;