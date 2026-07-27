import { test, expect } from '@playwright/test'

const ADMIN_USER = process.env.E2E_ADMIN_USER ?? 'admin'
const ADMIN_PASS = process.env.E2E_ADMIN_PASS ?? 'admin123'

test('admin opens review workbench page', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(ADMIN_USER)
  await page.getByLabel('密码').fill(ADMIN_PASS)
  await page.getByLabel('密码').press('Enter')

  await expect(page.getByText('数据总览')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('menuitem', { name: '校核' }).click()

  await expect(page.getByTestId('review-workbench-page')).toBeVisible()
  await expect(page.getByRole('heading', { name: '校核工作台' })).toBeVisible()
})
