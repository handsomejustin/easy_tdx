<script setup lang="ts">
// Walk-Forward 样本外验证面板：逐窗收益柱状图 + 稳定性汇总。
// 柱色按 A 股惯例：红涨绿跌。

import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import echarts from '../echarts-setup'
import type { WalkForwardResult } from '../types'

const props = defineProps<{
  wf: WalkForwardResult
}>()

const container = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const nWin = ref(props.wf.windows.filter((w) => w.total_return > 0).length)

function render() {
  if (!container.value || props.wf.windows.length === 0) return
  chart ??= echarts.init(container.value, 'dark')
  chart.setOption(buildOption(), true)
}

function buildOption(): echarts.EChartsCoreOption {
  const labels = props.wf.windows.map((w) => `窗${w.index + 1}\n${w.start.slice(5)}~${w.end.slice(5)}`)
  const values = props.wf.windows.map((w) => +(w.total_return * 100).toFixed(2))

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: number | string) => `${Number(v).toFixed(2)}%`,
    },
    grid: { left: '6%', right: '3%', top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { fontSize: 10, interval: 0 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v: number) => `${v}%` },
      splitLine: { lineStyle: { color: '#2a2e3a' } },
    },
    series: [
      {
        name: '窗口收益',
        type: 'bar',
        data: values.map((v) => ({
          value: v,
          itemStyle: { color: v >= 0 ? '#ef4146' : '#2ebd85' }, // 红涨绿跌
        })),
        barMaxWidth: 36,
        label: {
          show: true,
          position: 'top',
          fontSize: 10,
          formatter: (p: { value: number }) => `${p.value.toFixed(1)}%`,
        },
      },
    ],
  }
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  render()
  window.addEventListener('resize', resize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
watch(() => props.wf, render)
watch(
  () => props.wf.windows,
  (ws) => {
    nWin.value = ws.filter((w) => w.total_return > 0).length
  },
)
</script>

<template>
  <div class="wf-panel">
    <div class="wf-summary">
      <div class="stat">
        <span class="stat-label">盈利窗占比</span>
        <span class="stat-value" :class="wf.consistency >= 0.5 ? 'pos' : 'neg'">
          {{ nWin }}/{{ wf.windows.length }}（{{ (wf.consistency * 100).toFixed(0) }}%）
        </span>
      </div>
      <div class="stat">
        <span class="stat-label">连乘收益</span>
        <span class="stat-value" :class="wf.chained_return >= 0 ? 'pos' : 'neg'">
          {{ (wf.chained_return * 100).toFixed(2) }}%
        </span>
      </div>
      <div class="stat">
        <span class="stat-label">最差窗</span>
        <span class="stat-value neg">{{ (wf.worst_window * 100).toFixed(2) }}%</span>
      </div>
      <div class="stat">
        <span class="stat-label">最好窗</span>
        <span class="stat-value pos">{{ (wf.best_window * 100).toFixed(2) }}%</span>
      </div>
      <div class="stat">
        <span class="stat-label">平均夏普</span>
        <span class="stat-value">{{ wf.mean_sharpe.toFixed(2) }}</span>
      </div>
      <div class="stat">
        <span class="stat-label">总交易</span>
        <span class="stat-value">{{ wf.total_trades }} 笔</span>
      </div>
    </div>
    <p class="wf-hint">
      前 {{ (wf.warmup_ratio * 100).toFixed(0) }}% 为预热区不参与评估；每窗独立开仓（窗口起点空仓），
      稳健策略的盈利窗占比应 ≥ 50%。
    </p>
    <div ref="container" class="wf-chart"></div>
  </div>
</template>

<style scoped>
.wf-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}
.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 10px;
}
.stat-label {
  font-size: 11px;
  color: var(--text-dim);
}
.stat-value {
  font-size: 14px;
  font-weight: 600;
  font-family: var(--font-mono);
}
.stat-value.pos {
  color: var(--up);
}
.stat-value.neg {
  color: #2ebd85;
}
.wf-hint {
  font-size: 11px;
  color: var(--text-dim);
  margin: 0 0 8px;
}
.wf-chart {
  width: 100%;
  height: 280px;
}
</style>
