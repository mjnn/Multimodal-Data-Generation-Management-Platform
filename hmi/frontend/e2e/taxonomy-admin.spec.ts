import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

const ADMIN_USER = process.env.E2E_ADMIN_USER ?? 'admin'
const ADMIN_PASS = process.env.E2E_ADMIN_PASS ?? 'admin123'

test('admin opens taxonomy page and sees version list', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('用户名').fill(ADMIN_USER)
  await page.getByLabel('密码').fill(ADMIN_PASS)
  await page.getByLabel('密码').press('Enter')

  await expect(page.getByText('数据类型')).toBeVisible({ timeout: 15_000 })
  await page.getByRole('menuitem', { name: '标签树' }).click()

  await expect(page.getByTestId('taxonomy-page')).toBeVisible()
  await expect(page.getByRole('heading', { name: '标签树管理' })).toBeVisible()
  await expect(page.getByText('版本列表')).toBeVisible()
})

test('deleted taxonomy version_code can be reused', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/taxonomy')
  await expect(page.getByTestId('taxonomy-page')).toBeVisible({ timeout: 15_000 })

  const code = `e2e-reuse-${Date.now()}`

  const createNamed = async () => {
    await page.getByRole('button', { name: '新建版本' }).click()
    const dialog = page.getByRole('dialog', { name: '新建版本' })
    await expect(dialog).toBeVisible()
    const codeInput = dialog.getByLabel('版本号')
    await codeInput.click()
    await page.keyboard.press('Control+A')
    await page.keyboard.insertText(code)
    await dialog.getByRole('button', { name: /确\s*定/ }).click()
    await expect(page.getByText('版本已创建')).toBeVisible({ timeout: 15_000 })
  }

  await createNamed()
  await page.keyboard.press('Escape')

  const row = page.locator('.ant-table-row').filter({ hasText: code })
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: '删除' }).click()
  await page.getByRole('button', { name: /确\s*定/ }).click()
  await expect(page.getByText('已删除')).toBeVisible({ timeout: 15_000 })
  await expect(row).toHaveCount(0)

  await createNamed()
  await expect(page.getByText(/已存在|已被占用/)).toHaveCount(0)
  await expect(page.locator('.ant-table-row').filter({ hasText: code })).toBeVisible()
})
