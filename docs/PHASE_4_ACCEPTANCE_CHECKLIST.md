# Phase 4 — Human Acceptance Checklist

**Reviewer:** _________________________________________  
**Role:** Educational Product Specialist / Pedagogical Expert  
**Review Date:** _________________________________________  
**Package Version:** `docs/PHASE_4_ACCEPTANCE_PACKAGE.md` (Commit `9de59a6`)

---

## Acceptance Criteria

### 1. Daily Progress Reporting
| Criterion | Verified | Notes |
|-----------|----------|-------|
| Persian key-value input format accepted | ☐ | |
| English free-form input format accepted | ☐ | |
| Minimal input (resource IDs only) accepted | ☐ | |
| Response shows completion rate (Persian) | ☐ | |
| Response shows revised plan with session breakdown | ☐ | |
| Weak subjects highlighted in response | ☐ | |

### 2. Plan Revision Mechanics
| Criterion | Verified | Notes |
|-----------|----------|-------|
| Rev 1 → Rev 2 flow demonstrated correctly | ☐ | |
| Missed units carried over to next revision | ☐ | |
| Completed units excluded from future revisions | ☐ | |
| Prerequisite unlocking (e.g., bio_ch1 → bio_ch2) works | ☐ | |
| Revision numbers increment monotonically | ☐ | |
| Prior revision marked `superseded` | ☐ | |

### 3. Immutable History & Audit Trail
| Criterion | Verified | Notes |
|-----------|----------|-------|
| `study_plans` table is versioned, never mutated | ☐ | |
| `study_plan_items` stores per-revision snapshots | ☐ | |
| `daily_progress_logs` is append-only (trigger enforced) | ☐ | |
| History query returns full audit trail | ☐ | |

### 4. Validation & Rejection Behavior
| Scenario | Expected | Verified |
|----------|----------|----------|
| Empty units | 422 error | ☐ |
| Invalid unit ID | 422 error | ☐ |
| Duplicate unit (in both completed & missed) | 422 error | ☐ |
| Duration out of range (0-1440) | 422 error | ☐ |
| No active plan | 400 error | ☐ |
| Completed all units | Returns `curriculum_completed` | ☐ |

### 5. Known Limitations Acknowledged
| Limitation | Acknowledged | Acceptable for MVP? |
|------------|--------------|---------------------|
| No celebration/achievement UX on completion | ☐ | ☐ Yes ☐ No |
| No "review mode" when resources exhausted | ☐ | ☐ Yes ☐ No |
| Only 1-level prerequisite chains in catalog | ☐ | ☐ Yes ☐ No |
| Missed unit not deduplicated against history | ☐ | ☐ Yes ☐ No |
| Track change requires `/restart` | ☐ | ☐ Yes ☐ No |
| Capacity change requires `/restart` | ☐ | ☐ Yes ☐ No |

---

## Open Questions for Reviewer Decision

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Should missed units expire after N days? | ☐ Keep carryover ☐ Add expiry | |
| 2 | Is 50% completion rate motivating or demotivating? | ☐ Keep ☐ Modify display | |
| 3 | Should student notes be analyzed via NLP? | ☐ No ☐ Future phase | |
| 4 | Should deeper prerequisite chains unlock automatically? | ☐ No ☐ Yes (needs catalog update) | |
| 5 | Should `goal_code` affect resource selection/ordering? | ☐ No ☐ Yes (specify) | |
| 6 | Should there be a max revision limit (e.g., 10)? | ☐ No limit ☐ Set limit | |

---

## Acceptance Decision

- ☐ **Accepted** — Phase 4 behavior meets educational product requirements
- ☐ **Conditionally Accepted** — See decisions above; re-verify after changes
- ☐ **Rejected** — Fundamental issues; redesign required

---

## Sign-Off

**Reviewer Signature:** _________________________________________  
**Date:** _________________________________________

**Product Owner Acknowledgement:** _________________________________________  
**Date:** _________________________________________