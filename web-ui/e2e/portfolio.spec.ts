// 组合回测页 E2E：多标的 + 策略 → 开始组合回测 → 完整绩效指标 + 各标的对比
// + 附加分析（组合 WF / 组合一条龙）+ 组合成交明细 + AI 解读弹窗。
//
// 行情来自 mock /bars（确定性合成 OHLCV，2600 根/标的），组合回测/WF/一条龙
// 走真实后端引擎。

import { expect, test } from '@playwright/test'

test('组合回测全流程：评级 + 净值 + 完整指标 + 对比 + 成交明细', async ({ page }) => {
  await page.goto('/portfolio?startDate=2023-01-01&endDate=2025-12-31')

  // 默认两只标的（SZ:000001 / SH:600519），默认策略 ma_cross
  await expect(page.getByRole('button', { name: '开始组合回测' })).toBeEnabled()
  await page.getByRole('button', { name: '开始组合回测' }).click()

  // 组合评级 + 组合整体绩效（含年化收益）
  await expect(page.getByRole('heading', { name: '组合评级' })).toBeVisible({ timeout: 60_000 })
  const perfSummary = page.locator('.report-section', { hasText: '组合整体绩效' })
  await expect(perfSummary.getByText('年化收益', { exact: true })).toBeVisible()

  // 组合净值曲线（echarts canvas）
  await expect(page.getByRole('heading', { name: '组合净值曲线' })).toBeVisible()
  await expect(page.locator('.report-section canvas').first()).toBeVisible()

  // 完整绩效指标（v1.31 与单标的同口径，含 SQN/最大连胜）
  const perfSection = page.locator('.report-section', { hasText: '组合绩效指标' })
  await expect(perfSection.locator('.metric-label', { hasText: 'SQN 系统质量' })).toBeVisible()
  await expect(perfSection.locator('.metric-label', { hasText: '最大连胜' })).toBeVisible()
  await expect(perfSection.locator('.metric-label', { hasText: '最大连亏' })).toBeVisible()

  // 各标的对比 + 组合成交明细（带标的列）
  await expect(page.getByRole('heading', { name: '各标的绩效对比' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /组合成交明细（\d+ 笔/ })).toBeVisible()
  const tradeSection = page.locator('.report-section', { hasText: '组合成交明细' })
  await expect(tradeSection.locator('th', { hasText: '标的' })).toBeVisible()
})

test('勾选附加分析后出现组合 WF 面板、一条龙评估与 AI 组合 Prompt', async ({ page }) => {
  await page.goto('/portfolio?startDate=2023-01-01&endDate=2025-12-31')

  await page.getByLabel('Walk-Forward 样本外验证').check()
  await expect(page.getByLabel('一条龙评估')).toBeVisible()
  await page.getByLabel('一条龙评估').check()

  await page.getByRole('button', { name: '开始组合回测' }).click()

  // 组合 WF：与单标的同构面板（逐窗柱状图 + 6 项汇总）
  await expect(page.getByRole('heading', { name: 'Walk-Forward 样本外验证' })).toBeVisible({
    timeout: 60_000,
  })
  await expect(page.locator('.wf-chart canvas')).toBeVisible({ timeout: 120_000 })
  await expect(page.locator('.wf-summary .stat')).toHaveCount(6)

  // 组合一条龙：综合评分 + 基准对比（等权买入持有组合）
  await expect(page.locator('.eval-panel')).toBeVisible({ timeout: 180_000 })
  await expect(page.locator('.eval-header').getByText('综合评分', { exact: true })).toBeVisible()
  await expect(page.locator('.eval-header').getByText('对比买入持有')).toBeVisible()

  // AI 解读弹窗：组合版 Prompt 打包（组合配置 + 各标的表现 + WF + 一条龙）
  await page.getByRole('button', { name: '🤖 AI 解读' }).click()
  const area = page.locator('.ai-prompt-area')
  await expect(area).toBeVisible()
  await expect(area).toHaveValue(/组合回测报告（同一个策略分别跑在一篮子标的上/)
  await expect(area).toHaveValue(/# 组合回测配置/)
  await expect(area).toHaveValue(/SZ:000001、SH:600519/)
  await expect(area).toHaveValue(/# 各标的表现（按收益降序/)
  await expect(area).toHaveValue(/Walk-Forward 样本外验证/)
  await expect(area).toHaveValue(/# 一条龙评估/)
  await expect(area).toHaveValue(/# 背景与免责/)

  await page.getByRole('button', { name: '关闭' }).click()
  await expect(area).toBeHidden()
})
