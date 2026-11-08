---
name: plan-feature
description: Turns a raw PRD, feature brief, or vague request into a unified, consolidated Plan (PLAN.md) with reconciled sources, self-contained questions, Given/When/Then User Stories, and risk mitigations — then either builds a single-story feature as one-MR steps or hands an epic to plan-slicing. Uses a Lean 2-File Architecture (PLAN.md + CONTRACT.md) to eliminate over-management.
version: 3.0.0
---

# Feature Development Workflow (Lean Mode)

The requirements half of one streamlined pipeline: `/plan-feature` (writes `PLAN.md` §§ 1–3) → (epic) `/plan-slicing init` → `plan` → `step`.
Eliminates over-management by consolidating requirements, open questions, stories, and risks into a **single file (`plans/<EPIC>/PLAN.md`)**.

## Cognitive Load Reduction Rules (Anti-Overmanagement & Anti-Fatigue)

1. **Lean Architecture (Single Spec File):**
   - Output goes into **`plans/<EPIC or TICKET>/PLAN.md`** (from `assets/PLAN.template.md`).
   - Do NOT create separate `SOURCES.md`, `OPEN-QUESTIONS.md`, `FRAMES.md`, `use-cases.md`, `stories.md`, or `risks.md`. All sections live together in `PLAN.md`.
2. **Executive Summary First:** Every response MUST begin with a 3-line check:
   - `[Tier]`: Tier 1 (PRD only) · Tier 2 (PRD + Figma, no BE) · Tier 3 (Full Triad).
   - `[Red Flags]`: Breaking contradictions? (Yes/No + 1 sentence).
   - `[Readiness]`: Ready for Contract/Mocking? (Yes/No).
3. **Zero Happy Path for Standard Flows:** Assume intuitive UI interactions and 200 OK responses are understood. Never write verbose prose describing obvious user actions. Focus 100% on the **Anomaly Triangle**:
   - Contradictions between PRD, Figma, and API docs.
   - Information Gaps (missing fields, data type mismatches).
   - Edge cases, network failures, timeouts, race conditions.
4. **Self-Contained Questions in `PLAN.md §2`:** Never strip context. All rich context (flow/screen context, exact source citations, technical release risk, client defensive mock strategy, and Slack chat snippet) lives directly in `PLAN.md §2`.
5. **Persona-Aware Lazy Clarifications (No Developer Jargon):**
   - **When asking PM / Design:** Strictly communicate in **User Experience & Visual language**. Button labels, what user sees. **NEVER** use developer jargon (e.g. endpoint URLs, parameter names, "plumb it", "client-side merge").
   - **When asking Backend:** Communicate in **Data Flow & Responsibilities** (what fields UI needs, who calculates/stores, fallback behavior).
   - **Slack-Optimized Layout:** Visual examples, clear `👉 [A]` vs `👉 [B]` choices, and a polite soft-deadline assumption disclaimer so anyone can reply in 3 seconds.
6. **Ultra-Compact Output:** Max 1 screen scroll (< 300 words). Use tables and state transition formulas: `[Current State] + [Event] -> [Target State]`. No polite filler words.
7. **Language Consistency:** Always generate all artifacts in the language of the repository and PRD (default: English). Never mix languages.

## When to use

| Situation | Run |
|---|---|
| One story, no shared state, one developer | Steps 0–4 here. Builds directly into `PLAN.md §4`. |
| 2+ stories sharing data/state, or 2+ developers | Steps 0–3 here → `/plan-slicing init` |
| Revamp / migration of an existing feature | Refactor legacy workflow instead |
| Bugfix | Bugfix workflow instead |

## Inputs to gather first

1. The PRD / brief / ticket. If missing, ask — do not invent scope.
2. Figma URL, API docs, and replaced screen, if any.
   *Missing Figma or API?* Never halt or ask blocking questions. Adopt Mock-First / Domain-First via `references/unblocked-modes.md`.
3. Platform + architecture pattern. Default to repo's existing pattern (Android MVI `handleIntent` + Clean).
4. Artifact destination: `plans/<EPIC or TICKET>/PLAN.md`.

---

## Step 0 — Check for existing work (always first)

Look for prior runs in `plans/<EPIC>/PLAN.md` or existing specs. When an artifact exists, **cross-check and add deltas to it** — never write a rival spec.

## Step 1 — Reconcile sources & Log Questions (`PLAN.md` §§ 1–2)

Cross-check PRD, Figma, API docs and running code **against each other**; trust none alone.
- Write pinned specifications into `PLAN.md §1 Triad Sources & Scope`.
- For every discrepancy, gap, or ambiguity, write a **Self-Contained Question** in `PLAN.md §2`:
  - Flow & Screen context.
  - Citations (PRD §n, Figma node_id, API endpoint/field).
  - Technical Release Risk.
  - Client Defensive Strategy (fallback/mock).
  - Copy-pasteable Slack snippet with `👉 [A]` vs `👉 [B]` and deadline disclaimer.

## Step 2 & 3 — Stories, Acceptance & Risks (`PLAN.md` §3)

Consolidate user stories and edge cases into `PLAN.md §3 User Stories & Acceptance Criteria`:
- `Story <NN>`: `As a <actor>, I want <capability>, so that <value>`.
- **Zero Happy Path:** Happy path is a 1-line formula: `[State] + [Event] -> [State]`.
- Acceptance criteria focus 100% on the **Anomaly Triangle**:
  - `AC-1`: Missing fields / unknown backend data handling (map to safe state).
  - `AC-2`: Failures & edge cases (timeouts, 4xx, 5xx, retry).
  - `AC-3`: Stored data invariants (`act → leave → reopen → observe`).
- Record key technical risks (DB migration rollback, API limits, backward compatibility) with mitigations.
- Mark Phase 1 vs Phase 2. Phase 2 items go into `PLAN.md §5 Follow-ups & Phase 2`.

**Gate:** Story list and Phase 1 cut confirmed with user.
- **Single-story feature:** Proceed to Step 4.
- **2+ stories or 2+ developers:** Stop, persist `PLAN.md`, and hand off to `/plan-slicing init <EPIC>` (in this session or a fresh session).

## Step 4 — Build (single-story features only)

Cut the story into 3–5 steps (Scope goal + Acceptance Criteria) directly under `PLAN.md §4`.
**One step = one MR = one fresh session (`/clear`)**, 150–250 changed lines (hard limit 300), ~3–5 files (resources excluded).
**Step Order:** no-UI logic → walking skeleton (unreachable) → happy path → errors → polish. Every merged step falls back to the safe state.
> 🛑 **Session Boundary:** Do NOT implement all 3–5 steps in the planning session. Persist the step ladder in `PLAN.md §4`, then instruct the developer to open a **fresh session (`/clear`)** per step so each step scans and plans its own file-level details without context bloat.

---

## Iron Rules

1. **Single Source of Truth:** All specs, questions, stories, and execution steps live in `PLAN.md`. Never generate 10+ md files.
2. **No code before questions carry an assumption in force.** Every assumption is a visible row in `PLAN.md §2`.
3. **Every edge case ends up somewhere:** an `AC`, a risk mitigation, or `PLAN.md §5`.
4. **Zero Happy Path & Self-Contained Questions:** Never write verbose prose for standard flows. All questions in `PLAN.md §2` contain full context and Slack snippets.
5. **Never Block on Missing Figma or BE:** Unblock immediately with proposed contracts or wireframe skeleton assumptions via `references/unblocked-modes.md`.

## References

- `references/unblocked-modes.md` — Playbook when Figma or BE API is missing.
- `references/edge-case-checklist.md` — Probes for edge cases and omissions.
- `assets/PLAN.template.md` — Unified feature & execution plan template.
- Related skill: `plan-slicing` (for epics with 2+ stories).
