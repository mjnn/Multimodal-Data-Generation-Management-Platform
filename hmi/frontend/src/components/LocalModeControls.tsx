import { CloudOutlined, DatabaseOutlined, ReloadOutlined } from '@ant-design/icons'
import { Button, Modal, Space, Tooltip, Typography, message } from 'antd'
import { useState } from 'react'
import { api } from '../api'
import { useDataSourceMode } from '../context/DataSourceModeContext'

const CLOUD_UNAVAILABLE_TIP = '云端管线暂不可用'

type Props = {
  collapsed?: boolean
}

function DataSourceModeButtons({
  compact,
  localMode,
  loading,
  switching,
  onSelectLocal,
}: {
  compact?: boolean
  localMode: boolean
  loading: boolean
  switching: boolean
  onSelectLocal: () => void
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
      <Tooltip title={CLOUD_UNAVAILABLE_TIP} placement={compact ? 'right' : 'top'}>
        <span
          className={compact ? undefined : 'local-mode-cloud-btn-wrap'}
          style={compact ? { display: 'inline-block' } : undefined}
        >
          <Button
            size="small"
            icon={<CloudOutlined />}
            disabled
            block={!compact}
            aria-disabled
            data-testid="local-mode-cloud-btn"
          >
            {!compact ? '云端' : null}
          </Button>
        </span>
      </Tooltip>
    </Space.Compact>
  )
}

export function LocalModeControls({ collapsed = false }: Props) {
  const { localMode, loading, switching, setLocalMode, bumpDataRevision } = useDataSourceMode()
  const [resetting, setResetting] = useState(false)

  const handleResetHmiArtifacts = () => {
    Modal.confirm({
      title: '重置 HMI 产物？',
      content: (
        <>
          <p>将恢复到 baseline 初始状态（需 admin 权限）：</p>
          <ul style={{ marginBottom: 0, paddingLeft: 20 }}>
            <li>清空人工校核、派单任务、数据集快照与审计日志</li>
            <li>删除除 admin 以外的所有用户</li>
            <li>标签树仅保留已发布版本 <strong>label_tree_baseline</strong>（全量 YAML）</li>
            <li>
              本地模式：清空 SDK 管线（<code>hmi.db</code> clip/run/事实表、上传 rosbag、管线步骤、
              <code>artifacts/</code>、<code>oss/rosbags</code>、<code>oss/clips</code>、
              <code>oss/pipeline</code>、执行参数）
            </li>
            <li>本地模式下清空 oss/datasets、oss/reviews 目录</li>
          </ul>
        </>
      ),
      okText: '确认重置',
      cancelText: '取消',
      okButtonProps: { danger: true },
      width: 480,
      onOk: async () => {
        setResetting(true)
        try {
          const res = await api.resetHmiArtifacts()
          message.success(res.message ?? 'HMI 产物已重置')
          bumpDataRevision()
        } catch (e: unknown) {
          const msg = e instanceof Error ? e.message : '重置 HMI 产物失败'
          message.error(msg)
          throw e
        } finally {
          setResetting(false)
        }
      },
    })
  }

  const selectLocal = () => {
    if (!localMode) void setLocalMode(true)
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
        />
        {localMode ? (
          <Tooltip title="重置 HMI 产物" placement="right">
            <Button
              type="text"
              size="small"
              icon={<ReloadOutlined />}
              loading={resetting}
              onClick={handleResetHmiArtifacts}
              aria-label="重置 HMI 产物"
              data-testid="hmi-reset-button"
            />
          </Tooltip>
        ) : null}
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
        />
        <Typography.Text type="secondary" className="app-shell__demo-hint">
          本地：SQLite + 磁盘 oss/（ECS 同理）；云端入口暂不可用
        </Typography.Text>
        {localMode ? (
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={resetting}
            onClick={handleResetHmiArtifacts}
            block
            data-testid="hmi-reset-button"
          >
            重置 HMI 产物
          </Button>
        ) : null}
      </Space>
    </div>
  )
}
