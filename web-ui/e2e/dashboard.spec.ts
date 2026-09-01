// 看板 E2E：五大指数区块加载 + SSE 合成行情到达后价格渲染。
//
// 数据链路：QuoteStreamer 轮询 mock 客户端 → SSE /stream/quotes →
// quoteStore → .idx-card。首帧在打开页面后 1~3 秒内到达（轮询循环
// 「无订阅 1s 待命 → 有订阅立即拉一轮」），盘外时段也不受影响。

import { expect, test } from '@playwright/test'

test('市场看板加载五大指数区块并渲染实时价格', async ({ page }) => {
  await page.goto('/')

  const cards = page.locator('.idx-card')
  await expect(cards).toHaveCount(5)

  const names = cards.locator('.idx-name')
  await expect(names).toHaveText(['上证指数', '深证成指', '创业板指', '科创50', '沪深300'])

  // SSE 首帧到达前价格是占位符「—」；合成行情到达后变为数值
  await expect(cards.first().locator('.idx-price')).toHaveText(/\d/, { timeout: 30_000 })

  // 市场统计卡也从 mock /market/stat 拿到数据（不再是「加载中…」）
  await expect(page.locator('.card', { hasText: '市场统计' }).locator('.stat-nums')).toBeVisible()
})
