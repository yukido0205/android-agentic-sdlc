---
name: flow-bug
description: One-command bug workflow for a single Jira bug — Understand → Fix → Prove → Ship (→ Feedback), with the user speaking only at 3 gates. Checks fire on the shape of the fix, and every run ends with a retro that feeds gotcha candidates back into the skills. Chains existing skills (test-hunter, guard-blast, test-author, test-runner, ship-mr) under the always-on code-hygiene rule and loops review → fix → device check on its own. Resumable from plans/<TICKET>/flow-bug.md.
when_to_use: Invoke explicitly with /flow-bug <TICKET> (or "/flow-bug resume <TICKET>"). Personal skill, not the team's /bug-fixing. Do NOT auto-trigger.
disable-model-invocation: true
---

# Flow bug — Understand → Fix → Prove → Ship (→ Feedback)

This skill owns only the **order**, the **gates** and the **state file**. Every step borrows an existing
skill or agent; read that skill when you reach it and do not restate it here.

The user speaks at **3 gates**. Everything between gates runs without asking, except where a
hard rule below says to ask.

## State — `plans/<TICKET>/flow-bug.md`

Create on first run; read it first on every run. It is the resume point. Layout:

```markdown
# <TICKET> flow bug
Phase: 1|2|3|4|5   Gate passed: 0|1|2|3   Track: fast|full   Branch: <name>   Base: <branch>
## Root cause      ← phase 1, ≤6 bullets
## Decision        ← gate 1, the user's words + any PM ruling id
## Fix-shape checks ← phase 1 step 6 (b–d): the checks that fired and their tables
## Risks           ← phase 1, top 5 only
## Regression plan ← path to regression-plan.md
## Acceptance      ← device lines, one "- " bullet each (the e2e skill reads them as AC-n):
                     first the repro line (ticket steps → expected result), then the
                     regression-plan lines
## Open questions  ← phase 1; resolved ones struck through
## Baseline        ← test classes that ran + counts, before the change
## Loop log        ← phases 3 and 5, one line per round: findings kept / dropped (why) / re-test result
```

`/flow-bug resume <TICKET>` (or `/flow-bug <TICKET>` with an existing state file) → continue at the
recorded phase. Never redo a passed gate.

## Phase 1 — Understand (no code changes)

1. Ticket: read the Jira issue (read-only). The branch name gives the ticket when none is passed.
2. Root cause: spawn the `test-hunter` agent with the ticket text and the suspected area. Keep its
   DIAGNOSIS, including `Files this fix touches`. On NEEDS-INFO, carry its questions to Gate 1 and
   re-spawn it with the answers. **At most 2 NEEDS-INFO rounds**: still unclear after round 2 →
   list what is unknown and stop. Never fix blind.
3. Reproduce on device:
   a. Write the repro line as the first bullet of **Acceptance** in `plans/<TICKET>/flow-bug.md`
      (the ticket's steps → its **expected** result).
   b. **Author flow**: invoke the `test-author` skill with `plans/<TICKET>/flow-bug.md` to inspect
      layouts and generate the deterministic Maestro flow (`.maestro/<TICKET>/.../ac-01-repro.yaml` and
      any necessary `_shared/` helpers).
   c. **Execute Repro**: run `test-runner` with `-m repro` (executes directly in-process, completes in ~15–20s):
      `python3 skills/test-runner/scripts/suite-runner.py plans/<TICKET>/flow-bug.md -m repro`
      The flow asserts the correct behaviour, so it fails today (reproduced) and will pass after the fix.
   d. Record the result under **Root cause**: reproduced / not reproduced (with the data or device
      state tried). A NEEDS-INFO question the device can answer (which value is sent, what the server
      returns) is answered here, not carried to Gate 1.
4. Pick the track and record it in the state file:
   - **Fast**: fix ≤5 lines, one file, and no change to a business flow (only a wrong value, a guard,
     or a mapping). Skip step 5. The regression plan = the repro line + one adjacent flow.
   - **Full**: anything else.
5. Blast radius + regression (Full only): invoke `guard-blast` (Mode 2: Bug Fix Blast Radius & Regression Guard) using the `test-hunter` DIAGNOSIS:
   a. Map the 3 perimeters: **Direct Impact (strict Allowlist)**, **Downstream Impact (consumers/dependent screens)**, and **Explicit Non-Impact (perimeter)**.
   b. Derive the 3-Tier Regression Matrix (Tier 1 Repro, Tier 2 Downstream/adjacent flows, Tier 3 Lifecycle/state invariants).
   c. Write `plans/<TICKET>/regression-plan.md` and append the derived regression lines to **Acceptance** in `plans/<TICKET>/flow-bug.md`.
6. Open questions. Classify the planned fix by its shape and run every check whose trigger matches
   (none match → only (a)). Record (b–d) under **Fix-shape checks**.
   a. Always: for each step in the fix path ask "what if this fails / is empty / is duplicated /
      races / is retried?"
   b. **Bypass** — the fix skips, short-circuits, reorders or replaces an existing path (early
      return, skipped screen/callback/loader/init, new fast path). Read the old path and list
      everything it does. Mark each item: still done elsewhere (where) / not needed (why) / must be
      added. Read the code; don't list it from memory.
   c. **New or changed state** — a field, static, singleton, cache, preference, DB row or flag. Name
      the state's owner, derive every event that creates, resets or outlives that owner, and fill one
      row per state. A cell nobody can fill is a Gate 1 question. Default events by owner:
      View/Fragment/Activity → fresh launch, config change, recreation (background kill), back/finish ·
      ViewModel → process death, navigation pop · process static → new launch in a live process,
      process death · persisted (prefs/DB) → logout, account switch, app update, reinstall ·
      server/session → token refresh, offline.
   d. **Timing** — the fix depends on order, threads, delays, callbacks or lifecycle timing. List the
      interleavings it must survive; each one becomes a device or unit line.
   Then list only the questions the code and PRD cannot answer. Check the PRD and the
   other platform's fix if the user mentions one.

### 🚦 Gate 1 — direction

Show: the repro result, root cause (≤6 bullets), the track and why, **Blast Radius (Allowlist + Downstream consumers)**, **Regression Matrix** (adjacent flows to be verified), the fix-shape checks that fired (with their tables), top risks, and open questions. One `AskUserQuestion` with the questions plus "approach to take" (and any extra downstream scenarios the user wants tested). The user adds context (other platform, PM ruling). Record it under **Decision**. Stop here until answered.

## Phase 2 — Fix

1. Branch: `bugfix/<TICKET>-<slug>` from the base the user names (default: the current release
   branch). If on a dirty tree, ask.
2. Baseline: Run the project's debug unit test task (e.g. `./gradlew :app:testDevDebugUnitTest` or `./gradlew testDebugUnitTest` per `build.gradle`) with `--tests '*<feature>*'` → record the test classes
   that actually ran and their counts. Zero classes, or only unrelated ones (quarantine, filter
   mismatch) → say so; don't record it as a baseline.
3. Implement the Decision following `rules/code-hygiene.md` ("Why"-only comments, verified claims).
4. **YAGNI & Simplify gate on the diff** (`rules/code-hygiene.md` §3) — remove anything nobody needs today:
   - logging no one reads, log-only interface methods, speculative params/flags/abstractions;
   - new public API that only tests call;
   - flatten deep nesting with guard clauses and strip dead code on the changed files.
5. **Scope check**: `git diff --name-only` against `guard-blast`'s Direct Impact Allowlist (from `plans/<TICKET>/regression-plan.md`). Any extra file not in the allowlist is either explicitly justified in one line in the state file or reverted. No cleanup-while-here.
6. Unit tests for the new behaviour; run the feature tests + the project linter (e.g. `:app:ktlintCheck`, `detekt`, or `spotlessCheck`). A failing test →
   fix it, never skip it. **Build or compile failure → fix once; if it fails again, stop and show the
   error.** No retry loop.
   A test may be waived only with a named cause, from a full stack trace (or a thread dump if it
   hangs), that cannot be fixed inside the test. "A similar test is quarantined" or "the class is
   hard to test" is not a cause. Show the waiver at Gate 2.

## Phase 3 — Prove (loops on its own)

Repeat until a round keeps no finding (max 3 rounds; a 4th needs the user):

1. Device:
   a. Add the regression plan's lines to **Acceptance** (once) in `plans/<TICKET>/flow-bug.md`.
   b. **Author new flows**: if regression lines add new test cases not yet in `.maestro/<TICKET>/`,
      invoke `test-author` to generate them. Existing flows are re-run, not rewritten.
   c. Install this branch, then execute the regression suite with `test-runner` in regression mode (spawns live monitoring Terminal, 0 LLM token cost):
      `python3 skills/test-runner/scripts/suite-runner.py plans/<TICKET>/flow-bug.md -m regression`
   d. AC-1 (the repro) must now pass; all regression flows must also pass.
   e. **Negative control** — each line added for this ticket that guards new behaviour (not a line
      that checks an adjacent flow is unchanged) runs once on unfixed code: the base build, or the
      fix reverted locally and restored right after (check `git diff`). It must fail at its check,
      not at its precondition. Log both runs. A unit test for new behaviour gets the same treatment.
   f. New device flows: a precondition and the check fail with different messages, and no
      precondition depends on timing. Hold the state deterministically (fixture, offline, paused
      loader) instead of racing an animation, a network call or a timer.
2. Review, in three parts:
   a. `ship-mr` Step 1–2 (review + gate, no MR text yet).
   b. **Independent** (Full track, or any fix where a fix-shape check fired) — spawn the
      `code-reviewer` agent with only the diff (`git diff <base>...HEAD`), the ticket's expected
      result and the **Fix-shape checks** tables. Don't give it the diagnosis or the Decision, so it
      isn't anchored on them. Its findings go through step 3 like any other.
   c. **Claim check** — every code comment and commit-message line that states a cause or a source
      ("X is created by Y", "Z never runs here") cites a line read in this session. Otherwise fix it
      or delete it.
3. For **each** finding answer two questions before touching code:
   - *Who needs this, and what breaks for them without it?* No concrete answer → drop it, log why.
   - *What is the risk of changing it?* High → carry to Gate 2 instead of fixing.
   A failure that doesn't reproduce but has no root cause is not dropped: carry it to Gate 2 as an
   open risk, with its evidence path.
4. Fix the kept findings, re-run phase 2 steps 5–6, append one line to **Loop log**.

Fast track: one round only, unless the review finds a 🔴.

### 🚦 Gate 2 — approvals

Ask once, together: findings carried for a decision, and any outward action still needed (real
API mutations, external side effects, uninstalling a build). Device lines that need data the account lacks
follow the e2e skill's data rule. Resume the loop with the answers.

## Phase 4 — Ship

1. Commit (conventional message, ticket in scope, attribution per session reminder). Stage only
   this fix's files; leave untracked agent configuration files out.
2. MR text: `ship-mr` Step 3, testing section from the e2e results — every box ticked or
   explicitly marked not run with the reason.
3. Update the state file: Phase 4, Gate 2 passed.
4. **Retro** — for each miss found after Gate 1 (by the device, the review, or the user), answer
   "which rule or knowledge would have caught it, and where does it belong?"
   - a process rule any bug could need → candidate for **flow-bug**;
   - tool or environment knowledge → candidate for **that skill's Gotchas**;
   - a fact about this codebase → memory, or tell the user.
   Record candidates in `.agents/gotcha-candidates.md` (Skill target / Status: pending /
   Found: date + ticket), phrased without the ticket's specifics.
   No miss → write nothing.

### 🚦 Gate 3 — hand-off

Print the push command (with `-o merge_request.create` and target) and the MR text. The user pushes.

## Phase 5 — Review feedback (after Gate 3)

1. Check each comment against the code before accepting it; log valid / invalid (why) in the Loop log.
2. Valid → fix, test, negative control (Phase 3 step 1e), re-run the affected flows, then a new commit
   (not an amend) and updated MR testing lines.
3. Retro (Phase 4 step 4).

## Hard rules

- Every device action (repro, verify) follows the 2-tier pipeline: author via `test-author`
  (strict ID/text selectors, no coordinate guessing), then execute via `test-runner` with
  `--open-terminal`. No hand-driven Maestro/adb sessions, no full-screen screenshots.
- The Loop log and MR testing section record only what actually ran. A skipped step is written as
  skipped, with the reason.
- Never write to Jira; never push; never type credentials or create accounts.
- Outward effects (send, publish, delete real records) only on the user's yes, only to recipients
  the user named.
- Logs never contain email addresses or other PII — exception type, ids only.
- Code comments never cite `plans/`, Figma node ids or ticket analysis paths.
- Not in the PRD or the Decision → don't build it.

## Output per phase

End each phase with ≤8 lines: what is now true, what the next gate needs. No file dumps.
At each gate, when the session is long, end with: "Resume in a fresh session: `/flow-bug resume
<TICKET>`". The state file carries everything the next phase needs.
