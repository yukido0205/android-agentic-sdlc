---
name: test-author
description: "Author deterministic, robust Maestro E2E test flows from PRD, Figma specs, and Jira acceptance criteria. Enforces semantic domain directories (e.g., 01-order-list/), strict naming (ac-01-slug.yaml), selector best practices (id/text over coordinates), preflight dependencies, and reusable helpers. Use when creating new Maestro test flows, converting PRD/acceptance criteria to YAML, or when the runner reports missing flows."
argument-hint: "<step-file | <TICKET> | PRD/plan path> [--domain <folder-name>]"
model: sonnet
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Bash(python3 skills/test-author/scripts/*)
  - Bash(python3 skills/test-runner/scripts/*)
  - Bash(~/Library/Android/sdk/platform-tools/adb *)
  - Bash(adb *)
  - Bash(git status --short *)
  - mcp__maestro__run
  - mcp__maestro__cheat_sheet
---

# Test Author — PRD & Acceptance to Deterministic Maestro Flows

A dedicated skill for designing, structuring, and authoring clean, maintainable Maestro E2E test flows.

> [!IMPORTANT]
> **Separation of Concerns:**
> - **Authoring (`/test-author`):** Analyzes specs, designs directory structure, writes semantic YAML flows, and statically validates them.
> - **Executing (`/test-runner`):** Runs existing suites via `suite-runner.py`. The runner **NEVER** authors or improvises flows.

---

## 1. Directory & File Organization Standards

All test flows live under `.maestro/<EPIC>/`.

```
.maestro/<EPIC>/
├── _shared/                           # Reusable setup/teardown helpers (must start with '_')
│   ├── _login-user.yaml
│   └── _seed-order.yaml
├── 01-order-list/                     # NN-<domain-slug> (semantic, human-readable)
│   ├── ac-01-display-all-orders.yaml  # ac-NN-<slug>.yaml (mapped 1:1 to acceptance criteria)
│   ├── ac-02-pull-to-refresh.yaml
│   └── ac-03-filter-by-status.yaml
├── 02-order-details/
│   ├── ac-01-view-order-spec.yaml
│   └── ac-02-item-rows-layout.yaml
└── 03-checkout-payment/
    ├── ac-01-submit-disabled-initially.yaml
    └── ac-02-apply-discount-code.yaml
```

### Strict Naming Rules
1. **Directories:** Must match `^\d{2}-[a-z0-9-]+$` (e.g. `01-order-list`).
   - ❌ Never use cryptic abbreviations (`s1`, `f3`, `s2s4`).
2. **Test Flow Files:** Must match `^ac-\d{2}-[a-z0-9-]+\.yaml$` (e.g. `ac-01-display-all-orders.yaml`).
   - ❌ Never use ambiguous names (`r-1.yaml`, `test.yaml`, `step1.yaml`).
3. **Helper Flows:** Must start with `_` (e.g. `_login.yaml`, `_cleanup.yaml`).
   - Helper flows are excluded from regression runners automatically.

---

## 2. Authoring Workflow

### Step 1: Extract Acceptance Criteria
Extract the criteria from the story, PRD, or plan file:
```bash
skills/test-author/scripts/extract-acceptance.sh plans/<EPIC_OR_TICKET>/PLAN.md [step-id]
# or for bug workflows:
skills/test-author/scripts/extract-acceptance.sh plans/<TICKET>/flow-bug.md
```
Map each top-level acceptance criterion (AC) directly to an `ac-NN-<slug>.yaml` file.

### Step 2: Establish Common Helpers (`_shared/`)
Check if login, navigation, or data seeding helpers already exist in `.maestro/_nav/` or `.maestro/<EPIC>/_shared/`. If not, author them first.
Helpers must be idempotent:
```yaml
# _login-user.yaml
appId: com.example.app
---
- runFlow:
    when:
      visible:
        id: "com.example.app:id/btn_login"
    commands:
      - tapOn:
          id: "com.example.app:id/btn_login"
      # input credentials...
```

### Step 3: Write Test Flows
Each test flow must follow this standard structure:
```yaml
# ac-01-display-all-orders.yaml
appId: com.example.app
---
# 1. State Setup / Navigation
- runFlow:
    file: ../_shared/_login-user.yaml
    optional: true

# 2. Action Steps
- extendedWaitUntil:
    visible:
      id: "com.example.app:id/rv_order_list"
    timeout: 10000

# 3. Assertions (Strictly required)
- assertVisible:
    text: "My Orders"

- assertVisible:
    id: "com.example.app:id/tv_order_item_title"
```

### ⚠️ Anti-Flakiness & Quality Rules (Mandatory)
* **NO Coordinate Tapping (`point:`):** Never use hardcoded pixel coordinates like `input tap 100 500` or `tapOn: { point: "100, 500" }`. Always find the view ID in layout XMLs or use accessible text.
* **Always Assert:** Every flow must contain at least one `assertVisible`, `assertTrue`, or `assertNotVisible`. A flow with no assertion is not a test.
* **Timeout Handling:** Prefer `extendedWaitUntil: { visible: ..., timeout: 10000 }` over static `sleep: 5000`.

---

## 3. Validation

Before committing or handing off to the runner, always validate the authored flows:

```bash
python3 skills/test-author/scripts/validate-flow.py .maestro/<EPIC>/
```

The validator checks:
* Directory naming standard (`NN-<domain-slug>`)
* File naming standard (`ac-NN-<slug>.yaml`)
* Coordinate tap detection (`point:` prohibition)
* Presence of assertions (`assertVisible`)
* Excessive sleep warnings

---

## 4. Handoff to Test Runner

Once validation passes, inform the user or launch the runner:
```bash
python3 skills/test-runner/scripts/suite-runner.py .maestro/<EPIC>/ -m step
```
