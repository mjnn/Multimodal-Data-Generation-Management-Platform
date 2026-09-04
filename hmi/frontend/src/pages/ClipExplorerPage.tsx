import { AudioOutlined, SoundOutlined } from '@ant-design/icons'
import { Space, Spin, Tag, Typography } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type { AudioNvhBootstrap, ClipLabelView, ClipOverview, ClipRun, TaxonomyNodeDetail } from '../api/types'
import { ClipMediaPanel } from '../components/ClipMediaPanel'
import type { ClipTimelineState } from '../components/ClipTimelinePanel'
import { MomentDetailPanel } from '../components/MomentDetailPanel'
import { ClipLabelTreeView } from '../components/ClipLabelTreeView'
import { RunSelector } from '../components/RunSelector'
import { SimilarDrawer } from '../components/SimilarDrawer'
import { BackLink, ContentCard, PageStack } from '../components/ui'
import { useDataTypeRecipe } from '../context/DataTypeWorkspaceContext'
import { clipDisplayName } from '../utils/clipDisplay'
import { resolveSceneDescriptionText } from '../utils/labelDisplay'
import { resolveDetailCards } from '../utils/overviewLayout'

export function ClipExplorerPage() {
  const { clipId: rawId } = useParams()
  const clipId = rawId ? decodeURIComponent(rawId) : ''
  const [searchParams] = useSearchParams()

  const [clip, setClip] = useState<ClipOverview | null>(null)
  const [runs, setRuns] = useState<ClipRun[]>([])
  const [runId, setRunId] = useState(searchParams.get('run_id') ?? '')
  const [loading, setLoading] = useState(true)
  const [timelineState, setTimelineState] = useState<ClipTimelineState | null>(null)
  const [mediaMode, setMediaMode] = useState<'cabin' | 'audio_nvh' | null>(null)
  const recipe = useDataTypeRecipe()
  const detailIds = resolveDetailCards(recipe).map((c) => c.widget_id)
  const layoutNvh = detailIds.includes('nvh_spectrum')
  const layoutCabin = detailIds.includes('cabin_multicam') || detailIds.includes('frame_gallery_bbox')
  const layoutJson = detailIds.includes('json_tree')
  const layoutLabelsTree = detailIds.includes('labels_tree')
  const layoutAsr = detailIds.includes('asr_panel')
  const isAudioNvh = layoutNvh || (!detailIds.length && mediaMode === 'audio_nvh')
  const [similarCompositeId, setSimilarCompositeId] = useState<string | null>(null)
  const [taxonomyNodes, setTaxonomyNodes] = useState<TaxonomyNodeDetail[]>([])
  const [clipLabelMeta, setClipLabelMeta] = useState<ClipLabelView | null>(null)
  const [audioNvhBootstrap, setAudioNvhBootstrap] = useState<AudioNvhBootstrap | null>(null)
  const [selectedBoxKey, setSelectedBoxKey] = useState<string | null>(null)
  const [bboxRefreshToken, setBboxRefreshToken] = useState(0)

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
      setAudioNvhBootstrap(null)
      return
    }
    void api
      .getTimelineMeta(clipId, runId)
      .then((meta) => setClipLabelMeta(meta.clip_label ?? null))
      .catch(() => setClipLabelMeta(null))
  }, [clipId, runId])

  // NVH fallback: when timeline meta doesn't provide labels_json yet,
  // load bootstrap (nvh_labels.json) for the label tree.
  useEffect(() => {
    if (!clipId || !runId) return
    if (!isAudioNvh) return
    const timelineReady = Boolean(clipLabelMeta?.clip_label_ready)
    const timelineHasLabels = Boolean(clipLabelMeta?.labels_json && Object.keys(clipLabelMeta.labels_json).length > 0)
    if (timelineReady && timelineHasLabels) return
    void api
      .getAudioNvhBootstrap(clipId, runId)
      .then((boot) => setAudioNvhBootstrap(boot))
      .catch(() => setAudioNvhBootstrap(null))
  }, [clipId, runId, isAudioNvh, clipLabelMeta?.clip_label_ready, clipLabelMeta?.labels_json])

  useEffect(() => {
    const versionId = clipLabelMeta?.taxonomy_version_id
    if (versionId) {
      void api
        .getTaxonomyTree(versionId)
        .then((tree) => setTaxonomyNodes(tree.nodes))
        .catch(() => setTaxonomyNodes([]))
      return
    }
    // Default fallback should avoid accidentally picking OMS published taxonomy.
    if (isAudioNvh) {
      const targetVersionCode = clipLabelMeta?.taxonomy_version_code ?? 'audio_nvh-v2'
      void api
        .listTaxonomyVersions()
        .then((versions) => {
          const target = versions.find((v) => v.version_code === targetVersionCode)
          if (!target) {
            setTaxonomyNodes([])
            return
          }
          return api.getTaxonomyTree(target.id).then((tree) => setTaxonomyNodes(tree.nodes))
        })
        .catch(() => setTaxonomyNodes([]))
      return
    }

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
  }, [clipLabelMeta?.taxonomy_version_id, clipLabelMeta?.taxonomy_version_code, isAudioNvh])

  const sceneDescription = useMemo(() => {
    const clipLabel = timelineState?.meta.clip_label ?? clipLabelMeta
    if (!clipLabel?.clip_label_ready) return null
    return resolveSceneDescriptionText(clipLabel.labels_json, {
      taxonomyNodes,
      sceneSummary: clipLabel.scene_summary,
    })
  }, [timelineState?.meta.clip_label, clipLabelMeta, taxonomyNodes])

  const nvhLabelsJsonForTree = useMemo(() => {
    return (clipLabelMeta?.labels_json ?? audioNvhBootstrap?.labels ?? {}) as Record<string, unknown>
  }, [clipLabelMeta?.labels_json, audioNvhBootstrap?.labels])

  useEffect(() => {
    setSelectedBoxKey(null)
  }, [clipId, runId])

  const handleTimelineStateChange = useCallback((state: ClipTimelineState) => {
    setTimelineState(state)
  }, [])

  const handleMediaModeChange = useCallback((mode: 'cabin' | 'audio_nvh') => {
    setMediaMode(mode)
    if (mode === 'audio_nvh') setTimelineState(null)
  }, [])

  useEffect(() => {
    setMediaMode(null)
    setTimelineState(null)
  }, [clipId, runId])

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
            {isAudioNvh ? (
              <Tag icon={<SoundOutlined />} color="cyan">
                NVH 频谱时间轴
              </Tag>
            ) : (
              <Tag icon={<AudioOutlined />}>ASR {clip.asr_segment_count}</Tag>
            )}
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
        onMediaModeChange={handleMediaModeChange}
        selectedBoxKey={selectedBoxKey}
        onSelectedBoxChange={setSelectedBoxKey}
        onOverlaySaved={() => setBboxRefreshToken((n) => n + 1)}
        detailWidgetIds={detailIds}
      />

      {layoutLabelsTree ? (
        <ContentCard title="标签树">
          <pre data-testid="overview-runtime-labels_tree" style={{ maxHeight: 360, overflow: 'auto', fontSize: 12 }}>
            {JSON.stringify(nvhLabelsJsonForTree, null, 2)}
          </pre>
        </ContentCard>
      ) : null}

      {layoutJson ? (
        <ContentCard title="JSON 结构">
          <pre data-testid="overview-runtime-json_tree" style={{ maxHeight: 360, overflow: 'auto', fontSize: 12 }}>
            {JSON.stringify(nvhLabelsJsonForTree, null, 2)}
          </pre>
        </ContentCard>
      ) : null}

      {isAudioNvh && !layoutCabin ? (
        <ContentCard title="Clip 详情">
          <div data-testid="clip-explorer-nvh-detail">
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              纯音频 NVH：按标签树分组展示（客观只读；语义待校核）。
            </Typography.Paragraph>
            <div style={{ marginTop: 12 }}>
              <div data-testid="audio-nvh-label-tree">
                <ClipLabelTreeView taxonomyNodes={taxonomyNodes} labelsJson={nvhLabelsJsonForTree} />
              </div>
            </div>
          </div>
        </ContentCard>
      ) : layoutAsr || layoutCabin || !detailIds.length ? (
        timelineState ? (
          <MomentDetailPanel
            clip={timelineState.clip}
            runId={runId}
            cursorNs={timelineState.cursorNs}
            clipLabel={timelineState.meta.clip_label}
            sceneDescription={sceneDescription}
            asrSegments={timelineState.meta.asr_segments}
            events={timelineState.meta.events}
            selectedBoxKey={selectedBoxKey}
            onSelectBox={setSelectedBoxKey}
            bboxRefreshToken={bboxRefreshToken}
          />
        ) : (
          <ContentCard title="Clip 详情">
            <Spin />
          </ContentCard>
        )
      ) : null}

      <SimilarDrawer
        open={!!similarCompositeId}
        compositeId={similarCompositeId}
        onClose={() => setSimilarCompositeId(null)}
      />
    </PageStack>
  )
}
