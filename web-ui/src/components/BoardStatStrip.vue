<script setup lang="ts">
// 板块总览统计条：板块广度（上涨/下跌/平盘）+ 涨幅中位数 + 全市场涨停/跌停
// + 涨跌幅分布直方图（纯 CSS 柱，±1% 一档，截断 ±3% 外两档）。
import { computed } from 'vue'

import { fmtPctSigned } from '../format'
import type { BoardOverviewRow, MarketStat } from '../types'

const props = defineProps<{
  rows: BoardOverviewRow[]
  stat: MarketStat | null
}>()

const breadth = computed(() => {
  let up = 0
  let down = 0
  let flat = 0
  for (const r of props.rows) {
    const p = r.change_pct
    if (p === null || p === undefined) continue
    if (p > 0) up++
    else if (p < 0) down++
    else flat++
  }
  return { up, down, flat }
})

const medianPct = computed<number | null>(() => {
  const vals = props.rows
    .map((r) => r.change_pct)
    .filter((v): v is number => v !== null && v !== undefined)
    .sort((a, b) => a - b)
  if (vals.length === 0) return null
  const mid = Math.floor(vals.length / 2)
  return vals.length % 2 ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2
})

// 直方图：[-Inf,-3) [-3,-2) [-2,-1) [-1,0) [0,1) [1,2) [2,3) [3,+Inf)
const BUCKETS = [
  { label: '≤-3', dir: 'down' as const },
  { label: '-3~-2', dir: 'down' as const },
  { label: '-2~-1', dir: 'down' as const },
  { label: '-1~0', dir: 'down' as const },
  { label: '0~1', dir: 'up' as const },
  { label: '1~2', dir: 'up' as const },
  { label: '2~3', dir: 'up' as const },
  { label: '≥3', dir: 'up' as const },
]

const hist = computed(() => {
  const counts = new Array(BUCKETS.length).fill(0) as number[]
  for (const r of props.rows) {
    const p = r.change_pct
    if (p === null || p === undefined) continue
    const idx = p < -3 ? 0 : p < -2 ? 1 : p < -1 ? 2 : p < 0 ? 3 : p < 1 ? 4 : p < 2 ? 5 : p < 3 ? 6 : 7
    counts[idx]++
  }
  const max = Math.max(...counts, 1)
  return BUCKETS.map((b, i) => ({
    ...b,
    count: counts[i],
    // 68% 上限给顶部数字留空间
    height: counts[i] > 0 ? `${Math.max((counts[i] / max) * 68, 8)}%` : '0',
  }))
})
</script>

<template>
  <div class="stat-strip card">
    <div class="stat-cell">
      <span class="stat-label">板块广度</span>
      <span class="stat-value">
        <span class="mono">{{ rows.length }}</span> 个
        <span class="mono up"> {{ breadth.up }}▲</span>
        <span class="mono down"> {{ breadth.down }}▼</span>
        <span v-if="breadth.flat" class="mono flat"> {{ breadth.flat }}—</span>
      </span>
    </div>
    <div class="stat-cell">
      <span class="stat-label">涨幅中位数</span>
      <span class="stat-value mono" :class="medianPct === null ? 'flat' : medianPct > 0 ? 'up' : medianPct < 0 ? 'down' : 'flat'">
        {{ medianPct === null ? '-' : fmtPctSigned(medianPct) }}
      </span>
    </div>
    <div class="stat-cell">
      <span class="stat-label">全市场涨停 / 跌停</span>
      <span class="stat-value mono">
        <span class="up">{{ stat?.limit_up_count ?? '-' }}</span>
        <span class="dim"> / </span>
        <span class="down">{{ stat?.limit_down_count ?? '-' }}</span>
      </span>
    </div>
    <div class="stat-cell hist-cell">
      <span class="stat-label">板块涨跌幅分布</span>
      <div class="hist">
        <div v-for="b in hist" :key="b.label" class="hist-col">
          <div class="hist-bar" :class="b.dir" :style="{ height: b.height }"></div>
          <span v-if="b.count" class="hist-n mono">{{ b.count }}</span>
          <div class="hist-label">{{ b.label }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stat-strip {
  display: flex;
  align-items: stretch;
  gap: 20px;
  padding: 10px 14px;
}
.stat-cell {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  flex-shrink: 0;
}
.hist-cell {
  flex: 1;
  min-width: 260px;
}
.stat-label {
  font-size: 11px;
  color: var(--text-dim);
}
.stat-value {
  font-size: 14px;
  font-weight: 600;
}
.hist {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 44px;
  margin-top: 2px;
}
.hist-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
  position: relative;
  min-width: 0;
}
.hist-bar {
  width: 100%;
  border-radius: 2px 2px 0 0;
}
.hist-bar.up {
  background: var(--up);
  opacity: 0.75;
}
.hist-bar.down {
  background: var(--down);
  opacity: 0.75;
}
.hist-n {
  font-size: 9.5px;
  color: var(--text-muted);
  line-height: 1.1;
}
.hist-label {
  font-size: 9.5px;
  color: var(--text-dim);
  white-space: nowrap;
}
</style>
