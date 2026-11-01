# سناریوهای پذیرش: کنکور و پشت‌کنکور (`konkur`)
پایه دوازدهم و داوطلبان فارغ‌التحصیل کنکور سراسری. تمرکز بر مطالعه پرفشار، دوره‌های تست‌زنی سرعتی و مروری، آزمون‌های آزمایشی و صیانت از ظرفیت زیستی.

---

## سناریوهای موفق (Success Scenarios)

### SCEN-KO-S01: تولید برنامه ماراتن مطالعه با ظرفیت ۳۶۰ دقیقه
- **Cohort**: `konkur`
- **Requirement Reference**: `FR-P3`, `FR-P4`, `D-01`
- **Preconditions**: داوطلب رشته تجربی؛ ظرفیت روزانه ۳۶۰ دقیقه (۶ ساعت)؛ هدف کنکور سراسری.
- **Input Fixture**:
  ```json
  {
    "stage_code": "konkur",
    "grade": "G12",
    "track": "experimental",
    "daily_study_capacity_minutes": 360,
    "target_exam": "konkur_1406",
    "weak_subjects": ["mathematics", "physics"]
  }
  ```
- **Action**: تخصیص بلوک‌های مطالعاتی ۶۰ تا ۹۰ دقیقه‌ای متناسب با آزمون سراسری.
- **Expected Output & Validation**: برنامه با مجموع ۳۶۰ دقیقه دقیق، رعایت پیش‌نیازها و اولویت دروس ضعیف تایید می‌گردد.
- **Expected Persistence**: ذخیره در `study_plans` با `revision_no = 1` و وضعیت `active`.
- **Security & Privacy**: بدون ارتباط با سرویس‌های متفرقه بدون مجوز.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ko_s01`

### SCEN-KO-S02: ثبت دستی نتایج آزمون آزمایشی (بدون وابستگی به OCR)
- **Cohort**: `konkur`
- **Requirement Reference**: `FR-T3`, `D-03`
- **Preconditions**: داوطلب در آزمون جامع شرکت کرده و کارنامه دریافت کرده است.
- **Input Fixture**:
  ```json
  {
    "exam_title": "جامع سنجش ۱",
    "exam_date": "2026-11-15",
    "scores": {
      "biology": 72.5,
      "chemistry": 64.0,
      "physics": 55.0,
      "mathematics": 48.0
    }
  }
  ```
- **Action**: ورود دستی درصدها بدون ابزارهای ناامن OCR مطابق تصمیم `D-03`.
- **Expected Output & Validation**: اعتبارسنجی درصدهای بین ۰ تا ۱۰۰ و ثبت موفق نمرات.
- **Expected Persistence**: درج رکورد در سوابق آزمایشی داوطلب.
- **Security & Privacy**: ثبت صرفاً در محدوده کاربری دانش‌آموز (`student_id`).
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ko_s02`

### SCEN-KO-S03: چرخه مرور فاصله‌دار تسک‌های تست‌زنی
- **Cohort**: `konkur`
- **Requirement Reference**: `FR-T1`, `FR-T2`
- **Preconditions**: مبحث «حرکت‌شناسی فیزیک» ۵ روز پیش تست‌زنی شده است.
- **Input Fixture**:
  ```json
  {
    "topic_id": "top-physics-kinematics",
    "last_reviewed_days_ago": 5,
    "review_cycle_interval_days": 5
  }
  ```
- **Action**: پیشنهاد تسک مرور سریع ۲۰ تست منتخب توسط موتور قوانین.
- **Expected Output & Validation**: ایجاد تسک مرور در برنامه روز جاری با شناسه قانون `rule_spaced_repetition_v1`.
- **Expected Persistence**: افزودن تسک به برنامه فعال روزانه.
- **Security & Privacy**: حفظ حریم داده‌ها و جلوگیری از انتشار آمارهای فردی.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ko_s03`

---

## سناریوهای شکست (Failure Scenarios)

### SCEN-KO-F01: رد برنامه با زمان بیش از سقف فیزیولوژیک انسانی (> ۶۰۰ دقیقه)
- **Cohort**: `konkur`
- **Requirement Reference**: `FR-P3`, `ADR-0004`
- **Preconditions**: داوطلب یا هوش مصنوعی برنامه‌ای با ۱۲ ساعت (۷۲۰ دقیقه) مطالعه پیشنهاد می‌دهد.
- **Input Fixture**:
  ```json
  {
    "stage_code": "konkur",
    "daily_study_capacity_minutes": 720
  }
  ```
- **Action**: اعتبارسنجی درخواست در موتور قطعی.
- **Expected Output & Validation**: خطای `PhysiologicalCapacityExceededError` (سقف مجاز حداکثر ۶۰۰ دقیقه یا ۱۰ ساعت است).
- **Expected Persistence**: لغو کامل و ممانعت از ثبت در پایگاه داده.
- **Security & Privacy**: جلوگیری از تحمیل رفتارهای مخاطره‌آمیز روحی و جسمی به داوطلبان کنکور.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ko_f01`

### SCEN-KO-F02: رد پیشنهاد برنامه هوش مصنوعی به دلیل نقض پیش‌نیاز درسی
- **Cohort**: `konkur`
- **Requirement Reference**: `ADR-0004`, `ADR-0006`, `D-07`
- **Preconditions**: مدل زبانی بیرونی (از طریق 9router) برنامه‌ای ارائه داده که در آن «مشتق و کاربرد مشتق» قبل از «مفهوم حد و پیوستگی» قرار گرفته است.
- **Input Fixture**:
  ```json
  {
    "source": "9router_proposal",
    "items": [
      {"resource_id": "res-calculus-derivatives", "prerequisites": ["res-calculus-limits"]},
      {"resource_id": "res-calculus-limits", "prerequisites": []}
    ],
    "ordered_sequence": ["res-calculus-derivatives", "res-calculus-limits"]
  }
  ```
- **Action**: اعتبارسنجی قطعی خروجی مدل توسط `DeterministicValidator`.
- **Expected Output & Validation**: اعتبارسنج خروجی LLM را فاقد اعتبار دانسته، تراکنش را رد کرده و به سیستم قوانین قطعی Fallback می‌کند.
- **Expected Persistence**: پیشنهاد رد شده در پایگاه داده ذخیره نمی‌شود.
- **Security & Privacy**: ایزولاسیون کامل هسته سامانه از توهمات یا خروجی‌های نامعتبر هوش مصنوعی.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ko_f02`

### SCEN-KO-F03: ورود درصد نامعتبر یا غیرممکن در آزمون آزمایشی
- **Cohort**: `konkur`
- **Requirement Reference**: `FR-T3`, `D-03`
- **Preconditions**: دامنه معتبر درصد در سیستم سنجش ایران بین ۳۳٫۳۳- تا ۱۰۰٪ است.
- **Input Fixture**:
  ```json
  {
    "exam_title": "جامع آزمایشی",
    "scores": {
      "mathematics": 115.0
    }
  }
  ```
- **Action**: اعتبارسنجی داده ورودی کارنامه.
- **Expected Output & Validation**: خطای `ScoreOutOfRangeError`.
- **Expected Persistence**: عدم درج رکورد غلط در جداول آزمون.
- **Security & Privacy**: حفظ اعتبار و صحت محاسبات آماری سامانه.
- **Execution Status**: `AUTOMATED`
- **Related Test**: `services/api/tests/test_scenarios.py::test_scen_ko_f03`
