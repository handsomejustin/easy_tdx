// 回测页 E2E：选策略 → 开始回测（自动取行情）→ 净值图 + 绩效表 + 成交记录。
//
// 行情来自 mock /bars（确定性合成 OHLCV），回测跑真实引擎；
// URL query 指定较短日期区间加快取数（页面 onMounted 回填 startDate/endDate）。

import { expect, test } from '@playwright/test'

test('回测全流程出净值图与绩效表', async ({ page }) => {
  await page.goto('/backtest?startDate=2024-01-01&endDate=2025-12-31')

  // 策略下拉加载出内置策略，默认 ma_cross
  const strategySelect = page.locator('.strategy-picker select')
  await expect(strategySelect).toHaveValue('ma_cross')
  const optionCount = await strategySelect.locator('option').count()
  expect(optionCount).toBeGreaterThanOrEqual(18)

  // 取行情（mock /bars）+ 回测（真实引擎）
  await page.getByRole('button', { name: '开始回测' }).click()

  // 报告区：净值曲线（echarts canvas）+ 绩效指标 + 成交记录
  await expect(page.getByRole('heading', { name: '净值曲线与回撤' })).toBeVisible({ timeout: 60_000 })
  await expect(page.locator('.report-section canvas').first()).toBeVisible()
  await expect(page.getByRole('heading', { name: '绩效指标' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /成交记录（\d+ 笔）/ })).toBeVisible()

  // 绩效表渲染出具体数值（总收益/夏普等指标行）
  const perfSection = page.locator('.report-section', { hasText: '绩效指标' })
  await expect(perfSection.locator('td, .metric-value, .mono').first()).toBeVisible()
})

test('勾选附加分析后出现 WF 逐窗柱状图与一条龙评估卡', async ({ page }) => {
  await page.goto('/backtest?startDate=2023-01-01&endDate=2025-12-31')

  // 勾选两个「附加分析」开关（v1.27 新增）
  await page.getByLabel('Walk-Forward 样本外验证').check()
  await expect(page.getByLabel('一条龙评估')).toBeVisible()
  await page.getByLabel('一条龙评估').check()

  await page.getByRole('button', { name: '开始回测' }).click()

  // WF：先出现「验证中…」区块，随后逐窗柱状图（echarts canvas）+ 稳定性汇总
  await expect(page.getByRole('heading', { name: 'Walk-Forward 样本外验证' })).toBeVisible({
    timeout: 60_000,
  })
  await expect(page.locator('.wf-chart canvas')).toBeVisible({ timeout: 120_000 })
  // 收窄到汇总区：词条表里也有「盈利窗占比」（dt），全局 getByText 会触发 strict mode
  await expect(page.locator('.wf-summary').getByText('盈利窗占比', { exact: true })).toBeVisible()
  await expect(page.locator('.wf-summary .stat')).toHaveCount(6)

  // 一条龙评估：综合评分 + 高适配徽标 + 基准对比
  // 断言收窄到对应容器：名词解释按钮/词条文案里也含这些词，全局匹配会 strict mode
  await expect(page.locator('.eval-panel')).toBeVisible({ timeout: 120_000 })
  await expect(page.locator('.eval-header').getByText('综合评分', { exact: true })).toBeVisible()
  await expect(page.locator('.eval-header').getByText('对比买入持有')).toBeVisible()
  await expect(page.getByText(/适配性体检 \d+\/\d+/)).toBeVisible()
})

test('名词解释默认折叠，点击展开显示词条', async ({ page }) => {
  await page.goto('/backtest?startDate=2023-01-01&endDate=2025-12-31')
  await page.getByLabel('Walk-Forward 样本外验证').check()
  await page.getByLabel('一条龙评估').check()
  await page.getByRole('button', { name: '开始回测' }).click()
  await expect(page.locator('.eval-panel')).toBeVisible({ timeout: 120_000 })

  // 词条用 .g-term 类定位，与面板统计标签同名也不冲突
  const wfTerm = page.locator('.wf-panel .g-term', { hasText: '每窗独立开仓' })
  const evalTerm = page.locator('.eval-panel .g-term', { hasText: '高适配' })
  const metricTerm = page.locator('.metric-wrap .g-term', { hasText: '卡玛比率' })

  // 默认隐藏（内容在 DOM，但折叠框高度为 0）
  await expect(wfTerm).toBeHidden()
  await expect(evalTerm).toBeHidden()
  await expect(metricTerm).toBeHidden()

  // 点击「名词解释」按钮逐个展开
  await page.locator('.wf-panel .help-toggle').click()
  await expect(wfTerm).toBeVisible()
  await page.locator('.eval-panel .help-toggle').click()
  await expect(evalTerm).toBeVisible()
  await page.locator('.metric-wrap .help-toggle').click()
  await expect(metricTerm).toBeVisible()
})

test('AI 解读 Prompt 弹窗打包回测配置与各段报告', async ({ page }) => {
  await page.goto('/backtest?startDate=2023-01-01&endDate=2025-12-31')
  await page.getByLabel('Walk-Forward 样本外验证').check()
  await page.getByLabel('一条龙评估').check()
  await page.getByRole('button', { name: '开始回测' }).click()
  await expect(page.locator('.eval-panel')).toBeVisible({ timeout: 120_000 })

  await page.getByRole('button', { name: '🤖 AI 解读' }).click()
  const area = page.locator('.ai-prompt-area')
  await expect(area).toBeVisible()
  // textarea 的内容在 value 属性而非文本节点，用 toHaveValue（正则=子串匹配）
  await expect(area).toHaveValue(/# 角色设定/)
  await expect(area).toHaveValue(/# 回测配置/)
  await expect(area).toHaveValue(/SZ:000001（日线）/)
  await expect(area).toHaveValue(/- 总收益率：/)
  await expect(area).toHaveValue(/Walk-Forward 样本外验证/)
  await expect(area).toHaveValue(/# 一条龙评估/)
  await expect(area).toHaveValue(/# 评级（不看收益率/)
  await expect(area).toHaveValue(/# 背景与免责/)

  // 关闭弹窗回到报告
  await page.getByRole('button', { name: '关闭' }).click()
  await expect(area).toBeHidden()
})
