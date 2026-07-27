import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { message } from 'antd'

import type { AxiosError } from 'axios'

import { api } from '../api'

import type { ReviewV2Action, ReviewV2Mode, ReviewV2StagedReview, ReviewV2Task } from '../api/types'

import {

  buildStagedReview,

  comprehensiveFilterReady,

  reviewTaskKey,

  taskWithPosition,

} from '../utils/reviewV2'



function apiErrorMessage(e: unknown, fallback: string): string {

  const detail = (e as AxiosError<{ detail?: { message?: string } }>)?.response?.data?.detail?.message

  return detail ?? fallback

}



async function resolveClipUpdatedAt(task: ReviewV2Task): Promise<string | null> {

  try {

    const review = await api.getReviewDetail(task.clip_id, task.run_id)

    return review.updated_at

  } catch {

    return task.clip_card.clip_review_updated_at ?? null

  }

}



function restoreSessionForQueue(

  items: ReviewV2Task[],

  session: { staged?: Record<string, ReviewV2StagedReview>; current_index?: number },

): { staged: Record<string, ReviewV2StagedReview>; currentIndex: number } {

  const allowedKeys = new Set(items.map((t) => reviewTaskKey(t.clip_id, t.run_id, t.label_id)))

  const staged: Record<string, ReviewV2StagedReview> = {}

  for (const [key, value] of Object.entries(session.staged ?? {})) {

    if (allowedKeys.has(key) && value && typeof value === 'object') {

      staged[key] = value as ReviewV2StagedReview

    }

  }

  let currentIndex = session.current_index ?? 0

  if (items.length === 0) {

    currentIndex = 0

  } else {

    currentIndex = Math.min(Math.max(0, currentIndex), items.length - 1)

  }

  return { staged, currentIndex }

}



export function useReviewV2Session(batchId?: string | null) {

  const [mode, setMode] = useState<ReviewV2Mode>('confidence')

  const [labelId, setLabelId] = useState<string | null>(null)

  const [filterValue, setFilterValue] = useState('')

  const [dtype, setDtype] = useState<string | null>(null)

  const [queue, setQueue] = useState<ReviewV2Task[]>([])

  const [batchInfo, setBatchInfo] = useState<{ id: string; name: string } | null>(null)

  const [currentIndex, setCurrentIndex] = useState(0)

  const [staged, setStaged] = useState<Record<string, ReviewV2StagedReview>>({})

  const [loading, setLoading] = useState(false)

  const [committing, setCommitting] = useState(false)

  const [sessionReady, setSessionReady] = useState(false)

  const loadSeq = useRef(0)

  const queueSessionKey = useRef('')

  const stagedRef = useRef(staged)

  const currentIndexRef = useRef(currentIndex)

  const sessionLoadedRef = useRef(false)



  stagedRef.current = staged

  currentIndexRef.current = currentIndex



  const isBatchMode = Boolean(batchId)



  const filterReady = isBatchMode || comprehensiveFilterReady(mode, labelId, filterValue)



  const queryOpts = useMemo(

    () => ({

      mode,

      labelId: mode === 'comprehensive' ? (labelId ?? undefined) : undefined,

      value: mode === 'comprehensive' ? filterValue : undefined,

      dtype: mode === 'comprehensive' ? (dtype ?? undefined) : undefined,

    }),

    [mode, labelId, filterValue, dtype],

  )



  const sessionKey = useMemo(

    () => `${batchId ?? ''}|${mode}|${labelId ?? ''}|${filterValue}|${dtype ?? ''}`,

    [batchId, dtype, filterValue, labelId, mode],

  )



  const stagedCount = Object.keys(staged).length

  const queueTotal = queue.length

  const allStaged = queueTotal > 0 && stagedCount >= queueTotal



  const task = useMemo(() => {

    if (!queue.length || currentIndex < 0 || currentIndex >= queue.length) return null

    return taskWithPosition(queue[currentIndex], currentIndex, queue.length)

  }, [currentIndex, queue])



  const currentStaged = useMemo(() => {

    if (!task) return null

    return staged[reviewTaskKey(task.clip_id, task.run_id, task.label_id)] ?? null

  }, [staged, task])



  const persistSession = useCallback(async () => {

    if (!batchId || !sessionLoadedRef.current) return

    try {

      await api.saveReviewWorkbenchSession(batchId, {

        staged: stagedRef.current,

        current_index: currentIndexRef.current,

      })

    } catch {

      // Best-effort; unmount retry may succeed.

    }

  }, [batchId])



  const loadQueue = useCallback(async () => {

    const seq = ++loadSeq.current

    if (!filterReady) {

      setQueue([])

      setBatchInfo(null)

      setCurrentIndex(0)

      setStaged({})

      setSessionReady(false)

      sessionLoadedRef.current = false

      return

    }

    setLoading(true)

    setSessionReady(false)

    try {

      if (isBatchMode && batchId) {

        const [res, sessionRes] = await Promise.all([

          api.getReviewAssignmentWorkQueue(batchId),

          api.getReviewWorkbenchSession(batchId),

        ])

        if (seq !== loadSeq.current) return

        const restored = restoreSessionForQueue(res.items, sessionRes)

        setQueue(res.items)

        setBatchInfo({ id: res.batch.id, name: res.batch.name })

        setStaged(restored.staged)

        setCurrentIndex(restored.currentIndex)

        queueSessionKey.current = sessionKey

        sessionLoadedRef.current = true

        setSessionReady(true)

        return

      }



      const pageSize = 200

      const items: ReviewV2Task[] = []

      let offset = 0

      let total = 0

      do {

        const res = await api.getReviewV2Tasks({ ...queryOpts, limit: pageSize, offset })

        if (seq !== loadSeq.current) return

        items.push(...res.items)

        total = res.total

        offset += res.items.length

        if (res.items.length === 0) break

      } while (items.length < total)



      if (seq !== loadSeq.current) return

      setQueue(items)

      setBatchInfo(null)

      setCurrentIndex(0)

      if (queueSessionKey.current !== sessionKey) {

        setStaged({})

        queueSessionKey.current = sessionKey

      }

      sessionLoadedRef.current = false

      setSessionReady(true)

    } catch (e: unknown) {

      if (seq !== loadSeq.current) return

      message.error(apiErrorMessage(e, '加载队列失败'))

      setQueue([])

      sessionLoadedRef.current = false

    } finally {

      if (seq === loadSeq.current) setLoading(false)

    }

  }, [batchId, filterReady, isBatchMode, queryOpts, sessionKey])



  const stage = useCallback(

    (action: ReviewV2Action, value?: unknown) => {

      if (!task) return

      const key = reviewTaskKey(task.clip_id, task.run_id, task.label_id)

      const entry = buildStagedReview(task, action, value)

      setStaged((prev) => ({ ...prev, [key]: entry }))

      message.success('已暂存，待队列完成后统一提交')

      if (currentIndex < queue.length - 1) {

        setCurrentIndex((i) => i + 1)

      } else {

        message.info('本队列已全部审完，请核对暂存结果后点击「确认提交」')

      }

    },

    [currentIndex, queue.length, task],

  )



  const loadPrev = useCallback(() => {

    if (currentIndex <= 0) return

    setCurrentIndex((i) => i - 1)

  }, [currentIndex])



  const loadNext = useCallback(() => {

    if (currentIndex >= queue.length - 1) return

    setCurrentIndex((i) => i + 1)

  }, [currentIndex, queue.length])



  const goToIndex = useCallback(

    (index: number) => {

      if (index < 0 || index >= queue.length) return

      setCurrentIndex(index)

    },

    [queue.length],

  )



  const commitQueue = useCallback(async () => {

    if (!allStaged || committing) return false

    setCommitting(true)

    let okCount = 0

    try {

      for (const item of queue) {

        const key = reviewTaskKey(item.clip_id, item.run_id, item.label_id)

        const entry = staged[key]

        if (!entry) continue

        const clipUpdatedAt = await resolveClipUpdatedAt(item)

        await api.submitReviewV2({

          clip_id: item.clip_id,

          run_id: item.run_id,

          label_id: item.label_id,

          action: entry.action,

          value: entry.action === 'confirm' ? entry.ai_value : entry.value,

          clip_updated_at: clipUpdatedAt,

          assignment_batch_id: batchId ?? null,

        })

        okCount += 1

      }

      message.success(`已提交 ${okCount} 条校核结果`)

      setStaged({})

      queueSessionKey.current = ''

      if (batchId) {

        try {

          await api.clearReviewWorkbenchSession(batchId)

        } catch {

          // ignore

        }

      }

      await loadQueue()

      return true

    } catch (e: unknown) {

      message.error(apiErrorMessage(e, '提交失败，请检查后重试'))

      return false

    } finally {

      setCommitting(false)

    }

  }, [allStaged, batchId, committing, loadQueue, queue, staged])



  const switchMode = useCallback(

    (next: ReviewV2Mode) => {

      if (isBatchMode) return

      setMode(next)

      setQueue([])

      setCurrentIndex(0)

      setStaged({})

      queueSessionKey.current = ''

    },

    [isBatchMode],

  )



  const selectLabel = useCallback((nextLabelId: string | null, nextDtype?: string | null) => {

    setLabelId(nextLabelId)

    setFilterValue('')

    setDtype(nextDtype ?? null)

    setQueue([])

    setCurrentIndex(0)

    setStaged({})

    queueSessionKey.current = ''

  }, [])



  useEffect(() => {

    void loadQueue()

  }, [loadQueue])



  useEffect(() => {

    if (!batchId || !sessionReady || loading) return

    const timer = window.setTimeout(() => {

      void persistSession()

    }, 600)

    return () => window.clearTimeout(timer)

  }, [batchId, sessionReady, loading, staged, currentIndex, persistSession])



  useEffect(() => {

    if (!batchId) return

    return () => {

      if (!sessionLoadedRef.current) return

      void api.saveReviewWorkbenchSession(batchId, {

        staged: stagedRef.current,

        current_index: currentIndexRef.current,

      })

    }

  }, [batchId])



  return {

    mode,

    switchMode,

    labelId,

    selectLabel,

    filterValue,

    setFilterValue,

    dtype,

    setDtype,

    task,

    currentStaged,

    queue,

    staged,

    queueTotal,

    stagedCount,

    allStaged,

    currentIndex,

    loading,

    committing,

    filterReady,

    loadPrev,

    loadNext,

    goToIndex,

    stage,

    commitQueue,

    persistSession,

    canPrev: currentIndex > 0,

    canNext: currentIndex < queue.length - 1,

    isBatchMode,

    batchInfo,

  }

}


