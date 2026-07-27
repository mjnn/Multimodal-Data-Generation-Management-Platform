import {
  CloudDownloadOutlined,
  DeleteOutlined,
  FolderOpenOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Descriptions,
  Popconfirm,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import type { DatasetSnapshot, DatasetStatus } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { canManageDatasets } from '../auth/roles'
import { ContentCard, PageHeader, PageStack, BackLink } from '../components/ui'

const STATUS_COLOR: Record<DatasetStatus, string> = {
  building: 'processing',
  ready: 'success',
  failed: 'error',
  archived: 'default',
}

const STATUS_LABEL: Record<DatasetStatus, string> = {
  building: '构建中',
  ready: '就绪',
  failed: '失败',
  archived: '已归档',
}

function formatFilterJson(filter: DatasetSnapshot['filter_json']): string {
  const parts: string[] = []
  if (filter.include_pending_review) {
    parts.push('含待校核')
  } else {
    parts.push('仅已校核')
  }
  if (filter.sample_size) {
    parts.push(`随机取样 ${filter.sample_size} 条`)
  }
  if (filter.label_filters && Object.keys(filter.label_filters).length > 0) {
    const labels = Object.entries(filter.label_filters)
      .map(([k, v]) => `${k}=${String(v)}`)
      .join('；')
    parts.push(`标签: ${labels}`)
  }
  if (filter.clip_ids?.length) {
    parts.push(`指定 clip ${filter.clip_ids.length} 条`)
  }
  if (filter.taxonomy_version_id) {
    parts.push(`taxonomy ${filter.taxonomy_version_id}`)
  }
  return parts.join(' · ')
}

const POLL_MS = 2500

export function DatasetDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { user } = useAuth()
  const canManage = canManageDatasets(user?.roles)

  const [snapshot, setSnapshot] = useState<DatasetSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [downloading, setDownloading] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const pollRef = useRef<number | null>(null)

  const loadSnapshot = useCallback(async (silent = false) => {
    if (!id) return null
    if (!silent) setLoading(true)
    try {
      const detail = await api.getDataset(id)
      setSnapshot(detail)
      return detail
    } catch {
      if (!silent) message.error('加载数据集详情失败')
      navigate('/datasets')
      return null
    } finally {
      if (!silent) setLoading(false)
    }
  }, [id, navigate])

  useEffect(() => {
    void loadSnapshot()
  }, [loadSnapshot])

  useEffect(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
    if (!snapshot || (snapshot.status !== 'building' && !snapshot.build_running)) return

    pollRef.current = window.setInterval(() => {
      void loadSnapshot(true)
    }, POLL_MS)

    return () => {
      if (pollRef.current != null) window.clearInterval(pollRef.current)
    }
  }, [snapshot?.status, snapshot?.build_running, loadSnapshot])

  const openDownload = async () => {
    if (!id) return
    setDownloading(true)
    try {
      const res = await api.getDatasetDownload(id)
      window.open(res.package_url, '_blank', 'noopener,noreferrer')
      message.success(`已开始下载完整包（含特征、目标与解析原始数据，${res.clip_count ?? 0} 条 clip）`)
    } catch {
      message.error('获取下载链接失败')
    } finally {
      setDownloading(false)
    }
  }

  const handleRetry = async () => {
    if (!id) return
    setRetrying(true)
    try {
      const updated = await api.retryDataset(id)
      setSnapshot(updated)
      message.success('已重新触发构建')
    } catch {
      message.error('重试失败')
    } finally {
      setRetrying(false)
    }
  }

  const handleDelete = async () => {
    if (!id) return
    try {
      await api.deleteDataset(id)
      message.success('数据集已归档')
      navigate('/datasets')
    } catch {
      message.error('删除失败')
    }
  }

  if (loading || !snapshot) {
    return (
      <div data-testid="dataset-detail-page" style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    )
  }

  const building = snapshot.status === 'building' || snapshot.build_running

  return (
    <PageStack data-testid="dataset-detail-page">
      <PageHeader
        title={snapshot.name}
        description="数据集快照详情；就绪后可下载完整包（特征向量 + 校核标签 + 解析原始数据）。"
        icon={<FolderOpenOutlined />}
        extra={
          <Space wrap>
            <BackLink fallback="/datasets" label="返回列表" />
            <Tag color={STATUS_COLOR[snapshot.status]}>{STATUS_LABEL[snapshot.status]}</Tag>
          </Space>
        }
      />

      {building && (
        <Alert type="info" showIcon message="数据集构建中，页面将自动刷新状态…" />
      )}

      {snapshot.status === 'failed' && snapshot.error_message && (
        <Alert type="error" showIcon message="构建失败" description={snapshot.error_message} />
      )}

      <ContentCard
        title="快照信息"
        extra={
          <Space>
            {snapshot.status === 'ready' && (
              <Button
                type="primary"
                icon={<CloudDownloadOutlined />}
                loading={downloading}
                onClick={() => void openDownload()}
              >
                下载完整包
              </Button>
            )}
            {canManage && snapshot.status === 'failed' && (
              <Button icon={<ReloadOutlined />} loading={retrying} onClick={() => void handleRetry()}>
                重试构建
              </Button>
            )}
            {canManage && snapshot.status !== 'archived' && (
              <Popconfirm title="确认归档此数据集？" onConfirm={() => void handleDelete()}>
                <Button danger icon={<DeleteOutlined />}>
                  归档
                </Button>
              </Popconfirm>
            )}
          </Space>
        }
      >
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="ID">{snapshot.id}</Descriptions.Item>
          <Descriptions.Item label="描述">{snapshot.description ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="Clip 数">{snapshot.clip_count}</Descriptions.Item>
          <Descriptions.Item label="下载包">
            {snapshot.oss_manifest_uri ?? '构建完成后生成 dataset.zip'}
          </Descriptions.Item>
          <Descriptions.Item label="包内文件">
            <Typography.Text>
              特征.jsonl（向量）· 目标.jsonl（标签）· meta.json · README.txt
            </Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="OSS · 特征">{snapshot.oss_x_uri ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="OSS · 目标">{snapshot.oss_y_uri ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="取样条件">
            <Space direction="vertical" size={4}>
              <Typography.Text>{formatFilterJson(snapshot.filter_json)}</Typography.Text>
              <Typography.Text code className="mono" style={{ fontSize: 11 }}>
                {JSON.stringify(snapshot.filter_json)}
              </Typography.Text>
            </Space>
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">{snapshot.created_at}</Descriptions.Item>
          <Descriptions.Item label="就绪时间">{snapshot.ready_at ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="更新时间">{snapshot.updated_at}</Descriptions.Item>
        </Descriptions>
      </ContentCard>
    </PageStack>
  )
}
