<script setup lang="ts">
// 参数寻优主页面：左配置（选标的 + 策略 + 寻优参数）/ 右报告（排名表 + 热力图）。
// 取行情已整合进「开始寻优」。另有「一键寻优所有策略」：用各策略预设网格逐策略寻优再全局排名。

import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import GradeBadge from '../components/GradeBadge.vue'
import OptimizeHeatmap from '../components/OptimizeHeatmap.vue'
import OptimizeResultTable from '../components/OptimizeResultTable.vue'
import ParamGridPicker from '../components/ParamGridPicker.vue'
import QuoteCarousel from '../components/QuoteCarousel.vue'
import SymbolPicker from '../components/SymbolPicker.vue'
import { gradeGridPoint } from '../grading'
import type { GradeResult } from '../grading'
import type { Category, ExecutionMode } from '../types'
import { useBacktestStore } from '../stores/backtest'

const store = useBacktestStore()
const router = useRouter()
const route = useRoute()

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
// 一键寻优并发工作进程数：0=串行（同 workers=1）；2+=多进程并行（CPU-bound 必须）
const cpuCount = (() => {
  // navigator.hardwareConcurrency 返回逻辑核数（含超线程）；非浏览器/不可用时回退 4
  const n = typeof navigator !== 'undefined' ? navigator.hardwareConcurrency : undefined
  return n && n > 0 ? n : 4
})()
// 推荐档：min(cpu, 8)。默认 8 进程，若用户改过则记到 localStorage，
// 下次以其最后一次选择为默认。
const recommendedWorkers = Math.min(cpuCount, 8)
const DEFAULT_WORKERS = 8
const WORKERS_STORAGE_KEY = 'optimize.workers'
const WORKER_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: '串行（不并发）' },
  { value: 4, label: '4 进程' },
  { value: 8, label: '8 进程' },
  { value: 16, label: '16 进程' },
]
function loadWorkersFromStorage(): number {
  try {
    const raw = localStorage.getItem(WORKERS_STORAGE_KEY)
    if (raw == null) return DEFAULT_WORKERS
    const n = Number(raw)
    return Number.isFinite(n) && WORKER_OPTIONS.some((o) => o.value === n)
      ? n
      : DEFAULT_WORKERS
  } catch {
    return DEFAULT_WORKERS
  }
}
const workers = ref(loadWorkersFromStorage())
// 用户修改后持久化,下次以最后选择为默认
watch(workers, (v) => {
  try {
    localStorage.setItem(WORKERS_STORAGE_KEY, String(v))
  } catch {
    /* localStorage 不可用时静默忽略 */
  }
})
// 成交价模式（精简为 开盘价/收盘价）
const EXECUTIONS: { value: ExecutionMode; label: string }[] = [
  { value: 'next_open', label: '开盘价' },
  { value: 'next_close', label: '收盘价' },
]

const selectedStrategy = computed(
  () => store.strategies.find((s) => s.name === strategy.value) ?? null,
)

onMounted(async () => {
  store.loadStrategies().catch((e) => {
    store.error = `加载策略列表失败：${e instanceof Error ? e.message : e}`
  })

  // 个股弹窗「一键寻优」入口：/optimize?code=601088&autoAll=1
  // 填入代码后自动触发「一键寻优所有策略」（等 nextTick 让 SymbolPicker
  // 的 v-model 同步，onRunAll 里的 loadBars 才会取到正确标的）。
  const qCode = String(route.query.code ?? '')
  if (route.query.autoAll === '1' && /^\d{6}$/.test(qCode)) {
    code.value = qCode
    await nextTick()
    if (!store.optimizeRunning && !store.optimizeAllRunning) {
      onRunAll()
    }
  }
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
  // 取行情成功 → 冻结本次寻优真正使用的标的上下文，供「查看」拼 URL（存 store，跨路由保留）
  store.setOptimizeContext({
    code: code.value,
    category: category.value,
    startDate: startDate.value,
    endDate: endDate.value,
  })
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
  // 取行情成功 → 冻结本次寻优真正使用的标的上下文，供「查看」拼 URL（存 store，跨路由保留）
  store.setOptimizeContext({
    code: code.value,
    category: category.value,
    startDate: startDate.value,
    endDate: endDate.value,
  })
  // 2. 一键寻优
  await store.runOptimizeAll({
    cash: cash.value,
    execution: execution.value,
    workers: workers.value,
    ohlcv: store.ohlcv,
  })
}

/** 「查看」跳转时，把本次寻优实际使用的标的 + 周期 + 日期范围一并塞进 query，
 * 让回测页能完整复现寻优时的行情（而非只带策略参数）。
 * 注意：必须读 store.optimizeContext（取行情成功时冻结），不能读输入框实时值 ——
 * 否则寻优完成后改了输入框代码，「查看」URL 会被污染，指向一个根本没被回测过的标的；
 * 且不能读组件 ref，否则切走再回 /optimize 时排名还在但上下文已丢失。 */
function buildBacktestQuery(strategyName: string, params: Record<string, number | string>) {
  const ctx = store.optimizeContext
  return {
    strategy: strategyName,
    params: JSON.stringify(params),
    symbol: ctx?.code ?? '',
    startDate: ctx?.startDate ?? '',
    endDate: ctx?.endDate ?? '',
    category: ctx?.category ?? category.value,
  }
}

// 点击排名表「查看」→ 跳转单标的页用该参数回测
function onViewParams(params: Record<string, number | string>) {
  // 通过 query 传递参数，单标的页接收后自动填充
  router.push({ path: '/backtest', query: buildBacktestQuery(strategy.value, params) })
}

// 一键寻优结果点击「查看」→ 跳转单标的页用该策略 + 参数回测
function onViewAll(strategyName: string, params: Record<string, number | string>) {
  router.push({ path: '/backtest', query: buildBacktestQuery(strategyName, params) })
}

function pct(v: number | null | undefined): string {
  return v !== null && v !== undefined && Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : '-'
}
/** 买入持有的盈亏配色（A 股习惯：涨红跌绿；非数值不加色） */
function bhClass(v: number | null | undefined): string {
  return v !== null && v !== undefined && Number.isFinite(v) ? (v >= 0 ? 'pos' : 'neg') : ''
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

      <section class="panel-section">
        <h3>一键寻优并发</h3>
        <div class="field">
          <label
            >工作进程
            <span class="hint"
              >CPU {{ cpuCount }} 核 · 推荐 {{ recommendedWorkers }}</span
            ></label
          >
          <select v-model.number="workers">
            <option v-for="o in WORKER_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
        </div>
        <p class="workers-tip">
          寻优是 CPU 密集计算，多进程可显著提速（仅对「一键寻优所有策略」生效）。机器较弱时建议先用串行测一次再开并发。
        </p>
      </section>

      <button
        class="primary run-btn"
        :disabled="store.optimizeRunning || store.optimizeAllRunning"
        @click="onRun"
      >
        {{ store.optimizeRunning ? '取行情+寻优中…' : '开始寻优' }}
      </button>
      <button
        class="run-all-btn run-btn"
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

      <!-- 一键寻优进行中：投资大师名言轮播，让等待不枯燥 -->
      <QuoteCarousel v-if="store.optimizeAllRunning" :interval="3000" />

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
            <span v-if="store.optimizeResult.buy_hold" class="best-bh">
              [买入持有：<span :class="bhClass(store.optimizeResult.buy_hold.total_return)">{{
                pct(store.optimizeResult.buy_hold.total_return)
              }}</span>]
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
            <span v-if="store.optimizeAllResult.buy_hold" class="best-bh">
              [买入持有：<span :class="bhClass(store.optimizeAllResult.buy_hold.total_return)">{{
                pct(store.optimizeAllResult.buy_hold.total_return)
              }}</span>]
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
.hint {
  font-weight: 400;
  color: var(--text-muted, #888);
  font-size: 12px;
  margin-left: 6px;
}
.workers-tip {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-muted, #888);
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

/* 「一键寻优所有策略」按钮：暖橙渐变，比 primary 蓝更醒目 */
.run-all-btn {
  background: linear-gradient(135deg, #f59e0b 0%, #ea580c 100%);
  border: 1px solid #f59e0b;
  color: #fff;
  font-weight: 600;
  box-shadow: 0 4px 14px rgba(245, 158, 11, 0.35);
}
.run-all-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #fbbf24, #f59e0b);
  border-color: #fbbf24;
  box-shadow: 0 6px 18px rgba(245, 158, 11, 0.5);
  transform: translateY(-1px);
}
.run-all-btn:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 8px rgba(245, 158, 11, 0.35);
}
/* 运行中：暗橙 disabled，但仍是橙，区别于普通按钮的纯灰 */
.run-all-btn:disabled {
  background: linear-gradient(135deg, #b45309, #9a3412);
  border-color: #b45309;
  color: #fde68a;
  opacity: 0.9;
  cursor: not-allowed;
  box-shadow: none;
  transform: none;
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
/* 买入持有对比项：标签/括号弱化不抢焦点，百分比按盈亏走 .pos/.neg 红绿 */
.best-bh {
  color: var(--text-dim);
  font-size: 13px;
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
