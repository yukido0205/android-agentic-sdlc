---
name: flow-queue
description: Single-chat multi-task orchestrator for running multiple Android bugs and standalone tasks concurrently in isolated worktrees with a 0-token real-time Terminal monitor (`SDLC Queue Monitor`) and batched human gate approvals. Dispatches sub-agents per ticket running `flow-bug` or `flow-task` without diluting their rules.
when_to_use: Invoke explicitly with /flow-queue <ticket list> (e.g. "/flow-queue PAY-101 (bug: ...), APP-105 (task: ...)"), "/flow-queue status", or "/flow-queue resume". Do NOT auto-trigger.
disable-model-invocation: true
---

# Flow Queue — Multi-Task Orchestrator & Live Monitor

Orchestrate multiple tickets from **1 single chat prompt** while preserving 100% of `flow-bug` and `flow-task` discipline.

The coordinator owns **worktree provisioning**, **live monitor launch**, **sub-agent dispatch**, and **batched Gate 1 / 2 / 3 approvals**. Each sub-agent owns execution inside its isolated `.worktrees/<TICKET>/` sandbox.

---

## Subcommands

- `/flow-queue <ticket list>`: Parse tasks, provision worktrees, open live monitor, and dispatch parallel Phase 1 grounding.
- `/flow-queue status`: Run `queue-monitor.py --once` and summarize current state.
- `/flow-queue resume`: Inspect `.worktrees/*` and `plans/*/flow-*.md` via `--once`, then resume pending sub-agents from their recorded Gate/Phase.

*(Resolve `queue-monitor.py` from this skill's `scripts/queue-monitor.py` path—e.g. `skills/flow-queue/scripts/queue-monitor.py` or `.agents/skills/flow-queue/scripts/queue-monitor.py`).*

---

## Step 1 — Parse & Classify Queue

Extract each ticket ID and brief from the user's prompt. Classify into:
- **`bug`** → Sub-agent executes `skills/flow-bug/SKILL.md`.
- **`task`** (standalone feature/enhancement without `CONTRACT.md`) → Sub-agent executes `skills/flow-task/SKILL.md`.
- **`slice`** (existing `plans/<EPIC>/PLAN.md`) → Sub-agent executes `skills/code-domain/SKILL.md` / `skills/plan-slicing/SKILL.md`.

*(Ambiguous item? Default to `task` if describing new behavior, `bug` if describing broken behavior, and note the classification in Gate 1).*

---

## Step 2 — Provision Worktrees & Launch 0-Token Monitor

Run **one single shell command** from repo root:
```bash
python3 skills/flow-queue/scripts/queue-monitor.py --init <TICKET_1> <TICKET_2> ... --open-terminal
```
This creates `.worktrees/<TICKET>` (`<0.2s` each), symlinks Android SDK/keystores/skills, sets `org.gradle.workers.max=2` to protect macOS RAM, and opens the `SDLC Queue Monitor` Terminal window (0 LLM tokens).

---

## Step 3 — Parallel Sub-Agent Dispatch (Phase 1 Only)

Invoke up to **3 concurrent background sub-agents** (queued in waves if >3 tickets to prevent RAM exhaustion). Give every sub-agent these **4 Hard Rules**:

1. **Strict Worktree Confinement:** Read, edit, compile, and run git/gradle/maestro **only** inside `.worktrees/<TICKET>/`. Never touch root repo source files.
2. **Skill Fidelity:** Read and follow `skills/flow-bug/SKILL.md` (for `bug`) or `skills/flow-task/SKILL.md` (for `task`) verbatim. Do not skip `test-hunter`, `guard-blast`, `code-hygiene.md`, or `suite-runner.py --install`.
3. **Gate Stop Boundary:** Complete **Phase 1 (Read-Only Grounding)**, write `plans/<TICKET>/flow-{bug,task}.md` containing `[WAITING_GATE_1]` on its status header, then **STOP IMMEDIATELY** and return a concise Gate 1 summary (≤ 6 bullets). Never edit production code before Gate 1 approval.
4. **Decoupled Build & Device Lease:** In Phase 2–3, compile via `./gradlew assembleDebug` only; deploy & verify exclusively via `python3 skills/test-runner/scripts/suite-runner.py ... --install` so parallel agents auto-lease separate emulators safely.

---

## Step 4 — Batched Human Gate Approvals (Main Chat)

When Phase 1 sub-agents finish, present **one consolidated Gate 1 table** in the main chat:

| Ticket | Type | Track | Root Cause / Implicit Contract | Allowlist Scope | Open Questions |
| :--- | :--- | :--- | :--- | :--- | :--- |

Wait for the user's single batched reply (e.g., *"Approve all"*, or *"Approve PAY-101; for APP-105 use option B"*).

- On approval, instruct each approved sub-agent to clear `[WAITING_GATE_1]`, record the user's **Decision**, advance `Phase: 2   Gate passed: 1`, and execute autonomously through **Phase 2 → Phase 3** until **Gate 2** (`[WAITING_GATE_2]`).
- Repeat the same batched review at **Gate 2 (Approve Code & E2E Proof)** and **Gate 3 (Ship MR)**, then remind the user to clean up finished worktrees (`git worktree remove .worktrees/<TICKET>`).

---

## Coordinator Iron Rules

- **Zero Direct Edits by Coordinator:** The main chat agent must never edit Kotlin/XML/Gradle files or run `./gradlew` directly—always delegate to the ticket's sub-agent inside `.worktrees/<TICKET>/`.
- **No Redundant Tracking Files:** Never create queue-level `.md`/`.json` files; `queue-monitor.py` reads directly from each ticket's `plans/<TICKET>/flow-{bug,task}.md` and `/tmp/android_device_locks/*.lock`.
- **Diff Budget Respect:** Every ticket sub-agent must still respect its ≤ 300 lines per step MR cap.
