<script setup lang="ts">
// 自选行情：SSE 实时表格 + 行内迷你分时 + 一键加删 + 点击开个股对话框。
// 迷你分时按需懒加载（行可见时才拉 /minute，60s 重拉）——这里简化为
// 打开页面时批量拉前 N 只（80/批上限内），足够 MVP。

import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  addWatchItem,
  fetchMinute,
  fetchQuotes,
  fetchSymbolName,
  fetchWatchlist,
  formatError,
  removeWatchItem,
} from '../api'
import StockDialog from '../components/StockDialog.vue'
import BoardDialog from '../components/BoardDialog.vue'
import Sparkline from '../components/Sparkline.vue'
import { dirClass, fmt2, fmtAmount, fmtPctSigned, fmtVol } from '../format'
import { detectMarket } from '../market'
import { useQuoteStore } from '../stores/quotes'
import type { WatchItem } from '../types'

const quoteStore = useQuoteStore()

/** 板块指数（881/885/880 开头）走板块弹窗，其余走个股弹窗。 */
function isBoardCode(code: string): boolean {
  return /^88\d/.test(code)
}

const items = ref<WatchItem[]>([])
const listError = ref('')
const adding = ref(false)
const addCode = ref('')
const addName = ref('')

// ── 列表加载 ────────────────────────────────────────────────────────────────

async function loadList() {
  listError.value = ''
  try {
    const resp = await fetchWatchlist()
    items.value = resp.items
    loadSparks()
    restFallback()
    fillMissingNames()
  } catch (e) {
    listError.value = formatError(e)
  }
}

/** 给历史遗留的"只有代码没有名称"的自选项补中文名（幂等写回存储）。 */
async function fillMissingNames() {
  const missing = items.value.filter((i) => !i.name)
  for (const it of missing) {
    const name = await fetchSymbolName(it.market, it.code)
    if (name) {
      it.name = name
      try {
        await addWatchItem(it.market, it.code, name)
      } catch {
        // 写回失败仅影响下次加载，静默
      }
    }
  }
}

// ── 行情（SSE 快照 + REST 首次兜底） ────────────────────────────────────────

/** SSE 未覆盖时（自选刚加、服务重启间隙）用 REST 主动拉一次。 */
async function restFallback() {
  if (items.value.length === 0) return
  const missing = items.value.filter((i) => !quoteStore.getQuote(i.symbol))
  if (missing.length === 0) return
  try {
    await fetchQuotes(missing.map((i) => ({ market: i.market, code: i.code })))
  } catch {
    // SSE 会补上，静默
  }
}

function q(item: WatchItem) {
  return quoteStore.getQuote(item.symbol)
}

function pct(item: WatchItem): number | null {
  const qq = q(item)
  if (!qq?.price || !qq.pre_close) return null
  return (qq.price / qq.pre_close - 1) * 100
}

// ── 迷你分时 ────────────────────────────────────────────────────────────────

const sparks = ref(new Map<string, number[]>())
const sparkBase = ref(new Map<string, number>())

async function loadSparks() {
  const targets = items.value.slice(0, 80)
  for (const it of targets) {
    if (sparks.value.has(it.symbol)) continue
    try {
      const pts = await fetchMinute(it.market, it.code)
      if (pts.length > 0) {
        sparks.value.set(it.symbol, pts.map((p) => p.price))
        const qq = q(it)
        sparkBase.value.set(it.symbol, qq?.pre_close ?? pts[0].price)
      }
    } catch {
      // 单只失败不影响整表
    }
  }
}

let sparkTimer = 0
onMounted(() => {
  loadList()
  sparkTimer = window.setInterval(loadSparks, 60_000)
})
onBeforeUnmount(() => window.clearInterval(sparkTimer))

// ── 加/删自选 ───────────────────────────────────────────────────────────────

async function add() {
  const code = addCode.value.trim()
  if (!/^\d{6}$/.test(code)) {
    listError.value = '请输入 6 位数字代码'
    return
  }
  const market = detectMarket(code)
  adding.value = true
  listError.value = ''
  try {
    // 名称优先级：用户备注 > 证券名称接口（五档行情协议本身不带名称）。
    // 名称取不到不阻断（BJ 等市场 MAC 协议可能不支持），退回显示代码。
    let name = addName.value.trim()
    if (!name) name = await fetchSymbolName(market, code)
    try {
      const quotes = await fetchQuotes([{ market, code }])
      const qq = quotes[0]
      if (qq && qq.price == null) {
        listError.value = `提示：${market}${code} 暂无行情返回，仍已加入自选`
      } else if (qq && Number.isFinite(qq.vol) && qq.vol === 0 && qq.amount === 0) {
        listError.value = `提示：${market}${code} 今日无成交（停牌或非交易日），仍已加入自选`
      }
    } catch {
      listError.value = `提示：行情校验不可用，${market}${code} 仍已加入自选`
    }
    await addWatchItem(market, code, name)
    addCode.value = ''
    addName.value = ''
    await loadList()
  } catch (e) {
    listError.value = formatError(e)
  } finally {
    adding.value = false
  }
}

async function remove(item: WatchItem) {
  listError.value = ''
  try {
    await removeWatchItem(item.market, item.code)
    items.value = items.value.filter((i) => i.symbol !== item.symbol)
    sparks.value.delete(item.symbol)
  } catch (e) {
    listError.value = formatError(e)
  }
}

// ── 弹窗（个股 / 板块分流） ─────────────────────────────────────────────────

const dialog = ref<WatchItem | null>(null)
const boardDlg = ref<WatchItem | null>(null)

function openItem(item: WatchItem) {
  if (isBoardCode(item.code)) boardDlg.value = item
  else dialog.value = item
}

const emptyHint = computed(() =>
  items.value.length === 0 && !listError.value
    ? '自选为空：输入 6 位代码加入（如 600519）。加入后行情实时推送。'
    : '',
)
</script>

<template>
  <div class="wl">
    <div class="toolbar">
      <h2>自选行情</h2>
      <div class="add-row">
        <input v-model="addCode" class="code-input" placeholder="6 位代码" maxlength="6" @keyup.enter="add" />
        <input v-model="addName" class="name-input" placeholder="备注名（可空）" maxlength="16" @keyup.enter="add" />
        <button class="primary" :disabled="adding" @click="add">{{ adding ? '加入中…' : '加入自选' }}</button>
      </div>
      <span class="hint">共 {{ items.length }} 只 · 行情实时推送</span>
    </div>

    <div v-if="listError" class="err">{{ listError }}</div>

    <div class="table-wrap">
      <table class="qtable">
        <thead>
          <tr>
            <th>名称</th>
            <th>现价</th>
            <th>涨跌幅</th>
            <th>涨跌额</th>
            <th>成交量</th>
            <th>成交额</th>
            <th>最高</th>
            <th>最低</th>
            <th>今开</th>
            <th>昨收</th>
            <th>分时</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="emptyHint" class="empty-row">
            <td colspan="12">{{ emptyHint }}</td>
          </tr>
          <tr v-for="item in items" :key="item.symbol" class="data-row" @click="openItem(item)">
            <td>
              <div class="cell-name">{{ item.name || item.code }}</div>
              <div class="cell-code mono dim">{{ item.symbol }}</div>
            </td>
            <td class="big" :class="dirClass(pct(item))">{{ fmt2(q(item)?.price) }}</td>
            <td :class="dirClass(pct(item))">{{ fmtPctSigned(pct(item)) }}</td>
            <td :class="dirClass(pct(item))">
              {{ q(item)?.price && q(item)?.pre_close ? fmt2(q(item)!.price! - q(item)!.pre_close!) : '-' }}
            </td>
            <td>{{ fmtVol(q(item)?.vol) }}</td>
            <td>{{ fmtAmount(q(item)?.amount) }}</td>
            <td>{{ fmt2(q(item)?.high) }}</td>
            <td>{{ fmt2(q(item)?.low) }}</td>
            <td>{{ fmt2(q(item)?.open) }}</td>
            <td class="dim">{{ fmt2(q(item)?.pre_close) }}</td>
            <td>
              <Sparkline :prices="sparks.get(item.symbol) ?? []" :base="sparkBase.get(item.symbol) ?? null" />
            </td>
            <td>
              <button class="del" @click.stop="remove(item)">✕</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <StockDialog
      v-if="dialog"
      :market="dialog.market"
      :code="dialog.code"
      :name="dialog.name"
      @close="dialog = null"
      @watchlist-changed="loadList"
    />
    <BoardDialog
      v-if="boardDlg"
      :code="boardDlg.code"
      :name="boardDlg.name || boardDlg.code"
      @close="boardDlg = null"
      @watchlist-changed="loadList"
    />
  </div>
</template>

<style scoped>
.wl {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 14px 16px;
  gap: 10px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.toolbar h2 {
  font-size: 16px;
}
.add-row {
  display: flex;
  gap: 8px;
}
.code-input {
  width: 110px;
}
.name-input {
  width: 140px;
}
.hint {
  font-size: 12px;
  color: var(--text-dim);
  margin-left: auto;
}
.err {
  color: var(--up);
  font-size: 12px;
}
.table-wrap {
  flex: 1;
  overflow: auto;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
.data-row {
  cursor: pointer;
}
.data-row:hover {
  background: var(--bg-elevated);
}
.cell-name {
  font-weight: 600;
}
.cell-code {
  font-size: 11px;
}
.big {
  font-size: 14px;
  font-weight: 700;
}
.empty-row td {
  text-align: center;
  color: var(--text-dim);
  padding: 40px 0;
  font-size: 13px;
}
.del {
  padding: 1px 7px;
  font-size: 11px;
  color: var(--text-dim);
  border: none;
  background: transparent;
}
.del:hover {
  color: var(--up);
}
.dim {
  color: var(--text-dim);
}
</style>
