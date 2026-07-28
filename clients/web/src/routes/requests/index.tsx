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
  receivedAt: string
  requests: RequestRecord[]
}

function readViewMode(): ViewMode {
  try {
    return sessionStorage.getItem(VIEW_MODE_SESSION_KEY) === 'batch' ? 'batch' : 'flat'
  } catch {
    return 'flat'
  }
}

function requestBatchKey(request: RequestRecord): string {
  return `${request.intake_source}:${request.received_at.slice(0, 16)}`
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

function batchReceivedWindow(receivedAt: string): { received_after: string; received_before: string } {
  const minutePrefix = receivedAt.slice(0, 16)
  const start = new Date(minutePrefix)
  const end = new Date(start)
  end.setMinutes(end.getMinutes() + 1)
  end.setMilliseconds(-1)
  return {
    received_after: start.toISOString(),
    received_before: end.toISOString(),
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
      <PopoverContent className="w-72 space-y-3 p-3" align="start">
        <div className="flex items-center justify-between gap-2">
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

function groupRequestsByBatch(requests: RequestRecord[]): RequestBatch[] {
  const batches = new Map<string, RequestBatch>()
  for (const request of requests) {
    const batchKey = requestBatchKey(request)
    const existing = batches.get(batchKey)
    if (existing) {
      existing.requests.push(request)
      continue
    }
    batches.set(batchKey, {
      batchKey,
      intakeSource: request.intake_source,
      sourceLabel: SOURCE_LABELS[request.intake_source] ?? request.intake_source,
      receivedAt: request.received_at,
      requests: [request],
    })
  }
  return [...batches.values()].sort(
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
            className="group h-8 cursor-pointer transition-colors hover:bg-panel/50"
            onClick={() => onDrillIn(batch)}
            title={`View ${batch.requests.length} requests by request`}
          >
            <td className="w-[8.5rem] tabular-nums text-ink-soft">
              {formatRequestReceivedAt(batch.receivedAt)}
            </td>
            <td className="overflow-hidden">
              <span className="block truncate font-medium text-ink" title={batchTitle}>
                {batchTitle}
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
            <td className="w-12 tabular-nums text-ink-soft">{batch.requests.length}</td>
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
  const overlay = useRequestDetailOverlay()

  useEffect(() => {
    try {
      sessionStorage.setItem(VIEW_MODE_SESSION_KEY, viewMode)
    } catch {
      // ignore storage failures
    }
  }, [viewMode])

  const listStage = search.stage

  const requestsQuery = useQuery({
    queryKey: [
      'admin-api',
      'requests',
      search.source ?? 'all',
      search.source_bucket ?? '',
      listStage ?? '',
      search.posture ?? '',
      ephemeralSearch.trim(),
    ],
    queryFn: () =>
      listRequests({
        intakeSource: search.source,
        sourceBucket: search.source_bucket,
        stage: listStage,
        posture: search.posture,
        limit: 100,
        q: ephemeralSearch.trim().length >= 2 ? ephemeralSearch.trim() : undefined,
      }),
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

  const stateOptions = useMemo(() => {
    const set = new Set<string>()
    for (const request of requestsQuery.data ?? []) {
      if (request.requestor_state) set.add(request.requestor_state.toUpperCase())
    }
    return [...set].sort()
  }, [requestsQuery.data])

  const filtered = useMemo(() => {
    const rows = requestsQuery.data ?? []
    return rows.filter((request) =>
      matchesFilters(request, search, attentionByRequestId, ephemeralSearch),
    )
  }, [requestsQuery.data, search, attentionByRequestId, ephemeralSearch])

  const batches = useMemo(() => groupRequestsByBatch(filtered), [filtered])

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
    const window = batchReceivedWindow(batch.receivedAt)
    setViewMode('flat')
    void navigate({
      to: '/requests',
      search: {
        source: batch.intakeSource,
        source_bucket: undefined,
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
                {filtered.length !== (requestsQuery.data?.length ?? 0)
                  ? ` / ${requestsQuery.data?.length}`
                  : ''}{' '}
                shown
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2">
            <span className="text-[0.65rem] font-medium text-mute">Group by</span>
            <div
              className="inline-flex rounded-md border border-line bg-paper p-0.5"
              role="toolbar"
              aria-label="Group by"
            >
              <button
                type="button"
                className={cn(
                  'rounded px-2.5 py-1 text-[0.7rem] font-medium transition-colors',
                  viewMode === 'flat'
                    ? 'bg-habeas-navy/8 text-habeas-navy'
                    : 'text-ink-soft hover:text-ink',
                )}
                onClick={() => setViewMode('flat')}
              >
                By request
              </button>
              <button
                type="button"
                className={cn(
                  'rounded px-2.5 py-1 text-[0.7rem] font-medium transition-colors',
                  viewMode === 'batch'
                    ? 'bg-habeas-navy/8 text-habeas-navy'
                    : 'text-ink-soft hover:text-ink',
                )}
                onClick={() => setViewMode('batch')}
              >
                By batch
              </button>
            </div>
          </div>
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

      {stats ? (
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

      <div className="taste-panel overflow-hidden">
        {requestsQuery.isPending && <RequestsTableSkeleton tableClass={FLAT_REQUESTS_TABLE_CLASS} />}
        {requestsQuery.isError && (
          <p className="p-4 text-xs text-red-700">
            Could not load requests. Is admin-api running with DATABASE_URL?
          </p>
        )}
        {requestsQuery.isSuccess && filtered.length === 0 && (
          <p className="p-4 text-xs text-ink-soft">
            {(requestsQuery.data?.length ?? 0) === 0
              ? 'No requests yet.'
              : 'No requests match the current filters.'}
          </p>
        )}
        {requestsQuery.isSuccess && filtered.length > 0 && viewMode === 'flat' && (
          <div className="overflow-x-auto">
            <table className={FLAT_REQUESTS_TABLE_CLASS}>
              {flatTableHeader}
              <tbody>
                <RequestRows
                  requests={filtered}
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
                  batches={batches}
                  attentionByRequestId={attentionByRequestId}
                  onDrillIn={drillIntoBatch}
                />
              </tbody>
            </table>
          </div>
        )}
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
