import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

type ListQueryOptions = {
  statusKey?: string
  defaultStatus?: string
  pageKey?: string
  defaultPage?: number
}

/**
 * Sync list filter + pagination to URL for back-navigation state preservation (ux: state-preservation).
 */
export function useListQueryState(options: ListQueryOptions = {}) {
  const {
    statusKey = 'status',
    defaultStatus = 'all',
    pageKey = 'page',
    defaultPage = 1,
  } = options

  const [searchParams, setSearchParams] = useSearchParams()

  const status = searchParams.get(statusKey) ?? defaultStatus
  const page = Math.max(1, Number(searchParams.get(pageKey) ?? defaultPage) || defaultPage)

  const patchParams = useCallback(
    (patch: Record<string, string | null>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          for (const [key, value] of Object.entries(patch)) {
            if (value == null || value === '') {
              next.delete(key)
            } else {
              next.set(key, value)
            }
          }
          return next
        },
        { replace: false },
      )
    },
    [setSearchParams],
  )

  const setStatus = useCallback(
    (value: string) => {
      patchParams({
        [statusKey]: value === defaultStatus ? null : value,
        [pageKey]: null,
      })
    },
    [defaultStatus, pageKey, patchParams, statusKey],
  )

  const setPage = useCallback(
    (value: number) => {
      patchParams({
        [pageKey]: value <= 1 ? null : String(value),
      })
    },
    [pageKey, patchParams],
  )

  return useMemo(
    () => ({ status, page, setStatus, setPage }),
    [page, setPage, setStatus, status],
  )
}

export type ReviewTaskFilters = Record<string, string | boolean>

function parseTaskFilters(raw: string | null): ReviewTaskFilters {
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw) as ReviewTaskFilters
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function parseFilterValue(raw: string): string | boolean {
  if (raw === 'true') return true
  if (raw === 'false') return false
  return raw
}

/** Sync label-centric review task: tree label + search value (?label=&q=) or legacy task_filters. */
export function useReviewTaskQueryState() {
  const [searchParams, setSearchParams] = useSearchParams()

  const selectedLabelId = searchParams.get('label') ?? undefined
  const filterValue = searchParams.get('q') ?? ''
  const legacyFilters = useMemo(
    () => parseTaskFilters(searchParams.get('task_filters')),
    [searchParams],
  )

  const taskFilters = useMemo((): ReviewTaskFilters => {
    if (selectedLabelId && filterValue.trim()) {
      return { [selectedLabelId]: parseFilterValue(filterValue.trim()) }
    }
    return legacyFilters
  }, [filterValue, legacyFilters, selectedLabelId])

  const taskScope = (searchParams.get('task_scope') ?? 'unreviewed') as
    | 'all'
    | 'pending_review'
    | 'reviewed'
    | 'unreviewed'
  const disputesOnly = searchParams.get('disputes_only') === '1'
  const page = Math.max(1, Number(searchParams.get('page') ?? 1) || 1)

  const patchParams = useCallback(
    (patch: Record<string, string | null>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          for (const [key, value] of Object.entries(patch)) {
            if (value == null || value === '') next.delete(key)
            else next.set(key, value)
          }
          return next
        },
        { replace: false },
      )
    },
    [setSearchParams],
  )

  const setSelectedLabelId = useCallback(
    (labelId: string | undefined) => {
      patchParams({
        label: labelId ?? null,
        task_filters: null,
        page: null,
      })
    },
    [patchParams],
  )

  const setFilterValue = useCallback(
    (value: string) => {
      const trimmed = value.trim()
      patchParams({
        q: trimmed || null,
        task_filters: null,
        page: null,
      })
    },
    [patchParams],
  )

  const clearLabel = useCallback(() => {
    patchParams({ label: null, page: null })
  }, [patchParams])

  const applySearchTask = useCallback(
    (labelId: string | undefined, value: string | boolean) => {
      if (!labelId || value === '' || value == null) return
      const serialized = typeof value === 'boolean' ? (value ? 'true' : 'false') : value.trim()
      if (!serialized) return
      const filterValue = typeof value === 'boolean' ? value : serialized
      patchParams({
        label: labelId,
        q: serialized,
        task_filters: JSON.stringify({ [labelId]: filterValue }),
        page: null,
      })
    },
    [patchParams],
  )

  const setTaskFilters = useCallback(
    (filters: ReviewTaskFilters) => {
      const keys = Object.entries(filters).filter(([, v]) => v !== '' && v != null)
      if (keys.length === 1) {
        const [labelId, val] = keys[0]
        patchParams({
          label: labelId,
          q: String(val),
          task_filters: JSON.stringify(Object.fromEntries(keys)),
          page: null,
        })
        return
      }
      patchParams({
        label: null,
        q: null,
        task_filters: keys.length > 0 ? JSON.stringify(Object.fromEntries(keys)) : null,
        page: null,
      })
    },
    [patchParams],
  )

  const setTaskScope = useCallback(
    (scope: string) => {
      patchParams({
        task_scope: scope === 'unreviewed' ? null : scope,
        page: null,
      })
    },
    [patchParams],
  )

  const setDisputesOnly = useCallback(
    (enabled: boolean) => {
      patchParams({
        disputes_only: enabled ? '1' : null,
        page: null,
      })
    },
    [patchParams],
  )

  const setPage = useCallback(
    (value: number) => {
      patchParams({ page: value <= 1 ? null : String(value) })
    },
    [patchParams],
  )

  const buildReviewHref = useCallback(
    (clipId: string, runId: string) => {
      const params = new URLSearchParams()
      params.set('run_id', runId)
      const keys = Object.entries(taskFilters).filter(([, v]) => v !== '' && v != null)
      if (keys.length === 1) {
        params.set('label', keys[0][0])
        params.set('q', String(keys[0][1]))
      }
      if (keys.length > 0) {
        params.set('task_filters', JSON.stringify(Object.fromEntries(keys)))
      }
      if (taskScope !== 'unreviewed') {
        params.set('task_scope', taskScope)
      }
      if (disputesOnly) {
        params.set('disputes_only', '1')
      }
      return `/review/${encodeURIComponent(clipId)}?${params.toString()}`
    },
    [disputesOnly, taskFilters, taskScope],
  )

  return useMemo(
    () => ({
      taskFilters,
      selectedLabelId,
      filterValue,
      taskScope,
      disputesOnly,
      page,
      setSelectedLabelId,
      setFilterValue,
      clearLabel,
      applySearchTask,
      setTaskFilters,
      setTaskScope,
      setDisputesOnly,
      setPage,
      buildReviewHref,
      hasTask: Object.keys(taskFilters).length > 0,
    }),
    [
      applySearchTask,
      buildReviewHref,
      clearLabel,
      disputesOnly,
      filterValue,
      page,
      selectedLabelId,
      setDisputesOnly,
      setFilterValue,
      setPage,
      setSelectedLabelId,
      setTaskFilters,
      setTaskScope,
      taskFilters,
      taskScope,
    ],
  )
}
