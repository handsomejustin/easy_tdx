/**
 * 从组合净值曲线（EquityPoint[]）重算绩效指标。
 *
 * 背景：PortfolioResult.total_performance 只有 4 个字段（total_return/annual_return/
 * total_stocks/total_cash），不够评级。但 combined_equity 提供了完整的组合净值序列，
 * 可以在前端重算夏普/索提诺/卡玛/回撤/波动率/回撤持续天数。
 *
 * 注意：净值序列算不出胜率/利润因子/交易数（这些是逐笔成交统计），所以组合评级
 * 不用这两个维度，改用风险调整收益 + 索提诺补位。
 *
 * 频率假设：combined_equity 的每个点对应一个交易日（日线），
 *           夏普/波动率按 √252 年化。如果是周线/月线，年化因子需要调整。
 */

import type { EquityPoint } from '../types'

/** 年化因子（按交易日）。 */
const TRADING_DAYS_PER_YEAR = 252

/** 重算后的组合级指标（仅包含净值可推导的字段）。 */
export interface CombinedMetrics {
  /** 总收益率（小数，1.2643 = +126.43%） */
  total_return: number
  /** 年化收益率（小数）。按 (1+total)^(年数) - 1 反推。 */
  annual_return: number
  /** 最大回撤（小数，0.4165 = 41.65%） */
  max_drawdown: number
  /** 回撤持续天数（峰值到恢复的最长交易日数，未恢复则到末日） */
  max_dd_duration: number
  /** 夏普比率（年化，无风险利率按 0 处理） */
  sharpe: number
  /** 索提诺比率（年化，仅用下行波动） */
  sortino: number
  /** 卡玛比率 = 年化收益 / 最大回撤 */
  calmar: number
  /** 波动率（年化，小数） */
  volatility: number
  /** 净值点数 */
  n_points: number
  /** 跨度（年数，用于年化） */
  years: number
}

/**
 * 从净值序列重算组合级绩效指标。
 *
 * @param equity 净值序列，按时间升序。至少需要 2 个点才有统计意义。
 * @returns 重算结果；如果数据不足，相关字段返回 0（调用方应结合 n_points 判断）。
 */
export function computeCombinedMetrics(equity: EquityPoint[]): CombinedMetrics {
  const n = equity.length

  // 兜底：数据极少时返回全 0，避免除零或 NaN 污染
  if (n < 2) {
    return {
      total_return: 0,
      annual_return: 0,
      max_drawdown: 0,
      max_dd_duration: 0,
      sharpe: 0,
      sortino: 0,
      calmar: 0,
      volatility: 0,
      n_points: n,
      years: 0,
    }
  }

  // 取每个点的 total（= cash + position_value），与 EquityChart 口径一致
  const totals = equity.map((e) => e.total)
  const startValue = totals[0]
  const endValue = totals[n - 1]

  // ── 总收益 & 年化 ────────────────────────────────────────────────────────
  const total_return = startValue > 0 ? endValue / startValue - 1 : 0
  // 跨度（年）：按交易日数 / 252。若无日期信息，退化为 n / 252。
  const firstDt = Date.parse(equity[0].datetime)
  const lastDt = Date.parse(equity[n - 1].datetime)
  const years =
    Number.isFinite(firstDt) && Number.isFinite(lastDt) && lastDt > firstDt
      ? (lastDt - firstDt) / (365.25 * 24 * 3600 * 1000)
      : n / TRADING_DAYS_PER_YEAR
  const annual_return = years > 0 && endValue > 0 && startValue > 0
    ? Math.pow(endValue / startValue, 1 / years) - 1
    : 0

  // ── 逐期收益率（用于夏普/波动率） ────────────────────────────────────────
  const periodReturns: number[] = []
  for (let i = 1; i < n; i++) {
    if (totals[i - 1] > 0) {
      periodReturns.push(totals[i] / totals[i - 1] - 1)
    }
  }

  const meanPeriod = mean(periodReturns)
  const stdPeriod = stddev(periodReturns, meanPeriod)

  // 年化波动率 = 日波动率 × √252
  const volatility = stdPeriod * Math.sqrt(TRADING_DAYS_PER_YEAR)
  // 夏普 = 年化超额收益 / 年化波动（无风险利率按 0）
  // 等价于 meanPeriod / stdPeriod × √252
  const sharpe = stdPeriod > 0 ? (meanPeriod / stdPeriod) * Math.sqrt(TRADING_DAYS_PER_YEAR) : 0

  // ── 索提诺（仅用下行波动） ───────────────────────────────────────────────
  const downsideReturns = periodReturns.filter((r) => r < 0)
  const downsideStd = downsideReturns.length > 0
    ? Math.sqrt(downsideReturns.reduce((s, r) => s + r * r, 0) / downsideReturns.length)
    : 0
  const sortino = downsideStd > 0
    ? (meanPeriod / downsideStd) * Math.sqrt(TRADING_DAYS_PER_YEAR)
    : 0

  // ── 最大回撤 & 持续天数 ─────────────────────────────────────────────────
  // 优先用后端已算好的 drawdown_pct（与图表一致），反推峰值&持续更准。
  // 若后端字段缺失，再退回从 totals 反推。
  let maxDrawdown = 0
  let maxDdDuration = 0

  if (equity[0].drawdown_pct !== undefined) {
    let curPeakIdx = 0
    for (let i = 0; i < n; i++) {
      const dd = equity[i].drawdown_pct
      if (dd > maxDrawdown) {
        maxDrawdown = dd
        maxDdDuration = i - curPeakIdx
      }
      // 触及新峰值：重置当前峰值点
      // 注意 drawdown_pct == 0 表示创新高
      if (dd === 0) curPeakIdx = i
    }
  } else {
    // 退化路径：从 totals 反推
    let runningPeak = totals[0]
    let curPeakIdx = 0
    for (let i = 0; i < n; i++) {
      if (totals[i] > runningPeak) {
        runningPeak = totals[i]
        curPeakIdx = i
      }
      if (runningPeak > 0) {
        const dd = runningPeak - totals[i]
        const ddPct = dd / runningPeak
        if (ddPct > maxDrawdown) {
          maxDrawdown = ddPct
          maxDdDuration = i - curPeakIdx
        }
      }
    }
  }

  // ── 卡玛比率 = 年化收益 / 最大回撤 ───────────────────────────────────────
  const calmar = maxDrawdown > 0 ? annual_return / maxDrawdown : (annual_return > 0 ? Infinity : 0)

  return {
    total_return,
    annual_return,
    max_drawdown: maxDrawdown,
    max_dd_duration: maxDdDuration,
    sharpe,
    sortino,
    // 卡玛无穷大时（无回撤）封顶为一个大数，避免评级引擎 NaN
    calmar: Number.isFinite(calmar) ? calmar : 999,
    volatility,
    n_points: n,
    years,
  }
}

/** 求均值。空数组返回 0。 */
function mean(xs: number[]): number {
  if (xs.length === 0) return 0
  return xs.reduce((s, x) => s + x, 0) / xs.length
}

/** 求样本标准差（n-1 分母）。空/单点返回 0。 */
function stddev(xs: number[], m: number): number {
  if (xs.length < 2) return 0
  const sumSq = xs.reduce((s, x) => s + (x - m) * (x - m), 0)
  return Math.sqrt(sumSq / (xs.length - 1))
}
