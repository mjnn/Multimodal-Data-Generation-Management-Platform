import { Select, Typography } from 'antd'
import type { ClipRun } from '../api/types'
import { formatClipRunStatus } from '../utils/uiLabels'

interface Props {
  runs: ClipRun[]
  value: string
  onChange: (runId: string) => void
}

export function RunSelector({ runs, value, onChange }: Props) {
  if (runs.length <= 1) return null

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }} data-testid="run-selector">
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        管线分支
      </Typography.Text>
      <Select
        size="small"
        style={{ minWidth: 280 }}
        value={value}
        onChange={onChange}
        options={runs.map((r) => ({
          value: r.run_id,
          label: `${r.run_id.slice(0, 8)}… — ${formatClipRunStatus(r.status)}`,
        }))}
        optionRender={(opt) => (
          <span>
            {String(opt.value).slice(0, 8)}…
            <Typography.Text type="secondary" style={{ marginLeft: 4, fontSize: 11 }}>
              {formatClipRunStatus(runs.find((x) => x.run_id === opt.value)?.status ?? '')}
            </Typography.Text>
          </span>
        )}
      />
    </div>
  )
}
