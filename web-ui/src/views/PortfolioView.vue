<script setup lang="ts">
// 组合回测主页面：左配置（多标的 + 策略 + 日期 + 附加分析）/ 右报告
// （组合净值 + 完整绩效指标 + 各标的对比 + 附加分析 WF/一条龙 + 成交明细 + AI 解读）。
// 附加分析与单标的回测页（BacktestView）同构：勾选后随「开始组合回测」并行运行。

import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import AiInterpretModal from '../components/AiInterpretModal.vue'
import EquityChart from '../components/EquityChart.vue'
import EvaluatePanel from '../components/EvaluatePanel.vue'
import GradeDetails from '../components/GradeDetails.vue'
import MetricTable from '../components/MetricTable.vue'
import PortfolioCompareChart from '../components/PortfolioCompareChart.vue'
import PortfolioSummaryTable from '../components/PortfolioSummaryTable.vue'
import StocksPicker from '../components/StocksPicker.vue'
import StrategyPicker from '../components/StrategyPicker.vue'
import TradeTable from '../components/TradeTable.vue'
import WalkForwardPanel from '../components/WalkForwardPanel.vue'
import { formatError, saveStrategy } from '../api'
import { buildPortfolioAiPrompt } from '../aiPrompt'
import { GRADE_META, gradePortfolio } from '../grading'
import type { Category, ExecutionMode, PortfolioTrade } from '../types'
import { useBacktestStore } from '../stores/backtest'

const store = useBacktestStore()
const route = useRoute()

const stocks = ref<string[]>(['SZ:000001', 'SH:600519'])
const strategy = ref('ma_cross')
const params = ref<Record<string, number | string | boolean>>({})
const cash = ref(1000000)
const category = ref<Category>('DAY')
const execution = ref<ExecutionMode>('next_open')

// 成交价模式（精简为 开盘价/收盘价）
const EXECUTIONS: { value: ExecutionMode; label: string }[] = [
  { value: 'next_open', label: '开盘价' },
  { value: 'next_close', label: '收盘价' },
]
const CATEGORIES: Category[] = ['DAY', 'WEEK', 'MONTH', 'MIN_5', 'MIN_15', 'MIN_30', 'MIN_60', 'MIN_120']

// 日期默认（复用单标的逻辑）
function isoDaysFromNow(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}
const startDate = ref('2020-01-06')
const endDate = ref(isoDaysFromNow(0))

// 附加分析开关（与单标的回测页同构）：组合级 WF / 一条龙评估
const wfEnabled = ref(false)
const wfWindows = ref(7)
const evaluateEnabled = ref(false)

onMounted(async () => {
  store.loadStrategies().catch((e) => {
    store.error = `加载策略列表失败：${e instanceof Error ? e.message : e}`
  })

  // 从 URL query 回填（策略库「载入」组合策略跳转带来）
  const qStrategy = route.query.strategy as string | undefined
  const qParams = route.query.params as string | undefined
  const qStocks = route.query.stocks as string | undefined
  const qStartDate = route.query.startDate as string | undefined
  const qEndDate = route.query.endDate as string | undefined
  const qCategory = route.query.category as Category | undefined
  if (qStrategy) {
    strategy.value = qStrategy
    await nextTick()
  }
  if (qParams) {
    try {
      params.value = JSON.parse(qParams) as Record<string, number | string | boolean>
    } catch {
      // 解析失败忽略
    }
  }
  if (qStocks) {
    stocks.value = qStocks
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
  }
  if (qStartDate) startDate.value = qStartDate
  if (qEndDate) endDate.value = qEndDate
  if (qCategory) category.value = qCategory
})

function currentRequest() {
  return {
    strategy: strategy.value,
    params: params.value,
    cash: cash.value,
    execution: execution.value,
    stocks: stocks.value,
    category: category.value,
    start_date: startDate.value,
    end_date: endDate.value,
  }
}

async function onRun() {
  store.error = ''
  store.clearPortfolioExtraAnalysis()
  // 1. 主组合回测（后端返回完整 25 项指标 + grade/score）
  await store.runPortfolio(currentRequest())
  // 2. 附加分析：勾选的组合级 WF / 一条龙并行跑（互不阻塞，各自独立错误提示）
  if (!store.portfolioResult) return
  const jobs: Promise<void>[] = []
  if (wfEnabled.value) jobs.push(store.runPortfolioWalkforward(currentRequest(), wfWindows.value))
  if (evaluateEnabled.value) jobs.push(store.runPortfolioEvaluate(currentRequest()))
  await Promise.allSettled(jobs)
}

// ── 保存策略（把当前组合结果 + 配置 + 上下文存进策略库）──────────────────────
const showSaveForm = ref(false)
const saving = ref(false)
const saveName = ref('')
const saveTags = ref('')
const saveNotes = ref('')
const saveMsg = ref('')

const strategyLabel = computed(
  () => store.strategies.find((s) => s.name === strategy.value)?.label ?? strategy.value,
)

// 组合评级：从 combined_equity 重算夏普/卡玛/波动率等（组合级 5 维度口径，
// 与后端 grade_portfolio_equity 一致）。净值点数过少（< 60 个交易日）视为样本不足。
const grade = computed(() =>
  store.portfolioResult ? gradePortfolio(store.portfolioResult) : null,
)

function openSaveForm() {
  saveName.value = `${strategyLabel.value} · 组合${stocks.value.length}只`
  saveTags.value = ''
  saveNotes.value = ''
  saveMsg.value = ''
  showSaveForm.value = true
}

async function onSave() {
  if (!store.portfolioResult || !saveName.value.trim()) return
  saving.value = true
  saveMsg.value = ''
  try {
    const perf = store.portfolioResult.total_performance
    await saveStrategy({
      name: saveName.value.trim(),
      kind: 'portfolio',
      strategy: strategy.value,
      strategy_label: strategyLabel.value,
      params: params.value,
      context: {
        stocks: stocks.value,
        category: category.value,
        start_date: startDate.value,
        end_date: endDate.value,
      },
      trade_config: {
        cash: cash.value,
        execution: execution.value,
      },
      snapshot: {
        total_return: perf.total_return,
        annual_return: perf.annual_return,
        total_stocks: perf.total_stocks,
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

// ── AI 解读（与单标的回测页共用 AiInterpretModal）────────────────────────────
const showAiModal = ref(false)

const aiPromptText = computed(() => {
  if (!store.portfolioResult) return ''
  return buildPortfolioAiPrompt({
    stocks: stocks.value,
    category: category.value,
    startDate: startDate.value,
    endDate: endDate.value,
    strategyLabel: strategyLabel.value,
    params: params.value,
    cash: cash.value,
    commission: 0.0003,
    slippage: 0,
    execution: execution.value,
    result: store.portfolioResult,
    wf: store.portfolioWfResult,
    evaluate: store.portfolioEvaluateResult,
    grade: grade.value,
    gradeHint: grade.value ? GRADE_META[grade.value.grade].hint : undefined,
  })
})

/** 随解读落历史库的策略上下文（历史页「去回测」引导用） */
const aiContext = computed(() => ({
  strategy: strategy.value,
  strategy_label: strategyLabel.value,
  kind: 'portfolio',
  symbol: stocks.value.join(','),
  category: category.value,
  params: { ...params.value },
  start_date: startDate.value,
  end_date: endDate.value,
}))

const aiTip = computed(() =>
  wfEnabled.value || evaluateEnabled.value
    ? '建议等附加分析跑完再发，Walk-Forward / 一条龙评估的数据会一并打包。'
    : undefined,
)

// ── 组合成交明细（各标的汇总，按时间倒序）────────────────────────────────────
const TRADES_SHOW_LIMIT = 200
const portfolioTrades = computed<PortfolioTrade[]>(() => {
  const r = store.portfolioResult
  if (!r) return []
  // 优先用后端汇总的成交表；老结果无该字段时从 individual_results 客户端汇总
  const rows: PortfolioTrade[] = r.trades
    ? [...r.trades]
    : Object.entries(r.individual_results).flatMap(([symbol, res]) =>
        res.trades.map((t) => ({ ...t, symbol })),
      )
  return rows.sort((a, b) => String(b.datetime).localeCompare(String(a.datetime)))
})
</script>

<template>
  <div class="portfolio-view">
    <aside class="config-panel">
      <section class="panel-section">
        <h3>标的列表</h3>
        <StocksPicker v-model="stocks" />
      </section>

      <section class="panel-section">
        <h3>策略</h3>
        <StrategyPicker
          v-if="store.strategies.length"
          v-model:strategy="strategy"
          v-model:params="params"
          :strategies="store.strategies"
        />
        <p v-else class="loading-text">加载策略中…</p>
      </section>

      <section class="panel-section">
        <h3>周期与日期</h3>
        <div class="field">
          <label>周期</label>
          <select v-model="category">
            <option v-for="c in CATEGORIES" :key="c" :value="c">{{ c }}</option>
          </select>
        </div>
        <div class="row">
          <div class="field">
            <label>开始</label>
            <input v-model="startDate" type="date" />
          </div>
          <div class="field">
            <label>结束</label>
            <input v-model="endDate" type="date" />
          </div>
        </div>
      </section>

      <section class="panel-section">
        <h3>资金</h3>
        <div class="field">
          <label>组合总资金</label>
          <input v-model.number="cash" type="number" min="1000" step="10000" />
        </div>
        <div class="field">
          <label>成交价</label>
          <select v-model="execution">
            <option v-for="e in EXECUTIONS" :key="e.value" :value="e.value">{{ e.label }}</option>
          </select>
        </div>
      </section>

      <section class="panel-section">
        <h3>附加分析</h3>
        <div class="check-row">
          <label
            class="check-label"
            title="按全部标的日期并集切窗，每窗各标的独立回测后合成组合净值，检验跨时段稳定性"
          >
            <input v-model="wfEnabled" type="checkbox" />
            <span>Walk-Forward 样本外验证</span>
          </label>
          <span v-if="wfEnabled" class="wf-windows">
            窗口数
            <input v-model.number="wfWindows" type="number" min="2" max="12" step="1" />
          </span>
        </div>
        <div class="check-row">
          <label
            class="check-label"
            title="组合回测+组合WF+跨标的适配性体检+综合评分+等权买入持有基准对比，一份报告"
          >
            <input v-model="evaluateEnabled" type="checkbox" />
            <span>一条龙评估</span>
          </label>
        </div>
        <p class="extra-hint">勾选后随「开始组合回测」自动附加运行（标的越多越慢）</p>
      </section>

      <button
        class="primary run-btn"
        :disabled="
          store.portfolioRunning || store.portfolioWfRunning || store.portfolioEvaluateRunning || stocks.length === 0
        "
        @click="onRun"
      >
        {{
          store.portfolioRunning || store.portfolioWfRunning || store.portfolioEvaluateRunning
            ? '组合回测中…'
            : '开始组合回测'
        }}
      </button>
    </aside>

    <main class="report-panel">
      <div v-if="store.error" class="error-banner">⚠ {{ store.error }}</div>

      <div
        v-if="!store.portfolioResult && !store.portfolioRunning && !store.error"
        class="placeholder"
      >
        <p>添加多只标的，选择策略后点击「开始组合回测」</p>
      </div>

      <div v-if="store.portfolioResult" class="report-content">
        <div class="result-toolbar">
          <button class="ghost" @click="openSaveForm">💾 保存策略</button>
          <button class="ghost" @click="showAiModal = true">🤖 AI 解读</button>
          <span v-if="saveMsg" class="save-msg">{{ saveMsg }}</span>
        </div>

        <section v-if="grade" class="report-section">
          <h3>组合评级</h3>
          <GradeDetails :result="grade" expanded />
        </section>

        <section class="report-section">
          <h3>组合整体绩效</h3>
          <div class="perf-summary">
            <div class="perf-item">
              <span class="label">组合总收益</span>
              <span
                class="value"
                :class="store.portfolioResult.total_performance.total_return > 0 ? 'pos' : 'neg'"
              >
                {{ (store.portfolioResult.total_performance.total_return * 100).toFixed(2) }}%
              </span>
            </div>
            <div class="perf-item">
              <span class="label">年化收益</span>
              <span
                class="value"
                :class="store.portfolioResult.total_performance.annual_return > 0 ? 'pos' : 'neg'"
              >
                {{ (store.portfolioResult.total_performance.annual_return * 100).toFixed(2) }}%
              </span>
            </div>
            <div class="perf-item">
              <span class="label">标的数量</span>
              <span class="value">{{ store.portfolioResult.total_performance.total_stocks }}</span>
            </div>
            <div class="perf-item">
              <span class="label">组合总资金</span>
              <span class="value">{{ store.portfolioResult.total_performance.total_cash.toFixed(0) }}</span>
            </div>
          </div>
        </section>

        <!-- 附加分析：组合级 Walk-Forward（v1.31，与单标的同构面板） -->
        <section
          v-if="store.portfolioWfRunning || store.portfolioWfResult || store.portfolioWfError"
          class="report-section"
        >
          <h3>Walk-Forward 样本外验证</h3>
          <p v-if="store.portfolioWfRunning" class="loading-text">
            验证中…（标的数 × 窗口数 次回测，约需十几秒）
          </p>
          <div v-else-if="store.portfolioWfError" class="error-banner">
            ⚠ {{ store.portfolioWfError }}
          </div>
          <WalkForwardPanel v-else-if="store.portfolioWfResult" :wf="store.portfolioWfResult" />
        </section>

        <!-- 附加分析：组合级一条龙评估（v1.31，与单标的同构面板） -->
        <section
          v-if="
            store.portfolioEvaluateRunning || store.portfolioEvaluateResult || store.portfolioEvaluateError
          "
          class="report-section"
        >
          <h3>一条龙评估</h3>
          <p v-if="store.portfolioEvaluateRunning" class="loading-text">
            评估中…（组合回测 + 组合WF + 跨标的适配性 + 基准对比，可能需要一两分钟）
          </p>
          <div v-else-if="store.portfolioEvaluateError" class="error-banner">
            ⚠ {{ store.portfolioEvaluateError }}
          </div>
          <EvaluatePanel
            v-else-if="store.portfolioEvaluateResult"
            :report="store.portfolioEvaluateResult"
            :grade-override="grade"
          />
        </section>

        <section class="report-section">
          <h3>组合净值曲线</h3>
          <EquityChart :equity="store.portfolioResult.combined_equity" />
        </section>

        <section class="report-section">
          <h3>组合绩效指标</h3>
          <MetricTable :perf="store.portfolioResult.total_performance" />
        </section>

        <section class="report-section">
          <h3>各标的绩效对比</h3>
          <PortfolioSummaryTable
            :results="store.portfolioResult.individual_results"
            :allocation="store.portfolioResult.equity_allocation"
          />
        </section>

        <section class="report-section">
          <h3>各标的净值叠加（归一化）</h3>
          <PortfolioCompareChart :results="store.portfolioResult.individual_results" />
        </section>

        <section class="report-section">
          <h3>组合成交明细（{{ portfolioTrades.length }} 笔，按时间倒序）</h3>
          <p v-if="portfolioTrades.length > TRADES_SHOW_LIMIT" class="loading-text">
            仅显示最近 {{ TRADES_SHOW_LIMIT }} 笔，导出请用「对比分析」页的任务导出
          </p>
          <TradeTable
            :trades="portfolioTrades.slice(0, TRADES_SHOW_LIMIT)"
            show-symbol
          />
        </section>
      </div>
    </main>

    <!-- 保存策略对话框 -->
    <div v-if="showSaveForm" class="modal-overlay" @click.self="showSaveForm = false">
      <div class="modal">
        <h3>保存到策略库</h3>
        <p class="modal-desc">
          将当前组合策略 + 标的列表 + 成绩快照存下，下次可在「策略库」载入或重跑。
        </p>
        <div class="field">
          <label>名称</label>
          <input v-model="saveName" type="text" placeholder="给这个组合策略起个名" />
        </div>
        <div class="field">
          <label>标签（逗号分隔，可选）</label>
          <input v-model="saveTags" type="text" placeholder="如：消费,长线观察" />
        </div>
        <div class="field">
          <label>备注（可选）</label>
          <textarea v-model="saveNotes" rows="2" placeholder="为什么觉得它好？"></textarea>
        </div>
        <div class="modal-summary">
          {{ strategyLabel }} · {{ stocks.length }} 只 ·
          {{
            store.portfolioResult
              ? (store.portfolioResult.total_performance.total_return * 100).toFixed(2) + '%'
              : ''
          }}
        </div>
        <div class="modal-actions">
          <button class="ghost" :disabled="saving" @click="showSaveForm = false">取消</button>
          <button class="primary" :disabled="saving || !saveName.trim()" @click="onSave">
            {{ saving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- AI 解读 Prompt 对话框（单标的/组合通用组件） -->
    <AiInterpretModal
      v-if="showAiModal && store.portfolioResult"
      :prompt="aiPromptText"
      :filename="`AI解读_组合${stocks.length}只_${strategy}.md`"
      :context="aiContext"
      :tip="aiTip"
      @close="showAiModal = false"
    />
  </div>
</template>

<style scoped>
.portfolio-view {
  display: flex;
  height: 100%;
}
.config-panel {
  width: 320px;
  flex-shrink: 0;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  padding: 16px;
  overflow-y: auto;
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
  margin-bottom: 12px;
}
.loading-text {
  color: var(--text-dim);
  font-size: 12px;
}
/* 附加分析开关：勾选框靠左、文字单行不折行，窗口数同行跟排（与回测页一致） */
.check-row {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: 6px;
  margin-bottom: 8px;
  min-width: 0;
}
.check-label {
  display: inline-flex; /* 覆盖全局 label { display: block } */
  align-items: center;
  gap: 6px;
  margin-bottom: 0;
  font-size: 12px;
  color: var(--text);
  cursor: pointer;
  white-space: nowrap;
}
.check-label input[type='checkbox'] {
  width: auto;
  flex-shrink: 0;
  margin: 0;
  accent-color: var(--accent, #4a9eff);
}
.wf-windows {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-dim);
  white-space: nowrap;
}
.wf-windows input {
  width: 44px;
  padding: 3px 6px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 12px;
  color: var(--text);
}
.extra-hint {
  font-size: 11px;
  color: var(--text-dim);
  margin: 2px 0 0;
}
.run-btn {
  width: 100%;
  padding: 10px;
  font-size: 14px;
}
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
.perf-summary {
  display: flex;
  gap: 32px;
  flex-wrap: wrap;
}
.perf-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.perf-item .label {
  font-size: 12px;
  color: var(--text-dim);
}
.perf-item .value {
  font-size: 20px;
  font-weight: 600;
  font-family: var(--font-mono);
}
.pos {
  color: var(--up);
}
.neg {
  color: var(--down);
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
