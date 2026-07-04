<script setup lang="ts">
// 回测主页面：左配置面板 / 右报告面板。
// 编排：点击「开始回测」→ 自动取行情 → 回测 → 展示 K线+净值+指标+成交。
// 取行情已整合进「开始回测」（不再有单独的取行情按钮）。

import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import EquityChart from '../components/EquityChart.vue'
import KlineChart from '../components/KlineChart.vue'
import MetricTable from '../components/MetricTable.vue'
import StrategyPicker from '../components/StrategyPicker.vue'
import SymbolPicker from '../components/SymbolPicker.vue'
import TradeTable from '../components/TradeTable.vue'
import { formatError, saveStrategy } from '../api'
import type { Category, ExecutionMode } from '../types'
import { useBacktestStore } from '../stores/backtest'

const store = useBacktestStore()
const route = useRoute()

// SymbolPicker 实例引用，用于触发取行情
const symbolPicker = ref<InstanceType<typeof SymbolPicker> | null>(null)

// 镜像 SymbolPicker 的代码/周期/日期，与 SymbolPicker 通过 v-model 双向同步。
// 初始值与 SymbolPicker 默认一致；onMounted 时若 URL query 带了寻优页传来的值则覆盖。
const code = ref('000001')
const category = ref<Category>('DAY')
function isoDaysFromNow(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}
const startDate = ref(isoDaysFromNow(-365 * 3))
const endDate = ref(isoDaysFromNow(0))

// 表单状态（v-model 给子组件）
const strategy = ref('ma_cross')
const params = ref<Record<string, number | string | boolean>>({})
const cash = ref(1000000)
const commission = ref(0.0003)
const slippage = ref(0)
const execution = ref<ExecutionMode>('next_open')

// 成交价模式（精简为 开盘价/收盘价）
const EXECUTIONS: { value: ExecutionMode; label: string }[] = [
  { value: 'next_open', label: '开盘价' },
  { value: 'next_close', label: '收盘价' },
]

onMounted(async () => {
  await store.loadStrategies().catch((e) => {
    store.error = `加载策略列表失败：${e instanceof Error ? e.message : e}`
  })

  // 从 URL query 读取寻优页传来的 strategy + params（跳转自动填充）
  const qStrategy = route.query.strategy as string | undefined
  const qParams = route.query.params as string | undefined
  if (qStrategy) {
    strategy.value = qStrategy
    // 等待 StrategyPicker 的 watch(selectedSchema) 触发完默认值重置后，
    // 再用 query 的 params 覆盖，避免被 watch 重置掉
    await nextTick()
  }
  if (qParams) {
    try {
      params.value = JSON.parse(qParams) as Record<string, number | string | boolean>
    } catch {
      // query 参数解析失败，忽略
    }
  }

  // 从 URL query 回填标的代码 / 周期 / 日期范围（寻优页「查看」跳转带来）。
  // 各字段独立 if 守卫：老书签（只有 strategy/params）仍保持默认值，向后兼容。
  const qSymbol = route.query.symbol as string | undefined
  const qStartDate = route.query.startDate as string | undefined
  const qEndDate = route.query.endDate as string | undefined
  const qCategory = route.query.category as Category | undefined
  if (qSymbol) code.value = qSymbol
  if (qStartDate) startDate.value = qStartDate
  if (qEndDate) endDate.value = qEndDate
  if (qCategory) category.value = qCategory
})

// 取行情 + 回测 串联（点击「开始回测」触发）
async function onRun() {
  store.error = ''
  // 1. 先取行情（SymbolPicker.loadBars 会校验并填充 store.ohlcv）
  const ok = await symbolPicker.value?.loadBars()
  if (!ok) return // 校验/取数失败，错误已在 store.error
  // 2. 再回测
  await store.run({
    strategy: strategy.value,
    params: params.value,
    cash: cash.value,
    commission: commission.value,
    slippage: slippage.value,
    execution: execution.value,
  })
}

// ── 保存策略（把当前结果 + 配置 + 上下文存进策略库）──────────────────────────
const showSaveForm = ref(false)
const saving = ref(false)
const saveName = ref('')
const saveTags = ref('')
const saveNotes = ref('')
const saveMsg = ref('') // 保存后提示（成功/失败）

const strategyLabel = computed(
  () => store.strategies.find((s) => s.name === strategy.value)?.label ?? strategy.value,
)

// 当前股票完整代码（市场:6位），从 SymbolPicker 同步来的 code 是纯数字，
// 需要带上市场前缀。复用 SymbolPicker 内部已经算好的前缀更稳妥——这里简单按
// 交易所规则推断（6 位代码：6/9 开头 SH，其余 SZ；8/4 开头 BJ）。
function fullSymbol(code6: string): string {
  if (/^(6|9)/.test(code6)) return `SH:${code6}`
  if (/^(8|4)/.test(code6)) return `BJ:${code6}`
  return `SZ:${code6}`
}

function openSaveForm() {
  saveName.value = `${strategyLabel.value} · ${code.value}`
  saveTags.value = ''
  saveNotes.value = ''
  saveMsg.value = ''
  showSaveForm.value = true
}

async function onSave() {
  if (!store.result || !saveName.value.trim()) return
  saving.value = true
  saveMsg.value = ''
  try {
    await saveStrategy({
      name: saveName.value.trim(),
      kind: 'single',
      strategy: strategy.value,
      strategy_label: strategyLabel.value,
      params: params.value,
      context: {
        symbol: fullSymbol(code.value),
        category: category.value,
        start_date: startDate.value,
        end_date: endDate.value,
      },
      trade_config: {
        cash: cash.value,
        commission: commission.value,
        min_commission: 5,
        stamp_tax: 0.001,
        slippage: slippage.value,
        execution: execution.value,
      },
      snapshot: {
        total_return: store.result.performance.total_return,
        annual_return: store.result.performance.annual_return,
        max_drawdown: store.result.performance.max_drawdown,
        sharpe: store.result.performance.sharpe,
        win_rate: store.result.performance.win_rate,
        trades_count: store.result.performance.total_trades,
      },
      tags: saveTags.value
        .split(/[,，]/)
        .map((t) => t.trim())
        .filter(Boolean),
      notes: saveNotes.value,
    })
    saveMsg.value = '✓ 已保存到策略库'
    showSaveForm.value = false
  } catch (e) {
    saveMsg.value = `保存失败：${formatError(e)}`
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="backtest-view">
    <!-- 左栏：配置 -->
    <aside class="config-panel">
      <section class="panel-section">
        <h3>行情数据</h3>
        <SymbolPicker
          ref="symbolPicker"
          v-model:code="code"
          v-model:category="category"
          v-model:start-date="startDate"
          v-model:end-date="endDate"
        />
      </section>

      <section class="panel-section">
        <h3>策略</h3>
        <StrategyPicker
          v-if="store.strategies.length"
          :strategies="store.strategies"
          v-model:strategy="strategy"
          v-model:params="params"
        />
        <p v-else class="loading-text">加载策略中…</p>
      </section>

      <section class="panel-section">
        <h3>资金与成本</h3>
        <div class="field">
          <label>初始资金</label>
          <input v-model.number="cash" type="number" min="1000" step="10000" />
        </div>
        <div class="row">
          <div class="field">
            <label>佣金率</label>
            <input v-model.number="commission" type="number" min="0" step="0.0001" />
          </div>
          <div class="field">
            <label>滑点</label>
            <input v-model.number="slippage" type="number" min="0" step="0.001" />
          </div>
        </div>
        <div class="field">
          <label>成交价</label>
          <select v-model="execution">
            <option v-for="e in EXECUTIONS" :key="e.value" :value="e.value">{{ e.label }}</option>
          </select>
        </div>
      </section>

      <button
        class="primary run-btn"
        :disabled="store.running"
        @click="onRun"
      >
        {{ store.running ? '取行情+回测中…' : '开始回测' }}
      </button>
    </aside>

    <!-- 右栏：报告 -->
    <main class="report-panel">
      <div v-if="store.error" class="error-banner">⚠ {{ store.error }}</div>

      <div v-if="!store.result && !store.running && !store.error" class="placeholder">
        <p>输入代码、配置策略后点击「开始回测」（自动取行情）</p>
      </div>

      <div v-if="store.result" class="report-content">
        <div class="result-toolbar">
          <button class="ghost" @click="openSaveForm">💾 保存策略</button>
          <span v-if="saveMsg" class="save-msg">{{ saveMsg }}</span>
        </div>

        <section class="report-section">
          <h3>K线 + 买卖点</h3>
          <KlineChart :bars="store.ohlcv" :trades="store.result.trades" />
        </section>

        <section class="report-section">
          <h3>净值曲线与回撤</h3>
          <EquityChart :equity="store.result.equity_curve" />
        </section>

        <section class="report-section">
          <h3>绩效指标</h3>
          <MetricTable :perf="store.result.performance" />
        </section>

        <section class="report-section">
          <h3>成交记录（{{ store.result.trades.length }} 笔）</h3>
          <TradeTable :trades="store.result.trades" />
        </section>
      </div>
    </main>

    <!-- 保存策略对话框 -->
    <div v-if="showSaveForm" class="modal-overlay" @click.self="showSaveForm = false">
      <div class="modal">
        <h3>保存到策略库</h3>
        <p class="modal-desc">
          将当前策略 + 标的上下文 + 成绩快照存下，下次可在「策略库」载入或重跑。
        </p>
        <div class="field">
          <label>名称</label>
          <input v-model="saveName" type="text" placeholder="给这个策略起个名" />
        </div>
        <div class="field">
          <label>标签（逗号分隔，可选）</label>
          <input v-model="saveTags" type="text" placeholder="如：银行,长线观察" />
        </div>
        <div class="field">
          <label>备注（可选）</label>
          <textarea v-model="saveNotes" rows="2" placeholder="为什么觉得它好？"></textarea>
        </div>
        <div class="modal-summary">
          {{ strategyLabel }} · {{ code }} ·
          {{ store.result ? (store.result.performance.total_return * 100).toFixed(2) + '%' : '' }}
        </div>
        <div class="modal-actions">
          <button class="ghost" :disabled="saving" @click="showSaveForm = false">取消</button>
          <button class="primary" :disabled="saving || !saveName.trim()" @click="onSave">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.backtest-view {
  display: flex;
  height: 100%;
}

/* 左栏配置面板 */
.config-panel {
  width: 320px;
  flex-shrink: 0;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.panel-section {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
.panel-section:last-of-type {
  border-bottom: none;
}
.panel-section h3 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 12px;
}
.loading-text {
  color: var(--text-dim);
  font-size: 12px;
}
.run-btn {
  margin-top: auto;
  width: 100%;
  padding: 10px;
  font-size: 14px;
}

/* 右栏报告面板 */
.report-panel {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-dim);
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
.report-section {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  margin-bottom: 16px;
}
.report-section h3 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 12px;
}

/* 结果工具条 + 保存对话框 */
.result-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.result-toolbar .ghost {
  font-size: 12px;
  padding: 6px 12px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  cursor: pointer;
}
.result-toolbar .ghost:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.save-msg {
  font-size: 12px;
  color: var(--up);
}
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
  width: 380px;
  max-width: 90vw;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.modal h3 {
  font-size: 15px;
  font-weight: 600;
}
.modal-desc {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.5;
}
.modal .field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.modal .field label {
  font-size: 12px;
  color: var(--text-muted);
}
.modal .field input,
.modal .field textarea {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 7px 9px;
  font-size: 13px;
  color: var(--text);
  font-family: inherit;
  resize: vertical;
}
.modal .field textarea {
  font-family: inherit;
}
.modal-summary {
  font-size: 12px;
  color: var(--text-dim);
  font-family: var(--font-mono);
  padding: 8px 10px;
  background: var(--bg);
  border-radius: var(--radius);
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
.modal-actions .ghost {
  font-size: 13px;
  padding: 7px 16px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  cursor: pointer;
}
.modal-actions .primary {
  font-size: 13px;
  padding: 7px 16px;
  cursor: pointer;
}
.modal-actions .primary:disabled,
.modal-actions .ghost:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>
