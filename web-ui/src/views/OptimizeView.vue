<script setup lang="ts">
// 参数寻优主页面：左配置（选标的 + 策略 + 寻优参数）/ 右报告（排名表 + 热力图）。
// 取行情已整合进「开始寻优」。另有「一键寻优所有策略」：用各策略预设网格逐策略寻优再全局排名。

import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import GradeBadge from '../components/GradeBadge.vue'
import OptimizeHeatmap from '../components/OptimizeHeatmap.vue'
import OptimizeResultTable from '../components/OptimizeResultTable.vue'
import ParamGridPicker from '../components/ParamGridPicker.vue'
import SymbolPicker from '../components/SymbolPicker.vue'
import { gradeGridPoint } from '../grading'
import type { GradeResult } from '../grading'
import type { Category, ExecutionMode } from '../types'
import { useBacktestStore } from '../stores/backtest'

const store = useBacktestStore()
const router = useRouter()

// SymbolPicker 实例引用，用于触发取行情
const symbolPicker = ref<InstanceType<typeof SymbolPicker> | null>(null)

// 镜像 SymbolPicker 的代码/周期/日期，用于「查看」跳转时拼进 URL query。
// 与 SymbolPicker 通过 v-model 双向同步，初始值与 SymbolPicker 默认一致。
const code = ref('000001')
const category = ref<Category>('DAY')
function isoDaysFromNow(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}
const startDate = ref('2020-01-06')
const endDate = ref(isoDaysFromNow(0))

const strategy = ref('ma_cross')
const paramGrid = ref<Record<string, Array<number | string>>>({})
const cash = ref(1000000)
const execution = ref<ExecutionMode>('next_open')
// 成交价模式（精简为 开盘价/收盘价）
const EXECUTIONS: { value: ExecutionMode; label: string }[] = [
  { value: 'next_open', label: '开盘价' },
  { value: 'next_close', label: '收盘价' },
]

const selectedStrategy = computed(
  () => store.strategies.find((s) => s.name === strategy.value) ?? null,
)

onMounted(() => {
  store.loadStrategies().catch((e) => {
    store.error = `加载策略列表失败：${e instanceof Error ? e.message : e}`
  })
})

// 网格点数（前端预校验，提示用户）
const gridPoints = computed(() => {
  const sizes = Object.values(paramGrid.value).map((v) => v.length)
  return sizes.reduce((a, b) => a * b, 1)
})

// 取行情（点击「开始寻优」时触发）→ 寻优
async function onRun() {
  store.error = ''
  // 1. 先取行情
  const ok = await symbolPicker.value?.loadBars()
  if (!ok) return
  // 2. 校验寻优参数
  if (Object.keys(paramGrid.value).length === 0) {
    store.error = '请勾选至少 1 个参数并填入取值'
    return
  }
  if (gridPoints.value > 200) {
    store.error = `网格点数 ${gridPoints.value} 超过上限 200`
    return
  }
  // 3. 寻优
  await store.runOptimize({
    strategy: strategy.value,
    param_grid: paramGrid.value,
    cash: cash.value,
    execution: execution.value,
    ohlcv: store.ohlcv,
  })
}

// 一键寻优所有策略：取行情 → 全策略预设网格寻优 → 全局排名
async function onRunAll() {
  store.error = ''
  // 1. 先取行情
  const ok = await symbolPicker.value?.loadBars()
  if (!ok) return
  // 2. 一键寻优
  await store.runOptimizeAll({
    cash: cash.value,
    execution: execution.value,
    ohlcv: store.ohlcv,
  })
}

/** 「查看」跳转时，把当前标的 + 周期 + 日期范围一并塞进 query，
 * 让回测页能完整复现寻优时的行情（而非只带策略参数）。 */
function buildBacktestQuery(strategyName: string, params: Record<string, number | string>) {
  return {
    strategy: strategyName,
    params: JSON.stringify(params),
    symbol: code.value,
    startDate: startDate.value,
    endDate: endDate.value,
    category: category.value,
  }
}

// 点击排名表「查看」→ 跳转单标的页用该参数回测
function onViewParams(params: Record<string, number | string>) {
  // 通过 query 传递参数，单标的页接收后自动填充
  router.push({ path: '/', query: buildBacktestQuery(strategy.value, params) })
}

// 一键寻优结果点击「查看」→ 跳转单标的页用该策略 + 参数回测
function onViewAll(strategyName: string, params: Record<string, number | string>) {
  router.push({ path: '/', query: buildBacktestQuery(strategyName, params) })
}

function pct(v: number | null | undefined): string {
  return v !== null && v !== undefined && Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : '-'
}
function num(v: number | null | undefined, d = 2): string {
  return v !== null && v !== undefined && Number.isFinite(v) ? v.toFixed(d) : '-'
}

// 寻优评级：4 维度降级版（夏普30%/回撤28%/胜率22%/利润因子20%）。
// 各网格点交易数独立判断「样本不足」否决。
const bestGrade = computed<GradeResult | null>(() =>
  store.optimizeResult?.best ? gradeGridPoint(store.optimizeResult.best) : null,
)
// 一键寻优全局最佳评级
const bestAllGrade = computed<GradeResult | null>(() =>
  store.optimizeAllResult?.best ? gradeGridPoint(store.optimizeAllResult.best) : null,
)
// 一键寻优排名表每行的评级（按需计算，避免大表全量计算）
const rankingGrades = computed<GradeResult[]>(() =>
  (store.optimizeAllResult?.ranking ?? []).map((r) => gradeGridPoint(r)),
)
</script>

<template>
  <div class="optimize-view">
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
        <div class="field">
          <select v-model="strategy">
            <option v-for="s in store.strategies" :key="s.name" :value="s.name">
              {{ s.label }}（{{ s.name }}）
            </option>
          </select>
        </div>
      </section>

      <section class="panel-section">
        <h3>寻优参数</h3>
        <ParamGridPicker v-model="paramGrid" :strategy="selectedStrategy" />
      </section>

      <section class="panel-section">
        <h3>资金</h3>
        <div class="field">
          <label>初始资金</label>
          <input v-model.number="cash" type="number" min="1000" step="10000" />
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
        :disabled="store.optimizeRunning || store.optimizeAllRunning"
        @click="onRun"
      >
        {{ store.optimizeRunning ? '取行情+寻优中…' : '开始寻优' }}
      </button>
      <button
        class="run-btn"
        :disabled="store.optimizeRunning || store.optimizeAllRunning"
        @click="onRunAll"
      >
        {{ store.optimizeAllRunning ? '一键寻优所有策略中…' : '一键寻优所有策略' }}
      </button>
    </aside>

    <main class="report-panel">
      <div v-if="store.error" class="error-banner">⚠ {{ store.error }}</div>

      <div
        v-if="!store.optimizeResult && !store.optimizeAllResult && !store.optimizeRunning && !store.optimizeAllRunning && !store.error"
        class="placeholder"
      >
        <p>选标的 → 选策略 → 勾选寻优参数 → 开始寻优；或点「一键寻优所有策略」</p>
      </div>

      <!-- 单策略寻优结果 -->
      <div v-if="store.optimizeResult" class="report-content">
        <section class="report-section">
          <h3>最优结果</h3>
          <div v-if="store.optimizeResult.best" class="best-summary">
            <GradeBadge v-if="bestGrade" :result="bestGrade" size="md" />
            <span class="best-params">{{ JSON.stringify(store.optimizeResult.best.params) }}</span>
            <span class="best-return pos">
              {{ (store.optimizeResult.best.total_return! * 100).toFixed(2) }}%
            </span>
            <span class="best-meta">
              夏普 {{ store.optimizeResult.best.sharpe?.toFixed(2) }} · 回撤
              {{ (store.optimizeResult.best.max_drawdown! * 100).toFixed(2) }}%
            </span>
          </div>
        </section>

        <section v-if="store.optimizeResult.heatmap" class="report-section">
          <h3>参数热力图（{{ store.optimizeResult.heatmap.x_name }} × {{ store.optimizeResult.heatmap.y_name }}）</h3>
          <OptimizeHeatmap :heatmap="store.optimizeResult.heatmap" />
        </section>

        <section class="report-section">
          <h3>网格点排名（{{ store.optimizeResult.results.length }} 个）</h3>
          <OptimizeResultTable
            :results="store.optimizeResult.results"
            :best-index="0"
            @select="onViewParams"
          />
        </section>
      </div>

      <!-- 一键寻优所有策略结果 -->
      <div v-if="store.optimizeAllResult" class="report-content">
        <section class="report-section">
          <h3>全局最佳</h3>
          <div v-if="store.optimizeAllResult.best" class="best-summary">
            <GradeBadge v-if="bestAllGrade" :result="bestAllGrade" size="md" />
            <span class="best-params">
              {{ store.optimizeAllResult.best.strategy_label }}
              {{ JSON.stringify(store.optimizeAllResult.best.params) }}
            </span>
            <span class="best-return pos">
              {{ (store.optimizeAllResult.best.total_return! * 100).toFixed(2) }}%
            </span>
            <span class="best-meta">
              夏普 {{ store.optimizeAllResult.best.sharpe?.toFixed(2) }} · 回撤
              {{ (store.optimizeAllResult.best.max_drawdown! * 100).toFixed(2) }}% · 胜率
              {{ (store.optimizeAllResult.best.win_rate! * 100).toFixed(1) }}%
            </span>
          </div>
          <p class="meta-line">
            共 {{ store.optimizeAllResult.ranking.length }} 个策略有效 ·
            合计 {{ store.optimizeAllResult.total_grid_points }} 网格点
          </p>
        </section>

        <section class="report-section">
          <h3>策略排名（按总收益降序）</h3>
          <table class="opt-table">
            <thead>
              <tr>
                <th>#</th>
                <th>评级</th>
                <th>策略</th>
                <th>参数</th>
                <th class="num">总收益</th>
                <th class="num">夏普</th>
                <th class="num">最大回撤</th>
                <th class="num">交易数</th>
                <th class="num">胜率</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(r, i) in store.optimizeAllResult.ranking"
                :key="r.strategy"
                :class="{ best: i === 0 }"
              >
                <td class="rank">{{ i + 1 }}</td>
                <td class="grade-cell">
                  <GradeBadge
                    v-if="rankingGrades[i]"
                    :result="rankingGrades[i]"
                    size="sm"
                    :show-score="false"
                  />
                </td>
                <td>{{ r.strategy_label }}</td>
                <td class="params">{{ JSON.stringify(r.params) }}</td>
                <td class="num" :class="r.total_return !== null && r.total_return > 0 ? 'pos' : 'neg'">
                  {{ pct(r.total_return) }}
                </td>
                <td class="num">{{ num(r.sharpe) }}</td>
                <td class="num neg">{{ pct(r.max_drawdown) }}</td>
                <td class="num">{{ r.total_trades }}</td>
                <td class="num">{{ pct(r.win_rate) }}</td>
                <td>
                  <button class="view-btn" @click="onViewAll(r.strategy, r.params)">查看</button>
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.optimize-view {
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
.run-btn {
  width: 100%;
  padding: 10px;
  font-size: 14px;
  margin-top: 8px;
}
.run-btn:first-of-type {
  margin-top: 0;
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
.best-summary {
  display: flex;
  align-items: baseline;
  gap: 16px;
  flex-wrap: wrap;
}
.best-params {
  font-family: var(--font-mono);
  font-size: 14px;
  color: var(--accent);
}
.best-return {
  font-size: 22px;
  font-weight: 700;
  font-family: var(--font-mono);
}
.best-meta {
  color: var(--text-dim);
  font-size: 12px;
}
.meta-line {
  color: var(--text-dim);
  font-size: 12px;
  margin-top: 8px;
}
.pos {
  color: var(--up);
}
.neg {
  color: var(--down);
}
.opt-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.opt-table th,
.opt-table td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}
.opt-table th {
  color: var(--text-dim);
  font-size: 12px;
  position: sticky;
  top: 0;
  background: var(--bg-panel);
}
.num {
  text-align: right;
  font-family: var(--font-mono);
}
.params {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-muted);
}
.rank {
  color: var(--text-dim);
  width: 32px;
}
.best {
  background: rgba(74, 158, 255, 0.08);
}
.best .rank {
  color: var(--accent);
  font-weight: 700;
}
.view-btn {
  font-size: 11px;
  padding: 2px 8px;
}
.grade-cell {
  width: 56px;
}
</style>
