-- 0007_student_profile.up.sql
-- Add grade, track, and guardian_consent columns to students table

ALTER TABLE students
    ADD COLUMN IF NOT EXISTS grade VARCHAR(10),
    ADD COLUMN IF NOT EXISTS track VARCHAR(50),
    ADD COLUMN IF NOT EXISTS guardian_consent BOOLEAN;

-- Add index for common queries
CREATE INDEX IF NOT EXISTS idx_students_grade ON students (grade) WHERE grade IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_students_track ON students (track) WHERE track IS NOT NULL;

-- Add CHECK constraints for valid grades and tracks
ALTER TABLE students
    ADD CONSTRAINT chk_students_grade CHECK (
        grade IS NULL OR grade IN ('G10', 'G11', 'G12')
    );

ALTER TABLE students
    ADD CONSTRAINT chk_students_track CHECK (
        track IS NULL OR track IN ('general', 'mathematics', 'experimental', 'humanities')
    );