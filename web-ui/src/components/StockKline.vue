<script setup lang="ts">
// 个股日K图：candlestick + 成交量 + 可选主图指标（MA/BOLL/EMA）
// + 可选副图指标（MACD/KDJ/RSI）。指标由父组件传选择，前端本地计算
// （indicators.ts，与后端 MyTT 同口径）。

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import echarts, { DOWN_COLOR, UP_COLOR } from '../echarts-setup'
import { boll, ema, macd as calcMacd, kdj as calcKdj, rsi as calcRsi } from '../indicators'
import { fmt2 } from '../format'
import type { Bar } from '../types'

export type Overlay = 'none' | 'ma' | 'boll' | 'ema'
export type SubPane = 'none' | 'macd' | 'kdj' | 'rsi'

const props = defineProps<{
  bars: Bar[]
  overlay?: Overlay
  subPane?: SubPane
}>()

const container = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

const closes = computed(() => props.bars.map((b) => b.close))
const highs = computed(() => props.bars.map((b) => b.high))
const lows = computed(() => props.bars.map((b) => b.low))

interface LineSpec {
  name: string
  data: Array<number | null>
  color: string
  dashed?: boolean
}

/** 主图指标线（随 overlay 切换）。 */
const overlayLines = computed<LineSpec[]>(() => {
  const c = closes.value
  if (props.overlay === 'ma') {
    const colors = ['#f0a020', '#4a9eff', '#c084fc', '#22d3ee']
    return [5, 10, 20, 60].map((n, i) => ({
      name: `MA${n}`,
      data: maLocal(c, n),
      color: colors[i],
    }))
  }
  if (props.overlay === 'ema') {
    return [
      { name: 'EMA12', data: ema(c, 12), color: '#f0a020' },
      { name: 'EMA26', data: ema(c, 26), color: '#4a9eff' },
    ]
  }
  if (props.overlay === 'boll') {
    const { mid, upper, lower } = boll(c)
    return [
      { name: 'BOLL中轨', data: mid, color: '#f0a020' },
      { name: '上轨', data: upper, color: '#c084fc', dashed: true },
      { name: '下轨', data: lower, color: '#c084fc', dashed: true },
    ]
  }
  return []
})

function maLocal(data: number[], n: number): Array<number | null> {
  const out: Array<number | null> = []
  let sum = 0
  for (let i = 0; i < data.length; i++) {
    sum += data[i]
    if (i >= n) sum -= data[i - n]
    out.push(i >= n - 1 ? sum / n : null)
  }
  return out
}

function render() {
  if (!container.value || props.bars.length === 0) return
  chart ??= echarts.init(container.value, 'dark')
  chart.setOption(buildOption(), true)
}

function buildOption(): echarts.EChartsCoreOption {
  const bars = props.bars
  const dates = bars.map((b) => b.datetime.slice(0, 10))
  const ohlc = bars.map((b) => [b.open, b.close, b.low, b.high])
  const hasSub = props.subPane !== 'none'
  const start = Math.max(0, 100 - (120 / bars.length) * 100)

  // 布局：K 区 / 量区 /（可选）副图区
  const grids = [
    { left: 56, right: 16, top: 28, height: hasSub ? '48%' : '60%' },
    { left: 56, right: 16, top: hasSub ? '64%' : '74%', height: hasSub ? '13%' : '18%' },
  ]
  const xAxes: echarts.EChartsCoreOption[] = [
    { type: 'category', gridIndex: 0, data: dates, boundaryGap: true, axisLabel: { show: false }, axisTick: { show: false } },
    { type: 'category', gridIndex: 1, data: dates, boundaryGap: true, axisTick: { show: false } },
  ]
  const yAxes: echarts.EChartsCoreOption[] = [
    { gridIndex: 0, scale: true, axisLabel: { formatter: (v: number) => fmt2(v) }, splitLine: { lineStyle: { color: '#2a2e3a' } } },
    { gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
  ]
  if (hasSub) {
    grids.push({ left: 56, right: 16, top: '81%', height: '13%' } as never)
    xAxes.push({ type: 'category', gridIndex: 2, data: dates, boundaryGap: true, axisTick: { show: false } })
    yAxes.push({ gridIndex: 2, scale: true, axisLabel: { fontSize: 10 }, splitLine: { show: false } })
  }

  const series: echarts.EChartsCoreOption[] = [
    {
      name: 'K线',
      type: 'candlestick',
      xAxisIndex: 0,
      yAxisIndex: 0,
      data: ohlc,
      itemStyle: {
        color: UP_COLOR,
        color0: DOWN_COLOR,
        borderColor: UP_COLOR,
        borderColor0: DOWN_COLOR,
      },
    },
    ...overlayLines.value.map(
      (l) =>
        ({
          name: l.name,
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: l.data,
          showSymbol: false,
          connectNulls: false,
          lineStyle: { width: 1, color: l.color, type: l.dashed ? 'dashed' : 'solid' },
          itemStyle: { color: l.color },
        }) as never,
    ),
    {
      name: '成交量',
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: bars.map((b) => ({
        value: b.vol,
        itemStyle: { color: b.close >= b.open ? UP_COLOR : DOWN_COLOR },
      })),
      barWidth: '60%',
    },
  ]

  // 副图指标
  const c = closes.value
  if (props.subPane === 'macd') {
    const { dif, dea, hist } = calcMacd(c)
    series.push(
      {
        name: 'DIF',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: dif,
        showSymbol: false,
        lineStyle: { width: 1, color: '#f0a020' },
      },
      {
        name: 'DEA',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: dea,
        showSymbol: false,
        lineStyle: { width: 1, color: '#4a9eff' },
      },
      {
        name: 'MACD',
        type: 'bar',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: hist.map((v) => ({
          value: v,
          itemStyle: { color: (v ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR },
        })),
        barWidth: '50%',
      },
    )
  } else if (props.subPane === 'kdj') {
    const { k, d, j } = calcKdj(highs.value, lows.value, c)
    series.push(
      {
        name: 'K',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: k,
        showSymbol: false,
        lineStyle: { width: 1, color: '#f0a020' },
      },
      {
        name: 'D',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: d,
        showSymbol: false,
        lineStyle: { width: 1, color: '#4a9eff' },
      },
      {
        name: 'J',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: j,
        showSymbol: false,
        lineStyle: { width: 1, color: '#c084fc' },
      },
    )
  } else if (props.subPane === 'rsi') {
    series.push(
      {
        name: 'RSI6',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: calcRsi(c, 6),
        showSymbol: false,
        lineStyle: { width: 1, color: '#f0a020' },
      },
      {
        name: 'RSI12',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: calcRsi(c, 12),
        showSymbol: false,
        lineStyle: { width: 1, color: '#4a9eff' },
      },
      {
        name: 'RSI24',
        type: 'line',
        xAxisIndex: 2,
        yAxisIndex: 2,
        data: calcRsi(c, 24),
        showSymbol: false,
        lineStyle: { width: 1, color: '#c084fc' },
      },
    )
  }

  const legendNames = ['K线', ...overlayLines.value.map((l) => l.name)]
  if (hasSub) {
    legendNames.push(
      props.subPane === 'macd' ? 'DIF,DEA' : props.subPane === 'kdj' ? 'K,D,J' : 'RSI',
    )
  }

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      // OHLC/指标全部两位小数（用户约定：价格一律 2 位）
      valueFormatter: (v: number | string) => fmt2(Number(v)),
    },
    legend: { data: legendNames, top: 0, textStyle: { fontSize: 11 } },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1, ...(hasSub ? [2] : [])], start, end: 100 },
      { type: 'slider', xAxisIndex: [0, 1, ...(hasSub ? [2] : [])], bottom: 4, start, end: 100, height: 16 },
    ],
    series,
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
watch(() => [props.bars, props.overlay, props.subPane], render, { deep: false })
</script>

<template>
  <div ref="container" class="stock-kline"></div>
</template>

<style scoped>
.stock-kline {
  width: 100%;
  height: 520px;
}
</style>
