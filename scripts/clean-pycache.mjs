// 发布前清理 Python 缓存，防止 __pycache__/*.pyc 混进 tarball。
//
// 为什么必须在这里做：package.json 的 files 白名单里写了整个 "skills" 目录，
// 而 npm 的规则是 —— 目录一旦被 files 收录，其中的 .npmignore 与 .gitignore
// 都不再参与过滤（实测：根目录 .npmignore 写了 **/__pycache__/ 也拦不住）。
// 因此唯一可靠的做法是在 npm pack 之前把文件从磁盘上删掉。
//
// 由 prepack 钩子调用：npm pack / npm publish 时自动执行。
import { readdir, rm } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
/** 不扫描的目录：体积大、且本来就不在发布范围内。 */
const SKIP = new Set(['node_modules', '.git']);

/** 递归删除目录下所有 __pycache__，返回删除数量。 */
async function sweep(dir, removed) {
  let entries;
  try {
    entries = await readdir(dir, { withFileTypes: true });
  } catch {
    return removed;
  }
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const full = join(dir, entry.name);
    if (entry.name === '__pycache__') {
      await rm(full, { recursive: true, force: true });
      removed.push(full);
      continue;
    }
    if (SKIP.has(entry.name)) continue;
    await sweep(full, removed);
  }
  return removed;
}

const removed = await sweep(root, []);
if (removed.length === 0) {
  console.log('prepack: 没有需要清理的 __pycache__');
} else {
  console.log(`prepack: 清理了 ${removed.length} 个 __pycache__ 目录`);
  for (const dir of removed) console.log(`  - ${dir.slice(root.length + 1)}`);
}
