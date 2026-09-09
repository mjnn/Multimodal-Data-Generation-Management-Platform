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

test('lake products tab shows lineage for run step and source file', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/lake')
  await expect(page.getByTestId('lake-page')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('heading', { name: '数据源' })).toBeVisible()
  await expect(page.getByRole('tab', { name: '产物浏览' })).toBeVisible()

  const name = `prod-${Date.now()}.wav`
  await page.locator('input[type="file"]').first().setInputFiles({
    name,
    mimeType: 'audio/wav',
    buffer: Buffer.from(`RIFF....WAVEfmt ${name}`),
  })
  await page.locator('button').filter({ hasText: '入湖' }).click()
  await expect(page.getByText(/已入湖 1 个源文件/)).toBeVisible()

  const sourcesRes = await page.request.get('/api/platform/sources?limit=200')
  expect(sourcesRes.ok(), await sourcesRes.text()).toBeTruthy()
  const sourcesBody = (await sourcesRes.json()) as { items: { source_id: string; filename?: string }[] }
  const src = sourcesBody.items.find((item) => item.filename === name)
  expect(src).toBeTruthy()

  const runRes = await page.request.post('/api/platform/runs', {
    data: { data_type_id: 'audio_array_spec', source_ids: [src!.source_id] },
  })
  expect(runRes.ok(), await runRes.text()).toBeTruthy()
  const run = (await runRes.json()) as { run_id: string }

  const lookupRes = await page.request.post('/api/platform/products/lookup', {
    data: {
      input_ids: [src!.source_id],
      op_id: 'mel_spectrogram',
      params: { n_mels: 64 },
      artifact_path: `runs/e2e/${name}/mel.png`,
      run_id: run.run_id,
    },
  })
  expect(lookupRes.ok(), await lookupRes.text()).toBeTruthy()

  await page.getByRole('tab', { name: '产物浏览' }).click()
  await expect(page.getByTestId('lake-products-table')).toBeVisible()
  await page.getByTestId('lake-products-refresh').click()
  const row = page.getByTestId('lake-products-table').locator('.ant-table-row').filter({ hasText: run.run_id })
  await expect(row).toBeVisible({ timeout: 15_000 })
  await expect(row.getByText(name, { exact: true })).toBeVisible()
  await expect(row.getByText('梅尔频谱').first()).toBeVisible()
  await expect(row.getByText(/来自管线运行/)).toBeVisible()
  await expect(row.getByText(/步骤「梅尔频谱」/)).toBeVisible()
  await expect(row.getByText(new RegExp(`数据源 ${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`))).toBeVisible()
  const rowBox = await row.boundingBox()
  expect(rowBox, 'products row should render').toBeTruthy()
  expect(rowBox!.height, 'lineage must not wrap character-by-character').toBeLessThan(96)
})

test('lake compose unit then audio_defect bind auto-fills slots from that unit', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/lake')
  await expect(page.getByTestId('lake-page')).toBeVisible({ timeout: 20_000 })

  const stamp = Date.now()
  const wavName = `defect-${stamp}.wav`
  const jsonName = `defect-${stamp}.json`
  const extraWav = `other-${stamp}.wav`
  await page.locator('input[type="file"]').first().setInputFiles([
    {
      name: wavName,
      mimeType: 'audio/wav',
      buffer: Buffer.from(`RIFF....WAVEfmt ${wavName}`),
    },
    {
      name: jsonName,
      mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify({ tag: `e2e-${stamp}` })),
    },
    {
      name: extraWav,
      mimeType: 'audio/wav',
      buffer: Buffer.from(`RIFF....WAVEfmt ${extraWav}`),
    },
  ])
  await page.locator('button').filter({ hasText: '入湖' }).click()
  await expect(page.getByText(/已入湖 3 个源文件/)).toBeVisible()

  const table = page.getByTestId('lake-sources-table')
  await table.locator('.ant-table-row').filter({ hasText: wavName }).getByRole('checkbox').check()
  await table.locator('.ant-table-row').filter({ hasText: jsonName }).getByRole('checkbox').check()
  const unitTitle = `e2e-unit-${stamp}`
  await page.getByTestId('lake-compose-unit-title').fill(unitTitle)
  await page.getByTestId('lake-compose-unit').click()
  await expect(page.getByTestId('lake-unit-row').filter({ hasText: unitTitle })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('lake-unit-title').filter({ hasText: unitTitle })).toBeVisible()

  await page.goto('/pipeline?tab=run')
  await expect(page.getByTestId('lake-run-bind-panel')).toBeVisible({ timeout: 20_000 })
  await page.getByTestId('lake-run-data-type-select').click()
  await page
    .locator('.ant-select-dropdown .ant-select-item-option-content')
    .filter({ hasText: 'audio_defect' })
    .first()
    .click()

  await expect(page.getByTestId('lake-run-unit-list')).toBeVisible({ timeout: 15_000 })
  await page.getByTestId('lake-run-unit-list').locator('.ant-card').filter({ hasText: unitTitle }).click()
  const wavSlot = page.getByTestId('lake-run-slot-src-1')
  const jsonSlot = page.getByTestId('lake-run-slot-op-source-1788845633260')
  await expect(wavSlot).toBeVisible({ timeout: 15_000 })
  await expect(wavSlot.getByText(wavName)).toBeVisible()
  await expect(wavSlot.getByText(extraWav)).toHaveCount(0)
  await expect(jsonSlot.getByText(jsonName)).toBeVisible()
  await expect(wavSlot.locator('.ant-table-row').filter({ hasText: wavName }).getByRole('checkbox')).toBeChecked()
  await expect(jsonSlot.locator('.ant-table-row').filter({ hasText: jsonName }).getByRole('checkbox')).toBeChecked()

  await page.getByTestId('lake-run-preflight').click()
  await expect(page.getByTestId('lake-run-bind-panel').getByText('预检通过')).toBeVisible({
    timeout: 15_000,
  })
  await expect(page.getByTestId('lake-run-create-run')).toBeEnabled()
})
