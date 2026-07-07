# 更新日志

本文件记录 easy-tdx 的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/)。

## [1.19.1] — 2026-07-07

**支持打包成单一 Windows EXE + GitHub Actions 自动发版** —— 面向"一点都不懂的老年"用户群，让 easy-tdx 能从"开发者双进程"形态变成"双击 EXE → 浏览器自动打开 → 看到回测界面"的零门槛形态。本版为 Phase 1（未签名自测版）；Phase 2 引入代码签名消除 SmartScreen 提示，Phase 3 加 macOS。

### 新增

- **后端同源托管前端 dist**（`src/easy_tdx/web/app.py`）—— `_resolve_web_dist_dir()` 三级探测（环境变量 → PyInstaller `_MEIPASS/web_dist` → 仓库根 `web-ui/dist`），在所有 API 路由注册后 `app.mount("/", StaticFiles(..., html=True))`。开发态可缺省（仅 API），打包态同源服务前端。**前置条件**：此前前端 Vite 单独跑、靠 CORS 跨端口，老人无法双进程操作；现单进程同源解决。
- **`--open-browser` 启动选项**（`src/easy_tdx/cli/cmd_web.py`）—— uvicorn 启动后 `threading.Timer(1.5, ...)` 延迟开浏览器（等端口就绪），默认开、`--no-open-browser` 关闭、`--reload` 模式禁用（开发态不抢焦点）。
- **PyInstaller 打包入口**（`src/easy_tdx/__main__.py` + `easy_tdx.spec`）—— `python -m easy_tdx` 等价 CLI；无参数时默认走 `serve`。`.spec` 用 `--onefile` + `console=False`（无黑窗）+ `collect_submodules('uvicorn' / 'easy_tdx')` 收集动态 import + 前端 dist 打到 `web_dist`。
- **GitHub Actions 发版工作流**（`.github/workflows/release.yml`）—— `v*` tag 触发，`windows-latest` 构建前端 + EXE，重命名为 `easy-tdx-<版本>-windows.exe`，`softprops/action-gh-release` 上传。与 `publish.yml`（PyPI）完全独立并行，PyPI 失败不影响 EXE 发布。
- **系统托盘图标**（`src/easy_tdx/tray.py`）—— 打包态双击 EXE 后右下角任务栏出现 K 线风格图标，右键"打开浏览器 / 退出"可干净关闭，老人无需学任务管理器。
- **打包使用文档**（`docs/packaging.md`）—— 老人下载/运行/绕过 SmartScreen 图文说明 + 开发者本地构建步骤 + Phase 1/2/3 路线图。

### 已知约束（非 bug）

- **EXE 未签名，SmartScreen 会拦截** —— 老人首次运行需手动"更多信息 → 仍要运行"。这是 Phase 1 的明确取舍，Phase 2 引入 OV/EV 代码签名证书后消除。
- **EXE 体积 80-150MB** —— pandas/numpy/uvicorn/Vue dist 全量打包的必然结果。`--onefile` 首次启动解压需 2-5 秒。
- **离线 .day 读取需要通达信** —— 老人若未安装 Windows 版通达信，离线读取本地数据功能不可用；在线行情不受影响。

### 文档

- **README + 上手手册大改** —— 删除"两个终端 + npm run dev + 5173"的过时流程，改为三档分流：① 下载 EXE（零基础首选）② 装 Python 一条命令启动（会点电脑的）③ 源码运行 + 自己打包（开发者）。手册补虚拟环境配置、EXE 打包附录、EXE 排错 FAQ。

## [1.18.3] — 2026-07-06

**K 线响应截断容错 + 一键寻优并发默认值优化** —— 两个小修复合并发布。(1) 修复 `000408` 等标的请求 `count=800` 日线时，TDX 服务端返回截断响应（响应头声称有数据但 body 末尾若干条记录被切掉）导致整页 500 的问题：解析器现在丢弃残缺的末条记录，返回已成功解析的前 N-1 条，避免一条坏数据让整页请求失败。(2) 一键寻优并发默认值从「串行」改为「8 进程」，并把用户选择持久化到 `localStorage`，下次以其最后一次选择为默认。

### 修复

- **K 线响应截断容错**（`src/easy_tdx/commands/security_bars.py`）—— `GetSecurityBarsCmd` / `GetIndexBarsCmd` 的 `parse_response` 在逐条解析时，若某条记录的 datetime/price/volume 字段因数据不足抛 `TdxDecodeError`，改为丢弃残缺的末条并返回已成功解析的前若干条（记 warning 日志），而非整体抛 500。仅当连第一条都无法解析时才继续抛错（说明是真正的坏包而非尾部截断）。覆盖日线/分钟线/指数 K 线全部分支。

### 变更

- **一键寻优并发默认 8 进程 + 持久化**（`web-ui/src/views/OptimizeView.vue`）—— 「一键寻优并发」工作进程默认值从串行（0）改为 8 进程；用户修改后写入 `localStorage`（key `optimize.workers`），下次打开以其最后一次选择为默认。无历史记录或值非法时回退默认 8；`localStorage` 不可用时（隐私模式等）静默回退，不影响使用。

## [1.18.2] — 2026-07-06

**回退拼音声母搜索功能，回到稳定的 6 位代码输入** —— v1.19.0 引入的拼音声母搜索（输 `zjxc` 命中中际旭创）因底层依赖过重被移除。该功能首次使用时需从通达信服务器爬取沪深 A 股约 5000 条完整名单（几十次协议往返，慢机器耗时几十秒到超时），且与共享的 TDX 连接耦合——爬名单期间会阻塞行情请求。虽经多轮优化（按需加载 / 全站遮罩 / 单飞去重 / 后台预热），均无法兼顾"不阻塞核心行情"与"首次可用"。本次回到 v1.18.1 的干净基线，代码输入框恢复为纯 6 位代码输入（市场自动识别）。

### 变更

- **移除拼音声母搜索** —— 删除 `StockSearchInput` / `AppInitOverlay` / `useStockSearch` 三个组件与 composable，移除 `pypinyin` 依赖、`/security/search-index` 端点、lifespan 启动预热。`SymbolPicker` / `StocksPicker` 恢复为纯 6 位代码输入框。

### 已知约束（非 bug）

- **代码输入只支持 6 位数字** —— 不支持拼音/名字搜索。这是有意为之的取舍：避免引入需实时爬全名单的重依赖。如未来重做，应将股票名单做成独立本地数据库（用离线命令定期更新），搜索只查本地，不依赖实时爬 TDX。

## [1.18.1] — 2026-07-06

**Web UI 一键寻优多进程并发 + 策略库组合评级 + 市场前缀纠正** —— 两个独立主题合并发布。(1) 「一键寻优所有策略」此前串行跑 17 个策略的预设网格（共约 182 个网格点），在中大型机器上动辄几十秒到几分钟。本次引入 `ProcessPoolExecutor` 多进程并发，配置区新增并发数选择器（串行 / 4 / 8 / 16 进程，自动检测 CPU 核数并标注推荐档），实测 8 进程可提速 4-6×。**关键认知**：回测是 numpy/pandas 的 CPU 密集计算并持有 GIL，多线程无加速，必须用多进程；照搬项目里已跑通的 `screen/scanner.py` 进程池模板。(2) 策略库「组合回测」结果区补上组合评级徽章（与单标的回测/组合页同口径的 5 维度评分），同时修复历史保存策略的市场前缀错配（5 开头的沪市基金/ETF 曾被误判为深市）。

### 新增

- **一键寻优多进程并发**（`src/easy_tdx/web/routers/backtest.py` + `backtest_schemas.py`）—— `OptimizeAllBacktestRequest` 新增 `workers` 字段（默认 1=串行，范围 0-32）。抽出模块顶层函数 `_optimize_one_strategy`（可被 `ProcessPoolExecutor` pickle），`_run_optimize_all` 在 `workers >= 2` 时用进程池并行寻优，`workers` 为 0 或 1 时走原串行逻辑（向后兼容）。进程池在函数内 `with` 创建/销毁，对前端轮询与 `task_runner` 透明。
- **并发数选择器**（`web-ui/src/views/OptimizeView.vue`）—— 配置区新增「一键寻优并发」区：自动检测 CPU 核数（`navigator.hardwareConcurrency`）+ 串行/4/8/16 进程下拉，默认串行，标注推荐档（`min(CPU, 8)`）。默认串行的考量：Windows spawn 启动开销大，小机器上多进程可能反而更慢，让用户先实测再开并发。
- **策略库组合评级**（`web-ui/src/views/StrategiesView.vue`）—— 组合回测结果区新增「组合评级」详情块，从 `combined_equity` 重算夏普/卡玛/回撤/波动率等 5 维度评分，复用 `gradePortfolio`（与 `/portfolio` 页和单标的回测页同口径），让用户一眼判断这个组合该不该经常参与。

### 变更

- **市场前缀判断统一**（`web-ui/src/views/BacktestView.vue` + `StrategiesView.vue`）—— `BacktestView.fullSymbol` 此前硬编码规则（6/9 开头 SH，8/4 开头 BJ，其余 SZ），漏判 5 开头的沪市基金/ETF（如 `515030` 被误判为 SZ）。改为复用 `market.ts` 的 `detectMarket`（与 `SymbolPicker` / `StocksPicker` 同一套规则）。`StrategiesView` 新增 `normalizeSymbol`，在发请求前重算历史保存策略的市场前缀，纠正历史数据 + 兜底未来。
- **`backtest_schemas.py` 代码风格** —— 修复 `SavedStrategyCreate.kind` 字段描述行超过 ruff 100 字符上限（E501）的历史遗留。

### 已知约束（非 bug）

- **并发默认串行** —— 多进程在 Windows 上 spawn 子进程有启动开销，CPU 核数少的机器开并发可能反而更慢。因此 UI 默认选串行，让用户先用同一标的、串行 vs 并行各跑一次对比耗时，再决定是否开并发。
- **并发仅对「一键寻优所有策略」生效** —— 单策略寻优（`/backtest/optimize/run/async`）内部网格点也可并行，但收益小、复杂度高，本次未做。

## [1.18.0] — 2026-07-05

**Web UI 策略库新增「策略组合」保存能力 + 分类 Tab** —— 此前用户在策略库勾选多个单标的策略做组合回测，跑出满意结果后却**无法保存**这个组合，下次要重新勾选重新跑。更关键的是，用户真正的诉求是「下次打开就知道哪些该买、哪些该卖」——这本质是要**截至今天的策略信号**，而非静态存档。本次落地：在策略库融入 `kind: 'multi'` 类型，组合回测结果区加「💾 保存为组合」按钮，组合卡片「↻ 重跑到今天」一键用今天作为结束日重跑，跑出来的"当前持仓"就是截至今天的策略信号（持仓/空仓/浮盈/浮亏）。同时把策略库拆成「单标的」/「组合」两个 Tab，避免数量多了之后混排难找。

### 新增

- **策略组合保存**（`web-ui/src/views/StrategiesView.vue` + 后端 schema 扩展）—— 组合回测结果区右上「💾 保存为组合」橙色按钮，弹窗输入名称 + 备注。存为 `kind: 'multi'`，`context.items` 存完整 `MultiStrategyItem[]`（各策略的 strategy+params+symbol+日期），`snapshot` 存组合级绩效（总收益/年化/策略数/资金）。复用现有 SQLite 单表（`kind` 字段本就是 TEXT），**零数据库迁移，零后端逻辑改动**。
- **载入即重跑到今天** —— multi 卡片按钮不是普通「载入」而是「↻ 重跑到今天」：confirm 后自动把 `end_date` 全部覆盖为今天，触发组合回测，跑完滚动到结果区。这样"当前持仓"表 = 截至今天的策略信号，直接回答用户「哪些该买该卖」。
- **持仓三态高亮** —— 当前持仓表的状态徽章从两态（持仓/空仓）升级为三态：🟢 **持有**（浮盈，绿底）/ 🟠 **持有·浮亏**（橙底，提示注意止损）/ ⚪ **空仓·等买点**（灰底，行半透明）。让用户一眼分辨"该继续拿"还是"该警惕"。
- **策略库 Tab 分类** —— 顶部新增「单标的 [N]」/「组合 [N]」两个 Tab（带计数徽章 + 蓝色下划线 active 指示），切换时清空勾选避免跨 Tab 残留。「组合回测」按钮仅在单标的 Tab 显示（组合策略无法再被组合）；空态文案按 Tab 分别引导。
- **过拟合警示 + 模型仓位免责** —— 组合回测结果区顶部橙色警示条明确告知「历史回测优秀 ≠ 未来一定有效，收益可能来自特定时段市场环境」；持仓表上方水印标注「表中是**模型仓位**，不是你真实账户的持仓，过夜后可能因新 K 线触发买卖而变化」。载入组合的 confirm 弹窗也提示策略信号非投资建议。
- **保存组合弹窗 A11y** —— `role="dialog"` + `aria-modal="true"` + `aria-labelledby`，ESC 关闭，打开时自动 focus 到名称输入框。

### 变更

- **后端 schema kind 扩展**（`src/easy_tdx/web/backtest_schemas.py`）—— `SavedStrategyCreate.kind` / `SavedStrategy.kind` 的 `Literal` 由 `["single", "portfolio"]` 扩展为 `["single", "portfolio", "multi"]`。前端 `web-ui/src/types.ts` 镜像同步。
- **卡片 Badge 细化** —— multi 显示「多策略」橙色徽章 + 🗂 图标 + 橙色卡片边框；portfolio 显示「多标的」紫色徽章。两类组合在「组合」Tab 内可一眼区分。
- **代码审计修复（10 项）** —— 修复 `multi-icon` 误用未引入的 Material Icons 字体导致显示英文文本；补齐 `onComboBacktest` 漏写的 `lastComboCash`；持仓三态计算收敛为 `holdingViews` computed（避免模板每行 3 次函数调用）；`.overfit-warn` 与 `.signal-disclaimer` 合并为 `.warn-box` 基础类 + modifier；`ctx.items` 加运行时校验；`document.querySelector` 改用 ref；删除 `selectedIds` 静默替换的副作用。

### 已知约束（非 bug）

- **策略信号 ≠ 投资建议，也非真实账户持仓** —— 系统显示的"持仓"是**模型仓位**（策略说该持仓），不是用户真实账户的持仓。UI 已在多处（过拟合警示条 + 持仓表水印 + 载入 confirm）明确标注。用户应把它当作参考信号，而非"未来必涨"的保证。
- **信号会漂移** —— 今天重跑说"持仓"，明天大跌触发止损可能变"空仓"。需要定期打开重跑。水印标注的是计算当天的收盘价信号。
- **不做真实账户追踪** —— 不存用户实际买卖了多少股、真实成本。那是投资日记/MRP 级别功能，工程量 5x，本次未做。

## [1.17.15] — 2026-07-05

**Web UI 参数寻优体验升级：一键寻优按钮改橙色 + 等待期间投资大师名言轮播** —— 参数寻优是一个后台 Task，跑一遍全策略预设网格往往要 30 秒到几分钟。此前点击「一键寻优所有策略」后，按钮变灰、右侧整片纯色空白，用户根本不知道系统在干什么，容易以为卡住。本次给两段体验都做了升级：按钮改为暖橙渐变（`#f59e0b → #ea580c`）在深色金融主题下比 primary 蓝更醒目；寻优进行中右侧展示 100 条全球投资大师名言（巴菲特/芒格/格雷厄姆/林奇/索罗斯/利弗莫尔/塔勒布/达利欧等），3 秒随机轮播一条，Fisher-Yates 洗牌避免短期重复，让等待不枯燥、还能学到东西。

### 新增

- **100 条投资大师名言数据**（`web-ui/src/data/investment-quotes.ts`）—— 覆盖价值投资（巴菲特/芒格/格雷厄姆/林奇/费雪/博格尔/邓普顿）、宏观对冲（索罗斯/罗杰斯/达利欧/塔勒布）、技术趋势（利弗莫尔/江恩）、行为金融（霍华德·马克斯）等流派，纯中文面向中文用户。每条 `{ text, author }` 结构。
- **名言轮播组件**（`web-ui/src/components/QuoteCarousel.vue`）—— Props 驱动 `interval`（默认 3000ms），mount 时 Fisher-Yates 洗牌取第 0 条，每 `interval` ms 推进，一轮播完重新洗牌；`onUnmounted` 清 `setInterval` 防泄漏。视觉：顶部 3 秒线性进度条（橙色填充暗示"还在跑"）+ 装饰大引号 + fade/slide 过渡（350ms）+ 底部脉动橙点「后台寻优进行中，大师智慧伴你等待…」。CSS 变量 `--quote-interval` 把 props 透传给动画时长，保证进度条与切换同步。
- **一键寻优按钮橙色样式**（`web-ui/src/views/OptimizeView.vue`）—— 新增 `.run-all-btn` 暖橙渐变 + 橙色光晕；hover 加亮上移 1px；运行中保留暗橙识别度（不像普通按钮变纯灰）。

### 已知约束（非 bug）

- **轮播组件目前仅接入「一键寻优」** —— 设计成 Props 驱动、零业务耦合，未来可复用到「开始寻优」「组合回测」等同样有后台 Task 等待的页面，本次未做。

## [1.17.14] — 2026-07-05

**Web UI 新增「数据评级」系统（S/A/B/C/D 五档）** —— 此前回测结果只有冷冰冰的 19 项指标，普通用户看到「总收益 126%」会觉得不错，却看不出胜率仅 35%、最大回撤 41% 背后的「套牢拿不住」风险。本次给单标的回测、组合回测、参数寻优三个入口都加上一个一眼可读的评级徽章，让普通人 1 秒判断「这个品种适不适合经常参与」。评级**不看收益率**（避免被近期大涨误导），只看风险调整后的持有体验：卡玛比率（套牢回本难度）、最大回撤、胜率、利润因子、夏普、波动率六个维度加权评分，再叠加一票否决（系统亏损/深回撤/低胜率）。京东方那种「收益好看但风险高」的案例会评 **D 档**，明确告诉用户「别碰」。长线低频策略（如 6 年 6 笔交易）不会被一刀切否决——交易笔数少时只把胜率/利润因子降权，不影响基于净值的评级。

### 新增

- **评级核心模块**（`web-ui/src/grading/`）—— 纯前端 TypeScript 实现，零后端改动。`engine.ts`（线性插值 + 加权 + 一票否决）、`thresholds.ts`（8 维度阈值锚点表，集中可调）、`combinedMetrics.ts`（从组合净值曲线重算夏普/卡玛/波动率）、`index.ts`（三个场景入口）。
- **三个场景评级** —— 单标的回测用 6 维度（卡玛 18% + 最大回撤 17% + 胜率 17% + 利润因子 18% + 夏普 15% + 波动率 15%）；组合回测从 `combined_equity` 重算 5 维度（卡玛 25% + 最大回撤 22% + 夏普 22% + 索提诺 15% + 波动率 16%，因净值算不出胜率/利润因子）；参数寻优用 4 维度降级版（夏普 30% + 最大回撤 28% + 胜率 22% + 利润因子 20%，因 GridPointResult 只有 6 字段）。
- **一票否决规则** —— 系统亏损（`profit_factor < 1` → D）、深回撤（`max_drawdown > 60%` → D）、高回撤（> 50% 最高 B）、低胜率（< 30% 且样本充足最高 C）、微利（利润因子 < 1.2 最高 B）。
- **样本不足降权（不否决）** —— 交易笔数 < 10 时，把依赖逐笔成交的维度（胜率/利润因子）权重降到 0，重分配给净值类维度；评级照常给出，旁边标「⚠ 交易样本有限」。修复了「长线策略 6 年 6 笔被打到 D」的过度惩罚。
- **评级 UI 组件**（`GradeBadge.vue` / `GradeDetails.vue`）—— 圆形徽章（S 金/A 绿/B 蓝/C 橙/D 红，遵循 A 股颜色惯例）+ 展开式详情（维度得分条 + 否决原因 + 样本提示）。接入 `BacktestView` / `PortfolioView` / `OptimizeView`，寻优排名表新增「评级」列。
- **评级自检测试**（`web-ui/src/grading/__tests__/grade.test.ts`）—— 15 个测试用 Node 内置 `node:test` + rolldown 打包跑，覆盖核心场景：京东方 = D（核心断言）、长线策略 = B、否决规则、组合评级、插值边界。

### 变更

- **`tsconfig.app.json` 排除测试目录** —— `src/**/__tests__/**` 和 `scripts/**` 不进 app bundle（测试用 rolldown 独立打包跑，不经 vue-tsc）。

### 已知约束（非 bug）

- **评级阈值需在真实数据上观察后微调** —— 所有阈值集中在 `thresholds.ts`，当前用金融惯例值校准。如果某批真实回测的评级不符合直觉，可在该文件单点调整，无需动评分引擎。
- **寻优排名表全量算评级** —— 大表（200 行）未做虚拟化，目前性能可接受。若未来卡顿再优化。

## [1.17.13] — 2026-07-04

**修复多策略组合回测「最大回撤」严重虚高** —— 用户反馈：3 个策略各自最大回撤仅 45.53%/40.16%/16.89%，组合在一起却显示 **83.76%**。根因是 `MultiStrategyEngine._build_combined_equity` 计算 `drawdown_pct` 时**分母误用初始资金（`initial`）而非逐点峰值（`peak`）**：净值大涨后峰值是初始值的好几倍（本例总收益 545%，峰值≈6.45×初始），同样的绝对回撤额除以小的初始值，百分比被等比放大。正确公式应为 `drawdown / peak`（相对当时峰值的回撤，0~1），与单标的 `PortfolioTracker.equity_curve` 的 `drawdown_pct` 定义一致。修复后最大回撤回到合理区间（≤ 各策略最大回撤的加权，不可能超过 100%）。**连带修复**：卡玛比率（`年化收益 / 最大回撤`）此前因 max_drawdown 虚高而被压低，修复后恢复正常。其余指标（总收益/年化/夏普/索提诺/波动率/交易数/胜率/盈亏比）经逐一核对**均正确**，不受此 bug 影响。

### 修复

- **`drawdown_pct` 分母改用逐点峰值**（`src/easy_tdx/backtest/multi_strategy_engine.py` `_build_combined_equity`）—— `drawdown / initial` → `drawdown / peak`（`peak_safe = peak.where(peak != 0, 1.0)` 防除零）。这同时修复 `EquityChart` 回撤曲线显示（前端读 `drawdown_pct` 取负向下画）。
- **回归守卫**（`tests/unit/test_multi_strategy.py::test_max_drawdown_relative_to_peak_not_initial`）—— 构造「净值 1→6→4」的大涨后回撤场景，断言 `max_drawdown ≈ 33%`（旧逻辑会算成 200%，必 >1，断言 `≤1.0` 抓住回归）。

## [1.17.12] — 2026-07-04

**修复 CI 在新版 FastAPI 上路由注册失败** —— v1.17.11 的 `DELETE /api/v1/strategies/{id}` 用 `status_code=204`，较新 FastAPI/Starlette 在路由注册阶段（`add_api_route`）就抛 `AssertionError: Status code 204 must not have a response body`，导致 CI 的 ubuntu 矩阵（py3.10/3.12/3.13）整片 ERROR（21 个 web 测试因 fixture 导入 router 而连带失败）。改为返回 `200 + {"deleted": id}` 确认体，既消除注册期断言又给前端明确反馈。

### 修复

- **DELETE 路由不再用 204**（`src/easy_tdx/web/routers/strategies.py`）—— `status_code=204` 改为默认 200，返回 `{"deleted": strategy_id}`；同步更新测试断言（`tests/unit/test_strategy_store.py`）。

## [1.17.11] — 2026-07-04

**Web UI 新增「策略库」与「多策略组合回测」** —— 此前回测结果存在进程内存，重启即丢，用户无法留存自己反复验证过的好策略。本次落地两层能力：(1) **策略库**——在单标的/组合回测结果区点「保存策略」，把策略 + 标的上下文 + 成绩快照（总收益/夏普/回撤/胜率）一起存进本地 SQLite 单文件（`~/.easy_tdx/strategies.db`），策略库页可载入回填、一键重跑、删除；(2) **多策略组合回测**——策略库勾选 N 个单标的策略，各拿 1/N 资金、各跑原标的（取最新行情），净值曲线按日期并集对齐求和，组合结果复用单标的的 19 项完整绩效指标（基于合并净值曲线 + 汇总成交用 `PerformanceAnalyzer` 算出），并展示各策略当前持仓。**895 单测全绿**（+24 新增），ruff format/check / mypy strict / 前端 vue-tsc 全通过。

### 新增

- **策略库后端**（`src/easy_tdx/web/strategy_store.py`、`routers/strategies.py`）—— SQLite 单文件 CRUD（加入/列出/查看/删除），落库路径随 `EASY_TDX_CONFIG_DIR` 环境变量走（与 `config.py` 同约定），线程安全（写操作串行锁 + `check_same_thread=False`）。5 个接口：`GET/POST /api/v1/strategies`、`GET/DELETE /strategies/{id}`。保存记录含 strategy + params + context（symbol 或 stocks + 日期 + 周期）+ trade_config + snapshot（成绩快照）+ tags + notes。
- **策略库前端**（`web-ui/src/views/StrategiesView.vue` + 路由 `/strategies` + 导航）—— 卡片网格列表，展示策略名/标的/收益/夏普/回撤/标签/备注/创建时间。「载入」跳转对应回测页并自动回填（单标的剥掉市场前缀只传 6 位代码；组合新增 URL query 回填）；「删除」二次确认。空态提示去回测页保存。
- **保存策略按钮**（`BacktestView.vue` / `PortfolioView.vue` 结果区）—— 弹窗填名称/标签/备注，其余（策略参数、标的上下文、成绩快照）自动从当前请求 + 结果填入。
- **多策略组合回测引擎**（`src/easy_tdx/backtest/multi_strategy_engine.py`）—— `MultiStrategyEngine`：N 个策略各拿 1/N 资金、各跑原标的，曲线按日期并集 ffill 对齐求和。输出结构同 `PortfolioResult`（`individual_results` key 形如 `"双均线交叉@SH:601088"`），前端复用组合页图表零改动。
- **多策略组合回测接口**（`web/routers/backtest.py` `POST /backtest/multi-strategy/run/async`）—— 勾选 N 个策略，逐个在 async 上下文取行情 + 构造策略实例（失败跳过），后台线程跑引擎。组合整体绩效基于合并净值曲线 + 汇总成交喂 `PerformanceAnalyzer`，得到与单标的同口径的 19 项指标。
- **策略库组合回测 UI**（`StrategiesView.vue`）—— 每张卡片加复选框（组合策略无单一 symbol 自动 disabled），顶部「组合回测(N)」按钮，结果区复用 `EquityChart` + `MetricTable`（19 项绩效）+ `PortfolioSummaryTable` + `PortfolioCompareChart` + 当前持仓表（各策略回测结束持仓快照）。

### 变更

- **`PortfolioView.vue` 新增 URL query 回填** —— 此前组合页不读 query，策略库「载入组合策略」无法回填；新增 `onMounted` 读取 `strategy/params/stocks/startDate/endDate/category`，与单标的页回填风格一致。
- **修正多策略合并净值曲线回撤符号** —— `_build_combined_equity` 原用 `drawdown = total - peak`（负值），改为 `peak - total`（正值），与单标的 `PortfolioTracker`、`PerformanceAnalyzer`、`EquityChart`（前端取负向下画）的正值约定一致；否则最大回撤算成 0、夏普/卡玛比率失真。

### 已知约束（非 bug）

- **多策略组合回测仅支持资金分仓（并行制）** —— 每个策略各拿 1/N 资金独立回测后曲线相加；不支持信号共振（投票制，`combo.py` 已有但未暴露 Web API）。资金/成本统一一组均分，不支持每策略单独配置。
- **组合回测结果暂不回存策略库** —— 当前可保存的是单次回测的策略；多策略组合的结果暂未支持存为"策略的组合"。

## [1.17.10] — 2026-07-04

**Web UI 一键寻优「查看」按钮跳转携带完整行情上下文** —— `/optimize` 页策略排名表的两个「查看」按钮此前跳转只带 `strategy` + `params`，丢失了股票代码、周期、起止日期，导致跳到回测页后用户得手动重选标的与日期才能复现寻优行情。本次让跳转 URL 额外携带 `symbol/startDate/endDate/category`，回测页 `onMounted` 自动回填到 `SymbolPicker` 表单（股票代码/周期/起止日期全部就位），用户只需点「开始回测」即可完整复现。**向后兼容**：老书签（只有 `strategy/params`）仍正常工作，缺失字段保持默认值。前端 `vue-tsc --noEmit` / `vite build` 通过，后端 870 单测全绿（无回归）。

### 新增

- **SymbolPicker 表单状态双向同步**（`web-ui/src/components/SymbolPicker.vue`）—— `code/category/startDate/endDate` 从私有 `ref` 升级为 `defineModel`（带默认值），父组件可读（拼 URL）可写（回填表单）。`defineExpose({ loadBars, loading })` 保留不动，向后兼容已有调用。

### 变更

- **「查看」跳转 URL 携带完整上下文**（`web-ui/src/views/OptimizeView.vue`）—— 抽 `buildBacktestQuery(strategyName, params)` 统一构造 query，`onViewParams`（单策略网格排名表）/`onViewAll`（全局策略排名表）两个按钮跳转时附带 `symbol/startDate/endDate/category`。
- **回测页回填标的与日期**（`web-ui/src/views/BacktestView.vue`）—— `onMounted` 新增读取 `route.query.symbol/startDate/endDate/category`，各字段独立 `if` 守卫回填到 `SymbolPicker` v-model 镜像 ref。老 URL 缺失字段保持默认值。

### 已知约束（非 bug）

- **URL query `category` 无白名单校验** —— 与既有 `strategy/params` 读取风格一致，非法值由后端 `/bars` 兜底拒绝；前端 `<select>` 显示为空但不崩溃。属项目既有输入校验风格，留作后续可选加固（应整体覆盖，避免不对称修补）。

## [1.17.9] — 2026-07-04

**修复 Web UI 回测「交易」统计面板离谱数值** —— 单标的回测页绩效指标右侧「交易」面板出现 `平均盈利 65409694.45%`、`最大盈利 133926612.60%`、`平均持仓天数 1173.792`、`盈亏比 0.000`（却胜率 100%）等明显异常值。根因是后端 `avg_win/avg_loss/max_win/max_loss` 返回**绝对盈亏额（元）**，前端 `MetricTable.vue` 却按**百分比小数 ×100** 显示；`_compute_avg_holding_days` 用 `YYYYMMDD` 整数相减代替真实日期相减（跨月放大，如 `20240201-20240131=70`）；`profit_factor` 在无亏损交易时被强制记为 `0.0`。真实数据复现用户场景（300580，RSI reversal n=14/超卖30/超买70/开盘价，2020-01-06~2026-07-03）验证修复：平均盈利 `65409694.45% → 26.85%`、最大盈利 `133926612.60% → 49.26%`、平均持仓 `1173.792 → 91.0 天`、盈亏比 `0.000 → 999.000`。**870 单测全绿**（+3 回归守卫），ruff format/check / mypy strict / 前端 vue-tsc 全通过。

### 修复

- **交易盈亏指标口径**（`src/easy_tdx/backtest/performance.py` `compute`）—— `avg_win/avg_loss/max_win/max_loss` 由「绝对盈亏额（元）」改为「单笔收益率（= pnl / cost_basis）」。新增 `cost_basis` 字段：`Trade` 增加该字段（`types.py`），`engine._compute_pnls` 在 SELL 时填入对应持仓的移动加权平均成本 × 卖出数量（`engine.py`），`_trades_to_df` 增加列。明细表 `TradeTable.vue` 的「盈亏」列仍按元显示，与汇总表的「平均盈利 %」各司其职。
- **平均持仓天数跨月放大**（`src/easy_tdx/backtest/performance.py` `_compute_avg_holding_days`）—— 原用 `YYYYMMDD` 整数相减（如 `20240201-20240131=70`），跨月越多虚高越严重；改为解析为 `datetime.date` 后相减取真实日历日。无 `cost_basis` 列或日期无法解析时安全降级，不抛异常。
- **盈亏比在无亏损交易时为 0**（`src/easy_tdx/backtest/performance.py`）—— 100% 胜率（无亏损交易）时 `profit_factor` 由 `0.0` 改为 `999.0`（与 `calmar` 在无回撤正收益时的约定一致），消除「胜率 100% 却盈亏比 0」的自相矛盾。
- **object dtype 上 `np.isfinite` 崩溃**（`src/easy_tdx/backtest/performance.py`）—— 真实 engine 产出的 trades DataFrame 列可能为 int/object dtype，导致 `np.isfinite` 抛 `TypeError`；显式 `to_numpy(dtype=np.float64)` 转换。

### 回归守卫

- `tests/unit/test_backtest_performance.py::test_avg_holding_days_crosses_month_boundary` —— 跨月持仓必须用真实日历日（1 天），而非 YYYYMMDD 整数差（70）。
- `tests/unit/test_backtest_performance.py::test_profit_factor_no_losing_trades_is_large` —— 全盈利无亏损时 `profit_factor == 999.0`。
- `tests/unit/test_backtest_performance.py::test_avg_win_zero_when_no_cost_basis_column` —— trades 缺 `cost_basis` 列时 `avg_win/max_win` 安全降级为 0.0，不抛 KeyError。

## [1.17.8] — 2026-07-04

**修复 Windows CI 矩阵 flaky 测试** —— `test_task_runner_does_not_evict_running` 用 `release.wait(timeout=5)` 钉住慢任务保持 running，但 CI 慢环境（windows 3.10）下整个测试执行超过 5s 后任务因超时自动完成、状态变 `done`，掩盖了「running 任务被 LRU 错误淘汰」的回归断言。改为 `timeout=30` 留足 CI 慢环境余量（`release.set()` 仍是确定性释放点）。**867 单测全绿**（本地连跑 5 次稳定通过），Windows 全矩阵转绿。

### 修复

- **flaky 时序测试超时**（`tests/unit/test_web_backtest.py::test_task_runner_does_not_evict_running`）—— `slow_task` 的 `release.wait(timeout=5)` 在 CI 慢环境下不够整个测试跑完，改为 `timeout=30`。该测试用于守护「LRU 淘汰跳过 running 任务」的并发正确性回归（审计修复），与港股逐笔成交无关，是 v1.17.2 引入的预先存在问题。

## [1.17.7] — 2026-07-04

**修复 Windows CI：fixture 文件读取编码** —— 1.17.5 引入的 `tests/fixtures/ex_history_transaction.json` 含中文注释，Windows CI 默认用 cp1252 解码 UTF-8 文件触发 `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f`，导致 3 个 Windows 矩阵（3.10/3.12/3.13）的 `test_parse_ex_history_transaction_hk` 失败。统一为 fixture 读取显式指定 `encoding="utf-8"`。**867 单测全绿**，ruff format/check / mypy strict 通过，Windows + Linux 矩阵均转绿。

### 修复

- **Windows fixture 读取编码**（`tests/unit/test_hk_transaction.py` `load_hex`/`load_json`、`tests/unit/test_commands_offline.py` `load_hex`、`tests/unit/test_decode_errors.py` `_load_hex`）—— 所有 fixture 文件读取显式指定 `encoding="utf-8"`，避免 Windows 默认 cp1252 编码读取含中文 fixture 时 `UnicodeDecodeError`。`test_commands_offline` 与 `test_decode_errors` 的 hex 文件虽为纯 ASCII 当前未触发，但一并修复以统一编码规范、防范未来回归。

## [1.17.6] — 2026-07-04

**港股逐笔成交：补充 start 倒序语义文档 + 新增 goods_transaction_all 全量取数** —— 回应 issue #14 后用户反馈：默认 `count=2000` 取回的成交记录时间全集中在尾盘（如 02715 全天成交 13327 笔，count=2000 只取到最近 2000 笔）。根因是通达信逐笔协议（A 股 0x122F 与港股 ex 0x23FC/0x2406 一致）的 `start` 为**倒序**语义——start=0 指向最新一笔（收盘方向），并非 bug。本次：补 docstring 说明 start 语义；新增 `goods_transaction_all` 自动翻页取全天全部成交。**867 单测全绿**（+5），ruff format/check / mypy strict 通过。

### 新增

- **`goods_transaction_all`（全量取数）**（`src/easy_tdx/ex/mac_client.py` 同步 + 异步、`src/easy_tdx/ex/_hk_transaction.py` 新增 `_fetch_all_hk_transactions_sync/async`）—— 港股股票类市场专用，自动按 1800/页翻页直至末页（不足一页或空即停），返回当日全部逐笔成交（港股单日常 1~5 万笔）。安全上限 50 页（90000 条）防止异常数据导致无限翻页。返回顺序为协议原生倒序（最新在前）；需正序展示由调用方自行 `df.iloc[::-1]`。market 非港股股票类时抛 `ValueError`。

### 变更

- **`goods_transaction` docstring 补 start 倒序语义**（`src/easy_tdx/ex/mac_client.py`）—— 明确说明 `start=0` 指向最新一笔（收盘方向），与 A 股 0x122F 语义一致；提示 `count=2000` 默认只取最近 2000 笔会集中在尾盘，需全天数据请用 `goods_transaction_all`。

### 修复

- **CI ruff format 失败**（`tests/unit/test_hk_transaction.py`）—— 1.17.5 引入的测试文件未过 `ruff format --check`（参数化注释前双空格、MacTransaction 单行化、文末空行）。本次顺手修复。

## [1.17.5] — 2026-07-04

**港股逐笔成交协议路由修复** —— 修复 issue #14：`MacExClient.goods_transaction` 对港股市场（HK 主板 / 创业板 / 指数 / 基金 / 港股通 / 暗盘）返回空。根因是对所有扩展市场统一复用了 A 股 MAC 协议的 `SymbolTransactionCmd`（0x122F），而 0x122F 的数据源未接入港股，服务器对港股 market 一律返回 39 字节空响应（count=0）。改为对港股股票类市场路由到 ex 扩展行情协议（当日 0x23FC / 历史 0x2406），并把整数价格换算为港元浮点。**860 单测全绿**（+22），ruff / mypy strict 通过。

### 修复

- **港股逐笔成交协议路由**（`src/easy_tdx/ex/mac_client.py` 同步 + 异步 `goods_transaction`、新增 `src/easy_tdx/ex/_hk_transaction.py`）—— 港股股票类市场（`HK_STOCK_MARKETS = {27, 31, 48, 49, 71, 98}`，即 HK_INDEX/HK_MAIN_BOARD/HK_GEM/HK_FUND/HK_STOCK_GGT/HK_DARK_POOL）改走 ex 扩展行情协议：`query_date=None` → `GetExTransactionDataCmd`（0x23FC 当日），指定日期 → `GetExHistoryTransactionDataCmd`（0x2406 历史）。返回的 `ExTransactionRecord`（price 为整数、单位 0.001 HKD）映射为与 A 股 `MacTransaction` 一致的 schema（`time/price/vol/trade_count/bs_flag`），价格 ÷1000 换算为港元浮点，与港股分时图 float 价格对齐。count > 1800 时按 1800/页自动分页。其余扩展市场（美股 / 期货等）保持 MAC 0x122F 路径不变。
- **回归测试**（`tests/unit/test_hk_transaction.py`，新建 +22 例；`tests/fixtures/ex_history_transaction.hex` + `.json`，录制自真实港股 00700 在 2026-07-03 的 0x2406 响应）—— 覆盖：ex 历史 0x2406 响应解析、空响应处理、`ExTransactionRecord → MacTransaction` 字段映射 + 价格换算、`is_hk_stock_market` 市场判定边界（11 个参数化用例）、mock `_execute` 验证路由（港股走 ex / 期货仍走 0x122F）、分页与空停止逻辑。

### 说明

- issue #14 反馈的 `df1`（7/4 周六休市）与 `df2`（7/1 香港回归纪念日休市）返回空属正常休市；真正的 bug 是 `df3`（7/3 开市日 02715，`HK_MAIN_BOARD`）。修复后开市日港股逐笔成交可正常取数。
- 港股衍生品（HK_FINANCIAL_FUTURES=23 / HK_STOCK_OPTIONS=26 等）不在本次路由范围：期货/期权逐笔语义不同，且 0x122F 对 CFFEX 期货恰好可用，保持现状避免回归。

## [1.17.4] — 2026-07-04

**Web UI 回测交互重构 + 一键寻优全策略** —— 针对单标的 / 组合 / 寻优四个页面做交互精简与能力补强：取行情整合进「开始回测」一键完成、市场选择改为 6 位代码智能识别、成交价精简为开盘价/收盘价、初始资金统一为 100 万、新增 18 策略预设参数网格与「一键寻优所有策略」全局排名。**838 单测全绿**（+2），ruff / mypy strict / vue-tsc 全部通过。

### 新增

- **一键寻优所有策略**（`web/routers/backtest.py`）—— 新增第 7 个回测端点 `POST /backtest/optimize-all/run/async`：对全部 18 个内置策略逐个用其预设参数网格做 `ParamGridOptimizer` 网格寻优（共用同一份 OHLCV），取各策略最优点汇总成全局排名（按总收益降序），返回 `OptimizeAllResult`（`ranking` / `best` / `per_strategy` / `total_grid_points`）。前端寻优页新增「一键寻优所有策略」按钮 + 策略排名表（策略/参数/收益/夏普/回撤/胜率），点击行可跳转单标的页用该策略+参数回测。端到端实测：18 策略 × 182 网格点约 5s 跑完。
- **策略预设参数网格**（`backtest/strategies/presets.py`，新建独立配置文件）—— 18 个策略各配 1-2 个关键参数的合理取值列表（单策略笛卡尔积 ≤ 200），如双均线 `fast=[5,10,15,20,30,60] × slow=[10,20,30,60,120,250]`（36 点）、MACD `short=[8,10,12,15] × long=[20,26,30,40]`（16 点）等。作为单一事实源供寻优页自动填充 + 一键寻优消费；`RegisteredStrategy.to_schema()` 通过 `preset_grid` 字段返回，前端 `ParamGridPicker` 切换策略时自动勾选并填入预设（用户仍可编辑/取消）。
- **市场智能识别**（`web-ui/src/market.ts`，新建）—— `detectMarket(code)` 按 6 位代码段规则自动匹配沪市(SH)/深市(SZ)/北交所(BJ)：北交所 43/83/87/92(含920)/93 + 4xx/8xx，沪市 6xx(主板/科创板)/9xx(B股)/5xx(基金)，其余归深市。17 个真实边界用例（贵州茅台/宁德时代/北交所各段/ETF 等）全过。
- **一键寻优端到端单测**（`tests/unit/test_web_backtest.py`，+2 例）—— `test_optimize_all_endpoint` 验证排名降序、best 指向第一、各策略最优点齐全、合计网格点 = 各策略 grid_points 之和；`test_optimize_all_request_validation` 验证缺数据源报错 + 默认值。

### 变更

- **取行情整合进「开始回测」**（`web-ui/src/components/SymbolPicker.vue`、`views/BacktestView.vue`、`views/OptimizeView.vue`）—— 取消单标的/寻优页独立的「取行情」按钮，点击「开始回测/开始寻优」时先自动取行情（`SymbolPicker` 经 `defineExpose` 暴露 `loadBars()`）再回测，按钮文案随状态切换为「取行情+回测中…」。组合页本就是后端取数路径，无需改动。
- **取消市场手动选择**（`web-ui/src/components/SymbolPicker.vue`、`StocksPicker.vue`）—— 删除沪市/深市/北交所下拉框，只保留 6 位代码输入，由 `detectMarket` 自动识别并显示（代码框旁小标签 / 添加时提示）。后端校验仍要求 `市场:代码` 格式，前端始终发送带前缀 symbol。
- **成交价精简为开盘价 / 收盘价**（`backtest/orders.py`、`backtest_schemas.py`、`types.ts`）—— 删除 `this_close`（本根收盘，有未来函数偏差会高估收益）、`worst`（最差价）、`best`（最优价）三种非真实成交模式，只保留 `next_open`（次日开盘价）与 `next_close`（次日收盘价）两种真实可执行模式。UI 下拉显示中文「开盘价/收盘价」。后端字符串值不变以保持数据契约。
- **初始资金统一为 1,000,000**（前端三个 view + `backtest_schemas.py` 三处 default）—— 单标的/组合/寻优默认初始资金从 10 万/20 万统一为 100 万。
- **寻优预设自动填充**（`web-ui/src/components/ParamGridPicker.vue`）—— 切换策略时若有 `preset_grid` 自动勾选对应参数并填入预设取值，提示文案补充「切换策略会自动填入预设参数，可直接编辑」。

### 修复

- **一键寻优合计网格点计算错误**（`web/routers/backtest.py` `_run_optimize_all`）—— 初版用各参数取值列表长度之和（如双均线算成 6+6=12）而非笛卡尔积（应为 6×6=36），导致前端「合计 N 网格点」显示偏低。改为累加各策略 `len(result.results)`（真实成功网格点），现等于理论笛卡尔积之和。

## [1.17.2] — 2026-07-03

**QFQ 深层历史负价修复** —— 修复通达信服务端在前复权（QFQ）模式下对长期重度除权股票（如 601088 中远海控）深层历史页直接返回**负价格**的上游缺陷，导致回测出现总收益 -3087%、最大回撤 326.85%、年化 nan%、`bollinger_breakout` 崩溃（`ZeroDivisionError`）、10 个策略报 `invalid value in scalar power`、`MyTT` 报 `divide by zero` 等一连串症状。**844 单测全绿**（+20），ruff / mypy strict 通过。

### 修复

- **QFQ 深层历史返回负价**（`mac/commands/symbol_bar.py`、`mac/client.py`、`mac/adjust.py`）— 根因：通达信 MAC 服务端在 QFQ 模式下，对 601088 这类长期重度除权股票的深层历史页（`start` 偏移 > ~2100）直接返回负价格（如 2013-11-18 QFQ close=-3.80，而 NONE=16.58、HFQ=27.17 均正常）。`SymbolBarCmd` 原样解析，污染下游全部计算：负 close → `position_value = size*close < 0` → 总权益为负 → 回撤 >100%、`total_return < -1` → `(1+total_return)` 为负 → 分数次幂 = nan；同时 BOLL 指标在零价处触发 `cash/0` 崩溃。**非 easy_tdx 代码 bug，是上游数据缺陷。**
  - 修复：客户端兜底——`MacClient.get_stock_kline` 检测到 QFQ 结果含 `<=0` / NaN / inf 时，用 `fq=NONE` 重抓原始价，再经 `TdxClient.get_xdxr_info`（连 `get_known_hosts` 主机池，按 `(market,code)` 缓存）拉除权除息记录，本地重算前复权。同步 + 异步（`AsyncMacClient`）双路径一致修复。
  - 公式（经实证验证）：以**除权日前一交易日收盘价**（含权价 `P_cum`）为基准，前复权因子 `f = (P_cum - fenhong + peigujia×peigu) / (P_cum×(1+songzhuangu+peigu))`，乘到该日及之前所有 bar 的 OHLC。该约定保证除权日前后价格连续（验证 jump≈0%），若误用除权日收盘价则 jump 达 -8%~-13%。
  - 降级：XDXR 取不到或重算后仍含非法价格时，打 warning 返回原值（不比现状更坏）。
  - 验证：重跑 `run_all_strategies.py SH 601088 --count 3000 --adjust QFQ`，16 策略全绿，总收益落 [-33%, +430%]，最大回撤 [25%, 67%]，年化全有限，无任何 warning/nan/崩溃。
  - 新增纯函数模块 `mac/adjust.py`（`compute_forward_factor` / `apply_forward_adjust` / `has_bad_prices`），无网络依赖便于单测。

### 新增

- **QFQ 本地重算纯函数**（`mac/adjust.py`）— `compute_forward_factor`（单次除权因子）、`apply_forward_adjust`（OHLC 同比缩放，最新价锚定不动，多次事件累乘）、`has_bad_prices`（检测 <=0/NaN/inf）。纯 pandas/numpy，无 easy_tdx 内部依赖。
- **QFQ 重算单测**（`tests/unit/test_mac_qfq_adjust.py`，16 例）— 覆盖纯现金分红、送转股、多次事件累乘、无事件原样返回、非法因子跳过、输入不可变、最新价锚定、`has_bad_prices` 各分支。
- **QFQ 重算集成测试**（`tests/unit/test_mac_qfq_integration.py`，4 例）— monkeypatch `MacClient._execute` 返回含负价的 QFQ + mock `TdxClient.get_xdxr_info` 返回 XDXR，验证触发重算、干净 QFQ 不触发、XDXR 失败降级、NONE 跳过重算。无 live server。

## [1.17.0] — 2026-07-03

**回测可视化 Web UI 大版本** —— 从命令行回测升级到浏览器可视化。Vue3 + ECharts 单页应用，零代码完成单标的回测、组合回测、参数寻优、结果对比四大场景。后端新增回测 REST API + 策略注册表 + 后台任务执行器，内置策略从 5 个扩充到 18 个。**823 单测全绿**，ruff / mypy strict / vue-tsc 全部通过。

### 新增

- **回测可视化 Web UI**（`web-ui/`）—— Vue3 + Vite + TypeScript + Pinia + ECharts 单页应用，四个功能页：
  - **单标的回测**：选标的取行情（日期范围 + 自动翻页），18 个内置策略任选，参数表单按 schema 动态渲染，K 线主图标买卖点（markPoint 按 datetime 对齐），净值回撤双轴图，19 项绩效指标表，成交明细
  - **组合回测**：多只股票等权组合，组合净值曲线（各标的按日期并集 forward-fill 对齐求和），各标的净值归一化叠加对比，横向绩效表
  - **参数寻优**：勾选 1-2 个参数填取值列表，itertools.product 网格遍历，排名表 + 二维热力图（ECharts heatmap），最优点一键跳转单标的页用该参数回测
  - **结果对比**：选 2-4 个已完成回测任务，归一化净值叠加，8 项指标横向 PK，支持单标的 + 组合混合对比
- **回测 REST API**（`web/routers/backtest.py`）—— 6 个端点：
  - `GET /backtest/strategies` 策略枚举 + 参数 schema
  - `POST /backtest/run` 同步回测（内联 OHLCV）
  - `POST /backtest/run/async` 后台任务回测
  - `POST /backtest/portfolio/run/async` 组合回测
  - `POST /backtest/optimize/run/async` 参数网格寻优
  - `GET /backtest/tasks` + `GET /backtest/tasks/{id}` 任务列表 + 轮询
- **策略注册表**（`backtest/strategies/`）—— `Param` schema 声明机制 + `ParametrizedStrategy` 基类，策略参数自描述供 Web 表单动态渲染。`@register_strategy` 装饰器登记到全局 registry
- **后台任务执行器**（`web/task_runner.py`）—— ThreadPoolExecutor + 进程内 LRU 任务表，status-aware 淘汰（不淘汰 running 任务），线程安全单例 + lifespan shutdown 接入
- **参数网格寻优器**（`backtest/optimizer.py`）—— `ParamGridOptimizer` 遍历参数笛卡尔积，按收益排序，2 参数生成热力图矩阵，网格上限 200 防爆炸，寻优时跳过参数范围检查（探索超范围值是寻优目的）
- **内置策略扩充 5 → 18 个**（`backtest/strategies/builtin.py`），新增 13 个经典策略：
  - 趋势类：EMA 双线交叉、三均线系统、DMI 趋向指标、TRIX 三重平滑
  - 通道/突破类：唐安奇通道突破（海龟）、肯特纳通道（ATR-based）、ATR 通道突破
  - 震荡/反转类：CCI 超卖反弹、WR 威廉超卖、BIAS 乖离反弹、EMV 简易波动、DPO 区间震荡
  - 均线类：BBI 多空指标
- **组合回测引擎改造**（`portfolio_engine.py`）—— 接受策略实例（参数透传到每个标的），新增组合净值曲线（按日期并集 forward-fill 对齐求和 + 回撤计算）

### 修复

- **取数翻页拼接后未排序**（`web-ui/src/api.ts`）—— 翻页拼接 concat 后页间时间逆序（page1=最新段，page2=更旧段），导致超过 800 根时图表/成交记录错乱。修复：concat 后按 datetime 排序
- **日线 x 轴丢年份**（`KlineChart.vue`）—— `isIntraday` 用 `length > 10` 判断分钟线，但日线归一化后带 `T00:00:00` 后缀长度也 19，误判为分钟线走 slice(5,16) 砍年份。改为检查时分秒是否非零
- **组合回测取数不翻页**（`routers/backtest.py` `_fetch_portfolio_bars`）—— 固定 count=800 不翻页，超 800 天数据缺失。改为翻页循环 + sort_values 排序
- **寻优跳转参数未填充**（`BacktestView.vue`）—— OptimizeView 跳转传 query 参数，但 BacktestView 未读 route.query。加 useRoute() + nextTick 填充
- **参数校验安全加固**（`registry.py` `Param.validate`）—— 拦截 NaN/Inf/giant-int（防 DoS），int(inf) 的 OverflowError 统一转 ValueError；ohlcv max_length=2000 防内存耗尽
- **task_runner 并发竞态**（`task_runner.py`）—— LRU 淘汰跳过 running 任务（修复结果丢失），get_runner double-checked locking（修复单例竞态），shutdown 接入 lifespan（修复资源泄漏），submit+executor 原子化（消除注册-淘汰窗口）
- **对比页只认单标的**（`CompareView.vue`）—— 校验只认 BacktestResult 结构，组合/寻优任务报错。新增 extractComparable() 支持组合（combined_equity）
- **日线 bars 返回 date 列**（`api.ts` `normalizeBar`）—— 日线 bars 返回 `date` 列非 `datetime`，前端归一化为统一 datetime 字段

## [1.16.3] — 2026-07-02

### 修复

- **`market-stat` 全市场涨跌统计家数系统性偏小 10 倍**（`client.py`，同步 + 异步 `get_market_stat()`）— 实测 `easy-tdx market-stat` 返回 `up_count=322 / down_count=214 / total_count=553 / limit_up_count=13 / limit_down_count=0`，量级明显不符全 A 股（5000+ 只）。根因：通达信"统计指数"`880005`（涨跌统计）/ `880006`（涨跌停统计）的计数类字段返回的是**真实家数的 1/10**，旧实现直接 `int(q.price)` 当家数用，未做缩放还原。
  - 修复：对 6 个计数字段（涨 / 跌 / 平 / 总数 / 涨停 / 跌停）统一 `round(field * 10)` 还原；`total_amount` / `total_volume` / `total_market_cap` 不受此协议缩放影响，保持原样透传。
  - 验证：实抓 `up=3225 / down=2148 / neutral=144 / total=5530`，`3225+2148+144+13(suspended)=5530` 计数守恒；`limit_up=131 / limit_down=6` 量级回归正常。同步 + 异步路径一致修复。
  - 重写 `test_get_market_stat_mapping`：用真实协议值（还原前家数 / 10）构造 mock，断言 ×10 还原后的真实家数，并补齐此前未覆盖的 `limit_up_count` / `limit_down_count` / `suspended_count` / `total_amount` / `total_volume` / `total_market_cap` 断言。

## [1.16.2] — 2026-07-02

**质量加固版本** —— 经三轮代码审计（B 6.9 → A 7.6 → A 7.9）后的综合修复，覆盖协议核心层、数据正确性、错误处理、测试真实度与可维护性。**761 单测全绿**（+58），`ruff check` / `ruff format --check` / `mypy strict` 全部通过，CI 加 Windows 矩阵 + trusted publishing + 签名，达到稳定 PyPI 库发布质量。

### 修复

- **离线 `.day` 文件追加写入非原子，崩溃即损坏**（`offline/write_daily.py`，审计 #1）— 追加行情数据时若进程被杀 / 断电，会留下半截 bar 破坏整文件可读性。新增 `fsync + flush` 强制落盘，写入路径完成后调用独立的 `_repair_tail` 修复尾部残条，并在读取侧（`get_last_bar_date`）做完整性校验。**严格遵守 command-query separation**：「get」函数纯读不写，损坏清理只在写入路径触发——超出审计建议。
- **回测止损存在前视偏差**（`backtest/execution.py`、`backtest/orders.py`，审计 #4）— 止损单当根触发当根成交，等于用未知的当根收盘价决策。改为延迟到**下一根开盘**成交，并加**跳空保护**（SELL 取 `min(开盘, 触发价)`，即对持仓者更不利的价格，模拟真实滑点）。新增专门的 gap 回归测试。
- **VWAP 因子权重索引错误**（`factor/builtin/`，审计 #3）— `np.resize` 平铺权重时索引错位，导致计算用了未来数据（前视偏差）。显式用 `np.resize` 平铺，docstring 明确「仅用历史数据避免前视」。
- **`bar_time` 非法值静默回退**（`_df.py`、`client.py`、`ex/client.py`、`mac/client.py`，审计 #5）— 传入非法 `bar_time` 时静默当作默认值处理，掩盖用户错误。改为 fail-fast 抛 `ValueError`（同步 + 异步路径都加）。
- **绩效分析除零**（`backtest/performance.py`，审计 #11）— 日收益率 `np.diff(total) / total[:-1]` 在首根或中间净值为 0 时产生 `inf`，污染 sharpe / volatility 等指标。改为 `safe_prev = np.where(total[:-1] != 0, ..., np.nan)` + `np.isfinite` 过滤；总收益率在 `total[0] == 0` 时兜底为 `0.0`。新增 3 个边界回归测试（中间含 0 / 首根 = 0 / 全零）。
- **闭包延迟绑定循环变量 `date`**（`client.py`，审计 #10）— `get_history_fund_flow` 在循环里用 `lambda` 捕获 `date`，所有闭包共享最后一次的值。改用默认参数 `_d=date` 立即绑定。
- **路径穿越**（`offline/paths.py`，审计 #16）— 用户传入含 `/`、`\` 或 `..` 的代码可逃出 `vipdoc` 目录。新增清洗拒绝危险字符（保留通达信文件名常见的 `#`）。
- **`ruff check` 报 2 个 UP038 错误致 CI 红灯**（`cninfo/client.py`、`factor/engine.py`，审计复审 N1）— `isinstance(x, (int, float))` 在 pyupgrade 规则下应改 `int | float`（PEP 604，Python ≥3.10 运行时合法）。修复后 `ruff check src/ tests/` 全过。
- **naive datetime 跨时区误判缓存过期**（`client.py`、`config.py`，审计 #18）— 缓存时间戳用 naive datetime，UTC 机器（如 CI）与本地 +8 机器比较时差 8 小时，导致缓存频繁失效或永不过期。统一用 aware datetime（`Asia/Shanghai`），并兼容旧 naive 缓存（检测到 naive 时 localize）。

### 变更

- **抽出 `AsyncHeartbeatMixin`，收敛 4 处心跳副本**（`_reconnect.py`、`client.py`、`ex/client.py`、`ex/mac_client.py`、`mac/client.py`，审计复审 L1）— 4 个 async client（A股 / MAC / 扩展行情 / 扩展 MAC）的 `_start_heartbeat` / `_stop_heartbeat` / `_heartbeat_loop` 三件套**逐字节重复**（仅心跳命令和 logger 名不同），共 12 处副本。抽出到 `AsyncHeartbeatMixin`，子类只需实现 `_heartbeat_cmd()` 返回心跳 awaitable。同时统一 `_HEARTBEAT_RETRYABLE = (OSError, TdxConnectionError, TdxDecodeError)` 异常范围（审计 #6 收窄，不吞代码 bug）。未来改心跳策略只需改一处。
- **统一重连退避序列 `_RETRY_DELAYS`**（`_reconnect.py`，审计 #2）— 原先 6 处 client 副本里 MAC 用 4 次退避、扩展行情用 1 次，韧性策略不一致（最高危的行为分歧）。统一为 `(0.1, 0.5, 1.0, 2.0)` 4 次指数退避。
- **`unified.py` 重复方法加 `DeprecationWarning`**（审计 #14）— `UnifiedTdxClient` 与子 client 的同名方法重复，加弃用警告而非硬删，向后兼容。
- **`MAJORITY` 投票因子退化时告警**（审计 #17）— 样本数 `n < 3` 时投票无意义，原静默退化，现加 `logger.warning`。
- **scanner 并行扫描接入增量缓存**（`screen/scanner.py`，审计 #15）— 并行路径原先绕过 mtime 缓存，每次 `--workers` 全量重算 5000 只。现与串行路径一致地按 mtime 跳过未变文件。
- **async gather 假并发诚实文档化**（`mac/client.py`，审计 #12）— 单 TCP 连接的 `asyncio.gather` 实际串行（受 `_execute_lock` 约束），docstring 明确说明「无并发加速收益，如需真正并发需连接池」。

### 新增

- **scanner 系统性失败可观测性**（`screen/scanner.py`，审计 #6 / 复审 L2）— 串行 + 并行扫描循环原先 `except Exception: continue` 完全静默，系统性失败（大量损坏 `.day` / 磁盘故障）被吞，用户得到空结果却以为「没有信号」。现在：① 每个单股失败记 `logger.warning`（带 `exc_info`）；② 失败率 ≥ 50% 时循环结束发醒目汇总告警；③ 策略计算异常记 debug（避免 5000 只批量刷屏）。新增 2 个 caplog 回归测试。
- **公共 API 类型契约测试**（`tests/unit/test_public_api.py`，审计 #13 / 复审 L3）— 原先只验证 `__all__` 中每个名字「可导入」，无法捕获「类被误绑成模块 / None」。新增 `inspect.isclass` / `callable` 类型断言 + **契约完整性双向守卫**（同时检查「导出了但没声明类型」和「声明了但没导出」），防止 `__all__` 与类型契约表漂移。
- **5 个关键路径测试文件**（审计 #9）— 新增 `test_client_reconnect.py`（验证精确退避序列 + 4 次重试耗尽）、`test_ex_reconnect.py`（扩展行情统一退避 + MAC 重登录每次重试）、`test_config.py`（三级 host 优先级 + 原子写 + 缓存合并）、`test_codec_bitmap.py`（字节级编解码往返）、`test_public_api.py`（见上）。覆盖率门槛 50 → 60（实测 61%）。

### 发布工程

- **CI 加 Windows 矩阵**（`.github/workflows/ci.yml`，审计 #7）— 原 CI 仅 Linux，而通达信用户主要在 Windows。加 `windows-latest` 矩阵 + `fail-fast: false`。
- **启用 PyPI trusted publishing + sigstore 签名**（`.github/workflows/publish.yml`，审计 #8）— 发布产物加 attestations 签名认证，提升供应链可信度。
- **锁定 dev 工具链 + 依赖加上界**（`requirements-dev.txt`、`pyproject.toml`，审计 #8）— 新增 `requirements-dev.txt` 锁定 pytest / mypy / ruff / scipy 版本（CI 可复现）；运行时依赖加下界 + 上界（`pandas>=2.0,<3`、`click>=8.0,<9`、`fastapi<1`）。
- **删除 README 造假的 bandit 徽章**（审计 #8）— 徽章声称跑了 bandit 安全扫描但实际没有，移除。
- **`ruff format` 全仓合规**（审计复审 V3-1）— 修复 2 个文件的格式不合规，`ruff format --check src/ tests/` 全过。

## [1.16.1] — 2026-07-01

### 修复

- **多日分时图 `tick --days N` 命令因 `minutes ≥ 1440` 报 `ValueError: hour must be in 0..23`**（`mac/commands/tick_charts.py`，[Issue #10](https://github.com/handsomejustin/easy_tdx/issues/10)）— 执行 `easy-tdx tick SH 600519 --days 5` 时崩溃。多日分时图（MAC 协议 `0x123E`）解析 `time(minutes // 60, minutes % 60)` 缺少对 24 取模的保护，当个别服务器 / 数据状态下返回的 `minutes` 值 ≥ 1440（累计或异常值，用户实测出现 `minutes ≈ 62340` 即 `// 60 == 1039`）时，`minutes // 60` 超过 23 触发 `ValueError`。
  - 修复：改为 `time(minutes // 60 % 24, minutes % 60)`，与单日分时 `SymbolTickChartCmd` 的处理**完全一致**。
  - 语义自洽：每条 tick 的**日期**取自 `date_ints[d]`（与 `minutes` 无关），`minutes` 字段只承载「日内时刻」，`% 24` 折算成日内时刻是正确的降级。
  - **对正常数据零行为改变**：抓取多只股票 × {2 天, 5 天} 真实响应逐条对比，新公式与旧公式产出 `time` 对象**完全相同**（`new_vs_old_diffs=0`），所有时刻落在 09–15 交易时段。
  - 对异常 `minutes` 值，无法仅凭该字段恢复真正时刻（需日边界信息），故产出合法占位时刻，避免崩溃、不污染日期列。
  - 新增 3 个单元测试（`test_mac_tick_charts.py`：正常分钟 / Issue #10 回归用报错现场原值 62340 / 请求包布局），全量 703 单测通过。

## [1.16.0] — 2026-06-30

### 新增

- **分钟级 K 线时间戳可选「开始/结束时间」**，一键对齐 Tushare / 同花顺（`_df.py`、`client.py`、`ex/client.py`、`mac/client.py`、`cli/cmd_kline.py`、`web/routers/bars.py`，[Discussion #7](https://github.com/handsomejustin/easy_tdx/discussions/7)）— 通达信协议用 bar **开始时间**打时间戳（5min 线上午最后一根标 11:25、下午第一根标 13:00；午休 11:30–13:00 无 bar），而 Tushare / 同花顺 / 聚宽用 bar **结束时间**（标 11:30 / 13:05）。新增 `bar_time` 参数让用户自由切换，避免再自行 `+5 分钟` 偏移。
  - 全部 3 条 K 线路径覆盖：A 股 `get_security_bars` / `get_index_bars`（同步 + 异步）、扩展行情 `get_instrument_bars`（同步 + 异步）、MAC 协议 `get_stock_kline` / `get_stock_kline_with_indicators`（同步 + 异步）。
  - CLI `kline` 新增 `--bar-time {start,end}` 选项；Web `/bars`、`/bars/index` 新增 `bar_time` 查询参数。
  - `bar_time="start"`（**默认**）保持完全向后兼容，行为与 1.15.4 一致；`bar_time="end"` 仅对分钟级周期（1/5/15/30/60min）生效，日线及以上不受影响，自动按周期时长右移并处理跨小时 / 跨日边界。
  - 协议解码层（`codec/datetime_.py`、`symbol_bar.py`）零改动，偏移作为纯展示语义在 client 层后处理，单一工具函数 `_apply_bar_time_align_df` / `_apply_bar_time_align_bars` 复用于全部路径。
  - 已知限制：扩展行情 `get_history_instrument_bars_range`（按日期范围查询）不携带周期信息，传 `"end"` 时发出 warning 原样返回（建议改用 `get_instrument_bars`）。
  - 新增 27 个单元测试（`test_codec_datetime.py` 偏移逻辑 + `test_kline_bar_time.py` 三路径覆盖），全量 700 单测通过。

## [1.15.4] — 2026-06-29

### 修复

- **ETF / 指数 / 基金 / 可转债 / 国债实时行情价格被放大 10 倍**（`commands/security_quotes.py`，[Issue #8](https://github.com/handsomejustin/easy_tdx/issues/8)）— `get_security_quotes` 返回的 `price_raw` 及五档差分字段统一以「厘」(0.001 元) 为基本单位编码，但**报价精度按品种而异**：股票 2 位（分），ETF / 指数 / 基金 / 可转债 / 国债 / 国债逆回购 3 位（厘）。此前一律按 `/ 100.0`（2 位）解析，导致 ETF 等本应 `/ 1000.0`（3 位）的品种价格被放大 10 倍（如现价 6.123 元的 ETF 错误显示成 61.23）。
  - 新增 `_price_decimal_digits(market, code)`，凭 `market + code` 代码段推断有效小数位：沪市 `5`（ETF/基金）、`000`（指数）、`8`（行业指数）按 3 位；深市 `1`（ETF/LOF/可转债/国债）按 3 位；其余股票按 2 位。
  - 同一代码不同市场含义不同，必须结合市场判断：`SZ 000001` = 平安银行（股票，2 位），`SH 000001` = 上证指数（3 位），二者不可混淆。
  - 价格字段（现价 / 昨收 / 今开 / 最高 / 最低 / 五档买卖价）除法从硬编码 `/100.0` 改为按 `divisor = 10 ** 位数` 动态除法；`rise_speed` 等非价格字段保持 `/100.0` 不变。
  - `SecurityQuote` 新增 `decimal_point` 字段（默认 2，向后兼容），标注该条行情实际采用的小数位数，便于核对。
  - `decimal_point` 不在行情响应包内，仅能凭代码段推断（pytdx 把这一步留给用户，本项目做自包含解析）。新增 4 个单元测试覆盖 ETF/股票/指数精度与品种分类，全量 680 单测通过，既有 `600000` fixture 断言不变（股票行为无回归）。

## [1.15.3] — 2026-06-27

### 变更

- **`company-info` 传板块名时自动读完整正文** — 此前传板块名仍需用户关心 `--offset`/`--length`，体验笨拙。现在传板块名时自动按目录里的 `length` 分块循环读取整个板块（单次上限 30720 字节，大板块如「公司大事」77 万字节也能一次读全），`--offset`/`--length` 仅在传文件名时生效。
  - 用户只需：`easy-tdx company-info SH 601088 "公司概况"` 即可读到该板块完整内容，无需任何 offset/length。
  - 修复分块 offset 推进 bug：原按解码后字符串 GBK 重编码计字节数，遇到 GBK 无法解码的字符（U+FFFD）会抛 `UnicodeEncodeError`；改为按请求字节数推进（服务器按字节偏移工作）。

### 修复

- **多服务器 F10 目录版本不一致**（`cmd_company.py`）— 通达信不同服务器返回的 F10 目录板块名版本不一致（新版含「公司大事/研究报告/...」，旧版含「机构持股/分红融资/...」）。传板块名时若当前服务器未命中，现自动重试多个服务器（新建连接，最多 4 次）直至命中，避免「列目录能看到、读正文却找不到」的割裂。

## [1.15.2] — 2026-06-27

### 变更

- **`company-info` 命令合并** — 把 `company-info`（列目录）与 `company-info-content`（读正文）合并为一个命令，消除「列目录」和「读正文」两个相似命令名的混淆：
  - 无板块名参数 → 列 F10 板块目录（原 `company-info`）
  - 有板块名参数 → 读板块正文（原 `company-info-content`）
  - `company-info-content` 保留为**隐藏别名**（`hidden=True`），向后兼容 v1.15.1 脚本，不出现在 `--help`。
  - 示例：`easy-tdx company-info SH 600519 "公司概况"` 现在直接读正文（无需记忆用哪个命令）。

### 新增

- **examples/06_finance 文档完善** — 补全财务快照与 F10 公司信息的三种调用方式 demo：
  - 新增 `README.md`：命令关系图、16 个 F10 板块完整列表、字段说明、三方式快速开始。
  - 新增 `company_cli.sh`：CLI 命令 demo（finance-info / company-info 全用法、输出格式切换、错误处理）。
  - 新增 `company_web_api.py`：Web API 调用 demo（`/finance` `/company/category` `/company/content`）。
  - 更新 `company_info.py` 板块名列表为实测的 16 板块（分红扩股/高层治理/龙虎榜单等）。

## [1.15.1] — 2026-06-27

### 新增

- **通达信原生 F10 与财务快照 CLI 命令** — 把 `TdxClient` 上已封装但未暴露给 CLI 的三个方法做成命令，数据源与 Web 层 `/finance` `/company/*` 端点同源，覆盖 `f10`（新浪三表）之外的 F10 全文板块。
  - 新增 `easy-tdx finance-info` — 最新财务快照（37 字段：股本结构、资产负债、利润、现金流、每股指标），与 `f10`（多期三表）互补。
  - 新增 `easy-tdx company-info` — F10 板块目录，列出最新提示/公司概况/财务分析/股东研究/股本结构/资本运作/业内点评/行业分析/公司大事/研究报告/经营分析/主力追踪/分红扩股/高层治理/龙虎榜单/关联个股等板块及其文件偏移。
  - 新增 `easy-tdx company-info-content` — 读取 F10 板块正文，`name_or_filename` 既可传板块名（自动定位到该板块起点读取），也可直接传文件名；`--offset` 语义随入参而定（板块名=板块内相对偏移，文件名=文件绝对偏移），`--length` 控制读取范围。
  - 新增 `get_tdx_client()` 上下文管理器（`cli/conn.py`），仿 `get_mac_client()` 包装 `TdxClient.from_best_host()`。

## [1.15.0] — 2026-06-25

### 新增

- **强势股排名（strength）** — 全市场按 5/20/60 日涨幅加权合成强势分，选出"最近最强"的股票。
  - 新增核心引擎 `easy_tdx.screen.strength.StrengthRanker`，纯离线读取本地 `.day` 文件，复用 `SignalScanner` 的并发/进度回调架构。
  - 新增 CLI 子命令 `easy-tdx screen strength`，支持表格 / JSON 输出。
  - 新增 Web API 端点 `GET /api/v1/market/strength`，通过线程池执行避免阻塞事件循环。
  - **三种预设模式**：
    - `steady`（默认）：中长期稳健，60 日权重主导 + 波动率惩罚，选出"稳着涨"的票。
    - `breakout`：近期妖股爆发，5 日权重主导，纯加权涨幅（不除波动率），选出短期最猛的票。
    - `balanced`：三周期均衡 + 波动率调整。
  - 支持自定义权重（自动归一化）、成交额过滤、上市天数过滤、并发扫描。
  - 输出含 `data_date` / `last_date` 字段，标注数据截止日，便于判断时效。
  - 示例代码见 `examples/23_screen_strength/`。

### 修复

- **`_detect_security_type` 代码段判定不全**（`offline/daily_bar.py`）—— 上交所科创板 ETF（588/589）、LOF（560-563）、货币 ETF（551）、普通 ETF（520-530）等代码段，以及深交所封闭式基金/LOF（17/18 开头）、国债逆回购（204 开头）被默认返回值误判为深市 A 股，导致 `screen strength` / `screen scan` 把基金和 ETF 混入股票排名。修复后补全所有已知代码段，默认返回 `UNKNOWN`（不再误判成 A 股）。
- **`screen strength` / `screen rank` 名称补齐分批 bug**（`screen/cli.py`、`screen/ranker.py`）—— `MacClient.get_stock_quotes` 单次最多 80 只，传入超过 80 只时末尾名称被服务器静默丢弃。修复后改为 80 只/批分页查询。

### 变更

- `easy_tdx.screen.__init__` 导出 `StrengthRanker`、`StrengthResult`、`STRENGTH_PRESETS`。
- README 增加「强势股排名（strength）」章节及 Web API 调用示例。

## [1.14.5] (2026-06-17)

**缠论可视化日期自适应时分** — 响应网友反馈，分钟级别（1/5/15/30/60min）的缠论结果日期字段现在输出完整时分 `YYYY-MM-DD HH:MM`，日/周/月/年级别仍只输出日期 `YYYY-MM-DD`（无多余 `00:00`）。

新增 `ChanlunResult._fmt_dt()` 按 `frequency` 自适应格式化，统一作用于 `bis` / `zss` / `mmds` / `bcs` / `xds` 所有日期字段。兼容 CLI 原始值（`5MIN`/`30MIN`）与 Web 映射值（`5min`/`30min`）的大小写。三层接入同步生效。

## [1.14.4] (2026-06-16)

**CI 修复** — 修复 v1.14.3 中 `cmd_chanlun.py` 两处 `click.echo(...)` 未按 `ruff format` 行宽规则合并导致的 CI 格式检查失败（纯格式调整，无功能变化）。

## [1.14.3] (2026-06-16)

**缠论 CLI table 模式补日期** — 延续 v1.14.2 的可视化增强，在 `easy-tdx chanlun --table` 表格输出中也为中枢 / 买卖点 / 背驰带上对应日期，与 `笔` / `线段` 的风格对齐。日期缺失时显示 `—`。

- **中枢**：`[idx] <start_date> → <end_date> zg=... zd=...`
- **买卖点**：`<type> (<date>): <msg>`
- **背驰**：`[✓/✗] <type> (<prev_date> → <curr_date>): <msg>`

## [1.14.2] (2026-06-16)

**缠论结果可视化字段增强** — 响应 [Discussion #2](https://github.com/handsomejustin/easy-tdx/discussions/2)，为缠论分析 JSON 输出（`ChanlunResult.to_dict()`）中的中枢 / 买卖点 / 背驰补上对应 K 线日期，方便前端/可视化工具直接用来标点画图。纯增量、向后兼容，不破坏任何已有 JSON 字段。

新增字段：

- **中枢 `zss`**：输出起始笔与结束笔的日期 `start_date` / `end_date`（第一笔起点 → 最后一笔终点）。
- **买卖点 `mmds`**：输出触发该买卖点的笔确认日期 `date`（买卖点确立时刻的 K 线日期）。
- **背驰 `bcs`**：输出背驰对照两笔的日期 `curr_date`（当前背驰笔）/ `prev_date`（对照基准笔）。

日期统一采用 `YYYY-MM-DD` 格式（与已有 `bis` / `xds` 输出一致），全部字段对 `None` 做了兜底。三层接入（Python API / CLI `easy-tdx chanlun` / Web `/chanlun/analyze`）同步生效，Web 接口直接返回新字段无需改动。

## [1.14.1] (2026-06-15)

**高级回测 ExecutionModel 路径 3 个真实数据兼容 Bug 修复** — 实测 `601088` 高级回测（方根滑点 + TWAP）暴露：权益曲线恒定、收益归零。根因为 ExecutionModel 路径与真实行情数据的格式/列名/类型脱节。

Bug 修复：

- **datetime 类型分歧（致命）**：`ExecutionModel` 把 `Trade.datetime` 转成 `int(YYYYMMDD)`，而 `PortfolioTracker` 用 df 原始 `Timestamp` 作为 `trade_map` 字典 key，导致 TWAP/VWAP/Limit 路径的交易**全部静默丢失**、权益曲线恒定、收益恒为 0%。修复：`Trade.datetime` 改用 df 原始值，与 `OrderSimulator` 一致。
- **volume 列名分歧**：`execution.py`/`orders.py` 仅认 `"volume"` 列，但真实行情（`get_security_bars`）列为 `"vol"`，导致滑点模型 volume 恒为 0、`SquareRootSlippage` 退化百分比模式、VWAP 退化为等权。修复：兼容 `vol`/`volume` 列名。
- **date/datetime 列名分歧**：日线 `get_security_bars` 返回 `date` 列，但 `BacktestEngine` 硬性要求 `datetime` 列，按文档直接跑日线回测会 `ValueError`。修复：`BacktestEngine.run` 入口缺 `datetime` 时由 `date` 派生，下游无感兼容。

为何此前未发现：`test_engine_with_twap` 仅断言「生成了交易」，未断言「交易实际影响了组合」；execution 单测用 int datetime 掩盖了类型分歧。本次新增 3 个回归测试编码「权益曲线随交易变化」「vol 列可读」「date 列可跑」契约，均经红灯验证（修复前精确失败）。

验证：全部 650 单测通过，backtest 模块 ruff + mypy strict 清洁，`examples/22_backtest_advanced/backtest_601088_advanced.py` 实测权益曲线不再恒定、高级档收益从假的 0% 修正为真实的 -3.57%。

## [1.14.0] (2026-06-15)

**新增新浪财报三表** — 三层接入（编程 API / CLI / Web API），独立数据源，无需连接 TDX 行情服务器。

- 新模块 `easy_tdx.sina`：`SinaClient().get_financial_report(code, report_type=, num=)` 返回 `DataFrame`（每行一期，列为科目名 + `{科目}_同比`）
- 三表：`lrb`（利润表）/ `fzb`（资产负债表）/ `llb`（现金流量表），report_type 支持中英文别名
- CLI：`easy-tdx f10 600519 [--type lrb|fzb|llb] [--num N]`（接管原 f10 占位符）
- Web：`GET /api/v1/sina/financial-report?code=&type=&num=`
- 标准库 urllib 实现，零新依赖
- 修复参考脚本 bug：`item_value` 字符串转 float（原 object 列无法数值计算）
- 大类标题行（如「流动资产」）保留为 None，完整反映报表结构
- `SinaError` 继承 `TdxError`，保证全局 `except TdxError` 覆盖

测试：`tests/unit/test_sina.py` 27 个离线用例（mock HTTP，零网络），覆盖三表解析、数值转换、报告期格式化、同比键、paperCode 推导、错误转换。

## [1.13.1] (2026-06-15)

**cninfo 公告检索 Bug 修复 + PDF 下载**（实测 `easy-tdx announcement 601088` 暴露的 3 个 Bug + 新增 PDF 下载功能）。

Bug 修复：

- `url` 404：原仅拼 `announcementId` 一个参数，补全 4 参数 `stockCode`/`announcementId`/`orgId`/`announcementTime`（少任一参数 404）
- `type` 列全 null：cninfo 对很多公告不填 `announcementTypeName`，回退到 `adjunctType`（如 "PDF"）
- 表格输出 `url` 被截断成 `https://www.cninfo.com.cn/new/`：`output._render_table` 对 object 列硬切 30 字符；新增 `_render_table_full`，`announcement --table` 专用不截断

新增功能 — PDF 下载：

- `CninfoClient.download_pdf(announcement, dest_dir=, filename=)`：接受 `Announcement` 或 DataFrame 一行，自动建目录，默认文件名 `{YYYYMMDD}_{announcement_id}.PDF`
- CLI：`--download N --download-dir DIR` 批量下载最新 N 条 PDF
- `Announcement` dataclass 扩展字段：`code`/`org_id`/`announcement_id`/`announcement_time`/`pdf_url`（`pdf_url` 为 `static.cninfo.com.cn` 直链）

测试：`tests/unit/test_cninfo.py` 24 → 35 个用例，新增 URL 4 参数、type 回退、pdf_url 构建、`download_pdf`（成功/无附件/建目录/Series 兼容/网络失败/自定义文件名）共 11 个场景。全部 621 单测通过，mypy strict + ruff 清洁。

## [1.13.0] (2026-06-14)

**新增巨潮公告检索** — 三层接入（编程 API / CLI / Web API），独立数据源，无需连接 TDX 行情服务器。

- 新模块 `easy_tdx.cninfo`：`CninfoClient().get_announcements(code, count=, page=)` 返回 `DataFrame[title, type, date, url]`
- CLI：`easy-tdx announcement 688017 [--count N --page N --table]`
- Web：`GET /api/v1/announcements?code=&count=&page=`
- 标准库 urllib 实现，零新依赖
- 沿用 #19 修复的 orgId 动态映射 + 三段硬编码 fallback（保证 601xxx 段可查）

## [1.12.0] (2026-06-14)

**新增 4 个技术指标（30 → 34）** — 按"语义空白"补齐三类现有指标库缺失的维度：止损位、机构成本价、趋势启动时机。均为纯 numpy 实现，零新依赖。

**新增指标**：

- **SAR 抛物线转向**（`high, low` → `SAR`）：基于 Wilder 加速因子的动态止损位，填补 32 个指标里"止损位"语义的空白。可直接喂给 `BacktestEngine` 做动态 `stop_loss`。实现含反转检测、AF 加速/封顶、SAR 不穿越前两根 K 线极值的限制。
- **VWAP 成交量加权均价**（`close, high, low, vol` → `VWAP`）：N 日滚动机构基准成本价，填补"机构成本"维度空白。用典型价格 `(H+L+C)/3` 加权，含除零保护（零成交量返回 nan）。
- **AROON 阿隆指标**（`high, low` → `AROON_UP, AROON_DOWN, AROON_OSC`）：用"N 周期内新高/新低距今多少根"识别趋势启动时机，与现有 DMI（判断趋势强度但滞后）互补而非冗余。
- **FK 趋势指标**（`close` → `FK`）：清理孤儿函数——`MyTT.FK` 此前已实现但未在 `indicator.py` 注册，用户通过 CLI/API 无法调用。现正式注册暴露。语义为 EMA(2) 是否突破斜率外推 EMA(42)，本质是动量偏离检测。

**架构**：所有新指标沿用现有 `IndicatorSpec` 注册模式，`compute_indicators()` / `get_stock_kline_with_indicators()` / CLI `easy-tdx indicator` 自动可用，无需改动调度层。

**除零与边界保护**：

- SAR：一字板/停牌（高低价相同）不崩溃、不产生 inf；空输入返回空数组
- VWAP：零成交量返回 nan（不产生 inf）；前 N-1 根为 nan（rolling 窗口）
- AROON：输出严格落在 [0, 100] 区间

**类型存根**：`MyTT.pyi` 同步补充 SAR/VWAP/AROON/FK 四个函数签名，mypy strict 零错误。

**测试**：新增 `tests/unit/test_mytt.py`，22 个用例覆盖三个新指标 + FK 的数值正确性、单边行情行为、除零/空输入边界。注册层端到端覆盖复用 `test_indicator.py::test_all_registered_indicators_run`。

## [1.11.6] (2026-06-13)

**CI 类型与格式修复** — 修复 CI 流水线 mypy strict（13 errors）和 ruff format（8 files）失败，全部为类型标注与存根问题，无运行时行为变更。

**mypy strict 修复（13 errors → 0）**：

- `portfolio/optimizer.py`：`register_optimizer` 装饰器返回类型从 `type[WeightOptimizer]` 改为 `Callable[[type[WeightOptimizer]], type[WeightOptimizer]]`，消除 4 个子类 "Too many arguments" 误报
- `factor/engine.py`：`_datetime_to_int` 用 `isinstance` 收窄替代 `object → int` 强转，消除 call-overload + no-any-return
- `backtest/orders.py` / `execution.py`：年化波动率 `np.sqrt()` 表达式用 `float()` 包裹，消除 no-any-return
- `factor/builtin/technical.py`：`MyTT.pyi` 的 `MACD` 存根删除错误的 `LOW/HIGH` 参数，与 `MyTT.py` 实际签名 `MACD(CLOSE, SHORT, LONG, M)` 对齐
- `pyproject.toml`：新增 scipy mypy override（`ignore_missing_imports`），统一处理可选依赖的 stubs 缺失，移除冗余 inline `type: ignore`

**ruff format**：8 个 test 文件统一格式化。

**测试**：564 passed, 0 failed；mypy 192 文件零错误；ruff check/format 全绿。

## [1.11.5] (2026-06-13)

**稳定性与代码质量修复** — 全项目代码审计 + 一个潜伏的 ping 崩溃 bug 修复。

**Bug 修复**：

- 修复 `easy-tdx ping` 在非交易时间（服务器握手阶段关闭连接）整个命令崩溃的问题。根因：`ping_host` 仅捕获 `OSError`，但握手期 `_recv_exact_sock` 抛出的 `TdxConnectionError`（继承自 `TdxError(Exception)` 而非 `OSError`）逃出捕获，经 `ping_all` 的 `fut.result()` 重新抛出，导致单台服务器不可用就拖垮整条测速命令。修复后符合 docstring 承诺"不可达服务器不包含在结果中"，并加防御层让 `ping_all` 对异常 future 容错跳过。
- 修复回测 `OrderSimulator._find_bar_index` 把 DataFrame 的 index label 当位置索引用的隐患。当传入 df 的 index 非默认 RangeIndex 时，`idxmax()` 返回的 label 与 `iloc[]` 期望的位置不一致，可能导致撮合取错 K 线。改用 `to_numpy().argmax()` 取真实位置。

**依赖与工程化**：

- scipy 隐式硬依赖声明：`factor/analysis.py` 的 Rank IC（spearman）通过 pandas lazy import scipy，干净环境必报 `ModuleNotFoundError`。新增 `science` 可选依赖组（`pip install easy-tdx[science]`），并在 spearman 分支加 try-import 友好报错（复用 `optimizer.py` 现有模式）。
- `mac/client.py` 板块 N 日涨跌幅排行中静默吞异常的 `except Exception: continue` 补上 `logger.debug` 日志，便于排查。
- `.gitignore` 补全 `.coverage`、`signals.json`。

**文档**：

- `CLAUDE.md` 架构章节更新：补全 `mac/`、`ex/`、`unified.py`、`portfolio/`、`factor/`、`offline/`、`screen/` 等子包，说明四套 client（Windows/macOS/扩展/macOS扩展）的 sync+async 镜像关系。

**测试**：564 passed, 0 failed（+8 新增：2 ping 容错回归、2 非连续 index 回归、4 既有覆盖增强）

## [1.11.1] (2026-06-12)

**量化因子引擎 + 组合管理 + 高级回测增强** — 三大新模块，补齐从因子研究到组合执行的完整量化链路。

**因子引擎（factor/）**：

- `Factor` ABC + 注册表模式（`@register_factor` 装饰器），19 个内置因子
- `FactorEngine`：单股多因子 / 截面批量 / 远期收益计算
- 因子类别：动量、波动率、质量、成交量、技术（桥接 MyTT）、缠论（桥接 ChanlunAnalyser）、价值（占位）
- 因子预处理管道：去极值（MAD）、标准化、排名归一化、填充缺失、正交化
- `FactorAnalyzer`：IC（Spearman）、分层收益（5 组）、换手率、衰减分析、完整报告

**组合管理（portfolio/）**：

- 4 种权重优化器：等权、因子加权、风险平价（逆波动率）、均值方差（scipy 可选）
- 风险模型：Ledoit-Wolf 收缩协方差、组合风险分解
- `RebalanceEngine`：多期调仓回测（周/月/季），100 股整手、佣金+印花税

**高级回测增强（backtest/）**：

- 4 种滑点模型：Fixed、Percent、SquareRoot（Almgren-Chriss）、Volume
- 4 种执行仿真：Immediate、TWAP、VWAP、Limit（限价单 + TTL）
- `AttributionAnalyzer`：成本归因、Brinson 归因（配置/选股/交叉）、因子归因
- 完全向后兼容（`BacktestEngine` 新增 `slippage_model` / `execution_model` 可选参数）

**CLI**：

- `easy-tdx factor list` / `factor analyze` — 因子列表和分析
- `easy-tdx pfactor backtest` — 组合因子选股回测

**测试**：556 passed, 0 failed（+176 新增）

## [1.10.5] (2026-06-12)

**Web API 全面补齐 + 稳定性修复** — 新增 18 个 REST 端点，Web API 与 CLI 接口覆盖对齐，修复多个生产环境问题。

- **板块分析（6 端点）**：板块列表、成分股、所属板块、板块摘要、涨幅排名、N日涨幅排行
- **资金/信息（3 端点）**：个股资金流向、个股信息快照、服务器交易时段
- **排行/竞价/异动（3 端点）**：分类排序行情列表、集合竞价、市场异动
- **扩展市场（4 端点）**：港股/美股/期货的 K 线、报价、分时、逐笔成交
- **技术指标（2 端点）**：指标列表、指标计算（POST）
- 新增 `AsyncMacClient` 依赖注入（`get_mac_client`），Web 层同时管理 TDX + MAC 双客户端连接
- 新增 `AsyncExTdxClient` 依赖注入（`get_ex_client`），可选启用扩展市场端点
- 新增 6 个 MAC 枚举转换器（BoardType/SortType/SortOrder/Category/ExMarket/FilterType）
- 新增 `DictResponse` 和 `ComputeIndicatorsRequest` schemas
- Web API 端点总数从 22 增至 40
- 修复 MAC 客户端连接失败时 12 个端点返回 `AttributeError`（500），现正确返回 503
- 修复扩展市场 dataclass 序列化时 `_raw: bytes` 字段导致 JSON 编码 500 错误
- 修复 `/redoc` 页面 404（CDN `redoc@next` 已失效），手动注册端点并锁定 `redoc@2.2.0` 稳定版

## [1.10.0] (2026-06-12)

**Web API 层** — 新增 FastAPI REST + WebSocket 服务，一键将 easy-tdx 暴露为 HTTP API。

- 新增 `src/easy_tdx/web/` 模块：app factory、6 个路由（market/bars/finance/block/chanlun/realtime）、Pydantic schemas、异常处理
- 新增 `easy-tdx serve` CLI 命令，支持 `--host`、`--port`、`--tdx-host`、`--reload` 参数
- REST 端点覆盖全部 `AsyncTdxClient` 方法（K线/报价/资金流向/板块/财务/缠论分析等）
- WebSocket 端点 `/ws/realtime/{symbol}` 支持实时行情订阅和多标的动态切换
- 自动生成 Swagger UI (`/docs`) 和 ReDoc (`/redoc`) 文档
- 可选依赖 `pip install easy-tdx[web]`，核心安装不受影响
- 20 个离线单元测试覆盖 schemas、路由注册、OpenAPI schema 生成、输入验证
- 修复 `deps.py` 中 `AsyncTdxClient` 在 `TYPE_CHECKING` 下导致运行时 `NameError`（500 → 正常启动）
- 修复 market/category 参数不支持小写（`sz`/`sh`）和非法值（`ZZZ`）导致 500 的问题，统一返回 400 Bad Request

## [1.9.10] (2026-06-11)

**板块 N 日涨跌幅排行** — 新增 `board-change-ranking` 命令，支持按行业/概念/风格板块计算指定日期前 N 个交易日的涨跌幅并排行。

- 新增 `MacClient.get_board_change_ranking()` / `AsyncMacClient` 同名异步方法
- 新增 CLI 命令 `easy-tdx board-change-ranking`，支持 `--type`、`--date`、`--days`、`--top`、`--asc` 参数
- 利用板块指数 K 线直接计算，无需逐个聚合成分股，效率远高于现有 `board-ranking`
- 支持指定截止日期（`--date YYYYMMDD`），周末/节假日自动回退到前一交易日
- 默认列出全部板块，`--top N` 截断前 N 个
- 12 个单元测试覆盖计算正确性、边界条件、排序方向

## [1.9.9] (2026-06-11)

**Bug 修复** — 修复并发扫描（`--workers`）在动态加载策略时静默返回空结果的问题。

- **根因**：`ProcessPoolExecutor` 将动态 `importlib` 加载的策略类 pickle 序列化后发送到子进程，子进程无法反序列化（模块未注册到 `sys.modules`），异常被 `except` 静默吞掉
- **修复**：`_scan_parallel` 改为传递策略文件路径（字符串），子进程内通过 `_load_strategy_class` 自行加载策略类
- 新增 `_get_strategy_file` 辅助函数：从类方法 `co_filename` 反查策略文件路径
- 新增回归测试 `TestParallelPickleFix`

## [1.9.8] (2026-06-11)

**CI 修复** — 修复 CI 流水线 ruff 和 pytest 配置问题。

- 修复 `MyTT.pyi` 类型存根文件行过长导致 ruff check 失败（`.pyi` 文件排除 ruff 检查）
- 添加 `pytest-asyncio` 依赖，修复 `test_realtime.py` 异步测试报错
- 修复 `test_backtest_engine.py` 中未使用变量 `result` 的 lint 警告
- 380 个测试全部通过，CI 全绿

## [1.9.7] (2026-06-11)

**CLI 全量集成** — v1.9.6 新增的 6 项功能全部暴露到 CLI，修复缠论多级别联立的 client 生命周期 bug。

- **`screen scan` 并发扫描**：新增 `--workers N` 参数，ProcessPoolExecutor 并行处理，推荐 4-8 进程，扫描速度提升 4-8 倍
- **`screen scan` 增量缓存**：新增 `--cache PATH` 参数，mtime 检测未修改的 `.day` 文件自动跳过
- **`backtest` 缠论桥接**：新增 `--chanlun-level LEVEL` 参数，引擎自动计算缠论分析并注入策略 `self.chanlun`
- **`portfolio` 组合回测**：新增 `easy-tdx portfolio` 命令，多标的共享资金池、均等分配、汇总绩效
- **`chanlun` 多级别联立**：新增 `--multi-level PERIOD` 参数，分析高级别最后一笔在低级别中的趋势方向、笔重叠、背驰条件
- **Bug 修复**：`cmd_chanlun.py` 中 `_run_multi_level` 在 `with` 块外使用 `client`，导致已关闭连接报错

## [1.9.6] (2026-06-11)

**工程质量全面升级** — 基于 Devin AI 代码审查的 12 项改进建议全部落地，覆盖 CI、回测引擎、缠论模块、扫描引擎和架构层面。

- **CI 覆盖率强制执行**：pytest 命令加入 `--cov-fail-under=50`，CI 不再空转
- **真实平均持仓天数**：`avg_holding_days` 从硬编码 5.0 改为 FIFO 配对计算，区分 int/Timestamp 两种日期格式
- **向量化 datetime 转换**：`_datetime_to_int` 用 `pd.to_datetime` 向量化替代 Python for 循环，大数组性能提升 100x+
- **止损/止盈实际执行**：`BacktestEngine` 新增 `_StopCondition` 跟踪，`OrderSimulator` 在每根 bar 检查 SL/TP 并触发平仓信号
- **缠论信号自动桥接**：`BacktestEngine` 新增 `chanlun_level` 参数，自动调用 `ChanlunAnalyser` 并注入策略，两模块正式打通
- **多标的组合回测**：新增 `PortfolioBacktestEngine`，支持多股票共享资金池、均等/自定义分配、资金加权绩效汇总
- **并发扫描**：`SignalScanner` 新增 `workers` 参数，`ProcessPoolExecutor` 并行处理，扫描速度提升 4-8 倍
- **增量扫描缓存**：新增 mtime 检测 + JSON 缓存文件，未修改的 `.day` 文件自动跳过
- **缠论增量更新**：`ChanlunAnalyser` 新增 `append_klines()` 方法，追加新 K 线后去重重新计算，支持实时场景
- **多级别联立增强**：`query_low_level_qs` 新增趋势方向、笔重叠、背驰条件判断字段
- **MyTT 类型存根**：新增 `MyTT.pyi`，50+ 指标函数的类型标注，mypy strict 零错误
- **实时推送框架**：新增 `realtime/` 模块，`EventBus` 发布/订阅 + `RealtimeStrategy` 基类，asyncio 事件驱动架构（API 骨架）
- 380 个测试通过，57.56% 覆盖率，mypy strict 150 文件零错误

## [1.9.5] (2026-06-10)

**OBV 能量潮趋势策略** — 新增 `obv_trend.py` 策略，基于 OBV 与其 30 日均线 MAOBV 的关系判断多空方向。

- 新增 `strategies/obv_trend.py`：OBV 能量潮趋势策略
- 入场条件：OBV 超过 MAOBV 达 2% 缓冲带 且 MAOBV 趋势向上（20 根确认）
- 出场条件：OBV 跌破 MAOBV，资金流向转空即离场
- MAOBV 趋势仅作入场过滤（确认趋势存在），出场只看 OBV/MAOBV 交叉信号
- 可调参数：`maobv_period`（30）、`maobv_lookback`（20）、`obv_buffer`（0.02）

## [1.9.4] (2026-06-10)

**Bug 修复** — 修复 `easy-tdx version` 命令硬编码版本号的问题，改为从 `pyproject.toml` 动态读取。

- 修复 `cmd_admin.py` 中 `version` 命令硬编码 `1.1.0` 的问题
- 版本号现在通过 `importlib.metadata` 从 `pyproject.toml` 动态获取，不再需要手动同步

## [1.9.3] (2026-06-10)

**新增 `run-all` CLI 命令** — 一行命令批量运行 strategies/ 目录下所有策略并排名，与 `run_all_strategies.py` 脚本功能完全一致。

- 新增 `easy-tdx run-all` CLI 命令，支持 `--count`、`--cash`、`--commission`、`--adjust`、`--period`、`--combo`、`--combo-mode`、`--show`、`--strategies-dir` 参数
- 绩效排名 + 综合评分 + 最佳策略交易明细，输出与脚本完全一致
- 支持多因子组合回测（`--combo 2 --combo 3`）和资金曲线图表展示（`--show`）
- 支持自定义策略目录（`--strategies-dir`）
- `run_all_strategies.py` 保持不变，两种方式并存

## [1.9.2] (2026-06-10)

**策略选股扫描器** — 新增 `screen` 命令组，用策略扫描全市场找出触发买入信号的股票，再做历史回测排名。纯离线数据，零网络 IO。

- 新增 `screen scan` CLI 命令：纯离线扫描本地 `.day` 文件，提取策略信号，输出 JSON
- 新增 `screen rank` CLI 命令：读取扫描结果，批量回测并按夏普/回撤等指标排名
- 新增 `src/easy_tdx/screen/` 模块：`SignalScanner`（扫描引擎）、`SignalRanker`（排名引擎）
- 两步走工作流：scan 几秒扫完全市场 → rank 对信号股做历史评估
- 支持 `--universe` 指定范围（all/sh/sz/自定义文件）、`--sort` 排序、`--names` 在线补名称
- 支持管道模式：`easy-tdx screen scan ... | easy-tdx screen rank --from - --table`
- 新增 20 个单元测试（离线，无需网络）

## [1.9.0] (2026-06-10)

**多因子组合回测** — 新增组合回测引擎，支持 2-3 个因子信号叠加，自动遍历所有组合寻找最优搭配。

- 新增 `backtest/combo.py` 模块：`CombinationRunner`、`extract_factor_signals`、`combine_masks`、`FactorSignals`、`ComboResult`
- 信号合并模式：AND（全部同意）、OR（任一同意）、MAJORITY（过半同意）
- CLI 新增 `--combo-strategies` 和 `--combo-mode` 参数，支持指定策略文件组合回测
- `run_all_strategies.py` 新增 `--combo` 和 `--combo-mode` 选项，自动遍历 C(N,2)/C(N,3) 所有组合并排名
- 核心思路：预提取 N 个因子信号（只跑一次）→ 遍历组合合并遮罩（纯 numpy）→ 批量回测排名
- 新增 14 个单元测试（离线，无需网络）
- 修复 MyTT `MFI()` / `CR()` 指标分母为零时的 RuntimeWarning

## [1.8.2] (2026-06-09)

**策略扩充 + 可视化** — 新增 6 个策略（共 15 个）、`--show` 资金曲线图、茅台 demo 截图。

- 新增 `run_all_strategies.py --show` 参数：自动弹出最佳策略资金曲线 vs 股价归一化对比图（matplotlib 双轴图 + 买卖点标记）
- 新增 `zhuoyao_momentum` 策略：ZHUOYAO 多周期共振（SHORT/TREND/MID 三重过滤）
- 新增 `dmi_trend` 策略：DMI/ADX 趋势强度跟踪
- 新增 `cci_breakout` 策略：CCI ±100 区间突破
- 新增 `mfi_volume` 策略：MFI 量价反转（带成交量权重的 RSI）
- 新增 `trix_cross` 策略：TRIX 三重平滑趋势交叉
- 新增 `mtm_momentum` 策略：MTM 动量零线穿越
- 新增 SH600519 贵州茅台 demo 截图

## [1.8.1] (2026-06-09)

**回测增强** — 批量策略对比脚本新增最佳策略完整交易明细输出；版本号统一为单一来源（`pyproject.toml`）。

- `run_all_strategies.py` 排名结束后自动输出最佳策略的绩效概要 + 最近 10 笔交易记录
- 修复 `turtle_breakout` 策略 `TAQ()` 返回 3 值但只解包 2 个的 bug
- 版本号统一：`pyproject.toml` 为唯一来源，`__init__.py` / `cli/__init__.py` / `docs/conf.py` 均动态读取

## [1.8.0] (2026-06-09)

**回测引擎** — 内置向量回测引擎，支持自定义策略回测和全策略批量对比。

- 新增 `backtest` 子包：Strategy 基类、BacktestEngine、OrderSimulator、PortfolioTracker、PerformanceAnalyzer
- 新增 `easy-tdx backtest` CLI 命令，支持 `--strategy-file`、`--cash`、`--commission`、`--adjust` 等参数
- 绩效报告包含 19 项指标：总收益率、年化收益、最大回撤、夏普比率、索提诺、卡玛、胜率、盈亏比等
- 新增 `strategies/` 目录，包含 9 个开箱即用的策略示例（MA/EMA/MACD/BOLL/RSI/KDJ/BIAS/海龟/量价）
- 新增 `run_all_strategies.py` 批量对比脚本，一键跑完全部策略并按收益率和综合评分排名
- 自带策略在 SZ 300308 上 3 年回测：收益率最高 1413%（expma_cross），综合最优 turtle_breakout
- 30+ 离线单元测试覆盖，零网络依赖

## [1.7.1] (2026-06-08)

**Bug 修复** — 修复缠论笔计算在持续下跌/上涨走势中因"分型陷阱"导致近期笔丢失的问题。

- 修复 `find_bis()` 贪心算法在密集交替分型场景下提前终止的 bug
- 根因：当异类型分型 gap=0 时，算法仍用更极端的同类型分型替换 start_fx，导致 right_kline_index 不断前推，后续所有异类型分型 gap 永远为 0
- 新增 `pending_opposite` 保护机制：存在未配对异类型分型时冻结替换，保留 start_fx 较前位置
- 影响范围：持续下跌/上涨中的高价股（如贵州茅台）或分型密度高的股票
- 新增回归测试 `test_fractal_trap_regression`

## [1.7.0] (2026-06-07)

**缠论技术分析模块** — 新增完整的缠论（ChanLun）计算引擎，通过 CLI 和 Python API 提供个股缠论分析。

- 新增 `chanlun` 子包：K线合并、分型识别、笔/线段/中枢/买卖点/背驰计算
- 新增 `easy-tdx chanlun` CLI 命令，支持 JSON/表格输出
- 新增 MACD 指标计算（纯 numpy，无额外依赖）
- 新增多级别联立分析（MultiLevelAnalyser）
- 计算管道：`DataFrame → K线合并 → 分型 → 笔 → 中枢 → 线段 → 买卖点 → 背驰`
- 49 个离线单元测试覆盖，零网络依赖

## [1.6.1] (2026-06-07)

**Bug 修复** — 修复 sync-all/sync-daily 对指数文件误用股票解析器导致垃圾日期的问题。

- 修复 `_fetch_all_daily_bars` 对指数文件（sh00/sh88/sh99, sz39）错误调用 `get_security_bars()` 的问题
- 指数文件现在正确使用 `get_index_bars()`（服务端响应每条记录多 4 字节上涨/下跌家数）
- 新增 `_is_index_code()` 辅助函数，根据市场和代码前缀判断证券类型

## [1.6.0] (2026-06-07)

**离线数据写入同步** — 从服务端获取最新日线数据并写入本地通达信 .day 文件，替代通达信内置下载功能。

- 新增 `offline sync-daily` CLI 命令：同步单只股票日线，自动增量/全量判断，支持分页获取完整历史
- 新增 `offline sync-all` CLI 命令：一键扫描沪深全市场 .day 文件并同步
- 新增 `write_daily.py` 模块：日线编解码（`encode_daily_bar`）、追加写入（`append_daily_bars`）、末尾日期检测
- 新增 `write_ex_daily.py` 模块：扩展市场日线写入（期货/港股，价格 float32）
- 新增 `write_min_bar.py` 模块：分钟线写入（.5/.lc1/.lc5 格式）
- 写入自动跳过重复日期，空文件自动全量下载，已有数据只做增量追加
- 50 个新增单元测试覆盖编解码 round-trip、追加去重、边界条件

## [1.5.0] (2026-06-02)

**离线数据 CLI 命令** — 新增 `offline` 命令组，无需网络即可通过 CLI 读取本地通达信数据文件。

- 新增 `offline home`：检测通达信安装目录
- 新增 `offline daily`：A 股日线数据（.day 文件）
- 新增 `offline min`：分钟线数据（.5/.lc1/.lc5 文件，`--type` 指定格式）
- 新增 `offline ex-files`：列出扩展市场可用日线文件
- 新增 `offline ex-daily`：扩展市场日线数据（期货/港股/外盘）
- 新增 `offline gbbq`：股本变迁数据
- 新增 `offline financial`：历史财务数据
- 新增 `offline blocks`：自定义板块数据

## [1.4.3] (2026-05-28)

**30日乖离率信号指标** — 新增 BIAS_SIGNAL 指标，在标准乖离率基础上叠加短/长信号线，通过三者位置关系判断趋势方向和转折点。源自通达信经典指标。

- 新增 `BIAS_SIGNAL` 指标：输出 BS_X/BS_SMA/BS_LMA 三条线
- CLI: `easy-tdx indicator BIAS_SIGNAL -m SH -c 600519 --table`
- Python API: `indicators=["BIAS_SIGNAL"]`
- 详见 [30日乖离率信号指标详解](docs/indicator-bias-signal.md)

## [1.4.2] (2026-05-28)

修复 1.4.1 发布遗漏：MyTT.py 中 ZHUOYAO 函数定义未包含在 1.4.1 的 PyPI 包中。

## [1.4.1] (2026-05-28)

**捉妖大师指标** — 新增 ZHUOYAO 多周期涨幅共振指标，通过 20/60/120 日涨幅及指数平滑判断短中长线趋势是否同向，用于筛选趋势刚启动的强势股。

- 新增 `ZHUOYAO` 指标：输出 ZY_LONG/ZY_MID/ZY_SHORT/ZY_TREND 四条线
- CLI: `easy-tdx indicator ZHUOYAO -m SH -c 600519 --table`
- Python API: `indicators=["ZHUOYAO"]`
- 详见 [捉妖大师指标详解](docs/indicator-zhuoyao.md)

## [1.4.0] (2026-05-28)

**技术指标计算** — 集成 [MyTT](https://github.com/mpquant/MyTT) 麦语言指标库，支持 30 个常用技术指标，一步获取 K 线 + 指标值。

- 新增 `indicator.py` 核心模块：注册表驱动的指标调度，`compute_indicators()` 纯计算无 IO
- 新增 `MacClient.get_stock_kline_with_indicators()` / `AsyncMacClient` 同名方法
- 新增 `UnifiedTdxClient.get_stock_kline_with_indicators()` / `AsyncUnifiedTdxClient` 同名方法
- 新增 CLI 命令 `easy-tdx indicator` 和 `easy-tdx indicator-list`
- 自动获取 200+ 条历史数据预热 EMA，用户只需指定返回条数
- 支持的指标：MACD, KDJ, RSI, BOLL, DMI, ATR, WR, CCI, BIAS, OBV, VR, EMV, MFI, BRAR, ASI, TRIX, DPO, MTM, ROC, EXPMA, BBI, PSY, DFMA, CR, KTN, XSII, MASS, TAQ

## [1.3.1] (2025-05-15)

- 新增 `board-summary` 和 `board-ranking` CLI 命令
- 新增 `get_board_summary()` 板块汇总（成交额、主力净流入、涨跌家数）
- 新增 `get_board_ranking()` 板块涨跌幅排行榜

## [1.3.0] (2025-05-12)

- 新增 MAC 协议客户端 `MacClient` / `AsyncMacClient`（端口 7709）
- 新增扩展市场客户端 `MacExClient` / `AsyncMacExClient`（端口 7727）
- 新增统一客户端 `UnifiedTdxClient` 自动路由 A 股 / 扩展市场
- 新增板块、资金流向、集合竞价、异动、个股特征等数据接口
- 新增 `easy-tdx` CLI 工具，默认 JSON 输出

## [1.2.1] (2025-04-20)

- 离线数据读取模块（日线、分钟线、板块、财务）
- 除权除息、股本变迁读取

## [1.0.0] (2025-03-01)

- 首个正式版本
- TdxClient / AsyncTdxClient 标准协议客户端
- K 线、实时报价、分时、逐笔成交、财务数据
