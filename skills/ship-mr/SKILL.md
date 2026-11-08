---
name: ship-mr
description: 3-step Merge Request (MR) review, verification gate, and description author for mobile teams. Steps 1–2 audit the diff, test coverage, and claims; Step 3 generates conventional commit messages and structured MR bodies with testing evidence.
version: 1.0.0
tags: [git, merge-request, pull-request, conventional-commits, code-review]
---

# MR Message — 3-Step Review & Description Workflow

Use this skill to audit code changes and produce professional, review-ready Merge Requests (GitLab / GitHub).

---

## Step 1: Scope & Diff Audit (Review)

Before writing any MR description, audit the change:
1. **Diff Size & Budget:**
   - Run `git diff --stat <target-branch>...HEAD -- . ':!*/res/*'` (target: ≤ 300 lines).
   - Flag any large diffs that should be split into smaller slices.
2. **Scope Discipline:**
   - Verify every modified file directly corresponds to the planned fix or feature.
   - Any unrelated file (formatting-only, unrelated refactor) must be reverted or justified.
3. **Claim Check:**
   - Audit every claim in code comments or commit messages ("X is instantiated by Y", "Z never runs here").
   - Every claim must cite concrete code inspected in this session. Remove or correct unproven assumptions.

---

## Step 2: Quality Gate (Verification)

Check the following before approving readiness to ship:
- [ ] **Linter / Formatting:** Run the project linter (e.g. `:app:ktlintCheck`, `detekt`, or `spotlessCheck`). Zero new violations allowed.
- [ ] **Unit Tests:** Relevant feature unit tests pass.
- [ ] **E2E / Device Tests:** AC-1 (reproduction) passes; regression suite passes.
- [ ] **Negative Control (Bug fixes):** The test or flow fails on unfixed code and passes with the fix.

---

## Step 3: Author MR & Commit Message (Ship)

Generate the commit message and MR description according to this standard:

### 1. Commit Message (Conventional Commits)
```text
<type>(<scope>): <short imperative description> (PROJ-123)

[Optional body explaining context, root cause, and architectural decision]
```
* **Types:** `feat` (new feature), `fix` (bug fix), `refactor` (code restructuring), `test` (adding/updating tests), `chore` (build/deps).
* **Length:** First line ≤ 72 characters.

### 2. Merge Request Body Template

```markdown
## Summary
Brief 2-3 sentence overview of what changed and why.

## Ticket
- Closes [PROJ-123](https://jira.example.com/browse/PROJ-123)

## Changes
- Concise bullet points of technical modifications:
  - Added `...`
  - Fixed race condition in `...`

## Testing Evidence
- [x] **Unit Tests:** `<X> passing` (`<TestClass>`)
- [x] **Device / Maestro E2E:**
  - Repro Flow (`ac-01-repro.yaml`): **PASS**
  - Regression Flows: **PASS** (`<folder>/`)
- [ ] **Manual / QC Checklist:**
  - Verified on Android emulator (API XX)

## Blast Radius & Risks
- **Impacted Areas:** `<screen or domain components>`
- **Non-Impacted Areas:** Verified `<shared components>` remain untouched.
```
