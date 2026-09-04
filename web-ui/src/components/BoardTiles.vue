<script setup lang="ts">
// 板块热力图：等宽色块网格（纯 CSS Grid，红涨绿跌、透明度随涨跌幅增强）。
// 数据已由父组件排序过滤；单击色块打开板块弹窗。500 块内 DOM 足够流畅。
import { computed } from 'vue'

import { fmt2, fmtPctSigned } from '../format'
import type { BoardOverviewRow } from '../types'

const props = defineProps<{
  rows: BoardOverviewRow[]
  /** tile 最小宽度（概念页可传小值） */
  tileMinWidth?: number
}>()

const emit = defineEmits<{ select: [row: BoardOverviewRow] }>()

/** 涨跌幅 → 背景色（A股红涨绿跌，|pct| 分 5 档增强）。 */
function tileStyle(r: BoardOverviewRow): Record<string, string> {
  const p = r.change_pct
  if (p === null || p === undefined || p === 0) {
    return { background: 'var(--bg-elevated)', color: 'var(--text-muted)' }
  }
  const mag = Math.abs(p)
  const tier = mag > 3 ? 0.82 : mag > 2 ? 0.62 : mag > 1 ? 0.42 : mag > 0.5 ? 0.26 : 0.14
  const base = p > 0 ? '239, 65, 70' : '24, 160, 88' // var(--up) / var(--down) 的 rgb
  return { background: `rgba(${base}, ${tier})`, color: '#fff' }
}

function tileTitle(r: BoardOverviewRow): string {
  const parts = [`${r.name} (${r.code})`]
  if (r.price) parts.push(`最新 ${fmt2(r.price)}`)
  parts.push(`涨跌幅 ${fmtPctSigned(r.change_pct)}`)
  if (r.speed !== null && r.speed !== undefined) parts.push(`涨速 ${fmtPctSigned(r.speed)}`)
  if (r.leader_name) parts.push(`领涨 ${r.leader_name} ${fmtPctSigned(r.leader_change_pct)}`)
  return parts.join('\n')
}

const gridStyle = computed(() => ({
  gridTemplateColumns: `repeat(auto-fill, minmax(${props.tileMinWidth ?? 104}px, 1fr))`,
}))
</script>

<template>
  <div class="tiles" :style="gridStyle">
    <div
      v-for="r in rows"
      :key="r.code"
      class="tile"
      :style="tileStyle(r)"
      :title="tileTitle(r)"
      @click="emit('select', r)"
    >
      <span class="t-name">{{ r.name }}</span>
      <span class="t-pct mono">{{ fmtPctSigned(r.change_pct) }}</span>
      <span v-if="r.leader_name" class="t-leader">
        {{ r.leader_name }} <span class="mono">{{ fmtPctSigned(r.leader_change_pct) }}</span>
      </span>
    </div>
    <div v-if="rows.length === 0" class="tiles-empty">没有匹配的板块</div>
  </div>
</template>

<style scoped>
.tiles {
  display: grid;
  gap: 4px;
}
.tile {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 7px 8px;
  border-radius: 4px;
  cursor: pointer;
  min-height: 58px;
  overflow: hidden;
  transition: filter 0.1s;
}
.tile:hover {
  filter: brightness(1.25);
}
.t-name {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.t-pct {
  font-size: 13px;
  font-weight: 700;
}
.t-leader {
  font-size: 10px;
  opacity: 0.85;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.tiles-empty {
  grid-column: 1 / -1;
  padding: 40px 0;
  text-align: center;
  color: var(--text-dim);
}
</style>
