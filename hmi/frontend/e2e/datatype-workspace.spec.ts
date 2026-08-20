import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

test('data type home lists OMS, IVI stub, and audio NVH then isolates workspaces', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/')
  await expect(page.getByTestId('data-type-home')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('data-type-card-oms_cabin')).toBeVisible()
  await expect(page.getByTestId('data-type-card-ivi_ui_stub')).toBeVisible()
  await expect(page.getByTestId('data-type-card-audio_array_spec')).toBeVisible()

  await page.getByTestId('data-type-card-audio_array_spec').click()
  await expect(page.getByTestId('data-type-workspace-banner')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('data-type-workspace-banner')).toContainText('麦克风阵列')
  await expect(page).toHaveURL(/\/w\/audio_array_spec/)
  await expect(page.getByTestId('data-type-workspace-banner')).toContainText('audio_nvh_timeline')

  await page.goto('/')
  await page.getByTestId('data-type-card-ivi_ui_stub').click()
  await expect(page.getByTestId('data-type-workspace-banner')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('data-type-workspace-banner')).toContainText('车机 UI')
  await expect(page).toHaveURL(/\/w\/ivi_ui_stub/)

  await page.goto('/')
  await page.getByTestId('data-type-card-oms_cabin').click()
  await expect(page.getByTestId('data-type-workspace-banner')).toContainText('舱内 OMS')
  await expect(page).toHaveURL(/\/w\/oms_cabin/)
})
