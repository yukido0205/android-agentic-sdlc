#!/usr/bin/env python3
"""scripts/gradle-build.py — Native OS-level Gradle Build Lock wrapper for multi-worktree builds.

Serializes heavy ./gradlew invocations across parallel worktrees using fcntl.flock()
semaphores (/tmp/android_gradle_locks/slot-*.lock) without modifying any project
gradle.properties or Gradle config. Kernel automatically releases locks on SIGKILL.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

LOCK_DIR = Path("/tmp/android_gradle_locks")
EX_TEMPFAIL = 75
READ_ONLY_FLAGS = {"--version", "-v", "--help", "-h", "--status"}


def find_gradlew(explicit: str | None) -> Path:
    """Locate ./gradlew from explicit path or walking up from cwd."""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.is_file():
            sys.exit(f"❌ Error: Gradle wrapper not found at '{p}'.")
        return p

    cur = Path.cwd().resolve()
    for parent in (cur, *cur.parents):
        cand = parent / "gradlew"
        if cand.is_file():
            return cand
        if (parent / ".git").exists():
            break
    sys.exit("❌ Error: './gradlew' not found in current directory or parent repository.")


def infer_ticket(cwd: Path, explicit: str | None) -> str:
    """Infer ticket identifier from .worktrees/<TICKET> path or directory name."""
    if explicit:
        return explicit.strip()
    parts = cwd.parts
    if ".worktrees" in parts:
        idx = parts.index(".worktrees")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return cwd.name or "root"


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """Parse wrapper-only options while passing all Gradle args/tasks verbatim."""
    if argv in (["--help"], ["-h"], ["--wrapper-help"]):
        show_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--slots", type=int, default=int(os.environ.get("ANDROID_SDLC_GRADLE_SLOTS", "1")))
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=float(os.environ.get("ANDROID_SDLC_GRADLE_WAIT_TIMEOUT", "180")),
    )
    parser.add_argument("--ticket", default=None)
    parser.add_argument("--gradlew", default=None)

    if "--" in argv:
        idx = argv.index("--")
        wrapper_argv, gradle_args = argv[:idx], argv[idx + 1 :]
        ns, unknown = parser.parse_known_args(wrapper_argv)
        gradle_args = [*unknown, *gradle_args]
    else:
        ns, gradle_args = parser.parse_known_args(argv)

    ns.slots = max(1, ns.slots)
    ns.wait_timeout = max(0.0, ns.wait_timeout)
    return ns, gradle_args


def show_help() -> None:
    print(
        "Usage: python3 scripts/gradle-build.py [wrapper options] [--] <gradlew args/tasks...>\n\n"
        "Wrapper options:\n"
        "  --slots <N>           Max concurrent Gradle builds (env: ANDROID_SDLC_GRADLE_SLOTS, default: 1)\n"
        "  --wait-timeout <SEC>  Max seconds to wait for a build slot before returning exit 75 (default: 180)\n"
        "  --ticket <NAME>       Override ticket label recorded in lock metadata\n"
        "  --gradlew <PATH>      Path to gradlew executable (default: auto-detect from cwd)\n"
        "  --wrapper-help        Show this help message\n\n"
        "Examples:\n"
        "  python3 scripts/gradle-build.py assembleDebug\n"
        "  python3 scripts/gradle-build.py :app:testDebugUnitTest --tests '*Cart*'\n"
        "  python3 scripts/gradle-build.py --slots 2 --max-workers=4 assembleDebug"
    )


def inject_max_workers(gradle_args: list[str], cwd: Path) -> list[str]:
    """Inject --max-workers=<N> inside .worktrees/ unless already specified or disabled."""
    if any(a == "--max-workers" or a.startswith("--max-workers=") for a in gradle_args):
        return gradle_args

    env_val = os.environ.get("ANDROID_SDLC_GRADLE_WORKERS", "").strip().lower()
    if env_val in ("0", "auto", "off", "false"):
        return gradle_args

    if env_val.isdigit():
        workers = int(env_val)
    elif ".worktrees" in cwd.parts:
        workers = 2
    else:
        return gradle_args

    if workers <= 0:
        return gradle_args
    return [*gradle_args, f"--max-workers={workers}"]


def _read_slot_holder(slot_path: Path) -> dict | None:
    """Probe a slot file; return metadata dict if actively locked, else None."""
    try:
        fd = os.open(slot_path, os.O_RDONLY)
    except OSError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raw = os.read(fd, 4096).decode("utf-8", errors="replace").strip()
            try:
                return json.loads(raw) if raw else {"ticket": "unknown"}
            except json.JSONDecodeError:
                return {"ticket": "unknown"}
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


def list_active_holders(slots: int) -> list[dict]:
    """Return metadata for all currently locked build slots."""
    if not LOCK_DIR.exists():
        return []
    holders: list[dict] = []
    seen: set[Path] = set()
    candidates = [LOCK_DIR / f"slot-{i}.lock" for i in range(slots)] + sorted(LOCK_DIR.glob("slot-*.lock"))
    for p in candidates:
        if p in seen or not p.exists():
            continue
        seen.add(p)
        info = _read_slot_holder(p)
        if info is not None:
            holders.append(info)
    return holders


def format_holders(holders: list[dict]) -> str:
    if not holders:
        return "another process"
    return ", ".join(f"{h.get('ticket', '?')}(pid:{h.get('pid', '?')})" for h in holders)


def try_acquire_slot(slots: int, meta: dict) -> tuple[int, Path] | None:
    """Attempt non-blocking flock across slot-0..slot-{slots-1}."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(meta).encode("utf-8")
    for idx in range(slots):
        slot_path = LOCK_DIR / f"slot-{idx}.lock"
        fd = os.open(slot_path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            continue
        except Exception:
            os.close(fd)
            raise
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, payload)
        return fd, slot_path
    return None


def release_slot(fd: int) -> None:
    """Clear metadata and release flock without unlinking slot file (avoids inode races)."""
    try:
        os.ftruncate(fd, 0)
    except OSError:
        pass
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def acquire_with_wait(slots: int, wait_timeout: float, ticket: str, cwd: Path, tasks: list[str]) -> int:
    """Acquire an OS build slot, waiting up to wait_timeout seconds before returning exit 75."""
    meta = {
        "pid": os.getpid(),
        "ticket": ticket,
        "cwd": str(cwd),
        "tasks": tasks,
        "acquired_at": time.time(),
    }
    acquired = try_acquire_slot(slots, meta)
    if acquired is not None:
        return acquired[0]

    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    wait_file = LOCK_DIR / f"wait-{os.getpid()}.json"
    holders = list_active_holders(slots)
    sys.stderr.write(
        f"[gradle-build] Build slot busy (active: {format_holders(holders)}). "
        f"Waiting up to {wait_timeout:g}s...\n"
    )
    sys.stderr.flush()

    try:
        wait_file.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "ticket": ticket,
                    "cwd": str(cwd),
                    "tasks": tasks,
                    "waiting_since": time.time(),
                }
            ),
            encoding="utf-8",
        )
        deadline = time.monotonic() + wait_timeout
        while time.monotonic() < deadline:
            time.sleep(min(0.5, max(0.05, deadline - time.monotonic())))
            meta["acquired_at"] = time.time()
            acquired = try_acquire_slot(slots, meta)
            if acquired is not None:
                return acquired[0]
    finally:
        wait_file.unlink(missing_ok=True)

    holders = list_active_holders(slots)
    sys.stderr.write(
        f"[BUILD_SLOT_BUSY] Another worktree ({format_holders(holders)}) is currently building. "
        f"Wait timed out after {wait_timeout:g}s. Do NOT edit code — re-run this exact command to retry.\n"
    )
    sys.stderr.flush()
    sys.exit(EX_TEMPFAIL)


def run_gradlew(gradlew: Path, gradle_args: list[str]) -> int:
    """Run ./gradlew and forward termination signals so child processes never orphan."""
    cmd = [str(gradlew), *gradle_args] if os.access(gradlew, os.X_OK) else ["bash", str(gradlew), *gradle_args]
    proc = subprocess.Popen(cmd)

    def forward_signal(signum: int, _frame) -> None:
        if proc.poll() is None:
            try:
                proc.send_signal(signum)
            except OSError:
                pass

    prev_int = signal.signal(signal.SIGINT, forward_signal)
    prev_term = signal.signal(signal.SIGTERM, forward_signal)
    try:
        return proc.wait()
    finally:
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def main() -> None:
    ns, gradle_args = parse_args(sys.argv[1:])
    if not gradle_args:
        show_help()
        sys.exit(2)

    cwd = Path.cwd().resolve()
    gradlew = find_gradlew(ns.gradlew)

    if all(arg in READ_ONLY_FLAGS for arg in gradle_args):
        sys.exit(run_gradlew(gradlew, gradle_args))

    if "--stop" in gradle_args:
        holders = list_active_holders(ns.slots)
        if holders:
            sys.stderr.write(
                f"[BUILD_SLOT_BUSY] Refusing to run '--stop' while another build slot is active "
                f"({format_holders(holders)}).\n"
            )
            sys.exit(EX_TEMPFAIL)
        sys.exit(run_gradlew(gradlew, gradle_args))

    ticket = infer_ticket(cwd, ns.ticket)
    final_args = inject_max_workers(gradle_args, cwd)
    tasks_preview = [a for a in gradle_args if not a.startswith("-")][:3] or gradle_args[:2]

    fd = acquire_with_wait(ns.slots, ns.wait_timeout, ticket, cwd, tasks_preview)
    try:
        rc = run_gradlew(gradlew, final_args)
    finally:
        release_slot(fd)
    sys.exit(rc)


if __name__ == "__main__":
    main()
