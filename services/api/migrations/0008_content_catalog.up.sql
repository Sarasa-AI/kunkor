-- 0008_content_catalog.up.sql
-- Versioned Educational Content Catalog
-- Hierarchy: Curriculum → Subject → Book → Edition → Chapter → Lesson → PageSection → Question

-- 1. Curricula table
CREATE TABLE IF NOT EXISTS curricula (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    provenance_source VARCHAR(50) NOT NULL DEFAULT 'no_source',
    provenance_reference VARCHAR(500),
    provenance_license_id VARCHAR(200),
    provenance_rights_statement TEXT,
    provenance_verified_by VARCHAR(200),
    provenance_verified_at TIMESTAMPTZ,
    provenance_verification_status VARCHAR(50) NOT NULL DEFAULT 'unverified',
    provenance_notes TEXT,
    version VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_curricula_code ON curricula (code);
CREATE INDEX IF NOT EXISTS idx_curricula_status ON curricula (status);

-- 2. Subjects table
CREATE TABLE IF NOT EXISTS subjects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    curriculum_id UUID NOT NULL REFERENCES curricula(id) ON DELETE CASCADE,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    provenance_source VARCHAR(50) NOT NULL DEFAULT 'no_source',
    provenance_reference VARCHAR(500),
    provenance_license_id VARCHAR(200),
    provenance_rights_statement TEXT,
    provenance_verified_by VARCHAR(200),
    provenance_verified_at TIMESTAMPTZ,
    provenance_verification_status VARCHAR(50) NOT NULL DEFAULT 'unverified',
    provenance_notes TEXT,
    version VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_subjects_curriculum_code ON subjects (curriculum_id, code);
CREATE INDEX IF NOT EXISTS idx_subjects_curriculum ON subjects (curriculum_id);
CREATE INDEX IF NOT EXISTS idx_subjects_status ON subjects (status);

-- 3. Books table
CREATE TABLE IF NOT EXISTS books (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id UUID NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    publisher VARCHAR(200) NOT NULL,
    isbn VARCHAR(50),
    edition VARCHAR(50),
    grade_10 BOOLEAN NOT NULL DEFAULT FALSE,
    grade_11 BOOLEAN NOT NULL DEFAULT FALSE,
    grade_12 BOOLEAN NOT NULL DEFAULT FALSE,
    track VARCHAR(50),
    provenance_source VARCHAR(50) NOT NULL DEFAULT 'no_source',
    provenance_reference VARCHAR(500),
    provenance_license_id VARCHAR(200),
    provenance_rights_statement TEXT,
    provenance_verified_by VARCHAR(200),
    provenance_verified_at TIMESTAMPTZ,
    provenance_verification_status VARCHAR(50) NOT NULL DEFAULT 'unverified',
    provenance_notes TEXT,
    page_count INT,
    version VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_books_subject ON books (subject_id);
CREATE INDEX IF NOT EXISTS idx_books_status ON books (status);
CREATE INDEX IF NOT EXISTS idx_books_grade ON books (grade_10, grade_11, grade_12);
CREATE INDEX IF NOT EXISTS idx_books_track ON books (track);

-- 4. Editions table
CREATE TABLE IF NOT EXISTS editions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    edition_number INT NOT NULL,
    publication_year INT,
    isbn VARCHAR(50),
    provenance_source VARCHAR(50) NOT NULL DEFAULT 'no_source',
    provenance_reference VARCHAR(500),
    provenance_license_id VARCHAR(200),
    provenance_rights_statement TEXT,
    provenance_verified_by VARCHAR(200),
    provenance_verified_at TIMESTAMPTZ,
    provenance_verification_status VARCHAR(50) NOT NULL DEFAULT 'unverified',
    provenance_notes TEXT,
    page_count INT,
    version VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_editions_book_number ON editions (book_id, edition_number);
CREATE INDEX IF NOT EXISTS idx_editions_book ON editions (book_id);
CREATE INDEX IF NOT EXISTS idx_editions_status ON editions (status);

-- 5. Chapters table
CREATE TABLE IF NOT EXISTS chapters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    edition_id UUID NOT NULL REFERENCES editions(id) ON DELETE CASCADE,
    number INT NOT NULL,
    title VARCHAR(500) NOT NULL,
    page_start INT,
    page_end INT,
    question_count INT,
    prerequisites UUID[] NOT NULL DEFAULT '{}',
    provenance_source VARCHAR(50) NOT NULL DEFAULT 'no_source',
    provenance_reference VARCHAR(500),
    provenance_license_id VARCHAR(200),
    provenance_rights_statement TEXT,
    provenance_verified_by VARCHAR(200),
    provenance_verified_at TIMESTAMPTZ,
    provenance_verification_status VARCHAR(50) NOT NULL DEFAULT 'unverified',
    provenance_notes TEXT,
    version VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_chapters_edition_number ON chapters (edition_id, number);
CREATE INDEX IF NOT EXISTS idx_chapters_edition ON chapters (edition_id);
CREATE INDEX IF NOT EXISTS idx_chapters_status ON chapters (status);

-- Append-only trigger for chapters
DROP TRIGGER IF EXISTS trg_chapters_append_only ON chapters;
CREATE TRIGGER trg_chapters_append_only
BEFORE UPDATE OR DELETE ON chapters
FOR EACH ROW
EXECUTE FUNCTION prevent_append_only_mutation();

-- 6. Lessons table
CREATE TABLE IF NOT EXISTS lessons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id UUID NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    number INT NOT NULL,
    title VARCHAR(500) NOT NULL,
    page_start INT,
    page_end INT,
    estimated_duration_minutes INT,
    question_count INT,
    prerequisites UUID[] NOT NULL DEFAULT '{}',
    learning_objectives TEXT[] NOT NULL DEFAULT '{}',
    provenance_source VARCHAR(50) NOT NULL DEFAULT 'no_source',
    provenance_reference VARCHAR(500),
    provenance_license_id VARCHAR(200),
    provenance_rights_statement TEXT,
    provenance_verified_by VARCHAR(200),
    provenance_verified_at TIMESTAMPTZ,
    provenance_verification_status VARCHAR(50) NOT NULL DEFAULT 'unverified',
    provenance_notes TEXT,
    version VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_lessons_chapter_number ON lessons (chapter_id, number);
CREATE INDEX IF NOT EXISTS idx_lessons_chapter ON lessons (chapter_id);
CREATE INDEX IF NOT EXISTS idx_lessons_status ON lessons (status);

-- Append-only trigger for lessons
DROP TRIGGER IF EXISTS trg_lessons_append_only ON lessons;
CREATE TRIGGER trg_lessons_append_only
BEFORE UPDATE OR DELETE ON lessons
FOR EACH ROW
EXECUTE FUNCTION prevent_append_only_mutation();

-- 7. PageSections table
CREATE TABLE IF NOT EXISTS page_sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lesson_id UUID NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    page_number INT,
    section_title VARCHAR(500),
    content_summary TEXT,
    question_count INT,
    provenance_source VARCHAR(50) NOT NULL DEFAULT 'no_source',
    provenance_reference VARCHAR(500),
    provenance_license_id VARCHAR(200),
    provenance_rights_statement TEXT,
    provenance_verified_by VARCHAR(200),
    provenance_verified_at TIMESTAMPTZ,
    provenance_verification_status VARCHAR(50) NOT NULL DEFAULT 'unverified',
    provenance_notes TEXT,
    version VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_page_sections_lesson ON page_sections (lesson_id);
CREATE INDEX IF NOT EXISTS idx_page_sections_status ON page_sections (status);

-- Append-only trigger for page_sections
DROP TRIGGER IF EXISTS trg_page_sections_append_only ON page_sections;
CREATE TRIGGER trg_page_sections_append_only
BEFORE UPDATE OR DELETE ON page_sections
FOR EACH ROW
EXECUTE FUNCTION prevent_append_only_mutation();

-- 8. Questions table
CREATE TABLE IF NOT EXISTS questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    page_section_id UUID NOT NULL REFERENCES page_sections(id) ON DELETE CASCADE,
    question_number INT NOT NULL,
    question_type VARCHAR(100) NOT NULL,
    difficulty VARCHAR(50),
    estimated_time_minutes INT,
    tags TEXT[] NOT NULL DEFAULT '{}',
    provenance_source VARCHAR(50) NOT NULL DEFAULT 'no_source',
    provenance_reference VARCHAR(500),
    provenance_license_id VARCHAR(200),
    provenance_rights_statement TEXT,
    provenance_verified_by VARCHAR(200),
    provenance_verified_at TIMESTAMPTZ,
    provenance_verification_status VARCHAR(50) NOT NULL DEFAULT 'unverified',
    provenance_notes TEXT,
    version VARCHAR(50) NOT NULL DEFAULT '1.0.0',
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_questions_page_section_number ON questions (page_section_id, question_number);
CREATE INDEX IF NOT EXISTS idx_questions_page_section ON questions (page_section_id);
CREATE INDEX IF NOT EXISTS idx_questions_status ON questions (status);

-- Append-only trigger for questions
DROP TRIGGER IF EXISTS trg_questions_append_only ON questions;
CREATE TRIGGER trg_questions_append_only
BEFORE UPDATE OR DELETE ON questions
FOR EACH ROW
EXECUTE FUNCTION prevent_append_only_mutation();

-- 9. View for published content (Content Intelligence Agent read path)
-- Only returns content with status = 'published' AND published_at IS NOT NULL

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