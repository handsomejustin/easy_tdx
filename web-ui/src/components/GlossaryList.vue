<script setup lang="ts">
// 名词解释列表：按分组渲染词条（定义 / 公式 / 细节 / 怎么看）。
// 重点与非重点的字重层级：词条名与 **粗体** 段落为亮色粗体，
// 细节为细体暗色，"怎么看"里的阈值用暖色粗体突出。

import type { GlossarySection } from '../data/glossary'

defineProps<{
  sections: GlossarySection[]
}>()

/** 把 "**重点**普通" 切成片段：奇数段为粗体重点 */
function rich(text: string): Array<{ text: string; bold: boolean }> {
  return text
    .split('**')
    .map((t, i) => ({ text: t, bold: i % 2 === 1 }))
    .filter((p) => p.text.length > 0)
}
</script>

<template>
  <div class="glossary">
    <section v-for="s in sections" :key="s.title" class="g-section">
      <h5 class="g-title">{{ s.title }}</h5>
      <dl class="g-entries">
        <div v-for="e in s.entries" :key="e.term" class="g-entry">
          <dt class="g-term">{{ e.term }}</dt>
          <dd class="g-def">
            <p class="g-summary">
              <template v-for="(p, i) in rich(e.summary)" :key="i">
                <strong v-if="p.bold">{{ p.text }}</strong>
                <template v-else>{{ p.text }}</template>
              </template>
            </p>
            <p v-if="e.formula" class="g-formula">{{ e.formula }}</p>
            <p v-if="e.detail" class="g-detail">
              <template v-for="(p, i) in rich(e.detail)" :key="i">
                <strong v-if="p.bold">{{ p.text }}</strong>
                <template v-else>{{ p.text }}</template>
              </template>
            </p>
            <p v-if="e.guide" class="g-guide">
              <span class="g-guide-label">怎么看</span>
              <template v-for="(p, i) in rich(e.guide)" :key="i">
                <strong v-if="p.bold">{{ p.text }}</strong>
                <template v-else>{{ p.text }}</template>
              </template>
            </p>
          </dd>
        </div>
      </dl>
    </section>
  </div>
</template>

<style scoped>
.glossary {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 14px;
  font-size: 12.5px;
  line-height: 1.7;
}
.g-section + .g-section {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
}
.g-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  margin-bottom: 8px;
  letter-spacing: 0.5px;
}
/* 宽屏两列排布，缩短折叠后的滚动距离；词条整体不跨列拆断 */
.g-entries {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 8px 24px;
}
.g-entry {
  break-inside: avoid;
  margin: 0;
}
.g-term {
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text);
}
.g-def {
  margin: 0;
}
.g-def p {
  margin: 0;
}
.g-summary {
  color: var(--text-muted);
}
.g-summary strong {
  color: var(--text);
  font-weight: 600;
}
.g-formula {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 11.5px;
  color: var(--text-muted);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1px 8px;
  margin: 3px 0 !important;
}
/* 细节：细体暗色（非重点） */
.g-detail {
  color: var(--text-dim);
  font-weight: 300;
}
.g-detail strong {
  color: var(--text-muted);
  font-weight: 600;
}
/* 怎么看：标签 + 阈值暖色粗体（重点） */
.g-guide {
  color: var(--text-muted);
}
.g-guide-label {
  display: inline-block;
  font-size: 10.5px;
  font-weight: 600;
  color: var(--accent);
  border: 1px solid var(--accent);
  border-radius: var(--radius);
  padding: 0 5px;
  margin-right: 6px;
  line-height: 1.5;
  vertical-align: 1px;
}
.g-guide strong {
  color: var(--warn);
  font-weight: 700;
}
</style>
