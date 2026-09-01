<script setup lang="ts">
// 个股预览对话框：头部实时报价 + 加/移除自选 + 左侧五档盘口
// + 右侧 分时/日K tab（日K 支持技术指标切换）。
// 报价来自全局 SSE store；图表按需拉取，分时/日K 独立容错，
// 指数代码在个股 /bars 拿不到时自动回退 /bars/index。

import { computed, onMounted, ref, toRef, watch } from 'vue'
import { useRouter } from 'vue-router'

import {
  addWatchItem,
  fetchBars,
  fetchHistoryMinute,
  fetchIndexBars,
  fetchMinute,
  fetchWatchlist,
  formatError,
  removeWatchItem,
} from '../api'
import { dirClass, fmt2, fmtAmount, fmtPctSigned, fmtVol } from '../format'
import { useQuoteStore } from '../stores/quotes'
import type { Bar, MinutePoint } from '../types'
import IntradayChart from './IntradayChart.vue'
import StockKline, { type Overlay, type SubPane } from './StockKline.vue'

const props = defineProps<{
  market: string
  code: string
  name?: string
}>()

const emit = defineEmits<{ close: []; 'watchlist-changed': [] }>()

const quoteStore = useQuoteStore()
const quote = computed(() => quoteStore.getQuote(`${props.market}${props.code}`))

const changePct = computed(() => {
  const q = quote.value
  if (!q?.price || !q.pre_close) return null
  return (q.price / q.pre_close - 1) * 100
})

// ── tab / 指标 ──────────────────────────────────────────────────────────────

const tab = ref<'minute' | 'daily'>('minute')
const overlay = ref<Overlay>('ma')
const subPane = ref<SubPane>('macd')
const minuteDays = ref<1 | 3 | 5>(1)
const DAY_OPTIONS: Array<{ value: 1 | 3 | 5; label: string }> = [
  { value: 1, label: '1日' },
  { value: 3, label: '3日' },
  { value: 5, label: '5日' },
]

const overlayOptions: Array<{ value: Overlay; label: string }> = [
  { value: 'ma', label: 'MA' },
  { value: 'boll', label: 'BOLL' },
  { value: 'ema', label: 'EMA' },
  { value: 'none', label: '主图无' },
]
const subOptions: Array<{ value: SubPane; label: string }> = [
  { value: 'macd', label: 'MACD' },
  { value: 'kdj', label: 'KDJ' },
  { value: 'rsi', label: 'RSI' },
  { value: 'none', label: '副图无' },
]

// ── 图表数据（独立容错） ────────────────────────────────────────────────────

const minutePoints = ref<MinutePoint[]>([])
/** 多日分时的天分隔标记（每天起始索引 + 日期）。 */
const minuteDayMarks = ref<Array<{ start: number; date: string }>>([])
const dailyBars = ref<Bar[]>([])
const minuteError = ref('')
const dailyError = ref('')
const loading = ref(false)

async function loadMinute() {
  minuteError.value = ''
  try {
    // 交易日从日K尾部取（末日=今天），今天走 /minute，历史日走 /minute/history
    const dates = dailyBars.value.slice(-minuteDays.value).map((b) => b.datetime.slice(0, 10))
    const all: MinutePoint[] = []
    const marks: Array<{ start: number; date: string }> = []
    for (const d of dates) {
      const dateInt = Number(d.replaceAll('-', ''))
      const pts =
        d === new Date().toISOString().slice(0, 10)
          ? await fetchMinute(props.market, props.code)
          : await fetchHistoryMinute(props.market, props.code, dateInt)
      if (pts.length === 0) continue
      marks.push({ start: all.length, date: d })
      all.push(...pts)
    }
    minutePoints.value = all
    minuteDayMarks.value = marks
  } catch (e) {
    minutePoints.value = []
    minuteDayMarks.value = []
    minuteError.value = formatError(e)
  }
}

watch(minuteDays, loadMinute)

async function loadDaily() {
  dailyError.value = ''
  try {
    let bars = await fetchBars(props.market, props.code, 'DAY', undefined, undefined)
    // 指数（或 /bars 空数据的服务器）回退指数接口
    if (bars.length === 0) bars = await fetchIndexBars(props.market, props.code, 250)
    if (bars.length === 0) throw new Error('无日K数据（可能为新股或代码有误）')
    dailyBars.value = bars.slice(-250)
  } catch (e) {
    dailyBars.value = []
    dailyError.value = formatError(e)
  }
}

async function loadCharts() {
  loading.value = true
  // 先日K后分时：多日分时的交易日列表取自 dailyBars 尾部
  await loadDaily()
  await loadMinute()
  loading.value = false
}

onMounted(loadCharts)
watch([() => props.market, () => props.code], loadCharts)

// ── 自选状态 ────────────────────────────────────────────────────────────────

const inWatchlist = ref(false)
const watchBusy = ref(false)

async function refreshWatchState() {
  try {
    const resp = await fetchWatchlist()
    inWatchlist.value = resp.items.some((i) => i.symbol === `${props.market}${props.code}`)
  } catch {
    inWatchlist.value = false
  }
}
onMounted(refreshWatchState)
watch([() => props.market, () => props.code], refreshWatchState)

async function toggleWatch() {
  watchBusy.value = true
  try {
    if (inWatchlist.value) {
      await removeWatchItem(props.market, props.code)
      inWatchlist.value = false
    } else {
      await addWatchItem(props.market, props.code, props.name ?? '')
      inWatchlist.value = true
    }
    emit('watchlist-changed')
  } catch (e) {
    alert(formatError(e))
  } finally {
    watchBusy.value = false
  }
}

// ── 五档 ────────────────────────────────────────────────────────────────────

const bids = computed(() => {
  const q = quote.value
  if (!q) return []
  return [1, 2, 3, 4, 5].map((i) => ({
    level: i,
    price: (q as unknown as Record<string, number | null>)[`bid${i}`] ?? null,
    vol: (q as unknown as Record<string, number | null>)[`bid_vol${i}`] ?? null,
  }))
})
const asks = computed(() => {
  const q = quote.value
  if (!q) return []
  return [5, 4, 3, 2, 1].map((i) => ({
    level: i,
    price: (q as unknown as Record<string, number | null>)[`ask${i}`] ?? null,
    vol: (q as unknown as Record<string, number | null>)[`ask_vol${i}`] ?? null,
  }))
})

const maxDepthVol = computed(() => {
  let m = 1
  for (const lv of [...bids.value, ...asks.value]) m = Math.max(m, lv.vol ?? 0)
  return m
})

const preClose = toRef(() => quote.value?.pre_close ?? null)

// ── 一键寻优（跳 /optimize 并自动跑全策略预设网格） ─────────────────────────

const router = useRouter()

function gotoOptimize() {
  emit('close')
  router.push({ path: '/optimize', query: { code: props.code, autoAll: '1' } })
}
</script>

<template>
  <teleport to="body">
    <div class="dlg-mask" @click.self="emit('close')">
      <div class="dlg" :key="`${market}${code}`">
        <!-- 头部：名称 + 实时报价 + 自选开关 -->
        <div class="dlg-head">
          <div class="head-left">
            <span class="stock-name">{{ name || `${market}${code}` }}</span>
            <span class="stock-code mono">{{ market }}{{ code }}</span>
            <span v-if="quote?.server_time" class="srv-time mono">{{ quote.server_time.slice(0, 8) }}</span>
          </div>
          <div class="head-quote">
            <span class="price mono" :class="dirClass(changePct)">{{ fmt2(quote?.price) }}</span>
            <span v-if="changePct !== null" class="chg mono" :class="dirClass(changePct)">
              {{ fmt2((quote?.price ?? 0) - (quote?.pre_close ?? 0)) }}
              {{ fmtPctSigned(changePct) }}
            </span>
            <button
              class="watch-btn"
              :class="{ watched: inWatchlist }"
              :disabled="watchBusy"
              :title="inWatchlist ? '移除自选' : '加入自选'"
              @click="toggleWatch"
            >
              {{ inWatchlist ? '★ 移除自选' : '☆ 加入自选' }}
            </button>
            <button class="watch-btn" title="用全部策略的预设网格对该股一键寻优" @click="gotoOptimize">
              ⚙ 一键寻优
            </button>
            <button class="close-btn" @click="emit('close')">✕</button>
          </div>
        </div>

        <div class="dlg-body">
          <!-- 五档盘口 -->
          <div class="depth">
            <div class="depth-title">五档盘口</div>
            <table class="depth-table">
              <tbody>
                <tr v-for="lv in asks" :key="`a${lv.level}`">
                  <td class="lv">卖{{ lv.level }}</td>
                  <td class="mono" :class="lv.price && quote?.pre_close ? dirClass(lv.price - quote.pre_close) : 'flat'">
                    {{ fmt2(lv.price) }}
                  </td>
                  <td class="vol-cell">
                    <div class="vol-bar ask" :style="{ width: `${((lv.vol ?? 0) / maxDepthVol) * 100}%` }"></div>
                    <span class="mono">{{ lv.vol ? Math.round(lv.vol) : '-' }}</span>
                  </td>
                </tr>
                <tr class="sep-row">
                  <td colspan="3"><div class="sep"></div></td>
                </tr>
                <tr v-for="lv in bids" :key="`b${lv.level}`">
                  <td class="lv">买{{ lv.level }}</td>
                  <td class="mono" :class="lv.price && quote?.pre_close ? dirClass(lv.price - quote.pre_close) : 'flat'">
                    {{ fmt2(lv.price) }}
                  </td>
                  <td class="vol-cell">
                    <div class="vol-bar bid" :style="{ width: `${((lv.vol ?? 0) / maxDepthVol) * 100}%` }"></div>
                    <span class="mono">{{ lv.vol ? Math.round(lv.vol) : '-' }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="quote" class="depth-stats mono">
              <div><span class="dim2">量</span>{{ fmtVol(quote.vol) }}</div>
              <div><span class="dim2">额</span>{{ fmtAmount(quote.amount) }}</div>
              <div><span class="dim2">高</span>{{ fmt2(quote.high) }}</div>
              <div><span class="dim2">低</span>{{ fmt2(quote.low) }}</div>
              <div><span class="dim2">开</span>{{ fmt2(quote.open) }}</div>
              <div><span class="dim2">昨收</span>{{ fmt2(quote.pre_close) }}</div>
            </div>
          </div>

          <!-- 图表区 -->
          <div class="chart-area">
            <div class="tabs">
              <button :class="{ active: tab === 'minute' }" @click="tab = 'minute'">分时</button>
              <button :class="{ active: tab === 'daily' }" @click="tab = 'daily'">日K</button>
              <span v-if="tab === 'minute'" class="ind-group">
                <button
                  v-for="opt in DAY_OPTIONS"
                  :key="opt.value"
                  class="chip"
                  :class="{ on: minuteDays === opt.value }"
                  @click="minuteDays = opt.value"
                >
                  {{ opt.label }}
                </button>
              </span>
              <template v-if="tab === 'daily'">
                <span class="ind-group">
                  <button
                    v-for="opt in overlayOptions"
                    :key="opt.value"
                    class="chip"
                    :class="{ on: overlay === opt.value }"
                    @click="overlay = opt.value"
                  >
                    {{ opt.label }}
                  </button>
                </span>
                <span class="ind-group">
                  <button
                    v-for="opt in subOptions"
                    :key="opt.value"
                    class="chip"
                    :class="{ on: subPane === opt.value }"
                    @click="subPane = opt.value"
                  >
                    {{ opt.label }}
                  </button>
                </span>
              </template>
            </div>
            <div v-if="loading" class="chart-msg">加载中…</div>
            <template v-else>
              <template v-if="tab === 'minute'">
                <div v-if="minuteError" class="chart-msg error">分时：{{ minuteError }}</div>
                <IntradayChart
                  v-else
                  :points="minutePoints"
                  :pre-close="preClose"
                  :day-marks="minuteDayMarks"
                />
              </template>
              <template v-else>
                <div v-if="dailyError" class="chart-msg error">日K：{{ dailyError }}</div>
                <StockKline v-else :bars="dailyBars" :overlay="overlay" :sub-pane="subPane" />
              </template>
            </template>
          </div>
        </div>
      </div>
    </div>
  </teleport>
</template>

<style scoped>
.dlg-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.dlg {
  width: min(1280px, 96vw);
  max-height: 94vh;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.dlg-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.head-left {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.stock-name {
  font-size: 16px;
  font-weight: 700;
}
.stock-code {
  font-size: 12px;
  color: var(--text-dim);
}
.srv-time {
  font-size: 11px;
  color: var(--text-dim);
}
.head-quote {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.price {
  font-size: 22px;
  font-weight: 700;
}
.chg {
  font-size: 13px;
}
.watch-btn {
  font-size: 12px;
  padding: 4px 10px;
  margin-left: 10px;
  align-self: center;
}
.watch-btn.watched {
  border-color: var(--warn);
  color: var(--warn);
}
.close-btn {
  padding: 2px 8px;
  font-size: 12px;
  align-self: center;
}
.dlg-body {
  display: flex;
  gap: 0;
  overflow: auto;
}
.depth {
  width: 260px;
  flex-shrink: 0;
  padding: 10px 14px;
  border-right: 1px solid var(--border);
}
.depth-title {
  font-size: 12px;
  color: var(--text-dim);
  margin-bottom: 6px;
}
.depth-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.depth-table td {
  padding: 2.5px 4px;
  white-space: nowrap;
}
.lv {
  color: var(--text-dim);
  width: 34px;
}
.vol-cell {
  position: relative;
  width: 90px;
}
.vol-bar {
  position: absolute;
  right: 0;
  top: 2px;
  bottom: 2px;
  opacity: 0.18;
  border-radius: 2px;
}
.vol-bar.ask {
  background: var(--up);
}
.vol-bar.bid {
  background: var(--down);
}
.vol-cell span {
  position: relative;
}
.sep {
  border-top: 1px dashed var(--border);
  margin: 3px 0;
}
.depth-stats {
  margin-top: 10px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 3px 10px;
  font-size: 11.5px;
  color: var(--text-muted);
}
.depth-stats > div {
  display: flex;
  justify-content: space-between;
}
.dim2 {
  color: var(--text-dim);
}
.chart-area {
  flex: 1;
  min-width: 0;
  padding: 10px 12px;
}
.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.tabs button.active {
  border-color: var(--accent);
  color: var(--accent);
}
.ind-group {
  display: inline-flex;
  gap: 4px;
  margin-left: 12px;
}
.chip {
  padding: 2px 8px;
  font-size: 11px;
}
.chip.on {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(74, 158, 255, 0.12);
}
.chart-msg {
  padding: 40px 0;
  text-align: center;
  color: var(--text-dim);
}
.chart-msg.error {
  color: var(--up);
}
</style>
