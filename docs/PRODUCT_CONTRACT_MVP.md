# Current product interpretation — 2026-11-05 remaining work

**Mandatory Phase 2 content scope (D-13):** Build and accept owner-managed content infrastructure with an empty catalog. Owner entry, draft persistence, incremental unit publication, approval, rights, and audit controls are required; educational library population is not. Synthetic content is exclusively for automated tests. Empty catalog results do not block deployment or unrelated system capabilities. [Full contract and acceptance requirements](PHASE_2_EMPTY_TO_GROW.md) supersede earlier content seed/population and phase-numbering assumptions.

TASK-P1-REMOVE-01. The owner's explicit instruction removes the former age/guardian/withdrawal/provider-processing approval dependency from the active product specification, Phase 1 exit, Phase 2 entry and Live AI enablement. This does not assert legal approval or alter independent security and content-license controls.

Current technical contract: signed student authentication and owner-scoped repository writes protect profile updates. `guardian_consent` is an optional exact boolean assertion on the student's own profile; it neither verifies a guardian nor grants backend/provider authority. Provider calls follow explicit enablement, credential, pricing/quota, timeout, masking and validation controls. Default disablement remains. Existing local deterministic planning is not proof of verified educational content.

Current reconciliation: `PHASE_1_FINAL_COMPLETION_REPORT.md`; preserved original local evidence: `PHASE_1_COMPLETION_REPORT.md`. The contract below retains its educational and security requirements.

---

# قرارداد محصول MVP — Kunkor

**نسخه:** ۱.۰  
**تاریخ:** ۲۰۲۶-۱۱-۰۳  
**مبنای تصمیم:** D-12 · ADR-0009 · vision.md

---

## ۱. بیان محصول MVP (یک پاراگراف)

**Kunkor** یک مشاور آموزشی **خودمختار چندعاملی** برای دانش‌آموزان **پایه‌های ۱۰، ۱۱ و ۱۲** است که از طریق **تلگرام ۲۴/۷** شرح‌حال تطبیقی می‌گیرد، **برنامه مطالعه مبتنی بر محتوای واقعی و تأییدشده** تولید می‌کند، اجرا روزانه را پایش می‌کند، و با **شواهد** برنامه را اصلاح می‌کند. تمام نوشتن‌های دیتا از طریق **سرویس دامنه + اعتبارسنجی قطعی + Audit** انجام می‌شود (Single Write Authority).

---

## ۲. در محدوده MVP

| حوزه | جزئیات |
|-------|---------|
| **مخاطب** | دانش‌آموزان پایه ۱۰، ۱۱، ۱۲ (سه سال دبیرستان) |
| **کانال اصلی** | تلگرام (Bot + WebApp برای بخش‌های غنی) |
| **خودمختاری** | Full — کارهای روتین (برنامه، پایش، اصلاح) بدون تأیید انسانی |
| **Multi-Agent** | Orchestrator + ۷ عامل (Intake, Modeling, Content, Planning×N, Progress, Revision, Supervisor) |
| **بانک محتوا** | از صفر: Curriculum → Subject → Book → Edition → Chapter → Lesson → Page/Question با provenance |
| **اعتبارسنجی** | موتور قطعی: زمان، پیش‌نیاز، سقف روزانه/هفتگی، موجودیت منبع، سازگاری پروفایل |
| **حالت امن** | توقف/Degraded وقتی مدرک آموزشی ناکافی، پروفایل ناقص، نقض قيد سخت، Supervisor نتواند حل کند، یا مجوز/Provider نامعتبر |
| **پایداری** | Conversation، AgentRun، تصمیم‌ها، نسخه‌های برنامه، اجراها، شواهد — 모두 durable و recoverable |

---

## ۳. خارج از محدوده MVP

| مورد | دلیل |
|------|------|
| پایه‌های ۹ یا پایین‌تر / ۱۳ یا بالاتر | تمرکز MVP روی ۱۰–۱۲؛ معماری قابل گسترش |
| پرداخت، اشتراک، خرید در برنامه | اولویت אחרי امنیت و کیفیت |
| OCR، اسکن کتاب، استخراج خودکار محتوا | محتوای از صفر با Publish کنترل‌شده |
| داشبورد مدرسه/معلّم/پدر و مادر | تمرکز روی دانش‌آموز |
| اپلیکیشن بومی iOS/Android | تلگرام ۲۴/۷ به عنوان کانال |
| n8n، Zapier، میکروسرویس‌ها | Modular Monolith (FastAPI + Next.js + PostgreSQL) |
| محتوای تولید شده توسط LLM به عنوان منبع | Content Grounding: LLM منبع شمارش صفحه/تست نیست |

---

## ۴. بازیگران

| بازیگر | نقش |
|---------|-----|
| **دانش‌آموز** | کاربر نهایی؛ از طریق تلگرام تعامل می‌کند |
| **سیستم (Kunkor)** | Orchestrator، عوامل، Validator، سرویس‌های دامنه، دیتابیس، تلگرام Bot |
| **بازبین انسانی (Human Reviewer)** | فقط برای:.Content Publish، موارد استثنایی Safety، Pilot Authorization — نه در مسیر روتین |

---

## ۵. اختیارات و محدودیت عوامل

| عامل | اختیارات | محدودیت‌ها |
|------|----------|-----------|
| **Intake** | مصاحبه تطبیقی، تشخیص اطلاعات گمشده | فقط پرسش و ثبت پیشنهاد پرونده؛ نمی‌نویسد |
| **Student Modeling** | ساخت پروفایل ساختاریافته، تحلیل زمینه یادگیری | فقط پیشنهاد پروفایل؛ اعتبارسنجی در Validator |
| **Content Intelligence** | بازیابی کتاب/فصل/درس/صفحه/سوال تأییدشده | فقط خواندن از Content Service؛ بدون hallucination |
| **Planning Consultants (چندین)** | استراتژی‌های مشاوره مستقل، تولید برنامه کاندید | خروجی ساختاریافته پیشنهادی؛ بدون نوشتن مستقیم |
| **Progress** | تحلیل اجرای روزانه، شناسایی انحراف | فقط گزارش و پیشنهاد اصلاح |
| **Revision** | اصلاح مبتنی بر شواهد | پیشنهاد؛ عبور از Validator الزامی |
| **Supervisor** | مقایسه پیشنهادها، حل تضاد، امتیازدهی کیفیت، انتخاب نهایی | نمی‌تواند Validation را بایپس کند؛ انتخاب قابل ردیابی |

---

## ۶. قواعد نوشتن داده (Single Write Authority)

1. **هیچ عامل مستقیماً روی PostgreSQL نمی‌نویسد.**
2. **سرویس‌های دامنه** (StudentService, PlanService, ContentService, ProgressService) مالک تغییرات پایدار هستند.
3. **موتور اعتبارسنجی قطعی** (PlanningValidator) همه قيدهای سخت را بررسی می‌کند قبل از فعال‌سازی.
4. **Audit Log** همه تصمیم‌های مهم را ثبت می‌کند: عامل مسئول، مدل/Provider، نسخه پرامپت/کانفیگ، نسخه کانتکست ورودی، پیشنهاد، نتیجه اعتبارسنجی، اقدام نهایی.
5. **Idempotency** برای تلاش مجدد و پیام‌های تکراری تلگرام الزامی است.
6. **نسخه‌بندی برنامه** — نسخه‌های قبلی به عنوان مدرک تاریخی نگه داشته می‌شوند.

---

## ۷. قواعد محتوا (Content Grounding)

| اصل | تنفيذ |
|------|-------|
| **از صفر** |سلسله‌مراتب: Curriculum → Subject → Book → Edition → Chapter → Lesson → Section/Page → Question |
| **Provenance** | منبع، ویرایش، مجوز، حقوق استفاده برای هر گره |
| **شمارش دقیق** | تعداد صفحه و سوال دقیق در صورت تأیید؛ در غیر این صورت `unknown` |
| ** سختی و زمان** | سختی سوال و زمان تخمینی تکمیل در صورت پشتیبانی |
| **مپینگ** | برنامه درسی و اهداف یادگیری، پیش‌نیازها و روابط موضوعی |
| **نسخه‌بندی** | Review، Publish، Expiry، Correction |
| **حالت‌های صریح** | `no_source` (منبع وجود ندارد) و `unknown` (ناشناس) — هرگز پیش‌فرض عددی نمی‌گذارند |
| **جداسازی Ingest/Publish** | محتوای بررسی‌نشده **هرگز** به عنوان مرجع تلقی نمی‌شود |

---

## ۸. کانال‌ها

| کانال | وضعیت | جزئیات |
|-------|-------|---------|
| **Telegram Bot** | **Primary** — ۲۴/۷ | تعامل اصلی، اعلان، اجرای روزانه |
| **Telegram WebApp** | Complementary | فرم‌های پیچیده، انتخاب کتاب، نمودار پیشرفت |
| **Email / SMS** | Out of scope MVP | فقط برای Recovery در صورت نیاز |

---

## ۹. معیارهای موفقیت سطح محصول (Measurable)

| متریک | هدف MVP | روش سنجش |
|--------|---------|-----------|
| **تکمیل شرح‌حال** | ≥ ۸۰٪ دانش‌آموزان پرونده کامل در ≤ ۳ جلسه | لاگ Intake |
| **نرخ برنامه معتبر** | ۱۰۰٪ برنامه‌های فعال از Validator عبور کرده | PlanService + Audit |
| **پک rabbit پیشرفت روزانه** | ≥ ۷۰٪ روزهای فعال داشتن گزارش پیشرفت | Progress Agent runs |
| **اصلاح مبتنی بر شواهد** | ۱۰۰٪ اصلاح‌ها با مدرک (سوال حل شده، زمان واقعی) | Revision Agent + Validator |
| **ایزوله‌سازی داده** | ۰ نشت داده بین دانش‌آموزان (تست امنیتی) | Security test suite |
| **هزینه مدل** | ≤ سقف Policy روزانه/ماهانه | Provider abstraction metrics |
| **تأخیر تعامل** | P95 < ۵ ثانیه برای پاسخ‌های متنی | Telemetry |
| **تغطیت ارزیابی** | ≥ ۵۰ مورد ارزیابی برای هر عامل و Supervisor | Evaluation harness |

---

## ۱۰. شرایط توقف / حالت امن (Degraded Mode)

سیستم **باید** متوقف شود یا به حالت امن برود وقتی:

| شرط | رفتار |
|-------|-------|
| مدرک آموزشی لازم موجود نیست (مثلاً کتاب منتشرنشده) | پاسخ: «منبع تأییدشده‌ای برای این بخش وجود ندارد» — برنامه فعال نمی‌شود |
| پروفایل دانش‌آموز مادیاً ناقص یا متضاد | Intake ادامه می‌دهد؛ Planning متوقف |
| برنامه کاندید قيد سخت را نقض کند | Validator رد می‌کند؛ Supervisor نمی‌تواند بایپس کند |
| Supervisor نتواند تضاد مادی را حل کند | Escalation به Human Reviewer؛ برنامه قبلی فعال می‌ماند |
| احراز هویت، مجوز دسترسی یا کنترل فنی Provider برآورده نشود | Degraded: بدون فراخوانی Provider غیرمجاز یا برنامه نامعتبر |

**اصل:** هیچ برنامه پشتیبانی‌نشده فعال نمی‌شود تا ظاهر خودمختاری حفظ شود.

---

## ۱۱. وابستگی به تصمیم‌های باز

| تصمیم باز | کد | وضعیت | مالک | اثر در فازها |
|------------|----|-------|------|-------------|
| رشته/شاخه تحصیلی هر پایه | D-01 | `open` | Product Owner | Optional classification metadata; no empty-catalog or Phase 2 gate (D-13) |
| حقوق و مجوز محتوا | D-02 | `open` | Legal / Product | Per-item trusted-use and publication rights; no population or infrastructure gate (D-13) |
| میزبانی و زیرساخت | D-05 | `open` | Infra | بلاک فاز ۴+ (Deploy) |
| بودجه مدل (سقف روزانه/ماهانه) | — | `proposed` | Product / Finance | Policy در Product Contract؛ عدد نهایی فاز ۴ |

> **نکته:** کنترل‌های مستقل حفظ می‌شوند: محتوا فقط پس از Publish معتبر، مدل با سقف مصرف، PII masking، احراز هویت و جداسازی دانش‌آموز.
