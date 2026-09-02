<script setup lang="ts">
// 核心龙头池页：159 只核心龙头（东财全行业龙头名单，screen universe="core"
// 的同一份数据资产）。支持搜索过滤，点击行弹个股详情。
import { computed, onMounted, ref } from 'vue'
import { fetchCoreLeaders, formatError } from '../api'
import type { CoreLeaderRow } from '../types'
import RiskDisclaimer from '../components/RiskDisclaimer.vue'
import StockDialog from '../components/StockDialog.vue'

const leaders = ref<CoreLeaderRow[]>([])
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const dialog = ref<{ market: string; code: string; name: string } | null>(null)

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    leaders.value = await fetchCoreLeaders()
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return leaders.value
  return leaders.value.filter(
    (r) => r.code.includes(k) || r.name.toLowerCase().includes(k),
  )
})

function openDialog(row: CoreLeaderRow) {
  dialog.value = { market: row.market, code: row.code, name: row.name }
}
</script>

<template>
  <div class="leaders-view">
    <div class="toolbar">
      <h2>核心龙头池 <span class="dim title-sub">（{{ leaders.length }} 只 · 东财全行业龙头名单）</span></h2>
      <input
        v-model="keyword"
        class="search"
        type="text"
        placeholder="搜代码 / 名称…"
        spellcheck="false"
      />
    </div>
    <p class="hint">
      <strong>这份名单是什么：</strong>按东方财富公开的"全行业龙头股名单"整理的
      <strong>选股扫描范围</strong>（即离线扫描的 <code>universe="core"</code> 股票池，
      <code>easy-tdx screen scan --universe core</code> 与
      <code>/market/strength?universe=core</code> 均按此过滤），四组分层：全球第一 / 国内第一 /
      科技细分 / 行业冠军。<strong>名单仅描述"这些公司在其行业内规模/市占率领先"这一客观事实，
      不代表任何买入价值判断</strong>——龙头同样可能高估、滞涨或衰退。点击行查看个股详情。
    </p>
    <RiskDisclaimer prominent>
      <strong>⚠ 风险提示与免责声明</strong>
      <p>
        本页面展示的"核心龙头池"仅为<strong>策略扫描的股票范围筛选清单</strong>，
        <strong>不构成任何形式的个股推荐、买入建议或投资顾问服务</strong>。名单基于第三方公开
        资料整理，可能存在滞后、遗漏或错误；"行业龙头"是对历史经营地位的描述，
        不预示未来股价表现。本工具及作者不对任何人依据本名单作出的投资行为及损失承担责任。
        投资有风险，入市需谨慎，据此操作风险自负。
      </p>
    </RiskDisclaimer>
    <div v-if="error" class="error-banner">⚠ {{ error }}</div>
    <div v-else-if="loading" class="empty">加载中…</div>
    <div v-else class="grid">
      <div
        v-for="r in filtered"
        :key="r.market + r.code"
        class="cell"
        @click="openDialog(r)"
      >
        <span class="c-code mono dim">{{ r.code }}</span>
        <span class="c-name">{{ r.name }}</span>
        <span class="c-mkt mono dim">{{ r.market }}</span>
      </div>
    </div>
    <div v-if="!loading && !error && !filtered.length" class="empty">无匹配结果</div>

    <StockDialog
      v-if="dialog"
      :market="dialog.market"
      :code="dialog.code"
      :name="dialog.name"
      @close="dialog = null"
    />
  </div>
</template>

<style scoped>
.leaders-view {
  height: 100%;
  overflow-y: auto;
  padding: 14px 16px;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.toolbar h2 {
  font-size: 16px;
}
.title-sub {
  font-weight: 400;
  font-size: 12px;
}
.search {
  width: 200px;
  padding: 6px 10px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  font-size: 13px;
}
.search:focus {
  outline: none;
  border-color: var(--accent);
}
.hint {
  margin: 8px 0 12px;
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.7;
}
.hint code {
  font-family: var(--font-mono);
  font-size: 11px;
}
.error-banner {
  padding: 8px 12px;
  background: rgba(244, 67, 54, 0.1);
  border-radius: var(--radius);
  font-size: 12px;
  color: var(--red, #f44336);
}
.empty {
  color: var(--text-dim);
  padding: 40px;
  text-align: center;
  font-size: 13px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 6px;
}
.cell {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 12.5px;
  cursor: pointer;
}
.cell:hover {
  border-color: var(--accent);
}
.cell:hover .c-name {
  color: var(--accent);
}
.c-code {
  font-size: 11px;
  flex-shrink: 0;
}
.c-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.c-mkt {
  font-size: 10px;
  flex-shrink: 0;
}
.dim {
  color: var(--text-dim);
}
</style>
