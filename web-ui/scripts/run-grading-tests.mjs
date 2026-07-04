/**
 * 把评级测试入口打包成单文件 JS，再用 node:test 跑。
 *
 * 项目未引入 vitest/jest，临时用 rolldown（vite 自带依赖）打包，
 * 避免 Node 原生 strip-types 对 ESM 无后缀 import 的限制。
 *
 * 运行：node scripts/run-grading-tests.mjs
 */

import { build } from 'rolldown'
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const tmpDir = mkdtempSync(join(tmpdir(), 'grading-tests-'))
const bundlePath = join(tmpDir, 'bundle.mjs')

// 入口：导入测试文件，触发 node:test 注册
const entryPath = join(tmpDir, 'entry.mjs')
writeFileSync(
  entryPath,
  `import '${resolve('src/grading/__tests__/grade.test.ts').replace(/\\/g, '/')}'\n`,
)

console.log('→ 打包中…')
try {
  await build({
    input: entryPath,
    output: {
      file: bundlePath,
      format: 'esm',
    },
    // 顶层 await / dynamic import 都 OK
    platform: 'node',
    // 不外部化 node 内置
    external: ['node:test', 'node:assert', 'node:assert/strict', 'node:os', 'node:fs', 'node:path', 'node:child_process'],
    // 强制把测试文件和 grading 模块都打进 bundle
    treeshake: false,
  })
} catch (e) {
  console.error('打包失败:', e)
  process.exit(1)
}

console.log('→ 运行测试…')
const r = spawnSync('node', ['--test', bundlePath], { stdio: 'inherit' })

rmSync(tmpDir, { recursive: true, force: true })
process.exit(r.status ?? 0)
