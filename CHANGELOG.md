# 变更日志

本文件记录 `dsh-compound-engineering` 每个发行版的变化。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

发版时必须在本文件顶部为即将发布的版本添加一节 —— CI 会校验，
缺失则中止发布（见 `.github/workflows/publish.yml`）。

版本语义：

- **patch**（0.1.4 → 0.1.5）：修 bug、改文档、补测试，技能的行为与接口不变
- **minor**（0.1.5 → 0.2.0）：新增技能、技能行为调整、新增配置项
- **major**（0.2.0 → 1.0.0）：删除技能、改变已有技能的调用契约、提高 DSH 最低版本要求

---

## [0.1.4] - 2026-10-27

### 文档

- `docs/releasing.md` 补记 §4.11「测试在 Windows 全绿、Linux CI 必挂」：
  说明 mode/umask 类断言在 Windows 上拿不到真实结果（目录一律显示 0777），
  并记录已排除的两个方向（路径大小写、行尾污染）。
- `docs/releasing.md` 补记 §4.12「CI 日志看不到时怎么定位」：
  Actions 日志 API 在权限不足时返回 403，给出靠步骤名与静态 grep 定位的办法。

## [0.1.3] - 2026-10-27

### 修复

- **Windows 通过、Linux CI 必挂的测试前置条件**（`test/test_windows_compat.py`）：
  - `_make_unit` 原先先用 `os.makedirs` 建出 0o755 目录，触发了 POSIX 分支
    `validate_private_dir` 对 0700 的断言；改为直接调 `state.ensure_private_dir()`。
  - `test_read_and_stat_through_handle` 用默认 `open(..., "wb")` 写出 0644 文件，
    触发了 POSIX 分支对 0600 的断言；改为 `os.open(..., 0o600)` 显式指定权限。
  - 这两个断言在 Windows 分支被跳过，所以本地一直是绿的，直到 Linux runner 上才暴露。

## [0.1.2] - 未发布

此版本 CI 失败，从未上架 npm。npm 服务端保留了该版本号的占用记录，
无法重发，因此直接跳到 0.1.3。内容并入 0.1.3。

- 增加 `prepack` 钩子，打包前清理 `__pycache__`。
- 增加 `.github/workflows/publish.yml`，改为打 tag 触发 OIDC 自动发布。
- 修正 workflow 里 pyc 检查的误判（`grep` 会把 prepack 日志当成命中）。
- 修正 ubuntu runner 没有 `python` 命令（只有 `python3`）。

## [0.1.1] - 2026-10-27

### 修复

- 清理 `__pycache__`，避免 `.pyc` 文件混进发布包。
  起因是 `package.json` 的 `files` 白名单收录了整个 `skills` 目录，
  而 npm 打包时不看 `.gitignore` 对已跟踪目录的忽略规则。

### 杂项

- 补齐 npm 发布所需的 `repository` / `homepage` / `bugs` / `author` 字段。

## [0.1.0] - 2026-10-27

### 新增

- 首次发布：把 [compound-engineering](https://github.com/EveryInc/compound-engineering-plugin)
  移植到 DeepSeek Harness，以 bundle 插件形态分发 **36 个技能**：
  - 探索与规划：`ce-brainstorm`、`ce-ideate`、`ce-plan`、`ce-strategy`、`ce-pov`
  - 实现与验证：`ce-work`、`ce-debug`、`ce-prototype`、`ce-test-browser`、`ce-optimize`
  - 评审与收尾：`ce-code-review`、`ce-doc-review`、`ce-simplify-code`、`ce-noslop`
  - 提交与协作：`ce-commit`、`ce-commit-push-pr`、`ce-resolve-pr-feedback`、`ce-babysit-pr`、`ce-worktree`
  - 知识沉淀：`ce-compound`、`ce-compound-refresh`、`ce-handoff`、`ce-explain`
  - 其他：`ce-bakeoff`、`ce-dogfood`、`ce-polish`、`ce-product-pulse`、`ce-promote`、
    `ce-proof`、`ce-retune`、`ce-riffrec-feedback-analysis`、`ce-setup`、`ce-sweep`、
    `ce-test-xcode`、`lfg`、`wtf`
- 通过 `ctx.skills.registerProvider()` 注册到 DSH 技能注册表，装完即用，无需额外配置。
- `ce-compound` 的会话历史检索改为只读 DSH 会话
  （`$DSH_HOME/sessions/` 下的 `.jsonl.zstd`，Python 3.14+ 解码），
  不再支持 Claude Code / Codex / Cursor / Pi / omp 的会话格式。

<!--
以下链接只覆盖有 git tag 的版本。0.1.0 与 0.1.1 是打 tag 之前的本地手工发布，
没有对应 tag，故指向 npm 版本页而非 compare 链接（compare 会 404）。
-->

[0.1.4]: https://github.com/zzzhangy/dsh-compound-engineering/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/zzzhangy/dsh-compound-engineering/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/zzzhangy/dsh-compound-engineering/releases/tag/v0.1.2
[0.1.1]: https://www.npmjs.com/package/dsh-compound-engineering/v/0.1.1
[0.1.0]: https://www.npmjs.com/package/dsh-compound-engineering/v/0.1.0
