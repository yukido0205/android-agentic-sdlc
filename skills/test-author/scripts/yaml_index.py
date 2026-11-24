#!/usr/bin/env python3
"""
yaml_index.py — Lightweight in-memory Feature Map + Maestro YAML indexer (Lean v2).

Scans `.maestro/` on the fly (<20ms, zero cache files, zero Git conflicts) and optionally
joins with `.maestro/feature-map.json` to:
  1. Discover existing cross-ticket YAML flows before authoring new MCP flows (`--feature`, `--files`, `--query`).
  2. Emit a `.flows` manifest (`--out-manifest`) runnable directly by `suite-runner.py`.
  3. Report per-feature YAML coverage (`--coverage`) for QC releases and lazy migration.

Zero external dependencies (Python 3.8+ stdlib only).
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

EXCLUDED_DIRS = {"_nav", "_shared", "templates", "e2e-runs", ".run", "debug", "issues"}
SEMANTIC_FOLDER_RE = re.compile(r"^\d{2}-([a-z0-9][a-z0-9-]*)$")
CRYPTIC_OR_GENERIC_SLUGS = re.compile(
    r"^(s\d+|f\d+|s\d+s\d+|step-?\d+|regression|e2e|tests?|misc|tmp|temp|repro)$",
    re.IGNORECASE,
)
FEATURE_COMMENT_RE = re.compile(r"^\s*#\s*Feature\s*:\s*([A-Za-z0-9_/-]+)", re.IGNORECASE)
YAML_NAME_RE = re.compile(r"^\s*name\s*:\s*(.+)$")
TAG_RE = re.compile(r"@[A-Za-z0-9_-]+")
RUNFLOW_INLINE_RE = re.compile(r"^\s*-\s*runFlow\s*:\s*([^\s{#][^\n#]*)")
RUNFLOW_FILE_RE = re.compile(r"^\s*file\s*:\s*([^\s{#][^\n#]*)")
TICKET_DIR_RE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
WORD_SPLIT_RE = re.compile(r"[^a-z0-9]+")
STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "when", "then",
    "verify", "check", "test", "flow", "yaml", "app", "src", "main", "java",
    "kotlin", "com", "android", "activity", "fragment", "viewmodel", "screen",
    "ui", "kt", "xml", "file", "bug", "fix", "issue", "ticket", "ac",
}


def _clean_scalar(raw: str) -> str:
    val = raw.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        return val[1:-1].strip()
    return val


def _tokenize(text: str) -> Set[str]:
    # Split camelCase before lowercasing so `CheckoutViewModel` yields `checkout`.
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    raw_tokens = WORD_SPLIT_RE.split(spaced.lower())
    return {t for t in raw_tokens if len(t) >= 3 and t not in STOPWORDS}


def load_feature_map(maestro_root: Path, explicit_map: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Load optional `.maestro/feature-map.json`. Returns {} gracefully if absent."""
    candidates: List[Path] = []
    if explicit_map is not None:
        candidates.append(explicit_map)
    else:
        candidates.append(maestro_root / "feature-map.json")
        candidates.append(maestro_root / "_shared" / "feature-map.json")

    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"WARN: Could not parse feature-map '{path}': {exc}", file=sys.stderr)
            return {}
        features = data.get("features")
        if isinstance(features, dict):
            return {
                str(k).strip().lower(): v
                for k, v in features.items()
                if isinstance(v, dict)
            }
    return {}


def _extract_flow_info(yaml_path: Path, maestro_root: Path, feature_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Parse lightweight metadata from a Maestro YAML flow and infer its feature."""
    try:
        content = yaml_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        content = ""

    lines = content.splitlines()
    explicit_feature = ""
    flow_name = ""
    header_comments: List[str] = []
    helpers: List[str] = []
    tags: Set[str] = set()

    in_frontmatter = True
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if idx < 30:
            m_feat = FEATURE_COMMENT_RE.match(line)
            if m_feat and not explicit_feature:
                explicit_feature = m_feat.group(1).strip().lower()
            if stripped.startswith("#"):
                header_comments.append(stripped.lstrip("#").strip())
                tags.update(TAG_RE.findall(stripped))
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
                continue
            m_name = YAML_NAME_RE.match(line)
            if m_name and not flow_name:
                flow_name = _clean_scalar(m_name.group(1))
        m_rf = RUNFLOW_INLINE_RE.match(line) or RUNFLOW_FILE_RE.match(line)
        if m_rf:
            ref = _clean_scalar(m_rf.group(1))
            if ref and ref not in helpers:
                helpers.append(ref)

    try:
        rel_to_maestro = yaml_path.relative_to(maestro_root)
    except ValueError:
        rel_to_maestro = yaml_path

    parts = rel_to_maestro.parts
    ticket = ""
    if parts and TICKET_DIR_RE.match(parts[0]):
        ticket = parts[0]
    elif len(parts) >= 2 and parts[0] not in EXCLUDED_DIRS:
        ticket = parts[0]

    # Infer feature via 4-tier fallback (zero breaking changes on legacy folders)
    feature = ""
    feature_source = "unmapped"
    if explicit_feature:
        feature = explicit_feature
        feature_source = "header"
    else:
        parent_name = yaml_path.parent.name.lower()
        m_sem = SEMANTIC_FOLDER_RE.match(parent_name)
        if m_sem:
            slug = m_sem.group(1)
            if not CRYPTIC_OR_GENERIC_SLUGS.match(slug):
                feature = slug
                feature_source = "folder"

    if not feature and feature_map:
        # Tier 3a: exact nav helper basename match
        helper_basenames = {Path(h).name.lower() for h in helpers}
        for slug, cfg in feature_map.items():
            nav = str(cfg.get("nav", "")).strip()
            if nav and Path(nav).name.lower() in helper_basenames:
                feature = slug
                feature_source = "nav-match"
                break

    if not feature and feature_map:
        # Tier 3b: keyword match on path + name + header comments (require unique winner)
        haystack_text = " ".join([str(rel_to_maestro), flow_name, " ".join(header_comments)]).lower()
        haystack_tokens = _tokenize(haystack_text)
        scored: List[Tuple[int, str]] = []
        for slug, cfg in feature_map.items():
            score = 0
            for kw in cfg.get("keywords", []) or []:
                kw_l = str(kw).strip().lower()
                if len(kw_l) >= 3 and kw_l in haystack_text:
                    score += 2
            slug_tokens = _tokenize(slug)
            score += len(slug_tokens & haystack_tokens)
            if score > 0:
                scored.append((score, slug))
        scored.sort(reverse=True)
        if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            feature = scored[0][1]
            feature_source = "keyword-match"

    if not feature:
        feature = "unmapped"

    stem = yaml_path.stem
    flow_type = "regression" if (stem.startswith("r-") or "regression" in [p.lower() for p in parts]) else "ac"

    try:
        display_path = str(yaml_path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        display_path = str(yaml_path)

    return {
        "path": display_path.replace("\\", "/"),
        "abs_path": str(yaml_path.resolve()),
        "feature": feature,
        "feature_source": feature_source,
        "ticket": ticket,
        "type": flow_type,
        "name": flow_name or stem,
        "tags": sorted(tags),
        "helpers": helpers,
        "header": " ".join(header_comments[:3]),
    }


def scan_flows(maestro_root: Path, feature_map: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Recursively scan `.maestro/` in memory for all non-helper YAML test flows."""
    if not maestro_root.is_dir():
        return []
    discovered: List[Path] = []
    for ext in ("*.yaml", "*.yml"):
        for p in sorted(maestro_root.rglob(ext)):
            try:
                rel_parts = p.relative_to(maestro_root).parts
            except ValueError:
                rel_parts = p.parts
            if any(part in EXCLUDED_DIRS for part in rel_parts[:-1]):
                continue
            if p.name.startswith("_"):
                continue
            discovered.append(p)

    # Deduplicate while preserving deterministic order
    seen: Set[Path] = set()
    flows: List[Dict[str, Any]] = []
    for p in sorted(discovered):
        resolved = p.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        flows.append(_extract_flow_info(p, maestro_root, feature_map))
    return flows


def match_flows(
    flows: List[Dict[str, Any]],
    feature_map: Dict[str, Dict[str, Any]],
    features: Optional[List[str]] = None,
    files: Optional[List[str]] = None,
    query: Optional[str] = None,
    limit: int = 15,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Return (matched_feature_slugs, ranked_flows) without dropping unmapped legacy flows."""
    matched_features: Dict[str, int] = {}
    flow_scores: Dict[str, int] = {}
    flow_by_path: Dict[str, Dict[str, Any]] = {f["abs_path"]: f for f in flows}

    # 1. Direct --feature match
    if features:
        wanted: List[str] = []
        for item in features:
            for part in item.split(","):
                slug = part.strip().lower()
                if slug:
                    wanted.append(slug)
        for slug in wanted:
            for fm_slug in feature_map:
                if slug == fm_slug or slug in fm_slug:
                    matched_features[fm_slug] = matched_features.get(fm_slug, 0) + 10
            for f in flows:
                f_slug = f["feature"].lower()
                if slug == f_slug or (slug != "unmapped" and slug in f_slug):
                    matched_features[f_slug] = matched_features.get(f_slug, 0) + 10
                    flow_scores[f["abs_path"]] = flow_scores.get(f["abs_path"], 0) + 10

    # 2. --files match against feature-map code_paths + path tokens fallback
    if files:
        norm_files = [fp.replace("\\", "/").strip() for fp in files if fp.strip()]
        file_tokens: Set[str] = set()
        for fp in norm_files:
            fp_lower = fp.lower()
            file_tokens.update(_tokenize(fp))
            for slug, cfg in feature_map.items():
                for cp in cfg.get("code_paths", []) or []:
                    cp_norm = str(cp).replace("\\", "/").strip().lower()
                    if cp_norm and cp_norm in fp_lower:
                        matched_features[slug] = matched_features.get(slug, 0) + 8
                for kw in cfg.get("keywords", []) or []:
                    kw_l = str(kw).strip().lower()
                    if len(kw_l) >= 4 and kw_l in fp_lower:
                        matched_features[slug] = matched_features.get(slug, 0) + 3

        # Score flows belonging to matched features
        for f in flows:
            if f["feature"] in matched_features and f["feature"] != "unmapped":
                flow_scores[f["abs_path"]] = flow_scores.get(f["abs_path"], 0) + matched_features[f["feature"]]

        # Fallback: match tokens directly against flow feature/path/name (catches repos without feature-map.json & unmapped flows)
        if file_tokens:
            for f in flows:
                f_tokens = _tokenize(" ".join([f["feature"], f["path"], f["name"]]))
                overlap = file_tokens & f_tokens
                if overlap:
                    flow_scores[f["abs_path"]] = flow_scores.get(f["abs_path"], 0) + (2 * len(overlap))
                    if f["feature"] != "unmapped":
                        matched_features[f["feature"]] = matched_features.get(f["feature"], 0) + len(overlap)

    # 3. --query match across feature-map + ALL flows (including unmapped)
    if query:
        q_lower = query.strip().lower()
        q_tokens = _tokenize(query)
        for slug, cfg in feature_map.items():
            blob = " ".join([
                slug,
                str(cfg.get("description", "")),
                str(cfg.get("instruction", "")),
                " ".join(str(k) for k in (cfg.get("keywords", []) or [])),
            ]).lower()
            score = 0
            if q_lower and len(q_lower) >= 3 and q_lower in blob:
                score += 6
            score += 2 * len(q_tokens & _tokenize(blob))
            if score > 0:
                matched_features[slug] = matched_features.get(slug, 0) + score

        for f in flows:
            f_blob = " ".join([f["feature"], f["path"], f["name"], f["header"], " ".join(f["tags"])]).lower()
            score = 0
            if q_lower and len(q_lower) >= 3 and q_lower in f_blob:
                score += 6
            score += 2 * len(q_tokens & _tokenize(f_blob))
            if f["feature"] in matched_features and f["feature"] != "unmapped":
                score += max(2, matched_features[f["feature"]] // 2)
            if score > 0:
                flow_scores[f["abs_path"]] = flow_scores.get(f["abs_path"], 0) + score

    ranked_features = [slug for slug, _ in sorted(matched_features.items(), key=lambda kv: (-kv[1], kv[0])) if slug != "unmapped"]
    ranked_paths = sorted(flow_scores.keys(), key=lambda p: (-flow_scores[p], flow_by_path[p]["path"]))
    ranked_flows = [flow_by_path[p] for p in ranked_paths[: max(1, limit)]]
    return ranked_features, ranked_flows


def build_coverage(flows: List[Dict[str, Any]], feature_map: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build per-feature YAML coverage summary for QC releases & migration checks."""
    by_feature: Dict[str, List[Dict[str, Any]]] = {}
    for f in flows:
        by_feature.setdefault(f["feature"], []).append(f)

    all_slugs = sorted(set(feature_map.keys()) | {k for k in by_feature.keys() if k != "unmapped"})
    rows: List[Dict[str, Any]] = []
    for slug in all_slugs:
        cfg = feature_map.get(slug, {})
        f_list = by_feature.get(slug, [])
        rows.append({
            "feature": slug,
            "count": len(f_list),
            "in_feature_map": slug in feature_map,
            "nav": str(cfg.get("nav", "")).strip(),
            "description": str(cfg.get("description", "")).strip(),
            "instruction": str(cfg.get("instruction", "")).strip(),
            "flows": [f["path"] for f in f_list],
        })

    if "unmapped" in by_feature:
        u_list = by_feature["unmapped"]
        rows.append({
            "feature": "unmapped",
            "count": len(u_list),
            "in_feature_map": False,
            "nav": "",
            "description": "Legacy/untagged flows (still searchable via --query)",
            "instruction": "",
            "flows": [f["path"] for f in u_list],
        })
    return rows


def write_manifest(manifest_path: Path, flows: List[Dict[str, Any]], source_desc: str = "") -> Path:
    """Write a deduplicated `.flows` manifest consumable by `suite-runner.py`."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Maestro regression manifest (generated by yaml_index.py)"]
    if source_desc:
        lines.append(f"# Source: {source_desc}")
    seen: Set[str] = set()
    for f in flows:
        p = f["path"]
        if p not in seen:
            seen.add(p)
            lines.append(p)
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_path


def _print_coverage(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        print("No features or YAML flows found under .maestro/.")
        return
    print(f"{'FEATURE':<28} {'FLOWS':>5}  {'NAV':<30} DESCRIPTION")
    print("-" * 100)
    unmapped_flows: List[str] = []
    for r in rows:
        nav_disp = Path(r["nav"]).name if r["nav"] else "-"
        desc_disp = (r["description"] or ("(inferred from folder)" if not r["in_feature_map"] else "-"))[:50]
        print(f"{r['feature']:<28} {r['count']:>5}  {nav_disp:<30} {desc_disp}")
        if r["feature"] == "unmapped":
            unmapped_flows = r["flows"]
    if unmapped_flows:
        print(f"\nUnmapped legacy flows ({len(unmapped_flows)}, showing up to 10):")
        for p in unmapped_flows[:10]:
            print(f"  - {p}")


def _print_lookup(
    matched_features: List[str],
    matched_flows: List[Dict[str, Any]],
    feature_map: Dict[str, Dict[str, Any]],
) -> None:
    if matched_features:
        print("Matched features:")
        for slug in matched_features[:5]:
            cfg = feature_map.get(slug, {})
            desc = str(cfg.get("description", "")).strip()
            instr = str(cfg.get("instruction", "")).strip()
            nav = str(cfg.get("nav", "")).strip()
            print(f"  * {slug}" + (f" — {desc}" if desc else ""))
            if nav:
                print(f"      nav: {nav}")
            if instr:
                print(f"      instruction: {instr}")
    if not matched_flows:
        print("No existing YAML flows matched.")
        return
    print(f"Matched existing YAML flows ({len(matched_flows)}):")
    for f in matched_flows:
        helper_note = f" | helpers: {', '.join(Path(h).name for h in f['helpers'][:2])}" if f["helpers"] else ""
        print(f"  - [{f['feature']}] {f['path']} — {f['name']}{helper_note}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="In-memory Feature Map + Maestro YAML flow indexer (Lean v2)."
    )
    parser.add_argument("--root", default=".maestro", help="Maestro root directory (default: .maestro)")
    parser.add_argument("--feature-map", default=None, help="Optional path to feature-map.json")
    parser.add_argument("--feature", action="append", default=[], help="Filter by feature slug (repeatable or comma-separated)")
    parser.add_argument("--files", nargs="+", default=[], help="Changed source file paths to match against features/flows")
    parser.add_argument("--query", default="", help="Free-text keywords from ticket/PRD (searches all flows including unmapped)")
    parser.add_argument("--coverage", action="store_true", help="Show per-feature YAML coverage table")
    parser.add_argument("--limit", type=int, default=15, help="Max flows to return (default: 15)")
    parser.add_argument("--out-manifest", default="", help="Write matched flow paths to a .flows manifest for suite-runner.py")
    parser.add_argument("--json", action="store_true", help="Output structured JSON")
    args = parser.parse_args(argv)

    maestro_root = Path(args.root)
    explicit_map = Path(args.feature_map) if args.feature_map else None
    feature_map = load_feature_map(maestro_root, explicit_map)
    flows = scan_flows(maestro_root, feature_map)

    has_lookup = bool(args.feature or args.files or args.query)
    if args.coverage or not has_lookup:
        rows = build_coverage(flows, feature_map)
        if args.json:
            print(json.dumps({"features": rows}, indent=2))
        else:
            _print_coverage(rows)
        return 0

    matched_features, matched_flows = match_flows(
        flows,
        feature_map,
        features=args.feature,
        files=args.files,
        query=args.query,
        limit=args.limit,
    )

    if args.out_manifest:
        desc_parts = []
        if args.feature:
            desc_parts.append(f"feature={','.join(args.feature)}")
        if args.files:
            desc_parts.append(f"files={len(args.files)}")
        if args.query:
            desc_parts.append(f"query={args.query}")
        write_manifest(Path(args.out_manifest), matched_flows, "; ".join(desc_parts))

    if args.json:
        payload = {
            "matched_features": [
                {"slug": s, **(feature_map.get(s, {}))}
                for s in matched_features
            ],
            "flows": matched_flows,
            "manifest": args.out_manifest or None,
        }
        print(json.dumps(payload, indent=2))
    else:
        _print_lookup(matched_features, matched_flows, feature_map)
        if args.out_manifest:
            print(f"Manifest written: {args.out_manifest} ({len(matched_flows)} flows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
