<script setup lang="ts">
// 根组件：顶部标题栏 + 路由出口。
</script>

<template>
  <div class="app">
    <header class="app-header">
      <h1>easy-tdx 回测</h1>
      <nav class="app-nav">
        <RouterLink to="/" active-class="active">单标的回测</RouterLink>
        <RouterLink to="/portfolio" active-class="active">组合回测</RouterLink>
        <RouterLink to="/optimize" active-class="active">参数寻优</RouterLink>
        <RouterLink to="/compare" active-class="active">结果对比</RouterLink>
        <RouterLink to="/strategies" active-class="active">策略库</RouterLink>
      </nav>
    </header>
    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.app-header {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 0 20px;
  height: 48px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.app-header h1 {
  font-size: 16px;
  font-weight: 600;
}
.app-nav {
  display: flex;
  gap: 16px;
}
.app-nav a {
  color: var(--text-dim);
  text-decoration: none;
  font-size: 13px;
  padding: 4px 0;
  border-bottom: 2px solid transparent;
}
.app-nav a:hover {
  color: var(--text);
}
.app-nav a.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}
.app-main {
  flex: 1;
  overflow: hidden;
}
</style>
