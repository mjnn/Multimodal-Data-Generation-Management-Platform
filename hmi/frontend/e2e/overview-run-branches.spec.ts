import { expect, test } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

test('overview row opens explorer with run_id; run selector has no 当前生效', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/w/oms_cabin')
  await expect(page.getByTestId('data-type-workspace-banner')).toBeVisible({ timeout: 20_000 })

  const clips = (await page.evaluate(async () => {
    const res = await fetch('/api/clips?data_type_id=oms_cabin&light=1&refresh=1', {
      credentials: 'include',
    })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  })) as Array<{ clip_id: string; run_id?: string; active_run_id?: string }>

  test.skip(clips.length === 0, 'no local OMS clips to open')

  const first = clips[0]
  const runId = (first.run_id || first.active_run_id || '').trim()
  expect(runId).toBeTruthy()

  const row = page.getByTestId(`overview-clip-row-${runId}`)
  await expect(row).toBeVisible({ timeout: 20_000 })
  await row.click()
  await expect(page).toHaveURL(/\/clips\//)
  expect(new URL(page.url()).searchParams.get('run_id')).toBe(runId)

  const selector = page.getByTestId('run-selector')
  if (await selector.count()) {
    await expect(selector).not.toContainText('当前生效')
    await expect(selector).not.toContainText('生效中')
  }
})
