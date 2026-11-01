# سناریوهای پذیرش: متوسطه دوره اول (`lower_secondary`)
پایه‌های هفتم تا نهم (سنین ۱۳ تا ۱۵ سال). تمرکز بر مدیریت چنددرس، تنوع در واحدهای آموزشی، ایجاد عادات خودفرمان و عبور ایمن به متوسطه دوم.

---

## سناریوهای موفق (Success Scenarios)

### SCEN-LS-S01: توازن برنامه‌ریزی دروس علوم و ریاضی با ظرفیت ۱۲۰ دقیقه
- **Cohort**: `lower_secondary`
- **Requirement Reference**: `FR-P3`, `FR-P4`, `FR-T2`
- **Preconditions**: دانش‌آموز پایه هشتم؛ ظرفیت روزانه ۱۲۰ دقیقه؛ ضعف در درس ریاضی.
- **Input Fixture**:
  ```json
  {
    "stage_code": "lower_secondary",
    "grade": "G08",
    "daily_study_capacity_minutes": 120,
    "weak_subjects": ["mathematics"],
    "target_exam": "term_exams"
  }
  ```
- **Action**: تخصیص بلوک‌های ۴۰ دقیقه‌ای ریاضی، ۳۰ دقیقه‌ای علوم و ۳۰ دقیقه‌ای زبان.
- **Expected Output & Validation**: تایید برنامه با مجموع ۱۰۰ دقیقه ($\le$ ۱۲۰ دقیقه) و اولویت‌دهی به درس ریاضی.
- **Expected Persistence**: ایجاد سند `study_plans` با شناسه نسخه `v1.0.0`.
- **Security & Privacy**: کنترل دسترسی و اتصال به حساب کاربر طبق `ADR-0003`.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ls_s01`

### SCEN-LS-S02: زنجیره وابستگی چندمرحله‌ای پیش‌نیازها
- **Cohort**: `lower_secondary`
- **Requirement Reference**: `FR-T2`, `ADR-0004`
- **Preconditions**: زنجیره درسی: مثلثات مقدماتی $\rightarrow$ مساحت مثلث $\rightarrow$ حل مسائل ترکیبی.
- **Input Fixture**:
  ```json
  {
    "units": [
      {"id": "U1", "prerequisites": []},
      {"id": "U2", "prerequisites": ["U1"]},
      {"id": "U3", "prerequisites": ["U2"]}
    ],
    "completed_units": ["U1"]
  }
  ```
- **Action**: بررسی اعتبار تخصیص واحد `U2`.
- **Expected Output & Validation**: تخصیص موفق واحد `U2` و عدم ارائه `U3` تا زمان تکمیل `U2`.
- **Expected Persistence**: تخصیص فقط واحد معتبر به برنامه فعال دانش‌آموز.
- **Security & Privacy**: اعتبارسنجی قطعی گراف جهت‌دار بدون دور (DAG).
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ls_s02`

### SCEN-LS-S03: تسلیم گزارش پایان هفته و صدور سنجه استمرار
- **Cohort**: `lower_secondary`
- **Requirement Reference**: `FR-M5`, `FR-T3`
- **Preconditions**: دانش‌آموز ۵ روز متوالی حداقل ۸۰٪ تکالیف را تکمیل کرده است.
- **Input Fixture**:
  ```json
  {
    "student_id": "018f-ls-student-01",
    "week_number": 4,
    "completed_days": 5
  }
  ```
- **Action**: محاسبه شاخص استمرار (Streak) طبق `D-08`.
- **Expected Output & Validation**: محاسبه استمرار بدون به‌کارگیری مکانیسم‌های فریبنده یا تاریک (Dark Patterns).
- **Expected Persistence**: ثبت سنجه در لاگ پیشرفت تحصیلی دانش‌آموز.
- **Security & Privacy**: ایزولاسیون کامل رکورد با ستون `student_id` (ADR-0008).
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ls_s03`

---

## سناریوهای شکست (Failure Scenarios)

### SCEN-LS-F01: کشف و رد چرخه در گراف پیش‌نیازها (Circular Dependency)
- **Cohort**: `lower_secondary`
- **Requirement Reference**: `FR-T2`, `ADR-0004`
- **Preconditions**: ایجاد اشتباه محتوایی در ارتباط دروس: A نیازمند B و B نیازمند A.
- **Input Fixture**:
  ```json
  {
    "units": [
      {"id": "res-cycle-A", "prerequisites": ["res-cycle-B"]},
      {"id": "res-cycle-B", "prerequisites": ["res-cycle-A"]}
    ]
  }
  ```
- **Action**: بررسی گراف در موتور اعتبارسنجی پیش از ذخیره.
- **Expected Output & Validation**: خطای قطعی `CyclicDependencyError`.
- **Expected Persistence**: رد کامل پیشنهاد؛ عدم اعمال بر روی بانک اطلاعاتی.
- **Security & Privacy**: ممانعت از ایجاد لوپ نامتناهی در موتور پیشنهاددهنده.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ls_f01`

### SCEN-LS-F02: تخصیص منابع خارج از مقطع تحصیلی (Cross-Stage Contamination)
- **Cohort**: `lower_secondary`
- **Requirement Reference**: `FR-C5`, `ADR-0004`
- **Preconditions**: دانش‌آموز پایه هشتم است، اما منبع درخواستی متعلق به سال دوازدهم کنکور است.
- **Input Fixture**:
  ```json
  {
    "student_stage": "lower_secondary",
    "resource_stage": "konkur",
    "resource_id": "res-konkur-calculus-01"
  }
  ```
- **Action**: اعتبارسنجی همخوانی مقطع محتوا و کاربر.
- **Expected Output & Validation**: خطای `StageMismatchError`.
- **Expected Persistence**: رد ذخیره‌سازی تسک.
- **Security & Privacy**: ایزولاسیون مرزهای آموزشی پایه‌ها.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ls_f02`

### SCEN-LS-F03: پرش نسخه برنامه (Invalid Revision Sequence)
- **Cohort**: `lower_secondary`
- **Requirement Reference**: `ADR-0005`, `TASK-02`
- **Preconditions**: نسخه فعال جاری `revision_no = 2` است.
- **Input Fixture**:
  ```json
  {
    "plan_id": "018f-ls-plan-01",
    "submitted_revision_no": 5,
    "expected_revision_no": 3
  }
  ```
- **Action**: ثبت برنامه ویرایش‌شده با شماره نسخه نامعتبر.
- **Expected Output & Validation**: خطای `RevisionConflictError` یا ناسازگاری نسخه.
- **Expected Persistence**: رد کامل رونویسی و لغو تراکنش.
- **Security & Privacy**: جلوگیری از تداخل بازنویسی هم‌زمان (Optimistic Locking).
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ls_f03`
