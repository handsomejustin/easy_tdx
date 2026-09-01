<script setup lang="ts">
// 信号雷达页：一键扫描策略库全部已保存策略（单标的/多标的/多策略组合），
// 把每种策略展开成"策略×标的"子任务，用最近 N 根 K 线（窗口可选，默认 5）
// 判断买/卖信号并汇总列出——方便每天跟踪"今天哪些策略有信号"。
// 后端 POST /backtest/signal-scan/run/async；取行情在提交请求内完成（标的多时
// 提交本身就要等一会儿），结果轮询拿 SignalScanResult。上次扫描结果缓存在
// localStorage，进页面先展示，避免每次都要重扫。

import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { asSignalScanResult, formatError, runSignalScanWithPolling } from '../api'
import type { SignalScanResult, SignalScanRow } from '../types'

const router = useRouter()

const WINDOW_OPTIONS = [1, 3, 5, 10]
const STORAGE_KEY = 'easy-tdx.signal-radar.last'

const windowBars = ref(5)
const scanning = ref(false)
const error = ref('')
const result = ref<SignalScanResult | null>(null)
const scannedAt = ref('') // 本地时间戳（上次扫描完成时刻）
const elapsedSec = ref('') // 上次扫描总耗时（提交+计算）

interface CachedScan {
  result: SignalScanResult
  scannedAt: string
  windowBars: number
}

onMounted(() => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return
    const cached = JSON.parse(raw) as CachedScan
    if (cached?.result?.rows) {
      result.value = cached.result
      scannedAt.value = cached.scannedAt || ''
      if (WINDOW_OPTIONS.includes(cached.windowBars)) windowBars.value = cached.windowBars
    }
  } catch {
    // 缓存损坏则忽略，直接空态
  }
})

async function onScan() {
  if (scanning.value) return
  scanning.value = true
  error.value = ''
  const t0 = Date.now()
  try {
    const state = await runSignalScanWithPolling({ window_bars: windowBars.value })
    result.value = asSignalScanResult(state)
    scannedAt.value = new Date().toLocaleString('zh-CN', { hour12: false })
    elapsedSec.value = ((Date.now() - t0) / 1000).toFixed(1)
    const cached: CachedScan = {
      result: result.value,
      scannedAt: scannedAt.value,
      windowBars: windowBars.value,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cached))
  } catch (e) {
    error.value = formatError(e)
  } finally {
    scanning.value = false
  }
}

// ── 筛选 ─────────────────────────────────────────────────────────────────────

type FilterKey = 'signal' | 'buy' | 'sell' | 'error' | 'all'

const activeFilter = ref<FilterKey>('signal') // 默认只看有信号的

function hasBuy(r: SignalScanRow): boolean {
  return r.recent_signals.some((s) => s.direction === 'BUY')
}
function hasSell(r: SignalScanRow): boolean {
  return r.recent_signals.some((s) => s.direction === 'SELL')
}

const filterDefs = computed(() => {
  const rows = result.value?.rows || []
  const defs: { key: FilterKey; label: string; count: number }[] = [
    { key: 'signal', label: '有信号', count: rows.filter((r) => !r.error && r.recent_signals.length > 0).length },
    { key: 'buy', label: '买入', count: rows.filter((r) => !r.error && hasBuy(r)).length },
    { key: 'sell', label: '卖出', count: rows.filter((r) => !r.error && hasSell(r)).length },
    { key: 'error', label: '失败', count: rows.filter((r) => r.error).length },
    { key: 'all', label: '全部', count: rows.length },
  ]
  return defs
})

const visibleRows = computed(() => {
  const rows = result.value?.rows || []
  switch (activeFilter.value) {
    case 'signal':
      return rows.filter((r) => !r.error && r.recent_signals.length > 0)
    case 'buy':
      return rows.filter((r) => !r.error && hasBuy(r))
    case 'sell':
      return rows.filter((r) => !r.error && hasSell(r))
    case 'error':
      return rows.filter((r) => r.error)
    default:
      return rows
  }
})

// ── 展示辅助 ─────────────────────────────────────────────────────────────────

function kindLabel(kind: SignalScanRow['kind']): string {
  return kind === 'multi' ? '多策略' : kind === 'portfolio' ? '多标的' : '单标的'
}

/** 窗口内信号序列，如 "B 08-19 · S 08-20"（B=买 S=卖）。 */
function signalSeq(r: SignalScanRow): string {
  return r.recent_signals
    .map((s) => `${s.direction === 'BUY' ? 'B' : 'S'} ${s.date.slice(5, 10)}`)
    .join(' · ')
}

/** 跳转单标的回测页回填该子策略（query 模式与策略库「载入」一致）。 */
function onLoad(r: SignalScanRow) {
  const codeOnly = r.symbol.includes(':') ? r.symbol.split(':').pop()! : r.symbol
  router.push({
    path: '/backtest',
    query: {
      strategy: r.strategy,
      params: JSON.stringify(r.params),
      symbol: codeOnly || undefined,
      category: r.category || undefined,
      endDate: new Date().toISOString().slice(0, 10),
    },
  })
}
</script>

<template>
  <div class="radar-view">
    <header class="page-header">
      <div>
        <h2>信号雷达</h2>
        <p class="subtitle">
          一键扫描策略库全部已保存策略，列出最近 K 线内出现买入/卖出信号的策略。
          <template v-if="scannedAt">
            上次扫描 {{ scannedAt }}<template v-if="elapsedSec">（{{ elapsedSec }}s）</template>。
          </template>
        </p>
      </div>
      <div class="header-actions">
        <label class="window-picker">
          窗口
          <select v-model="windowBars" :disabled="scanning">
            <option v-for="w in WINDOW_OPTIONS" :key="w" :value="w">{{ w }} 根</option>
          </select>
        </label>
        <button class="primary" :disabled="scanning" @click="onScan">
          {{ scanning ? '扫描中…' : '⚡ 一键扫描' }}
        </button>
      </div>
    </header>

    <div v-if="error" class="error-banner">⚠ {{ error }}</div>

    <!-- 扫描中：提交请求内要逐标的取行情，需要等待 -->
    <div v-if="scanning" class="scanning-box">
      <span class="spinner"></span>
      正在扫描：逐标的取最近 800 根 K 线并计算信号（标的较多时约需几十秒，请稍候）…
    </div>

    <template v-if="result && !scanning">
      <!-- 汇总卡片 -->
      <div class="stat-cards">
        <div class="stat">
          <span class="k">子任务</span>
          <span class="v">{{ result.total }}</span>
        </div>
        <div class="stat">
          <span class="k">买入信号</span>
          <span class="v buy">{{ result.buy_count }}</span>
        </div>
        <div class="stat">
          <span class="k">卖出信号</span>
          <span class="v sell">{{ result.sell_count }}</span>
        </div>
        <div class="stat">
          <span class="k">失败</span>
          <span class="v dim">{{ result.error_count }}</span>
        </div>
      </div>

      <p class="hint">
        窗口 = 最近 {{ windowBars }} 根 {{ result.rows[0]?.category === 'DAY' ? '交易日' : 'K 线' }}；
        盘中最后一根 K 线未收盘，信号为盘中即时值，收盘后为准。
      </p>

      <!-- 筛选 tab -->
      <nav class="tabs">
        <button
          v-for="f in filterDefs"
          :key="f.key"
          :class="['tab', { active: activeFilter === f.key }]"
          @click="activeFilter = f.key"
        >
          {{ f.label }}<span class="tab-count">{{ f.count }}</span>
        </button>
      </nav>

      <div v-if="visibleRows.length === 0" class="placeholder">
        <p>{{ activeFilter === 'signal' ? '窗口内没有任何买卖信号。' : '该筛选下没有子任务。' }}</p>
        <p class="hint">可切换更大的窗口（如 10 根）或点「一键扫描」重新检查。</p>
      </div>

      <table v-else class="radar-table">
        <thead>
          <tr>
            <th>策略</th>
            <th>类型</th>
            <th>子策略 / 参数</th>
            <th>标的</th>
            <th>最新信号</th>
            <th>窗口内信号</th>
            <th class="num">最新收盘</th>
            <th>仓位</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, i) in visibleRows" :key="`${r.strategy_id}-${i}`" :class="{ errored: r.error }">
            <td class="name" :title="r.strategy_name">{{ r.strategy_name }}</td>
            <td><span class="kind-badge" :class="r.kind">{{ kindLabel(r.kind) }}</span></td>
            <td class="sub-strat">
              {{ r.strategy_label || r.strategy }}
              <span class="params">{{ JSON.stringify(r.params) }}</span>
            </td>
            <td class="sym">{{ r.symbol }}</td>
            <td v-if="r.error" class="err" colspan="4">⚠ {{ r.error }}</td>
            <template v-else>
              <td>
                <span v-if="r.latest_signal" class="signal-tag" :class="r.latest_signal">
                  {{ r.latest_signal === 'BUY' ? '买入' : '卖出' }}
                </span>
                <span v-else class="none-tag">—</span>
              </td>
              <td class="seq">{{ signalSeq(r) || '—' }}</td>
              <td class="num">{{ r.last_close != null ? r.last_close.toFixed(2) : '-' }}</td>
              <td>
                <span v-if="r.position" class="pos-tag" :class="r.position">
                  {{ r.position === 'holding' ? '持仓' : '空仓' }}
                </span>
              </td>
            </template>
            <td>
              <button v-if="!r.error" class="ghost sm" @click="onLoad(r)">载入</button>
            </td>
          </tr>
        </tbody>
      </table>
    </template>

    <div v-if="!result && !scanning && !error" class="placeholder">
      <p>还没有扫描结果。</p>
      <p class="hint">
        点右上角「⚡ 一键扫描」，把策略库里保存的单策略与组合策略全部检查一遍，
        列出最近 {{ windowBars }} 根 K 线内出现买卖信号的策略。每天收盘后扫一次即可跟踪。
      </p>
    </div>
  </div>
</template>

<style scoped>
.radar-view {
  height: 100%;
  overflow-y: auto;
  padding: 16px 20px 32px;
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-header h2 {
  font-size: 16px;
  font-weight: 600;
}
.subtitle {
  font-size: 12px;
  color: var(--text-dim);
  margin-top: 4px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.window-picker {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
}
.window-picker select {
  background: var(--bg-panel);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 5px 8px;
  font-size: 12px;
  cursor: pointer;
}
.primary {
  font-size: 13px;
  padding: 7px 18px;
  background: var(--accent);
  border: 1px solid var(--accent);
  color: #fff;
  font-weight: 600;
  border-radius: var(--radius);
  cursor: pointer;
}
.primary:hover:not(:disabled) {
  filter: brightness(1.1);
}
.primary:disabled {
  opacity: 0.6;
  cursor: default;
}
.error-banner {
  background: rgba(239, 65, 70, 0.12);
  border: 1px solid var(--up);
  color: var(--up);
  padding: 10px 14px;
  border-radius: var(--radius);
  margin-bottom: 16px;
  font-size: 13px;
}
.scanning-box {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  font-size: 13px;
}
.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 50%;
  color: var(--text-dim);
  gap: 8px;
}
.placeholder .hint,
.hint {
  font-size: 12px;
  color: var(--text-dim);
  max-width: 560px;
  line-height: 1.6;
}

/* 汇总卡片 */
.stat-cards {
  display: flex;
  gap: 14px;
  margin-bottom: 10px;
}
.stat {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 3px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
}
.stat .k {
  font-size: 12px;
  color: var(--text-dim);
}
.stat .v {
  font-size: 22px;
  font-weight: 700;
  font-family: var(--font-mono);
}
.stat .v.buy {
  color: var(--up);
}
.stat .v.sell {
  color: var(--down);
}
.stat .v.dim {
  color: var(--text-dim);
}

/* 筛选 tab（与策略库页同风格） */
.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border);
  margin: 14px 0 12px;
}
.tab {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.tab:hover {
  color: var(--text);
}
.tab.active {
  color: var(--text);
  border-bottom-color: var(--accent);
}
.tab-count {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  background: var(--border);
  color: var(--text-dim);
  font-weight: 400;
}
.tab.active .tab-count {
  background: rgba(74, 158, 255, 0.18);
  color: var(--accent);
}

/* 结果表 */
.radar-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.radar-table th,
.radar-table td {
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
.radar-table th {
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 600;
}
.radar-table .num {
  text-align: right;
  font-family: var(--font-mono);
}
.radar-table .name {
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
}
.radar-table .sym {
  font-family: var(--font-mono);
  font-weight: 600;
  white-space: nowrap;
}
.radar-table .sub-strat {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sub-strat .params {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
  margin-left: 6px;
}
.radar-table .seq {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
  white-space: nowrap;
}
.radar-table .err {
  color: var(--up);
  font-size: 12px;
}
.radar-table tr.errored {
  opacity: 0.75;
}

/* 徽章 */
.kind-badge {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 4px;
  background: rgba(74, 158, 255, 0.15);
  color: var(--accent);
  white-space: nowrap;
}
.kind-badge.portfolio {
  background: rgba(140, 110, 220, 0.18);
  color: #b39ddb;
}
.kind-badge.multi {
  background: rgba(245, 158, 11, 0.18);
  color: #f59e0b;
}
.signal-tag {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 4px;
  font-weight: 600;
  white-space: nowrap;
}
/* A股习惯：买入红、卖出绿 */
.signal-tag.BUY {
  background: rgba(239, 65, 70, 0.14);
  color: var(--up);
}
.signal-tag.SELL {
  background: rgba(24, 160, 88, 0.16);
  color: var(--down);
}
.none-tag {
  color: var(--text-dim);
}
.pos-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  white-space: nowrap;
}
.pos-tag.holding {
  background: rgba(239, 65, 70, 0.12);
  color: var(--up);
}
.pos-tag.flat {
  background: var(--border);
  color: var(--text-dim);
}
.ghost {
  font-size: 12px;
  padding: 4px 12px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  cursor: pointer;
}
.ghost:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}
.sm {
  font-size: 12px;
  padding: 4px 12px;
}
</style>
