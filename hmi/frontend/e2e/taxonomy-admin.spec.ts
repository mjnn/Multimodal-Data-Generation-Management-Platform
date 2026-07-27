import { test, expect } from '@playwright/test'

const ADMIN_USER = process.env.E2E_ADMIN_USER ?? 'admin'
const ADMIN_PASS = process.env.E2E_ADMIN_PASS ?? 'admin123'

test('admin opens taxonomy page and sees version list', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(ADMIN_USER)
  await page.getByLabel('密码').fill(ADMIN_PASS)
  await page.getByLabel('密码').press('Enter')

  await expect(page.getByText('数据总览')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('menuitem', { name: '标签树' }).click()

  await expect(page.getByTestId('taxonomy-page')).toBeVisible()
  await expect(page.getByRole('heading', { name: '标签树管理' })).toBeVisible()
  await expect(page.getByText('版本列表')).toBeVisible()
})
