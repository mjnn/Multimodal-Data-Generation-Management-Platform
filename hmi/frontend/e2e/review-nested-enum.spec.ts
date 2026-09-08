import { expect, test } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

const NESTED_SCHEMA = {
  type: 'enum_tree',
  values: [
    {
      id: 'powertrain',
      children: [{ id: 'engine' }, { id: 'motor' }],
    },
    { id: 'road' },
  ],
}

const parentOnlyTask = {
  clip_id: 'sha256:e2e_nested_enum',
  run_id: 'run-nested-enum',
  label_id: 'demo.noise_category',
  label_name: '噪音类别',
  dtype: 'enum_tree',
  value_schema: NESTED_SCHEMA,
  ai_value: 'powertrain',
  ai_confidence: 0.9,
  human_doubtful: false,
  low_confidence: false,
  priority_bucket: 1,
  clip_card: {
    clip_id: 'sha256:e2e_nested_enum',
    run_id: 'run-nested-enum',
    clip_dir_name: 'e2e_nested_enum',
    label_preview: 'powertrain',
  },
  cursor: 'e2e-nested-enum',
  position: { index: 1, total: 1 },
}

test('nested enum parent-only cannot confirm; parent+child can correct', async ({ page }) => {
  await page.route('**/api/review/v2/tasks**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [parentOnlyTask], total: 1, limit: 200, offset: 0 }),
    })
  })

  await loginAsAdmin(page)
  await page.goto('/review/workbench?mode=confidence')
  await expect(page.getByTestId('review-workbench-page')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('噪音类别')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('review-enum-incomplete-hint')).toBeVisible()
  await expect(page.getByTestId('review-action-confirm')).toBeDisabled()

  await page.getByTestId('review-action-correct').click()
  const level0 = page.getByTestId('review-enum-cascade-level-0')
  await expect(level0).toBeVisible()
  await expect(page.getByTestId('review-enum-cascade-level-1')).toBeVisible()
  await expect(page.getByRole('button', { name: '暂存修正' })).toBeDisabled()

  await page.getByTestId('review-enum-cascade-level-1').click()
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({
    hasText: 'engine',
  }).first().click()

  await expect(page.getByRole('button', { name: '暂存修正' })).toBeEnabled()
  await page.getByRole('button', { name: '暂存修正' }).click()
  await expect(page.getByTestId('review-staged-diff')).toBeVisible({ timeout: 10_000 })
  await expect(page.getByTestId('review-staged-diff').getByText('已暂存')).toBeVisible()
})
