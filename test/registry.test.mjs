// 集成测试：把 provider 注册进 DSH 真实的 SkillRegistry，验证合并、检索与
// renderSkillContent 渲染都正常。
//
// dsh 的宿主包不在本包的依赖里，找不到时整组跳过 —— 在普通 CI 上仍能跑
// 单测，在有 DSH 安装的机器上才跑集成。
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { createProvider } from '../lib/provider.js';
import { createSkillRegistry, loadDshSkill } from './_dsh-modules.mjs';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const skillsRoot = join(root, 'skills');

/** 探测 DSH 宿主是否可用，不可用时整组跳过。 */
async function hostAvailable() {
  try {
    await loadDshSkill();
    return true;
  } catch {
    return false;
  }
}

const available = await hostAvailable();
const skip = available ? false : '未找到 DSH 运行时（可用 DSH_RUNTIME 指定）';

test('注册表装载 36 个技能且无重名', { skip }, async () => {
  const { registry } = await createSkillRegistry();
  const dispose = registry.registerProvider(() => createProvider(skillsRoot, quietLogger()));
  try {
    const summaries = await registry.list();
    assert.equal(summaries.length, 36);
    assert.equal(new Set(summaries.map((s) => s.name)).size, 36);
  } finally {
    dispose();
  }
});

test('快照是完整的', { skip }, async () => {
  const { registry } = await createSkillRegistry();
  const dispose = registry.registerProvider(() => createProvider(skillsRoot, quietLogger()));
  try {
    const snapshot = await registry.snapshot();
    assert.equal(snapshot.complete, true);
  } finally {
    dispose();
  }
});

test('模型可见 27 个，仅手动 9 个', { skip }, async () => {
  const { registry } = await createSkillRegistry();
  const dispose = registry.registerProvider(() => createProvider(skillsRoot, quietLogger()));
  try {
    const summaries = await registry.list();
    const modelVisible = summaries.filter((s) => s.invocation.modelInvocable).length;
    assert.equal(modelVisible, 27);
    assert.equal(summaries.length - modelVisible, 9);
  } finally {
    dispose();
  }
});

test('renderSkillContent 渲染出 resourceBase 目录', { skip }, async () => {
  const { registry } = await createSkillRegistry();
  const { renderSkillContent } = await loadDshSkill();
  const dispose = registry.registerProvider(() => createProvider(skillsRoot, quietLogger()));
  try {
    const definition = await registry.get('ce-compound');
    assert.ok(definition, 'ce-compound 取不到');
    const rendered = renderSkillContent(definition);
    assert.match(rendered, /<skill_content name="ce-compound">/);
    assert.match(rendered, /<skill_instructions>/);
    // 有这一行，正文里的 references/xxx.md 才能被模型按相对路径打开
    assert.match(rendered, /Base directory for this skill:/);
    assert.ok(rendered.includes('ce-compound'));
  } finally {
    dispose();
  }
});

test('dispose 后注册表清空', { skip }, async () => {
  const { registry } = await createSkillRegistry();
  const dispose = registry.registerProvider(() => createProvider(skillsRoot, quietLogger()));
  dispose();
  assert.equal((await registry.list()).length, 0);
});

test('正文引用的关键脚本确实随包分发', () => {
  // 这些是 ce-compound 深挖历史会话的入口，缺一个就退化成只能读对话摘要
  const spots = [
    ['ce-compound', 'references/assembly.md'],
    ['ce-compound', 'references/modes.md'],
    ['ce-compound', 'scripts/validate-frontmatter.py'],
    ['ce-compound', 'scripts/session-history/discover-sessions.sh'],
    ['ce-compound', 'scripts/session-history/discover_dsh.py'],
    ['ce-compound', 'scripts/session-history/dsh_session.py'],
    ['ce-plan', 'references/universal-planning.md'],
    ['ce-work', 'references/implementation-loop.md'],
  ];
  for (const [skill, relative] of spots) {
    const path = join(skillsRoot, skill, relative);
    assert.ok(existsSync(path), `缺少引用文件: ${skill}/${relative}`);
  }
});

function quietLogger() {
  return { info() {}, warn() {}, debug() {} };
}
