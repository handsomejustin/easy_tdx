<script setup lang="ts">
// 市场情绪（/sentiment）：盘中宽度分时 + 涨停家数历史，回答"今天市场冷还是热"。
// 数据两层：采样器分钟快照（/market/sentiment/*，随使用逐渐积累）
//          + vipdoc 离线回补的逐日涨停/跌停家数（/market/limitup-history，即时可用）。
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

import echarts, { DOWN_COLOR, UP_COLOR } from '../echarts-setup'
import {
  fetchBars,
  fetchBoardFundHistory,
  fetchLimitUpEcology,
  fetchLimitUpHistory,
  fetchMarketStat,
  fetchSentimentHistory,
  fetchSentimentToday,
  formatError,
  runLlmChatWithPolling,
} from '../api'
import { fmtAmount, fmtPctSigned } from '../format'
import type {
  BoardFundDay,
  LimitUpHistoryRow,
  MarketStat,
  SentimentDay,
  SentimentSample,
} from '../types'

const today = ref<{ date: number; count?: number; samples: SentimentSample[] } | null>(null)
const histDays = ref<SentimentDay[]>([])
const luHistory = ref<LimitUpHistoryRow[]>([])
const stat = ref<MarketStat | null>(null)
const error = ref('')
const loading = ref(false)
const lastRefresh = ref('')

async function load() {
  loading.value = today.value === null
  error.value = ''
  try {
    const [t, h, lu, st] = await Promise.all([
      fetchSentimentToday(),
      fetchSentimentHistory(60),
      fetchLimitUpHistory(60),
      fetchMarketStat().catch(() => null),
    ])
    today.value = t
    histDays.value = h.days
    luHistory.value = lu
    stat.value = st
    lastRefresh.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
  // loading 复位触发 v-else-if 切换后，图表容器才挂载到 DOM
  await nextTick()
  render()
}

// ── 温度卡（今日实时 = /market/stat；缺省回退最后一条采样） ───────────────────

const latest = computed(() => {
  const s = today.value?.samples ?? []
  return s.length > 0 ? s[s.length - 1] : null
})

const upRatio = computed(() => {
  const s = stat.value
  if (s && s.up_count + s.down_count > 0) {
    return (100 * s.up_count) / (s.up_count + s.down_count)
  }
  return latest.value?.up_ratio ?? null
})

const limitUpNow = computed(() => stat.value?.limit_up_count ?? latest.value?.limit_up_count ?? null)
const limitDownNow = computed(
  () => stat.value?.limit_down_count ?? latest.value?.limit_down_count ?? null,
)
const amountNow = computed(() => stat.value?.total_amount ?? latest.value?.total_amount ?? null)

/** 情绪判定：上涨占比 + 涨跌停差 粗分五档 */
const mood = computed(() => {
  const r = upRatio.value
  if (r === null) return { label: '—', cls: 'flat' }
  if (r >= 70) return { label: '普涨 · 情绪高潮', cls: 'up' }
  if (r >= 55) return { label: '偏暖', cls: 'up' }
  if (r > 45) return { label: '均衡', cls: 'flat' }
  if (r > 30) return { label: '偏冷', cls: 'down' }
  return { label: '普跌 · 情绪冰点', cls: 'down' }
})

// ── 图表 ─────────────────────────────────────────────────────────────────────

const todayEl = ref<HTMLDivElement>()
const histEl = ref<HTMLDivElement>()
let todayChart: echarts.ECharts | null = null
let histChart: echarts.ECharts | null = null

function hm(minute: number): string {
  return `${String(Math.floor(minute / 100)).padStart(2, '0')}:${String(minute % 100).padStart(2, '0')}`
}

function render() {
  renderToday()
  renderHistory()
}

function renderToday() {
  if (!todayEl.value) return
  todayChart ??= echarts.init(todayEl.value, 'dark')
  const samples = today.value?.samples ?? []
  const x = samples.map((s) => hm(s.minute))
  todayChart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { data: ['上涨家数', '下跌家数', '涨停家数'], top: 0 },
      grid: { left: 60, right: 60, top: 30, bottom: 30 },
      xAxis: { type: 'category', data: x, boundaryGap: false },
      yAxis: [
        { type: 'value', name: '家数', scale: true, splitLine: { lineStyle: { color: '#2a2e3a' } } },
        { type: 'value', name: '涨停', scale: true, position: 'right', splitLine: { show: false } },
      ],
      series: [
        {
          name: '上涨家数',
          type: 'line',
          data: samples.map((s) => s.up_count),
          showSymbol: false,
          lineStyle: { color: UP_COLOR, width: 2 },
          itemStyle: { color: UP_COLOR },
          areaStyle: { color: 'rgba(239,65,70,0.08)' },
        },
        {
          name: '下跌家数',
          type: 'line',
          data: samples.map((s) => s.down_count),
          showSymbol: false,
          lineStyle: { color: DOWN_COLOR, width: 2 },
          itemStyle: { color: DOWN_COLOR },
        },
        {
          name: '涨停家数',
          type: 'line',
          yAxisIndex: 1,
          data: samples.map((s) => s.limit_up_count),
          showSymbol: false,
          lineStyle: { color: '#f5a623', width: 1.5, type: 'dashed' },
          itemStyle: { color: '#f5a623' },
        },
      ],
    },
    true,
  )
}

function renderHistory() {
  if (!histEl.value) return
  histChart ??= echarts.init(histEl.value, 'dark')
  // 基底 = vipdoc 回补的逐日涨跌停；采样聚合有值的日期叠加上涨占比线
  const lu = luHistory.value
  const sampled = new Map(histDays.value.map((d) => [d.date, d]))
  const x = lu.map((r: LimitUpHistoryRow) => String(r.date).replace(/^(\d{4})(\d{2})(\d{2})$/, '$2-$3'))
  const ratios = lu.map((r) => {
    const d = sampled.get(r.date)
    return d && d.n >= 10 ? d.up_ratio : null // 样本不足的交易日不画占比线
  })
  histChart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { data: ['涨停家数', '跌停家数', '上涨占比%'], top: 0 },
      grid: { left: 50, right: 55, top: 30, bottom: 30 },
      xAxis: { type: 'category', data: x },
      yAxis: [
        { type: 'value', name: '家数', splitLine: { lineStyle: { color: '#2a2e3a' } } },
        { type: 'value', name: '上涨占比%', position: 'right', max: 100, splitLine: { show: false } },
      ],
      series: [
        {
          name: '涨停家数',
          type: 'bar',
          data: lu.map((r) => r.limit_up),
          itemStyle: { color: UP_COLOR },
          barMaxWidth: 8,
        },
        {
          name: '跌停家数',
          type: 'bar',
          data: lu.map((r) => -r.limit_down),
          itemStyle: { color: DOWN_COLOR },
          barMaxWidth: 8,
          tooltip: { valueFormatter: (v: number) => String(Math.abs(Number(v))) },
        },
        {
          name: '上涨占比%',
          type: 'line',
          yAxisIndex: 1,
          data: ratios,
          connectNulls: false,
          showSymbol: false,
          lineStyle: { color: '#f5a623', width: 2 },
          itemStyle: { color: '#f5a623' },
        },
      ],
    },
    true,
  )
}

function onResize() {
  todayChart?.resize()
  histChart?.resize()
  volChart?.resize()
}

// ── ⑧ 量能仪表盘：两市累计成交额（最近交易日）vs 近 5 日同期均值 ─────────────

const volEl = ref<HTMLDivElement>()
let volChart: echarts.ECharts | null = null
const volRatio = ref<number | null>(null)
const volDate = ref('')
const fundDays = ref<BoardFundDay[]>([])

async function loadVolume() {
  try {
    const start = new Date(Date.now() - 14 * 86400_000).toISOString().slice(0, 10)
    const [sh, sz] = await Promise.all([
      fetchBars('SH', '000001', 'MIN_5', start),
      fetchBars('SZ', '399001', 'MIN_5', start),
    ])
    // 按日期聚合两市场 5 分钟 amount（元）
    const byDate = new Map<string, Map<string, number>>()
    for (const b of [...sh, ...sz]) {
      const d = b.datetime.slice(0, 10)
      const t = b.datetime.slice(11, 16)
      if (!d || !t) continue
      const slot = byDate.get(d) ?? new Map<string, number>()
      slot.set(t, (slot.get(t) ?? 0) + Number(b.amount ?? 0))
      byDate.set(d, slot)
    }
    const dates = [...byDate.keys()].sort()
    if (dates.length < 2) return
    volDate.value = dates[dates.length - 1]
    const cur = byDate.get(volDate.value)!
    const prevDates = dates.slice(-6, -1)
    const times = [...cur.keys()].sort()

    const cumAt = (m: Map<string, number>, upto: number): number => {
      let s = 0
      for (let i = 0; i <= upto; i++) s += m.get(times[i]) ?? 0
      return s / 1e12 // 万亿
    }
    const todayCurve = times.map((_, i) => cumAt(cur, i))
    const baseCurve = times.map((_, i) => {
      let s = 0
      let n = 0
      for (const d of prevDates) {
        const m = byDate.get(d)
        if (!m) continue
        s += cumAt(m, i)
        n += 1
      }
      return n ? s / n : null
    })

    const lastT = todayCurve[todayCurve.length - 1]
    const lastB = baseCurve[baseCurve.length - 1]
    volRatio.value = lastB && lastB > 0 ? ((lastT - lastB) / lastB) * 100 : null

    volChart ??= echarts.init(volEl.value!, 'dark')
    volChart.setOption(
      {
        backgroundColor: 'transparent',
        tooltip: {
          trigger: 'axis',
          valueFormatter: (v: number | string) => fmtAmount(Number(v) * 1e12),
        },
        legend: { data: ['最近交易日累计', '近 5 日同期均值'], top: 0 },
        grid: { left: 60, right: 20, top: 30, bottom: 30 },
        xAxis: { type: 'category', data: times },
        yAxis: {
          type: 'value',
          name: '万亿',
          scale: true,
          splitLine: { lineStyle: { color: '#2a2e3a' } },
          axisLabel: { formatter: (v: number) => v.toFixed(1) },
        },
        series: [
          {
            name: '最近交易日累计',
            type: 'line',
            data: todayCurve,
            showSymbol: false,
            lineStyle: { color: UP_COLOR, width: 2 },
            itemStyle: { color: UP_COLOR },
            areaStyle: { color: 'rgba(239,65,70,0.08)' },
          },
          {
            name: '近 5 日同期均值',
            type: 'line',
            data: baseCurve,
            showSymbol: false,
            lineStyle: { color: '#8b919e', width: 1.5, type: 'dashed' },
            itemStyle: { color: '#8b919e' },
          },
        ],
      },
      true,
    )
  } catch {
    volRatio.value = null // 量能图独立降级
  }
}

async function loadFund() {
  try {
    fundDays.value = await fetchBoardFundHistory(15)
  } catch {
    fundDays.value = [] // 资金日历独立降级
  }
}


let timer = 0

// ── ⑩ AI 盘面复盘：自动汇总上方数据 → LLM 生成 → 自动归档「AI 解读历史」 ─────

const aiReply = ref('')
const aiBusy = ref(false)
const aiError = ref('')
const aiModel = ref('')

async function buildDigest(): Promise<string> {
  const lines: string[] = []
  const s = stat.value
  if (s) {
    const denom = Math.max(s.up_count + s.down_count, 1)
    lines.push(
      `上涨 ${s.up_count} 家 / 下跌 ${s.down_count} 家（上涨占比 ${((100 * s.up_count) / denom).toFixed(1)}%），` +
        `涨停 ${s.limit_up_count} 家，跌停 ${s.limit_down_count} 家，两市成交 ${fmtAmount(s.total_amount)}。`,
    )
  }
  if (volRatio.value !== null) {
    lines.push(`量能：当日两市累计成交较近 5 日同期均值 ${fmtPctSigned(volRatio.value)}。`)
  }
  try {
    const eco = await fetchLimitUpEcology()
    const sm = eco.summary
    lines.push(`连板高度 ${sm.max_streak} 板（首板 ${sm.first_board}、二板 ${sm.second_board}、3 板以上 ${sm.plus3}），炸板率 ${sm.blown_rate ?? '-'}%。`)
  } catch {
    // 涨停生态不可用时跳过该维度
  }
  const lu = luHistory.value.slice(-5)
  if (lu.length) {
    lines.push(
      `近 5 日涨停家数：${lu.map((r) => `${String(r.date).slice(4, 6)}-${String(r.date).slice(6, 8)} ${r.limit_up}`).join('；')}。`,
    )
  }
  const sampled = histDays.value.filter((d) => d.n >= 10).slice(-5)
  if (sampled.length) {
    lines.push(
      `采样上涨占比：${sampled.map((d) => `${String(d.date).slice(4, 6)}-${String(d.date).slice(6, 8)} ${d.up_ratio}%`).join('；')}。`,
    )
  }
  if (lines.length === 0) return ''
  return `以下是最新的 A 股盘面数据摘要：\n${lines.join('\n')}\n\n` +
    '请以资深市场分析师的口吻写一段 200~400 字的盘面复盘，依次覆盖：1) 市场情绪与赚钱效应；' +
    '2) 量能特征（放量/缩量及其含义）；3) 涨停梯队与炸板率反映的题材热度与分歧；4) 结尾一句风险提示。' +
    '直接给观点和逻辑，不要复述数据。'
}

async function generateReview() {
  aiBusy.value = true
  aiError.value = ''
  aiReply.value = ''
  try {
    const digest = await buildDigest()
    if (!digest) {
      aiError.value = '暂无盘面数据可生成复盘'
      return
    }
    const state = await runLlmChatWithPolling(digest)
    if (state.status === 'failed') {
      throw new Error(String((state as { error?: string }).error ?? 'AI 解读任务失败'))
    }
    const result = state.result as { reply?: string; model?: string }
    aiReply.value = result.reply ?? ''
    aiModel.value = result.model ?? ''
  } catch (e) {
    aiError.value = formatError(e)
  } finally {
    aiBusy.value = false
  }
}

onMounted(async () => {
  await load()
  loadVolume()
  loadFund()
  timer = window.setInterval(() => {
    if (document.hidden) return
    load()
  }, 60_000)
  window.addEventListener('resize', onResize)
})
onBeforeUnmount(() => {
  window.clearInterval(timer)
  window.removeEventListener('resize', onResize)
  todayChart?.dispose()
  histChart?.dispose()
  volChart?.dispose()
})
</script>

<template>
  <div class="sentiment-view">
    <div class="view-head">
      <h2>市场情绪</h2>
      <span class="dim head-sub">宽度 · 涨停温度计</span>
      <span class="tb-spacer"></span>
      <span v-if="lastRefresh" class="dim refresh-ts">{{ lastRefresh }}</span>
      <button class="manual-refresh" @click="load">↻ 刷新</button>
    </div>

    <div v-if="error" class="err card">
      加载失败：{{ error }}
      <button @click="load">重试</button>
    </div>
    <div v-else-if="loading" class="loading">加载中…</div>

    <template v-else>
      <!-- 温度卡 -->
      <div class="stat-strip">
        <div class="stat-card card">
          <div class="stat-title">上涨占比</div>
          <div class="stat-main mono" :class="mood.cls">{{ upRatio === null ? '-' : upRatio.toFixed(1) + '%' }}</div>
          <div class="stat-sub" :class="mood.cls">{{ mood.label }}</div>
        </div>
        <div class="stat-card card">
          <div class="stat-title">涨停 / 跌停</div>
          <div class="stat-main">
            <span class="up">{{ limitUpNow ?? '-' }}</span>
            <span class="dim"> / </span>
            <span class="down">{{ limitDownNow ?? '-' }}</span>
          </div>
        </div>
        <div class="stat-card card">
          <div class="stat-title">今日总成交</div>
          <div class="stat-main">{{ fmtAmount(amountNow) }}</div>
        </div>
        <div class="stat-card card">
          <div class="stat-title">今日采样点</div>
          <div class="stat-main">{{ today?.count ?? 0 }} <span class="unit">个</span></div>
          <div class="stat-sub dim">交易时段每分钟一条 · 持续积累</div>
        </div>
      </div>

      <!-- 今日宽度分时 -->
      <div class="section">
        <div class="sec-title">今日宽度分时</div>
        <div class="card chart-card">
          <div ref="todayEl" class="chart"></div>
          <div v-if="(today?.samples?.length ?? 0) === 0" class="empty-hint dim">
            今日尚无采样数据。采样器在交易时段每分钟落一条，服务持续运行后曲线自动成形。
          </div>
        </div>
      </div>

      <!-- 量能仪表盘 -->
      <div class="section">
        <div class="sec-title">
          量能 · 两市累计成交额（最近交易日{{ volDate ? ` ${volDate.slice(5)}` : '' }} vs 近 5 日同期均值
          <span v-if="volRatio !== null" :class="volRatio > 0 ? 'up' : 'down'">{{ fmtPctSigned(volRatio) }}</span>）
        </div>
        <div class="card chart-card">
          <div ref="volEl" class="chart"></div>
        </div>
      </div>

      <!-- 板块主力资金日历 -->
      <div class="section">
        <div class="sec-title">行业主力资金 · 每日净流入 Top 10（交易日 14:45 后采样，需积累）</div>
        <div class="card fund-card">
          <div v-for="d in fundDays" :key="d.date" class="fund-row">
            <span class="mono dim fund-date">{{ String(d.date).slice(4, 6) }}-{{ String(d.date).slice(6, 8) }}</span>
            <span v-for="b in d.boards" :key="b.code" class="fund-chip mono">
              {{ b.name }} <span class="up">+{{ (b.main_net / 1e8).toFixed(1) }}亿</span>
            </span>
          </div>
          <div v-if="fundDays.length === 0" class="empty-hint dim">
            尚无采样：每个交易日的 14:45 后自动记录一次行业主力净流入排行（涨幅前 50 名口径），持续运行后日历成形。
          </div>
        </div>
      </div>

      <!-- AI 盘面复盘 -->
      <div class="section">
        <div class="sec-title-ai">
          AI 盘面复盘
          <button class="gen-btn" :disabled="aiBusy" @click="generateReview">
            {{ aiBusy ? '生成中…（约 1~3 分钟）' : aiReply ? '重新生成' : '生成 AI 复盘' }}
          </button>
          <span v-if="aiModel" class="dim">{{ aiModel }}</span>
        </div>
        <div class="card ai-card">
          <div v-if="aiBusy" class="dim">模型基于上方情绪 / 量能 / 涨停数据生成中…</div>
          <div v-else-if="aiError" class="up">{{ aiError }}</div>
          <div v-else-if="aiReply" class="ai-reply">{{ aiReply }}</div>
          <div v-else class="dim">
            汇总本页情绪 / 量能 / 涨停数据交给已配置的模型生成复盘，自动归档到「AI 解读历史」。
          </div>
        </div>
      </div>

      <!-- 近 60 日情绪 -->
      <div class="section">
        <div class="sec-title">近 60 日 · 涨停/跌停家数（vipdoc 回补）与上涨占比（采样积累）</div>
        <div class="card chart-card">
          <div ref="histEl" class="chart-lg"></div>
          <div v-if="luHistory.length === 0" class="empty-hint dim">
            未检测到本地 vipdoc 数据，历史涨停家数不可用。
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sentiment-view {
  height: 100%;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.view-head,
.stat-strip,
.err,
.loading,
.section {
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
.tb-spacer {
  flex: 1;
}
.refresh-ts {
  font-family: var(--font-mono);
  font-size: 11.5px;
}
.manual-refresh {
  font-size: 12px;
  padding: 4px 10px;
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
.stat-sub {
  font-size: 11.5px;
  margin-top: 2px;
}
.stat-sub.up,
.stat-main.up {
  color: var(--up);
}
.stat-sub.down,
.stat-main.down {
  color: var(--down);
}
.stat-sub.flat,
.stat-main.flat {
  color: var(--text-muted);
}
.section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sec-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-muted);
}
.sec-title-ai {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-muted);
}
.gen-btn {
  font-size: 11.5px;
  padding: 3px 12px;
}
.gen-btn:disabled {
  opacity: 0.6;
}
.fund-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  padding: 10px 12px;
}
.fund-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.fund-date {
  width: 44px;
  flex-shrink: 0;
}
.fund-chip {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
}
.ai-card {
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
}
.chart-card {
  padding: 8px;
  position: relative;
}
.chart {
  height: 260px;
}
.chart-lg {
  height: 300px;
}
.empty-hint {
  position: absolute;
  inset: 0;
  pointer-events: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  padding: 0 40px;
  text-align: center;
}
@media (max-width: 1024px) {
  .stat-strip {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
