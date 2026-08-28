<script setup lang="ts">
// 选标的 + 配置日期范围（取行情由父组件在「开始回测/开始寻优」时触发）。
// 市场按 6 位代码智能识别，不再手动选择。
// 后端 /bars 仅支持 count（上限 800，约 3.2 年），固定拉满后前端按日期过滤。
// 默认：结束日=今天（最近交易日），开始日=2020-01-06。

import { computed, ref } from 'vue'

import { CRYPTO_INTERVALS, fetchBars, fetchCryptoBars, fetchExBars, formatError } from '../api'
import { MARKET_OPTIONS, detectExMarket, detectMarket, exMarketParam, marketLabel } from '../market'
import { useBacktestStore } from '../stores/backtest'
import type { Category } from '../types'

const store = useBacktestStore()

// 代码 / 周期 / 日期通过 defineModel 与父组件双向同步：
// 既允许父组件读取（如寻优页「查看」按钮拼 URL 带上这些值），
// 也允许父组件写入（如回测页从 URL query 回填表单）。
// 未绑定时取默认值，向后兼容。
//
// 注意：defineModel 的 default 不能引用本 <script setup> 内声明的局部函数
// （编译期会被 hoist 到 setup() 外，此时函数还未定义），
// 因此日期默认值用内联字面量表达式计算。
const code = defineModel<string>('code', { default: '000001' })
const category = defineModel<Category>('category', { default: 'DAY' })
const startDate = defineModel<string>('startDate', {
  default: '2020-01-06',
})
const endDate = defineModel<string>('endDate', {
  default: new Date().toISOString().slice(0, 10),
})
// 市场选择：'auto' = 按代码自动识别（A股/港股/美股）；显式指定时覆盖自动识别
const marketSel = defineModel<string>('marketSel', { default: 'auto' })

const error = ref('')
// loading 由父组件控制（回测/寻优时驱动），组件自身只暴露 loadBars
const loading = ref(false)

const CATEGORIES: Category[] = ['DAY', 'WEEK', 'MONTH', 'MIN_5', 'MIN_15', 'MIN_30', 'MIN_60']

// 市场选择项：与 StocksPicker 共用 market.ts 的 MARKET_OPTIONS

// 智能识别的市场（用于提示展示）：A 股 6 位数字 / 港股 5 位数字 / 美股字母代码
const exMarket = computed(() => detectExMarket(code.value))
const isAShare = computed(() => /^\d{6}$/.test(code.value))
const detectedMarket = computed(() => {
  if (marketSel.value !== 'auto') {
    return MARKET_OPTIONS.find((o) => o.value === marketSel.value)?.label ?? ''
  }
  if (isAShare.value) return marketLabel(detectMarket(code.value))
  if (exMarket.value) return marketLabel(exMarket.value)
  return ''
})

/** 生效的市场类型（供父组件做回测拦截等决策）。
 * 'A' = A股；'HK'/'US' = 港股/美股（仅行情）；'FUT' = 国内期货（可回测）；
 * 'CRYPTO' = 加密货币（可回测，现货做多）。
 */
const marketType = computed<'A' | 'HK' | 'US' | 'FUT' | 'CRYPTO' | null>(() => {
  const sel = marketSel.value
  if (sel === 'CRYPTO') return 'CRYPTO'
  if (sel === 'HK' || sel === 'US') return sel
  if (sel === 'auto') {
    if (/^\d{6}$/.test(code.value.trim())) return 'A'
    return detectExMarket(code.value)
  }
  return 'FUT'
})

/** 生效的市场标识（/ex/* 用，如 CFFEX_FUTURES；加密为 CRYPTO）；A 股时为 null。 */
const marketName = computed(() => {
  const sel = marketSel.value
  if (sel === 'CRYPTO') return 'CRYPTO'
  if (sel === 'HK' || sel === 'US') return exMarketParam(sel)
  if (sel === 'auto') {
    const ex = detectExMarket(code.value)
    return ex ? exMarketParam(ex) : null
  }
  return sel === 'auto' ? null : sel
})

/** 取行情（由父组件在点击「开始回测/开始寻优」时调用）。
 * 成功返回 true，失败返回 false（并把错误写入 store.error 供父组件感知）。
 *
 * 支持三类标的：
 *   - A 股：6 位数字，走 /bars（分页 + 日期过滤）
 *   - 港股：5 位数字（如 00700），走 /ex/bars（最近 count 根）
 *   - 美股：1-5 位字母（如 TSLA），走 /ex/bars（最近 count 根）
 */
async function loadBars(): Promise<boolean> {
  const sel = marketSel.value
  const trimmed = code.value.trim()
  // 基本校验：auto 模式按格式识别；显式市场模式只要求非空
  if (sel === 'auto') {
    if (!/^\d{6}$/.test(trimmed) && !/^\d{5}$/.test(trimmed) && !/^[A-Za-z]{1,5}$/.test(trimmed)) {
      error.value = '代码格式不正确：A股 6 位数字 / 港股 5 位数字 / 美股 1-5 位字母（期货请选择市场）'
      store.error = error.value
      return false
    }
  } else if (!trimmed) {
    error.value = '请输入代码'
    store.error = error.value
    return false
  }
  if (startDate.value >= endDate.value) {
    error.value = '开始日期必须早于结束日期'
    store.error = error.value
    return false
  }

  loading.value = true
  error.value = ''
  try {
    // 加密货币：走 /api/v1/crypto/bars（Binance 现货）
    if (marketSel.value === 'CRYPTO') {
      const sym = trimmed.toUpperCase().replace(/[\/\-_]/g, '')
      const interval = CRYPTO_INTERVALS[category.value] ?? '1d'
      const bars = await fetchCryptoBars(sym, interval)
      if (bars.length < 2) {
        error.value = `仅取到 ${bars.length} 根 K 线`
        store.error = error.value
        return false
      }
      // 回测引擎按 A 股整手（100 股）成交：BTC 等高价标的需要现金 ≥ 价格×100。
      // 按最新价位数缩放价格（÷10^n）到 A 股价位——收益/胜率/回撤等比率类
      // 指标在等比缩放下数学不变，等效复权处理。
      const lastClose = bars[bars.length - 1]?.close ?? 0
      const digits = lastClose > 0 ? Math.floor(Math.log10(lastClose)) + 1 : 1
      const scale = Math.pow(10, Math.max(0, digits - 3))
      const scaledBars =
        scale > 1
          ? bars.map((b) => ({
              ...b,
              open: b.open / scale,
              high: b.high / scale,
              low: b.low / scale,
              close: b.close / scale,
            }))
          : bars
      store.setOhlcv(
        scaledBars,
        `CRYPTO:${sym} ${category.value} 最近${bars.length}根` +
          (scale > 1 ? `（价格÷${scale} 缩放）` : ''),
      )
      store.clearResult()
      return true
    }

    // 显式选择市场（港股/美股/期货）或 auto 识别到 ex 市场：走 /ex/bars
    const mkt = marketName.value
    if (mkt) {
      const exCode = trimmed.toUpperCase()
      const bars = await fetchExBars(mkt, exCode, category.value)
      if (bars.length < 2) {
        error.value = `仅取到 ${bars.length} 根 K 线`
        store.error = error.value
        return false
      }
      store.setOhlcv(bars, `${mkt}:${exCode} ${category.value} 最近${bars.length}根`)
      store.clearResult()
      return true
    }

    // A 股：分页 + 日期过滤
    const market = detectMarket(trimmed)
    const bars = await fetchBars(
      market,
      trimmed,
      category.value,
      startDate.value,
      endDate.value,
    )
    if (bars.length < 2) {
      error.value = `该日期范围内仅取到 ${bars.length} 根 K 线，不足以回测`
      store.error = error.value
      return false
    }
    const range = `${startDate.value} ~ ${endDate.value}`
    store.setOhlcv(bars, `${market}:${trimmed} ${category.value} ${range}`)
    store.clearResult()
    return true
  } catch (e) {
    error.value = formatError(e)
    store.error = error.value
    return false
  } finally {
    loading.value = false
  }
}

// 暴露给父组件（BacktestView / OptimizeView）在「开始回测/寻优」时串联调用
defineExpose({ loadBars, loading, marketType, marketName })
</script>

<template>
  <div class="symbol-picker">
    <div class="field code-field">
      <label>代码</label>
      <input
        v-model="code"
        maxlength="10"
        placeholder="A股6位/港股5位/美股字母（自动识别）"
      />
      <span v-if="detectedMarket" class="market-tag">{{ detectedMarket }}</span>
    </div>

    <div class="field">
      <label>市场</label>
      <select v-model="marketSel">
        <option v-for="o in MARKET_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
    </div>

    <p v-if="marketType === 'HK' || marketType === 'US'" class="hint">
      美股/港股仅支持行情查看（最近 700 根），暂不支持回测
    </p>
    <p v-else-if="marketType === 'FUT'" class="hint">
      期货支持回测（最近 700 根）；费用按股票模型计算，印花税请设为 0
    </p>
    <p v-else-if="marketType === 'CRYPTO'" class="hint">
      加密货币现货：24/7 交易，回测按现货做多模型（无涨跌停/印花税）；
      高价标的价格自动缩放（比率类指标不受影响）
    </p>

    <div class="field">
      <label>周期</label>
      <select v-model="category">
        <option v-for="c in CATEGORIES" :key="c" :value="c">{{ c }}</option>
      </select>
    </div>

    <div class="row">
      <div class="field">
        <label>开始日期</label>
        <input v-model="startDate" type="date" />
      </div>
      <div class="field">
        <label>结束日期</label>
        <input v-model="endDate" type="date" />
      </div>
    </div>

    <p v-if="error" class="err">{{ error }}</p>
    <p v-if="store.barsSource" class="ok">
      已加载：{{ store.barsSource }}（{{ store.ohlcv.length }} 根）
    </p>
  </div>
</template>

<style scoped>
.code-field {
  position: relative;
}
.code-field input {
  padding-right: 70px;
}
.market-tag {
  position: absolute;
  right: 8px;
  bottom: 8px;
  font-size: 11px;
  color: var(--text-dim);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  padding: 1px 6px;
  border-radius: 3px;
}
.hint {
  font-size: 12px;
  color: var(--text-dim);
  margin-top: 6px;
}
.err {
  color: var(--up);
  font-size: 12px;
  margin-top: 8px;
}
.ok {
  color: var(--down);
  font-size: 12px;
  margin-top: 8px;
}
</style>
