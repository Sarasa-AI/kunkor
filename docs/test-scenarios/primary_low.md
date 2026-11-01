# سناریوهای پذیرش: ابتدایی دوره اول (`primary_low`)
پایه‌های اول تا سوم ابتدایی (سنین ۷ تا ۹ سال). تمرکز بر رضایت سرپرست، واحدهای کوتاه‌مدت صوتی/بازی‌محور، و عدم دسترسی به داده بدون تایید سرپرست.

---

## سناریوهای موفق (Success Scenarios)

### SCEN-PL-S01: ثبت‌نام با رضایت والد و ایجاد برنامه صوتی کوتاه
- **Cohort**: `primary_low`
- **Requirement Reference**: `FR-A2`, `FR-P4`, `D-04`
- **Preconditions**: والد دارای شماره موبایل معتبر؛ کودک پایه دوم.
- **Input Fixture**:
  ```json
  {
    "stage_code": "primary_low",
    "grade": "G02",
    "guardian_consent": true,
    "daily_study_capacity_minutes": 20,
    "target_skill": "reading_fluency"
  }
  ```
- **Action**: اعتبارسنجی ورودی و تولید برنامه تک‌واحدی بازی‌محور ۱۵ دقیقه‌ای.
- **Expected Output & Validation**: برنامه با وضعیت `draft`، طول مدت ۱۵ دقیقه، بدون خطا تایید می‌شود.
- **Expected Persistence**: ذخیره در `study_plans` با `student_id` معتبر و ثبت رویداد در `audit_events`.
- **Security & Privacy**: فلگ `guardian_consent` الزامی و ثبت‌شده؛ شماره تماس کودک ذخیره نمی‌شود.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_pl_s01`

### SCEN-PL-S02: اجرای تسک صوتی و ثبت شواهد بدون فیلدهای متنی پیچیده
- **Cohort**: `primary_low`
- **Requirement Reference**: `FR-T1`, `FR-T3`, `ADR-0005`
- **Preconditions**: تسک صوتی فعال به مدت ۱۰ دقیقه با منبع تاییدشده.
- **Input Fixture**:
  ```json
  {
    "task_id": "018f-pl-task-02",
    "status": "completed",
    "perceived_difficulty": "easy",
    "completion_evidence": {"audio_listened_seconds": 600}
  }
  ```
- **Action**: ثبت پایان تسک در لاگ اجرای تکالیف.
- **Expected Output & Validation**: تایید موفقیت و محاسبه پیشرفت روزانه.
- **Expected Persistence**: درج یک ردیف Append-Only در `task_executions`.
- **Security & Privacy**: بدون ذخیره صدای خام کودک بدون اجازه صریح.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_pl_s02`

### SCEN-PL-S03: به‌روزرسانی برنامه توسط سرپرست با رعایت سقف زمان روزانه
- **Cohort**: `primary_low`
- **Requirement Reference**: `FR-P3`, `ADR-0004`
- **Preconditions**: برنامه جاری فعال؛ درخواست کاهش ظرفیت از ۲۰ دقیقه به ۱۵ دقیقه.
- **Input Fixture**:
  ```json
  {
    "new_daily_capacity_minutes": 15,
    "reason": "parent_request"
  }
  ```
- **Action**: بازتولید نسخه جدید برنامه با `revision_no = 2`.
- **Expected Output & Validation**: برنامه جدید جایگزین شده و برنامه قبلی به `superseded` تغییر می‌یابد.
- **Expected Persistence**: ایجاد رکورد جدید در `study_plans` با ارجاع به نسخه قبل.
- **Security & Privacy**: فقط والد مجاز به تغییر تنظیمات است.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_pl_s03`

---

## سناریوهای شکست (Failure Scenarios)

### SCEN-PL-F01: رد ثبت‌نام خودکار بدون تاییدیه صریح سرپرست
- **Cohort**: `primary_low`
- **Requirement Reference**: `FR-A2`, `D-04`
- **Preconditions**: کاربر سن ۸ سال وارد کرده اما `guardian_consent: false` است.
- **Input Fixture**:
  ```json
  {
    "stage_code": "primary_low",
    "grade": "G02",
    "guardian_consent": false,
    "daily_study_capacity_minutes": 20
  }
  ```
- **Action**: درخواست ایجاد پروفایل و برنامه.
- **Expected Output & Validation**: خطای اعتبارسنجی `GuardianConsentRequiredError`.
- **Expected Persistence**: هیچ رکوردی در دیتابیس ثبت نمی‌شود؛ هیچ تسکی تخصیص داده نمی‌شود.
- **Security & Privacy**: ممانعت قطعی از جمع‌آوری اطلاعات کودکان زیر سن قانونی.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_pl_f01`

### SCEN-PL-F02: رد تخصیص زمان بیش از سقف مجاز رشد کودک (> ۳۰ دقیقه)
- **Cohort**: `primary_low`
- **Requirement Reference**: `FR-P3`, `ADR-0004`
- **Preconditions**: سقف زمانی استاندارد برای دوره اول ابتدایی ۳۰ دقیقه است.
- **Input Fixture**:
  ```json
  {
    "stage_code": "primary_low",
    "grade": "G01",
    "guardian_consent": true,
    "daily_study_capacity_minutes": 90
  }
  ```
- **Action**: تلاش برای ثبت ظرفیت روزانه ۹۰ دقیقه.
- **Expected Output & Validation**: خطای محدودیت ظرفیت `CapacityExceedsStageLimitError`.
- **Expected Persistence**: عدم ذخیره مقدار نامعتبر.
- **Security & Privacy**: جلوگیری از تحمیل بار نامتناسب بر کودکان خردسال.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_pl_f02`

### SCEN-PL-F03: رد منبع آموزشی فاقد مجوز و وضعیت منتشرنشده
- **Cohort**: `primary_low`
- **Requirement Reference**: `FR-C5`, `ADR-0004`, `D-02`
- **Preconditions**: منبع صوتی دارای وضعیت `Draft` و بدون مجوز پردازش است.
- **Input Fixture**:
  ```json
  {
    "resource_version_id": "res-unlicensed-draft-01",
    "duration_minutes": 15
  }
  ```
- **Action**: اعتبارسنجی ورود منبع به برنامه درسی کودک.
- **Expected Output & Validation**: خطای اعتبارسنجی `ResourceNotPublishedOrUnlicensedError`.
- **Expected Persistence**: رد کامل ثبت در برنامه؛ بدون تغییر در دیتابیس.
- **Security & Privacy**: تضمین نمایش تنها محتوای پالایش‌شده و مجاز.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_pl_f03`
