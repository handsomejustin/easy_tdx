<script setup lang="ts">
// 帮助下拉框：默认折叠，点击按钮展开（内容为任意插槽）。
// 用于各报告框底部的名词解释，避免新手面对一堆指标名词无处下手。

import { ref } from 'vue'

withDefaults(
  defineProps<{
    /** 按钮文案（如「名词解释」「图例说明」） */
    label?: string
  }>(),
  { label: '名词解释' },
)

const open = ref(false)
</script>

<template>
  <div class="help-collapse">
    <button class="help-toggle" type="button" :aria-expanded="open" @click="open = !open">
      <span class="help-q">?</span>
      <span>{{ label }}</span>
      <span class="chevron" :class="{ open }">▾</span>
    </button>
    <!-- grid-template-rows 0fr→1fr 实现高度自适应的展开动画；
         关闭态叠加 visibility:hidden（延迟到收起动画结束），
         避免 overflow 裁剪的内容对无障碍树/自动化仍"可见" -->
    <div class="help-body" :class="{ open }">
      <div class="help-inner">
        <slot />
      </div>
    </div>
  </div>
</template>

<style scoped>
.help-collapse {
  margin-top: 10px;
}
.help-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  font-size: 12px;
  color: var(--text-muted);
  background: transparent;
  border-radius: 999px;
}
.help-toggle:hover {
  color: var(--accent);
}
.help-q {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  font-size: 10px;
  font-weight: 700;
  color: var(--accent);
  border: 1px solid var(--accent);
  border-radius: 50%;
  line-height: 1;
}
.chevron {
  font-size: 10px;
  transition: transform 0.2s ease;
}
.chevron.open {
  transform: rotate(180deg);
}
.help-body {
  display: grid;
  grid-template-rows: 0fr;
  visibility: hidden;
  transition:
    grid-template-rows 0.25s ease,
    visibility 0s linear 0.25s;
}
.help-body.open {
  grid-template-rows: 1fr;
  visibility: visible;
  transition: grid-template-rows 0.25s ease;
}
.help-inner {
  min-height: 0;
  overflow: hidden;
  padding-top: 8px;
}
</style>
