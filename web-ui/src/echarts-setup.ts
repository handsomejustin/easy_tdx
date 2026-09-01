// ECharts 按需引入。只注册用到的图表类型，避免全量引入（~1MB → ~400KB）。
// 用到的：candlestick（K线）、line（净值/回撤曲线）、markPoint（买卖点标注）、heatmap（寻优热力图）。

import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart, HeatmapChart, LineChart, RadarChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  RadarComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  CanvasRenderer,
  CandlestickChart,
  LineChart,
  BarChart,
  HeatmapChart,
  RadarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DataZoomComponent,
  MarkPointComponent,
  MarkLineComponent,
  RadarComponent,
  VisualMapComponent,
])

// A股惯例：红涨绿跌
export const UP_COLOR = '#ef4146'
export const DOWN_COLOR = '#18a058'

// 注册内联 dark 主题（echarts/core 不预置 'dark' 主题数据）。
// 覆盖坐标轴文字、分割线等默认浅色样式，适配深色背景。
echarts.registerTheme('dark', {
  backgroundColor: 'transparent',
  textStyle: { color: '#8b919e' },
  title: { textStyle: { color: '#e6e8eb' }, subtextStyle: { color: '#8b919e' } },
  legend: { textStyle: { color: '#8b919e' } },
  tooltip: {
    backgroundColor: 'rgba(26,29,38,0.95)',
    borderColor: '#2a2e3a',
    textStyle: { color: '#e6e8eb' },
  },
  categoryAxis: {
    axisLine: { lineStyle: { color: '#2a2e3a' } },
    axisLabel: { color: '#5c6370' },
    splitLine: { show: false },
  },
  valueAxis: {
    axisLine: { lineStyle: { color: '#2a2e3a' } },
    axisLabel: { color: '#5c6370' },
    splitLine: { lineStyle: { color: '#2a2e3a' } },
  },
})

export default echarts
