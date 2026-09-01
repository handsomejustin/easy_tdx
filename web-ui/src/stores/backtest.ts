// 回测状态管理（Pinia）。
// 持有：策略列表、当前 OHLCV、回测结果、运行状态、错误信息。

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  fetchStrategies,
  formatError,
  runBacktest,
  submitPortfolioTask,
  submitOptimizeAllTask,
  submitOptimizeTask,
  submitMultiStrategyTask,
  submitWalkforwardTask,
  submitEvaluateTask,
  fetchTask,
} from '../api'
import type {
  BacktestRequest,
  BacktestResult,
  Bar,
  Category,
  EvaluateReport,
  MultiStrategyBacktestRequest,
  PortfolioBacktestRequest,
  PortfolioResult,
  OptimizeAllBacktestRequest,
  OptimizeAllResult,
  OptimizeBacktestRequest,
  OptimizeResult,
  StrategySchema,
  WalkForwardResult,
} from '../types'

/** 轮询后台任务直到终态（done 返回 result，failed/超时抛错）。 */
async function pollTask<T>(taskId: string, timeoutMs: number, what: string): Promise<T> {
  const start = Date.now()
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const state = await fetchTask(taskId)
    if (state.status === 'done' && state.result) return state.result as T
    if (state.status === 'failed') throw new Error(state.error || `${what}失败`)
    if (Date.now() - start > timeoutMs) throw new Error(`${what}超时（${timeoutMs / 1000}s）`)
    await new Promise((r) => setTimeout(r, 400))
  }
}

export const useBacktestStore = defineStore('backtest', () => {
  // ── 策略 ─────────────────────────────────────────────────────────────────
  const strategies = ref<StrategySchema[]>([])
  const strategiesLoaded = ref(false)

  async function loadStrategies() {
    if (strategiesLoaded.value) return
    const resp = await fetchStrategies()
    strategies.value = resp.strategies
    strategiesLoaded.value = true
  }

  // ── OHLCV 行情（前端始终持有，回测与 K 线共用） ───────────────────────────
  const ohlcv = ref<Bar[]>([])
  const barsSource = ref<string>('') // 来源描述，如 "SZ:000001 DAY×250"

  function setOhlcv(bars: Bar[], source: string) {
    ohlcv.value = bars
    barsSource.value = source
  }

  const hasBars = computed(() => ohlcv.value.length >= 2)

  // ── 回测结果 ──────────────────────────────────────────────────────────────
  const result = ref<BacktestResult | null>(null)
  const running = ref(false)
  const error = ref<string>('')

  /** 运行同步回测（内联 OHLCV）。 */
  async function run(req: Omit<BacktestRequest, 'ohlcv'>) {
    if (!hasBars.value) {
      error.value = '请先取行情数据或粘贴 OHLCV'
      return
    }
    running.value = true
    error.value = ''
    try {
      const fullReq: BacktestRequest = { ...req, ohlcv: ohlcv.value }
      result.value = await runBacktest(fullReq)
    } catch (e) {
      error.value = formatError(e)
      result.value = null
    } finally {
      running.value = false
    }
  }

  function clearResult() {
    result.value = null
    error.value = ''
  }

  // ── 附加分析：Walk-Forward / 一条龙评估（v1.27） ─────────────────────────
  const wfResult = ref<WalkForwardResult | null>(null)
  const wfRunning = ref(false)
  const wfError = ref<string>('')
  const evaluateResult = ref<EvaluateReport | null>(null)
  const evaluateRunning = ref(false)
  const evaluateError = ref<string>('')

  /** 提交 WF 样本外验证后台任务并轮询（与主回测共用同一份内联 OHLCV）。 */
  async function runWalkforward(req: Omit<BacktestRequest, 'ohlcv'>, nWindows = 7) {
    if (!hasBars.value) return
    wfRunning.value = true
    wfError.value = ''
    wfResult.value = null
    try {
      const { task_id } = await submitWalkforwardTask({ ...req, ohlcv: ohlcv.value }, nWindows)
      const body = await pollTask<{ walkforward: WalkForwardResult }>(task_id, 180_000, 'WF 验证')
      wfResult.value = body.walkforward
    } catch (e) {
      wfError.value = formatError(e)
      wfResult.value = null
    } finally {
      wfRunning.value = false
    }
  }

  /** 提交一条龙评估后台任务并轮询（回测+WF+适配性+评分+基准对比）。 */
  async function runEvaluate(req: Omit<BacktestRequest, 'ohlcv'>) {
    if (!hasBars.value) return
    evaluateRunning.value = true
    evaluateError.value = ''
    evaluateResult.value = null
    try {
      const { task_id } = await submitEvaluateTask({ ...req, ohlcv: ohlcv.value })
      evaluateResult.value = await pollTask<EvaluateReport>(task_id, 300_000, '一条龙评估')
    } catch (e) {
      evaluateError.value = formatError(e)
      evaluateResult.value = null
    } finally {
      evaluateRunning.value = false
    }
  }

  function clearExtraAnalysis() {
    wfResult.value = null
    wfError.value = ''
    evaluateResult.value = null
    evaluateError.value = ''
  }

  // ── 组合回测（Phase 3） ───────────────────────────────────────────────────
  const portfolioResult = ref<PortfolioResult | null>(null)
  const portfolioRunning = ref(false)

  /** 提交组合回测后台任务并轮询直到完成。 */
  async function runPortfolio(req: PortfolioBacktestRequest) {
    portfolioRunning.value = true
    error.value = ''
    portfolioResult.value = null
    try {
      const { task_id } = await submitPortfolioTask(req)
      // 轮询
      const start = Date.now()
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const state = await fetchTask(task_id)
        if (state.status === 'done' && state.result) {
          portfolioResult.value = state.result as PortfolioResult
          break
        }
        if (state.status === 'failed') {
          throw new Error(state.error || '组合回测失败')
        }
        if (Date.now() - start > 120_000) throw new Error('组合回测超时（120s）')
        await new Promise((r) => setTimeout(r, 300))
      }
    } catch (e) {
      error.value = formatError(e)
      portfolioResult.value = null
    } finally {
      portfolioRunning.value = false
    }
  }

  function clearPortfolio() {
    portfolioResult.value = null
    error.value = ''
  }

  // ── 多策略组合回测（资金分仓） ─────────────────────────────────────────
  const multiStrategyResult = ref<PortfolioResult | null>(null)
  const multiStrategyRunning = ref(false)

  /** 提交多策略组合回测后台任务并轮询直到完成。
   * 结果结构同 PortfolioResult（复用组合页图表组件）。 */
  async function runMultiStrategy(req: MultiStrategyBacktestRequest) {
    multiStrategyRunning.value = true
    error.value = ''
    multiStrategyResult.value = null
    try {
      const { task_id } = await submitMultiStrategyTask(req)
      const start = Date.now()
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const state = await fetchTask(task_id)
        if (state.status === 'done' && state.result) {
          multiStrategyResult.value = state.result as PortfolioResult
          break
        }
        if (state.status === 'failed') {
          throw new Error(state.error || '多策略组合回测失败')
        }
        if (Date.now() - start > 180_000) throw new Error('多策略组合回测超时（180s）')
        await new Promise((r) => setTimeout(r, 400))
      }
    } catch (e) {
      error.value = formatError(e)
      multiStrategyResult.value = null
    } finally {
      multiStrategyRunning.value = false
    }
  }

  function clearMultiStrategy() {
    multiStrategyResult.value = null
    error.value = ''
  }

  // ── 参数网格寻优（Phase 4） ─────────────────────────────────────────────
  const optimizeResult = ref<OptimizeResult | null>(null)
  const optimizeRunning = ref(false)

  /** 寻优实际使用的标的上下文（取行情成功那一刻冻结）。
   * 放在 store 而非组件里，是为了在用户切走再回 /optimize 时，「查看」按钮仍能拼出正确 URL
   * —— 组件 ref 在卸载后丢失，而 store 与 optimizeResult 同生命周期保留。
   * 由 OptimizeView 在 loadBars() 成功后通过 setOptimizeContext() 写入。 */
  const optimizeContext = ref<{
    code: string
    category: Category
    startDate: string
    endDate: string
  } | null>(null)

  function setOptimizeContext(ctx: { code: string; category: Category; startDate: string; endDate: string }) {
    optimizeContext.value = ctx
  }

  /** 提交寻优后台任务并轮询直到完成。 */
  async function runOptimize(req: OptimizeBacktestRequest) {
    optimizeRunning.value = true
    error.value = ''
    optimizeResult.value = null
    try {
      const { task_id } = await submitOptimizeTask(req)
      const start = Date.now()
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const state = await fetchTask(task_id)
        if (state.status === 'done' && state.result) {
          optimizeResult.value = state.result as OptimizeResult
          break
        }
        if (state.status === 'failed') {
          throw new Error(state.error || '寻优失败')
        }
        if (Date.now() - start > 180_000) throw new Error('寻优超时（180s）')
        await new Promise((r) => setTimeout(r, 400))
      }
    } catch (e) {
      error.value = formatError(e)
      optimizeResult.value = null
    } finally {
      optimizeRunning.value = false
    }
  }

  // ── 一键寻优所有策略（Phase 6） ─────────────────────────────────────────
  const optimizeAllResult = ref<OptimizeAllResult | null>(null)
  const optimizeAllRunning = ref(false)

  /** 提交「一键寻优所有策略」后台任务并轮询直到完成。 */
  async function runOptimizeAll(req: OptimizeAllBacktestRequest) {
    optimizeAllRunning.value = true
    error.value = ''
    optimizeAllResult.value = null
    try {
      const { task_id } = await submitOptimizeAllTask(req)
      const start = Date.now()
      // 一键寻优全策略网格点更多，放宽超时到 300s
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const state = await fetchTask(task_id)
        if (state.status === 'done' && state.result) {
          optimizeAllResult.value = state.result as OptimizeAllResult
          break
        }
        if (state.status === 'failed') {
          throw new Error(state.error || '一键寻优失败')
        }
        if (Date.now() - start > 300_000) throw new Error('一键寻优超时（300s）')
        await new Promise((r) => setTimeout(r, 500))
      }
    } catch (e) {
      error.value = formatError(e)
      optimizeAllResult.value = null
    } finally {
      optimizeAllRunning.value = false
    }
  }

  return {
    // state
    strategies,
    strategiesLoaded,
    ohlcv,
    barsSource,
    result,
    running,
    error,
    portfolioResult,
    portfolioRunning,
    multiStrategyResult,
    multiStrategyRunning,
    optimizeResult,
    optimizeRunning,
    optimizeContext,
    optimizeAllResult,
    optimizeAllRunning,
    wfResult,
    wfRunning,
    wfError,
    evaluateResult,
    evaluateRunning,
    evaluateError,
    // getters
    hasBars,
    // actions
    loadStrategies,
    setOhlcv,
    run,
    clearResult,
    runWalkforward,
    runEvaluate,
    clearExtraAnalysis,
    runPortfolio,
    clearPortfolio,
    runMultiStrategy,
    clearMultiStrategy,
    runOptimize,
    runOptimizeAll,
    setOptimizeContext,
  }
})
