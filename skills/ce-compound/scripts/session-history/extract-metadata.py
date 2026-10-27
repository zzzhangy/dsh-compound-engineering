#!/usr/bin/env python3
"""Extract session metadata from DeepSeek Harness (dsh) session files.

Batch mode (preferred — one invocation for all files):
  python3 extract-metadata.py /path/to/dir/session-*.jsonl.zstd
  python3 extract-metadata.py file1.jsonl.zstd file2.jsonl.zstd

Single-file mode (stdin):
  head -20 <session.jsonl> | python3 extract-metadata.py

Detects dsh sessions from the JSONL structure. Non-dsh files are skipped.
Outputs one JSON object per file, one per line.
Includes a final _meta line with processing stats.

dsh sessions are zstd-compressed (`session*.jsonl.zstd`, one file per session
holding concatenated frames); they are decoded through `dsh_session.read_lines`
so every frame is read, not just the first. Decoding needs Python 3.14+
(`compression.zstd`); on older interpreters every file reports as unmatched.
"""
import sys
import json
import os

# LF-only line endings: callers may pipe our JSON lines through bash tools
# (tr/xargs/grep) where a Windows CRLF leaves a stray \r on every record.
sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dsh_session  # noqa: E402

MAX_LINES = 200  # Resumed dsh sessions front-load dozens of non-message records before the first user record


def try_dsh(lines):
    """DeepSeek Harness sessions.

    The dsh header is `{"type": "session", "cwd": ..., "createdAt": <epoch ms>}`.
    `createdAt` in epoch milliseconds is the field that separates a dsh header
    from any other harness that opens with a cwd-bearing session record.
    """
    for line in lines:
        try:
            obj = json.loads(line.strip())
        except (json.JSONDecodeError, KeyError):
            continue
        if obj.get("type") != "session" or "cwd" not in obj:
            continue
        if not isinstance(obj.get("createdAt"), (int, float)):
            return None
        return {
            "platform": "dsh",
            "cwd": obj.get("cwd", ""),
            "session": obj.get("id", ""),
            "ts": dsh_session.iso_from_millis(obj.get("createdAt")),
        }
    return None


def extract_from_lines(lines):
    return try_dsh(lines)


def get_last_timestamp(filepath):
    """Return the ISO time of the last timestamped record in a dsh session."""
    objects = dsh_session.read_objects(filepath)
    for obj in reversed(objects):
        stamp = dsh_session.iso_from_millis(obj.get("time"))
        if stamp:
            return stamp
    return None


def _extract_user_assistant_text(filepath):
    """Return concatenated user + assistant text content from a dsh session file.

    Skips JSONL metadata field names and values (session id, timestamps, type
    tags), tool calls, tool results, and thinking blocks. Only content the user
    or the model actually said is included.

    Without this filtering, common topic words like "session" would match every
    session file via its id field, drowning out real content matches.
    """
    chunks = []
    if not dsh_session.is_session_file(filepath):
        return ""
    try:
        objects = []
        # dsh sessions are zstd-compressed and hold concatenated frames, so
        # plain line iteration would yield binary garbage.
        for line in dsh_session.read_lines(filepath):
            try:
                objects.append(json.loads(line.strip()))
            except (json.JSONDecodeError, ValueError):
                continue

        for obj in objects:
            t = obj.get("type")

            # dsh: slash-tagged top-level records. User text lives at
            # data.content[], assistant text at data.message.content[].
            # dsh also stores framework context (runtime snapshots, the skill
            # catalog, timestamps) as user rows, so only `source.kind == "user"`
            # counts as something the person said.
            if t == "user/message":
                source = obj.get("data", {}).get("source")
                if isinstance(source, dict) and source.get("kind") not in ("user", "goal"):
                    continue
                chunks.extend(dsh_session.content_text(obj.get("data", {}).get("content")))
                continue
            if t == "assistant/message":
                message = obj.get("data", {}).get("message", {})
                chunks.extend(dsh_session.content_text(message.get("content")))
                continue
    except (OSError, IOError):
        pass
    return "\n".join(chunks)


def count_keyword_matches(filepath, keywords):
    """Case-insensitive substring count for each keyword in user/assistant text.

    Returns a dict {original_keyword: count}. Scans only content the user or
    assistant said — not JSONL metadata, tool calls, tool outputs, or thinking
    blocks — so common topic words like "session" do not false-match against
    the session id field.
    """
    text_lower = _extract_user_assistant_text(filepath).lower()
    return {kw: text_lower.count(kw.lower()) for kw in keywords}


def process_file(filepath):
    """Extract metadata only. Keyword scanning is done separately so callers
    can apply cheap filters (e.g. --cwd-filter) before paying the full-file
    content scan cost.

    Returns (result, error): (dict, None) on success, (None, None) when the
    file is readable but is not a dsh session, (None, filepath) on read error."""
    try:
        size = os.path.getsize(filepath)
        if not dsh_session.is_session_file(filepath):
            return None, None
        if not dsh_session.available():
            return None, None
        lines = dsh_session.read_lines(filepath, MAX_LINES)
        result = extract_from_lines(lines)
        if result:
            result["file"] = filepath
            result["size"] = size
            return result, None
        else:
            return None, None
    except (OSError, IOError) as e:
        return None, filepath


def _normalize_cwd(path):
    path = path.replace("\\", "/").strip()
    if len(path) > 1 and path.endswith("/") and not (
        len(path) == 3 and path[1] == ":"
    ):
        path = path.rstrip("/")
    # Windows drive paths are case-insensitive. Do not rewrite POSIX /d/...
    # to D:/ — those are different filesystems.
    if len(path) >= 2 and path[1] == ":":
        path = path[0].upper() + ":" + path[2:].casefold()
    return path


def _is_abs_cwd(path):
    if os.path.isabs(path):
        return True
    return len(path) >= 2 and path[1] == ":"


def _cwd_paths_related(session_cwd, cwd_filter):
    if session_cwd == cwd_filter:
        return True
    prefix = cwd_filter if cwd_filter.endswith("/") else cwd_filter + "/"
    if session_cwd.startswith(prefix):
        return True
    prefix = session_cwd if session_cwd.endswith("/") else session_cwd + "/"
    return cwd_filter.startswith(prefix)


def _attach_timestamps(result, filepath):
    # dsh already reported `createdAt` as ISO 8601; the last record's `time`
    # is read separately because decompression is not seekable.
    last_ts = get_last_timestamp(filepath)
    if last_ts:
        result["last_ts"] = last_ts


def cwd_matches_filter(session_cwd, cwd_filter):
    if not session_cwd or not cwd_filter:
        return True
    session = _normalize_cwd(session_cwd)
    filt = _normalize_cwd(cwd_filter)
    if not session or not filt:
        return True
    if _is_abs_cwd(filt):
        return _cwd_paths_related(session, filt)
    return filt in session.split("/")


# Parse arguments: files and optional --cwd-filter / --keyword
files = []
cwd_filter = None
keywords = None
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == "--cwd-filter" and i + 1 < len(args):
        cwd_filter = args[i + 1]
        i += 2
    elif args[i] == "--keyword" and i + 1 < len(args):
        keywords = [k for k in args[i + 1].split(",") if k]
        i += 2
    elif not args[i].startswith("-"):
        files.append(args[i])
        i += 1
    else:
        i += 1

if files:
    # Batch mode: process all files
    processed = 0
    parse_errors = 0
    no_metadata = 0
    filtered = 0
    matched = 0
    for filepath in files:
        if not dsh_session.is_session_file(filepath):
            continue
        result, error = process_file(filepath)
        processed += 1
        if result:
            # Apply CWD filter first: cheap metadata-only check. Skip
            # sessions from other repos before paying the full-file keyword
            # scan cost — dsh discovery lists across projects, so without
            # this ordering --keyword would scan files that are immediately
            # discarded.
            if cwd_filter:
                session_cwd = result.get("cwd")
                if session_cwd:
                    if not cwd_matches_filter(session_cwd, cwd_filter):
                        filtered += 1
                        continue
                elif result.get("platform") == "dsh":
                    filtered += 1
                    continue
            _attach_timestamps(result, filepath)
            # Apply keyword scan only after cheap filters pass.
            if keywords:
                matches = count_keyword_matches(filepath, keywords)
                result["keyword_matches"] = matches
                result["match_count"] = sum(matches.values())
                if result["match_count"] == 0:
                    continue
                matched += 1
            print(json.dumps(result))
        elif error:
            parse_errors += 1
        else:
            no_metadata += 1

    meta = {"_meta": True, "files_processed": processed, "parse_errors": parse_errors}
    if no_metadata:
        meta["files_without_metadata"] = no_metadata
    if filtered:
        meta["filtered_by_cwd"] = filtered
    if keywords:
        meta["files_matched"] = matched
    print(json.dumps(meta))
else:
    # No file arguments: either single-file stdin mode or empty xargs invocation.
    # When xargs runs us with no input (e.g., discover found no files), stdin is
    # empty or a TTY — emit a clean zero-file result instead of a false parse error.
    if sys.stdin.isatty():
        lines = []
    else:
        lines = list(sys.stdin)

    if not lines:
        # No input at all — zero-file result (clean exit for empty pipelines).
        # When --keyword was supplied, emit files_matched: 0 so callers relying
        # on its presence to terminate quickly in zero-match scans see a
        # consistent shape with the batch-mode no-match case.
        meta = {"_meta": True, "files_processed": 0, "parse_errors": 0}
        if keywords:
            meta["files_matched"] = 0
        print(json.dumps(meta))
    else:
        # Genuine single-file stdin mode (backward compatible)
        result = extract_from_lines(lines)
        meta = {"_meta": True, "files_processed": 1, "parse_errors": 0}
        if result:
            print(json.dumps(result))
        else:
            meta["files_without_metadata"] = 1
        print(json.dumps(meta))
