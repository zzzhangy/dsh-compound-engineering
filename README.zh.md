# dsh-compound-engineering

[English](README.md) | 简体中文

把 [Every 的 compound-engineering](https://github.com/EveryInc/compound-engineering-plugin) 方法论搬进 DeepSeek Harness 的技能包。

**核心想法**：大多数 AI 编程工具让每次任务都从零开始。compound-engineering 改成复利——每次解决的问题都沉淀成仓库里的一份文档，下一次遇到同类问题时直接读到，于是每一轮改动都让下一轮更容易。

```
brainstorm → plan → work → review → compound
                                      └─ 把这次学到的东西写进仓库
```

36 个技能全部随包分发，安装后无需任何配置即可使用。

**可选依赖 `jq`。** 有六个脚本会调用它：cross-model 系列（`ce-work`、`ce-code-review`、`ce-doc-review`、`ce-pov`）以及 `elevation-dispatch`（`ce-plan`、`ce-brainstorm`）。没有 `jq` 时它们都不会中断所在技能，但降级方式分两种：

- `ce-code-review` / `ce-doc-review` / `ce-pov`：打印 `jq not installed; skipping` 后退出码 0，该轮多模型审查直接跳过。
- `ce-work` 的 cross-model：报 `transport unavailable (pre-egress, shared): jq not found` 并以退出码 2 结束，外层按“跨模型通道不可用”处理。
- `elevation-dispatch`：输出 `status:failed` 的结果信封，外层降级为内联执行。

你也就失去了多模型交叉复核这一层。想启用就装上：

```bash
winget install jqlang.jq    # Windows
brew install jq             # macOS
apt install jq              # Debian/Ubuntu
```

## 安装

```bash
dsh plugin --profile web add dsh-compound-engineering
```

`web` 换成你实际用的 profile 名（`headless`、`tui` 等）。这条命令会自动把这个包加进 `dsh.profile.bundles`，不用手工改配置。

也可以手工两步：在 profile 的 `package.json` 里加依赖，再把它加进 `dsh.profile.bundles`。

```jsonc
{
  "dependencies": { "dsh-compound-engineering": "^0.1.4" },
  "dsh": { "profile": { "bundles": ["dsh-compound-engineering"] } }
}
```

装好后重启 DSH。会话里敲 `/ce-plan` 就能看到技能。

### 更新

```bash
dsh plugin --profile web update dsh-compound-engineering
```

更新后同样要重启 DSH —— 技能目录是会话启动时注入的，不重启的话当前会话看到的还是旧技能描述。

不指定版本安装时记下的是 caret 范围（`^0.1.4`），能接受 `0.1.5`、`0.1.9`，但**接不住 `0.2.0`**。跨 minor 或 major 需要再跑一次 `add dsh-compound-engineering`。想锁死版本就带版本号装：`dsh plugin --profile web add dsh-compound-engineering@0.1.4`。

每个版本改了什么见 [CHANGELOG.md](CHANGELOG.md)。

## 常用技能

| 技能 | 什么时候用 |
| --- | --- |
| `/ce-brainstorm` | 想法还模糊，先把它逼成明确的方案 |
| `/ce-plan` | 需求清楚，要一份能执行的计划 |
| `/ce-work` | 按计划动手实现 |
| `/ce-code-review` | 提交前找人挑刺（可以并行多模型对照） |
| `/ce-compound` | **收尾**：把这次排查出的非显然结论写进仓库 |
| `/ce-debug` | 卡住了，系统性定位根因 |
| `/ce-commit-push-pr` | 一次走完提交、推送、开 PR |

`/lfg`（let's f\*\*\*ing go）把 brainstorm 到 PR 的全流程串起来。

其余 28 个技能见 `skills/` 目录，或直接问模型"有哪些技能"。

## ce-compound 是这套东西的差异点

别处的"记忆"插件记住的是对话。`ce-compound` 记住的是**仓库**：

- 跑起来会先读本机的 dsh 历史会话文件，把当时踩过的坑挖出来
- 产出写在 `<repo>/docs/solutions/` 下，随代码一起提交、一起 review
- 下次任何人（或任何模型）在同一个仓库工作时都会读到它

它刻意不记录"改了哪几行"——那从 git 里就能看出来。它记录的是"为什么这么改"这类从代码和测试里读不出来的东西。

## 在 DeepSeek Harness 上的适配

上游是给 Claude Code 等 14 个宿主写的。移植时做了这些事：

**平台能力靠"能力"匹配，不硬编码工具名。** 上游正文本来就用 "the host's blocking question tool" 这类措辞，所以 36 个技能的正文几乎原样可用。补的只是 DSH 这一档的具体名字（`ask_user_question`、`todo_write`、`subagent`、`web_fetch`、`web_search`）。

**会话历史多了 dsh 平台。** `skills/ce-compound/scripts/session-history/dsh_session.py` 能读 DSH 自己的会话文件。这里有个坑值得记：DSH 的 `session.v4.jsonl.zstd` 是**多个 zstd 帧首尾拼接**（每次 append 追加一帧），标准的 `zstd -d` 或 `compression.zstd.decompress` 只解第一帧就返回，会静默丢掉整个会话。所以脚本自己扫帧边界，逐帧解压。需要 Python 3.14+；更老的解释器上会安静降级成"没有 dsh 会话可读"。

**会话历史三个提取脚本只认 dsh。** `extract-metadata.py`、`extract-skeleton.py`、`extract-errors.py` 只解 dsh 会话，原来的 Claude Code / Codex / Cursor / Pi / oh-my-pi 分支全部删掉，净减约 845 行。`discover-sessions.sh` 保留了其它平台探测（混合工具仓库仍能列文件），但文档里的管道固定带 `--platform dsh`。dsh 会话只记 `cwd` 不记 git 分支，所以过滤按工作目录走，不按分支。

**dev server 配置优先读 `.dsh/launch.json`。** `ce-polish` 需要知道怎么起本地服务，查找顺序是 `.dsh/` → `.claude/` → `.vscode/`。

**host 身份白名单加了 dsh。** 几个 cross-model 脚本原来只认 `codex|claude|grok|cursor|opencode|antigravity|omp`，如实上报 `dsh` 会被拒。

**任务追踪、子代理、网页抓取**都补了 DSH 的对应物。子代理在 DSH 上直接 `subagent` 派生，不必造一个假的 `subagent_type`。

**Windows 上 `ce-work` 的 unit 流水线现在能跑通。** 这条路线上游只做了 POSIX，改动了四处，移植同类代码时都会撞上：

- `fcntl` 不存在。加锁改用 `msvcrt.locking`，但它是非阻塞的，抢不到锁直接抛异常而不等待，所以封装层做了指数退避重试，最长 30 秒。
- Windows 上 **`os.open()` 打不开目录**（缺 `FILE_FLAG_BACKUP_SEMANTICS`，内核直接拒绝）。所有 `open(path, O_DIRECTORY)` + `fstat(fd)` 式的属主校验，改成走路径版的 `GetNamedSecurityInfoW`。`dir_fd` 同样不可用，于是"目录句柄"在 POSIX 上是真 fd、在 Windows 上是路径，由 `close_dir_handle()` 抹平差异。
- mode 位是合成的：`mkdir` 0o700 实测报 0o777，`chmod` 0o600 实测报 0o666。任何 `st_mode != 0o700` 的闸门在 Windows 上必然失败。改为比对当前用户 SID，私密性靠加固过的 ACL（`icacls /inheritance:r`）而不是 mode。
- CRT 文本模式会把 `\n` 变成 `\r\n`、在读到你 `0x1A` 时截断，所以二进制打开一律带 `O_BINARY`。

`os.lstat()` 在 Windows 上能给出稳定的非零 `st_dev`/`st_ino`，所以控制器记录的目录 identity 仍然有效可校验。

**文本一律显式按 UTF-8 读。** 中文 Windows 上 Python 默认 GBK，读上游自己的大部分技能文件都会抛 `UnicodeDecodeError`。

## 开发

```bash
npm test              # JS 单元 + 集成测试，随后跑 Python 测试
npm run test:py       # 只跑 Python 测试（会话读取器、Windows 兼容）
```

集成测试需要能找到 DSH 运行时。默认从包名 import，失败则扫描 `~/.dsh/runtime/versions/*`；也可以用 `DSH_RUNTIME` 指过去。找不到运行时时整组跳过，不会报失败。

发版由 tag 驱动：推送 `v*` tag 会触发 `.github/workflows/publish.yml`，走 npm 的 OIDC trusted publisher 发布（无需本地 OTP、不在仓库里存 token）。完整流程与已踩过的坑见 [docs/releasing.md](docs/releasing.md)。

改上游技能后，重新跑这两个幂等补丁脚本：

```bash
python scripts/patch-dsh-capabilities.py   # 给技能正文补 DSH 档位
python scripts/patch-host-allowlists.py    # 补 cross-model 的 host 白名单
```

### 用 `file:` 方式开发时，改完源码要刷副本

`dsh plugin add file:<本地路径>` 走的是 pnpm 的目录依赖，`node_modules/` 里放的是**拷贝**，不是软链。pnpm 会把目录依赖的内容记进 lockfile（`resolution: {directory: ..., type: directory}`），所以改完源码之后跑 `pnpm install`、`pnpm update`、甚至重跑 `dsh plugin add` 都**不会**刷新那份拷贝——你会一直跑到旧代码，而且因为技能清单来自旧副本，`lib/` 里改了什么都看不出来。

确认是否踩到（哈希不一致就是踩到了）：

```bash
md5sum skills/ce-work/scripts/unit_workspace_state.py \
  ~/.dsh/profiles/web/node_modules/dsh-compound-engineering/skills/ce-work/scripts/unit_workspace_state.py
```

直接重建副本最省事：

```bash
python -c "
import shutil, os
dst = os.path.expanduser('~/.dsh/profiles/web/node_modules/dsh-compound-engineering')
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree('<源码目录>', dst,
                ignore=shutil.ignore_patterns('node_modules','.git','__pycache__','*.pyc','test'))
"
```

副本里的 `skills/` 必须和源码一一对应（`test/` 不随包分发）。改完 `lib/` 后需要重启 DSH 才会重新加载插件。

## 结构

```
lib/
  index.js       插件入口：向 ctx.skills 注册 provider
  provider.js    把 skills/ 目录暴露成 SkillProvider
  frontmatter.js 零依赖 YAML frontmatter 解析
skills/          36 个技能（上游原样分发）
cordis.patch.yml 把插件插进 profile 的层栈
test/            单元 + 集成测试
scripts/         上游同步补丁、冒烟测试
```

本包不引入任何运行时依赖：技能的 YAML 用自带的解析器读，不与宿主的 YAML 版本打架。

## 许可

MIT，与上游一致。技能的著作权归 Every（Copyright (c) 2025 Every），见 `LICENSE`。
