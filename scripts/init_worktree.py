#!/usr/bin/env python3
"""scripts/init_worktree.py — Zero-Token Android Worktree Initializer for Parallel Agent Sessions.

Automates the creation of git worktrees under `.worktrees/<TICKET>`, symlinks critical Android
and Agent config files (local.properties, keystore.properties, google-services.json, .agents/, .claude/),
and enforces `org.gradle.workers.max=2` in `gradle.properties` to prevent Mac RAM exhaustion.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys


def run_cmd(cmd: list[str], check: bool = True, cwd: str | None = None) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True, check=check, cwd=cwd)
    return res.stdout.strip()


def get_repo_root() -> pathlib.Path:
    try:
        toplevel = run_cmd(["git", "rev-parse", "--show-toplevel"])
        common_dir = run_cmd(["git", "rev-parse", "--git-common-dir"])
        if common_dir and common_dir != ".git":
            return pathlib.Path(common_dir).resolve().parent
        return pathlib.Path(toplevel).resolve()
    except Exception as e:
        sys.exit(f"❌ Error: Not inside a git repository ({e}).")


def ensure_gitignore(repo_root: pathlib.Path) -> None:
    gitignore = repo_root / ".gitignore"
    entry = ".worktrees/"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if entry not in content:
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write(f"\n# Git worktrees for parallel agent sessions\n{entry}\n")
            print("📝 Added .worktrees/ to .gitignore")
    else:
        gitignore.write_text(f"# Git worktrees for parallel agent sessions\n{entry}\n", encoding="utf-8")
        print("📝 Created .gitignore with .worktrees/")


def symlink_item(src: pathlib.Path, dst: pathlib.Path, repo_root: pathlib.Path) -> None:
    if not src.exists() and not src.is_symlink():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.exists():
        if dst.is_dir() and not dst.is_symlink():
            import shutil
            shutil.rmtree(dst)
        else:
            dst.unlink(missing_ok=True)
    dst.symlink_to(src.resolve())
    try:
        rel_dst = dst.relative_to(repo_root)
    except ValueError:
        rel_dst = dst
    print(f"   🔗 Symlinked: {src.name} -> {rel_dst}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Zero-Token Android Worktree Initializer for Parallel Agent Sessions")
    parser.add_argument("ticket", help="Ticket identifier (e.g. PAY-101, PROJ-123, BUG-404)")
    parser.add_argument("-b", "--branch", help="Custom branch name (default: feature/<TICKET> or fix/<TICKET>)")
    parser.add_argument("--from-ref", dest="from_ref", default="HEAD", help="Base commit/branch reference (default: HEAD)")
    parser.add_argument("--workers", type=int, default=2, help="Max Gradle workers limit in gradle.properties (default: 2)")
    parser.add_argument("--dir", dest="custom_dir", help="Custom worktree destination path")

    args = parser.parse_args()
    ticket = args.ticket.strip()
    repo_root = get_repo_root()

    branch = args.branch
    if not branch:
        ticket_upper = ticket.upper()
        if ticket_upper.startswith("BUG") or ticket_upper.startswith("FIX"):
            branch = f"fix/{ticket}"
        else:
            branch = f"feature/{ticket}"

    worktree_dir = pathlib.Path(args.custom_dir).resolve() if args.custom_dir else repo_root / ".worktrees" / ticket

    print("=" * 70)
    print(f"🚀 Initializing Android Worktree for [{ticket}]...")
    print("=" * 70)

    # 1. Update .gitignore
    ensure_gitignore(repo_root)

    # 2. Add git worktree
    if worktree_dir.exists():
        print(f"ℹ️  Worktree folder already exists at: {worktree_dir}")
    else:
        worktree_dir.parent.mkdir(parents=True, exist_ok=True)
        # Check if branch exists locally or remotely
        has_local = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo_root).returncode == 0
        has_remote = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], cwd=repo_root).returncode == 0

        if has_local:
            print(f"🌿 Checking out existing local branch '{branch}'...")
            run_cmd(["git", "worktree", "add", str(worktree_dir), branch], cwd=repo_root)
        elif has_remote:
            print(f"🌿 Checking out remote branch 'origin/{branch}'...")
            run_cmd(["git", "worktree", "add", str(worktree_dir), "-b", branch, f"origin/{branch}"], cwd=repo_root)
        else:
            print(f"🌿 Creating new branch '{branch}' from '{args.from_ref}'...")
            run_cmd(["git", "worktree", "add", str(worktree_dir), "-b", branch, args.from_ref], cwd=repo_root)

    # 3. Symlink essential Android and Agent files
    print("\n🔗 Symlinking vital Android and Agent configs...")
    for prop_name in ("local.properties", "keystore.properties", "secrets.properties", "local.defaults.properties"):
        symlink_item(repo_root / prop_name, worktree_dir / prop_name, repo_root)

    # Google Services JSON (root & modules)
    symlink_item(repo_root / "google-services.json", worktree_dir / "google-services.json", repo_root)
    for p in repo_root.glob("**/google-services.json"):
        if ".worktrees" in p.parts or "build" in p.parts or p == repo_root / "google-services.json":
            continue
        rel_path = p.relative_to(repo_root)
        symlink_item(p, worktree_dir / rel_path, repo_root)

    # Agent configs
    symlink_item(repo_root / ".agents", worktree_dir / ".agents", repo_root)
    symlink_item(repo_root / ".claude", worktree_dir / ".claude", repo_root)

    # 4. Limit Gradle max-workers to prevent Mac RAM exhaustion
    print(f"\n⚡ Limiting Gradle workers to {args.workers} (Mac RAM protection)...")
    gradle_props = worktree_dir / "gradle.properties"
    worker_line = f"org.gradle.workers.max={args.workers}"
    if gradle_props.exists():
        lines = gradle_props.read_text(encoding="utf-8").splitlines()
        found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("org.gradle.workers.max="):
                new_lines.append(worker_line)
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.extend(["", "# Android Agentic SDLC: RAM protection for parallel agents", worker_line])
        gradle_props.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    else:
        content = (
            f"# Android Agentic SDLC: RAM protection for parallel agents\n"
            f"{worker_line}\n"
            f"org.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=512m\n"
        )
        gradle_props.write_text(content, encoding="utf-8")
    print(f"   🛡️ Set {worker_line} in gradle.properties")

    print("\n" + "=" * 70)
    print(f"✅ ANDROID WORKTREE READY: {worktree_dir}")
    print(f"   • Ticket:         {ticket}")
    print(f"   • Branch:         {branch}")
    print(f"   • Gradle Workers: {args.workers}")
    print("   • Zero-Token init completed in <0.2s")
    print("=" * 70)
    print(f"👉 To begin work in this isolated workspace:")
    print(f"   cd \"{worktree_dir}\"")
    print("=" * 70)


if __name__ == "__main__":
    main()
