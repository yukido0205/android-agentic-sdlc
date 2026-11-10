---
name: test-runner
description: "Device automation for Mobile (Android & iOS) — verifies PRD behavior, runs regression suites, and checks design specs on device/simulator. Supports high-volume test suites with real-time live terminal monitoring, instant defect logging, and state reset. Use when verifying a step, running regression, testing on device/simulator, or when the user says '/test-runner', 'verify on device', 'run regression'."
argument-hint: "<target> [-m repro|step|regression|smoke] [--filter <tag>] [--fail-fast [N]]"
model: sonnet
allowed-tools:
  - Read
  - Edit
  - Write
  - Grep
  - Glob
  - Bash(python3 skills/test-runner/scripts/*)
  - Bash(~/Library/Android/sdk/platform-tools/adb *)
  - Bash(adb *)
  - Bash(xcrun simctl *)
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
  - Bash(./gradlew :app:installDevDebug *)
---

# E2E Test Automation — PRD Behavior + Regression on Mobile (Android & iOS)

The unified test automation system for Mobile development and QC:
1. **Single-Step Authoring & Verification (`behavior`):** Author and verify flows for a single step/ticket using Maestro MCP and device nodes.
2. **High-Speed Suite & Regression Runner (`regression` / `suite`):** Execute multi-flow suites or full regression via platform-native runners with real-time live terminal monitoring, instant defect logging, and state reset:
   - **Android**: `skills/test-runner/scripts/suite-runner.py`
   - **iOS**: `skills/test-runner/scripts/suite-runner-ios.py`
3. **Design Verification (`design`):** Measure exact screen metrics against Figma specs.

| Mode | Answers | Tool | Re-run cost |
|---|---|---|---|
| `behavior` | Does it do what the PRD says? | Maestro MCP — one flow file per acceptance line | ~0 — read pass/fail |
| `design` | Does it look like Figma? | `device.py check` — Figma numbers vs measured dp/colours | a table, only diffs need eyes |
| `regression` | Does the epic meet its PRD edge cases? | `suite-runner.py` (Android) / `suite-runner-ios.py` (iOS) — native CLI execution | ~0 tokens |

---

## 🛑 UNIVERSAL DEFAULT ENTRYPOINT — RUNNER-FIRST POLICY

**RULE #1 (MANDATORY & NON-NEGOTIABLE):**
Unless the user explicitly asks to *author/write a brand new test file from scratch*, **EVERY request to test, verify, run, check, or validate on device/simulator MUST DEFAULT TO CALLING THE NATIVE RUNNER IMMEDIATELY**:

- **For Android Projects:**
  ```bash
  python3 skills/test-runner/scripts/suite-runner.py <target> [options]
  ```
- **For iOS Projects:**
  ```bash
  python3 skills/test-runner/scripts/suite-runner-ios.py <target> [options]
  ```

*(Note: `suite-runner.py` automatically initializes token usage tracking ngầm và xuất báo cáo khi hoàn thành).*

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

### ⛔ Strict Prohibitions (Zero Token Bleed):
- **DO NOT** inspect screens (`inspect_screen` or `device.py nodes`).
- **DO NOT** execute manual `adb shell input tap` or uiautomator dumps.
- **DO NOT** copy folders or rewrite `.yaml` flow files line by line.
- **DO NOT** run individual flows through sequential MCP calls.
Let `suite-runner.py` run natively. It handles execution, terminal streaming, defect logging, and state reset with **0 token waste**.

### Only When `suite-runner.py` Completes:
- **If all tests PASS (✅):** Report the summary table and finish immediately.
- **If a test FAILS (❌):**
  - Runner has ALREADY created `issues/NN-<slug>.md`, captured the screenshot, and dumped UI hierarchy XML.
  - ONLY THEN does the AI Agent read the issue file and failure evidence to explain the cause or propose a fix.

### When No Flows Exist or When Authoring New Tests:
- If `suite-runner.py` reports `No valid YAML flows found`, **STOP IMMEDIATELY**.
- **DO NOT** attempt manual exploratory testing (`inspect_screen`, `adb shell input tap`).
- **DO NOT** write improvised YAML flows inside a verification session.
- Instruct the user to use the dedicated authoring skill:
  > *"No Maestro test flows found for this target. Please invoke `/test-author <target>` to generate the test flows before running verification."*

---

## Token budget — non-negotiable

Measured on a real run: 91% of all input was the session's **earlier work re-read on every call**
(347k of context × 51 calls); the test itself added ~35k. So the two levers are, in order: start
from an empty session, and make fewer calls. Output size matters far less.

1. **Prefer a fresh session.** In an old one every call re-reads its history; `token-usage.py start` (§0) warns, and the run goes on.
2. **Never read a plan, PRD or Figma page whole.** Lines: `scripts/extract-acceptance.sh`. PRD: grep the `§` a line cites. Figma: cache first, then one frame node (see `references/design-spec.md`).
3. **Read a screen with `device.py nodes [substr]`, not `inspect_screen`.** It prints one line per usable node — `id | text | x,y wxh dp | flags` — about 8× smaller than `inspect_screen` on the same screen (measured: 1.1k vs ~8.4k characters). Pass a substring to print only matching rows. Once per screen state; again only after an action changed the screen and only for an id you do not have yet. `inspect_screen` only when you need the parent/child tree.
4. **No full-screen images, ever.** Not `take_screenshot`, not `adb screencap` + `Read`. The only image allowed is `device.py crop <id>` of a node on a ✗ row.
5. **One shell call per screen-state change.** Chain every `adb` command a state needs (`am start`, `input`, `logcat | grep`) into a single Bash call.
6. **Explore with inline YAML, persist once.** Try steps with `run` + `yaml`, several commands per call rather than one call per tap; write the `.yaml` file only when the sequence works (`run` validates syntax, no separate check). Gradle: `| tail -3`.
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

## 2 · Behavior mode (Single Step Authoring & Verification)

Use this when writing new test flows for a step:
1. Read `references/maestro-flow.md` for the **semantic naming conventions**.
2. **Never use cryptic folder names** (`s3`, `f3`, `s2s4`). Structure folders descriptively:
   - Feature folder: `.maestro/<RUN>/<index>-<feature-domain>/` (e.g. `.maestro/<TICKET>/03-checkout-payment/`)
   - Flow file: `ac-<index>-<verbatim-behavior-slug>.yaml` (e.g. `ac-01-submit-disabled-when-empty.yaml`)
3. Reach the screen (reuse `_nav/<screen>.yaml` via `run` + `files`), then `device.py nodes` to get element ids.
4. Try the line's steps with `run` + inline `yaml`. When they pass, write the `.yaml` flow file.
   Header must include: `# AC-n: <short title> — PRD §n`. Optional tags: `@smoke`, `@regression`.
   Log the progress to chat immediately: `<title> - verified - <n>/<total>`.
5. Run the flows. When testing > 2 flows, switch to `suite-runner.py` (§2b) to avoid context bloat.

---

## 2b · Regression & Suite Runner Mode (`regression <EPIC>` or multi-flow runs)

**Trigger:** When running regression cases (e.g. `plans/<EPIC>/PLAN.md` or `plans/<TICKET>/regression-plan.md`), checking a folder of flows (`.maestro/<RUN>/regression/`), or verifying multiple steps:

### Run via `suite-runner.py`:
```bash
python3 skills/test-runner/scripts/suite-runner.py <flow_directory_or_ticket> [options]
```

### Streamlined Mode Presets (`-m / --mode`):
Thay vì phải nhớ nhiều cờ rời rạc, sử dụng preset tương ứng với mục đích:
- `-m repro`: Chạy repro flows (`--filter repro`, `--fail-fast 1`, in-process).
- `-m step`: Xác minh step tính năng mới (`--fail-fast 1`, live terminal).
- `-m regression`: Chạy toàn bộ suite (`--resume`, live terminal).
- `-m smoke`: Chạy smoke tests nhanh (`--filter @smoke`, `--fail-fast 1`, live terminal).

### Granular Override Options (Quyền ưu tiên cao nhất ghi đè Preset):
- `--headless`, `--no-terminal`: Chạy trực tiếp trong shell hiện tại (không mở cửa sổ Terminal mới).
- `--open-terminal`: Mở cửa sổ macOS Terminal live streaming (mặc định với regression/step).
- `--filter <tag_or_keyword>`: Lọc case theo từ khóa hoặc tag (ghi đè filter của preset).
- `--fail-fast [N]`: Dừng sớm sau N failures (mặc định 1).
- `--resume`: Tiếp tục từ `checkpoint.json` (bỏ qua case đã PASS).
- `--require-env <vars>`: Danh sách env token bắt buộc (e.g. `API_AUTH_TOKEN`).
- `--mock-gps <lat,lon>`: Mock toạ độ GPS (e.g. `37.4220,-122.0841`).
- `--device <id>`: ADB device ID khi có nhiều hơn 1 device.
- `--no-reset`: Bỏ qua force-stop/relaunch giữa các test.
- `--skip-preflight`: Bỏ qua kiểm tra preflight môi trường.

### What `suite-runner.py` handles automatically:
1. **Configuration Transparency:** In banner `⚙️ SUITE CONFIGURATION` hiển thị rõ Mode, Terminal, Fail-Fast, và Filter đang áp dụng.
2. **Auto Token Tracking:** Tự động start token tracking ngầm và xuất báo cáo khi hoàn thành suite.
3. **Preflight Health Checks:** Verifies device connection, app package installation, required tokens, and GPS before running. Fails immediately with actionable instructions if anything is missing (0 token waste).
4. **Step Titles & Progress Streaming:** Automatically extracts semantic step names from folder paths (`03: Checkout Payment`, `Regression Suite`) and streams live progress.
5. **Robust Pass/Fail Parsing:** Immune to runner logging crashes during exit. If assertions passed, it will not register a false FAIL.
6. **Zero-Evidence-Loss Defect Logging:** On failure, captures screenshot via ADB binary stream + device fallback, dumps UI hierarchy XML for selector debugging, slices logcat, and generates `issues/NN-<slug>.md` immediately.
7. **App State Isolation:** Automatically executes `adb shell am force-stop` and relaunches the app between flows to prevent popup leakage and cascading failures.
8. **Summary & Checkpoint:** Records results in `checkpoint.json` và xuất báo cáo Markdown summary table.

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
- **`--open-terminal` returns at once**: the run continues in the Terminal window; wait on its progress log (`e2e-runs/<YYMMDD-HHMM>-progress.log`) for the `🏁 COMPLETED` line, which the runner writes after the summary and token report.
- **Labels don't reach the MCP result**: make a precondition and the check fail with different messages (text selector vs id) so a failure can be attributed.
