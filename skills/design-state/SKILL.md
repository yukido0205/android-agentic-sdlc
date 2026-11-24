---
name: design-state
description: Designs and validates Harel Statecharts (Mermaid stateDiagram-v2 + Transition & Guard Table) for non-trivial Android MVI and domain logic so developers can review behavior at a glance and agents avoid double-submits, stale callbacks, dead-ends, and impossible states. Supports Forward Design, Bug Delta (Before -> After), and Legacy Reverse-Engineering, backed by validate-statechart.py.
version: 1.0.0
---

# Design State — Lean Statechart Modeling & Validation

Use this skill to model **dynamic state behavior** before writing MVI `handleIntent` / domain state-machine code, or to reverse-engineer and audit complex existing state logic.

Instead of scattering transition rules across prose or discovering race conditions during QA, `/design-state` produces a **Dual Representation**:
1. **Mermaid `stateDiagram-v2` (≤ 12 states):** Visual topology (nested states, parallel regions, happy & error loops) for human review at Gate 1 and in MRs.
2. **Transition & Guard Table + Lifecycle Recovery:** Deterministic matrix specifying every `(State, Event/Intent, Guard) -> Next State | Effect`, including **`IGNORE`** (double-tap protection) and **`DROP`** (stale async callback protection).

---

## When to Use vs. When to Skip (Anti-Overmanagement Rule)

Do **not** draw a Statechart for trivial screens. Apply this gate first:

### Skip (`Statechart: SKIPPED (<reason>)`) when ALL apply:
- Purely static UI / read-only display or trivial 1-shot CRUD (`Idle -> Loading -> Content | Error`) with no retry/cancel/concurrency rules.
- `flow-bug` Fast track (≤ 5 changed lines, single file, no business flow change).

### Require Statechart when ANY apply:
1. **≥ 4 concrete states**, or uses **nested (composite)** / **parallel (orthogonal)** states.
2. **Async concurrency or timing:** debounce search, polling, countdown/OTP timer, upload/cancel, double-submit risk, or multi-step wizard.
3. **Lifecycle / persistence invariant:** state must survive `Process death`, config change, or navigation back/reopen.
4. **Bug fix with state/timing risk:** `flow-bug` triggers Fix-shape check `c` (*New or changed state*) or `d` (*Timing*).

---

## 3 Operating Modes

| Mode | Trigger / Caller | Input | Output Target |
|---|---|---|---|
| **1. Forward Design** | `/design-state <PLAN.md \| brief>`, `plan-slicing init`, `flow-task` Phase 1 | PRD / `PLAN.md` / `flow-task.md` | `CONTRACT.md §3` (epic) or `plans/<TICKET>/flow-task.md` |
| **2. Bug Delta** | `/design-state --delta <flow-bug.md>`, `flow-bug` Phase 1 Step 6 (checks `c`/`d`) | `test-hunter` DIAGNOSIS + target code | `plans/<TICKET>/flow-bug.md` (`Before -> After` delta) |
| **3. Reverse-Engineer** | `/design-state <PathToViewModel.kt>`, `code-domain` Step 2 | Existing Kotlin `ViewModel` / `Manager` / `UseCase` | `docs/domain/<feature>.md §5` or chat review report (flagging dead-ends & race bugs) |

---

## Execution Workflow

### Step 1 — Check Skip Rule & Identify State Boundaries
1. Read the source spec (`PLAN.md`, `flow-task.md`, `DIAGNOSIS`) or target Kotlin file (read-only).
2. Evaluate the **When to Use vs. When to Skip** rule above.
   - If skipped: write `Statechart: SKIPPED (<1-line reason>)` and stop.
3. List all finite states (prefer ≤ 12; group sub-states inside composite `state Parent { ... }` blocks, or split into orthogonal regions using `--`).

### Step 2 — Author Dual Representation (from `assets/STATECHART.template.md`)
Follow `references/statechart-patterns.md` for standard Android MVI patterns:

1. **Mermaid `stateDiagram-v2`:**
   - Must start with `[*] --> <InitialState>`.
   - Terminal states must transition to `[*]`, or non-terminal states must have valid exit/retry paths (no dead-ends).
   - Keep labels concise (`Event [Guard]`). Never put `IGNORE` or `DROP` boxes inside Mermaid — those belong in the Transition Table so the diagram stays readable.
2. **Transition & Guard Table:**
   ```markdown
   | State | Event / Intent | Guard | Next State | Effect / Event |
   |---|---|---|---|---|
   | `Editing` | `Submit` | `isValid` | `Submitting` | `submitOrder()` |
   | `Submitting` | `Submit` | `—` | `IGNORE` | `—` |
   | `Cancelled` | `ApiSuccess` | `—` | `DROP` | `—` |
   ```
   - **`IGNORE`**: Stay in current `State` and absorb duplicate user intent (e.g., double-tap while `Submitting`).
   - **`DROP`**: Discard stale async callback that arrives after leaving the expected state (e.g., `ApiSuccess` arriving when already `Cancelled` or `Idle`).
   - **`*` / `ANY`**: Global transition valid from any non-terminal state (e.g., `SessionExpired -> LoggedOut`).
3. **Lifecycle Recovery (1–2 lines):**
   - Explicitly state what happens on **Process death**, **Configuration change**, and **Background/Reopen** (e.g., `Process death in [Editing] -> restore draft via SavedStateHandle; in [Submitting] -> reset to [Editing] with Retry banner`).
4. **Mode 2 (`--delta`) Addendum:**
   - Put the buggy snapshot under a `### Before (Buggy)` heading (or tag the Mermaid block with `%% statechart-ignore` and the table with `<!-- statechart-ignore -->`) and the target state machine under `### After (Fixed)`.
   - `validate-statechart.py` automatically skips `### Before...` / `%% statechart-ignore` blocks and strictly validates the `### After (Fixed)` Statechart, so the reviewer sees the exact broken arrow without false-positive validator failures.

### Step 3 — Mechanical Validation (0 Tokens)
Before presenting at Gate 1 or freezing `CONTRACT.md`, **always** run:

```bash
python3 skills/design-state/scripts/validate-statechart.py <path-to-markdown-file>
```

- **Errors (exit 1 — must fix before Gate 1):**
  - Missing `[*] --> Initial` or missing Transition Table.
  - Unreachable state (cannot be reached from `[*]`).
  - Dead-end state (non-terminal state with zero outgoing transitions; `IGNORE`/`DROP` do not count as exits).
  - Graph ↔ Table drift (state in Table missing from Mermaid, or leaf state in Mermaid missing from Table).
  - Non-deterministic transition (same `(State, Event, Guard)` mapping to 2 different `Next State`s).
- **Warnings (exit 0 — review and either address or justify):**
  - Async state (`Loading`, `Submitting`, `Uploading`, `Polling`, etc.) missing `Error`/`Timeout`/`Cancel` exit or missing `IGNORE`/`DROP` re-entry protection.
  - Cognitive budget exceeded (> 12 states — consider composite states or splitting the slice).
  - Missing `Lifecycle Recovery` line.

### Step 4 — Map Statechart to Kotlin MVI & Unit Tests
When moving into implementation (`plan-slicing step`, `flow-task` Phase 2, `code-domain` Step 3–4):
1. **Encode states in types:** Model finite states as a `sealed interface` / `enum class` inside `UiState` (per `plan-slicing/references/mobile-contracts.md`), preventing impossible flag combinations like `isLoading = true && error != null`.
2. **1-to-1 `handleIntent` dispatch:** Match `when (currentState to intent)` (or nested `when` on state first, then intent) directly against the Transition Table. Explicitly handle `IGNORE` / `DROP` branches with no-op returns (never silently mutate state).
3. **1-to-1 Test Coverage:** Every row in the Transition Table with `Guard=false`, `Error`/`Timeout`, `IGNORE`, or `DROP` **must** have a corresponding JVM unit test (and critical user-visible rows covered by Maestro ACs).

---

## Iron Rules
1. **Skip trivial CRUD:** Never force a Statechart on static screens or simple 1-shot loads.
2. **Mermaid for humans, Table for machines:** Keep Mermaid ≤ 12 states; put `IGNORE`, `DROP`, and detailed effects in the Transition Table.
3. **Zero Drift:** Every state in the Transition Table must exist in Mermaid, and every leaf state in Mermaid must appear in the Transition Table.
4. **Validate before Gate 1:** Never freeze a `CONTRACT.md` or present Gate 1 with `validate-statechart.py` failing (exit 1).
5. **No speculative transitions:** Every transition and guard must trace back to the PRD, `PLAN.md`, or verified codebase behavior.

## References
- `references/statechart-patterns.md` — Standard Android MVI Statechart patterns (async submit, debounced search, orthogonal regions, process death).
- `assets/STATECHART.template.md` — Copy-ready Statechart section template passing `validate-statechart.py`.
- `scripts/validate-statechart.py` — Static analyzer for reachability, dead-ends, drift, determinism, and async safety.
