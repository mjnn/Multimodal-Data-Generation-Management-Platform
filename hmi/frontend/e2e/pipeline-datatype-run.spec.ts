import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

test('pipeline data-select tab requires data type before listing lake files', async ({ page }) => {
  await loginAsAdmin(page)
  await page.addInitScript(() => {
    sessionStorage.removeItem('hmi.dataTypeId')
  })
  await page.goto('/pipeline?tab=run')
  await expect(page.getByTestId('lake-run-bind-panel')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('tab', { name: '数据选择' })).toBeVisible()
  await expect(page.getByTestId('lake-run-pick-type-first')).toBeVisible()
  await expect(page.getByTestId('lake-run-slot-audio_primary')).toHaveCount(0)
})

test('pipeline data-select tab lists published DataTypes', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/pipeline?tab=run')
  await expect(page.getByTestId('lake-run-bind-panel')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('lake-run-data-type-select')).toBeVisible()
  await page.getByTestId('lake-run-data-type-select').click()
  const optionText = page.locator('.ant-select-dropdown .ant-select-item-option-content')
  await expect(optionText.filter({ hasText: 'oms_cabin' })).toBeVisible()
  await expect(optionText.filter({ hasText: 'ivi_ui_stub' })).toBeVisible()
})
