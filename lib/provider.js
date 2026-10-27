/**
 * 把随包分发的 `skills/` 目录暴露为一个 DSH 技能 provider。
 *
 * 每个技能目录是 `<skills>/<name>/SKILL.md`，正文里的 `references/xxx.md`、
 * `scripts/xxx.py` 等相对路径由 DSH 依据 `resourceBase` 解析，因此不需要改写
 * 上游的任何交叉引用。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { splitFrontmatter, booleanField, stringField } from './frontmatter.js';

/**
 * provider 在技能注册表里用的名字。
 * 注册表要求同层同名唯一，且 `runtime` 是保留名。
 */
export const PROVIDER_NAME = 'compound-engineering';

/**
 * 包里技能的统一优先级。
 *
 * 与 `BUNDLED_SKILL_RANK`（600）取同一档：社区里打包分发的技能默认都排在
 * 600，于是用户自己的 `.dsh/skills`（400）、`.agents/skills`（500）以及项目级
 * 目录（100/200）都能原地覆盖同名技能，而不用先卸插件。
 */
const SKILL_RANK = 600;

/** 技能入口文件名。 */
const SKILL_FILE = 'SKILL.md';

/**
 * 把可选的 `argument-hint` 补进正文尾部。
 *
 * DSH 的技能记录没有承载「命令参数提示」的字段，而模型读到正文时知道该技能
 * 期待什么参数是有用的（用户只敲了 `/ce-plan` 时可以先追问）。放在尾部而不是
 * 开头，避免打乱上游正文首段的标题结构。
 * @param body 技能正文
 * @param hint `argument-hint` 原文
 * @returns 补齐后的正文
 */
function appendArgumentHint(body, hint) {
  return `${body.replace(/\s+$/, '')}\n\n---\n\n_Argument hint: ${hint}_\n`;
}

/**
 * 把可选的 `allowed-tools` 补进正文尾部，让模型知道该技能预期的工具面。
 * @param body 技能正文
 * @param tools `allowed-tools` 列表
 * @returns 补齐后的正文
 */
function appendAllowedTools(body, tools) {
  const list = tools.map((tool) => `- \`${String(tool)}\``).join('\n');
  return `${body.replace(/\s+$/, '')}\n\n---\n\n_Tools this skill expects the harness to work with:_\n\n${list}\n`;
}

/**
 * 把一个 SKILL.md 解析成 DSH 的技能摘要与正文。
 * @param directory 技能目录绝对路径
 * @param directoryName 目录名（frontmatter 缺 name 时作为技能名）
 * @returns 解析结果；缺少必需字段时返回 `error` 描述
 */
function readSkill(directory, directoryName) {
  const file = join(directory, SKILL_FILE);
  let raw;
  try {
    raw = readFileSync(file, 'utf8');
  } catch (error) {
    return { error: `cannot read ${SKILL_FILE}: ${error instanceof Error ? error.message : String(error)}` };
  }
  const parsed = splitFrontmatter(raw);
  if (parsed === undefined) {
    return { error: 'missing or unterminated YAML frontmatter' };
  }
  const { data, body } = parsed;
  // 上游全部 36 个技能的 name 与目录名一致；万一以后不一致，以 frontmatter
  // 为准，因为那才是作者用来寻址的名字。
  const name = stringField(data, 'name') ?? directoryName;
  const description = stringField(data, 'description');
  if (description === undefined) {
    return { error: 'frontmatter has no non-empty description' };
  }
  const disableModelInvocation = booleanField(data, 'disable-model-invocation');
  const userInvocable = booleanField(data, 'user-invocable');
  const argumentHint = stringField(data, 'argument-hint');
  const allowedTools = Array.isArray(data['allowed-tools']) ? data['allowed-tools'] : undefined;

  let content = body;
  if (argumentHint !== undefined) content = appendArgumentHint(content, argumentHint);
  if (allowedTools !== undefined) content = appendAllowedTools(content, allowedTools);

  return {
    summary: {
      path: file,
      name,
      description,
      invocation: {
        // `disable-model-invocation: true` 在 DSH 上表现为「不进模型目录，
        // 只能由用户显式 /<name> 触达」，与上游语义逐字对应。
        modelInvocable: disableModelInvocation !== true,
        // 上游没有等价的「禁止用户触发」字段，缺省即可被用户调用。
        userInvocable: userInvocable !== false,
      },
      source: 'bundled',
      provider: PROVIDER_NAME,
      resourceBase: { kind: 'directory', path: directory },
    },
    content,
  };
}

/**
 * 扫描技能根目录，返回全部候选。
 * @param skillsRoot 技能根目录绝对路径
 * @param signal 取消信号
 * @returns 候选列表与告警
 */
function scanSkills(skillsRoot, signal) {
  const candidates = [];
  const warnings = [];
  let entries;
  try {
    entries = readdirSync(skillsRoot, { withFileTypes: true });
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    return { candidates, warnings: [`skills directory unavailable: ${reason}`] };
  }
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    if (signal?.aborted === true) break;
    if (!entry.isDirectory()) continue;
    const directory = join(skillsRoot, entry.name);
    try {
      if (!statSync(join(directory, SKILL_FILE)).isFile()) continue;
    } catch {
      // 目录里没有 SKILL.md：不是技能包（例如只放共享资产的目录）。
      continue;
    }
    const skill = readSkill(directory, entry.name);
    if (skill.error !== undefined) {
      warnings.push(`${entry.name}: ${skill.error}`);
      continue;
    }
    candidates.push({
      summary: skill.summary,
      candidate: {
        ...skill.summary,
        rank: SKILL_RANK,
        locator: { file: skill.summary.path },
      },
      content: skill.content,
    });
  }
  return { candidates, warnings };
}

/**
 * 构造一个 skill provider 实例。
 *
 * 技能随包分发、运行期不会变化，因此目录只扫描一次并常驻内存：36 个技能
 * 合计约 200KB 正文，相对于每次请求节省的 I/O 完全可以接受。
 * @param skillsRoot 技能根目录绝对路径
 * @param logger 宿主 logger，可为 undefined
 * @returns 满足 `SkillProvider` 契约的对象
 */
export function createProvider(skillsRoot, logger) {
  /** @type {ReturnType<typeof scanSkills> | undefined} */
  let scanned;
  const byName = new Map();

  /** 惰性扫描并缓存。 */
  function catalog(signal) {
    if (scanned === undefined) {
      scanned = scanSkills(skillsRoot, signal);
      for (const warning of scanned.warnings) {
        logger?.warn(`[${PROVIDER_NAME}] ${warning}`);
      }
      for (const item of scanned.candidates) byName.set(item.summary.name, item);
    }
    return scanned.candidates;
  }

  return {
    name: PROVIDER_NAME,
    /**
     * 列出全部技能摘要。
     * @param options 查找选项；本 provider 的目录不随 cwd 变化
     * @returns 候选数组
     */
    async list(options = {}) {
      return catalog(options.signal).map((item) => item.candidate);
    },
    /**
     * 载入某个技能的正文。
     * @param candidate `list()` 返回的候选
     * @returns 完整技能定义；技能已不可读时返回 undefined
     */
    async get(candidate) {
      const item = byName.get(candidate.name);
      if (item === undefined) return undefined;
      return { ...item.summary, content: item.content };
    },
  };
}
