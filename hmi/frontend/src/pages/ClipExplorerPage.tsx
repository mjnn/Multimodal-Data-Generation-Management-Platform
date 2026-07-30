import { AudioOutlined } from '@ant-design/icons'
import { Space, Spin, Tag, Typography } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type { ClipOverview, ClipRun, ClipLabelView, TaxonomyNodeDetail } from '../api/types'
import { ClipMediaPanel } from '../components/ClipMediaPanel'
import type { ClipTimelineState } from '../components/ClipTimelinePanel'
import { MomentDetailPanel } from '../components/MomentDetailPanel'
import { RunSelector } from '../components/RunSelector'
import { SimilarDrawer } from '../components/SimilarDrawer'
import { BackLink, ContentCard, PageStack } from '../components/ui'
import { clipDisplayName } from '../utils/clipDisplay'
import { resolveSceneDescriptionText } from '../utils/labelDisplay'

export function ClipExplorerPage() {
  const { clipId: rawId } = useParams()
  const clipId = rawId ? decodeURIComponent(rawId) : ''
  const [searchParams] = useSearchParams()

  const [clip, setClip] = useState<ClipOverview | null>(null)
  const [runs, setRuns] = useState<ClipRun[]>([])
  const [runId, setRunId] = useState(searchParams.get('run_id') ?? '')
  const [loading, setLoading] = useState(true)
  const [timelineState, setTimelineState] = useState<ClipTimelineState | null>(null)
  const [similarCompositeId, setSimilarCompositeId] = useState<string | null>(null)
  const [taxonomyNodes, setTaxonomyNodes] = useState<TaxonomyNodeDetail[]>([])
  const [clipLabelMeta, setClipLabelMeta] = useState<ClipLabelView | null>(null)

  const initialTimestampNs = useMemo(() => {
    const tParam = searchParams.get('t')
    if (tParam == null || tParam.trim() === '') return undefined
    const parsed = Number(tParam)
    return Number.isFinite(parsed) ? parsed : undefined
  }, [searchParams])

  useEffect(() => {
    if (!clipId) return
    setLoading(true)
    const initialRun = searchParams.get('run_id') ?? undefined
    api
      .getExplorerBootstrap(clipId, initialRun)
      .then(({ clip: c, runs: r }) => {
        setClip(c)
        setRuns(r)
        setRunId(initialRun ?? c.active_run_id)
      })
      .finally(() => setLoading(false))
  }, [clipId, searchParams])

  useEffect(() => {
    if (!clipId || !runId) {
      setClipLabelMeta(null)
      return
    }
    void api
      .getTimelineMeta(clipId, runId)
      .then((meta) => setClipLabelMeta(meta.clip_label ?? null))
      .catch(() => setClipLabelMeta(null))
  }, [clipId, runId])

  useEffect(() => {
    void api
      .listTaxonomyVersions()
      .then((versions) => {
        const published = versions.find((v) => v.status === 'published')
        if (!published) {
          setTaxonomyNodes([])
          return
        }
        return api.getTaxonomyTree(published.id).then((tree) => setTaxonomyNodes(tree.nodes))
      })
      .catch(() => setTaxonomyNodes([]))
  }, [])

  const sceneDescription = useMemo(() => {
    const clipLabel = timelineState?.meta.clip_label ?? clipLabelMeta
    if (!clipLabel?.clip_label_ready) return null
    return resolveSceneDescriptionText(clipLabel.labels_json, {
      taxonomyNodes,
      sceneSummary: clipLabel.scene_summary,
    })
  }, [timelineState?.meta.clip_label, clipLabelMeta, taxonomyNodes])

  const handleTimelineStateChange = useCallback((state: ClipTimelineState) => {
    setTimelineState(state)
  }, [])

  if (loading || !clip || !runId) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <PageStack className="clip-explorer">
      <ContentCard noPadding>
        <div className="clip-explorer__toolbar" style={{ padding: '12px 16px' }}>
          <Space>
            <BackLink fallback="/" />
            <div>
              <Typography.Title level={4} style={{ margin: 0 }} className="mono">
                {clipDisplayName(clip)}
              </Typography.Title>
              {sceneDescription ? (
                <Typography.Text type="secondary" style={{ fontSize: 13, display: 'block', marginTop: 4 }}>
                  {sceneDescription}
                </Typography.Text>
              ) : null}
            </div>
          </Space>
          <Space wrap align="center">
            <RunSelector runs={runs} value={runId} onChange={setRunId} />
            <Tag color="blue">{clip.clip_label_ready ? 'Clip 已打标' : 'Clip 未打标'}</Tag>
            {timelineState?.meta.sample_sync_mode === 'clip' ? <Tag color="purple">Clip 级</Tag> : null}
            <Tag icon={<AudioOutlined />}>ASR {clip.asr_segment_count}</Tag>
            <Tag>{clip.duration_sec.toFixed(1)}s</Tag>
          </Space>
        </div>
      </ContentCard>

      <ClipMediaPanel
        clipId={clipId}
        runId={runId}
        initialTimestampNs={initialTimestampNs}
        title={clipDisplayName(clip)}
        showMetaBelow={false}
        testId="clip-explorer-media"
        onTimelineStateChange={handleTimelineStateChange}
      />

      {timelineState ? (
        <MomentDetailPanel
          clip={timelineState.clip}
          runId={runId}
          cursorNs={timelineState.cursorNs}
          clipLabel={timelineState.meta.clip_label}
          sceneDescription={sceneDescription}
          asrSegments={timelineState.meta.asr_segments}
          events={timelineState.meta.events}
        />
      ) : (
        <ContentCard title="Clip 详情">
          <Spin />
        </ContentCard>
      )}

      <SimilarDrawer
        open={!!similarCompositeId}
        compositeId={similarCompositeId}
        onClose={() => setSimilarCompositeId(null)}
      />
    </PageStack>
  )
}
