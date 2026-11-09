# Feature Pipeline — Usage (Lean Mode)

`/plan-feature` (requirements) and `/plan-slicing` (contract, slices, steps) form a streamlined, anti-overmanagement pipeline.
All specifications, open questions, stories, step execution ladders, and follow-ups live in **`plans/<EPIC>/PLAN.md`**, with shared code types in **`plans/<EPIC>/CONTRACT.md`**.

## Pick a path first

| Situation | Path |
|---|---|
| One story, no shared state, one developer | **Small feature** — `/plan-feature` only (writes `PLAN.md`) |
| 2+ stories sharing data, or 2+ developers | **Epic** — `/plan-feature` → `/plan-slicing` (`PLAN.md` + `CONTRACT.md`) |
| Rewriting an existing screen's architecture | `/refactor-legacy` |

---

## Epic Path (Lean 2-File Architecture)

### 1. Requirements & Scoping (Lead, once)

```
/plan-feature <TICKET_OR_EPIC>
PRD: ~/Documents/specs/<path>.md
Figma: <url or node id>
API: <path or link>
Replaces: <screen being replaced, if any>
```

- **Output:** Creates `plans/<EPIC>/PLAN.md` (Sections 1: Sources, 2: Questions & Assumptions, 3: Stories & Acceptance Criteria).
- **Gate:** PM/BE questions resolved or carrying assumption in force; Phase 1 cut confirmed.

### 2. Contract and Slices Overview (Lead, Session 1)

```
/plan-slicing init <EPIC>
```

- **Output:**
  1. Writes `plans/<EPIC>/CONTRACT.md` (Shared models, Repository/UseCase interfaces, MVI state/intent/event).
  2. Appends `§4 Slices Overview` table (`Status: NOT PLANNED`) into `plans/<EPIC>/PLAN.md`.
- **Anti-Hallucination Boundary:** Does NOT plan individual steps for all slices upfront.
- **Handoff:** Review `CONTRACT.md` with the team, then **run `/clear` (open a fresh session)**.

### 3. Plan Your Assigned Slice Outline (Developer, Session 2)

```
/plan-slicing plan slice-01
```

- **Output:** Cuts **only `slice-01`** into a lightweight 3–5 step outline (`step-01`..`step-05`: Scope goal + Acceptance Criteria) directly inside `PLAN.md §4`.
- **Granularity:** 3–5 steps, each step = one MR (150–250 lines diff, ≤ 300 max).
- **Handoff:** Once the step ladder for `slice-01` is saved, **run `/clear` (open a fresh session)** before building `step-01`.

### 4. Micro-Plan & Build One Step Per Fresh Session (Developer, Session 3..N)

```
/plan-slicing step slice-01 step-01
```

- **1 Step = 1 Fresh Session = 1 MR:**
  - **JIT Micro-Plan:** Scans the codebase only for `step-01`, identifies the exact 3–5 files to touch, and fills in `step-01`'s `Tasks` in `PLAN.md §4`.
  - **Scope isolation:** Touch only layers for `step-01` under `rules/code-hygiene.md`.
  - **Mergeable discipline:** `step-02` (walking skeleton) merges behind a feature flag or unreachable router.
  - **Tests & Budget check:** At most one test file per step; `git diff --stat <target> -- . ':!*/res/*'` (≤ 300 lines).
  - **Repeat:** Commit/ship MR via `/ship-mr`, then **run `/clear`** before starting `step-02` in a new session.

### 5. Keep Status Updated & Handle Mid-Flight Changes (PRD / Figma / BE)

| Say | Effect |
|---|---|
| `slice-01 step-02 in review, MR !1234` | Updates `step-02` status to `REVIEWING` with MR link in `PLAN.md §4` |
| `slice-01 step-02 merged` | Ticks checkbox, marks `DONE` with commit hash in `PLAN.md §4` |
| `slice-01 step-03 blocked — missing BE API` | Marks `BLOCKED` with reason in `PLAN.md §4`; dependent steps `ON HOLD` |
| `question-02 answered: <ruling>` | Updates `PLAN.md §2` and keeps rejected option as history |
| `"BE/PM changed <X> while I'm in step-02"` | **Speed 1 (Quick Triage):** If it doesn't collide with `step-02`, parks a row in `PLAN.md §2 Pending Deltas` so you finish `step-02` with **zero context switch** |
| `/plan-slicing delta <EPIC>` | **Speed 2 (At `/clear` boundary):** Runs `guard-blast` Mode 1 (`Plan → Strategy`), updates `CONTRACT.md` / `TODO` steps or appends a `step-06 (Delta + Regression)` for `DONE` steps |
| `/plan-slicing progress <EPIC>` | Reports step progress directly from `PLAN.md §4` verified against git |

---

## Small-Feature Path

```
/plan-feature <TICKET_OR_EPIC>
```

Generates `PLAN.md` with Sections 1–4 directly. No `CONTRACT.md` needed. Step order follows the same discipline: logic → skeleton → happy path → errors → polish.
