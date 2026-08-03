import { test, expect } from '@playwright/test'

const REVIEWER_USER = process.env.E2E_REVIEWER_USER ?? 'admin'
const REVIEWER_PASS = process.env.E2E_REVIEWER_PASS ?? 'admin123'

test('reviewer opens workbench v2', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(REVIEWER_USER)
  await page.getByLabel('密码').fill(REVIEWER_PASS)
  await page.getByLabel('密码').press('Enter')

  await expect(page.getByText('数据总览')).toBeVisible({ timeout: 15_000 })
  await page.goto('/review/workbench')
  await expect(page.getByTestId('review-workbench-page')).toBeVisible({ timeout: 15_000 })
})
