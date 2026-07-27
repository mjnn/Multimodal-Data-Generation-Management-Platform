import { Space, Typography } from 'antd'
import type { ReactNode } from 'react'

type PageHeaderProps = {
  title: string
  description?: string
  icon?: ReactNode
  extra?: ReactNode
  'data-testid'?: string
}

export function PageHeader({ title, description, icon, extra, 'data-testid': testId }: PageHeaderProps) {
  return (
    <div className="page-header" data-testid={testId}>
      <div className="page-header__main">
        <Space align="start" size={12}>
          {icon ? <span className="page-header__icon">{icon}</span> : null}
          <div>
            <Typography.Title level={3} className="page-header__title">
              {title}
            </Typography.Title>
            {description ? (
              <Typography.Paragraph type="secondary" className="page-header__desc">
                {description}
              </Typography.Paragraph>
            ) : null}
          </div>
        </Space>
      </div>
      {extra ? <div className="page-header__extra">{extra}</div> : null}
    </div>
  )
}
