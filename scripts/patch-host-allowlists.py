"""给三个 cross-model worker 脚本加入 dsh / deepseek 的 host 标识。

上游的 host harness 白名单只认 codex|claude|grok|cursor|opencode|antigravity|omp，
host serving family 白名单只认 codex|claude|grok|composer|gemini。DeepSeek Harness
如实上报自己时会被拒绝，因此补上 dsh（harness）与 deepseek（family）。

迁移到上游新版本后需要重新执行本脚本。
"""
import os
import sys

SKILLS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")

TARGETS = [
    "ce-code-review/scripts/cross-model-adversarial-review.sh",
    "ce-doc-review/scripts/cross-model-doc-review.sh",
    "ce-pov/scripts/cross-model-pov.sh",
]

# (原文, 替换)
REPLACEMENTS = [
    ("codex|claude|grok|cursor|opencode|antigravity|omp|unknown) ;;",
     "codex|claude|grok|cursor|opencode|antigravity|omp|dsh|unknown) ;;"),
    ("codex|claude|grok|composer|gemini|unknown) ;;",
     "codex|claude|grok|composer|gemini|deepseek|unknown) ;;"),
    ("want codex|claude|grok|cursor|opencode|antigravity|omp|unknown",
     "want codex|claude|grok|cursor|opencode|antigravity|omp|dsh|unknown"),
    ("want codex|claude|grok|composer|gemini|unknown",
     "want codex|claude|grok|composer|gemini|deepseek|unknown"),
]


def patch(relative_path):
    path = os.path.join(SKILLS_ROOT, relative_path)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    changed = 0
    for old, new in REPLACEMENTS:
        if old in text and new not in text:
            text = text.replace(old, new)
            changed += 1
    if changed:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    print(f"{relative_path}: {changed} replacement(s)")
    return changed


if __name__ == "__main__":
    total = sum(patch(p) for p in TARGETS)
    sys.exit(0 if total else 1)
