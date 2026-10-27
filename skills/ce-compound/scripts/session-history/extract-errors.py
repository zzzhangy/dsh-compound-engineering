#!/usr/bin/env python3
"""Extract error signals from a DeepSeek Harness (dsh) session file.

Usage:
  python3 extract-errors.py <session-file> [--output PATH]
  cat <session.jsonl> | python3 extract-errors.py

Passing the session path instead of piping through stdin is required for dsh
sessions, which are zstd-compressed containers of concatenated frames; the path
form decodes them through the bundled `dsh_session` reader. The stdin form only
works for already-decompressed JSONL (e.g. a dsh session piped through the
reader), and reports no errors when the stream is not dsh-shaped.

Finds failed tool calls / commands and outputs them with timestamps.

When --output PATH is given, the extracted error log is written to PATH and
stdout receives only a one-line JSON status (_meta with wrote/bytes/stats).
This lets callers route bulk content to a scratch file without round-tripping
extraction bytes through orchestrator tool results.

Without --output, extracted content goes to stdout and ends with a _meta line.
"""
import argparse
import io
import os
import sys
import json

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
    help="Write extracted errors to PATH instead of stdout. Stdout receives a one-line _meta status.",
)
args = parser.parse_args()

# Session logs are UTF-8; force UTF-8 I/O so Windows' cp1252 default can't crash
# on non-Latin-1 content like emoji, smart quotes, or box-drawing (#1258).
# newline="\n" keeps bash-side consumers of our output (tr/xargs/grep) from
# seeing a Windows CRLF as part of the last field on every line.
sys.stdin.reconfigure(encoding="utf-8", errors="replace")
sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")

_original_stdout = sys.stdout
if args.output:
    sys.stdout = io.StringIO()

stats = {"lines": 0, "parse_errors": 0, "errors_found": 0}

# Top-level record types only dsh emits. Anything else in the stream is a
# non-dsh or framework record we deliberately ignore.
_DSH_RECORD_TYPES = ("user/message", "assistant/message", "tool/result", "step/start")


def summarize_error(raw):
    """Extract a short error summary instead of dumping the full payload."""
    text = str(raw).strip()
    # Take the first non-empty line as the error message
    for line in text.split("\n"):
        line = line.strip()
        if line:
            return line[:200]
    return text[:200]


def _dsh_result_text(content):
    """Flatten a dsh tool-result payload into a one-line summary."""
    if isinstance(content, str):
        return summarize_error(content)
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return summarize_error("\n".join(parts))
    return summarize_error(content)


def handle_dsh(obj):
    if obj.get("type") == "tool/result":
        data = obj.get("data", {})
        message = data.get("message", {})
        content = message.get("content", [])
        is_error = False
        summary = ""
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool-result":
                    if block.get("isError"):
                        is_error = True
                        summary = _dsh_result_text(block.get("content"))
        # dsh also records structured failures outside the content blocks.
        error = data.get("error")
        if isinstance(error, dict):
            is_error = True
            if not summary:
                summary = summarize_error(f"{error.get('name', 'error')}: {error.get('code', '')}")
        if not is_error:
            return
        ts = dsh_session.iso_from_millis(obj.get("time"))[:19]
        call_id = message.get("source", {}).get("callId", "")
        print(f"[{ts}] [error] tool_call={call_id}: {summary}")
        print("---")
        stats["errors_found"] += 1


def is_dsh_record(obj):
    """Report whether a parsed record can only come from a dsh session."""
    t = obj.get("type")
    if t in _DSH_RECORD_TYPES:
        return True
    # The session header is dsh only when it stamps createdAt in epoch millis;
    # other harnesses open with an ISO `timestamp` string instead.
    return t == "session" and isinstance(obj.get("createdAt"), (int, float))


# Read the whole stream once: dsh decoding is not seekable, and error detection
# needs the full record set anyway.
objects = []
_source = None
_close_source = False
if args.session_file:
    if dsh_session.is_session_file(args.session_file):
        _source = dsh_session.read_lines(args.session_file)
    elif dsh_session.available():
        # A path we cannot decode as a dsh session has no dsh errors to report.
        _source = []
    else:
        _source = open(args.session_file, "r", encoding="utf-8", errors="replace")
        _close_source = True
else:
    _source = sys.stdin

for line in _source:
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

if hasattr(_source, "close"):
    _source.close()

# Only stream dsh records; a non-dsh session yields no findings rather than
# misparsed noise from another harness's schema.
for obj in objects:
    if not is_dsh_record(obj):
        continue
    try:
        handle_dsh(obj)
    except KeyError:
        stats["parse_errors"] += 1

print(json.dumps({"_meta": True, **stats}))

if args.output:
    body = sys.stdout.getvalue()
    sys.stdout = _original_stdout
    with open(args.output, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    bytes_written = os.path.getsize(args.output)
    print(json.dumps({"_meta": True, "wrote": args.output, "bytes": bytes_written, **stats}))
