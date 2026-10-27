"""把 DeepSeek Harness 的工具等价物补进上游技能的跨平台段落。

上游技能正文本身已经按「能力」而不是「工具名」措辞，但在举例时会写
"`TaskCreate`/`TaskUpdate`/`TaskList` in Claude Code, `update_plan` in Codex"。
模型读到这类句子时只会去认 Claude 与 Codex 的名字，在 DSH 上就会退化成
「本平台没有该能力」，从而跳过任务列表、退回到纯 chat 提问等降级路径。

本脚本只做「追加 DSH 档位」的最小侵入替换，不改上游原有措辞与逻辑。
幂等：已补过的文件重跑不会重复插入。

迁移到上游新版本后需要重新执行。
"""
import os
import sys

SKILLS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")

# (相对路径, 原文, 替换)
REPLACEMENTS = [
    # --- 任务追踪能力：DSH 提供 todo_write ---
    (
        "ce-brainstorm/references/phase-0.md",
        "(`TaskCreate`/`TaskUpdate`/`TaskList` in Claude Code, `update_plan` in Codex, or the equivalent on other harnesses)",
        "(`TaskCreate`/`TaskUpdate`/`TaskList` in Claude Code, `update_plan` in Codex, `todo_write` in DeepSeek Harness, or the equivalent on other harnesses)",
    ),
    (
        "ce-work/references/work-intake.md",
        "(`TaskCreate`/`TaskUpdate`/`TaskList` in Claude Code, `update_plan` in Codex, or the equivalent on other harnesses)",
        "(`TaskCreate`/`TaskUpdate`/`TaskList` in Claude Code, `update_plan` in Codex, `todo_write` in DeepSeek Harness, or the equivalent on other harnesses)",
    ),
    (
        "ce-work/references/workspace-setup.md",
        "(`TaskCreate`/`TaskUpdate`/`TaskList` in Claude Code, `update_plan` in Codex, or the equivalent elsewhere)",
        "(`TaskCreate`/`TaskUpdate`/`TaskList` in Claude Code, `update_plan` in Codex, `todo_write` in DeepSeek Harness, or the equivalent elsewhere)",
    ),
    (
        "ce-resolve-pr-feedback/references/full-mode.md",
        "(e.g., `TaskCreate` in Claude Code, `update_plan` in Codex)",
        "(e.g., `TaskCreate` in Claude Code, `update_plan` in Codex, `todo_write` in DeepSeek Harness)",
    ),
    (
        "ce-dogfood/references/phases.md",
        "`TaskCreate`/`TaskUpdate` on Claude Code, `update_plan` on Codex, or the equivalent elsewhere)",
        "`TaskCreate`/`TaskUpdate` on Claude Code, `update_plan` on Codex, `todo_write` on DeepSeek Harness, or the equivalent elsewhere)",
    ),
    # --- 阻塞式提问能力：DSH 提供 ask_user_question ---
    # 关键差异：ask_user_question 对选项数量没有硬上限（Claude 4 个、Codex 2-3 个），
    # 所以「裁掉选项」的降级路径在 DSH 上根本不会被触发。
    (
        "ce-brainstorm/references/handoff.md",
        "Claude Code `AskUserQuestion` supports up to 4 explicit options, and Codex `request_user_input` supports only 2-3 explicit options.",
        "Claude Code `AskUserQuestion` supports up to 4 explicit options, Codex `request_user_input` supports only 2-3 explicit options, and DeepSeek Harness `ask_user_question` has no hard option cap (present every option).",
    ),
    (
        "ce-plan/references/plan-handoff.md",
        "Claude Code `AskUserQuestion` supports up to 4 explicit options, and Codex `request_user_input` supports only 2-3 explicit options.",
        "Claude Code `AskUserQuestion` supports up to 4 explicit options, Codex `request_user_input` supports only 2-3 explicit options, and DeepSeek Harness `ask_user_question` has no hard option cap, so the full menu always fits.",
    ),
    (
        "ce-ideate/references/issue-intelligence.md",
        "(Codex `request_user_input` takes 2-3 explicit options; `AskUserQuestion` takes 4)",
        "(Codex `request_user_input` takes 2-3 explicit options; `AskUserQuestion` takes 4; DeepSeek Harness `ask_user_question` is uncapped)",
    ),
    # --- 子代理能力：DSH 提供 subagent / subagent_fork ---
    (
        "ce-code-review/references/dispatch-reviewers.md",
        "Do not name a persona or CE agent through `subagent_type`, typed `Agent` names, or platform-level CE agent registration;",
        "Do not name a persona or CE agent through `subagent_type`, typed `Agent` names, or platform-level CE agent registration (on DeepSeek Harness, seed a plain `subagent` with the prompt asset inline);",
    ),
    (
        "ce-plan/references/deepening-workflow.md",
        "Do not name a persona or CE agent through `subagent_type`, typed `Agent` names, or platform-level CE agent registration;",
        "Do not name a persona or CE agent through `subagent_type`, typed `Agent` names, or platform-level CE agent registration (on DeepSeek Harness, seed a plain `subagent` with the prompt asset inline);",
    ),
    # --- 技能目录发现：DSH 用 .dsh/skills 与 ~/.dsh/skills ---
    (
        "ce-compound/references/agents/best-practices-researcher.md",
        "- For maximum compatibility, check project/workspace skill directories in `.claude/skills/**/SKILL.md`, `.codex/skills/**/SKILL.md`, and `.agents/skills/**/SKILL.md`\n   - Also check user/home skill directories in `~/.claude/skills/**/SKILL.md`, `~/.codex/skills/**/SKILL.md`, and `~/.agents/skills/**/SKILL.md`",
        "- For maximum compatibility, check project/workspace skill directories in `.claude/skills/**/SKILL.md`, `.codex/skills/**/SKILL.md`, `.dsh/skills/**/SKILL.md`, and `.agents/skills/**/SKILL.md`\n   - Also check user/home skill directories in `~/.claude/skills/**/SKILL.md`, `~/.codex/skills/**/SKILL.md`, `~/.dsh/skills/**/SKILL.md`, and `~/.agents/skills/**/SKILL.md`",
    ),
    (
        "ce-plan/references/agents/best-practices-researcher.md",
        "- For maximum compatibility, check project/workspace skill directories in `.claude/skills/**/SKILL.md`, `.codex/skills/**/SKILL.md`, and `.agents/skills/**/SKILL.md`\n   - Also check user/home skill directories in `~/.claude/skills/**/SKILL.md`, `~/.codex/skills/**/SKILL.md`, and `~/.agents/skills/**/SKILL.md`",
        "- For maximum compatibility, check project/workspace skill directories in `.claude/skills/**/SKILL.md`, `.codex/skills/**/SKILL.md`, `.dsh/skills/**/SKILL.md`, and `.agents/skills/**/SKILL.md`\n   - Also check user/home skill directories in `~/.claude/skills/**/SKILL.md`, `~/.codex/skills/**/SKILL.md`, `~/.dsh/skills/**/SKILL.md`, and `~/.agents/skills/**/SKILL.md`",
    ),
    # --- 网页抓取：DSH 提供 web_fetch / web_search ---
    (
        "ce-compound/references/agents/framework-docs-researcher.md",
        "- **WebFetch / WebSearch**: fallback when neither Context7 path works.",
        "- **WebFetch / WebSearch** (DeepSeek Harness: `web_fetch` / `web_search`): fallback when neither Context7 path works.",
    ),
    (
        "ce-plan/references/agents/framework-docs-researcher.md",
        "- **WebFetch / WebSearch**: fallback when neither Context7 path works.",
        "- **WebFetch / WebSearch** (DeepSeek Harness: `web_fetch` / `web_search`): fallback when neither Context7 path works.",
    ),
    (
        "ce-compound/references/agents/best-practices-researcher.md",
        "- **WebFetch / WebSearch**: fallback when neither Context7 path is available, or to augment with community articles, discussions, and style guides.",
        "- **WebFetch / WebSearch** (DeepSeek Harness: `web_fetch` / `web_search`): fallback when neither Context7 path is available, or to augment with community articles, discussions, and style guides.",
    ),
    (
        "ce-plan/references/agents/best-practices-researcher.md",
        "- **WebFetch / WebSearch**: fallback when neither Context7 path is available, or to augment with community articles, discussions, and style guides.",
        "- **WebFetch / WebSearch** (DeepSeek Harness: `web_fetch` / `web_search`): fallback when neither Context7 path is available, or to augment with community articles, discussions, and style guides.",
    ),
    # --- 会话历史根目录：补上 dsh ---
    (
        "ce-compound/references/agents/session-historian.md",
        "defaults: `~/.claude/projects/`, `~/.codex/sessions/`, `~/.cursor/projects/`, `~/.pi/agent/sessions/`, `~/.omp/agent/sessions/`, `$XDG_DATA_HOME/omp/sessions`; relocated when `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `PI_CODING_AGENT_DIR`, `PI_CODING_AGENT_SESSION_DIR`, or `PI_CONFIG_DIR` is set)",
        "defaults: `~/.claude/projects/`, `~/.codex/sessions/`, `~/.cursor/projects/`, `~/.pi/agent/sessions/`, `~/.omp/agent/sessions/`, `$XDG_DATA_HOME/omp/sessions`, `$DSH_HOME/sessions/`; relocated when `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `PI_CODING_AGENT_DIR`, `PI_CODING_AGENT_SESSION_DIR`, `PI_CONFIG_DIR`, or `DSH_HOME` is set)",
    ),
    # --- 平台绑定的可选工具清单：补上 DSH 的 read ---
    (
        "ce-compound/references/agents/session-historian.md",
        "Use the platform's native file-read tool (e.g., `Read` in Claude Code)",
        "Use the platform's native file-read tool (e.g., `Read` in Claude Code, `read` in DeepSeek Harness)",
    ),
]


def patch(relative_path, old, new):
    path = os.path.join(SKILLS_ROOT, relative_path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if new in text:
        return 0
    if old not in text:
        print(f"  ! 未命中: {relative_path}", file=sys.stderr)
        return 0
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text.replace(old, new, 1))
    return 1


if __name__ == "__main__":
    total = 0
    misses = 0
    for relative_path, old, new in REPLACEMENTS:
        changed = patch(relative_path, old, new)
        total += changed
        if changed == 0 and not os.path.exists(os.path.join(SKILLS_ROOT, relative_path)):
            misses += 1
    print(f"共应用 {total} 处 DSH 平台补丁")
    sys.exit(0)
