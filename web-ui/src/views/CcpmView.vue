<script setup lang="ts">
// 中金所成交持仓排名页（ccpm）：官网每日收盘后约 16:15 发布的
// 「成交量 / 持买单量 / 持卖单量」前 20 名会员数据。
// 下拉选品种 + 日期选择器 + 一键采集；附新手科普（品种含义 + 多空/加减仓解读）。
import { computed, onMounted, ref } from 'vue'
import { fetchCcpmProducts, fetchCcpmRank, formatError } from '../api'
import type { CcpmProductMeta, CcpmRankResponse, CcpmRankRow } from '../types'
import HelpCollapse from '../components/HelpCollapse.vue'
import RiskDisclaimer from '../components/RiskDisclaimer.vue'

const products = ref<CcpmProductMeta[]>([])
const product = ref('IF')
const tradeDate = ref(todayIso())
const autoDate = ref(true) // ☑ 自动取最近有数据的交易日（不传 date，后端自动回溯）
const loading = ref(false)
const error = ref('')
const resp = ref<CcpmRankResponse | null>(null)
const activeInstrument = ref('')

onMounted(async () => {
  try {
    const body = await fetchCcpmProducts()
    products.value = body.products
  } catch (e) {
    error.value = formatError(e)
    return
  }
  await load()
})

function todayIso(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    resp.value = await fetchCcpmRank(product.value, autoDate.value ? undefined : tradeDate.value)
    const insts = instruments.value
    activeInstrument.value = domInstruments.value[0] ?? insts[0] ?? ''
  } catch (e) {
    resp.value = null
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

const productMeta = computed(
  () => products.value.find((p) => p.code === product.value) ?? null,
)

/** 全部合约（升序）。 */
const instruments = computed(() => {
  if (!resp.value) return []
  return [...new Set(resp.value.data.map((r) => r.instrument))].sort()
})

/** 主力合约 = 当日前 20 名合计成交量最大的合约，放第一个页签。 */
const domInstruments = computed(() => {
  if (!resp.value) return []
  const volByInst = new Map<string, number>()
  for (const r of resp.value.data) {
    volByInst.set(r.instrument, (volByInst.get(r.instrument) ?? 0) + (r.vol ?? 0))
  }
  const dom = [...volByInst.entries()].sort((a, b) => b[1] - a[1])[0]?.[0]
  if (!dom) return []
  return [dom]
})

const isDom = (inst: string) => domInstruments.value[0] === inst

const currentRows = computed(() => {
  if (!resp.value) return []
  return resp.value.data
    .filter((r) => r.instrument === activeInstrument.value)
    .sort((a, b) => a.rank - b.rank)
})

/** 当前合约前 20 名合计（净持仓 = 多单合计 − 空单合计）。 */
const totals = computed(() => {
  const rows = currentRows.value
  const sum = (f: (r: CcpmRankRow) => number | null) =>
    rows.reduce((acc, r) => acc + (f(r) ?? 0), 0)
  const long = sum((r) => r.long_pos)
  const short = sum((r) => r.short_pos)
  return {
    vol: sum((r) => r.vol),
    volChg: sum((r) => r.vol_chg),
    long,
    longChg: sum((r) => r.long_chg),
    short,
    shortChg: sum((r) => r.short_chg),
    net: long - short,
    netChg: sum((r) => r.long_chg) - sum((r) => r.short_chg),
  }
})

function fmt(n: number | null | undefined): string {
  return n === null || n === undefined ? '—' : n.toLocaleString('zh-CN')
}

function fmtChg(n: number | null | undefined): string {
  if (n === null || n === undefined || n === 0) return n === 0 ? '0' : '—'
  return (n > 0 ? '+' : '') + n.toLocaleString('zh-CN')
}

function chgCls(n: number | null | undefined): string {
  if (n === null || n === undefined || n === 0) return 'flat'
  return n > 0 ? 'up' : 'down'
}

/** 交易日 YYYYMMDD → 展示（2026年9月2日）。 */
const dayLabel = computed(() => {
  const d = resp.value?.trading_day ?? ''
  if (d.length !== 8) return d
  return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`
})
</script>

<template>
  <div class="ccpm-view">
    <div class="toolbar">
      <h2>中金所成交持仓排名</h2>
      <div class="controls">
        <select v-model="product" :disabled="loading" title="选择品种">
          <option v-for="p in products" :key="p.code" :value="p.code">
            {{ p.code }} · {{ p.name }}
          </option>
        </select>
        <label class="auto-date" title="勾选后忽略下方日期，自动回溯到最近一个有数据的交易日">
          <input v-model="autoDate" type="checkbox" />
          自动取最近交易日
        </label>
        <input
          v-model="tradeDate"
          type="date"
          :disabled="loading || autoDate"
          title="交易日（每个交易日收盘后约 16:15 生成数据）"
        />
        <button class="primary" :disabled="loading" @click="load">
          {{ loading ? '采集中…' : '⟳ 采集数据' }}
        </button>
      </div>
    </div>

    <p class="hint">
      数据来自中国金融期货交易所官网「成交持仓排名」，每个交易日收盘后约 <strong>16:15</strong>
      发布：按品种按合约，统计<strong>成交量 / 持买单量（多单）/ 持卖单量（空单）各前 20
      名期货公司会员</strong>。首次采集会实时抓取官网并缓存到本地，同一天再次查看不再联网。
    </p>

    <!-- 品种信息卡：跟随下拉框切换 -->
    <div v-if="productMeta" class="product-card">
      <div class="pc-head">
        <span class="pc-code mono">{{ productMeta.code }}</span>
        <span class="pc-name">{{ productMeta.name }}</span>
        <span class="pc-cat">{{ productMeta.category }}</span>
      </div>
      <div class="pc-body">
        <div class="pc-row">
          <span class="pc-k">标的</span><span>{{ productMeta.underlying }}</span>
        </div>
        <div class="pc-row">
          <span class="pc-k">合约规模</span><span>{{ productMeta.unit }}</span>
        </div>
        <div class="pc-row"><span class="pc-k">一句话</span><span>{{ productMeta.intro }}</span></div>
      </div>
    </div>

    <div v-if="error" class="error-banner">
      ⚠ {{ error }}
      <span v-if="!autoDate" class="err-tip">（可勾选「自动取最近交易日」自动回溯）</span>
    </div>

    <div v-if="!error && loading" class="empty">采集中，正在从中金所官网拉取…</div>

    <template v-if="resp && !loading">
      <div class="result-head">
        <span class="day mono">交易日 {{ dayLabel }}</span>
        <span class="dim">{{ resp.product_name }} · {{ resp.count }} 行（前 20 名 × {{ instruments.length }} 个合约）</span>
      </div>

      <!-- 合约页签（主力=合计成交量最大的合约，排第一） -->
      <div class="inst-tabs">
        <button
          v-for="inst in instruments"
          :key="inst"
          class="inst-tab mono"
          :class="{ active: inst === activeInstrument }"
          @click="activeInstrument = inst"
        >
          {{ inst }}
          <span v-if="isDom(inst)" class="dom-badge">主力</span>
        </button>
      </div>

      <!-- 前 20 名合计概览 -->
      <div class="stat-chips">
        <div class="chip">
          <span class="chip-k">前20合计·多单</span>
          <span class="chip-v mono">{{ fmt(totals.long) }}</span>
          <span class="chip-d mono" :class="chgCls(totals.longChg)">{{ fmtChg(totals.longChg) }}</span>
        </div>
        <div class="chip">
          <span class="chip-k">前20合计·空单</span>
          <span class="chip-v mono">{{ fmt(totals.short) }}</span>
          <span class="chip-d mono" :class="chgCls(totals.shortChg)">{{ fmtChg(totals.shortChg) }}</span>
        </div>
        <div class="chip chip-net">
          <span class="chip-k">净持仓（多−空）</span>
          <span class="chip-v mono" :class="chgCls(totals.net)">{{ fmtChg(totals.net) }}</span>
          <span class="chip-d mono" :class="chgCls(totals.netChg)">{{ fmtChg(totals.netChg) }}</span>
        </div>
        <div class="chip">
          <span class="chip-k">当日合计成交</span>
          <span class="chip-v mono">{{ fmt(totals.vol) }}</span>
          <span class="chip-d mono" :class="chgCls(totals.volChg)">{{ fmtChg(totals.volChg) }}</span>
        </div>
      </div>

      <!-- 排名表：三类排名并排（与官网同构） -->
      <div class="table-wrap">
        <table class="rank-table">
          <thead>
            <tr>
              <th rowspan="2" class="rank-col">排名</th>
              <th colspan="3" class="g g-vol">成交量排名</th>
              <th colspan="3" class="g g-long">持买单量（多单）排名</th>
              <th colspan="3" class="g g-short">持卖单量（空单）排名</th>
            </tr>
            <tr>
              <th>会员简称</th><th class="num">手数</th><th class="num">增减</th>
              <th>会员简称</th><th class="num">手数</th><th class="num">增减</th>
              <th>会员简称</th><th class="num">手数</th><th class="num">增减</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in currentRows" :key="r.rank">
              <td class="mono dim rank-col">{{ r.rank }}</td>
              <td class="member">{{ r.vol_member ?? '—' }}</td>
              <td class="num mono">{{ fmt(r.vol) }}</td>
              <td class="num mono" :class="chgCls(r.vol_chg)">{{ fmtChg(r.vol_chg) }}</td>
              <td class="member">{{ r.long_member ?? '—' }}</td>
              <td class="num mono">{{ fmt(r.long_pos) }}</td>
              <td class="num mono" :class="chgCls(r.long_chg)">{{ fmtChg(r.long_chg) }}</td>
              <td class="member">{{ r.short_member ?? '—' }}</td>
              <td class="num mono">{{ fmt(r.short_pos) }}</td>
              <td class="num mono" :class="chgCls(r.short_chg)">{{ fmtChg(r.short_chg) }}</td>
            </tr>
          </tbody>
          <tfoot>
            <tr>
              <td class="rank-col dim">合计</td>
              <td class="member dim">前 20 名</td>
              <td class="num mono">{{ fmt(totals.vol) }}</td>
              <td class="num mono" :class="chgCls(totals.volChg)">{{ fmtChg(totals.volChg) }}</td>
              <td class="member dim">前 20 名</td>
              <td class="num mono">{{ fmt(totals.long) }}</td>
              <td class="num mono" :class="chgCls(totals.longChg)">{{ fmtChg(totals.longChg) }}</td>
              <td class="member dim">前 20 名</td>
              <td class="num mono">{{ fmt(totals.short) }}</td>
              <td class="num mono" :class="chgCls(totals.shortChg)">{{ fmtChg(totals.shortChg) }}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </template>

    <!-- ============ 科普 ============ -->
    <HelpCollapse label="这是什么数据？怎么看这张表？">
      <div class="edu">
        <p>
          <strong>数据来源：</strong>中国金融期货交易所（中金所）官网每个交易日收盘后发布的
          「成交持仓排名」。这里的每一行不是某个人，而是<strong>一家期货公司会员名下全部客户的合计</strong>
          ——名称后面的「(代客)」= 代理客户，即该公司<strong>经纪业务客户</strong>的汇总，
          不是期货公司自己的自营盘。
        </p>
        <p>
          <strong>三组排名的含义：</strong>
        </p>
        <ul>
          <li><strong>成交量排名</strong>——当天买卖成交的手数（双向计数：每笔成交买卖双方各记一次）。</li>
          <li><strong>持买单量排名（多单）</strong>——尚未平仓的<strong>买入</strong>合约数，即看涨一方持有的仓位。</li>
          <li><strong>持卖单量排名（空单）</strong>——尚未平仓的<strong>卖出</strong>合约数，即看跌一方持有的仓位。</li>
        </ul>
        <p>
          <strong>「增减」列</strong>= 相比上一个交易日的变化：正数 = 加仓（新开仓多于平仓），
          负数 = 减仓（平仓多于新开仓）。例如某会员空单 −800 = 其客户合计平掉了 800 手空单。
        </p>
        <p>
          <strong>注意口径：</strong>只统计<strong>前 20 名</strong>会员（通常约占全市场六到八成持仓），
          不是全部；同一会员名下的客户里套保、投机、套利混在一起，无法从这张表区分。
        </p>
      </div>
    </HelpCollapse>

    <HelpCollapse label="品种一览：IF / IH / IC / IM / TS / TF / T / TL 是什么？">
      <div class="edu">
        <p>
          中金所的期货分两大类：<strong>股指期货</strong>（跟踪股票指数，用来交易「大盘涨跌」）
          和<strong>国债期货</strong>（跟踪利率，用来交易「利率涨跌」）。合约代码后四位是到期月，
          如 IF2609 = 2026 年 9 月到期的沪深300股指期货。
        </p>
        <table class="edu-table">
          <thead>
            <tr><th>代码</th><th>名称</th><th>跟踪什么</th><th>1 手规模</th><th>代表市场哪一块</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in products" :key="p.code">
              <td class="mono">{{ p.code }}</td>
              <td>{{ p.name }}</td>
              <td>{{ p.underlying }}</td>
              <td>{{ p.unit }}</td>
              <td>{{ p.intro }}</td>
            </tr>
          </tbody>
        </table>
        <p>
          <strong>国债期货补充：</strong>它不跟踪某只指数，标的是「名义标准国债」，
          本质是<strong>利率期货</strong>——价格与市场利率<strong>反向</strong>：
          国债期货涨价 ≈ 市场预期利率下行（债券牛市）；跌价 ≈ 预期利率上行。
          四个品种对应 2 / 5 / 10 / 30 年期限，期限越长对利率越敏感（TL 波动最大）。
        </p>
      </div>
    </HelpCollapse>

    <HelpCollapse label="新手科普：多单、空单、加减仓怎么看？是对冲还是纯多纯空？">
      <div class="edu">
        <p><strong>先理解期货：</strong>期货是「约定未来按某个价格买卖」的合约。今天买入 = 认为未来会涨（<strong>多头</strong>）；今天卖出 = 认为未来会跌（<strong>空头</strong>）。不持有合约也可以先卖（这是期货和股票最大的不同）。</p>
        <p><strong>多单（持买单量）：</strong>已经买入、还没平仓的合约。持有的人分两种——① <strong>看涨投机</strong>：赌指数上涨赚差价；② <strong>多头套保</strong>：未来要买入一篮子股票，先买期货锁定成本。</p>
        <p><strong>空单（持卖单量）：</strong>已经卖出、还没平仓的合约。持有的人也分两种——① <strong>看跌投机</strong>：赌指数下跌；② <strong>套保空单</strong>（最常见！）：机构手里已经拿着股票现货，卖出股指期货来<strong>对冲大盘下跌风险</strong>。量化「中性策略」就是典型：买一篮子股票 + 卖空等值股指期货，赚选股超额收益、剥离大盘涨跌。</p>
        <p>
          <strong>★ 最重要的一点：这张表看不出「对冲」还是「纯做空」！</strong>
          排名只披露期货公司客户合计持仓，不区分目的。股指期货的空单大头通常是机构套保盘，
          <strong>「空单多 / 空单增加」≠ 看空市场</strong>，很多情况下反而说明机构持有大量现货股票。
          把空单直接读成利空，是新手最常见的误读。
        </p>
        <p><strong>加仓 / 减仓（增减列）：</strong>正数 = 加仓，负数 = 减仓。常见组合的含义（仅供参考，非预测）：</p>
        <ul>
          <li><strong>多单增加</strong>：有人新进场做多或多头加码，看涨意愿增强。</li>
          <li><strong>多单减少</strong>：多头获利了结或止损离场。</li>
          <li><strong>空单增加</strong>：新空头进场<strong>或</strong>机构加套保（可能只是现货仓位变大了）。</li>
          <li><strong>空单减少</strong>：空头回补（看跌者买回平仓）<strong>或</strong>套保盘解除（机构卖出股票后不再需要对冲）。</li>
        </ul>
        <p><strong>净持仓：</strong>本页顶部「净持仓（多−空）」= 前 20 名多单合计减空单合计，粗略衡量「头部席位」的多空力量对比：正 = 偏多，负 = 偏空。但它只覆盖前 20 名、且混合了各类目的的仓位，只能作为情绪参考，<strong>不能单独当作涨跌预测</strong>。</p>
        <p><strong>为什么全市场多空永远相等？</strong>期货是零和合约——每有一张多单，必然对应一张空单（你买到的合约就是别人卖出的）。所以看「全市场谁多谁空」没有意义，排名表真正告诉你的是：<strong>仓位集中在哪些期货公司的客户手里、它们在加码还是撤退</strong>。</p>
      </div>
    </HelpCollapse>

    <RiskDisclaimer prominent>
      <strong>⚠ 风险提示与免责声明</strong>
      <p>
        本页面数据来自中金所官网公开披露，仅供量化研究与学习参考。持仓排名仅反映前
        20 名会员客户的仓位分布，不区分套保/投机/套利目的，<strong>不构成任何投资建议，
        不能预测市场涨跌</strong>。期货交易带杠杆，亏损可能超过本金，入市需谨慎，
        据此操作风险自负。
      </p>
    </RiskDisclaimer>
  </div>
</template>

<style scoped>
.ccpm-view {
  height: 100%;
  overflow-y: auto;
  padding: 14px 16px;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.toolbar h2 {
  font-size: 16px;
}
.controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.controls select,
.controls input[type='date'] {
  padding: 6px 8px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  font-size: 13px;
}
.controls select:focus,
.controls input[type='date']:focus {
  outline: none;
  border-color: var(--accent);
}
.controls input[type='date']:disabled {
  opacity: 0.45;
}
.auto-date {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
}
.hint {
  margin: 8px 0 12px;
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.7;
}

/* 品种信息卡 */
.product-card {
  margin-bottom: 12px;
  padding: 10px 14px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
.pc-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 6px;
}
.pc-code {
  font-size: 15px;
  font-weight: 700;
  color: var(--accent);
}
.pc-name {
  font-size: 14px;
  font-weight: 600;
}
.pc-cat {
  font-size: 11px;
  color: var(--text-dim);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 1px 8px;
}
.pc-row {
  display: flex;
  gap: 10px;
  font-size: 12px;
  line-height: 1.8;
  color: var(--text-muted);
}
.pc-k {
  flex-shrink: 0;
  width: 60px;
  color: var(--text-dim);
}

.error-banner {
  padding: 8px 12px;
  background: rgba(244, 67, 54, 0.1);
  border-radius: var(--radius);
  font-size: 12px;
  color: var(--red, #f44336);
}
.err-tip {
  color: var(--text-dim);
}
.empty {
  color: var(--text-dim);
  padding: 40px;
  text-align: center;
  font-size: 13px;
}
.dim {
  color: var(--text-dim);
}
.mono {
  font-family: var(--font-mono);
}

.result-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 13px;
  margin: 6px 0 8px;
}
.day {
  font-weight: 600;
}

/* 合约页签 */
.inst-tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.inst-tab {
  font-size: 13px;
  padding: 4px 12px;
  border-radius: 999px;
}
.inst-tab.active {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(74, 158, 255, 0.1);
}
.dom-badge {
  margin-left: 4px;
  font-size: 10px;
  color: var(--warn);
}

/* 合计概览 chips */
.stat-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.chip {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 6px 12px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 12px;
}
.chip-net {
  border-color: rgba(240, 160, 32, 0.45);
}
.chip-k {
  color: var(--text-dim);
}
.chip-v {
  font-size: 14px;
  font-weight: 600;
}
.chip-d {
  font-size: 11px;
}

/* 排名表 */
.table-wrap {
  overflow-x: auto;
  margin-bottom: 6px;
}
.rank-table {
  width: 100%;
  min-width: 860px;
  border-collapse: collapse;
  font-size: 12.5px;
}
.rank-table th,
.rank-table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: middle;
  white-space: nowrap;
}
.rank-table thead th {
  color: var(--text-dim);
  font-size: 11.5px;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}
.rank-table .g {
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}
.rank-table .g-vol {
  background: rgba(74, 158, 255, 0.06);
}
.rank-table .g-long {
  background: rgba(239, 65, 70, 0.06);
}
.rank-table .g-short {
  background: rgba(24, 160, 88, 0.06);
}
.rank-col {
  width: 40px;
  text-align: center !important;
}
.member {
  min-width: 110px;
}
.num {
  text-align: right !important;
  font-size: 12px;
}
tfoot td {
  border-top: 1px solid var(--border);
  background: var(--bg-panel);
  font-weight: 600;
}
.up {
  color: var(--up);
}
.down {
  color: var(--down);
}
.flat {
  color: var(--text-dim);
}

/* 科普 */
.edu {
  font-size: 12.5px;
  color: var(--text-muted);
  line-height: 1.9;
}
.edu p {
  margin: 6px 0;
}
.edu ul {
  margin: 6px 0 6px 18px;
}
.edu li {
  margin: 3px 0;
}
.edu strong {
  color: var(--text);
}
.edu-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin: 8px 0;
}
.edu-table th,
.edu-table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
  line-height: 1.6;
}
.edu-table th {
  color: var(--text-dim);
  font-weight: 600;
  white-space: nowrap;
}
</style>
