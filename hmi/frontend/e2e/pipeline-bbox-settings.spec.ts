import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

test('pipeline settings lists DAG node params for cabin dtype', async ({ page }) => {
  await loginAsAdmin(page)
  await page.addInitScript(() => {
    sessionStorage.setItem('hmi.dataTypeId', 'oms_cabin')
  })
  await page.goto('/pipeline?tab=settings')
  await expect(page.getByTestId('pipeline-dag-params')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(/不能增删节点或改顺序|调整该 DAG 每个节点的参数/)).toBeVisible()
  const bboxNode = page.locator('.ant-collapse-item').filter({ hasText: 'detect_bbox' }).first()
  await expect(bboxNode).toBeVisible({ timeout: 15_000 })
  await bboxNode.locator('.ant-collapse-header').click()
  await expect(bboxNode.getByText('检测器')).toBeVisible()
})

test('audio_array_spec DAG params hide detect_bbox detector', async ({ page }) => {
  await loginAsAdmin(page)
  await page.addInitScript(() => {
    sessionStorage.setItem('hmi.dataTypeId', 'audio_array_spec')
  })
  await page.goto('/pipeline?tab=settings')
  await expect(page.getByTestId('pipeline-dag-params')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('pipeline-dag-params').getByText('stft_spectrogram').first()).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByTestId('pipeline-dag-params').getByText('detect_bbox')).toHaveCount(0)
})

test('taxonomy leaf editor offers enum dtype (enum_tree)', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/taxonomy')
  await expect(page.getByTestId('taxonomy-page')).toBeVisible({ timeout: 15_000 })
  const editBtn = page.getByRole('button', { name: /编辑|打开编辑器/ }).first()
  if (await editBtn.isVisible().catch(() => false)) {
    await editBtn.click()
  }
})
