import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

test('admin opens datasets list page', async ({ page }) => {
  await loginAsAdmin(page)
  await page.getByRole('menuitem', { name: '数据集' }).click()

  await expect(page.getByTestId('dataset-list-page')).toBeVisible()
  await expect(page.getByRole('heading', { name: '数据集' })).toBeVisible()
})
