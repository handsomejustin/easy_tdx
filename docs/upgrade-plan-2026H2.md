# easy-tdx 升级开发计划（2026 H2）

> **执行进度**（2026-09-01 最终更新：全部阶段完成）：
> - ✅ **P0 v1.24.0**——QFQ 对拍验证体系、回测任务 SQLite 持久化 + 导出、品种感知费率
> - ✅ **P1 v1.25.0**——Walk-Forward 引擎、适配性评估、一条龙评估、综合评分、评级后端化、多 seed 验证 + 晋级门槛、寻优两段式加速（指标缓存 + 进程并行）
> - ✅ **P2 v1.26.0**——DuckDB K 线仓库 + provisional 状态机 + 增量同步 + 健康自检 + CLI `warehouse` 命令组（P2-2 评级后端化已随 1.25.0 提前交付）
> - ✅ **P3 v1.27.0**——通达信公式解析器（tokenizer + AST + 白名单求值，无 Python eval）+ 公式三通道（CLI `formula` / REST `/formula/*` / Python API）+ 轮动组合引擎（排名换仓 + 槽位等额 + 自动补位 + 止盈止损，REST `/backtest/rotation/run/async`）
> - ✅ **P1 前端补全（随 1.27.0）**——回测页「附加分析」开关：WF 逐窗柱状图 + 一条龙评估报告卡（评分分项/高适配徽标/买入持有基准对比/8 项适配检查），复用同一份内联行情并行执行
> - ✅ **P4（部分）v1.27.0**——Docker Compose 部署 + `scripts/verify_ci.sh` 一键门禁。**未做**：Playwright E2E（需前端基建，独立排期）、WebSocket 实时推送联动 EventBus（README 既有 TODO，与本计划无耦合）、引擎逐 bar 循环向量化（寻优加速的下一步方向）——三项已整理为独立排期提示词
>
> 实测备注（诚实数据）：
> - 寻优加速——指标缓存命中率 41.7%（36 点网格）但墙钟 ~1.01x（本引擎指标层非瓶颈，逐 bar Python 循环才是）；进程并行 4 workers 约 2x。后续更大加速的方向是引擎循环向量化。
> - 最终回归：1252 个单元测试全过（基线 1078），ruff / ruff format / mypy strict（245 文件）全绿。
>
> 依据：对两个基于 easy-tdx 的下游项目的逆向调研
> - [mvpbaggio/backtest-system](https://github.com/mvpbaggio/backtest-system)（v1.4，MIT）— 回测框架，运行时依赖 easy-tdx（行情拉取、PerformanceAnalyzer、MyTT、Param 注册表思路）
> - [kendev93/indicator-lab](https://github.com/kendev93/indicator-lab)（AGPL-3.0）— 指标实验室，参考改写了 easy-tdx 的 TDX 协议层与 `.day` 格式（见其 THIRD_PARTY_NOTICES.md），运行时不依赖
> 调研日期：2026-09-01，基线版本 v1.23.3

---

## 一、核心洞察

两个下游项目**独立地**在补 easy-tdx 的同一类空白，这比任何单个功能都更有信号价值：

1. **防过拟合验证是最大空白**。backtest-system 自研了严格 7 窗 Walk-Forward；indicator-lab 自研了「策略适配性评估」（train/val/test 三段 + 8 项检查）。两条路殊途同归——easy-tdx 的回测引擎很全（滑点/执行仿真/归因/寻优/组合），但**没有任何样本外验证工具**，下游只能自己造。
2. **统一 K 线落盘是第二空白**。easy-tdx 的缓存是碎片化的（股票列表缓存、best_host、进程内 XDXR 字典、扫描 JSON 增量缓存），没有统一磁盘 K 线层；indicator-lab 为此建了 DuckDB 仓库，backtest-system 为此自建 cache/ 目录 + 7 天更新 + 数据自检。
3. **QFQ 质量收到了直接差评**。backtest-system README 明确弃用 easy-tdx 的 QFQ，理由是「茅台出现负价、浦发除权方向算反」，随后自研了板块感知阈值的跳空检测前复权。本地兜底 `mac/adjust.py` 已存在，但缺少对拍验证体系，无法自证可靠。
4. **降低使用门槛有巨大空间**。indicator-lab 的通达信公式解析器（粘贴公式自动识别参数/命名信号）直接命中中国最大的量化用户群体——写惯通达信公式的股民，而 easy-tdx 目前要求写 Python。

---

## 二、借鉴点清单（按价值排序）

| # | 借鉴点 | 来源 | easy-tdx 现状 | 价值 |
|---|--------|------|--------------|------|
| 1 | Walk-Forward 样本外验证（7 窗、每窗独立开仓防跨窗重复计收益） | backtest-system `walkforward.py` | ❌ 无 | ★★★★★ |
| 2 | 策略适配性评估（60/20/20 三段独立回测 + 8 个可解释检查项 + 滚动适配过滤防未来泄漏） | indicator-lab strategy-fitness | ❌ 无 | ★★★★★ |
| 3 | 综合评分 + 一条龙评估（score：收益50/夏普15/回撤10/Sortino5/WF20；evaluate：拉数/对齐/选模式/对比基准引擎） | backtest-system `benchmark.py` | ❌ 无 | ★★★★☆ |
| 4 | 通达信公式解析器（`名称:=数值` 参数识别、命名布尔输出作信号、命名数值用于排序/卖出） | indicator-lab | ❌ 无（34 指标需改源码新增） | ★★★★☆ |
| 5 | 本地数据仓库（增量导入、源只读、在线补缺不覆盖、provisional/completed 状态机） | indicator-lab（DuckDB） | ❌ 无统一 K 线磁盘缓存 | ★★★★☆ |
| 6 | 动态组合轮动回测（按指标排序 + 固定槽位等额 + 卖出自动补位 + 日/周/月刷新 + 槽内止盈止损） | indicator-lab portfolio-backtest | ⚠️ 有组合回测/再平衡，但无「排名轮动」模式 | ★★★★☆ |
| 7 | 两段式引擎协议（指标计算缓存 与 信号组合 解耦，迭代快 10 倍） | backtest-system `register_two_stage` | ❌ 优化器每组参数全量重算 | ★★★☆☆ |
| 8 | 多 seed 验证 + 晋级门槛（正收益比例/夏普/WF/交易数四门槛） | backtest-system `engine_iter.py` | ❌ 无 | ★★★☆☆ |
| 9 | QFQ 互检：NONE 原始价 + 向下跳空检测（主板10%/双创20%/北交所30% 阈值） | backtest-system `data_source.py` | ⚠️ 有 XDXR 公式法本地兜底，无对拍 | ★★★☆☆（质量修复） |
| 10 | 真实出场模型：吊灯 ATR14×3 + 保本 BE + 移动止盈 TP、跳空按更差开盘成交 | backtest-system | ⚠️ 有订单/滑点/执行仿真，出场模式较简单 | ★★★☆☆ |
| 11 | 品种感知费率（股票 vs ETF/B 股：最低佣金、印花税差异） | indicator-lab | ⚠️ 有费率参数，非品种感知 | ★★☆☆☆ |
| 12 | 任务体验：进度、失败/跳过摘要、JSON/CSV 导出 | indicator-lab | ❌ 任务仅内存、重启即清、无导出 | ★★★☆☆ |
| 13 | Playwright E2E（mock API、不依赖真实数据）+ verify_ci.sh + git hooks | indicator-lab | ❌ 前端无 E2E | ★★☆☆☆ |
| 14 | Docker Compose 部署 | indicator-lab | ❌ 无 | ★★☆☆☆ |
| 15 | 后端数据评级（S-D 五档六维加权，现仅存 web-ui/src/grading 前端 TS） | （自补，非下游首创） | ⚠️ 前端有、Python/CLI/REST 无 | ★★★☆☆ |

**不借鉴**：两个项目的回测执行内核（easy-tdx 引擎更全：TWAP/VWAP、Brinson 归因、DSL、缠论桥接）；indicator-lab 的 `at_least` 条件组合（`combo.py` 已有 MAJORITY）；图表截 220 根方案（前端已有自己方案）。

---

## 三、升级开发计划

### P0 — 信任与持久化（v1.24.0，约 1~2 周）

**目标：先修质量口碑，再谈新功能。**

| 任务 | 内容 | 验收标准 |
|------|------|---------|
| P0-1 QFQ 对拍验证体系 | ① 用 `adjust.py` 公式法与 backtest-system 跳空检测法做双引擎互检，不一致即告警；② 建立「已知除权案例」回归集（茅台/浦发等重度除权股）；③ `has_bad_prices` 从兜底升级为所有 QFQ 出口（CLI/Web/unified）的强制门禁，失败自动降级本地重算并标记 | 案例集全过；任何出口不再可能出现负价/方向反转；新增 `tests/test_qfq_crosscheck.py` |
| P0-2 回测任务持久化 | SQLite `~/.easy_tdx/tasks.db`（复用 watchlist.db/strategies.db 模式），任务状态/结果落盘，serve 重启不丢；REST 增加 JSON/CSV 导出端点 | 重启 serve 后 /compare 仍能看历史任务；可下载结果文件 |
| P0-3 真实平均持仓天数 | 去掉 `performance.py` 中 `avg_holding_days = 5.0` 的固定值，从成交记录真实统计 | 单测覆盖多笔开平仓场景 |
| P0-4 品种感知费率 | 费率模型按品种区分（股票：佣金万2.5~万3 最低5元+印花税卖出千1；ETF：佣金更低、免印花税；B 股单独口径） | 回测引擎按 symbol 自动套用，可覆盖 |

### P1 — 防过拟合验证链（v1.25.0，约 2~3 周）⭐ 主打版本

**目标：补上两个下游都在自己造的最大空白，让「回测好」升级为「样本外也好」。**

| 任务 | 内容 | 验收标准 |
|------|------|---------|
| P1-1 Walk-Forward 引擎 | 新增 `backtest/walkforward.py`：后 70% 切 N 窗（默认 7）严格样本外，**每窗独立开仓**（防跨窗重复计收益，backtest-system v1.2.1 的教训）；输出逐窗收益曲线 + 窗间稳定性指标；接入 CLI `easy-tdx backtest ... --wf` 与 REST `/backtest/wf/run/async` | 与 backtest-system 对齐的窗独立语义；Web 前端展示逐窗柱状图 |
| P1-2 策略综合评分 | `backtest/scoring.py`：score_strategy() 0-100 加权（收益 50 / 夏普 15 / 回撤 10 / Sortino 5 / WF 稳定性 20），与前端现有 S-D 评级打通（评级后端化一并完成，见 P2-2 可提前） | CLI/Web 均输出评分与分项 |
| P1-3 适配性评估 | `backtest/fitness.py`：train/valid/test（默认 60/20/20）三段独立回测 + 可解释检查项（收益一致性、回撤一致性、交易数充分性、胜率区间、参数敏感性等 8 项），≥75% 通过且样本达标 → 「高适配」标记；支持**滚动适配过滤**（仅用早于当天的已平仓数据，杜绝未来数据泄漏） | Web 策略库/对比页显示适配徽章；可解释报告 |
| P1-4 一条龙评估 | `evaluate_strategy()`：默认随机抽样股票池（固定 seed 可复现）→ 对齐 → 自动选出场模式 → 与基准引擎（买入持有 + MyTT MACD）同规则对比 | 一条命令出完整对比报告 |
| P1-5 两段式寻优加速 | 优化器支持指标缓存复用：参数只影响信号组合层时，指标层计算一次（backtest-system 实测快 10 倍） | 网格寻优基准测试提速 ≥3 倍 |
| P1-6 多 seed 验证 + 晋级门槛 | `run-all` / 优化器输出增加多随机种子组合验证；晋级门槛四项（正收益比例/夏普/WF/交易数）可配置 | 报告含跨 seed 稳定性列 |

### P2 — 本地数据仓库（v1.26.0，约 2~3 周）

**目标：把碎片化缓存升级为统一数据底座，服务全市场扫描/因子/回测的提速。**

| 任务 | 内容 | 验收标准 |
|------|------|---------|
| P2-1 K 线仓库 | 新增 `warehouse/` 模块（存储引擎选 DuckDB，零服务、列存、SQL 友好）：`easy-tdx warehouse sync`（全量/增量）、源只读、在线补缺不覆盖、按品种价格/成交量系数；**provisional 状态机**（15:05 前的今日数据标记临时，筛选/回测默认忽略，收盘后转 completed） | 二次 sync 增量；断网可用；screen/factor/pfactor 可切 `--source warehouse` |
| P2-2 评级后端化 | `web-ui/src/grading/`（engine.ts/thresholds.ts）移植为 Python `backtest/grading.py`，CLI `--grade`、REST 返回 grade 字段；前端改为消费后端结果（保留前端兜底） | API/CLI 输出 S-D；与前端旧实现结果一致率 100%（对拍单测） |
| P2-3 仓库健康自检 | 数据自检命令：缺口检测、异常跳变检测（复用 P0-1 跳空检测）、最新度报告 | `easy-tdx warehouse check` |

### P3 — 公式与轮动（v1.27.0，约 3~4 周）

**目标：把「写通达信公式」的庞大用户群接进来。**

| 任务 | 内容 | 验收标准 |
|------|------|---------|
| P3-1 通达信公式解析器 | `indicator/formula.py`：解析通达信/麦语言公式，自动识别 `名称:=数值` 参数、命名布尔输出→信号、命名数值→排序/排序卖出字段；内置函数映射到 MyTT；安全除零、无未来数据、数据不足跳过 | 一批典型公式（含用户常见主力/洗盘类指标）解析通过并可直接回测 |
| P3-2 公式三通道接入 | CLI `easy-tdx formula screen/backtest`、REST `/formula/compute`、Web 新页面（粘贴公式 → 选股/回测一体） | 三通道行为一致 |
| P3-3 轮动组合引擎 | `backtest/rotation.py`：按指标排序选股 + 固定槽位等额 + 卖出自动补位 + 日/周/月刷新 + 槽内止盈止损/指标阈值卖出/指标比较卖出 | CLI/REST/Web 均可跑；与单标的回测同一套绩效输出 |

### P4 — 工程化（滚动进行）

| 任务 | 内容 |
|------|------|
| P4-1 Playwright E2E | mock API 的前端 E2E（不依赖真实行情/网络），纳入 CI |
| P4-2 WebSocket 实时联动 | `/ws/realtime/{symbol}` 接通 `realtime/EventBus`（README 已自认未联动；两个下游都没碰实时，这是 easy-tdx 的独有优势区，应当做实） |
| P4-3 Docker Compose | 一键起 serve + Web UI 的部署方案 |
| P4-4 verify_ci 风格脚本 | 一条命令跑完 ruff/mypy/pytest/前端 typecheck+build/E2E，可安装 git hooks |

---

## 四、版本节奏与依赖关系

```
v1.24.0 (P0) ──→ v1.25.0 (P1 防过拟合链，依赖 P0-4 品种费率)
                └→ v1.26.0 (P2 数据仓库，与 P1 可并行启动，P2-2 建议提前到 P1 一起做)
                      └→ v1.27.0 (P3 公式+轮动，依赖 P2-1 仓库提速全市场公式选股)
P4 工程化滚动穿插。
```

**成功指标**（对外可宣传）：
- v1.25 后：官方提供 WF + 适配性双验证，下游不再需要自造防过拟合轮子；
- v1.26 后：下游不再需要自建数据层（backtest-system 的 cache/、indicator-lab 的 DuckDB 均可换成 easy-tdx 仓库）；
- v1.27 后：通达信公式用户零代码进入回测。

---

## 五、风险与注意

1. **P3 公式解析器工作量大**：通达信公式方言庞杂（函数集、隐式循环语义），建议首版只支持「日期序列 + 常用函数白名单」，明确不支持清单，渐进扩充。indicator-lab 的实现可作参考（注意其 AGPL 许可——**只看思路不抄代码**，避免传染）。
2. **DuckDB 引入新增运行时依赖**：当前核心依赖仅 3 个是卖点。建议放入 optional-dependencies `[warehouse]` 组，import 惰性加载。
3. **WF 每窗独立开仓**是 backtest-system 踩过的坑（v1.2.1 修复），实现时直接采用正确语义，勿重蹈覆辙。
4. **向后兼容**：新增能力全部走可选参数/可选依赖，默认行为不变；v1.24 的 QFQ 门禁若触发降级，需在输出中显式标记（grade 字段），不静默。
