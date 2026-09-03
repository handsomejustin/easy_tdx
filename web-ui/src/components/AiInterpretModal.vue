<script setup lang="ts">
// AI 解读弹窗（单标的/组合回测通用）：Prompt 预览 + 复制/下载 + 一键直接解读。
// Prompt 由父组件实时组装传入（附加分析跑完内容自动变全），本组件只管交互；
// 直接解读走后端 LLM 后台任务（配置见「AI 设置」页），解读记录旁路落历史库。
import { onMounted, ref, watch } from 'vue'

import { formatError, fetchLlmConfig, runLlmChatWithPolling } from '../api'
import type { LlmChatContext, LlmChatResult } from '../types'

const props = defineProps<{
  /** 已组装好的 Prompt 全文（computed 传入，实时更新） */
  prompt: string
  /** 下载文件名（如 AI解读_SZ000001_ma_cross.md） */
  filename: string
  /** 直接解读时随 Prompt 落历史库的策略上下文（历史页「去回测」引导用） */
  context?: LlmChatContext
  /** 弹窗描述里的附加提示（如「建议等附加分析跑完再发」） */
  tip?: string
}>()

const emit = defineEmits<{ close: [] }>()

const aiMsg = ref('')
// 直接解读（服务端 LLM 已配置时可用，配置见「AI 设置」页）
const llmReady = ref(false)
const llmLabel = ref('')
const aiRunning = ref(false)
const aiElapsed = ref(0)
const aiReply = ref('')
let aiTimer = 0

onMounted(() => {
  // 打开时探测 LLM 是否已配置（失败静默——导出 Prompt 的老路径不依赖后端）
  fetchLlmConfig()
    .then((resp) => {
      llmReady.value = resp.configured
      const p = resp.providers.find((x) => x.id === resp.config.provider)
      llmLabel.value = p ? `${p.label} · ${resp.resolved.model}` : resp.resolved.model
    })
    .catch(() => {
      llmReady.value = false
    })
})

watch(
  () => props.prompt,
  () => {
    // 配置更新后重置旧的失败/成功消息之外的回复？保持回复不动，仅清错误提示
    if (aiMsg.value.startsWith('解读失败')) aiMsg.value = ''
  },
)

/** 直接解读：把组装好的 Prompt 提交为后台任务并轮询（不占 HTTP 连接）。 */
async function runAiInterpret() {
  if (!props.prompt || aiRunning.value) return
  aiRunning.value = true
  aiMsg.value = ''
  aiReply.value = ''
  // 后台任务模式：模型生成 1-3 分钟正常——显示已耗时防误判卡死
  aiElapsed.value = 0
  aiTimer = window.setInterval(() => {
    aiElapsed.value += 1
  }, 1000)
  try {
    const state = await runLlmChatWithPolling(props.prompt, props.context)
    // TaskState.result 是多任务类型联合，按 LLM 任务结构收窄
    const r = state.result as LlmChatResult | null
    // 后端已保证非空正文（空白正文会以 failed 上浮），前端再拦一道纯空白
    if (state.status === 'done' && r?.reply?.trim()) {
      aiReply.value = r.reply
      aiMsg.value = `✓ ${r.provider} · ${r.model} 已解读（${aiElapsed.value}s）`
    } else if (state.status === 'done') {
      aiMsg.value = '解读失败：模型返回了空正文（可能被 Max Tokens 截断），可在「AI 设置」调大后重试'
    } else {
      aiMsg.value = `解读失败：${state.error ?? '未知错误'}（可在「AI 设置」检查配置，或复制 Prompt 手动使用）`
    }
  } catch (e) {
    aiMsg.value = `解读失败：${formatError(e)}（可在「AI 设置」检查配置，或复制 Prompt 手动使用）`
  } finally {
    window.clearInterval(aiTimer)
    aiRunning.value = false
  }
}

async function copyAiPrompt() {
  try {
    await navigator.clipboard.writeText(props.prompt)
    aiMsg.value = '✓ 已复制，粘贴给任意 AI 助手即可'
  } catch {
    // 剪贴板 API 不可用时退回选中文本，让用户手动 Ctrl+C
    const el = document.querySelector<HTMLTextAreaElement>('.ai-prompt-area')
    el?.focus()
    el?.select()
    aiMsg.value = document.execCommand('copy') ? '✓ 已复制' : '已全选文本，请按 Ctrl+C 复制'
  }
}

function downloadAiPrompt() {
  const blob = new Blob([props.prompt], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = props.filename
  a.click()
  URL.revokeObjectURL(url)
  aiMsg.value = '✓ 已下载 .md 文件'
}
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal modal-wide">
      <h3>🤖 AI 解读</h3>
      <p class="modal-desc">
        已把当前回测报告组装成提示词。
        <template v-if="llmReady">
          点击「直接解读」发送给已配置的模型（{{ llmLabel }}），
        </template>
        <template v-else>
          在「AI 设置」页配置模型后可一键直接解读；也可
        </template>
        复制后发给任意 AI 助手（ChatGPT / Claude / DeepSeek / 豆包…）。
        <template v-if="tip"> {{ tip }}</template>
      </p>
      <textarea
        :value="prompt"
        class="ai-prompt-area"
        :class="{ collapsed: !!aiReply }"
        readonly
        :rows="aiReply ? 6 : 16"
        spellcheck="false"
      ></textarea>
      <div v-if="aiReply" class="ai-reply">{{ aiReply }}</div>
      <div v-if="aiReply" class="ai-note">
        以上解读由 AI 模型生成，可能存在错误或过时信息，仅供参考，不构成投资建议。
      </div>
      <span v-if="aiMsg" class="ai-msg">{{ aiMsg }}</span>
      <div class="modal-actions">
        <button class="ghost" @click="emit('close')">关闭</button>
        <button class="ghost" @click="downloadAiPrompt">⬇ 下载 .md</button>
        <button class="ghost" @click="copyAiPrompt">复制 Prompt</button>
        <button
          v-if="llmReady"
          class="primary"
          :disabled="aiRunning || !prompt"
          @click="runAiInterpret"
        >
          {{ aiRunning ? `解读中… ${aiElapsed}s` : '✨ 直接解读' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
  width: 380px;
  max-width: 90vw;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.modal h3 {
  font-size: 15px;
  font-weight: 600;
}
.modal-desc {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.5;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
.modal-actions .ghost {
  font-size: 13px;
  padding: 7px 16px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-muted);
  cursor: pointer;
}
.modal-actions .primary {
  font-size: 13px;
  padding: 7px 16px;
  cursor: pointer;
}
.modal-actions .primary:disabled,
.modal-actions .ghost:disabled {
  opacity: 0.5;
  cursor: default;
}

/* AI 解读 Prompt 对话框（比保存对话框更宽，内容等宽小字可滚动） */
.modal-wide {
  width: 640px;
}
.ai-prompt-area {
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.6;
  white-space: pre;
  overflow: auto;
  max-height: 55vh;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 12px;
  color: var(--text-muted);
  resize: vertical;
}
/* 直接解读出结果后 Prompt 区收窄，把版面让给回复 */
.ai-prompt-area.collapsed {
  max-height: 18vh;
}
.ai-reply {
  margin-top: 8px;
  max-height: 38vh;
  overflow: auto;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: var(--radius);
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.ai-msg {
  font-size: 12px;
  color: var(--up);
}
.ai-note {
  margin-top: 4px;
  font-size: 11px;
  color: var(--warn, #ffc107);
}
</style>
