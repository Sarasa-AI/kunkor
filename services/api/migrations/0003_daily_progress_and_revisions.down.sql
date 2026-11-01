-- 0003_daily_progress_and_revisions.down.sql
-- Revert daily progress logs

DROP TRIGGER IF EXISTS trg_daily_progress_logs_append_only ON daily_progress_logs;
DROP TABLE IF EXISTS daily_progress_logs CASCADE;
