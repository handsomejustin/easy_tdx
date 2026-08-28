<script setup lang="ts">
// 多标的输入（组合回测用）。支持 A 股（自动识别）+ 港股/美股/期货/加密货币。

import { computed, ref } from 'vue'

import { MARKET_OPTIONS, detectMarket as detectMarketSafe, marketLabel, marketPrefix } from '../market'

const props = defineProps<{
  modelValue: string[]
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

const code = ref('')
const marketSel = ref('auto')

const detectedMarket = computed(() => {
  if (marketSel.value !== 'auto') {
    return MARKET_OPTIONS.find((o) => o.value === marketSel.value)?.label ?? ''
  }
  const c = code.value.trim()
  if (/^\d{6}$/.test(c)) return marketLabel(detectMarketSafe(c))
  if (/^\d{5}$/.test(c)) return '港股'
  if (/^[A-Za-z]{1,5}$/.test(c)) return '美股'
  return ''
})

function add() {
  const sym = marketPrefix(marketSel.value, code.value)
  if (!sym) return
  if (!props.modelValue.includes(sym)) {
    emit('update:modelValue', [...props.modelValue, sym])
  }
  code.value = ''
}

function remove(sym: string) {
  emit('update:modelValue', props.modelValue.filter((s) => s !== sym))
}
</script>

<template>
  <div class="stocks-picker">
    <div class="row add-row">
      <select v-model="marketSel" class="market-sel">
        <option v-for="o in MARKET_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <input
        v-model="code"
        maxlength="10"
        placeholder="代码（A股6位/港股5位/美股字母/期货/加密）"
        @keyup.enter="add"
      />
      <button @click="add">添加</button>
    </div>
    <p v-if="detectedMarket" class="market-hint">将识别为：{{ detectedMarket }}</p>

    <div v-if="modelValue.length" class="stock-list">
      <span v-for="s in modelValue" :key="s" class="stock-tag">
        {{ s }}
        <button class="remove" @click="remove(s)">×</button>
      </span>
    </div>
    <p v-else class="hint">至少添加 1 只标的</p>
  </div>
</template>

<style scoped>
.add-row {
  display: flex;
  gap: 6px;
}
.add-row input {
  flex: 1;
}
.market-sel {
  max-width: 130px;
}
.market-hint {
  color: var(--text-dim);
  font-size: 11px;
  margin-top: 4px;
}
.stock-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.stock-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-family: var(--font-mono);
}
.remove {
  border: none;
  background: none;
  color: var(--text-dim);
  padding: 0 2px;
  font-size: 14px;
  line-height: 1;
}
.remove:hover {
  color: var(--up);
}
.hint {
  color: var(--text-dim);
  font-size: 11px;
  margin-top: 8px;
}
</style>
