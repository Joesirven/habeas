/**
 * Dev lab: `/dev/drop-prod-cutover` — temporary, in Pipeline ▾ submenu (temp).
 *
 * impl-06 UX / API contract (`@/lib/api` — already present; do not invent a second client):
 *
 *   saveDropProdApiKey({ api_key: string })
 *     POST /ops/drop/prod/key
 *     → { status: string, configured: boolean }
 *     Never echo the key. Body field is `api_key`. Super_admin only — do not weaken.
 *
 *   confirmDropProdRun({ confirm: true })
 *     POST /ops/drop/prod/confirm-run
 *     → { status: string, process_id?: number | null, run_id?: string | null }
 *     `confirm: true` is required. Queues download → land → promote → dispatch → Data ensure-drain.
 *     Super_admin only — do not weaken.
 *
 *   getDropProdRunStatus()
 *     GET /ops/drop/prod/status
 *     → { status: string, configured?: boolean, process_id?: number | null, run_id?: string | null }
 *     Optional extra JSON (`stages[]`, `counts`) is rendered if present. No query arg.
 *
 * Monitor also polls `getDropPipeline()` (`GET /ops/drop/pipeline`) for ids/counts/stages
 * after Confirm — plan snapshot, ids/counts only. No PII.
 *
 * Router (impl-06, already wired): lazy `DropProdCutoverLabPage` (named or default)
 * at `/dev/drop-prod-cutover`. Temporary nav: Pipeline ▾ → DROP prod cutover.
 *
 * Scope: Cassandra off · Data matching only · People/HR later · no DROP upload/amend.
 * Feedback: action toasts only. No PII in copy.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { actionToast } from '@/lib/action-toast'
import {
  confirmDropProdRun,
  getDropPipeline,
  getDropProdRunStatus,
  saveDropProdApiKey,
  type DropPipelineStatus,
  type DropProdRunStatus,
  type StepStatusCount,
} from '@/lib/api'
import { canAccessOpsSurfaces, useMe } from '@/lib/auth'

const STATUS_QUERY_KEY = ['lab', 'drop-prod-cutover', 'status'] as const
const PIPELINE_QUERY_KEY = ['lab', 'drop-prod-cutover', 'pipeline'] as const
const RUN_TOAST_ID = 'lab-drop-prod-cutover-run'

const CUTOVER_STAGES = [
  { name: 'download', label: 'Download ZIP' },
  { name: 'land', label: 'Land (unzip)' },
  { name: 'promote', label: 'Promote to raw' },
  { name: 'dispatch', label: 'Dispatch' },
  { name: 'data_ensure_drain', label: 'Data ensure-drain' },
] as const

type StageName = (typeof CUTOVER_STAGES)[number]['name']

type OptionalStage = {
  name: string
  status?: string
  attempt_id?: number | string | null
  count?: number | null
}

const ACTIVE_STATUSES = new Set(['queued', 'running', 'in_progress', 'pending', 'started'])
/** Do not treat generic `ok` as a finished run — status endpoints often use it for idle. */
const SUCCESS_STATUSES = new Set(['succeeded', 'success', 'completed', 'finished'])
const FAILURE_STATUSES = new Set(['failed', 'error', 'cancelled', 'canceled'])

function normalizeStatus(value: string | undefined | null): string {
  return (value ?? '').trim().toLowerCase()
}

function isActiveStatus(status: string | undefined | null): boolean {
  return ACTIVE_STATUSES.has(normalizeStatus(status))
}

function isSuccessStatus(status: string | undefined | null): boolean {
  return SUCCESS_STATUSES.has(normalizeStatus(status))
}

function isFailureStatus(status: string | undefined | null): boolean {
  return FAILURE_STATUSES.has(normalizeStatus(status))
}

function statusBadgeVariant(
  status: string | undefined | null,
): 'ok' | 'fail' | 'run' | 'wait' {
  if (isSuccessStatus(status)) return 'ok'
  if (isFailureStatus(status)) return 'fail'
  if (isActiveStatus(status)) return 'run'
  return 'wait'
}

function formatId(value: string | number | null | undefined): string {
  if (value == null || value === '') return '—'
  return String(value)
}

function formatCount(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return String(value)
}

function readOptionalStages(data: DropProdRunStatus | undefined): OptionalStage[] {
  if (data == null) return []
  const extra = data as DropProdRunStatus & { stages?: unknown }
  if (!Array.isArray(extra.stages)) return []
  return extra.stages.flatMap((row) => {
    if (typeof row !== 'object' || row == null || !('name' in row)) return []
    const name = (row as { name: unknown }).name
    if (typeof name !== 'string' || !name.trim()) return []
    const status =
      'status' in row && typeof (row as { status: unknown }).status === 'string'
        ? (row as { status: string }).status
        : undefined
    const attemptRaw =
      'attempt_id' in row ? (row as { attempt_id: unknown }).attempt_id : undefined
    const attempt_id =
      typeof attemptRaw === 'number' || typeof attemptRaw === 'string' ? attemptRaw : null
    const countRaw = 'count' in row ? (row as { count: unknown }).count : undefined
    const count = typeof countRaw === 'number' && Number.isFinite(countRaw) ? countRaw : null
    return [{ name, status, attempt_id, count }]
  })
}

function readOptionalCounts(
  data: DropProdRunStatus | undefined,
): Record<string, number> {
  if (data == null) return {}
  const extra = data as DropProdRunStatus & { counts?: unknown }
  if (typeof extra.counts !== 'object' || extra.counts == null || Array.isArray(extra.counts)) {
    return {}
  }
  const out: Record<string, number> = {}
  for (const [key, value] of Object.entries(extra.counts)) {
    if (typeof value === 'number' && Number.isFinite(value)) out[key] = value
  }
  return out
}

function stageRow(
  name: StageName,
  optional: OptionalStage[],
  counts: Record<string, number>,
): OptionalStage {
  const match = optional.find((row) => normalizeStatus(row.name) === name)
  return {
    name,
    status: match?.status,
    attempt_id: match?.attempt_id ?? null,
    count: match?.count ?? counts[name] ?? null,
  }
}

function CutoverAccessEmptyState({
  identityError,
  role,
}: {
  identityError: boolean
  role: string | undefined
}) {
  return (
    <section className="mx-auto max-w-3xl space-y-5">
      <header className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-slate-500">
          Dev lab · Pipeline ▾ (temp)
        </p>
        <h1 className="text-xl font-semibold text-slate-900">DROP prod cutover</h1>
      </header>
      <div className="rounded-md border border-slate-200 bg-white p-4 space-y-2">
        <p className="text-sm font-medium text-slate-900">
          Needs super_admin / IAP Habeas login
        </p>
        <p className="text-sm leading-relaxed text-slate-600">
          {identityError
            ? 'Identity did not load. Sign in through Identity-Aware Proxy with a Habeas account (@habeas.us), then reload this page.'
            : 'This lab is under Pipeline ▾ (temporary). Confirm run and Save key stay super_admin. Sign in via IAP as Habeas, then open this page again.'}
        </p>
        {role ? (
          <p className="font-mono text-[11px] text-slate-500">role={role}</p>
        ) : null}
      </div>
    </section>
  )
}

function pipelineCountRows(pipeline: DropPipelineStatus | undefined): StepStatusCount[] {
  if (pipeline == null) return []
  return [
    ...pipeline.connector_attempts.map((row) => ({
      step: `download · ${row.step}`,
      status: row.status,
      count: row.count,
    })),
    ...pipeline.ingest_attempts.map((row) => ({
      step: `ingest · ${row.step}`,
      status: row.status,
      count: row.count,
    })),
    ...pipeline.matching_attempts.by_status.map((row) => ({
      step: 'matching',
      status: row.status,
      count: row.count,
    })),
  ]
}

export function DropProdCutoverLabPage() {
  const me = useMe()
  const queryClient = useQueryClient()
  const opsOk = canAccessOpsSurfaces(me.role)

  const [apiKey, setApiKey] = useState('')
  const [keySavedThisSession, setKeySavedThisSession] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [monitorArmed, setMonitorArmed] = useState(false)
  const toastedRunRef = useRef<string | null>(null)

  const statusQuery = useQuery({
    queryKey: STATUS_QUERY_KEY,
    queryFn: getDropProdRunStatus,
    enabled: opsOk,
    refetchInterval: (query) =>
      monitorArmed || isActiveStatus(query.state.data?.status) ? 4_000 : false,
  })

  const pipelineQuery = useQuery({
    queryKey: PIPELINE_QUERY_KEY,
    queryFn: getDropPipeline,
    enabled:
      opsOk &&
      (monitorArmed ||
        isActiveStatus(statusQuery.data?.status) ||
        statusQuery.data?.process_id != null),
    refetchInterval: () =>
      monitorArmed || isActiveStatus(statusQuery.data?.status) ? 4_000 : false,
  })

  const configured =
    statusQuery.data?.configured === true || keySavedThisSession
  const runStatus = statusQuery.data?.status ?? 'idle'
  const processId = statusQuery.data?.process_id ?? null
  const runId = statusQuery.data?.run_id ?? null
  const optionalStages = readOptionalStages(statusQuery.data)
  const optionalCounts = readOptionalCounts(statusQuery.data)
  const stageRows = CUTOVER_STAGES.map((stage) =>
    stageRow(stage.name, optionalStages, optionalCounts),
  )
  const pipelineRows = pipelineCountRows(pipelineQuery.data)
  const dropRequestCount = pipelineQuery.data?.drop_requests.count
  const matchingPending = pipelineQuery.data?.matching_attempts.pending
  const matchingSuccess = pipelineQuery.data?.matching_attempts.success
  const drainActive = pipelineQuery.data?.matching_attempts.drain?.active

  const saveMutation = useMutation({
    mutationFn: (key: string) => saveDropProdApiKey({ api_key: key }),
    onSuccess: (data) => {
      setApiKey('')
      setKeySavedThisSession(true)
      actionToast.success({
        title: 'DROP prod key saved',
        description: data.configured
          ? 'Secret stored. The key is not shown again.'
          : 'Save accepted. Refresh status if the configured badge stays off.',
      })
      void queryClient.invalidateQueries({ queryKey: STATUS_QUERY_KEY })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not save DROP prod key',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => {
            const next = apiKey.trim()
            if (next) saveMutation.mutate(next)
          },
        },
      })
    },
  })

  const runMutation = useMutation({
    mutationFn: () => confirmDropProdRun({ confirm: true }),
    onSuccess: () => {
      setConfirmOpen(false)
      setMonitorArmed(true)
      toastedRunRef.current = null
      void queryClient.invalidateQueries({ queryKey: STATUS_QUERY_KEY })
      void queryClient.invalidateQueries({ queryKey: PIPELINE_QUERY_KEY })
    },
    onError: () => {
      /* actionToast.promise handles error chrome */
    },
  })

  function confirmRun() {
    void actionToast.promise(runMutation.mutateAsync(), {
      id: RUN_TOAST_ID,
      loading: 'Queuing prod CA DROP cutover…',
      success: (data) => ({
        title: 'Cutover queued',
        description: `run=${formatId(data.run_id)} process=${formatId(data.process_id)}`,
      }),
      error: () => ({
        title: 'Cutover queue failed',
        action: {
          label: 'Retry',
          onClick: confirmRun,
        },
      }),
    })
  }

  useEffect(() => {
    if (!monitorArmed) return
    if (runId == null && processId == null) return
    const key = `${runId ?? ''}:${processId ?? ''}:${normalizeStatus(runStatus)}`
    if (toastedRunRef.current === key) return
    if (isSuccessStatus(runStatus)) {
      toastedRunRef.current = key
      setMonitorArmed(false)
      actionToast.success({
        title: 'Prod DROP run finished',
        description: `run=${formatId(runId)} process=${formatId(processId)}`,
      })
      return
    }
    if (isFailureStatus(runStatus)) {
      toastedRunRef.current = key
      setMonitorArmed(false)
      actionToast.error({
        title: 'Prod DROP run failed',
        description: `run=${formatId(runId)} process=${formatId(processId)}`,
        action: {
          label: 'Retry status',
          onClick: () => {
            void statusQuery.refetch()
          },
        },
      })
    }
  }, [monitorArmed, processId, runId, runStatus, statusQuery])

  if (me.isLoading) {
    return <p className="text-sm text-slate-500">Loading identity…</p>
  }
  if (!opsOk) {
    return <CutoverAccessEmptyState identityError={me.isError} role={me.role} />
  }

  return (
    <section className="mx-auto max-w-3xl space-y-5">
      <header className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-slate-500">
          Dev lab · Pipeline ▾ (temp)
        </p>
        <h1 className="text-xl font-semibold text-slate-900">DROP prod cutover</h1>
        <p className="text-sm leading-relaxed text-slate-600">
          Paste the CA DROP production API key, then confirm the first Data-only pull.
          Mutations go through admin-api. Ids and counts only — no PII.
        </p>
      </header>

      <div className="rounded-md border border-slate-200 bg-white p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500">Key</span>
          {statusQuery.isLoading && !keySavedThisSession ? (
            <Badge variant="wait">Checking…</Badge>
          ) : configured ? (
            <Badge variant="ok">Configured</Badge>
          ) : (
            <Badge variant="fail">Not configured</Badge>
          )}
          <span className="text-xs text-slate-500">Run</span>
          <Badge variant={statusBadgeVariant(runStatus)}>
            {runStatus || 'idle'}
          </Badge>
          <span className="text-xs text-slate-500">Cassandra</span>
          <Badge variant="wait">Off</Badge>
          <span className="text-xs text-slate-500">Matching</span>
          <Badge variant="run">Data only</Badge>
        </div>
        <ul className="text-xs leading-relaxed text-slate-600 space-y-1">
          <li>Cassandra prod writes stay off for this run.</li>
          <li>Data hash matching only. People / HR matching is later, after marts.</li>
          <li>No DROP upload or amend on this cutover.</li>
        </ul>
      </div>

      <ol className="space-y-4">
        <li className="rounded-md border border-slate-200 bg-white p-4 space-y-3">
          <p className="text-sm font-medium text-slate-900">1 · Production API key</p>
          <p className="text-xs text-slate-600">
            Paste the portal <span className="font-mono">X-API-KEY</span>. Stored via
            admin-api Secret Manager. The value is never echoed back.
          </p>
          <input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            aria-label="CA DROP production API key"
            autoComplete="off"
            spellCheck={false}
            placeholder="Paste production key"
            className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-900 outline-none focus:border-habeas-mid focus:ring-1 focus:ring-habeas-mid"
          />
          <Button
            type="button"
            disabled={saveMutation.isPending || !apiKey.trim()}
            onClick={() => {
              const next = apiKey.trim()
              if (!next) {
                actionToast.warning({
                  title: 'API key required',
                  description: 'Paste the production key before saving.',
                })
                return
              }
              saveMutation.mutate(next)
            }}
          >
            {saveMutation.isPending ? 'Saving…' : 'Save key'}
          </Button>
        </li>

        <li className="rounded-md border border-slate-200 bg-white p-4 space-y-3">
          <p className="text-sm font-medium text-slate-900">2 · Confirm run</p>
          <p className="text-xs text-slate-600">
            Queues download → land → promote → dispatch → Data ensure-drain. Explicit
            Confirm in the dialog.
          </p>
          <Button
            type="button"
            disabled={runMutation.isPending}
            onClick={() => {
              if (!configured) {
                actionToast.warning({
                  title: 'DROP prod key required',
                  description: 'Paste and save the production API key first.',
                })
                return
              }
              setConfirmOpen(true)
            }}
          >
            {runMutation.isPending ? 'Queuing…' : 'Confirm run'}
          </Button>
        </li>

        <li className="rounded-md border border-slate-200 bg-white p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-medium text-slate-900">3 · Monitor</p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={statusQuery.isFetching && pipelineQuery.isFetching}
              onClick={() => {
                void statusQuery.refetch()
                void pipelineQuery.refetch()
              }}
            >
              Refresh
            </Button>
          </div>
          <p className="font-mono text-[11px] text-slate-500">
            run={formatId(runId)} process={formatId(processId)}
            {drainActive === true ? ' drain=active' : ''}
          </p>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Stage</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Attempt</TableHead>
                <TableHead className="text-right">Count</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {CUTOVER_STAGES.map((stage, index) => {
                const row = stageRows[index]
                return (
                  <TableRow key={stage.name}>
                    <TableCell className="text-slate-900">{stage.label}</TableCell>
                    <TableCell>
                      <Badge variant={statusBadgeVariant(row.status ?? runStatus)}>
                        {row.status ?? (monitorArmed ? runStatus : 'idle')}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono tabular-nums text-slate-600">
                      {formatId(row.attempt_id)}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums text-slate-700">
                      {formatCount(row.count)}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
          {pipelineRows.length > 0 ? (
            <div className="space-y-2">
              <p className="text-[0.65rem] font-medium uppercase tracking-wide text-slate-500">
                Pipeline snapshot
              </p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Step</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Count</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pipelineRows.map((row, index) => (
                    <TableRow key={`${row.step}:${row.status}:${index}`}>
                      <TableCell className="font-mono text-slate-700">{row.step}</TableCell>
                      <TableCell>
                        <Badge variant={statusBadgeVariant(row.status)}>{row.status}</Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums text-slate-700">
                        {formatCount(row.count)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <p className="font-mono text-[11px] text-slate-500">
                drop_requests={formatCount(dropRequestCount)} matching_pending=
                {formatCount(matchingPending)} matching_success=
                {formatCount(matchingSuccess)}
              </p>
            </div>
          ) : null}
          {statusQuery.isError ? (
            <p className="text-xs text-slate-600">
              Status unavailable.{' '}
              <button
                type="button"
                className="text-habeas-navy underline-offset-2 hover:underline"
                onClick={() => {
                  void statusQuery.refetch()
                }}
              >
                Retry
              </button>
            </p>
          ) : null}
        </li>
      </ol>

      <Dialog
        open={confirmOpen}
        onOpenChange={(open) => {
          if (!open && runMutation.isPending) return
          setConfirmOpen(open)
        }}
      >
        {/* No `relative`: twMerge would override DialogContent `fixed` and park the modal at page bottom. */}
        <DialogContent className="max-w-md overflow-hidden rounded-md border-slate-200">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-1 overflow-hidden bg-slate-100">
            <div
              className={`h-full bg-habeas-navy transition-all duration-500 ${
                runMutation.isPending ? 'w-2/3 animate-pulse' : confirmOpen ? 'w-1/4' : 'w-0'
              }`}
            />
          </div>
          <DialogHeader>
            <DialogTitle className="font-body text-base font-semibold text-slate-900">
              Run prod CA DROP cutover?
            </DialogTitle>
            <DialogDescription>
              Queues download, land, promote, dispatch, and Data ensure-drain through
              admin-api. Cassandra stays off. No upload or amend.
            </DialogDescription>
          </DialogHeader>
          <ol className="space-y-1.5 text-xs text-slate-700">
            {CUTOVER_STAGES.map((stage, index) => (
              <li
                key={stage.name}
                className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5"
              >
                <span className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-200 bg-white text-[0.6rem] font-medium text-slate-500">
                  {index + 1}
                </span>
                {stage.label}
              </li>
            ))}
          </ol>
          {runMutation.isPending ? (
            <p className="text-xs text-habeas-navy" role="status" aria-live="polite">
              Queuing prod CA DROP cutover…
            </p>
          ) : null}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={runMutation.isPending}
              onClick={() => setConfirmOpen(false)}
            >
              Cancel
            </Button>
            <Button type="button" disabled={runMutation.isPending} onClick={confirmRun}>
              {runMutation.isPending ? 'Queuing…' : 'Confirm'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}

export default DropProdCutoverLabPage
