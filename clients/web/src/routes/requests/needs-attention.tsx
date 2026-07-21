import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { RequestDetailDrawer } from '@/components/requests/RequestTriageDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useMe } from '@/lib/auth'
import {
  getNeedsAttention,
  postDropMatchingResultDecline,
  postDropMatchingResultPromote,
  type NeedsAttentionItem,
} from '@/lib/api'
import { cn } from '@/lib/utils'

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

type SourceFilter = 'all' | string
type StageFilter = 'all' | string

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function formatRelativeTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  const diffMs = Date.now() - date.getTime()
  if (Number.isNaN(diffMs)) return '—'

  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return 'just now'

  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`

  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`

  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`

  return date.toLocaleDateString()
}

function reasonLabel(reason: string): string {
  return reason.replaceAll('.', ' · ').replaceAll('_', ' ')
}

function FilterChip({
  active,
  label,
  count,
  onClick,
}: {
  active: boolean
  label: string
  count?: number
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[0.7rem] font-medium transition-colors',
        active
          ? 'border-habeas-navy/30 bg-habeas-navy/8 text-habeas-navy'
          : 'border-line bg-paper text-ink-soft hover:border-line hover:text-ink',
      )}
    >
      {label}
      {count != null ? (
        <span
          className={cn(
            'tabular-nums',
            active ? 'text-habeas-navy/80' : 'text-mute',
          )}
        >
          {count}
        </span>
      ) : null}
    </button>
  )
}

export function NeedsAttentionPage() {
  const queryClient = useQueryClient()
  const { isAdmin } = useMe()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerRequestId, setDrawerRequestId] = useState<string | null>(null)
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [stageFilter, setStageFilter] = useState<StageFilter>('all')
  const [bulkError, setBulkError] = useState<string | null>(null)

  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention'],
    queryFn: () => getNeedsAttention(100),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const items = attentionQuery.data?.items ?? []

  const sourceOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const item of items) {
      counts.set(item.intake_source, (counts.get(item.intake_source) ?? 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [items])

  const stageOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const item of items) {
      counts.set(item.current_stage, (counts.get(item.current_stage) ?? 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [items])

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (sourceFilter !== 'all' && item.intake_source !== sourceFilter) return false
      if (stageFilter !== 'all' && item.current_stage !== stageFilter) return false
      return true
    })
  }, [items, sourceFilter, stageFilter])

  const filteredIds = useMemo(
    () => filteredItems.map((item) => item.request_id),
    [filteredItems],
  )

  const allFilteredSelected =
    filteredIds.length > 0 && filteredIds.every((id) => selectedIds.has(id))
  const someFilteredSelected = filteredIds.some((id) => selectedIds.has(id))

  const bulkMutation = useMutation({
    mutationFn: async ({
      action,
      requestIds,
    }: {
      action: 'promote' | 'decline'
      requestIds: string[]
    }) => {
      const results = await Promise.allSettled(
        requestIds.map((requestId) =>
          action === 'promote'
            ? postDropMatchingResultPromote(requestId)
            : postDropMatchingResultDecline(requestId),
        ),
      )
      const failed = results.filter((result) => result.status === 'rejected').length
      const succeeded = results.length - failed
      return { succeeded, failed, action }
    },
    onSuccess: async (result) => {
      setBulkError(
        result.failed > 0
          ? `${result.succeeded} ok, ${result.failed} failed`
          : null,
      )
      setSelectedIds(new Set())
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setBulkError(error instanceof Error ? error.message : 'Bulk action failed')
    },
  })

  const loading = attentionQuery.isPending && !attentionQuery.data

  function toggleId(requestId: string) {
    setSelectedIds((previous) => {
      const next = new Set(previous)
      if (next.has(requestId)) next.delete(requestId)
      else next.add(requestId)
      return next
    })
  }

  function toggleSelectAll() {
    setSelectedIds((previous) => {
      if (allFilteredSelected) {
        const next = new Set(previous)
        for (const id of filteredIds) next.delete(id)
        return next
      }
      const next = new Set(previous)
      for (const id of filteredIds) next.add(id)
      return next
    })
  }

  function openDrawer(item: NeedsAttentionItem) {
    setDrawerRequestId(item.request_id)
    setDrawerOpen(true)
  }

  function runBulk(action: 'promote' | 'decline') {
    const requestIds = [...selectedIds]
    if (requestIds.length === 0) return
    bulkMutation.mutate({ action, requestIds })
  }

  const selectedCount = selectedIds.size

  return (
    <section className="taste-ops-page space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>Requests</Micro>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              Needs attention
            </h2>
            {attentionQuery.isFetching && !attentionQuery.isPending ? (
              <span className="taste-frost-chip text-[0.65rem]">Refreshing</span>
            ) : null}
            {attentionQuery.data ? (
              <span className="taste-frost-chip tabular-nums text-[0.65rem]">
                {attentionQuery.data.items.length} open
              </span>
            ) : null}
          </div>
          <p className="mt-1 max-w-lg text-xs text-ink-soft">
            Matching review inbox — select rows for bulk actions, or open a request to review.
          </p>
        </div>
        <Link to="/requests" className="taste-btn text-xs">
          All requests
        </Link>
      </header>

      <div className="taste-panel overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
          <FilterChip
            active={sourceFilter === 'all' && stageFilter === 'all'}
            label="All"
            count={items.length}
            onClick={() => {
              setSourceFilter('all')
              setStageFilter('all')
            }}
          />
          {sourceOptions.map(([source, count]) => (
            <FilterChip
              key={source}
              active={sourceFilter === source}
              label={SOURCE_LABELS[source] ?? source}
              count={count}
              onClick={() =>
                setSourceFilter((current) => (current === source ? 'all' : source))
              }
            />
          ))}
          {stageOptions.map(([stage, count]) => (
            <FilterChip
              key={stage}
              active={stageFilter === stage}
              label={stage.replaceAll('_', ' ')}
              count={count}
              onClick={() =>
                setStageFilter((current) => (current === stage ? 'all' : stage))
              }
            />
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
          <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-ink-soft">
            <input
              type="checkbox"
              className="h-3.5 w-3.5 rounded border-line accent-habeas-navy"
              checked={allFilteredSelected}
              ref={(element) => {
                if (element) {
                  element.indeterminate = someFilteredSelected && !allFilteredSelected
                }
              }}
              onChange={toggleSelectAll}
              disabled={filteredIds.length === 0}
              aria-label="Select all visible"
            />
            Select all
          </label>

          {isAdmin ? (
            <>
              <Button
                size="sm"
                disabled={selectedCount === 0 || bulkMutation.isPending}
                onClick={() => runBulk('promote')}
              >
                Promote
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={selectedCount === 0 || bulkMutation.isPending}
                onClick={() => runBulk('decline')}
              >
                Decline
              </Button>
            </>
          ) : null}

          <div className="ml-auto flex items-center gap-2">
            {selectedCount > 0 ? (
              <span className="taste-frost-chip tabular-nums text-[0.65rem]">
                {selectedCount} selected
                <button
                  type="button"
                  className="ml-1.5 text-mute hover:text-ink"
                  onClick={() => setSelectedIds(new Set())}
                  aria-label="Clear selection"
                >
                  ×
                </button>
              </span>
            ) : (
              <span className="text-[0.65rem] text-mute tabular-nums">
                {filteredItems.length} shown
              </span>
            )}
          </div>
        </div>

        {bulkError ? (
          <p className="border-b border-line px-3 py-2 text-[0.7rem] text-red-700">{bulkError}</p>
        ) : null}

        {loading ? (
          <div className="p-4">
            <SkeletonLines lines={6} />
          </div>
        ) : null}
        {attentionQuery.isError ? (
          <p className="p-4 text-xs text-red-700">Could not load needs-attention queue.</p>
        ) : null}
        {!loading && !attentionQuery.isError && filteredItems.length === 0 ? (
          <p className="p-6 text-xs text-ink-soft">
            {items.length === 0
              ? 'Nothing needs attention right now.'
              : 'No items match the current filters.'}
          </p>
        ) : null}

        {!loading && !attentionQuery.isError && filteredItems.length > 0 ? (
          <ul className="divide-y divide-line">
            {filteredItems.map((item) => {
              const selected = selectedIds.has(item.request_id)
              const active = drawerOpen && drawerRequestId === item.request_id
              const timestamp = item.received_at ?? item.requested_at
              return (
                <li key={item.request_id}>
                  <div
                    className={cn(
                      'flex items-stretch gap-0 transition-colors',
                      selected || active ? 'bg-habeas-navy/[0.04]' : 'hover:bg-panel/50',
                    )}
                  >
                    <label
                      className="flex shrink-0 cursor-pointer items-center px-3"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        className="h-3.5 w-3.5 rounded border-line accent-habeas-navy"
                        checked={selected}
                        onChange={() => toggleId(item.request_id)}
                        aria-label={`Select ${item.request_id}`}
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => openDrawer(item)}
                      className="flex min-w-0 flex-1 items-start gap-3 px-1 py-2.5 pr-3 text-left"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                          <span className="font-mono text-[0.7rem] font-medium text-ink">
                            {item.request_id}
                          </span>
                          <span className="text-[0.7rem] text-mute">
                            {SOURCE_LABELS[item.intake_source] ?? item.intake_source}
                          </span>
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5">
                          <Badge variant="fail" className="normal-case tracking-normal">
                            {reasonLabel(item.reason)}
                          </Badge>
                          <span className="taste-frost-chip text-[0.6rem] capitalize">
                            {item.current_stage.replaceAll('_', ' ')}
                          </span>
                        </div>
                      </div>
                      <span className="shrink-0 tabular-nums text-[0.65rem] text-mute">
                        {formatRelativeTime(timestamp)}
                      </span>
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        ) : null}
      </div>

      <RequestDetailDrawer
        requestId={drawerRequestId}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
    </section>
  )
}
