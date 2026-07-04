<script setup lang="ts">
// 评级详情：徽章 + 维度得分条 + 否决原因。
// 与 GradeBadge 互补：GradeBadge 是「徽章快照」，本组件展示「为什么是这个评级」。
// 放在 MetricTable 旁边，让用户理解评分依据。

import { computed } from 'vue'

import GradeBadge from './GradeBadge.vue'
import { GRADE_META, type DimensionScore, type GradeResult } from '../grading'

const props = defineProps<{
  result: GradeResult
  /** 是否默认展开维度明细（紧凑场景可关闭，仅徽章 + 总分） */
  expanded?: boolean
}>()

const meta = computed(() => GRADE_META[props.result.grade])

// 维度得分条颜色：>=70 绿，50–70 蓝，<50 橙/红
function barColor(score: number): string {
  if (score >= 70) return 'var(--down)' // 绿（A 股惯例绿即好）
  if (score >= 50) return 'var(--accent)' // 蓝
  if (score >= 30) return 'var(--warn)' // 橙
  return 'var(--up)' // 红
}

// 把维度按权重降序展示
const sortedDimensions = computed<DimensionScore[]>(() =>
  [...props.result.dimensions].sort((a, b) => b.weight - a.weight),
)
</script>

<template>
  <div class="grade-details" :class="`scenario-${result.scenario}`">
    <div class="grade-header">
      <GradeBadge :result="result" size="lg" />
      <div class="grade-hint">{{ meta.hint }}</div>
    </div>

    <!-- 特殊标记 -->
    <div v-if="result.insufficientSample || result.isLosing" class="flags">
      <span v-if="result.isLosing" class="flag flag-losing">⚠ 系统亏损</span>
      <span v-if="result.insufficientSample" class="flag flag-insufficient">
        ⚠ 交易样本有限（< 10 笔），胜率/利润因子已降权，评级基于净值类指标
      </span>
    </div>

    <!-- 否决原因 -->
    <ul v-if="result.vetoes.length" class="vetoes">
      <li v-for="v in result.vetoes" :key="v.key" class="veto-item">
        <span class="veto-cap">{{ v.cap }}</span>
        <span class="veto-reason">{{ v.reason }}</span>
      </li>
    </ul>

    <!-- 维度明细 -->
    <div v-if="expanded" class="dimensions">
      <div v-for="d in sortedDimensions" :key="d.key" class="dim-row">
        <div class="dim-header">
          <span class="dim-label">{{ d.label }}</span>
          <span class="dim-weight">权重 {{ (d.weight * 100).toFixed(0) }}%</span>
          <span class="dim-score">{{ d.score.toFixed(1) }}</span>
        </div>
        <div class="dim-bar-track">
          <div
            class="dim-bar-fill"
            :style="{ width: `${Math.min(100, Math.max(0, d.score))}%`, background: barColor(d.score) }"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.grade-details {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.grade-header {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.grade-hint {
  font-size: 13px;
  color: var(--text-muted);
}

.flags {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.flag {
  font-size: 12px;
  padding: 3px 9px;
  border-radius: var(--radius);
  font-weight: 600;
}
.flag-losing {
  background: rgba(239, 65, 70, 0.15);
  color: var(--up);
  border: 1px solid var(--up);
}
.flag-insufficient {
  background: rgba(240, 160, 32, 0.15);
  color: var(--warn);
  border: 1px solid var(--warn);
}

.vetoes {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  background: rgba(239, 65, 70, 0.06);
  border: 1px solid rgba(239, 65, 70, 0.25);
  border-radius: var(--radius);
}
.veto-item {
  display: flex;
  gap: 10px;
  align-items: baseline;
  font-size: 12px;
}
.veto-cap {
  flex-shrink: 0;
  font-weight: 700;
  color: var(--up);
  width: 16px;
}
.veto-reason {
  color: var(--text-muted);
}

.dimensions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}
.dim-row {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.dim-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
}
.dim-label {
  flex: 1;
  color: var(--text);
}
.dim-weight {
  color: var(--text-dim);
  font-size: 11px;
}
.dim-score {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--text-muted);
  min-width: 36px;
  text-align: right;
}
.dim-bar-track {
  height: 4px;
  background: var(--bg);
  border-radius: 2px;
  overflow: hidden;
}
.dim-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease;
}
</style>
