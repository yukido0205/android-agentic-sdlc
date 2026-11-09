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
    """Detects whether running inside Antigravity or Claude Code, returning (path, format, warning)."""
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
            return t_path, "antigravity", None

    # Also search recent brain folders if env vars not exported
    brain_glob = glob.glob(os.path.expanduser("~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl"))
    if brain_glob:
        newest_brain = max(brain_glob, key=os.path.getmtime)
        # If modified in the last 30 minutes, it's our active session
        if time_diff_minutes(newest_brain) < 30:
            return newest_brain, "antigravity", None

    # 2. Claude Code environment
    return claude_transcript()


def claude_transcript():
    # Prefer explicit transcript path or session ID from environment if available
    env_path = os.environ.get("CLAUDE_TRANSCRIPT_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path, "claude", None

    proj = os.path.expanduser("~/.claude/projects/" + re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()))
    for env_key in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID"):
        sid = os.environ.get(env_key)
        if sid:
            candidate = os.path.join(proj, f"{sid}.jsonl")
            if os.path.isfile(candidate):
                return candidate, "claude", None

    files = glob.glob(proj + "/*.jsonl")
    if files:
        files.sort(key=os.path.getmtime, reverse=True)
        chosen = files[0]
        chosen_mtime = os.path.getmtime(chosen)
        # Warn if multiple transcripts in the same project were modified recently (within 5 minutes of the newest)
        concurrent = [
            os.path.basename(f) for f in files[1:]
            if abs(chosen_mtime - os.path.getmtime(f)) < 300 and time_diff_minutes(f) < 15
        ]
        warn = None
        if concurrent:
            warn = (
                f"WARNING: multiple recently active transcripts in project folder "
                f"(picked {os.path.basename(chosen)}; also active: {', '.join(concurrent[:3])})"
            )
        return chosen, "claude", warn
    return None, "unknown", None


def time_diff_minutes(path):
    try:
        return (os.path.getmtime(path) - dt.datetime.now().timestamp()) / -60.0
    except Exception:
        return 999999


def transcript():
    path, _, _ = detect_transcript()
    return path


def is_user_prompt(text):
    """Returns True if a Claude user message represents an actual user prompt (typed or slash command)."""
    if not text or text.startswith("Base directory for this skill"):
        return False
    if "<command-name>" in text or "<command-message>" in text:
        return True
    return not text.startswith("<")


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
            if is_user_prompt(text):
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


def subagent_calls(main_path, since, fmt, until=None):
    """Returns list of (agent_name, calls_list) for each subagent transcript active in [since, until]."""
    if not main_path or fmt != "claude":
        return []
    sub_dir = os.path.join(os.path.splitext(main_path)[0], "subagents")
    if not os.path.isdir(sub_dir):
        return []
    result = []
    for sf in sorted(glob.glob(os.path.join(sub_dir, "*.jsonl"))):
        sc = calls(sf, since, fmt, until)
        if sc:
            agent_name = os.path.splitext(os.path.basename(sf))[0]
            result.append((agent_name, sc))
    return result


def ctx(u):
    return u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)


def cmd_start():
    os.makedirs(os.path.dirname(MARK), exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    old_mark = None
    if os.path.isfile(MARK):
        try:
            old_mark = json.load(open(MARK))
        except Exception:
            print("WARNING: replacing corrupted token-start mark")

    path, fmt, warn = detect_transcript()
    if not path:
        if old_mark is not None:
            old_ts = old_mark.get("created_at") or old_mark.get("since") or "unknown time"
            print(f"WARNING: replacing stale token-start mark from {old_ts}")
        json.dump(
            {"file": None, "since": now, "fmt": "unknown", "created_at": now, "pid": os.getpid()},
            open(MARK, "w"),
        )
        print(f"token count started {now} (transcript not available in current environment)")
        return
    typed, last_ctx, last_user_ts = history(path, fmt)
    since_ts = "" if typed <= 1 else (last_user_ts or now)
    if old_mark is not None:
        same_turn = (
            old_mark.get("file") == path
            and old_mark.get("since") == since_ts
            and old_mark.get("last_user_ts") == last_user_ts
            and bool(old_mark.get("created_at"))
        )
        if not same_turn:
            old_ts = old_mark.get("created_at") or old_mark.get("since") or "unknown time"
            print(f"WARNING: replacing stale token-start mark from {old_ts}")
        else:
            # Preserve initial context from earlier in the same turn if manually started
            last_ctx = old_mark.get("start_ctx", last_ctx)

    mark_data = {
        "file": path,
        "since": since_ts,
        "last_user_ts": last_user_ts,
        "fmt": fmt,
        "start_ctx": last_ctx,
        "created_at": now,
        "pid": os.getpid(),
    }
    if warn:
        mark_data["warning"] = warn
    json.dump(mark_data, open(MARK, "w"))
    print(f"token count started {since_ts or now} · environment: {fmt}")
    print(f"session: {typed} request(s) so far · context of the last call {last_ctx:,}")
    if warn:
        print(warn)
    if typed > 1:
        print(f"WARNING: old session — every call of this run re-reads {last_ctx:,} tokens of earlier work; "
              "a new session would be cheaper")


def cmd_report(out, until=None):
    if not os.path.isfile(MARK):
        sys.exit(f"No token-start mark at {MARK} — run `token-usage.py start` first.")
    mark = json.load(open(MARK))
    if not mark.get("file") or not os.path.isfile(mark["file"]):
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        open(out, "w").write("# E2E test run — token usage\n\nToken tracking not available in current environment.\n")
        print(f"token tracking skipped in this environment\n→ {out}")
        return

    fmt = mark.get("fmt", "claude")
    cs = calls(mark["file"], mark["since"], fmt, until)
    sub_runs = subagent_calls(mark["file"], mark["since"], fmt, until)
    sub_cs = [c for _, sc in sub_runs for c in sc]
    warn = mark.get("warning")

    if not cs and not sub_cs:
        start_ctx = mark.get("start_ctx", 0)
        lines = [
            "# E2E test run — token usage",
            "",
            f"Since {mark['since'] or 'the start of the session'}" + (f" until {until}" if until else "") + f" · 0 API calls · environment `{fmt}` · transcript `{os.path.basename(mark['file'])}`",
        ]
        if warn:
            lines += ["", f"> ⚠️ {warn}"]
        lines += [
            "",
            "| | tokens |",
            "|---|---:|",
            "| Input, uncached | 0 |",
            "| Input, cache write | 0 |",
            "| Input, cache read | 0 |",
            "| Output (incl. 0 thinking) | 0 |",
            "| Subagents | 0 |",
            f"| Context at start → end | {start_ctx:,} → {start_ctx:,} |",
            "| **Carried in** (start context × 0 calls) | 0 — 0% of all input |",
            "",
            "Zero LLM API calls were made during this run (100% native execution).",
        ]
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        open(out, "w").write("\n".join(lines) + "\n")
        print(f"0 calls · 0 tokens (native execution, zero LLM token bleed)\n→ {out}")
        return

    all_cs = cs + sub_cs
    tot = lambda k: sum(c["usage"].get(k, 0) for c in all_cs)
    thinking = sum(c["usage"].get("output_tokens_details", {}).get("thinking_tokens", 0) for c in all_cs)

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

    sub_in = sum(ctx(c["usage"]) for c in sub_cs)
    sub_out = sum(c["usage"].get("output_tokens", 0) for c in sub_cs)
    sub_added = 0
    for agent_name, sc in sub_runs:
        agent_added = ctx(sc[0]["usage"])
        for prev, nxt in zip(sc, sc[1:]):
            g = ctx(nxt["usage"]) - ctx(prev["usage"]) - prev["usage"].get("output_tokens", 0)
            if g > 0:
                agent_added += g
        sub_added += agent_added
        biggest.append((agent_added, f"subagent:{agent_name}"))
    if sub_cs:
        by_tool["subagents"] = (len(sub_cs), sub_added)

    rows = sorted(by_tool.items(), key=lambda kv: -kv[1][1])
    start_c = ctx(cs[0]["usage"]) if cs else mark.get("start_ctx", 0)
    end_c = ctx(cs[-1]["usage"]) if cs else mark.get("start_ctx", 0)
    carried = start_c * len(cs)
    all_in = sum(ctx(c["usage"]) for c in cs) or 1
    sub_summary = (
        f"{sub_in + sub_out:,} ({len(sub_runs)} agent(s), {len(sub_cs)} calls: {sub_in:,} in / {sub_out:,} out)"
        if sub_cs else "0"
    )
    calls_label = f"{len(cs)} API calls" + (f" + {len(sub_cs)} subagent calls" if sub_cs else "")
    lines = [
        "# E2E test run — token usage",
        "",
        f"Since {mark['since'] or 'the start of the session'}" + (f" until {until}" if until else "") + f" · {calls_label} · environment `{fmt}` · transcript `{os.path.basename(mark['file'])}`",
    ]
    if warn:
        lines += ["", f"> ⚠️ {warn}"]
    lines += [
        "",
        "| | tokens |",
        "|---|---:|",
        f"| Input, uncached | {tot('input_tokens'):,} |",
        f"| Input, cache write | {tot('cache_creation_input_tokens'):,} |",
        f"| Input, cache read | {tot('cache_read_input_tokens'):,} |",
        f"| Output (incl. {thinking:,} thinking) | {tot('output_tokens'):,} |",
        f"| Subagents | {sub_summary} |",
        f"| Context at start → end | {start_c:,} → {end_c:,} |",
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
    print(f"carried-in context {carried * 100 // all_in}% of input (start {start_c:,} × {len(cs)} calls)")
    print(f"{calls_label} · output {tot('output_tokens'):,} · cache read {tot('cache_read_input_tokens'):,} · top: {top}\n→ {out}")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "start":
        cmd_start()
    elif len(sys.argv) == 3 and sys.argv[1] == "report":
        cmd_report(sys.argv[2])
    elif len(sys.argv) == 5 and sys.argv[1] == "report" and sys.argv[3] == "--until":
        cmd_report(sys.argv[2], sys.argv[4])
    else:
        sys.exit(__doc__)
