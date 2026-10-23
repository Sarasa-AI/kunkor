# TASK-02 — پایه پایگاه داده (WP-03)

## ۱. هدف
راه‌اندازی زیرساخت پایگاه داده، سامانه اجرای migration دوطرفه (Up و Down)، افزونه‌های پایگاه داده (`btree_gist` و `uuid-ossp`)، قراردادهای نام‌گذاری، پیاده‌سازی جداول پایه هسته (`audit_events`، `outbox_events`، `idempotency_keys`، `feature_flags`، `entitlements`)، تریگر محافظت از جداول فقط‌افزودنی (Append-only)، و ورکر پردازش رویدادهای Outbox.

## ۲. فایل‌هایی که ایجاد/تغییر می‌کنند
- `docs/tasks/TASK-02.md` (برنامه تسک)
- `services/api/migrations/0001_baseline_schema.up.sql`
- `services/api/migrations/0001_baseline_schema.down.sql`
- `services/api/scripts/migrate.py`
- `services/api/scripts/migrate_check.py`
- `services/api/app/core/config.py`
- `services/api/app/core/db.py`
- `services/api/app/workers/outbox_worker.py`
- `services/api/tests/test_migrations.py`
- `services/api/tests/test_append_only.py`
- `services/api/tests/test_outbox_worker.py`
- `services/api/requirements.txt`
- `Makefile`
- `PROGRESS.md`

## ۳. فرض‌ها و تصمیم‌های پیش‌فرض اعمال‌شده
- قراردادهای نام‌گذاری: اسامی جدول‌ها به صورت جمع با حروف کوچک و snake_case (`audit_events`)؛ ستون‌ها snake_case؛ کلید اصلی UUID.
- ستون `student_id` طبق ADR-8 در تمام جداول مرتبط با دانش‌آموز وجود دارد.
- جداول `audit_events` از نوع append-only بوده و هرگونه `UPDATE` یا `DELETE` توسط تریگر سطح پایگاه داده رد می‌شود.
- جدول `outbox_events` برای پشتیبانی از الگوی transactional outbox استفاده شده و ورکر اختصاصی ردیف‌های پردازش‌نشده را علامت‌گذاری و منتشر می‌کند.
- `entitlements` به عنوان پایه P1 بدون وابستگی به پرداخت طراحی شده و پیش‌فرض آن فعال بودن دسترسی است (FR-S1).
