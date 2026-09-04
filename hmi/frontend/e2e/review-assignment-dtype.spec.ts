import { test, expect, type Page } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

async function selectAssignmentDataType(page: Page, typeId: string) {
  await page.getByTestId('review-assignment-data-type-select').click()
  const option = page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').filter({
    hasText: typeId,
  })
  await expect(option.first()).toBeVisible()
  await option.first().click()
}

test('assignment dispatch label tree follows selected data type', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/review/assignments')
  await expect(page.getByTestId('review-assignment-admin-page')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('review-assignment-data-type-select')).toBeVisible()
  await expect(page.getByTestId('review-assignment-pick-type-first')).toBeVisible()
  await expect(page.getByTestId('review-assignment-label-tree')).toHaveCount(0)

  await selectAssignmentDataType(page, 'oms_cabin')
  const tree = page.getByTestId('review-assignment-label-tree')
  await expect(tree).toBeVisible({ timeout: 15_000 })
  await expect(tree.getByText('日时段')).toBeVisible({ timeout: 15_000 })
  await expect(tree.getByText('ivi.control')).toHaveCount(0)
  await expect(tree.getByText('nvh.meta.format')).toHaveCount(0)

  await selectAssignmentDataType(page, 'ivi_ui_stub')
  await expect(tree.getByText('控件')).toBeVisible({ timeout: 15_000 })
  await expect(tree.getByText('ivi.control')).toBeVisible()
  await expect(tree.getByText('日时段')).toHaveCount(0)
  await expect(tree.getByText('nvh.meta.format')).toHaveCount(0)

  await selectAssignmentDataType(page, 'audio_array_spec')
  await expect(tree.getByText('文件格式')).toBeVisible({ timeout: 15_000 })
  await expect(tree.getByText('nvh.meta.format')).toBeVisible()
  await expect(tree.getByText('控件')).toHaveCount(0)
  await expect(tree.getByText('日时段')).toHaveCount(0)
})
