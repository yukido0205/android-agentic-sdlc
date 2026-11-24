# Command Reference (`android-agentic-sdlc`)

> ← Back to [README.md](../README.md) | [Tiếng Việt (README_VI.md)](../README_VI.md)

Complete syntax, arguments, flags, inputs, outputs, and manual setup paths for all 12 skills, helper scripts, and pre-tool guards.

---

## 1. Detailed Skill Reference (12 Core Skills)

### 1.1. `plan-feature` — Lean Requirements & User Stories
- **When to Use:** Starting a new feature from a raw PRD, Figma link, Jira epic, or vague request.
- **Trigger / Command:**
  ```bash
  /plan-feature docs/prds/checkout-discount-prd.md
  # or
  /plan-feature "Build a biometric login option for users"
  ```
- **Inputs:** Raw requirement text, PRD markdown file, or user prompt.
- **Outputs:** Creates or updates `plans/<EPIC>/PLAN.md` containing reconciled requirements, self-contained open questions (with persona-aware Slack snippets), Anomaly Triangle User Stories, and technical risks.

---

### 1.2. `plan-slicing` — 3-Tier JIT Contract & Ladder Decomposition
- **When to Use:** Breaking down an epic's User Stories into parallel, reviewable vertical slices ($\le 300$ lines/MR) without causing context rot or planning hallucinations.
- **Trigger / Commands (3 Isolated Session Tiers — `/clear` Between Tiers):**
  ```bash
  # Tier 1 (Lead Session): Freeze Contract & list high-level Slices Overview (NOT PLANNED), then /clear
  /plan-slicing init ORDER-DISCOUNT

  # Tier 2 (Slice Owner's Fresh Session): Cut ONLY your assigned slice into a step outline (step-01..step-05), then /clear
  /plan-slicing plan slice-01

  # Tier 3 (1 Fresh Session Per Step): Scan code for step-01 only, micro-plan tasks, code, verify & ship MR, then /clear
  /plan-slicing step slice-01 step-01
  ```
- **Inputs:** `plans/<EPIC>/PLAN.md`.
- **Outputs:** `plans/<EPIC>/CONTRACT.md` (shared interfaces, DTOs, mocks) and inline step execution ladders inside `plans/<EPIC>/PLAN.md §4`.

---

### 1.3. `design-state` — Statechart Modeling & Static Validation
- **When to Use:** Designing non-trivial state machines ($\ge 4$ states, nested/parallel states, async concurrency/double-submit, or process-death recovery), generating bugfix Before/After state deltas, or reverse-engineering complex ViewModels. Skipped automatically for trivial CRUD.
- **Trigger / Commands:**
  ```bash
  # Mode 1: Forward Design into CONTRACT.md or flow-task.md
  /design-state plans/EPIC-42/PLAN.md

  # Mode 2: Bug Delta (Before -> After) for state/timing bugs
  /design-state --delta plans/APP-8092/flow-bug.md

  # Mode 3: Reverse-engineer an existing ViewModel/Manager
  /design-state app/src/main/java/com/app/checkout/CheckoutViewModel.kt

  # Static Validator (0 tokens): checks reachability, dead-ends, drift, determinism & async safety
  python3 skills/design-state/scripts/validate-statechart.py plans/EPIC-42/CONTRACT.md
  ```
- **Inputs:** `PLAN.md`, `flow-task.md`, `flow-bug.md`, or a Kotlin source file.
- **Outputs:** Dual-representation Statechart (Mermaid `stateDiagram-v2` + Transition & Guard Table with `IGNORE`/`DROP` + Lifecycle Recovery) validated by `validate-statechart.py`.

---

### 1.4. `code-domain` — Pure Domain Logic Extraction
- **When to Use:** Refactoring business logic out of fat ViewModels, Activities, or legacy helpers into pure Kotlin Clean Architecture.
- **Trigger / Command:**
  ```bash
  /code-domain app/src/main/java/com/app/user/UserViewModel.kt
  ```
- **Inputs:** Target Kotlin source file containing tangled logic and Android framework calls.
- **Outputs:**
  - Evaluates complexity (recommends skipping extraction if trivial CRUD).
  - Generates living domain specification: `docs/domain/<feature_name>.md` and pauses at an Approval Gate.
  - Creates pure Kotlin UseCases, Entities, and Sealed Errors with zero `android.*` imports.

---

### 1.5. `test-hunter` — Read-Only Defect Diagnosis
- **When to Use:** Analyzing a Jira defect, crash log, or user bug report without modifying code.
- **Trigger / Command:**
  ```bash
  /test-hunter "APP-8092: ANR occurs when user submits checkout with zero quantity items"
  # or
  /test-hunter crash-logs/anr-trace.txt
  ```
- **Inputs:** Bug description, stack trace, or logcat output.
- **Outputs:** A structured `DIAGNOSIS` report containing root cause failure mechanism, exact trigger conditions, and list of affected source files. **(Modifies zero code files.)**

---

### 1.6. `guard-blast` — Blast Radius & Regression Matrix
- **When to Use:** Post-diagnosis in bug fixing, or when PRD/Figma requirements change mid-sprint.
- **Trigger / Commands:**
  ```bash
  # Mode 1: Mid-flight PRD/design delta
  /guard-blast spec docs/prds/v1.md docs/prds/v2.md

  # Mode 2: Bug fix blast radius & allowlist definition
  /guard-blast plans/APP-8092/flow-bug.md
  ```
- **Inputs:** Diagnosis from `test-hunter` or diff between PRD documents.
- **Outputs:** Strict Allowlist of editable files and a prioritized 3-Tier Regression Test Matrix (`plans/<TICKET>/regression-plan.md`).

---

### 1.7. `test-author` — Prove-First Maestro Authoring & Static Validation
- **When to Use:** Proving acceptance criteria or bug reproductions live on a device first via Maestro MCP (`inspect_screen` + batched `run`), then freezing passing, standalone Maestro YAML flows to disk for flat-cost repeatable regression runs.
- **Trigger / Commands:**
  ```bash
  # Step 1: Prove ACs live via Maestro MCP and freeze standalone YAML flows
  /test-author plans/APP-8092/flow-bug.md --domain 02-checkout

  # Optional static fallback CLI: Scan XML android:id, Compose testTag & strings.xml by keyword
  python3 skills/test-author/scripts/extract-selectors.py app/src/main -k "checkout"

  # Step 2: Statically validate authored flows (no coordinate taps, assertions present)
  python3 skills/test-author/scripts/validate-flow.py .maestro/APP-8092/
  ```
- **Inputs:** Acceptance criteria, bug reproduction steps, or `PLAN.md` / `flow-bug.md`.
- **Outputs:** Validated, standalone Maestro YAML test flows (e.g., `.maestro/APP-8092/02-checkout/ac-01-repro.yaml`) using semantic selectors, plus overlay dismissal rules in `.maestro/_shared/popups.json`.
- **Note:** Never re-run `suite-runner.py` inside the same `/test-author` session if the ACs just passed via MCP. Use `suite-runner.py` in a fresh session for re-runs, Gate 3, or regression.

---

### 1.8. `test-runner` — Device Test Execution Engine
- **When to Use:** Running frozen Maestro suites for bug reproduction, vertical slice steps, smoke checks, or full regression on an emulator or physical device.
- **Invocation 1 — Inside Agent Chat (Slash Command & Natural Language):**
  ```text
  # Run a single vertical slice step in streaming terminal
  /test-runner .maestro/02-checkout/ -m step

  # Fast in-process bug reproduction run (15s timeout)
  /test-runner plans/APP-8092/flow-bug.md -m repro

  # Full regression suite run with streaming ANSI monitor
  /test-runner plans/APP-8092/flow-bug.md -m regression

  # Smoke tests in headless mode (suppresses external terminal, outputs in chat)
  /test-runner .maestro/ -m smoke --headless
  ```
  Natural language triggers:
  - `"run regression"` / `"verify on device"` → `regression` mode
  - `"test APP-8092"` / `"verify step-03"` → `step` mode
  - `"repro bug APP-8092"` → `repro` mode
  - `"run smoke tests"` → `smoke` mode

- **Invocation 2 — Direct CLI (Terminal / Shell / CI):**
  ```bash
  # Mode 'repro': Fast in-process run for bug reproduction
  python3 skills/test-runner/scripts/suite-runner.py plans/APP-8092/flow-bug.md -m repro

  # Mode 'step': Runs a vertical slice step in an external streaming terminal
  python3 skills/test-runner/scripts/suite-runner.py .maestro/02-checkout/ -m step

  # Mode 'regression': Full suite with state reset, live ANSI updates, and resume capability
  python3 skills/test-runner/scripts/suite-runner.py plans/APP-8092/flow-bug.md -m regression

  # Mode 'smoke': Fast smoke-tagged check for pull requests
  python3 skills/test-runner/scripts/suite-runner.py .maestro/ -m smoke

  # Headless flag (CI/CD or background runs)
  python3 skills/test-runner/scripts/suite-runner.py .maestro/ -m regression --headless

  # Decoupled build & isolated install for parallel agents (mutex device lock)
  python3 scripts/gradle-build.py assembleDebug
  python3 skills/test-runner/scripts/suite-runner.py .maestro/02-checkout/ -m step --install
  ```
- **Inputs:** Test directory path, test YAML file, or markdown state file containing a test matrix.
- **Outputs:** Live ANSI streaming terminal, `progress.log`, 1-read failure digests (`debug/digest_*.md`), failure screenshots/reports (`issues/`), and token usage summary.

---

### 1.9. `flow-bug` — End-to-End Bug Lifecycle Orchestrator
- **When to Use:** Single-command resolution of a Jira bug (*Diagnose → Repro → Fix → Verify → Ship*) with 3 human approval gates.
- **Trigger / Commands:**
  ```bash
  /flow-bug APP-8092
  /flow-bug resume APP-8092
  ```
- **Inputs:** Jira ticket ID or defect description.
- **Outputs:** Stateful tracking file `plans/<TICKET>/flow-bug.md`, verified minimal fix, and ready-to-merge branch.

---

### 1.10. `flow-task` — Standalone Sprint Task Orchestrator
- **When to Use:** Single-command delivery of an isolated mid-sprint feature or enhancement without an upfront `CONTRACT.md` (*Understand → Build → Prove → Ship*).
- **Trigger / Commands:**
  ```bash
  /flow-task APP-105 "Add voucher selection bottom sheet"
  /flow-task resume APP-105
  ```
- **Inputs:** Ticket ID and brief description or attached specs.
- **Outputs:** Lean single-file tracking state `plans/<TICKET>/flow-task.md`, verified implementation, and ready-to-merge branch.

---

### 1.11. `flow-queue` — Multi-Task Orchestrator
- **When to Use:** Running a batch of bugs and standalone tasks concurrently from one chat prompt in isolated git worktrees with batched Gate approvals.
- **Trigger / Commands:**
  ```bash
  /flow-queue PAY-101 (bug: crash on rotate), APP-105 (task: add date filter)
  /flow-queue status
  ```
- **Inputs:** List of ticket IDs and short briefs (auto-routed to `flow-bug` or `flow-task`).
- **Outputs:** Provisioned `.worktrees/<TICKET>` sandboxes and batched Gate 1/2/3 approvals.

---

### 1.12. `ship-mr` — Diff Auditing & Review Description Author
- **When to Use:** After implementation and verification, to audit staged git diffs against test evidence and draft a conventional commit + MR description.
- **Trigger / Command:**
  ```bash
  /ship-mr
  ```
- **Inputs:** Staged git diff and test output logs.
- **Outputs:** Conventional commit message and Markdown Merge Request description with embedded test evidence.

---

## 2. Parallel Agent Isolation Scripts & Guards

### Worktree Initializer (`scripts/init-worktree.sh`)
```bash
./scripts/init-worktree.sh PAY-101
# Or with a custom branch name:
./scripts/init-worktree.sh PAY-101 -b feature/pay-checkout
```
Creates `.worktrees/<TICKET>`, adds `.worktrees/` to `.gitignore`, and symlinks `local.properties`, `keystore.properties`, `secrets.properties`, `google-services.json`, `.agents/`, and `.claude/`.

### Serialized Gradle Build Wrapper (`scripts/gradle-build.py`)
```bash
python3 scripts/gradle-build.py assembleDebug
```
Uses OS-level `fcntl.flock()` semaphores (`/tmp/android_gradle_locks/slot-*.lock`, default `1` slot, configurable via `ANDROID_SDLC_GRADLE_SLOTS`) and passes `--max-workers=2` so concurrent worktrees share a single warm Gradle daemon without exhausting RAM.

### Pre-Tool Mechanical Guards (`hooks/scripts/pre-tool-guard.py`)
Runs natively in `<20ms` before `write_file`, `edit_file`, or `run_command`:
- **`[domain-purity-guard]`:** Blocks `import android.*` or `import androidx.*` inside `/domain/`.
- **`[maestro-static-gate]`:** Blocks `.maestro/**/*.yaml` files that violate `ac-NN-<slug>.yaml` naming, use coordinate taps (`point: x, y`), or omit assertions.
- **`[command-safety-guard]`:** Blocks raw `maestro test` CLI invocations (enforces `suite-runner.py`) and prompts confirmation on destructive Git/ADB commands (`git reset --hard`, `git push --force`, `adb uninstall`).
- **`[multi-device-guard]`:** Blocks un-isolated `./gradlew ... install...` commands without `ANDROID_SERIAL` when $\ge 2$ devices/emulators are active.
- **`[worktree-build-guard]`:** Blocks raw `./gradlew` inside `.worktrees/` (enforces `scripts/gradle-build.py`) and blocks `--stop` while another build slot is locked.

---

## 3. Manual Installation & Directory Layout

If you prefer manual setup instead of `./install.sh`, place or symlink files as follows:

| Target Platform | Workspace Path (Per-Project) | Global Path (Machine-Wide) |
| :--- | :--- | :--- |
| **Antigravity & Gemini CLI** | `<android-repo>/.agents/skills/*`<br>`<android-repo>/.agents/rules/code-hygiene.md`<br>`<android-repo>/.agents/hooks.json`<br>`<android-repo>/.agents/hooks/scripts/pre-tool-guard.py` | `~/.gemini/config/skills/*`<br>`~/.gemini/config/rules/code-hygiene.md`<br>`~/.gemini/config/hooks.json`<br>`~/.gemini/config/hooks/scripts/pre-tool-guard.py` |
| **Claude Code** | `<android-repo>/.claude/skills/*`<br>`<android-repo>/.claude/rules/code-hygiene.md`<br>`<android-repo>/.claude/hooks/scripts/pre-tool-guard.py` | `~/.claude/skills/*`<br>`~/.claude/rules/code-hygiene.md`<br>`~/.claude/hooks/scripts/pre-tool-guard.py` |

### Repository Structure

```text
android-agentic-sdlc/
├── README.md                     # Overview, workflows & quick start (English)
├── README_VI.md                  # Overview, workflows & quick start (Vietnamese)
├── docs/
│   └── COMMANDS.md               # Full command reference, flags & manual setup
├── install.sh                    # 1-click installer for Antigravity, Gemini CLI & Claude Code
├── scripts/
│   ├── gradle-build.py           # OS-flock Gradle build semaphore wrapper
│   ├── init-worktree.sh          # Native Android Worktree initializer (<0.2s)
│   └── init_worktree.py          # Cross-platform Python worktree initializer
├── hooks/
│   ├── hooks.json                # PreToolUse lifecycle hook configuration
│   └── scripts/
│       └── pre-tool-guard.py     # <20ms mechanical guard
├── rules/
│   └── code-hygiene.md           # Always-on rule: Lean SOLID + Why-only Docs + YAGNI Simplify
└── skills/
    ├── plan-feature/
    ├── plan-slicing/
    ├── design-state/
    ├── code-domain/
    ├── test-hunter/
    ├── guard-blast/
    ├── test-author/
    ├── test-runner/
    ├── flow-bug/
    ├── flow-task/
    ├── flow-queue/
    └── ship-mr/
```
