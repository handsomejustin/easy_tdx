<script setup lang="ts">
// 根组件：侧边栏终端外壳 + 路由出口。
// 布局借鉴专业看盘终端（侧边栏分组导航 + 底部实时连接状态徽标）。
import { onMounted } from 'vue'

import { useQuoteStore } from './stores/quotes'

const quoteStore = useQuoteStore()
onMounted(() => quoteStore.connect())

const sseLabel: Record<string, string> = {
  connecting: '连接中',
  open: '实时',
  closed: '离线',
}
</script>

<template>
  <div class="app">
    <div class="app-row">
      <aside class="sidebar">
        <div class="brand">
          <span class="brand-name">easy-tdx</span>
          <span class="brand-sub">行情终端</span>
        </div>
        <nav class="side-nav">
          <div class="nav-group">行情</div>
          <RouterLink to="/" exact-active-class="active">市场看板</RouterLink>
          <RouterLink to="/industries" active-class="active">行业总览</RouterLink>
          <RouterLink to="/concepts" active-class="active">概念总览</RouterLink>
          <RouterLink to="/hotspots" active-class="active">热点滚动</RouterLink>
          <RouterLink to="/calendar" active-class="active">大盘日历</RouterLink>
          <RouterLink to="/limitup" active-class="active">涨停生态</RouterLink>
          <RouterLink to="/watchlist" active-class="active">自选行情</RouterLink>
          <RouterLink to="/ccpm" active-class="active">期货持仓排名</RouterLink>
          <div class="nav-group">分析</div>
          <RouterLink to="/backtest" active-class="active">单标的回测</RouterLink>
          <RouterLink to="/portfolio" active-class="active">组合回测</RouterLink>
          <RouterLink to="/optimize" active-class="active">参数寻优</RouterLink>
          <RouterLink to="/compare" active-class="active">结果对比</RouterLink>
          <RouterLink to="/strategies" active-class="active">策略库</RouterLink>
          <RouterLink to="/signals" active-class="active">信号雷达</RouterLink>
          <RouterLink to="/ai-history" active-class="active">AI 解读历史</RouterLink>
          <div class="nav-group">系统</div>
          <RouterLink to="/settings" active-class="active">服务器设置</RouterLink>
          <RouterLink to="/llm" active-class="active">AI 设置</RouterLink>
        </nav>
        <div class="side-footer">
          <span class="dot" :class="quoteStore.status"></span>
          <span class="sse-label">{{ sseLabel[quoteStore.status] ?? '离线' }}</span>
          <span v-if="quoteStore.lastTs" class="sse-ts">{{ quoteStore.lastTs.slice(11, 19) }}</span>
          <span v-if="quoteStore.quoteCount" class="sse-n">×{{ quoteStore.quoteCount }}</span>
        </div>
      </aside>
      <main class="app-main">
        <RouterView />
      </main>
    </div>
    <!-- 全局风险提示：所有页面常驻（行情/回测/个股相关内容均在此覆盖范围） -->
    <footer class="global-disclaimer">
      本工具输出（行情数据 / 指标 / 回测 / 选股扫描 / AI 解读）仅供量化研究与学习，
      不构成任何投资建议或个股推荐；历史表现不代表未来，股市有风险，据此操作风险自负。
    </footer>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.app-row {
  flex: 1;
  display: flex;
  min-height: 0;
}
.global-disclaimer {
  flex-shrink: 0;
  padding: 5px 16px;
  background: var(--bg-panel);
  border-top: 1px solid var(--border);
  font-size: 10.5px;
  color: var(--text-dim);
  text-align: center;
  letter-spacing: 0.2px;
}
.sidebar {
  width: 176px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
}
.brand {
  padding: 14px 16px 12px;
  border-bottom: 1px solid var(--border);
}
.brand-name {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.brand-sub {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-dim);
}
.side-nav {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}
.nav-group {
  padding: 10px 16px 4px;
  font-size: 11px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 1px;
}
.side-nav a {
  display: block;
  padding: 7px 16px;
  color: var(--text-muted);
  text-decoration: none;
  font-size: 13px;
  border-left: 2px solid transparent;
}
.side-nav a:hover {
  color: var(--text);
  background: var(--bg-elevated);
}
.side-nav a.active {
  color: var(--accent);
  border-left-color: var(--accent);
  background: var(--bg-elevated);
}
.side-footer {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  border-top: 1px solid var(--border);
  font-size: 11px;
  color: var(--text-dim);
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-dim);
}
.dot.open {
  background: var(--up);
  box-shadow: 0 0 4px var(--up);
}
.dot.connecting {
  background: var(--warn);
}
.sse-ts {
  margin-left: auto;
  font-family: var(--font-mono);
}
.sse-n {
  color: var(--text-dim);
}
.app-main {
  flex: 1;
  overflow: hidden;
}
</style>
