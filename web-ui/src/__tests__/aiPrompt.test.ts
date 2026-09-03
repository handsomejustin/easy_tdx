// AI 解读 Prompt 生成器自检。
//
// 项目未引入 vitest，采用 Node 内置 test runner（node:test）跑。
// aiPrompt.ts 只含 type-only 本地导入（编译期擦除），因此 node --test 可直跑，
// 不需要 tsconfig 路径解析：
//
//   node --test src/__tests__/aiPrompt.test.ts
//
// 关键断言：配置/25 项指标/可选段落（WF/评估/评级）随输入增减，
// 缺省可选数据时对应标题不出现（发给 LLM 的内容不撒谎）。

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { buildAiPrompt } from '../aiPrompt.ts'
import type { BacktestResult, EvaluateReport, Performance } from '../types.ts'
import type { GradeResult } from '../grading/types.ts'

// ── 京东方案例（与 grade.test.ts 同源的真实回测数据）─────────────────────────

const PERF: Performance = {
  total_return: 1.2643,
  annual_return: 0.1401,
  max_drawdown: -0.4165,
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
  avg_holding_days: 5.2,
  volatility: 0.28,
  ulcer_index: 0.08,
  var_95: 0.025,
  cvar_95: 0.038,
  sqn: 1.8,
  max_consecutive_wins: 5,
  max_consecutive_losses: 8,
}

const RESULT: BacktestResult = {
  performance: PERF,
  equity_curve: [
    { datetime: '2020-01-06', cash: 1000000, position_value: 0, total: 1000000, drawdown: 0, drawdown_pct: 0 },
    { datetime: '2021-06-01', cash: 0, position_value: 2264300, total: 2264300, drawdown: 0, drawdown_pct: 0 },
    { datetime: '2022-04-26', cash: 0, position_value: 1320000, total: 1320000, drawdown: -944300, drawdown_pct: -0.4165 },
  ],
  trades: [
    { datetime: '2020-02-03', direction: 'BUY', size: 1000, price: 4.52, commission: 5, slippage: 0, pnl: 0, rejected: false },
    { datetime: '2020-03-10', direction: 'SELL', size: 1000, price: 4.71, commission: 5, slippage: 0, pnl: 150, rejected: false },
  ],
  positions: [],
  config: {},
}

const GRADE: GradeResult = {
  grade: 'D',
  score: 31.2,
  dimensions: [
    { key: 'calmar', label: '卡玛比率', raw: 0.336, score: 22.4, weight: 0.18 },
    { key: 'max_drawdown', label: '最大回撤', raw: -0.4165, score: 30.2, weight: 0.17 },
  ],
  vetoes: [
    { key: 'high_drawdown', reason: '最大回撤 41.7% > 50%，套牢难回本', cap: 'B' },
  ],
  insufficientSample: false,
  isLosing: false,
  scenario: 'single',
}

test('基础段：角色/任务/配置/25 项指标/净值/成交/免责齐全', () => {
  const p = buildAiPrompt({
    symbol: 'SZ:000001',
    category: 'DAY',
    startDate: '2020-01-06',
    endDate: '2026-09-02',
    bars: 1580,
    strategyLabel: '双均线交叉',
    params: { fast: 5, slow: 20 },
    cash: 1000000,
    commission: 0.0003,
    slippage: 0,
    execution: 'next_open',
    result: RESULT,
  })

  assert.match(p, /# 角色设定/)
  assert.match(p, /# 任务/)
  // 语气要求：优点毛病都讲 + 0-10 信心分 + 禁臆造数字
  assert.match(p, /优点和毛病都要讲/)
  assert.match(p, /0-10 的「信心分」/)
  assert.match(p, /报告里没有的不要臆造/)
  assert.match(p, /# 回测配置/)
  assert.match(p, /SZ:000001（日线）/)
  assert.match(p, /双均线交叉/)
  assert.match(p, /fast=5, slow=20/)
  // 25 项指标全部出现
  for (const label of [
    '总收益率', '年化收益', '夏普比率', '索提诺比率', '卡玛比率',
    '最大回撤', '回撤持续', '波动率(年化)', 'Ulcer 指数', '日 VaR (95%)', '日 CVaR (95%)',
    '总交易数', '盈利次数', '亏损次数', '胜率', '盈亏比(利润因子)',
    '平均盈利', '平均亏损', '最大盈利', '最大亏损', '平均持仓天数',
    'SQN 系统质量', '最大连胜', '最大连亏', '拒单数',
  ]) {
    assert.ok(p.includes(`- ${label}：`), `缺少指标行：${label}`)
  }
  assert.match(p, /- 总收益率：126\.43%/)
  assert.match(p, /# 净值概览/)
  assert.match(p, /# 最近成交（最后 8 笔）/)
  assert.match(p, /本笔盈亏 \+150 元/)
  assert.match(p, /# 背景与免责/)

  // 未提供可选数据时，对应段落不出现（内容不撒谎）
  assert.ok(!p.includes('Walk-Forward 样本外验证'))
  assert.ok(!p.includes('一条龙评估'))
  assert.ok(!p.includes('评级（不看收益率）'))
})

test('可选段：WF / 一条龙评估 / 评级按需拼接', () => {
  const p = buildAiPrompt({
    symbol: 'SZ:000001',
    category: 'MIN_15',
    startDate: '2024-01-01',
    endDate: '2025-12-31',
    bars: 480,
    strategyLabel: 'MACD',
    params: {},
    cash: 100000,
    commission: 0.0003,
    slippage: 0.001,
    execution: 'next_close',
    result: RESULT,
    wf: {
      n_windows: 7,
      warmup_ratio: 0.3,
      windows: [
        // 窗1 用字符串值（旧后端 to_json_native 会把有限 float 序列化成字符串），
        // 锁定 buildAiPrompt 的防御性数字转换：必须照常渲染为数值
        {
          index: 0,
          start: '2024-04-01',
          end: '2024-07-01',
          bars: 60,
          total_return: '0.05' as unknown as number,
          sharpe: '0.8' as unknown as number,
          max_drawdown: '-0.06' as unknown as number,
          total_trades: 12,
          win_rate: '0.5' as unknown as number,
        },
        { index: 1, start: '2024-07-02', end: '2024-10-01', bars: 60, total_return: -0.02, sharpe: -0.3, max_drawdown: -0.08, total_trades: 9, win_rate: 0.44 },
      ],
      consistency: 0.5,
      chained_return: 0.029,
      mean_window_return: 0.015,
      median_window_return: 0.015,
      worst_window: -0.02,
      best_window: 0.05,
      mean_sharpe: 0.25,
      worst_drawdown: -0.08,
      total_trades: 21,
    },
    evaluate: {
      performance: PERF,
      score: {
        total: 61.5,
        components: { total_return: 78, sharpe: 55, max_drawdown: 30, sortino: 50, wf_consistency: 40 },
        weights_used: { total_return: 0.5, sharpe: 0.15, max_drawdown: 0.1, sortino: 0.05, wf_consistency: 0.2 },
        wf_provided: true,
      },
      walkforward: null as never,
      fitness: {
        segments: [],
        checks: [
          { name: 'train_profitable', passed: true, detail: '训练段收益 +18.2% > 0' },
          { name: 'sign_consistent', passed: false, detail: '三段收益存在反号' },
        ],
        pass_ratio: 0.5,
        passed_count: 1,
        total_checks: 2,
        high_fitness: false,
        split: [0.6, 0.2, 0.2],
      },
      benchmark: {
        buy_hold: { total_return: 0.32, annual_return: 0.06, max_drawdown: -0.35, sharpe: 0.4, calmar: 0.17, volatility: 0.24 },
        excess_return: 0.94,
        alpha: 0.09,
        beta: 0.72,
        information_ratio: 0.85,
        tracking_error: 0.12,
      },
      config: {},
    },
    grade: GRADE,
    gradeHint: '持有体验差或系统亏损，不建议参与',
  })

  assert.match(p, /15 分钟/)
  assert.match(p, /（默认参数）/)
  assert.match(p, /Walk-Forward 样本外验证（同参数跨时段稳定性）/)
  assert.match(p, /盈利窗占比：50%（1\/2）/)
  assert.match(p, /窗1（2024-04-01 ~ 2024-07-01）：\+5\.00%，夏普 0\.80，最大回撤 -6\.00%，12 笔（胜率 \+50\.00%）/)
  assert.match(p, /# 一条龙评估/)
  assert.match(p, /综合评分：61\.5 \/ 100/)
  assert.match(p, /超额收益 \+94\.00%/)
  assert.match(p, /α（年化超额）\+9\.00%；β（敏感度）0\.72/)
  assert.match(p, /适配性体检：1\/2 通过/)
  assert.match(p, /✗ 三段收益存在反号/)
  assert.match(p, /# 评级（不看收益率，面向「普通人拿不拿得住」）/)
  assert.match(p, /档位：\*\*D\*\*（总分 31\.2\/100）——持有体验差或系统亏损，不建议参与/)
  assert.match(p, /一票否决：最大回撤 41\.7%/)
})

// ── 组合版 Prompt（buildPortfolioAiPrompt，v1.31）────────────────────────────

import { buildPortfolioAiPrompt } from '../aiPrompt.ts'
import type { PortfolioResult } from '../types.ts'

const PORTFOLIO_RESULT: PortfolioResult = {
  total_performance: {
    ...PERF,
    total_return: 0.42,
    annual_return: 0.098,
    max_drawdown: 0.18,
    total_stocks: 2,
    total_cash: 1000000,
  },
  individual_results: {
    'SZ:000001': RESULT,
    'SH:600519': RESULT,
  },
  equity_allocation: { 'SZ:000001': 0.5, 'SH:600519': 0.5 },
  combined_equity: [
    { datetime: '2020-01-06', cash: 1000000, position_value: 0, total: 1000000, drawdown: 0, drawdown_pct: 0 },
    { datetime: '2022-04-26', cash: 0, position_value: 1420000, total: 1420000, drawdown: 0, drawdown_pct: 0 },
  ],
  trades: [
    { symbol: 'SZ:000001', datetime: '2020-02-03', direction: 'BUY', size: 1000, price: 4.52, commission: 5, slippage: 0, pnl: 0, rejected: false },
    { symbol: 'SH:600519', datetime: '2020-03-10', direction: 'SELL', size: 500, price: 4.71, commission: 5, slippage: 0, pnl: 90, rejected: false },
  ],
}

test('组合版：组合配置/标的清单/完整指标/各标的表现/组合成交齐全', () => {
  const p = buildPortfolioAiPrompt({
    stocks: ['SZ:000001', 'SH:600519'],
    category: 'DAY',
    startDate: '2020-01-06',
    endDate: '2026-09-02',
    strategyLabel: '双均线交叉',
    params: { fast: 5, slow: 20 },
    cash: 1000000,
    commission: 0.0003,
    slippage: 0,
    execution: 'next_open',
    result: PORTFOLIO_RESULT,
  })

  // 组合角色设定（明确「一篮子标的、资金均分」语境）
  assert.match(p, /# 角色设定/)
  assert.match(p, /组合回测报告（同一个策略分别跑在一篮子标的上/)
  // 配置段
  assert.match(p, /# 组合回测配置/)
  assert.match(p, /2 只标的上，资金均分（各拿总额的 50\.0%）/)
  assert.match(p, /SZ:000001、SH:600519/)
  assert.match(p, /组合总资金：1,000,000 元/)
  // 完整 25 项指标（含 SQN/连胜连亏）
  for (const label of ['SQN 系统质量', '最大连胜', '最大连亏', 'Ulcer 指数']) {
    assert.ok(p.includes(`- ${label}：`), `缺少指标行：${label}`)
  }
  assert.match(p, /- 总收益率：42\.00%/)
  // 净值概览 + 各标的表现（降序）
  assert.match(p, /# 净值概览/)
  assert.match(p, /# 各标的表现（按收益降序；全部）/)
  assert.match(p, /- SZ:000001：总收益 \+126\.43%，最大回撤 -41\.65%，夏普 0\.53，90 笔（胜率 \+35\.56%）/)
  // 组合成交（带标的）
  assert.match(p, /# 最近成交（组合合计的最后 8 笔）/)
  assert.match(p, /SH:600519 2020-03-10 卖出 500 股 @ 4\.71，本笔盈亏 \+90 元/)
  assert.match(p, /# 背景与免责/)

  // 未提供可选数据时，对应段落不出现
  assert.ok(!p.includes('Walk-Forward 样本外验证'))
  assert.ok(!p.includes('一条龙评估'))
  assert.ok(!p.includes('评级（不看收益率）'))
})

test('组合版：WF / 一条龙 / 评级按需拼接', () => {
  const p = buildPortfolioAiPrompt({
    stocks: ['SZ:000001', 'SH:600519'],
    category: 'DAY',
    startDate: '2020-01-06',
    endDate: '2026-09-02',
    strategyLabel: '双均线交叉',
    params: {},
    cash: 1000000,
    commission: 0.0003,
    slippage: 0,
    execution: 'next_open',
    result: PORTFOLIO_RESULT,
    wf: {
      n_windows: 5,
      warmup_ratio: 0.3,
      windows: [
        { index: 0, start: '2021-01-01', end: '2021-12-31', bars: 240, total_return: 0.03, sharpe: 0.6, max_drawdown: -0.05, total_trades: 30, win_rate: 0.53 },
        { index: 1, start: '2022-01-01', end: '2022-12-31', bars: 240, total_return: -0.01, sharpe: -0.2, max_drawdown: -0.09, total_trades: 26, win_rate: 0.46 },
      ],
      consistency: 0.5,
      chained_return: 0.0197,
      mean_window_return: 0.01,
      median_window_return: 0.01,
      worst_window: -0.01,
      best_window: 0.03,
      mean_sharpe: 0.2,
      worst_drawdown: -0.09,
      total_trades: 56,
    },
    grade: { ...GRADE, scenario: 'portfolio' },
    gradeHint: '持有体验差或系统亏损，不建议参与',
  })

  assert.match(p, /Walk-Forward 样本外验证（同参数跨时段稳定性）/)
  assert.match(p, /窗口数：5/)
  assert.match(p, /窗1（2021-01-01 ~ 2021-12-31）：\+3\.00%，夏普 0\.60，最大回撤 -5\.00%，30 笔（胜率 \+53\.00%）/)
  assert.match(p, /# 评级（不看收益率，面向「普通人拿不拿得住」）/)
  assert.match(p, /档位：\*\*D\*\*/)
})
