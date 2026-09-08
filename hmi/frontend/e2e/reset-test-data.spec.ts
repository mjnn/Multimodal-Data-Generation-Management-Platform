import { expect, test } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

test('reset confirm lists lake OSS wipe and the seed DataTypes', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/')
  await expect(page.getByTestId('hmi-reset-button')).toBeVisible({ timeout: 15_000 })
  await page.getByTestId('hmi-reset-button').click()

  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByTestId('reset-confirm-datatypes')).toContainText('oms_cabin')
  await expect(dialog.getByTestId('reset-confirm-datatypes')).toContainText('ivi_ui_stub')
  await expect(dialog.getByTestId('reset-confirm-datatypes')).toContainText('audio_array_spec')
  await expect(dialog.getByTestId('reset-confirm-datatypes')).toContainText('audio_defect')
  await expect(dialog.getByTestId('reset-confirm-lake')).toContainText('sources/')
  await expect(dialog.getByTestId('reset-confirm-lake')).toContainText('lake_images/')
  await expect(dialog.getByTestId('reset-confirm-lake')).toContainText('platform_runs/')
  await expect(dialog.getByTestId('reset-confirm-products')).toContainText('platform_product')
  await expect(dialog.getByTestId('reset-confirm-products')).toContainText('sdk_runs')
  await expect(dialog.getByRole('button', { name: '确认重置' })).toBeVisible()
  await page.keyboard.press('Escape')
})
