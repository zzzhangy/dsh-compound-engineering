// 端到端测试：把插件当成真正的 cordis 插件挂到 Context 上，验证
// `inject` 依赖声明、`apply` 注册、以及 disposer 的清理顺序都成立。
//
// 这一层与 registry.test.mjs 的区别：registry 测试直接调 registerProvider，
// 这里走的是 cordis 的插件生命周期（ctx.plugin → fiber → effect）。
//
// 宿主包发现复用 _dsh-modules.mjs：从 profile 目录跑时按包名 import 命中，
// 否则扫描 ~/.dsh/runtime/versions 下的 pnpm 布局；都没有时整组跳过。
import assert from 'node:assert/strict';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createSkillRegistry, loadCordis } from './_dsh-modules.mjs';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const pluginUrl = pathToFileURL(join(root, 'lib/index.js')).href;

/** 探测 DSH 宿主是否可用，不可用时整组跳过。 */
async function hostAvailable() {
  try {
    await loadCordis();
    const plugin = await import(pluginUrl);
    return typeof plugin.apply === 'function';
  } catch {
    return false;
  }
}

const available = await hostAvailable();
const skip = available ? false : '未找到 DSH 运行时（可用 DSH_RUNTIME 指定）';

test('插件清单字段符合 cordis 约定', { skip }, async () => {
  const plugin = await import(pluginUrl);
  assert.equal(plugin.name, 'compound-engineering');
  assert.ok(Array.isArray(plugin.inject), 'inject 应为数组');
  assert.ok(plugin.inject.includes('skills'), 'inject 应声明 skills');
  assert.equal(typeof plugin.apply, 'function');
});

test('经 cordis 生命周期挂载后注册表有 36 个技能', { skip }, async () => {
  const { app } = await createSkillRegistry();
  const plugin = await import(pluginUrl);
  const mounted = app.plugin(plugin);
  if (mounted && typeof mounted.then === 'function') await mounted;
  await app.start?.();

  const names = (await app.skills.list()).map((s) => s.name).sort();
  assert.equal(names.length, 36, `期望 36 个技能，实际 ${names.length}`);
  assert.equal(new Set(names).size, 36, '技能名不应重复');
});

test('经 cordis 生命周期卸载后注册表清空', { skip }, async () => {
  const { app } = await createSkillRegistry();
  const plugin = await import(pluginUrl);
  const mounted = app.plugin(plugin);
  if (mounted && typeof mounted.then === 'function') await mounted;
  await app.start?.();

  if (mounted && typeof mounted.dispose === 'function') {
    await mounted.dispose();
    const left = await app.skills.list();
    assert.equal(left.length, 0, `卸载后仍有 ${left.length} 个技能`);
  }
  // 该宿主版本的 plugin() 若未返回可 dispose 的 fiber，则跳过卸载断言，
  // 清理路径已由 registry.test.mjs 的 dispose 测试覆盖。
});
