import { Alert, Steps, Typography } from 'antd'
import type { UploadPipelineStep } from '../api/types'
import { PipelineStatus } from './PipelineStatus'

function stepStatus(s: UploadPipelineStep['status']): 'wait' | 'process' | 'finish' | 'error' {
  if (s === 'success') return 'finish'
  if (s === 'running') return 'process'
  if (s === 'failed') return 'error'
  return 'wait'
}

export function firstFailedStepError(steps: UploadPipelineStep[] | undefined): string | null {
  if (!steps?.length) return null
  const failed = steps.find((s) => s.status === 'failed')
  const msg = failed?.error_message?.trim()
  return msg || null
}

interface Props {
  steps: UploadPipelineStep[]
  clipId?: string
  runId?: string
  /** 表格展开区：纵向步骤、省略 clip/run 重复与逐步长错误 */
  compact?: boolean
}

export function UploadPipelineProgress({ steps, clipId, runId, compact = false }: Props) {
  const done = steps.filter((s) => s.status === 'success').length
  const current = steps.find((s) => s.status === 'running')
  const failedStep = steps.find((s) => s.status === 'failed')
  const failedMsg = failedStep?.error_message?.trim()

  return (
    <div>
      {failedStep && failedMsg ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message={`${failedStep.label}失败`}
          description={
            <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 12 }}>
              {failedMsg}
            </Typography.Paragraph>
          }
        />
      ) : failedStep && !failedMsg ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message={`${failedStep.label}失败`}
          description="暂无详细错误信息，请刷新列表或查看后端日志。"
        />
      ) : null}
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        管线进度 {done}/{steps.length}
        {current && <> · 当前：{current.label}</>}
      </Typography.Text>
      {!compact && (clipId || runId) && (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
          {clipId && <>Clip ID：<Typography.Text code>{clipId}</Typography.Text></>}
          {runId && <> · 运行 ID：<Typography.Text code>{runId}</Typography.Text></>}
        </Typography.Text>
      )}
      <Steps
        size="small"
        direction={compact ? 'vertical' : 'horizontal'}
        style={compact ? { maxWidth: 420 } : undefined}
        current={steps.findIndex((s) => s.status === 'running')}
        items={steps.map((s) => ({
          title: s.label,
          status: stepStatus(s.status),
          description: compact ? (
            <PipelineStatus status={s.status} size="small" />
          ) : (
            <>
              <PipelineStatus status={s.status} size="small" />
              {s.status === 'failed' && s.error_message?.trim() ? (
                <Typography.Paragraph
                  type="danger"
                  style={{ margin: '4px 0 0', fontSize: 11, whiteSpace: 'pre-wrap' }}
                >
                  {s.error_message.trim()}
                </Typography.Paragraph>
              ) : null}
            </>
          ),
        }))}
      />
    </div>
  )
}
