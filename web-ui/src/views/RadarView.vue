<script setup lang="ts">
// 异动雷达（/radar）：沪深异动流时间线（封板/炸板/大笔买入/火箭发射…）
// + 每分钟异动密度柱。异动流为交易所最近交易日的盘中记录；15s 轮询、
// 交易时段外仅手动刷新；类型筛选 chips；单击行直达个股弹窗。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import echarts from '../echarts-setup'
import { fetchUnusual, formatError } from '../api'
import StockDialog from '../components/StockDialog.vue'

type UnusualRow = {
  index: number
  market: number
  code: string
  name: string
  time: string
  desc: string
  value: string
  unusual_type: number
  mkt: string
}

const rows = ref<UnusualRow[]>([])
const loading = ref(false)
const error = ref('')
const lastRefresh = ref('')
const activeType = ref('全部')

let timer = 0

async function load() {
  loading.value = rows.value.length === 0
  error.value = ''
  try {
    const [sh, sz] = await Promise.all([fetchUnusual('SH', 300), fetchUnusual('SZ', 300)])
    rows.value = [...sh, ...sz]
      .map((r) => ({ ...(r as unknown as UnusualRow), mkt: Number(r.market) === 1 ? 'SH' : 'SZ' }))
      .sort((a, b) => b.time.localeCompare(a.time))
    lastRefresh.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    renderDensity()
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

const types = computed(() => {
  const count = new Map<string, number>()
  for (const r of rows.value) count.set(r.desc, (count.get(r.desc) ?? 0) + 1)
  return ['全部', ...[...count.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t)]
})

const filtered = computed(() =>
  activeType.value === '全部' ? rows.value : rows.value.filter((r) => r.desc === activeType.value),
)

function typeCount(t: string): number {
  return t === '全部' ? rows.value.length : (rows.value.filter((r) => r.desc === t).length ?? 0)
}

// ── 密度图（每分钟异动条数） ─────────────────────────────────────────────────

const densityEl = ref<HTMLDivElement>()
let densityChart: echarts.ECharts | null = null

function renderDensity() {
  if (!densityEl.value) return
  const perMinute = new Map<string, number>()
  for (const r of rows.value) {
    const m = r.time.slice(0, 5)
    perMinute.set(m, (perMinute.get(m) ?? 0) + 1)
  }
  const x = [...perMinute.keys()].sort()
  const y = x.map((k) => perMinute.get(k) ?? 0)
  densityChart ??= echarts.init(densityEl.value, 'dark')
  densityChart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      grid: { left: 40, top: 8, bottom: 24, right: 10 },
      xAxis: { type: 'category', data: x, axisLabel: { fontSize: 9 } },
      yAxis: { type: 'value', name: '条/分', nameTextStyle: { fontSize: 9 } },
      series: [
        {
          type: 'bar',
          data: y,
          itemStyle: { color: '#f5a623' },
          barMaxWidth: 6,
        },
      ],
    },
    true,
  )
}

function onResize() {
  densityChart?.resize()
}

function tick() {
  const now = new Date()
  const day = now.getDay()
  if (day === 0 || day === 6 || document.hidden) return
  const m = now.getHours() * 60 + now.getMinutes()
  if ((m >= 555 && m <= 690) || (m >= 780 && m <= 905)) load()
}

const stockDlg = ref<{ market: string; code: string; name: string } | null>(null)

function openStock(r: UnusualRow) {
  stockDlg.value = { market: r.mkt, code: r.code, name: r.name }
}

onMounted(() => {
  load()
  timer = window.setInterval(tick, 15_000)
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  window.clearInterval(timer)
  window.removeEventListener('resize', onResize)
  densityChart?.dispose()
})
</script>

<template>
  <div class="radar-view">
    <div class="view-head">
      <h2>异动雷达</h2>
      <span class="dim head-sub">沪深异动流 · 最近交易日盘中记录</span>
      <span class="tb-spacer"></span>
      <span v-if="lastRefresh" class="dim refresh-ts">{{ lastRefresh }}</span>
      <button class="manual-refresh" @click="load">↻ 刷新</button>
    </div>

    <div v-if="error" class="err card">
      加载失败：{{ error }}
      <button @click="load">重试</button>
    </div>
    <div v-else-if="loading" class="loading">异动流加载中…</div>

    <template v-else>
      <div class="card chart-card">
        <div ref="densityEl" class="density-chart"></div>
      </div>

      <div class="chips">
        <button
          v-for="t in types"
          :key="t"
          class="chip-s"
          :class="{ on: activeType === t }"
          @click="activeType = t"
        >
          {{ t }} <span class="mono dim">{{ typeCount(t) }}</span>
        </button>
      </div>

      <div class="card list-card">
        <div v-for="r in filtered" :key="`${r.mkt}${r.code}${r.time}${r.index}`" class="u-row" @click="openStock(r)">
          <span class="mono u-time">{{ r.time }}</span>
          <span class="u-name">{{ r.name }}</span>
          <span class="mono dim u-code">{{ r.mkt }}·{{ r.code }}</span>
          <span class="u-desc" :class="{ hot: r.desc.includes('涨停') || r.desc.includes('买'), cold: r.desc.includes('跌') }">{{ r.desc }}</span>
          <span class="mono dim u-val">{{ r.value }}</span>
        </div>
        <div v-if="filtered.length === 0" class="empty dim">暂无对应类型的异动记录</div>
      </div>
    </template>

    <StockDialog
      v-if="stockDlg"
      :market="stockDlg.market"
      :code="stockDlg.code"
      :name="stockDlg.name"
      @close="stockDlg = null"
    />
  </div>
</template>

<style scoped>
.radar-view {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.view-head,
.err,
.loading,
.chart-card,
.chips {
  flex-shrink: 0;
}
.view-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.view-head h2 {
  font-size: 17px;
  font-weight: 700;
}
.head-sub {
  font-size: 12px;
}
.tb-spacer {
  flex: 1;
}
.refresh-ts {
  font-family: var(--font-mono);
  font-size: 11.5px;
}
.manual-refresh {
  font-size: 12px;
  padding: 4px 10px;
}
.err {
  color: var(--up);
  display: flex;
  align-items: center;
  gap: 10px;
}
.loading {
  padding: 40px 0;
  text-align: center;
  color: var(--text-dim);
}
.chart-card {
  padding: 6px;
}
.density-chart {
  height: 110px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip-s {
  padding: 3px 10px;
  font-size: 11.5px;
  border-radius: 999px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  cursor: pointer;
}
.chip-s.on {
  border-color: var(--accent);
  color: var(--accent);
}
.list-card {
  padding: 4px 0;
}
.u-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 5px 14px;
  font-size: 12.5px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
}
.u-row:last-child {
  border-bottom: none;
}
.u-row:hover {
  background: var(--bg-elevated);
}
.u-time {
  font-size: 11.5px;
  color: var(--text-dim);
  width: 62px;
}
.u-name {
  font-weight: 600;
  width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.u-code {
  font-size: 11px;
  width: 100px;
}
.u-desc {
  flex: 1;
}
.u-desc.hot {
  color: var(--up);
}
.u-desc.cold {
  color: var(--down);
}
.u-val {
  font-size: 11px;
}
.empty {
  padding: 24px 0;
  text-align: center;
  font-size: 12px;
}
</style>
