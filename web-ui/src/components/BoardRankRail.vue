<script setup lang="ts">
// 板块总览右栏：涨幅/跌幅/涨速异动 Top10 + 翻红翻绿时间线。
// 全部由父组件传入的全量 rows 在内存内计算，不额外发请求。
import { computed } from 'vue'

import { fmtPctSigned } from '../format'
import type { BoardFlipEvent, BoardOverviewRow } from '../types'

const props = defineProps<{
  rows: BoardOverviewRow[]
  flips: BoardFlipEvent[]
}>()

const emit = defineEmits<{ select: [row: BoardOverviewRow] }>()

const TOP_N = 10

function topBy(
  rows: BoardOverviewRow[],
  key: 'change_pct' | 'speed',
  order: 'desc' | 'asc' = 'desc',
  n = TOP_N,
): BoardOverviewRow[] {
  const sorted = rows
    .filter((r) => r[key] !== null && r[key] !== undefined)
    .sort((a, b) => (b[key] as number) - (a[key] as number))
  return (order === 'desc' ? sorted : sorted.slice().reverse()).slice(0, n)
}

const topGainers = computed(() => topBy(props.rows, 'change_pct'))
const topLosers = computed(() => topBy(props.rows, 'change_pct', 'asc'))
/** 涨速异动：按 |speed| 降序，急拉急杀都算；|speed| ≥ 0.5% 标闪烁。 */
const rowsByAbsSpeed = computed(() =>
  props.rows
    .filter((r) => r.speed !== null && r.speed !== undefined)
    .sort((a, b) => Math.abs(b.speed as number) - Math.abs(a.speed as number)),
)
const speedMovers = computed(() => rowsByAbsSpeed.value.slice(0, TOP_N))

const recentFlips = computed(() => props.flips.slice(0, 12))
</script>

<template>
  <div class="rail">
    <div class="card rank-card">
      <h3>涨幅榜 <span class="dim">Top{{ TOP_N }}</span></h3>
      <div v-for="(r, i) in topGainers" :key="r.code" class="rank-row clickable" @click="emit('select', r)">
        <span class="r-idx dim">{{ i + 1 }}</span>
        <span class="r-name">{{ r.name }}</span>
        <span class="r-pct mono up">{{ fmtPctSigned(r.change_pct) }}</span>
      </div>
      <div v-if="topGainers.length === 0" class="rank-empty dim">暂无数据</div>
    </div>

    <div class="card rank-card">
      <h3>跌幅榜 <span class="dim">Top{{ TOP_N }}</span></h3>
      <div v-for="(r, i) in topLosers" :key="r.code" class="rank-row clickable" @click="emit('select', r)">
        <span class="r-idx dim">{{ i + 1 }}</span>
        <span class="r-name">{{ r.name }}</span>
        <span class="r-pct mono down">{{ fmtPctSigned(r.change_pct) }}</span>
      </div>
      <div v-if="topLosers.length === 0" class="rank-empty dim">暂无数据</div>
    </div>

    <div class="card rank-card">
      <h3>异动 · 涨速 <span class="dim">|涨速| Top{{ TOP_N }}</span></h3>
      <div
        v-for="r in speedMovers"
        :key="r.code"
        class="rank-row clickable"
        :class="{ flashing: r.speed !== null && Math.abs(r.speed) >= 0.5 }"
        @click="emit('select', r)"
      >
        <span class="r-name">{{ r.name }}</span>
        <span class="r-pct mono" :class="(r.speed ?? 0) >= 0 ? 'up' : 'down'">{{ fmtPctSigned(r.speed) }}</span>
      </div>
      <div v-if="speedMovers.length === 0" class="rank-empty dim">暂无数据</div>
    </div>

    <div class="card rank-card">
      <h3>板块轮动 <span class="dim">翻红 / 翻绿</span></h3>
      <div v-if="recentFlips.length === 0" class="rank-empty dim">刷新期间暂无翻红/翻绿</div>
      <div v-for="(f, i) in recentFlips" :key="`${f.code}-${f.time}-${i}`" class="flip-row">
        <span class="f-time mono dim">{{ f.time }}</span>
        <span class="f-type" :class="f.type === 'up' ? 'up' : 'down'">{{ f.type === 'up' ? '翻红' : '翻绿' }}</span>
        <span class="f-name">{{ f.name }}</span>
        <span class="r-pct mono" :class="f.type === 'up' ? 'up' : 'down'">{{ fmtPctSigned(f.change_pct) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rail {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.rank-card {
  padding: 10px 12px;
}
.rank-card h3 {
  margin-bottom: 6px;
}
.rank-card h3 .dim {
  font-size: 10.5px;
  font-weight: 400;
}
.rank-row,
.flip-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2.5px 4px;
  font-size: 12px;
  border-radius: 3px;
}
.rank-row.clickable {
  cursor: pointer;
}
.rank-row.clickable:hover {
  background: var(--bg-elevated);
}
.r-idx {
  width: 16px;
  font-size: 10.5px;
  text-align: right;
}
.r-name,
.f-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.r-pct {
  font-weight: 600;
}
.flashing {
  animation: flash 1s ease-in-out infinite;
}
@keyframes flash {
  0%,
  100% {
    background: transparent;
  }
  50% {
    background: rgba(240, 160, 32, 0.18);
  }
}
.flip-row {
  font-size: 11.5px;
}
.f-time {
  font-size: 10.5px;
}
.f-type {
  width: 30px;
  font-weight: 600;
}
.rank-empty {
  padding: 8px 0;
  font-size: 12px;
}
</style>
