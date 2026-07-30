import { ApartmentOutlined, EyeOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons'
import { Button, Popconfirm, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType, TablePaginationConfig } from 'antd/es/table'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import type { PipelineExecution, PipelineExecutionClip } from '../api/types'
import { PipelineStatus } from '../components/PipelineStatus'
import { PipelineSyncControls } from '../components/pipeline/PipelineSyncControls'
import { RosbagUploadCard } from '../components/pipeline/RosbagUploadCard'
import { PipelineRunSettingsCard } from '../components/pipeline/PipelineRunSettingsCard'
import { UploadPipelineProgress, firstFailedStepError } from '../components/UploadPipelineProgress'
import { ContentCard, PageHeader, PageStack } from '../components/ui'
import { useDataSourceMode } from '../context/DataSourceModeContext'
import { clipDisplayName } from '../utils/clipDisplay'
import { formatDateTime } from '../utils/format'

import type { AxiosError } from 'axios'

function pipelineErrorMessage(e: unknown, fallback: string): string {
  const ax = e as AxiosError<{ detail?: string | { message?: string } }>
  const detail = ax.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
    return detail.message
  }
  if (e instanceof Error && e.message) return e.message
  return fallback
}

function clipStatusTag(status: string) {
  const s =
    status === 'completed' || status === 'success'
      ? 'success'
      : status === 'failed'
        ? 'failed'
        : status === 'cancelled'
          ? 'cancelled'
          : status === 'running'
            ? 'running'
            : 'pending'
  return <PipelineStatus status={s} size="small" />
}

function executionCanCancel(status: string): boolean {
  return status === 'pending' || status === 'running'
}

export function PipelineManagePage() {
  const navigate = useNavigate()
  const { dataSource, dataRevision, bumpDataRevision } = useDataSourceMode()
  const [executions, setExecutions] = useState<PipelineExecution[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [loading, setLoading] = useState(true)
  const [retryingClipId, setRetryingClipId] = useState<string | null>(null)
  const [cancellingRunId, setCancellingRunId] = useState<string | null>(null)
  const [expandedRowKeys, setExpandedRowKeys] = useState<string[]>([])

  const loadExecutions = useCallback(async () => {
    if (dataSource !== 'local') {
      setExecutions([])
      setTotal(0)
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const res = await api.listPipelineExecutions({ page, page_size: pageSize })
      setExecutions(res.items)
      setTotal(res.total)
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : '加载执行队列失败')
    } finally {
      setLoading(false)
    }
  }, [dataSource, page, pageSize])

  const handleRetryPipeline = useCallback(
    async (clipId: string, runId: string) => {
      setRetryingClipId(clipId)
      try {
        await api.retryPipelineRun({ clip_id: clipId, run_id: runId })
        message.success('已重置为上传后状态，SDK 轮询将重新处理')
        bumpDataRevision()
        await loadExecutions()
      } catch (e: unknown) {
        message.error(pipelineErrorMessage(e, '重试失败'))
      } finally {
        setRetryingClipId(null)
      }
    },
    [bumpDataRevision, loadExecutions],
  )

  const handleCancelExecution = useCallback(
    async (runId: string) => {
      setCancellingRunId(runId)
      try {
        const res = await api.cancelPipelineExecution(runId)
        message.success(`已中止 ${res.cancelled_clips} 个 clip`)
        bumpDataRevision()
        await loadExecutions()
      } catch (e: unknown) {
        message.error(pipelineErrorMessage(e, '中止失败'))
      } finally {
        setCancellingRunId(null)
      }
    },
    [bumpDataRevision, loadExecutions],
  )

  useEffect(() => {
    void loadExecutions()
  }, [dataSource, dataRevision, loadExecutions])

  const needsPoll = useMemo(
    () =>
      executions.some(
        (ex) =>
          ex.pipeline_status === 'running' ||
          ex.pipeline_status === 'pending' ||
          ex.clips.some((c) => c.pipeline_status === 'running' || c.pipeline_status === 'pending'),
      ),
    [executions],
  )

  useEffect(() => {
    if (!needsPoll) return
    const t = window.setInterval(() => void loadExecutions(), 5000)
    return () => window.clearInterval(t)
  }, [needsPoll, loadExecutions])

  const onTableChange = (pagination: TablePaginationConfig) => {
    if (pagination.current != null) setPage(pagination.current)
    if (pagination.pageSize != null) {
      setPageSize(pagination.pageSize)
      setPage(1)
    }
  }

  const clipColumns: ColumnsType<PipelineExecutionClip & { run_id: string }> = useMemo(
    () => [
      {
        title: 'Clip',
        key: 'clip',
        width: 200,
        ellipsis: true,
        render: (_, r) => {
          const id = clipDisplayName({ clip_id: r.clip_id })
          return (
            <Typography.Text className="mono" style={{ fontSize: 12 }} ellipsis={{ tooltip: id }}>
              {id}
            </Typography.Text>
          )
        },
      },
      {
        title: '状态',
        dataIndex: 'pipeline_status',
        width: 100,
        render: (v, r) => {
          const err = firstFailedStepError(r.steps)
          if (v === 'failed' && err) {
            return <PipelineStatus status="failed" errorMsg={err} size="small" />
          }
          return clipStatusTag(v)
        },
      },
      {
        title: '创建时间',
        dataIndex: 'pipeline_created_at',
        width: 168,
        render: (v: string | null | undefined) => (
          <Typography.Text style={{ fontSize: 12 }}>{formatDateTime(v)}</Typography.Text>
        ),
      },
      {
        title: '最近更新',
        dataIndex: 'pipeline_updated_at',
        width: 168,
        render: (v: string | null | undefined) => (
          <Typography.Text style={{ fontSize: 12 }}>{formatDateTime(v)}</Typography.Text>
        ),
      },
      {
        title: '操作',
        key: 'actions',
        width: 140,
        render: (_, r) => (
          <Space size={4} wrap>
            <Button
              type="link"
              size="small"
              icon={<EyeOutlined />}
              onClick={() => navigate(`/clips/${encodeURIComponent(r.clip_id)}`)}
            >
              预览
            </Button>
            {dataSource === 'local' &&
            (r.pipeline_status === 'failed' || r.pipeline_status === 'cancelled') ? (
              <Popconfirm
                title="重试管线"
                description={
                  r.pipeline_status === 'cancelled'
                    ? '将清除本 clip 在本 run 下的产物并重置为 pending，重新进入 SDK 队列。'
                    : '将清除本 clip 在本 run 下的产物并重置为 pending。'
                }
                okText="重试"
                cancelText="取消"
                onConfirm={() => void handleRetryPipeline(r.clip_id, r.run_id)}
              >
                <Button size="small" icon={<ReloadOutlined />} loading={retryingClipId === r.clip_id}>
                  重试
                </Button>
              </Popconfirm>
            ) : null}
          </Space>
        ),
      },
    ],
    [dataSource, handleRetryPipeline, navigate, retryingClipId],
  )

  const executionColumns: ColumnsType<PipelineExecution> = useMemo(
    () => [
      {
        title: '执行批次',
        dataIndex: 'label',
        key: 'label',
        width: 180,
        render: (label: string, row) => (
          <Space direction="vertical" size={0}>
            <Typography.Text strong style={{ fontSize: 13 }}>
              {label}
            </Typography.Text>
            <Typography.Text code style={{ fontSize: 10 }} ellipsis={{ tooltip: row.run_id }}>
              {row.run_id.slice(0, 8)}…
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: '状态',
        dataIndex: 'pipeline_status',
        width: 100,
        render: (v) => clipStatusTag(v),
      },
      {
        title: 'Clip 数',
        dataIndex: 'clip_count',
        width: 80,
      },
      {
        title: '开始时间',
        dataIndex: 'started_at',
        width: 168,
        render: (v: string) => (
          <Typography.Text style={{ fontSize: 12 }}>{formatDateTime(v)}</Typography.Text>
        ),
      },
      {
        title: '操作',
        key: 'actions',
        width: 100,
        render: (_, row) =>
          dataSource === 'local' && executionCanCancel(row.pipeline_status) ? (
            <Popconfirm
              title="中止执行"
              description="待执行与执行中的 clip 将标记为已中止，已完成/失败的 clip 不受影响。"
              okText="中止"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => void handleCancelExecution(row.run_id)}
            >
              <Button
                size="small"
                danger
                icon={<StopOutlined />}
                loading={cancellingRunId === row.run_id}
              >
                中止
              </Button>
            </Popconfirm>
          ) : null,
      },
    ],
    [cancellingRunId, dataSource, handleCancelExecution],
  )

  return (
    <PageStack>
      <PageHeader
        title="管线管理"
        description="上传 rosbag、控制 OSS 产物同步，并按执行批次查看 SDK 进度（最新在前）。"
        icon={<ApartmentOutlined />}
        extra={
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void loadExecutions()}>
            刷新
          </Button>
        }
      />

      <ContentCard title="执行参数">
        <PipelineRunSettingsCard />
      </ContentCard>

      <ContentCard title="上传与同步">
        <Space direction="vertical" size={20} style={{ width: '100%' }}>
          <RosbagUploadCard onUploaded={() => bumpDataRevision()} />
          <PipelineSyncControls />
        </Space>
      </ContentCard>

      <ContentCard title="管线执行队列" noPadding>
        <Table<PipelineExecution>
          rowKey="run_id"
          loading={loading}
          columns={executionColumns}
          dataSource={executions}
          tableLayout="fixed"
          scroll={{ x: 720 }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50'],
            showTotal: (t) => `共 ${t} 次执行`,
          }}
          onChange={onTableChange}
          expandable={{
            expandedRowKeys,
            onExpandedRowsChange: (keys) => setExpandedRowKeys(keys as string[]),
            expandedRowRender: (ex) => (
              <Table<PipelineExecutionClip & { run_id: string }>
                rowKey="clip_id"
                size="small"
                pagination={false}
                columns={clipColumns}
                dataSource={ex.clips.map((c) => ({ ...c, run_id: ex.run_id }))}
                expandable={{
                  expandedRowRender: (r) =>
                    r.steps?.length ? (
                      <UploadPipelineProgress steps={r.steps} compact />
                    ) : (
                      <Typography.Text type="secondary">暂无步骤数据</Typography.Text>
                    ),
                  rowExpandable: (r) => (r.steps?.length ?? 0) > 0,
                }}
              />
            ),
          }}
          locale={{
            emptyText:
              dataSource === 'local'
                ? '暂无执行记录；请暂存 rosbag 并「确认执行管线」'
                : '执行队列仅在本地数据源下展示',
          }}
        />
      </ContentCard>

      <ContentCard title="图例">
        <Space wrap>
          <Tag>
            {dataSource === 'local'
              ? '一次执行可包含多个 bag（同一 run_id）；各 clip SDK 步骤可并发'
              : 'SDK 上云：打标与向量 → OSS 上传 → MC 写入 → 调度'}
          </Tag>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            展开执行批次查看各 clip；再展开 clip 查看步骤详情
          </Typography.Text>
        </Space>
      </ContentCard>
    </PageStack>
  )
}
