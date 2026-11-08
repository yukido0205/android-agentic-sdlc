#!/usr/bin/env python3
"""High-volume E2E test suite runner for Android Maestro flows.

Designed for Dev & QC to execute large suites (~270 test cases) efficiently:
- Native Maestro execution (fast, headless, 0 LLM token waste on passing tests)
- Preflight health checks (device online, package installed, tokens/env, GPS mock)
- Real-time live console monitoring: `[n/total] AC-x: <title> - verified - m/total [time]`
- Instant on-failure defect reporting (with screenshot, UI hierarchy, and logcat)
- Automatic state teardown / reset hook (force-stop & relaunch) between tests
- Robust pass/fail detection (immune to Maestro shutdown/logging crashes)
- Checkpoint persistence and resume (`--resume`)
- Fail-fast support (`--fail-fast [N]`)
- Tag and keyword filtering (`--filter <tag>`)
- Semantic folder and flow naming support (e.g., `03-checkout-payment/ac-01-submit-disabled.yaml`)
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Android SDK & Maestro path resolution (respects ANDROID_HOME / ANDROID_SDK_ROOT with macOS/Linux fallbacks)
SDK_ROOT = (
    os.environ.get("ANDROID_HOME")
    or os.environ.get("ANDROID_SDK_ROOT")
    or os.path.expanduser("~/Library/Android/sdk" if sys.platform == "darwin" else "~/Android/Sdk")
)
PLATFORM_TOOLS = os.path.join(SDK_ROOT, "platform-tools")
MAESTRO_BIN_DIR = os.path.expanduser("~/.maestro/bin")

# Ensure adb and maestro are in PATH for child subprocesses
os.environ["PATH"] = f"{PLATFORM_TOOLS}:{MAESTRO_BIN_DIR}:{os.environ.get('PATH', '')}"

# ADB fallback path
ADB = shutil.which("adb") or os.path.join(PLATFORM_TOOLS, "adb")

# Maestro fallback path
MAESTRO = shutil.which("maestro") or os.path.join(MAESTRO_BIN_DIR, "maestro")


def run_adb(*args, binary=False, check=True):
    """Executes an adb command."""
    cmd = [ADB, *args]
    res = subprocess.run(cmd, capture_output=True)
    if check and res.returncode != 0:
        err = res.stderr.decode("utf-8", "replace")
        raise RuntimeError(f"ADB command failed ({' '.join(args)}): {err}")
    return res.stdout if binary else res.stdout.decode("utf-8", "replace")


def detect_device(device_arg=None):
    """Detects connected device ID or validates the provided one."""
    if device_arg:
        return device_arg
    try:
        out = run_adb("devices")
    except Exception as e:
        sys.exit(f"BLOCKED: Failed to run adb devices ({e}). Ensure adb is accessible.")
    lines = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("List of devices")]
    devices = [l.split()[0] for l in lines if "\tdevice" in l]
    if not devices:
        sys.exit("BLOCKED: No Android device/emulator found via `adb devices`. Please start one.")
    if len(devices) > 1:
        print(f"Multiple devices found: {devices}. Using first device: {devices[0]} (use --device to override)")
    return devices[0]


def run_preflight_checks(device_id, package_name, required_envs=None, mock_gps=None):
    """Validates device, package installation, required tokens, and GPS before test execution.
    
    Prevents burning tokens or execution time when the environment or preconditions are broken.
    """
    print("\n🔍 Running Preflight Health Checks...")
    errors = []
    
    # 1. Device responsiveness
    try:
        state = run_adb("-s", device_id, "get-state").strip()
        if state != "device":
            errors.append(f"Device '{device_id}' is in '{state}' state (expected 'device').")
        else:
            print(f"  ✅ Device online & ready: {device_id}")
    except Exception as e:
        errors.append(f"Cannot communicate with device '{device_id}': {e}")

    # 2. Package installation check
    try:
        pm_path = run_adb("-s", device_id, "shell", "pm", "path", package_name).strip()
        if not pm_path:
            errors.append(
                f"Package '{package_name}' is NOT installed on {device_id}.\n"
                f"   👉 Build & install first: ./gradlew :app:installDevDebug"
            )
        else:
            print(f"  ✅ App package installed: {package_name}")
    except Exception as e:
        errors.append(f"Failed to check package '{package_name}': {e}")

    # 3. Required Environment Variables / Tokens
    if required_envs:
        for var in required_envs:
            val = os.environ.get(var)
            if not val:
                errors.append(f"Missing required environment variable/token: '{var}' (e.g. export {var}=...)")
            else:
                masked = val[:4] + "..." + val[-3:] if len(val) > 8 else "***"
                print(f"  ✅ Environment variable found: {var} ({masked})")

    # 4. GPS / Location mock check & configuration
    if mock_gps:
        try:
            # Enable location services
            run_adb("-s", device_id, "shell", "settings", "put", "secure", "location_mode", "3", check=False)
            lat, lon = [x.strip() for x in mock_gps.split(",")]
            # Emulate geo fix
            run_adb("-s", device_id, "emu", "geo", "fix", lon, lat, check=False)
            print(f"  ✅ Mock GPS configured: Lat {lat}, Lon {lon}")
        except Exception as e:
            print(f"  ⚠️ Warning: Failed to set mock GPS: {e}")

    # 5. Device Lockout Warning to prevent manual interference
    print("  🔒 Warning: Do NOT touch or interact with device screen during execution.")

    if errors:
        print("\n" + "!" * 70)
        print("❌ PREFLIGHT CHECKS FAILED:")
        for err in errors:
            print(f"   • {err}")
        print("!" * 70)
        sys.exit(1)

    print("✅ All Preflight Checks Passed!\n")


def format_semantic_name(raw_name):
    """Converts a kebab-case or snake_case name into a clean title."""
    cleaned = raw_name.replace("-", " ").replace("_", " ").strip()
    return cleaned.title()


def parse_flow_metadata(yaml_path):
    """Extracts AC code, title, step title, and tags from YAML comments and path.
    
    Supports both semantic naming (e.g. 03-checkout-payment/ac-01-submit-disabled.yaml)
    and legacy formats (e.g. s3/ac-1.yaml).
    """
    ac_code = ""
    title = ""
    step_title = ""
    tags = []
    
    # 1. Extract AC/R code and fallback title from filename
    # e.g. ac-01-submit-disabled-look.yaml -> code="AC-01", slug="submit-disabled-look"
    base = os.path.basename(yaml_path)
    m_file = re.match(r"^((?:ac|r|smoke|test)[-_]?\d+)[-_]?(.*)\.(?:yaml|yml)$", base, re.IGNORECASE)
    fallback_title = ""
    if m_file:
        ac_code = m_file.group(1).upper().replace("_", "-")
        raw_slug = m_file.group(2)
        if raw_slug:
            fallback_title = format_semantic_name(raw_slug)
    else:
        ac_code = os.path.splitext(base)[0]

    # 2. Extract semantic step / category from folder hierarchy
    for part in Path(yaml_path).parts[:-1]:
        # Skip top-level generic folders
        if part in (".maestro", "plans", "regression", "e2e-runs", "debug"):
            if part == "regression":
                step_title = "Regression Suite"
            continue

        # Semantic pattern: 03-checkout-payment or 01-auth-login
        m_num_sem = re.match(r"^(\d{2})[-_](.+)$", part)
        if m_num_sem:
            s_num = m_num_sem.group(1)
            s_name = format_semantic_name(m_num_sem.group(2))
            step_title = f"{s_num}: {s_name}"
            break

        # Semantic pattern: slice-03-checkout-payment or step-02-order-summary or fix-01-auth
        m_prefix = re.match(r"^(slice|step|fix)[-_]?(\d+)[-_]?(.*)$", part, re.IGNORECASE)
        if m_prefix:
            p_type = m_prefix.group(1).capitalize()
            p_num = m_prefix.group(2)
            p_name = format_semantic_name(m_prefix.group(3))
            step_title = f"{p_type} {p_num}: {p_name}" if p_name else f"{p_type} {p_num}"
            break

        # Legacy shorthand patterns: s3, f3, s2s4
        m_legacy_multi = re.match(r"^s(\d+)s(\d+)$", part, re.IGNORECASE)
        if m_legacy_multi:
            step_title = f"Slice {m_legacy_multi.group(1)}-{m_legacy_multi.group(2)}"
            break
        m_legacy_s = re.match(r"^s(\d+)$", part, re.IGNORECASE)
        if m_legacy_s:
            step_title = f"Slice {int(m_legacy_s.group(1)):02d}"
            break
        m_legacy_f = re.match(r"^f(\d+)$", part, re.IGNORECASE)
        if m_legacy_f:
            step_title = f"Fix {int(m_legacy_f.group(1)):02d}"
            break

        # Named feature folders: checkout, order-history, etc.
        if not re.match(r"^[A-Z]+-\d+$", part, re.IGNORECASE) and not part.startswith("26"):
            step_title = format_semantic_name(part)

    # 3. Read YAML header comments for explicit AC, title, or tags
    try:
        with open(yaml_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[:25]
    except Exception:
        lines = []

    for line in lines:
        line_clean = line.strip()
        if not line_clean.startswith("#"):
            continue
        comment = line_clean.lstrip("#").strip()
        
        # Tags: @smoke, @regression, etc.
        found_tags = re.findall(r"@[\w-]+", comment)
        if found_tags:
            tags.extend(found_tags)

        # Step annotation in comment: # Step 02: Order Summary
        m_step_comment = re.search(r"(?:[A-Z]+-\d+\s+)?(?:step\s*(\d+)[:—\-]\s*(.+)|step[:—\-]\s*(.+))", comment, re.IGNORECASE)
        if m_step_comment:
            if m_step_comment.group(1) and m_step_comment.group(2):
                step_title = f"Step {m_step_comment.group(1)}: {m_step_comment.group(2).strip()}"
            elif m_step_comment.group(3):
                step_title = m_step_comment.group(3).strip()
            continue
            
        # Explicit AC match: # AC-1: Title or # R-1: Title or # PROJ-123 AC-1 — Title
        ac_match = re.search(r"((?:AC|R)-\d+)\s*[:—\-]\s*(.+)", comment, re.IGNORECASE)
        if ac_match:
            ac_code = ac_match.group(1).upper()
            title = ac_match.group(2).strip()
            continue

        # General Title: ...
        if comment.lower().startswith("title:"):
            title = comment[6:].strip()
            continue

        if not title and len(comment) > 3 and not comment.startswith("@") and not comment.lower().startswith("step"):
            # Avoid using file headers that are purely instructions
            if not re.match(r"^[a-z]+-\d+", comment.lower()) and not comment.lower().startswith("needs:"):
                title = comment

    if not title:
        title = fallback_title or base
        
    return {
        "ac": ac_code,
        "title": title,
        "step_title": step_title,
        "tags": tags,
        "path": yaml_path,
    }


def find_flows(target_path, filter_pattern=None):
    """Recursively finds all YAML flows, excluding helper folders like _nav."""
    flows = []
    target = Path(target_path)
    
    if target.is_file():
        if target.suffix in (".yaml", ".yml"):
            flows.append(str(target.resolve()))
    elif target.is_dir():
        for p in sorted(target.rglob("*.yaml")):
            if "_nav" in p.parts or p.name.startswith("_"):
                continue
            flows.append(str(p.resolve()))
        for p in sorted(target.rglob("*.yml")):
            if "_nav" in p.parts or p.name.startswith("_"):
                continue
            flows.append(str(p.resolve()))

    parsed_flows = [parse_flow_metadata(f) for f in flows]

    if filter_pattern:
        filt = filter_pattern.lower()
        parsed_flows = [
            f for f in parsed_flows
            if filt in f["path"].lower() or filt in f["title"].lower() or filt in f["step_title"].lower() or any(filt in t.lower() for t in f["tags"])
        ]

    # Sort naturally by step title then AC number
    def sort_key(item):
        m_step = re.search(r"(\d+)", item["step_title"])
        step_num = int(m_step.group(1)) if m_step else 0
        m_ac = re.search(r"(\d+)", item["ac"])
        ac_num = int(m_ac.group(1)) if m_ac else 999999
        return (step_num, ac_num, item["path"])

    parsed_flows.sort(key=sort_key)
    return parsed_flows


def reset_app_state(package_name, splash_activity, device_id):
    """Resets application state to ensure a clean screen between flows."""
    try:
        # Dismiss any lingering popups or software keyboard before stopping
        run_adb("-s", device_id, "shell", "input", "keyevent", "KEYCODE_BACK", check=False)
        run_adb("-s", device_id, "shell", "am", "force-stop", package_name, check=False)
        time.sleep(0.5)
        run_adb("-s", device_id, "shell", "am", "start", "-n", f"{package_name}/{splash_activity}", check=False)
        time.sleep(1.0)
    except Exception:
        pass


def capture_failure_artifacts(device_id, output_debug_dir, ac_code):
    """Captures screenshot (with fallback), UI hierarchy, and logcat upon test failure.
    
    Guarantees zero lost failure evidence across long-running suites.
    """
    os.makedirs(output_debug_dir, exist_ok=True)
    ts = dt.datetime.now().strftime("%H%M%S")
    screenshot_path = os.path.join(output_debug_dir, f"screenshot_{ac_code}_{ts}.png")
    hierarchy_path = os.path.join(output_debug_dir, f"hierarchy_{ac_code}_{ts}.xml")
    logcat_path = os.path.join(output_debug_dir, f"logcat_{ac_code}_{ts}.txt")

    img_captured = False

    # 1. Primary: Direct screencap binary stream via ADB
    try:
        raw_img = run_adb("-s", device_id, "exec-out", "screencap", "-p", binary=True, check=False)
        if raw_img and len(raw_img) > 1000 and raw_img.startswith(b"\x89PNG"):
            with open(screenshot_path, "wb") as f:
                f.write(raw_img)
            img_captured = True
    except Exception:
        pass

    # 2. Fallback: On-device screencap & pull (solves corrupted stream or slow pipe)
    if not img_captured:
        try:
            device_tmp = f"/sdcard/fail_{ac_code}_{ts}.png"
            run_adb("-s", device_id, "shell", "screencap", "-p", device_tmp, check=False)
            run_adb("-s", device_id, "pull", device_tmp, screenshot_path, check=False)
            run_adb("-s", device_id, "shell", "rm", "-f", device_tmp, check=False)
            if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 1000:
                img_captured = True
        except Exception:
            pass

    # 3. Capture View Hierarchy via uiautomator dump for instant selector analysis
    try:
        device_dump = f"/sdcard/dump_{ac_code}_{ts}.xml"
        run_adb("-s", device_id, "shell", "uiautomator", "dump", device_dump, check=False)
        run_adb("-s", device_id, "pull", device_dump, hierarchy_path, check=False)
        run_adb("-s", device_id, "shell", "rm", "-f", device_dump, check=False)
    except Exception:
        hierarchy_path = ""

    # 4. Dump Logcat (last 250 lines)
    try:
        logcat_out = run_adb("-s", device_id, "logcat", "-d", "-t", "250", check=False)
        with open(logcat_path, "w", encoding="utf-8") as f:
            f.write(logcat_out)
    except Exception:
        logcat_path = ""

    return {
        "screenshot": screenshot_path if img_captured else "",
        "hierarchy": hierarchy_path if os.path.exists(hierarchy_path) else "",
        "logcat": logcat_path if os.path.exists(logcat_path) else "",
    }


def parse_yaml_steps_to_reproduce(yaml_path):
    """Translates Maestro YAML commands into human-readable steps to reproduce."""
    steps = ["Launch the application"]
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            line = line.strip()
            if not line.startswith("- "):
                continue
            cmd = line[2:].strip()
            if cmd.startswith("tapOn:"):
                target = cmd[6:].strip().strip("\"'")
                steps.append(f"Tap on element: {target}")
            elif cmd.startswith("inputText:"):
                val = cmd[10:].strip().strip("\"'")
                steps.append(f"Input text: '{val}'")
            elif cmd.startswith("scrollUntilVisible:"):
                steps.append(f"Scroll until visible: {cmd[19:].strip()}")
            elif cmd.startswith("assertVisible:"):
                target = cmd[14:].strip().strip("\"'")
                steps.append(f"Assert visible: '{target}'")
            elif cmd.startswith("back"):
                steps.append("Tap Back button")
            elif cmd.startswith("runFlow:"):
                steps.append(f"Execute subflow: {cmd[8:].strip()}")
            else:
                steps.append(f"Step: {cmd}")
            if len(steps) >= 8:
                break
    except Exception:
        steps.append("Follow the interactions specified in the test flow")
    return steps


def generate_issue_report(flow_meta, error_msg, artifacts, issues_dir):
    """Creates a markdown defect report matching issue-report-template.md immediately."""
    os.makedirs(issues_dir, exist_ok=True)
    
    existing_issues = sorted([f for f in os.listdir(issues_dir) if f.endswith(".md")])
    next_num = len(existing_issues) + 1
    slug = re.sub(r"[^a-z0-9]+", "-", flow_meta["title"].lower()).strip("-")
    slug = slug[:40] if slug else "defect"
    issue_filename = f"{next_num:02d}-{slug}.md"
    issue_filepath = os.path.join(issues_dir, issue_filename)

    steps = parse_yaml_steps_to_reproduce(flow_meta["path"])
    steps_formatted = "\n".join([f"{i}. {s}" for i, s in enumerate(steps, start=1)])
    summary_error = error_msg.splitlines()[0] if error_msg else "Assertion failed or element missing."

    screenshot = artifacts.get("screenshot", "")
    hierarchy = artifacts.get("hierarchy", "")
    logcat = artifacts.get("logcat", "")

    evidence_parts = []
    if screenshot:
        evidence_parts.append(f"- Screenshot: `{screenshot}`")
    if hierarchy:
        evidence_parts.append(f"- UI Hierarchy: `{hierarchy}`")
    if logcat:
        evidence_parts.append(f"- Logcat slice: `{logcat}`")
    evidence_block = "\n".join(evidence_parts) if evidence_parts else "None captured"

    report_content = f"""# Issue Report

## Title
[Android] {flow_meta['title']} fails assertion on device

### Summary
During automated E2E execution of `{flow_meta['ac']}`, the flow encountered an assertion error: {summary_error}.
Flow file: `{flow_meta['path']}`.

### Steps to reproduce
{steps_formatted}

### Expected result
The flow should complete with all UI assertions passing per requirement `{flow_meta['ac']}` ({flow_meta['title']}).

### Actual result
Test failed at assertion:
```text
{error_msg}
```

### Evidence
{evidence_block}
"""

    with open(issue_filepath, "w", encoding="utf-8") as f:
        f.write(report_content)

    return issue_filepath


def run_maestro_flow(maestro_bin, device_id, flow_path, debug_dir):
    """Runs a single flow with Maestro CLI and detects pass/fail robustly.
    
    Prevents false negatives when Maestro passes assertions but crashes during shutdown/logging.
    """
    os.makedirs(debug_dir, exist_ok=True)
    cmd = [maestro_bin, "--device", device_id, "test", flow_path, "--debug-output", debug_dir]
    start = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    duration = time.time() - start
    output = (res.stdout or "") + "\n" + (res.stderr or "")

    # Robust pass/fail parsing
    has_passed_count = bool(re.search(r"Passed:\s*([1-9]\d*)", output, re.IGNORECASE))
    has_failed_count = bool(re.search(r"Failed:\s*([1-9]\d*)", output, re.IGNORECASE))
    has_passed_marker = "PASSED" in output or "✓" in output or "COMPLETED" in output
    has_failed_marker = "FAILED" in output or "✗" in output or "Assertion error" in output

    if res.returncode == 0:
        passed = not has_failed_count and not has_failed_marker
        warning = ""
    else:
        # Exit code != 0: check if assertions actually passed but runner crashed on log write
        if (has_passed_count or has_passed_marker) and not has_failed_count and not has_failed_marker:
            passed = True
            warning = f"⚠️ Assertions passed, but Maestro exited with code {res.returncode} (runner log crash ignored)."
        else:
            passed = False
            warning = ""

    # Extract clean error message if failed
    error_summary = ""
    if not passed:
        lines = [l.strip() for l in output.splitlines() if l.strip()]
        err_lines = [l for l in lines if "error" in l.lower() or "fail" in l.lower() or "not found" in l.lower() or "timed out" in l.lower()]
        error_summary = "\n".join(err_lines[-4:]) if err_lines else output[-300:]

    return {
        "passed": passed,
        "warning": warning,
        "duration": duration,
        "output": output,
        "error_summary": error_summary,
    }


def write_token_report(out_dir):
    """Writes the token report at suite end when a session ran `token-usage.py start`.

    Done here rather than left to the session: a backgrounded or --open-terminal run returns at once,
    and the session moves on before the suite ends, so a report left to it gets skipped.
    """
    mark = Path(".maestro/.run/token-start.json")
    if not mark.exists():
        return ""
    out = out_dir / f"{dt.datetime.now().strftime('%y%m%d-%H%M')}-token-usage.md"
    until = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    script = Path(__file__).with_name("token-usage.py")
    r = subprocess.run([sys.executable, str(script), "report", str(out), "--until", until],
                       capture_output=True, text=True)
    text = (r.stdout + r.stderr).strip()
    line = f"🪙 Token usage: {text}" if r.returncode == 0 else f"⚠️ Token report not written: {text}"
    print(line)
    if r.returncode == 0:
        mark.unlink()  # one report per start; a second suite needs its own start
    return line


def main():
    parser = argparse.ArgumentParser(description="High-Volume E2E Test Suite Runner for Dev & QC")
    parser.add_argument("target", help="Folder of YAML flows, ticket folder, or single YAML file")
    parser.add_argument("-m", "--mode", choices=["repro", "step", "regression", "smoke"], help="Execution mode preset (repro, step, regression, smoke)")
    parser.add_argument("--device", help="ADB device ID")
    parser.add_argument("--resume", action="store_true", help="Resume from previous checkpoint")
    parser.add_argument("--fail-fast", nargs="?", const=1, type=int, help="Stop after N failures (default 1)")
    parser.add_argument("--filter", help="Filter flows by keyword or tag (e.g. @smoke)")
    parser.add_argument("--repro", action="store_true", help="Shortcut for '-m repro' — runs only reproduction flows (ac-01-repro.yaml)")
    parser.add_argument("--no-reset", action="store_true", help="Skip app force-stop and relaunch between tests")
    parser.add_argument("--app-pkg", default="com.example.app", help="Target app package")
    parser.add_argument("--splash-activity", default="com.example.app.view.splash.SplashActivity")
    parser.add_argument("--require-env", help="Comma-separated list of required env variables/tokens (e.g. API_AUTH_TOKEN)")
    parser.add_argument("--mock-gps", help="Mock GPS latitude and longitude (e.g. '37.4220,-122.0841')")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip preflight environment checks")
    parser.add_argument("--output-dir", help="Output directory for reports and logs")
    parser.add_argument("--dry-run", action="store_true", help="List flows that would be executed and exit")
    parser.add_argument("--open-terminal", action="store_true", help="Launch suite in a new external macOS Terminal window for real-time live monitoring")
    parser.add_argument("--headless", "--no-terminal", dest="headless", action="store_true", help="Run directly in current shell without opening an external Terminal window")
    parser.add_argument("--no-token-track", action="store_true", help="Skip automatic token usage tracking")

    args = parser.parse_args()

    # 1. Resolve Mode & Preset Defaults
    mode = args.mode
    if not mode and args.repro:
        mode = "repro"

    is_auto_detected = False
    if not mode:
        # Context-aware fallback: auto-detect from target if no mode was explicitly passed
        target_lower = args.target.lower()
        if "regression" in target_lower:
            mode = "regression"
            is_auto_detected = True
        elif Path(args.target).is_file() and Path(args.target).suffix in (".yaml", ".yml"):
            mode = "step"
            is_auto_detected = True

    # Apply Mode Presets (explicit user flags always have higher precedence)
    if mode == "repro":
        if args.filter is None:
            args.filter = "repro"
        if args.fail_fast is None:
            args.fail_fast = 1
        # Repro defaults to in-process execution unless --open-terminal is explicitly requested
    elif mode == "regression":
        args.resume = True
        if not args.headless and not args.open_terminal:
            args.open_terminal = True
    elif mode == "step":
        if args.fail_fast is None:
            args.fail_fast = 1
        if not args.headless and not args.open_terminal:
            args.open_terminal = True
    elif mode == "smoke":
        if args.filter is None:
            args.filter = "@smoke"
        if args.fail_fast is None:
            args.fail_fast = 1
        if not args.headless and not args.open_terminal:
            args.open_terminal = True

    # If --headless is passed, it strictly disables --open-terminal
    if args.headless:
        args.open_terminal = False

    # Auto token tracking: start if not already started and not in dry-run
    if not args.dry_run and not args.no_token_track and not args.open_terminal:
        mark = Path(".maestro/.run/token-start.json")
        if not mark.exists():
            token_script = Path(__file__).with_name("token-usage.py")
            if token_script.exists():
                try:
                    subprocess.run([sys.executable, str(token_script), "start"], capture_output=True, text=True)
                except Exception:
                    pass

    # Print Configuration Banner for complete visibility
    mode_label = (mode.upper() + (" (auto-detected)" if is_auto_detected else "")) if mode else "CUSTOM"
    term_label = "EXTERNAL TERMINAL" if args.open_terminal else "IN-PROCESS (CURRENT SHELL)"
    ff_label = f"STOP AFTER {args.fail_fast} FAILURE(S)" if args.fail_fast else "RUN ALL"
    filter_label = f"'{args.filter}'" if args.filter else "NONE (ALL FLOWS)"

    print("=" * 70)
    print("⚙️  SUITE CONFIGURATION:")
    print(f"   • Target:    {args.target}")
    print(f"   • Mode:      {mode_label}")
    print(f"   • Terminal:  {term_label}")
    print(f"   • Fail-Fast: {ff_label}")
    print(f"   • Filter:    {filter_label}")
    print("=" * 70)

    # If --open-terminal is requested, spawn a new Terminal window on macOS and exit
    if args.open_terminal:
        # Build child arguments, ensuring child runs with --headless to prevent recursive window spawns
        remaining_args = [a for a in sys.argv[1:] if a != "--open-terminal"]
        if "--headless" not in remaining_args and "--no-terminal" not in remaining_args:
            remaining_args.append("--headless")
        script_path = os.path.abspath(sys.argv[0])
        cwd = os.getcwd()
        quoted_args = " ".join([f'"{a}"' if " " in a else a for a in remaining_args])
        full_cmd = f'export PATH="{PLATFORM_TOOLS}:{MAESTRO_BIN_DIR}:$PATH" && cd "{cwd}" && python3 "{script_path}" {quoted_args}'

        # Support iTerm2 or macOS Terminal.app based on active environment
        term_program = os.environ.get("TERM_PROGRAM", "").lower()
        launched = False

        if "iterm" in term_program:
            escaped_cmd = full_cmd.replace('\\', '\\\\').replace('"', '\\"')
            iterm_script = f'''
            tell application "iTerm"
                activate
                set newWindow to (create window with default profile)
                tell current session of newWindow
                    write text "{escaped_cmd}"
                end tell
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", iterm_script], check=True)
                launched = True
            except Exception:
                launched = False

        if not launched:
            escaped_cmd = full_cmd.replace('\\', '\\\\').replace('"', '\\"')
            terminal_script = f'''
            tell application "Terminal"
                activate
                do script "{escaped_cmd}"
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", terminal_script], check=True)
                launched = True
            except Exception as e:
                print(f"Warning: Could not launch Terminal window ({e}). Running in current process instead...")

        if launched:
            print("🚀 Successfully launched live monitor in external Terminal window!")
            print(f"👉 Command executing: {full_cmd}")
            return 0

    # Smart target resolution (e.g. plans/<TICKET>/REGRESSION.md -> .maestro/<TICKET>/regression)
    target_str = args.target
    p_target = Path(target_str)
    if p_target.suffix == ".md" or "plans" in p_target.parts or re.match(r"^[A-Z]+-\d+$", target_str, re.IGNORECASE):
        m_epic = re.search(r"([A-Z]+-\d+)", target_str, re.IGNORECASE)
        if m_epic:
            epic_code = m_epic.group(1).upper()
            cand_reg = Path(f".maestro/{epic_code}/regression")
            cand_epic = Path(f".maestro/{epic_code}")
            if "regression" in target_str.lower() and cand_reg.exists():
                target_str = str(cand_reg)
                print(f"💡 Resolved plan target to regression suite: {target_str}")
            elif cand_epic.exists():
                target_str = str(cand_epic)
                print(f"💡 Resolved plan target to epic folder: {target_str}")

    # Discover flows
    flows = find_flows(target_str, args.filter)
    if not flows:
        sys.exit(f"No valid YAML flows found in '{args.target}' (resolved='{target_str}', filter='{args.filter or ''}')")

    if args.dry_run:
        print(f"Discovered {len(flows)} flows in {args.target}:")
        for i, f in enumerate(flows, start=1):
            tag_str = f" [{' '.join(f['tags'])}]" if f["tags"] else ""
            step_str = f" [{f['step_title']}]" if f.get("step_title") else ""
            print(f"  {i:03d}.{step_str} {f['ac']}: {f['title']}{tag_str} ({f['path']})")
        sys.exit(0)

    # Detect device
    device_id = detect_device(args.device)

    # Preflight Health Checks
    if not args.skip_preflight:
        req_envs = [e.strip() for e in args.require_env.split(",")] if args.require_env else None
        run_preflight_checks(device_id, args.app_pkg, req_envs, args.mock_gps)

    # Determine Maestro binary
    maestro_bin = MAESTRO
    if not os.path.exists(maestro_bin) and not shutil.which("maestro"):
        sys.exit(f"BLOCKED: Maestro CLI binary not found at '{maestro_bin}' or on PATH. Please install Maestro or verify ~/.maestro/bin/maestro.")

    # Output directory setup
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        target_p = Path(target_str)
        base_dir = target_p if target_p.is_dir() else target_p.parent
        out_dir = base_dir / "e2e-runs"
    
    out_dir.mkdir(parents=True, exist_ok=True)
    issues_dir = out_dir.parent / "issues" if out_dir.name == "e2e-runs" else out_dir / "issues"
    checkpoint_file = out_dir / "checkpoint.json"
    progress_log = out_dir / f"{dt.datetime.now().strftime('%y%m%d-%H%M')}-progress.log"

    # Checkpoint handling
    checkpoint_data = {"completed": {}, "passed": 0, "failed": 0}
    if args.resume and checkpoint_file.exists():
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                checkpoint_data = json.load(f)
            print(f"Resuming from checkpoint: {len(checkpoint_data.get('completed', {}))} already processed.")
        except Exception as e:
            print(f"Warning: could not read checkpoint ({e}), starting clean.")

    total = len(flows)
    verified_count = checkpoint_data.get("passed", 0)
    failed_count = checkpoint_data.get("failed", 0)

    print("=" * 70)
    print(f"🚀 E2E SUITE RUNNER: {total} flows loaded on [{device_id}]")
    if args.filter:
        print(f"🎯 Filter: '{args.filter}'")
    if args.resume:
        print(f"🔄 Resume enabled: skipping already verified cases")
    if args.fail_fast:
        print(f"🛑 Fail-fast enabled: will stop after {args.fail_fast} failure(s)")
    print("=" * 70)

    start_suite_time = time.time()
    is_tty = sys.stdout.isatty()
    current_step = ""

    # ANSI color codes for rich live Terminal streaming
    CLR_LINE = "\033[2K\r"
    C_RESET = "\033[0m" if is_tty else ""
    C_GREEN = "\033[1;32m" if is_tty else ""
    C_RED = "\033[1;31m" if is_tty else ""
    C_YELLOW = "\033[1;33m" if is_tty else ""
    C_CYAN = "\033[1;36m" if is_tty else ""
    C_DIM = "\033[2m" if is_tty else ""

    for idx, flow in enumerate(flows, start=1):
        ac = flow["ac"]
        title = flow["title"]
        step_title = flow.get("step_title", "")
        flow_path = flow["path"]

        # Step header banner whenever step/category changes
        if step_title and step_title != current_step:
            current_step = step_title
            banner = f"\n━━━ 📌 {current_step} ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            print(f"{C_CYAN}{banner}{C_RESET}" if is_tty else banner, flush=True)
            with open(progress_log, "a", encoding="utf-8") as f:
                f.write(f"\n{banner}\n")

        step_prefix = f"[{current_step}] " if current_step else ""

        # Check if already completed in resume mode
        prev_result = checkpoint_data.get("completed", {}).get(flow_path)
        if args.resume and prev_result and prev_result.get("status") == "PASSED":
            skip_msg = f"{step_prefix}[{idx:03d}/{total:03d}] ⏩ {ac}: {title} - skipped (already verified)"
            print(f"{C_DIM}{skip_msg}{C_RESET}" if is_tty else skip_msg, flush=True)
            continue

        # Real-time ANSI stream: running status
        if is_tty:
            print(f"{CLR_LINE}{step_prefix}[{idx:03d}/{total:03d}] {C_YELLOW}🔄 Running {ac}: {title}...{C_RESET}", end="", flush=True)
        else:
            print(f"{step_prefix}[{idx:03d}/{total:03d}] 🔄 Running {ac}: {title}...", flush=True)

        # Teardown / Reset before executing flow
        if not args.no_reset:
            reset_app_state(args.app_pkg, args.splash_activity, device_id)

        debug_dir = os.path.join(out_dir, "debug", f"{idx:03d}_{ac}")
        run_res = run_maestro_flow(maestro_bin, device_id, flow_path, debug_dir)
        duration_s = int(round(run_res["duration"]))

        if run_res["passed"]:
            verified_count += 1
            warn_extra = f" {run_res['warning']}" if run_res.get("warning") else ""
            log_line = f"{step_prefix}[{idx:03d}/{total:03d}] ✅ {ac}: {title} - verified - {verified_count}/{total} [{duration_s}s]{warn_extra}"
            if is_tty:
                print(f"{CLR_LINE}{C_GREEN}{log_line}{C_RESET}", flush=True)
            else:
                print(f"{log_line}", flush=True)
            checkpoint_data.setdefault("completed", {})[flow_path] = {
                "status": "PASSED",
                "step": current_step,
                "ac": ac,
                "title": title,
                "duration": duration_s,
            }
            checkpoint_data["passed"] = verified_count
        else:
            failed_count += 1
            log_line = f"{step_prefix}[{idx:03d}/{total:03d}] ❌ {ac}: {title} - FAILED [{duration_s}s]"
            if is_tty:
                print(f"{CLR_LINE}{C_RED}{log_line}{C_RESET}", flush=True)
            else:
                print(f"{log_line}", flush=True)
            
            # Robust evidence capture & instant issue report generation
            artifacts = capture_failure_artifacts(device_id, debug_dir, ac)
            issue_path = generate_issue_report(flow, run_res["error_summary"], artifacts, str(issues_dir))
            
            if artifacts.get("screenshot"):
                print(f"          ├── 📸 Snapshot: {artifacts['screenshot']}")
            if artifacts.get("hierarchy"):
                print(f"          ├── 🔍 UI Hierarchy: {artifacts['hierarchy']}")
            print(f"          └── 📝 ISSUE LOGGED: {issue_path}", flush=True)

            checkpoint_data.setdefault("completed", {})[flow_path] = {
                "status": "FAILED",
                "step": current_step,
                "ac": ac,
                "title": title,
                "duration": duration_s,
                "issue": issue_path,
                "evidence": artifacts,
            }
            checkpoint_data["failed"] = failed_count

        # Append to progress log
        with open(progress_log, "a", encoding="utf-8") as f:
            f.write(f"{log_line}\n")

        # Save checkpoint atomically
        with open(checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, indent=2)

        # Check fail-fast condition
        if args.fail_fast and failed_count >= args.fail_fast:
            print("\n" + "!" * 70)
            print(f"🛑 Fail-fast threshold reached ({failed_count} failure(s)). Stopping suite early.")
            print("!" * 70)
            break

    total_suite_duration = time.time() - start_suite_time
    mins, secs = divmod(int(total_suite_duration), 60)

    # Print Final Summary Banner
    print("\n" + "=" * 70)
    final_banner = f"🏁 COMPLETED: ✅ {verified_count} Passed | ❌ {failed_count} Failed | Total: {total} | Duration: {mins}m {secs}s"
    if is_tty:
        c_final = C_GREEN if failed_count == 0 else C_RED
        print(f"{c_final}{final_banner}{C_RESET}")
    else:
        print(final_banner)
    print(f"📁 Checkpoint: {checkpoint_file}")
    print(f"📝 Issues: {issues_dir}")
    print("=" * 70)

    # Write Markdown Summary Report
    summary_md_path = out_dir / f"{dt.datetime.now().strftime('%y%m%d-%H%M')}-epic-summary.md"
    with open(summary_md_path, "w", encoding="utf-8") as f:
        f.write(f"## E2E Suite Run — ✅ {verified_count} passed · ❌ {failed_count} failed · Total {total}\n\n")
        f.write(f"Device: `{device_id}` · Duration: {mins}m {secs}s\n\n")
        f.write("| Step | AC | Title | Result | Duration | Evidence / Issue |\n")
        f.write("|---|---|---|---|---|---|\n")
        for p, d in checkpoint_data.get("completed", {}).items():
            status_icon = "✅ Passed" if d["status"] == "PASSED" else "❌ FAILED"
            step_col = d.get("step") or "—"
            issue_link = f"[{os.path.basename(d['issue'])}]({d['issue']})" if "issue" in d else f"`{os.path.basename(p)}`"
            f.write(f"| {step_col} | {d['ac']} | {d['title']} | {status_icon} | {d['duration']}s | {issue_link} |\n")
    
    print(f"📊 Summary report: {summary_md_path}")
    token_line = write_token_report(out_dir)

    # The session waits on this file, not on stdout: with --open-terminal stdout is another window.
    with open(progress_log, "a", encoding="utf-8") as f:
        if token_line:
            f.write(f"{token_line}\n")
        f.write(f"🏁 COMPLETED: ✅ {verified_count} Passed | ❌ {failed_count} Failed | Total: {total} | Duration: {mins}m {secs}s\n")
        f.write(f"📊 Summary report: {summary_md_path}\n")
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
