# Feature & Execution Plan — <EPIC / FEATURE NAME>

> **Status:** 🟡 DRAFT | 🟢 READY TO BUILD | 🚀 IN PROGRESS | ✅ DONE
> **Lead / Owner:** <Name>
> **Architecture:** Android MVI (`handleIntent`) + Clean Architecture
> **Files:** Lean 2-File Mode (`PLAN.md` + optional `CONTRACT.md` & `FIGMA-CACHE.md`)

---

## 1 · Triad Sources & Scope
- **PRD:** <link, pinned version + commit>
- **Figma:** <link / file key> *(raw node trees, tokens & copy cached in `FIGMA-CACHE.md` when large)*
- **API Docs:** <path / endpoint specs>
- **Replaced Screen (if any):** <screen being replaced, or None>
- **Phase 1 Goal:** <1–2 sentences on what this milestone ships>

### Screen Map (Delta Routing)
| Screen | Figma Node ID | Owning Slice | Known Traps / Stale Frames |
|---|---|---|---|
| <Screen Name> | `<node_id>` | `slice-01` | <e.g. Node `1:23` is outdated; use `FIGMA-CACHE.md#screen-a`> |

---

## 2 · Open Questions & Assumptions (Anomaly Triangle)
> **Chat-Only Slack Snippets:** Emit persona-aware Slack snippets in chat when running `/plan-feature` (or on demand); never bloat `PLAN.md` with copy-paste messages.
> When asking PM/Design: visual & UX terms only. When asking BE: data flow & field responsibilities.

### Open Questions
| Question ID | Conflict / Gap (PRD vs Figma vs API) | Technical Risk | Assumption in Force (Defensive Strategy) | Owner | Impact |
|---|---|---|---|---|---|
| question-01 | PRD (§2.1) vs Figma (`1:23`): <exact discrepancy> | <What breaks if wrong> | <Safe fallback / mock fixture> | PM / BE / Design | `slice-01` / `step-02` |

<details>
<summary>Resolved Questions (0)</summary>

| Question ID | Final Ruling | Superseded Assumption | Impact |
|---|---|---|---|
| — | — | — | — |

</details>

---

## 3 · User Stories & Acceptance Criteria
> Focus 100% on the **Anomaly Triangle**: missing data fallbacks, failures/timeouts, stored invariants (`act → leave → reopen → observe`).
> Zero Happy Path prose: standard flow is 1 formula `[State] + [Event] -> [Target State]`.

| Story ID | Capability & Happy Path | Key Anomalies (AC-1..AC-n) | Slice |
|---|---|---|---|
| Story 01 | **<Actor>:** <capability> — `[Idle] + [Action] -> [Success]` | **AC-1 (Safe State):** Unknown/missing fields map to neutral UI; **AC-2 (Failure):** Timeout/5xx shows retry snackbar & keeps input; **AC-3 (Invariant):** Save → leave → reopen → data persisted | `slice-01` |

### Key Technical Risks & Mitigations
- **Risk-01:** <e.g. DB migration rollback, API rate limit, backward compatibility> → Mitigation: <strategy>

---

## 4 · Slices & Step Execution Ladder
> **One step = One MR ≤ 300 changed lines**, ~3–5 files (excl. resources).
> **Step Order:** (1) No-UI logic → (2) Walking skeleton (unreachable) → (3) Happy path → (4) Errors & edge cases → (5) Polish.
> **Status Lifecycle:** `NOT PLANNED` → `TODO` → `IN PROGRESS` → `REVIEWING` (MR open) → `DONE` (merged)
> **Compaction Rule:** Keep active step `Files` / `Decisions` / `Tasks` inside `<details>`. When a step is `DONE`, drop checked-off boilerplate tasks and compact into 1–3 lines of permanent **Technical Decisions** (anti-hallucination anchor for subsequent steps & deltas).

### Slices Overview
| Slice ID | Name / Ticket | Owner | Delivers | Consumes / Mocks | Status |
|---|---|---|---|---|---|
| slice-01 | <PROJ-101> | <Dev> | <Capability> | <Contract types / Mock> | TODO |

---

### slice-01: <Name> (`PROJ-101`)
| Step | Scope | Key Acceptance (Observable) | Status | MR / Commit |
|---|---|---|---|---|
| step-01 | No-UI logic: validation, use cases, mappers (unknown → safe state) | Unexpected backend payload maps to safe fallback without crash | DONE | `!101` `a1b2c3d` |
| step-02 | Walking skeleton: MVI ViewModel (`handleIntent`), UiState, Screen UI on mock | Screen renders mock data; intents update state; gated behind flag | IN PROGRESS | — |
| step-03 | Happy path integration: real API / DB for success scenario only | Successful server response renders real data on device | TODO | — |
| step-04 | Errors & edge cases: timeouts, 4xx/5xx, retry, empty states | Simulated network failure shows retry banner; retry recovers | TODO | — |
| step-05 | Polish & telemetry: loading skeleton, analytics, UI polish | Analytics events verified on device/logcat | TODO | — |

<details>
<summary>📌 Technical Decisions & Active Step Plan (slice-01)</summary>

- **step-01 (DONE — Decisions):** `domain/<pkg>/<Validator>.kt` (pure Kotlin); `data/mapper/<Mapper>.kt` maps unknown/null → `SafeType.UNKNOWN`; unit tests in `<Mapper>Test.kt`.
- **step-02 (IN PROGRESS):**
  - **Files:** `ui/<pkg>/<Feature>ViewModel.kt`, `ui/<pkg>/<Feature>Screen.kt`, `di/<Feature>FakeModule.kt`, `<Router>.kt`
  - **Decisions:** Gate route behind `ff_<feature>_v2`; reuse existing `<SharedBanner>`; `Fake<Feature>Repository` returns 2 static items.
  - **Tasks:**
    - [x] Define `UiState`, `Intent`, `Event` per `CONTRACT.md`
    - [ ] Implement `handleIntent` on `Fake<Feature>Repository`
    - [ ] Connect Composable/Fragment to ViewModel behind feature flag

</details>

---

## 5 · Follow-ups & Phase 2 (Deferred Scope)
> Discovered technical debt, non-critical edge cases, or follow-up tickets found during implementation.

| Follow-up ID | Description | Originating Step | Target Ticket / Milestone |
|---|---|---|---|
| Followup-01 | <Deferred item> | step-03 | Phase 2 / PROJ-202 |
