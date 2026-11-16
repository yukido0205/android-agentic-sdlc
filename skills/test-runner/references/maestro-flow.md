# Maestro flow — behavior mode

Load this only when writing or fixing a flow.

## Semantic Directory Layout & Naming Conventions

Never use cryptic single-letter abbreviations like `s3`, `f3`, `s2s4`, `f5`. Folders and files must be **self-descriptive**, making it immediately obvious WHAT is being verified.

### Structure:
```
.maestro/
  _nav/<screen>.yaml                    # Reusable navigation subflows
  <TICKET_OR_EPIC>/                     # e.g., PROJ-123
    ├── <step_num>-<feature-slug>/      # Descriptive feature folder (e.g., 03-checkout-payment)
    │   ├── ac-01-<behavior-slug>.yaml # Acceptance flow (e.g., ac-01-submit-disabled-when-empty.yaml)
    │   ├── ac-02-<behavior-slug>.yaml
    │   └── design/
    │       └── <screen-state>.tsv
    ├── regression/                     # Regression suite for epic
    │   ├── r-01-<scenario-slug>.yaml
    │   └── r-02-<scenario-slug>.yaml
    └── e2e-runs/                       # Test logs & checkpoint.json
        └── issues/                     # Auto-generated defect reports
```

### Folder Naming Rules:
- ❌ **Forbidden (Cryptic):** `s3`, `f3`, `s2s4`, `s8`, `f5`
- ✅ **Standard (Semantic):**
  - `<index>-<feature-domain>`: `01-auth-login`, `02-cart-items`, `03-checkout-payment`, `04-order-history`
  - Or explicit prefixes: `slice-03-checkout-payment`, `fix-01-auth-prompt`

### File Naming Rules:
- Format: `<type>-<index>-<verbatim-intent-slug>.yaml`
- Examples:
  - `ac-01-submit-disabled-when-empty.yaml`
  - `ac-02-coupon-code-validation.yaml`
  - `r-05-removing-last-item-disables-checkout.yaml`
- Internal helper flows must start with an underscore `_` (e.g. `_seed_order.yaml`) so they are not executed as standalone tests.

`<RUN>` = `<TICKET>` when there is a ticket, else `yyMMdd-<kebab-slug>` (SKILL.md, "Run folder").

## Code-First ID Extraction (Static First, Dynamic Fallback)

Reading source code to extract IDs is **10× faster** than querying an emulator and costs **~0 device tokens**:

1. **Priority #1 — Static Source Code Scan (~90% of cases):**
   Run `python3 skills/test-author/scripts/extract-selectors.py [path] -k "<keyword>"` (or grep `res/layout/*.xml` for `android:id="@+id/..."` and `*.kt` for `Modifier.testTag(...)`).
   - **Found IDs in Code?** → Write the `.yaml` flow files immediately using the extracted bare IDs (`id: "<resource-id>"`) and resolved `strings.xml` text.
2. **Priority #2 — Dynamic Device Fallback (Only when static scan misses or SDUI):**
   Only when selectors are not in source code (Server-Driven UI, WebView, system dialogs) or a static selector fails at runtime:
   - Reach the screen and run `python3 skills/test-runner/scripts/device.py nodes [substr]` to dump runtime IDs once.
   - Write/update the `.yaml` flow file with the discovered ID.
3. **Execute in One Continuous CLI Pass (`suite-runner.py`):**
   Validate with `python3 skills/test-author/scripts/validate-flow.py .maestro/<RUN>/` and hand off to `python3 skills/test-runner/scripts/suite-runner.py .maestro/<RUN>/ -m step`.

## One flow = one acceptance line

```yaml
# <RUN> AC-n — PRD §<section>: <the acceptance line, verbatim>
appId: com.example.app
name: "AC-n <the line as a sentence>"
---
- launchApp:
    clearState: false          # keep the session the emulator is already signed in with
- runFlow: ../_nav/<screen>.yaml
- tapOn:
    id: "<resource-id>"        # id first (bare XML id or Compose testTag); text only when the node has no id
- assertVisible:
    id: "<resource-id>"
- assertNotVisible:
    text: "<what the PRD says must not show>"
- echo: "AC-n: <the line as a sentence> - verified"
```

Rules:
- **Select by id.** XML views: the bare `android:id` name (e.g. `btn_submit` — avoids hardcoded flavor package prefixes). Compose: the `Modifier.testTag` string, verbatim (requires `testTagsAsResourceId = true`). On a Compose row the id sits on the tappable node and the label on its child: tap by id, assert the label by text.
- **Every flow cites `PRD §n`** in its header. When the PRD moves, grep `.maestro/` for that `§`.
- **Assert what the line claims, nothing else.** Extra assertions are extra failures to triage.
- **Never type credentials.** Flows assume an already signed-in emulator. Signed out → stop with
  `BLOCKED` (see SKILL.md, "When something is missing") so the user signs in by hand.
- **No `takeScreenshot` in flows**, and no `take_screenshot` calls while passing — an image only for a failure.
- A screen reachable only through a long tap path: write the path once in `_nav/`, never inline.

## Execution & Debugging

- **Standard Execution (Always Preferred):** Run authored YAML files in one continuous pass via `suite-runner.py`:
  ```bash
  python3 skills/test-runner/scripts/suite-runner.py .maestro/<RUN>/ -m step
  ```
- **Fallback Interactive Debugging (Maestro MCP):** Only when fixing a stubborn single flow where static selectors and `suite-runner.py` failure logs aren't enough, you may test inline steps with MCP `run` (`device_id` from `list_devices`), then persist to `.maestro/<RUN>/ac-<n>.yaml` and re-verify via `suite-runner.py`.
