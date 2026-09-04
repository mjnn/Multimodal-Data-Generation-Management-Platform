import { expect, test, type Page } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

async function fillNewMetaAndEnterCanvas(
  page: Page,
  fields: { id: string; title: string; purpose: string },
) {
  await expect(page.getByTestId('dtype-meta-modal')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('dag-canvas')).toHaveCount(0)
  const idBox = page.getByTestId('dtype-id')
  await expect(idBox).toBeEnabled()
  await expect(async () => {
    await idBox.click()
    await idBox.press('Control+A')
    await page.keyboard.insertText(fields.id)
    await expect(idBox).toHaveValue(fields.id)
  }).toPass({ timeout: 10_000 })
  await page.getByTestId('dtype-title').click()
  await page.getByTestId('dtype-title').fill(fields.title)
  await page.getByTestId('dtype-purpose').fill(fields.purpose)
  await expect(idBox).toHaveValue(fields.id, { timeout: 10_000 })
  await page.getByTestId('dtype-meta-confirm').click()
  await expect(page.getByTestId('dtype-meta-modal')).toBeHidden()
  await expect(page.getByTestId('dag-canvas')).toBeVisible()
  const canvasBox = await page.getByTestId('dag-canvas').boundingBox()
  expect(canvasBox?.height).toBeGreaterThan(200)
  expect(canvasBox?.height).toBeLessThan(400)
  await expect(page.getByTestId('dag-inspector')).toHaveCount(0)
  await expect(page.getByTestId('palette-group-toggle-control')).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByTestId('palette-op-if')).toHaveCount(0)
  await expect(page.getByTestId('dtype-meta-summary')).toBeVisible()
  await expect(page.locator('.ant-card-head').filter({ hasText: /^管线编排$/ })).toHaveCount(0)
  await expect(page.locator('.dag-canvas path.react-flow__edge-path')).toHaveAttribute('marker-end', /url/)
}

async function openPaletteGroup(page: Page, groupId: string) {
  const toggle = page.getByTestId(`palette-group-toggle-${groupId}`)
  await expect(toggle).toBeVisible()
  if ((await toggle.getAttribute('aria-expanded')) !== 'true') {
    await toggle.click()
  }
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
}

async function openOverviewCompose(page: Page) {
  await expect(page.getByTestId('overview-composer')).toHaveCount(0)
  await expect(page.getByTestId('dag-canvas')).toBeVisible()
  await page.getByTestId('dtype-overview-open').click()
  await expect(page.getByTestId('dag-canvas')).toHaveCount(0)
  await expect(page.getByTestId('dtype-overview-page')).toBeVisible()
  await expect(page.getByTestId('overview-composer')).toBeVisible()
  await expect(page.getByTestId('overview-composer-list')).toHaveCount(0)
  await expect(page.getByTestId('overview-composer-detail')).toBeVisible()
  await expect(page.getByTestId('overview-preview')).toBeVisible()
  await expect(page.getByTestId('overview-locked-labels_tree')).toBeVisible()
  await expect(page.getByTestId('overview-remove-labels_tree')).toHaveCount(0)
}

test('admin can create draft data type with pipeline component cards', async ({ page }) => {
  await loginAsAdmin(page)
  await expect(page.getByTestId('data-type-home')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('绑定源槽位')).toHaveCount(0)
  await page.getByTestId('dtype-new-btn').click()
  await expect(page.getByTestId('data-type-editor')).toBeVisible({ timeout: 15_000 })

  const id = `e2e_orch_${Date.now()}`
  await fillNewMetaAndEnterCanvas(page, {
    id,
    title: 'E2E 管线编排类型',
    purpose: 'Playwright 创建的 draft 配方',
  })

  await expect(page.getByTestId('dag-cloud-hint')).toBeVisible()
  await expect(page.getByTestId('dag-cloud-hint')).toContainText('本地按图执行；上云只跑公共前缀。')
  await expect(page.getByTestId('dag-node-label')).toBeVisible()
  await expect(page.getByTestId('dag-remove-label')).toHaveCount(0)

  await openPaletteGroup(page, 'audio')
  await page.getByTestId('palette-op-mel_spectrogram').click()
  await expect(page.getByTestId(/dag-node-.*mel_spectrogram/)).toBeVisible()

  await openOverviewCompose(page)

  await page.getByTestId('dtype-save').click()
  await expect(page.getByText(/已保存/)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('data-type-home')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId(`data-type-card-${id}`)).toBeVisible()
  await expect(page.getByTestId(`data-type-card-${id}`).getByText('draft', { exact: true })).toBeVisible()

  await page.getByTestId(`dtype-edit-${id}`).click()
  await expect(page.getByTestId('data-type-editor')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('dtype-id')).toHaveValue(id)
  await expect(page.getByTestId('dag-canvas')).toBeVisible()
  await expect(page.getByTestId('dag-node-label')).toBeVisible()

  // if without then/else fails PUT validate_graph — click after save, do not save.
  await openPaletteGroup(page, 'control')
  await page.getByTestId('palette-op-if').click()
  await expect(page.getByTestId(/dag-node-op-if-/)).toBeVisible()
  await expect(page.getByTestId('dag-cloud-lossy')).toBeVisible()
  await expect(page.getByTestId('dag-cloud-lossy')).toContainText(
    '图含 if 或打标后节点：上云不会执行这些分支。',
  )
})

test('can delete a DAG edge and node', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-new-btn').click()
  await fillNewMetaAndEnterCanvas(page, {
    id: `e2e_del_${Date.now()}`,
    title: 'E2E DAG delete',
    purpose: 'Playwright delete node and edge',
  })
  await expect(page.getByTestId('dag-remove-label')).toHaveCount(0)
  await expect(page.getByTestId('dag-remove-src-1')).toBeVisible()
  await expect(page.getByTestId('dag-remove-edge-src-1->stage-label')).toBeVisible()

  await page.getByTestId('dag-remove-edge-src-1->stage-label').click()
  await expect(page.getByTestId('dag-node-src-1')).toBeVisible()
  await expect(page.getByTestId('dag-node-label')).toBeVisible()
  await expect(page.getByTestId('dag-remove-edge-src-1->stage-label')).toHaveCount(0)

  await openPaletteGroup(page, 'control')
  await page.getByTestId('palette-op-if').click()
  await expect(page.getByTestId(/dag-node-op-if-/)).toBeVisible()
  await page.getByTestId(/dag-remove-op-if-/).click()
  await expect(page.getByTestId(/dag-node-op-if-/)).toHaveCount(0)
  await expect(page.getByTestId('dag-node-label')).toBeVisible()

  await page.getByTestId('dag-remove-src-1').click()
  await expect(page.getByTestId('dag-node-src-1')).toHaveCount(0)
  await expect(page.getByTestId('dag-node-label')).toBeVisible()
})

test('dragging a DAG node keeps sibling nodes', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-new-btn').click()
  await fillNewMetaAndEnterCanvas(page, {
    id: `e2e_drag_${Date.now()}`,
    title: 'E2E DAG drag',
    purpose: 'Playwright drag must not drop siblings',
  })
  const canvas = page.getByTestId('dag-canvas')
  await canvas.scrollIntoViewIfNeeded()
  const source = page.getByTestId('dag-node-src-1')
  const label = page.getByTestId('dag-node-label')
  await expect(source).toBeVisible()
  await expect(label).toBeVisible()
  await expect(page.locator('.react-flow__node')).toHaveCount(2)

  const box = await source.boundingBox()
  expect(box).toBeTruthy()
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2)
  await page.mouse.down()
  await page.mouse.move(box!.x + box!.width / 2 + 80, box!.y + box!.height / 2 + 40, { steps: 8 })
  await page.mouse.up()

  await expect(source).toBeVisible()
  await expect(label).toBeVisible()
  await expect(page.locator('.react-flow__node')).toHaveCount(2)
})

test('palette groups can collapse and expand', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-edit-oms_cabin').click()
  await expect(page.getByTestId('data-type-editor')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('pipeline-palette')).toBeVisible()
  await expect(page.getByTestId('palette-group-toggle-control')).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByTestId('palette-op-if')).toHaveCount(0)
  await expect(page.getByTestId('palette-op-mel_spectrogram')).toHaveCount(0)
  const collapsedBox = await page.getByTestId('pipeline-palette').boundingBox()
  expect(collapsedBox?.height).toBeLessThan(360)
  await openPaletteGroup(page, 'control')
  await expect(page.getByTestId('palette-op-if')).toBeVisible()
  await expect(page.getByTestId('palette-op-mel_spectrogram')).toHaveCount(0)
  await openPaletteGroup(page, 'audio')
  await expect(page.getByTestId('palette-op-mel_spectrogram')).toBeVisible()
  await page.getByTestId('palette-group-toggle-control').click()
  await expect(page.getByTestId('palette-op-if')).toHaveCount(0)
  await expect(page.getByTestId('palette-op-mel_spectrogram')).toBeVisible()
})

test('STFT cannot bind to a video-only slot', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-new-btn').click()
  await fillNewMetaAndEnterCanvas(page, {
    id: `e2e_stft_${Date.now()}`,
    title: 'E2E STFT',
    purpose: 'Playwright STFT bind',
  })
  await openPaletteGroup(page, 'audio')
  await page.getByTestId('palette-op-stft_spectrogram').click()
  await expect(page.getByTestId(/dag-node-.*stft_spectrogram/)).toBeVisible()
  await page.getByTestId(/dag-node-.*stft_spectrogram/).click()
  await expect(page.getByTestId('dag-inspector')).toBeVisible()
  await page.getByTestId('dag-inspector-close').click()
  await expect(page.getByTestId('dag-inspector')).toHaveCount(0)
  await page.getByTestId(/dag-node-.*stft_spectrogram/).click()
  await expect(page.getByTestId('dag-inspector')).toBeVisible()
  await expect(page.getByTestId('pipe-bind-stft_spectrogram-in')).toBeVisible()
})

test('export node can pick upstream products', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-new-btn').click()
  await fillNewMetaAndEnterCanvas(page, {
    id: `e2e_exp_${Date.now()}`,
    title: 'E2E export products',
    purpose: 'Playwright export picks upstream products',
  })
  await openPaletteGroup(page, 'audio')
  await page.getByTestId('palette-op-mel_spectrogram').click()
  await openPaletteGroup(page, 'control')
  await page.getByTestId('palette-op-export').click()
  await page.getByTestId(/dag-node-op-export-/).click()
  const picker = page.getByTestId('dag-export-products')
  await expect(picker).toBeVisible()
  await picker.locator('.ant-select').click()
  const drop = page.locator('.ant-select-dropdown').filter({ visible: true })
  await expect(drop.getByText(/标签树/)).toBeVisible()
  await expect(drop.getByText(/梅尔/)).toBeVisible()
  await drop.getByText(/标签树/).click()
  await expect(picker.getByText(/标签树/)).toBeVisible()
})

test('admin can open edit page for oms_cabin', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-edit-oms_cabin').click()
  await expect(page.getByTestId('data-type-editor')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('dtype-meta-modal')).toHaveCount(0)
  await expect(page.getByTestId('dtype-id')).toBeDisabled()
  await expect(page.getByTestId('dtype-id')).toHaveValue('oms_cabin')
  await expect(page.getByTestId('overview-composer-list')).toHaveCount(0)
  await expect(page.getByTestId('overview-composer-detail')).toBeVisible()
  await expect(page.getByTestId('overview-card-cabin_multicam')).toBeVisible()
  await expect(page.getByTestId('overview-locked-labels_tree')).toBeVisible()
  await expect(page.getByTestId('overview-remove-labels_tree')).toHaveCount(0)
  await expect(page.getByTestId('overview-card-clip_table')).toHaveCount(0)
  await expect(page.getByTestId('overview-card-nvh_spl_column')).toHaveCount(0)
  await expect(page.getByText('展示页排版')).toBeVisible()
  await page.getByTestId('dtype-overview-preset').click()
  const presetDrop = page.locator('.ant-select-dropdown').filter({ visible: true })
  await expect(presetDrop.getByText(/audio_nvh_timeline/)).toBeVisible()
  await presetDrop.getByText(/四通道频谱时间轴/).click()
  await expect(page.getByTestId('overview-card-nvh_spl_column')).toHaveCount(0)
  await expect(page.getByTestId('overview-card-nvh_spectrum')).toBeVisible()
  await expect(page.getByTestId('overview-card-cabin_multicam')).toHaveCount(0)
  await expect(page.getByTestId('dag-canvas')).toBeVisible()
  await expect(page.getByTestId('dag-inspector')).toHaveCount(0)
  await expect(page.getByTestId('palette-group-toggle-control')).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByTestId('palette-op-if')).toHaveCount(0)
  const canvasBox = await page.getByTestId('dag-canvas').boundingBox()
  expect(canvasBox?.height).toBeGreaterThan(200)
  expect(canvasBox?.height).toBeLessThan(400)
  await expect(page.getByTestId('dag-node-label')).toBeVisible()
  await page.getByTestId('dag-node-label').click()
  await expect(page.getByTestId('dag-inspector')).toBeVisible()
  await expect(page.getByTestId('dag-inspector').getByText('打标器')).toBeVisible()
  const canvasBoxAfter = await page.getByTestId('dag-canvas').boundingBox()
  const inspectorBox = await page.getByTestId('dag-inspector').boundingBox()
  expect(inspectorBox).toBeTruthy()
  expect(canvasBoxAfter).toBeTruthy()
  expect(inspectorBox!.x).toBeGreaterThan(canvasBoxAfter!.x)
  expect(inspectorBox!.y).toBeGreaterThanOrEqual(canvasBoxAfter!.y - 8)
  expect(inspectorBox!.y + inspectorBox!.height).toBeLessThanOrEqual(canvasBoxAfter!.y + canvasBoxAfter!.height + 8)
  await page.getByTestId('dag-inspector-close').click()
  await expect(page.getByTestId('dag-inspector')).toHaveCount(0)
  await page.getByTestId('dag-node-label').click()
  await expect(page.getByTestId('dag-inspector')).toBeVisible()
  await page.locator('.dag-canvas .react-flow__pane').click({ position: { x: 12, y: 12 } })
  await expect(page.getByTestId('dag-inspector')).toHaveCount(0)
})
