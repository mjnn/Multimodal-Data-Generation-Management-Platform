import { test, expect } from '@playwright/test'
import { loginAsAdmin } from './helpers/auth'

test('pipeline data-select tab requires data type before listing lake files', async ({ page }) => {
  await loginAsAdmin(page)
  await page.addInitScript(() => {
    sessionStorage.removeItem('hmi.dataTypeId')
  })
  await page.goto('/pipeline?tab=run')
  await expect(page.getByTestId('lake-run-bind-panel')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByRole('tab', { name: '数据选择' })).toBeVisible()
  await expect(page.getByTestId('lake-run-pick-type-first')).toBeVisible()
  await expect(page.getByTestId('lake-run-slot-audio_primary')).toHaveCount(0)
})

test('pipeline data-select tab lists published DataTypes', async ({ page }) => {
  await loginAsAdmin(page)
  await page.goto('/pipeline?tab=run')
  await expect(page.getByTestId('lake-run-bind-panel')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByTestId('lake-run-data-type-select')).toBeVisible()
  await page.getByTestId('lake-run-data-type-select').click()
  const optionText = page.locator('.ant-select-dropdown .ant-select-item-option-content')
  await expect(optionText.filter({ hasText: 'oms_cabin' })).toBeVisible()
  await expect(optionText.filter({ hasText: 'ivi_ui_stub' })).toBeVisible()
})

test('queue progress renders DAG operator titles instead of fixed SDK infer', async ({ page }) => {
  await loginAsAdmin(page)
  await page.route('**/api/pipeline/executions**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            run_id: 'run-mock-dag',
            label: 'mock-dag-run',
            started_at: '2026-09-04T00:00:00Z',
            created_at: '2026-09-04T00:00:00Z',
            pipeline_status: 'running',
            clip_count: 1,
            data_type_id: 'oms_cabin',
            clips: [
              {
                clip_id: 'clip-mock-dag',
                clip_dir_name: 'demo-clip',
                ds: '20260904',
                pipeline_status: 'running',
                pipeline_created_at: '2026-09-04T00:00:00Z',
                steps: [
                  { step_id: 'dag:parse_bag', label: 'ROSBAG 解析器', status: 'running' },
                  { step_id: 'dag:extract_frames', label: '视频抽帧', status: 'pending' },
                  { step_id: 'dag:label', label: 'AI打标器', status: 'pending' },
                  { step_id: 'sdk_mc_write', label: 'SQLite 写入', status: 'pending' },
                  { step_id: 'sdk_upload', label: 'OSS 上传', status: 'pending' },
                  { step_id: 'sdk_dispatch', label: '调度发布', status: 'pending' },
                ],
              },
            ],
          },
        ],
        total: 1,
        page: 1,
        page_size: 10,
      }),
    })
  })
  await page.goto('/pipeline?run_id=run-mock-dag&clip_id=clip-mock-dag')
  const progress = page.getByTestId('upload-pipeline-progress')
  await expect(progress).toBeVisible({ timeout: 20_000 })
  await expect(progress).toContainText('管线进度 0/3')
  await expect(progress).toContainText('当前：ROSBAG 解析器')
  await expect(page.getByTestId('pipeline-step-dag:parse_bag')).toHaveText('ROSBAG 解析器')
  await expect(page.getByTestId('pipeline-step-dag:extract_frames')).toHaveText('视频抽帧')
  await expect(page.getByText('SDK 打标与向量')).toHaveCount(0)
  await expect(progress.getByText('SQLite 写入')).toHaveCount(0)
  await expect(progress.getByText('OSS 上传')).toHaveCount(0)
  await expect(progress.getByText('调度发布')).toHaveCount(0)
})

test('queue preview navigates with run_id and data_type_id', async ({ page }) => {
  await loginAsAdmin(page)
  await page.addInitScript(() => {
    sessionStorage.setItem('hmi.dataTypeId', 'oms_cabin')
  })
  await page.route('**/api/pipeline/executions**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            run_id: 'run-audio-preview',
            label: 'audio-preview-run',
            started_at: '2026-09-08T00:00:00Z',
            created_at: '2026-09-08T00:00:00Z',
            pipeline_status: 'completed',
            clip_count: 1,
            data_type_id: 'audio_defect',
            clips: [
              {
                clip_id: 'clip-audio-preview',
                clip_dir_name: 'audio-clip',
                ds: '20260908',
                pipeline_status: 'completed',
                pipeline_created_at: '2026-09-08T00:00:00Z',
                steps: [{ step_id: 'dag:label', label: 'AI打标器', status: 'completed' }],
              },
            ],
          },
        ],
        total: 1,
        page: 1,
        page_size: 10,
      }),
    })
  })
  await page.goto('/pipeline?run_id=run-audio-preview&clip_id=clip-audio-preview')
  await expect(page.getByTestId('pipeline-clip-preview')).toBeVisible({ timeout: 20_000 })
  await page.getByTestId('pipeline-clip-preview').click()
  await page.waitForURL(/\/clips\/clip-audio-preview\?/)
  expect(page.url()).toContain('run_id=run-audio-preview')
  expect(page.url()).toContain('data_type_id=audio_defect')
})
