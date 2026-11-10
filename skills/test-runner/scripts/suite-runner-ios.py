#!/usr/bin/env python3
"""High-volume E2E test suite runner for iOS Maestro flows (Simulator & Devices).

Designed for Dev & QC to execute large iOS test suites efficiently:
- Native Maestro execution (fast, headless, 0 LLM token waste on passing tests)
- iOS preflight checks (Simulator booted via `xcrun simctl`, app installed via bundle ID)
- Real-time live console monitoring: `[n/total] AC-x: <title> - verified - [time]`
- Instant on-failure defect reporting (with screenshot via `xcrun simctl io screenshot` and logs)
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

# ANSI Color Codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

MAESTRO_BIN_DIR = os.path.expanduser("~/.maestro/bin")
os.environ["PATH"] = f"{MAESTRO_BIN_DIR}:{os.environ.get('PATH', '')}"
MAESTRO = shutil.which("maestro") or os.path.join(MAESTRO_BIN_DIR, "maestro")
XCRUN = shutil.which("xcrun") or "/usr/bin/xcrun"


def run_simctl(*args, check=True):
    """Executes an xcrun simctl command."""
    cmd = [XCRUN, "simctl", *args]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"simctl command failed ({' '.join(args)}): {res.stderr.strip()}")
    return res.stdout


def detect_ios_device(device_arg=None):
    """Detects booted iOS simulator or returns the specified UDID."""
    if device_arg:
        return device_arg

    if not shutil.which(XCRUN):
        sys.exit("BLOCKED: `xcrun` command not found. Ensure Xcode Command Line Tools are installed.")

    try:
        out = run_simctl("list", "devices", "booted", "-j")
        data = json.loads(out)
        booted_devices = []
        for runtime, dev_list in data.get("devices", {}).items():
            for d in dev_list:
                if d.get("state") == "Booted":
                    booted_devices.append((d.get("name"), d.get("udid")))
        
        if not booted_devices:
            sys.exit(
                "BLOCKED: No booted iOS Simulator found.\n"
                "👉 Please boot a simulator first: xcrun simctl boot <device_udid> "
                "or launch Simulator.app."
            )
        
        if len(booted_devices) > 1:
            print(f"Multiple booted simulators found: {[n for n, _ in booted_devices]}. Using {booted_devices[0][0]} ({booted_devices[0][1]})")
        return booted_devices[0][1]
    except Exception as e:
        sys.exit(f"BLOCKED: Failed to query iOS simulators: {e}")


def run_preflight_checks(udid, bundle_id=None):
    """Validates Simulator status and app installation."""
    print(f"\n{CYAN}🔍 Running iOS Preflight Health Checks...{RESET}")
    errors = []

    # 1. Simulator check
    try:
        run_simctl("get_app_container", udid, "com.apple.mobilesafari")
        print(f"  {GREEN}✅ Simulator online & responsive: {udid}{RESET}")
    except Exception as e:
        errors.append(f"Cannot communicate with simulator '{udid}': {e}")

    # 2. App bundle check (if bundle_id specified)
    if bundle_id:
        try:
            container = run_simctl("get_app_container", udid, bundle_id).strip()
            if container:
                print(f"  {GREEN}✅ iOS App installed: {bundle_id}{RESET}")
        except Exception:
            errors.append(
                f"Bundle ID '{bundle_id}' is NOT installed on simulator {udid}.\n"
                f"   👉 Build & install first via Xcode or `xcrun simctl install {udid} <app_path>`"
            )

    if errors:
        print(f"\n{RED}❌ Preflight Checks Failed ({len(errors)} error(s)):{RESET}")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)


def find_flow_files(target_path, filter_kw=None):
    """Scans and collects non-helper YAML flow files."""
    path = Path(target_path)
    if not path.exists():
        sys.exit(f"BLOCKED: Target path does not exist: {target_path}")

    files = []
    if path.is_file():
        files = [path]
    else:
        for root, _, filenames in os.walk(path):
            for f in sorted(filenames):
                if f.endswith((".yaml", ".yml")) and not f.startswith("_"):
                    files.append(Path(root) / f)

    if filter_kw:
        files = [f for f in files if filter_kw.lower() in f.name.lower() or filter_kw.lower() in str(f).lower()]

    return sorted(files)


def extract_flow_title(flow_path):
    """Extracts test name / title from YAML header or filename."""
    try:
        with open(flow_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("name:"):
                    return line.split("name:", 1)[1].strip().strip('"\'')
    except Exception:
        pass
    return flow_path.stem


def execute_flow(flow_path, udid, output_dir):
    """Runs a single flow via Maestro CLI. Returns (passed, duration, output_log)."""
    start_time = time.time()
    cmd = [MAESTRO]
    if udid:
        cmd.extend(["--device", udid])
    cmd.extend(["test", str(flow_path)])

    res = subprocess.run(cmd, capture_output=True, text=True)
    duration = time.time() - start_time
    passed = (res.returncode == 0)
    output_log = res.stdout + ("\n" + res.stderr if res.stderr else "")
    return passed, duration, output_log


def capture_failure_artifacts(udid, flow_name, output_dir):
    """Captures screenshot and crash log snippet on test failure."""
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    artifacts = {}

    issues_dir = Path(output_dir) / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)

    # 1. Screenshot
    shot_path = issues_dir / f"{flow_name}_{timestamp}.png"
    try:
        run_simctl("io", udid, "screenshot", str(shot_path), check=False)
        if shot_path.exists():
            artifacts["screenshot"] = str(shot_path)
    except Exception as e:
        artifacts["screenshot_error"] = str(e)

    return artifacts


def save_defect_report(flow_path, title, duration, output_log, artifacts, output_dir):
    """Writes a standardized markdown defect report."""
    issues_dir = Path(output_dir) / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)
    report_file = issues_dir / f"DEFECT_{flow_path.stem}.md"

    content = f"""# [iOS Defect Report] {title}

**Flow File:** `{flow_path}`
**Timestamp:** {dt.datetime.now().isoformat()}
**Duration:** {duration:.2f}s
**Platform:** iOS Simulator

## Failure Summary
Flow failed assertion or timed out during Maestro execution.

## Captured Artifacts
- **Screenshot:** `{artifacts.get('screenshot', 'None')}`

## Maestro CLI Log Snippet
```
{output_log[-2000:] if len(output_log) > 2000 else output_log}
```

## Recommended Actions
1. Inspect the screenshot to check UI hierarchy / accessibility IDs.
2. Verify if the target element needs `.accessibilityIdentifier` or a relative selector (`below:`, `above:`).
3. If this is a regression, verify with `guard-blast` allowlist.
"""
    report_file.write_text(content, encoding="utf-8")
    return report_file


def main():
    parser = argparse.ArgumentParser(description="High-volume E2E test runner for iOS Maestro flows.")
    parser.add_argument("target", help="Directory or single YAML flow file to execute")
    parser.add_argument("-m", "--mode", choices=["repro", "step", "regression", "smoke"], default="step",
                        help="Execution mode (repro=single flow, step=feature folder, regression=full suite)")
    parser.add_argument("--device", help="Specific iOS Simulator UDID")
    parser.add_argument("--bundle-id", help="App Bundle ID to verify in preflight (e.g. com.example.app)")
    parser.add_argument("--filter", help="Filter flows by keyword / tag")
    parser.add_argument("--fail-fast", type=int, nargs="?", const=1, default=None,
                        help="Stop suite immediately after N failures (default: 1)")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint.json")

    args = parser.parse_args()

    # 1. Device detection & preflight
    udid = detect_ios_device(args.device)
    run_preflight_checks(udid, bundle_id=args.bundle_id)

    # 2. Collect flows
    flows = find_flow_files(args.target, filter_kw=args.filter)
    if not flows:
        print(f"\n{YELLOW}⚠️  No matching flows found in '{args.target}'{RESET}")
        sys.exit(0)

    # Setup output & checkpoint dir
    target_path = Path(args.target)
    run_dir = target_path if target_path.is_dir() else target_path.parent
    checkpoint_file = run_dir / "checkpoint.json"

    completed = set()
    if args.resume and checkpoint_file.exists():
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                completed = set(data.get("completed", []))
                print(f"{BLUE}ℹ️  Resuming suite. {len(completed)} flows previously passed.{RESET}")
        except Exception:
            pass

    remaining_flows = [f for f in flows if str(f) not in completed]
    total_count = len(flows)
    print(f"\n{BOLD}🚀 Starting iOS Maestro Suite ({len(remaining_flows)}/{total_count} flows to run){RESET}")
    print(f"Target: {args.target} | Mode: {args.mode} | Simulator: {udid}\n")

    passed_count = len(completed)
    failed_count = 0
    failures = []

    for idx, flow in enumerate(remaining_flows, start=len(completed) + 1):
        title = extract_flow_title(flow)
        prefix = f"[{idx}/{total_count}]"

        passed, duration, output_log = execute_flow(flow, udid, run_dir)

        if passed:
            passed_count += 1
            completed.add(str(flow))
            print(f"  {GREEN}✅ {prefix} {flow.name} - verified ({duration:.1f}s){RESET}")
            # Update checkpoint
            with open(checkpoint_file, "w", encoding="utf-8") as f:
                json.dump({"completed": list(completed), "timestamp": dt.datetime.now().isoformat()}, f, indent=2)
        else:
            failed_count += 1
            print(f"  {RED}❌ {prefix} {flow.name} - FAILED ({duration:.1f}s){RESET}")
            artifacts = capture_failure_artifacts(udid, flow.stem, run_dir)
            report_path = save_defect_report(flow, title, duration, output_log, artifacts, run_dir)
            failures.append((flow, report_path))
            print(f"     👉 Defect report generated: {report_path}")

            if args.fail_fast and failed_count >= args.fail_fast:
                print(f"\n{RED}⛔ Fail-fast triggered after {failed_count} failure(s). Stopping suite.{RESET}")
                break

    # Summary
    print(f"\n{'='*50}")
    print(f"{BOLD}Suite Summary:{RESET} {passed_count}/{total_count} Passed, {failed_count} Failed")
    if failed_count == 0:
        print(f"{GREEN}{BOLD}🎉 ALL iOS TESTS PASSED! (0 LLM Token Bleed){RESET}")
        sys.exit(0)
    else:
        print(f"{RED}{BOLD}⚠️  {failed_count} TEST(S) FAILED. Inspect defect reports above.{RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
