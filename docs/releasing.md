# 发版与推送流程

> 本文记录 `dsh-compound-engineering` 的完整发布链路。踩过的坑都写进来了，
> 遇到异常先来这里对照，不要凭直觉重试。

## 0. 一页速查

```bash
cd /e/project/dsh-compound-engineering

npm version patch --no-git-tag-version   # 0.1.2 → 0.1.3
git commit -am "chore: 0.1.3"
git tag v0.1.3
git push origin main
git push origin v0.1.3                   # 关键：tag 必须单独推
```

推完去看 <https://github.com/zzzhangy/dsh-compound-engineering/actions>，
`publish` workflow 跑绿即发版完成。

**`git push origin main` 不会带上 tag。** 忘了这一条，Actions 会显示
“This workflow has no runs yet”，很多人误以为 workflow 没配好。

---

## 1. 前置条件（只需配一次）

### 1.1 npm 侧：登记 Trusted Publisher

<https://www.npmjs.com/package/dsh-compound-engineering/access> → **Trusted Publisher**

| 字段 | 值 |
| --- | --- |
| Publisher | GitHub Actions |
| Organization or user | `zzzhangy` |
| Repository | `dsh-compound-engineering` |
| Workflow filename | `publish.yml`（只填文件名，不要带 `.github/workflows/` 路径） |
| Environment name | 留空 |

Allowed actions 两个都勾：**Allow npm publish**、**Allow npm dist-tag**。

配好后状态是 `Pending validation` —— **必须成功发布一次才会转正**。
npm 给的期限是配置后 7 天内。

### 1.2 npm 侧：收紧发布策略

同一个 Settings 页面的 **Publishing access**，选：

> Require two-factor authentication **and disallow bypass 2fa tokens**

理由见 §4.1。改完点 **Update Package Settings**。

### 1.3 仓库侧：workflow 文件存在

`.github/workflows/publish.yml` 必须在**默认分支**上，且文件名与 npm 后台
填的完全一致（`publish.yml`）。OIDC 校验失败时 npm 的报错很模糊，通常是这里错了。

---

## 2. 发版步骤详解

### 2.1 升版本号

```bash
npm version patch --no-git-tag-version
```

用 `--no-git-tag-version` 是因为我们**想自己控制 tag 的创建时机和注解**。
`patch` / `minor` / `major` 按改动性质选。

### 2.2 提交

```bash
git commit -am "chore: 0.1.3"
```

### 2.3 打 tag

```bash
git tag v0.1.3
```

tag 名必须与 `package.json` 的 version 严格对应（`v` + 版本号）。
workflow 第一步就会校验，不一致直接失败：

```
tag v0.1.3 与 package.json 的 0.1.2 不一致，中止发布
```

想带说明可以用注解 tag（此时 `--follow-tags` 才会认）：

```bash
git tag -a v0.1.3 -m "0.1.3"
```

### 2.4 推送分支和 tag

```bash
git push origin main
git push origin v0.1.3
```

**不要只推 main。** 触发条件是 `on: push: tags: ['v*']`，分支推送不触发。

`git push origin main --follow-tags` 看起来更省事，但 **`--follow-tags` 只推注解 tag**，
轻量 tag（`git tag v0.1.3` 这种）会被静默跳过。分两条命令最稳。

### 2.5 观察运行

<https://github.com/zzzhangy/dsh-compound-engineering/actions>

成功会看到 7 个步骤全绿：

```
✓ checkout
✓ setup-node
✓ 校验 tag 与 package.json 版本一致
✓ 确保 python 命令可用
✓ 跑测试
✓ 确认打包结果里没有 __pycache__
✓ 发布到 npm
```

发布完成后 npm 页面上：

- Trusted Publisher 的黄色 `Pending validation` 变成绿勾
- 包名旁出现 **Provenance** 徽章（证明包来自该仓库的该 commit）

---

## 3. 发布前自检

workflow 会跑这些，本地最好先过一遍，省一轮 CI：

```bash
npm test                                # 期望 JS 38 pass / 0 fail、py 33 OK
npm pack --dry-run                      # 看文件数和大小，期望 459 文件 / 1.8MB
git status --short                      # 期望干净
```

关于 `npm pack --dry-run` 的文件数：0.1.0 / 0.1.1 是 461（含 3 个 `.pyc`），
`prepack` 清掉 pyc 后是 458，`files` 收录 `docs/` 后是 **459**（0.1.3 起）。
**如果比上面多出 3 个，说明 pyc 又混进来了。**

---

## 4. 踩过的坑

### 4.1 bypass-2FA token 会强制走 staged publishing

**症状**（本项目首发时全套踩中）：

```
npm publish                    → + dsh-compound-engineering@0.1.0   （显示成功）
curl registry.npmjs.org/...    → dist-tags: {"latest":"0.0.0-stage"} （只有占位包）
npm publish                    → 409 Cannot publish over previously staged version "0.1.0"
npm stage list                 → No staged versions.（空的）
npm stage publish              → 409 Cannot stage previously published version "0.1.0"
```

服务端把版本记成“已暂存/已发布”，但 register 查不到、stage 列表为空 —— 版本进了黑洞。

**根因**：npm 11.x 对 bypass-2FA token 强制暂存发布，会先建 `0.0.0-stage`
占位包再异步处理。这个流程在“首次发布 + 占位包”组合下有 bug。

**后果**：`0.1.0` 这个版本号被永久占用，无法重发，只能升到 `0.1.1`。

**解决**：不要用 bypass token 首发新包。改用 §4.2 的 OIDC 路线，或普通 token。

### 4.2 普通 token 首发要浏览器授权（EOTP）

```
npm error code EOTP
npm error This operation requires a one-time password.
npm error Open this URL in your browser to authenticate:
npm error   https://www.npmjs.com/auth/cli/<uuid>
```

终端里那条 URL 在日志中被 `***` 遮蔽，**只出现在终端输出**。按 Enter 让 npm
打开浏览器，点 Authorize 后发布会自动继续。这是绕过 staged publishing 的方式，
但每次发版都要人工点一下 —— 所以才改用 OIDC。

### 4.3 发布有 5 分钟传播延迟

发布成功后立刻 `curl` 查 registry 可能查不到，tarball 返回 404。
**这是正常的**，等 5 分钟再查。当时我们误判成发布失败，白折腾了很久。

### 4.4 国内镜像导致安装 404

`~/.npmrc` 里 `registry` 指向淘宝镜像时，npm 的 `replace-registry-host`
（默认值 `npmjs`）会把官方 tarball 地址也改写成镜像域名。镜像尚未同步新版本时：

```
404 https://cdn.npmmirror.com/packages/dsh-compound-engineering/0.1.1/...tgz
```

包本身没问题。装新包时显式指定：

```bash
npm i dsh-compound-engineering --registry=https://registry.npmjs.org --replace-registry-host=never
```

### 4.5 `__pycache__` 混进发布包

**症状**：tarball 里出现 `skills/**/__pycache__/*.pyc`。

**根因**：`package.json` 的 `files` 白名单写了整个 `skills` 目录，而 npm 的规则是
—— **目录一旦被 `files` 收录，其中的忽略规则（`.npmignore` / `.gitignore`）全部失效**。
实测在根目录写 `**/__pycache__/` 也拦不住。

**解决**：`prepack` 钩子在打包前从磁盘删除（`scripts/clean-pycache.mjs`）：

```json
"prepack": "node scripts/clean-pycache.mjs"
```

### 4.6 workflow 里用 `grep` 查 pyc 会必然误报

`prepack` 的日志本身就会打印 `prepack: 清理了 3 个 __pycache__ 目录`，
所以下面这种写法**每次都会失败**：

```bash
# ❌ 错误：日志命中
if npm pack --dry-run 2>&1 | grep -qE '__pycache__|\.pyc'; then exit 1; fi
```

正确做法是解析 `--json` 的文件清单。另外 `prepack` 的 stdout 会混在 JSON 之前，
必须按行首的 `[` 定位数组起点：

```bash
npm pack --dry-run --json > pack.json
node -e '
  const raw = require("fs").readFileSync("pack.json", "utf8");
  const m = raw.match(/^\[$/m);
  ...'
```

### 4.7 ubuntu runner 没有 `python` 命令

`npm run test:py` 调的是 `python`，而 ubuntu-latest 默认只有 `python3`。
workflow 里补了一步软链（见 `.github/workflows/publish.yml`）。

### 4.8 tag 推了但 Actions 没跑

看远端到底有没有 tag：

```bash
git ls-remote origin main refs/tags/v0.1.3
```

如果只有 `main` 没有 `refs/tags/...`，就是 tag 没推上去（最常见的原因）。
再确认 tag 名匹配 `v*` 通配符。

### 4.9 Windows 上 git push 挂起

**症状**：`git push` 长时间无输出，120s/150s 超时，`exit code 124`。

**根因**：卡在 `git credential-helper-selector get`（Windows Git 的凭据选择器弹窗），
在无头/自动化环境里会一直阻塞。用 `GIT_TRACE=1 git push` 可以看到卡点。

**解决**：在真实终端里手动推一次，弹窗里选 GitHub 账号即可。之后的推送
会用缓存的凭据，不再弹窗。

排查时可以排除的因素（本次都验证过不是它们）：

```bash
git config --get http.proxy        # 空
env | grep -i proxy                # 有 127.0.0.1:7890，但绕过代理照样挂起
git config --get credential.helper # helper-selector ← 就是它
GIT_TERMINAL_PROMPT=0 git ls-remote origin main   # 1.2s 返回，说明网络正常
```

`ls-remote` 秒回而 `push` 挂起，说明卡在认证而非网络。

### 4.10 GitHub 仓库建的时候勾了 Add README

远端会有一个 `Initial commit`，与本地历史无共同祖先，push 直接被拒：

```
! [rejected] main -> main (fetch first)
```

解决：

```bash
git fetch origin
git rebase origin/main          # README.md 会有 add/add 冲突
# 解决冲突：保留本地完整 README，删掉 GitHub 生成的单行简介
git add README.md
GIT_EDITOR=true git rebase --continue
git push origin main
```

下次建仓库记得**不要勾 Add README**。

### 4.11 测试在 Windows 全绿、Linux CI 必挂

本项目是在 Windows 上开发的，而 CI 跑 ubuntu-latest。v0.1.2 的 CI 就挂在
「跑测试」这一步，本地怎么都复现不出来。根因是**测试自身的前置条件**踩到了
脚本里的 POSIX 校验，而 Windows 分支走的是 ACL/owner 检查，根本不看 mode 位。

两处（都在 `test/test_windows_compat.py`）：

```python
# ❌ os.makedirs 用默认 umask 建成 0755，随后 ensure_private_dir 的
#    validate_private_dir 要求 mode 恰好 0700，POSIX 分支直接抛 TrustFailure
os.makedirs(result_dir)
state.ensure_private_dir(result_dir)

# ✅ 交给它自己创建，内部是 os.mkdir(path, 0o700)
state.ensure_private_dir(result_dir)
```

```python
# ❌ 默认 umask 022 → 0644，而 read_private_at 要求 0600
with open(target, "wb") as handle:
    handle.write(payload)

# ✅ 显式指定 mode
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "wb") as handle:
    handle.write(payload)
```

**教训**：任何涉及 `mode & 0o777`、`stat.S_IMODE`、`os.chmod`、`umask` 的测试，
在 Windows 上都得不到真实结果（Windows 的 mode 是合成的，目录一律显示 0777）。
写这类测试要么显式指定 mode，要么就假定它会跑在 Linux 上。

另外两个当时排除掉的怀疑方向，记下来省得下次重查：

- **路径大小写**：Linux 区分大小写，`References/x.md` 与 `references/x.md` 不等价。
  实际用「按目录真实条目逐个解析」比对，缺失数 0。
- **行尾**：`.gitattributes` 已是 `* text=auto eol=lf`，`git ls-files --eol` 显示
  `i/lf w/lf`，检出到 Linux 不会混入 `\r`。

### 4.12 CI 日志看不到时怎么定位

私有仓库 + 细粒度 token 权限不足时，日志接口会直接拒绝：

```bash
curl -H "Authorization: Bearer $TOKEN" \
  https://api.github.com/repos/<owner>/<repo>/actions/jobs/<id>/logs
# → {"message": "Must have admin rights to Repository.", "status": 403}
```

此时仍能看到**哪一步失败**（`GET /actions/runs` 里的 `conclusion`，配合 web 页面
高亮的步骤名），只是拿不到 stdout。剩下的靠读代码推：

```bash
# 列出所有平台分支敏感的调用
grep -n "IS_WINDOWS\|sys.platform\|process.platform" test/*.py test/*.mjs
# 找出「先建目录/文件、后校验」的组合
grep -n "makedirs\|os.mkdir\|open(.*\"wb\")" test/*.py
```

---

## 5. 回滚与补救

### 5.1 想撤销一次发布

npm 不允许删除 24 小时内的版本，也不建议 `unpublish`。正确做法是**发布修复版本**，
然后把 `latest` 指回稳定版：

```bash
npm dist-tag add dsh-compound-engineering@0.1.2 latest
```

这也是为什么 Trusted Publisher 里要勾 **Allow npm dist-tag**。

### 5.2 把包标记为废弃

```bash
npm deprecate dsh-compound-engineering@0.1.3 "此版本有已知问题，请用 0.1.4"
```

用户安装时会看到警告，但已装的不会坏。

### 5.3 版本号被黑洞占用

如 §4.1 的 `0.1.0`：registry 查不到，但服务端记着“已发布”，无法重发。
只能升版本号。要彻底清理可以去 <https://github.com/npm/feedback> 提 issue。

---

## 6. 本地开发与 profile 同步

开发期把本地目录装进 DSH profile 调试：

```bash
DSH=C:/Users/zhiAngZhang/.dsh/runtime/node_modules/.bin/dsh
"$DSH" plugin --profile web add "file:E:/project/dsh-compound-engineering"
```

⚠️ `file:` 安装走 pnpm directory 依赖，`node_modules/` 里是**实体拷贝不是软链**，
且 pnpm 把内容记在 lockfile 里 —— **改完源码后 `pnpm install` / `plugin update`
都不会刷新那份拷贝**，你会一直跑到旧代码。

刷新办法：删掉再装。

```bash
"$DSH" plugin --profile web remove dsh-compound-engineering
"$DSH" plugin --profile web add "file:E:/project/dsh-compound-engineering"
```

或者直接覆盖拷贝后比对：

```bash
SRC=E:/project/dsh-compound-engineering
DST=C:/Users/zhiAngZhang/.dsh/profiles/web/node_modules/dsh-compound-engineering
cp -rf "$SRC/skills" "$SRC/lib" "$SRC/package.json" "$DST/"
diff -rq "$SRC/skills" "$DST/skills" && echo "一致"
```

---

## 7. 更新：用户怎么拿到新版

发布链路和安装链路是两条独立的线 —— 你把新版推上 npm，**已经装了的用户不会自动升级**，
必须显式更新。这一节写清两边各自要做什么。

### 7.1 用户侧：三种更新方式

```bash
# 升到最新（跟随 package.json 里记的版本范围）
dsh plugin update dsh-compound-engineering

# 装或升到指定版本（锁死，不受后续发版影响）
dsh plugin add dsh-compound-engineering@0.1.5

# 全新安装
dsh plugin add dsh-compound-engineering
```

`update` 之后**必须重启 DSH 会话**才生效 —— 技能目录是启动时向注册表注入的，
不重启的话模型看到的还是旧技能描述。

### 7.2 版本范围怎么写

`dsh plugin add` 不指定版本时，profile 的 `package.json` 里记下的是带 `^` 的范围，
例如 `"dsh-compound-engineering": "^0.1.4"`：

- `^0.1.4` 表示 `<0.2.0`，即自动接受 `0.1.5`、`0.1.9`
- 跨 minor 的大改动（`0.2.0` 起）需要用户自己再跑一次 `add dsh-compound-engineering`

这是语义化版本的预期行为：**minor 及以上不自动跟上**，用户得知道自己跨版本了。
所以升 minor 时务必在 CHANGELOG 里写清「需要用户做什么」。

### 7.3 本项目 profile 的特殊情况

开发机上 `C:/Users/zhiAngZhang/.dsh/profiles/web/package.json` 装的是本地目录：

```json
"dsh-compound-engineering": "file:E:/project/dsh-compound-engineering"
```

`file:` 依赖**永远不会跟随 npm 上的新版**，改完源码直接 `remove` + `add` 刷新（见 §6）。
如果想让本机也跟随 npm 发布版（模拟真实用户），改用：

```bash
DSH=C:/Users/zhiAngZhang/.dsh/runtime/node_modules/.bin/dsh
"$DSH" plugin --profile web remove dsh-compound-engineering
"$DSH" plugin --profile web add dsh-compound-engineering
```

换过去之后，本地源码的改动就不再进 profile，必须发版才生效 —— 调试期不要这么做。

---

## 8. 版本语义与 CHANGELOG

### 8.1 版本号怎么选

| 变更类型 | 版本位 | 例子 |
| --- | --- | --- |
| 修 bug、改文档、补测试，技能行为不变 | **patch** | `0.1.4 → 0.1.5` |
| 新增技能、调整已有技能行为、新增配置项 | **minor** | `0.1.5 → 0.2.0` |
| 删技能、改变技能调用契约、提高 DSH 最低版本 | **major** | `0.2.0 → 1.0.0` |

拿不准的时候往大里挑 —— 用户被 patch 版本悄悄改了行为，比多升一个 minor 更难受。

### 8.2 CHANGELOG.md 是发版硬门槛

`CHANGELOG.md` 放在仓库根目录，每次发版前**必须**在顶部加一节：

```markdown
## [0.1.5] - 2026-10-27

### 修复

- 一句话说清改了什么，以及用户需要做什么（如果需要）
```

workflow 里的「校验 CHANGELOG 有本版本条目」这一步会拦截三种情况：

1. 没有 `CHANGELOG.md`
2. 找不到 `## [0.1.5]` 这样标题匹配当前 `package.json` 版本
3. 该行仍写着「未发布」

所以 `npm version patch` 之后完整顺序是：

```bash
npm version patch --no-git-tag-version   # 0.1.4 → 0.1.5
# 现在去改 CHANGELOG.md，加一节 ## [0.1.5] - 日期
git commit -am "chore: 0.1.5"            # -a 会把 CHANGELOG 一起提交
git tag v0.1.5
git push origin main
git push origin v0.1.5
```

漏了 CHANGELOG 这一步，CI 会在打 tag 之后才失败，tag 已经推出去了，
清理起来要走 §5 的流程。**先写 CHANGELOG 再打 tag。**

### 8.3 为什么 CHANGELOG 要进发布包

`package.json` 的 `files` 白名单里收录了 `CHANGELOG.md`，
这样 npm 页面和 `node_modules/dsh-compound-engineering/CHANGELOG.md`
都能看到改动历史 —— 用户不用跳 GitHub 就能判断这次升级值不值。
改了白名单记得跑一次 `npm pack --dry-run` 确认文件数增加了。

---

## 9. 待办

- [x] Trusted Publisher 跑通一次，状态从 `Pending validation` 转正（v0.1.3 首次全绿）
- [x] 把 `Publishing access` 改为 disallow bypass 2fa tokens
- [x] 确认已删除临时 bypass token（<https://www.npmjs.com/settings/zhiangzhang1/tokens>）
- [x] 清除本地 `~/.npmrc` 里的发布凭据（CI 走 OIDC，本地不再需要）
- [x] 新增 `CHANGELOG.md`，workflow 校验发版必有对应条目
- [ ] README 加 npm 徽章与 provenance 徽章
- [ ] 考虑加一个 `test:linux` 的本地校验脚本，提前拦住 §4.11 那类问题
- [ ] 把 README 的安装段补上 `dsh plugin update` 的说明（目前只写了初次安装）
