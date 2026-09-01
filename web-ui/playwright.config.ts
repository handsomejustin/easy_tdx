// Playwright E2E 配置：mock 模式的 easy-tdx serve + 已构建的前端 dist。
//
// 运行前置：
//   1. `npm run build`（serve 从仓库根 web-ui/dist 托管前端，SPA fallback）；
//   2. 后端可用（仓库根 `pip install -e ".[web]"`）——自动探测仓库 .venv，
//      否则可用 EASY_TDX_PYTHON 指定解释器（CI 里是 `python`）。
//
// 行情全部来自合成数据（EASY_TDX_E2E_MOCK=1，见 src/easy_tdx/web/e2e_mock.py），
// 不连真实通达信服务器、不受交易时段限制；回测/WF/评估/自选/策略库走真实后端。
// 详见 e2e/README.md。

import { existsSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig } from '@playwright/test'

const PORT = Number(process.env.E2E_PORT ?? 8001)
const BASE_URL = `http://127.0.0.1:${PORT}`
const WEB_UI_DIR = path.dirname(fileURLToPath(import.meta.url))

/** 启动 serve 的 Python 解释器：优先仓库 .venv（开发态 editable 安装），
 *  没有则回退 EASY_TDX_PYTHON / 系统 python（CI 态 pip install -e 之后）。 */
function resolvePython(): string {
  const repoRoot = path.resolve(WEB_UI_DIR, '..')
  if (existsSync(path.join(repoRoot, '.venv/Scripts/python.exe'))) {
    return path.join(repoRoot, '.venv/Scripts/python.exe')
  }
  if (existsSync(path.join(repoRoot, '.venv/bin/python'))) {
    return path.join(repoRoot, '.venv/bin/python')
  }
  return process.env.EASY_TDX_PYTHON ?? 'python'
}

// 每次运行独立的临时配置目录：watchlist.db / strategies.db / tasks.db 写在这里，
// 不污染真实 ~/.easy_tdx，且每轮 E2E 从空自选、空策略库开始（断言可写死）。
const RUNTIME_CONFIG_DIR = mkdtempSync(path.join(tmpdir(), 'easy-tdx-e2e-'))

export default defineConfig({
  testDir: './e2e',
  timeout: 180_000,
  // 单 worker 串行：全部用例共享同一个 serve（SQLite 自选/策略库会互相干扰）
  workers: 1,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL: BASE_URL,
    headless: true,
    locale: 'zh-CN',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    actionTimeout: 15_000,
  },
  expect: {
    timeout: 20_000,
  },
  outputDir: './e2e/.results',
  webServer: {
    command: `${resolvePython()} -m easy_tdx serve --host 127.0.0.1 --port ${PORT} --no-open-browser`,
    url: `${BASE_URL}/api/v1/backtest/strategies`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      EASY_TDX_E2E_MOCK: '1',
      EASY_TDX_CONFIG_DIR: RUNTIME_CONFIG_DIR,
    },
  },
})
