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
    id: "<resource-id>"        # id first; text only when the node has no id
- assertVisible:
    id: "<resource-id>"
- assertNotVisible:
    text: "<what the PRD says must not show>"
- echo: "AC-n: <the line as a sentence> - verified"
```

Rules:
- **Select by id.** XML views: the bare `android:id` name. Compose: the test tag, verbatim — see
  `.claude/references/compose-test-tags.md`. On a Compose row the id sits on the tappable node and
  the label on its child: tap by id, assert the label by text.
- **Every flow cites `PRD §n`** in its header. When the PRD moves, grep `.maestro/` for that `§`.
- **Assert what the line claims, nothing else.** Extra assertions are extra failures to triage.
- **Never type credentials.** Flows assume an already signed-in emulator. Signed out → stop with
  `BLOCKED` (see SKILL.md, "When something is missing") so the user signs in by hand.
- **No `takeScreenshot` in flows**, and no `take_screenshot` calls while passing — an image only for a failure.
- A screen reachable only through a long tap path: write the path once in `_nav/`, never inline.

## Run (Maestro MCP)

Every call takes the `device_id` from `list_devices`. `run` takes exactly one of `yaml`, `files`, `dir`.

- Explore: `run` with `yaml` (inline) — nothing written to disk until it works.
- One flow while fixing: `run` with `files: [".maestro/<RUN>/ac-<n>.yaml"]`.
- The whole step: `run` with `dir: ".maestro/<RUN>"`. `_nav/` lives outside it, so it is never
  run as a test on its own.
- Syntax is validated by `run` itself; there is no separate check.
- Out of an MCP session (CI, a human): `maestro test .maestro/<RUN>/` runs the same files.
