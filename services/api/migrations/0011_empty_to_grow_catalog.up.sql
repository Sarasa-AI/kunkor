-- Empty-to-grow content: optional hierarchy, owner workflow, independent usage grants.
-- No educational rows are inserted by this migration.
-- Explicit text arrays keep check constraint expressions identical after dump/restore.
-- PostgreSQL otherwise rewrites implicit VARCHAR array casts while reloading the schema.
ALTER TABLE books ALTER COLUMN subject_id DROP NOT NULL;
ALTER TABLE books ALTER COLUMN publisher SET DEFAULT '';
ALTER TABLE chapters ALTER COLUMN edition_id DROP NOT NULL;
ALTER TABLE chapters ALTER COLUMN number DROP NOT NULL;
ALTER TABLE chapters ALTER COLUMN title SET DEFAULT '';
ALTER TABLE lessons ALTER COLUMN chapter_id DROP NOT NULL;
ALTER TABLE lessons ALTER COLUMN number DROP NOT NULL;
ALTER TABLE lessons ALTER COLUMN title SET DEFAULT '';
ALTER TABLE page_sections ALTER COLUMN lesson_id DROP NOT NULL;
ALTER TABLE books ADD COLUMN subject_code VARCHAR(100);
ALTER TABLE chapters ADD COLUMN book_id UUID REFERENCES books(id) ON DELETE CASCADE;
ALTER TABLE lessons ADD COLUMN book_id UUID REFERENCES books(id) ON DELETE CASCADE;
ALTER TABLE page_sections ADD COLUMN book_id UUID REFERENCES books(id) ON DELETE CASCADE;
ALTER TABLE page_sections ADD COLUMN chapter_id UUID REFERENCES chapters(id) ON DELETE CASCADE;
ALTER TABLE page_sections ADD COLUMN unit_kind VARCHAR(20) NOT NULL DEFAULT 'section'
    CHECK (unit_kind::text = ANY (ARRAY['section', 'topic']::text[]));
ALTER TABLE page_sections ADD COLUMN number INT;
ALTER TABLE page_sections ADD COLUMN page_start INT;
ALTER TABLE page_sections ADD COLUMN page_end INT;
ALTER TABLE page_sections ADD COLUMN estimated_duration_minutes INT;
ALTER TABLE page_sections ADD COLUMN prerequisites UUID[] NOT NULL DEFAULT '{}';
ALTER TABLE chapters ADD COLUMN estimated_duration_minutes INT;
DROP TRIGGER IF EXISTS trg_chapters_append_only ON chapters;
DROP TRIGGER IF EXISTS trg_lessons_append_only ON lessons;
DROP TRIGGER IF EXISTS trg_page_sections_append_only ON page_sections;

ALTER TABLE books ADD COLUMN owner_identity TEXT NOT NULL DEFAULT 'legacy_unattributed';
ALTER TABLE books ADD COLUMN approved_by TEXT;
ALTER TABLE books ADD COLUMN approved_at TIMESTAMPTZ;
ALTER TABLE books ADD COLUMN license_active BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE books ADD COLUMN exercise_start INT;
ALTER TABLE books ADD COLUMN exercise_end INT;
ALTER TABLE books ADD CONSTRAINT ck_books_owner_status
    CHECK (status::text = ANY (ARRAY['draft','pending_review','approved','published','archived','rejected','superseded']::text[]));
ALTER TABLE books ADD CONSTRAINT ck_books_exercise_range
    CHECK ((exercise_start IS NULL OR exercise_start > 0)
       AND (exercise_end IS NULL OR exercise_end > 0)
       AND (exercise_start IS NULL OR exercise_end IS NULL OR exercise_end >= exercise_start));

ALTER TABLE chapters ADD COLUMN owner_identity TEXT NOT NULL DEFAULT 'legacy_unattributed';
ALTER TABLE chapters ADD COLUMN approved_by TEXT;
ALTER TABLE chapters ADD COLUMN approved_at TIMESTAMPTZ;
ALTER TABLE chapters ADD COLUMN license_active BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE chapters ADD COLUMN exercise_start INT;
ALTER TABLE chapters ADD COLUMN exercise_end INT;
ALTER TABLE chapters ADD CONSTRAINT ck_chapters_owner_status
    CHECK (status::text = ANY (ARRAY['draft','pending_review','approved','published','archived','rejected','superseded']::text[]));
ALTER TABLE chapters ADD CONSTRAINT ck_chapters_exercise_range
    CHECK ((exercise_start IS NULL OR exercise_start > 0)
       AND (exercise_end IS NULL OR exercise_end > 0)
       AND (exercise_start IS NULL OR exercise_end IS NULL OR exercise_end >= exercise_start));

ALTER TABLE lessons ADD COLUMN owner_identity TEXT NOT NULL DEFAULT 'legacy_unattributed';
ALTER TABLE lessons ADD COLUMN approved_by TEXT;
ALTER TABLE lessons ADD COLUMN approved_at TIMESTAMPTZ;
ALTER TABLE lessons ADD COLUMN license_active BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE lessons ADD COLUMN exercise_start INT;
ALTER TABLE lessons ADD COLUMN exercise_end INT;
ALTER TABLE lessons ADD CONSTRAINT ck_lessons_owner_status
    CHECK (status::text = ANY (ARRAY['draft','pending_review','approved','published','archived','rejected','superseded']::text[]));
ALTER TABLE lessons ADD CONSTRAINT ck_lessons_exercise_range
    CHECK ((exercise_start IS NULL OR exercise_start > 0)
       AND (exercise_end IS NULL OR exercise_end > 0)
       AND (exercise_start IS NULL OR exercise_end IS NULL OR exercise_end >= exercise_start));

ALTER TABLE page_sections ADD COLUMN owner_identity TEXT NOT NULL DEFAULT 'legacy_unattributed';
ALTER TABLE page_sections ADD COLUMN approved_by TEXT;
ALTER TABLE page_sections ADD COLUMN approved_at TIMESTAMPTZ;
ALTER TABLE page_sections ADD COLUMN license_active BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE page_sections ADD COLUMN exercise_start INT;
ALTER TABLE page_sections ADD COLUMN exercise_end INT;
ALTER TABLE page_sections ADD CONSTRAINT ck_page_sections_owner_status
    CHECK (status::text = ANY (ARRAY['draft','pending_review','approved','published','archived','rejected','superseded']::text[]));
ALTER TABLE page_sections ADD CONSTRAINT ck_page_sections_exercise_range
    CHECK ((exercise_start IS NULL OR exercise_start > 0)
       AND (exercise_end IS NULL OR exercise_end > 0)
       AND (exercise_start IS NULL OR exercise_end IS NULL OR exercise_end >= exercise_start));

ALTER TABLE chapters ADD CONSTRAINT ck_chapters_page_range
    CHECK ((page_start IS NULL OR page_start > 0)
       AND (page_end IS NULL OR page_end > 0)
       AND (page_start IS NULL OR page_end IS NULL OR page_end >= page_start));
ALTER TABLE chapters ADD CONSTRAINT ck_chapters_nonnegative_counts
    CHECK ((question_count IS NULL OR question_count >= 0)
       AND (estimated_duration_minutes IS NULL OR estimated_duration_minutes > 0)
       AND (number IS NULL OR number > 0));
CREATE INDEX idx_chapters_direct_book ON chapters(book_id);

ALTER TABLE lessons ADD CONSTRAINT ck_lessons_page_range
    CHECK ((page_start IS NULL OR page_start > 0)
       AND (page_end IS NULL OR page_end > 0)
       AND (page_start IS NULL OR page_end IS NULL OR page_end >= page_start));
ALTER TABLE lessons ADD CONSTRAINT ck_lessons_nonnegative_counts
    CHECK ((question_count IS NULL OR question_count >= 0)
       AND (estimated_duration_minutes IS NULL OR estimated_duration_minutes > 0)
       AND (number IS NULL OR number > 0));
CREATE INDEX idx_lessons_direct_book ON lessons(book_id);

ALTER TABLE page_sections ADD CONSTRAINT ck_page_sections_page_range
    CHECK ((page_start IS NULL OR page_start > 0)
       AND (page_end IS NULL OR page_end > 0)
       AND (page_start IS NULL OR page_end IS NULL OR page_end >= page_start));
ALTER TABLE page_sections ADD CONSTRAINT ck_page_sections_nonnegative_counts
    CHECK ((question_count IS NULL OR question_count >= 0)
       AND (estimated_duration_minutes IS NULL OR estimated_duration_minutes > 0)
       AND (number IS NULL OR number > 0));
CREATE INDEX idx_page_sections_direct_book ON page_sections(book_id);

CREATE UNIQUE INDEX uq_chapters_direct_book_number ON chapters(book_id, number)
    WHERE edition_id IS NULL;
CREATE UNIQUE INDEX uq_lessons_direct_book_number ON lessons(book_id, number)
    WHERE chapter_id IS NULL;
ALTER TABLE books ADD CONSTRAINT ck_books_page_count CHECK (page_count IS NULL OR page_count >= 0);

CREATE TABLE content_audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL,
    entity_type TEXT NOT NULL,
    actor_identity TEXT NOT NULL,
    action TEXT NOT NULL,
    before_record JSONB,
    after_record JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX idx_content_audit_entity ON content_audit_events(entity_id, occurred_at);
CREATE TRIGGER trg_content_audit_append_only BEFORE UPDATE OR DELETE ON content_audit_events
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();
CREATE FUNCTION audit_content_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO content_audit_events(entity_id, entity_type, actor_identity, action,
                                    before_record, after_record, occurred_at)
    VALUES (COALESCE(NEW.id, OLD.id), TG_TABLE_NAME,
            COALESCE(NULLIF(current_setting('app.content_actor', true), ''), 'database_operator'),
            TG_OP, CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END,
            CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END, clock_timestamp());
    RETURN COALESCE(NEW, OLD);
END;
$$;
CREATE TRIGGER trg_books_content_audit AFTER INSERT OR UPDATE OR DELETE ON books
FOR EACH ROW EXECUTE FUNCTION audit_content_change();
CREATE TRIGGER trg_chapters_content_audit AFTER INSERT OR UPDATE OR DELETE ON chapters
FOR EACH ROW EXECUTE FUNCTION audit_content_change();
CREATE TRIGGER trg_lessons_content_audit AFTER INSERT OR UPDATE OR DELETE ON lessons
FOR EACH ROW EXECUTE FUNCTION audit_content_change();
CREATE TRIGGER trg_page_sections_content_audit AFTER INSERT OR UPDATE OR DELETE ON page_sections
FOR EACH ROW EXECUTE FUNCTION audit_content_change();

CREATE VIEW v_content_units AS
SELECT c.id, COALESCE(c.book_id, e.book_id) AS book_id, 'chapter'::text AS kind,
       NULL::uuid AS parent_id, c.number, c.title, c.page_start, c.page_end,
       c.exercise_start, c.exercise_end, c.question_count, c.estimated_duration_minutes,
       c.prerequisites, c.provenance_source, c.provenance_reference, c.provenance_license_id,
       c.provenance_rights_statement, c.provenance_verified_by, c.provenance_verified_at,
       c.provenance_verification_status, c.provenance_notes, c.version, c.status,
       c.owner_identity, c.approved_by, c.approved_at, c.license_active,
       c.created_at, c.updated_at, c.published_at,
       COALESCE(e.status IN ('archived','rejected','superseded'), FALSE) AS ancestor_hidden
FROM chapters c LEFT JOIN editions e ON e.id = c.edition_id
UNION ALL
SELECT l.id, COALESCE(l.book_id, c.book_id, e.book_id), 'lesson', l.chapter_id,
       l.number, l.title, l.page_start, l.page_end,
       l.exercise_start, l.exercise_end, l.question_count, l.estimated_duration_minutes,
       l.prerequisites, l.provenance_source, l.provenance_reference, l.provenance_license_id,
       l.provenance_rights_statement, l.provenance_verified_by, l.provenance_verified_at,
       l.provenance_verification_status, l.provenance_notes, l.version, l.status,
       l.owner_identity, l.approved_by, l.approved_at, l.license_active,
       l.created_at, l.updated_at, l.published_at,
       COALESCE(c.status IN ('archived','rejected','superseded'), FALSE)
       OR COALESCE(e.status IN ('archived','rejected','superseded'), FALSE)
FROM lessons l LEFT JOIN chapters c ON c.id = l.chapter_id
LEFT JOIN editions e ON e.id = c.edition_id
UNION ALL
SELECT s.id, COALESCE(s.book_id, l.book_id, c.book_id, e.book_id), s.unit_kind,
       COALESCE(s.lesson_id, s.chapter_id), s.number, COALESCE(s.section_title, ''),
       COALESCE(s.page_start, s.page_number), COALESCE(s.page_end, s.page_number),
       s.exercise_start, s.exercise_end, s.question_count, s.estimated_duration_minutes,
       s.prerequisites, s.provenance_source, s.provenance_reference, s.provenance_license_id,
       s.provenance_rights_statement, s.provenance_verified_by, s.provenance_verified_at,
       s.provenance_verification_status, s.provenance_notes, s.version, s.status,
       s.owner_identity, s.approved_by, s.approved_at, s.license_active,
       s.created_at, s.updated_at, s.published_at,
       COALESCE(l.status IN ('archived','rejected','superseded'), FALSE)
       OR COALESCE(c.status IN ('archived','rejected','superseded'), FALSE)
       OR COALESCE(e.status IN ('archived','rejected','superseded'), FALSE)
FROM page_sections s LEFT JOIN lessons l ON l.id = s.lesson_id
LEFT JOIN chapters c ON c.id = COALESCE(l.chapter_id, s.chapter_id)
LEFT JOIN editions e ON e.id = c.edition_id;

CREATE VIEW v_trusted_content_units AS
SELECT u.* FROM v_content_units u JOIN books b ON b.id = u.book_id
WHERE u.status = 'published' AND u.published_at IS NOT NULL
  AND u.approved_at IS NOT NULL AND NULLIF(BTRIM(u.approved_by), '') IS NOT NULL
  AND u.provenance_verification_status = 'verified'
  AND u.provenance_source NOT IN ('no_source','local_synthetic_fixture')
  AND NULLIF(BTRIM(u.provenance_reference), '') IS NOT NULL
  AND NULLIF(BTRIM(u.provenance_license_id), '') IS NOT NULL
  AND NULLIF(BTRIM(u.provenance_rights_statement), '') IS NOT NULL
  AND u.license_active AND NOT u.ancestor_hidden
  AND b.status NOT IN ('archived','rejected','superseded');

CREATE OR REPLACE VIEW v_published_books AS
SELECT b.id, b.title, b.publisher, b.edition, b.grade_10, b.grade_11, b.grade_12, b.track,
       b.provenance_source, b.provenance_reference, b.provenance_license_id,
       b.provenance_rights_statement, b.provenance_verified_by, b.provenance_verified_at,
       b.provenance_verification_status, b.provenance_notes, b.page_count, b.version,
       b.published_at,
       (SELECT COUNT(*) FROM v_trusted_content_units u
        WHERE u.book_id = b.id AND u.kind = 'chapter') AS chapter_count
FROM books b WHERE b.status = 'published' AND b.published_at IS NOT NULL
  AND b.approved_at IS NOT NULL AND NULLIF(BTRIM(b.approved_by), '') IS NOT NULL
  AND b.provenance_verification_status = 'verified'
  AND b.provenance_source NOT IN ('no_source','local_synthetic_fixture')
  AND NULLIF(BTRIM(b.provenance_reference), '') IS NOT NULL
  AND NULLIF(BTRIM(b.provenance_license_id), '') IS NOT NULL
  AND NULLIF(BTRIM(b.provenance_rights_statement), '') IS NOT NULL AND b.license_active;

CREATE OR REPLACE VIEW v_published_chapters AS
SELECT c.id, c.edition_id, c.number, c.title, c.page_start, c.page_end, c.question_count,
       c.prerequisites, c.provenance_source, c.provenance_reference, c.provenance_license_id,
       c.provenance_rights_statement, c.provenance_verified_by, c.provenance_verified_at,
       c.provenance_verification_status, c.provenance_notes, c.version, c.published_at
FROM chapters c JOIN v_trusted_content_units u ON u.id = c.id AND u.kind = 'chapter';
CREATE OR REPLACE VIEW v_published_lessons AS
SELECT l.id, l.chapter_id, l.number, l.title, l.page_start, l.page_end,
       l.estimated_duration_minutes, l.question_count, l.prerequisites, l.learning_objectives,
       l.provenance_source, l.provenance_reference, l.provenance_license_id,
       l.provenance_rights_statement, l.provenance_verified_by, l.provenance_verified_at,
       l.provenance_verification_status, l.provenance_notes, l.version, l.published_at
FROM lessons l JOIN v_trusted_content_units u ON u.id = l.id AND u.kind = 'lesson';
