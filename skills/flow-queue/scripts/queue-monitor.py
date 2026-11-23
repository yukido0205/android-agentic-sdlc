#!/usr/bin/env python3
"""Worktree initializer and one-shot status helper for /flow-queue."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path

LOCK_DIR = Path("/tmp/android_device_locks")
GRADLE_LOCK_DIR = Path("/tmp/android_gradle_locks")
PHASE_NAMES = {"0": "Init", "1": "Ground", "2": "Build", "3": "Prove", "4": "Ship", "5": "Feedback"}


def find_repo_root() -> Path:
    """Resolve main git repository root even when invoked inside a worktree."""
    res = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip() not in ("", ".git"):
        return Path(res.stdout.strip()).resolve().parent
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(top.stdout.strip()).resolve() if top.returncode == 0 else Path.cwd().resolve()


def read_device_locks() -> dict[str, dict]:
    """Read active device mutex locks created by suite-runner.py."""
    locks: dict[str, dict] = {}
    if not LOCK_DIR.exists():
        return locks
    for f in sorted(LOCK_DIR.glob("*.lock")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            pid = int(data.get("pid") or 0)
            if pid <= 0 or time.time() - data.get("acquired_at", 0) > 3600:
                continue
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            except PermissionError:
                pass
            locks[data.get("device_id", f.stem)] = data
        except (ValueError, OSError, json.JSONDecodeError):
            continue
    return locks


def read_gradle_locks() -> tuple[dict[str, dict], list[dict]]:
    """Read active Gradle build slots (via non-blocking flock probe) and waiting queue."""
    active: dict[str, dict] = {}
    waiting: list[dict] = []
    if not GRADLE_LOCK_DIR.exists():
        return active, waiting

    for f in sorted(GRADLE_LOCK_DIR.glob("slot-*.lock")):
        try:
            fd = os.open(f, os.O_RDONLY)
        except OSError:
            continue
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raw = os.read(fd, 4096).decode("utf-8", errors="replace").strip()
                try:
                    data = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    data = {}
                active[f.stem] = data
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    for wf in sorted(GRADLE_LOCK_DIR.glob("wait-*.json")):
        try:
            data = json.loads(wf.read_text(encoding="utf-8"))
            pid = int(data.get("pid") or 0)
            if pid <= 0:
                continue
            os.kill(pid, 0)
            waiting.append(data)
        except ProcessLookupError:
            wf.unlink(missing_ok=True)
        except PermissionError:
            waiting.append(data)
        except (ValueError, OSError, json.JSONDecodeError):
            continue

    return active, waiting


def list_adb_devices() -> list[str]:
    """Return connected ADB device serials with a short timeout."""
    adb = shutil.which("adb") or os.path.expanduser("~/Library/Android/sdk/platform-tools/adb")
    if not adb or not os.path.exists(adb):
        return []
    try:
        res = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=2)
        return [line.split()[0] for line in res.stdout.splitlines()[1:] if "\tdevice" in line]
    except Exception:
        return []


def parse_state_file(path: Path) -> dict[str, str]:
    """Extract phase, gate, track, step, and waiting marker from header lines."""
    header = " ".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[:5])
    kind = "bug" if path.name == "flow-bug.md" else ("task" if path.name == "flow-task.md" else "epic")
    def grab(pat: str, default: str) -> str:
        m = re.search(pat, header, re.IGNORECASE)
        return m.group(1) if m else default

    return {
        "kind": kind,
        "phase": grab(r"Phase:\s*(\d+)", "?"),
        "gate": grab(r"Gate passed:\s*(\d+)", "0"),
        "track": grab(r"Track:\s*([A-Za-z0-9_-]+)", "-"),
        "step": grab(r"Step:\s*([0-9]+/[0-9]+)", "-"),
        "waiting": grab(r"WAITING[_ ]GATE[_ ](\d)", ""),
    }


def collect_tickets(
    repo_root: Path,
    locks: dict[str, dict],
    gradle_active: dict[str, dict] | None = None,
    gradle_waiting: list[dict] | None = None,
) -> list[dict[str, str]]:
    """Collect ticket state across root plans/ and .worktrees/*/plans/."""
    tickets: dict[str, dict[str, str]] = {}
    building_tickets = {str(v.get("ticket", "")).upper(): v for v in (gradle_active or {}).values() if v.get("ticket")}
    waiting_tickets = {str(v.get("ticket", "")).upper(): v for v in (gradle_waiting or []) if v.get("ticket")}

    def scan_plans(base: Path) -> None:
        if not base.exists():
            return
        for pdir in sorted(d for d in base.iterdir() if d.is_dir()):
            for fname in ("flow-bug.md", "flow-task.md", "PLAN.md"):
                fpath = pdir / fname
                if fpath.is_file():
                    tickets[pdir.name] = {**parse_state_file(fpath), "ticket": pdir.name}
                    break

    scan_plans(repo_root / "plans")
    wt_root = repo_root / ".worktrees"
    if wt_root.exists():
        for wt in sorted(d for d in wt_root.iterdir() if d.is_dir()):
            tickets.setdefault(wt.name, {"ticket": wt.name, "kind": "-", "phase": "0", "gate": "0", "track": "-", "step": "-", "waiting": ""})
            scan_plans(wt / "plans")

    for ticket, row in tickets.items():
        dev = next((d for d, l in locks.items() if ticket.upper() in str(l.get("target", "")).upper()), "-")
        row["device"] = dev
        t_upper = ticket.upper()
        if dev != "-":
            row["status"] = "⚙️  E2E RUNNING"
        elif t_upper in building_tickets:
            tasks = " ".join(building_tickets[t_upper].get("tasks") or [])
            row["status"] = f"🔨 BUILDING ({tasks[:24]})" if tasks else "🔨 BUILDING"
        elif t_upper in waiting_tickets:
            row["status"] = "⏳ WAIT BUILD"
        elif row["waiting"]:
            row["status"] = f"🔔 WAITING GATE {row['waiting']}"
        elif row["gate"] == "3":
            row["status"] = "✅ READY / SHIPPED"
        elif row["phase"] == "0":
            row["status"] = "⏳ WORKTREE READY"
        else:
            row["status"] = f"🔄 PHASE {row['phase']}"
    return list(tickets.values())


def render_dashboard(repo_root: Path) -> str:
    """Render ANSI queue status, Gradle build slots, and emulator pool dashboard."""
    locks, devices = read_device_locks(), list_adb_devices()
    gradle_active, gradle_waiting = read_gradle_locks()
    rows = collect_tickets(repo_root, locks, gradle_active, gradle_waiting)
    now, div = dt.datetime.now().strftime("%H:%M:%S"), "═" * 82
    out = [
        f"\033[1;36m{div}\033[0m",
        f"\033[1;36m🚀 SDLC QUEUE MONITOR [{now}] — Tickets: {len(rows)} | Builds: {len(gradle_active)} | Devices: {len(devices)} | Locks: {len(locks)}\033[0m",
        f"\033[1;36m{div}\033[0m",
        f"{'TICKET':<12} {'TYPE':<6} {'TRACK':<7} {'PHASE':<13} {'GATE':<5} {'DEVICE':<15} {'STATUS'}",
        "─" * 82,
    ]
    waiting = []
    if not rows:
        out.append("  (No active worktrees or plans/*/flow-*.md found)")
    for r in rows:
        p_label = f"P{r['phase']} [{r['step']}]" if r["step"] != "-" else f"P{r['phase']} ({PHASE_NAMES.get(r['phase'], '?')})"
        if r["waiting"]:
            waiting.append(f"{r['ticket']}:G{r['waiting']}")
        out.append(f"{r['ticket']:<12} {r['kind']:<6} {r['track']:<7} {p_label:<13} {r['gate']}/3   {r['device']:<15} {r['status']}")

    out.extend(["─" * 82, "🔧 BUILD SLOTS:"])
    if not gradle_active and not gradle_waiting:
        out.append("  • Idle (no active Gradle builds)")
    for slot_name, info in sorted(gradle_active.items()):
        age = int(time.time() - info.get("acquired_at", time.time()))
        tasks = " ".join(info.get("tasks") or []) or "gradlew"
        out.append(f"  • {slot_name:<16}: 🔨 BUILDING ({info.get('ticket', '?')}: {tasks}, {age}s)")
    for w in gradle_waiting:
        age = int(time.time() - w.get("waiting_since", time.time()))
        out.append(f"  • {'waiting':<16}: ⏳ {w.get('ticket', '?')} queued for build slot ({age}s)")

    out.extend(["─" * 82, "📱 EMULATOR POOL:"])
    if not devices and not locks:
        out.append("  • No active ADB devices connected")
    for dev in sorted(set(devices) | set(locks.keys())):
        if dev in locks:
            age = int(time.time() - locks[dev].get("acquired_at", time.time()))
            out.append(f"  • {dev:<16}: 🔒 LOCKED ({locks[dev].get('target', '?')}, {age}s)")
        else:
            out.append(f"  • {dev:<16}: 🟢 IDLE (Ready for lease)")
    out.append(div)
    if waiting:
        out.append(f"\033[1;33m💡 Action Required in Chat: {', '.join(waiting)}\033[0m")
    return "\n".join(out)


def _find_init_script(repo_root: Path) -> Path | None:
    cands = [
        repo_root / "scripts" / "init_worktree.py",
        Path(__file__).resolve().parents[3] / "scripts" / "init_worktree.py",
        repo_root / ".agents" / "scripts" / "init_worktree.py",
        repo_root / ".claude" / "scripts" / "init_worktree.py",
    ]
    return next((p for p in cands if p.is_file()), None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Worktree initializer and one-shot status helper for /flow-queue")
    parser.add_argument("--init", nargs="+", metavar="TICKET", help="Initialize isolated worktrees for tickets")
    parser.add_argument("--once", action="store_true", help="Print status snapshot once and exit")
    args = parser.parse_args()

    repo_root = find_repo_root()
    if args.init:
        init_py = _find_init_script(repo_root)
        if not init_py:
            sys.exit("❌ Missing init_worktree.py in repo/scripts or installed skill root")
        for t in args.init:
            if subprocess.run([sys.executable, str(init_py), t], cwd=repo_root).returncode != 0:
                sys.exit(f"❌ Failed initializing worktree for {t}")

    print(render_dashboard(repo_root))


if __name__ == "__main__":
    main()
