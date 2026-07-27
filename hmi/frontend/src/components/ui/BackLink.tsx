import { ArrowLeftOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useNavigate } from 'react-router-dom'

type BackLinkProps = {
  fallback: string
  label?: string
}

/** Predictable back navigation with history fallback (ux: back-behavior, drill-down-consistency). */
export function BackLink({ fallback, label = '返回' }: BackLinkProps) {
  const navigate = useNavigate()

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
