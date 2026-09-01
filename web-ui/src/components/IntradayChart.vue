<script setup lang="ts">
// 分时图（ECharts）：价格线 + 渐变面积 + 均价线 + 昨收基准虚线 + 成交量副图。
// 单日模式：y 轴围绕昨收对称（分时图惯例）。
// 多日模式（dayMarks 提供每天起始索引）：y 轴自适应全段，天与天之间
// markLine 竖分隔，x 轴只在每天首点显示日期（借鉴多日分时惯例）。

import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import echarts, { DOWN_COLOR, UP_COLOR } from '../echarts-setup'
import { fmt2 } from '../format'
import type { MinutePoint } from '../types'

const props = defineProps<{
  points: MinutePoint[]
  preClose?: number | null
  /** 多日模式：每天起始索引 + 日期标签。 */
  dayMarks?: Array<{ start: number; date: string }>
}>()

const container = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const isMultiDay = () => (props.dayMarks?.length ?? 0) > 1

function render() {
  if (!container.value) return
  if (props.points.length === 0) return
  chart ??= echarts.init(container.value, 'dark')
  chart.setOption(buildOption(), true)
}

function buildOption(): echarts.EChartsCoreOption {
  const pts = props.points
  const multi = isMultiDay()
  // 基准（量柱首色与 tooltip 涨跌幅）：单日用昨收，多日用全段首价
  const base = !multi && props.preClose && props.preClose > 0 ? props.preClose : pts[0]?.price ?? 0

  const times = pts.map((p) => p.datetime.slice(11, 16))
  const prices = pts.map((p) => p.price)

  // 均价线：累计成交额近似 = Σ(price×vol)，均价 = cumAmount / cumVol
  let cumAmt = 0
  let cumVol = 0
  const avgPrices = pts.map((p) => {
    cumAmt += p.price * Math.max(p.vol, 0)
    cumVol += Math.max(p.vol, 0)
    return cumVol > 0 ? cumAmt / cumVol : p.price
  })

  // y 轴范围：单日围绕昨收对称；多日自适应全段
  const hi = Math.max(...prices)
  const lo = Math.min(...prices)
  let yMax: number
  let yMin: number
  if (multi) {
    const pad = (hi - lo) * 0.08 || hi * 0.002
    yMax = hi + pad
    yMin = lo - pad
  } else {
    const hi2 = Math.max(base, hi)
    const lo2 = Math.min(base, lo)
    const pad = Math.max((hi2 - lo2) * 0.1, base * 0.0025)
    yMax = hi2 + pad
    yMin = lo2 - pad
  }

  // 量柱颜色：与前一分钟价格比较（红涨绿跌），首柱与基准比
  const volColors = pts.map((p, i) => {
    const prev = i > 0 ? pts[i - 1].price : base
    return p.price >= prev ? UP_COLOR : DOWN_COLOR
  })

  // x 轴刻度：单日在关键时点；多日只在每天首点显示 MM-DD
  const markStarts = new Map((props.dayMarks ?? []).map((m) => [m.start, m.date]))
  const labelInterval = multi
    ? (index: number) => markStarts.has(index)
    : (index: number) => [0, 60, 120, 121, 180, 239].includes(index)
  const labelFormatter = multi
    ? (v: string) => {
        const idx = times.indexOf(v)
        const d = markStarts.get(idx)
        return d ? d.slice(5) : ''
      }
    : (v: string) => v

  // 多日分隔线 + 单日昨收基准线
  const markLines: Array<Record<string, unknown>> = multi
    ? (props.dayMarks ?? [])
        .filter((m) => m.start > 0)
        .map((m) => ({ xAxis: m.start - 0.5, lineStyle: { color: '#3a3f4d', type: 'dashed', width: 1 } }))
    : [{ yAxis: base, lineStyle: { color: '#5c6370', type: 'dashed', width: 1 } }]

  return {
    backgroundColor: 'transparent',
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params: unknown) => {
        const arr = params as Array<{ dataIndex: number }>
        const i = arr[0]?.dataIndex ?? 0
        const p = pts[i]
        if (!p) return ''
        const color = p.price >= base ? UP_COLOR : DOWN_COLOR
        return `${p.datetime.slice(5, 16)}<br/>价 <b style="color:${color}">${fmt2(p.price)}</b><br/>均 ${fmt2(avgPrices[i])}<br/>量 ${p.vol}`
      },
    },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 56, right: 16, top: 16, height: '58%' },
      { left: 56, right: 16, top: '74%', height: '20%' },
    ],
    xAxis: [
      {
        type: 'category',
        gridIndex: 0,
        data: times,
        boundaryGap: false,
        axisLabel: { show: false },
        axisTick: { show: false },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: times,
        boundaryGap: false,
        axisTick: { show: false },
        axisLabel: { interval: labelInterval, formatter: labelFormatter },
      },
    ],
    yAxis: [
      {
        gridIndex: 0,
        min: yMin,
        max: yMax,
        axisLabel: { formatter: (v: number) => fmt2(v) },
        splitLine: { lineStyle: { color: '#2a2e3a' } },
      },
      {
        gridIndex: 1,
        axisLabel: { show: false },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '价格',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: prices,
        showSymbol: false,
        lineStyle: { width: 1.3, color: '#4a9eff' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(74,158,255,0.25)' },
              { offset: 1, color: 'rgba(74,158,255,0.02)' },
            ],
          },
        },
        markLine: {
          silent: true,
          symbol: 'none',
          label: { show: false },
          data: markLines,
        },
      },
      {
        name: '均价',
        type: 'line',
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: avgPrices,
        showSymbol: false,
        lineStyle: { width: 1, color: '#f0a020' },
      },
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: pts.map((p, i) => ({
          value: p.vol,
          itemStyle: { color: volColors[i] },
        })),
        barWidth: '60%',
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
watch(() => [props.points, props.dayMarks], render)
</script>

<template>
  <div ref="container" class="intraday-chart"></div>
</template>

<style scoped>
.intraday-chart {
  width: 100%;
  height: 440px;
}
</style>
