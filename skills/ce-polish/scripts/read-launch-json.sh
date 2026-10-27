#!/usr/bin/env bash
#
# read-launch-json.sh — read a repo-root launch configuration and emit the
# selected configuration as JSON on stdout, or a sentinel on failure.
#
# Usage:
#   read-launch-json.sh [config-name]
#
# Arguments:
#   config-name (optional) — if multiple configurations exist and this arg
#                            matches a configuration's `name`, emit that one.
#                            If omitted and there are multiple configurations,
#                            emit a __MULTIPLE_CONFIGS__ sentinel followed by a
#                            JSON array of configuration names on the next line.
#
# Output contract:
#   Success: single-line JSON object on stdout representing the chosen
#            configuration. Shape mirrors VS Code's launch.json entry:
#            {name, runtimeExecutable, runtimeArgs, port, cwd, env}.
#   Sentinels (printed to stdout, one per line):
#     __NO_LAUNCH_JSON__           - file not found in any candidate location
#     __INVALID_LAUNCH_JSON__      - file exists but fails JSON parsing
#     __MISSING_CONFIGURATIONS__   - valid JSON but no `configurations` array
#     __MULTIPLE_CONFIGS__         - ambiguity, needs caller disambiguation.
#                                    Followed by a JSON array of names on line 2.
#     __CONFIG_NOT_FOUND__         - caller-provided name doesn't match any entry
#
# Candidate locations are tried in order, first match wins:
#     .dsh/launch.json     - DeepSeek Harness convention (preferred)
#     .claude/launch.json  - Claude Code / Cursor convention
#     .vscode/launch.json  - VS Code debug configs (often already present)
#
# The script never exits non-zero for a missing or malformed file -- callers
# parse the sentinel and decide how to proceed. Exit code 1 is reserved for
# genuine operational failures (git root not found, no JS runtime on PATH).
#
# JSON parsing runs on the host's JavaScript runtime rather than `jq`: dsh is a
# Node.js application, so a runtime is always present, whereas `jq` frequently
# is not installed on Windows and would turn a missing dev-server config into a
# hard failure.

set -u

REQUESTED_NAME="${1:-}"

REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
if [ -z "$REPO_ROOT" ]; then
  echo "ERROR: not in a git repository" >&2
  exit 1
fi

NODE=$(command -v node 2>/dev/null)
if [ -z "$NODE" ]; then
  echo "ERROR: no node runtime on PATH (required to parse the launch configuration)" >&2
  exit 1
fi

exec "$NODE" - "$REPO_ROOT" "$REQUESTED_NAME" <<'NODE_EOF'
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = process.argv[2] || process.cwd();
const requestedName = process.argv[3] || '';

const CANDIDATES = ['.dsh/launch.json', '.claude/launch.json', '.vscode/launch.json'];

let launchPath = '';
for (const relative of CANDIDATES) {
  const absolute = path.join(repoRoot, relative);
  if (fs.existsSync(absolute) && fs.statSync(absolute).isFile()) {
    launchPath = absolute;
    break;
  }
}

if (!launchPath) {
  console.log('__NO_LAUNCH_JSON__');
  process.exit(0);
}

let document;
try {
  document = JSON.parse(fs.readFileSync(launchPath, 'utf8'));
} catch {
  console.log('__INVALID_LAUNCH_JSON__');
  process.exit(0);
}

const configurations = document && Array.isArray(document.configurations)
  ? document.configurations
  : null;

if (!configurations || configurations.length === 0) {
  console.log('__MISSING_CONFIGURATIONS__');
  process.exit(0);
}

if (configurations.length === 1) {
  console.log(JSON.stringify(configurations[0]));
  process.exit(0);
}

if (requestedName) {
  const match = configurations.find(
    (entry) => entry && typeof entry === 'object' && entry.name === requestedName,
  );
  if (!match) {
    console.log('__CONFIG_NOT_FOUND__');
    process.exit(0);
  }
  console.log(JSON.stringify(match));
  process.exit(0);
}

console.log('__MULTIPLE_CONFIGS__');
console.log(JSON.stringify(configurations.map((entry) => (entry ? entry.name : null))));
NODE_EOF
