import { Select, Tag, Typography } from 'antd'
import type { ClipRun } from '../api/types'

interface Props {
  runs: ClipRun[]
  value: string
  onChange: (runId: string) => void
}

export function RunSelector({ runs, value, onChange }: Props) {
  if (runs.length <= 1) return null

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        Pipeline Run
      </Typography.Text>
      <Select
        size="small"
        style={{ minWidth: 280 }}
        value={value}
        onChange={onChange}
        options={runs.map((r) => ({
          value: r.run_id,
          label: `${r.run_id.slice(0, 8)}… ${r.is_active ? '(active)' : ''} — ${r.status}`,
        }))}
        optionRender={(opt) => (
          <span>
            {String(opt.label).split(' — ')[0]}
            {runs.find((x) => x.run_id === opt.value)?.is_active && (
              <Tag color="green" style={{ marginLeft: 6 }}>active</Tag>
            )}
            <Typography.Text type="secondary" style={{ marginLeft: 4, fontSize: 11 }}>
              {runs.find((x) => x.run_id === opt.value)?.status}
            </Typography.Text>
          </span>
        )}
      />
    </div>
  )
}
