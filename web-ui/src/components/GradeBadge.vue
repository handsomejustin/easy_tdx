<script setup lang="ts">
// 评级徽章：圆形大字母（S/A/B/C/D）+ 颜色 + tooltip。
// 用在 BacktestView/PortfolioView/OptimizeView 的报告顶部，让人一眼看到「适不适合参与」。
//
// 设计：徽章本身用档位主色，悬停展开评分明细 + 否决原因。
// 不适合展示太长的文本——详细信息交给同页的 GradeDetails 组件。

import { computed } from 'vue'

import { GRADE_META, type GradeResult } from '../grading'

const props = withDefaults(
  defineProps<{
    /** 评级结果 */
    result: GradeResult
    /** 尺寸：sm 用于表格内紧凑展示，md/lg 用于报告顶部 */
    size?: 'sm' | 'md' | 'lg'
    /** 是否展示分数（如 "B 65.3"）。表格内通常关闭。 */
    showScore?: boolean
  }>(),
  { size: 'md', showScore: true },
)

const meta = computed(() => GRADE_META[props.result.grade])

// tooltip 文案：档位含义 + 分数 + 触发的否决原因
const tooltip = computed(() => {
  const lines: string[] = [`${meta.value.grade} 档 · ${meta.value.hint}`]
  lines.push(`综合评分 ${props.result.score}`)
  if (props.result.insufficientSample) lines.push('⚠ 样本不足')
  if (props.result.isLosing) lines.push('⚠ 系统亏损')
  for (const v of props.result.vetoes) {
    lines.push(`• ${v.reason}`)
  }
  return lines.join('\n')
})

const badgeClass = computed(() => [
  'grade-badge',
  `size-${props.size}`,
  `grade-${props.result.grade}`,
])
</script>

<template>
  <span class="badge-wrapper">
    <span
      :class="badgeClass"
      :style="{ '--grade-color': meta.color }"
      :title="tooltip"
      role="img"
      :aria-label="`评级 ${result.grade}：${meta.hint}`"
    >
      <span class="grade-letter">{{ result.grade }}</span>
      <span v-if="showScore" class="grade-score">{{ result.score.toFixed(0) }}</span>
    </span>
    <span
      v-if="result.insufficientSample"
      class="sample-warn"
      title="交易笔数 < 10，胜率/利润因子已降权（不参与总分），评级基于净值类指标"
    >
      ⚠ 交易样本有限
    </span>
  </span>
</template>

<style scoped>
.badge-wrapper {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.sample-warn {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--radius);
  background: rgba(240, 160, 32, 0.12);
  border: 1px solid rgba(240, 160, 32, 0.45);
  color: var(--warn);
  font-weight: 500;
  white-space: nowrap;
  cursor: help;
}

.grade-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--grade-color) 18%, transparent);
  border: 1px solid color-mix(in srgb, var(--grade-color) 55%, transparent);
  color: var(--grade-color);
  font-weight: 700;
  line-height: 1;
  user-select: none;
  cursor: help;
  white-space: nowrap;
}

.grade-letter {
  font-size: 1em;
  letter-spacing: 0.5px;
}

.grade-score {
  font-size: 0.85em;
  opacity: 0.85;
  font-family: var(--font-mono);
  font-weight: 600;
}

/* 尺寸 */
.size-sm {
  font-size: 11px;
  padding: 1px 7px;
}
.size-md {
  font-size: 13px;
  padding: 3px 10px;
}
.size-lg {
  font-size: 16px;
  padding: 6px 14px;
}
.size-lg .grade-letter {
  font-size: 1.15em;
}

/* 各档位无需额外样式，--grade-color 已通过 style 绑定 */
</style>
