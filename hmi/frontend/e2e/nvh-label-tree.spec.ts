import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

async function firstAudioArrayClip(page: import('@playwright/test').Page) {
  const clips = (await page.evaluate(async () => {
    const res = await fetch('/api/clips?data_type_id=audio_array_spec&light=1&refresh=1', {
      credentials: 'include',
    })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  })) as any[]
  expect(clips.length).toBeGreaterThan(0)
  const preferred = clips.find((c) => c.clip_id === 'sha256:nvh_review_e2e') ?? clips[0]
  const clipId = preferred.clip_id as string
  const runId = (preferred.active_run_id ?? preferred.runs?.[0]?.run_id) as string
  expect(runId).toBeTruthy()
  return { clipId, runId }
}

async function expandAllTreePanels(tree: import('@playwright/test').Locator) {
  const headers = tree.locator('.ant-collapse-header')
  const n = await headers.count()
  for (let i = 0; i < n; i += 1) {
    const header = headers.nth(i)
    if ((await header.getAttribute('aria-expanded')) !== 'true') {
      await header.click()
    }
  }
}

test('NVH explorer shows taxonomy label tree (no raw label rail)', async ({ page }) => {
  await loginAsAdmin(page)
  const { clipId, runId } = await firstAudioArrayClip(page)

  await page.goto('/w/audio_array_spec')
  await expect(page.getByTestId('data-type-workspace-banner')).toBeVisible({ timeout: 20_000 })
  await page.goto(`/clips/${encodeURIComponent(clipId)}?run_id=${encodeURIComponent(runId)}`)

  await expect(page.getByTestId('overview-runtime-labels_tree')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('audio-nvh-label-rail')).toHaveCount(0)
})

test('NVH explorer L6 quick review writes back and keeps objective leaves', async ({ page }) => {
  await loginAsAdmin(page)
  const { clipId, runId } = await firstAudioArrayClip(page)

  await page.goto('/w/audio_array_spec')
  await expect(page.getByTestId('data-type-workspace-banner')).toBeVisible({ timeout: 20_000 })
  await page.goto(`/clips/${encodeURIComponent(clipId)}?run_id=${encodeURIComponent(runId)}`)
  const tree = page.getByTestId('overview-runtime-labels_tree')
  await expect(tree).toBeVisible({ timeout: 30_000 })
  await expandAllTreePanels(tree)

  await expect(tree.getByTestId('quick-review-nvh.sem.quality_grade')).toBeVisible({ timeout: 15_000 })
  await expect(tree.getByTestId('quick-review-nvh.clip.spl.leq_db_mean')).toHaveCount(0)

  const valueEl = tree.getByTestId('label-tree-value-nvh.sem.quality_grade')
  const before = ((await valueEl.textContent()) ?? '').trim()
  const next = before === 'A' ? 'B' : 'A'

  await tree.getByTestId('quick-review-nvh.sem.quality_grade').click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('combobox').click()
  await page
    .locator('.ant-select-dropdown:visible .ant-select-item-option-content')
    .filter({ hasText: new RegExp(`^${next}$`) })
    .first()
    .click()
  await dialog.getByRole('button', { name: /完成本标签校核/ }).click()
  await expect(dialog).toBeHidden({ timeout: 20_000 })

  await expandAllTreePanels(tree)
  await expect(tree.getByTestId('label-tree-value-nvh.sem.quality_grade')).toHaveText(next, {
    timeout: 15_000,
  })

  const boot = (await page.evaluate(
    async ({ clipId: cid, runId: rid }) => {
      const res = await fetch(
        `/api/clips/${encodeURIComponent(cid)}/runs/${encodeURIComponent(rid)}/audio-nvh`,
        { credentials: 'include' },
      )
      if (!res.ok) throw new Error(await res.text())
      return res.json()
    },
    { clipId, runId },
  )) as { labels?: Record<string, unknown> }

  expect(boot.labels?.['nvh.sem.quality_grade']).toBe(next)
  expect(boot.labels?.['nvh.clip.spl.leq_db_mean']).toBeDefined()
})
