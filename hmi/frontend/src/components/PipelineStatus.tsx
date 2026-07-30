import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  MinusCircleOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { Tag, Tooltip } from 'antd'
import type { PipelineStatus as Status } from '../api/types'

const CONFIG: Record<
  Status,
  { color: string; icon: React.ReactNode; text: string }
> = {
  success: { color: 'success', icon: <CheckCircleOutlined />, text: '成功' },
  failed: { color: 'error', icon: <CloseCircleOutlined />, text: '失败' },
  running: { color: 'processing', icon: <SyncOutlined spin />, text: '执行中' },
  pending: { color: 'warning', icon: <ClockCircleOutlined />, text: '待执行' },
  skipped: { color: 'default', icon: <MinusCircleOutlined />, text: '跳过' },
  cancelled: { color: 'default', icon: <CloseCircleOutlined />, text: '已中止' },
}

interface Props {
  status: Status
  errorStage?: string | null
  errorMsg?: string | null
  size?: 'small' | 'default'
}

export function PipelineStatus({ status, errorStage, errorMsg, size = 'default' }: Props) {
  const cfg = CONFIG[status] ?? CONFIG.pending
  const tag = (
    <Tag color={cfg.color} icon={cfg.icon} style={size === 'small' ? { fontSize: 12 } : undefined}>
      {cfg.text}
    </Tag>
  )
  if (status === 'failed' && (errorStage || errorMsg)) {
    return (
      <Tooltip title={[errorStage, errorMsg].filter(Boolean).join(' — ')}>{tag}</Tooltip>
    )
  }
  return tag
}
