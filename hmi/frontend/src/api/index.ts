import { formatDateTime, formatTimestampNs } from '../utils/format'
import { fetchJson, http } from './http'
import type { AuthUser } from '../auth/types'
import type {
  AudioSegment,
  ClipOverview,
  ClipRun,
  EventLabel,
  LabelTaxonomyNode,
  Paginated,
  SampledFrame,
  SimilarItem,
  TaxonomyNodeInput,
  TaxonomyTreeResponse,
  TaxonomyVersion,
  ClipLabelReview,
  ReviewQueueResponse,
  ReviewStatus,
  ReviewCandidatesResponse,
  ReviewTaskScope,
  ReviewV2LabelOption,
  ReviewV2Mode,
  ReviewV2SessionSnapshot,
  ReviewV2Stats,
  ReviewV2SubmitResult,
  ReviewV2Task,
  ReviewV2Action,
  ReviewV2StagedReview,
  ReviewAssignmentBatch,
  ReviewAssignmentItem,
  ReviewAssignmentReviewer,
  ReviewWorkbenchSession,
  DatasetPreviewResponse,
  DatasetSnapshot,
  DatasetListResponse,
  DatasetDownloadResponse,
  DatasetFilterJson,
  SystemEnvVariable,
  PipelineRunSettings,
  PipelineExecutionListResponse,
  RegisterResponse,
  PipelineSettingsResponse,
  TimelineMeta,
  TimelineSnapshot,
  UploadTask,
  OssBagPipeline,
  OssInfo,
  OssShortcut,
  OssShortcutsResponse,
  OssListResponse,
  OssFilePreview,
  OssSyncPollerStatus,
} from './types'

/** Query `mode` for review v2 APIs (legacy servers only accept `ai_dispute` for open queue). */
function reviewV2ModeQuery(mode: ReviewV2Mode): string {
  return mode === 'confidence' ? 'ai_dispute' : mode
}

function reviewV2SearchParams(opts: {
  mode: ReviewV2Mode
  labelId?: string
  value?: string
  dtype?: string
}): URLSearchParams {
  const params = new URLSearchParams({ mode: reviewV2ModeQuery(opts.mode) })
  if (opts.labelId) params.set('label_id', opts.labelId)
  if (opts.value != null && opts.value !== '') params.set('value', opts.value)
  if (opts.dtype) params.set('dtype', opts.dtype)
  return params
}

export type DataSourceMode = 'cloud' | 'local'

export type HealthResponse = {
  ok: boolean
  project?: string
  data_source?: DataSourceMode
  local_db?: boolean
  local_runtime_root?: string
  last_sync_clip?: string | null
  error?: string
}

export const api = {
  health: () => fetchJson<HealthResponse>('/health'),

  updateMe: (body: { display_name: string }): Promise<{ user: AuthUser }> =>
    fetchJson('/auth/me', { method: 'PATCH', body: JSON.stringify(body) }),

  changePassword: (current_password: string, new_password: string): Promise<{ ok: boolean }> =>
    fetchJson('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),

  deleteMyAccount: (password: string): Promise<{ ok: boolean }> =>
    fetchJson('/auth/me', {
      method: 'DELETE',
      body: JSON.stringify({ password }),
    }),

  getDataSource: (): Promise<{ data_source: DataSourceMode }> =>
    fetchJson('/config/data-source'),

  setDataSource: (mode: DataSourceMode): Promise<{ data_source: DataSourceMode }> =>
    fetchJson('/config/data-source', {
      method: 'POST',
      body: JSON.stringify({ data_source: mode }),
    }),

  getClips: (opts?: { light?: boolean; refresh?: boolean }): Promise<ClipOverview[]> => {
    const params = new URLSearchParams()
    if (opts?.light) params.set('light', '1')
    if (opts?.refresh) params.set('refresh', '1')
    const q = params.toString()
    return fetchJson(`/clips${q ? `?${q}` : ''}`)
  },

  getDemoClips: (): Promise<ClipOverview[]> => fetchJson('/clips/demo'),

  resetHmiArtifacts: (): Promise<{
    ok: boolean
    message?: string
    baseline_taxonomy?: { version_code: string; node_count: number }
  }> => fetchJson('/hmi/reset-artifacts', { method: 'POST' }),

  getBatchClipStats: (opts?: { refresh?: boolean }): Promise<
    Record<
      string,
      Pick<
        ClipOverview,
        | 'labeled_count'
        | 'asr_segment_count'
        | 'event_count'
        | 'label_granularity'
        | 'clip_label_ready'
        | 'clip_label_preview'
      >
    >
  > => {
    const q = opts?.refresh ? '?refresh=1' : ''
    return fetchJson(`/clips/batch-stats${q}`)
  },

  getClipStats: (
    clipId: string,
    runId?: string,
  ): Promise<
    Pick<
      ClipOverview,
      | 'labeled_count'
      | 'asr_segment_count'
      | 'event_count'
      | 'label_granularity'
      | 'clip_label_ready'
      | 'clip_label_preview'
    >
  > =>
    fetchJson(
      `/clips/${encodeURIComponent(clipId)}/stats` +
        (runId ? `?run_id=${encodeURIComponent(runId)}` : ''),
    ),

  getClip: (clipId: string, runId?: string): Promise<ClipOverview | null> =>
    fetchJson(
      `/clips/${encodeURIComponent(clipId)}` +
        (runId ? `?run_id=${encodeURIComponent(runId)}` : ''),
    ),

  getClipRuns: (clipId: string): Promise<ClipRun[]> =>
    fetchJson(`/clips/${encodeURIComponent(clipId)}/runs`),

  getExplorerBootstrap: (
    clipId: string,
    runId?: string,
  ): Promise<{ clip: ClipOverview; runs: ClipRun[]; meta: TimelineMeta }> =>
    fetchJson(
      `/clips/${encodeURIComponent(clipId)}/explorer-bootstrap` +
        (runId ? `?run_id=${encodeURIComponent(runId)}` : ''),
    ),

  getTimelineMeta: (clipId: string, runId?: string): Promise<TimelineMeta> =>
    fetchJson(
      `/clips/${encodeURIComponent(clipId)}/timeline-meta` +
        (runId ? `?run_id=${encodeURIComponent(runId)}` : ''),
    ),

  getFrames: (
    clipId: string,
    opts?: { sampled_only?: boolean; camera?: string; page?: number; page_size?: number },
  ): Promise<Paginated<SampledFrame>> =>
    fetchJson(
      `/clips/${encodeURIComponent(clipId)}/frames?` +
        new URLSearchParams({
          ...(opts?.sampled_only ? { sampled_only: '1' } : {}),
          ...(opts?.camera ? { camera: opts.camera } : {}),
          page: String(opts?.page ?? 1),
          page_size: String(opts?.page_size ?? 24),
        }),
    ),

  getTimelineAt: (
    clipId: string,
    timestamp_ns: number,
    window_ms = 200,
    runId?: string,
  ): Promise<TimelineSnapshot> =>
    fetchJson(
      `/clips/${encodeURIComponent(clipId)}/timeline?` +
        new URLSearchParams({
          timestamp_ns: String(timestamp_ns),
          window_ms: String(window_ms),
          ...(runId ? { run_id: runId } : {}),
        }),
    ),

  getLabelTaxonomy: (): Promise<LabelTaxonomyNode[]> => fetchJson('/label-taxonomy'),

  findSimilar: (compositeId: string, topK = 8): Promise<SimilarItem[]> =>
    fetchJson(`/similar?` + new URLSearchParams({ id: compositeId, top_k: String(topK) })),

  getLabelSuggestions: (): Promise<string[]> => fetchJson('/label-suggestions'),

  getAudioSegments: (clipId: string): Promise<AudioSegment[]> =>
    fetchJson(`/clips/${encodeURIComponent(clipId)}/audio-segments`),

  getEvents: (clipId: string): Promise<EventLabel[]> =>
    fetchJson(`/clips/${encodeURIComponent(clipId)}/events`),

  uploadRosbag: async (file: File): Promise<UploadTask> => {
    const form = new FormData()
    form.append('file', file)
    const res = await http.post<UploadTask>('/upload/rosbag', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return res.data
  },

  getUploadTasks: (): Promise<UploadTask[]> => fetchJson('/upload/tasks'),

  getOssInfo: (): Promise<OssInfo> => fetchJson('/oss/info'),

  getOssShortcuts: (): Promise<OssShortcutsResponse> => fetchJson('/oss/shortcuts'),

  saveOssShortcuts: (items: OssShortcut[]): Promise<OssShortcutsResponse> =>
    fetchJson('/oss/shortcuts', { method: 'PUT', body: JSON.stringify({ items }) }),

  getSyncPollerStatus: (): Promise<OssSyncPollerStatus> => fetchJson('/sync/poller'),

  setSyncPollerEnabled: (enabled: boolean): Promise<OssSyncPollerStatus> =>
    fetchJson('/sync/poller', {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),

  listOss: (prefix = ''): Promise<OssListResponse> =>
    fetchJson(`/oss/list?${new URLSearchParams({ prefix })}`),

  uploadOssFile: async (prefix: string, file: File): Promise<{ key: string; size: number }> => {
    const form = new FormData()
    form.append('file', file)
    const res = await http.post<{ key: string; size: number }>(
      `/oss/upload?${new URLSearchParams({ prefix })}`,
      form,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
    return res.data
  },

  deleteOssObject: (key: string): Promise<{ deleted: string[] }> =>
    fetchJson(`/oss/object?${new URLSearchParams({ key })}`, { method: 'DELETE' }),

  deleteOssPrefix: (prefix: string): Promise<{ deleted: string[]; count?: number }> =>
    fetchJson(`/oss/delete-prefix?${new URLSearchParams({ prefix })}`, { method: 'POST' }),

  mkdirOss: (prefix: string): Promise<{ key: string }> =>
    fetchJson(`/oss/mkdir?${new URLSearchParams({ prefix })}`, { method: 'POST' }),

  getOssDownloadUrl: (key: string): Promise<{ url: string }> =>
    fetchJson(`/oss/download-url?${new URLSearchParams({ key })}`),

  previewOssFile: (key: string): Promise<OssFilePreview> =>
    fetchJson(`/oss/preview?${new URLSearchParams({ key })}`),

  getOssBagPipeline: (key: string, refresh = false): Promise<OssBagPipeline> =>
    fetchJson(
      `/oss/bag-pipeline?${new URLSearchParams({ key, ...(refresh ? { refresh: '1' } : {}) })}`,
    ),

  formatTimestampNs,
  formatDateTime,

  listAdminUsers: (): Promise<AuthUser[]> => fetchJson('/admin/users'),

  listAuditLogs: (opts?: {
    action?: string
    resource_type?: string
    resource_id?: string
    actor_id?: string
    limit?: number
    offset?: number
  }): Promise<import('./types').AuditLogListResponse> =>
    fetchJson(
      `/admin/audit?${new URLSearchParams({
        ...(opts?.action ? { action: opts.action } : {}),
        ...(opts?.resource_type ? { resource_type: opts.resource_type } : {}),
        ...(opts?.resource_id ? { resource_id: opts.resource_id } : {}),
        ...(opts?.actor_id ? { actor_id: opts.actor_id } : {}),
        limit: String(opts?.limit ?? 50),
        offset: String(opts?.offset ?? 0),
      })}`,
    ),

  getSystemEnv: (): Promise<{
    path: string
    writable: boolean
    catalog_keys: string[]
    variables: SystemEnvVariable[]
    restart_required_hint?: string
  }> => fetchJson('/admin/system-env'),

  saveSystemEnv: (body: { env: Record<string, string | null> }): Promise<{
    path: string
    writable: boolean
    variables: SystemEnvVariable[]
    restart_required_hint?: string
  }> =>
    fetchJson('/admin/system-env', { method: 'PUT', body: JSON.stringify(body) }),

  createAdminUser: (body: {
    username: string
    password: string
    display_name?: string
    roles: string[]
  }): Promise<AuthUser> =>
    fetchJson('/admin/users', { method: 'POST', body: JSON.stringify(body) }),

  updateAdminUser: (
    userId: string,
    body: {
      display_name?: string
      is_active?: boolean
      roles?: string[]
      password?: string
    },
  ): Promise<AuthUser> =>
    fetchJson(`/admin/users/${encodeURIComponent(userId)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  deleteAdminUser: (userId: string): Promise<{ ok: boolean }> =>
    fetchJson(`/admin/users/${encodeURIComponent(userId)}`, { method: 'DELETE' }),

  listTaxonomyVersions: (): Promise<TaxonomyVersion[]> => fetchJson('/taxonomy/versions'),

  createTaxonomyVersion: (body: {
    version_code: string
    import_yaml?: boolean
  }): Promise<TaxonomyVersion> =>
    fetchJson('/taxonomy/versions', { method: 'POST', body: JSON.stringify(body) }),

  importTaxonomyYamlVersion: (body: {
    version_code: string
    yaml_content: string
  }): Promise<TaxonomyVersion> =>
    fetchJson('/taxonomy/versions/import-yaml', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  cloneTaxonomyVersion: (
    versionId: string,
    body: { version_code: string },
  ): Promise<TaxonomyVersion> =>
    fetchJson(`/taxonomy/versions/${encodeURIComponent(versionId)}/clone`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getTaxonomyTree: (versionId: string): Promise<TaxonomyTreeResponse> =>
    fetchJson(`/taxonomy/versions/${encodeURIComponent(versionId)}/tree`),

  replaceTaxonomyNodes: (
    versionId: string,
    nodes: TaxonomyNodeInput[],
  ): Promise<{ version: TaxonomyVersion; replaced: number }> =>
    fetchJson(`/taxonomy/versions/${encodeURIComponent(versionId)}/nodes`, {
      method: 'PUT',
      body: JSON.stringify({ nodes }),
    }),

  publishTaxonomyVersion: (versionId: string): Promise<TaxonomyVersion> =>
    fetchJson(`/taxonomy/versions/${encodeURIComponent(versionId)}/publish`, { method: 'POST' }),

  archiveTaxonomyVersion: (versionId: string): Promise<TaxonomyVersion> =>
    fetchJson(`/taxonomy/versions/${encodeURIComponent(versionId)}/archive`, { method: 'POST' }),

  getTaxonomyContext: (): Promise<import('./types').TaxonomyContext> =>
    fetchJson('/taxonomy/context'),

  getTaxonomyCoverage: (versionId: string): Promise<import('./types').TaxonomyCoverageResponse> =>
    fetchJson(`/taxonomy/versions/${encodeURIComponent(versionId)}/coverage`),

  getTaxonomyDiff: (versionId: string, against: string): Promise<import('./types').TaxonomyDiffResponse> =>
    fetchJson(
      `/taxonomy/versions/${encodeURIComponent(versionId)}/diff?against=${encodeURIComponent(against)}`,
    ),

  getTaxonomyImpact: (versionId: string): Promise<import('./types').TaxonomyImpactResponse> =>
    fetchJson(`/taxonomy/versions/${encodeURIComponent(versionId)}/impact`),

  getTaxonomyLineage: (versionId: string): Promise<import('./types').TaxonomyLineageResponse> =>
    fetchJson(`/taxonomy/versions/${encodeURIComponent(versionId)}/lineage`),

  listTaxonomyProposals: (opts?: { status?: string; limit?: number; offset?: number }): Promise<{
    items: import('./types').TaxonomyProposal[]
    total: number
  }> => {
    const q = new URLSearchParams()
    if (opts?.status) q.set('status', opts.status)
    if (opts?.limit != null) q.set('limit', String(opts.limit))
    if (opts?.offset != null) q.set('offset', String(opts.offset))
    const qs = q.toString()
    return fetchJson(`/taxonomy/proposals${qs ? `?${qs}` : ''}`)
  },

  createTaxonomyProposal: (body: {
    title: string
    base_version_id: string
    evidence: Record<string, unknown>
    nodes: import('./types').TaxonomyNodeInput[]
    /** Optional; omit/blank → server generates ``proposal-{hex}``. */
    version_code?: string | null
  }): Promise<import('./types').TaxonomyProposal> =>
    fetchJson('/taxonomy/proposals', { method: 'POST', body: JSON.stringify(body) }),

  patchTaxonomyProposal: (
    proposalId: string,
    body: { status: string; merged_version_id?: string | null },
  ): Promise<import('./types').TaxonomyProposal> =>
    fetchJson(`/taxonomy/proposals/${encodeURIComponent(proposalId)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  approveTaxonomyProposalDraft: (
    proposalId: string,
  ): Promise<{ proposal: import('./types').TaxonomyProposal; version: import('./types').TaxonomyVersion | null }> =>
    fetchJson(`/taxonomy/proposals/${encodeURIComponent(proposalId)}/approve-draft`, {
      method: 'POST',
    }),

  getTaxonomyNodeUsage: (
    labelId: string,
    versionId?: string,
  ): Promise<{
    label_id: string
    clip_with_label_count: number
    clip_samples: Array<{ clip_id: string; run_id: string; value: string }>
    dataset_reference_count: number
  }> =>
    fetchJson(
      `/taxonomy/nodes/${encodeURIComponent(labelId)}/usage${versionId ? `?version_id=${encodeURIComponent(versionId)}` : ''}`,
    ),

  getReviewQueue: (opts?: {
    status?: ReviewStatus
    labelFilters?: Record<string, string | boolean>
    limit?: number
    offset?: number
  }): Promise<ReviewQueueResponse> =>
    fetchJson(
      `/review/queue?${new URLSearchParams({
        ...(opts?.status ? { status: opts.status } : {}),
        ...(opts?.labelFilters && Object.keys(opts.labelFilters).length > 0
          ? { label_filters: JSON.stringify(opts.labelFilters) }
          : {}),
        limit: String(opts?.limit ?? 50),
        offset: String(opts?.offset ?? 0),
      })}`,
    ),

  getReviewCandidates: (opts: {
    labelFilters: Record<string, string | boolean>
    reviewScope?: ReviewTaskScope
    disputesOnly?: boolean
    limit?: number
    offset?: number
  }): Promise<ReviewCandidatesResponse> =>
    fetchJson(
      `/review/candidates?${new URLSearchParams({
        label_filters: JSON.stringify(opts.labelFilters),
        review_scope: opts.reviewScope ?? 'unreviewed',
        ...(opts.disputesOnly ? { disputes_only: '1' } : {}),
        limit: String(opts.limit ?? 50),
        offset: String(opts.offset ?? 0),
      })}`,
    ),

  ensureReview: (clipId: string, runId?: string): Promise<ClipLabelReview> =>
    fetchJson(`/review/clips/${encodeURIComponent(clipId)}/ensure`, {
      method: 'POST',
      body: JSON.stringify(runId ? { run_id: runId } : {}),
    }),

  getReviewDetail: (clipId: string, runId?: string): Promise<ClipLabelReview> =>
    fetchJson(
      `/review/clips/${encodeURIComponent(clipId)}` +
        (runId ? `?run_id=${encodeURIComponent(runId)}` : ''),
    ),

  saveReview: (
    clipId: string,
    body: {
      labels_json: Record<string, unknown>
      review_status: ReviewStatus
      updated_at: string
      run_id?: string
    },
  ): Promise<ClipLabelReview> =>
    fetchJson(`/review/clips/${encodeURIComponent(clipId)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  reopenReview: (clipId: string, body?: { run_id?: string }): Promise<ClipLabelReview> =>
    fetchJson(`/review/clips/${encodeURIComponent(clipId)}/reopen`, {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),

  getReviewV2Session: (opts: {
    mode: ReviewV2Mode
    labelId?: string
    value?: string
    dtype?: string
  }): Promise<{ session: ReviewV2SessionSnapshot; stats: ReviewV2Stats }> => {
    const params = reviewV2SearchParams(opts)
    return fetchJson(`/review/v2/session?${params}`)
  },

  getReviewV2Stats: (opts: {
    mode: ReviewV2Mode
    labelId?: string
    value?: string
    dtype?: string
  }): Promise<ReviewV2Stats> => {
    const params = reviewV2SearchParams(opts)
    return fetchJson(`/review/v2/tasks/stats?${params}`)
  },

  getReviewV2Next: (opts: {
    mode: ReviewV2Mode
    labelId?: string
    value?: string
    dtype?: string
    cursor?: string | null
  }): Promise<{ task: ReviewV2Task | null; session: ReviewV2SessionSnapshot }> => {
    const params = reviewV2SearchParams(opts)
    if (opts.cursor) params.set('cursor', opts.cursor)
    return fetchJson(`/review/v2/next?${params}`)
  },

  getReviewV2Prev: (opts: {
    mode: ReviewV2Mode
    labelId?: string
    value?: string
    dtype?: string
  }): Promise<{ task: ReviewV2Task | null; session: ReviewV2SessionSnapshot }> => {
    const params = reviewV2SearchParams(opts)
    return fetchJson(`/review/v2/prev?${params}`)
  },

  getReviewV2LabelOptions: (keyword?: string): Promise<{ items: ReviewV2LabelOption[]; total: number }> =>
    fetchJson(
      `/review/v2/label-options?${new URLSearchParams({
        keyword: keyword ?? '',
      })}`,
    ),

  getReviewV2Tasks: (opts: {
    mode: ReviewV2Mode
    labelId?: string
    value?: string
    dtype?: string
    limit?: number
    offset?: number
  }): Promise<{ items: ReviewV2Task[]; total: number; limit: number; offset: number }> => {
    const params = reviewV2SearchParams(opts)
    params.set('limit', String(opts.limit ?? 200))
    params.set('offset', String(opts.offset ?? 0))
    return fetchJson(`/review/v2/tasks?${params}`)
  },

  submitReviewV2: (body: {
    clip_id: string
    run_id: string
    label_id: string
    action: ReviewV2Action
    value?: unknown
    clip_updated_at?: string | null
    assignment_batch_id?: string | null
  }): Promise<ReviewV2SubmitResult> =>
    fetchJson('/review/v2/submit', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  listReviewAssignmentReviewers: (): Promise<ReviewAssignmentReviewer[]> =>
    fetchJson('/review/assignments/reviewers'),

  previewReviewAssignment: (body: {
    label_ids: string[]
    queue_limit: number
  }): Promise<{ count: number; items: ReviewV2Task[] }> =>
    fetchJson('/review/assignments/preview', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  createReviewAssignmentBatch: (body: {
    name: string
    label_ids: string[]
    queue_limit: number
    assignee_id?: string | null
  }): Promise<ReviewAssignmentBatch> =>
    fetchJson('/review/assignments/batches', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  listReviewAssignmentBatches: (): Promise<{ items: ReviewAssignmentBatch[]; total: number }> =>
    fetchJson('/review/assignments/batches'),

  getReviewAssignmentBatch: (batchId: string): Promise<ReviewAssignmentBatch> =>
    fetchJson(`/review/assignments/batches/${encodeURIComponent(batchId)}`),

  listReviewAssignmentBatchItems: (
    batchId: string,
  ): Promise<{ items: ReviewAssignmentItem[]; total: number }> =>
    fetchJson(`/review/assignments/batches/${encodeURIComponent(batchId)}/items`),

  closeReviewAssignmentBatch: (batchId: string): Promise<ReviewAssignmentBatch> =>
    fetchJson(`/review/assignments/batches/${encodeURIComponent(batchId)}/close`, {
      method: 'POST',
    }),

  listMyReviewAssignments: (opts?: {
    view?: 'active' | 'completed' | 'all'
  }): Promise<{ items: ReviewAssignmentBatch[]; total: number }> => {
    const params = new URLSearchParams()
    if (opts?.view) params.set('view', opts.view)
    const q = params.toString()
    return fetchJson(`/review/assignments/mine${q ? `?${q}` : ''}`)
  },

  claimReviewAssignment: (body: {
    batch_id: string
    limit?: number
  }): Promise<{ items: ReviewAssignmentItem[]; count: number }> =>
    fetchJson('/review/assignments/claim', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  claimLowConfidenceReviewBatch: (body: {
    limit: number
  }): Promise<ReviewAssignmentBatch> =>
    fetchJson('/review/assignments/claim-low-confidence', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  getReviewAssignmentWorkQueue: (
    batchId: string,
  ): Promise<{ batch: ReviewAssignmentBatch; items: ReviewV2Task[]; total: number }> =>
    fetchJson(`/review/assignments/batches/${encodeURIComponent(batchId)}/work-queue`),

  getReviewWorkbenchSession: (batchId: string): Promise<ReviewWorkbenchSession> =>
    fetchJson(`/review/assignments/batches/${encodeURIComponent(batchId)}/session`),

  saveReviewWorkbenchSession: (
    batchId: string,
    body: { staged: Record<string, ReviewV2StagedReview>; current_index: number },
  ): Promise<ReviewWorkbenchSession> =>
    fetchJson(`/review/assignments/batches/${encodeURIComponent(batchId)}/session`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  clearReviewWorkbenchSession: (batchId: string): Promise<{ ok: boolean }> =>
    fetchJson(`/review/assignments/batches/${encodeURIComponent(batchId)}/session`, {
      method: 'DELETE',
    }),

  listDatasets: (opts?: {
    status?: string
    limit?: number
    offset?: number
  }): Promise<DatasetListResponse> =>
    fetchJson(
      `/datasets?${new URLSearchParams({
        ...(opts?.status ? { status: opts.status } : {}),
        limit: String(opts?.limit ?? 50),
        offset: String(opts?.offset ?? 0),
      })}`,
    ),

  createDataset: (body: {
    name: string
    description?: string
    filter_json?: DatasetFilterJson
    export_preset?: 'minimal' | 'full'
    aug_recipe_id?: string
  }): Promise<DatasetSnapshot> =>
    fetchJson('/datasets', { method: 'POST', body: JSON.stringify(body) }),

  deriveDataset: (
    snapshotId: string,
    body: {
      name: string
      description?: string
      filter_json?: DatasetFilterJson
      taxonomy_crop_label_ids?: string[]
      aug_recipe_id?: string
    },
  ): Promise<DatasetSnapshot> =>
    fetchJson(`/datasets/${encodeURIComponent(snapshotId)}/derive`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  previewDataset: (body: {
    name?: string
    filter_json?: DatasetFilterJson
    export_preset?: 'minimal' | 'full'
  }): Promise<DatasetPreviewResponse> =>
    fetchJson('/datasets/preview', { method: 'POST', body: JSON.stringify(body) }),

  listAugRecipes: (opts?: { status?: string }): Promise<{ items: import('./types').AugRecipe[] }> =>
    fetchJson(
      `/datasets/aug-recipes${opts?.status ? `?status=${encodeURIComponent(opts.status)}` : ''}`,
    ),

  getDataset: (snapshotId: string): Promise<DatasetSnapshot> =>
    fetchJson(`/datasets/${encodeURIComponent(snapshotId)}`),

  getDatasetDownload: (snapshotId: string): Promise<DatasetDownloadResponse> =>
    fetchJson(`/datasets/${encodeURIComponent(snapshotId)}/download`),

  retryDataset: (snapshotId: string): Promise<DatasetSnapshot> =>
    fetchJson(`/datasets/${encodeURIComponent(snapshotId)}/retry`, { method: 'POST' }),

  deleteDataset: (snapshotId: string): Promise<DatasetSnapshot> =>
    fetchJson(`/datasets/${encodeURIComponent(snapshotId)}`, { method: 'DELETE' }),

  getPipelineSettings: (): Promise<PipelineSettingsResponse> =>
    fetchJson('/pipeline/settings'),

  savePipelineSettings: (body: Partial<PipelineRunSettings>): Promise<{ settings: PipelineRunSettings }> =>
    fetchJson('/pipeline/settings', { method: 'PUT', body: JSON.stringify(body) }),

  retryPipelineRun: (body: {
    clip_id: string
    run_id?: string
  }): Promise<{
    ok: boolean
    clip_id: string
    run_id: string
    pipeline_status?: string
  }> => fetchJson('/pipeline/runs/retry', { method: 'POST', body: JSON.stringify(body) }),

  listPipelineExecutions: (opts?: {
    page?: number
    page_size?: number
  }): Promise<PipelineExecutionListResponse> => {
    const params = new URLSearchParams()
    if (opts?.page != null) params.set('page', String(opts.page))
    if (opts?.page_size != null) params.set('page_size', String(opts.page_size))
    const q = params.toString()
    return fetchJson(`/pipeline/executions${q ? `?${q}` : ''}`)
  },

  createPipelineExecution: async (
    files: File[],
    opts?: {
      onUploadProgress?: (ev: { loaded: number; total: number; percent: number }) => void
    },
  ): Promise<{
    run_id: string
    label: string
    started_at: string
    ds: string
    clips: { clip_id: string; oss_key: string }[]
  }> => {
    const form = new FormData()
    for (const file of files) {
      form.append('files', file)
    }
    const res = await http.post('/pipeline/executions', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 0,
      onUploadProgress: (event) => {
        if (!opts?.onUploadProgress) return
        const loaded = event.loaded ?? 0
        const total = event.total && event.total > 0 ? event.total : loaded
        const percent = total > 0 ? Math.min(100, Math.round((loaded * 100) / total)) : 0
        opts.onUploadProgress({ loaded, total, percent })
      },
    })
    return res.data
  },

  cancelPipelineExecution: (runId: string): Promise<{
    run_id: string
    cancelled_clips: number
    unchanged_clips: number
  }> =>
    fetchJson(`/pipeline/executions/${encodeURIComponent(runId)}/cancel`, { method: 'POST' }),

  register: (body: {
    username: string
    password: string
    display_name?: string
  }): Promise<RegisterResponse> =>
    fetchJson('/auth/register', { method: 'POST', body: JSON.stringify(body) }),
}
