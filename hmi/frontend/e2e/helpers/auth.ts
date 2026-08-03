import { expect, type Page } from '@playwright/test'

const ADMIN_USER = process.env.E2E_ADMIN_USER ?? 'admin'
const ADMIN_PASS = process.env.E2E_ADMIN_PASS ?? 'admin123'

export async function loginAsAdmin(page: Page) {
  await page.goto('/login')
  const username = page.getByPlaceholder('admin')
  await expect(username).toBeVisible({ timeout: 30_000 })
  await username.fill(ADMIN_USER)
  const password = page.locator('input[type="password"]')
  await password.fill(ADMIN_PASS)
  await password.press('Enter')
  await expect(page.getByRole('menuitem', { name: '数据总览' })).toBeVisible({ timeout: 30_000 })
}
