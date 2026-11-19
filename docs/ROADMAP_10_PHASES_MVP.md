# نقشه راه ۱۰ فازی تا MVP — Kunkor

**2026-11-05 scope update (D-13):** Phase 2 includes the mandatory empty-to-grow owner-managed content infrastructure and its empty/synthetic-fixture acceptance. Historical Phase 3 catalog numbering below does not defer this requirement. Educational library population is continuous owner operation after deployment, with no population threshold for Phase 2, deployment, or unrelated capabilities. Missing trusted content blocks only content-dependent operations. See [the binding contract](PHASE_2_EMPTY_TO_GROW.md).

**نسخه:** ۲.۰ · **تاریخ:** ۲۰۲۶-۱۱-۰۳  
**محدوده:** پایه‌های ۱۰ · ۱۱ · ۱۲  
**مبتنی بر:** D-12 · ADR-0009

---

## هدف MVP

مشاور خودمختار چندعاملی برای دبیرستان (دهم تا دوازدهم):  
شرح‌حال · برنامه مبتنی بر محتوای واقعی · پایش روزانه · اصلاح خودکار · تلگرام ۲۴/۷

---

## ده فاز

| فاز | عنوان | خروجی | دروازه |
|-----|--------|--------|--------|
| 1 | قرارداد و معماری | Product Contract + معیارها | تأیید مالک |
| 2 | هویت، امنیت، پروفایل + owner content infrastructure | Student Context ایزوله + functional empty catalog (D-13) | Isolation and empty/synthetic content acceptance |
| 3 | بانک محتوا — extension | Extend retrieval/metadata as needed; owner population is ongoing operation | بدون منبع = بدون برنامه؛ no population threshold |
| 4 | زیرساخت Multi-Agent | Orchestrator + قرارداد عامل‌ها | بدون نوشتن مستقیم DB |
| 5 | Intake و مدل دانش‌آموز | شرح‌حال تطبیقی | فیلدهای ضروری |
| 6 | برنامه‌ریزی و اعتبارسنجی | برنامه معتبر فعال | Validator اجباری |
| 7 | پیشرفت و اصلاح | حلقه روزانه | اصلاح با شواهد |
| 8 | Supervisor و ارزیابی | Benchmark و مقایسه مشاورها | تصمیم قابل ردیابی |
| 9 | تلگرام ۲۴/۷ | کانال پایدار آزمایشی | E2E بدون کاربر واقعی |
| 10 | آمادگی MVP | Release Candidate | مجوز Pilot |

**موازی‌سازی:** بعد از فاز ۱، فازهای ۲ و ۳ و ۴ می‌توانند موازی پیش بروند.

---

## اصول اجرا

1. Multi-Agent از ابتدا پایه‌گذاری می‌شود.
2. بانک محتوا گلوگاه کیفیت آموزشی است.
3. هیچ برنامه‌ای بدون Validator فعال نمی‌شود.
4. Single Write Authority.
5. تلگرام زنده و Pilot فقط بعد از دروازه‌های امنیت و کیفیت.

---

## فاز ۱ (فعلی)

- نهایی بودن D-12 و ADR-0009
- Product Contract
- معیارهای موفقیت
- فهرست تصمیم‌های باز (رشته، حقوق محتوا)

مستر پرامپت: `docs/PHASE_1_MASTER_PROMPT.md`
