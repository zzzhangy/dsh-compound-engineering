/**
 * `dsh-compound-engineering`: 把 Every 的 compound-engineering 技能包移植进
 * DeepSeek Harness。
 *
 * 插件本身没有存储、没有工具、没有 Web 界面——只做一件事：把随包分发的
 * 36 个技能注册进 `ctx.skills`。所有行为都由技能正文驱动，因此未来的技能
 * 更新只需要替换 `skills/` 目录，不必改动这份宿主代码。
 */
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createProvider, PROVIDER_NAME } from './provider.js';

/** 插件在 cordis 组合里的名字。 */
export const name = 'compound-engineering';

/**
 * 依赖的技能注册表服务。
 *
 * 声明 `inject` 让 cordis 等技能服务就绪后再调用 `apply()`，插件被装到
 * 一个没有技能子系统的宿主上时会安静地不生效，而不是抛错。
 */
export const inject = ['skills'];

/** 技能目录相对包根的位置。 */
const SKILLS_SUBDIRECTORY = 'skills';

/** 由 `lib/index.js` 回推包根目录。 */
const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)));

/**
 * 把技能包挂到宿主上。
 * @param ctx 宿主上下文
 */
export function apply(ctx) {
  const skillsRoot = join(packageRoot, SKILLS_SUBDIRECTORY);
  const logger = {
    warn: (message) => ctx.logger.warn(message),
    info: (message) => ctx.logger.info(message),
  };
  // 返回的 disposer 由 `registerProvider` 自己挂成 cordis effect，无需再包一层。
  // `control.invalidate` 本插件用不到：技能是随包分发的静态文件，进程内不变。
  ctx.skills.registerProvider(() => createProvider(skillsRoot, logger));
  ctx.logger.info(`[${PROVIDER_NAME}] serving skills from ${skillsRoot}`);
}

export { PROVIDER_NAME };
