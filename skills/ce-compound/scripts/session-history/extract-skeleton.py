#!/usr/bin/env python3
"""Extract the conversation skeleton from a DeepSeek Harness (dsh) session file.

Usage:
  python3 extract-skeleton.py <session-file> [--output PATH]
  cat <session.jsonl> | python3 extract-skeleton.py [--output PATH]

Passing the session path instead of piping through stdin is the normal form for
dsh sessions: those files are zstd-compressed containers of concatenated frames,
so a shell redirect would hand this script binary bytes. The path form decodes
them through `dsh_session`; the stdin form works on an already-decoded dsh
JSONL stream.

Extracts:
  - User messages (text only, no tool results)
  - Assistant text (no thinking/reasoning blocks)
  - Collapsed tool call summaries (consecutive same-tool calls grouped)

Consecutive tool calls of the same type are collapsed:
  3+ Read calls -> "[tools] 3x Read (file1, file2, +1 more) -> all ok"

dsh splits a tool invocation and its outcome into two records, so calls are
buffered by `callId` and their status is filled in when the result arrives.

When --output PATH is given, the extracted skeleton is written to PATH and
stdout receives only a one-line JSON status (_meta with wrote/bytes/stats).
This lets callers route bulk content to a scratch file without round-tripping
extraction bytes through orchestrator tool results.

Without --output, extracted content goes to stdout and ends with a _meta line.
A stream that is not dsh-shaped yields no findings rather than misparsed noise.
"""
import argparse
import io
import os
import sys
import json
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dsh_session  # noqa: E402

parser = argparse.ArgumentParser(add_help=True)
parser.add_argument(
    "session_file",
    nargs="?",
    help="Session file to read. Omit to read JSONL from stdin. Required for compressed dsh sessions.",
)
parser.add_argument(
    "--output",
    metavar="PATH",
    help="Write extracted skeleton to PATH instead of stdout. Stdout receives a one-line _meta status.",
)
args = parser.parse_args()

# Session logs are UTF-8; force UTF-8 I/O so Windows' cp1252 default can't crash
# on non-Latin-1 content like emoji, smart quotes, or box-drawing (#1258).
# newline="\n" keeps bash-side consumers of our output from seeing a Windows
# CRLF as part of the last field on every line.
sys.stdin.reconfigure(encoding="utf-8", errors="replace")
sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")

# Capture-and-redirect when --output is set: prints in the rest of the script
# go to the buffer; at the end the buffer is written to PATH and a status
# line is emitted to the real stdout.
_original_stdout = sys.stdout
if args.output:
    sys.stdout = io.StringIO()

stats = {"lines": 0, "parse_errors": 0, "user": 0, "assistant": 0, "tool": 0, "summary": 0}

# Harness-injected wrapper blocks to strip from message text entirely:
# `<system-reminder>` skill catalogs and notices, and the proxy's per-message
# `<acp tokens=...>` annotations. Neither was authored in the conversation, and
# both repeat on most turns, so they would dominate a skeleton's budget.
_STRIP_BLOCK = re.compile(
    r"<(?:system-reminder|acp)[^>]*>.*?</(?:system-reminder|acp)>",
    re.DOTALL,
)


def clean_text(text):
    """Strip harness wrapper tags from message text."""
    text = _STRIP_BLOCK.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text

# Buffer for pending tool entries: [{"ts", "name", "target", "status"}]
pending_tools = []


def flush_tools():
    """Print buffered tool entries, collapsing consecutive same-name groups."""
    if not pending_tools:
        return

    # Group consecutive entries by tool name
    groups = []
    for entry in pending_tools:
        if groups and groups[-1][0]["name"] == entry["name"]:
            groups[-1].append(entry)
        else:
            groups.append([entry])

    for group in groups:
        name = group[0]["name"]
        if len(group) <= 2:
            # Print individually
            for e in group:
                status = f" -> {e['status']}" if e.get("status") else ""
                ts_prefix = f"[{e['ts']}] " if e.get("ts") else ""
                print(f"{ts_prefix}[tool] {name} {e['target']}{status}")
                stats["tool"] += 1
        else:
            # Collapse
            ts = group[0].get("ts", "")
            targets = [e["target"] for e in group if e.get("target")]
            ok = sum(1 for e in group if e.get("status") == "ok")
            err = sum(1 for e in group if e.get("status") and e["status"] != "ok")
            no_status = len(group) - ok - err

            # Show first 2 targets, then "+N more"
            if len(targets) > 2:
                target_str = ", ".join(targets[:2]) + f", +{len(targets) - 2} more"
            elif targets:
                target_str = ", ".join(targets)
            else:
                target_str = ""

            if no_status == len(group):
                status_str = ""
            elif err == 0:
                status_str = " -> all ok"
            else:
                status_str = f" -> {ok} ok, {err} error"

            ts_prefix = f"[{ts}] " if ts else ""
            print(f"{ts_prefix}[tools] {len(group)}x {name} ({target_str}){status_str}")
            stats["tool"] += len(group)

    pending_tools.clear()


def _safe_slice(value, n):
    """Slice value if it is a string; otherwise return ''.

    Some tools put structured data (dicts, lists) in fields like `query` or
    `prompt`. `dict[:N]` raises TypeError, so guard every slice with an
    isinstance check.
    """
    return value[:n] if isinstance(value, str) else ""


def handle_dsh(obj):
    """DeepSeek Harness records: slash-tagged `user/message`, `assistant/message`,
    `tool/call`, and `tool/result` rows sharing one envelope per turn/step.

    dsh splits a tool invocation and its outcome into two separate top-level
    records, so calls are buffered by `callId` and their status is filled in
    when the matching result row arrives.
    """
    msg_type = obj.get("type")
    data = obj.get("data", {})
    if not isinstance(data, dict):
        return
    ts = dsh_session.iso_from_millis(obj.get("time"))[:19]

    if msg_type == "user/message":
        # dsh writes framework context as user rows too (runtime-context
        # snapshots, the skill catalog, time stamps, model-change notices, goal
        # rounds). Only `source.kind == "user"` was authored by the person, and
        # only that belongs in a conversation skeleton.
        source = data.get("source")
        if isinstance(source, dict) and source.get("kind") not in ("user", "goal"):
            return
        text = clean_text(" ".join(dsh_session.content_text(data.get("content"))))
        if len(text) > 15:
            flush_tools()
            print(f"[{ts}] [user] {text[:800]}")
            print("---")
            stats["user"] += 1

    elif msg_type == "assistant/message":
        message = data.get("message", {})
        has_text = False
        for block in message.get("content", []) or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text = clean_text(block.get("text", ""))
                if len(text) > 20:
                    if not has_text:
                        flush_tools()
                        has_text = True
                    print(f"[{ts}] [assistant] {text[:800]}")
                    print("---")
                    stats["assistant"] += 1

    elif msg_type == "compaction/summary":
        # Context-compaction summaries carry the reasoning that survived a fold,
        # which is exactly what a later reader of the skeleton wants to see.
        # dsh stores them as `data.summary` content blocks with the range they
        # shadowed, so a fold shows up as a labeled entry instead of silence.
        text = clean_text(" ".join(dsh_session.content_text(data.get("summary"))))
        if len(text) > 15:
            flush_tools()
            print(f"[{ts}] [summary] {text[:800]}")
            print("---")
            stats["summary"] += 1

    elif msg_type == "tool/call":
        # dsh stores tool arguments as a JSON string, not a nested object.
        raw = data.get("arguments")
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (json.JSONDecodeError, ValueError):
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        target = (
            arguments.get("file_path")
            if isinstance(arguments.get("file_path"), str)
            else None
        ) or (
            arguments.get("path") if isinstance(arguments.get("path"), str) else None
        ) or _safe_slice(arguments.get("command"), 120) or _safe_slice(
            arguments.get("pattern"), 200
        ) or _safe_slice(
            arguments.get("query"), 80
        ) or _safe_slice(
            arguments.get("prompt"), 80
        ) or ""
        if isinstance(target, str) and len(target) > 120:
            target = target[:120]
        entry = {"ts": ts, "name": data.get("name", "unknown"), "target": target}
        call_id = data.get("callId")
        if call_id:
            entry["id"] = call_id
        pending_tools.append(entry)

    elif msg_type == "tool/result":
        message = data.get("message", {})
        for block in (message.get("content", []) or []):
            if not isinstance(block, dict) or block.get("type") != "tool-result":
                continue
            status = "error" if block.get("isError") else "ok"
            call_id = block.get("toolCallId") or message.get("source", {}).get("callId")
            matched = False
            if call_id:
                for entry in pending_tools:
                    if entry.get("id") == call_id:
                        entry["status"] = status
                        matched = True
                        break
            if not matched:
                for entry in pending_tools:
                    if not entry.get("status"):
                        entry["status"] = status
                        break


def is_dsh_header(obj):
    """The `session` row is dsh only when createdAt is epoch milliseconds."""
    return obj.get("type") == "session" and isinstance(obj.get("createdAt"), (int, float))


# Top-level record types only dsh emits.
_DSH_RECORD_TYPES = ("user/message", "assistant/message", "tool/call", "tool/result", "step/start", "turn/start")

# Read the stream once: dsh decoding is not seekable, and a skeleton needs every
# record anyway. Detect on any record rather than the first N lines, because a
# session can front-load many non-message rows before the first real turn.
detected = False
buffer = []

if args.session_file:
    if dsh_session.is_session_file(args.session_file):
        if not dsh_session.available():
            print(
                json.dumps(
                    {
                        "_meta": True,
                        "error": "python 3.14+ required to read dsh zstd sessions",
                        **stats,
                    }
                )
            )
            sys.exit(1)
        lines = dsh_session.read_lines(args.session_file)
    elif dsh_session.available():
        # A path we cannot decode as a dsh session has no dsh skeleton to show.
        lines = []
    else:
        with open(args.session_file, "r", encoding="utf-8", errors="replace") as f:
            lines = list(f)
else:
    lines = sys.stdin

objects = []
for line in lines:
    line = line.strip()
    if not line:
        continue
    stats["lines"] += 1
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, KeyError):
        stats["parse_errors"] += 1
        continue
    objects.append(obj)
    if not detected and (is_dsh_header(obj) or obj.get("type") in _DSH_RECORD_TYPES):
        detected = True

if not detected:
    print(json.dumps({"_meta": True, **stats}))
    if args.output:
        body = sys.stdout.getvalue()
        sys.stdout = _original_stdout
        with open(args.output, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        print(
            json.dumps(
                {"_meta": True, "wrote": args.output, "bytes": os.path.getsize(args.output), **stats}
            )
        )
    sys.exit(0)

for obj in objects:
    try:
        handle_dsh(obj)
    except KeyError:
        stats["parse_errors"] += 1

# Flush any remaining buffered tools
flush_tools()

print(json.dumps({"_meta": True, **stats}))

if args.output:
    body = sys.stdout.getvalue()
    sys.stdout = _original_stdout
    with open(args.output, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    bytes_written = os.path.getsize(args.output)
    print(json.dumps({"_meta": True, "wrote": args.output, "bytes": bytes_written, **stats}))
