import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import type {
  BulkProcessDetail,
  BulkProcessesPayload,
  BulkProcessStageCounts,
  BulkProcessSummary,
  BulkProcessVerticalStats,
} from '@/lib/api'

// EventSource cannot set Authorization. Keep same-origin /api/live/events
// (nginx/Vite proxy) even when JSON APIs go cross-origin via VITE_ADMIN_API_URL.
export const LIVE_EVENTS_PATH = '/api/live/events'

const MATCHING_PROGRESS_QUERY_KEY = ['admin-api', 'ops', 'drop-matching-progress'] as const
const DROP_PROCESSES_QUERY_PREFIX = ['admin-api', 'ops', 'drop-processes'] as const
const DROP_PROCESS_DETAIL_SEGMENT = 'detail'

/** Same shape as GET /ops/drop/matching-progress (ids/counts only). */
type DropMatchingProgress = {
  pending?: number
  claimed?: number
  success?: number
  by_status?: { status: string; count: number }[]
  drain?: {
    active: boolean
    holder: string | null
    expires_at: string | null
  }
  matching_attempts?: DropMatchingProgress
}

/** Cache shape for GET /ops/drop/console/snapshot — ids/counts only. */
type DropConsoleSnapshotCache = {
  matching_progress?: DropMatchingProgress
  processes?: {
    processes?: BulkProcessSummary[]
  }
  recent_processes?: {
    days?: number
    processes?: BulkProcessSummary[]
  }
}

type BulkProcessPatch = Partial<BulkProcessSummary> & Pick<BulkProcessSummary, 'process_id'>

/** Detail-only fields a `bulk_process` SSE summary may carry for expanded cards. */
export type BulkProcessExpandPatch = {
  stages?: Partial<Record<keyof BulkProcessDetail['stages'], BulkProcessStageCounts>>
  verticals?: BulkProcessVerticalStats[]
}

export type BulkProcessLivePatch = BulkProcessPatch & BulkProcessExpandPatch

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function parseEventPayload(data: string): unknown {
  if (!data) return null
  try {
    return JSON.parse(data) as unknown
  } catch {
    return null
  }
}

function isDropMatchingProgress(value: unknown): value is DropMatchingProgress {
  if (!isRecord(value)) return false
  return (
    'pending' in value ||
    'claimed' in value ||
    'success' in value ||
    'by_status' in value ||
    'drain' in value ||
    'matching_attempts' in value
  )
}

function isBulkProcessPatch(value: unknown): value is BulkProcessLivePatch {
  return isRecord(value) && typeof value.process_id === 'number'
}

function patchBulkProcessList(
  processes: BulkProcessSummary[],
  patch: BulkProcessPatch,
): BulkProcessSummary[] | null {
  const index = processes.findIndex((row) => row.process_id === patch.process_id)
  if (index === -1) return null
  return processes.map((row, i) => (i === index ? { ...row, ...patch } : row))
}

function isBulkProcessListQuery(queryKey: readonly unknown[]): boolean {
  if (queryKey.length < 4) return false
  const segment = queryKey[3]
  return segment === 'recent-30d' || segment === 'pipeline-list'
}

/** Expanded-card key is `['admin-api','ops','drop-processes','detail', processId]`. */
export function isDropProcessDetailQuery(queryKey: readonly unknown[]): boolean {
  return (
    queryKey[0] === 'admin-api' &&
    queryKey[1] === 'ops' &&
    queryKey[2] === 'drop-processes' &&
    queryKey[3] === DROP_PROCESS_DETAIL_SEGMENT &&
    typeof queryKey[4] === 'number'
  )
}

function isVerticalProgressRow(value: unknown): value is BulkProcessVerticalStats {
  return isRecord(value) && typeof value.vertical === 'string' && value.vertical.length > 0
}

function mergeVerticalProgressRows(
  current: BulkProcessVerticalStats[] | undefined,
  incoming: BulkProcessVerticalStats[],
): BulkProcessVerticalStats[] {
  const rows = incoming.filter(isVerticalProgressRow)
  if (!current?.length) return rows.map((row) => ({ ...row }))
  const incomingByVertical = new Map(rows.map((row) => [row.vertical, row]))
  const merged = current.map((row) => {
    const patchRow = incomingByVertical.get(row.vertical)
    if (!patchRow) return row
    incomingByVertical.delete(row.vertical)
    return {
      ...row,
      ...patchRow,
      matching: patchRow.matching ? { ...row.matching, ...patchRow.matching } : row.matching,
      review: patchRow.review ? { ...row.review, ...patchRow.review } : row.review,
      fulfillment: patchRow.fulfillment
        ? { ...row.fulfillment, ...patchRow.fulfillment }
        : row.fulfillment,
    }
  })
  for (const row of incomingByVertical.values()) {
    merged.push({ ...row })
  }
  return merged
}

/**
 * Merge a `bulk_process` SSE payload into a cached expand-detail response.
 * Counts are absolute, so incoming keys win; absent keys keep cached values —
 * a partial or empty patch never blanks fields the card is showing
 * (placeholderData discipline; the 5s refetch stays the reconciliation).
 */
export function mergeBulkProcessDetail(
  old: BulkProcessDetail,
  patch: BulkProcessLivePatch,
): BulkProcessDetail {
  const next: BulkProcessDetail = { ...old }

  if (patch.intake_source !== undefined) next.intake_source = patch.intake_source
  if (patch.process_at !== undefined) next.process_at = patch.process_at
  if (patch.completed_at !== undefined) next.completed_at = patch.completed_at
  if (patch.download_status !== undefined) next.download_status = patch.download_status
  if (patch.label !== undefined) next.label = patch.label
  if (patch.request_rows !== undefined) next.request_rows = patch.request_rows
  if (patch.raw_rows !== undefined) next.raw_rows = patch.raw_rows

  if (patch.stages) {
    const stages = { ...old.stages }
    for (const key of Object.keys(stages) as (keyof BulkProcessDetail['stages'])[]) {
      const incoming = patch.stages[key]
      if (incoming) {
        stages[key] = { ...stages[key], ...incoming }
      }
    }
    next.stages = stages
  }

  if (patch.overall) {
    next.overall = { ...old.overall, ...patch.overall }
  }

  if (Array.isArray(patch.verticals) && patch.verticals.length > 0) {
    next.verticals = mergeVerticalProgressRows(old.verticals, patch.verticals)
  }

  return next
}

function patchBulkProcessDetailQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  patch: BulkProcessLivePatch,
): boolean {
  let patched = false
  queryClient.setQueriesData<BulkProcessDetail>(
    {
      queryKey: DROP_PROCESSES_QUERY_PREFIX,
      predicate: (query) =>
        isDropProcessDetailQuery(query.queryKey) && query.queryKey[4] === patch.process_id,
    },
    (old) => {
      // Never seed a detail cache from SSE alone — expand still fetches first.
      if (!old) return old
      patched = true
      return mergeBulkProcessDetail(old, patch)
    },
  )
  return patched
}

/** Pipeline paint key is `['admin-api','ops','drop-console','snapshot', …]`. */
function isDropConsoleSnapshotQuery(queryKey: readonly unknown[]): boolean {
  return (
    queryKey[0] === 'admin-api' &&
    queryKey[1] === 'ops' &&
    queryKey[2] === 'drop-console' &&
    queryKey[3] === 'snapshot'
  )
}

function patchConsoleSnapshotMatchingProgress(
  queryClient: ReturnType<typeof useQueryClient>,
  payload: DropMatchingProgress,
) {
  queryClient.setQueriesData<DropConsoleSnapshotCache>(
    { predicate: (query) => isDropConsoleSnapshotQuery(query.queryKey) },
    (old) => {
      if (!old) return old
      const current = old.matching_progress
      return {
        ...old,
        matching_progress: current ? { ...current, ...payload } : payload,
      }
    },
  )
}

function patchConsoleSnapshotBulkProcess(
  queryClient: ReturnType<typeof useQueryClient>,
  patch: BulkProcessPatch,
): boolean {
  let patched = false
  queryClient.setQueriesData<DropConsoleSnapshotCache>(
    { predicate: (query) => isDropConsoleSnapshotQuery(query.queryKey) },
    (old) => {
      if (!old) return old
      const nextProcesses = old.processes?.processes
        ? patchBulkProcessList(old.processes.processes, patch)
        : null
      const nextRecent = old.recent_processes?.processes
        ? patchBulkProcessList(old.recent_processes.processes, patch)
        : null
      if (!nextProcesses && !nextRecent) return old
      patched = true
      return {
        ...old,
        processes: nextProcesses
          ? { ...old.processes, processes: nextProcesses }
          : old.processes,
        recent_processes: nextRecent
          ? { ...old.recent_processes, processes: nextRecent }
          : old.recent_processes,
      }
    },
  )
  return patched
}

export function useLiveEvents(enabled = true) {
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!enabled) return

    const source = new EventSource(LIVE_EVENTS_PATH)

    source.addEventListener('ready', () => {
      // Placeholder until Postgres LISTEN bridge emits resource-specific events.
    })

    source.addEventListener('matching_progress', (event) => {
      const payload = parseEventPayload((event as MessageEvent<string>).data)
      if (!isDropMatchingProgress(payload)) return

      queryClient.setQueryData(MATCHING_PROGRESS_QUERY_KEY, payload)
      patchConsoleSnapshotMatchingProgress(queryClient, payload)
    })

    source.addEventListener('bulk_process', (event) => {
      const payload = parseEventPayload((event as MessageEvent<string>).data)
      if (!isBulkProcessPatch(payload)) return

      let patchedList = false
      queryClient.setQueriesData<BulkProcessesPayload>(
        {
          queryKey: DROP_PROCESSES_QUERY_PREFIX,
          predicate: (query) => isBulkProcessListQuery(query.queryKey),
        },
        (old) => {
          if (!old?.processes) return old
          const next = patchBulkProcessList(old.processes, payload)
          if (!next) return old
          patchedList = true
          return { ...old, processes: next }
        },
      )

      const patchedSnapshot = patchConsoleSnapshotBulkProcess(queryClient, payload)
      const patchedDetail = patchBulkProcessDetailQueries(queryClient, payload)
      if (!patchedList && !patchedSnapshot && !patchedDetail) {
        void queryClient.invalidateQueries({ queryKey: DROP_PROCESSES_QUERY_PREFIX })
        void queryClient.invalidateQueries({
          predicate: (query) => isDropConsoleSnapshotQuery(query.queryKey),
        })
      }
    })

    source.onerror = () => {
      source.close()
    }

    return () => source.close()
  }, [enabled, queryClient])
}
