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
  await expect(page.getByText('盈利窗占比', { exact: true })).toBeVisible()
  await expect(page.locator('.wf-summary .stat')).toHaveCount(6)

  // 一条龙评估：综合评分 + 高适配徽标 + 基准对比
  await expect(page.locator('.eval-panel')).toBeVisible({ timeout: 120_000 })
  await expect(page.getByText('综合评分')).toBeVisible()
  await expect(page.getByText('对比买入持有')).toBeVisible()
  await expect(page.getByText(/适配性体检 \d+\/\d+/)).toBeVisible()
})
