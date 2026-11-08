# Architectural Overview & Case Studies: Android Agentic SDLC (`android-agentic-sdlc`)

## 1. Introduction

As AI coding assistants have evolved from simple code completion to autonomous multi-step agents, mobile engineering teams encounter distinct operational friction. Without specialized domain rules, Large Language Models (LLMs) struggle with mobile lifecycle nuances, generate speculative abstractions, accidentally refactor adjacent files, and deliver unverified patches.

To maximize pragmatism and eliminate tool-call overhead, this repository separates **Always-On Coding Guardrails (Rules)**, **Zero-Token Mechanical Checks (Hooks)**, and **Task-Specific Workflows (Skills)**:

- **1 Always-On Core Rule (`rules/code-hygiene.md`)**: Enforces Lean SOLID design (pre-code), Intent-Only documentation (during-code), and YAGNI simplification (post-code) on every line of code without requiring manual invocation.
- **1 Zero-Token PreToolUse Hook (`hooks/hooks.json` & `hooks/scripts/pre-tool-guard.py`)**: Executes in <20ms before file writes or shell commands to mechanically block `import android.*` in `/domain/`, invalid Maestro YAML flows (`point:` taps or missing assertions), and raw `maestro test` token-bleed commands.
- **9 Specialized Agent Skills (`skills/`)** organized by SDLC phase:
  - **`plan-*`**: Requirements normalization & architectural slicing (`plan-feature`, `plan-slicing`).
  - **`code-*`**: Pure domain logic extraction (`code-domain`).
  - **`guard-*`**: Blast radius containment & safety allowlists (`guard-blast`).
  - **`test-*`**: Defect investigation, test authoring, & device execution (`test-hunter`, `test-author`, `test-runner`).
  - **`flow-*`**: Closed-loop multi-skill orchestration (`flow-bug`).
  - **`ship-*`**: Diff auditing & production delivery (`ship-mr`).

---

## 2. Why Code Hygiene Is an Always-On Rule (Not 3 Separate Skills)

### `rules/code-hygiene.md` — Lean SOLID · Why-Only Docs · YAGNI Simplify
- **Real-World Pain Point:** Earlier iterations split code quality into three separate skills (`code-solid`, `code-doc`, `code-simplify`). In daily practice, developers rarely invoked three separate slash commands just to write clean code, and orchestrators wasted multiple `read_file` tool calls loading thin checklists.
- **Why It Evolved into a Single Rule:** Code quality is an **invariant**, not an optional workflow step. Every line of code written by the agent must adhere to Lean SOLID, high-signal comments, and YAGNI de-bloating by default.
- **Concrete Solution & Value:** Consolidates all three phases into a single 45-line Always-On Rule:
  1. **Pre-Code (Lean SOLID):** Challenges unnecessary abstractions (*"Does this interface actually have 2+ implementations?"*).
  2. **During-Code (Why-Only Docs):** Bans syntax-transliteration comments; requires every causal claim in comments to be verified against actual code lines.
  3. **Post-Code (YAGNI Simplify):** Flattens deep nesting with guard clauses, strips debug logs (`Log.d`), and forbids widening visibility to `public` solely for tests.

---

## 3. In-Depth Case Studies: The 9 Core Skills

### 3.1. `plan-feature` — Taming Ambiguous Specifications
- **Real-World Pain Point:** Product requirements arrive scattered across Jira tickets, Figma design files, and Slack discussions. When an AI agent is asked to "implement this feature," it often begins coding immediately on untested assumptions or generates 4–5 fragmented planning documents that create cognitive fatigue for the team.
- **Why the Skill Was Born:** To force a Lean 1-File Planning architecture (`plans/<EPIC>/PLAN.md`).
- **Concrete Solution & Value:** Reconciles conflicting sources upfront, documents explicit self-contained open questions with copy-pasteable Slack snippets, standardizes User Stories into Anomaly Triangle acceptance criteria, and catalogues technical risks before any code is generated.

### 3.2. `plan-slicing` — Eliminating Monolithic PRs & Planning Hallucinations (3-Tier JIT Slicing)
- **Real-World Pain Point:** Large epics handed to AI fail in two ways: (1) generating massive, unreviewable multi-thousand-line PRs, or (2) asking the AI to scan the entire codebase and plan micro-details for all 20+ steps upfront in one session, which dilutes attention and causes severe hallucination.
- **Why the Skill Was Born:** To break complex features into independent vertical slices using **3-Tier Just-In-Time (JIT) Progressive Planning** across isolated sessions (`init <EPIC>` $\to$ `plan <slice-id>` $\to$ `step <slice-id> <step-id>`).
- **Concrete Solution & Value:**
  1. **Tier 1 (`init <EPIC>` — Lead Session):** Generates a frozen `CONTRACT.md` (shared interfaces/mocks) and a high-level Slices Overview table in `PLAN.md §4` (`NOT PLANNED`), then clears context (`/clear`).
  2. **Tier 2 (`plan <slice-id>` — Slice Owner Session):** Whoever picks up a slice opens a fresh session to cut *only that slice* into a 3–5 step outline (`step-01..step-05`: Goal + AC only), then clears context (`/clear`).
  3. **Tier 3 (`step <slice-id> <step-id>` — 1 Step = 1 Fresh Session = 1 MR):** Each step runs in its own clean session, scanning the codebase just-in-time to micro-plan and code only that step ($\le 300$ lines per MR).

### 3.3. `code-domain` — Isolating Business Rules from Legacy Code
- **Real-World Pain Point:** Legacy Android codebases frequently contain 1,500+ line "God Activities" or bloated ViewModels where database queries, Android SDK calls (`Context`, `SharedPreferences`), and crucial domain calculations are tangled together. When prompted to modify or refactor such code, AI agents often hallucinate non-existent Android APIs, misinterpret Android lifecycle states, or introduce subtle regressions.
- **Why the Skill Was Born:** Originally conceived to **isolate pure business rules from legacy Android architecture into a pure Kotlin domain layer**, while knowing when to skip the layer entirely for simple CRUD.
- **Concrete Solution & Evolution:** Extracts logic into pure Kotlin Entities, UseCases, and Sealed Class Errors with zero Android framework dependencies after passing an explicit human Approval Gate. It serves as the architectural backbone of the pipeline—providing clean contracts for `plan-slicing`, deterministic boundaries for `guard-blast`, and explicit scenarios for `test-author`.

### 3.4. `test-hunter` — Disciplined, Read-Only Defect Investigation
- **Real-World Pain Point:** When presented with a bug report or stack trace, most AI agents immediately start modifying files based on superficial guesses. This trial-and-error editing pollutes git history and introduces new bugs.
- **Why the Skill Was Born:** To enforce a strict separation between *diagnosis* and *implementation*.
- **Concrete Solution & Value:** A strictly read-only investigative agent. It analyzes Jira tickets, stack traces, logs, and code flow without touching a single file, producing a formal `DIAGNOSIS` report identifying the root cause mechanism, trigger conditions, and affected files.

### 3.5. `guard-blast` — Blast Radius Control & Regression Prevention
- **Real-World Pain Point:** When fixing a defect or adapting to a mid-sprint PRD delta, agents often modify adjacent modules that were never intended to be touched, causing silent regressions across the application.
- **Why the Skill Was Born:** To prevent scope creep and provide a deterministic safety perimeter around changes.
- **Concrete Solution & Value:** Operates in two modes:
  - *Mode 1 (Spec/Design Delta):* Analyzes changes between requirement versions and re-sweeps finished work.
  - *Mode 2 (Bug Fix Blast Radius):* Establishes a strict **Allowlist** of editable files (forbidding edits elsewhere) and derives a high-signal regression test matrix based on actual risk tiers (Tier 1 Direct $\to$ Tier 3 System).

### 3.6. `test-author` — Deterministic Maestro Test Authoring
- **Real-World Pain Point:** Writing end-to-end mobile tests manually is slow, and raw AI-generated tests frequently fail due to hardcoded tap coordinates, missing accessibility selectors, or fragile timing delays (`sleep`).
- **Why the Skill Was Born:** To generate robust, deterministic Maestro UI test flows from PRD acceptance criteria or bug reproduction steps.
- **Concrete Solution & Value:** Enforces semantic domain directories (e.g., `01-order-list/`), standardized naming (`ac-01-display-all-orders.yaml`), robust selector hierarchies (preferring accessibility IDs and text over coordinates), and validates them statically via `validate-flow.py`.

### 3.7. `test-runner` — High-Volume Device Automation & Real-Time Feedback
- **Real-World Pain Point:** Real mobile regression suites contain hundreds of tests (~270 items). Running them via sequential LLM tool calls burns hundreds of thousands of tokens, and background runs without live terminal output leave developers guessing if tests are hanging.
- **Why the Skill Was Born:** To provide a unified native runner (`suite-runner.py`) with zero LLM token bleed, mode presets, and live visual feedback.
- **Concrete Solution & Value:** Introduces 4 streamlined presets (`-m repro`, `step`, `regression`, `smoke`), streams real-time ANSI updates directly to an external terminal, auto-captures failure screenshots/UI hierarchies, measures Figma dp/colors via `device.py`, and tracks AI token usage via `token-usage.py`.

### 3.8. `flow-bug` — Closed-Loop Bug Lifecycle Orchestrator
- **Real-World Pain Point:** The traditional bug-fixing process is fragmented: a developer diagnoses in one tool, tests on a device, writes code in an IDE, runs manual checks, and writes a PR description. Context is repeatedly lost between these manual steps.
- **Why the Skill Was Born:** A one-command orchestrator that automates the full bug lifecycle (Understand $\to$ Fix $\to$ Prove $\to$ Ship).
- **Concrete Solution & Value:** Chains 5 skills (`test-hunter` $\to$ `guard-blast` $\to$ `test-author` $\to$ `test-runner` $\to$ `ship-mr`) under the always-on `code-hygiene` rule in a stateful, resumable workflow (`plans/<TICKET>/flow-bug.md`), requesting human review at only 3 critical gates.

### 3.9. `ship-mr` — Rigorous Merge Request Auditing & Evidence Packaging
- **Real-World Pain Point:** Developers and AI agents often generate vague PR descriptions (e.g., "Fix ticket 123") without verifying git diffs against ticket requirements, leading to slow reviews and unverified claims.
- **Why the Skill Was Born:** To ensure every Merge Request is thoroughly audited and backed by concrete test evidence before submission.
- **Concrete Solution & Value:** Audits the staged git diff (≤300 lines), verifies causal claims in comments/commits against inspected code, checks test coverage and allowlist compliance, and generates conventional commit messages alongside structured MR documentation.

---

## 4. The Synergistic Evolution

While each component was originally developed to resolve a standalone bottleneck, their real power emerged when connected:
- `code-hygiene` acts as the always-on conscience keeping every diff lean, self-documenting, and free of speculative bloat.
- Once business rules are isolated into pure Kotlin UseCases via `code-domain`, `guard-blast` calculates zero-bleed blast radiuses, `plan-slicing` defines clean mock contracts, and `test-author` + `test-runner` verify device behavior with zero token waste.
