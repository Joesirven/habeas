/** Shared `/ops/runs` search-param helpers (avoid router ↔ page import cycles). */

export const RUNS_STATUS_FILTERS = ['failed', 'in_progress', 'success'] as const
export const RUNS_WINDOWS = ['8h', '24h', '1w'] as const
export const RUNS_JOBS = ['connector', 'ingest', 'matching', 'hash_index'] as const

export type OpsRunsSearch = {
  status: (typeof RUNS_STATUS_FILTERS)[number] | undefined
  window: (typeof RUNS_WINDOWS)[number] | undefined
  job: (typeof RUNS_JOBS)[number] | undefined
  request_id: string | undefined
}

/** Always return every key so TanStack Link `search` is assignable. */
export function parseOpsRunsSearch(search: Record<string, unknown>): OpsRunsSearch {
  const status =
    typeof search.status === 'string' &&
    (RUNS_STATUS_FILTERS as readonly string[]).includes(search.status)
      ? (search.status as (typeof RUNS_STATUS_FILTERS)[number])
      : undefined
  const window =
    typeof search.window === 'string' &&
    (RUNS_WINDOWS as readonly string[]).includes(search.window)
      ? (search.window as (typeof RUNS_WINDOWS)[number])
      : undefined
  const job =
    typeof search.job === 'string' && (RUNS_JOBS as readonly string[]).includes(search.job)
      ? (search.job as (typeof RUNS_JOBS)[number])
      : undefined
  const requestId =
    typeof search.request_id === 'string' && search.request_id.trim()
      ? search.request_id.trim()
      : undefined
  return {
    status,
    window,
    job,
    request_id: requestId,
  }
}

export function opsRunsSearch(partial: Partial<OpsRunsSearch> = {}): OpsRunsSearch {
  return {
    status: partial.status,
    window: partial.window,
    job: partial.job,
    request_id: partial.request_id,
  }
}
