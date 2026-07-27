import type { ReactNode } from 'react'

type PageStackProps = {
  children: ReactNode
  className?: string
  'data-testid'?: string
}

export function PageStack({ children, className = '', 'data-testid': testId }: PageStackProps) {
  return (
    <div className={`page-stack ${className}`.trim()} data-testid={testId}>
      {children}
    </div>
  )
}
