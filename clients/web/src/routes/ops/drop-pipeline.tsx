import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'

import { Skeleton, SkeletonLines } from '@/components/AppShell'
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

type ActionKey = (typeof ACTIONS)[number]['key']

type ActionOutcome =
  | {
      kind: 'success'
      key: ActionKey
      label: string
      response: Record<string, unknown>
    }
  | {
      kind: 'error'
      key: ActionKey | null
      label: string | null
      message: string
    }

/** Cold-start grace: show "warming" instead of "down" until this many ms after first load. */
const WORKER_WARMUP_MS = 45_000

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

function workerDisplayState(
  probe: WorkerHealthProbe | undefined,
  warmingWindow: boolean,
  checking: boolean,
): { label: string; className: string } {
  if (checking && !probe) {
    return { label: 'checking…', className: 'text-slate-400' }
  }
  if (!probe) {
    return { label: 'unknown', className: 'text-slate-500' }
  }
  if (probe.ok) {
    return { label: 'up', className: 'text-emerald-300' }
  }
  // Cold start / spin-up: keep amber until grace expires.
  if (warmingWindow) {
    return { label: 'warming up…', className: 'text-amber-300' }
  }
  return { label: 'down', className: 'text-red-300' }
}

function WorkerHealthRow({
  probe,
  name,
  warmingWindow,
  checking,
}: {
  probe: WorkerHealthProbe | undefined
  name: string
  warmingWindow: boolean
  checking: boolean
}) {
  const state = workerDisplayState(probe, warmingWindow, checking)
  return (
    <tr className="border-b border-slate-800/60 text-slate-200">
      <td className="py-2 pr-4 font-mono text-xs">{probe?.name ?? name}</td>
      <td className="py-2 pr-4">
        <span className={state.className}>{state.label}</span>
      </td>
      <td className="py-2 pr-4 tabular-nums text-slate-400">
        {checking && !probe ? <Skeleton className="h-4 w-8" /> : (probe?.status_code ?? '—')}
      </td>
      <td className="py-2 font-mono text-xs text-slate-500">
        {checking && !probe ? <Skeleton className="h-4 w-48" /> : (probe?.url ?? '—')}
      </td>
    </tr>
  )
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string')
}

function asNumberArray(value: unknown): number[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is number => typeof item === 'number' && Number.isFinite(item))
}

function formatYesNo(value: unknown): string {
  if (value === true) return 'yes'
  if (value === false) return 'no'
  return '—'
}

function statusClassName(status: string): string {
  if (status === 'ok') return 'text-emerald-300'
  if (status === 'idle') return 'text-amber-300'
  if (status === 'error') return 'text-red-300'
  return 'text-slate-300'
}

function summarizeNumericIds(ids: unknown): string {
  const nums = asNumberArray(ids)
  if (nums.length === 0) return 'none'
  const sorted = [...nums].sort((a, b) => a - b)
  const min = sorted[0]
  const max = sorted[sorted.length - 1]
  const range = min === max ? String(min) : `${min}–${max}`
  return `${nums.length} id${nums.length === 1 ? '' : 's'}, ${range}`
}

function summarizeStringIds(ids: unknown, sample = 3): string {
  const list = asStringArray(ids)
  if (list.length === 0) return 'none'
  if (list.length <= sample) return `${list.length} — ${list.join(', ')}`
  return `${list.length} — ${list.slice(0, sample).join(', ')} (+${list.length - sample} more)`
}

function summarizeAttemptIds(ids: unknown): string {
  const nums = asNumberArray(ids)
  if (nums.length === 0) return 'none'
  if (nums.length <= 5) return nums.join(', ')
  return `${nums.length} ids — ${nums.slice(0, 3).join(', ')} (+${nums.length - 3} more)`
}

function ResultRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[10rem_1fr] sm:gap-3">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="text-sm text-slate-200">{children}</dd>
    </div>
  )
}

function StatusValue({ status }: { status: string }) {
  return <span className={statusClassName(status)}>{status}</span>
}

function RawResponseDetails({ response }: { response: Record<string, unknown> }) {
  return (
    <details className="mt-4 rounded-lg border border-slate-800 bg-slate-950/60">
      <summary className="cursor-pointer px-3 py-2 text-xs text-slate-500 hover:text-slate-300">
        Raw response
      </summary>
      <pre className="overflow-x-auto border-t border-slate-800 px-3 py-2 text-xs text-slate-400">
        {JSON.stringify(response, null, 2)}
      </pre>
    </details>
  )
}

function ActionResultCard({
  title,
  children,
  response,
}: {
  title: string
  children: ReactNode
  response: Record<string, unknown>
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-4">
      <h4 className="text-sm font-medium text-white">{title}</h4>
      <dl className="mt-3 space-y-2">{children}</dl>
      <RawResponseDetails response={response} />
    </div>
  )
}

function DownloadResultSummary({ response }: { response: Record<string, unknown> }) {
  const status = asString(response.status) ?? 'unknown'
  const connectorAttemptId = asNumber(response.connector_attempt_id)
  const lists = Array.isArray(response.lists)
    ? response.lists.filter(
        (item): item is Record<string, unknown> =>
          typeof item === 'object' && item !== null && !Array.isArray(item),
      )
    : []

  return (
    <ActionResultCard title="Download ZIP" response={response}>
      <ResultRow label="Status">
        <StatusValue status={status} />
      </ResultRow>
      {asString(response.gcs_uri) && (
        <ResultRow label="GCS URI">
          <span className="break-all font-mono text-xs">{asString(response.gcs_uri)}</span>
        </ResultRow>
      )}
      {connectorAttemptId !== undefined && (
        <ResultRow label="Connector attempt">{connectorAttemptId}</ResultRow>
      )}
      {'land_attempt_ids' in response && (
        <ResultRow label="Land attempts queued">
          {summarizeAttemptIds(response.land_attempt_ids)}
        </ResultRow>
      )}
      <ResultRow label="Lists">
        {lists.length === 0 ? (
          'none'
        ) : (
          <ul className="space-y-1">
            {lists.map((item, index) => {
              const listType = asString(item.list_type)
              return (
              <li key={index} className="font-mono text-xs">
                {asString(item.source_csv_filename) ?? '—'}
                {listType ? (
                  <span className="ml-2 text-slate-500">({listType})</span>
                ) : null}
              </li>
              )
            })}
          </ul>
        )}
      </ResultRow>
    </ActionResultCard>
  )
}

function LandResultSummary({ response }: { response: Record<string, unknown> }) {
  const status = asString(response.status) ?? 'unknown'
  const rowsLanded = asNumber(response.rows_landed)
  const landAttemptId = asNumber(response.land_attempt_id)
  const csvFiles = asStringArray(response.source_csv_filenames)

  return (
    <ActionResultCard title="Land" response={response}>
      <ResultRow label="Status">
        <StatusValue status={status} />
      </ResultRow>
      {rowsLanded !== undefined && <ResultRow label="Rows landed">{rowsLanded}</ResultRow>}
      <ResultRow label="CSV files">
        {csvFiles.length === 0 ? 'none' : csvFiles.join(', ')}
      </ResultRow>
      {landAttemptId !== undefined && (
        <ResultRow label="Land attempt">{landAttemptId}</ResultRow>
      )}
      {'promote_attempt_ids' in response && (
        <ResultRow label="Promote attempts queued">
          {summarizeAttemptIds(response.promote_attempt_ids)}
        </ResultRow>
      )}
      {asBoolean(response.persisted) !== undefined && (
        <ResultRow label="Persisted">{formatYesNo(response.persisted)}</ResultRow>
      )}
      {'raw_record_ids' in response && (
        <ResultRow label="Raw record IDs">{summarizeNumericIds(response.raw_record_ids)}</ResultRow>
      )}
    </ActionResultCard>
  )
}

function PromoteResultSummary({ response }: { response: Record<string, unknown> }) {
  const status = asString(response.status) ?? 'unknown'
  const promoted = asNumber(response.promoted)
  const promoteAttemptId = asNumber(response.promote_attempt_id)
  const matchingAttemptsCreated = asNumber(response.matching_attempts_created)

  return (
    <ActionResultCard title="Promote" response={response}>
      <ResultRow label="Status">
        <StatusValue status={status} />
      </ResultRow>
      {promoted !== undefined && <ResultRow label="Promoted">{promoted}</ResultRow>}
      {'request_ids' in response && (
        <ResultRow label="Request IDs">{summarizeStringIds(response.request_ids)}</ResultRow>
      )}
      {promoteAttemptId !== undefined && (
        <ResultRow label="Promote attempt">{promoteAttemptId}</ResultRow>
      )}
      {matchingAttemptsCreated !== undefined && (
        <ResultRow label="Matching attempts created">{matchingAttemptsCreated}</ResultRow>
      )}
      {'raw_record_ids' in response && (
        <ResultRow label="Raw record IDs">{summarizeNumericIds(response.raw_record_ids)}</ResultRow>
      )}
    </ActionResultCard>
  )
}

function DispatchResultSummary({ response }: { response: Record<string, unknown> }) {
  const status = asString(response.status) ?? 'unknown'
  const enqueued = asNumber(response.enqueued)

  return (
    <ActionResultCard title="Dispatch matching" response={response}>
      <ResultRow label="Status">
        <StatusValue status={status} />
      </ResultRow>
      {enqueued !== undefined && <ResultRow label="Enqueued">{enqueued}</ResultRow>}
      {'request_ids' in response && (
        <ResultRow label="Request IDs">{summarizeStringIds(response.request_ids)}</ResultRow>
      )}
    </ActionResultCard>
  )
}

function MatchResultSummary({ response }: { response: Record<string, unknown> }) {
  const status = asString(response.status) ?? 'unknown'
  const reason = asString(response.reason)
  const attemptId = asNumber(response.attempt_id)
  const requestId = asString(response.request_id)
  const matched = asBoolean(response.matched)
  const resultId = asNumber(response.result_id)

  return (
    <ActionResultCard title="Run matching" response={response}>
      <ResultRow label="Status">
        <StatusValue status={status} />
      </ResultRow>
      {(status === 'error' || status === 'idle') && reason && (
        <ResultRow label="Reason">{reason}</ResultRow>
      )}
      {attemptId !== undefined && <ResultRow label="Attempt ID">{attemptId}</ResultRow>}
      {requestId && (
        <ResultRow label="Request ID">
          <span className="font-mono text-xs">{requestId}</span>
        </ResultRow>
      )}
      {matched !== undefined && <ResultRow label="Matched">{formatYesNo(matched)}</ResultRow>}
      {resultId !== undefined && <ResultRow label="Result ID">{resultId}</ResultRow>}
    </ActionResultCard>
  )
}

function FulfillResultSummary({ response }: { response: Record<string, unknown> }) {
  const status = asString(response.status) ?? 'unknown'
  const fulfilled = asNumber(response.fulfilled)
  const skipped = asNumber(response.skipped)
  const rejected = asNumber(response.rejected)
  const items = Array.isArray(response.items)
    ? response.items.filter(
        (item): item is Record<string, unknown> =>
          typeof item === 'object' && item !== null && !Array.isArray(item),
      )
    : []
  const sample = items.slice(0, 5)

  return (
    <ActionResultCard title="Fulfill" response={response}>
      <ResultRow label="Status">
        <StatusValue status={status} />
      </ResultRow>
      {fulfilled !== undefined && <ResultRow label="Fulfilled">{fulfilled}</ResultRow>}
      {skipped !== undefined && <ResultRow label="Skipped">{skipped}</ResultRow>}
      {rejected !== undefined && <ResultRow label="Rejected">{rejected}</ResultRow>}
      <ResultRow label="Items">
        {items.length === 0 ? (
          'none'
        ) : (
          <div className="space-y-1">
            <p>{items.length} item{items.length === 1 ? '' : 's'}</p>
            <ul className="space-y-1 text-xs text-slate-400">
              {sample.map((item, index) => (
                <li key={index} className="font-mono">
                  {asString(item.request_id) ?? '—'}
                  {asString(item.outcome) ? ` — ${item.outcome}` : ''}
                  {asString(item.reason) ? ` (${item.reason})` : ''}
                </li>
              ))}
              {items.length > sample.length && (
                <li>+{items.length - sample.length} more</li>
              )}
            </ul>
          </div>
        )}
      </ResultRow>
    </ActionResultCard>
  )
}

function GenericResultSummary({
  title,
  response,
}: {
  title: string
  response: Record<string, unknown>
}) {
  const status = asString(response.status)
  const detail = asString(response.detail) ?? asString(response.reason) ?? asString(response.message)

  return (
    <ActionResultCard title={title} response={response}>
      {status && (
        <ResultRow label="Status">
          <StatusValue status={status} />
        </ResultRow>
      )}
      {detail && <ResultRow label="Message">{detail}</ResultRow>}
      {!status && !detail && <ResultRow label="Message">Action completed.</ResultRow>}
    </ActionResultCard>
  )
}

function ActionResultSuccess({
  actionKey,
  label,
  response,
}: {
  actionKey: ActionKey
  label: string
  response: Record<string, unknown>
}) {
  switch (actionKey) {
    case 'download':
      return <DownloadResultSummary response={response} />
    case 'land':
      return <LandResultSummary response={response} />
    case 'promote':
      return <PromoteResultSummary response={response} />
    case 'dispatch':
      return <DispatchResultSummary response={response} />
    case 'match':
      return <MatchResultSummary response={response} />
    case 'fulfill':
      return <FulfillResultSummary response={response} />
    default:
      return <GenericResultSummary title={label} response={response} />
  }
}

function ActionResultLoading({ label }: { label: string | null }) {
  return (
    <div
      className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-4"
      role="status"
      aria-label="Waiting for action result"
    >
      <div className="flex items-center gap-3">
        <span className="inline-block h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-slate-500 border-t-slate-200" />
        <div>
          <p className="text-sm text-slate-200">Waiting on Cloud Run…</p>
          {label && (
            <p className="text-xs text-slate-500">
              {label} — cold starts can take a few seconds
            </p>
          )}
        </div>
      </div>
      <div className="mt-4">
        <SkeletonLines lines={4} />
      </div>
    </div>
  )
}

function ActionResultError({
  label,
  message,
}: {
  label: string | null
  message: string
}) {
  return (
    <div className="rounded-xl border border-red-900/50 bg-red-950/30 px-4 py-4">
      <h4 className="text-sm font-medium text-red-200">
        {label ? `${label} failed` : 'Action failed'}
      </h4>
      <p className="mt-2 text-sm text-red-200/90">{message}</p>
      <p className="mt-2 text-xs text-slate-400">
        Check worker health below. If workers just deployed, wait for cold start and retry.
      </p>
    </div>
  )
}

function PipelineSkeleton() {
  return (
    <div className="space-y-8" role="status" aria-label="Loading DROP pipeline">
      <div className="space-y-3">
        <Skeleton className="h-3 w-24" />
        <div className="flex flex-wrap gap-2">
          {ACTIONS.map((action) => (
            <Skeleton key={action.key} className="h-9 w-32" />
          ))}
        </div>
      </div>
      <div className="space-y-3">
        <Skeleton className="h-3 w-28" />
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-4">
          <SkeletonLines lines={5} />
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-4">
          <SkeletonLines lines={4} />
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-4">
          <SkeletonLines lines={4} />
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        {[0, 1, 2].map((key) => (
          <div key={key} className="rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-4">
            <SkeletonLines lines={3} />
          </div>
        ))}
      </div>
    </div>
  )
}

export function DropPipelinePage() {
  const queryClient = useQueryClient()
  const [lastAction, setLastAction] = useState<string | null>(null)
  const [actionOutcome, setActionOutcome] = useState<ActionOutcome | null>(null)
  const [pageReadyAt] = useState(() => Date.now())
  const [warmingWindow, setWarmingWindow] = useState(true)

  useEffect(() => {
    const remaining = WORKER_WARMUP_MS - (Date.now() - pageReadyAt)
    if (remaining <= 0) {
      setWarmingWindow(false)
      return
    }
    const timer = window.setTimeout(() => setWarmingWindow(false), remaining)
    return () => window.clearTimeout(timer)
  }, [pageReadyAt])

  const pipelineQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-pipeline'],
    queryFn: getDropPipeline,
    refetchInterval: 5_000,
    placeholderData: (previous) => previous,
    retry: 3,
    retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 8_000),
  })

  const actionMutation = useMutation({
    mutationFn: async (key: ActionKey) => {
      const action = ACTIONS.find((item) => item.key === key)
      if (!action) throw new Error(`unknown action ${key}`)
      setLastAction(action.label)
      setActionOutcome(null)
      return action.run()
    },
    onSuccess: (data, key) => {
      const action = ACTIONS.find((item) => item.key === key)
      setActionOutcome({
        kind: 'success',
        key,
        label: action?.label ?? key,
        response: data,
      })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
    },
    onError: (error, key) => {
      const action = ACTIONS.find((item) => item.key === key)
      setActionOutcome({
        kind: 'error',
        key: key ?? null,
        label: action?.label ?? null,
        message: error instanceof Error ? error.message : String(error),
      })
    },
  })

  const data: DropPipelineStatus | undefined = pipelineQuery.data
  const showSkeleton = pipelineQuery.isPending && !data
  const checkingWorkers = pipelineQuery.isPending || pipelineQuery.isFetching

  // All workers up → end warmup early so we do not flash amber after healthy.
  const allWorkersUp =
    !!data &&
    WORKER_ORDER.every((name) => data.worker_health[name]?.ok === true)
  const effectiveWarming = warmingWindow && !allWorkersUp

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
          {ACTIONS.map((action) => {
            const busy =
              actionMutation.isPending && actionMutation.variables === action.key
            return (
              <button
                key={action.key}
                type="button"
                className="inline-flex min-w-32 items-center justify-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 hover:border-slate-500 hover:bg-slate-800 disabled:opacity-50"
                disabled={actionMutation.isPending || showSkeleton}
                onClick={() => actionMutation.mutate(action.key)}
              >
                {busy ? (
                  <>
                    <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-500 border-t-slate-200" />
                    Running…
                  </>
                ) : (
                  action.label
                )}
              </button>
            )
          })}
        </div>
        {(actionMutation.isPending || actionOutcome) && (
          <div className="mt-2">
            {actionMutation.isPending ? (
              <ActionResultLoading label={lastAction} />
            ) : actionOutcome?.kind === 'error' ? (
              <ActionResultError label={actionOutcome.label} message={actionOutcome.message} />
            ) : actionOutcome?.kind === 'success' ? (
              <ActionResultSuccess
                actionKey={actionOutcome.key}
                label={actionOutcome.label}
                response={actionOutcome.response}
              />
            ) : null}
          </div>
        )}
      </div>

      {showSkeleton && <PipelineSkeleton />}

      {pipelineQuery.isError && !data && (
        <div className="rounded-xl border border-red-900/50 bg-red-950/30 p-4 text-red-300">
          <p>Could not load DROP pipeline status.</p>
          <p className="mt-2 text-sm text-red-200/80">
            {pipelineQuery.error instanceof Error
              ? pipelineQuery.error.message
              : String(pipelineQuery.error)}
          </p>
          <p className="mt-2 text-sm text-slate-400">
            If workers just deployed, wait for cold start and retry — status refreshes every 5s.
          </p>
        </div>
      )}

      {data && (
        <>
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-medium uppercase tracking-wide text-slate-400">
                Worker health
              </h3>
              {checkingWorkers && (
                <span className="text-xs text-slate-500">Refreshing…</span>
              )}
            </div>
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
                  {WORKER_ORDER.map((name) => (
                    <WorkerHealthRow
                      key={name}
                      name={name}
                      probe={data.worker_health[name]}
                      warmingWindow={effectiveWarming}
                      checking={checkingWorkers && !data.worker_health[name]}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            {effectiveWarming && !allWorkersUp && (
              <p className="text-xs text-amber-200/80">
                Waiting for Cloud Run instances to become ready before marking workers as down…
              </p>
            )}
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
