/**
 * 评级系统统一入口。
 *
 * 三个场景函数：
 *   gradePerformance(perf)            — 单标的回测（完整 Performance，6 维度）
 *   gradePortfolio(result)            — 组合回测（净值重算，5 维度）
 *   gradeGridPoint(point, totalTrades)— 参数寻优（4 字段子集，4 维度）
 *
 * 评级目的：让普通人一眼判断是否适合「经常参与」。
 * 低评级 = 长期套牢风险高，不建议参与（哪怕近期收益率好看）。
 *
 * @see docs/superpowers/plans 评级系统设计文档
 */

import type { BacktestResult, EquityPoint, GridPointResult, Performance, PortfolioResult } from '../types'
import { buildResult, scoreDimension } from './engine'
import { computeCombinedMetrics } from './combinedMetrics'
import type { DimensionScore, GradeResult, VetoHit } from './types'

// ════════════════════════════════════════════════════════════════════════════
// 一票否决规则（所有场景共用）
// ════════════════════════════════════════════════════════════════════════════

export interface VetoContext {
  /** 利润因子（< 1 表示系统实际亏钱） */
  profitFactor?: number | null
  /** 总交易笔数（< 10 视为样本不足） */
  totalTrades?: number
  /** 最大回撤（小数，> 0.6 几乎无法回本） */
  maxDrawdown?: number | null
  /** 胜率（小数） */
  winRate?: number | null
}

/**
 * 应用一票否决规则。返回触发的否决列表 + 特殊标记。
 *
 * 否决语义：
 * - 「直接 D」类：触发后无论原始分多少，最终就是 D。
 * - 「最高 X」类：触发后最终档位不超过 X（可能仍然是 D/C，但不会更高）。
 */
export function applyVetoes(ctx: VetoContext): {
  vetoes: VetoHit[]
  insufficientSample: boolean
  isLosing: boolean
} {
  const vetoes: VetoHit[] = []
  let insufficientSample = false
  let isLosing = false

  // ── 「直接 D」类 ──────────────────────────────────────────────────────────

  // 系统亏损：利润因子 < 1，实际在亏钱
  if (ctx.profitFactor !== undefined && ctx.profitFactor !== null && ctx.profitFactor < 1) {
    vetoes.push({
      key: 'losing_system',
      reason: `利润因子 ${ctx.profitFactor.toFixed(2)} < 1，系统实际亏损`,
      cap: 'D',
    })
    isLosing = true
  }

  // 样本不足（交易笔数 < 10）：不再直接否决到 D。
  // 长线策略天然交易少（如 6 年 6 笔），但净值曲线（夏普/回撤/卡玛）依然可信——
  // 只有 win_rate / profit_factor 这两个依赖逐笔成交的维度不可信。
  // 处理方式改为：在 gradePerformance / gradeGridPoint 里把这两个维度权重降到 0，
  // 重分配给净值类维度；同时通过 insufficientSample 标记让前端展示提示。
  if (ctx.totalTrades !== undefined && ctx.totalTrades < 10) {
    insufficientSample = true
  }

  // 深度套牢：最大回撤 > 60%
  if (ctx.maxDrawdown !== undefined && ctx.maxDrawdown !== null && ctx.maxDrawdown > 0.6) {
    vetoes.push({
      key: 'deep_drawdown',
      reason: `最大回撤 ${(ctx.maxDrawdown * 100).toFixed(1)}% > 60%，深度套牢几乎无法回本`,
      cap: 'D',
    })
  }

  // ── 「最高 X」类（需在足够样本下才生效，避免噪音误杀） ─────────────────────
  // 与 insufficientSample 同阈值：< 10 笔视为样本不足，>= 10 笔即让低胜率否决生效。
  // 之前的 30 笔阈值留出 10–29 笔的中间地带（既不算样本不足也不触发否决），逻辑有漏洞。
  const enoughTrades = ctx.totalTrades === undefined || ctx.totalTrades >= 10

  // 胜率极低：win_rate < 25% 且样本充足 → 直接 D
  if (
    enoughTrades &&
    ctx.winRate !== undefined &&
    ctx.winRate !== null &&
    ctx.winRate < 0.25
  ) {
    vetoes.push({
      key: 'very_low_winrate',
      reason: `胜率 ${(ctx.winRate * 100).toFixed(1)}% < 25% 且样本充足，几乎一直亏`,
      cap: 'D',
    })
  }

  // 高回撤：max_drawdown > 50% → 最高 B
  if (ctx.maxDrawdown !== undefined && ctx.maxDrawdown !== null && ctx.maxDrawdown > 0.5) {
    vetoes.push({
      key: 'high_drawdown',
      reason: `最大回撤 ${(ctx.maxDrawdown * 100).toFixed(1)}% > 50%，套牢难回本`,
      cap: 'B',
    })
  }

  // 低胜率：win_rate < 30% 且样本充足 → 最高 C
  if (
    enoughTrades &&
    ctx.winRate !== undefined &&
    ctx.winRate !== null &&
    ctx.winRate < 0.3 &&
    ctx.winRate >= 0.25 // 25% 以下已被上一条否决到 D
  ) {
    vetoes.push({
      key: 'low_winrate',
      reason: `胜率 ${(ctx.winRate * 100).toFixed(1)}% < 30% 且样本充足，普通人拿不住`,
      cap: 'C',
    })
  }

  // 微利：利润因子 < 1.2 → 最高 B（系统勉强盈亏平衡）
  if (
    ctx.profitFactor !== undefined &&
    ctx.profitFactor !== null &&
    ctx.profitFactor >= 1 &&
    ctx.profitFactor < 1.2
  ) {
    vetoes.push({
      key: 'thin_edge',
      reason: `利润因子 ${ctx.profitFactor.toFixed(2)} 接近 1，仅勉强盈亏平衡`,
      cap: 'B',
    })
  }

  return { vetoes, insufficientSample, isLosing }
}

/**
 * 当交易样本不足时，把依赖逐笔成交的维度（win_rate / profit_factor）权重降为 0，
 * 按比例重分配给净值类维度（夏普/卡玛/回撤/波动率）。
 *
 * 设计理由：交易笔数少只意味着「胜率/利润因子是噪音」，但夏普/卡玛/回撤
 * 是从净值曲线（通常几百到几千个点）算出来的，依然高度可信。
 * 把不可信维度降权而非整个评级否决，是统计上更合理的处理。
 *
 * @param dimensions 当前维度列表（会被原地修改 weight）
 * @param unreliableKeys 需要降权的维度 key（默认 win_rate / profit_factor）
 * @returns 是否实际发生了降权
 */
export function downweightUnreliableDimensions(
  dimensions: DimensionScore[],
  unreliableKeys: string[] = ['win_rate', 'profit_factor'],
): boolean {
  // 收集需要降权的维度及其原权重总和
  const toDownweight = dimensions.filter((d) => unreliableKeys.includes(d.key))
  if (toDownweight.length === 0) return false

  const releasedWeight = toDownweight.reduce((s, d) => s + d.weight, 0)
  if (releasedWeight <= 0) return false

  // 把权重清零
  for (const d of toDownweight) d.weight = 0

  // 剩余可承接权重的维度（weight > 0 的）
  const receivers = dimensions.filter((d) => d.weight > 0)
  if (receivers.length === 0) return false

  const receiverTotal = receivers.reduce((s, d) => s + d.weight, 0)
  if (receiverTotal <= 0) return false

  // 按现有权重比例分配释放出来的权重
  for (const d of receivers) {
    d.weight += releasedWeight * (d.weight / receiverTotal)
  }

  return true
}

// ════════════════════════════════════════════════════════════════════════════
// 场景 1：单标的回测评级（完整 Performance，6 维度）
// ════════════════════════════════════════════════════════════════════════════

/**
 * 评级单标的回测结果。
 *
 * 6 维度：卡玛(18%) + 最大回撤(17%) + 胜率(17%) + 利润因子(18%) +
 *         夏普(15%) + 波动率(15%)
 *
 * 注意：total_return **不直接计入评分**（只通过卡玛/夏普间接体现）。
 * 这是产品诉求——「哪怕近期收益率高，长期风险大也该低评」。
 *
 * 不再用 max_dd_duration 维度：后端该字段口径是「峰值跌到最深点」的 bar 数
 * （通常很短，京东方只有 1 天），与「套牢多久才回本」的产品直觉不符，
 * 信号弱且容易被高波动策略误判为优质。波动率已足以反映持有颠簸程度。
 */
export function gradePerformance(perf: Performance): GradeResult {
  const dimensions: DimensionScore[] = [
    scoreDimension('calmar', perf.calmar, 0.18),
    scoreDimension('max_drawdown', perf.max_drawdown, 0.17),
    scoreDimension('win_rate', perf.win_rate, 0.17),
    scoreDimension('profit_factor', perf.profit_factor, 0.18),
    scoreDimension('sharpe', perf.sharpe, 0.15),
    scoreDimension('volatility', perf.volatility, 0.15),
  ]

  const { vetoes, insufficientSample, isLosing } = applyVetoes({
    profitFactor: perf.profit_factor,
    totalTrades: perf.total_trades,
    maxDrawdown: perf.max_drawdown,
    winRate: perf.win_rate,
  })

  // 交易样本不足时：把 win_rate / profit_factor 权重降到 0，
  // 重分配给净值类维度。降权后这些维度的单项分仍展示（信息透明），
  // 但不再影响总分。详见 downweightUnreliableDimensions 注释。
  if (insufficientSample) {
    downweightUnreliableDimensions(dimensions)
  }

  return buildResult('single', dimensions, vetoes, { insufficientSample, isLosing })
}

// ════════════════════════════════════════════════════════════════════════════
// 场景 2：组合回测评级（净值重算，5 维度）
// ════════════════════════════════════════════════════════════════════════════

/**
 * 评级组合回测结果。
 *
 * 组合级净值算不出胜率/利润因子，所以用 5 个净值可推导的维度：
 *   卡玛(25%) + 最大回撤(22%) + 夏普(22%) + 索提诺(15%) + 波动率(16%)
 *
 * 否决规则中只有「深回撤」类能生效（无交易笔数/利润因子）。
 */
export function gradePortfolio(result: PortfolioResult): GradeResult {
  const equity: EquityPoint[] = result.combined_equity
  const m = computeCombinedMetrics(equity)

  const dimensions: DimensionScore[] = [
    scoreDimension('calmar', m.calmar, 0.25),
    scoreDimension('max_drawdown', m.max_drawdown, 0.22),
    scoreDimension('sharpe', m.sharpe, 0.22),
    scoreDimension('sortino', m.sortino, 0.15),
    scoreDimension('volatility', m.volatility, 0.16),
  ]

  // 组合级无逐笔交易统计，无法用 totalTrades 判断样本。改用净值点数：
  // 至少 60 个交易日（≈3 个月）才视为统计有效。语义等价的 totalTrades 占位值：
  //   n_points >= 60 → 用 30（>= enoughTrades 阈值，所有否决规则可生效）
  //   n_points <  60 → 用 5（触发 insufficientSample 标记）
  const PORTFOLIO_MIN_POINTS = 60
  const sampleProxyTrades = m.n_points >= PORTFOLIO_MIN_POINTS ? 30 : 5

  const { vetoes, insufficientSample, isLosing } = applyVetoes({
    maxDrawdown: m.max_drawdown,
    totalTrades: sampleProxyTrades,
  })

  return buildResult('portfolio', dimensions, vetoes, { insufficientSample, isLosing })
}

// ════════════════════════════════════════════════════════════════════════════
// 场景 3：参数寻优评级（4 字段子集，4 维度降级版）
// ════════════════════════════════════════════════════════════════════════════

/**
 * 评级单个寻优网格点（GridPointResult）。
 *
 * 寻优结果只有 6 个字段（total_return/sharpe/max_drawdown/total_trades/
 * win_rate/profit_factor），缺卡玛/波动率/年化/avg_win/loss。
 *
 * 降级到 4 维度（权重重分配）：
 *   夏普(30%) + 最大回撤(28%) + 胜率(22%) + 利润因子(20%)
 *
 * @param point 网格点结果
 * @param totalTradesOverride 可选，覆盖 point.total_trades（用于排名表统一基准）
 */
export function gradeGridPoint(
  point: GridPointResult,
  totalTradesOverride?: number,
): GradeResult {
  const totalTrades = totalTradesOverride ?? point.total_trades

  const dimensions: DimensionScore[] = [
    scoreDimension('sharpe', point.sharpe ?? 0, 0.3),
    scoreDimension('max_drawdown', point.max_drawdown ?? 1, 0.28),
    scoreDimension('win_rate', point.win_rate ?? 0, 0.22),
    scoreDimension('profit_factor', point.profit_factor ?? 0, 0.2),
  ]

  const { vetoes, insufficientSample, isLosing } = applyVetoes({
    profitFactor: point.profit_factor,
    totalTrades,
    maxDrawdown: point.max_drawdown,
    winRate: point.win_rate,
  })

  // 交易样本不足时同样降权 win_rate / profit_factor，重分配给夏普/回撤。
  if (insufficientSample) {
    downweightUnreliableDimensions(dimensions)
  }

  return buildResult('optimize', dimensions, vetoes, { insufficientSample, isLosing })
}

/**
 * 从 BacktestResult 评级的便捷封装（自动识别单标的/组合）。
 * 主要给 BacktestView / OptimizeView 跳转后回测结果用。
 */
export function gradeBacktestResult(result: BacktestResult): GradeResult {
  return gradePerformance(result.performance)
}

// ── 重新导出常用类型和工具，便于调用方一处 import ───────────────────────────
export { GRADE_META, GRADE_THRESHOLDS } from './types'
export type { Grade, GradeResult, DimensionScore, VetoHit, GradeMeta } from './types'
export { worseGrade, scoreToGrade } from './engine'
export { computeCombinedMetrics } from './combinedMetrics'
export type { CombinedMetrics } from './combinedMetrics'
