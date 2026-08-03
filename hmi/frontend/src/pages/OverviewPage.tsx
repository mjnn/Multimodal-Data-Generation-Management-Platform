import {
  AudioOutlined,
  CheckCircleOutlined,
  DatabaseOutlined,
  ReloadOutlined,
  TagOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { Alert, Button, Progress, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { clipRunOssPrefix, ossManageHref } from '../utils/ossPaths'
import { useAuth } from '../auth/AuthContext'
import { canAccessOss, canBrowseClips, isAnonymousOnly } from '../auth/roles'
import { api } from '../api'
import type { ClipOverview } from '../api/types'
import { PipelineStatus } from '../components/PipelineStatus'
import { OverviewClipMetricsGrid, OverviewClipPieChart } from '../components/OverviewClipPieChart'
import { ContentCard, FilterBar, PageHeader, PageStack } from '../components/ui'
import { useDataSourceMode } from '../context/DataSourceModeContext'
import { useListQueryState } from '../hooks/useListQueryState'
import { clearOverviewSnapshot, getOverviewSnapshot, setOverviewSnapshot } from '../utils/overviewCache'
import { clipDisplayName } from '../utils/clipDisplay'
import { isDemoClip } from '../utils/demoClip'
import {
  classifyOverviewClip,
  summarizeOverviewClipBuckets,
} from '../utils/overviewClipBuckets'

type PipelineFilter = 'all' | 'completed' | 'running' | 'failed' | 'pending' | 'in_review' | 'dataset_ready'

function mergeClipStats(
  clip: ClipOverview,
  statsMap: Record<string, Partial<ClipOverview>>,
): ClipOverview {
  return { ...clip, ...(statsMap[clip.clip_id] ?? {}) }
}

export function OverviewPage() {
  const { user } = useAuth()
  const browseClips = canBrowseClips(user?.roles)
  const showOssLinks = canAccessOss(user?.roles)
  const { dataSource, dataRevision } = useDataSourceMode()
  const cacheKey = `${dataSource}-${dataRevision}`
  const [clips, setClips] = useState<ClipOverview[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const navigate = useNavigate()
  const { status, page, pageSize, setStatus, setPage, setPageSize } = useListQueryState({
    statusKey: 'pipeline',
    defaultStatus: 'all',
    pageKey: 'p',
    pageSizeKey: 'ps',
    defaultPageSize: 10,
  })
  const pipelineFilter = status as PipelineFilter

  useEffect(() => {
    setLoadError(null)
    let cancelled = false

    const fetchFresh = async () => {
      try {
        const [rows, statsMapRaw] = await Promise.all([
          api.getClips({ light: true, refresh: true }),
          api.getBatchClipStats({ refresh: true }).catch(
            () => ({} as Record<string, Partial<ClipOverview>>),
          ),
        ])
        if (cancelled) return
        const merged = rows.map((c) => mergeClipStats(c, statsMapRaw))
        setClips(merged)
        setOverviewSnapshot(cacheKey, merged)
      } catch (e: unknown) {
        if (cancelled) return
        const msg = e instanceof Error ? e.message : '加载 Clip 列表失败'
        setLoadError(msg)
        message.error(msg)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    const cached = getOverviewSnapshot(cacheKey)
    if (cached) {
      setClips(cached.clips)
      setLoading(false)
    } else {
      setLoading(true)
    }
    void fetchFresh()

    return () => {
      cancelled = true
    }
  }, [cacheKey, dataSource])

  const needsPipelinePoll = useMemo(
    () =>
      dataSource === 'local' &&
      clips.some((c) => c.pipeline_status === 'running' || c.pipeline_status === 'pending'),
    [clips, dataSource],
  )

  useEffect(() => {
    if (!needsPipelinePoll) return
    const timer = window.setInterval(() => {
      clearOverviewSnapshot()
      void (async () => {
        try {
          const [rows, statsMapRaw] = await Promise.all([
            api.getClips({ light: true, refresh: true }),
            api.getBatchClipStats({ refresh: true }).catch(
              () => ({} as Record<string, Partial<ClipOverview>>),
            ),
          ])
          const merged = rows.map((c) => mergeClipStats(c, statsMapRaw))
          setClips(merged)
          setOverviewSnapshot(cacheKey, merged)
        } catch {
          /* keep last snapshot on poll errors */
        }
      })()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [needsPipelinePoll, cacheKey])

  const handleRefreshOverview = () => {
    clearOverviewSnapshot()
    setLoadError(null)
    setLoading(true)
    void (async () => {
      try {
        const [rows, statsMapRaw] = await Promise.all([
          api.getClips({ light: true, refresh: true }),
          api.getBatchClipStats({ refresh: true }).catch(
            () => ({} as Record<string, Partial<ClipOverview>>),
          ),
        ])
        const merged = rows.map((c) => mergeClipStats(c, statsMapRaw))
        setClips(merged)
        setOverviewSnapshot(cacheKey, merged)
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : '加载 Clip 列表失败'
        setLoadError(msg)
        message.error(msg)
      } finally {
        setLoading(false)
      }
    })()
  }

  const bucketCounts = useMemo(() => summarizeOverviewClipBuckets(clips), [clips])
  const totalErrors = clips.filter((c) => c.pipeline_status === 'failed').length
  const completed = clips.filter((c) => c.pipeline_status === 'completed').length
  const running = clips.filter((c) => c.pipeline_status === 'running').length
  const pending = clips.filter(
    (c) => c.pipeline_status !== 'completed' && c.pipeline_status !== 'failed' && c.pipeline_status !== 'running',
  ).length

  const filteredClips = useMemo(() => {
    if (pipelineFilter === 'all') return clips
    if (pipelineFilter === 'completed') return clips.filter((c) => c.pipeline_status === 'completed')
    if (pipelineFilter === 'failed') return clips.filter((c) => c.pipeline_status === 'failed')
    if (pipelineFilter === 'running') return clips.filter((c) => c.pipeline_status === 'running')
    if (pipelineFilter === 'in_review') {
      return clips.filter((c) => classifyOverviewClip(c) === 'in_review')
    }
    if (pipelineFilter === 'dataset_ready') {
      return clips.filter((c) => classifyOverviewClip(c) === 'dataset_ready')
    }
    return clips.filter(
      (c) => c.pipeline_status !== 'completed' && c.pipeline_status !== 'failed' && c.pipeline_status !== 'running',
    )
  }, [clips, pipelineFilter])

  const openClip = (clipId: string) => {
    if (!browseClips) return
    navigate(`/clips/${encodeURIComponent(clipId)}`)
  }

  const renderClipName = (r: ClipOverview) => (
    <Space size={6}>
      {isDemoClip(r) ? (
        <Tag color="purple" style={{ margin: 0 }}>
          演示
        </Tag>
      ) : null}
      <Typography.Text strong className="mono" style={{ fontSize: 13, wordBreak: 'break-all' }}>
        {clipDisplayName(r)}
      </Typography.Text>
    </Space>
  )

  const columns: ColumnsType<ClipOverview> = [
    {
      title: 'Clip 标识',
      key: 'clip_info',
      fixed: 'left',
      width: 280,
      render: (_, r) => renderClipName(r),
    },
    {
      title: '管线状态',
      dataIndex: 'pipeline_status',
      width: 100,
      render: (v) => (
        <PipelineStatus
          status={
            v === 'completed' ? 'success' : v === 'failed' ? 'failed' : v === 'running' ? 'running' : 'pending'
          }
        />
      ),
    },
    {
      title: '校核进度',
      width: 260,
      render: (_, r) => {
        const total = r.label_total ?? 0
        const reviewed = r.field_reviewed_count ?? 0
        const disputes = r.dispute_count ?? 0
        const pct = r.review_progress_pct ?? (total > 0 ? Math.round((reviewed / total) * 100) : 0)

        if (!r.clip_label_ready || total === 0) {
          return <Typography.Text type="secondary">未打标</Typography.Text>
        }

        return (
          <Space direction="vertical" size={6} style={{ width: '100%', minWidth: 220 }}>
            <Space size={6} wrap>
              {disputes > 0 ? (
                <Tag color="volcano" icon={<WarningOutlined />}>
                  待校核标签 {disputes}
                </Tag>
              ) : null}
              {r.dataset_ready ? (
                <Tag color="success" icon={<CheckCircleOutlined />}>
                  可入数据集
                </Tag>
              ) : (
                <Tag color="default">待校核</Tag>
              )}
            </Space>
            <Progress
              percent={pct}
              size="small"
              status={r.dataset_ready ? 'success' : reviewed > 0 ? 'active' : 'normal'}
              format={() => `校核 ${reviewed}/${total}`}
            />
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {r.dataset_ready
                ? '全部标签已校核，可用于数据集构建'
                : '需完成全部标签校核后方可纳入数据集'}
            </Typography.Text>
          </Space>
        )
      },
    },
    {
      title: '时长 / Clip 标签',
      width: 240,
      render: (_, r) => (
        <Space direction="vertical" size={4} style={{ width: '100%', minWidth: 200 }}>
          <Typography.Text type="secondary">{r.duration_sec.toFixed(1)}s</Typography.Text>
          <Progress
            percent={r.clip_label_ready ? 100 : 0}
            size="small"
            status={r.clip_label_ready ? 'success' : 'normal'}
            format={() => (r.clip_label_ready ? 'Clip 已打标' : 'Clip 未打标')}
          />
          {r.clip_label_preview ? (
            <Typography.Text type="secondary" ellipsis style={{ fontSize: 11, maxWidth: 220 }}>
              {r.clip_label_preview}
            </Typography.Text>
          ) : null}
        </Space>
      ),
    },
    {
      title: '多模内容',
      width: 140,
      render: (_, r) => (
        <Space direction="vertical" size={2}>
          <span>
            <TagOutlined /> {r.clip_label_ready ? 'Clip 已打标' : 'Clip 未打标'}
          </span>
          <span>
            <AudioOutlined /> ASR {r.asr_segment_count} 段
          </span>
          <span>
            <TagOutlined /> 事件 {r.event_count}
          </span>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      fixed: 'right',
      width: 160,
      render: (_, r) =>
        browseClips || showOssLinks ? (
          <Space size={12} onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
            {browseClips ? (
              <span className="text-link" role="button" tabIndex={0} onClick={() => openClip(r.clip_id)}>
                预览
              </span>
            ) : null}
            {showOssLinks && r.active_run_id ? (
              <span
                className="text-link"
                role="button"
                tabIndex={0}
                onClick={() => navigate(ossManageHref(clipRunOssPrefix(r.clip_id, r.active_run_id)))}
              >
                产物路径
              </span>
            ) : null}
          </Space>
        ) : (
          <Typography.Text type="secondary">—</Typography.Text>
        ),
    },
  ]

  const modeLabel = dataSource === 'local' ? '本地 SQLite + 磁盘' : '在线 OSS + MaxCompute'

  return (
    <PageStack>
      <PageHeader
        title="数据总览"
        description={
          isAnonymousOnly(user?.roles)
            ? `当前为匿名账号，仅可查看总览列表与统计。当前数据源：${modeLabel}。`
            : `当前数据源：${modeLabel}。以 Clip 为单位查看管线状态与校核进度。`
        }
        icon={<DatabaseOutlined />}
        extra={
          <Button icon={<ReloadOutlined />} loading={loading} onClick={handleRefreshOverview}>
            刷新
          </Button>
        }
      />

      {loadError ? (
        <Alert type="error" showIcon message="加载失败" description={loadError} style={{ marginBottom: 16 }} />
      ) : null}

      <ContentCard title="Clip 阶段分布">
        <div className="overview-summary">
          <OverviewClipPieChart counts={bucketCounts} total={clips.length} />
          <OverviewClipMetricsGrid counts={bucketCounts} total={clips.length} />
        </div>
      </ContentCard>

      <ContentCard
        title="全部 Clip"
        extra={browseClips ? '点击行进入 Clip 预览' : undefined}
        noPadding
        toolbar={
          <FilterBar
            aria-label="管线状态筛选"
            value={pipelineFilter}
            total={filteredClips.length}
            totalLabel="条 Clip"
            onChange={setStatus}
            options={[
              { value: 'all', label: '全部', count: clips.length },
              { value: 'completed', label: '管线已完成', count: completed },
              { value: 'running', label: '进行中', count: running },
              { value: 'in_review', label: '校核中', count: bucketCounts.in_review },
              { value: 'dataset_ready', label: '可入数据集', count: bucketCounts.dataset_ready },
              { value: 'failed', label: '失败', count: totalErrors },
              { value: 'pending', label: '待处理', count: pending },
            ]}
          />
        }
      >
        <Table
          rowKey="clip_id"
          loading={loading}
          columns={columns}
          dataSource={filteredClips}
          pagination={{
            current: page,
            pageSize,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50'],
            onChange: (p, ps) => {
              setPage(p)
              if (ps !== pageSize) setPageSize(ps)
            },
          }}
          scroll={{ x: 1100 }}
          tableLayout="fixed"
          locale={{
            emptyText:
              dataSource === 'local'
                ? '暂无 Clip；可运行 init_local_runtime.py、seed_demo 或 import_real_data_clips'
                : '暂无 Clip；请确认 OSS/MC 凭证与云端数据',
          }}
          rowClassName={browseClips ? () => 'clickable-row' : undefined}
          onRow={
            browseClips
              ? (r) => ({ onClick: () => openClip(r.clip_id) })
              : undefined
          }
        />
      </ContentCard>
    </PageStack>
  )
}
