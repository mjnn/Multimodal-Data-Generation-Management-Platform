import { Space, Switch, Tag, Typography, message } from 'antd'
import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { OssSyncPollerStatus } from '../../api/types'
import { useDataSourceMode } from '../../context/DataSourceModeContext'
import { formatSyncStatus } from '../../utils/uiLabels'

export function PipelineSyncControls() {
  const { dataSource } = useDataSourceMode()
  const [syncStatus, setSyncStatus] = useState<OssSyncPollerStatus | null>(null)
  const [syncSaving, setSyncSaving] = useState(false)
  const cloud = dataSource === 'cloud'

  useEffect(() => {
    api.getSyncPollerStatus().then(setSyncStatus).catch(() => {})
  }, [dataSource])

  const onToggleAutoSync = async (checked: boolean) => {
    setSyncSaving(true)
    try {
      const status = await api.setSyncPollerEnabled(checked)
      setSyncStatus(status)
      message.success(checked ? '已开启 OSS 自动同步' : '已关闭 OSS 自动同步')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSyncSaving(false)
    }
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={12} data-testid="oss-sync-controls">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {cloud
          ? '在线模式下可将 OSS 产物同步到本机 HMI（可选，不影响在线浏览）。'
          : '将 OSS 产物同步回本机 HMI 浏览目录（轮询 pipeline/dispatch/latest.json）。'}
      </Typography.Paragraph>
      <Space wrap align="center">
        <Switch
          checked={syncStatus?.auto_sync_enabled ?? false}
          loading={syncSaving}
          onChange={onToggleAutoSync}
          checkedChildren="开"
          unCheckedChildren="关"
          data-testid="oss-auto-sync-switch"
        />
        <Typography.Text>自动同步 OSS 产物到本地 HMI</Typography.Text>
        {syncStatus?.running_sync && <Tag color="processing">同步进行中</Tag>}
        {syncStatus?.last_sync_status && (
          <Tag color={syncStatus.last_sync_status === 'success' ? 'success' : 'default'}>
            上次：{formatSyncStatus(syncStatus.last_sync_status)}
            {syncStatus.last_sync_at
              ? ` · ${api.formatDateTime(syncStatus.last_sync_at)}`
              : ''}
          </Tag>
        )}
      </Space>
      {syncStatus?.last_sync_error ? (
        <Typography.Text type="danger" style={{ fontSize: 12 }}>
          {syncStatus.last_sync_error.slice(0, 300)}
        </Typography.Text>
      ) : null}
    </Space>
  )
}
