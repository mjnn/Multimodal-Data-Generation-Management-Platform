import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

test('taxonomy hub insights tab and context bar', async ({ page }) => {
  await loginAsAdmin(page)

  await page.goto('/taxonomy?tab=insights')
  await expect(page.getByTestId('taxonomy-page')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('taxonomy-context-bar')).toBeVisible()
  await expect(page.getByTestId('taxonomy-insights-panel')).toBeVisible()
})

test('dataset create modal shows taxonomy context bar', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/datasets')
  await page.getByRole('button', { name: '创建数据集' }).click()
  await expect(page.getByTestId('taxonomy-context-bar')).toBeVisible({ timeout: 15_000 })
})

test('taxonomy versions tab shows lineage bar', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/taxonomy')
  await expect(page.getByTestId('taxonomy-lineage-bar')).toBeVisible({ timeout: 15_000 })
})

test('taxonomy version drawer shows diff panel', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/taxonomy')
  const viewBtn = page.getByRole('button', { name: '查看' }).first()
  await viewBtn.click()
  await expect(page.getByTestId('taxonomy-version-meta')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('taxonomy-diff-panel')).toBeVisible({ timeout: 15_000 })
})
