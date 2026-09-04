import { test, expect, type Page } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

async function selectConfidenceDataType(page: Page, typeId: string) {
  await page.getByTestId('review-confidence-data-type-select').click()
  const option = page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({
    hasText: typeId,
  })
  await expect(option.first()).toBeVisible()
  await option.first().click()
}

test('low-confidence claim requires data type and switches bound taxonomy hint', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/review/confidence')
  await expect(page.getByTestId('review-confidence-tasks-page')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('review-confidence-data-type-select')).toBeVisible()
  await expect(page.getByTestId('review-confidence-pick-type-first')).toBeVisible()
  await expect(page.getByTestId('review-confidence-claim-open')).toBeDisabled()

  await selectConfidenceDataType(page, 'oms_cabin')
  await expect(page.getByText('绑定标签树：oms')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('review-confidence-pick-type-first')).toHaveCount(0)

  await selectConfidenceDataType(page, 'audio_array_spec')
  await expect(page.getByText('绑定标签树：audio_nvh')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('audio_nvh-v2')).toBeVisible()
})
