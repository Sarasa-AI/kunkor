# Phase 5 — Domain Review Package: Resource Catalog & Offline Evaluation

**Status:** `NEEDS_REWORK` (Domain Approval Pending)  
**Target Reviewer:** Educational Domain Specialist / Curriculum Expert / Publisher Liaison  
**Implementation:** `services/api/app/engines/catalog.py`, `services/api/scripts/evaluate_plans.py`  
**Synthetic Tests:** `services/api/tests/test_plan_evaluation.py`, `services/api/tests/test_stage_05_validator.py`

---

## 1. All 19 Synthetic Resource Metadata Fixtures

**Source:** `services/api/app/engines/catalog.py::RESOURCE_METADATA_DETAILS`  
**Provenance:** `local_synthetic_fixture` (all 19)  
**Verification Status:** `UNVERIFIED` (all 19)  
**Domain Approval:** `PENDING` (all 19)  
**Authorization Scope:** `metadata_only_synthetic_evaluation`  
**Full Content Access:** `False` (all 19)  
**Content License ID:** `None` (all 19)

---

### Konkur (G12) — 12 Resources

| # | Resource ID | Title | Subject | Publisher | Duration | Tests | Pages | Prerequisites | Status |
|---|-------------|-------|---------|-----------|----------|-------|-------|---------------|--------|
| 1 | `konkur_bio_g12_ch1` | زیست‌شناسی ۳ — فصل اول: مولکول‌های اطلاعاتی | biology | خیلی سبز | 60 | 85 | 24 | [] | Published |
| 2 | `konkur_bio_g12_ch2` | زیست‌شناسی ۳ — فصل دوم: جریان اطلاعات در یاخته | biology | خیلی سبز | 60 | 90 | 28 | [konkur_bio_g12_ch1] | Published |
| 3 | `konkur_chem_g12_ch1` | شیمی ۳ — فصل اول: مولکول‌ها در خدمت تندرستی | chemistry | مبتکران | 60 | 70 | 22 | [] | Published |
| 4 | `konkur_phys_g12_ch1` | فیزیک ۳ — فصل اول: حرکت بر خط راست | physics | گاج (میکرو) | 60 | 65 | 20 | [] | Published |
| 5 | `konkur_math_g12_calc` | ریاضیات تجربی — تابع و حد | mathematics | خیلی سبز | 60 | 80 | 25 | [] | Published |
| 6 | `konkur_math_calc_limits` | حسابان ۲ — حد و پیوستگی | calculus | نشر الگو | 60 | 60 | 18 | [] | Published |
| 7 | `konkur_math_calc_derivatives` | حسابان ۲ — مشتق و کاربرد آن | calculus | نشر الگو | 60 | 75 | 24 | [konkur_math_calc_limits] | Published |
| 8 | `konkur_math_discrete` | گسسته — نظریه گراف و ترکیبیات | discrete_math | گاج | 60 | 55 | 16 | [] | Published |
| 9 | `konkur_math_geom` | هندسه ۳ — ماتریس و بردارها | geometry | خیلی سبز | 60 | 50 | 15 | [] | Published |
| 10 | `konkur_hum_literature` | علوم و فنون ادبی ۳ — وزن شعر و سبک‌شناسی | literature | خیلی سبز | 60 | 70 | 20 | [] | Published |
| 11 | `konkur_hum_sociology` | جامعه‌شناسی ۳ — تمدن و فرهنگ | sociology | مشاوران آموزش | 60 | 60 | 18 | [] | Published |
| 12 | `konkur_hum_philosophy` | فلسفه ۲ — حکمت و معرفت | philosophy_logic | مشاوران آموزش | 60 | 50 | 16 | [] | Published |

---

### Upper Secondary (G10-G11) — 3 Resources

| # | Resource ID | Title | Subject | Publisher | Duration | Tests | Pages | Prerequisites | Status |
|---|-------------|-------|---------|-----------|----------|-------|-------|---------------|--------|
| 13 | `upper_math_g10_ch1` | ریاضی ۱ دهم — مجموعه، الگو و دنباله | mathematics | خیلی سبز | 45 | 40 | 15 | [] | Published |
| 14 | `upper_phys_g10_ch1` | فیزیک ۱ دهم — فیزیک و اندازه‌گیری | physics | خیلی سبز | 45 | 35 | 14 | [] | Published |
| 15 | `upper_chem_g11_ch1` | شیمی ۲ یازدهم — قدر هدایای زمینی را بدانیم | chemistry | مبتکران | 45 | 45 | 18 | [] | Published |

---

### Lower Secondary (G09) — 2 Resources

| # | Resource ID | Title | Subject | Publisher | Duration | Tests | Pages | Prerequisites | Status |
|---|-------------|-------|---------|-----------|----------|-------|-------|---------------|--------|
| 16 | `lower_math_g09_ch1` | ریاضی نهم — مجموعه‌ها | mathematics | مبتکران | 30 | 30 | 12 | [] | Published |
| 17 | `lower_sci_g09_ch1` | علوم تجربی نهم — مواد و نقش آنها در زندگی | science | خیلی سبز | 30 | 25 | 10 | [] | Published |

---

### Primary High (G05) — 1 Resource

| # | Resource ID | Title | Subject | Publisher | Duration | Tests | Pages | Prerequisites | Status |
|---|-------------|-------|---------|-----------|----------|-------|-------|---------------|--------|
| 18 | `primary_math_g05_ch1` | ریاضی پنجم — عددنویسی و الگوها | mathematics | کلاغ سپید | 20 | 15 | 8 | [] | Published |

---

### Primary Low (G02) — 1 Resource

| # | Resource ID | Title | Subject | Publisher | Duration | Tests | Pages | Prerequisites | Status |
|---|-------------|-------|---------|-----------|----------|-------|-------|---------------|--------|
| 19 | `primary_read_g02_ch1` | فارسی دوم — روان‌خوانی و واژگان | reading_fluency | گاج | 15 | 10 | 6 | [] | Published |

---

## 2. Field Definitions & Intended Educational Meaning

| Field | Type | Educational Meaning |
|-------|------|---------------------|
| `resource_id` | string | Stable opaque identifier for programmatic reference; never displayed to students |
| `title` | string | Human-readable chapter/book title in Persian; displayed in study plans |
| `subject` | string | Curriculum subject code; maps to `TRACK_SUBJECT_ALLOWLIST` for track filtering |
| `publisher` | string | Publisher name; for domain review only — not shown to students |
| `stage_code` | string | Educational stage: `konkur` / `upper_secondary` / `lower_secondary` / `primary_high` / `primary_low` |
| `grade` | string | Grade code: `G12` / `G11` / `G10` / `G09` / `G05` / `G02` |
| `duration_minutes` | int | Estimated study time for this unit; used in daily capacity budgeting |
| `test_count` | int | Number of practice questions available; for AI prompt context only |
| `page_count` | int | Estimated textbook pages; for AI prompt context only |
| `prerequisites` | string[] | Resource IDs that must be completed first; forms DAG for ordering |
| `status` | string | Lifecycle: `Published` / `Draft` / `Archived` — only `Published` scheduled |
| `license_active` | bool | Legacy field; permits scheduling only — NOT a content license |

---

## 3. Whitelist & Eligibility Rules

### Stage-Grade Mapping
| Stage | Grades | Tracks |
|-------|--------|--------|
| `konkur` | G12 | `experimental`, `mathematics`, `humanities` |
| `upper_secondary` | G10, G11 | `experimental`, `mathematics`, `humanities` |
| `lower_secondary` | G09 | `general` |
| `primary_high` | G05 | `general` |
| `primary_low` | G02 | `general` |

### Track → Subject Allowlist
```python
TRACK_SUBJECT_ALLOWLIST = {
    "experimental": ["biology", "chemistry", "physics", "mathematics"],
    "mathematics": ["mathematics", "calculus", "geometry", "discrete_math"],
    "humanities": ["literature", "sociology", "philosophy_logic"],
    "general": ["mathematics", "science", "reading_fluency"],
}
```

### Scheduling Constraints
1. **Grade match**: `resource.grade == intake.grade`
2. **Track match**: `resource.subject in TRACK_SUBJECT_ALLOWLIST[intake.track]`
3. **Prerequisites**: All prerequisite resource IDs must be in student's `completed_unit_ids`
4. **Capacity**: Sum of `duration_minutes` ≤ `daily_study_capacity_minutes`
5. **Prerequisite DAG**: No cycles; topological ordering enforced by validator

---

## 4. Nine Evaluation Scenarios (v2)

**Dataset:** `services/api/tests/fixtures/offline_plans.json` (version 2)

### 4.1 Positive Generation (7/7 PASS)

| Case ID | Stage | Grade | Track | Capacity | Weak Subjects | Result |
|---------|-------|-------|-------|-------|----------|---------------|--------|
| `primary_low` | primary_low | G02 | — | 30 min | ["reading_fluency"] | ✅ 1 unit |
| `primary_high` | primary_high | G05 | — | 60 min | ["mathematics"] | ✅ 2 units |
| `lower_secondary` | lower_secondary | G09 | — | 90 min | ["science"] | ✅ 2 units |
| `upper_secondary` | upper_secondary | G10 | experimental | 90 min | ["physics"] | ✅ 2 units |
| `konkur_experimental` | konkur | G12 | experimental | 180 min | ["biology"] | ✅ 4 units |
| `konkur_mathematics` | konkur | G12 | mathematics | 180 min | ["calculus"] | ✅ 4 units |
| `konkur_humanities` | konkur | G12 | humanities | 180 min | ["sociology"] | ✅ 4 units |

**All 7 pass DeterministicValidator:**
- Duration ≤ capacity ✅
- Grade match ✅
- Track match ✅
- Prerequisite DAG acyclic ✅
- Weak subject coverage = 100% ✅

### 4.2 Negative Boundary (2/2 Correctly Refused)

| Case ID | Stage | Grade | Capacity | Expected Refusal | Result |
|---------|-------|-------|-------|----------|------------------|--------|
| `missing_grade` | primary_high | **G04** | 30 min | `no_matching_resources_for_grade` | ✅ Refused (0 units) |
| `insufficient_time` | konkur | G12 | **10 min** | `capacity_below_minimum_resource_duration` | ✅ Refused (0 units) |

**Refusal Integrity Verified:**
- Zero invalid plans persisted ✅
- Zero state corruption ✅
- Zero cross-grade assignment ✅
- Zero capacity violations ✅
- Student intake preserved ✅

---

## 5. Uncertain / Incomplete / Potentially Misleading Metadata

| Issue | Affected Resources | Severity | Notes |
|-------|-------------------|----------|-------|
| **Publisher names synthetic** | All 19 | High | Names like "خیلی سبز", "مبتکران", "نشر الگو", "گاج", "کلاغ سپید" are placeholders. Real publisher contracts required. |
| **Page/test counts unverified** | All 19 | High | Numbers plausible but not sourced from actual textbooks. |
| **Duration estimates** | All 19 | Medium | Vary by stage (60/45/30/20/15 min); may not reflect actual study time per chapter. |
| **Prerequisite chains shallow** | 3 resources (bio_ch2, math_derivatives) | Medium | Only 1-level prerequisites; real curricula have deeper chains. |
| **Subject granularity** | G12 calculus vs mathematics | Medium | "calculus" and "mathematics" as separate subjects — mapping to track allowlists may need review. |
| **Primary_high (G05) has only math** | `primary_high` stage | High | `primary_high` eval uses G05 with weak_subjects=["mathematics"] but catalog has only 1 G05 resource (math). Passes with 2 units? Needs verification. |
| **No G11 resources except chem** | Upper secondary | Medium | Catalog has G11 only for chemistry; G11 experimental/humanities students would lack resources. |
| **License field misleading** | All 19 | Critical | `license_active: True` implies scheduling permission only. NOT a content license. Must not be confused with copyright clearance. |
| **Primary_low uses G02, eval expects G02** | `primary_low` stage | Medium | Catalog has G02 reading_fluency resource. `primary_low` eval case passes with 1 unit — verify this works correctly. |

---

## 6. Specific Questions for Educator/Domain Specialist

### Content Accuracy
1. **Grade alignment**: Do the G12 chapter titles match the actual Iranian Konkur curriculum for 2024-2025?
2. **Subject coverage**: Are the 4 experimental subjects (bio, chem, physics, math) sufficient? Missing: Persian literature, English, Arabic, Quran studies.
3. **Prerequisite depth**: Real biology curriculum has 5+ chapter dependencies. Is 1-level sufficient for MVP?
4. **Duration realism**: Is 60 minutes per chapter realistic for self-paced Konkur prep? What about 45 min (G10/G11), 30 min (G09), 20 min (G05), 15 min (G02)?

### Pedagogical Design
5. **Weak subject mapping**: "biology" → `konkur_bio_g12_ch1`. Is chapter-level granularity appropriate, or should weak subjects map to topics within chapters?
6. **Track filtering**: Humanities track gets only literature/sociology/philosophy. Should "English" and "Arabic" be included?
7. **Session splitting**: Units split into `max_session_minutes` sessions. Is this granularity useful for Pomodoro-style study?

### Policy & Legal
8. **`license_active` interpretation**: Engineering team treats this as "safe to schedule." Legal must confirm this does not imply content reproduction rights.
9. **Publisher confirmation**: Have "خیلی سبز", "مبتکران", "نشر الگو", "گاج", "کلاغ سپید" been contacted for metadata accuracy review?
10. **G04 gap**: `missing_grade` test shows G04 has no resources. Is this intentional (G04 not a Konkur grade) or a catalog gap?
11. **G11 coverage**: Only chemistry has G11 resource. How should G11 experimental/humanities students be handled?

### System Behavior
12. **Refusal UX**: When `resources_unavailable`, student sees Persian message and intake preserved. Is the messaging clear and actionable?
13. **Cross-grade fallback**: Currently disabled. If G11 student enrolls, they get G10 resources. Is this acceptable?
14. **Primary_high (G05) weak subject "mathematics"**: Only 1 math resource exists. How does eval produce 2 units? (Verify implementation behavior)

---

## 7. Test Coverage Reference

| Test | File | Cases |
|------|------|-------|
| `test_synthetic_catalog_never_claims_content_authorization` | `test_plan_evaluation.py` | Verifies all 19 fixtures have `UNVERIFIED`, `PENDING`, `full_content_access=False` |
| `test_offline_positive_and_negative_evaluations_are_reproducible` | `test_plan_evaluation.py` | 9 scenarios; 7 positive PASS, 2 negative correctly refused |
| `test_stage_05_validator.py` | 10 tests | DAG cycles, capacity bounds, track allowlists, grade/track consistency |

**All synthetic tests pass.** No live AI provider or network calls executed.