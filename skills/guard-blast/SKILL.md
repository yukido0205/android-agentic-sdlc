---  
name: guard-blast  
description: Analyzes PRD/design delta or bug fix blast radius, establishes strict allowlists, and derives high-signal regression test matrices to prevent regressions and context drift.  
version: 2.0.0  
tags: [guard-blast, blast-radius, regression-testing, bug-fixing, scope-control]
---  
  
# Guard Blast & Regression Guard

Acts as a defensive guardrail against AI hallucination, unwarranted refactoring, and regression bugs. Operates in two distinct modes:
- **Mode 1: Spec / Design Delta** — for mid-flight PRD or Figma requirement changes.
- **Mode 2: Bug Fix Blast Radius & Regression Guard** — for `flow-bug` post-diagnosis to isolate impact and guarantee system stability.

---

## Mode 1: Spec & Design Delta (Mid-flight Requirements Change)

Used when product requirements (PRD) or Figma designs change during feature development.

### Phase 1: Delta Isolation & Strategy
1. **Delta Isolation (Diffing):**
   Compare previous vs new specifications:
   | Change Item | Previous Spec | New Spec | Type (UI / Logic / Data / Contract) |
   |---|---|---|---|
   | ... | ... | ... | ... |

2. **Complexity Assessment:**
   - **Trivial (Low):** Text/color tweaks, single field addition without state side effects.
   - **Moderate (Medium):** State transition updates, modified ViewModel logic within an isolated screen.
   - **Complex (High):** Breaking contract changes, database schema migration, multi-screen navigation overhaul (requires vertical slicing).

3. **Re-sweep Finished Work:**
   For every delta row, grep existing code and completed AC lines. Re-verify each against the new spec. Any expectation that changed is rewritten and flagged `[flow ✎]`. If a delta reverses earlier work, revert the earlier commit rather than layering over.

4. **Allowlist & Execution Plan:**
   Produce target file list (allowlist), ordered implementation steps, and explicit constraints.

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
