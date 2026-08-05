import { ArrowLeftOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useNavigate, useSearchParams } from 'react-router-dom'

export const AUDIT_LOG_PATH = '/admin/audit'
export const FROM_AUDIT_PARAM = 'from'
export const FROM_AUDIT_VALUE = 'audit'

type BackLinkProps = {
  fallback: string
  label?: string
}

/** Append `from=audit` so destination pages can show「返回审计日志」. */
export function withFromAudit(path: string): string {
  const qIndex = path.indexOf('?')
  const base = qIndex >= 0 ? path.slice(0, qIndex) : path
  const qs = qIndex >= 0 ? path.slice(qIndex + 1) : ''
  const params = new URLSearchParams(qs)
  params.set(FROM_AUDIT_PARAM, FROM_AUDIT_VALUE)
  const q = params.toString()
  return q ? `${base}?${q}` : base
}

export function useFromAudit(): boolean {
  const [searchParams] = useSearchParams()
  return searchParams.get(FROM_AUDIT_PARAM) === FROM_AUDIT_VALUE
}

/** Predictable back navigation with history fallback (ux: back-behavior, drill-down-consistency). */
export function BackLink({ fallback, label = '返回' }: BackLinkProps) {
  const navigate = useNavigate()
  const fromAudit = useFromAudit()

  if (fromAudit) {
    return (
      <Button
        type="text"
        icon={<ArrowLeftOutlined />}
        onClick={() => navigate(AUDIT_LOG_PATH)}
        className="back-link"
        data-testid="back-to-audit-log"
      >
        返回审计日志
      </Button>
    )
  }

  const goBack = () => {
    if (window.history.length > 1) {
      navigate(-1)
      return
    }
    navigate(fallback)
  }

  return (
    <Button type="text" icon={<ArrowLeftOutlined />} onClick={goBack} className="back-link">
      {label}
    </Button>
  )
}

/** Renders「返回审计日志」only when the URL has `from=audit`. */
export function FromAuditBackLink() {
  const fromAudit = useFromAudit()
  if (!fromAudit) return null
  return <BackLink fallback={AUDIT_LOG_PATH} label="返回审计日志" />
}
