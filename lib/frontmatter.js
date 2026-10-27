/**
 * 零依赖的 YAML frontmatter 解析器。
 *
 * 只覆盖 SKILL.md 实际使用的子集：顶层 `key: value` 标量、带引号字符串、
 * 布尔字面量、以及 `key:` 后跟缩进列表（`- item`）。
 *
 * 之所以不引入 js-yaml：本插件是纯技能包，除了自身以外不向 profile 注入任何
 * 运行时依赖，避免与宿主的 YAML 版本产生冲突。
 */

/** 单个值里允许出现的行内注释起始符（` #` 之后整段视为注释）。 */
const INLINE_COMMENT = /\s+#.*$/;

/**
 * 去掉值两端的引号并还原转义。
 * @param {string} raw 原始值文本
 * @returns {string} 处理后的字符串
 */
function unquote(raw) {
  const text = raw.trim();
  if (text.length >= 2) {
    const first = text[0];
    const last = text[text.length - 1];
    if (first === '"' && last === '"') {
      return text.slice(1, -1).replace(/\\(["\\/])/g, '$1').replace(/\\n/g, '\n');
    }
    if (first === "'" && last === "'") {
      return text.slice(1, -1).replace(/''/g, "'");
    }
  }
  return text;
}

/**
 * 把标量文本转成 JS 值：布尔、数字、字符串。
 * @param {string} raw 原始值文本
 * @returns {unknown} 解析结果
 */
function scalar(raw) {
  const text = raw.trim();
  if (text === '') return undefined;
  const bare = text.replace(INLINE_COMMENT, '').trim();
  if (/^(true|yes|on)$/i.test(bare)) return true;
  if (/^(false|no|off)$/i.test(bare)) return false;
  if (/^-?\d+$/.test(bare)) return Number(bare);
  return unquote(bare);
}

/**
 * 解析 frontmatter 文本块。
 * @param {string} block 位于两条 `---` 之间的文本
 * @returns {Record<string, unknown>} 解析出的键值对
 */
export function parseFrontmatterBlock(block) {
  const data = {};
  const lines = block.split('\n');
  let index = 0;
  while (index < lines.length) {
    const line = lines[index].replace(/\r$/, '');
    index += 1;
    if (line.trim() === '' || line.trimStart().startsWith('#')) continue;
    // 只认顶层键：缩进行属于上一个键的子结构，已在下面消费或忽略。
    if (/^\s/.test(line)) continue;
    const colon = line.indexOf(':');
    if (colon <= 0) continue;
    const key = line.slice(0, colon).trim();
    if (key === '') continue;
    const rest = line.slice(colon + 1);
    if (rest.trim() !== '') {
      data[key] = scalar(rest);
      continue;
    }
    // 值为空：可能是缩进列表或嵌套映射。
    const items = [];
    let nested = {};
    let hasNested = false;
    while (index < lines.length) {
      const next = lines[index].replace(/\r$/, '');
      if (next.trim() === '') {
        index += 1;
        continue;
      }
      if (!/^\s/.test(next)) break;
      index += 1;
      const trimmed = next.trim();
      if (trimmed.startsWith('- ') || trimmed === '-') {
        items.push(scalar(trimmed.slice(1)));
        continue;
      }
      const inner = trimmed.indexOf(':');
      if (inner > 0) {
        nested[trimmed.slice(0, inner).trim()] = scalar(trimmed.slice(inner + 1));
        hasNested = true;
      }
    }
    if (items.length > 0) data[key] = items;
    else if (hasNested) data[key] = nested;
    else data[key] = undefined;
  }
  return data;
}

/**
 * 从完整的 SKILL.md 文本里切出 frontmatter 与正文。
 * @param {string} raw 文件全文
 * @returns {{data: Record<string, unknown>, body: string} | undefined} 解析结果
 */
export function splitFrontmatter(raw) {
  const firstLineEnd = raw.indexOf('\n');
  if (firstLineEnd < 0) return undefined;
  if (raw.slice(0, firstLineEnd).replace(/\r$/, '') !== '---') return undefined;
  const start = firstLineEnd + 1;
  let lineStart = start;
  while (lineStart <= raw.length) {
    const nextNewline = raw.indexOf('\n', lineStart);
    const lineEnd = nextNewline < 0 ? raw.length : nextNewline;
    if (raw.slice(lineStart, lineEnd).replace(/\r$/, '') === '---') {
      const bodyStart = nextNewline < 0 ? raw.length : nextNewline + 1;
      return {
        data: parseFrontmatterBlock(raw.slice(start, lineStart)),
        body: raw.slice(bodyStart),
      };
    }
    if (nextNewline < 0) return undefined;
    lineStart = nextNewline + 1;
  }
  return undefined;
}

/**
 * 按 DSH 的规则把布尔 frontmatter 字段转成布尔值。
 * 与 `@deepseek-ai/dsh-skill-filesystem` 保持一致：接受布尔、1/0 与常见字符串拼写。
 * @param {Record<string, unknown>} data frontmatter 数据
 * @param {string} key 字段名
 * @returns {boolean | undefined} 解析结果
 */
export function booleanField(data, key) {
  if (!Object.hasOwn(data, key)) return undefined;
  const value = data[key];
  if (typeof value === 'boolean') return value;
  if (value === 1 || value === '1') return true;
  if (value === 0 || value === '0') return false;
  if (typeof value === 'string') {
    switch (value.toLowerCase()) {
      case 'true':
      case 'yes':
      case 'on':
        return true;
      case 'false':
      case 'no':
      case 'off':
        return false;
    }
  }
  return undefined;
}

/**
 * 取出非空字符串字段。
 * @param {Record<string, unknown>} data frontmatter 数据
 * @param {string} key 字段名
 * @returns {string | undefined} 字段值
 */
export function stringField(data, key) {
  const value = data[key];
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}
