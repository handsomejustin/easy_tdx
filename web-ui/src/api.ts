// 后端 API 封装。统一 fetch + 错误处理，返回类型化结果。
// 开发期通过 vite proxy 走 /api（同源），生产期由 FastAPI 同源托管。

import type {
  ApiError,
  BacktestRequest,
  BacktestResult,
  Bar,
  BoardOverviewResp,
  BoardRow,
  Category,
  CcpmProductsResponse,
  CcpmRankResponse,
  DataFrameResponse,
  HotspotResp,
  LimitUpEcologyResp,
  LimitUpHistoryRow,
  LlmChatResponse,
  LlmChatContext,
  LlmHistoryResponse,
  LlmConfigResponse,
  LlmConfigUpdate,
  LlmTestResult,
  MarketSessionInfo,
  MarketStat,
  MinutePoint,
  MultiStrategyBacktestRequest,
  OptimizeAllBacktestRequest,
  OptimizeBacktestRequest,
  PortfolioBacktestRequest,
  RankRow,
  SavedStrategy,
  SavedStrategyCreate,
  SavedStrategyListResponse,
  SecurityQuote,
  SentimentHistoryResp,
  SentimentTodayResp,
  ServerHostInfo,
  ServerHostListResponse,
  ServerSwitchResult,
  SignalScanRequest,
  SignalScanResult,
  StrategiesResponse,
  TaskListResponse,
  TaskState,
  TaskSubmitResponse,
  WatchlistResponse,
} from './types'

const BASE = '/api/v1'

/** 把未知错误格式化为用户可读的消息（网络错误给友好提示）。 */
export function formatError(e: unknown): string {
  if (e instanceof TypeError && e.message.includes('fetch')) {
    return '网络错误：无法连接后端服务，请确认 easy-tdx serve 已启动'
  }
  return e instanceof Error ? e.message : String(e)
}

/** 把 Response 解析为 ApiError 抛出（后端统一错误格式 {error, detail}）。 */
async function throwError(resp: Response): Promise<never> {
  let detail = `${resp.status} ${resp.statusText}`
  try {
    const body = (await resp.json()) as ApiError
    if (body?.detail) detail = body.detail
  } catch {
    // 非 JSON 错误体，用 statusText
  }
  throw new Error(detail)
}

/** 枚举预置策略 + 参数 schema。 */
export async function fetchStrategies(): Promise<StrategiesResponse> {
  const resp = await fetch(`${BASE}/backtest/strategies`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as StrategiesResponse
}

/**
 * 按标的取 K 线行情（OHLCV）。
 *
 * 后端 /bars 单次最多 800 根。当 startDate 到 endDate 跨度超过 800 根时，
 * 自动分页拉取（start=0, 800, 1600...）拼接，直到覆盖 startDate 或达上限。
 * 可选 startDate/endDate 对结果做闭区间过滤（ISO 日期字符串，如 "2024-01-01"）。
 */
const MAX_PAGES = 10 // 翻页上限：10 × 800 = 8000 根（约 32 年日线）

export async function fetchBars(
  market: string,
  code: string,
  category: Category,
  startDate?: string,
  endDate?: string,
): Promise<Bar[]> {
  let allBars: Bar[] = []
  for (let page = 0; page < MAX_PAGES; page++) {
    const params = new URLSearchParams({
      market,
      code,
      category,
      count: '800',
      start: String(page * 800),
    })
    const resp = await fetch(`${BASE}/bars?${params}`)
    if (!resp.ok) await throwError(resp)
    const body = (await resp.json()) as { data: Record<string, unknown>[] }
    const pageBars = body.data.map((row) => normalizeBar(row))
    if (pageBars.length === 0) break // 无更多数据

    allBars = allBars.concat(pageBars)

    // 若已覆盖到 startDate（本页最早一根 ≤ startDate），停止翻页
    if (startDate && pageBars.length > 0) {
      const oldest = pageBars[pageBars.length - 1].datetime.slice(0, 10)
      if (oldest <= startDate) break
    }
    // 不足 800 根说明已到数据起点
    if (pageBars.length < 800) break
  }

    // 按日期范围过滤（闭区间）
    let bars = allBars
    if (startDate) bars = bars.filter((b) => b.datetime.slice(0, 10) >= startDate)
    if (endDate) bars = bars.filter((b) => b.datetime.slice(0, 10) <= endDate)
    // 翻页拼接后按时间正序排序：每页内部是正序，但页间是逆序
    // （page1=最新段，page2=更旧段），concat 后需排序保证整体正序，
    // 否则引擎/图表只正确处理第一页的数据。
    bars.sort((a, b) => a.datetime.localeCompare(b.datetime))
    return bars
}

/** 把后端 bars 的单条记录归一化为统一 Bar（datetime 字段）。 */
function normalizeBar(row: Record<string, unknown>): Bar {
  const raw = (row.datetime ?? row.date) as string | undefined
  if (!raw) throw new Error('行情数据缺少 datetime/date 字段')
  return {
    datetime: raw.slice(0, 19).replace(' ', 'T'),
    open: Number(row.open),
    high: Number(row.high),
    low: Number(row.low),
    close: Number(row.close),
    vol: Number(row.vol),
    amount: Number(row.amount),
  }
}

/** 同步回测（内联 OHLCV，快速）。 */
export async function runBacktest(req: BacktestRequest): Promise<BacktestResult> {
  const resp = await fetch(`${BASE}/backtest/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as BacktestResult
}

/** 提交后台回测任务，返回 task_id。 */
export async function submitBacktestTask(req: BacktestRequest): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交 Walk-Forward 样本外验证后台任务（v1.27，n_windows 默认 7）。 */
export async function submitWalkforwardTask(
  req: BacktestRequest,
  nWindows = 7,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/wf/run/async?n_windows=${nWindows}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交一条龙评估后台任务（回测+WF+适配性+评分+基准对比，v1.27）。 */
export async function submitEvaluateTask(
  req: BacktestRequest,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/evaluate/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交组合回测后台任务，返回 task_id。 */
export async function submitPortfolioTask(
  req: PortfolioBacktestRequest,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/portfolio/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交组合级 Walk-Forward 样本外验证后台任务（n_windows 默认 7）。 */
export async function submitPortfolioWalkforwardTask(
  req: PortfolioBacktestRequest,
  nWindows = 7,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/portfolio/wf/run/async?n_windows=${nWindows}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交组合级一条龙评估后台任务（组合回测+WF+适配性+评分+基准对比）。 */
export async function submitPortfolioEvaluateTask(
  req: PortfolioBacktestRequest,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/portfolio/evaluate/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交多策略组合回测后台任务（资金分仓），返回 task_id。 */
export async function submitMultiStrategyTask(
  req: MultiStrategyBacktestRequest,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/multi-strategy/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交多策略组合级 Walk-Forward 样本外验证后台任务（n_windows 默认 7）。 */
export async function submitMultiStrategyWalkforwardTask(
  req: MultiStrategyBacktestRequest,
  nWindows = 7,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/multi-strategy/wf/run/async?n_windows=${nWindows}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交多策略组合级一条龙评估后台任务（组合回测+WF+适配性+评分+基准对比）。 */
export async function submitMultiStrategyEvaluateTask(
  req: MultiStrategyBacktestRequest,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/multi-strategy/evaluate/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交参数网格寻优后台任务，返回 task_id。 */
export async function submitOptimizeTask(
  req: OptimizeBacktestRequest,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/optimize/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 提交「一键寻优所有策略」后台任务，返回 task_id。 */
export async function submitOptimizeAllTask(
  req: OptimizeAllBacktestRequest,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/optimize-all/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 查询后台任务状态（轮询用）。 */
export async function fetchTask(taskId: string): Promise<TaskState> {
  const resp = await fetch(`${BASE}/backtest/tasks/${taskId}`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskState
}

/** 列出最近任务摘要（供对比页选择）。 */
export async function fetchTaskList(limit = 20): Promise<TaskListResponse> {
  const resp = await fetch(`${BASE}/backtest/tasks?limit=${limit}`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskListResponse
}

/**
 * 提交后台任务并轮询直到 done/failed。
 * @param req 回测请求
 * @param onPoll 每次轮询回调（可选，用于更新 UI 进度）
 * @param intervalMs 轮询间隔（默认 300ms）
 * @param timeoutMs 总超时（默认 120s）
 */
export async function runBacktestWithPolling(
  req: BacktestRequest,
  onPoll?: (state: TaskState) => void,
  intervalMs = 300,
  timeoutMs = 120_000,
): Promise<TaskState> {
  const { task_id } = await submitBacktestTask(req)
  const start = Date.now()
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const state = await fetchTask(task_id)
    onPoll?.(state)
    if (state.status === 'done' || state.status === 'failed') return state
    if (Date.now() - start > timeoutMs) {
      throw new Error(`回测任务超时（${timeoutMs / 1000}s）`)
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

// ── 策略库（已保存策略）──────────────────────────────────────────────────────

/** 提交「信号雷达」一键扫描后台任务，返回 task_id。 */
export async function submitSignalScanTask(
  req: SignalScanRequest = {},
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/backtest/signal-scan/run/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/**
 * 提交信号扫描并轮询直到 done/failed。
 *
 * 与 runBacktestWithPolling 的区别：扫描要在请求内逐标的取行情（提交本身
 * 就可能耗时数十秒），且标的较多时总时长可能超过 2 分钟，故默认 300s 超时。
 */
export async function runSignalScanWithPolling(
  req: SignalScanRequest = {},
  onPoll?: (state: TaskState) => void,
  intervalMs = 500,
  timeoutMs = 300_000,
): Promise<TaskState> {
  const { task_id } = await submitSignalScanTask(req)
  const start = Date.now()
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const state = await fetchTask(task_id)
    onPoll?.(state)
    if (state.status === 'done' || state.status === 'failed') return state
    if (Date.now() - start > timeoutMs) {
      throw new Error(`信号扫描超时（${timeoutMs / 1000}s），可稍后重试或减小窗口`)
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

/** 断言任务结果为信号扫描结果（类型收窄用）。 */
export function asSignalScanResult(state: TaskState): SignalScanResult {
  if (state.status === 'failed') throw new Error(state.error || '信号扫描失败')
  const result = state.result as SignalScanResult | null
  if (!result || !Array.isArray(result.rows)) {
    throw new Error('信号扫描结果格式异常（缺少 rows）')
  }
  return result
}

/** 列出全部已保存策略（按创建时间倒序）。 */
export async function fetchSavedStrategies(): Promise<SavedStrategyListResponse> {
  const resp = await fetch(`${BASE}/strategies`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as SavedStrategyListResponse
}

/** 查看单条已保存策略。 */
export async function fetchSavedStrategy(id: string): Promise<SavedStrategy> {
  const resp = await fetch(`${BASE}/strategies/${id}`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as SavedStrategy
}

/** 保存一条策略（含当时的标的上下文与成绩快照）。 */
export async function saveStrategy(req: SavedStrategyCreate): Promise<SavedStrategy> {
  const resp = await fetch(`${BASE}/strategies`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as SavedStrategy
}

/** 删除一条已保存策略。 */
export async function deleteSavedStrategy(id: string): Promise<void> {
  const resp = await fetch(`${BASE}/strategies/${id}`, { method: 'DELETE' })
  if (!resp.ok) await throwError(resp)
}

// ── 服务器设置 ──────────────────────────────────────────────────────────────

/** 列出所有候选通达信服务器 + 当前使用的 host（不含延迟，需点测速）。 */
export async function fetchServerHosts(): Promise<ServerHostListResponse> {
  const resp = await fetch(`${BASE}/server/hosts`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as ServerHostListResponse
}

/** 并发测速全部（或指定）host，返回延迟和可达性。 */
export async function testServerHosts(hosts?: string[]): Promise<ServerHostInfo[]> {
  const resp = await fetch(`${BASE}/server/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ hosts: hosts ?? null }),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as ServerHostInfo[]
}

/** 切换到指定 host（热重连，无需重启服务）。 */
export async function switchServerHost(host: string): Promise<ServerSwitchResult> {
  const resp = await fetch(`${BASE}/server/switch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ host }),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as ServerSwitchResult
}

// ── 行情终端 ────────────────────────────────────────────────────────────────

/** 批量拉实时五档（REST 一次性；持续刷新走 SSE，见 stores/quotes.ts）。
 *  注意：后端路由是 POST /quotes（market router 挂在 /api/v1 前缀下）。 */
export async function fetchQuotes(symbols: Array<{ market: string; code: string }>): Promise<SecurityQuote[]> {
  const resp = await fetch(`${BASE}/quotes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stocks: symbols }),
  })
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as DataFrameResponse
  return body.data.map(normalizeQuote)
}

/** 后端 quotes 行 → SecurityQuote（补 symbol 键；数值列容错 null）。 */
function normalizeQuote(row: Record<string, unknown>): SecurityQuote {
  const market = String(row.market ?? '')
  const code = String(row.code ?? '')
  const num = (v: unknown): number | null => {
    const n = Number(v)
    return v == null || Number.isNaN(n) ? null : n
  }
  const q = { ...row } as Record<string, unknown>
  q.symbol = `${market}${code}`
  for (const k of Object.keys(q)) {
    if (k === 'symbol' || k === 'market' || k === 'code' || k === 'server_time') continue
    q[k] = num(q[k])
  }
  return q as unknown as SecurityQuote
}

/** 全市场涨跌统计（涨/跌/平/涨停/跌停家数 + 总成交）。 */
export async function fetchMarketStat(): Promise<MarketStat> {
  const resp = await fetch(`${BASE}/market/stat`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as DataFrameResponse
  const row = body.data[0] ?? {}
  const num = (v: unknown): number => Number(v ?? 0)
  return {
    up_count: num(row.up_count),
    down_count: num(row.down_count),
    neutral_count: num(row.neutral_count),
    suspended_count: num(row.suspended_count),
    total_count: num(row.total_count),
    total_amount: num(row.total_amount),
    total_volume: num(row.total_volume),
    total_market_cap: num(row.total_market_cap),
    limit_up_count: num(row.limit_up_count),
    limit_down_count: num(row.limit_down_count),
  }
}

/** 今日分时（240 点：价格 + 每分钟量）。 */
export async function fetchMinute(market: string, code: string): Promise<MinutePoint[]> {
  const params = new URLSearchParams({ market, code })
  const resp = await fetch(`${BASE}/minute?${params}`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as DataFrameResponse
  return body.data.map((row) => ({
    datetime: String(row.datetime ?? ''),
    price: Number(row.price ?? 0),
    vol: Number(row.vol ?? 0),
  }))
}

/** 历史某日分时（date: YYYYMMDD 整数，如 20260829）。 */
export async function fetchHistoryMinute(
  market: string,
  code: string,
  date: number,
): Promise<MinutePoint[]> {
  const params = new URLSearchParams({ market, code, date: String(date) })
  const resp = await fetch(`${BASE}/minute/history?${params}`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as DataFrameResponse
  return body.data.map((row) => ({
    datetime: String(row.datetime ?? ''),
    price: Number(row.price ?? 0),
    vol: Number(row.vol ?? 0),
  }))
}

/** 指数日 K（/bars/index；指数代码在个股接口可能返回空，用它兜底）。 */
export async function fetchIndexBars(
  market: string,
  code: string,
  count = 250,
): Promise<Bar[]> {
  const params = new URLSearchParams({ market, code, category: 'DAY', count: String(count) })
  const resp = await fetch(`${BASE}/bars/index?${params}`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as DataFrameResponse
  return body.data.map((row) => ({
    datetime: String(row.datetime ?? row.date ?? '').slice(0, 19).replace(' ', 'T'),
    open: Number(row.open),
    high: Number(row.high),
    low: Number(row.low),
    close: Number(row.close),
    vol: Number(row.vol),
    amount: Number(row.amount ?? 0),
  }))
}

/** 板块列表（MAC 协议；CHANGE_PCT 排序时涨跌幅 = price/pre_close - 1 自行计算）。 */
export async function fetchBoards(boardType = 'HY', count = 60): Promise<BoardRow[]> {
  const params = new URLSearchParams({ board_type: boardType, count: String(count) })
  const resp = await fetch(`${BASE}/board-mac/list?${params}`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as DataFrameResponse
  return body.data.map((row) => {
    const r = { ...row }
    const price = Number(r.price ?? 0)
    const pre = Number(r.pre_close ?? 0)
    r.change_pct = pre > 0 ? (price / pre - 1) * 100 : Number(r.change_pct ?? 0)
    return r as BoardRow
  })
}

/** 板块总览（服务端一次归并当日涨跌幅 + 涨速 + 多周期涨幅，15s 缓存）。
 *  当日涨跌幅后端已按 price/pre_close-1 计算；未请求/缺失的周期指标为 null。 */
export async function fetchBoardOverview(
  boardType: string,
  metrics = 'SPEED,CHANGE_3D,CHANGE_5D,CHANGE_20D,YTD',
): Promise<BoardOverviewResp> {
  const params = new URLSearchParams({ board_type: boardType, metrics })
  const resp = await fetch(`${BASE}/board-mac/overview?${params}`)
  if (!resp.ok) await throwError(resp)
  // 后端 DictResponse 包装为 {data: {...}}，这里解包
  const body = (await resp.json()) as { data: BoardOverviewResp }
  return body.data
}

/** 市场热点滚动（交易日×板块涨跌矩阵 + 每日排名）。
 *  首次请求某板块类型时后端后台构建，返回 status=building（附 progress），
 *  前端 ~1s 轮询直至 ready；构建失败 status=error 稳定返回，retry=true 重建。 */
export async function fetchBoardHotspot(
  boardType: string,
  days: number,
  mode: 'top' | 'bottom',
  perDay = 5,
  retry = false,
): Promise<HotspotResp> {
  const params = new URLSearchParams({
    board_type: boardType,
    days: String(days),
    mode,
    per_day: String(perDay),
  })
  if (retry) params.set('retry', 'true')
  const resp = await fetch(`${BASE}/board-mac/hotspot?${params}`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as { data: HotspotResp }
  return body.data
}

/** 市场异动流（火箭发射/大笔买入/封涨停板/打开跌停板/快速反弹等）。 */
export async function fetchUnusual(market: 'SH' | 'SZ', count = 50): Promise<Record<string, unknown>[]> {
  const params = new URLSearchParams({ market, count: String(count) })
  const resp = await fetch(`${BASE}/mac/unusual?${params}`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as DataFrameResponse
  return body.data
}

/** 排行榜（MAC 排行行情）。
 *  MAC 协议价格列是 close（无 price/change_pct），这里统一归一化为
 *  price/change_pct，渲染端不再做多候选探测。sortBy 对应后端 SortType。 */
export async function fetchRankList(
  sortOrder: 'DESC' | 'ASC',
  count = 20,
  sortBy = 'CHANGE_PCT',
): Promise<RankRow[]> {
  const params = new URLSearchParams({
    category: 'A',
    sort_type: sortBy,
    sort_order: sortOrder,
    count: String(count),
  })
  const resp = await fetch(`${BASE}/mac/quote-list?${params}`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as DataFrameResponse
  return body.data.map((row) => {
    const close = Number(row.close ?? row.price ?? 0)
    const pre = Number(row.pre_close ?? 0)
    const r = { ...row } as Record<string, unknown>
    r.price = close
    r.change_pct = pre > 0 ? (close / pre - 1) * 100 : 0
    r.market = Number(row.market) === 1 ? 'SH' : 'SZ'
    return r as RankRow
  })
}

/** 查询证券中文名称（MAC 协议个股快照；BJ 市场可能不支持，失败返回空）。 */
export async function fetchSymbolName(market: string, code: string): Promise<string> {
  try {
    const params = new URLSearchParams({ market, code })
    const resp = await fetch(`${BASE}/mac/symbol-info?${params}`)
    if (!resp.ok) return ''
    const body = (await resp.json()) as DataFrameResponse
    return String(body.data[0]?.name ?? '')
  } catch {
    return ''
  }
}

/** 板块成分股（MAC 协议；按涨跌幅排序，列与排行行情同构，做同款归一化）。 */
export async function fetchBoardMembers(
  boardSymbol: string,
  count = 100,
  sortOrder: 'DESC' | 'ASC' = 'DESC',
): Promise<RankRow[]> {
  const params = new URLSearchParams({
    board_symbol: boardSymbol,
    count: String(count),
    sort_type: 'CHANGE_PCT',
    sort_order: sortOrder,
  })
  const resp = await fetch(`${BASE}/board-mac/members?${params}`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as DataFrameResponse
  return body.data.map((row) => {
    const close = Number(row.close ?? row.price ?? 0)
    const pre = Number(row.pre_close ?? 0)
    const r = { ...row } as Record<string, unknown>
    r.price = close
    r.change_pct = pre > 0 ? (close / pre - 1) * 100 : 0
    const m = Number(row.market)
    r.market = m === 1 ? 'SH' : m === 2 ? 'BJ' : 'SZ'
    return r as RankRow
  })
}

// ── 自选 ────────────────────────────────────────────────────────────────────

/** 列出全部自选。 */
export async function fetchWatchlist(): Promise<WatchlistResponse> {
  const resp = await fetch(`${BASE}/watchlist`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as WatchlistResponse
}

/** 加入自选（幂等）。 */
export async function addWatchItem(market: string, code: string, name = ''): Promise<void> {
  const resp = await fetch(`${BASE}/watchlist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ market, code, name }),
  })
  if (!resp.ok) await throwError(resp)
}

/** 移除自选。 */
export async function removeWatchItem(market: string, code: string): Promise<void> {
  const resp = await fetch(`${BASE}/watchlist/${market}/${code}`, { method: 'DELETE' })
  if (!resp.ok) await throwError(resp)
}

// ── 交易时段（Dashboard 自动刷新门控） ──────────────────────────────────────

/** 服务器侧交易时段判断（前端本地判断为主，本接口用于校准展示）。 */
export async function fetchMarketSession(): Promise<MarketSessionInfo> {
  const resp = await fetch(`${BASE}/market/session`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as MarketSessionInfo
}

// ── LLM 配置与对话（AI 设置页 / AI 解读直连） ───────────────────────────────

/** 当前 LLM 配置（key 脱敏）+ Provider 预设表。 */
export async function fetchLlmConfig(): Promise<LlmConfigResponse> {
  const resp = await fetch(`${BASE}/llm/config`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as LlmConfigResponse
}

/** 保存 LLM 配置（写入 ~/.easy_tdx/llm.json，与手工编辑同一份文件）。 */
export async function saveLlmConfig(req: LlmConfigUpdate): Promise<LlmConfigResponse> {
  const resp = await fetch(`${BASE}/llm/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!resp.ok) await throwError(resp)
  await resp.json() // 丢弃 PUT 响应体，统一以 GET 回读为准（providers/missing 同步刷新）
  return fetchLlmConfig()
}

/** 连通性测试（用已保存配置或请求体临时配置发一句 ping）。 */
export async function testLlm(override?: LlmConfigUpdate): Promise<LlmTestResult> {
  const resp = await fetch(`${BASE}/llm/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(override ?? null),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as LlmTestResult
}

/** 一轮 LLM 对话（如把 AI 解读 Prompt 直接发给已配置的模型）。 */
export async function chatLlm(
  prompt: string,
  systemPrompt?: string | null,
): Promise<LlmChatResponse> {
  const resp = await fetch(`${BASE}/llm/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, system_prompt: systemPrompt ?? null }),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as LlmChatResponse
}

/** 提交 AI 解读后台任务（长耗时模型调用不占 HTTP 连接），返回 task_id。 */
export async function submitLlmChatTask(
  prompt: string,
  context?: LlmChatContext | null,
  systemPrompt?: string | null,
): Promise<TaskSubmitResponse> {
  const resp = await fetch(`${BASE}/llm/chat/async`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, system_prompt: systemPrompt ?? null, context: context ?? null }),
  })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskSubmitResponse
}

/** 查询 AI 解读任务状态（轮询用）。 */
export async function fetchLlmChatTask(taskId: string): Promise<TaskState> {
  const resp = await fetch(`${BASE}/llm/chat/tasks/${taskId}`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as TaskState
}

/**
 * 提交 AI 解读并轮询直到 done/failed。
 *
 * 大报告解读 1-3 分钟属正常：轮询间隔放宽到 1.5s（回测是 0.3s），
 * 前端上限 20 分钟兜底（后端 LLM 读超时最大 600s，正常应先于此前返回）。
 */
export async function runLlmChatWithPolling(
  prompt: string,
  context?: LlmChatContext | null,
  onPoll?: (state: TaskState) => void,
  intervalMs = 1_500,
  timeoutMs = 20 * 60_000,
): Promise<TaskState> {
  const { task_id } = await submitLlmChatTask(prompt, context)
  const start = Date.now()
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const state = await fetchLlmChatTask(task_id)
    onPoll?.(state)
    if (state.status === 'done' || state.status === 'failed') return state
    if (Date.now() - start > timeoutMs) {
      throw new Error(`AI 解读任务超时（${timeoutMs / 1000}s），任务仍在后台运行，可稍后重试`)
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}

// ── AI 解读历史 ──────────────────────────────────────────────────────────────

/** 列出 AI 解读历史（时间倒序，含 Prompt/正文/策略上下文）。 */
export async function fetchLlmHistory(limit = 50): Promise<LlmHistoryResponse> {
  const resp = await fetch(`${BASE}/llm/history?limit=${limit}`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as LlmHistoryResponse
}

/** 删除一条历史记录。 */
export async function deleteLlmHistory(id: number): Promise<void> {
  const resp = await fetch(`${BASE}/llm/history/${id}`, { method: 'DELETE' })
  if (!resp.ok) await throwError(resp)
}

/** 清空全部历史。 */
export async function clearLlmHistory(): Promise<number> {
  const resp = await fetch(`${BASE}/llm/history`, { method: 'DELETE' })
  if (!resp.ok) await throwError(resp)
  return (await resp.json()).deleted as number
}

/** 涨停生态（连板天梯/炸板/跌停，本地 vipdoc 离线回算，服务端缓存 60s）。
 *  data_date 为 vipdoc 数据日期；name 字段需前端经 fetchSymbolName 补齐。 */
export async function fetchLimitUpEcology(): Promise<LimitUpEcologyResp> {
  const resp = await fetch(`${BASE}/limitup-ecology`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as { data: LimitUpEcologyResp }
  return body.data
}

/** 当日情绪分钟曲线（采样器逐分钟落库；date=0 表示尚无采样）。 */
export async function fetchSentimentToday(): Promise<SentimentTodayResp> {
  const resp = await fetch(`${BASE}/market/sentiment/today`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as { data: SentimentTodayResp }
  return body.data
}

/** 逐日情绪聚合（收盘快照上涨占比 + 涨跌停家数，依赖采样积累）。 */
export async function fetchSentimentHistory(days = 60): Promise<SentimentHistoryResp> {
  const params = new URLSearchParams({ days: String(days) })
  const resp = await fetch(`${BASE}/market/sentiment/history?${params}`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as { data: SentimentHistoryResp }
  return body.data
}

/** 涨停/跌停家数逐日历史（vipdoc 离线回补，服务端缓存 10 分钟）。 */
export async function fetchLimitUpHistory(days = 60): Promise<LimitUpHistoryRow[]> {
  const params = new URLSearchParams({ days: String(days) })
  const resp = await fetch(`${BASE}/market/limitup-history?${params}`)
  if (!resp.ok) await throwError(resp)
  const body = (await resp.json()) as { data: { count: number; days: LimitUpHistoryRow[] } }
  return body.data.days
}

/** 中金所成交持仓排名：品种列表（含科普元数据）。 */
export async function fetchCcpmProducts(): Promise<CcpmProductsResponse> {
  const resp = await fetch(`${BASE}/ccpm/products`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as CcpmProductsResponse
}

/** 中金所成交持仓排名：按品种 + 交易日抓取（date 缺省自动回溯最近有数据的交易日）。 */
export async function fetchCcpmRank(product: string, date?: string): Promise<CcpmRankResponse> {
  const params = new URLSearchParams()
  params.set('product', product)
  if (date) params.set('date', date)
  const resp = await fetch(`${BASE}/ccpm/rank?${params.toString()}`)
  if (!resp.ok) await throwError(resp)
  return (await resp.json()) as CcpmRankResponse
}
