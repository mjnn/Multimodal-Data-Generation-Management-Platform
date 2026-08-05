import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

async function openCreateDatasetWizard(page: import('@playwright/test').Page, step: 'filter' | 'sample' | 'export' | 'review' = 'filter') {
  await loginAsAdmin(page)
  await page.goto('/datasets')
  await expect(page.getByTestId('dataset-list-page')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('button', { name: '创建数据集' }).click()

  await page.getByPlaceholder('例如 training_v1').fill('e2e_wizard_dataset')
  await page.getByRole('button', { name: '下一步' }).click()

  if (step === 'filter') return

  await page.getByRole('button', { name: '下一步' }).click()
  if (step === 'sample') return

  await page.getByRole('button', { name: '下一步' }).click()
  if (step === 'export') return

  await page.getByRole('button', { name: '下一步' }).click()
}

test('M7.8 export recommendation visible and apply fills form', async ({ page }) => {
  await openCreateDatasetWizard(page, 'export')

  await expect(page.getByTestId('dataset-preview-panel')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('export-recommendation')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('导出建议')).toBeVisible()

  await page.getByRole('button', { name: '采用建议' }).click()
  await expect(page.getByText('已应用导出建议')).toBeVisible({ timeout: 5_000 })
})

test('M7.5 parquet checkbox and M8 balance dimension in create wizard', async ({ page }) => {
  await openCreateDatasetWizard(page, 'sample')

  await expect(page.getByTestId('dataset-preview-panel')).toBeVisible()
  await expect(page.getByText('类别平衡（可选）')).toBeVisible()
  await expect(page.getByText('平衡维度')).toBeVisible()

  await page.getByRole('button', { name: '下一步' }).click()
  const parquetCheckbox = page.getByText('同时导出 Parquet')
  await expect(parquetCheckbox).toBeVisible()
  await parquetCheckbox.click()
})
