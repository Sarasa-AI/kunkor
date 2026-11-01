# سناریوهای پذیرش: ابتدایی دوره دوم (`primary_high`)
پایه‌های چهارم تا ششم ابتدایی (سنین ۱۰ تا ۱۲ سال). تمرکز بر ایجاد عادات منظم مطالعه، چک‌این تکالیف، نظارت سرپرست و کنترل پیش‌نیازهای پایه.

---

## سناریوهای موفق (Success Scenarios)

### SCEN-PH-S01: ایجاد برنامه هفتگی روتین ریاضی و فارسی
- **Cohort**: `primary_high`
- **Requirement Reference**: `FR-P3`, `FR-P4`, `D-04`
- **Preconditions**: دانش‌آموز پایه پنجم؛ رضایت سرپرست تایید شده؛ ظرفیت روزانه ۴۵ دقیقه.
- **Input Fixture**:
  ```json
  {
    "stage_code": "primary_high",
    "grade": "G05",
    "guardian_consent": true,
    "daily_study_capacity_minutes": 45,
    "weak_subjects": ["mathematics"]
  }
  ```
- **Action**: اعتبارسنجی و ساخت برنامه با ۲ واحد ۲۰ دقیقه‌ای (ریاضی و فارسی).
- **Expected Output & Validation**: برنامه تایید شده؛ جمع دقایق ۴۰ $\le$ ۴۵ دقیقه ظرفیت روزانه.
- **Expected Persistence**: ذخیره در `study_plans` با شناسه یکتای دانش‌آموز.
- **Security & Privacy**: ثبت در حوزه مجاز `student_id` با کنترل دسترسی سرپرست.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ph_s01`

### SCEN-PH-S02: ثبت موفق چک‌این تکلیف و محاسبه پیشرفت هفتگی
- **Cohort**: `primary_high`
- **Requirement Reference**: `FR-T3`, `FR-M5`
- **Preconditions**: تسک فعال تمرین ریاضی با پیش‌نیاز پاس‌شده.
- **Input Fixture**:
  ```json
  {
    "task_id": "018f-ph-math-05",
    "status": "completed",
    "perceived_difficulty": "medium",
    "completion_evidence": {"exercises_solved": 5, "duration_minutes": 20}
  }
  ```
- **Action**: ثبت رویداد اتمام تسک.
- **Expected Output & Validation**: تایید اتمام و بروزرسانی سنجه درصد تکمیل روزانه.
- **Expected Persistence**: ایجاد رکورد غیرقابل‌تغییر در `task_executions`.
- **Security & Privacy**: ممانعت از ارسال محتوای تصویری تاییدنشده.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ph_s02`

### SCEN-PH-S03: جایگزینی تسک با نسخه جدید هنگام غیبت یا بیماری
- **Cohort**: `primary_high`
- **Requirement Reference**: `FR-T3`, `ADR-0005`
- **Preconditions**: دانش‌آموز یک روز تکالیف را انجام نداده و تسک معوق شده است.
- **Input Fixture**:
  ```json
  {
    "task_id": "018f-ph-math-05",
    "action": "defer",
    "reason_code": "student_sick"
  }
  ```
- **Action**: تعویق تسک و بازتنظیم اولویت برنامه روز بعد.
- **Expected Output & Validation**: تسک قبلی بدون حذف با وضعیت `deferred` بایگانی و تسک جدید با `supersedes_id` درج می‌گردد.
- **Expected Persistence**: درج رکورد با ارجاع زنجیره‌ای به رکورد قبلی.
- **Security & Privacy**: حسابرسی کامل تغییر وضعیت‌ها در `audit_events`.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ph_s03`

---

## سناریوهای شکست (Failure Scenarios)

### SCEN-PH-F01: نقض پیش‌نیاز درسی (تلاش برای حل کسر قبل از آموزش مبنا)
- **Cohort**: `primary_high`
- **Requirement Reference**: `FR-T2`, `ADR-0004`
- **Preconditions**: مبحث «جمع کسرها» نیازمند پیش‌نیاز «مفهوم کسر» است که هنوز پاس نشده.
- **Input Fixture**:
  ```json
  {
    "stage_code": "primary_high",
    "requested_units": [
      {"resource_id": "res-fractions-addition", "prerequisites": ["res-fractions-basics"]}
    ],
    "completed_prerequisites": []
  }
  ```
- **Action**: اعتبارسنجی برنامه در موتور پیش از ثبت در پایگاه داده.
- **Expected Output & Validation**: خطای قطعی `PrerequisiteNotSatisfiedError`.
- **Expected Persistence**: عدم صدور تسک؛ عدم تغییر در جدول `study_plans`.
- **Security & Privacy**: موتور قطعی بدون دخالت پرامپت خطای منطقی را برمی‌گرداند.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ph_f01`

### SCEN-PH-F02: تجاوز زمان کل برنامه روزانه از سقف ظرفیت دانش‌آموز
- **Cohort**: `primary_high`
- **Requirement Reference**: `FR-P3`, `ADR-0004`
- **Preconditions**: ظرفیت تعیین‌شده توسط سرپرست ۴۵ دقیقه است.
- **Input Fixture**:
  ```json
  {
    "daily_study_capacity_minutes": 45,
    "items": [
      {"resource_id": "res-1", "duration_minutes": 30},
      {"resource_id": "res-2", "duration_minutes": 25}
    ]
  }
  ```
- **Action**: اعتبارسنجی ساختار برنامه پیش از ثبت.
- **Expected Output & Validation**: خطای `StudyTimeLimitExceededError` (مجموع ۵۵ > ۴۵).
- **Expected Persistence**: لغو کامل تراکنش (Transaction Rollback).
- **Security & Privacy**: پیشگیری از خستگی مفرط آموزشی دانش‌آموز.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ph_f02`

### SCEN-PH-F03: ویرایش مستقیم رکورد انجام تکلیف (نقض قانون تریگر Append-Only)
- **Cohort**: `primary_high`
- **Requirement Reference**: `ADR-0005`, `TASK-02`
- **Preconditions**: رکورد ثبت‌شده برای تسک قبلی در پایگاه داده وجود دارد.
- **Input Fixture**:
  ```sql
  UPDATE task_executions SET status = 'completed' WHERE execution_id = '018f-exec-01';
  ```
- **Action**: تلاش برای اجرای دستور مستقیم UPDATE.
- **Expected Output & Validation**: خطای دیتابیس با کد SQLSTATE `P0001` (یا رد اعتبارسنجی سطح سرویس).
- **Expected Persistence**: پایگاه داده ردیف را تغییر نمی‌دهد و تراکنش خطا می‌دهد.
- **Security & Privacy**: تضمین اصالت سوابق ارزیابی دانش‌آموز.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ph_f03`
