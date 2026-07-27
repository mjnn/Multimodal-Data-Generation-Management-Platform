export type PipelineStatus =
  | 'success'
  | 'failed'
  | 'running'
  | 'pending'
  | 'skipped'

export type ClipRunStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface ClipRun {
  run_id: string
  status: ClipRunStatus
  is_active: boolean
  started_at: string
}

export type LabelGranularity = 'clip' | 'frame'
export type SampleSyncMode = 'uniform' | 'uniform_sync' | 'clip'

export interface ClipLabelView {
  label_granularity: LabelGranularity
  clip_label_ready: boolean
  label_preview?: string
  labels_json?: Record<string, unknown>
  anchor_timestamp_ns?: number | null
  source?: string | null
  aggregation?: string | null
}

export interface ClipOverview {
  clip_id: string
  clip_dir_name: string
  bag_oss_key: string
  active_run_id: string
  runs?: ClipRun[]
  duration_sec: number
  start_time_ns: number
  end_time_ns: number
  pipeline_status: ClipRunStatus
  steps: PipelineStepSummary[]
  frame_count: number
  /** Clip-centric: always 1 (one label unit per clip). */
  sampled_count: number
  /** Clip-centric: 0 or 1. */
  labeled_count: number
  asr_segment_count: number
  event_count: number
  label_granularity?: LabelGranularity
  clip_label_ready?: boolean
  clip_label_preview?: string
  /** AI label count on clip */
  label_total?: number
  /** AI multi-model dispute label count */
  dispute_count?: number
  /** Human field-review completed count */
  field_reviewed_count?: number
  /** 0–100 */
  review_progress_pct?: number
  review_complete?: boolean
  /** All labels reviewed — eligible for dataset build (default policy) */
  dataset_ready?: boolean
  review_status?: ReviewStatus | null
}

export interface UploadPipelineStep {
  step_id: string
  label: string
  status: PipelineStatus
}

export interface PipelineStepSummary {
  step_id: string
  status: PipelineStatus
  label: string
}

export type LabelScope = 'frame' | 'sync_group' | 'clip'

export interface SampledFrame {
  composite_id: string
  clip_id: string
  run_id: string
  camera: string
  frame_idx: number
  timestamp_ns: number
  image_url: string
  is_sampled: boolean
  has_label: boolean
  label_preview?: string
  labels_json?: Record<string, unknown>
  sync_group_id?: string | null
  anchor_timestamp_ns?: number | null
  label_scope?: LabelScope | null
  is_sync_group?: boolean
}

export interface AudioSegment {
  segment_id: number
  start_ns: number
  end_ns: number
  asr_text: string
  confidence: number
  audio_url?: string
}

export interface EventLabel {
  timestamp_ns: number
  event_data: string
  parsed_label?: string
}

export interface TimelineSnapshot {
  timestamp_ns: number
  frames: SampledFrame[]
  audio_segment?: AudioSegment
  events: EventLabel[]
  clip_label?: ClipLabelView | null
}

export interface ClipPreviewManifest {
  mode: 'mp4'
  fps: number
  frame_count: number
  start_time_ns: number
  end_time_ns: number
  grid_url: string
  cameras: { camera: string; url: string; frame_count: number }[]
}

export interface TimelineMeta {
  sampled_timestamps_ns: number[]
  sample_sync_mode?: SampleSyncMode
  /** Cameras present in fact_frame (omit empty slots). */
  cameras?: string[]
  /** MP4 grid preview when import uses --preview-mode mp4 */
  preview?: ClipPreviewManifest | null
  events: EventLabel[]
  asr_segments: AudioSegment[]
  clip_label?: ClipLabelView | null
}

export interface LabelTaxonomyNode {
  id: string
  name: string
  children?: LabelTaxonomyNode[]
}

export interface SimilarItem {
  composite_id: string
  clip_id: string
  camera: string
  timestamp_ns: number
  preview_url: string
  label_text: string
  score: number
}

export interface UploadTask {
  task_id: string
  filename: string
  size_bytes: number
  progress: number
  status: PipelineStatus
  oss_key?: string
  clip_id?: string
  run_id?: string
  pipeline_status?: 'idle' | 'running' | 'completed' | 'failed'
  pipeline_steps?: UploadPipelineStep[]
}

export interface Paginated<T> {
  total: number
  page: number
  page_size: number
  items: T[]
}

export interface OssSyncPollerStatus {
  enabled: boolean
  auto_sync_enabled: boolean
  running_sync: boolean
  interval_sec: number
  manifest_key?: string
  last_fingerprint?: string | null
  last_sync_status?: string | null
  last_sync_at?: string | null
  last_sync_error?: string | null
  last_sync_clip_id?: string | null
  last_sync_run_id?: string | null
}

export interface OssRootPrefix {
  prefix: string
  label: string
  hint: string
}

export interface OssInfo {
  bucket: string
  endpoint: string
  root_prefixes: OssRootPrefix[]
}

export interface OssListItem {
  name: string
  key: string
  type: 'dir' | 'file'
  size: number
  last_modified: string | null
}

export interface OssListResponse {
  bucket: string
  prefix: string
  parent_prefix: string
  items: OssListItem[]
}

export type BagPipelineStatus =
  | 'idle'
  | 'running'
  | 'completed'
  | 'failed'
  | 'not_discovered'

export interface OssBagPipeline {
  oss_key: string
  clip_id: string | null
  run_id: string | null
  active_run_id?: string | null
  is_active_run?: boolean
  run_status?: string | null
  ds?: string | null
  pipeline_status: BagPipelineStatus
  pipeline_steps: UploadPipelineStep[] | null
  message?: string | null
}

export type TaxonomyStatus = 'draft' | 'published' | 'archived'

export interface TaxonomyVersion {
  id: string
  version_code: string
  status: TaxonomyStatus
  published_at: string | null
  created_by: string | null
  source_import: string | null
  created_at: string
  updated_at: string
  node_count: number
}

export interface TaxonomyNodeDetail {
  id: string
  taxonomy_version_id: string
  parent_id: string | null
  level_code: string
  level_name: string | null
  label_id: string
  name: string
  definition: string | null
  dtype: string | null
  value_schema: unknown
  sort_order: number
  is_active: boolean
}

export interface TaxonomyTreeResponse {
  version: TaxonomyVersion
  nodes: TaxonomyNodeDetail[]
  tree: LabelTaxonomyNode[]
}

export type TaxonomyNodeInput = {
  label_id: string
  level_code?: string
  level_name?: string | null
  name?: string
  definition?: string | null
  dtype?: string | null
  value_schema?: unknown
  sort_order?: number
  is_active?: boolean
}

export type ReviewStatus = 'pending_review' | 'reviewed'

export type AiLabelHint = {
  confidence?: number | null
  evidence?: string | null
}

export interface ClipLabelReview {
  id: string
  clip_id: string
  run_id: string
  taxonomy_version_id: string | null
  labels_json: Record<string, unknown>
  review_status: ReviewStatus
  ai_source_summary_json: Record<string, unknown> | null
  reviewer_id: string | null
  reviewed_at: string | null
  created_at: string
  updated_at: string
  label_preview?: string
  ai_label_hints?: Record<string, AiLabelHint>
  /** Per-label human field review completed (clip_label_field_review). */
  field_reviewed_label_ids?: string[]
}

export type ReviewTaskScope = 'all' | 'pending_review' | 'reviewed' | 'unreviewed'

export interface AiLabelVote {
  model: string
  value: string | boolean | number
  confidence?: number
}

export interface LabelConsensusEntry {
  output: string | boolean | number
  status: 'unanimous' | 'majority' | 'split' | 'minority' | 'tie' | string
  agreement: number
  needs_review: boolean
  votes: AiLabelVote[]
}

export interface MultiAiGateMeta {
  passed: boolean
  clip_score: number
  threshold: number
  model_count: number
}

export interface ReviewTaskCandidate {
  clip_id: string
  run_id: string
  clip_dir_name: string
  labels_json: Record<string, unknown>
  label_preview: string
  label_granularity: LabelGranularity | string
  review_status: ReviewStatus | null
  review_id: string | null
  in_queue: boolean
  disputed_label_ids?: string[]
  dispute_count?: number
  multi_ai_gate?: MultiAiGateMeta | null
  label_consensus?: Record<string, LabelConsensusEntry>
}

export interface ReviewCandidatesResponse {
  items: ReviewTaskCandidate[]
  total: number
  limit: number
  offset: number
}

export interface ReviewQueueResponse {
  items: ClipLabelReview[]
  total: number
  limit: number
  offset: number
}

export type ReviewV2Mode = 'confidence' | 'comprehensive'

export type ReviewV2Action = 'confirm' | 'correct' | 'uncertain'

export interface ReviewV2StagedReview {
  clip_id: string
  run_id: string
  label_id: string
  action: ReviewV2Action
  /** Resolved value after review (confirm→ai, uncertain→null, correct→input). */
  value: unknown
  ai_value: unknown
  staged_at: string
}

export interface ReviewV2ClipCard {
  clip_id: string
  run_id: string
  clip_dir_name: string
  label_preview?: string
  anchor_timestamp_ns?: number | null
  dispute_count?: number
  multi_ai_gate?: MultiAiGateMeta | null
  review_status?: ReviewStatus | null
  clip_review_updated_at?: string | null
  thumbnail?: {
    camera?: string
    frame_idx?: number
    image_path?: string
    timestamp_ns?: number
  } | null
}

export interface ReviewV2Task {
  clip_id: string
  run_id: string
  label_id: string
  label_name: string
  dtype?: string | null
  value_schema?: { type?: string; values?: unknown[] } | null
  ai_value: unknown
  ai_confidence?: number | null
  ai_evidence?: string | null
  human_doubtful?: boolean
  low_confidence?: boolean
  priority_bucket?: number | null
  clip_card: ReviewV2ClipCard
  cursor: string
  position: { index: number; total: number }
}

export interface ReviewV2SessionSnapshot {
  mode: ReviewV2Mode
  label_id: string | null
  value: unknown
  history_count: number
  history_index: number
  can_prev: boolean
}

export interface ReviewV2Stats {
  mode: ReviewV2Mode
  label_id: string | null
  value: unknown
  pending: number
  total: number
}

export interface ReviewV2LabelOption {
  label_id: string
  name: string
  dtype?: string | null
  value_schema?: unknown
  enum_values: unknown[]
}

export interface ReviewV2FieldReview {
  id: string
  clip_id: string
  run_id: string
  label_id: string
  action: ReviewV2Action
  value_json: unknown
  human_doubtful: boolean
  ai_value_json: unknown
  reviewer_id: string | null
  reviewed_at: string
}

export interface ReviewV2SubmitResult {
  field_review: ReviewV2FieldReview
  clip_review: ClipLabelReview
  rolled_up_to_reviewed: boolean
  assignment_item_done?: boolean
}

export interface ReviewAssignmentBatch {
  id: string
  name: string
  label_ids: string[]
  queue_limit: number
  assignee_id: string | null
  status: 'open' | 'closed'
  created_by: string | null
  created_at: string
  updated_at: string
  item_total?: number
  item_pending?: number
  item_claimed?: number
  item_done?: number
  my_claimed?: number
  my_done?: number
  my_staged_count?: number
  my_session_updated_at?: string | null
}

export interface ReviewWorkbenchSession {
  batch_id: string
  staged: Record<string, ReviewV2StagedReview>
  current_index: number
  updated_at: string | null
}

export interface ReviewAssignmentItem {
  id: string
  batch_id: string
  clip_id: string
  run_id: string
  label_id: string
  status: 'pending' | 'claimed' | 'done'
  assignee_id: string | null
  claimed_at: string | null
  sort_order: number
}

export interface ReviewAssignmentReviewer {
  id: string
  username: string
  display_name: string
  roles: string[]
}

export type DatasetStatus = 'building' | 'ready' | 'failed' | 'archived'

export interface DatasetFilterJson {
  review_status?: string
  include_pending_review?: boolean
  clip_ids?: string[] | null
  taxonomy_version_id?: string | null
  label_filters?: Record<string, string | boolean> | null
  sample_size?: number | null
}

export interface DatasetPreviewResponse {
  pool_count: number
  candidate_count: number
  sample_size?: number | null
  clip_ids: string[]
  filter_json: DatasetFilterJson
}

export interface DatasetSnapshot {
  id: string
  name: string
  description: string | null
  status: DatasetStatus
  filter_json: DatasetFilterJson
  clip_count: number
  feature_spec_json: Record<string, unknown>
  target_spec_json: Record<string, unknown>
  oss_manifest_uri?: string | null
  oss_x_uri: string | null
  oss_y_uri: string | null
  mc_table_name?: string | null
  error_message: string | null
  created_by: string | null
  created_at: string
  updated_at: string
  ready_at: string | null
  build_running?: boolean
}

export interface DatasetListResponse {
  items: DatasetSnapshot[]
  total: number
  limit: number
  offset: number
}

export interface DatasetDownloadResponse {
  snapshot_id: string
  package_key: string
  package_url: string
  filename: string
  clip_count: number
  expires_in: number
  /** @deprecated 使用 package_url 下载完整包 */
  x_key?: string
  y_key?: string
  x_url?: string
  y_url?: string
}
