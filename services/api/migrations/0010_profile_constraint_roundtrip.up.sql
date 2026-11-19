-- P1-C03: Preserve the 0007 value sets with dump/restore-stable expressions.
-- Explicit text literals avoid PostgreSQL's VARCHAR-array cast rewrite on reload.
-- Validate existing rows; never modify student data or historical migrations.
ALTER TABLE students
    DROP CONSTRAINT chk_students_grade,
    DROP CONSTRAINT chk_students_track,
    ADD CONSTRAINT chk_students_grade CHECK (
        grade IS NULL OR grade::text IN ('G10'::text, 'G11'::text, 'G12'::text)
    ),
    ADD CONSTRAINT chk_students_track CHECK (
        track IS NULL OR track::text IN (
            'general'::text, 'mathematics'::text, 'experimental'::text, 'humanities'::text
        )
    );
