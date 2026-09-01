# easy-tdx Web UI — Playwright E2E

无头浏览器端到端测试，覆盖：市场看板（五大指数 SSE）、自选增删、回测全流程
（取行情→净值图→绩效表→成交记录）、「附加分析」开关（WF 逐窗柱状图 + 一条龙
评估卡）、策略库保存。

## Mock 方案：后端合成数据（EASY_TDX_E2E_MOCK=1），不是 page.route 拦截

两种可行路径的取舍：

| | 后端 mock（已选） | Playwright `page.route` 拦截 |
|---|---|---|
| 回测/WF/评估/自选/策略库 | **走真实后端代码**，schema 变更会被 E2E 捕获 | 静态 JSON，会与后端 schema 漂移 |
| SSE `/stream/quotes`（EventSource） | QuoteStreamer 真轮询合成数据，SSE 全链路被覆盖 | 无法稳定 mock（需流式 body） |
| 任务型端点（提交→轮询→done） | 天然支持 | 要手写状态机 |
| 代价 | 后端多一个 `src/easy_tdx/web/e2e_mock.py`（约 400 行，由单测守护契约） | 无后端改动 |

实现：`playwright.config.ts` 的 `webServer` 以 `EASY_TDX_E2E_MOCK=1` 启动
`easy-tdx serve --port 8001`，lifespan 把 TDX/MAC 客户端替换为合成数据客户端
（确定性随机游走、按 (market, code) 播种，逐轮结果完全一致）。
`EASY_TDX_CONFIG_DIR` 指向每轮独立的临时目录——自选/策略库/任务从空开始，
断言可以写死，也不污染真实 `~/.easy_tdx`。

## 本地跑法

```bash
# 仓库根（Python 侧，一次性）
pip install -e ".[web]"          # fastapi + uvicorn

cd web-ui
npm install
npx playwright install chromium  # 首次下载浏览器（约 115MB）
npm run build                    # 必须：serve 从 ../web-ui/dist 托管前端
npm run test:e2e                 # = npx playwright test（无头）
```

- Python 解释器自动探测仓库 `.venv`；没有 `.venv` 时用 `EASY_TDX_PYTHON`
  环境变量指定（CI 里是系统 `python`）。
- 调试：`npx playwright test --headed`，或 `--ui` 打开交互式运行器；
  失败时自动留 trace/截图在 `e2e/.results/`（已 gitignore）。
- 想复用已启动的 serve：直接跑即可（`reuseExistingServer`，本地非 CI 默认开），
  但注意该 serve 必须带 `EASY_TDX_E2E_MOCK=1` 才有合成行情。

## CI

`.github/workflows/ci.yml` 的 `frontend` job 在 typecheck+build 后追加：
安装 Python + `pip install -e ".[web]"` → `npx playwright install chromium` →
`npm run test:e2e`（mock 模式，不需要任何真实行情连接）。

## 用例清单

| 文件 | 覆盖 |
|---|---|
| `dashboard.spec.ts` | 五大指数区块渲染 + SSE 首帧价格 + 市场统计卡 |
| `watchlist.spec.ts` | 自选加入（含名称补全）/删除/空态 |
| `backtest.spec.ts` | 策略下拉 + 回测全流程 + WF 柱状图 + 一条龙评估卡 |
| `strategies.spec.ts` | 保存策略对话框 + 策略库页可见 |
