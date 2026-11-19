# چشم‌انداز محصول — Kunkor

**D-13 (2026-11-05):** Content infrastructure starts empty and grows through manual owner entry after deployment. Phase 2 accepts zero real educational records. Valid units publish independently after owner approval and rights checks; empty results must not cause invented content or block unrelated capabilities. See [PHASE_2_EMPTY_TO_GROW.md](PHASE_2_EMPTY_TO_GROW.md).

**نسخه:** ۳.۰  
**تاریخ:** ۲۰۲۶-۱۱-۰۳  
**وضعیت:** فعال (D-12)  
**منبع:** تصمیم مالک پروژه

---

## هدف

**Kunkor** مشاور آموزشی **خودمختار چندعاملی** برای دانش‌آموزان **پایه دهم، یازدهم و دوازدهم** است.

نه چت‌بات ساده، نه فقط برنامه‌ریز درسی.

---

## چهار تصمیم قطعی

| محور | تصمیم |
|------|--------|
| محدوده | **پایه‌های ۱۰ · ۱۱ · ۱۲** (سه سال دبیرستان) |
| خودمختاری | **Full** — کارهای عادی بدون تأیید انسانی |
| Multi-Agent | **From start** — چند مشاور + Supervisor |
| بانک محتوا | **From scratch** — مدل منبع حقیقت صفحه/تست نیست |

---

## اصل کنترل اختیار

عامل‌ها پیشنهاد می‌دهند و استدلال می‌کنند.  
اعمال تغییر فقط از سرویس دامنه + اعتبارسنجی قطعی + Audit.  
هیچ Agent مستقیماً روی دیتابیس نمی‌نویسد.

---

## معماری هدف (خلاصه)

```
دانش‌آموز (تلگرام ۲۴/۷)
    ↓
هویت و Student Context
    ↓
Orchestrator چندعاملی
  Intake · Modeling · Content · Planning · Progress · Revision · Supervisor
    ↓
بانک محتوا (نسخه‌دار)
    ↓
موتور اعتبارسنجی قطعی
    ↓
ذخیره و اجرا (PostgreSQL · Audit · Jobs)
```

---

## اصول الزامی

- Modular Monolith (FastAPI · Next.js · PostgreSQL)
- Single Write Authority
- Deterministic Validation قبل از فعال‌سازی برنامه
- Content Grounding
- Durable Execution
- Privacy by Design / student isolation
- Evaluation First

---

*منبع حقیقت: `docs/decisions.md` · `docs/adr/ADR-0009.md`*
