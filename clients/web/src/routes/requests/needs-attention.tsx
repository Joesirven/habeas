import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useMemo, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { MatchingReviewPanel } from '@/components/requests/RequestTriageDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmActionDialog } from '@/components/ui/dialog'
import { useMe } from '@/lib/auth'
import {
  getDropMatchingResultDetail,
  getNeedsAttention,
  getRequestComments,
  postDropMatchingResultDecline,
  postDropMatchingResultPromote,
  postDropWorkflowAssign,
  postRequestComment,
  type MatchingResultDetail,
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
type MatchFilter = 'all' | 'single_match' | 'multi_match' | 'not_found' | 'unknown'

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

function matchTypeLabel(matchType: string | null | undefined): string {
  if (!matchType) return 'No match data'
  return matchType.replaceAll('_', ' ')
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

async function fetchMatchingDetailOptional(
  requestId: string,
): Promise<MatchingResultDetail | null> {
  try {
    return await getDropMatchingResultDetail(requestId)
  } catch (error) {
    if (
      error instanceof Error &&
      (error.message.includes('404') ||
        error.message.includes('500') ||
        error.message.includes('502') ||
        error.message.includes('503'))
    ) {
      return null
    }
    throw error
  }
}

function InboxReviewPane({
  item,
  canReviewActions,
}: {
  item: NeedsAttentionItem
  canReviewActions: boolean
}) {
  const queryClient = useQueryClient()
  const [actionError, setActionError] = useState<string | null>(null)
  const [assigneeEmail, setAssigneeEmail] = useState('')
  const [commentDraft, setCommentDraft] = useState('')
  const [assignError, setAssignError] = useState<string | null>(null)
  const [commentError, setCommentError] = useState<string | null>(null)

  const matchingQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop', 'matching-results', item.request_id],
    queryFn: () => fetchMatchingDetailOptional(item.request_id),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const commentsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'comments'],
    queryFn: () => getRequestComments(item.request_id),
    refetchInterval: 15_000,
  })

  const promoteMutation = useMutation({
    mutationFn: () => postDropMatchingResultPromote(item.request_id),
    onSuccess: async () => {
      setActionError(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Promote failed')
    },
  })

  const declineMutation = useMutation({
    mutationFn: () => postDropMatchingResultDecline(item.request_id),
    onSuccess: async () => {
      setActionError(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Decline failed')
    },
  })

  const assignMutation = useMutation({
    mutationFn: (email: string) =>
      postDropWorkflowAssign({
        request_ids: [item.request_id],
        assignee_identity: email,
        target_role: 'reviewer',
      }),
    onSuccess: async () => {
      setAssignError(null)
      setAssigneeEmail('')
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setAssignError(error instanceof Error ? error.message : 'Assign failed')
    },
  })

  const commentMutation = useMutation({
    mutationFn: (body: string) => postRequestComment(item.request_id, body),
    onSuccess: async () => {
      setCommentError(null)
      setCommentDraft('')
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'comments'],
      })
    },
    onError: (error) => {
      setCommentError(error instanceof Error ? error.message : 'Comment failed')
    },
  })

  const actionPending = promoteMutation.isPending || declineMutation.isPending
  const comments = commentsQuery.data ?? []

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-line px-4 py-3">
        <Micro>Review</Micro>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <h3 className="font-mono text-sm font-medium text-ink">{item.request_id}</h3>
          <span className="text-[0.7rem] text-mute">
            {SOURCE_LABELS[item.intake_source] ?? item.intake_source}
          </span>
          {item.requestor_state ? (
            <span className="taste-frost-chip font-mono text-[0.6rem]">
              {item.requestor_state}
            </span>
          ) : null}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <Badge variant="fail" className="normal-case tracking-normal">
            {reasonLabel(item.reason)}
          </Badge>
          <span className="taste-frost-chip text-[0.6rem]">
            {matchTypeLabel(item.match_type)}
            {item.match_count != null ? ` · ${item.match_count}` : ''}
          </span>
          {item.assignment?.assignee_identity ? (
            <span className="taste-frost-chip text-[0.6rem]">
              Assigned · {item.assignment.assignee_identity}
            </span>
          ) : (
            <span className="taste-frost-chip text-[0.6rem] text-mute">Unassigned</span>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-4 py-4">
        <MatchingReviewPanel
          requestId={item.request_id}
          matching={matchingQuery.data}
          isPending={matchingQuery.isPending}
          isError={matchingQuery.isError}
          canReviewActions={canReviewActions}
          actionPending={actionPending}
          actionError={actionError}
          onPromote={() => promoteMutation.mutate()}
          onDecline={() => declineMutation.mutate()}
        />

        {canReviewActions ? (
          <section className="space-y-2 border-t border-line pt-4">
            <Micro>Assign reviewer</Micro>
            <p className="text-[0.7rem] text-ink-soft">
              Route this request to another reviewer (workflow assignment).
            </p>
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-[0.7rem] text-ink-soft">
                Reviewer email
                <input
                  className="rounded-md border border-line bg-paper px-2.5 py-1.5 text-sm text-ink"
                  value={assigneeEmail}
                  onChange={(event) => setAssigneeEmail(event.target.value)}
                  placeholder="reviewer@habeas.com"
                  aria-label="Assignee email"
                />
              </label>
              <Button
                size="sm"
                variant="outline"
                disabled={
                  assignMutation.isPending || assigneeEmail.trim().length === 0
                }
                onClick={() => assignMutation.mutate(assigneeEmail.trim())}
              >
                {assignMutation.isPending ? 'Assigning…' : 'Assign'}
              </Button>
            </div>
            {assignError ? (
              <p className="text-[0.65rem] text-red-700">{assignError}</p>
            ) : null}
          </section>
        ) : null}

        <section className="space-y-2 border-t border-line pt-4">
          <Micro>Comments</Micro>
          <p className="text-[0.7rem] text-ink-soft">
            Operator notes via audit log — no DROP personally identifiable information.
          </p>

          {commentsQuery.isPending && comments.length === 0 ? (
            <p className="text-[0.7rem] text-mute">Loading comments…</p>
          ) : null}
          {commentsQuery.isError ? (
            <p className="text-[0.7rem] text-red-700">Could not load comments.</p>
          ) : null}
          {!commentsQuery.isPending && !commentsQuery.isError && comments.length === 0 ? (
            <p className="text-[0.7rem] text-mute">No comments yet.</p>
          ) : null}

          {comments.length > 0 ? (
            <ul className="space-y-2">
              {comments.map((comment) => (
                <li
                  key={comment.id}
                  className="rounded-md border border-line bg-paper/60 px-3 py-2"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-[0.7rem] font-medium text-ink">
                      {comment.actor}
                    </span>
                    <span className="tabular-nums text-[0.65rem] text-mute">
                      {formatRelativeTime(comment.occurred_at)}
                    </span>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-xs text-ink-soft">
                    {comment.body}
                  </p>
                </li>
              ))}
            </ul>
          ) : null}

          {canReviewActions ? (
            <div className="space-y-2 pt-1">
              <textarea
                className="min-h-[4.5rem] w-full rounded-md border border-line bg-paper px-2.5 py-2 text-sm text-ink"
                value={commentDraft}
                onChange={(event) => setCommentDraft(event.target.value)}
                placeholder="Add a review note…"
                aria-label="Comment body"
                maxLength={2000}
              />
              <div className="flex items-center justify-between gap-2">
                <span className="text-[0.6rem] text-mute tabular-nums">
                  {commentDraft.length}/2000
                </span>
                <Button
                  size="sm"
                  disabled={
                    commentMutation.isPending || commentDraft.trim().length === 0
                  }
                  onClick={() => commentMutation.mutate(commentDraft.trim())}
                >
                  {commentMutation.isPending ? 'Posting…' : 'Post comment'}
                </Button>
              </div>
              {commentError ? (
                <p className="text-[0.65rem] text-red-700">{commentError}</p>
              ) : null}
            </div>
          ) : null}
        </section>

        <p className="text-[0.65rem] text-mute">
          Open full history:{' '}
          <Link
            to="/requests/$requestId"
            params={{ requestId: item.request_id }}
            className="text-habeas-navy underline-offset-2 hover:underline"
          >
            request detail
          </Link>
        </p>
      </div>
    </div>
  )
}

export function NeedsAttentionPage() {
  const queryClient = useQueryClient()
  const { isAdmin } = useMe()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [activeRequestId, setActiveRequestId] = useState<string | null>(null)
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [matchFilter, setMatchFilter] = useState<MatchFilter>('all')
  const [bulkError, setBulkError] = useState<string | null>(null)
  const [bulkAssignee, setBulkAssignee] = useState('')
  const [bulkConfirm, setBulkConfirm] = useState<'promote' | 'decline' | 'assign' | null>(
    null,
  )

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

  const matchOptions = useMemo(() => {
    const counts = new Map<MatchFilter, number>()
    for (const item of items) {
      const key = (item.match_type as MatchFilter | undefined) ?? 'unknown'
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    return (
      ['single_match', 'multi_match', 'not_found', 'unknown'] as MatchFilter[]
    )
      .filter((key) => (counts.get(key) ?? 0) > 0)
      .map((key) => [key, counts.get(key) ?? 0] as const)
  }, [items])

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (sourceFilter !== 'all' && item.intake_source !== sourceFilter) return false
      if (matchFilter !== 'all') {
        const key = (item.match_type as MatchFilter | undefined) ?? 'unknown'
        if (key !== matchFilter) return false
      }
      return true
    })
  }, [items, sourceFilter, matchFilter])

  useEffect(() => {
    if (filteredItems.length === 0) {
      setActiveRequestId(null)
      return
    }
    if (
      activeRequestId == null ||
      !filteredItems.some((item) => item.request_id === activeRequestId)
    ) {
      setActiveRequestId(filteredItems[0]!.request_id)
    }
  }, [filteredItems, activeRequestId])

  const activeItem =
    filteredItems.find((item) => item.request_id === activeRequestId) ?? null

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

  const bulkAssignMutation = useMutation({
    mutationFn: async ({
      requestIds,
      assignee,
    }: {
      requestIds: string[]
      assignee: string
    }) =>
      postDropWorkflowAssign({
        request_ids: requestIds,
        assignee_identity: assignee,
        target_role: 'reviewer',
      }),
    onSuccess: async () => {
      setBulkError(null)
      setBulkAssignee('')
      setSelectedIds(new Set())
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setBulkError(error instanceof Error ? error.message : 'Bulk assign failed')
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

  function runBulk(action: 'promote' | 'decline') {
    const requestIds = [...selectedIds]
    if (requestIds.length === 0) return
    bulkMutation.mutate({ action, requestIds })
  }

  const selectedCount = selectedIds.size

  return (
    <section className="taste-ops-page flex min-h-[calc(100vh-7rem)] flex-col gap-3">
      <ConfirmActionDialog
        open={bulkConfirm === 'promote'}
        onOpenChange={(open) => {
          if (!open) setBulkConfirm(null)
        }}
        title={`Promote ${selectedCount} request${selectedCount === 1 ? '' : 's'}?`}
        description="Selected items will be promoted past matching review into fulfillment."
        confirmLabel="Promote selected"
        confirming={bulkMutation.isPending}
        onConfirm={() => {
          setBulkConfirm(null)
          runBulk('promote')
        }}
      />
      <ConfirmActionDialog
        open={bulkConfirm === 'decline'}
        onOpenChange={(open) => {
          if (!open) setBulkConfirm(null)
        }}
        title={`Decline ${selectedCount} request${selectedCount === 1 ? '' : 's'}?`}
        description="Selected items will leave the review queue without fulfillment."
        confirmLabel="Decline selected"
        tone="destructive"
        confirming={bulkMutation.isPending}
        onConfirm={() => {
          setBulkConfirm(null)
          runBulk('decline')
        }}
      />
      <ConfirmActionDialog
        open={bulkConfirm === 'assign'}
        onOpenChange={(open) => {
          if (!open) setBulkConfirm(null)
        }}
        title={`Assign ${selectedCount} request${selectedCount === 1 ? '' : 's'}?`}
        description={`Assign selected reviews to ${bulkAssignee.trim() || 'the reviewer'}.`}
        confirmLabel="Assign selected"
        confirming={bulkAssignMutation.isPending}
        onConfirm={() => {
          setBulkConfirm(null)
          bulkAssignMutation.mutate({
            requestIds: [...selectedIds],
            assignee: bulkAssignee.trim(),
          })
        }}
      />
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>Requests</Micro>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              Inbox
            </h2>
            {attentionQuery.isFetching && !attentionQuery.isPending ? (
              <span className="taste-frost-chip text-[0.65rem]">Refreshing</span>
            ) : null}
            {attentionQuery.data ? (
              <span className="taste-frost-chip tabular-nums text-[0.65rem]">
                {attentionQuery.data.items.length} to review
              </span>
            ) : null}
          </div>
          <p className="mt-1 max-w-lg text-xs text-ink-soft">
            Matching review queue — first item opens automatically for review, assign, and
            comments.
          </p>
        </div>
        <Link to="/requests" className="taste-btn text-xs">
          All requests
        </Link>
      </header>

      <div className="taste-panel flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
        <div className="flex min-h-0 w-full flex-col border-b border-line lg:w-[22rem] lg:shrink-0 lg:border-b-0 lg:border-r">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
            <FilterChip
              active={sourceFilter === 'all' && matchFilter === 'all'}
              label="All"
              count={items.length}
              onClick={() => {
                setSourceFilter('all')
                setMatchFilter('all')
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
            {matchOptions.map(([matchType, count]) => (
              <FilterChip
                key={matchType}
                active={matchFilter === matchType}
                label={matchTypeLabel(matchType)}
                count={count}
                onClick={() =>
                  setMatchFilter((current) =>
                    current === matchType ? 'all' : matchType,
                  )
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
              Select
            </label>

            {isAdmin ? (
              <>
                <Button
                  size="sm"
                  disabled={selectedCount === 0 || bulkMutation.isPending}
                  onClick={() => setBulkConfirm('promote')}
                >
                  Promote
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={selectedCount === 0 || bulkMutation.isPending}
                  onClick={() => setBulkConfirm('decline')}
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

          {isAdmin && selectedCount > 0 ? (
            <div className="flex flex-wrap items-end gap-2 border-b border-line px-3 py-2">
              <label className="flex min-w-[10rem] flex-1 flex-col gap-1 text-[0.65rem] text-ink-soft">
                Assign selected
                <input
                  className="rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
                  value={bulkAssignee}
                  onChange={(event) => setBulkAssignee(event.target.value)}
                  placeholder="reviewer@habeas.com"
                  aria-label="Bulk assignee email"
                />
              </label>
              <Button
                size="sm"
                variant="outline"
                disabled={
                  bulkAssignMutation.isPending || bulkAssignee.trim().length === 0
                }
                onClick={() => setBulkConfirm('assign')}
              >
                {bulkAssignMutation.isPending ? 'Assigning…' : 'Assign'}
              </Button>
            </div>
          ) : null}

          {bulkError ? (
            <p className="border-b border-line px-3 py-2 text-[0.7rem] text-red-700">
              {bulkError}
            </p>
          ) : null}

          <div className="min-h-0 flex-1 overflow-y-auto">
            {loading ? (
              <div className="p-4">
                <SkeletonLines lines={6} />
              </div>
            ) : null}
            {attentionQuery.isError ? (
              <p className="p-4 text-xs text-red-700">Could not load inbox.</p>
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
                  const active = activeRequestId === item.request_id
                  const timestamp = item.received_at ?? item.requested_at
                  return (
                    <li key={item.request_id}>
                      <div
                        className={cn(
                          'flex items-stretch gap-0 transition-colors',
                          active
                            ? 'bg-habeas-navy/[0.07]'
                            : selected
                              ? 'bg-habeas-navy/[0.03]'
                              : 'hover:bg-panel/50',
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
                          onClick={() => setActiveRequestId(item.request_id)}
                          className="flex min-w-0 flex-1 items-start gap-3 px-1 py-2.5 pr-3 text-left"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                              <span className="font-mono text-[0.7rem] font-medium text-ink">
                                {item.request_id.slice(0, 8)}…
                              </span>
                              <span className="text-[0.7rem] text-mute">
                                {SOURCE_LABELS[item.intake_source] ?? item.intake_source}
                              </span>
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-1.5">
                              <Badge
                                variant={
                                  item.match_type === 'multi_match'
                                    ? 'fail'
                                    : item.match_type === 'single_match'
                                      ? 'wait'
                                      : 'default'
                                }
                                className="normal-case tracking-normal"
                              >
                                {matchTypeLabel(item.match_type)}
                              </Badge>
                              {item.assignment?.assignee_identity ? (
                                <span className="text-[0.6rem] text-mute truncate max-w-[9rem]">
                                  → {item.assignment.assignee_identity}
                                </span>
                              ) : null}
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
        </div>

        <div className="min-h-[24rem] min-w-0 flex-1 lg:min-h-0">
          {activeItem ? (
            <InboxReviewPane item={activeItem} canReviewActions={Boolean(isAdmin)} />
          ) : (
            <div className="flex h-full items-center justify-center p-8 text-xs text-ink-soft">
              {loading ? 'Loading review queue…' : 'Select a request to review.'}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
