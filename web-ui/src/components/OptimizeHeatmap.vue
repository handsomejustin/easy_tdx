<script setup lang="ts">
// 2 参数寻优热力图（ECharts heatmap）。x=参数1取值，y=参数2取值，cell=total_return。

import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import echarts from '../echarts-setup'
import type { OptimizeHeatmap } from '../types'

const props = defineProps<{
  heatmap: OptimizeHeatmap
}>()

const container = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function render() {
  if (!container.value) return
  chart ??= echarts.init(container.value, 'dark')
  chart.setOption(buildOption(), true)
}

function buildOption(): echarts.EChartsCoreOption {
  const { x, y, data, x_name, y_name } = props.heatmap
  // 计算 visualMap 范围
  const values = data.map((d) => d[2]).filter((v): v is number => v !== null)
  const min = values.length ? Math.min(...values) : 0
  const max = values.length ? Math.max(...values) : 1
  return {
    backgroundColor: 'transparent',
    tooltip: {
      position: 'top',
      formatter: (p: { data: [number, number, number | null] }) => {
        const xv = x[p.data[0]]
        const yv = y[p.data[1]]
        const ret = p.data[2]
        const retStr = ret !== null ? `${(ret * 100).toFixed(2)}%` : '-'
        return `${x_name}=${xv}, ${y_name}=${yv}<br/>收益: ${retStr}`
      },
    },
    grid: { left: '12%', right: '5%', top: 20, bottom: 60 },
    xAxis: { type: 'category', data: x.map(String), name: x_name, splitArea: { show: true } },
    yAxis: { type: 'category', data: y.map(String), name: y_name, splitArea: { show: true } },
    visualMap: {
      min,
      max,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      formatter: (v: number) => `${(v * 100).toFixed(2)}%`,
      inRange: { color: ['#18a058', '#2a2e3a', '#ef4146'] }, // 绿(低)→暗→红(高)
    },
    series: [
      {
        type: 'heatmap',
        data,
        label: { show: false },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } },
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
watch(() => props.heatmap, render)
</script>

<template>
  <div ref="container" class="heatmap-chart"></div>
</template>

<style scoped>
.heatmap-chart {
  width: 100%;
  height: 380px;
}
</style>
