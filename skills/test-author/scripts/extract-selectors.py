#!/usr/bin/env python3
"""
extract-selectors.py — Fast, zero-device-token static selector extractor for Android (XML & Compose)

Scans Android source code to extract Maestro-ready selectors before touching a device:
1. XML Layout / Menu IDs (`android:id="@+id/..."`) + associated tag & text/hint attributes
2. Jetpack Compose Test Tags (`.testTag("...")`, `testTag = "..."`, and `const val` tag definitions)
3. String resources (`res/values/strings.xml`) referenced by layouts or matching `--keyword`

Usage:
  python3 skills/test-author/scripts/extract-selectors.py [search_path] [-k KEYWORD] [--limit N]

Zero external dependencies (Python 3.8+ stdlib only).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Regex patterns for static extraction
XML_TAG_RE = re.compile(r"<([A-Za-z0-9_.]+)\b([^>]*?)/?>", re.DOTALL)
XML_ID_RE = re.compile(r'android:id="@\+?(?:android:)?id/([A-Za-z0-9_]+)"')
XML_TEXT_RE = re.compile(r'android:(?:text|hint|contentDescription)="([^"]+)"')

COMPOSE_TAG_LITERAL_RE = re.compile(r'(?:\.\s*testTag\s*\(\s*|testTag\s*=\s*)"([^"]+)"')
COMPOSE_TAG_CONST_RE = re.compile(r'(?:\.\s*testTag\s*\(\s*|testTag\s*=\s*)([A-Za-z0-9_.]+)')
KT_CONST_VAL_RE = re.compile(r'const\s+val\s+([A-Za-z0-9_]+)\s*=\s*"([^"]+)"')
KT_STRING_RES_RE = re.compile(r'stringResource\s*\(\s*(?:id\s*=\s*)?R\.string\.([A-Za-z0-9_]+)')

STRING_XML_RE = re.compile(r'<string\s+name="([A-Za-z0-9_]+)"[^>]*>(.*?)</string>', re.DOTALL)

SKIP_DIRS = {".git", ".gradle", ".idea", "build", ".maestro", "node_modules", ".agents", ".claude"}


def iter_files(root: Path, suffixes: tuple[str, ...]):
    if root.is_file():
        if root.name.endswith(suffixes):
            yield root
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if fname.endswith(suffixes):
                yield Path(dirpath) / fname


def load_strings_map(root: Path) -> dict[str, str]:
    """Load default res/values/strings.xml entries for quick @string/ and R.string.* resolution."""
    search_root = root if root.is_dir() else root.parent
    # Walk up to repo root if target is a subdirectory/file
    for parent in [search_root] + list(search_root.parents):
        if (parent / "settings.gradle").exists() or (parent / "settings.gradle.kts").exists() or (parent / ".git").exists():
            search_root = parent
            break

    strings_map: dict[str, str] = {}
    for xml_file in iter_files(search_root, ("strings.xml",)):
        # Prefer default values/strings.xml over localized values-xx/strings.xml
        if xml_file.parent.name != "values":
            continue
        try:
            content = xml_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in STRING_XML_RE.finditer(content):
            key, val = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
            strings_map[key] = val
    return strings_map


def load_kotlin_const_map(root: Path) -> dict[str, str]:
    """Collect `const val X = "..."` across Kotlin files to resolve symbolic Compose testTags."""
    consts: dict[str, str] = {}
    for kt_file in iter_files(root, (".kt",)):
        try:
            content = kt_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in KT_CONST_VAL_RE.finditer(content):
            consts[m.group(1)] = m.group(2)
    return consts


def rel_path(path: Path, cwd: Path) -> str:
    try:
        return str(path.relative_to(cwd))
    except ValueError:
        return str(path)


def extract_xml_selectors(root: Path, strings_map: dict[str, str], cwd: Path) -> list[dict]:
    results = []
    for xml_file in iter_files(root, (".xml",)):
        p_str = xml_file.as_posix()
        if "/res/layout" not in p_str and "/res/menu" not in p_str and "/res/navigation" not in p_str:
            continue
        try:
            content = xml_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        for m in XML_TAG_RE.finditer(content):
            tag_name = m.group(1).split(".")[-1]
            attrs = m.group(2)
            id_match = XML_ID_RE.search(attrs)
            if not id_match:
                continue
            view_id = id_match.group(1)
            line_no = content.count("\n", 0, m.start()) + 1

            text_hint = ""
            txt_match = XML_TEXT_RE.search(attrs)
            if txt_match:
                raw_txt = txt_match.group(1)
                if raw_txt.startswith("@string/"):
                    s_key = raw_txt.split("/", 1)[1]
                    resolved = strings_map.get(s_key)
                    text_hint = f'text="{resolved}" (@string/{s_key})' if resolved else f"@string/{s_key}"
                else:
                    text_hint = f'text="{raw_txt}"'

            results.append(
                {
                    "kind": "XML id",
                    "selector": f'id: "{view_id}"',
                    "context": f"<{tag_name}> {text_hint}".strip(),
                    "source": f"{rel_path(xml_file, cwd)}:{line_no}",
                    "raw": f"{view_id} {tag_name} {text_hint} {xml_file.name}".lower(),
                }
            )
    return results


def extract_compose_selectors(
    root: Path, strings_map: dict[str, str], const_map: dict[str, str], cwd: Path
) -> list[dict]:
    results = []
    for kt_file in iter_files(root, (".kt",)):
        try:
            lines = kt_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue

        for idx, line in enumerate(lines, start=1):
            # 1. Direct literal testTag("...")
            for m in COMPOSE_TAG_LITERAL_RE.finditer(line):
                tag_val = m.group(1)
                results.append(
                    {
                        "kind": "Compose tag",
                        "selector": f'id: "{tag_val}"',
                        "context": line.strip()[:60],
                        "source": f"{rel_path(kt_file, cwd)}:{idx}",
                        "raw": f"{tag_val} {line} {kt_file.name}".lower(),
                    }
                )

            # 2. Symbolic testTag(SomeConst.TAG_NAME)
            if "testTag" in line and not COMPOSE_TAG_LITERAL_RE.search(line):
                for m in COMPOSE_TAG_CONST_RE.finditer(line):
                    sym = m.group(1)
                    short_sym = sym.split(".")[-1]
                    resolved = const_map.get(short_sym)
                    sel = f'id: "{resolved}"' if resolved else f'id: "<{sym}>"'
                    results.append(
                        {
                            "kind": "Compose tag",
                            "selector": sel,
                            "context": f"const {sym}" + (f' = "{resolved}"' if resolved else ""),
                            "source": f"{rel_path(kt_file, cwd)}:{idx}",
                            "raw": f"{sym} {resolved or ''} {line} {kt_file.name}".lower(),
                        }
                    )

            # 3. Compose stringResource(R.string.xxx) for text fallback
            for m in KT_STRING_RES_RE.finditer(line):
                s_key = m.group(1)
                resolved = strings_map.get(s_key)
                if resolved:
                    results.append(
                        {
                            "kind": "Compose text",
                            "selector": f'text: "{resolved}"',
                            "context": f"R.string.{s_key}",
                            "source": f"{rel_path(kt_file, cwd)}:{idx}",
                            "raw": f"{s_key} {resolved} {line} {kt_file.name}".lower(),
                        }
                    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Code-First ID Extraction: scan Android XML & Compose sources for Maestro selectors."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Target directory or file to scan (default: current directory)",
    )
    parser.add_argument(
        "-k",
        "--keyword",
        default="",
        help="Filter selectors/files by keyword (e.g., 'checkout', 'login', 'btn_')",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=150,
        help="Maximum number of rows to print (default: 150)",
    )
    args = parser.parse_args()

    target = Path(args.path).resolve()
    cwd = Path.cwd()
    if not target.exists():
        print(f"Error: path not found: {target}", file=sys.stderr)
        sys.exit(1)

    strings_map = load_strings_map(target)
    const_map = load_kotlin_const_map(target)

    items = extract_xml_selectors(target, strings_map, cwd) + extract_compose_selectors(
        target, strings_map, const_map, cwd
    )

    kw = args.keyword.strip().lower()
    if kw:
        items = [it for it in items if kw in it["raw"] or kw in it["source"].lower()]

    if not items:
        print("NO_STATIC_SELECTORS_FOUND")
        print(
            "Hint: If this screen uses Server-Driven UI (SDUI), dynamic IDs, or external SDK views, "
            "fallback to: python3 skills/test-runner/scripts/device.py nodes"
        )
        sys.exit(0)

    print(f"# Found {len(items)} static selector(s) (showing up to {args.limit}):")
    print(f"{'TYPE':<14} | {'MAESTRO SELECTOR':<34} | {'CONTEXT / TEXT':<36} | SOURCE")
    print("-" * 120)
    for it in items[: args.limit]:
        print(f"{it['kind']:<14} | {it['selector']:<34} | {it['context'][:36]:<36} | {it['source']}")

    if len(items) > args.limit:
        print(f"... ({len(items) - args.limit} more rows truncated; narrow with -k <keyword> or specific path)")


if __name__ == "__main__":
    main()

