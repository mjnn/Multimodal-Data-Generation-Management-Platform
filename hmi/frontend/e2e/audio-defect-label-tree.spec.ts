import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

async function firstAudioBoundClip(page: import('@playwright/test').Page) {
  for (const dataTypeId of ['audio_defect', 'test']) {
    const clips = (await page.evaluate(async (dt) => {
      const res = await fetch(`/api/clips?data_type_id=${encodeURIComponent(dt)}&light=1&refresh=1`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(await res.text())
      return res.json()
    }, dataTypeId)) as any[]
    if (!clips.length) continue
    const preferred = clips[0]
    const clipId = preferred.clip_id as string
    const runId = (preferred.run_id ?? preferred.active_run_id ?? preferred.runs?.[0]?.run_id) as string
    if (!clipId || !runId) continue
    return { clipId, runId, dataTypeId }
  }
  return null
}

test('audio_defect explorer shows bound tree, not NVH groups', async ({ page }) => {
  await loginAsAdmin(page)
  const found = await firstAudioBoundClip(page)
  test.skip(!found, 'no audio_defect/test clips to inspect')
  const { clipId, runId, dataTypeId } = found!

  await page.goto(`/w/${encodeURIComponent(dataTypeId)}`)
  await expect(page.getByTestId('data-type-workspace-banner')).toBeVisible({ timeout: 20_000 })
  await page.goto(
    `/clips/${encodeURIComponent(clipId)}?run_id=${encodeURIComponent(runId)}&data_type_id=${encodeURIComponent(dataTypeId)}`,
  )

  await expect(page.getByTestId('clip-bound-label-tree')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByTestId('audio-nvh-label-tree')).toHaveCount(0)
  await expect(page.getByText('纯音频 NVH')).toHaveCount(0)
  const tree = page.getByTestId('clip-bound-label-tree')
  const header = tree.locator('.ant-collapse-header').first()
  if ((await header.count()) && (await header.getAttribute('aria-expanded')) !== 'true') {
    await header.click()
  }
  await expect(tree.getByText('是否有问题音频')).toBeVisible({ timeout: 15_000 })
  await expect(tree.getByText('时间维度')).toHaveCount(0)
})

test('clip explorer ignores remembered oms_cabin when URL binds audio recipe', async ({ page }) => {
  await loginAsAdmin(page)
  const found = await firstAudioBoundClip(page)
  test.skip(!found, 'no audio_defect/test clips to inspect')
  const { clipId, runId, dataTypeId } = found!

  await page.addInitScript(() => {
    sessionStorage.setItem('hmi.dataTypeId', 'oms_cabin')
  })
  await page.goto(
    `/clips/${encodeURIComponent(clipId)}?run_id=${encodeURIComponent(runId)}&data_type_id=${encodeURIComponent(dataTypeId)}`,
  )

  await expect(page.getByTestId('clip-bound-label-tree')).toBeVisible({ timeout: 30_000 })
  const tree = page.getByTestId('clip-bound-label-tree')
  const header = tree.locator('.ant-collapse-header').first()
  if ((await header.count()) && (await header.getAttribute('aria-expanded')) !== 'true') {
    await header.click()
  }
  await expect(tree.getByText('是否有问题音频')).toBeVisible({ timeout: 15_000 })
  await expect(tree.getByText('时间维度')).toHaveCount(0)
  await expect(tree.getByText('光照条件')).toHaveCount(0)
})

test('audio_defect spectrum playhead keeps advancing while playing', async ({ page }) => {
  await loginAsAdmin(page)
  const found = await firstAudioBoundClip(page)
  test.skip(!found, 'no audio_defect/test clips to inspect')
  const { clipId, runId, dataTypeId } = found!

  await page.goto(
    `/clips/${encodeURIComponent(clipId)}?run_id=${encodeURIComponent(runId)}&data_type_id=${encodeURIComponent(dataTypeId)}`,
  )
  await expect(page.getByTestId('audio-nvh-play')).toBeVisible({ timeout: 30_000 })
  await page.getByTestId('audio-nvh-play').click()
  await expect(page.getByTestId('audio-nvh-play')).toHaveText('暂停')
  await expect
    .poll(
      async () => {
        const text = await page.getByTestId('audio-nvh-clock').innerText()
        const m = /^([\d.]+)s/.exec(text)
        return m ? Number(m[1]) : 0
      },
      { timeout: 5_000 },
    )
    .toBeGreaterThan(0.5)
})
