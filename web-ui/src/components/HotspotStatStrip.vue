<script setup lang="ts">
// 热点窗口统计卡：窗口领涨(跌)王 / 持续热点 / 新面孔 / 一日游。
// 全部由矩阵行前端派生，零额外请求；领跌模式切换弱势词汇。
// 数量不为 0 的卡片可点击：王卡直达板块弹窗，其余展开成员板块列表（ chips 可再点弹窗）。
import { computed, ref } from 'vue'

import { fmtPctSigned } from '../format'
import type { HotspotRow } from '../types'

const props = defineProps<{
  rows: HotspotRow[]
  dates: string[]
  mode: 'top' | 'bottom'
}>()

const emit = defineEmits<{ select: [row: HotspotRow] }>()

const king = computed(() => {
  const withSum = props.rows.filter((r) => r.sum_pct !== null)
  if (withSum.length === 0) return null
  return [...withSum].sort((a, b) =>
    props.mode === 'top'
      ? (b.sum_pct ?? 0) - (a.sum_pct ?? 0)
      : (a.sum_pct ?? 0) - (b.sum_pct ?? 0),
  )[0]
})

/** 持续热点阈值：上榜 ≥ max(3, ⌈窗口/4⌉) 天（真实数据下前 5 名轮动快，÷3 会常年为 0） */
const persistentThreshold = computed(() => Math.max(3, Math.ceil(props.dates.length / 4)))
const persistent = computed(() => props.rows.filter((r) => r.days_in >= persistentThreshold.value))

/** 新面孔：首次上榜落在最近 5 个交易日 */
const fresh = computed(() => {
  if (props.dates.length === 0) return []
  const cutoff = props.dates.length - 5
  return props.rows.filter((r) => {
    if (!r.first_date) return false
    return props.dates.indexOf(r.first_date) >= cutoff
  })
})

/** 一日游：整个窗口仅上榜 1 天（脉冲行情，数量越多轮动越快） */
const flash = computed(() => props.rows.filter((r) => r.days_in === 1))

const kingLabel = computed(() => (props.mode === 'top' ? '窗口领涨王' : '窗口领跌王'))
const persistentLabel = computed(() => (props.mode === 'top' ? '持续热点' : '持续弱势'))
const freshLabel = computed(() => (props.mode === 'top' ? '新面孔' : '新杀跌'))

// ── 卡片点击：展开成员板块列表 ───────────────────────────────────────────────

type ExpandKey = 'persistent' | 'fresh' | 'flash'
const expanded = ref<ExpandKey | null>(null)

const EXPAND_META: Record<ExpandKey, { label: () => string; list: () => HotspotRow[] }> = {
  persistent: { label: () => `${persistentLabel.value}（上榜 ≥ ${persistentThreshold.value} 天）`, list: () => persistent.value },
  fresh: { label: () => `${freshLabel.value}（近 5 个交易日首次上榜）`, list: () => fresh.value },
  flash: { label: () => '一日游（仅上榜 1 天）', list: () => flash.value },
}

function toggle(key: ExpandKey) {
  expanded.value = expanded.value === key ? null : key
}

const expandedTitle = computed(() =>
  expanded.value ? EXPAND_META[expanded.value].label() : '',
)
const expandedList = computed(() =>
  expanded.value ? EXPAND_META[expanded.value].list().sort((a, b) =>
    props.mode === 'top'
      ? (b.sum_pct ?? 0) - (a.sum_pct ?? 0)
      : (a.sum_pct ?? 0) - (b.sum_pct ?? 0),
  ) : [],
)

function firstDateShort(r: HotspotRow): string {
  return r.first_date ? r.first_date.slice(5) : ''
}
</script>

<template>
  <div class="stat-strip-wrap">
    <div class="stat-strip">
      <div
        class="stat-card card king"
        :class="mode"
        title="点击查看板块详情"
        @click="king && emit('select', king)"
      >
        <div class="stat-title">{{ kingLabel }}</div>
        <template v-if="king">
          <div class="stat-main">{{ king.name }}</div>
          <div class="stat-sub mono" :class="king.sum_pct !== null && king.sum_pct < 0 ? 'down' : 'up'">
            {{ fmtPctSigned(king.sum_pct) }}
            <span class="dim">· 上榜 {{ king.days_in }} 天</span>
          </div>
        </template>
        <div v-else class="stat-main dim">—</div>
      </div>
      <div
        class="stat-card card"
        :class="{ clickable: persistent.length > 0, on: expanded === 'persistent' }"
        @click="toggle('persistent')"
      >
        <div class="stat-title">{{ persistentLabel }}</div>
        <div class="stat-main">
          {{ persistent.length }} <span class="unit">个</span>
          <span v-if="persistent.length > 0" class="expand-hint">{{ expanded === 'persistent' ? '收起 ▴' : '展开 ▾' }}</span>
        </div>
        <div class="stat-sub dim">上榜 ≥ {{ persistentThreshold }} 天</div>
      </div>
      <div
        class="stat-card card"
        :class="{ clickable: fresh.length > 0, on: expanded === 'fresh' }"
        @click="toggle('fresh')"
      >
        <div class="stat-title">{{ freshLabel }}</div>
        <div class="stat-main">
          {{ fresh.length }} <span class="unit">个</span>
          <span v-if="fresh.length > 0" class="expand-hint">{{ expanded === 'fresh' ? '收起 ▴' : '展开 ▾' }}</span>
        </div>
        <div class="stat-sub dim">近 5 个交易日首次上榜</div>
      </div>
      <div
        class="stat-card card"
        :class="{ clickable: flash.length > 0, on: expanded === 'flash' }"
        @click="toggle('flash')"
      >
        <div class="stat-title">一日游</div>
        <div class="stat-main">
          {{ flash.length }} <span class="unit">个</span>
          <span v-if="flash.length > 0" class="expand-hint">{{ expanded === 'flash' ? '收起 ▴' : '展开 ▾' }}</span>
        </div>
        <div class="stat-sub dim">仅上榜 1 天 · 越多轮动越快</div>
      </div>
    </div>

    <!-- 成员板块展开面板 -->
    <div v-if="expanded && expandedList.length > 0" class="member-panel card">
      <div class="mp-title">{{ expandedTitle }} · {{ expandedList.length }} 个板块，单击查看详情</div>
      <div class="mp-chips">
        <button
          v-for="r in expandedList"
          :key="r.code"
          class="member-chip"
          :title="`${r.name} (${r.code})\n上榜 ${r.days_in} 天 · 累计 ${fmtPctSigned(r.sum_pct)}${r.first_date ? ` · 首榜 ${firstDateShort(r)}` : ''}`"
          @click.stop="emit('select', r)"
        >
          <span class="mc-name">{{ r.name }}</span>
          <span class="mono mc-pct" :class="r.sum_pct === null ? 'flat' : r.sum_pct > 0 ? 'up' : 'down'">
            {{ fmtPctSigned(r.sum_pct) }}
          </span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stat-strip-wrap {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.stat-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.stat-card {
  padding: 10px 14px;
}
.stat-card.clickable {
  cursor: pointer;
  transition: border-color 0.1s;
}
.stat-card.clickable:hover {
  border-color: var(--accent);
}
.stat-card.on {
  border-color: var(--accent);
}
.stat-card.king {
  cursor: pointer;
}
.stat-card.king:hover {
  border-color: var(--accent);
}
.stat-title {
  font-size: 11.5px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.stat-main {
  font-size: 17px;
  font-weight: 700;
}
.stat-main.up {
  color: var(--up);
}
.stat-main.down {
  color: var(--down);
}
.unit {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-muted);
}
.expand-hint {
  font-size: 11px;
  font-weight: 400;
  color: var(--accent);
  margin-left: 6px;
}
.stat-sub {
  font-size: 11.5px;
  margin-top: 2px;
}
.member-panel {
  padding: 10px 14px;
}
.mp-title {
  font-size: 11.5px;
  color: var(--text-muted);
  margin-bottom: 8px;
}
.mp-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.member-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  font-size: 12px;
  border-radius: 999px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  cursor: pointer;
}
.member-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.mc-name {
  font-weight: 600;
}
.mc-pct {
  font-size: 11.5px;
}
@media (max-width: 1024px) {
  .stat-strip {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
