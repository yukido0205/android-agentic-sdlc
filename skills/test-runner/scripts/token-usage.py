#!/usr/bin/env python3
"""Measures the tokens one test run cost, from the session transcript written by Antigravity or Claude Code.

Real API usage numbers, not an estimate:
  token-usage.py start              mark the start of the run (call before anything else)
  token-usage.py report <out.md> [--until <ISO-UTC>]
                                    write the report for everything since `start`, print a summary;
                                    --until drops calls made after the run ended (late or recovered reports)

Per-tool cost is the growth of the context between two consecutive API calls, charged to the tools
the earlier call used: that growth is the tool results the next call had to read.
"""
import datetime as dt
import glob
import json
import os
import re
import sys

MARK = ".maestro/.run/token-start.json"  # outside app/build, so `./gradlew clean` cannot delete it mid-run


def detect_transcript():
    """Detects whether running inside Antigravity or Claude Code, returning (path, format)."""
    # Claude Code sets CLAUDECODE=1 in every shell it starts; checking it first keeps a recently used
    # Antigravity transcript from being measured instead of this session.
    if os.environ.get("CLAUDECODE") == "1":
        return claude_transcript()

    # 1. Antigravity environment
    conv_id = os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
    app_dir = os.environ.get("ANTIGRAVITY_APP_DATA_DIR", os.path.expanduser("~/.gemini/antigravity"))
    if conv_id and app_dir:
        t_path = os.path.join(app_dir, "brain", conv_id, ".system_generated", "logs", "transcript.jsonl")
        if os.path.isfile(t_path):
            return t_path, "antigravity"

    # Also search recent brain folders if env vars not exported
    brain_glob = glob.glob(os.path.expanduser("~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl"))
    if brain_glob:
        newest_brain = max(brain_glob, key=os.path.getmtime)
        # If modified in the last 30 minutes, it's our active session
        if time_diff_minutes(newest_brain) < 30:
            return newest_brain, "antigravity"

    # 2. Claude Code environment
    return claude_transcript()


def claude_transcript():
    proj = os.path.expanduser("~/.claude/projects/" + re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()))
    files = glob.glob(proj + "/*.jsonl")
    if files:
        return max(files, key=os.path.getmtime), "claude"
    return None, "unknown"


def time_diff_minutes(path):
    try:
        return (os.path.getmtime(path) - dt.datetime.now().timestamp()) / -60.0
    except Exception:
        return 999999


def transcript():
    path, _ = detect_transcript()
    return path


def history(path, fmt):
    """Requests the user typed in this session, the context size of the latest API call, and latest user prompt timestamp."""
    if not path or not os.path.isfile(path):
        return 0, 0, ""
    typed, last_ctx, last_user_ts = 0, 0, ""

    if fmt == "antigravity":
        for line in open(path):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") == "PLANNER_RESPONSE" and (o.get("input_tokens") or o.get("output_tokens")):
                last_ctx = o.get("input_tokens", 0) + o.get("cache_read_tokens", 0) + o.get("cache_write_tokens", 0)
            if o.get("type") == "USER_INPUT":
                typed += 1
                if o.get("created_at"):
                    last_user_ts = o["created_at"]
    else:
        for line in open(path):
            try:
                o = json.loads(line)
            except Exception:
                continue
            m = o.get("message", {})
            if o.get("type") == "assistant" and m.get("usage"):
                last_ctx = ctx(m["usage"])
            if o.get("type") != "user" or o.get("isMeta"):
                continue
            c = m.get("content")
            text = c if isinstance(c, str) else " ".join(
                b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text")
            text = text.strip()
            if text and not text.startswith("<") and not text.startswith("Base directory for this skill"):
                typed += 1
                if o.get("timestamp"):
                    last_user_ts = o["timestamp"]

    return typed, last_ctx, last_user_ts


def calls(path, since, fmt, until=None):
    merged = []
    if fmt == "antigravity":
        for line in open(path):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") != "PLANNER_RESPONSE" or not (o.get("input_tokens") or o.get("output_tokens")):
                continue
            created_at = o.get("created_at", "")
            if since and created_at and created_at < since:
                continue
            if until and created_at and created_at > until:
                continue
            tools = [tc.get("name") for tc in o.get("tool_calls", []) if isinstance(tc, dict) and "name" in tc]
            merged.append({
                "usage": {
                    "input_tokens": o.get("input_tokens", 0),
                    "cache_read_input_tokens": o.get("cache_read_tokens", 0),
                    "cache_creation_input_tokens": o.get("cache_write_tokens", 0),
                    "output_tokens": o.get("output_tokens", 0),
                },
                "tools": tools,
            })
    else:
        id_map = {}
        for line in open(path):
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") != "assistant" or o.get("timestamp", "") < since:
                continue
            if until and o.get("timestamp", "") > until:
                continue
            m = o.get("message", {})
            if not m.get("usage"):
                continue
            c = id_map.setdefault(m["id"], {"usage": m["usage"], "tools": []})
            c["tools"] += [b["name"] for b in m.get("content", []) if isinstance(b, dict) and b.get("type") == "tool_use"]
        merged = list(id_map.values())

    return merged


def ctx(u):
    return u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)


def cmd_start():
    os.makedirs(os.path.dirname(MARK), exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    path, fmt = detect_transcript()
    if not path:
        json.dump({"file": None, "since": now, "fmt": "unknown"}, open(MARK, "w"))
        print(f"token count started {now} (transcript not available in current environment)")
        return
    typed, last_ctx, last_user_ts = history(path, fmt)
    since_ts = "" if typed <= 1 else (last_user_ts or now)
    json.dump({"file": path, "since": since_ts, "fmt": fmt, "start_ctx": last_ctx}, open(MARK, "w"))
    print(f"token count started {since_ts or now} · environment: {fmt}")
    print(f"session: {typed} request(s) so far · context of the last call {last_ctx:,}")
    if typed > 1:
        print(f"WARNING: old session — every call of this run re-reads {last_ctx:,} tokens of earlier work; "
              "a new session would be cheaper")


def cmd_report(out, until=None):
    mark = json.load(open(MARK))
    if not mark.get("file") or not os.path.isfile(mark["file"]):
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        open(out, "w").write("# E2E test run — token usage\n\nToken tracking not available in current environment.\n")
        print(f"token tracking skipped in this environment\n→ {out}")
        return

    fmt = mark.get("fmt", "claude")
    cs = calls(mark["file"], mark["since"], fmt, until)
    if not cs:
        start_ctx = mark.get("start_ctx", 0)
        lines = [
            "# E2E test run — token usage",
            "",
            f"Since {mark['since'] or 'the start of the session'}" + (f" until {until}" if until else "") + f" · 0 API calls · environment `{fmt}` · transcript `{os.path.basename(mark['file'])}`",
            "",
            "| | tokens |",
            "|---|---:|",
            "| Input, uncached | 0 |",
            "| Input, cache write | 0 |",
            "| Input, cache read | 0 |",
            "| Output (incl. 0 thinking) | 0 |",
            f"| Context at start → end | {start_ctx:,} → {start_ctx:,} |",
            "| **Carried in** (start context × 0 calls) | 0 — 0% of all input |",
            "",
            "Zero LLM API calls were made during this run (100% native execution).",
        ]
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        open(out, "w").write("\n".join(lines) + "\n")
        print(f"0 calls · 0 tokens (native execution, zero LLM token bleed)\n→ {out}")
        return
    tot = lambda k: sum(c["usage"].get(k, 0) for c in cs)
    thinking = sum(c["usage"].get("output_tokens_details", {}).get("thinking_tokens", 0) for c in cs)

    by_tool, biggest, compacted = {}, [], 0
    for prev, nxt in zip(cs, cs[1:]):
        grown = ctx(nxt["usage"]) - ctx(prev["usage"]) - prev["usage"].get("output_tokens", 0)
        if grown < 0:  # Context was compacted
            compacted += 1
            continue
        tools = prev["tools"] or ["(user message)"]
        for t in tools:
            name = t.replace("mcp__maestro__", "maestro:")
            n, total = by_tool.get(name, (0, 0))
            by_tool[name] = (n + 1, total + grown // len(tools))
        biggest.append((grown, ", ".join(tools)))

    rows = sorted(by_tool.items(), key=lambda kv: -kv[1][1])
    carried = ctx(cs[0]["usage"]) * len(cs)
    all_in = sum(ctx(c["usage"]) for c in cs) or 1
    lines = [
        "# E2E test run — token usage",
        "",
        f"Since {mark['since'] or 'the start of the session'}" + (f" until {until}" if until else "") + f" · {len(cs)} API calls · environment `{fmt}` · transcript `{os.path.basename(mark['file'])}`",
        "",
        "| | tokens |",
        "|---|---:|",
        f"| Input, uncached | {tot('input_tokens'):,} |",
        f"| Input, cache write | {tot('cache_creation_input_tokens'):,} |",
        f"| Input, cache read | {tot('cache_read_input_tokens'):,} |",
        f"| Output (incl. {thinking:,} thinking) | {tot('output_tokens'):,} |",
        f"| Context at start → end | {ctx(cs[0]['usage']):,} → {ctx(cs[-1]['usage']):,} |",
        f"| **Carried in** (start context × {len(cs)} calls) | {carried:,} — {carried * 100 // all_in}% of all input |",
        "",
        "## Context added, by tool",
        "",
        "| tool | calls | tokens added |",
        "|---|---:|---:|",
        *[f"| {t} | {n} | {total:,} |" for t, (n, total) in rows],
        "",
        "## Five largest single additions",
        "",
        *[f"- {g:,} — {t}" for g, t in sorted(biggest, reverse=True)[:5]],
        "",
        "Not counted: the final message written after this report."
        + (f" {compacted} compaction(s) during the run; growth across them is not charged." if compacted else ""),
    ]
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "w").write("\n".join(lines) + "\n")
    top = ", ".join(f"{t} {total:,}" for t, (_, total) in rows[:3])
    print(f"carried-in context {carried * 100 // all_in}% of input (start {ctx(cs[0]['usage']):,} × {len(cs)} calls)")
    print(f"{len(cs)} calls · output {tot('output_tokens'):,} · cache read {tot('cache_read_input_tokens'):,} · top: {top}\n→ {out}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "start":
        cmd_start()
    elif len(sys.argv) == 3 and sys.argv[1] == "report":
        cmd_report(sys.argv[2])
    elif len(sys.argv) == 5 and sys.argv[1] == "report" and sys.argv[3] == "--until":
        cmd_report(sys.argv[2], sys.argv[4])
    else:
        sys.exit(__doc__)
