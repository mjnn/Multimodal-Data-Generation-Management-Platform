import { AudioOutlined, SoundOutlined } from '@ant-design/icons'
import { Space, Spin, Tag, Typography } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type {
  AudioNvhBootstrap,
  ClipLabelReview,
  ClipLabelView,
  ClipOverview,
  ClipRun,
  DataTypeRecipe,
  TaxonomyNodeDetail,
} from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { canAccessReview } from '../auth/roles'
import { ClipMediaPanel } from '../components/ClipMediaPanel'
import type { ClipTimelineState } from '../components/ClipTimelinePanel'
import { MomentDetailPanel } from '../components/MomentDetailPanel'
import { ClipLabelTreeView } from '../components/ClipLabelTreeView'
import { RunSelector } from '../components/RunSelector'
import { SimilarDrawer } from '../components/SimilarDrawer'
import { BackLink, ContentCard, PageStack } from '../components/ui'
import { clipDisplayName } from '../utils/clipDisplay'
import { resolveSceneDescriptionText } from '../utils/labelDisplay'
import { resolveDetailCards } from '../utils/overviewLayout'
import { recipeUsesNvhTaxonomy } from '../utils/recipeTaxonomy'
import { pickBoundTaxonomyVersion } from '../utils/boundTaxonomy'

export function ClipExplorerPage() {
  const { clipId: rawId } = useParams()
  const clipId = rawId ? decodeURIComponent(rawId) : ''
  const [searchParams, setSearchParams] = useSearchParams()
  const { user } = useAuth()
  const canQuickReview = canAccessReview(user?.roles)

  const [clip, setClip] = useState<ClipOverview | null>(null)
  const [runs, setRuns] = useState<ClipRun[]>([])
  const [runId, setRunId] = useState(searchParams.get('run_id') ?? '')
  const [loading, setLoading] = useState(true)
  const [timelineState, setTimelineState] = useState<ClipTimelineState | null>(null)
  const [mediaMode, setMediaMode] = useState<'cabin' | 'audio_nvh' | null>(null)
  const [boundRecipe, setBoundRecipe] = useState<DataTypeRecipe | null>(null)
  const recipe = boundRecipe
  const queryRunId = (searchParams.get('run_id') || '').trim()
  const urlDataTypeId = (searchParams.get('data_type_id') || '').trim()
  const clipDataTypeId = String(clip?.data_type_id || '').trim()
  const boundDataTypeId = clip ? clipDataTypeId || urlDataTypeId : urlDataTypeId
  const detailCards = resolveDetailCards(recipe)
  const mediaWidgetIds = new Set(['spectrum_timeline', 'video_timeline', 'frame_gallery_bbox'])
  const mediaCards = detailCards.filter((c) => mediaWidgetIds.has(c.widget_id))
  const hasSpectrum = detailCards.some((c) => c.widget_id === 'spectrum_timeline')
  const usesNvhTaxonomy = recipeUsesNvhTaxonomy(recipe)
  const showSpectrumTag = hasSpectrum || (!detailCards.length && mediaMode === 'audio_nvh')
  const [syncCursors, setSyncCursors] = useState<Record<string, number>>({})
  const [similarCompositeId, setSimilarCompositeId] = useState<string | null>(null)
  const [taxonomyNodes, setTaxonomyNodes] = useState<TaxonomyNodeDetail[]>([])
  const [clipLabelMeta, setClipLabelMeta] = useState<ClipLabelView | null>(null)
  const [audioNvhBootstrap, setAudioNvhBootstrap] = useState<AudioNvhBootstrap | null>(null)
  const [selectedBoxKey, setSelectedBoxKey] = useState<string | null>(null)
  const [bboxRefreshToken, setBboxRefreshToken] = useState(0)
  const [review, setReview] = useState<ClipLabelReview | null>(null)

  const initialTimestampNs = useMemo(() => {
    const tParam = searchParams.get('t')
    if (tParam == null || tParam.trim() === '') return undefined
    const parsed = Number(tParam)
    return Number.isFinite(parsed) ? parsed : undefined
  }, [searchParams])

  useEffect(() => {
    if (!clipId) return
    setLoading(true)
    const initialRun = queryRunId || undefined
    api
      .getExplorerBootstrap(clipId, initialRun)
      .then(({ clip: c, runs: r }) => {
        setClip(c)
        setRuns(r)
        setRunId(initialRun ?? c.active_run_id)
      })
      .finally(() => setLoading(false))
  }, [clipId, queryRunId])

  useEffect(() => {
    if (!boundDataTypeId) {
      setBoundRecipe(null)
      return
    }
    let cancelled = false
    void api
      .getDataType(boundDataTypeId)
      .then((rec) => {
        if (!cancelled) setBoundRecipe(rec)
      })
      .catch(() => {
        if (!cancelled) setBoundRecipe(null)
      })
    return () => {
      cancelled = true
    }
  }, [boundDataTypeId])

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
  // load bootstrap (nvh_labels.json) for the label tree — only NVH taxonomy recipes.
  useEffect(() => {
    if (!clipId || !runId) return
    if (!usesNvhTaxonomy) {
      setAudioNvhBootstrap(null)
      return
    }
    const timelineReady = Boolean(clipLabelMeta?.clip_label_ready)
    const timelineHasLabels = Boolean(clipLabelMeta?.labels_json && Object.keys(clipLabelMeta.labels_json).length > 0)
    if (timelineReady && timelineHasLabels) return
    void api
      .getAudioNvhBootstrap(clipId, runId)
      .then((boot) => setAudioNvhBootstrap(boot))
      .catch(() => setAudioNvhBootstrap(null))
  }, [clipId, runId, usesNvhTaxonomy, clipLabelMeta?.clip_label_ready, clipLabelMeta?.labels_json])

  useEffect(() => {
    const factVersionId = clipLabelMeta?.taxonomy_version_id
    if (usesNvhTaxonomy && factVersionId) {
      void api
        .getTaxonomyTree(factVersionId)
        .then((tree) => setTaxonomyNodes(tree.nodes))
        .catch(() => setTaxonomyNodes([]))
      return
    }
    const targetVersionCode = usesNvhTaxonomy
      ? (clipLabelMeta?.taxonomy_version_code ?? 'audio_nvh-v2')
      : (recipe?.taxonomy_version_code || clipLabelMeta?.taxonomy_version_code || '')
    const taxonomyId = String(recipe?.taxonomy_id || '').trim()
    if (targetVersionCode || taxonomyId) {
      void api
        .listTaxonomyVersions()
        .then((versions) => {
          const target = pickBoundTaxonomyVersion(versions, {
            versionCode: targetVersionCode,
            taxonomyId,
          })
          if (!target) {
            if (factVersionId) {
              return api.getTaxonomyTree(factVersionId).then((tree) => setTaxonomyNodes(tree.nodes))
            }
            setTaxonomyNodes([])
            return
          }
          return api.getTaxonomyTree(target.id).then((tree) => setTaxonomyNodes(tree.nodes))
        })
        .catch(() => setTaxonomyNodes([]))
      return
    }
    if (factVersionId) {
      void api
        .getTaxonomyTree(factVersionId)
        .then((tree) => setTaxonomyNodes(tree.nodes))
        .catch(() => setTaxonomyNodes([]))
      return
    }
    setTaxonomyNodes([])
  }, [
    clipLabelMeta?.taxonomy_version_id,
    clipLabelMeta?.taxonomy_version_code,
    usesNvhTaxonomy,
    recipe?.taxonomy_version_code,
    recipe?.taxonomy_id,
    recipe,
  ])

  useEffect(() => {
    if (!clipId || !runId || !canQuickReview) {
      setReview(null)
      return
    }
    void api
      .getReviewDetail(clipId, runId)
      .then(setReview)
      .catch(() => setReview(null))
  }, [clipId, runId, canQuickReview])

  const handleNvhReviewSaved = useCallback(
    (updated: ClipLabelReview) => {
      setReview(updated)
      if (!clipId || !runId) return
      void api
        .getTimelineMeta(clipId, runId)
        .then((meta) => setClipLabelMeta(meta.clip_label ?? null))
        .catch(() => setClipLabelMeta(null))
      if (recipeUsesNvhTaxonomy(boundRecipe)) {
        void api
          .getAudioNvhBootstrap(clipId, runId)
          .then((boot) => setAudioNvhBootstrap(boot))
          .catch(() => setAudioNvhBootstrap(null))
      }
    },
    [clipId, runId, boundRecipe],
  )

  const sceneDescription = useMemo(() => {
    const clipLabel = timelineState?.meta.clip_label ?? clipLabelMeta
    if (!clipLabel?.clip_label_ready) return null
    return resolveSceneDescriptionText(clipLabel.labels_json, {
      taxonomyNodes,
      sceneSummary: clipLabel.scene_summary,
    })
  }, [timelineState?.meta.clip_label, clipLabelMeta, taxonomyNodes])

  const nvhLabelsJsonForTree = useMemo(() => {
    const fromFacts = (
      usesNvhTaxonomy
        ? (clipLabelMeta?.labels_json ?? audioNvhBootstrap?.labels ?? {})
        : (clipLabelMeta?.labels_json ?? {})
    ) as Record<string, unknown>
    const fromReview = review?.labels_json
    if (!fromReview || typeof fromReview !== 'object') return fromFacts
    const merged = { ...fromFacts }
    for (const [key, val] of Object.entries(fromReview)) {
      if (usesNvhTaxonomy) {
        if (key.startsWith('nvh.sem.')) merged[key] = val
      } else {
        merged[key] = val
      }
    }
    return merged
  }, [clipLabelMeta?.labels_json, audioNvhBootstrap?.labels, review?.labels_json, usesNvhTaxonomy])

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
            <RunSelector
              runs={runs}
              value={runId}
              onChange={(id) => {
                setSearchParams(
                  (prev) => {
                    const next = new URLSearchParams(prev)
                    next.set('run_id', id)
                    return next
                  },
                  { replace: true },
                )
              }}
            />
            <Tag color="blue">{clip.clip_label_ready ? 'Clip 已打标' : 'Clip 未打标'}</Tag>
            {timelineState?.meta.sample_sync_mode === 'clip' ? <Tag color="purple">Clip 级</Tag> : null}
            {showSpectrumTag ? (
              <Tag icon={<SoundOutlined />} color="cyan">
                频谱时间轴
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
        detailCards={mediaCards}
        syncCursors={syncCursors}
        onSyncSeek={(group, t) => setSyncCursors((prev) => ({ ...prev, [group]: t }))}
      />

      {detailCards
        .filter((c) => !mediaWidgetIds.has(c.widget_id))
        .map((card) => {
          if (card.widget_id === 'labels_tree') {
            return (
              <ContentCard key={card.key} title="标签树">
                <div data-testid="overview-runtime-labels_tree">
                  <div data-testid="clip-bound-label-tree">
                    <ClipLabelTreeView
                      taxonomyNodes={taxonomyNodes}
                      labelsJson={nvhLabelsJsonForTree}
                      fieldReviewedLabelIds={review?.field_reviewed_label_ids ?? []}
                      canQuickReview={canQuickReview}
                      clipId={clipId}
                      runId={runId}
                      onReviewSaved={handleNvhReviewSaved}
                    />
                  </div>
                </div>
              </ContentCard>
            )
          }
          if (card.widget_id === 'json_tree') {
            return (
              <ContentCard key={card.key} title="JSON 结构">
                <pre data-testid="overview-runtime-json_tree" style={{ maxHeight: 360, overflow: 'auto', fontSize: 12 }}>
                  {JSON.stringify(nvhLabelsJsonForTree, null, 2)}
                </pre>
              </ContentCard>
            )
          }
          if (card.widget_id === 'asr_panel') {
            return timelineState ? (
              <MomentDetailPanel
                key={card.key}
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
              <ContentCard key={card.key} title="ASR 文本">
                <Spin />
              </ContentCard>
            )
          }
          return null
        })}

      {!detailCards.length && timelineState ? (
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
      ) : null}

      <SimilarDrawer
        open={!!similarCompositeId}
        compositeId={similarCompositeId}
        onClose={() => setSimilarCompositeId(null)}
      />
    </PageStack>
  )
}
