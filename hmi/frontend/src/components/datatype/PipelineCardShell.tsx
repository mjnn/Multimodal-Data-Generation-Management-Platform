import { DownOutlined, HolderOutlined, RightOutlined } from '@ant-design/icons'
import { Button, Space, Typography } from 'antd'
import { useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'

type Props = {
  testId?: string
  variant?: 'source' | 'op'
  title: ReactNode
  subtitle?: ReactNode
  summary?: ReactNode
  extra?: ReactNode
  dragging?: boolean
  dragOver?: boolean
  onHandlePointerDown?: (e: ReactPointerEvent<HTMLButtonElement>) => void
  children: ReactNode
}

export function PipelineCardShell({
  testId,
  variant = 'op',
  title,
  subtitle,
  summary,
  extra,
  dragging,
  dragOver,
  onHandlePointerDown,
  children,
}: Props) {
  const [collapsed, setCollapsed] = useState(false)
  const cls = [
    'pipe-step',
    variant === 'source' ? 'pipe-step--source' : '',
    collapsed ? 'is-collapsed' : '',
    dragging ? 'is-dragging' : '',
    dragOver && !dragging ? 'is-drag-over' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <article className={cls} data-testid={testId}>
      <div className="pipe-step__head">
        <div className="pipe-step__head-main">
          {onHandlePointerDown ? (
          <Button
            type="text"
            size="small"
            className="pipe-step__drag"
            data-testid="pipe-card-drag"
            aria-label="拖动排序"
            icon={<HolderOutlined />}
            onPointerDown={onHandlePointerDown}
          />
          ) : null}
          <Button
            type="text"
            size="small"
            className="pipe-step__fold"
            data-testid="pipe-card-collapse"
            aria-label={collapsed ? '展开' : '折叠'}
            aria-expanded={!collapsed}
            icon={collapsed ? <RightOutlined /> : <DownOutlined />}
            onClick={() => setCollapsed((v) => !v)}
          />
          <div>
            <Typography.Title level={5} className="pipe-step__title">
              {title}
            </Typography.Title>
            {subtitle ? <p className="pipe-step__op">{subtitle}</p> : null}
          </div>
        </div>
        <Space>{extra}</Space>
      </div>
      {collapsed ? (
        summary ? <div className="pipe-step__summary">{summary}</div> : null
      ) : (
        children
      )}
    </article>
  )
}
