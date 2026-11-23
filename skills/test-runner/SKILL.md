---
name: test-runner
description: "Device automation for Android — verifies PRD behavior, runs regression suites, and checks Figma design specs on device. Supports high-volume test suites (~270 items) with real-time live terminal monitoring, instant defect logging, and state reset. Use when verifying a step, running regression, testing on emulator, or when the user says '/test-runner', 'verify on device', 'run regression', 'test PROJ-123'."
argument-hint: "<target> [-m repro|step|regression|smoke] [--filter <tag>] [--fail-fast [N]]"
model: sonnet
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Bash(python3 skills/test-runner/scripts/*)
  - Bash(python3 skills/test-author/scripts/*)
  - Bash(~/Library/Android/sdk/platform-tools/adb *)
  - Bash(adb *)
  - Bash(claude mcp list *)
  - ToolSearch
  - AskUserQuestion
  - Bash(git apply *)
  - Bash(git status --short *)
  - mcp__maestro__list_devices
  - mcp__maestro__inspect_screen
  - mcp__maestro__run
  - mcp__maestro__cheat_sheet
  - mcp__maestro__take_screenshot
  - Bash(./gradlew assembleDebug *)
  - Bash(./gradlew assemble*Debug *)
  - Bash(./gradlew :app:assemble*Debug *)
  - Bash(./gradlew :app:installDevDebug *)
---

# E2E Test Automation — PRD Behavior + Figma Look + Regression on Device

The unified test automation system for Android development and QC:
1. **First-Time AC Authoring (`/test-author`):** Proves ACs live via Maestro MCP (`inspect_screen` + `run`), registers any random app overlays in `.maestro/_shared/popups.json`, and freezes standalone `.yaml` flows.
2. **High-Speed Suite & Regression Runner (`suite-runner.py`):** Executes frozen flows or full regression (~270 items) with real-time live terminal monitoring, safe overlay recovery, `LIKELY_CAUSE` triage, and state reset.
3. **Design Verification (`design`):** Measures exact screen metrics (dp, padding, colors) against Figma specs using `device.py check`.

| Mode | Answers | Tool | Re-run cost |
|---|---|---|---|
| `behavior` (first pass) | Does it do what the PRD says? | `/test-author` (MCP Prove-First + Freeze) | Frozen to YAML for 0-token re-runs |
| `design` | Does it look like Figma? | `device.py check` — Figma numbers vs measured dp/colours | a table, only diffs need eyes |
| `regression` / `step` | Do frozen flows still pass? | `suite-runner.py` — native CLI execution with live monitor | ~0 tokens |

---

## 🛑 ROUTING POLICY — EXISTING FLOWS VS FIRST-TIME ACs

**RULE #1 (MANDATORY):**
- **When frozen `.yaml` flows already exist** (regression, post-fix re-run, Gate 3 before MR): **DEFAULT TO CALLING `suite-runner.py` IMMEDIATELY**:
  ```bash
  python3 skills/test-runner/scripts/suite-runner.py <target> [options]
  ```
- **When NO `.yaml` flows exist yet** (first time testing ACs, or `suite-runner.py` reports `No valid YAML flows found`): **DO NOT** write blind YAML flows from source code or run manual `adb shell input tap` loops. Invoke **`/test-author`** (Prove-First via Maestro MCP → Freeze to YAML).

*(Note: `suite-runner.py` automatically initializes background token usage tracking and exports a report upon completion).*

`suite-runner.py` automatically resolves targets (e.g. `plans/<EPIC>/PLAN.md`, `plans/<TICKET>/regression-plan.md`, or `<TICKET>` resolves directly to `.maestro/<TICKET>/regression`).

### Mapping User Prompts Directly to `suite-runner.py`:
| User Request | Immediate Action Executed |
|---|---|
| `repro bug PROJ-123` or `verify repro` | `python3 skills/test-runner/scripts/suite-runner.py plans/<TICKET>/flow-bug.md -m repro` |
| `verify @plans/.../PLAN.md` or `regression-plan.md` | `python3 skills/test-runner/scripts/suite-runner.py plans/<EPIC>/PLAN.md -m regression` |
| `verify @plans/... about <topic>` | `python3 skills/test-runner/scripts/suite-runner.py plans/<EPIC>/PLAN.md -m regression --filter "<topic>"` |
| `verify r-1.yaml` (or any single flow) | `python3 skills/test-runner/scripts/suite-runner.py .maestro/<EPIC>/regression/r-1.yaml` |
| `test PROJ-123` or `verify step-03` | `python3 skills/test-runner/scripts/suite-runner.py .maestro/<EPIC>/<step_folder>/ -m step` |
| `run smoke tests` | `python3 skills/test-runner/scripts/suite-runner.py .maestro/<EPIC>/ -m smoke` |

### 🔒 Multi-Agent Device Isolation & Decoupled Build/Install:
When running multiple agents in parallel on 1 Mac with 2+ Emulators:
1. **Never run raw `./gradlew install...` without `ANDROID_SERIAL`**: Gradle broadcasts APKs across all active emulators, colliding with concurrent agent runs. The mechanical guard `pre-tool-guard.py` will block this immediately (<20ms).
2. **Decouple Build and Install**:
   - **Step 1 (Build)**: Run `./gradlew assembleDebug` (or `python3 scripts/gradle-build.py assembleDebug` inside `.worktrees/` to serialize builds via OS `flock`). Pure artifact compile, zero emulator interaction.
   - **Step 2 (Install & Verify)**: Run `suite-runner.py` with `--install`:
     ```bash
     python3 skills/test-runner/scripts/suite-runner.py <target> -m step --install
     ```
   `suite-runner.py` acquires an exclusive mutex lock on an available emulator first, sets `ANDROID_SERIAL=<locked_device_id>`, installs the APK exclusively to that emulator, and runs tests in complete isolation.

### ⛔ Strict Prohibitions (Zero Token Bleed & Live Terminal Enforcement):
- **DO NOT** pass `--headless` or `--no-terminal` unless the user **explicitly typed** `--headless`, `--no-terminal`, or `headless` in their prompt. By default, `suite-runner.py` opens the external macOS Terminal window (`--open-terminal`) for live visual monitoring and **block-waits** until completion (returning the child exit code and printing the final summary + failure digest paths directly).
- **DO NOT** poll `progress.log` in a loop (set a generous command timeout such as 600s, or run in background with reactive wakeup for large suites).
- **DO NOT** inspect screens (`inspect_screen` or `device.py nodes`) before running existing flows.
- **DO NOT** execute manual `adb shell input tap` or `adb shell uiautomator dump` (and never call `uiautomator dump` while Maestro MCP is active — Maestro holds UiAutomation so it always fails).
- **DO NOT** copy folders or rewrite `.yaml` flow files line by line.
- **DO NOT** run individual flows through sequential MCP calls.
Let `suite-runner.py` run natively. It handles execution, terminal streaming, failure digest generation, defect logging, and state reset with **0 token waste**.

### Only When `suite-runner.py` Completes (1-Read Debug Budget):
- **If all tests PASS (✅):** Report the summary table printed by `suite-runner.py` and finish immediately.
- **If a test FAILS (❌):** Read the single-file **`debug/digest_<ac>_<ts>.md`** first (printed in stdout and linked inside `issues/NN-<slug>.md`) — it already contains `LIKELY_CAUSE`, focus window, Maestro error, failing flow YAML, prioritized visible UI nodes, and filtered logcat. Do **not** separately read raw `hierarchy.xml` + `logcat.txt` + `.yaml` unless the digest is missing an element.
  - **`BLOCKED_BY_OVERLAY`:** Runner detected a random app/system overlay (user guide, promo, rating, etc.) and skipped creating a false bug report. Use **at most 1–2 MCP calls** (`inspect_screen` once → dismiss), add a specific rule (`when_visible` + `actions`) to `.maestro/_shared/popups.json`, and resume with `suite-runner.py <target> --resume --no-reset`.
  - **`SELECTOR_NOT_FOUND`:** Check the digest's visible UI nodes first; if live confirmation is needed, use **at most 1–2 MCP calls** (`inspect_screen`), update the YAML selector, and resume with `--resume --no-reset` (or `--resume`).
  - **`ASSERTION_FAILED` / `APP_CRASH_OR_ANR`:** Genuine app defect candidate. Cite the digest and generated `issues/NN-<slug>.md` to report or fix.

### When No Flows Exist or When Authoring New Tests:
- If `suite-runner.py` reports `No valid YAML flows found`, **STOP IMMEDIATELY**.
- **DO NOT** attempt manual `adb shell input tap` loops or blind YAML authoring.
- Use `/test-author <target>` (Prove-First via Maestro MCP → Freeze to `.yaml`) to create and prove the flows first.

---

## Token budget — non-negotiable

Measured on a real run: 91% of all input was the session's **earlier work re-read on every call**
(347k of context × 51 calls); the test itself added ~35k. So the two levers are, in order: start
from an empty session, and make fewer calls. Output size matters far less.

1. **Prefer a fresh session.** In an old one every call re-reads its history; `token-usage.py start` (§0) warns, and the run goes on.
2. **Never read a plan, PRD or Figma page whole.** Lines: `scripts/extract-acceptance.sh`. PRD: grep the `§` a line cites. Figma: cache first, then one frame node (see `references/design-spec.md`).
3. **Do not author flows blindly from source code.** For new ACs without frozen flows, use `/test-author` (Prove-First via Maestro MCP `inspect_screen` once per new screen + batched `run` → freeze YAML). Only fall back to `extract-selectors.py` / `Grep` when MCP is unavailable or a view lacks runtime IDs.
4. **No full-screen images, ever.** Not `take_screenshot`, not `adb screencap` + `Read`. The only image allowed is `device.py crop <id>` of a node on a ✗ row.
5. **One shell call per screen-state change.** Chain every `adb` command a state needs (`am start`, `input`, `logcat | grep`) into a single Bash call.
6. **1-read debug & single-pass execution.** Run frozen flows in one pass via `suite-runner.py` (which block-waits and prints the summary directly). On failure, read `debug/digest_<ac>_<ts>.md` in 1 call before touching raw XML/logcat or calling MCP. Gradle: `| tail -3`.
7. **`cheat_sheet` is long — at most once per session**, and only when `references/maestro-flow.md` does not cover the command you need. Never call it "to be safe".
8. **Never use the cloud tools** (`run_on_cloud`, `list_cloud_devices`, …): they upload the app to an external service.
9. **Load a reference only for the mode you are in** (`maestro-flow.md` / `design-spec.md`), and `issue-report-template.md` only once an app defect is confirmed.
10. **Reuse before writing.** `_nav/<screen>.yaml` and `design/<screen>.tsv` that already exist are run, not rewritten. Rewrite only what a failure points at.
11. **Batch runs (> 2 flows): always use `suite-runner.py`.** Never call MCP `run` sequentially in a loop for multiple flows; use `suite-runner.py` for speed, zero token cost, and real-time live monitoring.

---

## 0 · Preconditions (stop with BLOCKED if any fails — do not work around)

- **First command of the run**, before any read or device call:
  `python3 skills/test-runner/scripts/token-usage.py start`
  If it prints `WARNING: old session`, keep going, and put that line first in the output's Tokens section.

Then, in this order:
1. `~/Library/Android/sdk/platform-tools/adb devices` shows exactly one device.
2. App built from this branch: `./gradlew <installDebugTask> | tail -3` (auto-detect variant from `app/build.gradle*`, default `:app:installDevDebug` or `:app:installDebug`).
3. Maestro tools: Verify `list_devices` returns the emulator; keep its `device_id`.
4. **Emulator auth state (Context-aware):**
   - **Default:** Expects a signed-in test account.
   - **Testing Auth / Logged-out / Guest flows:** Allowed to proceed signed out (e.g., verifying onboarding, login UI, or logged-out empty states).
   - **Signed out when login is required:** If an automated helper flow exists (e.g., `_shared/_login-user.yaml`), run it to authenticate automatically. Only stop with `BLOCKED` if no helper exists and the feature cannot be reached without an account.
   - **Security guardrail:** **Never invent arbitrary credentials or click "Create Account"** to register new accounts.

---

## Data — real first, mock only with the user's yes

The default is a **real test**: the app as built from this branch, talking to the real backend, on
the data the signed-in test account already has. No source is touched.

**When a line needs data the account does not have** (a state the backend cannot produce yet, or
one the account lacks), do not patch anything on your own. Collect every such line first, then ask
**once per run** with `ask_question`, naming the lines and the state each needs:
- **Mock it** — apply `.maestro/<RUN>/fixture-override.patch`, `./gradlew :app:installDevDebug | tail -3`, run those lines, then `git apply -R` and reinstall.
- **I'll prepare the data** — mark those lines ⚠️ Not verified ("needs data: …") and run the rest.
- **Skip** — mark them ⚠️ Not verified ("skipped by user").

---

## 1 · Lines

```bash
skills/test-runner/scripts/extract-acceptance.sh <step-file>
```
For each `AC-n`, classify once: **behavior**, **design**, or **not on device** (pure rule, time zone, process death, backend).

---

## 2 · Authoring New Flows (Hand Off to `/test-author`)

When ACs have no frozen `.yaml` files yet, do **not** author flows blindly from source code inside `test-runner`. Invoke `/test-author`:
1. Prove each AC live via Maestro MCP (`inspect_screen` once per new screen + batched `mcp__maestro__run`).
2. Record any random app overlay encountered into `.maestro/_shared/popups.json`.
3. Freeze standalone `ac-NN-<slug>.yaml` files (with `launchApp` / `_nav/` preconditions) and validate with `validate-flow.py`.
4. Do not re-run `suite-runner.py` in the same session if ACs just passed via MCP; use `suite-runner.py` in a fresh session for regression or Gate 3.

---

## 2b · Regression & Suite Runner Mode (`regression <EPIC>` or multi-flow runs)

**Trigger:** When running regression cases (e.g. `plans/<EPIC>/PLAN.md` or `plans/<TICKET>/regression-plan.md`), checking a folder of flows (`.maestro/<RUN>/regression/`), or verifying multiple steps:

### Run via `suite-runner.py`:
```bash
python3 skills/test-runner/scripts/suite-runner.py <flow_directory_or_ticket> [options]
```

### Streamlined Mode Presets (`-m / --mode`):
Instead of remembering disparate flags, choose the preset matching your goal:
- `-m repro`: Runs repro flows (`--filter repro`, `--fail-fast 1`, live terminal with block-wait).
- `-m step`: Verifies all flows in a feature step (`RUN ALL` by default so every failure surfaces in one pass; add `--fail-fast 1` explicitly if desired; live terminal with block-wait).
- `-m regression`: Runs entire suite (`--resume`, live terminal with block-wait).
- `-m smoke`: Runs fast smoke suite (`--filter @smoke`, `--fail-fast 1`, live terminal with block-wait).

### Core Options (Most runs only need `-m` and `--install`):
- `--install [APK_PATH]`: Locks an available emulator and installs the debug APK exclusively to it.
- `--resume`: Resumes from `checkpoint.json` (skips passed flows).
- `--filter <tag_or_keyword>`: Filters flows by keyword or tag.
- `--fail-fast [N]`: Stops execution after N failures (default 1).
- `--device <id>`: Targets a specific ADB device ID.
- `--no-reset`: Skips `force-stop` between flows (useful when resuming after dismissing a session overlay).
- `--headless`: **Use only when explicitly requested in prompt** (blocked by `pre-tool-guard.py` and `suite-runner.py` if agent adds it unrequested).

### What `suite-runner.py` handles automatically:
1. **Configuration Transparency:** Prints `⚙️ SUITE CONFIGURATION` banner displaying active Mode, Terminal, Fail-Fast, and Filter.
2. **Auto Token Tracking:** Automatically runs background token usage tracking and writes report upon suite completion.
3. **Preflight Health Checks:** Verifies device connection, app package installation, required tokens, and GPS before running. Fails immediately with actionable instructions if anything is missing (0 token waste).
4. **Step Titles & Progress Streaming:** Automatically extracts semantic step names from folder paths (`03: Checkout Payment`, `Regression Suite`) and streams live progress.
5. **Robust Pass/Fail Parsing:** Immune to runner logging crashes during exit. If assertions passed, it will not register a false FAIL.
6. **Zero-Evidence-Loss Defect Logging & 1-Read Digest:** On failure, captures screenshot via ADB binary stream + device fallback, dumps UI hierarchy XML, slices logcat, generates a compact 1-read `debug/digest_<ac>_<ts>.md` (prioritized visible nodes + filtered logcat + flow YAML + `LIKELY_CAUSE`, PII-redacted), and writes `issues/NN-<slug>.md` (skipped on `BLOCKED_BY_OVERLAY`).
7. **App State Isolation:** Automatically executes `adb shell am force-stop` and relaunches the app between flows to prevent popup leakage and cascading failures.
8. **Summary & Checkpoint:** Records results in `checkpoint.json` and outputs a clean Markdown summary table.

---

## 3 · Design mode

1. Read `references/design-spec.md`. Write or reuse `.maestro/<RUN>/design/<screen>.tsv`.
2. Put the screen in the state the Figma frame draws, then:
   ```bash
   python3 skills/test-runner/scripts/device.py check .maestro/<RUN>/design/<screen>.tsv
   ```
3. For each ✗ only: `device.py crop <id> app/build/test-runner/<id>.png`, inspect, and classify whether build or Figma spec is wrong.

---

## 4 · Report each app defect

Only confirmed **app** defects get a report. One defect per file in `<PLAN>/issues/NN-<slug>.md`.
Format: exactly `skills/test-runner/issue-report-template.md`:
- **Title:** `[Android] <observable defect>`
- **Summary:** 1–3 sentences describing what is wrong and which PRD/AC it contradicts.
- **Steps to reproduce:** Plain human interaction steps from a fresh launch.
- **Expected result:** Citation of PRD/AC/Figma.
- **Actual result:** Exact observed assertion failure + crop/screenshot path.

---

## 5 · Final Output

Rendered markdown (never in a code block):
- Verdict heading: `✅ Passed · ❌ Defect · ⚠️ Not verified · ➖ Not on device`.
- Table listing Step, AC, Title, Result, Duration, and Issue/Evidence link.
- Tokens usage section: the lines after `🪙 Token usage:` in the runner's progress log, then a
  link to the `<YYMMDD-HHMM>-token-usage.md` next to its `📊 Summary report:`. The runner writes it
  at suite end, cut off at that moment. Without the runner, the run ends with:
  ```bash
  python3 skills/test-runner/scripts/token-usage.py report <PLAN>/e2e-runs/<YYMMDD-HHMM>-token-usage.md
  ```
  A run that never got its report: add `--until <suite end, ISO UTC>` so later work isn't counted.
  Never write token numbers yourself — no report, no numbers ("token report not written: <reason>").

---

## Gotchas (Android / Maestro-specific)

- **`assertNotVisible` hides brief screens**: it retries until the element is gone, so it passes over a screen that showed for a second; to prove something never appears, poll a fixed window (`repeat` → `runFlow when visible` → failing `assertTrue`, then `waitForAnimationToEnd: {timeout: 500}`). Maestro reads the view tree, so a view under an overlay still counts as visible.
- **`launchApp` outlasts short first screens**: it waits for the app to settle, so a splash or loader of 1–2 s is often gone before the next step; make the screen stay (`setAirplaneMode`, a fixture, a paused loader) and reset it in `onFlowComplete`.
- **`killApp` doesn't kill a foreground app**: for a cold start or process death run `adb shell am force-stop <pkg>` before the flow and confirm a new pid (`Start proc` in logcat).
- **Developer options need the Settings UI**: `settings put global always_finish_activities 1` is stored but not applied by the running system; toggle "Don't keep activities" in Developer options (Maestro on `com.android.settings`, `scrollUntilVisible ".*keep activities.*"`) and confirm `onActivityDestroyed` on Home in logcat.
- **Two devices connected**: pass `--device` to `suite-runner.py`, `device_id` to Maestro and `ANDROID_SERIAL` to Gradle, or steps can land on different devices.
- **Installed app newer than the branch**: `installDevDebug` fails with `INSTALL_FAILED_VERSION_DOWNGRADE` and `adb install` of the APK path is hook-blocked; add `--init-script` with a scratchpad script setting `android.installation.installOptions = ['-d','-r']` on the app project (keeps sign-in, no repo edit). A branch and its base can share a version code, so record the git SHA and install time.
- **Emulator network drops**: a launch showing "No internet connection" is the emulator, not the app; check `adb shell ping` before a run and recover with `svc wifi disable && svc wifi enable`.
- **`--open-terminal` block-waits until completion**: the runner opens/reuses the external Terminal window and blocks until the suite finishes (or the Terminal closes), then prints the final summary, failed `digest_*.md` paths, and token line directly. Do **not** poll `progress.log`; use a generous command timeout (e.g., 600s) or background execution with completion wakeup for large regression suites.
- **Never run `adb shell uiautomator dump` while Maestro MCP is active**: Maestro holds Android's `UiAutomation` service so `uiautomator dump` always fails; use `mcp__maestro__inspect_screen` instead.
- **Labels don't reach the MCP result**: make a precondition and the check fail with different messages (text selector vs id) so a failure can be attributed.
