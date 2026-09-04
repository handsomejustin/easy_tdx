// 策略库 E2E：回测出结果 → 保存策略（含成绩快照）→ 策略库页可见。

import { expect, test } from '@playwright/test'

test('回测结果保存到策略库并在策略库页可见', async ({ page }) => {
  await page.goto('/backtest?startDate=2024-01-01&endDate=2025-12-31')

  // 跑一次回测拿到结果（保存按钮只在有结果时出现）
  await page.getByRole('button', { name: '开始回测' }).click()
  await expect(page.getByRole('button', { name: '💾 保存策略' })).toBeVisible({ timeout: 60_000 })

  // 打开保存对话框（名称已预填「双均线交叉 · 000001 · 平安银行」，
  // 股票名由 /mac/symbol-info 异步补全，toHaveValue 自动重试等待）
  await page.getByRole('button', { name: '💾 保存策略' }).click()
  await expect(page.locator('.modal')).toBeVisible()
  const nameInput = page.getByPlaceholder('给这个策略起个名')
  await expect(nameInput).toHaveValue('双均线交叉 · 000001 · 平安银行')
  await nameInput.fill('E2E 冒烟策略')

  await page.locator('.modal-actions .primary').click()
  await expect(page.getByText('✓ 已保存到策略库')).toBeVisible()

  // 策略库页列出刚保存的条目（SQLite strategies.db 落在临时 EASY_TDX_CONFIG_DIR）
  await page.goto('/strategies')
  await expect(page.getByText('E2E 冒烟策略').first()).toBeVisible({ timeout: 30_000 })
})
