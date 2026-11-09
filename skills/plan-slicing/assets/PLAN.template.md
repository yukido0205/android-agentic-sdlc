# Feature & Execution Plan — <EPIC / FEATURE NAME>

> **Status:** 🟡 DRAFT | 🟢 READY TO BUILD | 🚀 IN PROGRESS | ✅ DONE
> **Lead / Owner:** <Name>
> **Architecture:** Android MVI (`handleIntent`) + Clean Architecture
> **Files:** Lean 2-File Mode (`PLAN.md` + optional `CONTRACT.md`)

---

## 1 · Triad Sources & Scope
- **PRD:** <link, pinned version + commit>
- **Figma:** <link / file key / node IDs>
- **API Docs:** <path / endpoint specs>
- **Replaced Screen (if any):** <screen being replaced, or None>
- **Phase 1 Goal:** <1-2 sentences on what this milestone ships>

---

## 2 · Open Questions & Assumptions (Anomaly Triangle)
> Self-contained table for discrepancies, gaps, and assumptions.
> When asking PM/Design: Use visual & UX terms (No developer jargon).
> When asking BE: Use data flow & field responsibilities.

| Question ID | Discrepancy / Question | Owner | Assumption in force (Defensive Strategy) | Blocks | Status |
|---|---|---|---|---|---|
| question-01 | <short summary> | PM / BE / Design | <Safe fallback / mock fixture> | <step/slice> | Open |

### Detailed Questions & Copy-Paste Clarification Snippets

#### question-01 — <Discrepancy Title>
- **Flow & Screen:** <What the user is doing on which screen>
- **Discrepancy (PRD vs Figma vs API):**
  - **PRD (§n):** <exact quote or spec>
  - **Figma (`node_id`):** <design behavior>
  - **API:** <endpoint / payload>
- **Technical Release Risk:** <What fails or breaks if assumed wrong>
- **Client Defensive Strategy:** <Safe fallback, mock, or neutral state>

> 💬 **Slack / Teams Snippet (Persona-Aware):**
>
> `@<Role>: For [<Screen / Flow Name>], we noticed a specification discrepancy:
> - **Design / Current:** <visual / behavior per Figma or code>
> - **PRD:** <behavior per spec>
>
> Please confirm the preferred approach:
> 👉 **[A]** <Option A in product/data terms>
> 👉 **[B]** <Option B in product/data terms>
>
> *(Client is temporarily proceeding with [A]. If no reply by [Deadline: e.g. 5:00 PM tomorrow], we will lock A to maintain schedule).*`

### Pending Spec / Design / BE Deltas (Focus-First Queue)
> Mid-step requirement/design/API changes that do NOT directly block the currently `IN PROGRESS` step are parked here first (Speed 1 — Zero Context Switch), then processed at the next `/clear` boundary via `/plan-slicing delta <EPIC>` (Speed 2).

| Delta ID | Source (`PRD` / `Figma` / `BE`) | Summary of Change | Collides with Active Step? | Complexity (`L1` / `L2` / `L3`) | Target Action / Delta Step | Status |
|---|---|---|---|---|---|---|
| delta-01 | <e.g. BE API v2> | <short summary> | No (Parked during `step-02`) | <TBD at `/clear`> | <e.g. Update `step-03` AC / Add `step-06`> | Queued for `/clear` |

---

## 3 · User Stories & Acceptance Criteria
> Focus 100% on the **Anomaly Triangle**: edge cases, missing data fallbacks, timeouts, stored invariants (`act → leave → reopen → observe`).
> Zero Happy Path prose: standard flows are 1 line: `[State] + [Event] -> [Target State]`.

### Story 01: <Title>
*As a <actor>, I want <capability>, so that <value>.*
- **Happy Path:** `[Idle] + [User action] -> [Success state]`
- **AC-1 (Missing Data / Safe State):** <e.g. Missing/unknown backend fields map safely to neutral UI>
- **AC-2 (Failure & Timeout):** <e.g. Network error displays retry snackbar, keeps current input>
- **AC-3 (Stored Invariant):** <e.g. Save action → leave screen → reopen app → observe data persisted>

### Key Technical Risks & Mitigations
- **Risk-01:** <e.g. DB migration rollback, third-party API rate limits, backward compatibility> → Mitigation: <strategy>

---

## 4 · Slices & Step Execution Ladder
> **One step = One MR ≤ 300 changed lines**, ~3–5 files (excl. resources).
> **Step Order:** (1) No-UI logic → (2) Walking skeleton (unreachable) → (3) Happy path → (4) Errors & edge cases → (5) Polish.
> **Status Lifecycle:** `NOT PLANNED` → `TODO` → `IN PROGRESS` → `REVIEWING` (MR open) → `DONE` (merged)

### Slices Overview
| Slice ID | Name / Ticket | Owner | Delivers | Consumes / Mocks | Status |
|---|---|---|---|---|---|
| slice-01 | <PROJ-101> | <Dev> | <Capability> | <Contract types / Mock> | TODO |

---

### slice-01: <Name> (`PROJ-101`)

#### step-01: No-UI Logic
- **Status:** TODO
- **MR:** — | **Commit:** —
- **Scope:** Validation, domain use cases, formatters, mappers (unknown → safe state).
- **Tasks:**
  - [ ] Add domain entity & mapper
  - [ ] Unit test mapper with edge cases & unknown types
- **Acceptance:**
  - [ ] Given unexpected backend payload, mapper returns safe fallback without crash.

#### step-02: Walking Skeleton
- **Status:** TODO
- **MR:** — | **Commit:** —
- **Scope:** MVI ViewModel (`handleIntent`), UiState, Screen UI on mock data. Merged unreachable behind feature flag/router.
- **Tasks:**
  - [ ] Define `UiState`, `Intent`, `Event`
  - [ ] Implement `handleIntent` on fake repository
  - [ ] Connect Fragment/Composable to ViewModel
- **Acceptance:**
  - [ ] Screen renders mock data; intents update state; hidden behind flag in production.

#### step-03: Happy Path Integration
- **Status:** TODO
- **MR:** — | **Commit:** —
- **Scope:** Real API / DB integration for success scenario only.
- **Tasks:**
  - [ ] Connect remote data source & repository implementation
- **Acceptance:**
  - [ ] Successful server response renders real data on device.

#### step-04: Errors & Edge Cases
- **Status:** TODO
- **MR:** — | **Commit:** —
- **Scope:** Timeouts, 4xx, 5xx, retry mechanisms, empty states.
- **Tasks:**
  - [ ] Handle error states in ViewModel & UI
- **Acceptance:**
  - [ ] Simulating network failure displays retry banner; retry recovers gracefully.

#### step-05: Polish & Telemetry
- **Status:** TODO
- **MR:** — | **Commit:** —
- **Scope:** Loading skeleton, analytics events, UI polish.
- **Tasks:**
  - [ ] Track screen view and click events
- **Acceptance:**
  - [ ] Analytics events verified on device/logcat.

---

## 5 · Follow-ups & Phase 2 (Deferred Scope)
> Discovered technical debt, non-critical edge cases, or follow-up tickets found during implementation.

| Follow-up ID | Description | Originating Step | Target Ticket / Milestone |
|---|---|---|---|
| Followup-01 | <Deferred item> | step-03 | Phase 2 / PROJ-202 |
