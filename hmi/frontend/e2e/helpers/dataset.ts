import { expect, type Page } from '@playwright/test'

/** Find a ready root dataset id, or create a small one and wait until ready. */
export async function ensureReadyBaseDatasetId(page: Page): Promise<string | null> {
  const existing = await page.evaluate(async () => {
    const res = await fetch('/api/datasets?status=ready&limit=50')
    if (!res.ok) return null
    const data = (await res.json()) as {
      items?: Array<{ id: string; status: string; parent_snapshot_id?: string | null }>
    }
    const base = data.items?.find((d) => d.status === 'ready' && !d.parent_snapshot_id)
    return base?.id ?? null
  })
  if (existing) return existing

  const createdId = await page.evaluate(async () => {
    const previewRes = await fetch('/api/datasets/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'e2e-preview', filter_json: { review_status: 'reviewed' } }),
    })
    if (!previewRes.ok) return null
    const preview = (await previewRes.json()) as { pool_count?: number }
    const pool = preview.pool_count ?? 0
    if (pool < 1) return null

    const sampleSize = Math.min(3, pool)
    const createRes = await fetch('/api/datasets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: `e2e_base_${Date.now()}`,
        filter_json: { review_status: 'reviewed', sample_size: sampleSize },
      }),
    })
    if (!createRes.ok) return null
    const created = (await createRes.json()) as { id: string }
    return created.id
  })
  if (!createdId) return null

  const deadline = Date.now() + 120_000
  while (Date.now() < deadline) {
    const status = await page.evaluate(async (id) => {
      const res = await fetch(`/api/datasets/${encodeURIComponent(id)}`)
      if (!res.ok) return 'unknown'
      const snap = (await res.json()) as { status: string }
      return snap.status
    }, createdId)
    if (status === 'ready') return createdId
    if (status === 'failed') return null
    await page.waitForTimeout(2000)
  }
  return null
}

export async function gotoReadyBaseDetail(page: Page) {
  const id = await ensureReadyBaseDatasetId(page)
  expect(id, 'need at least one ready base dataset (reviewed clips in pool)').toBeTruthy()
  await page.goto(`/datasets/${id}`)
  await expect(page.getByTestId('dataset-detail-page')).toBeVisible({ timeout: 15_000 })
  return id as string
}
