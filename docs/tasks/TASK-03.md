# TASK-03 — دفتر سناریوهای آزمون پذیرش (WP-06)

## ۱. هدف
ایجاد دفتر جامع سناریوهای آزمون پذیرش برای ۵ گروه آموزشی (`primary_low`, `primary_high`, `lower_secondary`, `upper_secondary`, `konkur`) با تفکیک ۳ سناریوی موفق و ۳ سناریوی شکست به ازای هر گروه (مجموعاً ۳۰ سناریو) منطبق بر بخش‌های ۱٫۵، ۱٫۶ و جدول WP-06 در `docs/spec.md`. همچنین ارائه پوشش آزمون‌های خودکار معادل در `services/api/tests/test_scenarios.py`.

## ۲. فایل‌های ایجادشده
- `docs/test-scenarios/README.md` (ماتریس توزیع سناریوها و ساختار استاندارد)
- `docs/test-scenarios/primary_low.md` (سناریوهای دوره اول ابتدایی: SCEN-PL-S01..S03 و SCEN-PL-F01..F03)
- `docs/test-scenarios/primary_high.md` (سناریوهای دوره دوم ابتدایی: SCEN-PH-S01..S03 و SCEN-PH-F01..F03)
- `docs/test-scenarios/lower_secondary.md` (سناریوهای متوسطه اول: SCEN-LS-S01..S03 و SCEN-LS-F01..F03)
- `docs/test-scenarios/upper_secondary.md` (سناریوهای متوسطه دوم: SCEN-US-S01..S03 و SCEN-US-F01..F03)
- `docs/test-scenarios/konkur.md` (سناریوهای کنکور: SCEN-KO-S01..S03 و SCEN-KO-F01..F03)
- `services/api/tests/test_scenarios.py` (۳۰ آزمون خودکار قطعی برای همه سناریوها)
- `PROGRESS.md` (بروزرسانی وضعیت تسک به done)

## ۳. شواهد اعتبارسنجی
- اجرای کامل ۳۰ آزمون سناریو: `pytest services/api/tests/test_scenarios.py` (۳۰ passed).
- همخوانی ۱۰۰٪ با ADR-0003 (مجوزها)، ADR-0004 (جداسازی منطق آموزشی)، ADR-0005 (عدم تغییر لاگ‌ها)، ADR-0006 (انتزاع هوش مصنوعی)، ADR-0008 (ستون student_id) و تصمیم D-04 (رضایت سرپرست).
