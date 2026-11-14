---
name: plan-slicing
description: Turns an epic's stories (from /plan-feature or PLAN.md) into a versioned Technical Contract and vertical slices built in parallel on mocks — each slice a short ladder of one-MR steps (≤300 lines) tracked with commit evidence. Uses a Lean 2-File Architecture (PLAN.md + CONTRACT.md) to eliminate over-management.
version: 4.0.0
---

# Vertical Slicing + Technical Contract (Lean Mode)

Break an Epic/PRD into work that:
(a) validates each User Story independently,
(b) lets multiple devs — or parallel AI agents — build simultaneously without overwriting each other's code,
(c) lands as small, reviewable MRs whose progress is provable from git,
(d) **Eliminates Over-Management**: Replaces the 10+ file markdown sprawl with a **Lean 2-File Architecture (`PLAN.md` + `CONTRACT.md`)**.

This is the second half of one pipeline: `/plan-feature` (sources, questions, stories in `PLAN.md`) → `/plan-slicing init` → `plan` → `step`.

## Cognitive Load Reduction Rules (Anti-Overmanagement & Anti-Fatigue)

1. **Lean 2-File Architecture (Strict Limit):**
   - **`PLAN.md`**: Single source of truth for scope, questions, stories, acceptance criteria, step execution ladder, and follow-ups.
   - **`CONTRACT.md`**: Shared Kotlin/Swift types, interfaces, navigation keys, and MVI state/intent/event.
   - **Eliminated Files:** Do NOT create separate `TASK-BREAKDOWN.md`, `PRD-TRACE.md`, `REGRESSION.md`, `TICKETS.md`, `use-cases.md`, or individual `slices/*.md` files (keep steps inline in `PLAN.md §4` unless `PLAN.md` exceeds 600 lines).
2. **Executive Summary First:** Mode responses begin with a 3-line check:
   - `[Red Flags]`: Breaking Contract/PRD conflicts? (Yes/No + 1 sentence).
   - `[Missing Data]`: Any unmapped fields or unrouted PRD hits?
   - `[Readiness]`: Ready for implementation/merge? (Yes/No).
3. **Zero Happy Path:** Do not write verbose narrative for standard 200 OK operations. Steps and acceptance focus on the **Anomaly Triangle**: edge cases, timeouts, missing data fallbacks, and stored data verification (`act → leave → reopen → observe`).
4. **Ultra-Compact Output:** Max 1 screen scroll (< 300 words). Use markdown tables, checkboxes, and state transitions `[State] + [Event] -> [New State]`. No polite filler.
5. **Language Consistency:** Always generate all artifacts and responses in the language of the repository and PRD (default: English). Never mix languages or switch to another language unless explicitly requested by the user.
6. **Parallel Agent Isolation (Worktree + Mutex Device Lock):** For parallel agents executing on one Mac, initialize each ticket's workspace via `./scripts/init-worktree.sh <TICKET>` (0 tokens, <0.2s). Automatically symlinks `local.properties`, `google-services.json`, `keystore.properties`, `.agents/`, `.claude/`, and sets `org.gradle.workers.max=2`. Build with `./gradlew assembleDebug` and verify with `suite-runner.py --install`.

## When to use

- Breaking down an Epic/PRD with 2+ User Stories that share data or state.
- Stories have a dependency chain (Story B needs Story A's output).
- Planning parallel work — multiple devs, or parallel agents.
- Executing or reporting on a step of an epic already sliced this way.
- User says: "break down this epic", "slice tasks", "split PRD for parallel work", "how do I parallelize this", "vertical slicing", "epic progress".

Do NOT use for a single isolated story, a pure bugfix, or work with no shared state between tasks — a flat task list in `/plan-feature` is fine there.

## Inputs to gather first

1. `plans/<EPIC>/PLAN.md` from `/plan-feature`. Missing → run `/plan-feature` first; do not re-derive requirements here.
2. Platform + architecture so the Contract uses the right types. Default to the repo's existing pattern (Android MVI `handleIntent` + Clean).
3. Artifacts destination: `plans/<EPIC>/PLAN.md` and `plans/<EPIC>/CONTRACT.md`.

## Modes — 3-Tier Just-In-Time (JIT) Planning & Strict Session Boundaries

**Why JIT Progressive Slicing?** Asking an AI agent to scan the entire codebase and plan micro-details for 4–5 slices (20+ steps) in a single session causes attention dilution and severe hallucination. Instead, planning is deferred across **3 isolated session tiers** (`init` → `plan <SLICE>` → `step <SLICE> <STEP>`).
Files are kept strictly within `PLAN.md` and `CONTRACT.md`.

| Mode | Session Owner | Trigger | Writes | Does NOT write / Hard Boundary |
|---|---|---|---|---|
| `init <EPIC>` | Tech Lead (Session 1) | `/plan-slicing init <EPIC>` | `CONTRACT.md` + appends high-level `§4 Slices Overview` table (`Status: NOT PLANNED`) to `PLAN.md` | Individual step breakdowns for slices. **Ends with `/clear`.** |
| `plan <slice-id>` | Slice Owner (Session 2) | `/plan-slicing plan <slice-id>` | High-level step ladder (`step-01..step-05`: Goal + AC only) for **that 1 slice** under `PLAN.md §4` | Premature file-level tasks or other slices' steps. **Ends with `/clear`.** |
| `step <slice-id> <step-id>` | Step Dev (Fresh Session per Step) | `/plan-slicing step <slice-id> <step-id>` | Scans code for `<step-id>` only → writes JIT micro-tasks → codes `<step-id>` → updates `PLAN.md §4` | Code or detailed plans for the next step. **Ends with `/clear`.** |
| `update` | Any | "step-02 in review / merged / blocked", "question-04 answered" | Updates affected rows in `PLAN.md` | — |
| `progress` | Any | `/plan-slicing progress <EPIC>` | Nothing — reads `PLAN.md §4` and verifies against git | — |

---

### Step 0 — Check requirements readiness (`init`)

Check `plans/<EPIC>/PLAN.md`. Confirm gates passed: every `question-<NN>` in `§2` has an assumption in force, Phase 1 scope is clear, and P0 risks are mitigated. If missing, ask the user or run `/plan-feature`.

### Step 1 — Version the Technical Contract (`init`)

Extract the SMALLEST shared surface every story touches: domain models, Repository/UseCase signatures, UI state/events, navigation keys. Encode rules in types (sealed/enum fields). Android UI state follows MVI `handleIntent` (repo workflow §1a).
Write `plans/<EPIC>/CONTRACT.md` from `assets/CONTRACT.template.md`. Kotlin patterns → `references/mobile-contracts.md`.

### Step 2a — List the slices (`init`)

Slices come from Phase 1 stories in `PLAN.md §3`. Each story (or tight group) becomes one vertical slice (UI → logic → mocked data). 3–7 slices per epic.
Append ONLY the **Slices Overview table** to `PLAN.md §4` with Slice ID (`slice-01`, `slice-02`, ...), ticket, owner, delivers, consumes, mocks, status `NOT PLANNED`.
> 🛑 **Session Boundary (`init` complete):** Stop here. Do NOT plan the steps of individual slices in this session. Instruct the user:
> *"Contract and Slices Overview are ready. Start a **fresh session (`/clear`)** when picking up a slice and run `/plan-slicing plan <slice-id>`."*

### Step 2b — Cut ONE slice into a step outline (`plan <slice-id>`)

Run in a **fresh session** for **one requested slice only** (never all slices at once):
- Read `CONTRACT.md` and grep the PRD strictly for rules/edge cases touching `<slice-id>`.
- Cut `<slice-id>` into 3–5 lightweight steps directly under `PLAN.md §4` (**one step = one MR**, ≤ 300 lines):
  1. **No-UI logic (`step-01`)** — validation, formatters, domain mappers (unknown backend data → safe state).
  2. **Walking skeleton (`step-02`)** — UI on mock data, wired to MVI ViewModel, merged **unreachable** behind a flag/router.
  3. **Happy path (`step-03`)** — real API/DB integration for the success case.
  4. **Errors & edge cases (`step-04`)** — timeout, 4xx, 5xx, offline, retry.
  5. **Polish (`step-05`)** — loading skeletons, analytics, haptics.
- **Anti-Hallucination Rule:** Write only each step's **Scope goal** and observable **Acceptance Criteria (AC)**. Leave file-level micro-tasks to be discovered just-in-time when the developer starts that specific step's session.
> 🛑 **Session Boundary (`plan` complete):** Stop here. Instruct the developer:
> *"Step ladder for `<slice-id>` is saved in `PLAN.md §4`. Open a **fresh session (`/clear`)** for each step and run `/plan-slicing step <slice-id> step-01`."*

### Step 3 — Plan detail & build ONE step per fresh session (`step <slice-id> <step-id>`)

Run in a **dedicated fresh session** for a single step (`<step-id>`):
1. **Phase A — Just-In-Time (JIT) Step Micro-Plan:**
   - Read `CONTRACT.md` and `<step-id>`'s Scope/AC in `PLAN.md §4`.
   - Scan the actual codebase *only* for the files relevant to `<step-id>`.
   - Formulate the exact micro-tasks (which 3–5 files to create/modify) and update `<step-id>`'s `Tasks` checklist in `PLAN.md §4`.
2. **Phase B — Scoped Implementation:**
   - Scope isolation: code **only** current step `<step-id>`. Reuse existing widgets/utils first.
   - **Code Hygiene Guardrails (`rules/code-hygiene.md`):**
     - *Pre-Code (Lean SOLID):* Do not introduce any new interface, wrapper, or abstraction layer not already frozen in `CONTRACT.md` unless it has 2+ implementations.
     - *During-Code (Why-Only Docs):* Document only non-obvious intent, invariants, and workarounds.
     - *Post-Code (YAGNI Simplify):* Once the step compiles, flatten deep nesting with guard clauses and strip debug logs/speculative flags before running tests.
   - At most one test file at the highest layer of the slice (`handleIntent` -> state/events).
   - Fallback discipline: missing backend field maps to the **safe state** (`UNKNOWN`), never optimistic.
   - Ambiguity mid-step: stop, add a `question-<NN>` to `PLAN.md §2`, do not guess.
   - Deferred work / discovered debt goes directly into `PLAN.md §5 Follow-ups & Phase 2`.
3. **Phase C — Verify, Ship & `/clear`:**
   - Run device/unit verification (`test-runner`) for `<step-id>`'s Acceptance lines, then run `ship-mr` Steps 1–3 to audit the ≤300-line diff budget and generate the commit/MR description.
   - Update `<step-id>` status in `PLAN.md §4`.
   - 🛑 **Session Boundary (`step` complete):** Instruct the developer:
     > *"Step `<step-id>` is complete and persisted in `PLAN.md`. Run `/clear` (open a fresh session) before starting the next step."*

### Step 4 — Integrate and track (`update`, `progress`)

- When real dependency lands: swap mock → real at the single DI point.
- Status lifecycle: `TODO` → `IN PROGRESS` → `REVIEWING` (MR open) → `DONE` (merged).
- Tick step in `PLAN.md §4` only on merge, with commit hash verified from git tree.

---

## Iron Rules

1. **Lean 2-File Architecture:** All plans, stories, questions, steps, and follow-ups stay in `PLAN.md`. Types live in `CONTRACT.md`. Never generate 10+ md files.
2. **The Contract is versioned; enforce its freeze or call it a draft.**
3. **Mocks conform to the Contract, never to a slice's internals.**
4. **Unknowns carry an assumption in force.** No silent assumptions.
5. **Placeholders never lie.** Unknown backend values map to the safe state, never the optimistic one.
6. **One step, one MR, ≤ 300 lines.** Over budget → split the step.
7. **Verify, don't recall.** A `DONE` step names a verified commit hash.
8. **Zero Happy Path & Cognitive Load Reduction.** Executive Summary first, concise tables, no filler prose.

## References

- `USAGE.md` — Example prompts for each mode in Lean Mode.
- `assets/PLAN.template.md` — Unified feature & execution plan template.
- `assets/CONTRACT.template.md` — Shared technical contract template.
- `references/mobile-contracts.md` — Kotlin MVI patterns, fake repositories, mock→real swap.
- `references/execution-rules.md` — Step size, order, testing, and evidence rules.
