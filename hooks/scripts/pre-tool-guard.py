#!/usr/bin/env python3
"""
pre-tool-guard.py — Zero-token, <20ms PreToolUse mechanical guardrails for Mobile Agent Skills.

Enforces 3 hard rules before a tool executes:
1. [domain-purity-guard] Blocks `import android.*` / `import androidx.*` inside `/domain/` Kotlin files.
2. [maestro-static-gate] Blocks invalid Maestro YAML filenames, coordinate taps (`point:`), and missing assertions.
3. [command-safety-guard] Blocks raw `maestro test` CLI calls (enforces `suite-runner.py`) and prompts on destructive git commands.
"""

import json
import pathlib
import re
import sys

# --- Regex patterns aligned with skills/test-author/scripts/validate-flow.py ---
ANDROID_IMPORT_RE = re.compile(r"^\s*import\s+android(x)?\.", re.MULTILINE)
MAESTRO_FILE_RE = re.compile(r"^(ac-\d{2}-[a-z0-9-]+\.yaml|_.*\.yaml)$")
COORD_TAP_RE = re.compile(r"point:\s*[\"']?\s*\d+\s*,\s*\d+", re.IGNORECASE)
ASSERTION_RE = re.compile(r"^\s*-\s*(assertVisible|assertTrue|assertNotVisible):", re.MULTILINE)

RAW_MAESTRO_TEST_RE = re.compile(r"(^|[;&|]\s*)maestro\s+test\b")
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


def check_run_command(args: dict) -> None:
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

    # 3b. Force user confirmation on destructive git / adb commands
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
        check_run_command(args)
    else:
        reply("allow")


if __name__ == "__main__":
    main()
