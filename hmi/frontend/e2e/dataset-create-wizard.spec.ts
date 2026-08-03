import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

async function openCreateDatasetModal(page: import('@playwright/test').Page) {
  await loginAsAdmin(page)
  await page.goto('/datasets')
  await expect(page.getByTestId('dataset-list-page')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: '创建数据集' }).click()
  await expect(page.getByTestId('dataset-preview-panel')).toBeVisible()
}

test('M7.8 export recommendation visible and apply fills form', async ({ page }) => {
  await openCreateDatasetModal(page)

  await expect(page.getByTestId('export-recommendation')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('导出建议')).toBeVisible()

  await page.getByRole('button', { name: '采用建议' }).click()
  await expect(page.getByText('已应用导出建议')).toBeVisible({ timeout: 5_000 })
})

test('M7.5 parquet checkbox and M8 balance dimension in create wizard', async ({ page }) => {
  await openCreateDatasetModal(page)

  const parquetCheckbox = page.getByText('同时导出 Parquet')
  await expect(parquetCheckbox).toBeVisible()
  await parquetCheckbox.click()

  await expect(page.getByText('类别平衡（可选 · M8）')).toBeVisible()
  await expect(page.getByText('平衡维度')).toBeVisible()
})
