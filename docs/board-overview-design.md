# 行业总览 / 概念总览 页面设计（v1 草案）

> 目标：在 WebUI 左侧导航新增「行业总览」「概念总览」两个栏目，提供全部行业/概念板块的行情总览、
> 实用统计与板块异动监控；点击板块复用首页 `BoardDialog` 弹窗（左：分时/日K，右：成分股列表）。

---

## 1. 现状盘点（设计依据，全部为已验证的现成能力）

### 1.1 后端可复用接口（`src/easy_tdx/web/routers/board_mac.py`，前缀 `/api/v1`）

| 端点 | 能给什么 | 成本 |
|---|---|---|
| `GET /board-mac/list?board_type=HY\|HY2\|GN\|FG\|DQ&sort_column=…` | 全量板块列表：`market, code(881xxx/885xxx), name, price, pre_close, sort_value, 领涨股6字段(symbol_*)`。行业(HY)约 86 个、概念(GN)约 270–500 个；每页 150，自动翻页。排序键支持 `SPEED / CHANGE_3D / 5D / 10D / 20D / 60D / YTD` | 低（1–2 页/次） |
| `GET /board-mac/members?board_symbol=881001&count=120&sort_type=CHANGE_PCT` | 板块成分股 + 全量报价（自动 80/页翻页），弹窗已在用 | 低 |
| `GET /board-mac/summary?board_symbol=…` | `member_count, amount, vol, main_net_amount, main_net_3d/5d, up_count, down_count, members` | 高（每板块一次，概念 300+ 不可全量） |
| `GET /board-mac/ranking?board_type=…&sort_by=main_net_amount&top_n=10` | 资金/成交/涨跌幅榜（内部逐板块 summary） | 中，必须限 `top_n` |
| `GET /board-mac/change-ranking?board_type=…&days=20` | N 日区间涨幅榜（走板块指数日K） | 低 |
| `GET /market/stat` | 全市场上涨/下跌/平盘/涨停/跌停家数（880005/880001/880006） | 低 |
| `GET /minute` `/bars`（SH+88xxxx） | 板块指数分时/日K，弹窗已在用；客户端已内置换机容错 | 低 |
| `GET /market/session` | 交易时段判定，用于启停自动刷新 | 低 |

**口径注意（Issue #53）**：`sort_column=CHANGE_PCT` 时 `sort_value` 恒为 0；当日涨跌幅必须由
`price / pre_close - 1` 自行计算。其余排序键的 `sort_value` 即该指标值。

### 1.2 前端可复用资产（`web-ui/src/`）

| 资产 | 位置 | 复用方式 |
|---|---|---|
| `BoardDialog.vue` 板块弹窗 | components | **原样复用**：头部 SSE 实时报价+加/移自选；左侧分时(`IntradayChart`)/日K(`StockKline`) tab；右侧成分股涨跌榜（用户所称"下拉框"），点成分股可再叠 `StockDialog` |
| `StockDialog.vue` 个股弹窗 | components | 原样复用（成分股点击穿透） |
| 自选股体系 | stores + `watchlist.py` | 已支持板块（WatchlistView 板块行开 BoardDialog），板块行可直接加"加自选"星标 |
| ECharts 封装 | `echarts-setup.ts` | 已注册 Bar/Heatmap 等；红涨绿跌 `UP_COLOR='#ef4146'` / `DOWN_COLOR='#18a058'` |
| API 封装 | `api.ts`（`BASE='/api/v1'` + 统一错误解析） | 新增 2–3 个 fetch 函数 |
| 导航/路由 | `App.vue:26-43` + `router.ts:21-40` | 「行情」分组下加两个 RouterLink + 两条路由 |

**结论：后端仅缺一个"多指标合并"端点，前端为本需求的全部工作量主体。**

---

## 2. 总体设计

```
路由与导航（行情分组）
  /industries  行业总览  ─┐
  /concepts   概念总览  ─┴─ 共用 BoardOverviewView.vue，路由 props 区分 board_type
                           行业页额外提供 HY(一级)/HY2(二级) 切换
```

新组件（建议 4 个，均放 `components/`）：

- `BoardStatStrip.vue` — 顶部统计条（板块广度 + 全市场涨跌家数 + 涨跌幅分布直方图）
- `BoardTiles.vue` — 热力图模式（CSS Grid 色块，不用 ECharts，500 块内 DOM 足够快）
- `BoardRankRail.vue` — 右侧栏：涨幅/跌幅/涨速(异动) 榜 + 翻红翻绿时间线 + 资金榜(懒加载)
- `BoardOverviewView.vue` — 主视图：统计条 + [热力图|表格] 切换 + 右栏 + 弹窗编排

主表格直接内嵌在 View 中（与 DashboardView 同风格），不再抽组件。

---

## 3. 功能设计

### 3.1 页面信息架构（自上而下）

1. **统计条**：一眼判断今天板块层面强弱
2. **工具行**：视图切换 / 排序 / 搜索 / 自动刷新开关
3. **主区**：热力图（默认）或 全量表
4. **右栏**：榜单 + 异动（热力图模式下承担"看榜"职责，表格模式下可折叠）

### 3.2 统计条（BoardStatStrip）

数据源：1 次 `/board-mac/list`（默认排序）+ 1 次 `/market/stat`，全部前端聚合。

| 指标 | 计算 | 说明 |
|---|---|---|
| 板块总数 / 上涨 / 下跌 / 平盘 | 按 `change_pct` 正负统计本类型板块 | 如「86 个板块 · 52▲ / 30▼ / 4—」 |
| 板块涨幅中位数 | median(change_pct) | 比均值抗极值 |
| 全市场涨停/跌停家数 | `/market/stat`（×10 还原） | 判断赚钱效应 |
| 涨幅分布直方图 | change_pct 分桶(±1% 一档，截断 ±5%) 小柱图 | ECharts Bar，点击桶可过滤主区（P2） |

### 3.3 主区一：热力图模式（默认）

- **布局**：CSS Grid 自适应列（tile 最小宽 ~104px），按当前排序降序排列。
- **着色**：红涨绿跌，透明度随 `|change_pct|` 分 5 档增强（复用 UP/DOWN_COLOR）。
- **tile 内容**：板块名（超长省略）+ 当日涨跌幅；≥140px 宽度时追加领涨股名+其涨幅。
- **交互**：hover 显示 tooltip（代码/价格/涨跌幅/领涨股）；**单击打开 BoardDialog**；
  右键或 tile 上的 ★ 加自选（P2）。
- **概念页适配**：500 tile 时顶部加搜索框联动高亮/过滤，tile 缩小至 ~88px。

> 为什么不用 ECharts heatmap/treemap：treemap 未注册、treemap 按市值定容缺少廉价数据源
> （逐板块 summary 不可行），等宽色块已满足"扫一眼谁强谁弱"，且交互实现最简单。

### 3.4 主区二：表格模式（全量、可排序）

列定义（行业页）：

| 列 | 来源 | 备注 |
|---|---|---|
| 名称 / 代码 | list | 点击行 → BoardDialog |
| 最新价 | list.price | |
| **涨跌幅** | price/pre_close | 默认排序列，红绿色阶背景 |
| 涨速 | list(sort_column=SPEED).sort_value | 盘中异动核心 |
| 3日 / 5日 / 20日 / YTD | list(对应 sort_column).sort_value | 见 3.7 合并策略 |
| 轮动标签 | 前端规则（3.6） | 「反弹 / 走强 / 回调 / 补跌」 |
| 领涨股(+涨幅) | list.symbol_* | 点领涨股 → StockDialog（stopPropagation） |
| 主力净额 | `/board-mac/ranking` 合并（懒加载，见 3.7） | 可空 |
| ★ | 自选 | 复用 watchlist API（P2） |

表格排序纯前端（数据已全量在内存），不再发请求。行业 86 行、概念 ≤500 行，无需虚拟滚动。

### 3.5 右栏：榜单 + 板块异动（BoardRankRail）

1. **涨幅榜 Top10 / 跌幅榜 Top10**：前端内存排序，随刷新同步。
2. **涨速榜 Top10**（"板块异动"主入口）：`sort_column=SPEED` 的 `sort_value`，
   `|speed| ≥ 0.5%/5min` 的条目加闪烁高亮；点击直达 BoardDialog。
3. **翻红/翻绿时间线**：前端对相邻两次快照做 diff，`change_pct` 由负转正记「翻红」、
   正转负记「翻绿」，按时间倒序展示（保留最近 30 条）。这是最低成本的"板块轮动监控"。
4. **主力资金榜 Top10**（懒加载 tab）：首次展开才调 `/board-mac/ranking?sort_by=main_net_amount&top_n=10`，
   每 5 分钟刷新一次（接口较贵）。
5. **轮动信号卡**（P2）：超跌反弹聚集度（当日↑ 且 20日↓ 的板块数）等汇总提示。

### 3.6 轮动标签规则（表格列 + tile 角标）

前端基于已合并的多周期涨幅做简单规则标注（阈值可调，初版取 1%）：

| 标签 | 条件 | 含义 |
|---|---|---|
| 超跌反弹 | 当日 > +1% 且 20日 < -3% | 前期弱势，今日异动 |
| 趋势走强 | 当日>0 且 3日>0 且 5日>0 | 多周期共振向上 |
| 高位回调 | 当日 < -1% 且 20日 > +5% | 强势板块补跌 |
| 趋势走弱 | 当日<0 且 3日<0 且 5日<0 | 多周期共振向下 |

规则透明、可解释，不引入额外请求。

### 3.7 数据获取与刷新策略

**合并请求（关键设计）**：页面一次刷新需要 6 种排序的 list（当日、涨速、3日、5日、20日、YTD）。
前端直连将产生 6–12 个 MAC 请求/次。因此新增一个后端聚合端点：

```
GET /api/v1/board-mac/overview?board_type=HY&metrics=speed,3d,5d,20d,ytd
→ {
    board_type: "HY",
    ts: 1725400000,
    rows: [{
      market: 1, code: "881106", name: "种植业",
      price: 1039.93, pre_close: 1031.20, change_pct: 0.846,   // 服务端算好
      speed: 0.32, chg_3d: 2.1, chg_5d: -0.8, chg_20d: 6.3, chg_ytd: 14.2,
      leader_code: "600xxx", leader_name: "xxx", leader_change_pct: 10.02
    }, ...]
  }
```

- 服务端并发拉取各 sort_column 的 list 后按 code 归并，任一指标缺失置 null（不阻塞整体）。
- **服务端缓存 15s**（TTL），多人/多页共享，保护 MAC 服务器。
- 前端 30s 轮询（仅交易时段，`/market/session` 判定），手动 ⟳ 随时可用；页面不可见时暂停
  （`document.visibilitychange`）。
- 降级：`/board-mac/overview` 不可用时前端回退为直连 6 次 `/board-mac/list` 并归并（同口径函数复用）。

**懒加载项**：主力资金榜（首次展开）、板块弹窗内容（点击时，BoardDialog 自理）。

### 3.8 行业页 vs 概念页差异

| 维度 | 行业总览 (`HY`) | 概念总览 (`GN`) |
|---|---|---|
| 板块数量级 | ~86 | ~270–500 |
| 二级切换 | 一级(HY) / 二级(HY2) toggle | 无 |
| 搜索框 | 有（按名/代码） | **显著位置**，支持拼音/关键词过滤 |
| 热力图 tile | 104px | 88px |
| 其余（统计条/榜单/异动/弹窗/刷新） | 完全一致 | 完全一致 |

同一组件路由 props 驱动，后续 `FG`(风格)/`DQ`(地域) 仅需在 App.vue 加入口 + 传 props。

### 3.9 板块弹窗（点击板块）

**原样复用 `BoardDialog.vue`**（与首页体验一致）：

- 头部：板块名 + SSE 实时报价 + 加/移自选 + 关闭
- 左侧：分时（`/minute`，SH+881xxx/885xxx）/ 日K（`/bars`，MA/MACD/KDJ 等指标前端本地算）
- 右侧 330px 成分股涨跌榜：`/board-mac/members`，支持点击成分股叠加 `StockDialog`（五档盘口+K线）

增量增强（P2，可选）：弹窗右侧顶部补一行成分股广度（`up_count/down_count`，来自 summary，单板块成本可接受）。

---

## 4. UI 布局设计

### 4.1 线框

```
┌────────────────────────────────────────────────────────────────────────────┐
│ 行业总览      86个板块  52▲ 30▼ 4— │ 中位 +0.84% │ 涨停23 跌停5 │ ▂▄▆█▆▄▂ 分布图 │
├────────────────────────────────────────────────────────────────────────────┤
│ [热力图|表格]  排序[涨跌幅▾]  [搜索____]  HY/HY2  ⟳30s[ON]  上次刷新 14:32:05 │
├───────────────────────────────────────────────┬────────────────────────────┤
│                                               │ 涨幅榜 Top10               │
│   ┌────────┐ ┌────────┐ ┌────────┐ ┌───────┐  │  1 种植业   +3.21%         │
│   │种植业  │ │渔业    │ │煤炭开采│ │...    │  │  2 ...                    │
│   │ +3.21% │ │ +2.88% │ │ +2.10% │ │       │  │ 跌幅榜 Top10               │
│   │领涨 xx │ │        │ │        │ │       │  │ 异动(涨速) Top10 ⚡闪烁    │
│   └────────┘ └────────┘ └────────┘ └───────┘  │  …                         │
│   ┌────────┐ ┌────────┐ ...                   │ ──────────────────────     │
│   │概念名…  │ │        │                       │ 翻红/翻绿 时间线            │
│   └────────┘ └────────┘                       │  14:31 翻红 生物疫苗        │
│                                               │  14:28 翻绿 房地产开发      │
│   （表格模式：3.4 节列定义，同区域替换）          │ [资金榜 Top10 ▸懒加载]      │
├───────────────────────────────────────────────┴────────────────────────────┤
│  单击板块 → BoardDialog 弹窗（左 分时/日K ｜ 右 成分股涨跌榜 → StockDialog）     │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 交互与视觉细则

- **配色**：沿用全局主题变量与 `UP_COLOR/DOWN_COLOR`；色阶透明度 5 档：0–0.5% / 0.5–1 / 1–2 / 2–3 / >3%。
- **弹窗层级**：与首页一致（BoardDialog teleport to body，1280px 遮罩弹窗）；成分股→StockDialog 叠加。
- **空/错误态**：接口失败 → 顶部错误条（api.ts 统一 `{error,detail}` 解析）+ 重试按钮；
  非交易时段显示"休市中，显示最近收盘数据"徽标。
- **响应式**：右栏 ≥1280px 常驻，<1280px 折叠为顶部横向 chips；主区 tile 自动换列。
- **localStorage 偏好**：视图模式 / 排序列 / 自动刷新开关（P2）。

---

## 5. 改动清单（实施落点）

### 后端（仅 1 个新端点）

| 文件 | 改动 |
|---|---|
| `src/easy_tdx/web/routers/board_mac.py` | 新增 `GET /board-mac/overview`：并发聚合多 sort_column 的 `MacClient.get_board_list`，计算 change_pct，按 code 归并；模块级 TTL 缓存(15s) |
| `tests/unit/test_board_mac_overview.py` | 单测：归并正确性 / 缺失指标置 null / 缓存命中（mock AsyncMacClient） |

### 前端

| 文件 | 改动 |
|---|---|
| `web-ui/src/App.vue` | 行情分组 +2 RouterLink（行业总览 `/industries`、概念总览 `/concepts`） |
| `web-ui/src/router.ts` | 两条路由 → `BoardOverviewView`，`props: { boardType: 'HY' \| 'GN' }` |
| `web-ui/src/types.ts` | `BoardOverviewRow / BoardOverviewResp / BoardRankRow` 类型 |
| `web-ui/src/api.ts` | `fetchBoardOverview(boardType, metrics)`；`fetchBoardRanking` 薄封装（复用现有错误处理） |
| `web-ui/src/views/BoardOverviewView.vue` | 主视图（统计条编排 / 工具行 / 热力图⇄表格 / 右栏 / 弹窗编排 / 轮询与 diff） |
| `web-ui/src/components/BoardStatStrip.vue` | 统计条 + 分布直方图 |
| `web-ui/src/components/BoardTiles.vue` | 热力图模式 |
| `web-ui/src/components/BoardRankRail.vue` | 榜单 + 翻红翻绿时间线 + 资金懒加载 |

---

## 6. 边界与风险

1. **MAC 服务器可用性**：`get_board_list` 依赖 MAC host（`get_mac_hosts`）；客户端已有故障转移，
   overview 端点失败时前端展示错误条并可回退直连。
2. **板块指数 K 线缺数据**：部分服务器不给 88xxxx 日K——仅影响 `change-ranking`（本设计未依赖它做主指标，
   多周期涨幅全部来自 board list），弹窗日K沿用现有换机容错。
3. **概念数量大**：500 个 tile / 行的渲染无压力；`/board-mac/ranking`（逐板块 summary）只允许 top_n 懒加载。
4. **盘中口径**：当日涨跌幅一律 `price/pre_close-1`，禁止使用 CHANGE_PCT 排序的 sort_value（恒 0，Issue #53）。
5. **刷新风暴**：TTL 缓存 + visibilitychange 暂停 + 30s 间隔，三重保护。

## 7. 分期计划

| 期 | 内容 | 预估 |
|---|---|---|
| **P1（MVP）** | 导航+路由、BoardOverviewView（热力图+表格+搜索）、统计条、右栏涨幅/跌幅/涨速榜、翻红翻绿时间线、30s 自动刷新、BoardDialog 复用、`/board-mac/overview` 端点+缓存+单测 | 1.5–2 天 |
| **P2** | 主力资金榜懒加载、轮动标签、tile ★加自选、直方图点击过滤、localStorage 偏好、HY2 切换打磨、休市徽标 | 1 天 |
| **P3（远期）** | FG/DQ 入口、板块间对比（多选叠加K线）、"点击板块过滤全市场个股"联动、板块轮动 AI 解读 | 另立项 |

## 8. 验收清单（P1）

- [ ] 左侧导航出现两个新栏目，路由/高亮/刷新兜底均正常
- [ ] 行业页展示全部 ~86 个行业（HY，且可切 HY2），概念页展示全部概念（≈300+），数量与 `/board-mac/list` 原始返回一致
- [ ] 当日涨跌幅与通达信客户端同口径（price/pre_close），排序、搜索、色阶正确
- [ ] 单击板块 tile/行 → BoardDialog：分时、日K、成分股榜、成分股→StockDialog 全链路可用
- [ ] 交易时段 30s 自动刷新且网络面板只有 1 个 overview 请求；休市自动停止
- [ ] 涨速榜闪烁、翻红/翻绿时间线在盘中可见事件产生
- [ ] 断开 MAC 服务器时出现错误条 + 重试，页面不白屏
