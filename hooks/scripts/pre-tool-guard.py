#!/usr/bin/env python3
"""
pre-tool-guard.py — Zero-token, <20ms PreToolUse mechanical guardrails for Mobile Agent Skills.

Enforces 3 hard rules before a tool executes:
1. [domain-purity-guard] Blocks `import android.*` / `import androidx.*` inside `/domain/` Kotlin files.
2. [maestro-static-gate] Blocks invalid Maestro YAML filenames, coordinate taps (`point:`), and missing assertions.
3. [command-safety-guard] Blocks raw `maestro test` CLI calls (enforces `suite-runner.py`) and prompts on destructive git commands.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import pathlib
import re
import sys

# --- Regex patterns aligned with skills/test-author/scripts/validate-flow.py ---
ANDROID_IMPORT_RE = re.compile(r"^\s*import\s+android(x)?\.", re.MULTILINE)
MAESTRO_FILE_RE = re.compile(r"^(ac-\d{2}-[a-z0-9-]+\.yaml|_.*\.yaml)$")
COORD_TAP_RE = re.compile(r"point:\s*[\"']?\s*\d+\s*,\s*\d+", re.IGNORECASE)
ASSERTION_RE = re.compile(r"^\s*-\s*(assertVisible|assertTrue|assertNotVisible):", re.MULTILINE)

RAW_MAESTRO_TEST_RE = re.compile(r"(^|[;&|]\s*)maestro\s+test\b")
HEADLESS_RUNNER_RE = re.compile(r"suite-runner\.py\b.*(?:\s|^)(--headless|--no-terminal)\b")
DRY_RUN_RE = re.compile(r"(?:\s|^)--dry-run\b")
USER_HEADLESS_INTENT_RE = re.compile(r"(--headless|--no-terminal|\bheadless\b|\bno[- ]terminal\b)", re.IGNORECASE)
DESTRUCTIVE_CMD_RE = re.compile(
    r"\b(git\s+reset\s+--hard|git\s+push\s+(-f|--force)|git\s+clean\s+-[a-z]*f|adb\s+uninstall)\b"
)


def reply(decision: str, reason: str = "") -> None:
    payload = {"decision": decision}
    if reason:
        payload["reason"] = reason
    print(json.dumps(payload))
    sys.exit(0)


def check_file_modification(tool_name: str, args: dict) -> None:
    raw_path = args.get("Path") or args.get("TargetFile") or args.get("file_path") or ""
    if not raw_path:
        reply("allow")

    norm_path = raw_path.replace("\\", "/")
    new_text = (
        args.get("Content")
        or args.get("Replacement")
        or args.get("content")
        or args.get("new_string")
        or ""
    )

    # 1. Domain Purity Guard (for `code-domain` skill)
    if norm_path.endswith(".kt") and "/domain/" in norm_path:
        if ANDROID_IMPORT_RE.search(new_text):
            reply(
                "deny",
                "[domain-purity-guard] Prohibited `import android.*` or `import androidx.*` detected in "
                f"'{raw_path}'. Files inside `/domain/` must remain 100% pure Kotlin.",
            )

    # 2. Maestro Static Gate (for `test-author` skill)
    if "/.maestro/" in norm_path or norm_path.startswith(".maestro/"):
        if norm_path.endswith((".yaml", ".yml")):
            filename = pathlib.PurePosixPath(norm_path).name
            is_helper = filename.startswith("_")

            # 2a. Enforce naming convention on creation/edit
            if not MAESTRO_FILE_RE.match(filename):
                reply(
                    "deny",
                    f"[maestro-static-gate] Invalid Maestro filename '{filename}'. "
                    "Test flows must match 'ac-NN-<slug>.yaml' (e.g. 'ac-01-apply-discount.yaml') "
                    "and reusable helpers must start with '_' (e.g. '_login.yaml').",
                )

            # 2b. Prohibit hardcoded coordinate taps (`point: x, y`)
            if COORD_TAP_RE.search(new_text):
                reply(
                    "deny",
                    f"[maestro-static-gate] Hardcoded coordinate tap (`point:`) detected in '{filename}'. "
                    "Use semantic selectors (`id:` or `text:`) instead.",
                )

            # 2c. On full file write (`write_file` / `Write`), require at least 1 assertion in non-helper flows
            if tool_name in ("write_file", "Write") and not is_helper and new_text.strip():
                if not ASSERTION_RE.search(new_text):
                    reply(
                        "deny",
                        f"[maestro-static-gate] Missing assertion in '{filename}'. "
                        "Every non-helper Maestro flow must include at least one "
                        "`assertVisible`, `assertTrue`, or `assertNotVisible`.",
                    )

    reply("allow")


def _detect_transcript_path(hook_data: dict) -> tuple[str | None, str]:
    """Locates the active session transcript for Claude Code or Antigravity."""
    t_path = hook_data.get("transcript_path") or os.environ.get("CLAUDE_TRANSCRIPT_PATH")
    if t_path and os.path.isfile(t_path):
        return t_path, "claude"

    if os.environ.get("CLAUDECODE") == "1":
        proj = os.path.expanduser("~/.claude/projects/" + re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()))
        for env_key in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
            sid = os.environ.get(env_key)
            if sid:
                cand = os.path.join(proj, f"{sid}.jsonl")
                if os.path.isfile(cand):
                    return cand, "claude"
        files = glob.glob(proj + "/*.jsonl")
        if files:
            return max(files, key=os.path.getmtime), "claude"

    conv_id = os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
    app_dir = os.environ.get("ANTIGRAVITY_APP_DATA_DIR", os.path.expanduser("~/.gemini/antigravity"))
    if conv_id and app_dir:
        cand = os.path.join(app_dir, "brain", conv_id, ".system_generated", "logs", "transcript.jsonl")
        if os.path.isfile(cand):
            return cand, "antigravity"

    brain_glob = glob.glob(os.path.expanduser("~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl"))
    if brain_glob:
        newest = max(brain_glob, key=os.path.getmtime)
        if (dt.datetime.now().timestamp() - os.path.getmtime(newest)) / 60.0 < 30:
            return newest, "antigravity"

    proj = os.path.expanduser("~/.claude/projects/" + re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()))
    files = glob.glob(proj + "/*.jsonl")
    if files:
        return max(files, key=os.path.getmtime), "claude"

    return None, "unknown"


def _user_requested_headless(hook_data: dict) -> bool | None:
    """Returns True if the user's latest prompt explicitly requested --headless / --no-terminal,
    False if the user prompt did not request it, or None if transcript could not be read."""
    if os.environ.get("SUITE_RUNNER_ALLOW_HEADLESS") == "1":
        return True

    path, fmt = _detect_transcript_path(hook_data)
    if not path or not os.path.isfile(path):
        return None

    latest_user_text = ""
    try:
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
                        c
                        if isinstance(c, str)
                        else " ".join(
                            b.get("text", "") for b in (c or []) if isinstance(b, dict) and b.get("type") == "text"
                        )
                    ).strip()
                    if not text:
                        continue
                    if text.startswith("Base directory for this skill"):
                        m_arg = re.search(r"^ARGUMENTS:\s*(.+)$", text, re.MULTILINE)
                        if m_arg:
                            latest_user_text = f"{latest_user_text} {m_arg.group(1)}".strip()
                        continue
                    if not o.get("isMeta") and (
                        "<command-name>" in text or "<command-message>" in text or not text.startswith("<")
                    ):
                        latest_user_text = text
    except Exception:
        return None

    if not latest_user_text:
        return None
    return bool(USER_HEADLESS_INTENT_RE.search(latest_user_text))


def check_run_command(args: dict, hook_data: dict) -> None:
    cmd = args.get("CommandLine") or args.get("command") or ""
    if not cmd:
        reply("allow")

    # 3a. Block raw `maestro test` to prevent context/token bleed (enforce `test-runner`)
    if RAW_MAESTRO_TEST_RE.search(cmd) and "suite-runner.py" not in cmd:
        reply(
            "deny",
            "[command-safety-guard] Do not run raw `maestro test` directly in the shell — it floods "
            "the context window with verbose logs. Use `suite-runner.py` from `test-runner` instead "
            "(e.g., `python3 skills/test-runner/scripts/suite-runner.py <target> -m step`).",
        )

    # 3b. Block unrequested `--headless` / `--no-terminal` on `suite-runner.py` (allow when user requested it)
    if HEADLESS_RUNNER_RE.search(cmd) and not DRY_RUN_RE.search(cmd) and "--_terminal-child" not in cmd:
        user_asked = _user_requested_headless(hook_data)
        if user_asked is False:
            reply(
                "deny",
                "[command-safety-guard] Do not pass `--headless` or `--no-terminal` to `suite-runner.py` "
                "unless the user explicitly requested headless execution in their prompt. "
                "Re-run `suite-runner.py` without `--headless` so the live monitoring Terminal window opens.",
            )
        elif user_asked is None:
            reply(
                "force_ask",
                "[command-safety-guard] `--headless` / `--no-terminal` suppresses the live monitoring Terminal window. "
                "Requires explicit user confirmation unless requested in prompt.",
            )

    # 3c. Force user confirmation on destructive git / adb commands
    match = DESTRUCTIVE_CMD_RE.search(cmd)
    if match:
        reply(
            "force_ask",
            f"[command-safety-guard] Destructive command detected (`{match.group(1)}`). "
            "Requires explicit user confirmation before executing.",
        )

    reply("allow")


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        # Fail-open if stdin is malformed so we never deadlock the agent loop
        reply("allow")

    # Support both Antigravity/Gemini (`toolCall`) and Claude Code (`tool_name` / `tool_input`) payloads
    tool_call = data.get("toolCall") or {}
    tool_name = tool_call.get("name") or data.get("tool_name") or ""
    args = tool_call.get("args") or data.get("tool_input") or {}

    if tool_name in ("write_file", "edit_file", "Write", "Edit", "MultiEdit"):
        check_file_modification(tool_name, args)
    elif tool_name in ("run_command", "Bash"):
        check_run_command(args, data)
    else:
        reply("allow")


if __name__ == "__main__":
    main()
