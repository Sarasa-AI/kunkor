-- Restore the previous schema only when no owner-managed data would be discarded.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM books WHERE subject_id IS NULL OR owner_identity <> 'legacy_unattributed')
       OR EXISTS (SELECT 1 FROM chapters WHERE edition_id IS NULL OR number IS NULL
                  OR owner_identity <> 'legacy_unattributed')
       OR EXISTS (SELECT 1 FROM lessons WHERE chapter_id IS NULL OR number IS NULL
                  OR owner_identity <> 'legacy_unattributed')
       OR EXISTS (SELECT 1 FROM page_sections WHERE lesson_id IS NULL
                  OR owner_identity <> 'legacy_unattributed')
       OR EXISTS (SELECT 1 FROM content_audit_events) THEN
        RAISE EXCEPTION 'Owner-managed catalog data exists: rollback requires a data-preserving plan';
    END IF;
END $$;
DROP VIEW v_published_books;
DROP VIEW v_published_chapters;
DROP VIEW v_published_lessons;
DROP VIEW v_trusted_content_units;
DROP VIEW v_content_units;
DROP TRIGGER trg_books_content_audit ON books;
DROP TRIGGER trg_chapters_content_audit ON chapters;
DROP TRIGGER trg_lessons_content_audit ON lessons;
DROP TRIGGER trg_page_sections_content_audit ON page_sections;
DROP FUNCTION audit_content_change();
DROP TABLE content_audit_events;
ALTER TABLE books DROP COLUMN owner_identity;
ALTER TABLE books DROP COLUMN approved_by;
ALTER TABLE books DROP COLUMN approved_at;
ALTER TABLE books DROP COLUMN license_active;
ALTER TABLE books DROP COLUMN exercise_start;
ALTER TABLE books DROP COLUMN exercise_end;
ALTER TABLE books DROP CONSTRAINT ck_books_owner_status;
ALTER TABLE chapters DROP COLUMN owner_identity;
ALTER TABLE chapters DROP COLUMN approved_by;
ALTER TABLE chapters DROP COLUMN approved_at;
ALTER TABLE chapters DROP COLUMN license_active;
ALTER TABLE chapters DROP COLUMN exercise_start;
ALTER TABLE chapters DROP COLUMN exercise_end;
ALTER TABLE chapters DROP CONSTRAINT ck_chapters_owner_status;
ALTER TABLE lessons DROP COLUMN owner_identity;
ALTER TABLE lessons DROP COLUMN approved_by;
ALTER TABLE lessons DROP COLUMN approved_at;
ALTER TABLE lessons DROP COLUMN license_active;
ALTER TABLE lessons DROP COLUMN exercise_start;
ALTER TABLE lessons DROP COLUMN exercise_end;
ALTER TABLE lessons DROP CONSTRAINT ck_lessons_owner_status;
ALTER TABLE page_sections DROP COLUMN owner_identity;
ALTER TABLE page_sections DROP COLUMN approved_by;
ALTER TABLE page_sections DROP COLUMN approved_at;
ALTER TABLE page_sections DROP COLUMN license_active;
ALTER TABLE page_sections DROP COLUMN exercise_start;
ALTER TABLE page_sections DROP COLUMN exercise_end;
ALTER TABLE page_sections DROP CONSTRAINT ck_page_sections_owner_status;
ALTER TABLE chapters DROP CONSTRAINT ck_chapters_page_range;
ALTER TABLE chapters DROP CONSTRAINT ck_chapters_nonnegative_counts;
ALTER TABLE chapters DROP COLUMN book_id;
CREATE TRIGGER trg_chapters_append_only BEFORE UPDATE OR DELETE ON chapters
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();
ALTER TABLE lessons DROP CONSTRAINT ck_lessons_page_range;
ALTER TABLE lessons DROP CONSTRAINT ck_lessons_nonnegative_counts;
ALTER TABLE lessons DROP COLUMN book_id;
CREATE TRIGGER trg_lessons_append_only BEFORE UPDATE OR DELETE ON lessons
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();
ALTER TABLE page_sections DROP CONSTRAINT ck_page_sections_page_range;
ALTER TABLE page_sections DROP CONSTRAINT ck_page_sections_nonnegative_counts;
ALTER TABLE page_sections DROP COLUMN book_id;
CREATE TRIGGER trg_page_sections_append_only BEFORE UPDATE OR DELETE ON page_sections
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();
ALTER TABLE books DROP COLUMN subject_code;
ALTER TABLE books DROP CONSTRAINT ck_books_page_count;
ALTER TABLE books ALTER COLUMN subject_id SET NOT NULL;
ALTER TABLE books ALTER COLUMN publisher DROP DEFAULT;
ALTER TABLE chapters ALTER COLUMN edition_id SET NOT NULL;
ALTER TABLE chapters ALTER COLUMN number SET NOT NULL;
ALTER TABLE chapters ALTER COLUMN title DROP DEFAULT;
ALTER TABLE chapters DROP COLUMN estimated_duration_minutes;
ALTER TABLE lessons ALTER COLUMN chapter_id SET NOT NULL;
ALTER TABLE lessons ALTER COLUMN number SET NOT NULL;
ALTER TABLE lessons ALTER COLUMN title DROP DEFAULT;
ALTER TABLE page_sections ALTER COLUMN lesson_id SET NOT NULL;
ALTER TABLE page_sections DROP COLUMN chapter_id;
ALTER TABLE page_sections DROP COLUMN unit_kind;
ALTER TABLE page_sections DROP COLUMN number;
ALTER TABLE page_sections DROP COLUMN page_start;
ALTER TABLE page_sections DROP COLUMN page_end;
ALTER TABLE page_sections DROP COLUMN estimated_duration_minutes;
ALTER TABLE page_sections DROP COLUMN prerequisites;
CREATE OR REPLACE VIEW v_published_books AS
SELECT
    b.id,
    b.title,
    b.publisher,
    b.edition,
    b.grade_10,
    b.grade_11,
    b.grade_12,
    b.track,
    b.provenance_source,
    b.provenance_reference,
    b.provenance_license_id,
    b.provenance_rights_statement,
    b.provenance_verified_by,
    b.provenance_verified_at,
    b.provenance_verification_status,
    b.provenance_notes,
    b.page_count,
    b.version,
    b.published_at,
    (SELECT COUNT(*) FROM chapters c WHERE c.edition_id = e.id AND c.status = 'published' AND c.published_at IS NOT NULL) AS chapter_count
FROM books b
JOIN editions e ON e.book_id = b.id AND e.status = 'published' AND e.published_at IS NOT NULL
WHERE b.status = 'published' AND b.published_at IS NOT NULL;

CREATE OR REPLACE VIEW v_published_chapters AS
SELECT
    c.id,
    c.edition_id,
    c.number,
    c.title,
    c.page_start,
    c.page_end,
    c.question_count,
    c.prerequisites,
    c.provenance_source,
    c.provenance_reference,
    c.provenance_license_id,
    c.provenance_rights_statement,
    c.provenance_verified_by,
    c.provenance_verified_at,
    c.provenance_verification_status,
    c.provenance_notes,
    c.version,
    c.published_at
FROM chapters c
WHERE c.status = 'published' AND c.published_at IS NOT NULL;

CREATE OR REPLACE VIEW v_published_lessons AS
SELECT
    l.id,
    l.chapter_id,
    l.number,
    l.title,
    l.page_start,
    l.page_end,
    l.estimated_duration_minutes,
    l.question_count,
    l.prerequisites,
    l.learning_objectives,
    l.provenance_source,
    l.provenance_reference,
    l.provenance_license_id,
    l.provenance_rights_statement,
    l.provenance_verified_by,
    l.provenance_verified_at,
    l.provenance_verification_status,
    l.provenance_notes,
    l.version,
    l.published_at
FROM lessons l
WHERE l.status = 'published' AND l.published_at IS NOT NULL;