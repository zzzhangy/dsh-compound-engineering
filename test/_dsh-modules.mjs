// 定位并加载 DSH 自己的 @deepseek-ai/cordis 与 @deepseek-ai/dsh-skill。
//
// 插件本身不依赖这两个包（它们在 DSH 宿主里由内核提供），所以测试必须
// 自己去宿主安装目录里找。查找顺序：
//   1. 直接按包名 import —— 从 profile 目录跑测试时通常能命中；
//   2. DSH_RUNTIME 环境变量指向的 runtime 目录；
//   3. 逐个扫描 ~/.dsh/runtime/versions/*/node_modules/.pnpm 下的 pnpm 布局。
import { existsSync, readdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const PACKAGES = {
  cordis: { scope: '@deepseek-ai', name: 'cordis', entry: 'lib/index.js' },
  skill: { scope: '@deepseek-ai', name: 'dsh-skill', entry: 'lib/index.js' },
};

/** 从 pnpm 虚拟仓库里按前缀找出包的真实目录。 */
function findInPnpm(pnpmDir, { scope, name, entry }) {
  if (!existsSync(pnpmDir)) return null;
  const prefix = `${scope.replace('/', '+')}+${name}@`;
  let candidates;
  try {
    candidates = readdirSync(pnpmDir).filter((d) => d.startsWith(prefix));
  } catch {
    return null;
  }
  for (const dir of candidates.sort().reverse()) {
    const entryPath = join(pnpmDir, dir, 'node_modules', scope, name, entry);
    if (existsSync(entryPath)) return entryPath;
  }
  return null;
}

/** 遍历所有已安装的 DSH runtime，返回第一个找到的入口文件。 */
function findInRuntimes(spec) {
  const versionsRoot = join(homedir(), '.dsh', 'runtime', 'versions');
  if (!existsSync(versionsRoot)) return null;
  const runtimes = [];
  if (process.env.DSH_RUNTIME) runtimes.push(process.env.DSH_RUNTIME);
  try {
    for (const version of readdirSync(versionsRoot).sort().reverse()) {
      runtimes.push(join(versionsRoot, version, 'node_modules'));
    }
  } catch {
    /* ignore */
  }
  for (const nodeModules of runtimes) {
    const found = findInPnpm(join(nodeModules, '.pnpm'), spec);
    if (found) return found;
  }
  return null;
}

async function load(spec) {
  try {
    return await import(`${spec.scope}/${spec.name}`);
  } catch {
    /* 宿主外跑测试时按包名 import 会失败，继续往下找 */
  }
  const entryPath = findInRuntimes(spec);
  if (!entryPath) {
    throw new Error(
      `找不到 ${spec.scope}/${spec.name}。请从 DSH profile 目录运行测试，` +
        `或用 DSH_RUNTIME=<runtime 的 node_modules 目录> 指定安装位置。`,
    );
  }
  return import(pathToFileURL(entryPath).href);
}

export const loadCordis = () => load(PACKAGES.cordis);
export const loadDshSkill = () => load(PACKAGES.skill);

/**
 * 建一个挂了 SkillRegistry 的 cordis Context。
 *
 * SkillRegistry 是 cordis Service，直接 new 会因为缺少 ctx.reflect 而崩，
 * 必须通过 app.plugin() 挂载后才拿得到 fiber。
 */
export async function createSkillRegistry() {
  const { Context } = await loadCordis();
  const { SkillRegistry } = await loadDshSkill();
  const app = new Context();
  app.plugin(SkillRegistry);
  await app.start?.();
  if (!app.skills) throw new Error('skills 服务未挂载');
  return { app, registry: app.skills };
}
