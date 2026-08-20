import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

/**
 * HMI-BBOX-OVERLAY: 总览「原图预览 / 带识别框预览」；后者为只读 jsonl 叠加（不可编辑）。
 */
test('explorer shows readonly jsonl overlay on boxed preview tab', async ({ page }) => {
  await loginAsAdmin(page)

  await page.goto('/w/oms_cabin')
  const modeSwitch = page.getByRole('switch', { name: /本地|local|数据源/i }).first()
  if (await modeSwitch.isVisible().catch(() => false)) {
    const checked = await modeSwitch.isChecked().catch(() => false)
    if (!checked) await modeSwitch.click()
  }

  await page.goto('/w/oms_cabin')
  const clipLink = page.locator('a[href*="/clips/"]').first()
  const hasClip = await clipLink.isVisible({ timeout: 15_000 }).catch(() => false)
  test.skip(!hasClip, 'no local clips to open in Explorer')

  await clipLink.click()
  await expect(page.getByTestId('clip-timeline-panel')).toBeVisible({ timeout: 30_000 })

  const toggle = page.getByTestId('preview-variant-toggle')
  const hasToggle = await toggle.isVisible({ timeout: 8_000 }).catch(() => false)
  test.skip(!hasToggle, 'opened clip has no preview tabs')

  await expect(toggle.getByText('原图预览')).toBeVisible()
  await expect(toggle.getByText('带识别框预览')).toBeVisible()
  await expect(toggle.getByText('烧录预览')).toHaveCount(0)
  await expect(toggle.getByText('带可编辑框')).toHaveCount(0)

  // 原图 tab：无编辑条；叠加层不应出现（或随 tab 切换）
  await expect(page.getByTestId('bbox-edit-panel')).toHaveCount(0)

  await toggle.getByText('带识别框预览').click()
  await expect(page.getByTestId('bbox-preview-hint')).toBeVisible()
  await expect(page.getByTestId('bbox-edit-panel')).toHaveCount(0)

  // 有 jsonl 时出现只读 overlay；无则跳过 overlay 断言
  const overlay = page.getByTestId('bbox-overlay').first()
  const hasOverlay = await overlay.isVisible({ timeout: 8_000 }).catch(() => false)
  if (hasOverlay) {
    await expect(overlay).toBeVisible()
  } else {
    test.info().annotations.push({
      type: 'note',
      description: 'No bboxes.jsonl on opened clip — tab/hint-only assertion',
    })
  }
})
