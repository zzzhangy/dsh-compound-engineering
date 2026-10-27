// provider 契约测试：用真实的 skills/ 目录跑，确认对外契约稳定。
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { PROVIDER_NAME, createProvider } from '../lib/provider.js';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const skillsRoot = join(root, 'skills');
const quietLogger = { info() {}, warn() {}, debug() {} };

/** 上游 36 个技能名，用于对齐断言。 */
const EXPECTED_NAMES = [
  'ce-babysit-pr', 'ce-bakeoff', 'ce-brainstorm', 'ce-code-review', 'ce-commit',
  'ce-commit-push-pr', 'ce-compound', 'ce-compound-refresh', 'ce-debug', 'ce-doc-review',
  'ce-dogfood', 'ce-explain', 'ce-handoff', 'ce-ideate', 'ce-noslop', 'ce-optimize',
  'ce-plan', 'ce-polish', 'ce-pov', 'ce-product-pulse', 'ce-promote', 'ce-proof',
  'ce-prototype', 'ce-resolve-pr-feedback', 'ce-retune', 'ce-riffrec-feedback-analysis',
  'ce-setup', 'ce-simplify-code', 'ce-strategy', 'ce-sweep', 'ce-test-browser',
  'ce-test-xcode', 'ce-work', 'ce-worktree', 'lfg', 'wtf',
];

/** 上游标记 `disable-model-invocation: true` 的 9 个技能。 */
const EXPECTED_MANUAL_ONLY = [
  'ce-dogfood', 'ce-polish', 'ce-product-pulse', 'ce-promote',
  'ce-retune', 'ce-setup', 'ce-sweep', 'ce-test-xcode', 'wtf',
];

test('provider 名字固定为 compound-engineering', () => {
  assert.equal(PROVIDER_NAME, 'compound-engineering');
  assert.equal(createProvider(skillsRoot, quietLogger).name, 'compound-engineering');
});

test('技能名单与上游 36 个完全一致', async () => {
  const names = (await createProvider(skillsRoot, quietLogger).list()).map((c) => c.name).sort();
  assert.equal(names.length, 36);
  assert.deepEqual(names, [...EXPECTED_NAMES].sort());
});

test('技能名全部符合 DSH 的 kebab-case 规范', async () => {
  const candidates = await createProvider(skillsRoot, quietLogger).list();
  for (const candidate of candidates) {
    assert.match(candidate.name, /^[a-z0-9]+(?:-[a-z0-9]+)*$/, candidate.name);
  }
});

test('每个候选都带齐 SkillCandidate 的必需字段', async () => {
  for (const candidate of await createProvider(skillsRoot, quietLogger).list()) {
    assert.equal(typeof candidate.rank, 'number', candidate.name);
    assert.ok(candidate.description.length > 0, candidate.name);
    assert.ok(candidate.locator, candidate.name);
    assert.equal(candidate.provider, 'compound-engineering', candidate.name);
    assert.equal(candidate.source, 'bundled', candidate.name);
    assert.equal(candidate.resourceBase?.kind, 'directory', candidate.name);
  }
});

test('打包分发的技能排在 600 档，可被用户目录覆盖', async () => {
  for (const candidate of await createProvider(skillsRoot, quietLogger).list()) {
    assert.equal(candidate.rank, 600, candidate.name);
  }
});

test('disable-model-invocation 精确映射到 9 个仅手动技能', async () => {
  const provider = createProvider(skillsRoot, quietLogger);
  const manual = [];
  for (const candidate of await provider.list()) {
    const definition = await provider.get(candidate);
    assert.equal(definition.invocation.userInvocable, true, candidate.name);
    if (!definition.invocation.modelInvocable) manual.push(candidate.name);
  }
  assert.deepEqual(manual.sort(), [...EXPECTED_MANUAL_ONLY].sort());
});

test('get() 返回正文与 resourceBase 目录', async () => {
  const provider = createProvider(skillsRoot, quietLogger);
  const candidate = (await provider.list()).find((c) => c.name === 'ce-compound');
  const definition = await provider.get(candidate);
  assert.ok(definition.content.length > 1000);
  assert.equal(definition.resourceBase.path, join(skillsRoot, 'ce-compound'));
  assert.ok(definition.content.includes('compound'));
});

test('argument-hint 与 allowed-tools 转成正文尾巴而非残留 frontmatter', async () => {
  const provider = createProvider(skillsRoot, quietLogger);
  const candidate = (await provider.list()).find((c) => c.name === 'ce-sweep');
  const definition = await provider.get(candidate);
  assert.doesNotMatch(definition.content, /^argument-hint:/m);
  assert.doesNotMatch(definition.content, /^allowed-tools:/m);
  assert.match(definition.content, /_Tools this skill expects the harness to work with:_/);
});

test('未知技能返回 undefined 而不是抛错', async () => {
  const provider = createProvider(skillsRoot, quietLogger);
  assert.equal(await provider.get({ name: 'no-such-skill', rank: 600, locator: null }), undefined);
});

test('目录不存在时返回空列表并记一条告警', async () => {
  const warnings = [];
  const provider = createProvider(join(root, 'no-such-directory'), {
    info() {},
    warn: (message) => warnings.push(message),
    debug() {},
  });
  assert.deepEqual(await provider.list(), []);
  assert.equal(warnings.length, 1);
});

test('缺少 description 的技能被跳过并告警', async () => {
  const scratch = mkdtempSync(join(tmpdir(), 'ce-provider-'));
  try {
    mkdirSync(join(scratch, 'good'));
    writeFileSync(join(scratch, 'good', 'SKILL.md'), '---\nname: good\ndescription: 正常\n---\n正文\n');
    mkdirSync(join(scratch, 'broken'));
    writeFileSync(join(scratch, 'broken', 'SKILL.md'), '---\nname: broken\n---\n正文\n');
    // 无 SKILL.md 的目录（例如共享资产目录）不应算作错误
    mkdirSync(join(scratch, 'assets'));

    const warnings = [];
    const provider = createProvider(scratch, { info() {}, warn: (m) => warnings.push(m), debug() {} });
    const names = (await provider.list()).map((c) => c.name);
    assert.deepEqual(names, ['good']);
    assert.equal(warnings.length, 1);
    assert.match(warnings[0], /broken: frontmatter has no non-empty description/);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test('frontmatter 缺 name 时回退到目录名', async () => {
  const scratch = mkdtempSync(join(tmpdir(), 'ce-provider-'));
  try {
    mkdirSync(join(scratch, 'fallback-name'));
    writeFileSync(join(scratch, 'fallback-name', 'SKILL.md'), '---\ndescription: 无 name\n---\n正文\n');
    const names = (await createProvider(scratch, quietLogger).list()).map((c) => c.name);
    assert.deepEqual(names, ['fallback-name']);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test('正文引用的 references/scripts/assets 资产全部随包分发', async () => {
  // 上游技能用「读 SKILL.md 记住其目录，再按相对路径读 references/xxx.md」
  // 的方式分层加载。只要引用的文件不在包里，模型读到那一行就会卡住，
  // 而且这种缺失在单测里不会自己暴露，所以逐个解析一遍。
  const provider = createProvider(skillsRoot, quietLogger);
  const missing = [];
  let total = 0;
  for (const candidate of await provider.list()) {
    const definition = await provider.get(candidate);
    const matches = definition.content.matchAll(
      /(?:^|[\s`(])((?:references|scripts|assets)\/[A-Za-z0-9._/-]+\.[A-Za-z0-9]+)/g,
    );
    for (const match of new Set([...matches].map((m) => m[1]))) {
      total += 1;
      if (!existsSync(join(definition.resourceBase.path, match))) {
        missing.push(`${candidate.name}: ${match}`);
      }
    }
  }
  assert.ok(total > 100, `应该解析出上百个资产引用，实际 ${total}`);
  assert.deepEqual(missing, [], `有资产没随包分发:\n${missing.join('\n')}`);
});
