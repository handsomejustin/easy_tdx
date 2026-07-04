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
  fetchTask,
} from '../api'
import type {
  BacktestRequest,
  BacktestResult,
  Bar,
  MultiStrategyBacktestRequest,
  PortfolioBacktestRequest,
  PortfolioResult,
  OptimizeAllBacktestRequest,
  OptimizeAllResult,
  OptimizeBacktestRequest,
  OptimizeResult,
  StrategySchema,
} from '../types'

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
    optimizeAllResult,
    optimizeAllRunning,
    // getters
    hasBars,
    // actions
    loadStrategies,
    setOhlcv,
    run,
    clearResult,
    runPortfolio,
    clearPortfolio,
    runMultiStrategy,
    clearMultiStrategy,
    runOptimize,
    runOptimizeAll,
  }
})
