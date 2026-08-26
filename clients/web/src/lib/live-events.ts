import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import type { BulkProcessesPayload, BulkProcessSummary } from '@/lib/api'

// Empty string must fall back to /api (same as api.ts) — ?? keeps "".
const LIVE_EVENTS_PATH = `${import.meta.env.VITE_ADMIN_API_URL || '/api'}/live/events`

const MATCHING_PROGRESS_QUERY_KEY = ['admin-api', 'ops', 'drop-matching-progress'] as const
const DROP_PROCESSES_QUERY_PREFIX = ['admin-api', 'ops', 'drop-processes'] as const
const DROP_CONSOLE_SNAPSHOT_PREFIX = ['admin-api', 'ops', 'drop-console-snapshot'] as const

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

type DropConsoleSnapshot = {
  matching_progress?: DropMatchingProgress
  processes?: {
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

function isDropConsoleSnapshotQuery(queryKey: readonly unknown[]): boolean {
  if (queryKey.length < 3) return false
  if (queryKey[0] !== 'admin-api' || queryKey[1] !== 'ops') return false
  if (queryKey[2] === DROP_CONSOLE_SNAPSHOT_PREFIX[2]) return true
  return queryKey[2] === 'drop-console' && queryKey[3] === 'snapshot'
}

function patchConsoleSnapshotMatchingProgress(
  queryClient: ReturnType<typeof useQueryClient>,
  payload: DropMatchingProgress,
) {
  queryClient.setQueriesData<DropConsoleSnapshot>(
    { predicate: (query) => isDropConsoleSnapshotQuery(query.queryKey) },
    (old) => (old ? { ...old, matching_progress: payload } : old),
  )
}

function patchConsoleSnapshotBulkProcess(
  queryClient: ReturnType<typeof useQueryClient>,
  patch: BulkProcessPatch,
) {
  queryClient.setQueriesData<DropConsoleSnapshot>(
    { predicate: (query) => isDropConsoleSnapshotQuery(query.queryKey) },
    (old) => {
      const list = old?.processes?.processes
      if (!list) return old
      const next = patchBulkProcessList(list, patch)
      if (!next) return old
      return {
        ...old,
        processes: { ...old.processes!, processes: next },
      }
    },
  )
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

      queryClient.setQueriesData<BulkProcessesPayload>(
        {
          queryKey: DROP_PROCESSES_QUERY_PREFIX,
          predicate: (query) => isBulkProcessListQuery(query.queryKey),
        },
        (old) => {
          if (!old?.processes) return old
          const next = patchBulkProcessList(old.processes, payload)
          if (!next) return old
          return { ...old, processes: next }
        },
      )

      patchConsoleSnapshotBulkProcess(queryClient, payload)
    })

    source.onerror = () => {
      source.close()
    }

    return () => source.close()
  }, [enabled, queryClient])
}
