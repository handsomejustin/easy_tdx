<script setup lang="ts">
// 市场热点滚动（/hotspots）：交易日 × 板块涨跌矩阵，直观展示热点形成/持续/轮动/领跌。
// 首次构建走后端后台任务（1s 轮询进度），完成后当日缓存；盘中 60s 轮询仅滚动今日列。
// 单击板块复用 BoardDialog。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { fetchBoardHotspot, formatError } from '../api'
import BoardDialog from '../components/BoardDialog.vue'
import HotspotMatrix from '../components/HotspotMatrix.vue'
import HotspotStatStrip from '../components/HotspotStatStrip.vue'
import type { HotspotResp, HotspotRow } from '../types'

// boardType 可由路由 props 注入（/styles → FG 风格轮动），页内仍可自由切换
const props = defineProps<{ boardType?: 'HY' | 'GN' | 'FG' }>()

const PER_DAY = 5 // 每日前 5 名入选（与后端默认一致）

type SortKey = 'days_in' | 'sum_pct' | 'first_date'

const boardType = ref<'HY' | 'GN' | 'FG'>(props.boardType ?? 'HY')
const days = ref<number>(20)
const mode = ref<'top' | 'bottom'>('top')

watch(
  () => props.boardType,
  (t) => {
    if (t && t !== boardType.value) setType(t)
  },
)

const typeLabels: Record<'HY' | 'GN' | 'FG', string> = { HY: '行业', GN: '概念', FG: '风格' }

const dayOptions: Array<{ v: number; label: string }> = [
  { v: 1, label: '今日' },
  { v: 10, label: '近10日' },
  { v: 20, label: '近20日' },
  { v: 30, label: '近30日' },
]

// ── 数据状态机：loading → building(进度) → ready / error ─────────────────────

const resp = ref<HotspotResp | null>(null)
const buildingProgress = ref<number | null>(null) // null = 非构建中
const buildError = ref('')
const loading = ref(false)
const lastRefresh = ref('')

let buildTimer = 0

function stopBuildPoll() {
  if (buildTimer) {
    window.clearInterval(buildTimer)
    buildTimer = 0
  }
}

async function load(retry = false) {
  try {
    const r = await fetchBoardHotspot(boardType.value, days.value, mode.value, PER_DAY, retry)
    if (r.status === 'building') {
      buildError.value = ''
      resp.value = null
      loading.value = false
      buildingProgress.value = r.progress ?? 0
      if (!buildTimer) buildTimer = window.setInterval(pollBuild, 1000)
      return
    }
    stopBuildPoll()
    buildingProgress.value = null
    if (r.status === 'error') {
      buildError.value = r.error || '热点矩阵构建失败'
      return
    }
    buildError.value = ''
    resp.value = r
    loading.value = false
    lastRefresh.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } catch (e) {
    stopBuildPoll()
    buildingProgress.value = null
    buildError.value = formatError(e)
  }
}

function pollBuild() {
  if (!document.hidden) load()
}

const buildPct = computed(() => Math.round((buildingProgress.value ?? 0) * 100))

function setType(t: 'HY' | 'GN' | 'FG') {
  if (boardType.value === t) return
  boardType.value = t
  resetAndLoad()
}
function setDays(d: number) {
  if (days.value === d) return
  days.value = d
  resetAndLoad()
}
function setMode(m: 'top' | 'bottom') {
  if (mode.value === m) return
  mode.value = m
  resetAndLoad()
}
function resetAndLoad() {
  stopBuildPoll()
  resp.value = null
  buildingProgress.value = null
  buildError.value = ''
  loading.value = true
  load()
}

// ── 行排序 / 过滤（数据已全量在内存，纯前端） ─────────────────────────────────

const search = ref('')
const onlyMulti = ref(false)
const sortKey = ref<SortKey>('days_in')

const dates = computed(() => resp.value?.dates ?? [])
const perDay = computed(() => resp.value?.per_day ?? PER_DAY)
const todayIndex = computed(() => resp.value?.today_index ?? null)

const displayRows = computed<HotspotRow[]>(() => {
  let out = resp.value?.rows ?? []
  const q = search.value.trim().toLowerCase()
  if (q) out = out.filter((r) => r.name.toLowerCase().includes(q) || r.code.includes(q))
  if (onlyMulti.value) out = out.filter((r) => r.days_in >= 2)
  return [...out].sort((a, b) => {
    switch (sortKey.value) {
      case 'sum_pct':
        return (b.sum_pct ?? -Infinity) - (a.sum_pct ?? -Infinity)
      case 'first_date':
        return (b.first_date ?? '').localeCompare(a.first_date ?? '') // 新热点在前
      default:
        return b.days_in - a.days_in || (b.sum_pct ?? 0) - (a.sum_pct ?? 0)
    }
  })
})

// ── 轮询调度（同行业总览：交易时段门控 + 页面隐藏暂停） ───────────────────────

let refreshTimer = 0
let sessionTimer = 0

const sessionGated = ref(localStorage.getItem('hotspot.sessionGated') !== '0')
function onSessionToggle() {
  localStorage.setItem('hotspot.sessionGated', sessionGated.value ? '1' : '0')
}

function isTradeSession(now = new Date()): boolean {
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const m = now.getHours() * 60 + now.getMinutes()
  return (m >= 555 && m <= 690) || (m >= 780 && m <= 905)
}

const inSession = ref(isTradeSession())
const autoPaused = computed(() => sessionGated.value && !inSession.value)
const sessionLabel = computed(() => {
  if (!sessionGated.value) return '全天候模式'
  return inSession.value ? '交易中' : '休市 · 自动刷新已暂停'
})

function tick() {
  inSession.value = isTradeSession()
  if (autoPaused.value || document.hidden) return
  if (resp.value) load() // 历史列服务端当日缓存，仅今日列滚动，请求很快
}

onMounted(() => {
  load()
  refreshTimer = window.setInterval(tick, 60_000)
  sessionTimer = window.setInterval(() => {
    inSession.value = isTradeSession()
  }, 60_000)
})
onBeforeUnmount(() => {
  stopBuildPoll()
  window.clearInterval(refreshTimer)
  window.clearInterval(sessionTimer)
})

// ── 弹窗（板块详情） ─────────────────────────────────────────────────────────

const boardDialog = ref<{ code: string; name: string } | null>(null)

function openBoard(r: HotspotRow) {
  boardDialog.value = { code: r.code, name: r.name }
}
</script>

<template>
  <div class="hotspot-view">
    <div class="view-head">
      <h2>热点滚动</h2>
      <span class="dim head-sub">板块热点的形成 · 持续 · 轮动</span>
      <span v-if="resp?.total_boards" class="dim head-sub">参与板块 {{ resp.total_boards }}</span>
      <span v-if="resp?.session === 'live'" class="live-badge">今日列 · 实时</span>
    </div>

    <!-- 工具行 -->
    <div class="toolbar">
      <span class="seg">
        <button
          v-for="t in (['HY', 'GN', 'FG'] as const)"
          :key="t"
          :class="{ on: boardType === t }"
          @click="setType(t)"
        >
          {{ typeLabels[t] }}
        </button>
      </span>
      <span class="seg">
        <button
          v-for="o in dayOptions"
          :key="o.v"
          :class="{ on: days === o.v }"
          :title="o.v === 1 ? '今日领涨/领跌前5名' : undefined"
          @click="setDays(o.v)"
        >
          {{ o.label }}
        </button>
      </span>
      <span class="seg">
        <button :class="{ on: mode === 'top' }" @click="setMode('top')">领涨</button>
        <button :class="{ on: mode === 'bottom' }" @click="setMode('bottom')">领跌</button>
      </span>
      <label class="tb-label">排序
        <select v-model="sortKey">
          <option value="days_in">上榜次数</option>
          <option value="sum_pct">累计涨跌</option>
          <option value="first_date">最新上榜</option>
        </select>
      </label>
      <label class="tb-label multi-toggle">
        <input v-model="onlyMulti" type="checkbox" />
        只看上榜≥2次
      </label>
      <input v-model="search" class="search" type="text" placeholder="搜索板块名/代码" />
      <span class="tb-spacer"></span>
      <span class="dot" :class="{ live: !autoPaused }"></span>
      <span class="session-label" :class="{ paused: autoPaused }">{{ sessionLabel }}</span>
      <label class="session-toggle">
        <input v-model="sessionGated" type="checkbox" @change="onSessionToggle" />
        仅交易时段刷新
      </label>
      <span v-if="lastRefresh" class="dim refresh-ts">{{ lastRefresh }}</span>
      <button class="manual-refresh" @click="load()">↻ 刷新</button>
    </div>

    <!-- 构建中 / 失败 -->
    <div v-if="buildingProgress !== null" class="building card">
      <div class="build-text">正在构建板块日K矩阵 … {{ buildPct }}%</div>
      <div class="build-bar">
        <div class="build-fill" :style="{ width: buildPct + '%' }"></div>
      </div>
      <div class="dim build-hint">
        首次构建需逐板块拉取日K（{{ boardType === 'GN' ? '概念板块数量多，' : '' }}约需数十秒），
        完成后当日缓存、秒级刷新
      </div>    </div>
    <div v-else-if="buildError" class="err card">
      构建失败：{{ buildError }}
      <button @click="load(true)">重试</button>
    </div>

    <div v-else-if="loading" class="loading">加载中…</div>

    <!-- 主区：统计卡 + 图例 + 矩阵 -->
    <template v-else-if="resp">
      <HotspotStatStrip :rows="resp.rows ?? []" :dates="dates" :mode="mode" @select="openBoard" />

      <div class="legend">
        <span class="lg-title">色阶</span>
        <i class="sw u1"></i><i class="sw u2"></i><i class="sw u3"></i>
        <span>涨</span>
        <i class="sw d1"></i><i class="sw d2"></i><i class="sw d3"></i>
        <span>跌（越深幅度越大）</span>
        <span class="lg-sep">|</span>
        <span><b class="lg-rank">①~⑤</b> 当日前 {{ perDay }} 名（{{ mode === 'top' ? '最强' : '最弱' }}）</span>
        <span>描边 = 当日前 3 名</span>
        <span class="lg-sep">|</span>
        <span>单击板块看分时/日K/成分股</span>
      </div>

      <div class="matrix-card card">
        <HotspotMatrix
          :dates="dates"
          :rows="displayRows"
          :per-day="perDay"
          :today-index="todayIndex"
          :mode="mode"
          @select="openBoard"
        />
      </div>
    </template>

    <BoardDialog
      v-if="boardDialog"
      :code="boardDialog.code"
      :name="boardDialog.name"
      @close="boardDialog = null"
    />
  </div>
</template>

<style scoped>
.hotspot-view {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.view-head,
.toolbar,
.legend,
.building,
.err,
.loading {
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
.live-badge {
  font-size: 11px;
  color: var(--up);
  border: 1px solid var(--up);
  border-radius: 3px;
  padding: 0 6px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.seg {
  display: inline-flex;
}
.seg button {
  border-radius: 0;
  font-size: 12px;
  padding: 4px 12px;
}
.seg button:first-child {
  border-radius: var(--radius) 0 0 var(--radius);
}
.seg button:last-child {
  border-radius: 0 var(--radius) var(--radius) 0;
  margin-left: -1px;
}
.seg button.on {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(74, 158, 255, 0.12);
  position: relative;
  z-index: 1;
}
.tb-label {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 0;
  font-size: 12px;
  color: var(--text-muted);
}
.tb-label select {
  width: auto;
  padding: 4px 8px;
  font-size: 12px;
}
.multi-toggle input {
  width: auto;
}
.search {
  width: 170px;
  padding: 4px 10px;
  font-size: 12px;
}
.tb-spacer {
  flex: 1;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-dim);
}
.dot.live {
  background: var(--up);
  box-shadow: 0 0 4px var(--up);
}
.session-label {
  font-size: 11.5px;
  color: var(--text-muted);
}
.session-label.paused {
  color: var(--warn);
}
.session-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 0;
  font-size: 11.5px;
  color: var(--text-muted);
  white-space: nowrap;
}
.session-toggle input {
  width: auto;
}
.refresh-ts {
  font-family: var(--font-mono);
  font-size: 11.5px;
}
.manual-refresh {
  font-size: 12px;
  padding: 4px 10px;
}
.building {
  padding: 18px 20px;
}
.build-text {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}
.build-bar {
  height: 8px;
  background: var(--bg-elevated);
  border-radius: 4px;
  overflow: hidden;
}
.build-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 4px;
  transition: width 0.4s ease;
}
.build-hint {
  font-size: 11.5px;
  margin-top: 8px;
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
.legend {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 11.5px;
  color: var(--text-muted);
}
.lg-title {
  color: var(--text-dim);
}
.sw {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 2px;
  margin: 0 1px;
  vertical-align: -2px;
}
.sw.u1 {
  background: rgba(239, 65, 70, 0.26);
}
.sw.u2 {
  background: rgba(239, 65, 70, 0.5);
}
.sw.u3 {
  background: rgba(239, 65, 70, 0.82);
}
.sw.d1 {
  background: rgba(24, 160, 88, 0.26);
}
.sw.d2 {
  background: rgba(24, 160, 88, 0.5);
}
.sw.d3 {
  background: rgba(24, 160, 88, 0.82);
}
.lg-sep {
  color: var(--border);
}
.lg-rank {
  color: var(--text);
}
.matrix-card {
  padding: 8px;
}
.matrix-card :deep(.matrix-wrap) {
  max-height: calc(100vh - 380px);
}
</style>
