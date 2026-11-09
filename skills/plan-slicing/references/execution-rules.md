# Execution Rules — Steps, Tests, Status, Evidence

How a slice turns into merged code, and how progress is proven. Each rule
carries its reason; drop the reason and it becomes ritual.

## Granularity

- 3–7 slices per epic, 3–5 steps per slice. More steps than that usually means
  the slice is really two — split it rather than stretching the list.

## What a step is

- **One step = one MR.** Estimate in days (0.5–4), but *size* in diff:
  - Target **150–250 changed lines**; **hard limit 300** — over it, split.
  - **~3–5 files (soft target)** — Clean Architecture layers may touch 6–7 small
    files; never cram multiple classes into one file just to lower the file count.
  - Resource files are ignored in both counts (Android `res/`; iOS asset
    catalogs and `.strings`).
- Each step has its own **Tasks** and **Acceptance** written as observable
  behaviour a reviewer or tester can check.
- **Acceptance about stored data is checked after reopening** — act, leave the
  screen (or restart the app), come back, observe. A screen that closes cleanly
  says nothing about what it wrote.
- **Shared data gets one line per entry point.** When two screens reach the same
  write with different inputs (the whole list vs only the new items), each
  entry is its own line — that is where one caller's assumption breaks another.
- **A screen that holds input or picked state gets three lifecycle lines**, each
  checked on a device: process death (Home → `adb shell am kill <package>` →
  reopen from recents), configuration change (rotate, split screen / pop-up),
  and offline (at open and at the action). A line that cannot apply is written
  `n/a — <reason>`, never dropped. The edge-case checklist names these probes;
  this is what makes them tested instead of noted.

## Order of steps inside a slice

1. **No UI first** — validation, clocks, formatters. Things that fail silently
   get tested before a screen exists to hide them; a skeleton on static data
   proves nothing a reviewer can't see by eye.
2. **Walking skeleton** — UI on mock data, wired to the real logic from step 1,
   events fire. **Merged unreachable** behind the router/flag that hides the new
   screen (created here if missing) — mock data never reaches a user.
3. **Happy path** — the real API/DB for the success case only.
4. **Errors and edge cases** — timeout, 4xx, 5xx, carried from API up to UI.
5. **Polish** — loading skeletons, analytics, local cache, haptics.

**Every intermediate step must be shippable as merged.** Steps 2–3 fall back to
the *safe* state, never the optimistic one: a happy-path-only MR that merges
alone must not show success it cannot prove.

## Discipline while building

- **Scope isolation** — code only the current step; pre-built logic for the
  next step lands untested under the wrong MR.
- **Reuse before you add** — existing base components and utils first; no new
  helper/view class that duplicates one.
- **Ambiguity → stop.** Unspecified logic becomes a new `question-<NN>` in
  `PLAN.md §2 (Questions)`; the plan gives it an assumption in force; the step
  continues on that assumption. Never guess silently.
- **A screen being replaced is read-only.** Only the cutover MR touches it, and
  that MR deletes it — refactoring it pays twice for code about to vanish.
- **Branches are purely additive** — no shared config (`.editorconfig`, build
  files, lint baselines). Restructure your own code instead.
- **Prefix shared resource files per developer**, append at the end of your own
  block, never reflow — two devs in one big strings file conflict daily.
- **Run it on a device before calling a step done.** Insets, backgrounds and
  wrapping labels are invisible to green unit tests.
- **A wrong value on screen is fixed where the value is made, not where QA saw
  it.** Before writing the fix, grep every reader of that field (formatter,
  mapper, card, detail, form, email) and list them in the MR description; fix
  each one or route it to `TICKETS.md`. Fixing one reader of a shared value is
  how a resolved bug returns from the next entry point.
- **One bug, one MR.** Put tickets in one MR only when they share a root cause or
  the same lines, and the 300-line limit still applies. A bundle of unrelated
  fixes is reviewed as a whole and its regressions are traced to nobody.
- **Never invent a constant** (threshold, latency, cap) without a real source.
- **Check the budget before handing over:**
  `git diff --stat <target> -- . ':!*/res/*'` (Android) — add
  `':!*.xcassets/*' ':!*.strings'` on iOS.
- If the plans folder is gitignored, **code comments must not cite it** — state
  the reason itself.

## Tests per step

- **At most one test file per step**, at the highest layer of the slice
  (ViewModel / use case, or the screen) so it verifies Acceptance directly.
- **Do not test**: DTOs, data models, entities, enums; repository wrappers that
  only pass through to API/DB; plain field-copy mappers.
- **Do test** a mapper that encodes a rule — unknown → safe state, enum
  fallbacks, derived states. That mapper is where a slice's behaviour switches on.
- Inline mock data over ~15 lines goes into a shared fixture.

## Step status

```
TODO → IN PROGRESS → REVIEWING (MR open) → DONE (merged)
                         │
                  external blocker
                         ▼
                      BLOCKED  →  dependent steps: ON HOLD
```

- **Before `REVIEWING`, route every "Not this step's" line** to a `TICKETS.md` row
  or a named step in the owning slice. A note left in a finished step file is
  never read again.
- **Code done + tests green + MR open** → slice file: tick the step's Acceptance, its header
  `REVIEWING`; dashboard: `REVIEWING` + MR link. **Do not tick the dashboard.**
- **Merged** → dashboard: tick, `DONE`, commit hash.
- **Blocked** (no API, no design) → dashboard: `BLOCKED` + reason + who
  unblocks; question into `PLAN.md §2 (Questions)`; dependent steps `ON HOLD`.

## Evidence

- **Every ✅ names its commit**, verified with `git merge-base --is-ancestor`,
  never from memory.
- **Built ≠ merged** — `REVIEWING` vs `DONE`; the gap is routinely days of work.
- **Abandoned work is VOID with a reason**, never ticked.
- **Say which estimates were agreed and which were derived.**
- Re-derive the percentage from the plan's own numbers and state the
  denominator — scope found mid-epic moves it *down*.
- **Progress reports start from `PLAN.md §4` but verify its ✅s against
  the tree.** The costliest mistakes are records that disagree with reality.

## Maintaining the plans & Mid-Flight Change Management (Focus-First)

- **Never interrupt an `IN PROGRESS` step for non-colliding changes (Speed 1 — Park & Defer):**
  When PRD, Figma, or BE specs change while a developer is coding `<current-step>`, perform a ≤30s collision check. If the change does not invalidate the code currently being typed in `<current-step>`, log a 1-line row in `PLAN.md §2 Pending Spec / Design / BE Deltas` (`Status: Queued for next /clear`) and let the developer finish and merge `<current-step>` without context switching.
- **Process deltas only at `/clear` session boundaries (Speed 2 — `Plan → Execute → Regression`):**
  Run `/plan-slicing delta <EPIC>` in a fresh session to invoke `guard-blast` Mode 1:
  - **Level 1 (Trivial / Unbuilt):** Update `TODO` / `NOT PLANNED` step ACs in-place in `PLAN.md §4`.
  - **Level 2 (Moderate / Isolated `DONE` Step):** Keep `DONE` steps immutable; mark superseded AC lines with `[Superseded by delta-NN]` and append a new delta step (`step-06: Adapt to <delta-NN>`, ≤ 300 lines) with a strict **Direct Impact Allowlist**.
  - **Level 3 (Complex / Breaking Contract):** Bump `CONTRACT.md` version + Amendment Log + `FakeRepository`, mark obsolete unmerged steps `VOID`, and schedule delta steps (or push new scope to `PLAN.md §5 Follow-ups & Phase 2`).
- **Never rewrite a finished plan.** A contradicting ruling or spec delta gets a `[Superseded by delta-NN]` tag and a pointer; the original reasoning and verified commit hash stay as the record.
- **New scope gets a new plan folder (or `PLAN.md §5`)**, not an edit to a closed slice.
- **Deferred work has one home:** the `PLAN.md §5 Follow-ups & Phase 2` section.
- **When an answer or delta arrives, reconcile dependent records** in `PLAN.md §2`, `CONTRACT.md`, and the 3-Tier Regression Matrix (Tier 1 updated AC, Tier 2 downstream contract consumers, Tier 3 prior `DONE` invariants).
- **Split rule (Emergency only):** Only split `PLAN.md` if it exceeds 600 lines, keeping `PLAN.md` as the index and extracting `slices/<TICKET>.md`. Otherwise keep everything in `PLAN.md`.

## Plan folder layout (Lean 2-File Architecture)

```
plans/<EPIC>/
  PLAN.md        ← Single source of truth: Sources, Questions, Stories, Slices & Steps, Phase 2
  CONTRACT.md    ← Shared Kotlin/Swift types, interfaces, MVI state/intent (if shared across slices)
```

**Anti-Overmanagement:** Eliminate `TASK-BREAKDOWN.md`, `PRD-TRACE.md`, `REGRESSION.md`, `TICKETS.md`, `use-cases.md`, and individual slice files. All steps, acceptance criteria, and progress live directly inside `PLAN.md`.
when there is Figma; `TICKETS.md` on the first follow-up. Planning slices nobody is
working on wastes tokens and goes stale before anyone builds them. Prefer a gitignored folder (`plans/`)
over a new root folder that git would track.
