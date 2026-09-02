<script setup lang="ts">
// 25 项绩效指标表。按金融惯例格式化：比率类→百分比，保留小数。
// v1.28 新增深度风险指标（Ulcer/VaR/CVaR/SQN/连胜连亏），老结果缺键时显示 '-'。

import { computed } from 'vue'

import type { Performance } from '../types'

const props = defineProps<{
  perf: Performance
}>()

interface MetricRow {
  key: keyof Performance
  label: string
  /** percent = 显示为百分比；ratio = 原值保留小数；int = 整数；days = 天 */
  format: 'percent' | 'ratio' | 'int' | 'days'
  group: string
}

// 按业务分组排列：收益 / 风险 / 交易
const METRICS: MetricRow[] = [
  { key: 'total_return', label: '总收益率', format: 'percent', group: '收益' },
  { key: 'annual_return', label: '年化收益', format: 'percent', group: '收益' },
  { key: 'sharpe', label: '夏普比率', format: 'ratio', group: '收益' },
  { key: 'sortino', label: '索提诺比率', format: 'ratio', group: '收益' },
  { key: 'calmar', label: '卡玛比率', format: 'ratio', group: '收益' },
  { key: 'max_drawdown', label: '最大回撤', format: 'percent', group: '风险' },
  { key: 'max_dd_duration', label: '回撤持续', format: 'days', group: '风险' },
  { key: 'volatility', label: '波动率', format: 'percent', group: '风险' },
  { key: 'ulcer_index', label: 'Ulcer 指数', format: 'percent', group: '风险' },
  { key: 'var_95', label: '日 VaR (95%)', format: 'percent', group: '风险' },
  { key: 'cvar_95', label: '日 CVaR (95%)', format: 'percent', group: '风险' },
  { key: 'total_trades', label: '总交易数', format: 'int', group: '交易' },
  { key: 'win_trades', label: '盈利次数', format: 'int', group: '交易' },
  { key: 'lose_trades', label: '亏损次数', format: 'int', group: '交易' },
  { key: 'win_rate', label: '胜率', format: 'percent', group: '交易' },
  { key: 'profit_factor', label: '盈亏比', format: 'ratio', group: '交易' },
  { key: 'avg_win', label: '平均盈利', format: 'percent', group: '交易' },
  { key: 'avg_loss', label: '平均亏损', format: 'percent', group: '交易' },
  { key: 'max_win', label: '最大盈利', format: 'percent', group: '交易' },
  { key: 'max_loss', label: '最大亏损', format: 'percent', group: '交易' },
  { key: 'avg_holding_days', label: '平均持仓天数', format: 'ratio', group: '交易' },
  { key: 'sqn', label: 'SQN 系统质量', format: 'ratio', group: '交易' },
  { key: 'max_consecutive_wins', label: '最大连胜', format: 'int', group: '交易' },
  { key: 'max_consecutive_losses', label: '最大连亏', format: 'int', group: '交易' },
  { key: 'rejected_trades', label: '拒单数', format: 'int', group: '交易' },
]

function formatVal(row: MetricRow, v: number | undefined): string {
  if (v === undefined || v === null || !Number.isFinite(v)) return '-'
  if (row.format === 'percent') return `${(v * 100).toFixed(2)}%`
  if (row.format === 'int') return String(Math.round(v))
  if (row.format === 'days') return `${v.toFixed(0)} 天`
  return v.toFixed(3)
}

// 分组渲染
const groups = computed(() => {
  const map = new Map<string, MetricRow[]>()
  for (const m of METRICS) {
    if (!map.has(m.group)) map.set(m.group, [])
    map.get(m.group)!.push(m)
  }
  return Array.from(map.entries())
})

// 收益相关指标着色
function valueClass(row: MetricRow): string {
  if (row.key === 'max_drawdown' || row.key === 'avg_loss' || row.key === 'max_loss') {
    return props.perf[row.key] !== 0 ? 'neg' : ''
  }
  if (row.key === 'total_return' || row.key === 'annual_return') {
    return props.perf[row.key] > 0 ? 'pos' : 'neg'
  }
  // win_rate 是 0-1 分数（>=0.5 视为正向）；profit_factor 是绝对比值（>=1 正向）
  if (row.key === 'win_rate') {
    return props.perf[row.key] >= 0.5 ? 'pos' : ''
  }
  if (row.key === 'profit_factor') {
    return props.perf[row.key] >= 1 ? 'pos' : ''
  }
  return ''
}
</script>

<template>
  <div class="metric-grid">
    <div v-for="[group, rows] in groups" :key="group" class="metric-group">
      <h4 class="group-title">{{ group }}</h4>
      <div class="metric-rows">
        <div v-for="row in rows" :key="row.key" class="metric-row">
          <span class="metric-label">{{ row.label }}</span>
          <span class="metric-value" :class="valueClass(row)">
            {{ formatVal(row, perf[row.key]) }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.metric-grid {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
}
.metric-group {
  flex: 1;
  min-width: 180px;
}
.group-title {
  font-size: 12px;
  color: var(--text-dim);
  font-weight: 600;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}
.metric-rows {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.metric-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 13px;
}
.metric-label {
  color: var(--text-muted);
}
.metric-value {
  font-family: var(--font-mono);
  font-weight: 600;
}
.pos {
  color: var(--up);
}
.neg {
  color: var(--down);
}
</style>
