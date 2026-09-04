<script setup lang="ts">
// 大盘日历（/calendar）：指数全年每日涨跌红绿日历热力图（GitHub 贡献图风格）。
// 数据 = /bars/index 指数日K（上证/深成/创业板），前端算逐日涨跌幅、按年渲染 12 个月块。
import { computed, onMounted, ref, watch } from 'vue'

import { fetchIndexBars, formatError } from '../api'
import { fmt2, fmtAmount, fmtPctSigned, pctCellStyle } from '../format'
import type { Bar } from '../types'

const INDICES = [
  { market: 'SH', code: '000001', name: '上证指数' },
  { market: 'SZ', code: '399001', name: '深证成指' },
  { market: 'SZ', code: '399006', name: '创业板指' },
] as const

type DailyPoint = { date: string; pct: number | null; close: number; amount: number }

const activeIdx = ref(0)
const barsByIndex = new Map<number, Bar[]>()

const loading = ref(false)
const error = ref('')
const bars = ref<Bar[]>([])
const lastUpdate = ref('')

async function loadIndex(idx: number) {
  if (barsByIndex.has(idx)) {
    bars.value = barsByIndex.get(idx)!
    return
  }
  loading.value = true
  error.value = ''
  try {
    const meta = INDICES[idx]
    const data = await fetchIndexBars(meta.market, meta.code, 550) // ≈2.2 年
    barsByIndex.set(idx, data)
    bars.value = data
    if (data.length === 0) error.value = `${meta.name} 日K返回空`
    lastUpdate.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

function onIndexChange(idx: number) {
  activeIdx.value = idx
  loadIndex(idx)
}

/** 全序列逐日涨跌幅（首日无前收 → null；跨年由上一年末收盘提供基准） */
const daily = computed<DailyPoint[]>(() => {
  const out: DailyPoint[] = []
  let prev: number | null = null
  for (const b of bars.value) {
    const close = b.close
    out.push({
      date: b.datetime.slice(0, 10),
      pct: prev !== null && prev > 0 ? (close / prev - 1) * 100 : null,
      close,
      amount: Number(b.amount ?? 0),
    })
    prev = close
  }
  return out
})

const years = computed(() => {
  const set = new Set<number>()
  for (const p of daily.value) set.add(Number(p.date.slice(0, 4)))
  return [...set].sort((a, b) => b - a) // 新年份在前
})

const activeYear = ref<number>(new Date().getFullYear())

watch(years, (ys) => {
  if (ys.length > 0 && !ys.includes(activeYear.value)) activeYear.value = ys[0]
})

const yearPoints = computed(() =>
  daily.value.filter((p) => Number(p.date.slice(0, 4)) === activeYear.value),
)

/** 年内统计：红绿天数、最大连涨/连跌 */
const yearStats = computed(() => {
  const pts = yearPoints.value
  if (pts.length === 0) return null
  const up = pts.filter((p) => (p.pct ?? 0) > 0).length
  const down = pts.filter((p) => (p.pct ?? 0) < 0).length
  let maxUpStreak = 0
  let maxDownStreak = 0
  let cu = 0
  let cd = 0
  for (const p of pts) {
    if ((p.pct ?? 0) > 0) cu += 1
    else cu = 0
    if ((p.pct ?? 0) < 0) cd += 1
    else cd = 0
    maxUpStreak = Math.max(maxUpStreak, cu)
    maxDownStreak = Math.max(maxDownStreak, cd)
  }
  return { up, down, maxUpStreak, maxDownStreak }
})

/** 年涨幅：上年末收盘为基准（取全序列中年内首日的前一根） */
const yearPct = computed(() => {
  const firstPos = daily.value.findIndex(
    (p) => Number(p.date.slice(0, 4)) === activeYear.value,
  )
  if (firstPos <= 0) return null
  const base = daily.value[firstPos - 1].close
  const lastPt = daily.value[firstPos + yearPoints.value.length - 1]
  if (!lastPt || base <= 0) return null
  return (lastPt.close / base - 1) * 100
})

/** 按月分组的渲染模型：12 个月块，各含交易日格与月涨幅（上月末收盘为基准） */
const months = computed(() => {
  const byMonth: DailyPoint[][] = Array.from({ length: 12 }, () => [])
  for (const p of yearPoints.value) byMonth[Number(p.date.slice(5, 7)) - 1].push(p)
  return byMonth.map((pts, i) => {
    let pct: number | null = null
    if (pts.length > 0) {
      const pos = daily.value.findIndex((p) => p.date === pts[0].date)
      if (pos > 0) pct = (pts[pts.length - 1].close / daily.value[pos - 1].close - 1) * 100
    }
    return { month: i + 1, days: pts, pct }
  })
})

// ── 方框大小编码成交额：年内四分位分 4 档（相对口径，跨指数/年份自归一） ─────

const SIZE_STEPS = [18, 22, 26, 30]

const amountTiers = computed(() => {
  const sorted = yearPoints.value
    .filter((p) => p.amount > 0)
    .map((p) => p.amount)
    .sort((a, b) => a - b)
  const map = new Map<string, number>()
  const q = (t: number) => (sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(t * sorted.length))] : 0)
  const cuts = [q(0.25), q(0.5), q(0.75)]
  for (const p of yearPoints.value) {
    const tier =
      p.amount <= 0 || sorted.length === 0
        ? 0
        : p.amount <= cuts[0]
          ? 0
          : p.amount <= cuts[1]
            ? 1
            : p.amount <= cuts[2]
              ? 2
              : 3
    map.set(p.date, tier)
  }
  return map
})

function daySize(p: DailyPoint): number {
  return SIZE_STEPS[amountTiers.value.get(p.date) ?? 0]
}

// ── 浮动 tooltip：跟随鼠标展示当日涨跌幅 / 收盘 / 成交额 ────────────────────

const tip = ref<{ x: number; y: number; lines: Array<{ t: string; cls?: string }> } | null>(null)

function showTip(e: MouseEvent, p: DailyPoint) {
  tip.value = {
    x: e.clientX,
    y: e.clientY,
    lines: [
      { t: p.date },
      { t: `收盘 ${fmt2(p.close)}` },
      { t: fmtPctSigned(p.pct), cls: (p.pct ?? 0) > 0 ? 'up' : (p.pct ?? 0) < 0 ? 'down' : 'flat' },
      { t: `成交 ${fmtAmount(p.amount)}` },
    ],
  }
}

function hideTip() {
  tip.value = null
}

function cellTitle(p: DailyPoint): string {
  return `${p.date}\n收 ${fmt2(p.close)} · ${fmtPctSigned(p.pct)}`
}

onMounted(() => loadIndex(activeIdx.value))
</script>

<template>
  <div class="calendar-view">
    <div class="view-head">
      <h2>大盘日历</h2>
      <span class="dim head-sub">全年红绿一眼扫完 · 红涨绿跌</span>
      <span v-if="lastUpdate" class="dim head-sub">更新于 {{ lastUpdate }}</span>
    </div>

    <div class="toolbar">
      <span class="seg">
        <button
          v-for="(m, i) in INDICES"
          :key="m.code"
          :class="{ on: activeIdx === i }"
          @click="onIndexChange(i)"
        >
          {{ m.name }}
        </button>
      </span>
      <span class="seg">
        <button v-for="y in years" :key="y" :class="{ on: activeYear === y }" @click="activeYear = y">
          {{ y }}年
        </button>
      </span>
      <span class="tb-spacer"></span>
      <div class="legend">
        <span class="lg-title">色阶</span>
        <i class="sw u1"></i><i class="sw u2"></i><i class="sw u3"></i>
        <span>涨</span>
        <i class="sw d1"></i><i class="sw d2"></i><i class="sw d3"></i>
        <span>跌（越深幅度越大）</span>
        <span class="lg-sep">|</span>
        <span>框越大 = 当日成交额越高（年内相对分档）</span>
        <span class="lg-sep">|</span>
        <span>悬停看当日详情</span>
      </div>
    </div>

    <div v-if="error" class="err card">
      加载失败：{{ error }}
      <button @click="onIndexChange(activeIdx)">重试</button>
    </div>
    <div v-else-if="loading" class="loading">指数日K加载中…</div>

    <template v-else>
      <!-- 年度统计条 -->
      <div class="stat-strip">
        <div class="stat-card card">
          <div class="stat-title">{{ activeYear }}年涨幅</div>
          <div class="stat-main mono" :class="yearPct === null ? 'flat' : yearPct > 0 ? 'up' : 'down'">
            {{ fmtPctSigned(yearPct) }}
          </div>
        </div>
        <div class="stat-card card">
          <div class="stat-title">上涨 / 下跌天数</div>
          <div class="stat-main">
            <span class="up">{{ yearStats?.up ?? '-' }}</span>
            <span class="dim"> / </span>
            <span class="down">{{ yearStats?.down ?? '-' }}</span>
          </div>
        </div>
        <div class="stat-card card">
          <div class="stat-title">最长连涨</div>
          <div class="stat-main">{{ yearStats?.maxUpStreak ?? '-' }} <span class="unit">天</span></div>
        </div>
        <div class="stat-card card">
          <div class="stat-title">最长连跌</div>
          <div class="stat-main">{{ yearStats?.maxDownStreak ?? '-' }} <span class="unit">天</span></div>
        </div>
      </div>

      <!-- 12 个月块日历 -->
      <div class="cal-grid">
        <div v-for="m in months" :key="m.month" class="month-block card">
          <div class="m-head">
            <span class="m-name">{{ m.month }}月</span>
            <span
              v-if="m.pct !== null"
              class="m-pct mono"
              :class="m.pct > 0 ? 'up' : m.pct < 0 ? 'down' : 'flat'"
            >
              {{ fmtPctSigned(m.pct) }}
            </span>
          </div>
          <div class="m-days">
            <div
              v-for="p in m.days"
              :key="p.date"
              class="day-cell mono"
              :style="{ ...pctCellStyle(p.pct), width: daySize(p) + 'px', height: daySize(p) + 'px' }"
              :title="cellTitle(p)"
              @mouseenter="showTip($event, p)"
              @mousemove="showTip($event, p)"
              @mouseleave="hideTip"
            >
              {{ Number(p.date.slice(8, 10)) }}
            </div>
          </div>
        </div>
      </div>

      <!-- 浮动 tooltip -->
      <div
        v-if="tip"
        class="float-tip"
        :style="{ left: tip.x + 14 + 'px', top: tip.y + 14 + 'px' }"
      >
        <div v-for="(l, i) in tip.lines" :key="i" class="ft-line" :class="l.cls">{{ l.t }}</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.calendar-view {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.view-head,
.toolbar,
.stat-strip,
.err,
.loading {
  flex-shrink: 0;
}
.view-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.view-head h2 {
  font-size: 17px;
  font-weight: 700;
}
.head-sub {
  font-size: 12px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.seg {
  display: inline-flex;
}
.seg button {
  border-radius: 0;
  font-size: 12px;
  padding: 4px 12px;
}
.seg button:first-child {
  border-radius: var(--radius) 0 0 var(--radius);
}
.seg button:last-child {
  border-radius: 0 var(--radius) var(--radius) 0;
  margin-left: -1px;
}
.seg button.on {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(74, 158, 255, 0.12);
  position: relative;
  z-index: 1;
}
.tb-spacer {
  flex: 1;
}
.legend {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--text-muted);
}
.lg-title {
  color: var(--text-dim);
}
.sw {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 2px;
  margin: 0 1px;
}
.sw.u1 {
  background: rgba(239, 65, 70, 0.26);
}
.sw.u2 {
  background: rgba(239, 65, 70, 0.5);
}
.sw.u3 {
  background: rgba(239, 65, 70, 0.82);
}
.sw.d1 {
  background: rgba(24, 160, 88, 0.26);
}
.sw.d2 {
  background: rgba(24, 160, 88, 0.5);
}
.sw.d3 {
  background: rgba(24, 160, 88, 0.82);
}
.err {
  color: var(--up);
  display: flex;
  align-items: center;
  gap: 10px;
}
.loading {
  padding: 40px 0;
  text-align: center;
  color: var(--text-dim);
}
.stat-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.stat-card {
  padding: 10px 14px;
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
.unit {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-muted);
}
.cal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
  padding-bottom: 20px;
}
.month-block {
  padding: 10px 12px;
}
.m-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 8px;
}
.m-name {
  font-size: 12.5px;
  font-weight: 700;
}
.m-pct {
  font-size: 12px;
}
.m-days {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  align-items: center;
  min-height: 30px;
}
.day-cell {
  border-radius: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 9.5px;
  cursor: default;
  transition: width 0.15s, height 0.15s;
}
.day-cell:hover {
  filter: brightness(1.3);
  outline: 1px solid var(--accent);
}
/* 浮动 tooltip（跟随鼠标；fixed 定位不受滚动容器裁剪） */
.float-tip {
  position: fixed;
  z-index: 1000;
  pointer-events: none;
  background: rgba(26, 29, 38, 0.96);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 7px 10px;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  white-space: nowrap;
}
.ft-line.up {
  color: var(--up);
  font-weight: 700;
}
.ft-line.down {
  color: var(--down);
  font-weight: 700;
}
.ft-line.flat {
  color: var(--text-muted);
}
@media (max-width: 1024px) {
  .stat-strip {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
