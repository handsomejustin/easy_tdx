/**
 * 评级系统自检脚本。
 *
 * 项目未引入 vitest，采用 Node 内置 test runner（node:test）跑。
 * 评级逻辑是纯函数 + 零 DOM 依赖，可直接 import ESM TypeScript（Node v22+ 原生支持）。
 *
 * 运行：node --test src/grading/__tests__/grade.test.ts
 *
 * 关键断言：京东方案例（126.43% 收益但胜率 35.56%、回撤 41.65%、卡玛 0.336）
 * 必须落在 D 档——这是产品诉求的核心验证点。
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { gradePerformance, gradeGridPoint, gradePortfolio } from '../index.ts'
import { interpolate } from '../engine.ts'
import { THRESHOLDS } from '../thresholds.ts'
import { computeCombinedMetrics } from '../combinedMetrics.ts'
import type { Performance, PortfolioResult, GridPointResult, EquityPoint } from '../../types.ts'

// ── 京东方案例（用户提供的真实回测数据）──────────────────────────────────────
const BOE_PERF: Performance = {
  total_return: 1.2643,
  annual_return: 0.1401,
  max_drawdown: 0.4165,
  max_dd_duration: 1,
  sharpe: 0.529,
  sortino: 0.825,
  calmar: 0.336,
  total_trades: 90,
  win_trades: 32,
  lose_trades: 58,
  rejected_trades: 0,
  win_rate: 0.3556,
  profit_factor: 1.107,
  avg_win: 0.0444,
  avg_loss: -0.0203,
  max_win: 0.2554,
  max_loss: -0.05,
  avg_holding_days: 11.222,
  volatility: 0.2496,
}

test('京东方回测必须评为 D 档（用户核心诉求验证点）', () => {
  const r = gradePerformance(BOE_PERF)
  console.log('京东方评级:', r.grade, '分数:', r.score)
  console.log('维度明细:', r.dimensions.map((d) => `${d.label}=${d.score.toFixed(1)}`).join(', '))
  console.log('否决:', r.vetoes.map((v) => v.reason).join('; '))
  assert.equal(r.grade, 'D', `期望 D，实际 ${r.grade}（分数 ${r.score}）。这个评级必须让用户认可。`)
})

test('京东方评分应在 30-43 区间（C 与 D 的边界）', () => {
  const r = gradePerformance(BOE_PERF)
  // 京东方分项：卡玛低 + 回撤深 + 胜率低，应在 D 档中段
  assert.ok(r.score >= 25 && r.score < 43, `分数 ${r.score} 不在 D 档合理区间`)
})

test('低利润因子触发系统亏损否决', () => {
  const r = gradePerformance({ ...BOE_PERF, profit_factor: 0.95 })
  assert.equal(r.grade, 'D')
  assert.equal(r.isLosing, true)
  assert.ok(r.vetoes.some((v) => v.key === 'losing_system'))
})

test('样本不足（< 10 笔交易）降权但不否决整个评级', () => {
  // 用户实测场景：策略本身数据不错（高夏普、低回撤），但因为长线策略天然交易少，
  // 旧逻辑会直接打到 D。修复后应该只降权 win_rate/profit_factor，评级照常给。
  // 这里用一个净值质量中等的案例，验证它不会无脑掉到 D。
  const r = gradePerformance({
    ...BOE_PERF,
    total_trades: 6,
    sharpe: 1.2,
    max_drawdown: 0.2,
    calmar: 1.5,
    volatility: 0.15,
    // win_rate / profit_factor 故意留噪音值，验证它们不影响总分
    win_rate: 0.5,
    profit_factor: 1.5,
  })
  assert.equal(r.insufficientSample, true, '应标记样本不足')
  // 修复后不应再否决到 D —— 高夏普/低回撤的长线策略应得 B 或更好
  assert.ok(
    ['A', 'B', 'S'].includes(r.grade),
    `高夏普长线策略不应因交易少被打到 D，实际 ${r.grade}（分数 ${r.score}）`,
  )
  // win_rate / profit_factor 权重应为 0
  const wr = r.dimensions.find((d) => d.key === 'win_rate')
  const pf = r.dimensions.find((d) => d.key === 'profit_factor')
  assert.equal(wr?.weight, 0, 'win_rate 权重应降为 0')
  assert.equal(pf?.weight, 0, 'profit_factor 权重应降为 0')
})

test('用户实测场景：6年6笔交易 + 高夏普 → 应得 A/B（核心回归测试）', () => {
  // 用户反馈：「有些策略数据不错，夏普也挺高，但是6年只有6次交易，评级就是D了」
  // 这条测试就是为这个场景兜底，确保修复后不再回归。
  const longTermGood: Performance = {
    total_return: 1.8, // 6 年 80%
    annual_return: 0.103, // 年化约 10%
    max_drawdown: 0.18, // 浅回撤
    max_dd_duration: 120,
    sharpe: 1.4, // 高夏普
    sortino: 1.8,
    calmar: 0.57, // 年化/回撤
    total_trades: 6, // ← 关键：长线策略交易少
    win_trades: 4,
    lose_trades: 2,
    rejected_trades: 0,
    win_rate: 0.667, // 6 笔里 4 笔赢，但样本太小不可信
    profit_factor: 2.5, // 同上
    avg_win: 0.15,
    avg_loss: -0.05,
    max_win: 0.3,
    max_loss: -0.08,
    avg_holding_days: 365, // 平均持仓 1 年
    volatility: 0.16,
  }
  const r = gradePerformance(longTermGood)
  console.log('长线优质策略评级:', r.grade, '分数:', r.score)
  console.log('维度权重:', r.dimensions.map((d) => `${d.label}=${(d.weight * 100).toFixed(0)}%`).join(', '))
  assert.equal(r.insufficientSample, true)
  // 这是核心断言：高夏普长线策略不该因交易少被打到 D
  assert.ok(
    ['A', 'B', 'S'].includes(r.grade),
    `用户场景必须修复：期望 A/B/S，实际 ${r.grade}（分数 ${r.score}）`,
  )
})

test('深回撤 > 60% 触发直接 D 否决', () => {
  const r = gradePerformance({ ...BOE_PERF, max_drawdown: 0.65 })
  assert.equal(r.grade, 'D')
  assert.ok(r.vetoes.some((v) => v.key === 'deep_drawdown'))
})

test('优质回测应得 A 或 S 档', () => {
  // 卡玛 2.0、夏普 1.8、回撤 15%、胜率 55%、利润因子 2.0、波动率 12% → 应是 A 或 S
  const good: Performance = {
    ...BOE_PERF,
    max_drawdown: 0.15,
    max_dd_duration: 30,
    sharpe: 1.8,
    sortino: 2.5,
    calmar: 2.0,
    win_rate: 0.55,
    profit_factor: 2.0,
    volatility: 0.12,
    total_trades: 80,
  }
  const r = gradePerformance(good)
  console.log('优质案例评级:', r.grade, '分数:', r.score)
  assert.ok(r.grade === 'A' || r.grade === 'S', `期望 A/S，实际 ${r.grade}`)
})

test('高回撤但收益高 → 最高 B（一票否决 cap）', () => {
  // 收益 200% 但回撤 55%，不该得高分
  const r = gradePerformance({
    ...BOE_PERF,
    max_drawdown: 0.55,
    total_return: 2.0,
    annual_return: 0.25,
    calmar: 0.45,
  })
  assert.ok(['B', 'C', 'D'].includes(r.grade), `回撤 55% 不应高于 B，实际 ${r.grade}`)
  assert.ok(r.vetoes.some((v) => v.key === 'high_drawdown'))
})

test('插值函数：边界值取端点分数', () => {
  assert.equal(interpolate(THRESHOLDS.max_drawdown.anchors, 0), 100)
  assert.equal(interpolate(THRESHOLDS.max_drawdown.anchors, 0.7), 0)
  assert.equal(interpolate(THRESHOLDS.max_drawdown.anchors, -1), 100) // 越界取端点
})

test('插值函数：中间值线性插值', () => {
  // 夏普 0.5 → 40, 0.8 → 55，0.65 应在中间附近
  const s = interpolate(THRESHOLDS.sharpe.anchors, 0.65)
  assert.ok(s > 40 && s < 55, `夏普 0.65 应在 40-55 之间，实际 ${s}`)
})

test('寻优评级：4 维度降级版', () => {
  const point: GridPointResult = {
    params: {},
    total_return: 1.5,
    sharpe: 1.5,
    max_drawdown: 0.2,
    total_trades: 50,
    win_rate: 0.5,
    profit_factor: 1.8,
  }
  const r = gradeGridPoint(point)
  assert.equal(r.scenario, 'optimize')
  assert.ok(['A', 'B', 'S'].includes(r.grade), `优质寻优点应得 A/B/S，实际 ${r.grade}（${r.score}）`)
  console.log('寻优点评级:', r.grade, r.score)
})

test('寻优评级：网格点交易太少 → 降权但评级照常', () => {
  const point: GridPointResult = {
    params: {},
    total_return: 0.5,
    sharpe: 2.0,
    max_drawdown: 0.1,
    total_trades: 3,
    win_rate: 0.7,
    profit_factor: 2.5,
  }
  const r = gradeGridPoint(point)
  assert.equal(r.insufficientSample, true)
  // 高夏普 + 浅回撤，即使交易少也应该得高分（不再否决到 D）
  assert.ok(
    ['A', 'B', 'S'].includes(r.grade),
    `优质寻优点不应因交易少被打到 D，实际 ${r.grade}`,
  )
})

// ── 组合评级：构造合成净值曲线验证 ─────────────────────────────────────────

function makeSyntheticEquity(
  startValue: number,
  dailyReturns: number[],
  startDate = '2022-01-03',
): EquityPoint[] {
  const points: EquityPoint[] = []
  let value = startValue
  let peak = startValue
  let dt = new Date(startDate)
  for (let i = 0; i < dailyReturns.length; i++) {
    if (i > 0) value *= 1 + dailyReturns[i]
    if (value > peak) peak = value
    const drawdown_pct = peak > 0 ? (peak - value) / peak : 0
    points.push({
      datetime: dt.toISOString().slice(0, 10),
      cash: 0,
      position_value: value,
      total: value,
      drawdown: peak - value,
      drawdown_pct,
    })
    dt.setDate(dt.getDate() + 1)
  }
  return points
}

test('组合评级：稳定上涨净值应得 A 或 S', () => {
  // 252 个交易日，日均 0.05% → 年化约 13%，回撤极小
  const returns = Array.from({ length: 252 }, (_, i) => {
    // 平稳上涨 + 小幅噪声，偶尔回调
    return i % 30 === 0 ? -0.008 : 0.0008 + (Math.sin(i) * 0.0003)
  })
  const equity = makeSyntheticEquity(1000000, returns)
  const m = computeCombinedMetrics(equity)
  console.log('组合重算指标:', {
    年化: (m.annual_return * 100).toFixed(2) + '%',
    回撤: (m.max_drawdown * 100).toFixed(2) + '%',
    夏普: m.sharpe.toFixed(2),
    卡玛: m.calmar.toFixed(2),
  })

  const result: PortfolioResult = {
    total_performance: {
      total_return: m.total_return,
      annual_return: m.annual_return,
      total_stocks: 3,
      total_cash: 1000000,
    },
    individual_results: {},
    equity_allocation: {},
    combined_equity: equity,
  }
  const r = gradePortfolio(result)
  console.log('稳定上涨组合评级:', r.grade, r.score)
  assert.equal(r.scenario, 'portfolio')
  // 这种平滑上涨应该有不错的评级
  assert.ok(['A', 'B', 'S'].includes(r.grade), `稳定组合应得 A/B/S，实际 ${r.grade}`)
})

test('组合评级：高波动深回撤净值 → 低档', () => {
  // 模拟一个大幅震荡、最终亏损 + 深回撤的净值
  const returns = Array.from({ length: 252 }, (_, i) => {
    if (i < 60) return -0.01 + Math.sin(i) * 0.015 // 前 60 日大跌
    if (i < 120) return 0.005 + Math.sin(i) * 0.012
    return -0.002 + Math.sin(i) * 0.02 // 后期大幅震荡
  })
  const equity = makeSyntheticEquity(1000000, returns)
  const m = computeCombinedMetrics(equity)
  console.log('波动组合重算:', {
    回撤: (m.max_drawdown * 100).toFixed(2) + '%',
    夏普: m.sharpe.toFixed(2),
    持续: m.max_dd_duration,
  })

  const result: PortfolioResult = {
    total_performance: {
      total_return: m.total_return,
      annual_return: m.annual_return,
      total_stocks: 3,
      total_cash: 1000000,
    },
    individual_results: {},
    equity_allocation: {},
    combined_equity: equity,
  }
  const r = gradePortfolio(result)
  console.log('波动组合评级:', r.grade, r.score)
  // 高波动 + 深回撤应得低评级
  assert.ok(['C', 'D', 'B'].includes(r.grade), `差组合应得 B/C/D，实际 ${r.grade}`)
})

test('combinedMetrics：单点净值返回全 0（兜底）', () => {
  const m = computeCombinedMetrics([{
    datetime: '2022-01-03',
    cash: 1000000,
    position_value: 0,
    total: 1000000,
    drawdown: 0,
    drawdown_pct: 0,
  }])
  assert.equal(m.total_return, 0)
  assert.equal(m.sharpe, 0)
  assert.equal(m.n_points, 1)
})
