#!/usr/bin/env python3
"""Read DeepSeek Harness (dsh) session files.

dsh stores each session as a single `session*.jsonl.zstd` file: **concatenated
zstd frames**, one per append. A plain `zstd -d` or `compression.zstd.decompress`
call stops after the first frame and silently loses the rest of the session, so
this module scans frame boundaries itself before decompressing each frame.

Requires Python 3.14+ (`compression.zstd` in the standard library). Import is
safe on older interpreters: `available()` reports whether reading will work and
callers degrade to "no dsh sessions" instead of crashing.
"""
import json
import os
import sys

try:
    from compression import zstd as _zstd
except ImportError:  # Python < 3.14
    _zstd = None

# zstd frame magic, little-endian 0xFD2FB528.
ZSTD_MAGIC = 4247762216

# dsh names session files `session.v<N>.jsonl.zstd` and, in older layouts,
# `session.jsonl.zstd`. Session directories are `session-<uuid>` or a bare uuid.
SESSION_FILE_PREFIX = "session"
SESSION_FILE_SUFFIX = ".jsonl.zstd"


def available():
    """Report whether this interpreter can decompress dsh sessions."""
    return _zstd is not None


def is_session_file(path):
    """Report whether a path looks like a dsh session file."""
    base = os.path.basename(path)
    return base.startswith(SESSION_FILE_PREFIX) and base.endswith(SESSION_FILE_SUFFIX)


def project_key(cwd):
    """Encode a project directory the way dsh names its session bucket.

    Mirrors dsh's own `projectKey`: separators (`/`, `\\\\`, `:`) collapse into a
    single `-` run, other unsafe code units become `~XXXX`, and the result is
    wrapped in `--` with leading separators trimmed. Encoding the cwd exactly
    means a repo's bucket is addressed directly instead of by fuzzy basename
    match, so sibling repos (`my-repo` vs `my-repo-old`) never mix.
    """
    if not cwd:
        raise ValueError("cannot encode an empty project path")
    readable = ""
    separator_run = False
    for ch in cwd:
        if ch in ("/", "\\", ":"):
            if not separator_run:
                readable += "-"
            separator_run = True
        elif ch != "~" and (ch.isascii() and (ch.isalnum() or ch in "._-")):
            readable += ch
            separator_run = False
        else:
            readable += "~" + format(ord(ch), "04X")
            separator_run = False
    trimmed = readable.lstrip("-") or "root"
    return "--" + trimmed[:251] + "--"


def session_roots():
    """Return the candidate dsh session roots, most specific first.

    `DSH_HOME` relocates the whole state tree; without it dsh uses `~/.dsh`.
    """
    home = os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")
    return [os.path.join(home, "sessions")]


def scan_frames(buffer, max_frames=None):
    """Locate concatenated zstd frames.

    Walks each frame header and block list exactly as zstd frames are laid out:
    magic, frame header descriptor, optional window/dictionary/content-size
    fields, then blocks whose 3-byte header carries last-block, type, and size.

    Returns `(frames, torn_start)` where `frames` is a list of `(start, end)`
    byte ranges and `torn_start` is the offset of an incomplete trailing frame
    (a crash mid-append), or None.
    """
    frames = []
    offset = 0
    limit = len(buffer)
    while offset + 4 <= limit:
        if max_frames is not None and len(frames) >= max_frames:
            break
        if int.from_bytes(buffer[offset:offset + 4], "little") != ZSTD_MAGIC:
            # Not a frame boundary: the tail is corrupt or truncated.
            return frames, offset
        start = offset
        offset += 4
        if offset >= limit:
            return frames, start
        descriptor = buffer[offset]
        offset += 1
        if (descriptor & 24) != 0:
            # Reserved frame-header bits set: this is not a frame boundary.
            return frames, start
        content_size_flag = descriptor >> 6
        single_segment = (descriptor & 32) != 0
        checksum = (descriptor & 4) != 0
        dictionary_flag = descriptor & 3
        dictionary_bytes = 4 if dictionary_flag == 3 else dictionary_flag
        if content_size_flag == 0:
            content_size_bytes = 1 if single_segment else 0
        else:
            content_size_bytes = 1 << content_size_flag
        header_bytes = (0 if single_segment else 1) + dictionary_bytes + content_size_bytes
        if offset + header_bytes > limit:
            return frames, start
        offset += header_bytes
        while True:
            if offset + 3 > limit:
                return frames, start
            header = int.from_bytes(buffer[offset:offset + 3], "little")
            offset += 3
            last_block = (header & 1) != 0
            block_type = (header >> 1) & 3
            block_size = header >> 3
            if block_type == 3:
                return frames, start
            # Raw (0) and compressed (2) blocks carry block_size bytes; an RLE
            # block carries a single byte repeated block_size times.
            payload = 1 if block_type == 1 else block_size
            if offset + payload > limit:
                return frames, start
            offset += payload
            if last_block:
                break
        if checksum:
            offset += 4
        if offset > limit:
            return frames, start
        frames.append((start, offset))
    return frames, None


def read_lines(path, max_lines=None):
    """Decode a dsh session file into its JSONL lines.

    Emits only complete decoded frames. A torn trailing frame (interrupted
    append) is dropped rather than failing the whole read, matching how dsh
    itself tolerates the last partial record.
    """
    if _zstd is None:
        raise RuntimeError("Python 3.14+ required: `compression.zstd` is unavailable")
    with open(path, "rb") as handle:
        buffer = handle.read()
    frames, _torn = scan_frames(buffer)
    chunks = []
    for start, end in frames:
        try:
            chunks.append(_zstd.decompress(buffer[start:end]))
        except Exception:  # noqa: BLE001 - a single bad frame must not hide the rest
            continue
    text = b"".join(chunks).decode("utf-8", errors="replace")
    if max_lines is None:
        return text.splitlines()
    return text.splitlines()[:max_lines]


def read_objects(path, max_lines=None):
    """Decode a dsh session file into parsed JSON objects, skipping bad lines."""
    objects = []
    for line in read_lines(path, max_lines):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            objects.append(json.loads(stripped))
        except (json.JSONDecodeError, ValueError):
            continue
    return objects


def session_header(objects):
    """Return the `type: session` header object, or None.

    The header carries `id`, `cwd`, and `createdAt` (epoch milliseconds); it is
    the first record dsh writes, so it survives any later truncation.
    """
    for obj in objects:
        if isinstance(obj, dict) and obj.get("type") == "session":
            return obj
    return None


def iso_from_millis(value):
    """Format dsh's epoch-millisecond timestamps as ISO 8601 UTC."""
    if not isinstance(value, (int, float)):
        return ""
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def content_text(blocks):
    """Concatenate the text blocks of one dsh content array.

    dsh content blocks are `{type: 'text'|'reasoning'|'tool-call'|'image', ...}`.
    Only `text` is model- or user-authored prose; reasoning and tool calls stay
    out so keyword scans cannot false-match tool names or inner monologue.
    """
    if isinstance(blocks, str):
        return [blocks]
    chunks = []
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    return chunks
