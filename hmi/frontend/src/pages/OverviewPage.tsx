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
import { api } from '../api'
import type { ClipOverview } from '../api/types'
import { PipelineStatus } from '../components/PipelineStatus'
import { ContentCard, FilterBar, PageHeader, PageStack, StatCard } from '../components/ui'
import { useDemoMode } from '../context/DemoModeContext'
import { useListQueryState } from '../hooks/useListQueryState'
import { clearOverviewSnapshot, getOverviewSnapshot, setOverviewSnapshot } from '../utils/overviewCache'
import { clipDisplayName } from '../utils/clipDisplay'
import { isDemoClip } from '../utils/demoClip'

type PipelineFilter = 'all' | 'completed' | 'running' | 'failed' | 'pending'

function mergeClipStats(
  clip: ClipOverview,
  statsMap: Record<string, Partial<ClipOverview>>,
): ClipOverview {
  return { ...clip, ...(statsMap[clip.clip_id] ?? {}) }
}

export function OverviewPage() {
  const { demoMode, demoDataVersion } = useDemoMode()
  const [realClips, setRealClips] = useState<ClipOverview[]>([])
  const [demoClips, setDemoClips] = useState<ClipOverview[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const navigate = useNavigate()
  const { status, setStatus } = useListQueryState({
    statusKey: 'pipeline',
    defaultStatus: 'all',
    pageKey: 'p',
  })
  const pipelineFilter = status as PipelineFilter

  useEffect(() => {
    setLoadError(null)

    const load = async (refresh = false) => {
      const cached = !refresh ? getOverviewSnapshot(demoDataVersion) : null
      if (cached) {
        setRealClips(cached.realClips)
        setDemoClips(cached.demoClips)
        setLoading(false)
        return
      }

      setLoading(true)
      try {
        const [rows, statsMapRaw] = await Promise.all([
          api.getClips({ light: true, refresh }),
          api.getBatchClipStats({ refresh }).catch(
            () => ({} as Record<string, Partial<ClipOverview>>),
          ),
        ])
        const statsMap = statsMapRaw

        const merged = rows.map((c) => mergeClipStats(c, statsMap))
        const fromList = merged.filter(isDemoClip)

        let demoRows: ClipOverview[] = fromList
        if (demoMode) {
          try {
            const remoteDemo = await api.getDemoClips()
            if (remoteDemo.length > 0) {
              demoRows = remoteDemo.map((c) => mergeClipStats(c, statsMap))
            }
          } catch {
            // Fallback when /clips/demo is unavailable (older backend).
          }
        }

        const real = merged.filter((c) => !isDemoClip(c))
        setDemoClips(demoRows)
        setRealClips(real)
        setOverviewSnapshot(demoDataVersion, real, demoRows)
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : '加载 Clip 列表失败'
        setLoadError(msg)
        message.error(msg)
      } finally {
        setLoading(false)
      }
    }

    void load(false)
  }, [demoDataVersion, demoMode])

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
        const statsMap = statsMapRaw
        const merged = rows.map((c) => mergeClipStats(c, statsMap))
        const fromList = merged.filter(isDemoClip)
        let demoRows: ClipOverview[] = fromList
        if (demoMode) {
          try {
            const remoteDemo = await api.getDemoClips()
            if (remoteDemo.length > 0) {
              demoRows = remoteDemo.map((c) => mergeClipStats(c, statsMap))
            }
          } catch {
            /* ignore */
          }
        }
        const real = merged.filter((c) => !isDemoClip(c))
        setDemoClips(demoRows)
        setRealClips(real)
        setOverviewSnapshot(demoDataVersion, real, demoRows)
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : '加载 Clip 列表失败'
        setLoadError(msg)
        message.error(msg)
      } finally {
        setLoading(false)
      }
    })()
  }

  const clips = demoMode ? demoClips : realClips

  const labeledCount = clips.filter((c) => c.clip_label_ready).length
  const datasetReadyCount = clips.filter((c) => c.dataset_ready).length
  const disputeClipCount = clips.filter((c) => (c.dispute_count ?? 0) > 0).length
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
    return clips.filter(
      (c) => c.pipeline_status !== 'completed' && c.pipeline_status !== 'failed' && c.pipeline_status !== 'running',
    )
  }, [clips, pipelineFilter])

  const openClip = (clipId: string) => {
    navigate(`/clips/${encodeURIComponent(clipId)}`)
  }

  const renderClipName = (r: ClipOverview) => (
    <Space size={6}>
      {demoMode ? (
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
      title: 'Clip ID',
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
      width: 80,
      render: (_, r) => (
        <Space size={12} onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
          <span className="text-link" role="button" tabIndex={0} onClick={() => openClip(r.clip_id)}>
            预览
          </span>
        </Space>
      ),
    },
  ]

  return (
    <PageStack>
      <PageHeader
        title="数据总览"
        description={
          demoMode
            ? '演示模式：仅展示 mock 演示 Clip，可用于 walkthrough 与功能验证。'
            : '以 Clip 为单位查看管线状态与校核进度；全部标签校核完成后方可纳入数据集构建。'
        }
        icon={<DatabaseOutlined />}
        extra={
          <Button
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={handleRefreshOverview}
          >
            刷新
          </Button>
        }
      />

      {loadError ? (
        <Alert type="error" showIcon message="加载失败" description={loadError} style={{ marginBottom: 16 }} />
      ) : null}

      <div className="stat-grid">
        <StatCard label="Clip 总数" value={clips.length} accent="stat" />
        <StatCard label="已完成" value={completed} icon={<CheckCircleOutlined />} accent="success" />
        <StatCard label="Clip 已打标" value={labeledCount} accent="default" />
        <StatCard
          label="可入数据集"
          value={datasetReadyCount}
          icon={<CheckCircleOutlined />}
          accent={datasetReadyCount ? 'success' : 'default'}
        />
        <StatCard
          label="含待校核标签"
          value={disputeClipCount}
          icon={<WarningOutlined />}
          accent={disputeClipCount ? 'danger' : 'default'}
        />
        <StatCard
          label="失败 Clip"
          value={totalErrors}
          icon={<WarningOutlined />}
          accent={totalErrors ? 'danger' : 'default'}
        />
      </div>

      <ContentCard
        title={demoMode ? '演示 Clip' : '全部 Clip'}
        extra={
          demoMode
            ? '覆盖 AI 打标各场景（空值/低置信/已校核/未打标等）；可在左上角重置'
            : '点击行进入 Clip 预览'
        }
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
              { value: 'completed', label: '已完成', count: completed },
              { value: 'running', label: '进行中', count: running },
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
          pagination={{ pageSize: 10, showSizeChanger: true, pageSizeOptions: ['10', '20', '50'] }}
          scroll={{ x: 1100 }}
          tableLayout="fixed"
          locale={{
            emptyText: demoMode
              ? '暂无演示数据，请打开演示模式后点击「重置演示数据」'
              : '暂无 Clip 数据',
          }}
          rowClassName={() => 'clickable-row'}
          onRow={(r) => ({ onClick: () => openClip(r.clip_id) })}
        />
      </ContentCard>
    </PageStack>
  )
}
