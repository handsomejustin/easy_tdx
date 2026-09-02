<script setup lang="ts">
// AI 解读历史页：历次「直接解读」的提问 Prompt + 模型解读 + 策略上下文。
// 每条可展开查看全文，「去回测」带策略/参数/标的/周期/日期一键跳回回测页，
// 「重新解读」用原 Prompt 再发起一次（模型更新/换模型后对比）。
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fetchLlmHistory, deleteLlmHistory, clearLlmHistory, formatError } from '../api'
import type { LlmHistoryItem } from '../types'
import RiskDisclaimer from '../components/RiskDisclaimer.vue'

const router = useRouter()
const items = ref<LlmHistoryItem[]>([])
const loading = ref(false)
const error = ref('')
const expandedId = ref<number | null>(null)
const showPromptOf = ref<number | null>(null)

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetchLlmHistory(100)
    items.value = resp.items
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

function toggle(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}

function togglePrompt(id: number) {
  showPromptOf.value = showPromptOf.value === id ? null : id
}

/** 本地时间 + 只保留日期时分。 */
function fmtTime(iso: string): string {
  if (!iso) return ''
  // 后端存 UTC（Z 结尾），转本地展示
  const d = new Date(iso.endsWith('Z') && iso.length === 17 ? iso.slice(0, 16) + 'Z' : iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 标题：策略 @ 标的 · 周期（手工调用无上下文时只显示模型）。 */
function title(it: LlmHistoryItem): string {
  if (!it.strategy_label && !it.symbol) return `AI 对话 · ${it.model}`
  const sym = it.symbol || '—'
  const cat = it.category ? ` · ${it.category}` : ''
  return `${it.strategy_label || it.strategy || '策略'} @ ${sym}${cat}`
}

/** 去回测：带全部上下文跳转（回测页 onMounted 读 query 预填）。 */
function goBacktest(it: LlmHistoryItem) {
  const query: Record<string, string> = {}
  if (it.strategy) query.strategy = it.strategy
  if (Object.keys(it.params || {}).length) query.params = JSON.stringify(it.params)
  if (it.symbol) query.symbol = it.symbol
  if (it.category) query.category = it.category
  if (it.start_date) query.startDate = it.start_date
  if (it.end_date) query.endDate = it.end_date
  router.push({ path: '/backtest', query })
}

async function onDelete(id: number) {
  try {
    await deleteLlmHistory(id)
    items.value = items.value.filter((i) => i.id !== id)
  } catch (e) {
    error.value = formatError(e)
  }
}

async function onClearAll() {
  if (!window.confirm('确定清空全部 AI 解读历史？此操作不可恢复。')) return
  try {
    await clearLlmHistory()
    items.value = []
  } catch (e) {
    error.value = formatError(e)
  }
}
</script>

<template>
  <div class="ai-history">
    <aside class="side-panel">
      <h2>AI 解读历史</h2>
      <p class="hint">
        每次「直接解读」成功后自动归档：提问 Prompt、模型解读、以及当时的策略配置。
        「去回测」可一键带参数跳回回测页复现当时的场景；「重新解读」适合换模型后对比结论。
      </p>
      <button class="btn-ghost" :disabled="!items.length || loading" @click="onClearAll">
        清空历史
      </button>
      <div v-if="error" class="error-banner">⚠ {{ error }}</div>
      <RiskDisclaimer>
        历史解读由 AI 生成、基于当时的回测数据，均不构成投资建议；策略过往表现不代表未来。
      </RiskDisclaimer>
    </aside>

    <main class="list-panel">
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="!items.length" class="empty">
        暂无解读记录——到「单标的回测」页跑一次回测，点「🤖 AI 解读 → ✨ 直接解读」即可归档。
      </div>

      <div v-for="it in items" :key="it.id" class="record" :class="{ open: expandedId === it.id }">
        <div class="record-head" @click="toggle(it.id)">
          <span class="r-time mono dim">{{ fmtTime(it.created_at) }}</span>
          <span class="r-title">{{ title(it) }}</span>
          <span class="r-model mono dim">{{ it.provider }} · {{ it.model }}</span>
          <span class="r-elapsed mono dim">{{ it.elapsed }}s</span>
          <span class="r-arrow">{{ expandedId === it.id ? '▾' : '▸' }}</span>
        </div>

        <div v-if="expandedId === it.id" class="record-body">
          <div class="reply">{{ it.reply }}</div>
          <div class="ai-note">以上解读由 AI 模型生成，可能存在错误或过时信息，仅供参考，不构成投资建议。</div>

          <div v-if="it.start_date || it.end_date" class="ctx-line dim">
            回测区间 {{ it.start_date || '…' }} ~ {{ it.end_date || '…' }}
            <template v-if="Object.keys(it.params || {}).length">
              · 参数 {{ JSON.stringify(it.params) }}
            </template>
          </div>

          <div class="actions">
            <button
              v-if="it.strategy || it.symbol"
              class="btn-primary"
              @click="goBacktest(it)"
            >
              → 去回测（带参数）
            </button>
            <button class="btn-ghost" @click="togglePrompt(it.id)">
              {{ showPromptOf === it.id ? '收起提问' : '查看提问 Prompt' }}
            </button>
            <button class="btn-danger" @click="onDelete(it.id)">删除</button>
          </div>

          <pre v-if="showPromptOf === it.id" class="prompt">{{ it.prompt }}</pre>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.ai-history {
  display: flex;
  height: 100%;
  overflow: hidden;
}
.side-panel {
  width: 280px;
  flex-shrink: 0;
  padding: 20px;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  overflow-y: auto;
}
.side-panel h2 {
  font-size: 16px;
  margin-bottom: 12px;
}
.hint {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.7;
  margin-bottom: 16px;
}
.error-banner {
  margin-top: 12px;
  padding: 8px 12px;
  background: rgba(244, 67, 54, 0.1);
  border-radius: var(--radius);
  font-size: 12px;
  color: var(--red, #f44336);
}
.list-panel {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
}
.empty {
  color: var(--text-dim);
  padding: 40px;
  text-align: center;
  font-size: 13px;
}
.record {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 8px;
  background: var(--bg-panel);
}
.record.open {
  border-color: var(--accent);
}
.record-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  cursor: pointer;
  font-size: 12.5px;
}
.record-head:hover .r-title {
  color: var(--accent);
}
.r-time {
  flex-shrink: 0;
  font-size: 11px;
}
.r-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}
.r-model {
  flex-shrink: 0;
  font-size: 11px;
}
.r-elapsed {
  flex-shrink: 0;
  font-size: 11px;
}
.r-arrow {
  color: var(--text-dim);
  flex-shrink: 0;
}
.record-body {
  border-top: 1px solid var(--border);
  padding: 12px;
}
.reply {
  /* 不设内层滚动：正文完整铺开，由外层 list-panel 页面级滚动（内层限高
     曾导致"高度太低无滚轴、文字展示不全"的阅读问题） */
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 13px;
  line-height: 1.75;
  background: var(--bg-elevated);
  border-left: 3px solid var(--accent);
  border-radius: var(--radius);
  padding: 10px 12px;
}
.ctx-line {
  margin-top: 8px;
  font-size: 11.5px;
}
.ai-note {
  margin-top: 6px;
  font-size: 11px;
  color: var(--warn, #ffc107);
}
.actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
.btn-primary {
  padding: 5px 14px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 12px;
}
.btn-ghost {
  padding: 5px 14px;
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-muted);
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 12px;
}
.btn-ghost:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}
.btn-ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-danger {
  padding: 5px 14px;
  background: transparent;
  border: 1px solid rgba(244, 67, 54, 0.5);
  color: var(--red, #f44336);
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 12px;
}
.btn-danger:hover {
  background: rgba(244, 67, 54, 0.1);
}
.prompt {
  margin-top: 10px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-dim);
  background: var(--bg);
  border: 1px dashed var(--border);
  border-radius: var(--radius);
  padding: 8px 10px;
}
</style>
