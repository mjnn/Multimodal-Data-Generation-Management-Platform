import type { ClipOverview } from '../api/types'

/** Mutually exclusive Clip lifecycle bucket for overview stats + pie chart. */
export type ClipOverviewBucket = 'in_pipeline' | 'pipeline_done' | 'in_review' | 'dataset_ready'

export const CLIP_BUCKET_ORDER: ClipOverviewBucket[] = [
  'in_pipeline',
  'pipeline_done',
  'in_review',
  'dataset_ready',
]

export const CLIP_BUCKET_LABELS: Record<ClipOverviewBucket, string> = {
  in_pipeline: '管线中',
  pipeline_done: '完成管线',
  in_review: '校核中',
  dataset_ready: '可入数据集',
}

export const CLIP_BUCKET_HINTS: Record<ClipOverviewBucket, string> = {
  in_pipeline: '管线未完成（进行中 / 待处理 / 失败）',
  pipeline_done: '管线已完成，尚未开始标签校核',
  in_review: '已有标签完成校核，尚未全部完成',
  dataset_ready: '全部标签校核完成，可纳入数据集',
}

export const CLIP_BUCKET_COLORS: Record<ClipOverviewBucket, string> = {
  in_pipeline: '#faad14',
  pipeline_done: '#1677ff',
  in_review: '#722ed1',
  dataset_ready: '#52c41a',
}

export type ClipOverviewBucketCounts = Record<ClipOverviewBucket, number>

export function classifyOverviewClip(clip: ClipOverview): ClipOverviewBucket {
  if (clip.dataset_ready) return 'dataset_ready'

  const reviewed = clip.field_reviewed_count ?? 0
  if (clip.clip_label_ready && reviewed > 0) return 'in_review'

  if (clip.pipeline_status === 'completed') return 'pipeline_done'

  return 'in_pipeline'
}

export function summarizeOverviewClipBuckets(clips: ClipOverview[]): ClipOverviewBucketCounts {
  const counts: ClipOverviewBucketCounts = {
    in_pipeline: 0,
    pipeline_done: 0,
    in_review: 0,
    dataset_ready: 0,
  }
  for (const clip of clips) {
    counts[classifyOverviewClip(clip)] += 1
  }
  return counts
}
