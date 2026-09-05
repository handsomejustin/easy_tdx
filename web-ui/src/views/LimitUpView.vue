<script setup lang="ts">
// 涨停生态（/limitup）：连板天梯 / 首板 / 炸板 / 跌停，本地 vipdoc 日线离线回算。
// 数据日期取决于本机通达信客户端（页头明示）；股票名称经 fetchSymbolName 懒加载补齐；
// 单击任意股票打开 StockDialog。120s 轮询 + 手动刷新。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { fetchLimitUpEcology, fetchSymbolName, fetchVipdocSetting, formatError, saveVipdocSetting } from '../api'
import StockDialog from '../components/StockDialog.vue'
import type { LimitUpEntry } from '../types'

const resp = ref<Awaited<ReturnType<typeof fetchLimitUpEcology>> | null>(null)
const loading = ref(false)
const error = ref('')
const lastRefresh = ref('')

const vipdocStored = ref<string | null>(null)
const vipdocResolved = ref<string | null>(null)
const vipdocInput = ref('')
const vipdocBusy = ref(false)
const vipdocMsg = ref('')

async function loadVipdocSetting() {
  try {
    const r = await fetchVipdocSetting()
    vipdocStored.value = r.stored
    vipdocResolved.value = r.resolved
    vipdocInput.value = r.stored ?? ''
  } catch {
    // 设置读取失败不打扰主流程
  }
}

async function saveVipdoc() {
  vipdocBusy.value = true
  vipdocMsg.value = ''
  try {
    const r = await saveVipdocSetting(vipdocInput.value.trim())
    vipdocStored.value = r.stored || null
    vipdocResolved.value = r.resolved
    vipdocMsg.value = '已保存，正在按新路径重新扫描…'
    await load()
    vipdocMsg.value = '已保存'
  } catch (e) {
    vipdocMsg.value = formatError(e)
  } finally {
    vipdocBusy.value = false
  }
}

async function load() {
  loading.value = resp.value === null
  error.value = ''
  try {
    resp.value = await fetchLimitUpEcology()
    vipdocResolved.value = resp.value.vipdoc_path ?? vipdocResolved.value
    lastRefresh.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    fillNames(allEntries.value)
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

// ── 名称懒加载（vipdoc 无名称，逐只经 MAC symbol-info 补齐，并发 8） ──────────

const names = ref<Record<string, string>>({})

function nameKey(e: LimitUpEntry): string {
  return `${e.market}${e.code}`
}

function nameOf(e: LimitUpEntry): string {
  return names.value[nameKey(e)] || e.code
}

async function fillNames(list: LimitUpEntry[]) {
  const todo = list.filter((e) => names.value[nameKey(e)] === undefined)
  let i = 0
  const workers = Array.from({ length: 8 }, async () => {
    while (i < todo.length) {
      const e = todo[i++]
      try {
        names.value[nameKey(e)] = await fetchSymbolName(e.market, e.code)
      } catch {
        names.value[nameKey(e)] = ''
      }
    }
  })
  await Promise.all(workers)
}

// ── 派生视图模型 ──────────────────────────────────────────────────────────────

const allEntries = computed<LimitUpEntry[]>(() =>
  resp.value ? [...resp.value.limit_up, ...resp.value.blown, ...resp.value.limit_down] : [],
)

const summary = computed(() => resp.value?.summary ?? null)

const dataDate = computed(() => {
  const d = resp.value?.data_date ?? 0
  if (!d) return ''
  return `${String(d).slice(0, 4)}-${String(d).slice(4, 6)}-${String(d).slice(6, 8)}`
})

/** 连板天梯：streak ≥ 2 的分组（高度降序） */
const ladder = computed(() => {
  const groups = new Map<number, LimitUpEntry[]>()
  for (const e of resp.value?.limit_up ?? []) {
    if (e.streak < 2) continue
    const arr = groups.get(e.streak) ?? []
    arr.push(e)
    groups.set(e.streak, arr)
  }
  return [...groups.entries()].sort((a, b) => b[0] - a[0])
})

const firstBoard = computed<LimitUpEntry[]>(() =>
  (resp.value?.limit_up ?? []).filter((e) => e.streak === 1),
)

const dataStale = computed(() => {
  if (!resp.value?.data_date) return false
  const d = resp.value.data_date
  const today = new Date()
  const todayInt = today.getFullYear() * 10000 + (today.getMonth() + 1) * 100 + today.getDate()
  return d < todayInt
})

// ── 轮询与弹窗 ────────────────────────────────────────────────────────────────

let timer = 0

function isTradeSession(now = new Date()): boolean {
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const m = now.getHours() * 60 + now.getMinutes()
  return (m >= 555 && m <= 690) || (m >= 780 && m <= 905)
}

function tick() {
  if (document.hidden || !isTradeSession()) return
  load()
}

onMounted(() => {
  loadVipdocSetting()
  load()
  timer = window.setInterval(tick, 120_000)
})
onBeforeUnmount(() => window.clearInterval(timer))

const stockDialog = ref<{ market: string; code: string; name?: string } | null>(null)

function openStock(e: LimitUpEntry) {
  stockDialog.value = { market: e.market, code: e.code, name: nameOf(e) }
}

function pctClass(pct: number): string {
  return pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat'
}
</script>

<template>
  <div class="limitup-view">
    <div class="view-head">
      <h2>涨停生态</h2>
      <span v-if="dataDate" class="dim head-sub">数据日期 {{ dataDate }}</span>
      <span v-if="dataStale" class="stale-badge">数据非今日 · 通达信客户端下载数据后更新</span>
      <span class="tb-spacer"></span>
      <span v-if="lastRefresh" class="dim refresh-ts">{{ lastRefresh }}</span>
      <button class="manual-refresh" @click="load">↻ 刷新</button>
    </div>

    <div class="vipdoc-bar card">
      <span class="dim">vipdoc 数据目录</span>
      <input
        v-model="vipdocInput"
        class="vipdoc-input mono"
        type="text"
        :placeholder="vipdocResolved || '自动检测（TDX_HOME 或常见安装路径）'"
        spellcheck="false"
      />
      <button :disabled="vipdocBusy" @click="saveVipdoc">{{ vipdocBusy ? '保存中…' : '保存' }}</button>
      <button :disabled="vipdocBusy || !vipdocStored" title="清除已存路径，恢复自动检测" @click="vipdocInput = ''; saveVipdoc()">自动检测</button>
      <span v-if="vipdocMsg" class="dim">{{ vipdocMsg }}</span>
      <span v-else-if="vipdocResolved && !vipdocStored" class="dim">当前自动检测：{{ vipdocResolved }}</span>
    </div>

    <div v-if="error" class="err card">
      加载失败：{{ error }}
      <button @click="load">重试</button>
    </div>
    <div v-else-if="loading" class="loading">扫描本地 vipdoc 日线（全市场，约需数秒）…</div>

    <template v-else-if="resp">
      <div v-if="resp.total === 0" class="err card">
        未检测到本地通达信 vipdoc 日线数据。可在上方填写安装目录（如 D:\new_tdx\vipdoc）后保存；或确认通达信已安装且
        <code> vipdoc/{sh,sz}/lday/*.day </code> 存在（自动检测失败时可在 CLI 侧指定路径）。
      </div>

      <template v-else>
        <!-- 统计卡条 -->
        <div class="stat-strip">
          <div class="stat-card card">
            <div class="stat-title">涨停</div>
            <div class="stat-main up">{{ summary?.limit_up_count ?? '-' }}</div>
          </div>
          <div class="stat-card card">
            <div class="stat-title">跌停</div>
            <div class="stat-main down">{{ summary?.limit_down_count ?? '-' }}</div>
          </div>
          <div class="stat-card card">
            <div class="stat-title">炸板</div>
            <div class="stat-main">{{ summary?.blown_count ?? '-' }}</div>
            <div class="stat-sub dim">
              炸板率 {{ summary?.blown_rate === null || summary?.blown_rate === undefined ? '-' : summary.blown_rate + '%' }}
            </div>
          </div>
          <div class="stat-card card">
            <div class="stat-title">最高连板</div>
            <div class="stat-main up">{{ summary?.max_streak ?? '-' }} <span class="unit">板</span></div>
            <div class="stat-sub dim">
              首板 {{ summary?.first_board ?? '-' }} · 二板 {{ summary?.second_board ?? '-' }} · 3板以上 {{ summary?.plus3 ?? '-' }}
            </div>
          </div>
        </div>

        <!-- 连板天梯 -->
        <div v-if="ladder.length > 0" class="section">
          <div class="sec-title">连板天梯</div>
          <div v-for="[height, entries] in ladder" :key="height" class="ladder-row card">
            <div class="l-height" :class="{ high: height >= 5 }">{{ height }}板</div>
            <div class="l-chips">
              <button v-for="e in entries" :key="e.code" class="chip-s" @click="openStock(e)">
                <span class="c-name">{{ nameOf(e) }}<span v-if="e.st" class="st-mark">ST?</span></span>
                <span class="mono c-pct" :class="pctClass(e.pct)">{{ e.pct.toFixed(1) }}%</span>
              </button>
            </div>
          </div>
        </div>

        <!-- 首板 -->
        <div class="section">
          <div class="sec-title">首板（{{ firstBoard.length }}）</div>
          <div class="card flat-card">
            <div class="l-chips">
              <button v-for="e in firstBoard" :key="e.code" class="chip-s" @click="openStock(e)">
                <span class="c-name">{{ nameOf(e) }}<span v-if="e.st" class="st-mark">ST?</span></span>
                <span class="mono c-pct" :class="pctClass(e.pct)">{{ e.pct.toFixed(1) }}%</span>
              </button>
              <span v-if="firstBoard.length === 0" class="dim">今日无首板</span>
            </div>
          </div>
        </div>

        <!-- 炸板 / 跌停 -->
        <div class="two-col">
          <div class="section">
            <div class="sec-title">炸板（{{ resp.blown.length }}）· 曾触涨停未封住</div>
            <div class="card flat-card">
              <div class="l-chips">
                <button v-for="e in resp.blown" :key="e.code" class="chip-s blown" @click="openStock(e)">
                  <span class="c-name">{{ nameOf(e) }}</span>
                  <span class="mono c-pct" :class="pctClass(e.pct)">{{ e.pct.toFixed(1) }}%</span>
                </button>
                <span v-if="resp.blown.length === 0" class="dim">无</span>
              </div>
            </div>
          </div>
          <div class="section">
            <div class="sec-title">跌停（{{ resp.limit_down.length }}）</div>
            <div class="card flat-card">
              <div class="l-chips">
                <button v-for="e in resp.limit_down" :key="e.code" class="chip-s downed" @click="openStock(e)">
                  <span class="c-name">{{ nameOf(e) }}</span>
                  <span class="mono c-pct down">{{ e.pct.toFixed(1) }}%</span>
                </button>
                <span v-if="resp.limit_down.length === 0" class="dim">无</span>
              </div>
            </div>
          </div>
        </div>
      </template>
    </template>

    <StockDialog
      v-if="stockDialog"
      :market="stockDialog.market"
      :code="stockDialog.code"
      :name="stockDialog.name"
      @close="stockDialog = null"
    />
  </div>
</template>

<style scoped>
.vipdoc-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  padding: 8px 12px;
}
.vipdoc-input {
  flex: 1;
  min-width: 260px;
  padding: 4px 10px;
  font-size: 12px;
}
.limitup-view {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.view-head,
.stat-strip,
.err,
.loading,
.section {
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
.stale-badge {
  font-size: 11px;
  color: var(--warn);
  border: 1px solid var(--warn);
  border-radius: 3px;
  padding: 0 6px;
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
  flex-wrap: wrap;
}
.err code {
  color: var(--text-muted);
}
.loading {
  padding: 40px 0;
  text-align: center;
  color: var(--text-dim);
}
.stat-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.stat-card {
  padding: 10px 14px;
}
.stat-title {
  font-size: 11.5px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.stat-main {
  font-size: 17px;
  font-weight: 700;
}
.unit {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-muted);
}
.stat-sub {
  font-size: 11.5px;
  margin-top: 2px;
}
.section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sec-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-muted);
}
.ladder-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
}
.l-height {
  flex-shrink: 0;
  width: 52px;
  text-align: center;
  font-weight: 700;
  font-size: 14px;
  color: var(--up);
  border: 1px solid var(--up);
  border-radius: var(--radius);
  padding: 3px 0;
}
.l-height.high {
  color: #fff;
  background: var(--up);
}
.l-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip-s {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  font-size: 12px;
  border-radius: 999px;
  background: rgba(239, 65, 70, 0.08);
  border: 1px solid var(--border);
  cursor: pointer;
}
.chip-s:hover {
  border-color: var(--up);
}
.chip-s.blown {
  background: rgba(255, 165, 0, 0.08);
}
.chip-s.blown:hover {
  border-color: var(--warn);
}
.chip-s.downed {
  background: rgba(24, 160, 88, 0.08);
}
.chip-s.downed:hover {
  border-color: var(--down);
}
.c-name {
  font-weight: 600;
}
.st-mark {
  font-size: 9.5px;
  color: var(--warn);
  margin-left: 3px;
}
.c-pct {
  font-size: 11.5px;
}
.flat-card {
  padding: 10px 12px;
}
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
@media (max-width: 1024px) {
  .stat-strip,
  .two-col {
    grid-template-columns: 1fr;
  }
}
</style>
