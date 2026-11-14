---
name: flow-task
description: One-command workflow for a standalone Jira/sprint feature or enhancement task without an upfront contract — Understand (Implicit Contract) → Build → Prove on Device → Ship, with the user speaking only at 3 gates. Bridges the gap between full epic slicing and bug fixing. Chains existing skills (code-domain, guard-blast, test-author, test-runner, ship-mr) under code-hygiene.md and suite-runner.py --install. Resumable from plans/<TICKET>/flow-task.md.
when_to_use: Invoke explicitly with /flow-task <TICKET> [description/brief] (or "/flow-task resume <TICKET>"). Use for single mid-sprint tasks without an upfront CONTRACT.md. Do NOT auto-trigger.
disable-model-invocation: true
---

# Flow Task — Understand → Build → Prove on Device → Ship (→ Feedback)

This skill owns the **order**, the **gates**, and the **state file** for a standalone feature or enhancement task. Every phase delegates to an existing skill or tool; do not reinvent their rules.

The user speaks at **3 gates**. Everything between gates executes autonomously.

## State — `plans/<TICKET>/flow-task.md`

Created on first run; read first on every resume. Format:

```markdown
# <TICKET> flow task
Phase: 1|2|3|4|5   Gate passed: 0|1|2|3   Track: fast|sliced   Step: 1/1 (or 1/2)   Branch: <name>   Base: <branch>
## Implicit Contract (Codebase Grounding) ← phase 1 (read-only): existing ViewModels/UseCases/State/Routes
## Blast Radius & Allowlist               ← phase 1: Direct Allowlist | Downstream Consumers | Explicit Non-Impact
## Anomaly Triangle & Acceptance          ← phase 1: 1-line happy path formula + AC-n bullets (safe fallback, errors, lifecycle)
## Open Questions & Assumptions           ← phase 1: resolved ones struck through
## Decision & Step Ladder                 ← gate 1: user approval + step outline (step-01..step-03 if sliced)
## Baseline                               ← unit test classes that ran + counts, before the change
## Loop Log                               ← phases 3 and 5, one line per round: findings kept / dropped / re-test result
```

`/flow-task resume <TICKET>` continues from the recorded phase. Never redo a passed gate.

---

## Phase 1 — Understand & Ground (Read-Only, Zero Code Changes)

1. **Ticket & Inputs:** Read ticket, description, and attached specs/Figma/API.
   - Missing Figma or API? Never halt. Adopt Mock-First / Skeleton mode; document assumptions in `Open Questions`.
2. **Codebase Grounding & Implicit Contract (Anti-Hallucination):**
   - Read-only scan of the target area in the repository.
   - Extract the **Implicit Contract**: exact class names, methods, ViewModels, `UiState`, `Intent`, UseCases, Repositories, and Navigation routes already in the codebase.
   - **Iron Rule:** Never invent duplicate abstractions or new wrapper interfaces when existing signatures suffice.
3. **Blast Radius & Scope Lock (via `guard-blast`):**
   - **🟢 Direct Impact (Strict Allowlist):** 2–5 files directly created or modified. Any file outside this list fails the scope check.
   - **🟡 Downstream Impact (Consumers):** Adjacent screens/observers that consume modified state/classes.
   - **🔴 Explicit Non-Impact:** Unrelated modules strictly forbidden from refactoring.
4. **Acceptance & Anomaly Triangle:**
   - Happy path is a 1-line formula: `[Current State] + [Event] -> [Target State]`.
   - Acceptance criteria (`AC-01`..`AC-n`) focus 100% on the **Anomaly Triangle**:
     - *Missing/Null Backend Data:* Map to safe state (`UNKNOWN`/empty), never optimistic.
     - *Errors & Resiliency:* Timeouts, 4xx/5xx, offline fallback, retry.
     - *Lifecycle & Stored Invariants:* Process death (`adb shell am kill`), configuration change / rotate, back/reopen.
5. **Track Selection:**
   - **Fast:** Diff ≤ 150 lines, ≤ 4 files, 1 self-contained step (`step-01`).
   - **Sliced:** Diff 150–600 lines → split into 2–3 lightweight steps (≤ 300 lines each):
     - `step-01`: Domain/business logic & validation (no-UI).
     - `step-02`: UI layout, MVI wiring, and mock integration.
     - `step-03`: Real integration, error handling, and polish.
6. **Open Questions:** List ambiguities with persona-aware Slack snippets (`👉 [A]` vs `👉 [B]`) and safe default assumptions.

### 🚦 Gate 1 — Direction & Scope

Present: Implicit Contract summary, Allowlist files, selected Track, Step Ladder, Acceptance lines, and Open Questions.
Wait for user decision. Record user response under **Decision & Step Ladder**.

---

## Phase 2 — Build (Scoped & Decoupled)

1. **Branch & Workspace:** Branch `feat/<TICKET>-<slug>` from base. When running in parallel agents, execute inside `.worktrees/<TICKET>` (initialized via `scripts/init-worktree.sh`).
2. **Baseline:** Run project unit tests with `--tests '*<feature>*'` to capture baseline count.
3. **Pure Domain Extraction (if business logic is non-trivial):**
   - Invoke `code-domain` to extract pure Kotlin UseCases into `/domain/` (enforced pure by `pre-tool-guard.py`). Skip for pure UI/CRUD tasks.
4. **Implementation under `rules/code-hygiene.md`:**
   - Code strictly the current step.
   - Apply YAGNI & Simplify: flatten nesting with guard clauses, strip debug logs and speculative params.
5. **Scope Check:** Run `git diff --name-only` against the Direct Impact Allowlist. Max 300 lines diff (excluding `res/`).
6. **Unit Tests & Decoupled Compile:**
   - Add unit tests for new logic (at most 1 test file per step).
   - Run project linter (`ktlintCheck`, `spotlessCheck`, or `detekt`).
   - **Decoupled Compile:** Run `./gradlew assembleDebug` (generates APK artifact only, zero device touch). Build failure → fix once; if it fails again, stop.

---

## Phase 3 — Prove on Device (Isolated Execution)

Repeat until a round keeps no finding (max 3 rounds):

1. **Device Execution (Parallel-Safe):**
   - Author Maestro YAML flows via `test-author` (`.maestro/<TICKET>/.../ac-NN-<slug>.yaml`) and validate with `validate-flow.py`.
   - **Isolated Install & Run:** Execute `test-runner` with `--install`:
     ```bash
     python3 skills/test-runner/scripts/suite-runner.py .maestro/<TICKET>/ -m step --install
     ```
     *(Auto-leases idle emulator via mutex lock, sets `ANDROID_SERIAL`, installs APK exclusively to locked device, and streams live ANSI terminal).*
   - AC-01 through AC-n must pass.
   - **Negative Control:** For safety guards, verify failure on invalid state or inverted condition.
2. **Review & Diff Audit:**
   - Audit diff against ≤ 300-line budget via `ship-mr` Step 1–2.
   - **Claim Check:** Every comment or commit message stating a cause cites a line read in this session.
3. **Finding Resolution:** Fix kept findings, re-run unit tests, and append to **Loop Log**.
   *(For Sliced track: when current step passes, commit and proceed to next step).*

### 🚦 Gate 2 — Approvals

Present: Diff line count, unit test results, live test proof from `suite-runner.py`, and remaining steps. Stop until answered.

---

## Phase 4 — Ship

1. **Commit:** Conventional commit message scoped to ticket (e.g. `feat(checkout): add voucher bottom sheet (#APP-105)`).
2. **MR Description:** Generated via `ship-mr` Step 3 with testing checkboxes filled with device proof.
3. **State Update:** Mark Phase 4, Gate 2 passed in `plans/<TICKET>/flow-task.md`.
4. **Retro:** For unexpected gotchas, record candidate in `.agents/gotcha-candidates.md`.

### 🚦 Gate 3 — Hand-off

Print push command (`git push -u origin <branch>`) and MR body. User pushes.

---

## Phase 5 — Review Feedback (Post-Ship)

1. Parse reviewer comments; log valid / invalid in Loop Log.
2. Fix valid feedback, re-test on device (`suite-runner.py -m step --install`), create new commit (not amend).

---

## Hard Rules

- **Zero Code Before Gate 1:** Phase 1 is strictly read-only.
- **Allowlist Scope Enforcement:** `git diff --name-only` must never exceed Direct Impact files. Max 300 lines diff per step.
- **Decoupled Build & Install:** Use `./gradlew assembleDebug` to compile; use `suite-runner.py --install` to deploy to device. Raw `./gradlew installDebug` without `ANDROID_SERIAL` is mechanically blocked.
- **Single-File State Tracking:** All status lives in `plans/<TICKET>/flow-task.md`. Never generate redundant markdown files.
- **Strict Selector Quality:** Author Maestro flows using semantic selectors (`id:` / `text:`). Coordinate taps (`point:`) are blocked by `pre-tool-guard.py`.
