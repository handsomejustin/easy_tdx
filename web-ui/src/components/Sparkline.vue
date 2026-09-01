<script setup lang="ts">
// 表格行内 SVG 迷你分时图（无 ECharts 实例，几千行表格也轻）。
// 相对昨收着色：线上方偏红、下方偏绿（简化：整线按首尾涨跌着色）。

import { computed } from 'vue'

const props = defineProps<{
  /** 分时价格序列。 */
  prices: number[]
  /** 昨收基准（可选，画虚线）。 */
  base?: number | null
  width?: number
  height?: number
}>()

const W = computed(() => props.width ?? 92)
const H = computed(() => props.height ?? 28)

const geom = computed(() => {
  const pts = props.prices.filter((p) => Number.isFinite(p))
  if (pts.length < 2) return null
  const base = props.base ?? pts[0]
  const all = props.base != null ? [...pts, props.base] : pts
  const min = Math.min(...all)
  const max = Math.max(...all)
  const span = max - min || 1
  const dx = W.value / (pts.length - 1)
  const y = (v: number) => H.value - 2 - ((v - min) / span) * (H.value - 4)
  const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${(i * dx).toFixed(1)},${y(p).toFixed(1)}`).join('')
  const area = `${path}L${W.value},${H.value}L0,${H.value}Z`
  const last = pts[pts.length - 1]
  const rising = last >= base
  return { path, area, baseY: y(base), rising, baseValid: props.base != null }
})
</script>

<template>
  <svg :width="W" :height="H" class="sparkline" viewBox="0 0 92 28" preserveAspectRatio="none">
    <template v-if="geom">
      <line
        v-if="geom.baseValid"
        x1="0"
        :y1="geom.baseY"
        :x2="W"
        :y2="geom.baseY"
        stroke="#5c6370"
        stroke-width="0.7"
        stroke-dasharray="3 2"
      />
      <path :d="geom.area" :fill="geom.rising ? 'rgba(239,65,70,0.12)' : 'rgba(24,160,88,0.12)'" />
      <path
        :d="geom.path"
        fill="none"
        :stroke="geom.rising ? '#ef4146' : '#18a058'"
        stroke-width="1.2"
        vector-effect="non-scaling-stroke"
      />
    </template>
    <text v-else x="46" y="18" text-anchor="middle" fill="#5c6370" font-size="9">加载中…</text>
  </svg>
</template>

<style scoped>
.sparkline {
  display: block;
}
</style>
