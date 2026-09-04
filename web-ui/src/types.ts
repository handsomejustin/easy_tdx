// 后端 API 的 TypeScript 类型镜像。
// 与 src/easy_tdx/web/backtest_schemas.py 及 backtest router 的响应保持一致。
// 后端是唯一事实源；这里只做类型契约。

import type { GradeResult } from './grading/types'

// ── 策略 schema（GET /api/v1/backtest/strategies） ───────────────────────────

export type ParamType = 'int' | 'float' | 'bool' | 'str'

export interface ParamSchema {
  name: string
  type: ParamType
  default: number | string | boolean
  label: string
  min_value?: number
  max_value?: number
  choices?: string[]
  description?: string
}

export interface StrategySchema {
  name: string
  label: string
  description: string
  params: ParamSchema[]
  preset_grid?: Record<string, Array<number | string>>
}

export interface StrategiesResponse {
  strategies: StrategySchema[]
  count: number
}

// ── OHLCV 行情（GET /api/v1/bars） ────────────────────────────────────────────

export interface Bar {
  datetime: string
  open: number
  high: number
  low: number
  close: number
  vol: number
  amount: number
}

export interface DataFrameResponse {
  data: Record<string, unknown>[]
  count: number
}

// ── 回测请求（POST /api/v1/backtest/run） ─────────────────────────────────────

export type ExecutionMode = 'next_open' | 'next_close'
export type Category =
  | 'DAY'
  | 'WEEK'
  | 'MONTH'
  | 'MIN_5'
  | 'MIN_15'
  | 'MIN_30'
  | 'MIN_60'
  | 'MIN_120'

export interface BacktestRequest {
  strategy: string
  params?: Record<string, number | string | boolean>
  cash?: number
  commission?: number
  min_commission?: number
  stamp_tax?: number
  slippage?: number
  execution?: ExecutionMode
  ohlcv?: Bar[]
  symbol?: string
  category?: Category
  count?: number
}

// ── 回测结果 ──────────────────────────────────────────────────────────────────

export interface Performance {
  total_return: number
  annual_return: number
  max_drawdown: number
  max_dd_duration: number
  sharpe: number
  sortino: number
  calmar: number
  total_trades: number
  win_trades: number
  lose_trades: number
  rejected_trades: number
  win_rate: number
  profit_factor: number
  avg_win: number
  avg_loss: number
  max_win: number
  max_loss: number
  avg_holding_days: number
  volatility: number
  // v1.28 深度风险指标（老版本保存的结果可能缺省）
  /** Ulcer 指数：回撤深度平方均值开方，越小持有体验越好 */
  ulcer_index?: number
  /** 95% 日 VaR（历史分位数法，正数 = 单日最大损失幅度） */
  var_95?: number
  /** 95% 日 CVaR / 期望损失 */
  cvar_95?: number
  /** SQN 系统质量数（>2 可用、>4 优秀、>6 极佳） */
  sqn?: number
  /** 最大连胜笔数 */
  max_consecutive_wins?: number
  /** 最大连亏笔数 */
  max_consecutive_losses?: number
}

export interface EquityPoint {
  datetime: string
  cash: number
  position_value: number
  total: number
  drawdown: number
  drawdown_pct: number
}

export interface Trade {
  datetime: string
  direction: 'BUY' | 'SELL'
  size: number
  price: number
  commission: number
  slippage: number
  pnl: number
  rejected: boolean
}

export interface BacktestResult {
  performance: Performance
  equity_curve: EquityPoint[]
  trades: Trade[]
  positions: Record<string, unknown>[]
  config: Record<string, unknown>
}

// ── 后台任务（POST /api/v1/backtest/run/async + GET /tasks/{id}） ─────────────

export interface TaskSubmitResponse {
  task_id: string
  status: 'pending' | 'running'
}

export type TaskStatus = 'pending' | 'running' | 'done' | 'failed'

export interface TaskState {
  task_id: string
  status: TaskStatus
  result:
    | BacktestResult
    | PortfolioResult
    | OptimizeResult
    | OptimizeAllResult
    | SignalScanResult
    | WalkForwardResult
    | EvaluateReport
    | LlmChatResult
    | null
  error: string | null
  description: string
  elapsed: number
}

// ── 任务摘要（Phase 5 对比页） ────────────────────────────────────────────────

export interface TaskSummary {
  task_id: string
  status: TaskStatus
  description: string
  created_at: number
  elapsed: number
}

export interface TaskListResponse {
  tasks: TaskSummary[]
  count: number
}

// ── 组合回测（Phase 3） ───────────────────────────────────────────────────────

export interface PortfolioBacktestRequest {
  strategy: string
  params?: Record<string, number | string | boolean>
  cash?: number
  commission?: number
  slippage?: number
  execution?: ExecutionMode
  stocks: string[]
  category?: Category
  start_date?: string
  end_date?: string
}

/** 组合整体绩效：与单标的同口径的完整指标（PerformanceAnalyzer 算出，
 * 含 SQN/最大连胜连亏等）+ 组合专属的标的数与总资金。 */
export type PortfolioTotalPerformance = Performance & {
  total_stocks: number
  total_cash: number
}

/** 组合交易明细行：单标的 Trade 附来源标的（组合层汇总成交表）。 */
export type PortfolioTrade = Trade & { symbol: string }

export interface PortfolioResult {
  total_performance: PortfolioTotalPerformance
  individual_results: Record<string, BacktestResult>
  equity_allocation: Record<string, number>
  combined_equity: EquityPoint[]
  /** 组合层汇总成交（各标的 concat + symbol 列；v1.31 起返回，老结果缺省） */
  trades?: PortfolioTrade[]
  /** 后端组合评级（净值曲线 5 维度口径，v1.31 起返回，老结果缺省） */
  grade?: GradeResult
  /** 后端综合评分（v1.31 起返回，老结果缺省） */
  score?: StrategyScoreReport
}

// ── 参数网格寻优（Phase 4） ──────────────────────────────────────────────────

export interface OptimizeBacktestRequest {
  strategy: string
  cash?: number
  commission?: number
  slippage?: number
  execution?: ExecutionMode
  param_grid: Record<string, Array<number | string>>
  ohlcv?: Bar[]
  symbol?: string
  category?: Category
  count?: number
  start_date?: string
  end_date?: string
}

export interface GridPointResult {
  params: Record<string, number | string>
  total_return: number | null
  sharpe: number | null
  max_drawdown: number | null
  total_trades: number
  win_rate: number | null
  profit_factor: number | null
}

export interface OptimizeHeatmap {
  x_name: string
  y_name: string
  x: Array<number | string>
  y: Array<number | string>
  data: Array<[number, number, number | null]>
}

export interface OptimizeResult {
  strategy: string
  param_names: string[]
  results: GridPointResult[]
  best: GridPointResult | null
  heatmap: OptimizeHeatmap | null
}

// ── 一键寻优所有策略（Phase 6） ──────────────────────────────────────────────

export interface OptimizeAllBacktestRequest {
  cash?: number
  commission?: number
  slippage?: number
  execution?: ExecutionMode
  workers?: number
  ohlcv?: Bar[]
  symbol?: string
  category?: Category
  count?: number
  start_date?: string
  end_date?: string
}

export interface OptimizeAllRankEntry {
  strategy: string
  strategy_label: string
  params: Record<string, number | string>
  total_return: number | null
  sharpe: number | null
  max_drawdown: number | null
  total_trades: number
  win_rate: number | null
  profit_factor: number | null
  grid_points: number
}

export interface OptimizeAllResult {
  ranking: OptimizeAllRankEntry[]
  best: OptimizeAllRankEntry | null
  per_strategy: Record<string, OptimizeAllRankEntry>
  total_grid_points: number
}

// ── 错误响应（后端 ApiErrorResponse） ─────────────────────────────────────────

export interface ApiError {
  error: string
  detail: string
}

// ── 策略库（已保存策略，GET/POST/DELETE /api/v1/strategies） ─────────────────

/** 新建一条已保存策略的请求体（前端在回测结果区点「保存」时提交）。 */
export interface SavedStrategyCreate {
  name: string
  kind: 'single' | 'portfolio' | 'multi'
  strategy: string
  strategy_label?: string
  params?: Record<string, number | string | boolean>
  /** 标的上下文：single 存 symbol/category/start_date/end_date；portfolio 存 stocks；multi 存 items + cash/execution */
  context?: Record<string, unknown>
  /** 资金与成本配置（cash/commission/...） */
  trade_config?: Record<string, unknown>
  /** 保存时的成绩快照（total_return/sharpe/...） */
  snapshot?: Record<string, unknown>
  tags?: string[]
  notes?: string
}

/** 一条已保存策略（响应模型，含 id 与时间戳）。 */
export interface SavedStrategy {
  id: string
  name: string
  kind: 'single' | 'portfolio' | 'multi'
  strategy: string
  strategy_label: string
  params: Record<string, number | string | boolean>
  context: Record<string, unknown>
  trade_config: Record<string, unknown>
  snapshot: Record<string, unknown>
  tags: string[]
  notes: string
  created_at: string
  updated_at: string
  app_version: string
}

export interface SavedStrategyListResponse {
  strategies: SavedStrategy[]
  count: number
}

// ── 信号雷达（POST /api/v1/backtest/signal-scan/run/async） ──────────────────

/** 信号扫描请求：window_bars = 检查最近 N 根 K 线内的信号。 */
export interface SignalScanRequest {
  window_bars?: number
}

/** 窗口内单根 K 线的信号。 */
export interface SignalScanRecentSignal {
  date: string
  direction: 'BUY' | 'SELL'
}

/** 扫描结果单行：一个"策略×标的"子任务的信号摘要。 */
export interface SignalScanRow {
  strategy_id: string
  strategy_name: string
  kind: 'single' | 'portfolio' | 'multi'
  strategy: string
  strategy_label: string
  params: Record<string, number | string | boolean>
  symbol: string
  category: string
  latest_signal: 'BUY' | 'SELL' | null
  signal_date: string | null
  recent_signals: SignalScanRecentSignal[]
  position: 'holding' | 'flat' | null
  last_close: number | null
  last_bar_date: string | null
  error: string | null
}

/** 信号扫描结果：全部子任务行 + 汇总计数。 */
export interface SignalScanResult {
  rows: SignalScanRow[]
  total: number
  buy_count: number
  sell_count: number
  error_count: number
  elapsed: number
}

// ── 多策略组合回测（资金分仓，POST /api/v1/backtest/multi-strategy/run/async） ──

/** 多策略组合的单个策略槽位（一个策略 + 参数 + 它要跑的原标的 + 日期）。 */
export interface MultiStrategyItem {
  strategy: string
  strategy_label?: string
  params?: Record<string, number | string | boolean>
  symbol: string
  category?: Category
  start_date?: string
  end_date?: string
}

/** 多策略组合回测请求（各策略各拿 1/N 资金，结果结构同 PortfolioResult）。 */
export interface MultiStrategyBacktestRequest {
  items: MultiStrategyItem[]
  cash?: number
  commission?: number
  min_commission?: number
  stamp_tax?: number
  slippage?: number
  execution?: ExecutionMode
}

// ── 服务器设置（GET /api/v1/server/hosts 等） ────────────────────────────────

/** 单个通达信服务器的状态信息。 */
export interface ServerHostInfo {
  host: string
  /** 延迟（毫秒）。null = 未测速或不可达。 */
  latency_ms: number | null
  reachable: boolean
  is_current: boolean
}

/** GET /server/hosts 的响应。 */
export interface ServerHostListResponse {
  hosts: ServerHostInfo[]
  current_host: string
  total: number
}

/** POST /server/switch 的响应。 */
export interface ServerSwitchResult {
  ok: boolean
  host: string
  message: string
}

// ── 行情终端：实时五档（SSE / POST /api/v1/security/quotes） ─────────────────

/** 单只标的实时五档行情（后端 SecurityQuote 白名单投影，SSE 与 REST 同构）。 */
export interface SecurityQuote {
  symbol: string // "SH600000"
  market: string // SH/SZ/BJ
  code: string
  price: number | null
  pre_close: number | null
  open: number | null
  high: number | null
  low: number | null
  vol: number | null // 总成交量（手）
  cur_vol: number | null
  amount: number | null // 成交额（元）
  s_vol: number | null // 内盘
  b_vol: number | null // 外盘
  rise_speed: number | null // 涨速
  limit_up: number | null
  limit_down: number | null
  decimal_point: number | null
  server_time: string
  trading_status: number | null
  bid1: number | null
  bid_vol1: number | null
  bid2: number | null
  bid_vol2: number | null
  bid3: number | null
  bid_vol3: number | null
  bid4: number | null
  bid_vol4: number | null
  bid5: number | null
  bid_vol5: number | null
  ask1: number | null
  ask_vol1: number | null
  ask2: number | null
  ask_vol2: number | null
  ask3: number | null
  ask_vol3: number | null
  ask4: number | null
  ask_vol4: number | null
  ask5: number | null
  ask_vol5: number | null
}

/** SSE 消息：quotes_updated / hello。 */
export interface SseMessage {
  type: 'quotes_updated' | 'hello'
  ts?: string
  count?: number
  quotes?: SecurityQuote[]
  subscribers?: number
}

// ── 行情终端：市场统计（GET /api/v1/market/stat） ────────────────────────────

export interface MarketStat {
  up_count: number
  down_count: number
  neutral_count: number
  suspended_count: number
  total_count: number
  total_amount: number
  total_volume: number
  total_market_cap: number
  limit_up_count: number
  limit_down_count: number
}

// ── 行情终端：分时（GET /api/v1/minute） ─────────────────────────────────────

export interface MinutePoint {
  datetime: string
  price: number
  vol: number
}

// ── 行情终端：自选（GET/POST/DELETE /api/v1/watchlist） ──────────────────────

export interface WatchItem {
  market: string
  code: string
  symbol: string // SH600000
  name: string
  group_name: string
  created_at: string
  sort_order: number
}

export interface WatchlistResponse {
  items: WatchItem[]
  count: number
}

// ── 行情终端：板块列表（GET /api/v1/board-mac/list，MAC 协议，防御式取列） ────

/** 板块行（MAC 协议字段随版本浮动，全部可选，渲染端容错）。 */
export interface BoardRow {
  code?: string
  name?: string
  price?: number
  pre_close?: number
  change_pct?: number
  sort_value?: number
  [key: string]: unknown
}

// ── 行情终端：排行行情（GET /api/v1/mac/quote-list，MAC 协议，防御式取列） ────

export interface RankRow {
  code?: string
  name?: string
  price?: number
  change_pct?: number
  [key: string]: unknown
}

// ── 行业/概念总览（GET /api/v1/board-mac/overview，服务端归并多排序键） ──────

/** 板块总览行。多周期指标未请求/缺失时为 null；当日涨跌幅由后端按 price/pre_close 计算。 */
export interface BoardOverviewRow {
  market: number
  code: string
  name: string
  price: number
  pre_close: number
  change_pct: number | null
  speed: number | null
  chg_3d: number | null
  chg_5d: number | null
  chg_10d: number | null
  chg_20d: number | null
  chg_60d: number | null
  chg_ytd: number | null
  leader_code: string
  leader_name: string
  leader_change_pct: number | null
}

export interface BoardOverviewResp {
  board_type: string
  /** 数据抓取时刻（epoch 秒） */
  ts: number
  count: number
  rows: BoardOverviewRow[]
}

/** 板块翻红/翻绿事件（前端对相邻两次快照 diff 产生）。 */
export interface BoardFlipEvent {
  code: string
  name: string
  /** up = 翻红（负转正），down = 翻绿（正转负） */
  type: 'up' | 'down'
  time: string
  change_pct: number
}

// ── Walk-Forward 样本外验证（v1.27 POST /backtest/wf/run/async）──────────────

export interface WalkForwardWindow {
  index: number
  start: string
  end: string
  bars: number
  total_return: number
  sharpe: number
  max_drawdown: number
  total_trades: number
  win_rate: number
}

export interface WalkForwardResult {
  n_windows: number
  warmup_ratio: number
  windows: WalkForwardWindow[]
  /** 盈利窗占比（0~1，时间稳定性核心指标） */
  consistency: number
  /** 各窗收益连乘 - 1 */
  chained_return: number
  mean_window_return: number
  median_window_return: number
  worst_window: number
  best_window: number
  mean_sharpe: number
  worst_drawdown: number
  total_trades: number
}

// ── 一条龙评估（v1.27 POST /backtest/evaluate/run/async）─────────────────────

export interface FitnessCheckRow {
  name: string
  passed: boolean
  detail: string
}

export interface FitnessSegmentRow {
  name: string
  start: string
  end: string
  bars: number
  total_return: number
  sharpe: number
  max_drawdown: number
  total_trades: number
  win_rate: number
}

export interface FitnessReport {
  segments: FitnessSegmentRow[]
  checks: FitnessCheckRow[]
  pass_ratio: number
  passed_count: number
  total_checks: number
  high_fitness: boolean
  split: number[]
}

/** 综合评分（0-100 加权：收益50/夏普15/回撤10/Sortino5/WF一致性20） */
export interface StrategyScoreReport {
  total: number
  components: Record<string, number>
  weights_used: Record<string, number>
  wf_provided: boolean
}

export interface EvaluateBenchmarkReport {
  buy_hold: {
    total_return: number
    annual_return: number
    max_drawdown: number
    sharpe: number
    calmar: number
    volatility: number
  }
  /** 策略总收益 - 买入持有总收益 */
  excess_return: number
  // v1.28 CAPM / 主动管理对比指标（老版本保存的报告可能缺省）
  /** 年化 CAPM α：剔除基准影响后的超额收益，>0 仍有真实超额 */
  alpha?: number
  /** β：对基准的敏感度（1 = 与基准同涨跌） */
  beta?: number
  /** 年化信息比率：每 1 单位跟踪误差换来的超额收益 */
  information_ratio?: number
  /** 年化跟踪误差 */
  tracking_error?: number
}

export interface EvaluateReport {
  performance: Performance
  score: StrategyScoreReport
  walkforward: WalkForwardResult
  fitness: FitnessReport
  benchmark: EvaluateBenchmarkReport
  config: Record<string, unknown>
}

// ── 交易时段（GET /api/v1/market/session） ───────────────────────────────────

export interface MarketSessionInfo {
  is_trading_time: boolean
  sessions: Array<{ start: string; end: string }>
  session_desc: string
  server_time: string
  weekday: number
}

// ── LLM 配置与对话（GET/PUT /api/v1/llm/config 等） ──────────────────────────

export interface LlmProviderInfo {
  id: string
  label: string
  base_url: string
  default_model: string
  api_style: 'openai' | 'anthropic'
  needs_key: boolean
}

export interface LlmConfigInfo {
  provider: string
  /** 脱敏回显（sk-***abcd）；提交时空串/原样回传 = 不修改已存 key */
  api_key: string
  api_url: string
  model: string
  temperature: number
  max_tokens: number
  timeout: number
  system_prompt: string
}

export interface LlmConfigResponse {
  config: LlmConfigInfo
  providers: LlmProviderInfo[]
  configured: boolean
  missing: string[]
  config_path: string
  resolved: { api_url: string; model: string }
}

export interface LlmConfigUpdate {
  provider: string
  api_key?: string
  api_url?: string
  model?: string
  temperature?: number
  max_tokens?: number
  timeout?: number
  system_prompt?: string
}

export interface LlmTestResult {
  ok: boolean
  latency_ms: number
  model: string
  provider: string
  reply?: string
  error?: string
}

export interface LlmChatResponse {
  reply: string
  model: string
  provider: string
}

/** AI 解读后台任务（POST /llm/chat/async）完成后的 result 结构。 */
export interface LlmChatResult {
  reply: string
  model: string
  provider: string
  elapsed: number
}

// ── AI 解读历史（GET /api/v1/llm/history） ───────────────────────────────────

/** 策略上下文（随解读落库，供「去回测」引导跳转）。 */
export interface LlmChatContext {
  strategy: string
  strategy_label: string
  symbol: string
  category: string
  params: Record<string, number | string | boolean>
  start_date: string
  end_date: string
}

export interface LlmHistoryItem {
  id: number
  created_at: string
  provider: string
  model: string
  prompt: string
  reply: string
  elapsed: number
  strategy: string
  strategy_label: string
  symbol: string
  category: string
  params: Record<string, number | string | boolean>
  start_date: string
  end_date: string
}

export interface LlmHistoryResponse {
  items: LlmHistoryItem[]
  count: number
}

/** 核心龙头池条目（GET /api/v1/market/core-leaders）。 */
export interface CoreLeaderRow {
  code: string
  name: string
  market: string
}

// ── 中金所成交持仓排名（GET /api/v1/ccpm/*） ─────────────────────────────────

/** 品种元数据（含给新手的科普文案）。 */
export interface CcpmProductMeta {
  code: string
  name: string
  category: string
  underlying: string
  underlying_code: string
  unit: string
  intro: string
}

export interface CcpmProductsResponse {
  products: CcpmProductMeta[]
  count: number
}

/** 排名行（宽表：合约 × 排名 对齐三类排名；单位均为「手」）。 */
export interface CcpmRankRow {
  trading_day: string
  product: string
  instrument: string
  rank: number
  vol_member: string | null
  vol: number | null
  vol_chg: number | null
  long_member: string | null
  long_pos: number | null
  long_chg: number | null
  short_member: string | null
  short_pos: number | null
  short_chg: number | null
}

export interface CcpmRankResponse {
  trading_day: string
  product: string
  product_name: string
  data: CcpmRankRow[]
  count: number
}
