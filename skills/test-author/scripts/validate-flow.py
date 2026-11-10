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
import os
import re
import sys
from pathlib import Path

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
COORDINATE_TAP_PATTERN = re.compile(r"point:\s*[\"']?\s*\d+(?:\.\d+)?(?!\s*%)\s*,\s*\d+(?:\.\d+)?(?!\s*%)", re.IGNORECASE)
EXCESSIVE_SLEEP_PATTERN = re.compile(r"^\s*-\s*sleep:\s*(\d+)", re.MULTILINE)


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

    # 4. Assertion check for test flows (helpers exempt)
    if not is_helper:
        if not ASSERTION_PATTERN.search(content):
            errors.append(
                "Missing test assertion. Test flows must contain at least one "
                "'assertVisible', 'assertTrue', or 'assertNotVisible'."
            )

    # 5. Excessive sleep warning
    sleep_matches = EXCESSIVE_SLEEP_PATTERN.findall(content)
    for ms_str in sleep_matches:
        if int(ms_str) >= 5000:
            warnings.append(
                f"Sleep of {ms_str}ms detected. Consider using 'extendedWaitUntil: {{ visible: ..., timeout: ... }}' "
                f"instead of hardcoded sleep."
            )

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

    print(f"\n{BOLD}{BLUE}==================================================")
    print(f"  MAESTRO FLOW VALIDATOR")
    print(f"  Target: {target_path}")
    print(f"  Files : {len(files)}")
    print(f"=================================================={RESET}\n")

    total_errors = 0
    total_warnings = 0

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
