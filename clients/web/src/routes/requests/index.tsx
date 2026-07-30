import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useMemo, useState } from 'react'

import { Skeleton } from '@/components/AppShell'
import {
  RequestDetailOverlay,
  useRequestDetailOverlay,
} from '@/components/requests/RequestDetailOverlay'
import { LegalChromeActions } from '@/components/UploadMenu'
import { Badge } from '@/components/ui/badge'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  getDropGlobalStats,
  getNeedsAttention,
  listRequests,
  type IntakeSource,
  type RequestRecord,
} from '@/lib/api'
import { isLegalAdminPersona, useMe } from '@/lib/auth'
import { cn } from '@/lib/utils'
import type { RequestsSearch } from '@/router'

/** Flat view — one server page of requests per screen. */
const REQUESTS_PAGE_SIZE = 30
/**
 * Batch view — server still paginates *requests*, not batches (batches can span
 * pages). A wider request window keeps most real intake batches on one screen;
 * Prev/Next moves the underlying request window ("Requests 1–100 of T"), and
 * batch rows are simply whatever lands inside that window.
 */
const BATCH_WINDOW_SIZE = 100

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

const SOURCE_OPTIONS: { value: '' | IntakeSource; label: string }[] = [
  { value: '', label: 'All sources' },
  { value: 'drop', label: 'CA DROP' },
  { value: 'webform', label: 'Gravity Forms' },
  { value: 'csv', label: 'Authorized Agent' },
  { value: 'manual', label: 'Manual' },
]

const VIEW_MODE_SESSION_KEY = 'requests-view-mode'

const FLAT_REQUESTS_TABLE_CLASS =
  'taste-table table-fixed min-w-[720px] w-full text-xs leading-snug [&_th]:!px-2.5 [&_th]:!py-1.5 [&_th]:whitespace-nowrap [&_td]:!px-2.5 [&_td]:!py-1.5 [&_td]:whitespace-nowrap'

const BATCH_REQUESTS_TABLE_CLASS =
  'taste-table table-fixed min-w-[520px] w-full text-xs leading-snug [&_th]:!px-2.5 [&_th]:!py-1 [&_th]:whitespace-nowrap [&_td]:!px-2.5 [&_td]:!py-1 [&_td]:whitespace-nowrap'

type ViewMode = 'flat' | 'batch'

type RequestBatch = {
  batchKey: string
  intakeSource: IntakeSource
  sourceLabel: string
  /** Most recent `received_at` in the cluster — used for sort/display. */
  receivedAt: string
  /** Earliest `received_at` in the cluster — used to build the drill-in window. */
  receivedAtStart: string
  requests: RequestRecord[]
}

function readViewMode(): ViewMode {
  try {
    return sessionStorage.getItem(VIEW_MODE_SESSION_KEY) === 'batch' ? 'batch' : 'flat'
  } catch {
    return 'flat'
  }
}

function requestRowLabel(request: RequestRecord): string {
  const channel = SOURCE_LABELS[request.intake_source] ?? request.intake_source
  if (request.intake_source === 'drop') {
    return `${request.id} · ${channel}`
  }
  return request.display_label?.trim() || request.id
}

function formatRequestReceivedAt(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

/**
 * Drill-in window spanning the whole batch cluster (not just one minute) — computed from
 * epoch ms so it's timezone-safe regardless of how `received_at` is formatted, with a small
 * buffer on each edge to guard against clock/precision rounding at the cluster boundary.
 */
function batchReceivedWindow(
  receivedAtStart: string,
  receivedAtEnd: string,
): { received_after: string; received_before: string } {
  const startMs = new Date(receivedAtStart).getTime()
  const endMs = new Date(receivedAtEnd).getTime()
  if (Number.isNaN(startMs) || Number.isNaN(endMs)) {
    return { received_after: receivedAtStart, received_before: receivedAtEnd }
  }
  return {
    received_after: new Date(startMs - 1_000).toISOString(),
    received_before: new Date(endMs + 1_000).toISOString(),
  }
}

function summarizeBatchAttention(
  requests: RequestRecord[],
  attentionByRequestId: Map<string, string>,
): { flagged: number; label: string } {
  let flagged = 0
  for (const request of requests) {
    if (attentionByRequestId.has(request.id)) flagged++
  }
  if (flagged === 0) return { flagged: 0, label: '—' }
  return { flagged, label: `${flagged} flagged` }
}

function RequestsTableSkeleton({
  rows = 8,
  tableClass = FLAT_REQUESTS_TABLE_CLASS,
}: {
  rows?: number
  tableClass?: string
}) {
  return (
    <table className={tableClass} role="status" aria-label="Loading requests">
      <thead>
        <tr>
          {Array.from({ length: 5 }, (_, index) => (
            <th key={index}>
              <Skeleton className="h-2.5 w-16" />
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, index) => (
          <tr key={index}>
            {Array.from({ length: 5 }, (_, cell) => (
              <td key={cell}>
                <Skeleton className="h-2.5 w-20" />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function StatTile({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="rounded-lg border border-line/80 bg-paper/60 px-4 py-3">
      <p className="taste-micro">{label}</p>
      <p className="mt-1 font-display text-2xl font-medium tabular-nums text-habeas-navy">
        {value}
      </p>
      {hint ? <p className="mt-1 text-[0.65rem] text-mute">{hint}</p> : null}
    </div>
  )
}

function PaginationBar({
  unitLabel,
  start,
  end,
  total,
  currentPage,
  totalPages,
  onPrev,
  onNext,
}: {
  unitLabel: string
  start: number
  end: number
  total: number
  currentPage: number
  totalPages: number
  onPrev: () => void
  onNext: () => void
}) {
  return (
    <div className="flex items-center justify-between gap-2 border-t border-line px-3 py-1.5 text-[0.65rem] text-ink-soft">
      <span className="tabular-nums">
        {total === 0
          ? `No ${unitLabel}`
          : `Showing ${start + 1}–${end} of ${total} ${unitLabel}`}
      </span>
      {totalPages > 1 ? (
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            className="taste-btn h-6 px-2 text-[0.65rem] disabled:cursor-not-allowed disabled:opacity-40"
            onClick={onPrev}
            disabled={currentPage <= 1}
          >
            Previous
          </button>
          <span className="tabular-nums text-mute">
            Page {currentPage} / {totalPages}
          </span>
          <button
            type="button"
            className="taste-btn h-6 px-2 text-[0.65rem] disabled:cursor-not-allowed disabled:opacity-40"
            onClick={onNext}
            disabled={currentPage >= totalPages}
          >
            Next
          </button>
        </div>
      ) : null}
    </div>
  )
}

function matchesFilters(
  request: RequestRecord,
  search: RequestsSearch,
  attentionByRequestId: Map<string, string>,
  ephemeralSearch: string,
): boolean {
  if (search.source && request.intake_source !== search.source) return false
  if (search.source_bucket === 'drop' && request.intake_source !== 'drop') return false
  if (search.source_bucket === 'other' && request.intake_source === 'drop') return false
  if (search.request_type && request.request_type !== search.request_type) return false

  if (search.state) {
    const state = (request.requestor_state ?? '').toUpperCase()
    if (state !== search.state.toUpperCase()) return false
  }

  const needle = ephemeralSearch.trim().toLowerCase()
  if (needle) {
    if (request.id.toLowerCase().includes(needle)) return true
    if (request.intake_source === 'drop') return false
    if (request.display_label?.toLowerCase().includes(needle)) return true
    return false
  }

  if (search.raw === 'yes' && request.raw_record_id == null) return false
  if (search.raw === 'no' && request.raw_record_id != null) return false

  const hasAttention = attentionByRequestId.has(request.id)
  if (search.attention === 'needs' && !hasAttention) return false
  if (search.attention === 'clear' && hasAttention) return false

  if (search.received_after) {
    const after = new Date(search.received_after).getTime()
    if (!Number.isNaN(after) && new Date(request.received_at).getTime() < after) return false
  }
  if (search.received_before) {
    const before = new Date(search.received_before).getTime()
    if (!Number.isNaN(before) && new Date(request.received_at).getTime() > before) return false
  }

  return true
}

const POSTURE_OPTIONS: { value: '' | NonNullable<RequestsSearch['posture']>; label: string }[] = [
  { value: '', label: 'Any posture' },
  { value: 'in_queue', label: 'In queue' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'complete', label: 'Complete' },
]

const DUE_OPTIONS: { value: '' | NonNullable<RequestsSearch['due']>; label: string }[] = [
  { value: '', label: 'Any due' },
  { value: 'overdue', label: 'Overdue' },
  { value: 'due_soon', label: 'Due within 7 days' },
  { value: 'on_track', label: 'On track' },
]

const SOURCE_BUCKET_OPTIONS: { value: '' | NonNullable<RequestsSearch['source_bucket']>; label: string }[] = [
  { value: '', label: 'All intakes' },
  { value: 'drop', label: 'DROP only' },
  { value: 'other', label: 'Non-DROP' },
]

const RAW_OPTIONS: { value: '' | NonNullable<RequestsSearch['raw']>; label: string }[] = [
  { value: '', label: 'Any' },
  { value: 'yes', label: 'Has raw record' },
  { value: 'no', label: 'Missing raw record' },
]

const ATTENTION_OPTIONS: { value: '' | NonNullable<RequestsSearch['attention']>; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'needs', label: 'Needs attention' },
  { value: 'clear', label: 'No flag' },
]

function secondaryFilterCount(search: RequestsSearch): number {
  return [
    search.state,
    search.raw,
    search.posture,
    search.stage,
    search.request_type,
    search.source_bucket,
    search.due,
    search.received_after,
    search.received_before,
  ].filter(Boolean).length
}

function FilterPillSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const selected = options.find((option) => option.value === value)
  const active = Boolean(value)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'inline-flex h-7 max-w-[11rem] items-center gap-1 rounded-md border px-2 text-[0.65rem] font-medium transition-colors',
            active
              ? 'border-habeas-navy/30 bg-habeas-navy/8 text-habeas-navy'
              : 'border-line bg-white text-ink-soft hover:bg-panel/60 hover:text-ink',
          )}
          aria-label={label}
        >
          <span className="text-mute">{label}</span>
          <span className="truncate">{selected?.label ?? 'Any'}</span>
          <span className="text-[0.55rem] opacity-60" aria-hidden>
            ▾
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-48 p-1" align="start">
        <ul className="max-h-56 overflow-y-auto">
          {options.map((option) => {
            const isActive = option.value === value
            return (
              <li key={option.value || '__any'}>
                <button
                  type="button"
                  className={cn(
                    'flex w-full rounded px-2 py-1.5 text-left text-[0.7rem]',
                    isActive
                      ? 'bg-habeas-navy/10 font-medium text-habeas-navy'
                      : 'text-ink hover:bg-panel/60',
                  )}
                  onClick={() => {
                    onChange(option.value)
                    setOpen(false)
                  }}
                >
                  {option.label}
                </button>
              </li>
            )
          })}
        </ul>
      </PopoverContent>
    </Popover>
  )
}

function AttentionFilterPills({
  value,
  onChange,
}: {
  value: RequestsSearch['attention']
  onChange: (attention: RequestsSearch['attention']) => void
}) {
  return (
    <div
      className="inline-flex rounded-md border border-line bg-paper p-0.5"
      role="group"
      aria-label="Attention"
    >
      {ATTENTION_OPTIONS.map((option) => {
        const active = (value ?? '') === option.value
        return (
          <button
            key={option.value || 'all'}
            type="button"
            className={cn(
              'rounded px-2 py-0.5 text-[0.65rem] font-medium transition-colors',
              active
                ? 'bg-habeas-navy/8 text-habeas-navy'
                : 'text-ink-soft hover:text-ink',
            )}
            onClick={() => onChange(option.value || undefined)}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

function MoreFiltersPopover({
  search,
  stateOptions,
  onPatch,
}: {
  search: RequestsSearch
  stateOptions: string[]
  onPatch: (patch: Partial<RequestsSearch>) => void
}) {
  const [open, setOpen] = useState(false)
  const activeCount = secondaryFilterCount(search)
  const [stageDraft, setStageDraft] = useState(search.stage ?? '')
  const [requestTypeDraft, setRequestTypeDraft] = useState(search.request_type ?? '')

  useEffect(() => {
    if (open) {
      setStageDraft(search.stage ?? '')
      setRequestTypeDraft(search.request_type ?? '')
    }
  }, [open, search.stage, search.request_type])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-[0.65rem] font-medium transition-colors',
            activeCount > 0
              ? 'border-habeas-navy/30 bg-habeas-navy/8 text-habeas-navy'
              : 'border-line bg-white text-ink-soft hover:bg-panel/60 hover:text-ink',
          )}
        >
          More filters
          {activeCount > 0 ? (
            <span className="rounded bg-habeas-navy/15 px-1 py-px text-[0.6rem] tabular-nums">
              {activeCount}
            </span>
          ) : null}
          <span className="text-[0.55rem] opacity-60" aria-hidden>
            ▾
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        className="w-72 max-h-[min(28rem,var(--radix-popover-content-available-height))] overflow-y-auto overscroll-contain space-y-3 p-3"
        align="start"
        side="bottom"
        collisionPadding={16}
      >
        <div className="sticky top-0 z-10 -mx-3 -mt-3 mb-0 flex items-center justify-between gap-2 border-b border-line/70 bg-paper px-3 py-2">
          <p className="taste-micro">More filters</p>
          {activeCount > 0 ? (
            <button
              type="button"
              className="taste-link text-[0.65rem]"
              onClick={() => {
                onPatch({
                  state: undefined,
                  raw: undefined,
                  posture: undefined,
                  stage: undefined,
                  request_type: undefined,
                  source_bucket: undefined,
                  due: undefined,
                  received_after: undefined,
                  received_before: undefined,
                })
                setStageDraft('')
                setRequestTypeDraft('')
              }}
            >
              Clear
            </button>
          ) : null}
        </div>
        <div className="grid gap-2">
          <label className="flex flex-col gap-1 text-[0.65rem] text-ink-soft">
            Requestor state
            <select
              className="glass rounded-md px-2 py-1.5 text-xs text-ink"
              value={search.state ?? ''}
              onChange={(event) => onPatch({ state: event.target.value || undefined })}
            >
              <option value="">All states</option>
              {stateOptions.map((state) => (
                <option key={state} value={state}>
                  {state}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[0.65rem] text-ink-soft">
            Raw record
            <select
              className="glass rounded-md px-2 py-1.5 text-xs text-ink"
              value={search.raw ?? ''}
              onChange={(event) =>
                onPatch({
                  raw: (event.target.value || undefined) as RequestsSearch['raw'],
                })
              }
            >
              {RAW_OPTIONS.map((option) => (
                <option key={option.value || 'any'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[0.65rem] text-ink-soft">
            Posture
            <select
              className="glass rounded-md px-2 py-1.5 text-xs text-ink"
              value={search.posture ?? ''}
              onChange={(event) =>
                onPatch({
                  posture: (event.target.value || undefined) as RequestsSearch['posture'],
                })
              }
            >
              {POSTURE_OPTIONS.map((option) => (
                <option key={option.value || 'any'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[0.65rem] text-ink-soft">
            Due
            <select
              className="glass rounded-md px-2 py-1.5 text-xs text-ink"
              value={search.due ?? ''}
              onChange={(event) =>
                onPatch({
                  due: (event.target.value || undefined) as RequestsSearch['due'],
                })
              }
            >
              {DUE_OPTIONS.map((option) => (
                <option key={option.value || 'any'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[0.65rem] text-ink-soft">
            Intake bucket
            <select
              className="glass rounded-md px-2 py-1.5 text-xs text-ink"
              value={search.source_bucket ?? ''}
              onChange={(event) =>
                onPatch({
                  source_bucket: (event.target.value || undefined) as RequestsSearch['source_bucket'],
                })
              }
            >
              {SOURCE_BUCKET_OPTIONS.map((option) => (
                <option key={option.value || 'any'} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[0.65rem] text-ink-soft">
            Stage
            <input
              className="glass rounded-md px-2 py-1.5 text-xs text-ink"
              value={stageDraft}
              placeholder="e.g. matching"
              onChange={(event) => setStageDraft(event.target.value)}
              onBlur={() => onPatch({ stage: stageDraft.trim() || undefined })}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  onPatch({ stage: stageDraft.trim() || undefined })
                  setOpen(false)
                }
              }}
            />
          </label>
          <label className="flex flex-col gap-1 text-[0.65rem] text-ink-soft">
            Request type
            <input
              className="glass rounded-md px-2 py-1.5 text-xs text-ink"
              value={requestTypeDraft}
              placeholder="e.g. delete"
              onChange={(event) => setRequestTypeDraft(event.target.value)}
              onBlur={() => onPatch({ request_type: requestTypeDraft.trim() || undefined })}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  onPatch({ request_type: requestTypeDraft.trim() || undefined })
                  setOpen(false)
                }
              }}
            />
          </label>
          <label className="flex flex-col gap-1 text-[0.65rem] text-ink-soft">
            Received after
            <input
              type="datetime-local"
              className="glass rounded-md px-2 py-1.5 font-mono text-xs text-ink"
              value={search.received_after?.slice(0, 16) ?? ''}
              onChange={(event) => {
                const value = event.target.value
                onPatch({
                  received_after: value ? new Date(value).toISOString() : undefined,
                })
              }}
            />
          </label>
          <label className="flex flex-col gap-1 text-[0.65rem] text-ink-soft">
            Received before
            <input
              type="datetime-local"
              className="glass rounded-md px-2 py-1.5 font-mono text-xs text-ink"
              value={search.received_before?.slice(0, 16) ?? ''}
              onChange={(event) => {
                const value = event.target.value
                onPatch({
                  received_before: value ? new Date(value).toISOString() : undefined,
                })
              }}
            />
          </label>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function RequestsFilterBar({
  search,
  stateOptions,
  ephemeralSearch,
  onEphemeralSearchChange,
  onPatch,
  onClear,
  activeFilterCount,
}: {
  search: RequestsSearch
  stateOptions: string[]
  ephemeralSearch: string
  onEphemeralSearchChange: (value: string) => void
  onPatch: (patch: Partial<RequestsSearch>) => void
  onClear: () => void
  activeFilterCount: number
}) {
  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      role="toolbar"
      aria-label="Request filters"
    >
      <FilterPillSelect
        label="Source"
        value={search.source ?? ''}
        options={SOURCE_OPTIONS}
        onChange={(next) =>
          onPatch({ source: (next || undefined) as RequestsSearch['source'] })
        }
      />
      <AttentionFilterPills
        value={search.attention}
        onChange={(attention) => onPatch({ attention })}
      />
      <input
        type="search"
        className="h-7 min-w-[9rem] flex-1 rounded-md border border-line bg-white px-2 text-xs text-ink placeholder:text-mute sm:max-w-[14rem] sm:flex-none"
        placeholder="Name or request ID"
        aria-label="Search by name or request ID — not saved to URL"
        value={ephemeralSearch}
        onChange={(event) => onEphemeralSearchChange(event.target.value)}
      />
      <MoreFiltersPopover search={search} stateOptions={stateOptions} onPatch={onPatch} />
      {activeFilterCount > 0 ? (
        <button type="button" className="taste-link text-[0.65rem]" onClick={onClear}>
          Clear {activeFilterCount}
        </button>
      ) : null}
    </div>
  )
}

/**
 * Requests arriving within this gap (same intake source) are treated as one intake batch —
 * tolerant of a DROP ingest trickling in over a few minutes, instead of requiring every row
 * share the exact same UTC minute (which fragmented a single real batch into many).
 */
const BATCH_GAP_MS = 3 * 60 * 1000

/** Cluster by source + time-proximity — approximates real intake batches without a true batch id. */
function groupRequestsByBatch(requests: RequestRecord[]): RequestBatch[] {
  const bySource = new Map<IntakeSource, RequestRecord[]>()
  for (const request of requests) {
    const list = bySource.get(request.intake_source)
    if (list) list.push(request)
    else bySource.set(request.intake_source, [request])
  }

  const batches: RequestBatch[] = []
  for (const [intakeSource, sourceRequests] of bySource) {
    const sorted = [...sourceRequests].sort(
      (a, b) => new Date(a.received_at).getTime() - new Date(b.received_at).getTime(),
    )
    let cluster: RequestRecord[] = []
    let clusterEndMs: number | null = null

    const flush = () => {
      if (cluster.length === 0) return
      const earliest = cluster[0]!
      const latest = cluster[cluster.length - 1]!
      batches.push({
        batchKey: `${intakeSource}:${earliest.received_at}`,
        intakeSource,
        sourceLabel: SOURCE_LABELS[intakeSource] ?? intakeSource,
        receivedAt: latest.received_at,
        receivedAtStart: earliest.received_at,
        // Newest-first, matching the row order used everywhere else on this page.
        requests: [...cluster].reverse(),
      })
      cluster = []
    }

    for (const request of sorted) {
      const t = new Date(request.received_at).getTime()
      const gap = clusterEndMs != null && !Number.isNaN(t) ? t - clusterEndMs : 0
      if (gap > BATCH_GAP_MS) flush()
      cluster.push(request)
      if (!Number.isNaN(t)) clusterEndMs = t
    }
    flush()
  }

  return batches.sort(
    (left, right) => new Date(right.receivedAt).getTime() - new Date(left.receivedAt).getTime(),
  )
}

function BatchRows({
  batches,
  attentionByRequestId,
  onDrillIn,
}: {
  batches: RequestBatch[]
  attentionByRequestId: Map<string, string>
  onDrillIn: (batch: RequestBatch) => void
}) {
  return (
    <>
      {batches.map((batch) => {
        const attention = summarizeBatchAttention(batch.requests, attentionByRequestId)
        const batchTitle = `${batch.sourceLabel} · ${formatRequestReceivedAt(batch.receivedAt)}`
        return (
          <tr
            key={batch.batchKey}
            className="group h-10 cursor-pointer border-l-2 border-l-habeas-navy/55 bg-habeas-navy/[0.02] transition-colors hover:bg-habeas-navy/[0.05]"
            onClick={() => onDrillIn(batch)}
            title={`View ${batch.requests.length} requests by request`}
          >
            <td className="w-[8.5rem] tabular-nums text-ink-soft">
              {formatRequestReceivedAt(batch.receivedAt)}
            </td>
            <td className="overflow-hidden">
              <span className="flex min-w-0 items-center gap-2" title={batchTitle}>
                <span
                  className="relative flex h-5 w-6 shrink-0 items-center justify-center"
                  aria-hidden
                >
                  <span className="absolute left-0 top-0.5 h-3.5 w-3.5 rounded border border-habeas-navy/25 bg-habeas-navy/5" />
                  <span className="relative flex h-3.5 w-3.5 items-center justify-center rounded border border-habeas-navy/45 bg-paper text-[0.5rem] font-semibold tabular-nums text-habeas-navy">
                    {batch.requests.length > 99 ? '99+' : batch.requests.length}
                  </span>
                </span>
                <span className="truncate font-medium text-ink">{batchTitle}</span>
              </span>
            </td>
            <td className="w-[6.5rem] overflow-hidden">
              <span
                className="inline-block max-w-full truncate taste-frost-chip px-1.5 py-0.5 text-[0.65rem]"
                title={batch.sourceLabel}
              >
                {batch.sourceLabel}
              </span>
            </td>
            <td className="w-12 tabular-nums font-medium text-habeas-navy">
              {batch.requests.length}
            </td>
            <td className="w-[9rem] overflow-hidden">
              {attention.flagged > 0 ? (
                <Badge
                  variant="fail"
                  className="inline-block max-w-full truncate whitespace-nowrap px-1.5 py-0.5 text-[0.65rem] normal-case tracking-normal"
                  title={attention.label}
                >
                  {attention.label}
                </Badge>
              ) : (
                <span className="text-ink-soft">—</span>
              )}
            </td>
          </tr>
        )
      })}
    </>
  )
}

function RequestRows({
  requests,
  attentionByRequestId,
  onOpen,
}: {
  requests: RequestRecord[]
  attentionByRequestId: Map<string, string>
  onOpen: (requestId: string, trigger?: HTMLElement | null, request?: RequestRecord) => void
}) {
  return (
    <>
      {requests.map((request) => {
        const attentionReason = attentionByRequestId.get(request.id)
        return (
          <tr
            key={request.id}
            className="group h-8 cursor-pointer transition-colors hover:bg-panel/50"
            onClick={(event) => onOpen(request.id, event.currentTarget, request)}
          >
            <td className="w-[8.5rem] tabular-nums text-ink-soft">
              {formatRequestReceivedAt(request.received_at)}
            </td>
            <td className="overflow-hidden">
              <span
                className="block truncate font-mono text-ink"
                title={requestRowLabel(request)}
              >
                {requestRowLabel(request)}
              </span>
            </td>
            <td className="w-[6.5rem] overflow-hidden">
              <span
                className="inline-block max-w-full truncate taste-frost-chip px-1.5 py-0.5 text-[0.65rem]"
                title={SOURCE_LABELS[request.intake_source] ?? request.intake_source}
              >
                {SOURCE_LABELS[request.intake_source] ?? request.intake_source}
              </span>
            </td>
            <td className="w-12 overflow-hidden font-mono text-xs">
              <span className="block truncate" title={request.requestor_state ?? undefined}>
                {request.requestor_state ?? '—'}
              </span>
            </td>
            <td className="w-[9rem] overflow-hidden">
              {attentionReason ? (
                <Badge
                  variant="fail"
                  className="inline-block max-w-full truncate whitespace-nowrap px-1.5 py-0.5 text-[0.65rem] normal-case tracking-normal"
                  title={attentionReason}
                >
                  {attentionReason}
                </Badge>
              ) : (
                <span className="text-ink-soft">—</span>
              )}
            </td>
          </tr>
        )
      })}
    </>
  )
}

export function RequestsPage() {
  const navigate = useNavigate()
  const search = useSearch({ from: '/requests' })
  const { role } = useMe()
  const legalAdmin = isLegalAdminPersona(role)
  const [ephemeralSearch, setEphemeralSearch] = useState('')
  const [viewMode, setViewMode] = useState<ViewMode>(readViewMode)
  const [page, setPage] = useState(1)
  const overlay = useRequestDetailOverlay()

  useEffect(() => {
    try {
      sessionStorage.setItem(VIEW_MODE_SESSION_KEY, viewMode)
    } catch {
      // ignore storage failures
    }
  }, [viewMode])

  const listStage = search.stage
  const pageSize = viewMode === 'batch' ? BATCH_WINDOW_SIZE : REQUESTS_PAGE_SIZE
  const offset = (page - 1) * pageSize

  const requestsQuery = useQuery({
    queryKey: [
      'admin-api',
      'requests',
      search.source ?? 'all',
      search.source_bucket ?? '',
      listStage ?? '',
      search.posture ?? '',
      search.request_type ?? '',
      search.state ?? '',
      search.received_after ?? '',
      search.received_before ?? '',
      ephemeralSearch.trim(),
      pageSize,
      offset,
    ],
    queryFn: () =>
      listRequests({
        intakeSource: search.source,
        sourceBucket: search.source_bucket,
        stage: listStage,
        posture: search.posture,
        requestType: search.request_type,
        requestorState: search.state,
        receivedAfter: search.received_after,
        receivedBefore: search.received_before,
        limit: pageSize,
        offset,
        q: ephemeralSearch.trim().length >= 2 ? ephemeralSearch.trim() : undefined,
      }),
    placeholderData: (previous) => previous,
    refetchInterval: 15_000,
  })

  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention'],
    queryFn: () => getNeedsAttention(200),
    refetchInterval: 15_000,
    staleTime: 10_000,
  })

  const statsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-stats-global'],
    queryFn: getDropGlobalStats,
    refetchInterval: 15_000,
    staleTime: 10_000,
  })

  const attentionByRequestId = useMemo(() => {
    const map = new Map<string, string>()
    for (const item of attentionQuery.data?.items ?? []) {
      map.set(item.request_id, item.reason)
    }
    return map
  }, [attentionQuery.data?.items])

  const requestItems = requestsQuery.data?.items ?? []

  const stateOptions = useMemo(() => {
    const set = new Set<string>()
    for (const request of requestItems) {
      if (request.requestor_state) set.add(request.requestor_state.toUpperCase())
    }
    return [...set].sort()
  }, [requestItems])

  // Source/bucket/type/state/received-window/q are already applied server-side —
  // this only narrows the current page for filters the API doesn't support yet
  // (attention, raw-record presence).
  const filtered = useMemo(() => {
    return requestItems.filter((request) =>
      matchesFilters(request, search, attentionByRequestId, ephemeralSearch),
    )
  }, [requestItems, search, attentionByRequestId, ephemeralSearch])

  const batches = useMemo(() => groupRequestsByBatch(filtered), [filtered])

  const batchStats = useMemo(() => {
    let largest = 0
    let needingAttention = 0
    for (const batch of batches) {
      if (batch.requests.length > largest) largest = batch.requests.length
      if (batch.requests.some((request) => attentionByRequestId.has(request.id))) {
        needingAttention += 1
      }
    }
    return {
      batchCount: batches.length,
      requestCount: filtered.length,
      largest,
      avg: batches.length > 0 ? Math.round(filtered.length / batches.length) : 0,
      needingAttention,
    }
  }, [batches, filtered.length, attentionByRequestId])

  // Reset to page 1 whenever filters, grouping, or search narrow/reshape the visible rows —
  // otherwise a stale page number can land the user on an empty page.
  useEffect(() => {
    setPage(1)
  }, [
    search.source,
    search.source_bucket,
    search.request_type,
    search.stage,
    search.posture,
    search.state,
    search.attention,
    search.due,
    search.raw,
    search.received_after,
    search.received_before,
    ephemeralSearch.trim(),
    viewMode,
  ])

  const pageBatchRows = viewMode === 'batch' ? batches : []
  const pageFlatRows = viewMode === 'flat' ? filtered : []

  // Pagination is server-side on *requests* (both view modes) — batch rows are
  // whatever the current request window groups into, not separately paginated.
  const serverTotal = requestsQuery.data?.total ?? 0
  const serverOffset = requestsQuery.data?.offset ?? offset
  const totalPages = Math.max(1, Math.ceil(serverTotal / pageSize))
  const currentPage = Math.min(Math.max(1, page), totalPages)
  const pageStart = serverTotal === 0 ? 0 : serverOffset
  const pageEnd =
    serverTotal === 0 ? 0 : Math.min(serverOffset + requestItems.length, serverTotal)
  const pageTotal = serverTotal

  function patchSearch(patch: Partial<RequestsSearch>) {
    void navigate({
      to: '/requests',
      search: {
        source: 'source' in patch ? patch.source : search.source,
        source_bucket: 'source_bucket' in patch ? patch.source_bucket : search.source_bucket,
        request_type: 'request_type' in patch ? patch.request_type : search.request_type,
        stage: 'stage' in patch ? patch.stage : search.stage,
        posture: 'posture' in patch ? patch.posture : search.posture,
        state: 'state' in patch ? patch.state : search.state,
        attention: 'attention' in patch ? patch.attention : search.attention,
        due: 'due' in patch ? patch.due : search.due,
        raw: 'raw' in patch ? patch.raw : search.raw,
        received_after: 'received_after' in patch ? patch.received_after : search.received_after,
        received_before:
          'received_before' in patch ? patch.received_before : search.received_before,
      },
      replace: true,
    })
  }

  function clearFilters() {
    void navigate({ to: '/requests', search: {}, replace: true })
  }

  function openTriage(requestId: string, trigger?: HTMLElement | null, request?: RequestRecord) {
    overlay.openOverlay(requestId, trigger, request)
  }

  function drillIntoBatch(batch: RequestBatch) {
    const window = batchReceivedWindow(batch.receivedAtStart, batch.receivedAt)
    // A stale name/id search combined with the new source + date-window filters would
    // otherwise filter the drilled-in list down to nothing.
    setEphemeralSearch('')
    setViewMode('flat')
    void navigate({
      to: '/requests',
      search: {
        source: batch.intakeSource,
        source_bucket: undefined,
        request_type: undefined,
        stage: undefined,
        posture: undefined,
        state: undefined,
        attention: undefined,
        due: undefined,
        raw: undefined,
        received_after: window.received_after,
        received_before: window.received_before,
      },
      replace: true,
    })
  }

  const stats = statsQuery.data
  const activeFilterCount = [
    search.source,
    search.source_bucket,
    search.request_type,
    search.stage,
    search.posture,
    search.state,
    search.attention,
    search.due,
    search.raw,
    search.received_after,
    search.received_before,
  ].filter(Boolean).length

  const flatTableHeader = (
    <thead>
      <tr>
        <th className="w-[8.5rem]">Received</th>
        <th>Request</th>
        <th className="w-[6.5rem]">Source</th>
        <th className="w-12">State</th>
        <th className="w-[9rem]">Attention</th>
      </tr>
    </thead>
  )

  const batchTableHeader = (
    <thead>
      <tr>
        <th className="w-[8.5rem]">Received</th>
        <th>Batch</th>
        <th className="w-[6.5rem]">Source</th>
        <th className="w-12">Count</th>
        <th className="w-[9rem]">Attention</th>
      </tr>
    </thead>
  )

  return (
    <section className="taste-ops-page space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="taste-micro">Requests</p>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              All requests
            </h2>
            {requestsQuery.isFetching && !requestsQuery.isPending && (
              <span className="taste-frost-chip text-[0.65rem]">Refreshing</span>
            )}
            {requestsQuery.isSuccess ? (
              <span className="taste-frost-chip tabular-nums text-[0.65rem]">
                {filtered.length}
                {filtered.length !== requestItems.length ? ` / ${requestItems.length}` : ''}{' '}
                on this page · {serverTotal} total
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-[0.65rem] text-ink-soft">
            <span className="uppercase tracking-wide text-mute">Batch</span>
            <button
              type="button"
              role="switch"
              aria-checked={viewMode === 'batch'}
              aria-label="Group all requests by intake batch"
              title={
                viewMode === 'batch'
                  ? 'Batch grouping on — click for flat request list'
                  : 'Batch grouping off — click to group by intake batch'
              }
              onClick={() =>
                setViewMode((current) => (current === 'batch' ? 'flat' : 'batch'))
              }
              className={cn(
                'relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors',
                viewMode === 'batch'
                  ? 'border-habeas-navy/40 bg-habeas-navy'
                  : 'border-line bg-canvas',
              )}
            >
              <span
                className={cn(
                  'pointer-events-none block h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform duration-150',
                  viewMode === 'batch' ? 'translate-x-[1.125rem]' : 'translate-x-0.5',
                )}
                aria-hidden
              />
            </button>
          </label>
          <Link to="/requests/needs-attention" className="taste-btn text-xs">
            Inbox
            {attentionQuery.data && attentionQuery.data.items.length > 0 ? (
              <span className="ml-1.5 tabular-nums text-[0.65rem] opacity-80">
                ({attentionQuery.data.items.length})
              </span>
            ) : null}
          </Link>
          {legalAdmin ? (
            <LegalChromeActions />
          ) : (
            <Link to="/requests/new" className="taste-btn-primary text-xs">
              Manual submit
            </Link>
          )}
        </div>
      </header>

      {viewMode === 'batch' ? (
        requestsQuery.isPending ? (
          <div className="grid gap-3 sm:grid-cols-4">
            {Array.from({ length: 4 }, (_, index) => (
              <div key={index} className="rounded-lg border border-line/80 bg-paper/60 px-4 py-3">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="mt-3 h-7 w-12" />
              </div>
            ))}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-4">
            <StatTile label="Batches" value={batchStats.batchCount} />
            <StatTile label="Requests in view" value={batchStats.requestCount} />
            <StatTile
              label="Largest batch"
              value={batchStats.largest}
              hint={batchStats.avg > 0 ? `${batchStats.avg} avg` : undefined}
            />
            <StatTile label="Batches needing attention" value={batchStats.needingAttention} />
          </div>
        )
      ) : stats ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <StatTile label="Open DROP requests" value={stats.open_drop_requests} />
          <StatTile label="Matching review pending" value={stats.matching_review_pending} />
          <StatTile
            label="Matching failed terminal"
            value={stats.matching_failed_terminal}
            hint={
              stats.workers_down > 0
                ? `${stats.workers_down}/${stats.workers_total} workers down`
                : undefined
            }
          />
        </div>
      ) : statsQuery.isPending ? (
        <div className="grid gap-3 sm:grid-cols-3">
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className="rounded-lg border border-line/80 bg-paper/60 px-4 py-3">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-3 h-7 w-12" />
            </div>
          ))}
        </div>
      ) : null}

      <RequestsFilterBar
        search={search}
        stateOptions={stateOptions}
        ephemeralSearch={ephemeralSearch}
        onEphemeralSearchChange={setEphemeralSearch}
        onPatch={patchSearch}
        onClear={clearFilters}
        activeFilterCount={activeFilterCount}
      />

      {search.received_after && search.received_before && viewMode === 'flat' ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-habeas-navy/20 bg-habeas-navy/[0.04] px-3 py-2 text-[0.7rem] text-ink-soft">
          <span>
            Showing requests in one intake batch
            {search.source ? (
              <>
                {' '}
                ·{' '}
                <span className="font-medium text-ink">
                  {SOURCE_LABELS[search.source] ?? search.source}
                </span>
              </>
            ) : null}
            {filtered.length > 0 ? (
              <span className="tabular-nums"> · {filtered.length}</span>
            ) : null}
          </span>
          <button
            type="button"
            className="taste-link ml-auto text-[0.65rem]"
            onClick={() => {
              clearFilters()
              setEphemeralSearch('')
              setViewMode('batch')
            }}
          >
            Back to batches
          </button>
        </div>
      ) : null}

      <div className="taste-panel overflow-hidden">
        {requestsQuery.isPending && <RequestsTableSkeleton tableClass={FLAT_REQUESTS_TABLE_CLASS} />}
        {requestsQuery.isError && (
          <p className="p-4 text-xs text-red-700">
            Could not load requests. Is admin-api running with DATABASE_URL?
          </p>
        )}
        {requestsQuery.isSuccess && filtered.length === 0 && (
          <p className="p-4 text-xs text-ink-soft">
            {serverTotal === 0
              ? 'No requests yet.'
              : requestItems.length === 0
                ? 'No requests on this page — try Previous.'
                : 'No requests match the current filters.'}
          </p>
        )}
        {requestsQuery.isSuccess && filtered.length > 0 && viewMode === 'flat' && (
          <div className="overflow-x-auto">
            <table className={FLAT_REQUESTS_TABLE_CLASS}>
              {flatTableHeader}
              <tbody>
                <RequestRows
                  requests={pageFlatRows}
                  attentionByRequestId={attentionByRequestId}
                  onOpen={openTriage}
                />
              </tbody>
            </table>
          </div>
        )}
        {requestsQuery.isSuccess && filtered.length > 0 && viewMode === 'batch' && (
          <div className="overflow-x-auto">
            <table className={BATCH_REQUESTS_TABLE_CLASS}>
              {batchTableHeader}
              <tbody>
                <BatchRows
                  batches={pageBatchRows}
                  attentionByRequestId={attentionByRequestId}
                  onDrillIn={drillIntoBatch}
                />
              </tbody>
            </table>
          </div>
        )}
        {requestsQuery.isSuccess && requestItems.length > 0 ? (
          <PaginationBar
            unitLabel="requests"
            start={pageStart}
            end={pageEnd}
            total={pageTotal}
            currentPage={currentPage}
            totalPages={totalPages}
            onPrev={() => setPage(Math.max(1, currentPage - 1))}
            onNext={() => setPage(Math.min(totalPages, currentPage + 1))}
          />
        ) : null}
      </div>

      <RequestDetailOverlay
        requestId={overlay.requestId}
        open={overlay.open}
        onOpenChange={overlay.onOpenChange}
        returnFocusRef={overlay.returnFocusRef}
        seedRequest={overlay.seedRequest}
      />
    </section>
  )
}
