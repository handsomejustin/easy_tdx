<script setup lang="ts">
// 一条龙评估面板：综合评分 + 适配性体检 + 买入持有基准对比。
// 评级复用前端 grading（与后端口径对拍一致），评分/适配性/基准来自后端报告。

import { computed } from 'vue'

import GradeDetails from './GradeDetails.vue'
import GlossaryList from './GlossaryList.vue'
import HelpCollapse from './HelpCollapse.vue'
import { gradePerformance } from '../grading'
import { evaluateGlossary } from '../data/glossary'
import type { EvaluateReport } from '../types'

const props = defineProps<{
  report: EvaluateReport
}>()

/** 综合评分分项（含权重，展示顺序固定） */
const scoreComponents = computed(() => {
  const labels: Record<string, string> = {
    total_return: '收益',
    sharpe: '夏普',
    max_drawdown: '回撤',
    sortino: '索提诺',
    wf_consistency: 'WF一致性',
  }
  return Object.entries(props.report.score.components).map(([key, v]) => ({
    key,
    label: labels[key] ?? key,
    value: v,
    weight: props.report.score.weights_used[key] ?? 0,
  }))
})

const grade = computed(() => gradePerformance(props.report.performance))

const excess = computed(() => props.report.benchmark.excess_return)

/** v1.28 CAPM/主动管理指标（老报告缺省时不渲染该行；good=null 为中性不着色） */
const capm = computed(() => {
  const b = props.report.benchmark
  if (b.alpha === undefined || b.beta === undefined) return null
  return [
    { label: 'α 年化超额', value: b.alpha, fmt: 'percent', good: (b.alpha ?? 0) >= 0 },
    { label: 'β 敏感度', value: b.beta, fmt: 'ratio', good: null },
    {
      label: '信息比率',
      value: b.information_ratio ?? 0,
      fmt: 'ratio',
      good: (b.information_ratio ?? 0) >= 0,
    },
    { label: '跟踪误差', value: b.tracking_error ?? 0, fmt: 'percent', good: null },
  ]
})

function fmtCapm(v: number, fmt: string): string {
  if (!Number.isFinite(v)) return '-'
  if (fmt === 'percent') return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`
  return v.toFixed(2)
}
</script>

<template>
  <div class="eval-panel">
    <!-- 顶部：综合评分 + 高适配 + 超额收益 -->
    <div class="eval-header">
      <div class="score-block">
        <span class="score-label">综合评分</span>
        <span class="score-value" :class="report.score.total >= 60 ? 'pos' : 'neg'">
          {{ report.score.total.toFixed(1) }}
        </span>
        <span class="score-unit">/100</span>
      </div>
      <div class="badge" :class="report.fitness.high_fitness ? 'badge-ok' : 'badge-warn'">
        {{ report.fitness.high_fitness ? '✓ 高适配' : '△ 适配性未达标' }}
      </div>
      <div class="excess-block">
        <span class="score-label">对比买入持有</span>
        <span class="score-value" :class="excess >= 0 ? 'pos' : 'neg'">
          {{ excess >= 0 ? '+' : '' }}{{ (excess * 100).toFixed(2) }}%
        </span>
      </div>
    </div>

    <!-- 分项评分条 -->
    <div class="score-components">
      <div v-for="c in scoreComponents" :key="c.key" class="comp">
        <span class="comp-label">{{ c.label }}<small> ×{{ (c.weight * 100).toFixed(0) }}%</small></span>
        <div class="comp-bar">
          <div class="comp-fill" :style="{ width: `${Math.min(c.value, 100)}%` }"></div>
        </div>
        <span class="comp-value">{{ c.value.toFixed(0) }}</span>
      </div>
    </div>

    <!-- 基准对比 -->
    <div class="bench-row">
      <div class="bench-cell">
        <span class="stat-label">策略总收益</span>
        <span :class="report.performance.total_return >= 0 ? 'pos' : 'neg'" class="mono">
          {{ (report.performance.total_return * 100).toFixed(2) }}%
        </span>
      </div>
      <div class="bench-cell">
        <span class="stat-label">买入持有</span>
        <span :class="report.benchmark.buy_hold.total_return >= 0 ? 'pos' : 'neg'" class="mono">
          {{ (report.benchmark.buy_hold.total_return * 100).toFixed(2) }}%
        </span>
      </div>
      <div class="bench-cell">
        <span class="stat-label">超额收益</span>
        <span :class="excess >= 0 ? 'pos' : 'neg'" class="mono">
          {{ excess >= 0 ? '+' : '' }}{{ (excess * 100).toFixed(2) }}%
        </span>
      </div>
    </div>
    <!-- v1.28：CAPM / 主动管理对比（α/β/信息比率/跟踪误差） -->
    <div v-if="capm" class="bench-row bench-row-4">
      <div v-for="c in capm" :key="c.label" class="bench-cell">
        <span class="stat-label">{{ c.label }}</span>
        <span class="mono" :class="c.good === null ? '' : c.good ? 'pos' : 'neg'">
          {{ fmtCapm(c.value, c.fmt) }}
        </span>
      </div>
    </div>
    <p v-if="excess < 0" class="bench-warn">⚠ 策略跑输同区间买入持有——研发阶段的一票否决信号。</p>

    <!-- 适配性检查（8 项可解释） -->
    <h4 class="sub-title">
      适配性体检 {{ report.fitness.passed_count }}/{{ report.fitness.total_checks }}
      （train/valid/test = {{ report.fitness.split.map((s) => (s * 100).toFixed(0)).join('/') }}）
    </h4>
    <ul class="check-list">
      <li v-for="c in report.fitness.checks" :key="c.name" :class="c.passed ? 'ok' : 'bad'">
        <span class="check-mark">{{ c.passed ? '✓' : '✗' }}</span>
        <span class="check-detail">{{ c.detail }}</span>
      </li>
    </ul>

    <!-- 评级（复用本地评级，与后端字段口径一致） -->
    <h4 class="sub-title">评级（不看收益率）</h4>
    <GradeDetails :result="grade" />

    <!-- 名词解释（默认折叠，新手向） -->
    <HelpCollapse label="名词解释：综合评分 / 高适配 / α·β·IR / 适配性体检…">
      <GlossaryList :sections="evaluateGlossary" />
    </HelpCollapse>
  </div>
</template>

<style scoped>
.eval-header {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.score-block,
.excess-block {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.score-label {
  font-size: 12px;
  color: var(--text-dim);
}
.score-value {
  font-size: 26px;
  font-weight: 700;
  font-family: var(--font-mono);
}
.score-unit {
  font-size: 12px;
  color: var(--text-dim);
}
.pos {
  color: var(--up);
}
.neg {
  color: #2ebd85;
}
.badge {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 10px;
  font-weight: 600;
}
.badge-ok {
  background: rgba(46, 189, 133, 0.15);
  color: #2ebd85;
  border: 1px solid #2ebd85;
}
.badge-warn {
  background: rgba(239, 65, 70, 0.12);
  color: var(--up);
  border: 1px solid var(--up);
}
.score-components {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 6px 14px;
  margin-bottom: 14px;
}
.comp {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.comp-label {
  width: 86px;
  color: var(--text-muted);
  flex-shrink: 0;
}
.comp-label small {
  color: var(--text-dim);
}
.comp-bar {
  flex: 1;
  height: 6px;
  background: var(--bg);
  border-radius: 3px;
  overflow: hidden;
}
.comp-fill {
  height: 100%;
  background: var(--accent, #4a9eff);
  border-radius: 3px;
}
.comp-value {
  width: 28px;
  text-align: right;
  font-family: var(--font-mono);
  color: var(--text-muted);
}
.bench-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 6px;
}
.bench-row-4 {
  grid-template-columns: repeat(4, 1fr);
}
.bench-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 10px;
}
.mono {
  font-family: var(--font-mono);
  font-weight: 600;
}
.bench-warn {
  font-size: 12px;
  color: var(--up);
  margin: 4px 0 12px;
}
.sub-title {
  font-size: 12px;
  color: var(--text-muted);
  margin: 14px 0 8px;
}
.check-list {
  list-style: none;
  padding: 0;
  margin: 0 0 8px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 4px 14px;
}
.check-list li {
  display: flex;
  gap: 6px;
  font-size: 12px;
  align-items: baseline;
}
.check-mark {
  font-weight: 700;
  width: 14px;
  flex-shrink: 0;
}
.check-list li.ok .check-mark {
  color: #2ebd85;
}
.check-list li.bad .check-mark {
  color: var(--up);
}
.check-detail {
  color: var(--text-muted);
}
</style>
