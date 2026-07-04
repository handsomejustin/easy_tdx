<script setup lang="ts">
// 策略库页面：列出用户保存的策略，支持「载入」（回填到对应回测页）+「删除」，
// 以及「组合回测」——勾选多个策略，各拿 1/N 资金、各跑原标的，看综合表现。
// 数据来自后端 SQLite（GET /api/v1/strategies）。空态提示去回测页保存。

import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import EquityChart from '../components/EquityChart.vue'
import MetricTable from '../components/MetricTable.vue'
import PortfolioCompareChart from '../components/PortfolioCompareChart.vue'
import PortfolioSummaryTable from '../components/PortfolioSummaryTable.vue'
import {
  deleteSavedStrategy,
  fetchSavedStrategies,
  formatError,
} from '../api'
import type { MultiStrategyItem, Performance, SavedStrategy } from '../types'
import { useBacktestStore } from '../stores/backtest'

const router = useRouter()
const store = useBacktestStore()

const strategies = ref<SavedStrategy[]>([])
const loading = ref(false)
const error = ref('')
const deletingId = ref<string | null>(null)

// ── 多策略组合回测：勾选 ─────────────────────────────────────────────────────
const selectedIds = ref<Set<string>>(new Set())

function toggleSelect(id: string) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

const selectedStrategies = computed(() =>
  strategies.value.filter((s) => selectedIds.value.has(s.id)),
)

function clearSelection() {
  selectedIds.value = new Set()
}

/** 组合回测：把勾选的策略组装成 MultiStrategyItem[]，各跑原标的，资金均分。 */
async function onComboBacktest() {
  if (selectedStrategies.value.length === 0) return
  store.error = ''
  // 只取有单标的上下文（symbol）的策略；组合类策略没有单一 symbol，跳过并提示。
  const usable = selectedStrategies.value.filter((s) => s.context?.symbol)
  const skipped = selectedStrategies.value.length - usable.length
  if (usable.length === 0) {
    store.error = '勾选的策略缺少标的上下文（symbol），无法组合回测。请勾选单标的策略。'
    return
  }
  const items: MultiStrategyItem[] = usable.map((s) => ({
    strategy: s.strategy,
    strategy_label: s.strategy_label || s.strategy,
    params: s.params,
    symbol: s.context.symbol as string,
    category: (s.context.category as MultiStrategyItem['category']) || 'DAY',
    start_date: (s.context.start_date as string) || undefined,
    end_date: (s.context.end_date as string) || undefined,
  }))
  await store.runMultiStrategy({ items, cash: 1_000_000 })
  if (skipped > 0) {
    store.error = `已跳过 ${skipped} 个缺少单一标的的策略（组合策略无 symbol）。`
  }
}

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetchSavedStrategies()
    strategies.value = resp.strategies
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

/** 载入：把保存的策略 + 标的上下文塞进 URL query，跳转对应回测页（页面 onMounted 时回填）。 */
function onLoad(s: SavedStrategy) {
  const ctx = s.context
  const params = JSON.stringify(s.params)
  if (s.kind === 'portfolio') {
    router.push({
      path: '/portfolio',
      query: {
        strategy: s.strategy,
        params,
        stocks: Array.isArray(ctx.stocks) ? (ctx.stocks as string[]).join(',') : '',
        startDate: (ctx.start_date as string) || undefined,
        endDate: (ctx.end_date as string) || undefined,
        category: (ctx.category as string) || undefined,
      },
    })
  } else {
    // 保存的 symbol 带"市场:6位代码"前缀（如 SH:601088，便于策略库展示），
    // 但回测页 SymbolPicker 的 code 只接受纯 6 位数字（市场由 detectMarket 自动识别），
    // 故载入时剥掉前缀，只传 6 位代码。
    const rawSymbol = (ctx.symbol as string) || ''
    const codeOnly = rawSymbol.includes(':') ? rawSymbol.split(':').pop()! : rawSymbol
    router.push({
      path: '/',
      query: {
        strategy: s.strategy,
        params,
        symbol: codeOnly || undefined,
        startDate: (ctx.start_date as string) || undefined,
        endDate: (ctx.end_date as string) || undefined,
        category: (ctx.category as string) || undefined,
      },
    })
  }
}

async function onDelete(s: SavedStrategy) {
  if (!confirm(`确定删除「${s.name}」？此操作不可撤销。`)) return
  deletingId.value = s.id
  try {
    await deleteSavedStrategy(s.id)
    strategies.value = strategies.value.filter((x) => x.id !== s.id)
  } catch (e) {
    error.value = formatError(e)
  } finally {
    deletingId.value = null
  }
}

// ── 展示辅助 ────────────────────────────────────────────────────────────────

function pct(v: unknown): string {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : '-'
}
function num(v: unknown, d = 2): string {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n.toFixed(d) : '-'
}
function ctxLabel(s: SavedStrategy): string {
  const ctx = s.context
  if (s.kind === 'portfolio') {
    const stocks = Array.isArray(ctx.stocks) ? (ctx.stocks as string[]) : []
    return stocks.length ? `${stocks.length} 只：${stocks.slice(0, 3).join(' ')}${stocks.length > 3 ? ' …' : ''}` : '-'
  }
  return (ctx.symbol as string) || '-'
}
function dateRange(s: SavedStrategy): string {
  const ctx = s.context
  const s0 = (ctx.start_date as string) || ''
  const s1 = (ctx.end_date as string) || ''
  if (!s0 && !s1) return '-'
  return `${s0 || '?'} ~ ${s1 || '?'}`
}
function createdShort(s: SavedStrategy): string {
  // created_at 形如 "2026-07-04T15:30:22Z"，截到分钟
  return (s.created_at || '').replace('T', ' ').replace(/:\d{2}Z?$/, '').slice(0, 16)
}

// ── 组合回测：当前持仓（回测结束时各策略的持仓快照）────────────────────────────
// positions 是每根 K 线一行的快照序列，取最后一行 = 回测结束时的持仓。
// size > 0 表示该策略结束仍持有，size ≈ 0 表示已清仓。

interface Holding {
  key: string // 策略槽位 key，如 "双均线交叉@SH:601088"
  strategyLabel: string
  symbol: string
  size: number // 持仓数量（0 = 已清仓）
  avgPrice: number // 持仓成本
  marketValue: number // 市值
  unrealizedPnl: number // 未实现盈亏（元）
  unrealizedPct: number // 未实现收益率
  holding: boolean // 是否在持仓中
}

const holdings = computed<Holding[]>(() => {
  const res = store.multiStrategyResult
  if (!res) return []
  const out: Holding[] = []
  for (const [key, br] of Object.entries(res.individual_results)) {
    const positions = br.positions as Array<Record<string, unknown>>
    if (!Array.isArray(positions) || positions.length === 0) continue
    const last = positions[positions.length - 1]
    const size = Number(last.size ?? 0)
    const avgPrice = Number(last.avg_price ?? 0)
    const marketValue = Number(last.market_value ?? 0)
    const unrealizedPnl = Number(last.unrealized_pnl ?? 0)
    const [strategyLabel, symbol] = key.split('@')
    out.push({
      key,
      strategyLabel: strategyLabel || key,
      symbol: symbol || '',
      size,
      avgPrice,
      marketValue,
      unrealizedPnl,
      unrealizedPct: avgPrice > 0 ? unrealizedPnl / (avgPrice * Math.abs(size)) : 0,
      holding: size > 0.5, // 容忍浮点误差
    })
  }
  return out
})

const holdingCount = computed(() => holdings.value.filter((h) => h.holding).length)

// 组合整体绩效（19 项指标）。后端 total_performance 现含完整指标，转成
// MetricTable 需要的 Performance 类型（缺失字段补 0 兜底，保证渲染不崩）。
const comboPerf = computed<Performance | null>(() => {
  const tp = store.multiStrategyResult?.total_performance
  if (!tp) return null
  const get = (k: string, d = 0): number => {
    const v = (tp as Record<string, unknown>)[k]
    return typeof v === 'number' ? v : d
  }
  return {
    total_return: get('total_return'),
    annual_return: get('annual_return'),
    max_drawdown: get('max_drawdown'),
    max_dd_duration: get('max_dd_duration'),
    sharpe: get('sharpe'),
    sortino: get('sortino'),
    calmar: get('calmar'),
    total_trades: get('total_trades'),
    win_trades: get('win_trades'),
    lose_trades: get('lose_trades'),
    rejected_trades: get('rejected_trades'),
    win_rate: get('win_rate'),
    profit_factor: get('profit_factor'),
    avg_win: get('avg_win'),
    avg_loss: get('avg_loss'),
    max_win: get('max_win'),
    max_loss: get('max_loss'),
    avg_holding_days: get('avg_holding_days'),
    volatility: get('volatility'),
  }
})
</script>

<template>
  <div class="strategies-view">
    <header class="page-header">
      <div>
        <h2>策略库</h2>
        <p class="subtitle">
          保存你觉得不错的策略，下次直接载入或重跑。共 {{ strategies.length }} 条。
          勾选多个单标的策略可做「组合回测」——各拿 1/N 资金、各跑原标的，看综合表现。
        </p>
      </div>
      <div class="header-actions">
        <button
          class="primary sm"
          :disabled="selectedStrategies.length === 0 || store.multiStrategyRunning"
          @click="onComboBacktest"
        >
          {{ store.multiStrategyRunning ? '组合回测中…' : `组合回测（${selectedStrategies.length}）` }}
        </button>
        <button
          v-if="selectedStrategies.length > 0"
          class="ghost sm"
          @click="clearSelection"
        >
          清除选择
        </button>
        <button class="ghost" :disabled="loading" @click="load">
          {{ loading ? '刷新中…' : '↻ 刷新' }}
        </button>
      </div>
    </header>

    <div v-if="error || store.error" class="error-banner">⚠ {{ error || store.error }}</div>

    <div v-if="!loading && strategies.length === 0 && !error" class="placeholder">
      <p>还没有保存的策略。</p>
      <p class="hint">
        在「单标的回测」或「组合回测」跑出满意结果后，点结果区的「保存策略」即可收藏到这里。
      </p>
    </div>

    <div v-if="loading && strategies.length === 0" class="placeholder">
      <p>加载中…</p>
    </div>

    <div v-if="strategies.length" class="card-grid">
      <article
        v-for="s in strategies"
        :key="s.id"
        class="card"
        :class="{ selected: selectedIds.has(s.id) }"
      >
        <div class="card-head">
          <label class="select-box" :title="s.context?.symbol ? '加入组合回测' : '组合策略暂不支持组合回测'">
            <input
              type="checkbox"
              :checked="selectedIds.has(s.id)"
              :disabled="!s.context?.symbol"
              @change="toggleSelect(s.id)"
            />
          </label>
          <span class="kind-badge" :class="s.kind">{{ s.kind === 'portfolio' ? '组合' : '单标的' }}</span>
          <h3 class="card-title">{{ s.name }}</h3>
        </div>

        <div class="card-strategy">
          {{ s.strategy_label || s.strategy }}
          <span class="params">{{ JSON.stringify(s.params) }}</span>
        </div>

        <div class="card-meta">
          <div class="meta-row"><span class="k">标的</span><span class="v">{{ ctxLabel(s) }}</span></div>
          <div class="meta-row"><span class="k">区间</span><span class="v">{{ dateRange(s) }}</span></div>
        </div>

        <div v-if="Object.keys(s.snapshot).length" class="card-snapshot">
          <div class="snap-item">
            <span class="k">总收益</span>
            <span class="v mono" :class="Number(s.snapshot.total_return) > 0 ? 'pos' : 'neg'">
              {{ pct(s.snapshot.total_return) }}
            </span>
          </div>
          <div class="snap-item">
            <span class="k">夏普</span><span class="v mono">{{ num(s.snapshot.sharpe) }}</span>
          </div>
          <div class="snap-item">
            <span class="k">回撤</span><span class="v mono neg">{{ pct(s.snapshot.max_drawdown) }}</span>
          </div>
        </div>

        <div v-if="s.tags.length" class="card-tags">
          <span v-for="t in s.tags" :key="t" class="tag">{{ t }}</span>
        </div>

        <p v-if="s.notes" class="card-notes">{{ s.notes }}</p>

        <div class="card-foot">
          <span class="created">{{ createdShort(s) }}</span>
          <span class="actions">
            <button class="primary sm" @click="onLoad(s)">载入</button>
            <button
              class="danger sm"
              :disabled="deletingId === s.id"
              @click="onDelete(s)"
            >
              {{ deletingId === s.id ? '…' : '删除' }}
            </button>
          </span>
        </div>
      </article>
    </div>

    <!-- 多策略组合回测结果（复用组合页图表组件） -->
    <section v-if="store.multiStrategyResult || store.multiStrategyRunning" class="combo-result">
      <h3 class="combo-title">
        组合回测结果
        <span v-if="store.multiStrategyResult" class="combo-meta">
          · {{ store.multiStrategyResult.total_performance.total_stocks }} 个策略 ·
          总资金 {{ store.multiStrategyResult.total_performance.total_cash.toFixed(0) }}
        </span>
      </h3>

      <div v-if="store.multiStrategyRunning && !store.multiStrategyResult" class="combo-loading">
        组合回测中…（逐个策略取行情 + 回测，请稍候）
      </div>

      <div v-if="store.multiStrategyResult" class="combo-content">
        <div class="combo-summary">
          <div class="combo-stat">
            <span class="label">组合总收益</span>
            <span
              class="value"
              :class="store.multiStrategyResult.total_performance.total_return > 0 ? 'pos' : 'neg'"
            >
              {{ (store.multiStrategyResult.total_performance.total_return * 100).toFixed(2) }}%
            </span>
          </div>
        </div>

        <div class="combo-chart-block">
          <h4>组合净值曲线</h4>
          <EquityChart :equity="store.multiStrategyResult.combined_equity" />
        </div>

        <div v-if="comboPerf" class="combo-chart-block">
          <h4>绩效指标</h4>
          <MetricTable :perf="comboPerf" />
        </div>

        <div class="combo-chart-block">
          <h4>各策略绩效对比</h4>
          <PortfolioSummaryTable
            :results="store.multiStrategyResult.individual_results"
            :allocation="store.multiStrategyResult.equity_allocation"
          />
        </div>

        <div class="combo-chart-block">
          <h4>各策略净值叠加（归一化）</h4>
          <PortfolioCompareChart
            :results="store.multiStrategyResult.individual_results"
          />
        </div>

        <div class="combo-chart-block">
          <h4>
            当前持仓（{{ holdingCount }}/{{ holdings.length }} 在持仓中）
            <span class="holdings-hint">回测结束时各策略的持仓快照</span>
          </h4>
          <p v-if="holdings.length === 0" class="empty-text">无持仓数据</p>
          <table v-else class="holdings-table">
            <thead>
              <tr>
                <th>策略</th>
                <th>标的</th>
                <th>状态</th>
                <th class="num">持仓数量</th>
                <th class="num">成本价</th>
                <th class="num">市值</th>
                <th class="num">未实现盈亏</th>
                <th class="num">收益率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="h in holdings" :key="h.key" :class="{ cleared: !h.holding }">
                <td>{{ h.strategyLabel }}</td>
                <td class="sym">{{ h.symbol }}</td>
                <td>
                  <span class="status-tag" :class="h.holding ? 'holding' : 'cleared'">
                    {{ h.holding ? '持仓' : '空仓' }}
                  </span>
                </td>
                <td class="num">{{ h.size > 0 ? h.size.toFixed(0) : '-' }}</td>
                <td class="num">{{ h.holding ? h.avgPrice.toFixed(2) : '-' }}</td>
                <td class="num">{{ h.holding ? h.marketValue.toFixed(0) : '-' }}</td>
                <td class="num" :class="{ pos: h.unrealizedPnl > 0, neg: h.unrealizedPnl < 0 }">
                  {{ h.holding ? (h.unrealizedPnl > 0 ? '+' : '') + h.unrealizedPnl.toFixed(0) : '-' }}
                </td>
                <td
                  class="num"
                  :class="{ pos: h.unrealizedPct > 0, neg: h.unrealizedPct < 0 }"
                >
                  {{ h.holding ? (h.unrealizedPct * 100).toFixed(2) + '%' : '-' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.strategies-view {
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
  gap: 8px;
}
.header-actions .sm {
  font-size: 12px;
  padding: 6px 12px;
  cursor: pointer;
}
.header-actions .primary {
  border-radius: var(--radius);
}
.ghost {
  font-size: 12px;
  padding: 6px 12px;
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
.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  height: 60%;
  color: var(--text-dim);
  gap: 8px;
}
.placeholder .hint {
  font-size: 12px;
  max-width: 420px;
  line-height: 1.6;
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

/* 卡片网格 */
.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}
.card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
/* 勾选框：加入组合回测 */
.select-box {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  cursor: pointer;
}
.select-box input {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: var(--accent);
}
.select-box input:disabled {
  cursor: not-allowed;
  opacity: 0.3;
}
.card.selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}
.kind-badge {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 4px;
  background: rgba(74, 158, 255, 0.15);
  color: var(--accent);
  flex-shrink: 0;
}
.kind-badge.portfolio {
  background: rgba(140, 110, 220, 0.18);
  color: #b39ddb;
}
.card-title {
  font-size: 14px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-strategy {
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.card-strategy .params {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-dim);
}
.card-meta {
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.meta-row {
  display: flex;
  gap: 8px;
}
.meta-row .k {
  color: var(--text-dim);
  width: 32px;
  flex-shrink: 0;
}
.meta-row .v {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-snapshot {
  display: flex;
  gap: 20px;
  padding: 8px 0;
  border-top: 1px dashed var(--border);
  border-bottom: 1px dashed var(--border);
}
.snap-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.snap-item .k {
  font-size: 11px;
  color: var(--text-dim);
}
.snap-item .v {
  font-size: 15px;
  font-weight: 600;
}
.mono {
  font-family: var(--font-mono);
}
.pos {
  color: var(--up);
}
.neg {
  color: var(--down);
}
.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--border);
  color: var(--text-muted);
}
.card-notes {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
  white-space: pre-wrap;
}
.card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
  padding-top: 6px;
}
.created {
  font-size: 11px;
  color: var(--text-dim);
  font-family: var(--font-mono);
}
.actions {
  display: flex;
  gap: 8px;
}
.sm {
  font-size: 12px;
  padding: 4px 12px;
}
.danger {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-muted);
  border-radius: var(--radius);
  cursor: pointer;
}
.danger:hover:not(:disabled) {
  border-color: var(--up);
  color: var(--up);
}
.danger:disabled {
  opacity: 0.5;
  cursor: default;
}

/* 多策略组合回测结果区 */
.combo-result {
  margin-top: 24px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 18px;
}
.combo-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 14px;
}
.combo-meta {
  font-size: 12px;
  color: var(--text-dim);
  font-weight: 400;
}
.combo-loading {
  padding: 24px;
  text-align: center;
  color: var(--text-dim);
  font-size: 13px;
}
.combo-content {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.combo-summary {
  display: flex;
  gap: 28px;
}
.combo-stat {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.combo-stat .label {
  font-size: 12px;
  color: var(--text-dim);
}
.combo-stat .value {
  font-size: 22px;
  font-weight: 700;
  font-family: var(--font-mono);
}
.combo-chart-block h4 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 10px;
}
.holdings-hint {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-dim);
  margin-left: 6px;
}
.empty-text {
  color: var(--text-dim);
  font-size: 13px;
  padding: 12px 0;
}
.holdings-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.holdings-table th,
.holdings-table td {
  padding: 7px 10px;
  text-align: left;
  border-bottom: 1px solid var(--border);
}
.holdings-table th {
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 600;
}
.holdings-table .num {
  text-align: right;
  font-family: var(--font-mono);
}
.holdings-table .sym {
  font-family: var(--font-mono);
  font-weight: 600;
}
.holdings-table tr.cleared {
  opacity: 0.5;
}
.status-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
}
.status-tag.holding {
  background: rgba(239, 65, 70, 0.12);
  color: var(--up);
}
.status-tag.cleared {
  background: var(--border);
  color: var(--text-dim);
}
</style>
