<script setup lang="ts">
// AI 设置页：LLM Provider 配置（WebUI 表单 ⇆ ~/.easy_tdx/llm.json 同一份文件）。
// 选 Provider 自动填充预设 base_url / 默认模型，均可手工覆盖；API Key 脱敏
// 回显，留空或原样回传不覆盖已存 key。支持「测试连接」即时验证。
import { computed, onMounted, reactive, ref } from 'vue'
import { fetchLlmConfig, saveLlmConfig, testLlm, formatError } from '../api'
import type { LlmProviderInfo } from '../types'

const providers = ref<LlmProviderInfo[]>([])
const configPath = ref('')
const configured = ref(false)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const message = ref('')
const error = ref('')
const testResult = ref<string>('')

const form = reactive({
  provider: 'deepseek',
  api_url: '',
  api_key: '',
  model: '',
  temperature: 0.3,
  max_tokens: 16000,
  timeout: 180,
  system_prompt: '',
})

/** 当前选中 Provider 的预设（填充提示用）。 */
const currentPreset = computed(
  () => providers.value.find((p) => p.id === form.provider) ?? null,
)

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetchLlmConfig()
    providers.value = resp.providers
    configPath.value = resp.config_path
    configured.value = resp.configured
    form.provider = resp.config.provider
    form.api_url = resp.config.api_url
    form.api_key = resp.config.api_key
    form.model = resp.config.model
    form.temperature = resp.config.temperature
    form.max_tokens = resp.config.max_tokens
    form.timeout = resp.config.timeout
    form.system_prompt = resp.config.system_prompt
  } catch (e) {
    error.value = formatError(e)
  } finally {
    loading.value = false
  }
}

/** 切换 Provider：清空 key 与空字段，让预设兜底（已有自定义值不覆盖）。 */
function onProviderChange() {
  form.api_key = ''
  form.api_url = ''
  form.model = ''
  message.value = ''
  error.value = ''
  testResult.value = ''
}

async function save() {
  saving.value = true
  error.value = ''
  message.value = ''
  testResult.value = ''
  try {
    const resp = await saveLlmConfig({
      provider: form.provider,
      api_url: form.api_url,
      // 脱敏串原样回传 = 不覆盖已存 key；后端再判一次
      api_key: form.api_key,
      model: form.model,
      temperature: form.temperature,
      max_tokens: form.max_tokens,
      timeout: form.timeout,
      system_prompt: form.system_prompt,
    })
    configured.value = resp.configured
    // 回填脱敏 key，避免明文留在表单里
    form.api_key = resp.config.api_key
    message.value = `已保存到 ${resp.config_path}`
  } catch (e) {
    error.value = formatError(e)
  } finally {
    saving.value = false
  }
}

async function test() {
  testing.value = true
  error.value = ''
  message.value = ''
  testResult.value = ''
  try {
    // 先保存再测（保存时脱敏串回传不会覆盖真 key），保证测的就是落盘配置
    await save()
    const r = await testLlm()
    if (r.ok) {
      testResult.value = `✓ 连通成功 · ${r.model} · ${r.latency_ms} ms · 回复「${r.reply}」`
    } else {
      testResult.value = `✗ 失败 · ${r.error}`
    }
  } catch (e) {
    error.value = formatError(e)
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="llm-settings">
    <aside class="config-panel">
      <h2>AI 设置</h2>
      <p class="hint">
        配置 LLM 后，回测页的「AI 解读」可直接把报告发给模型解读，无需复制粘贴。
        配置同时落盘到 <code>{{ configPath || '~/.easy_tdx/llm.json' }}</code>
        ，手工编辑该文件与此处保存完全等效。
      </p>

      <label class="field">
        <span>Provider</span>
        <select v-model="form.provider" @change="onProviderChange">
          <option v-for="p in providers" :key="p.id" :value="p.id">
            {{ p.label }}{{ p.needs_key ? '' : '（免Key）' }}
          </option>
        </select>
      </label>

      <label class="field">
        <span>API 地址</span>
        <input
          v-model="form.api_url"
          type="text"
          :placeholder="currentPreset?.base_url || 'https://...（OpenAI 兼容地址）'"
          spellcheck="false"
        />
      </label>

      <label class="field">
        <span>API Key</span>
        <input
          v-model="form.api_key"
          type="password"
          :placeholder="form.api_key ? '已保存（留空不修改，填 CLEAR 清除）' : 'sk-…'"
          autocomplete="off"
          spellcheck="false"
        />
      </label>

      <label class="field">
        <span>模型</span>
        <input
          v-model="form.model"
          type="text"
          :placeholder="currentPreset?.default_model || '模型名'"
          spellcheck="false"
        />
      </label>

      <div class="row-2">
        <label class="field">
          <span>Temperature</span>
          <input v-model.number="form.temperature" type="number" min="0" max="2" step="0.1" />
        </label>
        <label class="field">
          <span>Max Tokens——思考型模型的思考链计入此预算，建议 ≥16000</span>
          <input v-model.number="form.max_tokens" type="number" min="64" max="128000" step="512" />
        </label>
      </div>

      <label class="field">
        <span>超时（秒）——报告解读需等模型生成完整段回复，建议 ≥120</span>
        <input v-model.number="form.timeout" type="number" min="5" max="600" step="10" />
      </label>

      <label class="field">
        <span>系统提示词（AI 解读的默认角色设定）</span>
        <textarea v-model="form.system_prompt" rows="4" spellcheck="false"></textarea>
      </label>

      <div class="actions">
        <button class="btn-primary" :disabled="saving || loading" @click="save">
          {{ saving ? '保存中…' : '保存配置' }}
        </button>
        <button class="btn-ghost" :disabled="testing || loading" @click="test">
          {{ testing ? '测试中…' : '保存并测试' }}
        </button>
      </div>

      <div v-if="message" class="message">{{ message }}</div>
      <div v-if="testResult" class="test-result" :class="{ ok: testResult.startsWith('✓') }">
        {{ testResult }}
      </div>
      <div v-if="error" class="error-banner">⚠ {{ error }}</div>
      <div v-if="!loading && !configured" class="warn-banner">
        尚未配置可用的 API Key——「AI 解读」仍可导出 Prompt 手动使用。
      </div>
    </aside>

    <main class="info-panel">
      <h3>支持的 Provider</h3>
      <table class="provider-table">
        <thead>
          <tr>
            <th>Provider</th>
            <th>默认地址</th>
            <th>默认模型</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in providers" :key="p.id" :class="{ current: p.id === form.provider }">
            <td>{{ p.label }}</td>
            <td class="mono">{{ p.base_url || '—' }}</td>
            <td class="mono">{{ p.default_model || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p class="hint">
        除 Claude 走 Anthropic 原生协议外，其余均走 OpenAI 兼容接口；「自定义」可填任意
        兼容网关（如 OpenRouter、one-api、vLLM）。Ollama 本地服务无需 API Key。
        环境变量 LLM_PROVIDER / LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 在配置文件
        缺字段时兜底生效。
      </p>
    </main>
  </div>
</template>

<style scoped>
.llm-settings {
  display: flex;
  height: 100%;
  overflow: hidden;
}
.config-panel {
  width: 360px;
  flex-shrink: 0;
  padding: 20px;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  overflow-y: auto;
}
.config-panel h2 {
  font-size: 16px;
  margin-bottom: 12px;
}
.hint {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.6;
}
.hint code {
  font-family: var(--font-mono);
  font-size: 11px;
  word-break: break-all;
}
.field {
  display: block;
  margin-top: 12px;
}
.field span {
  display: block;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.field input,
.field select,
.field textarea {
  width: 100%;
  padding: 6px 8px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  font-size: 13px;
  font-family: inherit;
}
.field textarea {
  font-family: var(--font-mono);
  font-size: 12px;
  resize: vertical;
}
.row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.actions {
  display: flex;
  gap: 10px;
  margin-top: 16px;
}
.btn-primary {
  flex: 1;
  padding: 9px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 13px;
}
.btn-primary:hover:not(:disabled) {
  opacity: 0.9;
}
.btn-ghost {
  flex: 1;
  padding: 9px;
  background: transparent;
  border: 1px solid var(--accent);
  color: var(--accent);
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 13px;
}
.btn-ghost:hover:not(:disabled) {
  background: var(--accent);
  color: #fff;
}
.btn-primary:disabled,
.btn-ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.message {
  margin-top: 12px;
  padding: 8px 12px;
  background: var(--accent-bg, rgba(0, 120, 212, 0.1));
  border-radius: var(--radius);
  font-size: 12px;
  color: var(--accent);
  word-break: break-all;
}
.test-result {
  margin-top: 10px;
  padding: 8px 12px;
  background: rgba(244, 67, 54, 0.08);
  border-radius: var(--radius);
  font-size: 12px;
  color: var(--red, #f44336);
  word-break: break-all;
}
.test-result.ok {
  background: rgba(76, 175, 80, 0.12);
  color: var(--green, #4caf50);
}
.error-banner {
  margin-top: 12px;
  padding: 8px 12px;
  background: rgba(244, 67, 54, 0.1);
  border-radius: var(--radius);
  font-size: 12px;
  color: var(--red, #f44336);
}
.warn-banner {
  margin-top: 12px;
  padding: 8px 12px;
  background: rgba(255, 193, 7, 0.1);
  border-radius: var(--radius);
  font-size: 12px;
  color: var(--warn, #ffc107);
}
.info-panel {
  flex: 1;
  overflow: auto;
  padding: 20px;
}
.info-panel h3 {
  font-size: 14px;
  margin-bottom: 12px;
}
.provider-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
  margin-bottom: 14px;
}
.provider-table th {
  text-align: left;
  padding: 7px 10px;
  border-bottom: 2px solid var(--border);
  color: var(--text-dim);
  font-weight: 500;
}
.provider-table td {
  padding: 7px 10px;
  border-bottom: 1px solid var(--border);
}
.provider-table tr.current {
  background: var(--accent-bg, rgba(0, 120, 212, 0.06));
}
.mono {
  font-family: var(--font-mono);
  font-size: 11.5px;
}
</style>
