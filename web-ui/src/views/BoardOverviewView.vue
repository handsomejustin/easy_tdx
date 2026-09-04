<script setup lang="ts">
// 行业/概念总览（/industries、/concepts 共用，路由 props 区分 board_type）。
// 顶部统计条 + [热力图|表格] 主区 + 右栏榜单异动；单击板块复用 BoardDialog。
// 数据走 /board-mac/overview（服务端归并多排序键，15s 缓存），30s 轮询、休市暂停。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import {
  fetchBoardOverview,
  fetchMarketStat,
  formatError,
} from '../api'
import { dirClass, fmt2, fmtPctSigned } from '../format'
import BoardDialog from '../components/BoardDialog.vue'
import BoardRankRail from '../components/BoardRankRail.vue'
import BoardStatStrip from '../components/BoardStatStrip.vue'
import BoardTiles from '../components/BoardTiles.vue'
import type { BoardFlipEvent, BoardOverviewRow, MarketStat } from '../types'

const props = defineProps<{
  boardType: 'HY' | 'GN'
}>()

// 行业页可切一级(HY)/二级(HY2)分类；概念页固定 GN
const activeType = ref<'HY' | 'HY2' | 'GN'>(props.boardType)
const isIndustry = computed(() => props.boardType !== 'GN')

const title = computed(() => (props.boardType === 'GN' ? '概念总览' : '行业总览'))
const titleSub = computed(() =>
  props.boardType !== 'GN' && activeType.value === 'HY2' ? '二级' : '',
)

// ── 数据状态 ──────────────────────────────────────────────────────────────────

const rows = ref<BoardOverviewRow[]>([])
const loading = ref(false)
const error = ref('')
const lastRefresh = ref('')
const stat = ref<MarketStat | null>(null)

async function loadOverview() {
  loading.value = rows.value.length === 0
  error.value = ''
  try {
    const resp = await fetchBoardOverview(activeType.value)
    rows.value = resp.rows
    lastRefresh.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    diffFlips(resp.rows)
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

async function loadStat() {
  try {
    stat.value = await fetchMarketStat()
  } catch {
    stat.value = null // 统计条独立降级，不打扰主数据
  }
}

// ── 翻红/翻绿：对相邻两次快照按涨跌幅符号 diff ────────────────────────────────

const flips = ref<BoardFlipEvent[]>([])
let snapshot: Map<string, number> | null = null

function diffFlips(fresh: BoardOverviewRow[]) {
  const now = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  const next = new Map<string, number>()
  const names = new Map<string, string>()
  for (const r of fresh) {
    if (r.change_pct !== null && r.change_pct !== undefined) next.set(r.code, r.change_pct)
    names.set(r.code, r.name)
  }
  if (snapshot) {
    const events: BoardFlipEvent[] = []
    for (const [code, pct] of next) {
      const before = snapshot.get(code)
      if (before === undefined) continue
      if (before <= 0 && pct > 0) {
        events.push({ code, name: names.get(code) ?? code, type: 'up', time: now, change_pct: pct })
      } else if (before >= 0 && pct < 0) {
        events.push({ code, name: names.get(code) ?? code, type: 'down', time: now, change_pct: pct })
      }
    }
    if (events.length > 0) flips.value = [...events, ...flips.value].slice(0, 30)
  }
  snapshot = next
}

// ── 工具行：视图模式 / 排序 / 搜索 / 分类切换 ─────────────────────────────────

type SortKey = 'change_pct' | 'speed' | 'chg_3d' | 'chg_5d' | 'chg_20d' | 'chg_ytd'

const viewMode = ref<'tiles' | 'table'>(
  localStorage.getItem('board.viewMode') === 'table' ? 'table' : 'tiles',
)
function setViewMode(m: 'tiles' | 'table') {
  viewMode.value = m
  localStorage.setItem('board.viewMode', m)
}

const sortKey = ref<SortKey>('change_pct')
const sortOptions: Array<{ value: SortKey; label: string }> = [
  { value: 'change_pct', label: '涨跌幅' },
  { value: 'speed', label: '涨速' },
  { value: 'chg_3d', label: '3日' },
  { value: 'chg_5d', label: '5日' },
  { value: 'chg_20d', label: '20日' },
  { value: 'chg_ytd', label: '年初至今' },
]

const search = ref('')

const filteredRows = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter(
    (r) => r.name.toLowerCase().includes(q) || r.code.includes(q),
  )
})

const sortedRows = computed(() => {
  const key = sortKey.value
  return [...filteredRows.value].sort((a, b) => {
    const av = a[key]
    const bv = b[key]
    if (av === null || av === undefined) return 1 // null 沉底
    if (bv === null || bv === undefined) return -1
    return bv - av
  })
})

function setLevel(t: 'HY' | 'HY2') {
  if (activeType.value === t) return
  activeType.value = t
  resetAndReload()
}

function resetAndReload() {
  rows.value = []
  flips.value = []
  snapshot = null
  loadOverview()
}

watch(
  () => props.boardType,
  (t) => {
    activeType.value = t
    search.value = ''
    resetAndReload()
  },
)

// ── 轮询调度（同 Dashboard：交易时段门控 + 页面隐藏暂停） ──────────────────────

let timer = 0
let sessionTimer = 0

const sessionGated = ref(localStorage.getItem('board.sessionGated') !== '0')
function onSessionToggle() {
  localStorage.setItem('board.sessionGated', sessionGated.value ? '1' : '0')
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
  loadOverview()
  loadStat()
}

function refreshAll() {
  loadOverview()
  loadStat()
}

onMounted(() => {
  refreshAll()
  timer = window.setInterval(tick, 30_000)
  sessionTimer = window.setInterval(() => {
    inSession.value = isTradeSession()
  }, 60_000)
})
onBeforeUnmount(() => {
  window.clearInterval(timer)
  window.clearInterval(sessionTimer)
})

// ── 弹窗（板块详情） ─────────────────────────────────────────────────────────

const boardDialog = ref<{ code: string; name: string } | null>(null)

function openBoard(r: BoardOverviewRow) {
  boardDialog.value = { code: r.code, name: r.name }
}
</script>

<template>
  <div class="board-view">
    <div class="view-head">
      <h2>{{ title }}<span v-if="titleSub" class="dim head-sub">{{ titleSub }}</span></h2>
      <template v-if="isIndustry">
        <button class="chip" :class="{ on: activeType === 'HY' }" @click="setLevel('HY')">一级</button>
        <button class="chip" :class="{ on: activeType === 'HY2' }" @click="setLevel('HY2')">二级</button>
      </template>
    </div>

    <BoardStatStrip :rows="rows" :stat="stat" />

    <!-- 工具行 -->
    <div class="toolbar">
      <span class="seg">
        <button :class="{ on: viewMode === 'tiles' }" @click="setViewMode('tiles')">热力图</button>
        <button :class="{ on: viewMode === 'table' }" @click="setViewMode('table')">表格</button>
      </span>
      <label class="tb-label">排序
        <select v-model="sortKey">
          <option v-for="o in sortOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </label>
      <input v-model="search" class="search" type="text" :placeholder="isIndustry ? '搜索行业名/代码' : '搜索概念名/代码'" />
      <span class="tb-spacer"></span>
      <span class="dot" :class="{ live: !autoPaused }"></span>
      <span class="session-label" :class="{ paused: autoPaused }">{{ sessionLabel }}</span>
      <label class="session-toggle">
        <input v-model="sessionGated" type="checkbox" @change="onSessionToggle" />
        仅交易时段刷新
      </label>
      <span v-if="lastRefresh" class="dim refresh-ts">{{ lastRefresh }}</span>
      <button class="manual-refresh" @click="refreshAll">↻ 刷新</button>
    </div>

    <div v-if="error" class="err card">
      加载失败：{{ error }}
      <button @click="refreshAll">重试</button>
    </div>
    <div v-else-if="loading" class="loading">板块数据加载中…</div>

    <!-- 主区 + 右栏 -->
    <div v-show="!error && !loading" class="content">
      <div class="main-area card">
        <BoardTiles
          v-if="viewMode === 'tiles'"
          :rows="sortedRows"
          :tile-min-width="isIndustry ? 104 : 88"
          @select="openBoard"
        />
        <table v-else class="qtable board-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>代码</th>
              <th>最新价</th>
              <th class="sortable" :class="{ on: sortKey === 'change_pct' }" @click="sortKey = 'change_pct'">
                涨跌幅{{ sortKey === 'change_pct' ? ' ▾' : '' }}
              </th>
              <th class="sortable" :class="{ on: sortKey === 'speed' }" @click="sortKey = 'speed'">
                涨速{{ sortKey === 'speed' ? ' ▾' : '' }}
              </th>
              <th class="sortable" :class="{ on: sortKey === 'chg_3d' }" @click="sortKey = 'chg_3d'">
                3日{{ sortKey === 'chg_3d' ? ' ▾' : '' }}
              </th>
              <th class="sortable" :class="{ on: sortKey === 'chg_5d' }" @click="sortKey = 'chg_5d'">
                5日{{ sortKey === 'chg_5d' ? ' ▾' : '' }}
              </th>
              <th class="sortable" :class="{ on: sortKey === 'chg_20d' }" @click="sortKey = 'chg_20d'">
                20日{{ sortKey === 'chg_20d' ? ' ▾' : '' }}
              </th>
              <th class="sortable" :class="{ on: sortKey === 'chg_ytd' }" @click="sortKey = 'chg_ytd'">
                YTD{{ sortKey === 'chg_ytd' ? ' ▾' : '' }}
              </th>
              <th>领涨股</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in sortedRows" :key="r.code" class="clickable" @click="openBoard(r)">
              <td class="name-cell">{{ r.name }}</td>
              <td class="dim">{{ r.code }}</td>
              <td class="mono">{{ fmt2(r.price) }}</td>
              <td class="mono" :class="dirClass(r.change_pct)">{{ fmtPctSigned(r.change_pct) }}</td>
              <td class="mono" :class="dirClass(r.speed)">{{ fmtPctSigned(r.speed) }}</td>
              <td class="mono" :class="dirClass(r.chg_3d)">{{ fmtPctSigned(r.chg_3d) }}</td>
              <td class="mono" :class="dirClass(r.chg_5d)">{{ fmtPctSigned(r.chg_5d) }}</td>
              <td class="mono" :class="dirClass(r.chg_20d)">{{ fmtPctSigned(r.chg_20d) }}</td>
              <td class="mono" :class="dirClass(r.chg_ytd)">{{ fmtPctSigned(r.chg_ytd) }}</td>
              <td class="leader-cell">
                <span v-if="r.leader_name">{{ r.leader_name }}</span>
                <span class="mono" :class="dirClass(r.leader_change_pct)">{{ fmtPctSigned(r.leader_change_pct) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="viewMode === 'table' && sortedRows.length === 0" class="loading">没有匹配的板块</div>
      </div>
      <BoardRankRail class="rail-area" :rows="rows" :flips="flips" @select="openBoard" />
    </div>

    <BoardDialog
      v-if="boardDialog"
      :code="boardDialog.code"
      :name="boardDialog.name"
      @close="boardDialog = null"
    />
  </div>
</template>

<style scoped>
.board-view {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
/* flex 列内子项按内容占位，禁止被压缩（容器超高时靠 overflow-y 滚动） */
.view-head,
.toolbar,
.stat-strip,
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
  font-weight: 400;
  margin-left: 6px;
}
.chip {
  padding: 2px 10px;
  font-size: 11.5px;
}
.chip.on {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(74, 158, 255, 0.12);
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
.search {
  width: 180px;
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
.content {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 10px;
  align-items: start;
}
.main-area {
  padding: 10px;
  min-height: 300px;
}
.board-table th.sortable {
  cursor: pointer;
}
.board-table th.sortable:hover,
.board-table th.sortable.on {
  color: var(--accent);
}
.board-table td.name-cell {
  font-weight: 600;
}
.board-table .leader-cell span:first-child {
  margin-right: 8px;
}
@media (max-width: 1280px) {
  .content {
    grid-template-columns: 1fr;
  }
}
</style>
