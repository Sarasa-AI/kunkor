# Phase 4 — Human Acceptance Package: Daily Progress & Plan Revision

**Status:** `READY_FOR_ACCEPTANCE` (Synthetic Only)  
**Target Reviewer:** Educational Product Specialist / Pedagogical Expert  
**Implementation:** `services/api/app/modules/consultation/service.py::handle_progress_and_revision()`  
**Synthetic Tests:** `services/api/tests/test_daily_progress_and_revision.py`, `services/api/tests/test_web_consultation_endpoints.py::test_web_daily_progress_revision_loop`

---

## 1. User-Facing Progress Report Examples

### Telegram /progress Command (Persian & English)

**Input (Persian, key-value):**
```
/progress تکمیل: konkur_bio_g12_ch1 | نرسیدم: konkur_chem_g12_ch1 | زمان: 60 | یادداشت: خوب پیش رفت اما وقت برای تست شیمی کم آوردم
```

**Input (English, free-form):**
```
/progress completed: konkur_bio_g12_ch1, konkur_bio_g12_ch2 missed: konkur_chem_g12_ch1 time: 45 minutes
```

**Input (Minimal - just resource IDs):**
```
/progress konkur_bio_g12_ch1, konkur_chem_g12_ch1
```

### Bot Response (Persian)
```
📊 گزارش پیشرفت شما ثبت شد! درصد تحقق: 50.0%
🔄 برنامه مطالعاتی جدید (ویرایش ۲) بر اساس عملکرد شما بازتنظیم شد:
⏱ مدت زمان کل روزانه: 180 دقیقه
📚 محدودیت‌ها: پایه: G12 | رشته: تجربی | روزان: ۴ ساعت
⚠️ مباحث جبرانی در اولویت: konkur_chem_g12_ch1
واحد‌های مطالعاتی بازنگری‌شده:
1. زیست‌شناسی ۳ — فصل اول: مولکول‌های اطلاعاتی — 60 دقیقه
جلسه‌ها (دقیقه): 60
شناسه گزارش: konkur_bio_g12_ch1
2. شیمی ۳ — فصل اول: مولکول‌ها در خدمت تندرستی — 60 دقیقه
جلسه‌ها (دقیقه): 60
شناسه گزارش: konkur_chem_g12_ch1
...
```

---

## 2. Plan Revision Examples

### Revision 1 → 2 Flow

| Step | Action | Result |
|------|--------|--------|
| 1 | Student completes intake (Konkur G12 Experimental, 4h/day, weak: biology) | Rev 1 generated: 4 units (biology, chemistry, physics, math) |
| 2 | Student submits progress: completed biology, missed chemistry, 60 min | Rev 1 logged, marked `superseded` |
| 3 | System generates Rev 2 | Missed chemistry carried over; biology excluded from future revisions |

**Rev 1 Items:**
```
1. konkur_bio_g12_ch1 (60 min)
2. konkur_chem_g12_ch1 (60 min)
3. konkur_phys_g12_ch1 (60 min)
4. konkur_math_g12_calc (60 min)
Total: 240 min
```

**Progress Input:**
```
completed: [konkur_bio_g12_ch1]
missed: [konkur_chem_g12_ch1]
duration: 60 min
```

**Rev 2 Items:**
```
1. konkur_chem_g12_ch1 (carried over - missed)
2. konkur_phys_g12_ch1 (60 min)
3. konkur_math_g12_calc (60 min)
4. konkur_bio_g12_ch2 (prerequisite: ch1 completed, now unlocked)
Total: 240 min
```

---

## 3. Immutable Plan-Version History

### Database Schema (Enforced by PostgreSQL)

```sql
-- study_plans: versioned, never mutated
CREATE TABLE study_plans (
    id UUID PRIMARY KEY,
    student_id UUID REFERENCES students(id),
    revision_no INT NOT NULL,
    status VARCHAR(20) CHECK (status IN ('active', 'superseded')),
    intake_slots JSONB NOT NULL,
    raw_proposal JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- study_plan_items: per-revision snapshots
CREATE TABLE study_plan_items (
    id UUID PRIMARY KEY,
    plan_id UUID REFERENCES study_plans(id),
    student_id UUID,
    item_order INT,
    resource_version_id VARCHAR(100),
    duration_minutes INT,
    prerequisites JSONB
);

-- daily_progress_logs: append-only (trigger prevents UPDATE/DELETE)
CREATE TABLE daily_progress_logs (
    id UUID PRIMARY KEY,
    student_id UUID,
    plan_id UUID,
    revision_no INT,
    completed_units JSONB,
    missed_units JSONB,
    duration_spent_minutes INT,
    completion_rate NUMERIC(5,2),
    student_notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Append-only trigger
CREATE TRIGGER trg_daily_progress_logs_append_only
BEFORE UPDATE OR DELETE ON daily_progress_logs
FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation();
```

### History Query Example

```sql
-- Full audit trail for student
SELECT 
    sp.revision_no,
    sp.status,
    sp.created_at as plan_created,
    dpl.created_at as progress_logged,
    dpl.completed_units,
    dpl.missed_units,
    dpl.duration_spent_minutes,
    dpl.student_notes
FROM study_plans sp
LEFT JOIN daily_progress_logs dpl ON dpl.plan_id = sp.id
WHERE sp.student_id = $1
ORDER BY sp.revision_no, dpl.created_at;
```

---

## 4. Validation & Rejection Behavior

| Scenario | Input | Expected Outcome |
|----------|-------|------------------|
| Empty units | `completed: [], missed: []` | 422: "Progress requires unique, disjoint active-plan units" |
| Invalid unit ID | `completed: ["nonexistent"]` | 422: "Progress requires unique, disjoint active-plan units" |
| Duplicate unit | `completed: ["bio_ch1"], missed: ["bio_ch1"]` | 422: "disjoint active-plan units" |
| Duration out of range | `duration: 1500` | 422: "duration must be 0 to 1440 minutes" |
| No active plan | (any progress) | 400: "No active study plan found" |
| Completed all units | All units in `completed` | Returns `curriculum_completed`, no new revision |

---

## 5. Edge Cases & Known Limitations

| Edge Case | Current Handling | Limitation |
|-----------|------------------|------------|
| Student completes all units early | Returns `curriculum_completed` status | No celebration/achievement UX |
| All resources exhausted | Same as above | No "review mode" or "maintenance plan" |
| Prerequisite chain depth > 1 | Handled via DAG in validator | Only 1-level prerequisites in catalog |
| Missed unit already completed in history | Prioritized but not deduplicated | Could lead to redundant assignment |
| Student changes track mid-revision | Not supported | Requires `/restart` and new intake |
| Capacity change between revisions | Not supported | Fixed at intake; `/restart` needed |

---

## 6. Questions for Educational/Product Reviewer

1. **Revision pacing**: Is "missed unit carries over to next revision" pedagogically sound, or should missed units expire after N days?

2. **Completion rate display**: Showing 50% (1 of 2 completed) — is this motivating or demotivating for struggling students?

3. **Student notes**: Persian notes stored but not analyzed. Should NLP extract sentiment/actionable feedback?

4. **Prerequisite unlocking**: Currently unlocks immediate dependents only (e.g., bio_ch1 → bio_ch2). Should deeper chains unlock automatically?

3. **Session splitting**: 60-min units split into sessions of `max_session_minutes` (default 60). Is this granularity appropriate for self-paced students?

4. **Goal code impact**: `goal_code` (exam/review/pace) currently affects only session distribution. Should it alter resource selection or ordering?

5. **Revision cap**: No limit on revisions. Should there be a max (e.g., 10 revisions) after which student must `/restart`?

---

## 7. Test Coverage Reference

| Test File | Key Tests |
|-----------|-----------|
| `test_daily_progress_and_revision.py` | Multi-day progress via Telegram webhook, Rev 1→2 revision, prerequisite unlocking, missed unit prioritization, outbox events, historical query |
| `test_web_consultation_endpoints.py::test_web_daily_progress_revision_loop` | Web intake → progress → Rev 2 with missed unit carryover → history query |

**All synthetic tests pass (189/189).** No live Telegram or external AI calls executed.