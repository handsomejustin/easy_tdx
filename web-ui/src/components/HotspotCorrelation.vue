<script setup lang="ts">
// 热点板块相关性热力图：窗口内活跃板块两两日涨跌幅 Pearson 相关。
// 红 = 同涨同跌（抱团），绿 = 跷跷板（资金轮动换手）。复用热点历史缓存，秒级出图。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import echarts, { DOWN_COLOR, UP_COLOR } from '../echarts-setup'
import { fetchHotspotCorrelation, formatError } from '../api'
import type { HotspotCorrelationResp } from '../types'

const props = defineProps<{
  boardType: 'HY' | 'GN' | 'FG'
  days: number
  perDay: number
}>()

const resp = ref<HotspotCorrelationResp | null>(null)
const error = ref('')
const loading = ref(false)

let poll: number | null = null

function stopPoll() {
  if (poll !== null) {
    window.clearInterval(poll)
    poll = null
  }
}

async function load() {
  error.value = ''
  try {
    const r = await fetchHotspotCorrelation(props.boardType, props.days, props.perDay)
    if (r.status === 'building') {
      resp.value = null
      loading.value = true
      if (poll === null) poll = window.setInterval(load, 1500)
      return
    }
    stopPoll()
    loading.value = false
    if (r.status === 'error') {
      error.value = r.error || '相关性矩阵不可用'
      return
    }
    resp.value = r
    render()
  } catch (e) {
    stopPoll()
    loading.value = false
    error.value = formatError(e)
  }
}

// ── 热力图渲染 ────────────────────────────────────────────────────────────────

const container = ref<HTMLDivElement>()
let chart: echarts.ECharts | null = null

function render() {
  if (!container.value || !resp.value?.boards || !resp.value.matrix) return
  const boards = resp.value.boards
  const matrix = resp.value.matrix
  const names = boards.map((b) => b.name)
  const data: Array<[number, number, number]> = []
  matrix.forEach((row, i) =>
    row.forEach((v, j) => {
      if (v !== null) data.push([i, j, v])
    }),
  )
  chart ??= echarts.init(container.value, 'dark')
  chart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: {
        formatter: (p: { value: [number, number, number] }) => {
          const [i, j, v] = p.value
          return `${names[i]} × ${names[j]}<br/>相关系数 <b>${v.toFixed(2)}</b>`
        },
      },
      grid: { left: 90, top: 10, bottom: 90, right: 20 },
      xAxis: {
        type: 'category',
        data: names,
        axisLabel: { rotate: 45, fontSize: 10, interval: 0 },
      },
      yAxis: { type: 'category', data: names, axisLabel: { fontSize: 10 } },
      visualMap: {
        min: -1,
        max: 1,
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 0,
        text: ['同涨同跌', '跷跷板'],
        textStyle: { fontSize: 10 },
        inRange: { color: [DOWN_COLOR, '#1f2430', UP_COLOR] },
      },
      series: [
        {
          type: 'heatmap',
          data,
          label: { show: boards.length <= 12, fontSize: 9, formatter: (p: { value: [number, number, number] }) => p.value[2].toFixed(1) },
        },
      ],
    },
    true,
  )
}

function onResize() {
  chart?.resize()
}

onMounted(() => {
  load()
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  stopPoll()
  window.removeEventListener('resize', onResize)
  chart?.dispose()
})

watch(
  () => [props.boardType, props.days, props.perDay],
  () => {
    resp.value = null
    load()
  },
)
</script>

<template>
  <div class="corr-wrap card">
    <div v-if="loading" class="corr-hint dim">等待热点矩阵构建（若行业矩阵已构建则为秒级）…</div>
    <div v-else-if="error" class="corr-hint up">{{ error }}</div>
    <div v-else-if="resp && (resp.boards?.length ?? 0) < 2" class="corr-hint dim">窗口内活跃板块不足 2 个，无法计算相关性</div>
    <div v-else ref="container" class="corr-chart"></div>
  </div>
</template>

<style scoped>
.corr-wrap {
  padding: 8px;
}
.corr-chart {
  height: 520px;
}
.corr-hint {
  padding: 40px 0;
  text-align: center;
  font-size: 12px;
}
</style>
