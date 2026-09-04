import { createRouter, createWebHistory } from 'vue-router'

import BacktestView from './views/BacktestView.vue'
import BoardOverviewView from './views/BoardOverviewView.vue'
import CcpmView from './views/CcpmView.vue'
import CompareView from './views/CompareView.vue'
import DashboardView from './views/DashboardView.vue'
import HotspotView from './views/HotspotView.vue'
import IndexCalendarView from './views/IndexCalendarView.vue'
import LimitUpView from './views/LimitUpView.vue'
import LlmHistoryView from './views/LlmHistoryView.vue'
import LlmSettingsView from './views/LlmSettingsView.vue'
import OptimizeView from './views/OptimizeView.vue'
import PortfolioView from './views/PortfolioView.vue'
import SentimentView from './views/SentimentView.vue'
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
  // 行业/概念总览（同一视图组件，路由 props 区分板块类型）
  { path: '/industries', name: 'industries', component: BoardOverviewView, props: { boardType: 'HY' } },
  { path: '/concepts', name: 'concepts', component: BoardOverviewView, props: { boardType: 'GN' } },
  // 市场热点滚动（交易日×板块涨跌矩阵：热点形成/持续/轮动/领跌）
  { path: '/hotspots', name: 'hotspots', component: HotspotView },
  // 风格轮动（同一热点视图 × FG 风格板块：大/小盘、高股息/成长…）
  { path: '/styles', name: 'styles', component: HotspotView, props: { boardType: 'FG' } },
  // 大盘日历（指数全年红绿热力图）
  { path: '/calendar', name: 'calendar', component: IndexCalendarView },
  { path: '/watchlist', name: 'watchlist', component: WatchlistView },
  // 涨停生态（连板天梯/炸板/跌停，本地 vipdoc 离线回算）
  { path: '/limitup', name: 'limitup', component: LimitUpView },
  // 市场情绪（宽度分时 + 涨停温度计；采样器盘中逐分钟积累）
  { path: '/sentiment', name: 'sentiment', component: SentimentView },
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
  // 中金所成交持仓排名（独立数据源，每日收盘后发布）
  { path: '/ccpm', name: 'ccpm', component: CcpmView },
  // 兜底：未注册路径（如把 API 路径当页面访问）回看板，不再渲染空白
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
