import { expect, test } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

test('lake page lists persisted sources after reload grouped by collection', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/lake')
  await expect(page.getByTestId('lake-page')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('lake-sources-table')).toBeVisible()

  const name = `reuse-${Date.now()}.txt`
  await page.locator('input[type="file"]').first().setInputFiles({
    name,
    mimeType: 'text/plain',
    buffer: Buffer.from(`persist across sessions ${name}`),
  })
  await page.locator('button').filter({ hasText: '入湖' }).click()
  await expect(page.getByText(/已入湖 1 个源文件/)).toBeVisible()
  await expect(page.getByTestId('lake-sources-table').getByText(name)).toBeVisible({ timeout: 15_000 })

  await page.reload()
  await expect(page.getByTestId('lake-sources-table')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('lake-sources-table').getByText(name)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('lake-collection-tag').first()).toBeVisible()
})

test('lake page hosts OSS browser tab (no standalone OSS nav)', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/lake')
  await expect(page.getByTestId('lake-page')).toBeVisible({ timeout: 20_000 })
  await page.getByRole('tab', { name: 'OSS 浏览' }).click()
  await expect(page.getByTestId('oss-browser-panel')).toBeVisible({ timeout: 15_000 })

  await page.goto('/oss')
  await expect(page).toHaveURL(/\/lake\?.*tab=oss/)
  await expect(page.getByTestId('oss-browser-panel')).toBeVisible({ timeout: 15_000 })
})

test('pipeline lake-run: select data type, multi-select eligible source, preflight then enable run', async ({
  page,
}) => {
  await loginAsAdmin(page)
  await page.goto('/lake')
  await expect(page.getByTestId('lake-page')).toBeVisible({ timeout: 20_000 })

  const name = `nvh-${Date.now()}.wav`
  await page.locator('input[type="file"]').first().setInputFiles({
    name,
    mimeType: 'audio/wav',
    buffer: Buffer.from(`RIFF....WAVEfmt ${name}`),
  })
  await page.locator('button').filter({ hasText: '入湖' }).click()
  await expect(page.getByText(/已入湖 1 个源文件/)).toBeVisible()
  await expect(page.getByTestId('lake-sources-table').getByText(name)).toBeVisible({ timeout: 15_000 })
  await expect(
    page.getByTestId('lake-sources-table').locator('.ant-tag').filter({ hasText: /^\.wav$/ }).first(),
  ).toBeVisible()

  await page.goto('/pipeline?tab=run')
  await expect(page.getByTestId('lake-run-bind-panel')).toBeVisible({ timeout: 20_000 })

  await page.getByTestId('lake-run-data-type-select').click()
  const audioOption = page
    .locator('.ant-select-dropdown .ant-select-item-option-content')
    .filter({ hasText: 'audio_array_spec' })
    .first()
  await expect(audioOption).toBeVisible()
  await audioOption.click()

  const audioSlot = page.getByTestId('lake-run-slot-audio_primary')
  await expect(audioSlot).toBeVisible({ timeout: 15_000 })
  await expect(audioSlot.getByText(name)).toBeVisible()
  await audioSlot.locator('.ant-table-row').filter({ hasText: name }).first().getByRole('checkbox').check()

  await page.getByTestId('lake-run-preflight').click()
  await expect(page.getByTestId('lake-run-bind-panel').getByText('预检通过')).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByTestId('lake-run-create-run')).toBeEnabled()
})

test('pipeline lake-run: text source filtered out for ivi_ui_stub', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/lake')
  await expect(page.getByTestId('lake-page')).toBeVisible({ timeout: 20_000 })

  const name = `note-${Date.now()}.txt`
  await page.locator('input[type="file"]').first().setInputFiles({
    name,
    mimeType: 'text/plain',
    buffer: Buffer.from(`hello lake ${name}`),
  })
  await page.locator('button').filter({ hasText: '入湖' }).click()
  await expect(page.getByText(/已入湖 1 个源文件/)).toBeVisible()

  await page.goto('/pipeline?tab=run')
  await expect(page.getByTestId('lake-run-bind-panel')).toBeVisible({ timeout: 20_000 })
  await page.getByTestId('lake-run-data-type-select').click()
  await page
    .locator('.ant-select-dropdown .ant-select-item-option-content')
    .filter({ hasText: 'ivi_ui_stub' })
    .first()
    .click()

  await expect(page.getByTestId('lake-run-slot-ui_media')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('lake-run-sources-table').getByText(name)).toHaveCount(0)
  await expect(page.getByTestId('lake-run-slot-ui_media').getByText(name)).toHaveCount(0)
})
