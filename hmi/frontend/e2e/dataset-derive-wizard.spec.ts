import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'
import { gotoReadyBaseDetail } from './helpers/dataset'

test.setTimeout(120_000)

test('M8 derive wizard shows label crop balance and preview', async ({ page }) => {
  await loginAsAdmin(page)
  await gotoReadyBaseDetail(page)

  const deriveBtn = page.getByTestId('derive-dataset-btn')
  await expect(deriveBtn).toBeVisible({ timeout: 10_000 })
  await deriveBtn.click()

  await expect(page.getByRole('dialog')).toContainText('派生扩展快照')
  await expect(page.getByTestId('derive-preview-panel')).toBeVisible()
  await expect(page.getByText('标签树裁剪（可选）')).toBeVisible()
  await expect(page.getByText('按标签值筛选 clip（可选）')).toBeVisible()
  await expect(page.getByText('类别平衡（可选）')).toBeVisible()
  await expect(page.getByText('平衡维度')).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: '当前快照条件' })).toBeVisible()

  await page.getByLabel('每类最多行数').fill('2')
  await expect(page.getByTestId('derive-preview-panel')).toContainText('预估导出行', { timeout: 30_000 })
})

test('M8 derive creates child snapshot with parent link', async ({ page }) => {
  await loginAsAdmin(page)
  await gotoReadyBaseDetail(page)

  await page.getByTestId('derive-dataset-btn').click()
  await expect(page.getByTestId('derive-preview-panel')).toBeVisible()

  const childName = `e2e_derived_${Date.now()}`
  await page.getByLabel('名称').fill(childName)
  await page.getByLabel('每类最多行数').fill('5')
  await page.getByRole('button', { name: '创建派生快照' }).click()

  await expect(page.getByText('派生快照已创建')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('dataset-detail-page')).toBeVisible()
  await expect(page.getByText(childName)).toBeVisible()
  await expect(page.getByTestId('dataset-lineage-bar')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('直接父快照')).toBeVisible()
  await expect(page.getByRole('button', { name: '派生扩展' })).toBeVisible()
})
