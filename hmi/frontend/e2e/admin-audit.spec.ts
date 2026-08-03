import { test, expect } from '@playwright/test'

const ADMIN_USER = process.env.E2E_ADMIN_USER ?? 'admin'
const ADMIN_PASS = process.env.E2E_ADMIN_PASS ?? 'admin123'

test('admin opens audit log page', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(ADMIN_USER)
  await page.getByLabel('密码').fill(ADMIN_PASS)
  await page.getByLabel('密码').press('Enter')

  await page.waitForURL(/\/($|\?)/, { timeout: 15_000 })

  await page.goto('/admin/audit')
  await expect(page).toHaveURL(/\/admin\/audit$/)
  await expect(page.getByTestId('admin-audit-page')).toBeVisible({ timeout: 15_000 })
})
