import { CloudOutlined, DatabaseOutlined } from '@ant-design/icons'
import { Button, Space, Tooltip, Typography } from 'antd'
import { useDataSourceMode } from '../context/DataSourceModeContext'
import { ResetTestDataButton } from './ResetTestDataButton'

type Props = {
  collapsed?: boolean
}

function DataSourceModeButtons({
  compact,
  localMode,
  loading,
  switching,
  onSelectLocal,
  onSelectCloud,
}: {
  compact?: boolean
  localMode: boolean
  loading: boolean
  switching: boolean
  onSelectLocal: () => void
  onSelectCloud: () => void
}) {
  const busy = loading || switching

  return (
    <Space.Compact block={!compact} style={compact ? undefined : { width: '100%' }}>
      <Tooltip title={compact ? '本地：SQLite + 磁盘' : undefined} placement={compact ? 'right' : 'top'}>
        <Button
          type={localMode ? 'primary' : 'default'}
          size="small"
          icon={<DatabaseOutlined />}
          loading={busy && !localMode}
          onClick={onSelectLocal}
          aria-pressed={localMode}
          data-testid="local-mode-local-btn"
        >
          {!compact ? '本地' : null}
        </Button>
      </Tooltip>
      <Tooltip
        title={compact ? '在线：aig_sdk__ + OSS bucket2' : undefined}
        placement={compact ? 'right' : 'top'}
      >
        <Button
          type={!localMode ? 'primary' : 'default'}
          size="small"
          icon={<CloudOutlined />}
          loading={busy && localMode}
          onClick={onSelectCloud}
          block={!compact}
          aria-pressed={!localMode}
          data-testid="local-mode-cloud-btn"
        >
          {!compact ? '在线' : null}
        </Button>
      </Tooltip>
    </Space.Compact>
  )
}

/** Shown only when HMI_TEST_MODE is on (local/cloud switch + reset). */
export function LocalModeControls({ collapsed = false }: Props) {
  const { localMode, loading, switching, testMode, setLocalMode } = useDataSourceMode()

  if (!testMode) {
    return null
  }

  const selectLocal = () => {
    if (!localMode) void setLocalMode(true)
  }

  const selectCloud = () => {
    if (localMode) void setLocalMode(false)
  }

  if (collapsed) {
    return (
      <div className="app-shell__demo-controls app-shell__demo-controls--collapsed">
        <DataSourceModeButtons
          compact
          localMode={localMode}
          loading={loading}
          switching={switching}
          onSelectLocal={selectLocal}
          onSelectCloud={selectCloud}
        />
        <ResetTestDataButton collapsed />
      </div>
    )
  }

  return (
    <div className="app-shell__demo-controls">
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <DataSourceModeButtons
          localMode={localMode}
          loading={loading}
          switching={switching}
          onSelectLocal={selectLocal}
          onSelectCloud={selectCloud}
        />
        <Typography.Text type="secondary" className="app-shell__demo-hint">
          测试模式：可切换本地 / 云端；云端重置会清空 OSS + MC
        </Typography.Text>
        <ResetTestDataButton block />
      </Space>
    </div>
  )
}
