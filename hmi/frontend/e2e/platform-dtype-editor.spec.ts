import { expect, test, type Locator, type Page } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

/** Ant Design 6 showSearch Select remounts the search input as the dropdown opens. */
async function openAntSelect(bind: Locator) {
  const box = bind.getByRole('combobox')
  await expect(box).toBeEnabled({ timeout: 15_000 })
  await box.click({ force: true })
}

async function fillNewMetaAndEnterCanvas(
  page: Page,
  fields: { id: string; title: string; purpose: string },
) {
  await expect(page.getByTestId('dtype-meta-modal')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('dtype-meta-modal').getByText('绑定标签树 taxonomy_id')).toBeVisible()
  await expect(page.getByTestId('dtype-meta-modal').getByTestId('dtype-overview-preset')).toHaveCount(0)
  await expect(page.getByTestId('dag-canvas')).toHaveCount(0)
  const idBox = page.getByTestId('dtype-id')
  await expect(idBox).toBeEnabled()
  await page.getByTestId('dtype-title').click()
  await page.getByTestId('dtype-title').fill(fields.title)
  await page.getByTestId('dtype-purpose').fill(fields.purpose)
  await expect(async () => {
    await idBox.click()
    await idBox.press('Control+A')
    await page.keyboard.insertText(fields.id)
    await expect(idBox).toHaveValue(fields.id)
  }).toPass({ timeout: 10_000 })
  await page.getByTestId('dtype-meta-confirm').click()
  await expect(page.getByTestId('dtype-meta-modal')).toBeHidden()
  await expect(page.getByTestId('dag-canvas')).toBeVisible()
  const canvasBox = await page.getByTestId('dag-canvas').boundingBox()
  expect(canvasBox?.height).toBeGreaterThan(300)
  expect(canvasBox?.height).toBeLessThan(720)
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
  await expect(page.getByTestId('dtype-overview-page').getByTestId('dtype-overview-preset')).toHaveCount(0)
  await expect(page.getByTestId('overview-add-labels_tree')).toBeVisible()
  await expect(page.getByTestId('overview-locked-labels_tree')).toHaveCount(0)
  await expect(page.getByTestId('overview-card-labels_tree')).toHaveCount(0)
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
  await expect(page.getByTestId('dag-remove-stage-label')).toBeVisible()

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
  await expect(page.getByTestId('dag-remove-stage-label')).toBeVisible()
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
  await expect(page.getByTestId('palette-op-source')).toBeVisible()
  await expect(page.getByTestId('palette-op-review')).toHaveCount(0)
  await expect(page.getByTestId('palette-op-export')).toHaveCount(0)
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

test('palette ASR can bind into an earlier card and save', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-new-btn').click()
  const id = `e2e_asr_bind_${Date.now()}`
  await fillNewMetaAndEnterCanvas(page, {
    id,
    title: 'E2E palette ASR bind',
    purpose: 'Playwright save after binding later palette ASR',
  })
  await openPaletteGroup(page, 'audio')
  await page.getByTestId('palette-op-transcribe').click()
  await expect(page.getByTestId(/dag-node-op-transcribe-/)).toBeVisible()

  await page.getByTestId('dag-node-label').click()
  await expect(page.getByTestId('dag-inspector')).toBeVisible()
  const bind = page.getByTestId('pipe-bind-label-in')
  await expect(bind).toBeVisible()
  await bind.locator('.ant-select').click()
  const drop = page.locator('.ant-select-dropdown').filter({ visible: true })
  await expect(drop.getByText(/音频 ASR/)).toBeVisible()
  await drop.getByText(/音频 ASR/).click()
  await expect(bind.getByText(/音频 ASR/)).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByTestId('dag-inspector-close').click()
  await expect(page.getByTestId('dag-inspector')).toHaveCount(0)

  await openOverviewCompose(page)
  await page.getByTestId('dtype-save').click()
  await expect(page.getByText(/配方校验失败|must reference a card above/)).toHaveCount(0)
  await expect(page.getByText(/已保存/)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('data-type-home')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId(`data-type-card-${id}`)).toBeVisible()
})

test('oms_cabin DAG nodes use palette catalog operators', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-edit-oms_cabin').click()
  await expect(page.getByTestId('data-type-editor')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('dag-canvas')).toBeVisible()
  await expect(page.getByTestId('dag-node-parse_bag')).toBeVisible()
  await expect(page.getByTestId('dag-node-parse_bag')).toContainText('ROSBAG 解析器')
  await expect(page.getByTestId('dag-node-extract_frames')).toContainText('视频抽帧')
  await expect(page.getByTestId('dag-node-encode_preview')).toContainText('视频编码器')
  await expect(page.getByTestId('dag-node-transcribe')).toContainText('音频 ASR')
  await expect(page.getByTestId('dag-node-embed')).toContainText('向量化器')
  await expect(page.getByTestId('dag-node-label')).toBeVisible()
  await expect(page.getByTestId('dag-node-prep-0-parse_bag')).toHaveCount(0)

  await openPaletteGroup(page, 'parse')
  await expect(page.getByTestId('palette-op-parse_bag')).toBeVisible()
  await expect(page.getByTestId('palette-op-extract_frames')).toBeVisible()
  await expect(page.getByTestId('palette-op-text_to_json')).toBeVisible()
  await expect(page.getByTestId('palette-op-json_extract')).toBeVisible()
  await expect(page.getByTestId('palette-op-json_extract')).toContainText('JSON 值提取')
  await openPaletteGroup(page, 'encode')
  await expect(page.getByTestId('palette-op-encode_preview')).toBeVisible()
  await openPaletteGroup(page, 'audio')
  await expect(page.getByTestId('palette-op-transcribe')).toBeVisible()
  await openPaletteGroup(page, 'detect_ai')
  await expect(page.getByTestId('palette-op-embed')).toBeVisible()
  await expect(page.getByTestId('palette-op-label_tree_input')).toBeVisible()
  await expect(page.getByTestId('palette-op-label_tree_input')).toContainText('标签树输入')

  await expect(page.getByTestId('dag-node-label')).toContainText('AI打标器')

  await page.getByTestId('dag-node-parse_bag').click()
  await expect(page.getByTestId('dag-inspector')).toBeVisible()
  await expect(page.getByTestId('dag-inspector')).toContainText('ROSBAG 解析器')
  await expect(page.getByTestId('dag-inspector')).toContainText('parse_bag')
})

test('palette JSON extract and label tree input can be added', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-new-btn').click()
  await fillNewMetaAndEnterCanvas(page, {
    id: `e2e_json_fill_${Date.now()}`,
    title: 'E2E JSON extract + label tree',
    purpose: 'Playwright catalog ops',
  })
  await openPaletteGroup(page, 'parse')
  await page.getByTestId('palette-op-json_extract').click()
  const extractNode = page.getByTestId(/dag-node-op-json_extract-/)
  await expect(extractNode).toBeVisible()
  await expect(extractNode).toContainText('JSON 值提取')
  await extractNode.click()
  await expect(page.getByTestId('dag-inspector')).toBeVisible()
  await expect(page.getByTestId('pipe-json-extract-keys')).toBeVisible()
  await page.getByTestId('pipe-json-extract-key-0').fill('a')
  await page.getByTestId('pipe-json-extract-add').click()
  await expect(page.getByTestId('pipe-json-extract-key-1')).toBeVisible()
  await page.getByTestId('pipe-json-extract-key-1').fill('b')
  await expect(page.getByTestId('dag-inspector')).toContainText('a.b')

  await page.getByTestId('dag-inspector-close').click()
  await expect(page.getByTestId('dag-inspector')).toHaveCount(0)

  await openPaletteGroup(page, 'detect_ai')
  await page.getByTestId('palette-op-label_tree_input').click()
  const fillNode = page.getByTestId(/dag-node-op-label_tree_input-/)
  await expect(fillNode).toBeVisible()
  await expect(fillNode).toContainText('标签树输入')
  await fillNode.click()
  await expect(page.getByTestId('pipe-label-tree-input')).toBeVisible()
})

test('can delete AI labeler when label tree input is the labels sink', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-new-btn').click()
  await fillNewMetaAndEnterCanvas(page, {
    id: `e2e_fill_sink_${Date.now()}`,
    title: 'E2E fill without AI labeler',
    purpose: 'Playwright delete AI when JSON fills the tree',
  })
  await openPaletteGroup(page, 'detect_ai')
  await page.getByTestId('dag-node-src-1').click()
  await page.getByTestId('palette-op-label_tree_input').click()
  const fillNode = page.getByTestId(/dag-node-op-label_tree_input-/)
  await expect(fillNode).toBeVisible()
  await expect(page.getByTestId(/dag-remove-edge-src-1-out->op-label_tree_input-/)).toBeVisible()
  await expect(page.getByTestId('dag-remove-stage-label')).toBeVisible()
  await page.getByTestId('dag-remove-stage-label').click()
  await expect(page.getByTestId('dag-node-label')).toHaveCount(0)
  await expect(fillNode).toBeVisible()
  await expect(page.getByTestId('dag-node-src-1')).toBeVisible()
  await expect(page.getByTestId(/dag-remove-edge-src-1-out->op-label_tree_input-/)).toBeVisible()
  await openOverviewCompose(page)
  await page.getByTestId('dtype-save').click()
  await expect(page.getByText(/已保存/)).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('data-type-home')).toBeVisible({ timeout: 15_000 })
})

test('ivi_ui_stub DAG nodes use palette catalog operators', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-edit-ivi_ui_stub').click()
  await expect(page.getByTestId('data-type-editor')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('dag-canvas')).toBeVisible()
  await expect(page.getByTestId('dag-node-extract_frames')).toContainText('视频抽帧')
  await expect(page.getByTestId('dag-node-detect_bbox')).toContainText('BBox 检测器')
  await expect(page.getByTestId('dag-node-label')).toBeVisible()
  await expect(page.getByTestId('dag-node-prep-0-extract_frames')).toHaveCount(0)
  await expect(page.getByTestId('dag-node-prep-1-detect_bbox')).toHaveCount(0)
})

test('audio_array_spec DAG nodes use palette catalog operators', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-edit-audio_array_spec').click()
  await expect(page.getByTestId('data-type-editor')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('dag-canvas')).toBeVisible()
  await expect(page.getByTestId('dag-node-mel_spectrogram')).toContainText('梅尔频谱')
  await expect(page.getByTestId('dag-node-stft_spectrogram')).toContainText('STFT 频谱')
  await expect(page.getByTestId('dag-node-spl_timeline')).toContainText('SPL 时间线')
  await expect(page.getByTestId('dag-node-label')).toBeVisible()
  await expect(page.getByTestId('dag-node-prep-3-transcribe')).toHaveCount(0)
  await expect(page.getByTestId('dag-node-prep-4-mel_spectrogram')).toHaveCount(0)
  await expect(page.getByTestId('dag-node-transcribe')).toHaveCount(0)
})

test('audio_defect editor DAG matches copied test recipe except id/title', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-edit-audio_defect').click()
  await expect(page.getByTestId('data-type-editor')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('dtype-id')).toHaveValue('audio_defect')
  await expect(page.getByTestId('dtype-title')).toHaveValue('问题音频判定')
  await expect(page.getByTestId('dag-canvas')).toBeVisible()
  await expect(page.getByTestId('dag-node-src-1')).toContainText('录音')
  await expect(page.getByTestId('dag-node-op-source-1788845633260')).toContainText('标签')
  await expect(page.getByTestId('dag-node-op-json_extract-1788845651418')).toContainText('JSON 值提取')
  await expect(page.getByTestId('dag-node-op-mel_spectrogram-1788845699364')).toContainText('梅尔频谱')
  await expect(page.getByTestId('dag-node-op-third_octave-1788845718012')).toContainText('1/3 倍频程')
  await expect(page.getByTestId('dag-node-op-spl_timeline-1788845725414')).toContainText('SPL 时间线')
  await expect(page.getByTestId('dag-node-op-if-1788845784271')).toContainText('条件')
  await expect(page.getByTestId('dag-node-op-label_tree_input-1788845853076')).toContainText('标签树输入')
  await expect(page.getByTestId('dag-node-op-label_tree_input-1788845889559')).toContainText('标签树输入')
  await expect(page.getByTestId('palette-search')).toBeVisible()
  await expect(page.getByTestId('dag-auto-layout')).toBeVisible()
  await expect(page.locator('.dag-edge__label--then')).toBeVisible()
  await expect(page.locator('.dag-edge__label--else')).toBeVisible()
  await page.getByTestId('dag-auto-layout').click()
  await expect(page.getByTestId('dag-node-src-1')).toBeVisible()
  await page.getByTestId('palette-search').fill('条件')
  await expect(page.getByTestId('palette-op-if')).toBeVisible()
  await expect(page.getByTestId('dag-node-audio_primary')).toHaveCount(0)
  await expect(page.getByTestId('dag-node-stage-label')).toHaveCount(0)
  await expect(page.getByTestId('overview-card-spectrum_timeline')).toBeVisible()
  await expect(page.getByTestId('overview-card-labels_tree')).toBeVisible()
  await page.getByRole('button', { name: '返回列表' }).click()
  await expect(page.getByTestId('data-type-home')).toBeVisible({ timeout: 15_000 })
  await page.getByTestId('dtype-edit-test').click()
  await expect(page.getByTestId('data-type-editor')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('dtype-id')).toHaveValue('test')
  await expect(page.getByTestId('dag-node-src-1')).toContainText('录音')
  await expect(page.getByTestId('dag-node-op-if-1788845784271')).toContainText('条件')
  await expect(page.getByTestId('dag-node-op-label_tree_input-1788845853076')).toBeVisible()
  await expect(page.getByTestId('overview-card-spectrum_timeline')).toBeVisible()
})

test('inspector 输入 does not auto-fill DAG upstream products', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-edit-oms_cabin').click()
  await expect(page.getByTestId('data-type-editor')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('dtype-id')).toHaveValue('oms_cabin')
  await expect(page.getByTestId('overview-card-video_timeline')).toHaveCount(4)
  await expect(page.getByTestId('dag-canvas')).toBeVisible()
  await expect(page.getByTestId('dag-inspector')).toHaveCount(0)
  await page.getByTestId('dag-node-label').click()
  const inspector = page.getByTestId('dag-inspector')
  await expect(inspector).toBeVisible({ timeout: 15_000 })
  const labelBind = inspector.getByTestId('pipe-bind-label-in')
  await expect(labelBind).toBeVisible({ timeout: 15_000 })
  await expect(labelBind.locator('.ant-tag, .ant-select-selection-item').filter({ hasText: /^up:/ })).toHaveCount(0)
  await openAntSelect(labelBind)
  await expect(page.getByText('ROSBAG 解析器 · 连续帧')).toBeVisible()
  await expect(page.getByText('视频抽帧 · 连续帧')).toBeVisible()
  await page.getByText('ROSBAG 解析器 · 连续帧').click()
  await expect(labelBind.getByText(/ROSBAG 解析器 · 连续帧/)).toBeVisible()
  await expect(labelBind.locator('.ant-tag, .ant-select-selection-item').filter({ hasText: /^up:/ })).toHaveCount(0)
  await page.keyboard.press('Escape')
  await page.getByTestId('dag-inspector-close').click()

  await page.getByTestId('dag-node-embed').click()
  await expect(page.getByTestId('dag-inspector')).toBeVisible()
  const embedBind = page.getByTestId('dag-inspector').getByTestId('pipe-bind-embed-in')
  await expect(embedBind).toBeVisible()
  await expect(embedBind.locator('.ant-tag, .ant-select-selection-item').filter({ hasText: /^up:/ })).toHaveCount(0)
  await openAntSelect(embedBind)
  await embedBind.getByRole('combobox').fill('ASR', { force: true })
  await expect(page.getByRole('option', { name: '音频 ASR · 转写文本', includeHidden: true })).toHaveCount(1)
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
  await expect(page.getByTestId('overview-card-video_timeline')).toHaveCount(4)
  await expect(page.getByTestId('overview-add-labels_tree')).toBeVisible()
  await expect(page.getByTestId('overview-card-labels_tree')).toBeVisible()
  await expect(page.getByTestId('overview-card-clip_table')).toHaveCount(0)
  await expect(page.getByTestId('overview-card-nvh_spl_column')).toHaveCount(0)
  await expect(page.getByText('展示页排版')).toBeVisible()
  const pipelineHead = page.locator('.ant-card-head').filter({ hasText: /^管线编排$/ })
  const overviewHead = page.locator('.ant-card-head').filter({ hasText: /^展示页排版$/ })
  await expect(pipelineHead).toBeVisible()
  const pipelineBox = await pipelineHead.boundingBox()
  const overviewBox = await overviewHead.boundingBox()
  expect(pipelineBox).toBeTruthy()
  expect(overviewBox).toBeTruthy()
  expect(pipelineBox!.y).toBeLessThan(overviewBox!.y)
  const metaCard = page.locator('.ant-card').filter({ has: page.locator('.ant-card-head', { hasText: /^基本信息$/ }) })
  const overviewCard = page.locator('.ant-card').filter({ has: page.locator('.ant-card-head', { hasText: /^展示页排版$/ }) })
  await expect(metaCard.getByText('绑定标签树 taxonomy_id')).toBeVisible()
  await expect(metaCard.getByTestId('dtype-overview-preset')).toHaveCount(0)
  await expect(overviewCard.getByTestId('dtype-overview-preset')).toHaveCount(0)
  await expect(page.getByTestId('overview-add-spectrum_timeline')).toBeVisible()
  await expect(page.getByText('四通道频谱时间轴')).toHaveCount(0)
  await expect(page.getByTestId('overview-card-spectrum_timeline')).toHaveCount(0)
  await expect(page.getByTestId('overview-card-video_timeline')).toHaveCount(4)
  await expect(page.getByTestId('dag-canvas')).toBeVisible()
  await expect(page.getByTestId('dag-inspector')).toHaveCount(0)
  await expect(page.getByTestId('palette-group-toggle-control')).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByTestId('palette-op-if')).toHaveCount(0)
  const canvasBox = await page.getByTestId('dag-canvas').boundingBox()
  expect(canvasBox?.height).toBeGreaterThan(300)
  expect(canvasBox?.height).toBeLessThan(720)
  await expect(page.getByTestId('dag-node-label')).toBeVisible()
  await page.getByTestId('dag-node-label').click()
  await expect(page.getByTestId('dag-inspector')).toBeVisible()
  await expect(page.getByTestId('dag-inspector').getByText('AI打标器', { exact: true })).toBeVisible()
  await expect(page.getByTestId('pipe-label-model')).toBeVisible()
  await expect(page.getByTestId('pipe-label-call-omni_label_prompt')).toBeVisible()
  await expect(page.getByTestId('pipe-label-omni-system_role')).toBeVisible()
  await expect(page.getByTestId('pipe-label-call-ast_top_k')).toHaveCount(0)
  await page.getByTestId('pipe-label-model').scrollIntoViewIfNeeded()
  await page.getByTestId('pipe-label-model').getByRole('combobox').click()
  await expect(page.getByRole('option', { name: 'nvh_sem_ast（AudioSet AST）' })).toHaveCount(1)
  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('pipe-label-call-ast_top_k')).toBeVisible()
  await expect(page.getByTestId('pipe-label-call-reference_constraints')).toBeVisible()
  await expect(page.getByTestId('pipe-label-omni-system_role')).toHaveCount(0)
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

test('legacy prep-N graph loads as catalog palette operators', async ({ page }) => {
  await loginAsAdmin(page)
  const id = `e2e_legacy_prep_${Date.now()}`
  const body = {
    id,
    title: 'E2E 旧 hydrate 图',
    purpose: 'prep-N 键应显示目录组件中文名',
    owner: 'qa',
    taxonomy_id: 'oms',
    overview_view: 'custom',
    status: 'draft',
    require_any_kinds: [['.mp4']],
    slots: [
      {
        id: 'ui_media',
        title: 'IVI 画面',
        kinds: ['.mp4'],
        cardinality_min: 1,
        cardinality_max: 1,
        role: 'primary',
        required: true,
      },
    ],
    preprocess: [
      { op_id: 'text_to_json', produces: ['structured_json'] },
      { op_id: 'detect_bbox', required: true, produces: ['bboxes_jsonl'] },
    ],
    products: [],
    stages: { label: { enabled: true, model: 'default' }, embed: { enabled: true } },
    bbox: { enabled: true, detector: 'opencv', yolo_classes: '' },
    overview: {
      preset: 'custom',
      list: [{ key: 't', widget_id: 'clip_table', bindings: {} }],
      detail: [{ key: 'legacy-lt', widget_id: 'labels_tree', bindings: {} }],
    },
    graph: {
      nodes: [
        {
          key: 'ui_media',
          type: 'source',
          op_id: 'source',
          title: 'IVI 画面',
          params: { kinds: ['.mp4'], required: true, cardinality_min: 1, cardinality_max: 1 },
          position: { x: 80, y: 0 },
        },
        {
          key: 'prep-5-text_to_json',
          type: 'op',
          op_id: 'text_to_json',
          title: 'prep-5-text_to_json',
          params: {},
          position: { x: 80, y: 96 },
        },
        {
          key: 'prep-6-detect_bbox',
          type: 'op',
          op_id: 'detect_bbox',
          title: 'prep-6-detect_bbox',
          params: {},
          position: { x: 80, y: 192 },
        },
        {
          key: 'stage-embed',
          type: 'op',
          op_id: 'embed',
          title: 'stage-embed',
          params: {},
          position: { x: 80, y: 288 },
        },
        {
          key: 'stage-label',
          type: 'label',
          op_id: 'label',
          title: '打标器',
          params: { model: 'default' },
          position: { x: 80, y: 384 },
        },
      ],
      edges: [
        { id: 'a', source: 'ui_media', source_port: 'out', target: 'prep-5-text_to_json', target_port: 'in' },
        { id: 'b', source: 'prep-5-text_to_json', source_port: 'out', target: 'prep-6-detect_bbox', target_port: 'in' },
        { id: 'c', source: 'prep-6-detect_bbox', source_port: 'out', target: 'stage-embed', target_port: 'in' },
        { id: 'd', source: 'stage-embed', source_port: 'out', target: 'stage-label', target_port: 'in' },
      ],
    },
  }
  const res = await page.request.put(`/api/platform/data-types/${id}`, { data: body })
  expect(res.ok(), await res.text()).toBeTruthy()
  await page.goto(`/data-types/${id}/edit`)
  await expect(page.getByTestId('data-type-editor')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('dtype-title')).toBeEnabled({ timeout: 15_000 })
  await expect(page.getByTestId('dag-canvas')).toBeVisible()
  await expect(page.getByTestId('dag-node-text_to_json')).toBeVisible()
  await expect(page.getByTestId('dag-node-text_to_json')).toContainText('文本结构化')
  await expect(page.getByTestId('dag-node-detect_bbox')).toContainText('BBox 检测器')
  await expect(page.getByTestId('dag-node-embed')).toContainText('向量化器')
  await expect(page.getByTestId('dag-node-prep-5-text_to_json')).toHaveCount(0)
  await expect(page.getByTestId('dag-node-prep-6-detect_bbox')).toHaveCount(0)
  await expect(page.getByTestId('dag-node-stage-embed')).toHaveCount(0)
  await expect(page.getByTestId('overview-card-labels_tree')).toBeVisible()
  await expect(page.getByTestId('overview-remove-labels_tree')).toBeVisible()
  await expect(page.getByTestId('overview-add-labels_tree')).toBeVisible()
})

test('DAG I/O warn bang, expected outputs, and node probe', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByTestId('dtype-new-btn').click()
  await fillNewMetaAndEnterCanvas(page, {
    id: `e2e_io_${Date.now()}`,
    title: 'E2E DAG I/O contract',
    purpose: 'Playwright min-input warn and probe',
  })
  await expect(page.getByTestId('dag-io-warn-stage-label')).toHaveCount(0)
  await page.getByTestId('dag-remove-edge-src-1->stage-label').click()
  await expect(page.getByTestId('dag-io-warn-stage-label')).toBeVisible()

  await page.getByTestId('dag-node-src-1').click()
  await expect(page.getByTestId('dag-source-kinds')).toBeVisible()
  await page.getByTestId('dag-source-kinds').locator('.ant-select').click()
  const kindsDrop = page.locator('.ant-select-dropdown').filter({ visible: true })
  await kindsDrop.getByText('.bag', { exact: true }).click()
  await page.keyboard.press('Escape')
  await page.getByTestId('dag-inspector-close').click()
  await expect(page.getByTestId('dag-inspector')).toHaveCount(0)

  await openPaletteGroup(page, 'parse')
  await page.getByTestId('palette-op-parse_bag').click()
  await expect(page.getByTestId(/dag-node-.*parse_bag/)).toBeVisible()
  await expect(page.getByTestId(/dag-io-warn-.*parse_bag/)).toBeVisible()

  await page.getByTestId(/dag-node-.*parse_bag/).click()
  await expect(page.getByTestId('dag-expected-outputs')).toBeVisible()
  await expect(page.getByTestId('dag-node-probe')).toBeVisible()
  await expect(page.getByTestId('dag-probe-until')).toBeVisible()
  await expect(page.getByTestId('dag-probe-single')).toBeVisible()
  const parseBind = page.getByTestId('pipe-bind-parse_bag-in')
  await parseBind.locator('.ant-select').click()
  const parseDrop = page.locator('.ant-select-dropdown').filter({ visible: true })
  await expect(parseDrop.getByText(/数据源/)).toBeVisible()
  await parseDrop.getByText(/数据源/).click()
  await expect(page.getByTestId(/dag-io-warn-.*parse_bag/)).toHaveCount(0)
  await page.getByTestId('dag-inspector-close').click()
  await expect(page.getByTestId('dag-inspector')).toHaveCount(0)

  await page.getByTestId('dag-node-label').click()
  await expect(page.getByTestId('dag-expected-outputs')).toBeVisible()
  await expect(page.getByTestId('dag-node-probe')).toBeVisible()
  const labelBind = page.getByTestId('pipe-bind-label-in')
  await labelBind.locator('.ant-select').click()
  const labelDrop = page.locator('.ant-select-dropdown').filter({ visible: true })
  await expect(labelDrop.getByText('ROSBAG 解析器 · 连续帧')).toBeVisible()
  await labelDrop.getByText('ROSBAG 解析器 · 连续帧').click()
  await expect(page.getByTestId('dag-io-warn-stage-label')).toHaveCount(0)

  await page.getByTestId('dag-probe-until').click()
  await expect(page.getByTestId('dag-probe-result')).toContainText('需要数据源才能试跑')
})
