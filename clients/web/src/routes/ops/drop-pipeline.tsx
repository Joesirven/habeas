import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  getDropPipeline,
  postDropDispatch,
  postDropDownload,
  postDropFulfill,
  postDropLand,
  postDropMatch,
  postDropPromote,
  postHashIndexRefreshEnqueue,
  postHashIndexRefreshProcess,
  type DropPipelineStatus,
  type StepStatusCount,
  type WorkerHealthProbe,
} from '@/lib/api'

const WORKER_ORDER = [
  'drop_connector',
  'drop_ingestor',
  'request_dispatcher',
  'matching',
  'data_fulfillment',
  'hash_index_refresh',
] as const

const PIPELINE_STAGES = [
  '01 Download',
  '02 Land',
  '03 Promote',
  '04 Match',
  '05 Review',
  '06 Fulfill',
] as const

const ACTIONS = [
  { key: 'download', label: 'Download ZIP', run: () => postDropDownload() },
  { key: 'land', label: 'Land', run: () => postDropLand() },
  { key: 'promote', label: 'Promote', run: () => postDropPromote() },
  { key: 'dispatch', label: 'Dispatch matching', run: () => postDropDispatch() },
  { key: 'match', label: 'Run matching', run: () => postDropMatch() },
  { key: 'fulfill', label: 'Fulfill', run: () => postDropFulfill() },
] as const

type ActionKey = (typeof ACTIONS)[number]['key']

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function CountTable({ rows, empty }: { rows: StepStatusCount[]; empty: string }) {
  if (rows.length === 0) {
    return <p className="text-sm text-ink-soft">{empty}</p>
  }
  return (
    <table className="taste-table">
      <thead>
        <tr>
          <th className="!px-0">Step</th>
          <th className="!px-0">Status</th>
          <th className="!px-0">Count</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.step}-${row.status}`}>
            <td className="!px-0 font-mono text-xs">{row.step}</td>
            <td className="!px-0">{row.status}</td>
            <td className="!px-0 tabular-nums">{row.count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function WorkerHealthRow({ probe }: { probe: WorkerHealthProbe }) {
  return (
    <tr>
      <td className="font-mono text-xs">{probe.name}</td>
      <td>
        <span className={probe.ok ? 'text-emerald-700' : 'text-red-700'}>
          {probe.ok ? 'up' : 'down'}
        </span>
      </td>
      <td className="tabular-nums text-ink-soft">{probe.status_code ?? '—'}</td>
      <td className="font-mono text-xs text-mute">{probe.url}</td>
    </tr>
  )
}

function AtmospherePanel({ data }: { data: DropPipelineStatus | undefined }) {
  const workersUp = data
    ? WORKER_ORDER.filter((name) => data.worker_health[name]?.ok).length
    : 0

  return (
    <div className="relative min-h-[22rem] overflow-hidden rounded-[1.35rem] bg-habeas-navy">
      <div
        aria-hidden
        className="taste-atmosphere-orb pointer-events-none absolute -left-16 top-8 h-56 w-56 rounded-full bg-habeas-light/35 blur-2xl"
      />
      <div
        aria-hidden
        className="taste-atmosphere-orb pointer-events-none absolute -right-10 bottom-0 h-64 w-64 rounded-full bg-habeas-mid/45 blur-3xl"
        style={{ animationDelay: '1.6s' }}
      />
      <div
        aria-hidden
        className="taste-atmosphere-orb pointer-events-none absolute left-1/3 top-1/4 h-40 w-40 rounded-full bg-white/10 blur-xl"
        style={{ animationDelay: '3.2s' }}
      />

      <div className="relative flex h-full flex-col justify-between gap-8 p-6 sm:p-7">
        <div className="flex flex-wrap gap-2">
          <span className="taste-frost-chip-dark">Spine live</span>
          <span className="taste-frost-chip-dark">
            Workers {data ? `${workersUp}/${WORKER_ORDER.length}` : '—'}
          </span>
          <span className="taste-frost-chip-dark">
            Matching pending {data?.matching_review.pending ?? '—'}
          </span>
        </div>

        <div>
          <p className="text-[0.65rem] font-medium uppercase tracking-[0.18em] text-white/55">
            DROP requests
          </p>
          <p className="mt-2 font-display text-6xl font-medium tracking-tight text-white sm:text-7xl">
            {data?.drop_requests.count ?? '—'}
          </p>
          <p className="mt-3 max-w-xs text-sm leading-relaxed text-white/65">
            Thin intake rows in flight. Counts and ids only — no personally identifiable
            information.
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <span className="taste-frost-chip-dark">
            Match success {data?.matching_attempts.success ?? '—'}
          </span>
          <span className="taste-frost-chip-dark">
            Review approved {data?.matching_review.approved ?? '—'}
          </span>
        </div>
      </div>
    </div>
  )
}

export function DropPipelinePage() {
  const queryClient = useQueryClient()
  const [lastAction, setLastAction] = useState<string | null>(null)
  const [actionResult, setActionResult] = useState<string | null>(null)

  const pipelineQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-pipeline'],
    queryFn: getDropPipeline,
    refetchInterval: 5_000,
    placeholderData: (previous) => previous,
  })

  const actionMutation = useMutation({
    mutationFn: async (key: ActionKey) => {
      const action = ACTIONS.find((item) => item.key === key)
      if (!action) throw new Error(`unknown action ${key}`)
      setLastAction(action.label)
      return action.run()
    },
    onSuccess: (data) => {
      setActionResult(JSON.stringify(data, null, 2))
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
    },
    onError: (error) => {
      setActionResult(error instanceof Error ? error.message : String(error))
    },
  })

  const hashIndexMutation = useMutation({
    mutationFn: async (key: 'enqueue' | 'process') => {
      setLastAction(key === 'enqueue' ? 'Enqueue hash-index refresh' : 'Process hash-index refresh')
      return key === 'enqueue'
        ? postHashIndexRefreshEnqueue({ state: 'CA' })
        : postHashIndexRefreshProcess()
    },
    onSuccess: (payload) => {
      setActionResult(JSON.stringify(payload, null, 2))
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
    },
    onError: (error) => {
      setActionResult(error instanceof Error ? error.message : String(error))
    },
  })

  const data: DropPipelineStatus | undefined = pipelineQuery.data
  const showSkeleton = pipelineQuery.isPending && !data
  const hashPending = (data?.hash_index_refresh.pending ?? 0) > 0
  const hashWorkerDown = data ? !data.worker_health.hash_index_refresh?.ok : false
  const lastRun = data?.hash_index_refresh.last_run

  return (
    <section className="space-y-16">
      <header className="grid gap-10 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
        <div>
          <Micro>Operations</Micro>
          <h2 className="mt-4 max-w-md font-display text-[3.25rem] font-medium leading-[1.02] tracking-tight text-ink sm:text-[3.75rem]">
            DROP
            <br />
            pipeline
          </h2>
        </div>
        <div className="border-l border-line pl-5">
          <p className="max-w-sm text-sm leading-relaxed text-ink-soft">
            Super-admin console for CA DROP download → land → promote → match → matching review →
            fulfill. Counts and ids only.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            {PIPELINE_STAGES.map((stage) => (
              <span
                key={stage}
                className="glass px-2.5 py-1 font-mono text-[0.65rem] uppercase tracking-[0.08em] text-ink-soft"
              >
                {stage}
              </span>
            ))}
          </div>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
        <div className="taste-panel-soft flex flex-col gap-6 p-6 sm:p-7">
          <div>
            <Micro>Actions</Micro>
            <p className="mt-2 max-w-sm text-sm text-ink-soft">
              Run one step at a time. Results stay on this page — ids and counts only.
            </p>
          </div>

          <div className="flex flex-col gap-2">
            {ACTIONS.map((action, index) => {
              const busy =
                actionMutation.isPending && actionMutation.variables === action.key
              return (
                <button
                  key={action.key}
                  type="button"
                  className={
                    index === 0
                      ? 'taste-btn-primary w-full justify-between gap-3 text-left'
                      : 'taste-btn w-full justify-between gap-3 text-left'
                  }
                  disabled={actionMutation.isPending || showSkeleton}
                  onClick={() => actionMutation.mutate(action.key)}
                >
                  <span>{action.label}</span>
                  {busy ? (
                    <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                  ) : (
                    <span className="font-mono text-[0.65rem] opacity-50">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                  )}
                </button>
              )
            })}
          </div>

          {(lastAction || actionResult) && (
            <pre className="overflow-x-auto rounded-lg border border-line bg-paper-raised p-3 text-xs text-ink-soft">
              {lastAction ? `# ${lastAction}\n` : ''}
              {actionResult ?? ''}
            </pre>
          )}
        </div>

        <AtmospherePanel data={data} />
      </div>

      <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
        <div>
          <Micro>Hash index refresh</Micro>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            Rebuild CA serving marts via dbt, then rematch open not-found DROP requests. Enqueue
            queues an attempt; process claims the worker.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="glass px-2.5 py-1 font-mono text-[0.65rem] uppercase tracking-[0.08em] text-ink-soft">
            State CA
          </span>
          <span className="text-sm text-ink-soft">
            {hashWorkerDown
              ? 'Worker down'
              : hashPending
                ? 'Pending / in-flight'
                : lastRun
                  ? `Last ${lastRun.status}`
                  : 'None'}
          </span>
          {lastRun?.status === 'success' && (
            <span className="text-sm text-ink-soft">
              rows e/p/n {lastRun.rows_email ?? '—'}/{lastRun.rows_phone ?? '—'}/
              {lastRun.rows_ndz ?? '—'} · rematch {lastRun.rematch_enqueued_count}
            </span>
          )}
          {lastRun?.status && lastRun.status !== 'success' && lastRun.error_message && (
            <span className="text-sm text-red-700">{lastRun.error_message}</span>
          )}
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:gap-3">
          <button
            type="button"
            className="taste-btn"
            disabled={
              showSkeleton || hashPending || hashIndexMutation.isPending || actionMutation.isPending
            }
            onClick={() => hashIndexMutation.mutate('enqueue')}
          >
            Enqueue refresh
          </button>
          <button
            type="button"
            className="taste-btn"
            disabled={showSkeleton || hashIndexMutation.isPending || actionMutation.isPending}
            onClick={() => hashIndexMutation.mutate('process')}
          >
            Process refresh
          </button>
        </div>
      </div>

      {showSkeleton && (
        <div className="taste-panel p-6" role="status" aria-label="Loading pipeline status">
          <SkeletonLines lines={5} />
        </div>
      )}

      {pipelineQuery.isError && !data && (
        <p className="text-sm text-red-700">
          Could not load DROP pipeline status. Is admin-api running with DATABASE_URL?
        </p>
      )}

      {data && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Link
              to="/approvals/matching-review"
              className="taste-panel block p-5 transition hover:border-habeas-mid/40"
            >
              <Micro>Matching review</Micro>
              <p className="mt-3 font-display text-3xl text-ink">{data.matching_review.pending}</p>
              <p className="mt-1 text-xs text-mute">{data.matching_review.approved} approved</p>
            </Link>
            <div className="taste-panel p-5">
              <Micro>Matching attempts</Micro>
              <p className="mt-3 font-display text-3xl text-ink">{data.matching_attempts.pending}</p>
              <p className="mt-1 text-xs text-mute">{data.matching_attempts.success} success</p>
            </div>
            <div className="taste-panel p-5">
              <Micro>DROP requests</Micro>
              <p className="mt-3 font-display text-3xl text-ink">{data.drop_requests.count}</p>
              <p className="mt-1 text-xs text-mute">intake_source=drop</p>
            </div>
          </div>

          <div className="space-y-3">
            <Micro>Worker health</Micro>
            <div className="taste-panel overflow-x-auto px-2 py-1">
              <table className="taste-table">
                <thead>
                  <tr>
                    <th>Worker</th>
                    <th>Health</th>
                    <th>Code</th>
                    <th>URL</th>
                  </tr>
                </thead>
                <tbody>
                  {WORKER_ORDER.map((name) => {
                    const probe = data.worker_health[name]
                    if (!probe) {
                      return (
                        <tr key={name}>
                          <td className="font-mono text-xs">{name}</td>
                          <td colSpan={3} className="text-mute">
                            —
                          </td>
                        </tr>
                      )
                    }
                    return <WorkerHealthRow key={name} probe={probe} />
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <div className="space-y-3">
              <Micro>Connector attempts</Micro>
              <div className="taste-panel-soft p-4">
                <CountTable rows={data.connector_attempts} empty="No connector attempts." />
              </div>
            </div>
            <div className="space-y-3">
              <Micro>Ingest attempts</Micro>
              <div className="taste-panel-soft p-4">
                <CountTable rows={data.ingest_attempts} empty="No ingest attempts." />
              </div>
            </div>
          </div>

          <div className="space-y-3">
            <Micro>Raw by list type</Micro>
            <div className="taste-panel overflow-x-auto px-2 py-1">
              {data.raw_requests_by_list_type.length === 0 ? (
                <p className="p-4 text-sm text-ink-soft">No drop_raw_requests rows.</p>
              ) : (
                <table className="taste-table">
                  <thead>
                    <tr>
                      <th>List type</th>
                      <th>Total</th>
                      <th>response_status null</th>
                      <th>response_status set</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.raw_requests_by_list_type.map((row) => (
                      <tr key={row.list_type}>
                        <td className="font-mono text-xs">{row.list_type}</td>
                        <td className="tabular-nums">{row.total}</td>
                        <td className="tabular-nums">{row.response_status_null}</td>
                        <td className="tabular-nums">{row.response_status_set}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          <div className="space-y-3">
            <Micro>Recent DROP requests</Micro>
            <div className="taste-panel overflow-x-auto px-2 py-1">
              {data.drop_requests.recent.length === 0 ? (
                <p className="p-4 text-sm text-ink-soft">No DROP thin requests yet.</p>
              ) : (
                <table className="taste-table">
                  <thead>
                    <tr>
                      <th>Received</th>
                      <th>Request ID</th>
                      <th>Raw record</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.drop_requests.recent.map((row) => (
                      <tr key={row.id}>
                        <td>
                          {row.received_at ? new Date(row.received_at).toLocaleString() : '—'}
                        </td>
                        <td className="font-mono text-xs">{row.id}</td>
                        <td className="tabular-nums">{row.raw_record_id ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          <div className="space-y-3">
            <Micro>Matching results</Micro>
            <div className="taste-panel overflow-x-auto px-2 py-1">
              {data.matching_results_recent.length === 0 ? (
                <p className="p-4 text-sm text-ink-soft">No matching results for DROP requests.</p>
              ) : (
                <table className="taste-table">
                  <thead>
                    <tr>
                      <th>Recorded</th>
                      <th>Request ID</th>
                      <th>Matched</th>
                      <th>Count</th>
                      <th>Via</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.matching_results_recent.map((row) => (
                      <tr key={`${row.request_id}-${row.recorded_at}`}>
                        <td>
                          {row.recorded_at ? new Date(row.recorded_at).toLocaleString() : '—'}
                        </td>
                        <td className="font-mono text-xs">{row.request_id}</td>
                        <td>
                          <span className={row.matched ? 'text-emerald-700' : 'text-mute'}>
                            {row.matched ? 'yes' : 'no'}
                          </span>
                        </td>
                        <td className="tabular-nums">{row.match_count}</td>
                        <td className="font-mono text-xs">{row.matched_via}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  )
}
