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
import atexit
import datetime as dt
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Dict, Any

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


# Device Mutex Lock Constants & Helpers
DEVICE_LOCK_DIR = Path("/tmp/android_device_locks")
LOCK_TIMEOUT_SECONDS = 30  # Max wait time for a busy device to become free
STALE_LOCK_AGE_SECONDS = 3600  # 1 hour max age before auto-clearing stale lock


def _is_pid_alive(pid: int) -> bool:
    """Checks if a process ID is currently running on the system."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def get_device_lock_info(device_id: str) -> Optional[Dict[str, Any]]:
    """Reads lock info for device if active. Cleans up stale locks automatically."""
    lock_file = DEVICE_LOCK_DIR / f"{device_id}.lock"
    if not lock_file.exists():
        return None
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        pid = data.get("pid")
        acquired_at = data.get("acquired_at", 0)
        if (time.time() - acquired_at > STALE_LOCK_AGE_SECONDS) or not _is_pid_alive(pid):
            try:
                lock_file.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        return data
    except Exception:
        try:
            lock_file.unlink(missing_ok=True)
        except Exception:
            pass
        return None


def acquire_device_lock(device_id: str, target: str = "") -> bool:
    """Acquires lock for device_id under current PID."""
    DEVICE_LOCK_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = DEVICE_LOCK_DIR / f"{device_id}.lock"
    data = {
        "device_id": device_id,
        "pid": os.getpid(),
        "target": target,
        "acquired_at": time.time(),
    }
    try:
        lock_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print(f"Warning: Failed to write lock file for {device_id}: {e}")
        return False


def release_device_lock(device_id: str):
    """Releases lock for device_id if held by current process."""
    lock_file = DEVICE_LOCK_DIR / f"{device_id}.lock"
    if not lock_file.exists():
        return
    try:
        data = json.loads(lock_file.read_text(encoding="utf-8"))
        if data.get("pid") == os.getpid():
            lock_file.unlink(missing_ok=True)
    except Exception:
        pass


def setup_lock_cleanup(device_id: str):
    """Registers atexit and signal handlers to release device lock upon process exit."""
    atexit.register(lambda: release_device_lock(device_id))

    def _sig_handler(signum, frame):
        release_device_lock(device_id)
        sys.exit(128 + signum)

    try:
        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, _sig_handler)
    except Exception:
        pass


def detect_device(device_arg=None, target="", enable_lock=True, inherited_lock_pid=None):
    """Detects connected device ID, auto-leases a free device if multiple exist, or validates the provided one."""
    env_serial = os.environ.get("ANDROID_SERIAL")
    explicit_device = device_arg or (env_serial.strip() if env_serial else None)

    owned_pids = {os.getpid()}
    if inherited_lock_pid:
        owned_pids.add(int(inherited_lock_pid))

    try:
        out = run_adb("devices")
    except Exception as e:
        sys.exit(f"BLOCKED: Failed to run adb devices ({e}). Ensure adb is accessible.")
    lines = [l.strip() for l in out.splitlines() if l.strip() and not l.startswith("List of devices")]
    devices = [l.split()[0] for l in lines if "\tdevice" in l]
    if not devices:
        sys.exit("BLOCKED: No Android device/emulator found via `adb devices`. Please start one.")

    if not enable_lock:
        if explicit_device:
            return explicit_device
        return devices[0]

    # Case 1: Explicit device specified by user / flag / ANDROID_SERIAL
    if explicit_device:
        if explicit_device not in devices:
            sys.exit(f"BLOCKED: Specified device '{explicit_device}' not found in active devices: {devices}")
        lock_info = get_device_lock_info(explicit_device)
        if lock_info and lock_info.get("pid") not in owned_pids:
            other_pid = lock_info.get("pid")
            target_desc = f" ({lock_info.get('target')})" if lock_info.get("target") else ""
            print(f"⚠️  Specified device '{explicit_device}' is currently locked by PID {other_pid}{target_desc}.")
            waited = 0
            while waited < LOCK_TIMEOUT_SECONDS:
                time.sleep(2)
                waited += 2
                lock_info = get_device_lock_info(explicit_device)
                if not lock_info or lock_info.get("pid") in owned_pids:
                    break
                print(f"⏳ Waiting for device '{explicit_device}' to be released ({waited}/{LOCK_TIMEOUT_SECONDS}s)...")
            if lock_info and lock_info.get("pid") not in owned_pids:
                sys.exit(f"BLOCKED: Device '{explicit_device}' is busy (PID {lock_info.get('pid')}). Please wait or use another emulator.")
        acquire_device_lock(explicit_device, target)
        return explicit_device

    # Case 2: Only 1 device connected
    if len(devices) == 1:
        dev = devices[0]
        lock_info = get_device_lock_info(dev)
        if lock_info and lock_info.get("pid") not in owned_pids:
            other_pid = lock_info.get("pid")
            print(f"⏳ Single device '{dev}' is currently busy (PID {other_pid}). Waiting for release...")
            waited = 0
            while waited < LOCK_TIMEOUT_SECONDS:
                time.sleep(2)
                waited += 2
                lock_info = get_device_lock_info(dev)
                if not lock_info or lock_info.get("pid") in owned_pids:
                    break
            if lock_info and lock_info.get("pid") not in owned_pids:
                sys.exit(f"BLOCKED: Device '{dev}' is busy (PID {lock_info.get('pid')}). Please wait or start a second emulator.")
        acquire_device_lock(dev, target)
        return dev

    # Case 3: Multiple devices connected -> Smart Auto-Lease!
    # Check all available devices and pick the first free (unlocked) one
    start_wait = time.time()
    first_attempt = True
    while True:
        for dev in devices:
            lock_info = get_device_lock_info(dev)
            if not lock_info or lock_info.get("pid") in owned_pids:
                if not first_attempt:
                    print(f"✅ Device released! Auto-leased: {dev}")
                else:
                    print(f"🤖 Multiple devices detected {devices}. Auto-leased available device: {dev}")
                acquire_device_lock(dev, target)
                return dev

        first_attempt = False
        elapsed = int(time.time() - start_wait)
        if elapsed >= LOCK_TIMEOUT_SECONDS:
            busy_summary = ", ".join([f"{d} (PID {get_device_lock_info(d).get('pid')})" for d in devices if get_device_lock_info(d)])
            sys.exit(f"BLOCKED: All connected devices are busy: [{busy_summary}]. Timed out after {LOCK_TIMEOUT_SECONDS}s.")

        print(f"⏳ All devices busy ({devices}). Waiting for a free device ({elapsed}/{LOCK_TIMEOUT_SECONDS}s)...")
        time.sleep(2)


def detect_app_package(flows: list[dict]) -> str:
    """Auto-detects the Android package name from discovered Maestro flow appId headers or Gradle config."""
    app_id_re = re.compile(r"^\s*appId\s*:\s*['\"]?([A-Za-z][A-Za-z0-9_]*\.[A-Za-z0-9_.]+)['\"]?")
    for flow in flows:
        fpath = flow.get("path", "")
        if not fpath or not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                for idx, line in enumerate(f):
                    if idx >= 30:
                        break
                    m = app_id_re.match(line)
                    if m:
                        return m.group(1).strip()
        except Exception:
            continue

    env_app_id = os.environ.get("APP_ID", "").strip()
    if env_app_id and "." in env_app_id:
        return env_app_id

    for gradle_rel in ("app/build.gradle.kts", "app/build.gradle"):
        gp = Path(gradle_rel)
        if gp.is_file():
            try:
                txt = gp.read_text(encoding="utf-8", errors="ignore")
                m = re.search(r'applicationId\s*[= ]\s*["\']([A-Za-z][A-Za-z0-9_]*\.[A-Za-z0-9_.]+)["\']', txt)
                if m:
                    return m.group(1).strip()
            except Exception:
                pass
    return ""


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
    if not package_name:
        print("  ⚠️ App package not detected (no literal appId in flows and no --app-pkg); skipping pm path check.")
    else:
        try:
            pm_path = run_adb("-s", device_id, "shell", "pm", "path", package_name).strip()
            if not pm_path:
                errors.append(
                    f"Package '{package_name}' is NOT installed on {device_id}.\n"
                    f"   👉 Decoupled solution: Build with './gradlew assembleDebug', then run suite-runner with '--install'\n"
                    f"      (e.g., `python3 skills/test-runner/scripts/suite-runner.py <target> -m step --install`),\n"
                    f"      which isolates the installation onto locked device {device_id} without colliding with other emulators."
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


def find_debug_apk(explicit_path: Optional[str] = None, search_dir: Optional[Path] = None) -> Optional[Path]:
    """Finds target APK for installation. Checks explicit path first, then searches build outputs."""
    if explicit_path:
        p = Path(explicit_path)
        if p.exists() and p.is_file():
            return p.resolve()
        return None

    root = search_dir or Path.cwd()
    candidates = []

    # Priority search locations for Android Gradle builds
    search_globs = [
        "app/build/outputs/apk/**/*.apk",
        "*/build/outputs/apk/**/*.apk",
        "build/outputs/apk/**/*.apk",
    ]
    for pattern in search_globs:
        for p in root.glob(pattern):
            if p.is_file():
                candidates.append(p)

    # Fallback search if standard build folders differ
    if not candidates:
        for p in root.rglob("*.apk"):
            parts = set(p.parts)
            if {".git", ".worktrees", "e2e-runs", "issues", "node_modules"}.intersection(parts):
                continue
            candidates.append(p)

    # Filter out test and unaligned APKs
    filtered = []
    for c in candidates:
        name_lower = c.name.lower()
        if "test" in name_lower or "unaligned" in name_lower:
            continue
        filtered.append(c)

    if not filtered:
        filtered = [c for c in candidates if "test" not in c.name.lower()]

    if not filtered:
        return None

    # Prefer APKs with 'debug' in name
    debug_apks = [c for c in filtered if "debug" in c.name.lower()]
    pool = debug_apks if debug_apks else filtered

    # Return newest modified file
    return max(pool, key=lambda f: f.stat().st_mtime).resolve()


def install_apk_on_device(device_id: str, apk_arg: Optional[str] = None, explicit_apk: Optional[str] = None) -> str:
    """Installs the target APK onto the locked device via ADB using isolated serial."""
    target_path = explicit_apk or (apk_arg if apk_arg and apk_arg != "auto" else None)
    apk_file = find_debug_apk(target_path)
    if not apk_file or not apk_file.exists():
        if target_path:
            sys.exit(f"BLOCKED: Specified APK not found at '{target_path}'. Please verify the path or build first with './gradlew assembleDebug'.")
        else:
            sys.exit(
                "BLOCKED: No debug APK found in build outputs. "
                "Please build with './gradlew assembleDebug' first, or pass explicit path via '--install <path>'."
            )

    print(f"\n📦 Installing APK onto locked device [{device_id}]...")
    print(f"   • APK: {apk_file}")
    try:
        out = run_adb("-s", device_id, "install", "-r", "-t", "-d", "-g", str(apk_file))
        if "Success" not in out:
            print(f"   ⚠️ ADB Output: {out.strip()}")
        print(f"   ✅ Successfully installed APK onto [{device_id}]!\n")
        return str(apk_file)
    except Exception as e:
        sys.exit(f"BLOCKED: Failed to install APK onto device '{device_id}': {e}")


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


def flow_uses_launch_app(yaml_path: str) -> bool:
    """Returns True if the Maestro YAML flow already invokes launchApp."""
    try:
        content = Path(yaml_path).read_text(encoding="utf-8", errors="ignore")
        return bool(re.search(r"^\s*-\s*launchApp\b", content, re.MULTILINE))
    except Exception:
        return False


def reset_app_state(package_name, splash_activity, device_id, skip_launch=False):
    """Resets application state to ensure a clean screen between flows."""
    if not package_name:
        return
    try:
        # Dismiss any lingering popups or software keyboard before stopping
        run_adb("-s", device_id, "shell", "input", "keyevent", "KEYCODE_BACK", check=False)
        run_adb("-s", device_id, "shell", "am", "force-stop", package_name, check=False)
        time.sleep(0.4)
        if not skip_launch:
            if splash_activity:
                run_adb("-s", device_id, "shell", "am", "start", "-n", f"{package_name}/{splash_activity}", check=False)
            else:
                run_adb(
                    "-s", device_id, "shell", "monkey",
                    "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1",
                    check=False,
                )
            time.sleep(1.0)
    except Exception:
        pass


def get_window_focus(device_id: str) -> str:
    """Returns current focused window line via dumpsys window (<50ms, immune to animations)."""
    try:
        res = subprocess.run(
            [ADB, "-s", device_id, "shell", "dumpsys", "window", "displays"],
            capture_output=True, text=True, timeout=3.0,
        )
        out = res.stdout or ""
        for line in out.splitlines():
            if "mCurrentFocus=" in line or "mFocusedApp=" in line:
                return line.strip()
        res2 = subprocess.run(
            [ADB, "-s", device_id, "shell", "dumpsys", "window"],
            capture_output=True, text=True, timeout=3.0,
        )
        for line in (res2.stdout or "").splitlines():
            if "mCurrentFocus=" in line:
                return line.strip()
    except Exception:
        pass
    return ""


def _run_adb_timeout(device_id: str, args: list[str], timeout: float = 5.0) -> str:
    try:
        res = subprocess.run([ADB, "-s", device_id, *args], capture_output=True, text=True, timeout=timeout)
        return res.stdout or ""
    except Exception:
        return ""


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

    # 3. Capture View Hierarchy via uiautomator dump (bounded timeout so Lottie/animations don't hang)
    try:
        device_dump = f"/sdcard/dump_{ac_code}_{ts}.xml"
        _run_adb_timeout(device_id, ["shell", "uiautomator", "dump", device_dump], timeout=6.0)
        _run_adb_timeout(device_id, ["pull", device_dump, hierarchy_path], timeout=4.0)
        _run_adb_timeout(device_id, ["shell", "rm", "-f", device_dump], timeout=3.0)
    except Exception:
        hierarchy_path = ""

    # 4. Dump Logcat (last 250 lines)
    try:
        logcat_out = run_adb("-s", device_id, "logcat", "-d", "-t", "250", check=False)
        with open(logcat_path, "w", encoding="utf-8") as f:
            f.write(logcat_out)
    except Exception:
        logcat_path = ""

    focus_window = get_window_focus(device_id)

    return {
        "screenshot": screenshot_path if img_captured else "",
        "hierarchy": hierarchy_path if os.path.exists(hierarchy_path) else "",
        "logcat": logcat_path if os.path.exists(logcat_path) else "",
        "focus_window": focus_window,
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


# Built-in Android OS / Google Play Services system dialog rules (safe, app-agnostic)
SYSTEM_POPUP_RULES = [
    {
        "name": "android-runtime-permission",
        "when_visible": {"window": "com.android.permissioncontroller|com.google.android.permissioncontroller"},
        "actions": [{"type": "tap", "id": "permission_allow_foreground_only_button|permission_allow_button|permission_allow_one_time_button"}],
    },
    {
        "name": "google-autofill-save-password",
        "when_visible": {"window": "com.google.android.gms", "text": "Save password|Autofill|Not now|Never"},
        "actions": [{"type": "tap", "text": "^(Not now|Never|No thanks)$"}],
    },
]

SAFE_CLOSE_HINT_RE = re.compile(
    r"^(close|dismiss|skip|later|not now|got it|no thanks|đóng|bỏ qua|để sau|đã hiểu)$",
    re.IGNORECASE,
)
SAFE_CLOSE_ID_RE = re.compile(r"(?:btn|iv|ic|img|action)[_-]?(?:close|dismiss|skip)(?:[_-].*)?$", re.IGNORECASE)


def load_popup_rules(target_str: str) -> list[dict]:
    """Loads built-in system dialog rules + project-specific .maestro/_shared/popups.json rules."""
    rules = list(SYSTEM_POPUP_RULES)
    candidates = [Path.cwd() / ".maestro" / "_shared" / "popups.json"]
    p = Path(target_str).resolve()
    for parent in [p, *p.parents]:
        if parent.name == ".maestro":
            candidates.insert(0, parent / "_shared" / "popups.json")
            break
    for cand in candidates:
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
                for r in data.get("rules", []):
                    if isinstance(r, dict) and r.get("enabled", True) is not False and r.get("when_visible") and r.get("actions"):
                        rules.append(r)
                break
            except Exception:
                pass
    return rules


def _parse_xml_nodes(hierarchy_path: str) -> list[dict]:
    if not hierarchy_path or not os.path.isfile(hierarchy_path):
        return []
    try:
        root = ET.parse(hierarchy_path).getroot()
    except Exception:
        return []
    nodes = []
    for n in root.iter("node"):
        rid = n.get("resource-id", "")
        short_id = rid.split(":id/")[-1] if ":id/" in rid else rid
        b_str = n.get("bounds", "")
        cx, cy = None, None
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b_str)
        if m:
            l, t, r, b = map(int, m.groups())
            cx, cy = (l + r) // 2, (t + b) // 2
        nodes.append({
            "id": short_id,
            "raw_id": rid,
            "text": n.get("text", "") or "",
            "desc": n.get("content-desc", "") or "",
            "clickable": n.get("clickable") == "true",
            "bounds": b_str,
            "cx": cx,
            "cy": cy,
        })
    return nodes


def _node_matches(node: dict, matcher: dict) -> bool:
    for key, attr in (("id", "id"), ("text", "text"), ("content_desc", "desc")):
        pat = matcher.get(key)
        if pat:
            val = node.get(attr, "")
            if not val or not re.search(pat, val, re.IGNORECASE):
                return False
    return any(k in matcher for k in ("id", "text", "content_desc"))


def _rule_matches_screen(rule: dict, focus_window: str, nodes: list[dict]) -> bool:
    when = rule.get("when_visible") or {}
    win_pat = when.get("window")
    if win_pat and not re.search(win_pat, focus_window or "", re.IGNORECASE):
        return False
    node_keys = {k: when[k] for k in ("id", "text", "content_desc") if when.get(k)}
    if node_keys:
        return any(_node_matches(n, node_keys) for n in nodes)
    return bool(win_pat)


def _execute_dismiss_actions(device_id: str, actions: list[dict], nodes: list[dict], debug_dir: str, ac_code: str) -> bool:
    acted = False
    cur_nodes = nodes
    for step_idx, act in enumerate(actions):
        atype = act.get("type", "")
        if atype == "back":
            _run_adb_timeout(device_id, ["shell", "input", "keyevent", "KEYCODE_BACK"], timeout=3.0)
            acted = True
            time.sleep(0.5)
        elif atype == "tap":
            if step_idx > 0:
                tmp_xml = os.path.join(debug_dir, f"popup_step_{ac_code}_{step_idx}.xml")
                _run_adb_timeout(device_id, ["shell", "uiautomator", "dump", "/sdcard/popup_step.xml"], timeout=5.0)
                _run_adb_timeout(device_id, ["pull", "/sdcard/popup_step.xml", tmp_xml], timeout=3.0)
                refreshed = _parse_xml_nodes(tmp_xml)
                if refreshed:
                    cur_nodes = refreshed
            target_node = next((n for n in cur_nodes if _node_matches(n, act) and n["cx"] is not None), None)
            if not target_node:
                return acted
            _run_adb_timeout(device_id, ["shell", "input", "tap", str(target_node["cx"]), str(target_node["cy"])], timeout=3.0)
            acted = True
            time.sleep(0.5)
    return acted


def try_dismiss_overlay(
    device_id: str,
    hierarchy_path: str,
    focus_window: str,
    flow_path: str,
    rules: list[dict],
    debug_dir: str,
    ac_code: str,
) -> tuple[bool, str]:
    """Dismisses only known system dialogs or project popups.json rules. Returns (dismissed, rule_name)."""
    nodes = _parse_xml_nodes(hierarchy_path)
    if not nodes and not focus_window:
        return False, ""

    if os.path.isfile(flow_path) and "@keep-dialogs" in Path(flow_path).read_text(encoding="utf-8", errors="ignore"):
        return False, ""

    for rule in rules:
        if _rule_matches_screen(rule, focus_window, nodes):
            if _execute_dismiss_actions(device_id, rule["actions"], nodes, debug_dir, ac_code):
                return True, rule.get("name", "known-rule")

    return False, ""


def classify_failure(
    error_summary: str,
    focus_window: str,
    hierarchy_path: str,
    logcat_path: str,
    app_pkg: str,
) -> tuple[str, list[str], list[str]]:
    """Classifies failure into LIKELY_CAUSE + raw evidence lines + overlay clickable hints."""
    evidence: list[str] = []
    if focus_window:
        evidence.append(f"Focus: {focus_window}")

    # 1. Check Crash / ANR in logcat
    log_txt = ""
    if logcat_path and os.path.isfile(logcat_path):
        try:
            log_txt = Path(logcat_path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            pass
    if "FATAL EXCEPTION" in log_txt or (app_pkg and f"ANR in {app_pkg}" in log_txt):
        return "APP_CRASH_OR_ANR", evidence, []

    # 2. Check if an overlay / external window / dialog is likely blocking
    nodes = _parse_xml_nodes(hierarchy_path)
    is_external_win = bool(focus_window) and (not app_pkg or app_pkg not in focus_window) and ("PopupWindow" in focus_window or "Dialog" in focus_window or "permissioncontroller" in focus_window or "gms" in focus_window)
    has_close_hint = any(
        SAFE_CLOSE_HINT_RE.match(n["text"]) or SAFE_CLOSE_HINT_RE.match(n["desc"]) or SAFE_CLOSE_ID_RE.search(n["id"])
        for n in nodes
    )
    is_dialog_win = "Dialog" in (focus_window or "") or "PopupWindow" in (focus_window or "")
    if is_external_win or is_dialog_win or has_close_hint:
        hints = []
        for n in nodes:
            if n["clickable"] or n["id"] or SAFE_CLOSE_HINT_RE.match(n["text"]):
                label = n["id"] or n["desc"] or n["text"]
                if label:
                    hints.append(f"{label} {n['bounds']}")
            if len(hints) >= 8:
                break
        return "BLOCKED_BY_OVERLAY", evidence, hints

    # 3. Selector vs Assertion
    err_lower = (error_summary or "").lower()
    if "not found" in err_lower or "timed out" in err_lower or "element" in err_lower:
        return "SELECTOR_NOT_FOUND", evidence, []
    return "ASSERTION_FAILED", evidence, []


PII_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PII_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
PII_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*\b")
PII_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\s().-]?){10,14}\d(?!\d)")


def _redact_pii(text: str) -> str:
    if not text:
        return ""
    out = PII_EMAIL_RE.sub("<email>", text)
    out = PII_BEARER_RE.sub(r"\1<redacted>", out)
    out = PII_JWT_RE.sub("<jwt>", out)
    out = PII_PHONE_RE.sub("<phone>", out)
    return out


def _select_digest_nodes(nodes: list[dict], error_summary: str, max_nodes: int = 45) -> list[dict]:
    """Selects up to max_nodes informative UI nodes, prioritizing error matches, overlays, clickables, and tail nodes."""
    meaningful = [n for n in nodes if n.get("id") or n.get("text") or n.get("desc")]
    if len(meaningful) <= max_nodes:
        return meaningful

    hint_tokens = {
        tok.lower()
        for tok in re.findall(r"[A-Za-z0-9_./-]{3,}", error_summary or "")
        if tok.lower() not in {"not", "found", "element", "visible", "timed", "out", "assertion", "failed", "error", "text", "true", "false"}
    }

    tail_start = max(0, len(meaningful) - 12)
    buckets: list[list[int]] = [[], [], [], []]
    for idx, n in enumerate(meaningful):
        hay = f"{n.get('id', '')} {n.get('text', '')} {n.get('desc', '')}".lower()
        is_close_hint = bool(
            SAFE_CLOSE_HINT_RE.match(n.get("text", ""))
            or SAFE_CLOSE_HINT_RE.match(n.get("desc", ""))
            or SAFE_CLOSE_ID_RE.search(n.get("id", ""))
        )
        is_err_match = any(tok in hay for tok in hint_tokens)
        if is_close_hint or is_err_match:
            buckets[0].append(idx)
        elif n.get("clickable"):
            buckets[1].append(idx)
        elif idx >= tail_start:
            buckets[2].append(idx)
        else:
            buckets[3].append(idx)

    chosen_indices: list[int] = []
    seen: set[int] = set()
    for bucket in buckets:
        for idx in bucket:
            if idx not in seen:
                seen.add(idx)
                chosen_indices.append(idx)
                if len(chosen_indices) >= max_nodes:
                    break
        if len(chosen_indices) >= max_nodes:
            break

    chosen_indices.sort()
    return [meaningful[i] for i in chosen_indices]


def _filter_digest_logcat(logcat_path: str, app_pkg: str, max_lines: int = 25) -> list[str]:
    if not logcat_path or not os.path.isfile(logcat_path):
        return []
    try:
        raw_lines = [l.rstrip() for l in Path(logcat_path).read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    except Exception:
        return []
    if not raw_lines:
        return []

    interesting = [
        l for l in raw_lines
        if (
            "FATAL EXCEPTION" in l
            or "AndroidRuntime" in l
            or "ANR in" in l
            or " E " in l
            or "E/" in l
            or "exception" in l.lower()
            or "error" in l.lower()
            or (app_pkg and app_pkg != "com.example.app" and app_pkg in l)
        )
    ]
    selected = interesting[-max_lines:] if interesting else raw_lines[-min(10, max_lines):]
    return [_redact_pii(l) for l in selected]


def generate_failure_digest(
    flow_meta: dict,
    error_summary: str,
    artifacts: dict,
    debug_dir: str,
    likely_cause: str,
    app_pkg: str,
    max_nodes: int = 45,
    max_log_lines: int = 25,
) -> str:
    """Generates a compact 1-read failure digest markdown file (never raises)."""
    try:
        os.makedirs(debug_dir, exist_ok=True)
        ts = dt.datetime.now().strftime("%H%M%S")
        safe_ac = re.sub(r"[^A-Za-z0-9._-]+", "_", str(flow_meta.get("ac", "flow")))
        digest_path = os.path.join(debug_dir, f"digest_{safe_ac}_{ts}.md")

        nodes = _parse_xml_nodes(artifacts.get("hierarchy", ""))
        selected_nodes = _select_digest_nodes(nodes, error_summary, max_nodes=max_nodes)
        node_lines = []
        for n in selected_nodes:
            nid = n.get("id") or "-"
            ntext = _redact_pii((n.get("text") or "").replace("\n", " "))[:60]
            ndesc = _redact_pii((n.get("desc") or "").replace("\n", " "))[:40]
            clk = "Y" if n.get("clickable") else "N"
            node_lines.append(f'id={nid} | text="{ntext}" | desc="{ndesc}" | clickable={clk} | bounds={n.get("bounds", "")}')

        flow_snippet = ""
        flow_path = flow_meta.get("path", "")
        if flow_path and os.path.isfile(flow_path):
            try:
                yaml_lines = Path(flow_path).read_text(encoding="utf-8", errors="ignore").splitlines()
                if len(yaml_lines) > 60:
                    flow_snippet = "\n".join(yaml_lines[:60]) + f"\n# ... ({len(yaml_lines) - 60} more lines)"
                else:
                    flow_snippet = "\n".join(yaml_lines)
            except Exception:
                flow_snippet = ""

        log_lines = _filter_digest_logcat(artifacts.get("logcat", ""), app_pkg, max_lines=max_log_lines)

        lines = [
            f"# Failure Digest — {flow_meta.get('ac', 'FLOW')}: {flow_meta.get('title', '')}",
            "",
            f"- **Flow:** `{flow_path}`",
            f"- **Likely Cause:** `{likely_cause}`",
            f"- **Focus Window:** `{artifacts.get('focus_window') or 'unknown'}`",
            f"- **Raw Artifacts:** screenshot=`{artifacts.get('screenshot') or 'none'}`, hierarchy=`{artifacts.get('hierarchy') or 'none'}`, logcat=`{artifacts.get('logcat') or 'none'}`",
            "",
            "## Maestro Error",
            "```text",
            _redact_pii(error_summary or "Assertion failed or element missing."),
            "```",
            "",
            "## Flow YAML",
            "```yaml",
            flow_snippet or "# (unavailable)",
            "```",
            "",
            f"## Visible UI Nodes (prioritized: {len(selected_nodes)} of {len(nodes)})",
            "```text",
            "\n".join(node_lines) if node_lines else "(no UI hierarchy captured)",
            "```",
            "",
            f"## Filtered Logcat ({len(log_lines)} lines)",
            "```text",
            "\n".join(log_lines) if log_lines else "(no relevant logcat lines captured)",
            "```",
            "",
        ]
        with open(digest_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return digest_path
    except Exception:
        return ""


def generate_issue_report(flow_meta, error_msg, artifacts, issues_dir, likely_cause="ASSERTION_FAILED"):
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
    digest = artifacts.get("digest", "")
    focus_window = artifacts.get("focus_window", "")

    evidence_parts = [f"- Likely Cause: `{likely_cause}`"]
    if focus_window:
        evidence_parts.append(f"- Focus Window: `{focus_window}`")
    if digest:
        evidence_parts.append(f"- Failure Digest (1-read): `{digest}`")
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


def start_token_tracking(track_enabled=True):
    """Starts or validates token tracking after all preconditions (flows, device, preflight, Maestro) pass.

    Returns a list of warning strings to be logged into progress.log.
    """
    if not track_enabled:
        return []
    mark = Path(".maestro/.run/token-start.json")
    # If spawned in an external Terminal by a parent suite-runner, reuse the fresh mark it just wrote
    if os.environ.get("MAESTRO_TOKEN_MARK_INHERITED") == "1" and mark.exists():
        try:
            data = json.loads(mark.read_text(encoding="utf-8"))
            if data.get("created_at"):
                return []
        except Exception:
            pass

    token_script = Path(__file__).with_name("token-usage.py")
    if not token_script.exists():
        msg = f"⚠️ Token tracking not started: script not found at {token_script}"
        print(msg)
        return [msg]

    warnings = []
    try:
        r = subprocess.run([sys.executable, str(token_script), "start"], capture_output=True, text=True)
        out_text = (r.stdout or "") + "\n" + (r.stderr or "")
        if r.returncode != 0:
            msg = f"⚠️ Token tracking failed to start (exit {r.returncode}): {out_text.strip()}"
            print(msg)
            warnings.append(msg)
        else:
            for line in out_text.splitlines():
                line_s = line.strip()
                if line_s.startswith("WARNING:"):
                    w_msg = f"⚠️ {line_s}"
                    print(w_msg)
                    warnings.append(w_msg)
    except Exception as e:
        msg = f"⚠️ Token tracking failed to start: {e}"
        print(msg)
        warnings.append(msg)
    return warnings


def write_token_report(out_dir, track_enabled=True):
    """Writes the token report at suite end when a session ran `token-usage.py start`.

    Done here rather than left to the session: a backgrounded or --open-terminal run returns at once,
    and the session moves on before the suite ends, so a report left to it gets skipped.
    """
    if not track_enabled:
        return ""
    mark = Path(".maestro/.run/token-start.json")
    if not mark.exists():
        line = "⚠️ No token-start mark — token usage not measured"
        print(line)
        return line
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


USER_HEADLESS_INTENT_RE = re.compile(r"(--headless|--no-terminal|\bheadless\b|\bno[- ]terminal\b)", re.IGNORECASE)


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _wait_for_terminal_child(
    sentinel_path: str,
    pid_path: str,
    result_path: str,
    timeout_s: float = 3600.0,
    startup_grace_s: float = 20.0,
    poll_interval_s: float = 0.5,
) -> tuple[int, str, bool]:
    """Blocks until the external Terminal child writes sentinel_path or exits unexpectedly.

    Returns (exit_code, result_text, child_started).
    """
    start = time.time()
    child_pid = None
    child_started = False

    try:
        while True:
            if os.path.isfile(sentinel_path):
                child_started = True
                break

            if child_pid is None and os.path.isfile(pid_path):
                try:
                    raw_pid = Path(pid_path).read_text(encoding="utf-8").strip()
                    if raw_pid.isdigit():
                        child_pid = int(raw_pid)
                        child_started = True
                except Exception:
                    pass

            elapsed = time.time() - start
            if not child_started and elapsed >= startup_grace_s:
                return 1, "⚠️ External Terminal runner did not start within startup grace period.", False

            if child_pid is not None and not _pid_is_alive(child_pid):
                # Brief grace for EXIT trap to flush sentinel file
                time.sleep(min(0.5, poll_interval_s))
                if os.path.isfile(sentinel_path):
                    break
                return 130, "⚠️ External Terminal window closed or process terminated before completion.", True

            if elapsed >= timeout_s:
                return 124, f"⚠️ Timed out waiting for external Terminal runner after {int(timeout_s)}s.", child_started

            time.sleep(poll_interval_s)
    except KeyboardInterrupt:
        return 130, "⚠️ Wait interrupted (Ctrl+C). External Terminal run may still be active.", child_started

    rc = 1
    try:
        raw_rc = Path(sentinel_path).read_text(encoding="utf-8").strip()
        if raw_rc.lstrip("-").isdigit():
            rc = int(raw_rc)
    except Exception:
        pass

    result_text = ""
    if os.path.isfile(result_path):
        try:
            result_text = Path(result_path).read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            pass

    return rc, result_text, True


def _user_requested_headless():
    """Returns True if the user's latest chat prompt explicitly requested --headless / --no-terminal,
    False if the user prompt did not request it, or None if no session transcript is active."""
    if os.environ.get("SUITE_RUNNER_ALLOW_HEADLESS") == "1":
        return True
    try:
        import glob as _glob
        path, fmt = None, "unknown"
        env_path = os.environ.get("CLAUDE_TRANSCRIPT_PATH")
        if env_path and os.path.isfile(env_path):
            path, fmt = env_path, "claude"
        elif os.environ.get("CLAUDECODE") == "1":
            proj = os.path.expanduser("~/.claude/projects/" + re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()))
            for k in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
                sid = os.environ.get(k)
                if sid and os.path.isfile(os.path.join(proj, f"{sid}.jsonl")):
                    path, fmt = os.path.join(proj, f"{sid}.jsonl"), "claude"
                    break
            if not path:
                files = _glob.glob(proj + "/*.jsonl")
                if files:
                    path, fmt = max(files, key=os.path.getmtime), "claude"
        if not path:
            conv_id = os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
            app_dir = os.environ.get("ANTIGRAVITY_APP_DATA_DIR", os.path.expanduser("~/.gemini/antigravity"))
            if conv_id and app_dir:
                cand = os.path.join(app_dir, "brain", conv_id, ".system_generated", "logs", "transcript.jsonl")
                if os.path.isfile(cand):
                    path, fmt = cand, "antigravity"
        if not path:
            brain_glob = _glob.glob(os.path.expanduser("~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl"))
            if brain_glob:
                newest = max(brain_glob, key=os.path.getmtime)
                if (dt.datetime.now().timestamp() - os.path.getmtime(newest)) / 60.0 < 30:
                    path, fmt = newest, "antigravity"
        if not path or not os.path.isfile(path):
            return None

        latest_user_text = ""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if fmt == "antigravity":
                    if o.get("type") == "USER_INPUT":
                        raw = o.get("content") or ""
                        m = re.search(r"<USER_REQUEST>(.*?)</USER_REQUEST>", raw, re.DOTALL)
                        latest_user_text = m.group(1).strip() if m else raw.strip()
                else:
                    if o.get("type") != "user":
                        continue
                    msg = o.get("message") or {}
                    c = msg.get("content")
                    text = (
                        c if isinstance(c, str)
                        else " ".join(b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text")
                    ).strip()
                    if not text:
                        continue
                    if text.startswith("Base directory for this skill"):
                        m_arg = re.search(r"^ARGUMENTS:\s*(.+)$", text, re.MULTILINE)
                        if m_arg:
                            latest_user_text = f"{latest_user_text} {m_arg.group(1)}".strip()
                        continue
                    if not o.get("isMeta") and ("<command-name>" in text or "<command-message>" in text or not text.startswith("<")):
                        latest_user_text = text
        if not latest_user_text:
            return None
        return bool(USER_HEADLESS_INTENT_RE.search(latest_user_text))
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="High-Volume E2E Test Suite Runner for Dev & QC")
    parser.add_argument("target", help="Folder of YAML flows, ticket folder, or single YAML file")
    parser.add_argument("-m", "--mode", choices=["repro", "step", "regression", "smoke"], help="Execution mode preset (repro, step, regression, smoke)")
    parser.add_argument(
        "--install",
        nargs="?",
        const="auto",
        default=None,
        metavar="APK_PATH",
        help="Install APK onto the locked device before running (auto-detects debug APK if omitted)",
    )
    parser.add_argument("--resume", action="store_true", help="Resume from previous checkpoint")
    parser.add_argument("--fail-fast", nargs="?", const=1, type=int, help="Stop after N failures (default 1)")
    parser.add_argument("--filter", help="Filter flows by keyword or tag (e.g. @smoke)")
    parser.add_argument("--device", help="ADB device ID")
    parser.add_argument("--no-reset", action="store_true", help="Skip app force-stop between tests")
    parser.add_argument("--headless", "--no-terminal", dest="headless", action="store_true", help="Run in current shell without external Terminal (when requested by user)")

    # Advanced / backward-compatible flags (hidden from default --help to keep CLI lean)
    parser.add_argument("--repro", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--app-pkg", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--splash-activity", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--require-env", help=argparse.SUPPRESS)
    parser.add_argument("--mock-gps", help=argparse.SUPPRESS)
    parser.add_argument("--skip-preflight", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output-dir", help=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--open-terminal", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--new-terminal", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-wait", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_terminal-child", dest="terminal_child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-token-track", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-device-lock", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--apk", dest="apk_path", help=argparse.SUPPRESS)

    args = parser.parse_args()

    # Guard against unprompted AI Agent `--headless` calls (honor `--headless` when run directly by user in TTY or requested in prompt)
    if args.headless and not args.dry_run and not args.terminal_child:
        is_agent_call = (
            os.environ.get("CLAUDECODE") == "1"
            or bool(os.environ.get("ANTIGRAVITY_CONVERSATION_ID"))
            or not sys.stdout.isatty()
        )
        if is_agent_call and _user_requested_headless() is False:
            print("⚠️ [guard] Ignoring unrequested `--headless` flag (user prompt did not request headless). Enforcing live Terminal window...")
            args.headless = False

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
        elif "repro" in target_lower:
            mode = "repro"
            is_auto_detected = True
        else:
            mode = "step"
            is_auto_detected = True

    # Apply Mode Presets (explicit user flags always have higher precedence)
    if mode == "repro":
        if args.filter is None:
            args.filter = "repro"
        if args.fail_fast is None:
            args.fail_fast = 1
        if not args.headless and not args.terminal_child and not args.open_terminal:
            args.open_terminal = True
    elif mode == "regression":
        args.resume = True
        if not args.headless and not args.terminal_child and not args.open_terminal:
            args.open_terminal = True
    elif mode == "step":
        # Run all flows in a step by default so every failure surfaces in one pass
        # (callers can still pass `--fail-fast 1` explicitly).
        if not args.headless and not args.terminal_child and not args.open_terminal:
            args.open_terminal = True
    elif mode == "smoke":
        if args.filter is None:
            args.filter = "@smoke"
        if args.fail_fast is None:
            args.fail_fast = 1
        if not args.headless and not args.terminal_child and not args.open_terminal:
            args.open_terminal = True

    # If --headless or internal --_terminal-child is active, disable --open-terminal
    if args.headless or args.terminal_child:
        args.open_terminal = False

    # Print Configuration Banner for complete visibility
    mode_label = (mode.upper() + (" (auto-detected)" if is_auto_detected else "")) if mode else "CUSTOM"
    if args.open_terminal:
        term_label = "EXTERNAL TERMINAL"
    elif args.terminal_child:
        term_label = "LIVE TERMINAL MONITOR"
    else:
        term_label = "IN-PROCESS (CURRENT SHELL)"
    ff_label = f"STOP AFTER {args.fail_fast} FAILURE(S)" if args.fail_fast else "RUN ALL"
    filter_label = f"'{args.filter}'" if args.filter else "NONE (ALL FLOWS)"
    install_target = args.apk_path or args.install
    install_label = f"YES ({install_target})" if install_target else "NO (PRE-INSTALLED)"
    run_time_str = dt.datetime.now().strftime("%H:%M:%S")

    print("=" * 70)
    print(f"⚙️  SUITE CONFIGURATION [{run_time_str}]:")
    print(f"   • Target:    {args.target}")
    print(f"   • Mode:      {mode_label}")
    print(f"   • Terminal:  {term_label}")
    print(f"   • Fail-Fast: {ff_label}")
    print(f"   • Filter:    {filter_label}")
    print(f"   • Install:   {install_label}")
    print("=" * 70)

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

    # Discover flows before starting token tracking or opening external Terminal
    flows = find_flows(target_str, args.filter)
    if not flows:
        sys.exit(f"No valid YAML flows found in '{args.target}' (resolved='{target_str}', filter='{args.filter or ''}')")

    # Auto-detect app package from flow appId headers (avoids hardcoded placeholder defaults)
    if not args.app_pkg:
        detected_pkg = detect_app_package(flows)
        if detected_pkg:
            args.app_pkg = detected_pkg
            print(f"📦 Auto-detected app package from flows: {args.app_pkg}")

    if args.dry_run:
        print(f"Discovered {len(flows)} flows in {args.target}:")
        for i, f in enumerate(flows, start=1):
            tag_str = f" [{' '.join(f['tags'])}]" if f["tags"] else ""
            step_str = f" [{f['step_title']}]" if f.get("step_title") else ""
            print(f"  {i:03d}.{step_str} {f['ac']}: {f['title']}{tag_str} ({f['path']})")
        sys.exit(0)

    # Detect device & run preflight before starting token tracking or spawning external Terminal
    enable_lock = not args.no_device_lock
    inherited_lock_pid = None
    if args.terminal_child:
        raw_parent_pid = os.environ.get("MAESTRO_LOCK_PARENT_PID", "").strip()
        if raw_parent_pid.isdigit():
            inherited_lock_pid = int(raw_parent_pid)
    device_id = detect_device(
        args.device,
        target=str(args.target),
        enable_lock=enable_lock,
        inherited_lock_pid=inherited_lock_pid,
    )
    os.environ["ANDROID_SERIAL"] = device_id

    lock_handed_off = False
    if enable_lock:
        atexit.register(lambda: release_device_lock(device_id) if not lock_handed_off else None)

    # Isolated APK installation on locked device if requested
    if args.install or args.apk_path:
        install_apk_on_device(device_id, args.install, args.apk_path)

    if not args.skip_preflight:
        req_envs = [e.strip() for e in args.require_env.split(",")] if args.require_env else None
        run_preflight_checks(device_id, args.app_pkg, req_envs, args.mock_gps)

    # Determine Maestro binary
    maestro_bin = MAESTRO
    if not os.path.exists(maestro_bin) and not shutil.which("maestro"):
        sys.exit(f"BLOCKED: Maestro CLI binary not found at '{maestro_bin}' or on PATH. Please install Maestro or verify ~/.maestro/bin/maestro.")

    # Auto token tracking: start only AFTER flows, device, preflight, and Maestro are verified,
    # and BEFORE spawning external Terminal so CLAUDECODE / ANTIGRAVITY_CONVERSATION_ID env vars are captured.
    track_tokens = not args.no_token_track
    token_start_warnings = start_token_tracking(track_tokens)

    # If --open-terminal is requested, spawn or reuse an external Terminal window on macOS
    # and block-wait for completion (unless --no-wait is passed) so callers never poll progress.log.
    if args.open_terminal:
        # Build child arguments using internal --_terminal-child to prevent recursive window spawns
        # Omit --install and --apk since APK was already installed onto the locked device above
        remaining_args = []
        skip_next = False
        raw_argv = sys.argv[1:]
        for i, a in enumerate(raw_argv):
            if skip_next:
                skip_next = False
                continue
            if a in ("--open-terminal", "--new-terminal", "--no-wait", "--headless", "--no-terminal"):
                continue
            if a in ("--apk",):
                skip_next = True
                continue
            if a.startswith("--apk="):
                continue
            if a == "--install":
                if i + 1 < len(raw_argv) and not raw_argv[i + 1].startswith("-"):
                    skip_next = True
                continue
            if a.startswith("--install="):
                continue
            remaining_args.append(a)

        if "--_terminal-child" not in remaining_args:
            remaining_args.append("--_terminal-child")
        if "--skip-preflight" not in remaining_args:
            remaining_args.append("--skip-preflight")
        if "--device" not in remaining_args:
            remaining_args.extend(["--device", device_id])
        script_path = os.path.abspath(sys.argv[0])
        cwd = os.getcwd()
        quoted_args = " ".join(shlex.quote(a) for a in remaining_args)
        child_cmd = f"python3 {shlex.quote(script_path)} {quoted_args}"

        # Write the banner, exports, cd, and python3 command to a short-path launcher script
        # in /tmp so Terminal's `do script` stays well under macOS's 1024-byte MAX_CANON PTY
        # input buffer limit (which otherwise truncates long worktree paths/banners before Enter).
        run_time = dt.datetime.now().strftime("%H:%M:%S")
        divider = "═" * 70
        monitor_title = f"Test Monitor [{device_id}]"
        wait_for_child = not args.no_wait
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir="/tmp",
            prefix="sr-monitor-",
            suffix=".sh",
            delete=False,
            encoding="utf-8",
        ) as tf:
            launcher_path = tf.name
            sentinel_path = f"{launcher_path}.done"
            pid_path = f"{launcher_path}.pid"
            result_path = f"{launcher_path}.result"
            tf.write("#!/usr/bin/env bash\n")
            if wait_for_child:
                tf.write(f"SENTINEL={shlex.quote(sentinel_path)}\n")
                tf.write(f"PIDFILE={shlex.quote(pid_path)}\n")
                tf.write("CHILD_RC=130\n")
                tf.write("_cleanup() {\n")
                tf.write("  local rc=$?\n")
                tf.write('  if [ ! -f "$SENTINEL" ]; then\n')
                tf.write('    printf \'%s\\n\' "${CHILD_RC:-$rc}" > "$SENTINEL"\n')
                tf.write("  fi\n")
                tf.write(f'  rm -f {shlex.quote(launcher_path)} "$PIDFILE"\n')
                tf.write("}\n")
                tf.write("trap '_cleanup' EXIT INT TERM HUP\n")
                tf.write('echo $$ > "$PIDFILE"\n')
            else:
                tf.write(f"trap 'rm -f {shlex.quote(launcher_path)}' EXIT\n")
            tf.write(f"printf '\\033]0;%s\\007' {shlex.quote(monitor_title)}\n")
            tf.write("clear\n")
            tf.write(
                "printf '\\033[1;36m%s\\n🔄 [%s] E2E RUN (%s): %s\\n%s\\033[0m\\n\\n' "
                f"{shlex.quote(divider)} {shlex.quote(run_time)} {shlex.quote(device_id)} "
                f"{shlex.quote(str(args.target))} {shlex.quote(divider)}\n"
            )
            if wait_for_child:
                tf.write(f"export MAESTRO_SUITE_RESULT_FILE={shlex.quote(result_path)}\n")
            tf.write(f"export MAESTRO_LOCK_PARENT_PID={os.getpid()}\n")
            tf.write("export MAESTRO_TOKEN_MARK_INHERITED=1\n")
            tf.write(f"export ANDROID_SERIAL={shlex.quote(device_id)}\n")
            tf.write(f'export PATH={shlex.quote(f"{PLATFORM_TOOLS}:{MAESTRO_BIN_DIR}")}:"$PATH"\n')
            tf.write(f"cd {shlex.quote(cwd)} || {{ CHILD_RC=1; exit 1; }}\n")
            tf.write(f"{child_cmd}\n")
            if wait_for_child:
                tf.write("CHILD_RC=$?\n")
                tf.write('printf \'%s\\n\' "$CHILD_RC" > "$SENTINEL"\n')
                tf.write('exit "$CHILD_RC"\n')
        os.chmod(launcher_path, 0o700)

        launch_cmd = f"bash {shlex.quote(launcher_path)}"

        # Support iTerm2 or macOS Terminal.app based on active environment
        term_program = os.environ.get("TERM_PROGRAM", "").lower()
        launched = False
        force_new_term = "true" if args.new_terminal else "false"
        escaped_cmd = launch_cmd.replace('\\', '\\\\').replace('"', '\\"')

        if "iterm" in term_program:
            iterm_script = f'''
            tell application "iTerm"
                activate
                set targetSession to missing value
                if not {force_new_term} then
                    repeat with w in windows
                        repeat with t in tabs of w
                            repeat with s in sessions of t
                                try
                                    if name of s contains "{monitor_title}" or name of w contains "{monitor_title}" then
                                        set targetSession to s
                                        select w
                                        select t
                                        select s
                                        exit repeat
                                    end if
                                end try
                            end repeat
                            if targetSession is not missing value then exit repeat
                        end repeat
                        if targetSession is not missing value then exit repeat
                    end repeat
                end if

                if targetSession is not missing value then
                    tell targetSession
                        write text "{escaped_cmd}"
                    end tell
                else
                    set newWindow to (create window with default profile)
                    tell current session of newWindow
                        write text "{escaped_cmd}"
                    end tell
                end if
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", iterm_script], check=True)
                launched = True
            except Exception:
                launched = False

        if not launched:
            terminal_script = f'''
            tell application "Terminal"
                activate
                set targetTab to missing value
                if not {force_new_term} then
                    repeat with w in windows
                        try
                            if name of w contains "{monitor_title}" and not (busy of selected tab of w) then
                                set targetTab to selected tab of w
                                set index of w to 1
                                exit repeat
                            end if
                        end try
                    end repeat
                end if

                if targetTab is not missing value then
                    do script "{escaped_cmd}" in targetTab
                else
                    do script "{escaped_cmd}"
                end if
            end tell
            '''
            try:
                subprocess.run(["osascript", "-e", terminal_script], check=True)
                launched = True
            except Exception as e:
                print(f"Warning: Could not launch Terminal window ({e}). Running in current process instead...")

        if not launched:
            for p_tmp in (launcher_path, sentinel_path, pid_path, result_path):
                try:
                    os.unlink(p_tmp)
                except OSError:
                    pass
        else:
            lock_handed_off = True
            reused_str = "reused existing" if not args.new_terminal else "new window"
            print(f"🚀 Successfully launched live monitor in external Terminal ({reused_str}) [{monitor_title}]!", flush=True)
            print(f"👉 Command executing: {child_cmd}", flush=True)
            if not wait_for_child:
                print("⏳ Tests are now running live in the external Terminal window (--no-wait).", flush=True)
                print("⛔ DO NOT re-run with --headless. Wait for `🏁 COMPLETED` in the progress log.", flush=True)
                return 0

            print("⏳ Waiting for external Terminal run to finish (do not poll progress.log)...", flush=True)
            wait_timeout = float(os.environ.get("SUITE_RUNNER_WAIT_TIMEOUT", "3600"))
            child_rc, result_text, child_started = _wait_for_terminal_child(
                sentinel_path,
                pid_path,
                result_path,
                timeout_s=wait_timeout,
            )
            for p_tmp in (sentinel_path, pid_path, result_path):
                try:
                    os.unlink(p_tmp)
                except OSError:
                    pass
            # release_device_lock only unlinks if the lock is still owned by THIS parent PID
            # (safe no-op when the child already took over and released it; cleans up if child died early).
            if enable_lock:
                release_device_lock(device_id)
            if not child_started:
                lock_handed_off = False
            if result_text:
                print("\n" + result_text, flush=True)
            return child_rc

    # For in-process or terminal-child runs, ensure lock is refreshed with current PID and cleanup registered
    if enable_lock:
        acquire_device_lock(device_id, str(args.target))
        setup_lock_cleanup(device_id)

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
    if token_start_warnings:
        with open(progress_log, "a", encoding="utf-8") as f:
            for w in token_start_warnings:
                f.write(f"{w}\n")

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
    interrupted = False
    failed_summaries: list[str] = []

    # ANSI color codes for rich live Terminal streaming
    CLR_LINE = "\033[2K\r"
    C_RESET = "\033[0m" if is_tty else ""
    C_GREEN = "\033[1;32m" if is_tty else ""
    C_RED = "\033[1;31m" if is_tty else ""
    C_YELLOW = "\033[1;33m" if is_tty else ""
    C_CYAN = "\033[1;36m" if is_tty else ""
    C_DIM = "\033[2m" if is_tty else ""

    popup_rules = load_popup_rules(target_str)

    try:
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

            # Teardown / Reset before executing flow (skip redundant am start if flow calls launchApp)
            if not args.no_reset:
                reset_app_state(
                    args.app_pkg,
                    args.splash_activity,
                    device_id,
                    skip_launch=flow_uses_launch_app(flow_path),
                )

            debug_dir = os.path.join(out_dir, "debug", f"{idx:03d}_{ac}")
            run_res = run_maestro_flow(maestro_bin, device_id, flow_path, debug_dir)
            duration_s = int(round(run_res["duration"]))

            # Safe overlay recovery + 1 warm retry (never force-stops on retry so session-seen flags stay intact)
            artifacts = None
            dismiss_note = ""
            if not run_res["passed"]:
                artifacts = capture_failure_artifacts(device_id, debug_dir, ac)
                dismissed, rule_name = try_dismiss_overlay(
                    device_id,
                    artifacts.get("hierarchy", ""),
                    artifacts.get("focus_window", ""),
                    flow_path,
                    popup_rules,
                    debug_dir,
                    ac,
                )
                if dismissed:
                    print(f"\n          🔄 Dismissed overlay [{rule_name}], warm-retrying {ac}...", flush=True)
                    retry_res = run_maestro_flow(maestro_bin, device_id, flow_path, debug_dir)
                    duration_s += int(round(retry_res["duration"]))
                    run_res = retry_res
                    dismiss_note = f"(overlay dismissed: {rule_name})"
                    if run_res["passed"]:
                        artifacts = None

            if run_res["passed"]:
                verified_count += 1
                warn_extra = f" {run_res['warning']}" if run_res.get("warning") else ""
                note_extra = f" {dismiss_note}" if dismiss_note else ""
                log_line = f"{step_prefix}[{idx:03d}/{total:03d}] ✅ {ac}: {title} - verified - {verified_count}/{total} [{duration_s}s]{warn_extra}{note_extra}"
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
                if artifacts is None:
                    artifacts = capture_failure_artifacts(device_id, debug_dir, ac)

                likely_cause, evidence_lines, overlay_hints = classify_failure(
                    run_res["error_summary"],
                    artifacts.get("focus_window", ""),
                    artifacts.get("hierarchy", ""),
                    artifacts.get("logcat", ""),
                    args.app_pkg,
                )

                digest_path = generate_failure_digest(
                    flow,
                    run_res["error_summary"],
                    artifacts,
                    debug_dir,
                    likely_cause=likely_cause,
                    app_pkg=args.app_pkg,
                )
                if digest_path:
                    artifacts["digest"] = digest_path

                log_line = f"{step_prefix}[{idx:03d}/{total:03d}] ❌ {ac}: {title} - FAILED [{likely_cause}] [{duration_s}s]"
                if is_tty:
                    print(f"{CLR_LINE}{C_RED}{log_line}{C_RESET}", flush=True)
                else:
                    print(f"{log_line}", flush=True)

                print(f"          ├── 🔎 Likely Cause: {likely_cause}")
                for ev in evidence_lines:
                    print(f"          ├── {ev}")
                if digest_path:
                    print(f"          ├── 📄 Digest (1-read): {digest_path}")
                if artifacts.get("screenshot"):
                    print(f"          ├── 📸 Snapshot: {artifacts['screenshot']}")
                if artifacts.get("hierarchy"):
                    print(f"          ├── 🔍 UI Hierarchy: {artifacts['hierarchy']}")

                issue_path = ""
                if likely_cause == "BLOCKED_BY_OVERLAY":
                    print("          ├── 🚧 Blocked by overlay/dialog — skipping false defect report in issues/.")
                    if overlay_hints:
                        print(f"          ├── 🖱️  Visible overlay nodes: {' | '.join(overlay_hints[:5])}")
                    print("          └── 💡 Next: inspect once via MCP, dismiss/save rule to .maestro/_shared/popups.json, then run `--resume --no-reset`.", flush=True)
                else:
                    issue_path = generate_issue_report(flow, run_res["error_summary"], artifacts, str(issues_dir), likely_cause=likely_cause)
                    print(f"          └── 📝 ISSUE LOGGED: {issue_path}", flush=True)

                fail_summary_parts = [f"❌ {ac}: {title} [{likely_cause}]"]
                if digest_path:
                    fail_summary_parts.append(f"digest={digest_path}")
                if issue_path:
                    fail_summary_parts.append(f"issue={issue_path}")
                failed_summaries.append(" | ".join(fail_summary_parts))

                cp_entry = {
                    "status": "FAILED",
                    "likely_cause": likely_cause,
                    "step": current_step,
                    "ac": ac,
                    "title": title,
                    "duration": duration_s,
                    "evidence": artifacts,
                }
                if issue_path:
                    cp_entry["issue"] = issue_path
                checkpoint_data.setdefault("completed", {})[flow_path] = cp_entry
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
    except KeyboardInterrupt:
        interrupted = True
        msg = "\n🛑 Suite interrupted by user (Ctrl+C). Writing summary and token report..."
        print(msg, flush=True)
        with open(progress_log, "a", encoding="utf-8") as f:
            f.write(f"{msg.strip()}\n")

    total_suite_duration = time.time() - start_suite_time
    mins, secs = divmod(int(total_suite_duration), 60)

    # Print Final Summary Banner
    print("\n" + "=" * 70)
    status_label = "INTERRUPTED" if interrupted else "COMPLETED"
    final_banner = f"🏁 {status_label}: ✅ {verified_count} Passed | ❌ {failed_count} Failed | Total: {total} | Duration: {mins}m {secs}s"
    if is_tty:
        c_final = C_GREEN if (failed_count == 0 and not interrupted) else C_RED
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
    token_line = write_token_report(out_dir, track_tokens)

    # Write final progress log lines and optional parent-waiter result summary
    with open(progress_log, "a", encoding="utf-8") as f:
        if token_line:
            f.write(f"{token_line}\n")
        f.write(f"{final_banner}\n")
        f.write(f"📊 Summary report: {summary_md_path}\n")

    result_file = os.environ.get("MAESTRO_SUITE_RESULT_FILE")
    if result_file:
        try:
            summary_lines = [final_banner]
            if failed_summaries:
                summary_lines.append("Failed flows (1-read digest first):")
                summary_lines.extend(f"  - {line}" for line in failed_summaries)
            summary_lines.append(f"📊 Summary report: {summary_md_path}")
            summary_lines.append(f"📜 Progress log: {progress_log}")
            if token_line:
                summary_lines.append(token_line)
            Path(result_file).write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
        except Exception:
            pass

    if enable_lock:
        release_device_lock(device_id)
    if interrupted:
        return 130
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
