<script setup lang="ts">
// 回测主页面：左配置面板 / 右报告面板。
// 编排：点击「开始回测」→ 自动取行情 → 回测 → 展示 K线+净值+指标+成交。
// 取行情已整合进「开始回测」（不再有单独的取行情按钮）。

import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import AiInterpretModal from '../components/AiInterpretModal.vue'
import EquityChart from '../components/EquityChart.vue'
import EvaluatePanel from '../components/EvaluatePanel.vue'
import GradeDetails from '../components/GradeDetails.vue'
import KlineChart from '../components/KlineChart.vue'
import MetricTable from '../components/MetricTable.vue'
import StrategyPicker from '../components/StrategyPicker.vue'
import SymbolPicker from '../components/SymbolPicker.vue'
import TradeTable from '../components/TradeTable.vue'
import WalkForwardPanel from '../components/WalkForwardPanel.vue'
import { fetchSymbolName, formatError, saveStrategy } from '../api'
import { detectMarket } from '../market'
import { GRADE_META, gradePerformance } from '../grading'
import { buildAiPrompt } from '../aiPrompt'
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
const startDate = ref('2020-01-06')
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

// 附加分析开关（v1.27）：WF 样本外验证 / 一条龙评估，
// 勾选后随「开始回测」一起提交（与主回测共用同一份内联 OHLCV）。
const wfEnabled = ref(false)
const wfWindows = ref(7)
const evaluateEnabled = ref(false)

// 取行情 + 回测 串联（点击「开始回测」触发）
async function onRun() {
  store.error = ''
  store.clearExtraAnalysis()
  // 1. 先取行情（SymbolPicker.loadBars 会校验并填充 store.ohlcv）
  const ok = await symbolPicker.value?.loadBars()
  if (!ok) return // 校验/取数失败，错误已在 store.error
  // 2. 再回测
  const req = {
    strategy: strategy.value,
    params: params.value,
    cash: cash.value,
    commission: commission.value,
    slippage: slippage.value,
    execution: execution.value,
  }
  await store.run(req)
  // 3. 附加分析：勾选的 WF / 一条龙评估并行跑（互不阻塞，各自有独立错误提示）
  if (!store.result) return
  const jobs: Promise<void>[] = []
  if (wfEnabled.value) jobs.push(store.runWalkforward(req, wfWindows.value))
  if (evaluateEnabled.value) jobs.push(store.runEvaluate(req))
  await Promise.allSettled(jobs)
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

// 评级：基于完整 Performance，6 维度评分 + 一票否决。
// total_return 不直接计入评分（只通过卡玛/夏普间接体现），
// 体现「哪怕近期收益率高，长期风险大也该低评」的产品诉求。
const grade = computed(() =>
  store.result ? gradePerformance(store.result.performance) : null,
)

// 当前股票完整代码（市场:6位），从 SymbolPicker 同步来的 code 是纯数字，
// 需要带上市场前缀。复用 market.ts 的 detectMarket（与 SymbolPicker /
// StocksPicker 同一套规则），避免分叉导致 ETF/基金（5 开头）等被错判市场。
function fullSymbol(code6: string): string {
  return `${detectMarket(code6)}:${code6}`
}

// 当前标的的股票名（打开保存弹窗时异步查询，挂到名称/摘要后；查不到则为空）
const symbolName = ref('')

async function openSaveForm() {
  const baseName = `${strategyLabel.value} · ${code.value}`
  saveName.value = baseName
  saveTags.value = ''
  saveNotes.value = ''
  saveMsg.value = ''
  symbolName.value = ''
  showSaveForm.value = true
  // 查询股票中文名，拼成「策略 · 代码 · 股票名」（如 双均线交叉 · 002163 · 海南发展）。
  // 查询失败/市场不支持（如 BJ）时保持原名称；若用户在等待期间已手动改名则不打扰。
  const name = await fetchSymbolName(detectMarket(code.value), code.value)
  if (!name) return
  symbolName.value = name
  if (saveName.value === baseName) saveName.value = `${baseName} · ${name}`
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

// ── AI 解读 Prompt（把当前报告组装成提示词，发给任意 LLM 解读）──────────────
// 弹窗交互（复制/下载/直接解读）抽在 AiInterpretModal 通用组件里，
// 与组合回测页共用；这里只负责实时组装 Prompt 与策略上下文。
const showAiModal = ref(false)

/** 实时组装：附加分析（WF/评估）跑完后内容自动变全 */
const aiPromptText = computed(() => {
  if (!store.result) return ''
  return buildAiPrompt({
    symbol: fullSymbol(code.value),
    category: category.value,
    startDate: startDate.value,
    endDate: endDate.value,
    bars: store.ohlcv.length,
    strategyLabel: strategyLabel.value,
    params: params.value,
    cash: cash.value,
    commission: commission.value,
    slippage: slippage.value,
    execution: execution.value,
    result: store.result,
    wf: store.wfResult,
    evaluate: store.evaluateResult,
    grade: grade.value,
    gradeHint: grade.value ? GRADE_META[grade.value.grade].hint : undefined,
  })
})

/** 随解读落历史库的策略上下文（AI 解读历史页「去回测」引导用） */
const aiContext = computed(() => ({
  strategy: strategy.value,
  strategy_label: strategyLabel.value,
  symbol: code.value,
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

      <section class="panel-section">
        <h3>附加分析</h3>
        <div class="check-row">
          <label
            class="check-label"
            title="把时间轴切 7 窗独立回测，检验跨时段稳定性（每窗独立开仓）"
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
            title="回测+WF+适配性体检+综合评分+买入持有基准对比，一份报告"
          >
            <input v-model="evaluateEnabled" type="checkbox" />
            <span>一条龙评估</span>
          </label>
        </div>
        <p class="extra-hint">勾选后随「开始回测」自动附加运行</p>
      </section>

      <button
        class="primary run-btn"
        :disabled="store.running || store.wfRunning || store.evaluateRunning"
        @click="onRun"
      >
        {{ store.running || store.wfRunning || store.evaluateRunning ? '取行情+回测中…' : '开始回测' }}
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
          <button class="ghost" @click="showAiModal = true">🤖 AI 解读</button>
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

        <section v-if="grade" class="report-section">
          <h3>评级</h3>
          <GradeDetails :result="grade" expanded />
        </section>

        <!-- 附加分析：WF 样本外验证（v1.27） -->
        <section
          v-if="store.wfRunning || store.wfResult || store.wfError"
          class="report-section"
        >
          <h3>Walk-Forward 样本外验证</h3>
          <p v-if="store.wfRunning" class="loading-text">验证中…（逐窗独立回测，约需数秒）</p>
          <div v-else-if="store.wfError" class="error-banner">⚠ {{ store.wfError }}</div>
          <WalkForwardPanel v-else-if="store.wfResult" :wf="store.wfResult" />
        </section>

        <!-- 附加分析：一条龙评估（v1.27） -->
        <section
          v-if="store.evaluateRunning || store.evaluateResult || store.evaluateError"
          class="report-section"
        >
          <h3>一条龙评估</h3>
          <p v-if="store.evaluateRunning" class="loading-text">
            评估中…（回测 + WF + 适配性 + 基准对比，约需数秒）
          </p>
          <div v-else-if="store.evaluateError" class="error-banner">⚠ {{ store.evaluateError }}</div>
          <EvaluatePanel v-else-if="store.evaluateResult" :report="store.evaluateResult" />
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
          {{ strategyLabel }} · {{ code }}{{ symbolName ? ` · ${symbolName}` : '' }} ·
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

    <!-- AI 解读 Prompt 对话框（单标的/组合通用组件） -->
    <AiInterpretModal
      v-if="showAiModal && store.result"
      :prompt="aiPromptText"
      :filename="`AI解读_${code}_${strategy}.md`"
      :context="aiContext"
      :tip="aiTip"
      @close="showAiModal = false"
    />
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
/* 附加分析开关：勾选框靠左、文字单行不折行，窗口数同行跟排 */
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
  margin-bottom: 0; /* 覆盖全局 label 的 margin-bottom: 4px */
  font-size: 12px;
  color: var(--text);
  cursor: pointer;
  white-space: nowrap; /* 文字不折行 */
}
.check-label input[type='checkbox'] {
  width: auto; /* 覆盖全局 input{width:100%}——复选框被撑满整行才是折行根因 */
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
