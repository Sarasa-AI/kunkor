# Kunkor — دفتر سناریوهای آزمون پذیرش (Acceptance Scenario Book)
## WP-06 / TASK-03

این مستند ماتریس سناریوهای پذیرش برای ۵ گروه تحصیلی منطبق بر سند مشخصات (`docs/spec.md` بخش ۱٫۵ و ۱٫۶) و ADRهای پروژه است.

### ماتریس گروه‌ها و توزیع سناریوها

| شناسه گروه | عنوان گروه | پایه‌ها | سناریوی موفق | سناریوی شکست | مجموع | فایل سناریو |
|---|---|---|---|---|---|---|
| `primary_low` | ابتدایی دوره اول | ۱ تا ۳ | ۳ | ۳ | ۶ | [`primary_low.md`](./primary_low.md) |
| `primary_high` | ابتدایی دوره دوم | ۴ تا ۶ | ۳ | ۳ | ۶ | [`primary_high.md`](./primary_high.md) |
| `lower_secondary` | متوسطه دوره اول | ۷ تا ۹ | ۳ | ۳ | ۶ | [`lower_secondary.md`](./lower_secondary.md) |
| `upper_secondary` | متوسطه دوره دوم | ۱۰ و ۱۱ | ۳ | ۳ | ۶ | [`upper_secondary.md`](./upper_secondary.md) |
| `konkur` | سال دوازدهم و پشت‌کنکور | ۱۲ و فارغ‌التحصیل | ۳ | ۳ | ۶ | [`konkur.md`](./konkur.md) |
| **مجموع** | — | — | **۱۵** | **۱۵** | **۳۰** | — |

---

### ساختار استاندارد هر سناریو

1. **Scenario ID**: شناسه یکتا (`SCEN-<GROUP>-<S|F><NUM>`)
2. **Scenario Name**: نام سناریو
3. **Cohort**: گروه آموزشی هدف
4. **Requirement Reference**: ارجاع به سند نیازمندی‌ها (`FR-*` یا `UJ-*`)
5. **Preconditions**: پیش‌شرط‌ها و وضعیت داده پایه
6. **Input Fixture**: داده ورودی مشخص (JSON/Mock)
7. **Action**: عملیات سامانه
8. **Expected Output & Validation**: نتیجه اعتبارسنجی قطعی موتور
9. **Expected Persistence**: رفتار ذخیره‌سازی و تریگرهای پایگاه داده
10. **Security & Privacy**: کنترل دسترسی و حریم خصوصی (ADR-0003, ADR-0008, D-04)
11. **Execution Status**: وضعیت اجرای خودکار
12. **Related Test**: مسیر فایل آزمون خودکار
