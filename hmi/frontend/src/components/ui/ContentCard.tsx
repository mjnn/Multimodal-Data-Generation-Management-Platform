import { Typography } from 'antd'
import type { ReactNode } from 'react'

type ContentCardProps = {
  title?: ReactNode
  extra?: ReactNode
  toolbar?: ReactNode
  children: ReactNode
  className?: string
  noPadding?: boolean
}

export function ContentCard({
  title,
  extra,
  toolbar,
  children,
  className = '',
  noPadding,
}: ContentCardProps) {
  return (
    <section className={`content-card ${className}`.trim()}>
      {title || extra ? (
        <header className="content-card__header">
          {title ? (
            typeof title === 'string' ? (
              <Typography.Title level={5} className="content-card__title">
                {title}
              </Typography.Title>
            ) : (
              title
            )
          ) : (
            <span />
          )}
          {extra ? <div className="content-card__extra">{extra}</div> : null}
        </header>
      ) : null}
      {toolbar ? <div className="content-card__toolbar">{toolbar}</div> : null}
      <div className={noPadding ? 'content-card__body content-card__body--flush' : 'content-card__body'}>
        {children}
      </div>
    </section>
  )
}
