import { createRouter, createWebHistory } from 'vue-router'

import BacktestView from './views/BacktestView.vue'
import CompareView from './views/CompareView.vue'
import CoreLeadersView from './views/CoreLeadersView.vue'
import DashboardView from './views/DashboardView.vue'
import LlmHistoryView from './views/LlmHistoryView.vue'
import LlmSettingsView from './views/LlmSettingsView.vue'
import OptimizeView from './views/OptimizeView.vue'
import PortfolioView from './views/PortfolioView.vue'
import ServerSettingsView from './views/ServerSettingsView.vue'
import SignalRadarView from './views/SignalRadarView.vue'
import StrategiesView from './views/StrategiesView.vue'
import WatchlistView from './views/WatchlistView.vue'

// 行情终端：市场看板（/）+ 自选（/watchlist）。
// 分析工具：单标的回测（/backtest）+ 组合回测（/portfolio）+ 参数寻优（/optimize）
// + 结果对比（/compare）+ 策略库（/strategies）+ 信号雷达（/signals）
// + 设置（/settings 服务器 / /llm AI 模型）。
const routes = [
  { path: '/', name: 'dashboard', component: DashboardView },
  { path: '/watchlist', name: 'watchlist', component: WatchlistView },
  { path: '/backtest', name: 'backtest', component: BacktestView },
  { path: '/portfolio', name: 'portfolio', component: PortfolioView },
  { path: '/optimize', name: 'optimize', component: OptimizeView },
  { path: '/compare', name: 'compare', component: CompareView },
  { path: '/strategies', name: 'strategies', component: StrategiesView },
  { path: '/signals', name: 'signals', component: SignalRadarView },
  { path: '/settings', name: 'settings', component: ServerSettingsView },
  { path: '/llm', name: 'llm', component: LlmSettingsView },
  // AI 解读历史（每次「直接解读」自动归档）
  { path: '/ai-history', name: 'ai-history', component: LlmHistoryView },
  // 核心龙头池（universe=core 的 159 只名单）
  { path: '/leaders', name: 'leaders', component: CoreLeadersView },
  // 兜底：未注册路径（如把 API 路径当页面访问）回看板，不再渲染空白
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
