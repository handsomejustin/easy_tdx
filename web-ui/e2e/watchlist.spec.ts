// 自选页 E2E：加入自选（行情校验 + 名称补全走 mock）→ 表格出现 → 删除 → 消失。
//
// 每轮 E2E 用独立的临时 EASY_TDX_CONFIG_DIR，自选从空开始，断言可写死。

import { expect, test } from '@playwright/test'

test('自选页增删自选', async ({ page }) => {
  await page.goto('/watchlist')

  // 初始为空（临时配置目录）
  await expect(page.locator('.empty-row')).toBeVisible()

  // 加入 600519（市场自动识别 SH；名称走 mock /mac/symbol-info → 贵州茅台）
  await page.fill('.code-input', '600519')
  await page.getByRole('button', { name: '加入自选' }).click()
  await expect(page.locator('.data-row')).toHaveCount(1, { timeout: 30_000 })
  await expect(page.locator('.data-row .cell-name')).toHaveText('贵州茅台')
  await expect(page.locator('.data-row .cell-code')).toHaveText('SH600519')

  // 删除后表格回到空态
  await page.locator('.data-row .del').first().click()
  await expect(page.locator('.data-row')).toHaveCount(0)
  await expect(page.locator('.empty-row')).toBeVisible()
})
