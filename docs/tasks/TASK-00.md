# TASK-00 — مخزن، CI و اسکلت (WP-05)

## ۱. هدف
راه‌اندازی ساختار اولیه مخزن، فایل مشخصات تغییرناپذیر، بسته‌بندی Docker Compose، دستورهای Makefile، اسکلت FastAPI با endpoint سلامت (`GET /healthz`)، اسکلت کلاینت Next.js (RTL)، گردش کار CI، و آزمون‌های اعتبارسنجی اسکلت.

## ۲. فایل‌هایی که ایجاد/تغییر می‌کنند
- `docs/spec.md` (کپی دقیق مشخصات اصلی)
- `.gitignore`
- `.github/workflows/ci.yml`
- `docker-compose.yml`
- `Makefile`
- `services/api/` (pyproject.toml/requirements, Dockerfile, app/main.py, tests/)
- `apps/web/` (package.json, Dockerfile, src/app/)
- `packages/contracts/` (README.md یا اسکلت قرارداد)
- `PROGRESS.md`
- `docs/tasks/TASK-00.md`

## ۳. فرض‌ها و تصمیم‌های پیش‌فرض
- استفاده از Docker Compose برای یکپارچگی محلی (db با Postgres و btree_gist، api با FastAPI، web با Next.js، queue worker).
- `make check` شامل lint، typecheck، test و بررسی اسکلت است.
- عدم افزودن داده یا منطق محصولی ناتمام؛ فقط اسکلت راه‌اندازی و healthz.
