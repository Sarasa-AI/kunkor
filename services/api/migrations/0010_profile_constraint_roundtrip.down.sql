-- Restore exactly the constraint expressions introduced by 0007.
ALTER TABLE students
    DROP CONSTRAINT chk_students_grade,
    DROP CONSTRAINT chk_students_track,
    ADD CONSTRAINT chk_students_grade CHECK (
        grade IS NULL OR grade IN ('G10', 'G11', 'G12')
    ),
    ADD CONSTRAINT chk_students_track CHECK (
        track IS NULL OR track IN ('general', 'mathematics', 'experimental', 'humanities')
    );
