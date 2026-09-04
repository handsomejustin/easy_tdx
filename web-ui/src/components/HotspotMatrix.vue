<script setup lang="ts">
// 热点矩阵：交易日 × 板块 的红涨绿跌色阶网格（纯 DOM 表格，sticky 双向表头）。
// 当日进入前 per_day 的格子带名次徽标（①~⑩，前3加粗描边）；今日列高亮；
// hover 出数值 tooltip，单击行头/格子打开板块弹窗。数据已由父组件排序过滤。
import { fmtPctSigned } from '../format'
import type { HotspotRow } from '../types'

const props = defineProps<{
  dates: string[]
  rows: HotspotRow[]
  perDay: number
  /** 今日实时列下标，null = 无今日列 */
  todayIndex: number | null
  mode: 'top' | 'bottom'
}>()

const emit = defineEmits<{ select: [row: HotspotRow] }>()

// 名次徽标：①②③④⑤⑥⑦⑧⑨⑩（perDay ≤ 10）
const RANK_CHARS = '①②③④⑤⑥⑦⑧⑨⑩'

function rankChar(rank: number | null): string {
  if (rank === null || rank < 1 || rank > 10) return ''
  return RANK_CHARS[rank - 1] ?? ''
}

/** 涨跌幅 → 背景色（A股红涨绿跌，|pct| 分 5 档增强；与 BoardTiles 同规） */
function cellStyle(pct: number | null): Record<string, string> {
  if (pct === null || pct === undefined) {
    return { background: 'transparent' }
  }
  if (pct === 0) {
    return { background: 'var(--bg-elevated)', color: 'var(--text-muted)' }
  }
  const mag = Math.abs(pct)
  const tier = mag > 3 ? 0.82 : mag > 2 ? 0.62 : mag > 1 ? 0.42 : mag > 0.5 ? 0.26 : 0.14
  const base = pct > 0 ? '239, 65, 70' : '24, 160, 88' // var(--up) / var(--down) 的 rgb
  return { background: `rgba(${base}, ${tier})`, color: '#fff' }
}

function isTopDay(rank: number | null): boolean {
  return rank !== null && rank <= props.perDay
}

function shortDate(d: string): string {
  return d.slice(5) // MM-DD
}

function cellTitle(row: HotspotRow, i: number): string {
  const pct = row.pct[i]
  const rank = row.rank[i]
  const parts = [`${props.dates[i]} ${row.name}`]
  parts.push(pct === null ? '无数据' : `${fmtPctSigned(pct)}`)
  if (rank !== null) {
    const label = props.mode === 'top' ? '涨幅' : '跌幅'
    parts.push(`当日${label}第 ${rank} 名`)
  }
  return parts.join(' · ')
}

function rowTitle(row: HotspotRow): string {
  return `${row.name} (${row.code})\n上榜 ${row.days_in} 天 · 当前连榜 ${row.streak} 天`
}
</script>

<template>
  <div class="matrix-wrap">
    <table class="hs-table qtable">
      <thead>
        <tr>
          <th class="sticky-name head-name">板块</th>
          <th
            v-for="(d, i) in dates"
            :key="d"
            class="date-col"
            :class="{ today: todayIndex === i }"
          >
            {{ shortDate(d) }}<span v-if="todayIndex === i" class="today-tag">今</span>
          </th>
          <th class="sum-col">上榜</th>
          <th class="sum-col">连榜</th>
          <th class="sum-col">累计</th>
          <th class="sum-col">首榜</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.code">
          <th class="sticky-name name" :title="rowTitle(row)" @click="emit('select', row)">
            <span class="n">{{ row.name }}</span>
            <span class="c dim">{{ row.code }}</span>
          </th>
          <td
            v-for="(d, i) in dates"
            :key="d"
            class="cell-td"
            :class="{ today: todayIndex === i }"
          >
            <div
              class="cell"
              :class="{ top3: isTopDay(row.rank[i]) && row.rank[i]! <= 3 }"
              :style="cellStyle(row.pct[i])"
              :title="cellTitle(row, i)"
              @click="emit('select', row)"
            >
              <span class="pct mono">{{ fmtPctSigned(row.pct[i]) }}</span>
              <span v-if="isTopDay(row.rank[i])" class="rk">{{ rankChar(row.rank[i]) }}</span>
            </div>
          </td>
          <td class="sum-col strong">{{ row.days_in }}</td>
          <td class="sum-col" :class="{ hot: row.streak >= 3 }">{{ row.streak }}</td>
          <td
            class="sum-col mono strong"
            :class="row.sum_pct === null ? 'flat' : row.sum_pct > 0 ? 'up' : 'down'"
          >
            {{ fmtPctSigned(row.sum_pct) }}
          </td>
          <td class="sum-col dim">{{ row.first_date ? shortDate(row.first_date) : '-' }}</td>
        </tr>
      </tbody>
    </table>
    <div v-if="rows.length === 0" class="matrix-empty">窗口内暂无上榜板块</div>
  </div>
</template>

<style scoped>
.matrix-wrap {
  overflow: auto;
  max-height: calc(100vh - 320px);
  min-height: 240px;
}
.hs-table {
  border-collapse: separate;
  border-spacing: 0;
  font-size: 12px;
}
.hs-table th,
.hs-table td {
  padding: 0;
  border-bottom: 1px solid var(--border);
  text-align: center;
  white-space: nowrap;
}
/* 列头（sticky 顶） */
.hs-table thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--bg-panel);
  padding: 6px 4px;
  color: var(--text-dim);
  font-weight: 500;
  border-bottom: 1px solid var(--border);
}
/* 行头板块名（sticky 左） */
.hs-table .sticky-name {
  position: sticky;
  left: 0;
  z-index: 1;
  background: var(--bg-panel);
}
.hs-table thead .sticky-name {
  z-index: 3;
}
.hs-table .head-name {
  text-align: left;
  min-width: 100px;
}
.hs-table .name {
  text-align: left;
  cursor: pointer;
  padding: 0 8px;
  min-width: 100px;
  max-width: 124px;
}
.hs-table .name:hover {
  color: var(--accent);
}
.hs-table .name .n {
  display: block;
  font-weight: 600;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hs-table .name .c {
  display: block;
  font-size: 10px;
  font-family: var(--font-mono);
}
.date-col {
  min-width: 53px;
}
/* 单元格 */
.cell-td {
  padding: 0 !important;
}
.cell {
  position: relative;
  min-width: 53px;
  height: 34px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  line-height: 1.1;
  cursor: pointer;
  overflow: hidden;
}
.cell:hover {
  filter: brightness(1.3);
}
.cell .pct {
  font-size: 10.5px;
}
.cell .rk {
  font-size: 10px;
  opacity: 0.95;
}
/* 当日第一名加粗描边 */
.cell.top3 {
  box-shadow: inset 0 0 0 1.5px rgba(255, 255, 255, 0.65);
}
/* 今日列高亮 */
.date-col.today {
  color: var(--accent);
  font-weight: 700;
}
.cell-td.today {
  border-left: 1px solid var(--accent);
}
.today-tag {
  margin-left: 2px;
  font-size: 9px;
  background: var(--accent);
  color: #fff;
  border-radius: 2px;
  padding: 0 2px;
}
/* 行尾汇总列 */
.sum-col {
  min-width: 46px;
  padding: 0 7px !important;
  font-family: var(--font-mono);
}
.sum-col.strong {
  font-weight: 700;
}
.sum-col.hot {
  color: var(--up);
}
.matrix-empty {
  padding: 40px 0;
  text-align: center;
  color: var(--text-dim);
}
</style>
