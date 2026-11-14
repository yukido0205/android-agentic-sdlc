#!/usr/bin/env python3
"""Zero-token real-time monitor and worktree initializer for /flow-queue."""

from __future__ import annotations

import argparse
import datetime as dt
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path

LOCK_DIR = Path("/tmp/android_device_locks")
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


def collect_tickets(repo_root: Path, locks: dict[str, dict]) -> list[dict[str, str]]:
    """Collect ticket state across root plans/ and .worktrees/*/plans/."""
    tickets: dict[str, dict[str, str]] = {}

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
        if dev != "-":
            row["status"] = "⚙️  E2E RUNNING"
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
    """Render ANSI queue status and emulator pool dashboard."""
    locks, devices = read_device_locks(), list_adb_devices()
    rows = collect_tickets(repo_root, locks)
    now, div = dt.datetime.now().strftime("%H:%M:%S"), "═" * 82
    out = [
        f"\033[1;36m{div}\033[0m",
        f"\033[1;36m🚀 SDLC QUEUE MONITOR [{now}] — Tickets: {len(rows)} | Devices: {len(devices)} | Active Locks: {len(locks)}\033[0m",
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


def open_external_terminal(script_path: Path, repo_root: Path, interval: float) -> bool:
    """Launch or reuse an external macOS Terminal / iTerm2 live monitor window."""
    title = "SDLC Queue Monitor"
    cmd = f"printf '\\033]0;{title}\\007' && cd \"{repo_root}\" && python3 \"{script_path}\" --_terminal-child --interval {interval}"
    esc = cmd.replace("\\", "\\\\").replace('"', '\\"')
    if "iterm" in os.environ.get("TERM_PROGRAM", "").lower():
        osa = f'tell application "iTerm"\nactivate\nrepeat with w in windows\nrepeat with s in sessions of current tab of w\nif name of s contains "{title}" then\ntell s to write text "{esc}"\nreturn\nend if\nend repeat\nend repeat\ntell current session of (create window with default profile) to write text "{esc}"\nend tell'
    else:
        osa = f'tell application "Terminal"\nactivate\nrepeat with w in windows\nif name of w contains "{title}" then\ndo script "{esc}" in selected tab of w\nset index of w to 1\nreturn\nend if\nend repeat\ndo script "{esc}"\nend tell'
    return subprocess.run(["osascript", "-e", osa], capture_output=True).returncode == 0


def _find_init_script(repo_root: Path) -> Path | None:
    cands = [
        repo_root / "scripts" / "init_worktree.py",
        Path(__file__).resolve().parents[3] / "scripts" / "init_worktree.py",
        repo_root / ".agents" / "scripts" / "init_worktree.py",
        repo_root / ".claude" / "scripts" / "init_worktree.py",
    ]
    return next((p for p in cands if p.is_file()), None)


def main() -> None:
    parser = argparse.ArgumentParser(description="0-token SDLC Queue Live Monitor")
    parser.add_argument("--init", nargs="+", metavar="TICKET", help="Initialize isolated worktrees for tickets")
    parser.add_argument("--open-terminal", action="store_true", help="Launch live watch window in macOS Terminal/iTerm")
    parser.add_argument("--once", action="store_true", help="Print status snapshot once and exit")
    parser.add_argument("--interval", type=float, default=1.0, help="Refresh interval in seconds")
    parser.add_argument("--_terminal-child", dest="terminal_child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    repo_root = find_repo_root()
    if args.init:
        init_py = _find_init_script(repo_root)
        if not init_py:
            sys.exit("❌ Missing init_worktree.py in repo/scripts or installed skill root")
        for t in args.init:
            if subprocess.run([sys.executable, str(init_py), t], cwd=repo_root).returncode != 0:
                sys.exit(f"❌ Failed initializing worktree for {t}")

    if args.open_terminal and not args.terminal_child:
        if open_external_terminal(Path(__file__).resolve(), repo_root, args.interval):
            print("🖥️  Opened live 'SDLC Queue Monitor' terminal window (0 LLM tokens).")
            return
        print("⚠️ Could not open external Terminal; printing snapshot instead.\n")

    if args.once or not args.terminal_child:
        print(render_dashboard(repo_root))
        return

    try:
        while True:
            sys.stdout.write("\033[2J\033[H" + render_dashboard(repo_root) + "\n")
            sys.stdout.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n👋 SDLC Queue Monitor stopped.")


if __name__ == "__main__":
    main()
