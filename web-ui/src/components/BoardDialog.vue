<script setup lang="ts">
// 板块详情弹窗（行业/概念板块指数）：左 分时/日K（含技术指标），
// 右 成分股涨跌榜（点击行打开个股弹窗，快速定位人气股）。
// 板块代码 881xxx/885xxx（沪市板块指数），分时与日K走与个股相同的
// /minute、/bars 接口（协议天然支持板块）。

import { computed, onMounted, ref, watch } from 'vue'

import {
  addWatchItem,
  fetchBars,
  fetchBoardMembers,
  fetchMinute,
  fetchWatchlist,
  formatError,
  removeWatchItem,
} from '../api'
import { dirClass, fmt2, fmtPctSigned } from '../format'
import { useQuoteStore } from '../stores/quotes'
import type { Bar, MinutePoint, RankRow } from '../types'
import IntradayChart from './IntradayChart.vue'
import StockKline, { type Overlay, type SubPane } from './StockKline.vue'
import StockDialog from './StockDialog.vue'

const props = defineProps<{
  code: string // 881106 / 885418 ...
  name: string
}>()

const emit = defineEmits<{ close: []; 'watchlist-changed': [] }>()

const quoteStore = useQuoteStore()
const quote = computed(() => quoteStore.getQuote(`SH${props.code}`))

const changePct = computed(() => {
  const q = quote.value
  if (!q?.price || !q.pre_close) return null
  return (q.price / q.pre_close - 1) * 100
})

const tab = ref<'minute' | 'daily'>('minute')
const overlay = ref<Overlay>('ma')
const subPane = ref<SubPane>('macd')

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

const minutePoints = ref<MinutePoint[]>([])
const dailyBars = ref<Bar[]>([])
const minuteError = ref('')
const dailyError = ref('')
const loading = ref(false)

async function loadMinute() {
  minuteError.value = ''
  try {
    minutePoints.value = await fetchMinute('SH', props.code)
  } catch (e) {
    minutePoints.value = []
    minuteError.value = formatError(e)
  }
}

async function loadDaily() {
  dailyError.value = ''
  try {
    const bars = await fetchBars('SH', props.code, 'DAY', undefined, undefined)
    if (bars.length === 0) throw new Error('该板块无日K数据')
    dailyBars.value = bars.slice(-250)
  } catch (e) {
    dailyBars.value = []
    dailyError.value = formatError(e)
  }
}

async function loadCharts() {
  loading.value = true
  await Promise.all([loadMinute(), loadDaily()])
  loading.value = false
}

onMounted(loadCharts)
watch(() => props.code, loadCharts)

// ── 自选 ────────────────────────────────────────────────────────────────────

const inWatchlist = ref(false)
const watchBusy = ref(false)

async function refreshWatchState() {
  try {
    const resp = await fetchWatchlist()
    inWatchlist.value = resp.items.some((i) => i.symbol === `SH${props.code}`)
  } catch {
    inWatchlist.value = false
  }
}
onMounted(refreshWatchState)
watch(() => props.code, refreshWatchState)

async function toggleWatch() {
  watchBusy.value = true
  try {
    if (inWatchlist.value) {
      await removeWatchItem('SH', props.code)
      inWatchlist.value = false
    } else {
      await addWatchItem('SH', props.code, props.name)
      inWatchlist.value = true
    }
    emit('watchlist-changed')
  } catch (e) {
    alert(formatError(e))
  } finally {
    watchBusy.value = false
  }
}

const preClose = computed(() => quote.value?.pre_close ?? null)

// ── 成分股涨跌榜 ────────────────────────────────────────────────────────────

const members = ref<RankRow[]>([])
const memberOrder = ref<'DESC' | 'ASC'>('DESC')
const membersError = ref('')
const membersLoading = ref(false)

// 全量拉取成分股（此前写死 120，大板块如 CPO 205 只/半导体 185 只被截断）。
// 后端单页 80 自动翻页，1000 覆盖最大概念板块，拉满后按成员清单自然终止。
const MEMBER_FETCH_COUNT = 1000

async function loadMembers() {
  membersLoading.value = true
  membersError.value = ''
  try {
    members.value = await fetchBoardMembers(props.code, MEMBER_FETCH_COUNT, memberOrder.value)
  } catch (e) {
    members.value = []
    membersError.value = formatError(e)
  } finally {
    membersLoading.value = false
  }
}

function toggleMemberOrder() {
  memberOrder.value = memberOrder.value === 'DESC' ? 'ASC' : 'DESC'
  loadMembers()
}

onMounted(loadMembers)
watch(() => props.code, loadMembers)

/** 成分股行点击 → 叠开个股弹窗。 */
const stockDlg = ref<{ market: string; code: string; name: string } | null>(null)

function openMember(r: RankRow) {
  stockDlg.value = {
    market: String(r.market ?? ''),
    code: String(r.code ?? ''),
    name: String(r.name ?? ''),
  }
}
</script>

<template>
  <teleport to="body">
    <div class="dlg-mask" @click.self="emit('close')">
      <div class="dlg" :key="code">
        <div class="dlg-head">
          <div class="head-left">
            <span class="board-name">{{ name }}</span>
            <span class="board-code mono">SH{{ code }} · 板块指数</span>
          </div>
          <div class="head-quote">
            <span v-if="quote" class="price mono" :class="dirClass(changePct)">{{ fmt2(quote.price) }}</span>
            <span v-if="changePct !== null" class="chg mono" :class="dirClass(changePct)">
              {{ fmtPctSigned(changePct) }}
            </span>
            <button
              class="watch-btn"
              :class="{ watched: inWatchlist }"
              :disabled="watchBusy"
              @click="toggleWatch"
            >
              {{ inWatchlist ? '★ 移除自选' : '☆ 加入自选' }}
            </button>
            <button class="close-btn" @click="emit('close')">✕</button>
          </div>
        </div>

        <div class="dlg-body">
          <!-- 左：分时 / 日K -->
          <div class="chart-area">
            <div class="tabs">
              <button :class="{ active: tab === 'minute' }" @click="tab = 'minute'">分时</button>
              <button :class="{ active: tab === 'daily' }" @click="tab = 'daily'">日K</button>
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
                <IntradayChart v-else :points="minutePoints" :pre-close="preClose" />
              </template>
              <template v-else>
                <div v-if="dailyError" class="chart-msg error">日K：{{ dailyError }}</div>
                <StockKline v-else :bars="dailyBars" :overlay="overlay" :sub-pane="subPane" />
              </template>
            </template>
          </div>

          <!-- 右：成分股涨跌榜 -->
          <div class="members-panel">
            <div class="members-head">
              <h3>成分股 <span class="dim members-count">（{{ members.length }}）</span></h3>
              <button class="order-btn" @click="toggleMemberOrder">
                {{ memberOrder === 'DESC' ? '↓ 涨幅降序' : '↑ 涨幅升序' }}
              </button>
            </div>
            <div v-if="membersError" class="chart-msg error">{{ membersError }}</div>
            <div v-else-if="membersLoading" class="chart-msg">成分股加载中…</div>
            <div v-else class="members-list">
              <div
                v-for="(r, i) in members"
                :key="i"
                class="member-row"
                @click="openMember(r)"
              >
                <span class="m-idx">{{ i + 1 }}</span>
                <span class="m-name">{{ r.name }}</span>
                <span class="m-code mono dim">{{ r.code }}</span>
                <span class="m-price mono">{{ fmt2(r.price) }}</span>
                <span class="m-pct mono" :class="dirClass(r.change_pct)">
                  {{ fmtPctSigned(r.change_pct) }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <StockDialog
      v-if="stockDlg"
      :market="stockDlg.market"
      :code="stockDlg.code"
      :name="stockDlg.name"
      @close="stockDlg = null"
      @watchlist-changed="emit('watchlist-changed')"
    />
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
.board-name {
  font-size: 16px;
  font-weight: 700;
}
.board-code {
  font-size: 12px;
  color: var(--text-dim);
}
.head-quote {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.price {
  font-size: 20px;
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
  overflow: hidden;
}
.chart-area {
  flex: 1;
  min-width: 0;
  padding: 10px 12px;
  overflow: auto;
}
.members-panel {
  width: 330px;
  flex-shrink: 0;
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.members-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px 6px;
}
.members-head h3 {
  font-size: 13px;
  font-weight: 600;
}
.members-count {
  font-weight: 400;
  font-size: 11px;
}
.order-btn {
  font-size: 11px;
  padding: 2px 8px;
}
.members-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px 10px;
}
.member-row {
  display: grid;
  grid-template-columns: 20px 1fr 66px 58px 62px;
  align-items: center;
  gap: 6px;
  padding: 4px 6px;
  font-size: 12px;
  border-radius: 4px;
  cursor: pointer;
}
.member-row:hover {
  background: var(--bg-elevated);
}
.m-idx {
  color: var(--text-dim);
  font-size: 10.5px;
}
.m-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.m-code {
  font-size: 10.5px;
}
.m-price {
  text-align: right;
}
.m-pct {
  text-align: right;
  font-weight: 600;
}
.dim {
  color: var(--text-dim);
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
