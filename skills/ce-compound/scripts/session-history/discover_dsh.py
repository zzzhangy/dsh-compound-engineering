#!/usr/bin/env python3
"""Print dsh session files for one repository.

dsh buckets sessions per project cwd:

    <DSH_HOME>/sessions/--<projectKey(cwd)>--/<session-id>/session[.v<N>].jsonl.zstd

`projectKey` collapses path separators into `-` and escapes other unsafe code
units as `~XXXX`, which bash cannot reproduce faithfully (a `~` in a path, a
non-ASCII directory name, or a separator run all change the bucket name). This
helper reuses the same encoder as the reader so discovery and decoding agree.

Usage:
  discover_dsh.py --cwd /abs/repo/root --days 7
  discover_dsh.py --name my-repo --days 7     # basename fallback
  discover_dsh.py --list-all --days 7         # every bucket, cwd filtered later

Prints one absolute path per line, newest first. Exits 0 with no output when
nothing matches, so an empty pipeline stays a normal state.

Line endings are forced to LF. Callers pipe us through `tr '\n' '\0' | xargs -0`
(a bash pipeline, LF-delimited); Python's default text mode on Windows would
emit CRLF and leave a stray `\r` glued to every path, which then fails the
extension gate in the extractors as a file-not-found.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dsh_session  # noqa: E402


def iter_session_files(directory):
    """Yield the session artifacts inside one session directory.

    A session can keep more than one artifact when a format generation was
    migrated (`session.jsonl.zstd` -> `session.v3.jsonl.zstd` -> `session.v4...`);
    emit only the highest generation so one session is not reported twice.
    """
    try:
        names = os.listdir(directory)
    except OSError:
        return
    candidates = sorted(n for n in names if dsh_session.is_session_file(os.path.join(directory, n)))
    if not candidates:
        return
    # Sort by generation number so `.v4` wins over `.v3`, and a bare
    # `session.jsonl.zstd` (generation 0) sorts first.
    def generation(name):
        marker = ".v"
        if marker in name:
            try:
                return int(name.split(marker, 1)[1].split(".", 1)[0])
            except (IndexError, ValueError):
                return 0
        return 0

    newest = max(candidates, key=lambda n: (generation(n), n))
    yield os.path.join(directory, newest)


def recent(path, cutoff):
    """Report whether a file's mtime falls inside the scan window."""
    try:
        return os.path.getmtime(path) >= cutoff
    except OSError:
        return False


def main():
    # LF-only output so the bash pipe below us sees clean paths (see module doc).
    sys.stdout.reconfigure(newline="\n")

    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--cwd", help="absolute repository root; probes its exact bucket")
    group.add_argument("--name", help="repository folder name; matches bucket substrings")
    group.add_argument("--list-all", action="store_true", help="scan every bucket")
    parser.add_argument("--days", type=float, default=7.0, help="scan window in days")
    args = parser.parse_args()

    if not dsh_session.available():
        # Python < 3.14 cannot decode dsh sessions; stay silent so the caller
        # degrades to "no dsh sessions" instead of failing the pipeline.
        return 0

    cutoff = time.time() - args.days * 86400
    found = []
    for root in dsh_session.session_roots():
        if not os.path.isdir(root):
            continue
        if args.list_all:
            buckets = [os.path.join(root, n) for n in sorted(os.listdir(root))]
        elif args.cwd:
            buckets = [os.path.join(root, dsh_session.project_key(args.cwd))]
        else:
            buckets = [
                os.path.join(root, n)
                for n in sorted(os.listdir(root))
                if args.name in n
            ]
        for bucket in buckets:
            if not os.path.isdir(bucket):
                continue
            for session in sorted(os.listdir(bucket)):
                session_dir = os.path.join(bucket, session)
                if not os.path.isdir(session_dir):
                    continue
                for path in iter_session_files(session_dir):
                    if recent(path, cutoff):
                        found.append(path)

    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    for path in found:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
