#!/usr/bin/env python3
"""
validate-flow.py — Static validator for Maestro YAML flows

Enforces:
1. Semantic directory naming (<index>-<domain-slug>, e.g. 01-order-list)
2. Semantic file naming (ac-<index>-<slug>.yaml, e.g. ac-01-display-all-orders.yaml)
3. Helper files must start with '_' (e.g. _login.yaml, _seed-data.yaml)
4. Anti-flakiness checks:
   - Prohibits hardcoded coordinate taps (point: "x, y")
   - Requires assertions (assertVisible, assertTrue, assertNotVisible)
   - Warns on excessive sleep commands (prefer extendedWaitUntil)

Zero external dependencies (Python 3.8+ stdlib only).
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# ANSI colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"

FOLDER_PATTERN = re.compile(r"^(\d{2}-[a-z0-9-]+|regression|_.*|templates)$")
FILE_PATTERN = re.compile(r"^(ac-\d{2}-[a-z0-9-]+\.yaml|_.*\.yaml)$")
ASSERTION_PATTERN = re.compile(r"^\s*-\s*(assertVisible|assertTrue|assertNotVisible):", re.MULTILINE)
PRECONDITION_PATTERN = re.compile(r"^\s*-\s*(launchApp|runFlow)\b", re.MULTILINE)
COORDINATE_TAP_PATTERN = re.compile(r"point:\s*[\"']?\s*\d+\s*,\s*\d+", re.IGNORECASE)
EXCESSIVE_SLEEP_PATTERN = re.compile(r"^\s*-\s*sleep:\s*(\d+)", re.MULTILINE)
EMAIL_LITERAL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
PHONE_LITERAL_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
REGEX_HINT_PATTERN = re.compile(r"(\.\*|\.\+|\\d|\\w|\\s|\[[^\]]+\]|\^|\$)")
SAFE_EMAIL_DOMAINS = {"example.com", "example.org", "example.net", "test.local"}
LIST_CMD_PATTERN = re.compile(r"^(\s*)-\s*([A-Za-z0-9_]+)\s*:(.*)$")
TEXT_KEY_PATTERN = re.compile(r"^(\s*)text\s*:(.*)$")
NON_SELECTOR_COMMANDS = {"inputText", "echo", "eraseText", "writeKeychain", "setLocation"}
SELECTOR_SHORTHAND_COMMANDS = {
    "assertVisible",
    "assertNotVisible",
    "tapOn",
    "longPressOn",
    "doubleTapOn",
}

TOO_BROAD_POPUP_SELECTORS = {
    "ok",
    "cancel",
    "yes",
    "no",
    "close",
    "dismiss",
    ".*close.*",
    ".*ok.*",
    ".*",
    ".+",
}


def _strip_yaml_comment(raw: str) -> str:
    """Strip unquoted YAML comments and surrounding quotes/whitespace."""
    in_single = False
    in_double = False
    escaped = False
    out = []
    for ch in raw:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_double:
            out.append(ch)
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            break
        out.append(ch)
    cleaned = "".join(out).strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ("'", '"'):
        return cleaned[1:-1].strip()
    return cleaned


def _extract_runflow_targets(content: str) -> list[tuple[str, bool]]:
    """Extract (target_path, is_optional) tuples from all `runFlow` steps."""
    results: list[tuple[str, bool]] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\s*)-\s*runFlow\s*:(.*)$", line)
        if not m:
            i += 1
            continue

        base_indent = len(m.group(1))
        rest = _strip_yaml_comment(m.group(2))

        if rest and not rest.startswith("{"):
            results.append((rest, False))
            i += 1
            continue

        if rest.startswith("{"):
            file_m = re.search(r"\bfile\s*:\s*([^,}]+)", rest)
            opt_m = re.search(r"\boptional\s*:\s*(true|false)\b", rest, re.IGNORECASE)
            if file_m:
                target = _strip_yaml_comment(file_m.group(1))
                is_opt = bool(opt_m and opt_m.group(1).lower() == "true")
                if target:
                    results.append((target, is_opt))
            i += 1
            continue

        # Multi-line mapping block under `- runFlow:`
        j = i + 1
        target = ""
        is_opt = False
        child_indent: Optional[int] = None
        while j < len(lines):
            sub = lines[j]
            stripped = sub.strip()
            if not stripped or stripped.startswith("#"):
                j += 1
                continue
            indent = len(sub) - len(sub.lstrip(" "))
            if indent <= base_indent:
                break
            if child_indent is None:
                child_indent = indent
            if indent == child_indent:
                if stripped.startswith("file:"):
                    target = _strip_yaml_comment(stripped.split(":", 1)[1])
                elif stripped.startswith("optional:"):
                    val = _strip_yaml_comment(stripped.split(":", 1)[1]).lower()
                    is_opt = val == "true"
            j += 1

        if target:
            results.append((target, is_opt))
        i = j

    return results


def _looks_like_account_literal(value: str) -> Optional[str]:
    """Return a short reason if a selector value appears hardcoded to a specific account."""
    if not value or "${" in value or ("<" in value and ">" in value):
        return None
    if REGEX_HINT_PATTERN.search(value):
        return None

    email_m = EMAIL_LITERAL_PATTERN.search(value)
    if email_m:
        domain = email_m.group(1).lower()
        if domain not in SAFE_EMAIL_DOMAINS:
            return f"hardcoded email '{email_m.group(0)}'"

    for phone_m in PHONE_LITERAL_PATTERN.finditer(value):
        candidate = phone_m.group(0).strip()
        if ":" in candidate or candidate.count(".") >= 2:
            continue
        digits = re.sub(r"\D", "", candidate)
        if 9 <= len(digits) <= 15:
            return f"hardcoded phone-like literal '{candidate}'"

    return None


def _find_account_portability_warnings(content: str) -> list[str]:
    """Warn on account-specific literals (email/phone) inside UI selectors."""
    warnings: list[str] = []
    in_body = False
    lines = content.splitlines()
    has_doc_sep = any(line.strip() == "---" for line in lines)
    if not has_doc_sep:
        in_body = True

    current_cmd = ""
    cmd_indent = -1
    seen_warnings: set[str] = set()

    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not in_body:
            if stripped == "---":
                in_body = True
            continue
        if not stripped or stripped.startswith("#"):
            continue

        cmd_m = LIST_CMD_PATTERN.match(line)
        if cmd_m:
            indent = len(cmd_m.group(1))
            cmd_name = cmd_m.group(2)
            raw_val = _strip_yaml_comment(cmd_m.group(3))
            current_cmd = cmd_name
            cmd_indent = indent
            if cmd_name in SELECTOR_SHORTHAND_COMMANDS and raw_val and not raw_val.startswith("{"):
                reason = _looks_like_account_literal(raw_val)
                if reason and reason not in seen_warnings:
                    seen_warnings.add(reason)
                    warnings.append(
                        f"Line {line_no}: selector uses {reason}. Prefer id/index, copyTextFrom, "
                        "regex, or ${ENV_VAR} so flows stay portable across accounts/devices."
                    )
            elif raw_val.startswith("{") and cmd_name not in NON_SELECTOR_COMMANDS:
                text_m = re.search(r"\btext\s*:\s*([^,}]+)", raw_val)
                if text_m:
                    val = _strip_yaml_comment(text_m.group(1))
                    reason = _looks_like_account_literal(val)
                    if reason and reason not in seen_warnings:
                        seen_warnings.add(reason)
                        warnings.append(
                            f"Line {line_no}: selector uses {reason}. Prefer id/index, copyTextFrom, "
                            "regex, or ${ENV_VAR} so flows stay portable across accounts/devices."
                        )
            continue

        cur_indent = len(line) - len(line.lstrip(" "))
        if cur_indent <= cmd_indent:
            current_cmd = ""
            cmd_indent = -1

        if current_cmd in NON_SELECTOR_COMMANDS:
            continue

        text_m = TEXT_KEY_PATTERN.match(line)
        if text_m:
            val = _strip_yaml_comment(text_m.group(2))
            reason = _looks_like_account_literal(val)
            if reason and reason not in seen_warnings:
                seen_warnings.add(reason)
                warnings.append(
                    f"Line {line_no}: selector uses {reason}. Prefer id/index, copyTextFrom, "
                    "regex, or ${ENV_VAR} so flows stay portable across accounts/devices."
                )

    return warnings


def validate_file(path: Path) -> tuple[list[str], list[str]]:
    """Validate a single flow file. Returns (errors, warnings)."""
    errors = []
    warnings = []

    filename = path.name
    is_helper = filename.startswith("_")

    # 1. File naming
    if not FILE_PATTERN.match(filename):
        errors.append(
            f"Invalid filename '{filename}'. Test flows must match 'ac-NN-<slug>.yaml' "
            f"(e.g. ac-01-order-list.yaml), and helper flows must start with '_' (e.g. _login.yaml)."
        )

    # 2. Parent folder naming
    parent_name = path.parent.name
    if not FOLDER_PATTERN.match(parent_name):
        warnings.append(
            f"Parent directory '{parent_name}' does not follow semantic naming (expected 'NN-<domain>', e.g. '01-order-list')."
        )

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        errors.append(f"Cannot read file: {e}")
        return errors, warnings

    if not content.strip():
        errors.append("File is empty.")
        return errors, warnings

    # 3. Coordinate taps check
    coord_matches = COORDINATE_TAP_PATTERN.findall(content)
    if coord_matches:
        errors.append(
            f"Prohibited coordinate tap detected ({coord_matches[0]}). "
            f"Use resource ID ('id: ...') or text ('text: ...') selectors instead."
        )

    # 4. Assertion & standalone precondition checks for test flows (helpers exempt)
    if not is_helper:
        if not ASSERTION_PATTERN.search(content):
            errors.append(
                "Missing test assertion. Test flows must contain at least one "
                "'assertVisible', 'assertTrue', or 'assertNotVisible'."
            )
        if not PRECONDITION_PATTERN.search(content):
            warnings.append(
                "No 'launchApp' or 'runFlow' precondition found. Frozen flows should be standalone "
                "from app launch or a shared _nav/ subflow so suite-runner.py can run them independently."
            )

    # 5. runFlow relative target existence check (skip templates directory)
    if path.parent.name != "templates":
        for target_ref, is_optional in _extract_runflow_targets(content):
            if "${" in target_ref:
                continue
            resolved = (path.parent / target_ref).resolve()
            if not resolved.is_file() and not is_optional:
                errors.append(
                    f"Missing runFlow target '{target_ref}' (resolved to '{resolved}')."
                )

    # 6. Account portability heuristic warning
    if path.parent.name != "templates":
        warnings.extend(_find_account_portability_warnings(content))

    # 7. Excessive sleep warning
    sleep_matches = EXCESSIVE_SLEEP_PATTERN.findall(content)
    for ms_str in sleep_matches:
        if int(ms_str) >= 5000:
            warnings.append(
                f"Sleep of {ms_str}ms detected. Consider using 'extendedWaitUntil: {{ visible: ..., timeout: ... }}' "
                f"instead of hardcoded sleep."
            )

    return errors, warnings


def validate_popups_json(path: Path) -> tuple[list[str], list[str]]:
    """Validate .maestro/_shared/popups.json to prevent overly broad dismissal rules."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"Invalid JSON in {path.name}: {e}"], warnings

    rules = data.get("rules")
    if not isinstance(rules, list):
        return [f"{path.name} must contain a 'rules' list."], warnings

    for idx, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            errors.append(f"Rule #{idx} must be an object.")
            continue
        if rule.get("enabled") is False:
            continue
        name = rule.get("name") or f"rule-{idx}"
        when = rule.get("when_visible")
        if not isinstance(when, dict) or not any(when.get(k) for k in ("id", "text", "content_desc", "window")):
            errors.append(
                f"Popup rule '{name}' must define 'when_visible' with at least one of: id, text, content_desc, window."
            )
        else:
            for k in ("id", "text", "content_desc"):
                val = str(when.get(k, "")).strip().lower()
                if val and val in TOO_BROAD_POPUP_SELECTORS:
                    errors.append(
                        f"Popup rule '{name}' has overly broad 'when_visible.{k}' ('{when.get(k)}'). "
                        "Use a specific container/overlay ID or title to avoid dismissing real app dialogs."
                    )
        actions = rule.get("actions")
        if not isinstance(actions, list) or not actions:
            errors.append(f"Popup rule '{name}' must define a non-empty 'actions' list.")

    return errors, warnings


def validate_feature_map_json(path: Path) -> tuple[list[str], list[str]]:
    """Validate optional .maestro/feature-map.json schema (opt-in; never required)."""
    errors: list[str] = []
    warnings: list[str] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"Invalid JSON in {path.name}: {e}"], warnings

    features = data.get("features")
    if not isinstance(features, dict):
        return [f"{path.name} must contain a 'features' object."], warnings

    is_template = path.parent.name == "templates"
    for slug, cfg in features.items():
        if not isinstance(cfg, dict):
            errors.append(f"Feature '{slug}' must be a JSON object.")
            continue
        for str_key in ("description", "instruction", "nav"):
            val = cfg.get(str_key)
            if val is not None and not isinstance(val, str):
                errors.append(f"Feature '{slug}.{str_key}' must be a string.")
        for list_key in ("keywords", "code_paths"):
            val = cfg.get(list_key)
            if val is not None and (not isinstance(val, list) or not all(isinstance(x, str) for x in val)):
                errors.append(f"Feature '{slug}.{list_key}' must be a list of strings.")
        nav = str(cfg.get("nav", "")).strip()
        if nav and not is_template:
            nav_path = Path(nav)
            if not nav_path.is_absolute():
                repo_cand = (Path.cwd() / nav_path).resolve()
                rel_cand = (path.parent / nav_path).resolve()
                if not repo_cand.is_file() and not rel_cand.is_file():
                    warnings.append(f"Feature '{slug}' references missing nav helper '{nav}'.")

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Validate Maestro E2E YAML flows against semantic standards.")
    parser.add_argument("target", help="Path to a YAML file or directory of flows")
    args = parser.parse_args()

    target_path = Path(args.target).resolve()
    if not target_path.exists():
        print(f"{RED}Target not found: {target_path}{RESET}")
        sys.exit(1)

    if target_path.is_file():
        files = [target_path]
    else:
        files = sorted(list(target_path.rglob("*.yaml")))

    if not files:
        print(f"{RED}No .yaml files found in {target_path}{RESET}")
        sys.exit(1)

    # Also validate .maestro/_shared/popups.json and optional .maestro/feature-map.json if discoverable
    popups_files: list[Path] = []
    feature_map_files: list[Path] = []
    for cand in [target_path / "popups.json", target_path / "_shared" / "popups.json"]:
        if cand.is_file():
            popups_files.append(cand)
    for cand in [target_path / "feature-map.json", target_path / "_shared" / "feature-map.json"]:
        if cand.is_file():
            feature_map_files.append(cand)
    for parent in [target_path, *target_path.parents]:
        if parent.name == ".maestro":
            p = parent / "_shared" / "popups.json"
            if p.is_file() and p not in popups_files:
                popups_files.append(p)
            fm = parent / "feature-map.json"
            if fm.is_file() and fm not in feature_map_files:
                feature_map_files.append(fm)
            break

    print(f"\n{BOLD}{BLUE}==================================================")
    print(f"  MAESTRO FLOW VALIDATOR")
    print(f"  Target: {target_path}")
    print(f"  Files : {len(files)}")
    print(f"=================================================={RESET}\n")

    total_errors = 0
    total_warnings = 0

    for pf in popups_files:
        p_errors, p_warnings = validate_popups_json(pf)
        total_errors += len(p_errors)
        total_warnings += len(p_warnings)
        if p_errors:
            print(f"{RED}FAIL{RESET}  {BOLD}{pf}{RESET}")
            for err in p_errors:
                print(f"      {RED}✖ Error:{RESET} {err}")
        elif p_warnings:
            print(f"{YELLOW}WARN{RESET}  {BOLD}{pf}{RESET}")
            for wrn in p_warnings:
                print(f"      {YELLOW}⚠ Warning:{RESET} {wrn}")
        else:
            print(f"{GREEN}PASS{RESET}  {pf}")

    for fm in feature_map_files:
        fm_errors, fm_warnings = validate_feature_map_json(fm)
        total_errors += len(fm_errors)
        total_warnings += len(fm_warnings)
        if fm_errors:
            print(f"{RED}FAIL{RESET}  {BOLD}{fm}{RESET}")
            for err in fm_errors:
                print(f"      {RED}✖ Error:{RESET} {err}")
        elif fm_warnings:
            print(f"{YELLOW}WARN{RESET}  {BOLD}{fm}{RESET}")
            for wrn in fm_warnings:
                print(f"      {YELLOW}⚠ Warning:{RESET} {wrn}")
        else:
            print(f"{GREEN}PASS{RESET}  {fm}")

    for f in files:
        rel_path = f.name
        try:
            rel_path = f.relative_to(Path.cwd())
        except ValueError:
            pass

        errors, warnings = validate_file(f)
        total_errors += len(errors)
        total_warnings += len(warnings)

        if errors:
            print(f"{RED}FAIL{RESET}  {BOLD}{rel_path}{RESET}")
            for err in errors:
                print(f"      {RED}✖ Error:{RESET} {err}")
            for wrn in warnings:
                print(f"      {YELLOW}⚠ Warning:{RESET} {wrn}")
        elif warnings:
            print(f"{YELLOW}WARN{RESET}  {BOLD}{rel_path}{RESET}")
            for wrn in warnings:
                print(f"      {YELLOW}⚠ Warning:{RESET} {wrn}")
        else:
            print(f"{GREEN}PASS{RESET}  {rel_path}")

    print(f"\n{BOLD}Summary:{RESET} {len(files)} files scanned | {RED}{total_errors} errors{RESET} | {YELLOW}{total_warnings} warnings{RESET}")
    if total_errors > 0:
        print(f"{RED}{BOLD}Validation failed.{RESET} Please fix errors before running test suites.\n")
        sys.exit(1)
    else:
        print(f"{GREEN}{BOLD}All flows passed validation!{RESET}\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
