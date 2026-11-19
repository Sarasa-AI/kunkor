-- 0008_content_catalog.down.sql

DROP VIEW IF EXISTS v_published_lessons;
DROP VIEW IF EXISTS v_published_chapters;
DROP VIEW IF EXISTS v_published_books;

DROP TRIGGER IF EXISTS trg_questions_append_only ON questions;
DROP TABLE IF EXISTS questions;

DROP TRIGGER IF EXISTS trg_page_sections_append_only ON page_sections;
DROP TABLE IF EXISTS page_sections;

DROP TRIGGER IF EXISTS trg_lessons_append_only ON lessons;
DROP TABLE IF EXISTS lessons;

DROP TRIGGER IF EXISTS trg_chapters_append_only ON chapters;
DROP TABLE IF EXISTS chapters;

DROP TABLE IF EXISTS editions;
DROP TABLE IF EXISTS books;
DROP TABLE IF EXISTS subjects;
DROP TABLE IF EXISTS curricula;