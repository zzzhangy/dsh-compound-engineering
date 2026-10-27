# dsh-compound-engineering

English | [简体中文](README.zh.md)

[Every's compound-engineering](https://github.com/EveryInc/compound-engineering-plugin) methodology, packaged as a skill bundle for DeepSeek Harness.

**The idea**: most AI coding tools restart from zero on every task. compound-engineering compounds instead — every problem you solve gets written down in the repo, so the next time something similar comes up, the answer is already there. Each change makes the next one cheaper.

```
brainstorm → plan → work → review → compound
                                      └─ write what you learned back into the repo
```

All 36 skills ship with the package. Nothing to configure after install.

**Optional: `jq`.** Six scripts shell out to it — the cross-model workers (`ce-work`, `ce-code-review`, `ce-doc-review`, `ce-pov`) and `elevation-dispatch` (`ce-plan`, `ce-brainstorm`). Without `jq` on `PATH` none of them break the surrounding skill, but they degrade in two different ways:

- `ce-code-review` / `ce-doc-review` / `ce-pov` print `jq not installed; skipping` and exit 0 — that round of cross-model review is simply skipped.
- `ce-work`'s cross-model path reports `transport unavailable (pre-egress, shared): jq not found` and exits 2, which the caller treats as the cross-model channel being unavailable.
- `elevation-dispatch` emits a `status:failed` envelope, and the caller degrades to inline execution.

Either way you lose the multi-model cross-check. Install it if you want those paths live:

```bash
winget install jqlang.jq    # Windows
brew install jq             # macOS
apt install jq              # Debian/Ubuntu
```

## Install

```bash
dsh plugin --profile web add dsh-compound-engineering
```

Replace `web` with the profile you actually use (`headless`, `tui`, ...). The command also adds the package to `dsh.profile.bundles` for you.

Or do it by hand: add the dependency to the profile's `package.json`, then list it in `dsh.profile.bundles`.

```jsonc
{
  "dependencies": { "dsh-compound-engineering": "^0.1.0" },
  "dsh": { "profile": { "bundles": ["dsh-compound-engineering"] } }
}
```

Restart DSH. Type `/ce-plan` in a session and the skills are there.

## Skills you will actually reach for

| Skill | When |
| --- | --- |
| `/ce-brainstorm` | The idea is still vague; force it into a concrete proposal |
| `/ce-plan` | Requirements are clear; you want an executable plan |
| `/ce-work` | Execute the plan |
| `/ce-code-review` | Find problems before review does (can fan out across models) |
| `/ce-compound` | **Wrap up**: write the non-obvious conclusions into the repo |
| `/ce-debug` | Stuck; locate the root cause systematically |
| `/ce-commit-push-pr` | Commit, push, and open a PR in one go |

`/lfg` chains brainstorm through PR.

The other 28 skills live in `skills/`, or just ask the model what it can see.

## ce-compound is the part that differs

Most "memory" plugins remember conversations. `ce-compound` remembers the **repo**:

- It reads your local dsh session history first to recover what was already tried and why it failed
- Output goes into `<repo>/docs/solutions/`, committed and reviewed alongside code
- The next person — or the next model — working in that repo reads it

It deliberately does not record which lines changed; git already has that. It records why, which neither the code nor the tests can tell you.

## Adapting to DeepSeek Harness

Upstream targets 14 hosts including Claude Code. The port does this:

**Capabilities are matched by capability, not by tool name.** Upstream was already written that way ("the host's blocking question tool"), so the 36 skill bodies work nearly as-is. What got added is the DSH spelling: `ask_user_question`, `todo_write`, `subagent`, `web_fetch`, `web_search`.

**Session history gained a dsh platform.** `skills/ce-compound/scripts/session-history/dsh_session.py` reads DSH's own session files. One trap worth knowing: DSH's `session.v4.jsonl.zstd` is **concatenated zstd frames**, one per append. Plain `zstd -d` or `compression.zstd.decompress` stops after the first frame and silently loses the rest of the session, so the script scans frame boundaries itself and decompresses frame by frame. It needs Python 3.14+; on older interpreters it degrades quietly to "no dsh sessions".

**The session-history extractors are dsh-only.** `extract-metadata.py`, `extract-skeleton.py`, and `extract-errors.py` decode dsh session files and nothing else, which dropped ~845 lines of Claude Code / Codex / Cursor / Pi / oh-my-pi branching. `discover-sessions.sh` keeps its other probes so a mixed-tool repo can still enumerate files, but run the documented pipeline with `--platform dsh`. Sessions carry a recorded `cwd` but no git branch, so filtering is by working directory, not by branch.

**Dev-server config prefers `.dsh/launch.json`.** `ce-polish` looks in `.dsh/` → `.claude/` → `.vscode/`.

**Host identity allowlists accept `dsh`.** Several cross-model scripts only knew `codex|claude|grok|cursor|opencode|antigravity|omp`, so reporting `dsh` honestly was rejected.

**Task tracking, subagents, and web fetching** each gained a DSH form. Subagents use `subagent` directly rather than faking a `subagent_type`.

**Windows works for the `ce-work` unit pipeline.** That path was POSIX-only upstream. Four things had to change, and any of them will bite you if you port similar code:

- `fcntl` does not exist. Locking goes through `msvcrt.locking`, which is non-blocking and raises instead of waiting, so the wrapper retries with exponential backoff for up to 30s.
- `os.open()` **cannot open a directory** on Windows — the kernel rejects it without `FILE_FLAG_BACKUP_SEMANTICS`. Every `open(path, O_DIRECTORY)` + `fstat(fd)` ownership check became a path-based `GetNamedSecurityInfoW` call. `dir_fd` is unavailable for the same reason, so the "directory handle" is a real fd on POSIX and a plain path on Windows; `close_dir_handle()` papers over the difference.
- Mode bits are synthetic: a `0o700` mkdir reports `0o777` and a `0o600` file reports `0o666`. Every `st_mode != 0o700` gate would fail unconditionally. Ownership is checked against the current user's SID instead, and privacy comes from the hardened ACL (`icacls /inheritance:r`), not from a mode.
- `\n` turns into `\r\n` and `0x1A` ends the read when the CRT opens a descriptor in text mode, so binary opens pass `O_BINARY`.

`os.lstat()` does return stable, non-zero `st_dev`/`st_ino` on Windows, so the controller's recorded directory identity still verifies.

**Text is read as UTF-8 explicitly.** Python on a Chinese Windows defaults to GBK and throws `UnicodeDecodeError` on most of upstream's own skill files.

## Development

```bash
npm test                          # JS unit + integration, then the Python suites
npm run test:smoke                # three layers: provider / registry / plugin lifecycle
npm run test:py                   # Python suites only (session reader, Windows compat)
```

Integration tests need to find a DSH runtime: they import by package name first, then scan `~/.dsh/runtime/versions/*`. Point `DSH_RUNTIME` at it to override.

After pulling in upstream changes, re-run the two idempotent patch scripts:

```bash
python scripts/patch-dsh-capabilities.py   # add DSH forms to skill bodies
python scripts/patch-host-allowlists.py    # add dsh to cross-model host allowlists
```

### With `file:` installs, refresh the copy after editing source

`dsh plugin add file:<local path>` goes through pnpm directory dependencies, so `node_modules/` holds a **copy**, not a symlink. pnpm records the dependency's contents in its lockfile (`resolution: {directory: ..., type: directory}`), which means `pnpm install`, `pnpm update`, and even re-running `dsh plugin add` will **not** refresh that copy after you edit source. You keep running the old code, and since the skill catalog comes from the stale copy, changes under `lib/` look like they did nothing.

Check whether you are hitting this (a hash mismatch means yes):

```bash
md5sum skills/ce-work/scripts/unit_workspace_state.py \
  ~/.dsh/profiles/web/node_modules/dsh-compound-engineering/skills/ce-work/scripts/unit_workspace_state.py
```

Rebuilding the copy is the shortest fix:

```bash
python -c "
import shutil, os
dst = os.path.expanduser('~/.dsh/profiles/web/node_modules/dsh-compound-engineering')
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree('<source dir>', dst,
                ignore=shutil.ignore_patterns('node_modules','.git','__pycache__','*.pyc','test'))
"
```

The copy's `skills/` must mirror the source one-to-one (`test/` is not shipped). Restart DSH after changing `lib/` so the plugin reloads.

## Layout

```
lib/
  index.js       plugin entry: registers a provider with ctx.skills
  provider.js    exposes skills/ as a SkillProvider
  frontmatter.js dependency-free YAML frontmatter parser
skills/          36 skills, shipped as upstream wrote them
cordis.patch.yml inserts the plugin into a profile's layer stack
test/            unit + integration tests
scripts/         upstream-sync patches, smoke tests
```

No runtime dependencies: skill frontmatter is read by the bundled parser, so this package never fights the host over YAML versions.

## License

MIT, same as upstream. The skills are Every's work (Copyright (c) 2025 Every); see `LICENSE`.
