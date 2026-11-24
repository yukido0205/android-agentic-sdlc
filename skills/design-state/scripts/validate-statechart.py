#!/usr/bin/env python3
"""
validate-statechart.py — Static validator for Dual-Representation Statecharts
(Mermaid `stateDiagram-v2` + Transition & Guard Table) in Markdown specs.

Enforces:
1. Structure: Mermaid stateDiagram-v2 has `[*] --> <Initial>` and a matching Transition Table.
2. Reachability: Every state is reachable from root `[*]` via BFS.
3. Dead-End Detection: Every non-terminal state has at least one real outgoing transition
   (`IGNORE` and `DROP` do not count as exits; composite children inherit parent exits).
4. Graph <-> Table Alignment: Zero drift between Mermaid states and Transition Table states.
5. Determinism: Same `(State, Event, Guard)` cannot map to multiple distinct `Next State`s.
6. Async Safety (Warnings): Async states (`Loading`, `Submitting`, etc.) should handle
   failure/timeout/cancel exits and double-tap/stale-callback protection (`IGNORE` / `DROP`).
7. Cognitive Budget (Warning): Keep statecharts <= 12 concrete states per diagram.
8. Lifecycle Recovery (Warning): Document Process Death / Config Change behavior.

Zero external dependencies (Python 3.9+ stdlib only).
"""

import argparse
import json
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ANSI colors (aligned with validate-flow.py)
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"

MAX_COGNITIVE_STATES = 12

SKIPPED_RE = re.compile(r"Statechart:\s*SKIPPED\b", re.IGNORECASE)
IGNORE_MARKER_RE = re.compile(r"(?:%%\s*statechart-ignore\b|<!--\s*statechart-ignore\s*-->)", re.IGNORECASE)
BEFORE_HEADING_RE = re.compile(r"^(#{1,6})\s+before(?:\s*\(|\s*:|\s*$)", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
LIFECYCLE_RE = re.compile(
    r"(Lifecycle\s+Recovery|Process\s+death|SavedStateHandle|Config(?:uration)?\s+change)",
    re.IGNORECASE,
)

MERMAID_OPEN_RE = re.compile(r"^\s*(`{3,})\s*mermaid\s*$", re.IGNORECASE)
FENCE_OPEN_RE = re.compile(r"^\s*(`{3,})\s*\S*")
FENCE_CLOSE_RE = re.compile(r"^\s*(`{3,})\s*$")
STATE_DIAGRAM_HDR_RE = re.compile(r"^\s*stateDiagram(?:-v2)?\b")
COMPOSITE_OPEN_RE = re.compile(
    r'^\s*state\s+(?:"([^"]+)"\s+as\s+)?([A-Za-z0-9_.-]+)\s*\{\s*$'
)
STATE_ALIAS_RE = re.compile(r'^\s*state\s+"[^"]+"\s+as\s+([A-Za-z0-9_.-]+)\s*$')
STEREOTYPE_RE = re.compile(
    r"^\s*state\s+([A-Za-z0-9_.-]+)\s*<<(choice|fork|join)>>\s*$", re.IGNORECASE
)
STATE_DESC_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*:\s*(.+)$")
TRANSITION_RE = re.compile(
    r"^\s*(\[\*\]|[A-Za-z0-9_.-]+)\s*-+>\s*(\[\*\]|[A-Za-z0-9_.-]+)(?:\s*:\s*(.+))?$"
)
NOTE_START_RE = re.compile(r"^\s*note\s+(?:left|right)\s+of\b", re.IGNORECASE)
NOTE_END_RE = re.compile(r"^\s*end\s+note\s*$", re.IGNORECASE)
DIRECTIVE_RE = re.compile(r"^\s*(?:direction\s+\w+|classDef\b|class\b|style\b|%%)", re.IGNORECASE)

ASYNC_STATE_HINTS = (
    "loading",
    "submitting",
    "fetching",
    "syncing",
    "uploading",
    "downloading",
    "polling",
    "processing",
    "verifying",
    "sending",
    "refreshing",
    "saving",
    "deleting",
    "debouncing",
    "connecting",
    "retrying",
)

ERROR_OR_CANCEL_HINTS = (
    "error",
    "fail",
    "failure",
    "timeout",
    "offline",
    "cancel",
    "abort",
    "retry",
    "denied",
    "reject",
    "expired",
    "clear",
    "reset",
)

SPECIAL_TARGETS = {"IGNORE", "DROP"}
WILDCARD_SOURCES = {"*", "ANY", "ALL"}
EMPTY_TOKENS = {"", "-", "—", "--", "n/a", "none", "null"}


@dataclass
class MermaidGraph:
    states: Set[str] = field(default_factory=set)
    composite_parents: Set[str] = field(default_factory=set)
    pseudo_states: Set[str] = field(default_factory=set)
    parent_of: Dict[str, Optional[str]] = field(default_factory=dict)
    children_of: Dict[str, Set[str]] = field(default_factory=dict)
    root_initials: Set[str] = field(default_factory=set)
    composite_initials: Dict[str, Set[str]] = field(default_factory=dict)
    edges: List[Tuple[str, str, str]] = field(default_factory=list)  # (src, dst, label)
    terminal_sources: Set[str] = field(default_factory=set)
    start_line: int = 0


@dataclass
class TableRow:
    source: str
    event: str
    guard: str
    target: str
    effect: str
    line_no: int


@dataclass
class ParsedStatechart:
    mermaid: Optional[MermaidGraph] = None
    table_rows: List[TableRow] = field(default_factory=list)
    table_line: int = 0


def _clean_cell(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()
    return text


def _normalize_target_keyword(raw: str) -> str:
    cleaned = _clean_cell(raw)
    upper = cleaned.upper()
    # Handle annotations like "IGNORE *(blocks double-tap)*" or "DROP (stale)"
    head = re.split(r"[\s(]", upper, maxsplit=1)[0]
    if head in SPECIAL_TARGETS:
        return head
    return cleaned


def _normalize_guard(raw: str) -> str:
    cleaned = _clean_cell(raw)
    if cleaned.lower() in EMPTY_TOKENS:
        return "—"
    return re.sub(r"\s+", " ", cleaned)


def _split_md_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    if not cells:
        return False
    return all(bool(re.match(r"^:?-{2,}:?$", c.strip())) for c in cells)


def _parse_mermaid_block(lines: list[str], start_line: int) -> Optional[MermaidGraph]:
    # Locate stateDiagram header
    idx = 0
    while idx < len(lines) and (not lines[idx].strip() or lines[idx].strip().startswith("%%")):
        idx += 1
    if idx >= len(lines) or not STATE_DIAGRAM_HDR_RE.match(lines[idx]):
        return None

    graph = MermaidGraph(start_line=start_line)
    scope_stack: list[str] = []
    in_note = False

    def register_state(name: str, explicit_scope: Optional[str] = None) -> None:
        if name == "[*]":
            return
        graph.states.add(name)
        scope = explicit_scope if explicit_scope is not None else (scope_stack[-1] if scope_stack else None)
        if name not in graph.parent_of or (graph.parent_of[name] is None and scope is not None):
            graph.parent_of[name] = scope
        if scope is not None:
            graph.children_of.setdefault(scope, set()).add(name)

    for raw_line in lines[idx + 1 :]:
        line = raw_line.strip()
        if not line or DIRECTIVE_RE.match(line):
            continue

        if in_note:
            if NOTE_END_RE.match(line):
                in_note = False
            continue
        if NOTE_START_RE.match(line):
            if ":" not in line:
                in_note = True
            continue

        if line == "--":
            # Orthogonal region separator inside composite state
            continue

        if line == "}":
            if scope_stack:
                scope_stack.pop()
            continue

        m_comp = COMPOSITE_OPEN_RE.match(line)
        if m_comp:
            comp_id = m_comp.group(2)
            register_state(comp_id)
            graph.composite_parents.add(comp_id)
            scope_stack.append(comp_id)
            continue

        m_stereo = STEREOTYPE_RE.match(line)
        if m_stereo:
            sid = m_stereo.group(1)
            register_state(sid)
            graph.pseudo_states.add(sid)
            continue

        m_alias = STATE_ALIAS_RE.match(line)
        if m_alias:
            register_state(m_alias.group(1))
            continue

        m_trans = TRANSITION_RE.match(line)
        if m_trans:
            src, dst, label = m_trans.group(1), m_trans.group(2), (m_trans.group(3) or "").strip()
            current_scope = scope_stack[-1] if scope_stack else None
            if src == "[*]":
                if dst != "[*]":
                    register_state(dst)
                    if current_scope is None:
                        graph.root_initials.add(dst)
                    else:
                        graph.composite_initials.setdefault(current_scope, set()).add(dst)
            elif dst == "[*]":
                register_state(src)
                graph.terminal_sources.add(src)
            else:
                register_state(src)
                register_state(dst)
                graph.edges.append((src, dst, label))
            continue

        m_desc = STATE_DESC_RE.match(line)
        if m_desc:
            register_state(m_desc.group(1))
            continue

    return graph


def _match_table_headers(headers: list[str]) -> Optional[dict[str, int]]:
    norm = [re.sub(r"\s+", " ", _clean_cell(h).lower()) for h in headers]
    mapping: dict[str, int] = {}
    for i, col in enumerate(norm):
        if col in ("state", "current state", "from", "from state"):
            mapping.setdefault("state", i)
        elif col in ("event", "intent", "event / intent", "intent / event", "trigger", "action"):
            mapping.setdefault("event", i)
        elif col in ("guard", "guards", "condition"):
            mapping.setdefault("guard", i)
        elif col in ("next state", "target state", "target", "to", "next"):
            mapping.setdefault("next", i)
        elif col in ("effect", "effect / event", "side effect", "output", "effect / ui event"):
            mapping.setdefault("effect", i)

    if "state" in mapping and "event" in mapping and "next" in mapping:
        return mapping
    return None


def _extract_statecharts(content: str) -> List[ParsedStatechart]:
    """Extract Mermaid stateDiagram blocks and Transition Tables from markdown."""
    lines = content.splitlines()
    charts: List[ParsedStatechart] = []

    mermaids: List[Tuple[int, MermaidGraph]] = []
    tables: List[Tuple[int, List[TableRow]]] = []

    i = 0
    non_mermaid_fence_len = 0
    ignored_heading_level: Optional[int] = None
    ignore_next_block = False

    while i < len(lines):
        line = lines[i]

        if non_mermaid_fence_len > 0:
            m_close = FENCE_CLOSE_RE.match(line)
            if m_close and len(m_close.group(1)) >= non_mermaid_fence_len:
                non_mermaid_fence_len = 0
            i += 1
            continue

        # Track `### Before` / `#### Before (Buggy)` sections for Mode 2 (--delta)
        m_hdr = HEADING_RE.match(line.strip())
        if m_hdr:
            lvl = len(m_hdr.group(1))
            if BEFORE_HEADING_RE.match(line.strip()):
                ignored_heading_level = lvl
                i += 1
                continue
            if ignored_heading_level is not None and lvl <= ignored_heading_level:
                ignored_heading_level = None

        if IGNORE_MARKER_RE.search(line):
            ignore_next_block = True
            i += 1
            continue

        m_mermaid = MERMAID_OPEN_RE.match(line)
        if m_mermaid:
            fence_len = len(m_mermaid.group(1))
            start_line = i + 1
            block_lines: List[str] = []
            i += 1
            while i < len(lines):
                m_close = FENCE_CLOSE_RE.match(lines[i])
                if m_close and len(m_close.group(1)) >= fence_len:
                    break
                block_lines.append(lines[i])
                i += 1

            block_ignored = (
                ignored_heading_level is not None
                or ignore_next_block
                or any(IGNORE_MARKER_RE.search(bl) for bl in block_lines)
            )
            ignore_next_block = False

            if not block_ignored:
                graph = _parse_mermaid_block(block_lines, start_line)
                if graph is not None:
                    mermaids.append((start_line, graph))
            i += 1
            continue

        m_fence = FENCE_OPEN_RE.match(line)
        if m_fence:
            non_mermaid_fence_len = len(m_fence.group(1))
            ignore_next_block = False
            i += 1
            continue

        # Check for markdown Transition Table
        if line.strip().startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
            hdr_cells = _split_md_row(line)
            sep_cells = _split_md_row(lines[i + 1])
            col_map = _match_table_headers(hdr_cells) if _is_separator_row(sep_cells) else None
            if col_map is not None:
                table_start = i + 1
                rows: List[TableRow] = []
                i += 2
                while i < len(lines) and lines[i].strip().startswith("|"):
                    cells = _split_md_row(lines[i])
                    if len(cells) >= max(col_map.values()) + 1:
                        src = _clean_cell(cells[col_map["state"]])
                        evt = _clean_cell(cells[col_map["event"]])
                        grd = _normalize_guard(cells[col_map["guard"]]) if "guard" in col_map else "—"
                        nxt = _normalize_target_keyword(cells[col_map["next"]])
                        eff = _clean_cell(cells[col_map["effect"]]) if "effect" in col_map else "—"
                        if src and src not in EMPTY_TOKENS:
                            rows.append(
                                TableRow(
                                    source=src,
                                    event=evt,
                                    guard=grd,
                                    target=nxt,
                                    effect=eff,
                                    line_no=i + 1,
                                )
                            )
                    i += 1

                table_ignored = (ignored_heading_level is not None) or ignore_next_block
                ignore_next_block = False
                if not table_ignored:
                    tables.append((table_start, rows))
                continue

        if line.strip():
            ignore_next_block = False
        i += 1

    # Pair each Mermaid diagram with the first Transition Table that follows it
    # (before the next Mermaid diagram). Unpaired tables/diagrams are kept for error reporting.
    used_tables: set[int] = set()
    for m_idx, (m_line, graph) in enumerate(mermaids):
        next_m_line = mermaids[m_idx + 1][0] if m_idx + 1 < len(mermaids) else sys.maxsize
        paired_t_idx: Optional[int] = None
        for t_idx, (t_line, _) in enumerate(tables):
            if t_idx in used_tables:
                continue
            if m_line < t_line < next_m_line:
                paired_t_idx = t_idx
                break

        if paired_t_idx is not None:
            used_tables.add(paired_t_idx)
            t_line, rows = tables[paired_t_idx]
            charts.append(ParsedStatechart(mermaid=graph, table_rows=rows, table_line=t_line))
        else:
            charts.append(ParsedStatechart(mermaid=graph))

    for t_idx, (t_line, rows) in enumerate(tables):
        if t_idx not in used_tables:
            charts.append(ParsedStatechart(table_rows=rows, table_line=t_line))

    return charts


def _all_ancestors(state: str, parent_of: dict[str, Optional[str]]) -> list[str]:
    ancestors: list[str] = []
    cur = parent_of.get(state)
    seen: set[str] = set()
    while cur is not None and cur not in seen:
        ancestors.append(cur)
        seen.add(cur)
        cur = parent_of.get(cur)
    return ancestors


def _validate_single_chart(
    chart: ParsedStatechart,
    content: str,
    allow_diagram_only: bool = False,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    graph = chart.mermaid
    rows = chart.table_rows

    if graph is None and rows:
        errors.append(
            f"[MISSING_DIAGRAM] Transition Table at line {chart.table_line} has no matching "
            "Mermaid `stateDiagram-v2` block."
        )
        return errors, warnings

    if graph is not None and not rows and not allow_diagram_only:
        errors.append(
            f"[MISSING_TABLE] Mermaid `stateDiagram-v2` at line {graph.start_line} has no matching "
            "Transition & Guard Table (`| State | Event / Intent | Guard | Next State | Effect / Event |`)."
        )
        return errors, warnings

    assert graph is not None

    # 1. Initial state check
    if not graph.root_initials:
        errors.append(
            f"[MISSING_INITIAL_STATE] Mermaid `stateDiagram-v2` (line {graph.start_line}) "
            "must declare at least one root initial transition `[*] --> <InitialState>`."
        )

    # Build combined transition graph (Mermaid + Table excluding IGNORE/DROP)
    adj: dict[str, set[str]] = {s: set() for s in graph.states}
    real_outgoing: dict[str, set[str]] = {s: set() for s in graph.states}
    terminal_capable: set[str] = set(graph.terminal_sources)

    for src, dst, _ in graph.edges:
        adj.setdefault(src, set()).add(dst)
        if dst != src:
            real_outgoing.setdefault(src, set()).add(dst)

    # Table rows analysis
    table_states: set[str] = set()
    seen_determinism: dict[tuple[str, str, str], tuple[str, int]] = {}
    has_drop_rule = False
    states_with_ignore: set[str] = set()
    async_error_covered: set[str] = set()

    for row in rows:
        src = row.source
        dst = row.target
        src_upper = src.upper()

        if src != "[*]" and src_upper not in WILDCARD_SOURCES:
            table_states.add(src)
        if dst not in ("[*]", *SPECIAL_TARGETS) and dst not in EMPTY_TOKENS:
            table_states.add(dst)

        # Determinism check
        det_key = (src, row.event, row.guard)
        if det_key in seen_determinism:
            prev_dst, prev_line = seen_determinism[det_key]
            if prev_dst != dst:
                errors.append(
                    f"[NON_DETERMINISTIC] Duplicate `(State='{src}', Event='{row.event}', Guard='{row.guard}')` "
                    f"at lines {prev_line} & {row.line_no} maps to different targets ('{prev_dst}' vs '{dst}')."
                )
        else:
            seen_determinism[det_key] = (dst, row.line_no)

        if dst == "DROP":
            has_drop_rule = True
            continue
        if dst == "IGNORE":
            states_with_ignore.add(src)
            continue
        if dst in EMPTY_TOKENS:
            continue

        if src == "[*]":
            if dst != "[*]":
                graph.root_initials.add(dst)
        elif src_upper in WILDCARD_SOURCES:
            # Global transition applies to all non-terminal states
            for s in graph.states:
                if dst == "[*]":
                    terminal_capable.add(s)
                else:
                    adj.setdefault(s, set()).add(dst)
                    if dst != s:
                        real_outgoing.setdefault(s, set()).add(dst)
        else:
            if dst == "[*]":
                terminal_capable.add(src)
            else:
                adj.setdefault(src, set()).add(dst)
                if dst != src:
                    real_outgoing.setdefault(src, set()).add(dst)

        # Async error/cancel heuristic from table
        combined_hint = f"{row.event} {row.guard} {dst}".lower()
        if any(h in combined_hint for h in ERROR_OR_CANCEL_HINTS) or dst == "[*]":
            async_error_covered.add(src)

    # Also check Mermaid edges for async error/cancel hints
    for src, dst, label in graph.edges:
        combined_hint = f"{label} {dst}".lower()
        if any(h in combined_hint for h in ERROR_OR_CANCEL_HINTS):
            async_error_covered.add(src)
    for src in graph.terminal_sources:
        async_error_covered.add(src)

    # 2. Graph <-> Table alignment (only when table is present)
    if rows:
        for ts in sorted(table_states):
            if ts not in graph.states:
                errors.append(
                    f"[DRIFT_TABLE_TO_MERMAID] State `{ts}` appears in Transition Table "
                    f"but is missing from Mermaid `stateDiagram-v2` (line {graph.start_line})."
                )

        leaf_mermaid_states = {
            s
            for s in graph.states
            if s not in graph.composite_parents and s not in graph.pseudo_states
        }
        for ms in sorted(leaf_mermaid_states):
            if ms not in table_states:
                errors.append(
                    f"[DRIFT_MERMAID_TO_TABLE] State `{ms}` appears in Mermaid `stateDiagram-v2` "
                    f"(line {graph.start_line}) but has no entry in the Transition Table."
                )

    # 3. Reachability via BFS from root initials (entering composite enters its composite_initials)
    reachable: set[str] = set()
    queue: deque[str] = deque(sorted(graph.root_initials))
    while queue:
        cur = queue.popleft()
        if cur in reachable:
            continue
        reachable.add(cur)

        # Entering a composite state enters its initial children
        for child_init in graph.composite_initials.get(cur, set()):
            if child_init not in reachable:
                queue.append(child_init)

        # Outgoing transitions from cur (and inherited from ancestors? No, outgoing reaches targets)
        for nxt in adj.get(cur, set()):
            if nxt not in reachable:
                queue.append(nxt)

    for s in sorted(graph.states):
        if s not in reachable:
            errors.append(
                f"[UNREACHABLE_STATE] State `{s}` cannot be reached from `[*] --> <Initial>` "
                f"(line {graph.start_line})."
            )

    # 4. Dead-end check for concrete states
    # A state has an exit if:
    # - it is terminal-capable (`State --> [*]`), OR
    # - it has at least one real outgoing transition to a different state, OR
    # - it is a composite parent whose children handle exits (composite parents themselves aren't dead-ends if children exit, or parent itself has outgoing), OR
    # - any of its composite ancestors is terminal-capable or has a real outgoing transition.
    for s in sorted(graph.states):
        if s in graph.pseudo_states:
            continue
        if s in graph.composite_parents:
            # Check if composite parent itself has no exit AND none of its children exit the composite
            children = graph.children_of.get(s, set())
            has_parent_exit = bool(real_outgoing.get(s)) or (s in terminal_capable)
            has_child_exit = any(
                (c in terminal_capable) or any(dst not in children for dst in real_outgoing.get(c, set()))
                for c in children
            )
            if not has_parent_exit and not has_child_exit:
                errors.append(
                    f"[DEAD_END_STATE] Composite state `{s}` has no exit transition (`--> [*]` or external target)."
                )
            continue

        ancestors = _all_ancestors(s, graph.parent_of)
        can_exit = (
            (s in terminal_capable)
            or bool(real_outgoing.get(s))
            or any((anc in terminal_capable) or bool(real_outgoing.get(anc)) for anc in ancestors)
        )
        if not can_exit:
            errors.append(
                f"[DEAD_END_STATE] State `{s}` is a dead-end (no outgoing transition to another state or `[*]`; "
                "`IGNORE`/`DROP` do not count as exits)."
            )

    # 5. Async Safety warnings
    concrete_states = {s for s in graph.states if s not in graph.pseudo_states}
    for s in sorted(concrete_states):
        s_lower = s.lower()
        if any(hint in s_lower for hint in ASYNC_STATE_HINTS):
            ancestors = _all_ancestors(s, graph.parent_of)
            covered_err = (s in async_error_covered) or any(anc in async_error_covered for anc in ancestors)
            if not covered_err:
                warnings.append(
                    f"[ASYNC_MISSING_ERROR_OR_CANCEL] Async state `{s}` has no Failure/Timeout/Cancel exit transition."
                )
            if rows and (s not in states_with_ignore) and not has_drop_rule:
                warnings.append(
                    f"[ASYNC_MISSING_REENTRY_GUARD] Async state `{s}` has no `IGNORE` (double-tap) "
                    "or `DROP` (stale callback) rule in the Transition Table."
                )

    # 6. Cognitive Budget warning
    if len(concrete_states) > MAX_COGNITIVE_STATES:
        warnings.append(
            f"[COGNITIVE_BUDGET] Statechart has {len(concrete_states)} states (recommended <= {MAX_COGNITIVE_STATES}). "
            "Group sub-states into composite blocks or split into smaller slices."
        )

    # 7. Lifecycle Recovery warning
    if not LIFECYCLE_RE.search(content):
        warnings.append(
            "[MISSING_LIFECYCLE_RECOVERY] Document does not specify **Lifecycle Recovery** "
            "(Process death / SavedStateHandle / Config change behavior)."
        )

    return errors, warnings


def validate_file(
    file_path: Path,
    require_statechart: bool = True,
    allow_diagram_only: bool = False,
) -> tuple[list[str], list[str], bool]:
    """Validate a markdown file. Returns (errors, warnings, was_skipped)."""
    content = file_path.read_text(encoding="utf-8")
    charts = _extract_statecharts(content)

    if not charts:
        if SKIPPED_RE.search(content) or not require_statechart:
            return [], [], True
        return (
            [
                f"No Statechart found in '{file_path.name}'. Add a Mermaid `stateDiagram-v2` + "
                "Transition Table, or explicitly mark `Statechart: SKIPPED (<reason>)`."
            ],
            [],
            False,
        )

    all_errors: list[str] = []
    all_warnings: list[str] = []
    for chart in charts:
        errs, wrns = _validate_single_chart(chart, content, allow_diagram_only=allow_diagram_only)
        all_errors.extend(errs)
        all_warnings.extend(wrns)

    return all_errors, all_warnings, False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate Dual-Representation Statecharts (Mermaid stateDiagram-v2 + Transition Table)."
    )
    parser.add_argument("target", help="Path to a Markdown spec file or directory")
    parser.add_argument(
        "--allow-diagram-only",
        action="store_true",
        help="Allow Mermaid stateDiagram-v2 without a Transition Table",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit machine-readable JSON output",
    )
    args = parser.parse_args()

    target_path = Path(args.target).resolve()
    if not target_path.exists():
        if args.json_output:
            print(json.dumps({"error": f"Target not found: {target_path}"}))
        else:
            print(f"{RED}Target not found: {target_path}{RESET}")
        sys.exit(1)

    if target_path.is_file():
        files = [target_path]
        require_sc = True
    else:
        files = sorted(target_path.rglob("*.md"))
        require_sc = False

    if not files:
        if args.json_output:
            print(json.dumps({"error": f"No .md files found in {target_path}"}))
        else:
            print(f"{RED}No .md files found in {target_path}{RESET}")
        sys.exit(1)

    total_errors = 0
    total_warnings = 0
    validated_count = 0
    json_results = []

    if not args.json_output:
        print(f"\n{BOLD}{BLUE}==================================================")
        print("  STATECHART VALIDATOR")
        print(f"  Target: {target_path}")
        print(f"  Files : {len(files)}")
        print(f"=================================================={RESET}\n")

    for f in files:
        rel_path = f.name
        try:
            rel_path = str(f.relative_to(Path.cwd()))
        except ValueError:
            rel_path = str(f)

        errors, warnings, skipped = validate_file(
            f, require_statechart=require_sc, allow_diagram_only=args.allow_diagram_only
        )
        if skipped:
            if args.json_output:
                json_results.append({"file": rel_path, "status": "SKIPPED", "errors": [], "warnings": []})
            elif target_path.is_file():
                print(f"{BLUE}SKIP{RESET}  {rel_path} (Statechart: SKIPPED)")
            continue

        validated_count += 1
        total_errors += len(errors)
        total_warnings += len(warnings)

        if args.json_output:
            status = "FAIL" if errors else ("WARN" if warnings else "PASS")
            json_results.append(
                {"file": rel_path, "status": status, "errors": errors, "warnings": warnings}
            )
        else:
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

    if args.json_output:
        print(
            json.dumps(
                {
                    "validated_files": validated_count,
                    "errors": total_errors,
                    "warnings": total_warnings,
                    "results": json_results,
                },
                indent=2,
            )
        )
    else:
        print(
            f"\n{BOLD}Summary:{RESET} {validated_count} statechart(s) validated | "
            f"{RED}{total_errors} errors{RESET} | {YELLOW}{total_warnings} warnings{RESET}"
        )
        if total_errors > 0:
            print(f"{RED}{BOLD}Validation failed.{RESET} Fix statechart errors before Gate 1 / Freeze.\n")
        else:
            print(f"{GREEN}{BOLD}Statechart validation passed!{RESET}\n")

    sys.exit(1 if total_errors > 0 else 0)


if __name__ == "__main__":
    main()
