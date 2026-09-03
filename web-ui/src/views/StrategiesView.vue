<script setup lang="ts">
// 策略库页面：列出用户保存的策略，支持「载入」（回填到对应回测页）+「删除」，
// 以及「组合回测」——勾选多个策略，各拿 1/N 资金、各跑原标的，看综合表现。
// 数据来自后端 SQLite（GET /api/v1/strategies）。空态提示去回测页保存。

import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import AiInterpretModal from '../components/AiInterpretModal.vue'
import EquityChart from '../components/EquityChart.vue'
import EvaluatePanel from '../components/EvaluatePanel.vue'
import GradeDetails from '../components/GradeDetails.vue'
import MetricTable from '../components/MetricTable.vue'
import PortfolioCompareChart from '../components/PortfolioCompareChart.vue'
import PortfolioSummaryTable from '../components/PortfolioSummaryTable.vue'
import WalkForwardPanel from '../components/WalkForwardPanel.vue'
import {
  deleteSavedStrategy,
  fetchSavedStrategies,
  formatError,
  saveStrategy,
} from '../api'
import { buildPortfolioAiPrompt } from '../aiPrompt'
import { GRADE_META, gradePortfolio } from '../grading'
import { detectMarket } from '../market'
import type { Category, MultiStrategyItem, Performance, SavedStrategy } from '../types'
import { useBacktestStore } from '../stores/backtest'

const router = useRouter()
const store = useBacktestStore()

const strategies = ref<SavedStrategy[]>([])
const loading = ref(false)
const error = ref('')
const deletingId = ref<string | null>(null)

// ── Tab 分类：单标的 / 组合 ────────────────────────────────────────────────────
// single tab = kind='single'；combo tab = kind='portfolio' | 'multi'
// 默认进单标的；组合回测按钮仅在 single tab 显示（组合策略无法再被组合）
type TabKey = 'single' | 'combo'
const activeTab = ref<TabKey>('single')

const singleStrategies = computed(() => strategies.value.filter((s) => s.kind === 'single'))
const comboStrategies = computed(() => strategies.value.filter((s) => s.kind !== 'single'))

// 切 tab 时清空勾选（避免跨 tab 看不到的勾选残留）
function switchTab(tab: TabKey) {
  if (activeTab.value === tab) return
  activeTab.value = tab
  selectedIds.value = new Set()
}

const visibleStrategies = computed(() =>
  activeTab.value === 'single' ? singleStrategies.value : comboStrategies.value,
)

// ── 保存组合弹窗 ─────────────────────────────────────────────────────────────
const saveComboOpen = ref(false)
const saveComboName = ref('')
const saveComboNotes = ref('')
const saveComboLoading = ref(false)
// 最近一次组合回测使用的 items（保存时复用），由 onComboBacktest 写入
const lastComboItems = ref<MultiStrategyItem[]>([])
const lastComboCash = ref<number>(1_000_000)
// 结果区引用：跑完后滚动定位
const comboResultRef = ref<HTMLElement | null>(null)
// 保存弹窗里名称输入框：打开时自动聚焦
const saveComboNameRef = ref<HTMLInputElement | null>(null)

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

/** 纠正历史保存策略的市场前缀。
 *  早期 BacktestView.fullSymbol 硬编码市场判断（漏判 5 开头的沪市基金/ETF），
 *  导致部分历史保存的策略 symbol 被错标（如 SZ:515030，应为 SH:515030），
 *  后端按错配市场取到 0 根 K 线被静默跳过。
 *  这里在发请求前用 detectMarket 重算前缀，纠正历史数据 + 兜底未来。 */
function normalizeSymbol(raw: string): string {
  if (!raw) return raw
  const code = raw.includes(':') ? raw.split(':').pop()! : raw
  return `${detectMarket(code)}:${code}`
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
    symbol: normalizeSymbol(s.context.symbol as string),
    category: (s.context.category as MultiStrategyItem['category']) || 'DAY',
    start_date: (s.context.start_date as string) || undefined,
    end_date: (s.context.end_date as string) || undefined,
  }))
  lastComboItems.value = items
  lastComboCash.value = 1_000_000
  await store.runMultiStrategy({ items, cash: 1_000_000 })
  if (skipped > 0) {
    store.error = `已跳过 ${skipped} 个缺少单一标的的策略（组合策略无 symbol）。`
  }
}

// ── 保存组合（kind: 'multi'）─────────────────────────────────────────────────

/** 打开保存组合弹窗：预填名称 + 自动聚焦输入框。 */
function openSaveCombo() {
  if (!store.multiStrategyResult) return
  saveComboName.value = `组合·${lastComboItems.value.length}策略·${new Date().toISOString().slice(0, 10)}`
  saveComboNotes.value = ''
  saveComboOpen.value = true
  // 等弹窗渲染完再聚焦
  nextTick(() => saveComboNameRef.value?.focus())
}

/** ESC 关闭弹窗（绑定在弹窗根元素 @keydown.esc） */
function closeSaveCombo() {
  if (!saveComboLoading.value) saveComboOpen.value = false
}

/** 提交保存组合：把 items + cash 存进 context，组合级绩效存 snapshot。 */
async function submitSaveCombo() {
  if (!store.multiStrategyResult || lastComboItems.value.length === 0) return
  if (!saveComboName.value.trim()) {
    error.value = '请填写组合名称'
    return
  }
  saveComboLoading.value = true
  error.value = ''
  try {
    const tp = store.multiStrategyResult.total_performance
    const created = await saveStrategy({
      name: saveComboName.value.trim(),
      kind: 'multi',
      strategy: 'multi',
      strategy_label: `${lastComboItems.value.length} 策略组合`,
      context: {
        items: lastComboItems.value,
        cash: lastComboCash.value,
      },
      trade_config: { cash: lastComboCash.value },
      snapshot: {
        total_return: tp.total_return,
        annual_return: tp.annual_return,
        total_stocks: tp.total_stocks,
        total_cash: tp.total_cash,
      },
      tags: ['组合'],
      notes: saveComboNotes.value.trim(),
    })
    strategies.value = [created, ...strategies.value]
    saveComboOpen.value = false
  } catch (e) {
    error.value = formatError(e)
  } finally {
    saveComboLoading.value = false
  }
}

// ── 载入组合（kind: 'multi'）→ 自动重跑到今天 ────────────────────────────────

function isoToday(): string {
  return new Date().toISOString().slice(0, 10)
}

/** 载入组合：把保存的 items 的 end_date 全部覆盖为今天，自动触发组合回测。
 *  这样跑出来的"当前持仓"= 截至今天的策略信号（哪些该买/该卖）。 */
async function onLoadMulti(s: SavedStrategy) {
  const ctx = s.context || {}
  const rawItems = Array.isArray(ctx.items) ? (ctx.items as MultiStrategyItem[]) : []
  if (rawItems.length === 0) {
    error.value = '该组合没有保存策略明细（items），可能数据损坏。'
    return
  }
  // 运行时校验：每条至少要有 strategy + symbol，否则带病跑到后端才报错
  const valid = rawItems.every(
    (it) => it && typeof it.strategy === 'string' && typeof it.symbol === 'string',
  )
  if (!valid) {
    error.value = '组合数据损坏：部分策略缺少 strategy 或 symbol 字段。'
    return
  }
  if (!confirm(
    `载入「${s.name}」并用今天（${isoToday()}）重跑 ${rawItems.length} 个策略？\n\n` +
    `结果区会显示截至今天的策略信号（"哪些该买/该卖"）。`,
  )) return
  const today = isoToday()
  const items = rawItems.map((it) => ({
    ...it,
    symbol: normalizeSymbol(it.symbol),
    end_date: today,
  }))
  const cash = typeof ctx.cash === 'number' ? ctx.cash : 1_000_000
  lastComboItems.value = items
  lastComboCash.value = cash
  await store.runMultiStrategy({ items, cash })
  // 跑完滚动到结果区
  await nextTick()
  comboResultRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
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
      path: '/backtest',
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
  if (s.kind === 'multi') {
    const items = Array.isArray(ctx.items) ? (ctx.items as MultiStrategyItem[]) : []
    return items.length ? `${items.length} 策略 · ${items.map((i) => i.symbol).slice(0, 3).join(' ')}${items.length > 3 ? ' …' : ''}` : '-'
  }
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

// 持仓三态视图：把 statusClass / label / rowClass 一次性算好，模板只读不调函数。
// 否则每行 ×3 次函数调用 + holdingRowClass 返回新对象会触发 Vue 额外跟踪。
type HoldingView = Holding & {
  statusClass: 'win' | 'lose' | 'wait'
  statusLabel: string
  rowClass: string
}
const holdingViews = computed<HoldingView[]>(() =>
  holdings.value.map((h) => {
    if (!h.holding) {
      return { ...h, statusClass: 'wait', statusLabel: '空仓·等买点', rowClass: 'cleared' }
    }
    return h.unrealizedPnl >= 0
      ? { ...h, statusClass: 'win', statusLabel: '持有', rowClass: 'row-win' }
      : { ...h, statusClass: 'lose', statusLabel: '持有·浮亏', rowClass: 'row-lose' }
  }),
)

// 组合整体绩效（25 项指标，与单标的 MetricTable 同口径）。后端
// total_performance 含完整指标，转成 MetricTable 需要的 Performance 类型
// （缺失字段补 0 兜底，保证老结果渲染不崩）。
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
    ulcer_index: get('ulcer_index'),
    var_95: get('var_95'),
    cvar_95: get('cvar_95'),
    sqn: get('sqn'),
    max_consecutive_wins: get('max_consecutive_wins'),
    max_consecutive_losses: get('max_consecutive_losses'),
  }
})

// 组合评级：从 combined_equity 重算夏普/卡玛/回撤/波动率等 5 维度评分，
// 与 /portfolio 页和单标的回测页同口径（复用 gradePortfolio）。
const comboGrade = computed(() =>
  store.multiStrategyResult ? gradePortfolio(store.multiStrategyResult) : null,
)

// ── 组合附加分析：组合级 Walk-Forward / 一条龙 / AI 解读 ─────────────────────
// 与单标的/组合回测页同构；按钮在组合结果区按需触发（复用最近一次
// 组合回测的 items/cash，区间保持不变——检验的是"这组配置"的稳定性）。

function multiComboRequest() {
  return { items: lastComboItems.value, cash: lastComboCash.value }
}

async function onComboWf() {
  if (lastComboItems.value.length === 0) return
  await store.runMultiStrategyWalkforward(multiComboRequest())
}

async function onComboEvaluate() {
  if (lastComboItems.value.length === 0) return
  await store.runMultiStrategyEvaluate(multiComboRequest())
}

// AI 解读：组合版 Prompt（multi 模式：N 个策略各跑各自的原标的）
const showAiModal = ref(false)

const comboStrategyLabel = computed(() =>
  lastComboItems.value.length > 0
    ? `${lastComboItems.value.length} 策略组合`
    : '策略组合',
)

const aiPromptText = computed(() => {
  if (!store.multiStrategyResult) return ''
  return buildPortfolioAiPrompt({
    stocks: lastComboItems.value.map(
      (it) => `${it.strategy_label || it.strategy}@${it.symbol}`,
    ),
    category: (lastComboItems.value[0]?.category as Category) ?? 'DAY',
    startDate: (lastComboItems.value[0]?.start_date as string) || '',
    endDate: (lastComboItems.value[0]?.end_date as string) || isoToday(),
    strategyLabel: comboStrategyLabel.value,
    params: {},
    cash: lastComboCash.value,
    commission: 0.0003,
    slippage: 0,
    execution: 'next_open',
    result: store.multiStrategyResult,
    mode: 'multi',
    wf: store.multiWfResult,
    evaluate: store.multiEvaluateResult,
    grade: comboGrade.value,
    gradeHint: comboGrade.value ? GRADE_META[comboGrade.value.grade].hint : undefined,
  })
})

/** 随解读落历史库的策略上下文（历史页「去回测」引导用） */
const aiContext = computed(() => ({
  strategy: 'multi',
  strategy_label: comboStrategyLabel.value,
  kind: 'multi',
  symbol: lastComboItems.value.map((it) => it.symbol).join(','),
  category: (lastComboItems.value[0]?.category as string) || 'DAY',
  params: {},
  start_date: (lastComboItems.value[0]?.start_date as string) || '',
  end_date: isoToday(),
}))
</script>

<template>
  <div class="strategies-view">
    <header class="page-header">
      <div>
        <h2>策略库</h2>
        <p class="subtitle">
          保存你觉得不错的策略，下次直接载入或重跑。共 {{ strategies.length }} 条。
        </p>
      </div>
      <div class="header-actions">
        <button
          v-if="activeTab === 'single'"
          class="primary sm"
          :disabled="selectedStrategies.length === 0 || store.multiStrategyRunning"
          @click="onComboBacktest"
        >
          {{ store.multiStrategyRunning ? '组合回测中…' : `组合回测（${selectedStrategies.length}）` }}
        </button>
        <button
          v-if="activeTab === 'single' && selectedStrategies.length > 0"
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

    <!-- Tab 切换 -->
    <nav class="tabs" role="tablist">
      <button
        role="tab"
        :aria-selected="activeTab === 'single'"
        :class="['tab', { active: activeTab === 'single' }]"
        @click="switchTab('single')"
      >
        单标的<span class="tab-count">{{ singleStrategies.length }}</span>
      </button>
      <button
        role="tab"
        :aria-selected="activeTab === 'combo'"
        :class="['tab', { active: activeTab === 'combo' }]"
        @click="switchTab('combo')"
      >
        组合<span class="tab-count">{{ comboStrategies.length }}</span>
      </button>
    </nav>

    <div v-if="error || store.error" class="error-banner">⚠ {{ error || store.error }}</div>

    <div v-if="!loading && visibleStrategies.length === 0 && !error" class="placeholder">
      <p>{{ activeTab === 'single' ? '还没有保存的单标的策略。' : '还没有保存的组合策略。' }}</p>
      <p class="hint">
        <template v-if="activeTab === 'single'">
          在「单标的回测」跑出满意结果后，点结果区的「保存策略」即可收藏到这里。
          勾选多个单标的策略还能做「组合回测」。
        </template>
        <template v-else>
          勾选多个单标的策略 → 点「组合回测」→ 跑出结果后点「💾 保存为组合」，
          即可在这里看到。下次点「↻ 重跑到今天」即可获取最新策略信号。
        </template>
      </p>
    </div>

    <div v-if="loading && strategies.length === 0" class="placeholder">
      <p>加载中…</p>
    </div>

    <div v-if="visibleStrategies.length" class="card-grid">
      <article
        v-for="s in visibleStrategies"
        :key="s.id"
        class="card"
        :class="{ selected: selectedIds.has(s.id), 'card-multi': s.kind === 'multi' }"
      >
        <div class="card-head">
          <label
            v-if="s.kind !== 'multi'"
            class="select-box"
            :title="s.context?.symbol ? '加入组合回测' : '组合策略暂不支持组合回测'"
          >
            <input
              type="checkbox"
              :checked="selectedIds.has(s.id)"
              :disabled="!s.context?.symbol"
              @change="toggleSelect(s.id)"
            />
          </label>
          <span v-else class="multi-icon" title="多策略组合">🗂</span>
          <span class="kind-badge" :class="s.kind">
            {{ s.kind === 'multi' ? '多策略' : s.kind === 'portfolio' ? '多标的' : '单标的' }}
          </span>
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
            <button
              v-if="s.kind === 'multi'"
              class="rerun-btn sm"
              :disabled="store.multiStrategyRunning"
              @click="onLoadMulti(s)"
            >
              {{ store.multiStrategyRunning ? '重跑中…' : '↻ 重跑到今天' }}
            </button>
            <button v-else class="primary sm" @click="onLoad(s)">载入</button>
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

    <!-- 保存组合弹窗 -->
    <div
      v-if="saveComboOpen"
      class="modal-mask"
      @click.self="closeSaveCombo"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="combo-modal-title"
        class="modal"
        @keydown.esc.prevent="closeSaveCombo"
      >
        <h3 id="combo-modal-title">保存为策略组合</h3>
        <p class="modal-desc">
          将当前 {{ lastComboItems.length }} 个策略的整体配置（策略+参数+标的+资金配比）存为「组合」，
          下次点「↻ 重跑到今天」即可用截至今天的行情算出每个策略的当前信号（持仓/空仓）。
        </p>
        <div class="modal-field">
          <label for="combo-name-input">组合名称</label>
          <input
            id="combo-name-input"
            ref="saveComboNameRef"
            v-model="saveComboName"
            placeholder="如：科技+消费+银行 防守反击组合"
            maxlength="120"
          />
        </div>
        <div class="modal-field">
          <label for="combo-notes-input">备注（可选）</label>
          <textarea
            id="combo-notes-input"
            v-model="saveComboNotes"
            rows="3"
            placeholder="如：牛市跑得好，震荡市待验证"
            maxlength="2000"
          />
        </div>
        <div class="modal-actions">
          <button class="ghost sm" @click="closeSaveCombo">取消</button>
          <button class="primary sm" :disabled="saveComboLoading" @click="submitSaveCombo">
            {{ saveComboLoading ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 多策略组合回测结果（复用组合页图表组件） -->
    <section
      v-if="store.multiStrategyResult || store.multiStrategyRunning"
      ref="comboResultRef"
      class="combo-result"
    >
      <h3 class="combo-title">
        组合回测结果
        <span v-if="store.multiStrategyResult" class="combo-meta">
          · {{ store.multiStrategyResult.total_performance.total_stocks }} 个策略 ·
          总资金 {{ store.multiStrategyResult.total_performance.total_cash.toFixed(0) }}
        </span>
        <span v-if="store.multiStrategyResult && !store.multiStrategyRunning" class="combo-extra-actions">
          <button
            class="save-combo-btn"
            :disabled="store.multiWfRunning"
            title="按全部槽位日期并集切窗，每窗各策略独立回测后合成组合净值，检验跨时段稳定性"
            @click="onComboWf"
          >
            {{ store.multiWfRunning ? 'WF 验证中…' : '🔬 WF 样本外验证' }}
          </button>
          <button
            class="save-combo-btn"
            :disabled="store.multiEvaluateRunning"
            title="组合回测+组合WF+跨策略适配性体检+综合评分+等权买入持有基准对比，一份报告"
            @click="onComboEvaluate"
          >
            {{ store.multiEvaluateRunning ? '评估中…' : '📋 一条龙评估' }}
          </button>
          <button class="save-combo-btn" @click="showAiModal = true">🤖 AI 解读</button>
          <button class="save-combo-btn" @click="openSaveCombo">💾 保存为组合</button>
        </span>
        <button
          v-else-if="store.multiStrategyResult && store.multiStrategyRunning"
          class="save-combo-btn"
          disabled
        >
          💾 保存为组合
        </button>
      </h3>

      <!-- 过拟合警示 -->
      <div v-if="store.multiStrategyResult" class="warn-box overfit">
        ⚠ <strong>过拟合提醒：</strong>组合的历史回测表现优秀，不代表未来一定有效。
        收益可能来自特定时段的市场环境（如某段主升浪），切换到震荡/熊市可能失效。
        把它当作"今日该买该卖"的<strong>参考信号</strong>，而非"未来必涨"的保证。
      </div>

      <div v-if="store.multiStrategyRunning && !store.multiStrategyResult" class="combo-loading">
        组合回测中…（逐个策略取行情 + 回测，请稍候）
      </div>

      <div v-if="store.multiStrategyResult" class="combo-content">
        <div v-if="comboGrade" class="combo-chart-block">
          <h4>组合评级</h4>
          <GradeDetails :result="comboGrade" expanded />
        </div>

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

        <!-- 附加分析：组合级 Walk-Forward（与单标的/组合回测页同构面板） -->
        <div
          v-if="store.multiWfRunning || store.multiWfResult || store.multiWfError"
          class="combo-chart-block"
        >
          <h4>Walk-Forward 样本外验证</h4>
          <p v-if="store.multiWfRunning" class="empty-text">
            验证中…（策略数 × 窗口数 次回测，约需十几秒）
          </p>
          <div v-else-if="store.multiWfError" class="warn-box">
            ⚠ {{ store.multiWfError }}
          </div>
          <WalkForwardPanel v-else-if="store.multiWfResult" :wf="store.multiWfResult" />
        </div>

        <!-- 附加分析：组合级一条龙评估（与单标的/组合回测页同构面板） -->
        <div
          v-if="
            store.multiEvaluateRunning || store.multiEvaluateResult || store.multiEvaluateError
          "
          class="combo-chart-block"
        >
          <h4>一条龙评估</h4>
          <p v-if="store.multiEvaluateRunning" class="empty-text">
            评估中…（组合回测 + 组合WF + 跨策略适配性 + 基准对比，可能需要一两分钟）
          </p>
          <div v-else-if="store.multiEvaluateError" class="warn-box">
            ⚠ {{ store.multiEvaluateError }}
          </div>
          <EvaluatePanel
            v-else-if="store.multiEvaluateResult"
            :report="store.multiEvaluateResult"
            :grade-override="comboGrade"
          />
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
            <span class="holdings-hint">截至回测结束日的策略信号</span>
          </h4>

          <!-- 模型仓位免责水印：与上方过拟合警示条互补，这里只强调"持仓≠你真实账户" -->
          <div class="warn-box disclaimer">
            ⚠ 表中是<strong>模型仓位</strong>（策略说"该持仓"），<strong>不是你真实账户的持仓</strong>。
            基于回测结束日收盘价计算，过夜后可能因新 K 线触发买卖而变化。
          </div>

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
              <tr v-for="h in holdingViews" :key="h.key" :class="h.rowClass">
                <td>{{ h.strategyLabel }}</td>
                <td class="sym">{{ h.symbol }}</td>
                <td>
                  <span class="status-tag" :class="h.statusClass">
                    {{ h.statusLabel }}
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

    <!-- AI 解读 Prompt 对话框（单标的/组合/策略组合通用组件） -->
    <AiInterpretModal
      v-if="showAiModal && store.multiStrategyResult"
      :prompt="aiPromptText"
      :filename="`AI解读_${comboStrategyLabel}.md`"
      :context="aiContext"
      tip="建议先点「WF 样本外验证」「一条龙评估」，跑完再打开此弹窗，数据会一并打包。"
      @close="showAiModal = false"
    />
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

/* Tab 切换条 */
.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 16px;
}
.tab {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border-radius: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: color 0.15s, border-color 0.15s;
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

/* 组合卡片 / multi 视觉差异 */
.card-multi {
  border-color: rgba(245, 158, 11, 0.35);
  background: linear-gradient(180deg, rgba(245, 158, 11, 0.04), var(--bg-panel) 30%);
}
.card-multi:hover {
  border-color: rgba(245, 158, 11, 0.6);
}
.multi-icon {
  font-size: 18px;
  color: #f59e0b;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  width: 16px;
  text-align: center;
}
.kind-badge.multi {
  background: rgba(245, 158, 11, 0.18);
  color: #f59e0b;
}

/* 保存组合按钮（结果区右上） */
.save-combo-btn {
  font-size: 12px;
  padding: 5px 12px;
  margin-left: 12px;
  background: linear-gradient(135deg, #f59e0b, #ea580c);
  border: 1px solid #f59e0b;
  color: #fff;
  font-weight: 600;
  border-radius: var(--radius);
  cursor: pointer;
  vertical-align: middle;
}
.save-combo-btn:hover {
  background: linear-gradient(135deg, #fbbf24, #f59e0b);
}
.save-combo-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
/* 组合结果区附加分析按钮组（WF/一条龙/AI 解读/保存）：内联排列，窄屏可换行 */
.combo-extra-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-left: 10px;
  flex-wrap: wrap;
  vertical-align: middle;
}
.combo-extra-actions .save-combo-btn {
  margin-left: 0;
}

/* 警示条基础类（过拟合 / 免责共享） */
.warn-box {
  padding: 10px 14px;
  border-radius: var(--radius);
  margin-bottom: 12px;
  font-size: 12px;
  line-height: 1.6;
}
.warn-box strong {
  color: #fbbf24;
}
.warn-box.overfit {
  background: rgba(240, 160, 32, 0.1);
  border-left: 3px solid var(--warn);
  color: #f0a020;
  margin-bottom: 14px;
}
.warn-box.disclaimer {
  background: rgba(240, 160, 32, 0.06);
  border: 1px dashed rgba(240, 160, 32, 0.4);
  color: var(--text-muted);
  font-size: 11px;
  padding: 8px 12px;
}

/* 多策略组合卡片的"重跑到今天"按钮：橙色 outline，呼应组合主题色 */
.rerun-btn {
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.5);
  color: #f59e0b;
  font-weight: 600;
  border-radius: var(--radius);
  cursor: pointer;
}
.rerun-btn:hover:not(:disabled) {
  background: rgba(245, 158, 11, 0.2);
  border-color: #f59e0b;
  color: #fbbf24;
}
.rerun-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 持仓三态 */
.status-tag.win {
  background: rgba(24, 160, 88, 0.18);
  color: var(--down);
}
.status-tag.lose {
  background: rgba(240, 160, 32, 0.18);
  color: #f0a020;
}
.status-tag.wait {
  background: var(--border);
  color: var(--text-dim);
}
.holdings-table tr.row-win {
  background: rgba(24, 160, 88, 0.04);
}
.holdings-table tr.row-lose {
  background: rgba(240, 160, 32, 0.05);
}

/* 保存组合弹窗 */
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 20px 22px;
  width: 420px;
  max-width: calc(100vw - 32px);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
}
.modal h3 {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 6px;
}
.modal-desc {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.6;
  margin-bottom: 14px;
}
.modal-field {
  margin-bottom: 12px;
}
.modal-field textarea {
  resize: vertical;
  font-family: inherit;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}
</style>
