<script setup lang="ts">
// 各标的净值叠加对比图（归一化为初始=1，方便对比走势）。

import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import echarts from '../echarts-setup'
import { fmt2 } from '../format'
import type { BacktestResult } from '../types'

const props = defineProps<{
  results: Record<string, BacktestResult>
}>()

const container = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function render() {
  if (!container.value) return
  const series = buildSeries()
  if (series.length === 0) return
  chart ??= echarts.init(container.value, 'dark')
  chart.setOption(buildOption(series), true)
}

function buildSeries(): Array<{ name: string; dates: string[]; values: number[] }> {
  const out: Array<{ name: string; dates: string[]; values: number[] }> = []
  for (const [key, res] of Object.entries(props.results)) {
    const ec = res.equity_curve
    if (ec.length === 0) continue
    const initial = ec[0].total || 1
    out.push({
      name: key,
      dates: ec.map((e) => e.datetime.slice(0, 10)),
      values: ec.map((e) => e.total / initial),
    })
  }
  return out
}

function buildOption(
  series: Array<{ name: string; dates: string[]; values: number[] }>,
): echarts.EChartsCoreOption {
  // 取最长日期序列作 x 轴（各标的日期可能不同，取并集近似）
  const allDates = Array.from(new Set(series.flatMap((s) => s.dates))).sort()
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: number | string) => fmt2(Number(v)),
    },
    legend: { top: 0, data: series.map((s) => s.name) },
    grid: { left: '8%', right: '5%', top: 30, bottom: 50 },
    xAxis: { type: 'category', data: allDates, boundaryGap: false },
    yAxis: {
      type: 'value',
      scale: true,
      name: '归一化净值',
      axisLabel: { formatter: (v: number) => fmt2(v) },
    },
    dataZoom: [{ type: 'inside', start: 0, end: 100 }],
    series: series.map((s) => {
      // 按 allDates 对齐（缺失日期 forward-fill）
      const valMap = new Map(s.dates.map((d, i) => [d, s.values[i]]))
      let last = 1
      const aligned = allDates.map((d) => {
        const v = valMap.get(d)
        if (v !== undefined) last = v
        return last
      })
      return {
        name: s.name,
        type: 'line',
        data: aligned,
        symbol: 'none',
        lineStyle: { width: 1.5 },
      }
    }),
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
watch(() => props.results, render)
</script>

<template>
  <div ref="container" class="compare-chart"></div>
</template>

<style scoped>
.compare-chart {
  width: 100%;
  height: 360px;
}
</style>
