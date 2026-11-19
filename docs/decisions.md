# دفتر تصمیم‌ها — Kunkor

وضعیت‌ها: `open` | `proposed` | `decided` | `superseded`

## D-13 — Empty-to-grow content infrastructure (decided)

- Date: 2026-11-05; explicit owner requirement.
- Phase 2 must deliver functional owner-managed content infrastructure with an empty catalog. No real educational content or minimum catalog size is a development, acceptance, deployment, or unrelated capability activation gate.
- Resources and smaller units are saved as incomplete drafts and reviewed, approved, published, rejected, or archived independently. Parent/catalog completeness is not a publication prerequisite.
- Student and trusted-agent reads require explicit owner approval, publication, and active usage rights. Missing content yields empty results or an awaiting-content state, never fabricated content.
- Synthetic educational fixtures exist exclusively in automated tests. No runtime content seed or synthetic fallback catalog.
- Binding contract and ten acceptance requirements: [PHASE_2_EMPTY_TO_GROW.md](PHASE_2_EMPTY_TO_GROW.md).

---

## D-12 — جهت محصول و معماری (قطعی)

- **تاریخ:** ۲۰۲۶-۱۱-۰۳
- **وضعیت:** `decided`

| محور | تصمیم |
|------|--------|
| محدوده | پایه‌های **۱۰، ۱۱ و ۱۲** (سه سال دبیرستان) |
| خودمختاری | Full با کنترل نوشتن |
| Multi-Agent | از ابتدا |
| بانک محتوا | از صفر؛ LLM منبع شمارش صفحه/تست نیست |

**اصل:** Agent پیشنهاد می‌دهد؛ سرویس دامنه + Validator اعمال می‌کند.

**اسناد:** ADR-0009 · vision.md · ROADMAP_10_PHASES_MVP.md

---

## تصمیم‌های باز مهم

### D-01 — رشته / شاخه تحصیلی
- پوشش ریاضی، تجربی، انسانی برای هر پایه
- **وضعیت:** `open`
- تا تأیید: seed قطعی رشته‌محور ساخته نشود

### D-02 — حقوق و مجوز محتوا
- Rights are enforced per item independently of availability. Incomplete unverified metadata may be saved as drafts; trusted use requires owner approval, publication, and active usage rights. Empty-catalog infrastructure has no content-population or catalog-wide license approval prerequisite (D-13).
- **وضعیت:** `open`

### D-05 — میزبانی و زیرساخت
- **وضعیت:** `open` — معماری قابل‌انتقال

### D-07 — نقش AI در تصمیم
- AI پیشنهاددهنده؛ Engine اعتبارسنج قیود سخت
- **وضعیت:** `decided` (هم‌راستا با ADR-0009)

---

## تاریخچه کوتاه

| کد | موضوع | وضعیت |
|----|--------|--------|
| D-10 | Vision Reset اولیه | `superseded` توسط D-12 |
| D-12 | Multi-Agent + دهم تا دوازدهم | `decided` |

---

## ADRهای فعال

| ADR | موضوع |
|-----|--------|
| ADR-0009 | معماری Multi-Agent و Controlled Autonomy |
| ADR-4 | تفکیک استدلال AI و اعتبارسنجی قطعی |
| ADR-6 | Provider abstraction + AI به‌عنوان وابستگی اصلی با Fallback |

اصول حفظ‌شده از معماری قبلی: Modular Monolith · مجوز بک‌اند · student isolation · شواهد/نسخه‌بندی append-oriented.
