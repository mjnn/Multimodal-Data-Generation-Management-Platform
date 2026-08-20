import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

test('NVH explorer shows taxonomy label tree (no raw label rail)', async ({ page }) => {
  await loginAsAdmin(page)

  const demoClips = (await page.evaluate(async () => {
    const res = await fetch('/api/clips/demo?data_type_id=audio_array_spec', { credentials: 'include' })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  })) as any[]
  const fallbackClips = (demoClips?.length ?? 0) > 0 ? demoClips : ((await page.evaluate(async () => {
    const res = await fetch('/api/clips?data_type_id=audio_array_spec&light=1', { credentials: 'include' })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  })) as any[])

  expect(fallbackClips.length).toBeGreaterThan(0)

  const clipId = fallbackClips[0].clip_id
  const runId = fallbackClips[0].active_run_id ?? fallbackClips[0].runs?.[0]?.run_id
  expect(runId).toBeTruthy()

  await page.goto(`/clips/${encodeURIComponent(clipId)}?run_id=${encodeURIComponent(runId)}`)

  await expect(page.getByTestId('audio-nvh-label-tree')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('audio-nvh-label-rail')).toHaveCount(0)
})

