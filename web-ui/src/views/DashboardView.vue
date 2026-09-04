<script setup lang="ts">
// 市场看板 v2：指数实时条（内嵌迷你分时）+ 涨跌统计 + 市场情绪 +
// 涨跌分布直方图 + 行业/概念热度榜 + 涨跌幅榜 + 异动雷达。
// 指数走全局 SSE；统计/情绪/分布/板块/异动定时轮询；全市场分布懒加载。

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  fetchBoards,
  fetchIndexBars,
  fetchMarketStat,
  fetchRankList,
  fetchMinute,
  formatError,
} from '../api'
import { dirClass, fmtAmount, fmtPctSigned } from '../format'
import { useQuoteStore } from '../stores/quotes'
import type { Bar, BoardRow, MarketStat, RankRow } from '../types'
import BoardDialog from '../components/BoardDialog.vue'
import MoodRadar from '../components/MoodRadar.vue'
import Sparkline from '../components/Sparkline.vue'
import StockDialog from '../components/StockDialog.vue'

const quoteStore = useQuoteStore()

// ── 指数条（SSE 实时 + 迷你分时） ────────────────────────────────────────────

const INDEXES = [
  { symbol: 'SH000001', name: '上证指数' },
  { symbol: 'SZ399001', name: '深证成指' },
  { symbol: 'SZ399006', name: '创业板指' },
  { symbol: 'SH000688', name: '科创50' },
  { symbol: 'SH000300', name: '沪深300' },
]

function idxQuote(symbol: string) {
  return quoteStore.getQuote(symbol)
}

function idxPct(symbol: string): number | null {
  const q = idxQuote(symbol)
  if (!q?.price || !q.pre_close) return null
  return (q.price / q.pre_close - 1) * 100
}

const idxSparks = ref(new Map<string, number[]>())
const idxSparkBase = ref(new Map<string, number>())

async function loadIdxSparks() {
  for (const idx of INDEXES) {
    try {
      const pts = await fetchMinute(idx.symbol.slice(0, 2), idx.symbol.slice(2))
      if (pts.length > 0) {
        const prices = pts.map((p) => p.price)
        idxSparks.value.set(idx.symbol, prices)
        const q = idxQuote(idx.symbol)
        idxSparkBase.value.set(idx.symbol, q?.pre_close ?? prices[0])
      }
    } catch {
      // 单指数失败跳过
    }
  }
}

// ── 市场统计（轮询 30s） ─────────────────────────────────────────────────────

const stat = ref<MarketStat | null>(null)
const statError = ref('')

async function loadStat() {
  try {
    stat.value = await fetchMarketStat()
    statError.value = ''
  } catch (e) {
    statError.value = formatError(e)
  }
}

const breadth = computed(() => {
  const s = stat.value
  if (!s || !s.total_count) return null
  const active = s.up_count + s.down_count + s.neutral_count || 1
  return {
    up: (s.up_count / active) * 100,
    flat: (s.neutral_count / active) * 100,
    down: (s.down_count / active) * 100,
  }
})

// ── 市场情绪（统计 + 分布 + 指数上下文合成四维雷达） ───────────────────────

/** 上证/深证指数近 60 日 K（量能与趋势维的数据源）。 */
const idxBars = ref<{ sh: Bar[]; sz: Bar[] }>({ sh: [], sz: [] })

async function loadIndexContext() {
  try {
    const [sh, sz] = await Promise.all([
      fetchIndexBars('SH', '000001', 60),
      fetchIndexBars('SZ', '399001', 60),
    ])
    idxBars.value = { sh, sz }
  } catch {
    // 指数 K 线失败静默，雷达相关维退化为中性 50
  }
}

/** 沪深两市今日/昨日成交额（两指数 amount 之和）。 */
const amountToday = computed(() => {
  const { sh, sz } = idxBars.value
  return (Number(sh.at(-1)?.amount ?? 0)) + (Number(sz.at(-1)?.amount ?? 0))
})
const amountYesterday = computed(() => {
  const { sh, sz } = idxBars.value
  return (Number(sh.at(-2)?.amount ?? 0)) + (Number(sz.at(-2)?.amount ?? 0))
})

const amountPct = computed(() => {
  if (amountToday.value <= 0 || amountYesterday.value <= 0) return null
  return (amountToday.value / amountYesterday.value - 1) * 100
})

/** 四维雷达分值（0~100，50 中性）。 */
const radarValues = computed(() => {
  const s = stat.value
  // 赚钱效应：涨跌比 tanh 压缩到 0~100（1:1 → 50，4:1 → 90，1:4 → 10）
  let profit = 50
  if (s && s.down_count + s.up_count > 0) {
    const ratio = s.up_count / Math.max(s.down_count, 1)
    profit = 50 + Math.tanh(Math.log(ratio)) * 50
  }
  // 量能：较昨日成交额 ±50% 打满
  const ap = amountPct.value
  const volume = ap === null ? 50 : Math.min(100, Math.max(0, 50 + ap))
  // 动量：上证 5 日涨幅 ±5% 打满
  const sh = idxBars.value.sh
  let momentum = 50
  if (sh.length >= 6) {
    const ret5 = (sh.at(-1)!.close / sh.at(-6)!.close - 1) * 100
    momentum = Math.min(100, Math.max(0, 50 + ret5 * 10))
  }
  // 趋势：上证收盘相对 MA20 偏离 ±5% 打满
  let trend = 50
  if (sh.length >= 20) {
    const ma20 = sh.slice(-20).reduce((a, b) => a + b.close, 0) / 20
    trend = Math.min(100, Math.max(0, 50 + (sh.at(-1)!.close / ma20 - 1) * 1000))
  }
  return { profit, volume, momentum, trend }
})

/** 综合分（四维均值，保留 1 位）。 */
const moodScore = computed(() => {
  const v = radarValues.value
  return Math.round(((v.profit + v.volume + v.momentum + v.trend) / 4) * 10) / 10
})

function moodLabel(score: number): string {
  if (score >= 70) return '亢奋'
  if (score >= 57) return '偏暖'
  if (score >= 43) return '均衡'
  if (score >= 30) return '偏冷'
  return '冰点'
}

// ── 涨跌分布直方图（全市场懒加载，120s） ────────────────────────────────────

const BUCKETS = [
  '≤-10',
  ...Array.from({ length: 20 }, (_, i) => {
    const v = -10 + i
    return v === 0 ? '0' : `${v > 0 ? '+' : ''}${v}`
  }),
  '≥10',
]

interface DistData {
  counts: number[]
  gt5: number // 涨超 5%（不含涨停也计入）
  lt5: number // 跌超 5%
  total: number
}

const dist = ref<DistData | null>(null)
const distLoading = ref(false)
const distError = ref('')
/** 今日涨幅 ≥9.8% 的名单（涨停/触板观察，含 20cm 品种）。 */
const limitRows = ref<RankRow[]>([])

async function loadDist() {
  distLoading.value = true
  distError.value = ''
  try {
    // 接口单向上限 5000：DESC+ASC 各拉 3000 覆盖两端（全 A 约 5400 只），
    // 按 code 去重合并，避免单向截断丢掉分布另一端的尾部
    const [top, bottom] = await Promise.all([fetchRankList('DESC', 3000), fetchRankList('ASC', 3000)])
    const seen = new Set<string>()
    const rows: RankRow[] = []
    for (const r of [...top, ...bottom]) {
      const key = String(r.code ?? '')
      if (!key || seen.has(key)) continue
      seen.add(key)
      rows.push(r)
    }
    const counts = new Array(BUCKETS.length).fill(0)
    let gt5 = 0
    let lt5 = 0
    for (const r of rows) {
      const pct = Number(r.change_pct ?? 0)
      if (!Number.isFinite(pct)) continue
      if (pct > 5) gt5++
      if (pct < -5) lt5++
      // 桶布局：[0]='≤-10'，[1..10]='-10'..'-1'，[11]='0'，[12..20]='+1'..'+9'，[21]='≥10'
      // 统一公式 idx = 11 + floor(pct)，两端 clamp
      let idx = 11 + Math.floor(pct)
      if (pct <= -10) idx = 0
      if (pct >= 10) idx = BUCKETS.length - 1
      counts[Math.max(0, Math.min(BUCKETS.length - 1, idx))]++
    }
    dist.value = { counts, gt5, lt5, total: rows.length }
    // 涨停雷达名单：涨幅 ≥9.8%（主板涨停 10%、创业/科创 20% 都会覆盖）
    limitRows.value = rows
      .filter((r) => Number(r.change_pct ?? 0) >= 9.8)
      .slice(0, 15)
  } catch (e) {
    distError.value = formatError(e)
  } finally {
    distLoading.value = false
  }
}

/** 涨跌分布 hover 浮窗：跟随鼠标，超界自动贴边。 */
const hoverBucket = ref(-1)
const popX = ref(0)
const popY = ref(0)
const distChartEl = ref<HTMLElement | null>(null)

function onDistMove(e: MouseEvent) {
  const host = distChartEl.value
  if (!host) return
  const rect = host.getBoundingClientRect()
  // 浮窗约 110px 宽 56px 高：先按鼠标右上角偏移，再 clamp 到容器内
  popX.value = Math.min(Math.max(e.clientX - rect.left + 14, 0), rect.width - 110)
  popY.value = Math.min(Math.max(e.clientY - rect.top - 64, 0), rect.height - 56)
}

/** 桶区间文案（如 "-5% ~ -4%"；两端为 ≤-10% / ≥+10%）。 */
function bucketRange(i: number): string {
  if (i === 0) return '≤ -10%'
  if (i === BUCKETS.length - 1) return '≥ +10%'
  const v = -10 + (i - 1) // '-10'..'+9' 桶对应 v..v+1
  if (v === 0) return '0 ~ +1%'
  const fmt = (x: number) => (x > 0 ? `+${x}%` : `${x}%`)
  return `${fmt(v)} ~ ${fmt(v + 1)}`
}

/** 桶内家数占比。 */
function bucketShare(count: number): string {
  const total = dist.value?.total ?? 0
  return total > 0 ? `${((count / total) * 100).toFixed(1)}%` : '-'
}

/** 分布柱高（相对最大桶）。 */
function distHeight(count: number): string {
  const max = Math.max(...(dist.value?.counts ?? [1]), 1)
  return `${Math.max(2, (count / max) * 100)}%`
}

function distColor(i: number): string {
  // 桶 1..20 对应 -10..+9：前 10 绿（跌），后 10 红（涨）；两端按方向
  if (i === 0) return 'var(--down)'
  if (i === BUCKETS.length - 1) return 'var(--up)'
  return i <= 10 ? 'var(--down)' : 'var(--up)'
}

// ── 板块热度 + 冰冷（一次拉 120 个，前端切热/冷两端） ───────────────────────

const industryBoards = ref<BoardRow[]>([])
const conceptBoards = ref<BoardRow[]>([])
const boardsError = ref('')

/** 热榜（涨幅前 8）。 */
function hotBoards(list: BoardRow[]): BoardRow[] {
  return list.slice(0, 8)
}

/** 冷榜（跌幅前 8，倒回正序显示）。 */
function coldBoards(list: BoardRow[]): BoardRow[] {
  return list.slice(-8).reverse()
}

async function loadBoards() {
  boardsError.value = ''
  try {
    // 概念板块约 270 个：必须拉全量才能覆盖跌幅区（曾拉 120 导致
    // 冷榜全是 +0.7% 附近的正值板块）；行业仅 86 个，120 已全量。
    const [hy, gn] = await Promise.all([fetchBoards('HY', 120), fetchBoards('GN', 500)])
    industryBoards.value = hy
    conceptBoards.value = gn
  } catch (e) {
    boardsError.value = formatError(e)
  }
}

function boardPct(b: BoardRow): number {
  return Number(b.change_pct ?? 0)
}

function barWidth(pct: number, list: BoardRow[]): string {
  const maxAbs = Math.max(...list.map(boardPct), 0.5)
  return `${Math.min(100, (Math.abs(pct) / maxAbs) * 100)}%`
}

// ── 排行榜（涨幅/跌幅/成交额/换手 四 tab，轮询 60s） ───────────────────────

const gainers = ref<RankRow[]>([])
const losers = ref<RankRow[]>([])
const hotAmount = ref<RankRow[]>([])
const hotTurnover = ref<RankRow[]>([])
const rankError = ref('')
const rankTab = ref<'gain' | 'loss' | 'amount' | 'turnover'>('gain')

const RANK_TABS: Array<{ value: 'gain' | 'loss' | 'amount' | 'turnover'; label: string }> = [
  { value: 'gain', label: '涨幅' },
  { value: 'loss', label: '跌幅' },
  { value: 'amount', label: '成交额' },
  { value: 'turnover', label: '换手' },
]

const activeRankRows = computed<RankRow[]>(() => {
  switch (rankTab.value) {
    case 'loss':
      return losers.value
    case 'amount':
      return hotAmount.value
    case 'turnover':
      return hotTurnover.value
    default:
      return gainers.value
  }
})

async function loadRanks() {
  rankError.value = ''
  try {
    const [top, bottom, byAmount, byTurnover] = await Promise.all([
      fetchRankList('DESC', 12),
      fetchRankList('ASC', 12),
      fetchRankList('DESC', 12, 'TOTAL_AMOUNT'),
      fetchRankList('DESC', 12, 'TURNOVER_RATE'),
    ])
    gainers.value = top
    losers.value = bottom
    hotAmount.value = byAmount
    hotTurnover.value = byTurnover
  } catch (e) {
    rankError.value = formatError(e)
  }
}

/** 排行榜第三列内容：涨幅榜显示成交额，其余显示涨跌幅。 */
function rankExtra(r: RankRow): { text: string; cls: string } {
  if (rankTab.value === 'gain' || rankTab.value === 'loss') {
    return {
      text: fmtAmount(Number(r.amount ?? 0)),
      cls: 'dim',
    }
  }
  const pct = Number(r.change_pct ?? 0)
  return { text: fmtPctSigned(pct), cls: dirClass(pct) }
}

// ── 轮询调度（交易时段感知：休市自动暂停，手动刷新不受限） ────────────────────

let statTimer = 0
let slowTimer = 0
let distTimer = 0
let sessionTimer = 0

/** 仅交易时段自动刷新（localStorage 持久化；勾掉 = 全天候模式）。 */
const sessionGated = ref(localStorage.getItem('dash.sessionGated') !== '0')

function onSessionToggle() {
  localStorage.setItem('dash.sessionGated', sessionGated.value ? '1' : '0')
}

/** 本地判断当前是否处于 A 股有效行情时段（09:15~11:30、13:00~15:05，周一至五）。 */
function isTradeSession(now = new Date()): boolean {
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const m = now.getHours() * 60 + now.getMinutes()
  return (m >= 555 && m <= 690) || (m >= 780 && m <= 905)
}

/** 会话状态（每分钟重估）：gated 开关 × 是否盘中。 */
const inSession = ref(isTradeSession())

/** 自动刷新是否暂停（全天候模式或盘中 = 不暂停）。 */
const autoPaused = computed(() => sessionGated.value && !inSession.value)

const sessionLabel = computed(() => {
  if (!sessionGated.value) return '全天候模式'
  return inSession.value ? '交易中' : '休市 · 自动刷新已暂停'
})

function refreshAll() {
  loadStat()
  loadBoards()
  loadRanks()
  loadIdxSparks()
  loadIndexContext()
  loadDist()
}

function tickIfActive() {
  // 门控放在 fetch 前：定时器照常触发，休市时只重估会话状态、不发请求
  inSession.value = isTradeSession()
  if (autoPaused.value) return
  loadStat()
}

function slowTickIfActive() {
  if (autoPaused.value) return
  loadRanks()
  loadBoards()
  loadIdxSparks()
  loadIndexContext()
}

function distTickIfActive() {
  if (autoPaused.value) return
  loadDist()
}

onMounted(() => {
  refreshAll()
  statTimer = window.setInterval(tickIfActive, 30_000)
  slowTimer = window.setInterval(slowTickIfActive, 60_000)
  distTimer = window.setInterval(distTickIfActive, 120_000)
  // 每分钟重估会话状态（跨过 11:30/15:05 边界后状态栏即时切换）
  sessionTimer = window.setInterval(() => {
    inSession.value = isTradeSession()
  }, 60_000)
})
onBeforeUnmount(() => {
  window.clearInterval(statTimer)
  window.clearInterval(slowTimer)
  window.clearInterval(distTimer)
  window.clearInterval(sessionTimer)
})

// ── 弹窗（个股 / 板块） ──────────────────────────────────────────────────────

const dialog = ref<{ market: string; code: string; name: string } | null>(null)
const boardDialog = ref<{ code: string; name: string } | null>(null)

function openDialog(code: string, name: string, marketHint?: string) {
  if (!code) return
  const mkt = marketHint ?? (/^(6|9|5)/.test(code) ? 'SH' : /^(4|8|92|43)/.test(code) ? 'BJ' : 'SZ')
  dialog.value = { market: mkt, code, name }
}

/** 板块行点击 → 板块详情弹窗。 */
function openBoard(code: string | undefined, name: string | undefined) {
  if (!code) return
  boardDialog.value = { code: String(code), name: String(name ?? code) }
}
</script>

<template>
  <div class="dash">
    <!-- 刷新状态条：会话状态 + 手动刷新 + 门控开关 -->
    <div class="session-bar">
      <span class="dot" :class="{ live: !autoPaused }"></span>
      <span class="session-label" :class="{ paused: autoPaused }">{{ sessionLabel }}</span>
      <span class="dim session-hint">（09:15~11:30, 13:00~15:05）</span>
      <label class="session-toggle">
        <input v-model="sessionGated" type="checkbox" @change="onSessionToggle" />
        仅交易时段自动刷新
      </label>
      <button class="manual-refresh" @click="refreshAll">↻ 手动刷新</button>
    </div>

    <!-- 指数条（内嵌迷你分时） -->
    <div class="idx-row">
      <div
        v-for="idx in INDEXES"
        :key="idx.symbol"
        class="idx-card"
        @click="openDialog(idx.symbol.slice(2), idx.name, idx.symbol.slice(0, 2))"
      >
        <div class="idx-top">
          <span class="idx-name">{{ idx.name }}</span>
          <span class="idx-chg mono" :class="dirClass(idxPct(idx.symbol))">
            {{ fmtPctSigned(idxPct(idx.symbol)) }}
          </span>
        </div>
        <div class="idx-mid">
          <span class="idx-price mono" :class="dirClass(idxPct(idx.symbol))">
            {{ idxQuote(idx.symbol)?.price?.toFixed(2) ?? '—' }}
          </span>
          <span class="idx-amt mono dim">
            {{ fmtAmount(idxQuote(idx.symbol)?.amount) }}
          </span>
        </div>
        <Sparkline
          :prices="idxSparks.get(idx.symbol) ?? []"
          :base="idxSparkBase.get(idx.symbol) ?? null"
          :width="150"
          :height="30"
        />
      </div>
    </div>

    <div class="grid">
      <!-- 市场统计 -->
      <div class="card">
        <h3>市场统计</h3>
        <div v-if="statError" class="err">{{ statError }}</div>
        <template v-else-if="stat && breadth">
          <div class="breadth-bar">
            <div class="seg up" :style="{ width: `${breadth.up}%` }"></div>
            <div class="seg flat" :style="{ width: `${breadth.flat}%` }"></div>
            <div class="seg down" :style="{ width: `${breadth.down}%` }"></div>
          </div>
          <div class="stat-nums">
            <span class="up">涨 {{ stat.up_count }}</span>
            <span class="flat">平 {{ stat.neutral_count }}</span>
            <span class="down">跌 {{ stat.down_count }}</span>
            <span class="dim">停 {{ stat.suspended_count }}</span>
          </div>
          <div class="stat-rows mono">
            <div><span class="dim">涨停</span><span class="up">{{ stat.limit_up_count }}</span></div>
            <div><span class="dim">跌停</span><span class="down">{{ stat.limit_down_count }}</span></div>
            <div><span class="dim">总成交</span><span>{{ fmtAmount(stat.total_amount) }}</span></div>
            <div><span class="dim">总市值</span><span>{{ fmtAmount(stat.total_market_cap) }}</span></div>
          </div>
        </template>
        <div v-else class="loading">加载中…</div>
      </div>

      <!-- 市场情绪雷达 -->
      <div class="card">
        <h3>市场情绪 <span class="mood-score mono">{{ moodScore }}</span></h3>
        <MoodRadar :values="radarValues" />
        <div class="mood-foot">
          <span class="mood-word">{{ moodLabel(moodScore) }}</span>
          <span class="dim mono">量能 {{ fmtPctSigned(amountPct) }}</span>
        </div>
      </div>

      <!-- 涨跌分布直方图 -->
      <div class="card dist-card">
        <h3>涨跌分布 <span class="dim title-sub">（全市场 {{ dist?.total ?? '…' }} 只）</span></h3>
        <div v-if="distError" class="err">{{ distError }}</div>
        <div v-else-if="dist" ref="distChartEl" class="dist-chart" @mousemove="onDistMove" @mouseleave="hoverBucket = -1">
          <div
            v-for="(count, i) in dist.counts"
            :key="i"
            class="dist-col"
            :class="{ zero: BUCKETS[i] === '0', hovered: hoverBucket === i }"
            @mouseenter="hoverBucket = i"
          >
            <div class="dist-bar" :style="{ height: distHeight(count), background: distColor(i) }"></div>
            <div class="dist-label">{{ BUCKETS[i] }}</div>
          </div>
          <div v-if="hoverBucket >= 0 && dist" class="dist-pop" :style="{ left: `${popX}px`, top: `${popY}px` }">
            <div class="pop-range">{{ bucketRange(hoverBucket) }}</div>
            <div class="pop-count mono">{{ dist.counts[hoverBucket] }} 只</div>
            <div class="pop-share mono">占 {{ bucketShare(dist.counts[hoverBucket]) }}</div>
          </div>
        </div>
        <div v-else class="loading">{{ distLoading ? '全市场分布计算中…（约 5s）' : '加载中…' }}</div>
      </div>

      <!-- 行业板块（热 + 冷） -->
      <div class="card board-card">
        <h3>行业板块 <span class="dim title-sub">热</span></h3>
        <div v-if="boardsError" class="err">{{ boardsError }}</div>
        <div v-else class="board-list">
          <div
            v-for="b in hotBoards(industryBoards)"
            :key="b.code"
            class="board-row clickable"
            @click="openBoard(b.code, b.name)"
          >
            <span class="b-name">{{ b.name }}</span>
            <div class="b-bar-wrap">
              <div class="b-bar" :class="dirClass(boardPct(b))" :style="{ width: barWidth(boardPct(b), industryBoards) }"></div>
            </div>
            <span class="b-pct mono" :class="dirClass(boardPct(b))">{{ fmtPctSigned(boardPct(b)) }}</span>
          </div>
        </div>
        <h3 class="cold-title">冷</h3>
        <div v-if="!boardsError" class="board-list">
          <div
            v-for="b in coldBoards(industryBoards)"
            :key="`c${b.code}`"
            class="board-row clickable"
            @click="openBoard(b.code, b.name)"
          >
            <span class="b-name">{{ b.name }}</span>
            <div class="b-bar-wrap">
              <div class="b-bar" :class="dirClass(boardPct(b))" :style="{ width: barWidth(boardPct(b), industryBoards) }"></div>
            </div>
            <span class="b-pct mono" :class="dirClass(boardPct(b))">{{ fmtPctSigned(boardPct(b)) }}</span>
          </div>
        </div>
      </div>

      <!-- 概念板块（热 + 冷） -->
      <div class="card board-card">
        <h3>概念板块 <span class="dim title-sub">热</span></h3>
        <div v-if="boardsError" class="err">{{ boardsError }}</div>
        <div v-else class="board-list">
          <div
            v-for="b in hotBoards(conceptBoards)"
            :key="b.code"
            class="board-row clickable"
            @click="openBoard(b.code, b.name)"
          >
            <span class="b-name">{{ b.name }}</span>
            <div class="b-bar-wrap">
              <div class="b-bar" :class="dirClass(boardPct(b))" :style="{ width: barWidth(boardPct(b), conceptBoards) }"></div>
            </div>
            <span class="b-pct mono" :class="dirClass(boardPct(b))">{{ fmtPctSigned(boardPct(b)) }}</span>
          </div>
        </div>
        <h3 class="cold-title">冷</h3>
        <div v-if="!boardsError" class="board-list">
          <div
            v-for="b in coldBoards(conceptBoards)"
            :key="`c${b.code}`"
            class="board-row clickable"
            @click="openBoard(b.code, b.name)"
          >
            <span class="b-name">{{ b.name }}</span>
            <div class="b-bar-wrap">
              <div class="b-bar" :class="dirClass(boardPct(b))" :style="{ width: barWidth(boardPct(b), conceptBoards) }"></div>
            </div>
            <span class="b-pct mono" :class="dirClass(boardPct(b))">{{ fmtPctSigned(boardPct(b)) }}</span>
          </div>
        </div>
      </div>

      <!-- 排行榜（四 tab） -->
      <div class="card">
        <h3>
          排行榜
          <span class="rank-tabs">
            <button
              v-for="t in RANK_TABS"
              :key="t.value"
              class="rank-tab"
              :class="{ on: rankTab === t.value }"
              @click="rankTab = t.value"
            >
              {{ t.label }}
            </button>
          </span>
        </h3>
        <div v-if="rankError" class="err">{{ rankError }}</div>
        <table v-else class="qtable">
          <tbody>
            <tr v-for="(r, i) in activeRankRows" :key="`${rankTab}${i}`" @click="openDialog(String(r.code ?? ''), String(r.name ?? ''), r.market ? String(r.market) : undefined)">
              <td>{{ i + 1 }}. {{ r.name }}</td>
              <td class="mono dim">{{ fmtAmount(Number(r.amount ?? 0)) }}</td>
              <td class="mono" :class="rankExtra(r).cls">{{ rankExtra(r).text }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 涨停雷达 -->
      <div class="card limit-card">
        <h3>
          涨停雷达
          <span class="limit-n mono">{{ limitRows.length }}+</span>
          <span class="dim title-sub">（≥9.8%）</span>
        </h3>
        <div v-if="distError" class="err">{{ distError }}</div>
        <table v-else class="qtable">
          <tbody>
            <tr v-for="(r, i) in limitRows" :key="`lu${i}`" @click="openDialog(String(r.code ?? ''), String(r.name ?? ''), r.market ? String(r.market) : undefined)">
              <td>{{ i + 1 }}. {{ r.name }}</td>
              <td class="mono dim">{{ fmtAmount(Number(r.amount ?? 0)) }}</td>
              <td class="mono up">{{ fmtPctSigned(r.change_pct) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!distError && limitRows.length === 0" class="loading">
          {{ distLoading ? '全市场扫描中…' : '今日暂无 ≥9.8% 个股' }}
        </div>
      </div>

    </div>

    <StockDialog
      v-if="dialog"
      :market="dialog.market"
      :code="dialog.code"
      :name="dialog.name"
      @close="dialog = null"
    />
    <BoardDialog
      v-if="boardDialog"
      :code="boardDialog.code"
      :name="boardDialog.name"
      @close="boardDialog = null"
    />
  </div>
</template>

<style scoped>
.dash {
  height: 100%;
  overflow: auto;
  padding: 14px 16px;
}
.session-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 12px;
}
.session-bar .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-dim);
}
.session-bar .dot.live {
  background: var(--up);
  box-shadow: 0 0 4px var(--up);
}
.session-label {
  font-weight: 600;
}
.session-label.paused {
  color: var(--text-dim);
}
.session-hint {
  font-size: 11px;
}
.session-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 12px;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
}
.manual-refresh {
  margin-left: auto;
  padding: 3px 12px;
  font-size: 12px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  cursor: pointer;
}
.manual-refresh:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.idx-row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}
.idx-card {
  flex: 1;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 12px 6px;
  cursor: pointer;
}
.idx-card:hover {
  border-color: var(--accent);
}
.idx-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.idx-name {
  font-size: 12px;
  color: var(--text-muted);
}
.idx-chg {
  font-size: 12px;
}
.idx-mid {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 2px;
}
.idx-price {
  font-size: 19px;
  font-weight: 700;
}
.idx-amt {
  font-size: 11px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.dist-card {
  min-height: 220px;
}

/* 市场统计 */
.breadth-bar {
  display: flex;
  height: 10px;
  border-radius: 3px;
  overflow: hidden;
  margin: 8px 0 6px;
}
.seg.up {
  background: var(--up);
}
.seg.flat {
  background: var(--text-dim);
}
.seg.down {
  background: var(--down);
}
.stat-nums {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  margin-bottom: 10px;
}
.stat-rows {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 12px;
  font-size: 12px;
}
.stat-rows > div {
  display: flex;
  justify-content: space-between;
}

/* 市场情绪雷达 */
.mood-score {
  float: right;
  font-size: 15px;
  font-weight: 700;
  color: var(--accent);
}
.mood-foot {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-top: 4px;
}
.mood-word {
  font-size: 15px;
  font-weight: 700;
}

/* 排行榜 tab */
.rank-tabs {
  display: inline-flex;
  gap: 3px;
  margin-left: 10px;
}
.rank-tab {
  padding: 1px 8px;
  font-size: 11px;
}
.rank-tab.on {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(74, 158, 255, 0.12);
}

/* 涨停雷达 */
.limit-n {
  float: right;
  font-size: 15px;
  font-weight: 700;
  color: var(--up);
}
.limit-card {
  min-height: 200px;
}

/* 涨跌分布 */
.title-sub {
  font-weight: 400;
  font-size: 11px;
}
.dist-chart {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 120px;
  margin-top: 10px;
  position: relative;
}
.dist-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100%;
  justify-content: flex-end;
  position: relative;
}
.dist-col:hover,
.dist-col.hovered {
  z-index: 10;
}
.dist-pop {
  position: absolute;
  background: rgba(26, 29, 38, 0.97);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 6px 10px;
  font-size: 11px;
  white-space: nowrap;
  pointer-events: none;
  text-align: center;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.45);
  z-index: 20;
}
.pop-range {
  color: var(--text-muted);
  margin-bottom: 3px;
}
.pop-count {
  font-size: 13px;
  font-weight: 700;
}
.pop-share {
  color: var(--text-dim);
  font-size: 10.5px;
}
.dist-bar {
  width: 100%;
  border-radius: 1px;
  min-height: 1px;
}
.dist-col.zero {
  outline: 1px dashed var(--text-dim);
  outline-offset: 1px;
}
.dist-label {
  font-size: 8.5px;
  color: var(--text-dim);
  margin-top: 3px;
  transform: rotate(-60deg);
  transform-origin: top center;
  white-space: nowrap;
}

/* 板块热度 */
.board-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.board-row {
  display: grid;
  grid-template-columns: 84px 1fr 64px;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.b-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.board-row.clickable {
  cursor: pointer;
}
.board-row.clickable:hover .b-name {
  color: var(--accent);
}
.cold-title {
  margin-top: 10px;
}
.b-bar-wrap {
  height: 8px;
  background: var(--bg);
  border-radius: 2px;
  overflow: hidden;
}
.b-bar {
  height: 100%;
  border-radius: 2px;
  margin-left: auto;
}
.b-bar.up {
  background: var(--up);
}
.b-bar.down {
  background: var(--down);
}
.b-pct {
  text-align: right;
}

/* 涨跌幅榜 */

/* 异动 */
.tag {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 11px;
  color: var(--warn);
}

.err {
  color: var(--up);
  font-size: 12px;
  padding: 12px 0;
}
.loading {
  color: var(--text-dim);
  padding: 12px 0;
  font-size: 12px;
}
.dim {
  color: var(--text-dim);
}
</style>
