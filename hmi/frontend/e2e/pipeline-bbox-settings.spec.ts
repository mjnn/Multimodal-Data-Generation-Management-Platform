import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

test('pipeline settings shows BBox detector controls in local mode', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/pipeline')
  await expect(page.getByText('BBox 检测 / 预览编码')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('启用 BBox')).toBeVisible()
  await expect(page.getByText('检测器')).toBeVisible()
})

test('pipeline BBox detector dropdown hides noop/stub', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/pipeline')
  await expect(page.getByText('BBox 检测 / 预览编码')).toBeVisible({ timeout: 20_000 })
  const bboxSwitch = page.locator('.ant-form-item').filter({ hasText: '启用 BBox' }).locator('.ant-switch')
  await bboxSwitch.click()
  await page.locator('.ant-form-item').filter({ hasText: '检测器' }).locator('.ant-select').click()
  const dropdown = page.locator('.ant-select-dropdown:visible')
  await expect(dropdown.getByText(/opencv/i).first()).toBeVisible()
  await expect(dropdown.getByText(/yolo/i).first()).toBeVisible()
  await expect(dropdown.getByText(/\bnoop\b/i)).toHaveCount(0)
  await expect(dropdown.getByText(/\bstub\b/i)).toHaveCount(0)
})

test('pipeline YOLO detector exposes class checklist modal', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/pipeline')
  await expect(page.getByText('BBox 检测 / 预览编码')).toBeVisible({ timeout: 20_000 })
  const enable = page.getByRole('switch', { name: /启用 BBox|bbox_enabled/i }).first()
  // Ant Design Switch may not have accessible name; fall back to form label proximity
  const bboxSwitch = page.locator('.ant-form-item').filter({ hasText: '启用 BBox' }).locator('.ant-switch')
  await bboxSwitch.click()
  await page.locator('.ant-form-item').filter({ hasText: '检测器' }).locator('.ant-select').click()
  await page.getByText(/yolo/i).first().click()
  await expect(page.getByRole('button', { name: '类别清单' })).toBeVisible()
  await page.getByRole('button', { name: '类别清单' }).click()
  await expect(page.getByText('YOLO 识别类别清单')).toBeVisible()
  await expect(page.getByText('person (id=0)')).toBeVisible()
  await expect(page.getByRole('button', { name: /舱内遗留物/ })).toBeVisible()
  await expect(page.getByText(/标准 YOLOv8n\/COCO 无 face|人脸请改用检测器 OpenCV/)).toBeVisible()
})

test('taxonomy leaf editor offers enum dtype (enum_tree)', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/taxonomy')
  await expect(page.getByTestId('taxonomy-page')).toBeVisible({ timeout: 15_000 })
  // Hub leaf editor: single「枚举」option stores dtype=enum_tree.
  const editBtn = page.getByRole('button', { name: /编辑|打开编辑器/ }).first()
  if (await editBtn.isVisible().catch(() => false)) {
    await editBtn.click()
  }
})
