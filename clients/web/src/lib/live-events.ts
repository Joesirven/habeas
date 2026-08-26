import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import type { BulkProcessesPayload, BulkProcessSummary } from '@/lib/api'

// EventSource cannot set Authorization. Keep same-origin /api/live/events
// (nginx/Vite proxy) even when JSON APIs go cross-origin via VITE_ADMIN_API_URL.
export const LIVE_EVENTS_PATH = '/api/live/events'

const MATCHING_PROGRESS_QUERY_KEY = ['admin-api', 'ops', 'drop-matching-progress'] as const
const DROP_PROCESSES_QUERY_PREFIX = ['admin-api', 'ops', 'drop-processes'] as const

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

function isBulkProcessPatch(value: unknown): value is BulkProcessPatch {
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
      if (!patchedList && !patchedSnapshot) {
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
