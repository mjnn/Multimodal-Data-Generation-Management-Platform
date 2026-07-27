import { Steps, Typography } from 'antd'
import type { UploadPipelineStep } from '../api/types'
import { PipelineStatus } from './PipelineStatus'

function stepStatus(s: UploadPipelineStep['status']): 'wait' | 'process' | 'finish' | 'error' {
  if (s === 'success') return 'finish'
  if (s === 'running') return 'process'
  if (s === 'failed') return 'error'
  return 'wait'
}

interface Props {
  steps: UploadPipelineStep[]
  clipId?: string
  runId?: string
}

export function UploadPipelineProgress({ steps, clipId, runId }: Props) {
  const done = steps.filter((s) => s.status === 'success').length
  const current = steps.find((s) => s.status === 'running')

  return (
    <div>
      <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12 }}>
        管线进度 {done}/{steps.length}
        {current && <> · 当前：{current.label}</>}
      </Typography.Text>
      {(clipId || runId) && (
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
          {clipId && <>clip_id: <Typography.Text code>{clipId}</Typography.Text></>}
          {runId && <> · run_id: <Typography.Text code>{runId}</Typography.Text></>}
        </Typography.Text>
      )}
      <Steps
        size="small"
        current={steps.findIndex((s) => s.status === 'running')}
        items={steps.map((s) => ({
          title: s.label,
          status: stepStatus(s.status),
          description: <PipelineStatus status={s.status} size="small" />,
        }))}
      />
    </div>
  )
}
