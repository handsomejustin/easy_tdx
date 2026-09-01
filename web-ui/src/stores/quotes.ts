// 实时行情 SSE 状态（Pinia，全局单连接）。
// App.vue 挂载时 connect()，所有视图共享同一份 quotes 快照。
// 断线指数退避重连（上限 30s），状态徽标挂在侧边栏底部。

import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'

import type { SecurityQuote, SseMessage } from '../types'

export type SseStatus = 'connecting' | 'open' | 'closed'

const STREAM_URL = '/api/v1/stream/quotes'
const MAX_RETRY_DELAY = 30_000

export const useQuoteStore = defineStore('quotes', () => {
  /** symbol（SH600000）→ 最新行情快照。 */
  const quotes = reactive(new Map<string, SecurityQuote>())
  const status = ref<SseStatus>('closed')
  const lastTs = ref('')
  let es: EventSource | null = null
  let retryTimer: number | null = null
  let retryCount = 0

  const quoteCount = computed(() => quotes.size)

  function handleMsg(ev: MessageEvent<string>) {
    try {
      const msg = JSON.parse(ev.data) as SseMessage
      if (msg.type === 'quotes_updated' && msg.quotes) {
        for (const q of msg.quotes) quotes.set(q.symbol, q)
        if (msg.ts) lastTs.value = msg.ts
      }
      status.value = 'open'
      retryCount = 0
    } catch {
      // 非 JSON 帧（服务端注释/心跳），忽略
    }
  }

  function connect() {
    if (es) return
    status.value = 'connecting'
    es = new EventSource(STREAM_URL)
    es.onmessage = handleMsg
    es.onopen = () => {
      status.value = 'open'
      retryCount = 0
    }
    es.onerror = () => {
      // EventSource 断开后进入 readyState=CONNECTING 自行重试；但若服务已停，
      // 会无限静默重试——这里手动接管：关闭后按退避重连，同时更新状态徽标。
      close(false)
      retryCount += 1
      const delay = Math.min(1000 * 2 ** (retryCount - 1), MAX_RETRY_DELAY)
      status.value = 'closed'
      retryTimer = window.setTimeout(connect, delay)
    }
  }

  function close(markClosed = true) {
    if (retryTimer !== null) {
      window.clearTimeout(retryTimer)
      retryTimer = null
    }
    es?.close()
    es = null
    if (markClosed) status.value = 'closed'
  }

  /** 取单只行情（无数据时返回 undefined）。 */
  function getQuote(symbol: string): SecurityQuote | undefined {
    return quotes.get(symbol)
  }

  return { quotes, status, lastTs, quoteCount, connect, close, getQuote }
})
