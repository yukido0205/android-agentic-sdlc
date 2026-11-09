---  
name: guard-blast  
description: Analyzes PRD/design/BE delta or bug fix blast radius with Focus-First 2-Speed Triage, establishes strict allowlists, and derives high-signal regression test matrices to prevent regressions and context drift.  
version: 2.1.0  
tags: [guard-blast, blast-radius, regression-testing, bug-fixing, scope-control, change-management]
---  
  
# Guard Blast & Regression Guard

Acts as a defensive guardrail against AI hallucination, human context-switching fatigue, unwarranted refactoring, and regression bugs. Operates in two distinct modes:
- **Mode 1: Spec, Design & BE Delta (Focus-First Change Management)** — for mid-flight PRD, Figma, or Backend API requirement changes during feature slicing.
- **Mode 2: Bug Fix Blast Radius & Regression Guard** — for `flow-bug` post-diagnosis to isolate impact and guarantee system stability.

---

## Mode 1: Spec, Design & BE Delta (Mid-flight Requirements Change)

Used when product requirements (PRD), Figma designs, or Backend API specs change during `/plan-slicing` execution. To prevent human context-switching fatigue, Mode 1 enforces a **2-Speed Focus-First Protocol** (*Speed 1: Mid-Step Quick Triage* vs *Speed 2: Session-Boundary Assessment*).

### Speed 1: Mid-Step Quick Triage (≤ 30s — When a Step is `IN PROGRESS`)
When a requirement/design/BE change arrives while the developer is actively coding `<current-step>` (`Status: IN PROGRESS`), **DO NOT** run a full-epic impact analysis or force a context switch. Answer one question only:
> *"Does this change directly invalidate the exact lines of code being written in `<current-step>` right now?"*

- **🟢 NO (Does NOT block `<current-step>` — 85% of cases):**
  - **Park & Defer (Zero Context Switch):** Log a 1-line row under `PLAN.md §2 Pending Spec / Design / BE Deltas` (`Status: Queued for next /clear`).
  - Instruct the developer: *"Safe to ignore right now. Finish and merge `<current-step>` first, then run `/clear` and `/plan-slicing delta <EPIC>`."*
- **🟡 YES — Trivial Local Tweak (Fits inside `<current-step>` within ≤ 300-line diff budget):**
  - Absorb in-place into `<current-step>`'s AC and continue coding without switching sessions.
- **🔴 YES — Breaking Collision (Invalidates `<current-step>`'s core premise or exceeds 300-line budget):**
  - **Safe Abort:** Stop coding `<current-step>`. Instruct the developer to `git stash` (or discard draft branch), mark `<current-step>` as `BLOCKED` (or revert to `TODO`), run `/clear`, and invoke Speed 2 in a fresh session.

### Speed 2: Session-Boundary Assessment (`Plan → Execute → Regression` at `/clear`)
Run **only** in a fresh session between steps (or via `/plan-slicing delta <EPIC>`) when cognitive load is zero:

1. **Delta Isolation (Diffing):**
   Compare previous vs new specifications across PRD, Figma, and BE API:
   | Delta ID | Change Item | Previous Spec | New Spec | Layer (`UI` / `Logic` / `Data` / `Contract`) | Affected Slices & Steps (`NOT PLANNED` / `TODO` / `DONE`) |
   |---|---|---|---|---|---|
   | `delta-01` | ... | ... | ... | ... | ... |

2. **Complexity Assessment & Strategy Definition:**
   Classify each delta and assign a deterministic execution strategy:
   | Complexity | Trigger Criteria | Execution Strategy |
   |---|---|---|
   | **Level 1: Trivial (Low)** | Copy/color tweaks, single field addition with no state side effects, or changes hitting only `NOT PLANNED` / `TODO` steps. | **In-Place Plan Update:** Do not touch `CONTRACT.md`. Update AC lines directly in `PLAN.md §3–4` for `TODO` steps. If hitting a `DONE` step, append a micro patch step (`step-05b`, ≤ 100 lines). |
   | **Level 2: Moderate (Medium)** | Isolated ViewModel logic, state transition, or slice-private API payload changes affecting a `DONE` step within 1 slice. | **Delta Step Injection:** Never rewrite `DONE` steps. Mark superseded AC as `[Superseded by delta-NN]`. Append a new step (`step-06: Adapt to <delta-NN>`, 1 MR ≤ 300 lines) at the end of the slice with a strict **Direct Impact Allowlist**. |
   | **Level 3: Complex (High)** | Breaking shared models/interfaces in `CONTRACT.md`, DB schema migration, or multi-slice navigation overhaul. | **Contract Bump & Re-Slice:** Bump `CONTRACT.md` version + Amendment Log + `FakeRepository`. Mark obsolete unmerged steps `VOID`. Schedule dedicated ` git revert` + adaptation steps for `DONE` work, or defer new scope to `PLAN.md §5 Phase 2`. |

3. **Re-sweep Finished Work (`DONE` Steps):**
   For every delta row touching a `DONE` step, grep existing code and completed AC lines. Re-verify each against the new spec. Flag altered expectations with `[Superseded by delta-NN]`. If a delta reverses earlier merged work, require a clean revert commit in the new delta step rather than layering dead code over it.

4. **Allowlist & 3-Tier Regression Plan (Hand-off to `plan-slicing`):**
   - Lock the **Direct Impact Allowlist** (exact 3–5 files the delta step is permitted to touch).
   - Define the **3-Tier Regression Matrix** to be executed by `test-runner -m regression` during the delta step:
     - **Tier 1 (Updated AC):** New/updated Maestro or unit tests proving the changed requirement.
     - **Tier 2 (Downstream Consumers):** Other slices/screens consuming the updated `CONTRACT.md` or shared state.
     - **Tier 3 (Prior `DONE` Invariants):** Existing tests from `step-01..step-0N` of the slice to prove zero regression on previously merged steps.
   - Present the **Gate 1 Delta Briefing** (Delta table + Complexity + Strategy + Allowlist) for human approval before modifying `PLAN.md` or `CONTRACT.md`.

---

## Mode 2: Bug Fix Blast Radius & Regression Guard (For `flow-bug`)

Used immediately after `test-hunter` produces the `DIAGNOSIS` and proposed solution, before any code is modified. Prevents the #1 cause of secondary defects: **fixing point A and breaking point B**.

### 1. Fix Delta & Change Classification
Classify the proposed fix by its mechanism:
- **Contract / Signature:** Modifying interface, method arguments, or DTO serialization.
- **State & Lifecycle:** Modifying SharedFlow, StateFlow, cache, singleton, or database state.
- **Branch / Guard:** Adding early returns, null checks, or bypassing existing logic.
- **Data / Mapping:** Changing calculation, transformer, or enum handling.

### 2. Blast Radius Mapping (The 3 Perimeters)
Map the exact boundary of the change:

| Perimeter | Scope | Rules / Actions |
|---|---|---|
| **🟢 Direct Impact (Allowlist)** | Files, classes, and methods directly modified by the fix. | Becomes the **strict Allowlist**. Any file modified outside this list in Phase 2 fails the scope check. |
| **🟡 Downstream Impact (Consumers)** | Screens, ViewModels, Use Cases, Observers, or DB queries that read or depend on the modified component. | Must be analyzed for unintended side effects. Each downstream consumer becomes a candidate for the **Regression Matrix**. |
| **🔴 Explicit Non-Impact (Perimeter)** | Adjacent features, shared base classes, or theme values verified to remain untouched. | Agent is **strictly prohibited** from refactoring, reformatting, or cleaning up these files. |

### 3. High-Signal Regression Matrix
Derive concrete test scenarios from the blast radius, categorized into 3 tiers:

```markdown
### Regression Matrix for <TICKET>
| Tier | Scenario / Flow | Component / Screen | Test Type | Invariant / Expected Behavior |
|---|---|---|---|---|
| **Tier 1: Repro** | AC-01: Ticket defect steps | Buggy screen | E2E (Maestro) | Verifies bug is resolved (fails before, passes after). |
| **Tier 2: Downstream** | AC-02: Primary downstream consumer | Adjacent screen / flow | E2E or ViewModel Test | Verifies dependent feature continues working normally. |
| **Tier 2: Downstream** | AC-03: Shared state / cache sync | Shared component | Unit / State Test | Verifies state remains valid across multiple consumers. |
| **Tier 3: Invariant** | AC-04: Lifecycle / Process Death | Affected feature | E2E / Negative Control | Verifies state restoration after recreation or back navigation. |
```

### 4. Output: `plans/<TICKET>/regression-plan.md`
Generate the artifact containing:
1. **Summary of Fix Delta & Classification**
2. **Blast Radius Table** (Direct Allowlist, Downstream Consumers, Explicit Non-Impact)
3. **Regression Matrix** (AC-01 through AC-n)
4. **Gate 1 Briefing Lines** (Concise 3–4 bullet summary for human review at Gate 1)

---

## Execution & Verification Discipline (Universal)

1. **Allowlist Discipline:** Only touch files in the Direct Impact list. `git diff --name-only` must match the allowlist.
2. **Diff Budgeting:** Keep changes focused strictly on the fix/delta. No unsolicited cleanups or reformatting.
3. **Verification Checklist:**
   - [ ] No compilation errors across dependent modules.
   - [ ] All Tier 1 (Repro) and Tier 2/3 (Downstream Regression) tests pass.
   - [ ] Negative control verified (Tier 1 fails on unfixed code).
   - [ ] No regression on untouched shared utilities or adjacent screens.
