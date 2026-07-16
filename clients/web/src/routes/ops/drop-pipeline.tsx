import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  getDropPipeline,
  postDropDispatch,
  postDropDownload,
  postDropFulfill,
  postDropLand,
  postDropMatch,
  postDropPromote,
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
] as const

const ACTIONS = [
  { key: 'download', label: 'Download ZIP', run: () => postDropDownload() },
  { key: 'land', label: 'Land', run: () => postDropLand() },
  { key: 'promote', label: 'Promote', run: () => postDropPromote() },
  { key: 'dispatch', label: 'Dispatch matching', run: () => postDropDispatch() },
  { key: 'match', label: 'Run matching', run: () => postDropMatch() },
  { key: 'fulfill', label: 'Fulfill', run: () => postDropFulfill() },
] as const

function CountTable({ rows, empty }: { rows: StepStatusCount[]; empty: string }) {
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">{empty}</p>
  }
  return (
    <table className="min-w-full text-left text-sm">
      <thead className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th className="py-2 pr-4">Step</th>
          <th className="py-2 pr-4">Status</th>
          <th className="py-2">Count</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.step}-${row.status}`} className="border-b border-slate-800/60 text-slate-200">
            <td className="py-2 pr-4 font-mono text-xs">{row.step}</td>
            <td className="py-2 pr-4">{row.status}</td>
            <td className="py-2 tabular-nums">{row.count}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function WorkerHealthRow({ probe }: { probe: WorkerHealthProbe }) {
  return (
    <tr className="border-b border-slate-800/60 text-slate-200">
      <td className="py-2 pr-4 font-mono text-xs">{probe.name}</td>
      <td className="py-2 pr-4">
        <span className={probe.ok ? 'text-emerald-300' : 'text-red-300'}>
          {probe.ok ? 'up' : 'down'}
        </span>
      </td>
      <td className="py-2 pr-4 tabular-nums text-slate-400">{probe.status_code ?? '—'}</td>
      <td className="py-2 font-mono text-xs text-slate-500">{probe.url}</td>
    </tr>
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
  })

  const actionMutation = useMutation({
    mutationFn: async (key: (typeof ACTIONS)[number]['key']) => {
      const action = ACTIONS.find((item) => item.key === key)
      if (!action) throw new Error(`unknown action ${key}`)
      setLastAction(action.label)
      return action.run()
    },
    onSuccess: (data) => {
      setActionResult(JSON.stringify(data))
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
    },
    onError: (error) => {
      setActionResult(error instanceof Error ? error.message : String(error))
    },
  })

  const data: DropPipelineStatus | undefined = pipelineQuery.data

  return (
    <section className="space-y-8">
      <div>
        <h2 className="text-2xl font-semibold text-white">DROP pipeline</h2>
        <p className="mt-2 max-w-2xl text-slate-400">
          Super-admin console for CA DROP download → land → promote → match → fulfill. Counts and
          ids only — no personally identifiable information.
        </p>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">Actions</h3>
        <div className="flex flex-wrap gap-2">
          {ACTIONS.map((action) => (
            <button
              key={action.key}
              type="button"
              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 hover:border-slate-500 hover:bg-slate-800 disabled:opacity-50"
              disabled={actionMutation.isPending}
              onClick={() => actionMutation.mutate(action.key)}
            >
              {action.label}
            </button>
          ))}
        </div>
        {(lastAction || actionResult) && (
          <pre className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-950/80 p-3 text-xs text-slate-300">
            {lastAction ? `# ${lastAction}\n` : ''}
            {actionResult ?? ''}
          </pre>
        )}
      </div>

      {pipelineQuery.isPending && <p className="text-slate-300">Loading pipeline status…</p>}
      {pipelineQuery.isError && (
        <p className="text-red-300">
          Could not load DROP pipeline status. Is admin-api running with DATABASE_URL?
        </p>
      )}

      {data && (
        <>
          <div className="space-y-3">
            <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">
              Worker health
            </h3>
            <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-2">
              <table className="min-w-full text-left text-sm">
                <thead className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="py-2 pr-4">Worker</th>
                    <th className="py-2 pr-4">Health</th>
                    <th className="py-2 pr-4">Code</th>
                    <th className="py-2">URL</th>
                  </tr>
                </thead>
                <tbody>
                  {WORKER_ORDER.map((name) => {
                    const probe = data.worker_health[name]
                    if (!probe) {
                      return (
                        <tr key={name} className="border-b border-slate-800/60 text-slate-500">
                          <td className="py-2 pr-4 font-mono text-xs">{name}</td>
                          <td className="py-2" colSpan={3}>
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
              <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">
                Connector attempts
              </h3>
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3">
                <CountTable rows={data.connector_attempts} empty="No connector attempts." />
              </div>
            </div>
            <div className="space-y-3">
              <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">
                Ingest attempts
              </h3>
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3">
                <CountTable rows={data.ingest_attempts} empty="No ingest attempts." />
              </div>
            </div>
          </div>

          <div className="space-y-3">
            <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">
              Raw by list type
            </h3>
            <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-2">
              {data.raw_requests_by_list_type.length === 0 ? (
                <p className="py-2 text-sm text-slate-500">No drop_raw_requests rows.</p>
              ) : (
                <table className="min-w-full text-left text-sm">
                  <thead className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="py-2 pr-4">List type</th>
                      <th className="py-2 pr-4">Total</th>
                      <th className="py-2 pr-4">response_status null</th>
                      <th className="py-2">response_status set</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.raw_requests_by_list_type.map((row) => (
                      <tr
                        key={row.list_type}
                        className="border-b border-slate-800/60 text-slate-200"
                      >
                        <td className="py-2 pr-4 font-mono text-xs">{row.list_type}</td>
                        <td className="py-2 pr-4 tabular-nums">{row.total}</td>
                        <td className="py-2 pr-4 tabular-nums">{row.response_status_null}</td>
                        <td className="py-2 tabular-nums">{row.response_status_set}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <div className="space-y-2 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3">
              <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">
                Matching attempts
              </h3>
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <dt className="text-xs text-slate-500">Pending</dt>
                  <dd className="text-lg tabular-nums text-amber-200">
                    {data.matching_attempts.pending}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Success</dt>
                  <dd className="text-lg tabular-nums text-emerald-300">
                    {data.matching_attempts.success}
                  </dd>
                </div>
              </dl>
            </div>
            <div className="space-y-2 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3">
              <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">
                Matching review
              </h3>
              <dl className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <dt className="text-xs text-slate-500">Pending</dt>
                  <dd className="text-lg tabular-nums text-amber-200">
                    {data.matching_review.pending}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Approved</dt>
                  <dd className="text-lg tabular-nums text-emerald-300">
                    {data.matching_review.approved}
                  </dd>
                </div>
              </dl>
            </div>
            <div className="space-y-2 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3">
              <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">
                DROP requests
              </h3>
              <p className="text-lg tabular-nums text-white">{data.drop_requests.count}</p>
              <p className="text-xs text-slate-500">intake_source=drop</p>
            </div>
          </div>

          <div className="space-y-3">
            <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">
              Recent DROP requests
            </h3>
            <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-2">
              {data.drop_requests.recent.length === 0 ? (
                <p className="py-2 text-sm text-slate-500">No DROP thin requests yet.</p>
              ) : (
                <table className="min-w-full text-left text-sm">
                  <thead className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="py-2 pr-4">Received</th>
                      <th className="py-2 pr-4">Request ID</th>
                      <th className="py-2">Raw record</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.drop_requests.recent.map((row) => (
                      <tr key={row.id} className="border-b border-slate-800/60 text-slate-200">
                        <td className="py-2 pr-4">
                          {row.received_at ? new Date(row.received_at).toLocaleString() : '—'}
                        </td>
                        <td className="py-2 pr-4 font-mono text-xs">{row.id}</td>
                        <td className="py-2 tabular-nums">{row.raw_record_id ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          <div className="space-y-3">
            <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">
              Matching results
            </h3>
            <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-2">
              {data.matching_results_recent.length === 0 ? (
                <p className="py-2 text-sm text-slate-500">No matching results for DROP requests.</p>
              ) : (
                <table className="min-w-full text-left text-sm">
                  <thead className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="py-2 pr-4">Recorded</th>
                      <th className="py-2 pr-4">Request ID</th>
                      <th className="py-2 pr-4">Matched</th>
                      <th className="py-2">Via</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.matching_results_recent.map((row) => (
                      <tr
                        key={`${row.request_id}-${row.recorded_at}`}
                        className="border-b border-slate-800/60 text-slate-200"
                      >
                        <td className="py-2 pr-4">
                          {row.recorded_at ? new Date(row.recorded_at).toLocaleString() : '—'}
                        </td>
                        <td className="py-2 pr-4 font-mono text-xs">{row.request_id}</td>
                        <td className="py-2 pr-4">
                          <span className={row.matched ? 'text-emerald-300' : 'text-slate-400'}>
                            {row.matched ? 'yes' : 'no'}
                          </span>
                        </td>
                        <td className="py-2 font-mono text-xs">{row.matched_via}</td>
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
