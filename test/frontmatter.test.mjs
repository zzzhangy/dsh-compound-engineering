// frontmatter 解析器的单元测试。
//
// 这些用例直接对应 DSH 官方 `@deepseek-ai/dsh-skill-filesystem` 接受/拒绝的
// 形态：拼错布尔值必须让技能被丢弃，所以我们把“拒绝”也当成契约来测。
import assert from 'node:assert/strict';
import test from 'node:test';
import {
  booleanField,
  parseFrontmatterBlock,
  splitFrontmatter,
  stringField,
} from '../lib/frontmatter.js';

test('解析简单的键值对', () => {
  const data = parseFrontmatterBlock('name: ce-plan\ndescription: 制定计划\n');
  assert.equal(data.name, 'ce-plan');
  assert.equal(data.description, '制定计划');
});

test('去掉双引号并还原转义', () => {
  const data = parseFrontmatterBlock('description: "含 \\"引号\\" 与 \\n 换行"');
  assert.equal(data.description, '含 "引号" 与 \n 换行');
});

test('去掉单引号并还原双写', () => {
  const data = parseFrontmatterBlock("description: 'it''s fine'");
  assert.equal(data.description, "it's fine");
});

test('解析行内注释', () => {
  const data = parseFrontmatterBlock('description: hello  # 这是注释');
  assert.equal(data.description, 'hello');
});

test('布尔字面量转成布尔值', () => {
  const data = parseFrontmatterBlock('a: true\nb: false\nc: yes\nd: off\n');
  assert.equal(data.a, true);
  assert.equal(data.b, false);
  assert.equal(data.c, true);
  assert.equal(data.d, false);
});

test('数字字面量转成数字', () => {
  const data = parseFrontmatterBlock('rank: 600\nnegative: -3\n');
  assert.equal(data.rank, 600);
  assert.equal(data.negative, -3);
});

test('缩进列表', () => {
  const data = parseFrontmatterBlock('allowed-tools:\n  - Bash(gh *)\n  - Read\n');
  assert.deepEqual(data['allowed-tools'], ['Bash(gh *)', 'Read']);
});

test('缩进映射', () => {
  const data = parseFrontmatterBlock('metadata:\n  author: every\n  version: 3\n');
  assert.deepEqual(data.metadata, { author: 'every', version: 3 });
});

test('空值键保留为 undefined', () => {
  const data = parseFrontmatterBlock('name:\n');
  assert.ok(Object.hasOwn(data, 'name'));
  assert.equal(data.name, undefined);
});

test('忽略注释行与空行', () => {
  const data = parseFrontmatterBlock('# 开头注释\n\nname: x\n');
  assert.deepEqual(Object.keys(data), ['name']);
});

test('splitFrontmatter 切出正文', () => {
  const raw = '---\nname: x\ndescription: y\n---\n正文第一行\n第二行\n';
  const split = splitFrontmatter(raw);
  assert.equal(split.data.name, 'x');
  assert.equal(split.body, '正文第一行\n第二行\n');
});

test('splitFrontmatter 兼容 CRLF', () => {
  const raw = '---\r\nname: x\r\n---\r\n正文\r\n';
  const split = splitFrontmatter(raw);
  assert.equal(split.data.name, 'x');
  assert.equal(split.body, '正文\r\n');
});

test('splitFrontmatter 无 frontmatter 时返回 undefined', () => {
  assert.equal(splitFrontmatter('没有前置元数据\n'), undefined);
  assert.equal(splitFrontmatter('---\n没有结束分隔符\n'), undefined);
});

test('booleanField 接受多种拼写', () => {
  for (const raw of ['true', 'yes', 'on', '1', 'TRUE']) {
    assert.equal(booleanField({ flag: parseFrontmatterBlock(`flag: ${raw}`).flag }, 'flag'), true, raw);
  }
  for (const raw of ['false', 'no', 'off', '0', 'FALSE']) {
    assert.equal(booleanField({ flag: parseFrontmatterBlock(`flag: ${raw}`).flag }, 'flag'), false, raw);
  }
});

test('booleanField 对未识别值返回 undefined', () => {
  assert.equal(booleanField({ flag: 'maybe' }, 'flag'), undefined);
  assert.equal(booleanField({}, 'flag'), undefined);
});

test('stringField 只接受非空字符串', () => {
  assert.equal(stringField({ a: 'x' }, 'a'), 'x');
  assert.equal(stringField({ a: '' }, 'a'), undefined);
  assert.equal(stringField({ a: 3 }, 'a'), undefined);
  assert.equal(stringField({}, 'a'), undefined);
});
