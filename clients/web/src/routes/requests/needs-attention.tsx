import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  AccessHandoffPanel,
  MatchingReviewPanel,
} from '@/components/requests/RequestTriageDialog'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmActionDialog } from '@/components/ui/dialog'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMe } from '@/lib/auth'
import {
  getDropMatchingResultDetail,
  getFulfillmentArtifact,
  getNeedsAttention,
  getRequestComments,
  getRequestJourney,
  patchAccessDeliveryStatus,
  postDropMatchingResultDecline,
  postDropMatchingResultPromote,
  postDropWorkflowAssign,
  postRequestComment,
  type JourneyStage,
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

/** Mirrors admin-api APPROACHING_SLA_THRESHOLD_HOURS.matching_review */
const MATCHING_REVIEW_SLA_HOURS = 48
/** Within this window of due, treat as “due soon”. */
const DUE_SOON_HOURS = 12

/** Inbox message kind — orthogonal to match result type. */
type InboxKind =
  | 'all'
  | 'matching'
  | 'delivery'
  | 'notice'
  | 'communications'
  | 'pending_tasks'
type MatchFilter = 'all' | 'single_match' | 'multi_match' | 'not_found' | 'unknown'
type DueFilter = 'all' | 'overdue' | 'due_soon' | 'on_track'

const INBOX_KIND_TABS: { value: InboxKind; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'matching', label: 'Matching' },
  { value: 'delivery', label: 'Delivery' },
  { value: 'notice', label: 'Notice' },
  { value: 'communications', label: 'Comms' },
  { value: 'pending_tasks', label: 'Tasks' },
]

function isMatchingItem(item: NeedsAttentionItem): boolean {
  return (
    item.reason === 'matching.review' ||
    item.match_type != null ||
    item.current_stage === 'review'
  )
}

function isDeliveryItem(item: NeedsAttentionItem): boolean {
  return (
    item.reason === 'access.delivery' ||
    item.reason === 'delivery.confirm' ||
    item.current_stage === 'delivery'
  )
}

function isNoticeItem(item: NeedsAttentionItem): boolean {
  return item.reason === 'notice.review' || item.current_stage === 'notice'
}

function isCommsItem(item: NeedsAttentionItem): boolean {
  return (
    item.reason.startsWith('comms.') ||
    item.reason.includes('communication') ||
    item.current_stage === 'comms'
  )
}

function isPendingTaskFor(item: NeedsAttentionItem, email: string | undefined): boolean {
  if (!email) return false
  const assignee = item.assignment?.assignee_identity?.trim().toLowerCase()
  return Boolean(assignee && assignee === email.trim().toLowerCase())
}

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

function inboxItemTitle(item: NeedsAttentionItem): string {
  if (isDeliveryItem(item)) return 'Access pack ready · copy URL'
  if (isNoticeItem(item)) return 'Notice review before Wed upload'
  if (isCommsItem(item)) return 'Requester communications'
  if (isMatchingItem(item)) {
    return `Matching review · ${matchTypeLabel(item.match_type)}`
  }
  return reasonLabel(item.reason)
}

function journeyDot(status: JourneyStage['status']): string {
  if (status === 'complete') return 'bg-emerald-600/70'
  if (status === 'waiting' || status === 'in_progress') return 'bg-amber-500/80'
  if (status === 'failed') return 'bg-red-600/70'
  return 'bg-line'
}

function emailInitials(email: string | null | undefined): string {
  if (!email) return '?'
  const local = email.split('@')[0] ?? email
  const parts = local.split(/[._+-]/).filter(Boolean)
  if (parts.length >= 2) {
    return `${parts[0]![0] ?? ''}${parts[1]![0] ?? ''}`.toUpperCase()
  }
  return local.slice(0, 2).toUpperCase() || '?'
}

/** Deterministic due from matching.review SLA + request anchors (id for stable label). */
function deriveDueAt(item: NeedsAttentionItem): Date | null {
  const anchor = item.requested_at ?? item.received_at
  if (!anchor) return null
  const start = new Date(anchor)
  if (Number.isNaN(start.getTime())) return null
  return new Date(start.getTime() + MATCHING_REVIEW_SLA_HOURS * 60 * 60 * 1000)
}

type DueBucket = 'overdue' | 'due_soon' | 'on_track' | 'unknown'

function dueBucket(item: NeedsAttentionItem, now = Date.now()): DueBucket {
  const due = deriveDueAt(item)
  if (!due) return 'unknown'
  const msLeft = due.getTime() - now
  if (msLeft < 0) return 'overdue'
  if (msLeft <= DUE_SOON_HOURS * 60 * 60 * 1000) return 'due_soon'
  return 'on_track'
}

function formatDueLabel(item: NeedsAttentionItem): string {
  const due = deriveDueAt(item)
  if (!due) return 'No due date'
  const bucket = dueBucket(item)
  const when = due.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
  if (bucket === 'overdue') return `Overdue · ${when}`
  if (bucket === 'due_soon') return `Due soon · ${when}`
  return `Due ${when}`
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

function AssigneeAvatarPicker({
  currentEmail,
  candidates,
  disabled,
  pending,
  error,
  onAssign,
}: {
  currentEmail: string | null | undefined
  candidates: string[]
  disabled: boolean
  pending: boolean
  error: string | null
  onAssign: (email: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [customEmail, setCustomEmail] = useState('')
  const assigned = Boolean(currentEmail)

  return (
    <div className="flex items-center gap-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            disabled={disabled || pending}
            className={cn(
              'inline-flex items-center gap-2 rounded-md border border-line bg-paper px-1.5 py-1 text-left transition-colors',
              disabled
                ? 'cursor-default opacity-70'
                : 'hover:border-habeas-navy/30 hover:bg-habeas-navy/[0.04]',
            )}
            aria-label={assigned ? `Assigned to ${currentEmail}` : 'Assign reviewer'}
          >
            <Avatar className="h-7 w-7">
              <AvatarFallback>{emailInitials(currentEmail)}</AvatarFallback>
            </Avatar>
            <span className="min-w-0 max-w-[10rem]">
              <span className="block text-[0.6rem] text-mute">Assignee</span>
              <span className="block truncate text-[0.7rem] font-medium text-ink">
                {currentEmail ?? 'Unassigned'}
              </span>
            </span>
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-72 p-2" align="start">
          <p className="px-1.5 pb-1.5 text-[0.65rem] text-mute">
            Pick a reviewer or enter an email
          </p>
          <ul className="max-h-40 space-y-0.5 overflow-y-auto">
            {candidates.map((email) => {
              const selected = email === currentEmail
              return (
                <li key={email}>
                  <button
                    type="button"
                    className={cn(
                      'flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left text-xs',
                      selected
                        ? 'bg-habeas-navy/10 text-habeas-navy'
                        : 'hover:bg-panel/60',
                    )}
                    disabled={pending}
                    onClick={() => {
                      onAssign(email)
                      setOpen(false)
                    }}
                  >
                    <Avatar className="h-6 w-6">
                      <AvatarFallback className="text-[0.55rem]">
                        {emailInitials(email)}
                      </AvatarFallback>
                    </Avatar>
                    <span className="min-w-0 truncate">{email}</span>
                  </button>
                </li>
              )
            })}
            {candidates.length === 0 ? (
              <li className="px-1.5 py-2 text-[0.65rem] text-mute">No known reviewers yet.</li>
            ) : null}
          </ul>
          <div className="mt-2 flex gap-1.5 border-t border-line pt-2">
            <input
              className="min-w-0 flex-1 rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
              value={customEmail}
              onChange={(event) => setCustomEmail(event.target.value)}
              placeholder="reviewer@habeas.com"
              aria-label="Assignee email"
              onKeyDown={(event) => {
                if (event.key === 'Enter' && customEmail.trim()) {
                  onAssign(customEmail.trim())
                  setCustomEmail('')
                  setOpen(false)
                }
              }}
            />
            <Button
              size="sm"
              disabled={pending || customEmail.trim().length === 0}
              onClick={() => {
                onAssign(customEmail.trim())
                setCustomEmail('')
                setOpen(false)
              }}
            >
              {pending ? '…' : 'Assign'}
            </Button>
          </div>
          {error ? <p className="mt-1.5 px-0.5 text-[0.65rem] text-red-700">{error}</p> : null}
        </PopoverContent>
      </Popover>
    </div>
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
  assigneeCandidates,
  onBackToQueue,
}: {
  item: NeedsAttentionItem
  canReviewActions: boolean
  assigneeCandidates: string[]
  onBackToQueue?: () => void
}) {
  const queryClient = useQueryClient()
  const [actionError, setActionError] = useState<string | null>(null)
  const [commentDraft, setCommentDraft] = useState('')
  const [assignError, setAssignError] = useState<string | null>(null)
  const [commentError, setCommentError] = useState<string | null>(null)
  const [copyNote, setCopyNote] = useState<string | null>(null)

  const showMatching = isMatchingItem(item) && !isDeliveryItem(item) && !isNoticeItem(item)
  const showDelivery = isDeliveryItem(item) || item.current_stage === 'fulfill'
  const showNotice = isNoticeItem(item)
  const showComms = isCommsItem(item)

  const matchingQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop', 'matching-results', item.request_id],
    queryFn: () => fetchMatchingDetailOptional(item.request_id),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
    enabled: showMatching || showDelivery,
  })

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', item.request_id, 'journey'],
    queryFn: () => getRequestJourney(item.request_id),
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const artifactQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', item.request_id],
    queryFn: () => getFulfillmentArtifact(item.request_id),
    refetchInterval: 15_000,
    retry: false,
    enabled: showDelivery || showComms || item.current_stage === 'fulfill',
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
      setActionError(error instanceof Error ? error.message : 'Fulfill failed')
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

  const deliveryMutation = useMutation({
    mutationFn: (status: 'delivered' | 'failed' | 'recalled') =>
      patchAccessDeliveryStatus(item.request_id, { status }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', item.request_id],
      })
    },
  })

  const actionPending = promoteMutation.isPending || declineMutation.isPending
  const comments = commentsQuery.data ?? []
  const bucket = dueBucket(item)
  const assignee = item.assignment?.assignee_identity
  const stages = journeyQuery.data?.stages ?? []

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-2 border-b border-line px-4 py-3">
        {onBackToQueue ? (
          <button
            type="button"
            onClick={onBackToQueue}
            className="mb-1 text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline md:hidden"
          >
            ← Queue
          </button>
        ) : null}
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <Micro>Request detail</Micro>
            <h2 className="mt-0.5 text-sm font-medium text-ink">{inboxItemTitle(item)}</h2>
            <h3 className="font-mono text-[0.75rem] text-mute">{item.request_id}</h3>
            <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[0.7rem] text-ink-soft">
              <div>
                Source{' '}
                <span className="text-ink">
                  {SOURCE_LABELS[item.intake_source] ?? item.intake_source}
                </span>
              </div>
              <div>
                Stage{' '}
                <span className="capitalize text-ink">
                  {item.current_stage.replaceAll('_', ' ')}
                </span>
              </div>
              <div>
                Blocker <span className="text-ink">{reasonLabel(item.reason)}</span>
              </div>
              {item.bulk_process_id != null || item.source_csv_filename ? (
                <div>
                  Batch{' '}
                  <span className="font-mono text-ink">
                    {inboxBatchLabel(item)}
                  </span>
                </div>
              ) : null}
            </dl>
          </div>
          <AssigneeAvatarPicker
            currentEmail={assignee}
            candidates={assigneeCandidates}
            disabled={!canReviewActions}
            pending={assignMutation.isPending}
            error={assignError}
            onAssign={(email) => assignMutation.mutate(email)}
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge
            variant={
              bucket === 'overdue' ? 'fail' : bucket === 'due_soon' ? 'wait' : 'default'
            }
            className="normal-case tracking-normal"
          >
            {formatDueLabel(item)}
          </Badge>
        </div>
      </div>

      {stages.length > 0 ? (
        <div className="shrink-0 border-b border-line px-4 py-3">
          <Micro>Journey</Micro>
          <ol className="mt-2 flex flex-wrap gap-2">
            {stages.map((stage) => (
              <li
                key={stage.stage}
                className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[0.65rem]"
              >
                <span className={cn('h-1.5 w-1.5 rounded-full', journeyDot(stage.status))} />
                <span className="text-ink">{stage.label}</span>
                {stage.blocker ? (
                  <span className="max-w-[10rem] truncate text-mute">{stage.blocker}</span>
                ) : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {showMatching ? (
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
            compact
          />
        ) : null}

        {showDelivery || showComms ? (
          <AccessHandoffPanel
            requestId={item.request_id}
            artifact={artifactQuery.data}
            isPending={artifactQuery.isFetching && !artifactQuery.data}
            isError={artifactQuery.isError}
            canMutate={canReviewActions}
            busy={deliveryMutation.isPending}
            onCopyUrl={() => {
              const url =
                artifactQuery.data?.shareable_url ??
                artifactQuery.data?.fulfillment_artifact_uri
              if (!url) return
              void navigator.clipboard.writeText(url).then(() => {
                setCopyNote('Copied URL')
                window.setTimeout(() => setCopyNote(null), 2000)
              })
            }}
            onSetStatus={(status) => deliveryMutation.mutate(status)}
          />
        ) : null}
        {copyNote ? <p className="text-[0.7rem] text-mute">{copyNote}</p> : null}

        {showNotice ? (
          <div className="space-y-3 text-xs">
            <p className="text-ink-soft">
              DROP path after fulfill: approve{' '}
              <span className="font-mono">notice.review</span>, then Wed upload — not a
              consumer URL.
            </p>
            <p className="text-mute">Next upload window: Wed 00:00 America/Los_Angeles</p>
          </div>
        ) : null}

        {showComms ? (
          <div className="space-y-2 rounded-lg border border-dashed border-line px-3 py-4 text-xs text-ink-soft">
            <p className="font-medium text-ink">Requester communications</p>
            <p>
              Outbound drafts, sent attempts, and inbound replies will thread here. Use{' '}
              <span className="font-medium text-ink">Draft outbound</span> on Delivery items
              for access URL emails today.
            </p>
          </div>
        ) : null}

        <p className="text-[0.65rem] text-mute">
          <Link
            to="/requests/$requestId"
            params={{ requestId: item.request_id }}
            className="text-habeas-navy underline-offset-2 hover:underline"
          >
            Full request history →
          </Link>
        </p>
      </div>

      <section className="shrink-0 space-y-2 border-t border-line bg-paper/80 px-4 py-3">
        <Micro>
          Comments ·{' '}
          {commentsQuery.isPending && comments.length === 0
            ? '…'
            : `${comments.length} note${comments.length === 1 ? '' : 's'}`}
        </Micro>
        <div className="max-h-28 space-y-1 overflow-y-auto">
          {commentsQuery.isError ? (
            <p className="text-[0.7rem] text-red-700">Could not load comments.</p>
          ) : null}
          {!commentsQuery.isPending && !commentsQuery.isError && comments.length === 0 ? (
            <p className="text-[0.7rem] text-mute">No comments yet.</p>
          ) : null}
          {comments.map((comment) => (
            <div
              key={comment.id}
              className="rounded-md border border-line/80 bg-canvas/60 px-2 py-1"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-1">
                <span className="text-[0.65rem] font-medium text-ink">{comment.actor}</span>
                <span className="tabular-nums text-[0.6rem] text-mute">
                  {formatRelativeTime(comment.occurred_at)}
                </span>
              </div>
              <p className="whitespace-pre-wrap text-[0.7rem] text-ink-soft">{comment.body}</p>
            </div>
          ))}
        </div>
        {canReviewActions ? (
          <div className="flex items-end gap-2">
            <textarea
              className="min-h-[2.5rem] max-h-20 flex-1 resize-y rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
              value={commentDraft}
              onChange={(event) => setCommentDraft(event.target.value)}
              placeholder="Add a review note…"
              aria-label="Comment body"
              maxLength={2000}
            />
            <Button
              size="sm"
              disabled={commentMutation.isPending || commentDraft.trim().length === 0}
              onClick={() => commentMutation.mutate(commentDraft.trim())}
            >
              {commentMutation.isPending ? '…' : 'Post'}
            </Button>
          </div>
        ) : null}
        {commentError ? (
          <p className="text-[0.65rem] text-red-700">{commentError}</p>
        ) : null}
      </section>
    </div>
  )
}



type InboxRow =
  | {
      kind: 'thread'
      batchKey: string
      batchLabel: string
      items: NeedsAttentionItem[]
    }
  | { kind: 'request'; item: NeedsAttentionItem }

type ActiveTarget =
  | { kind: 'thread'; batchKey: string }
  | { kind: 'request'; requestId: string }

/** Prefer download attempt id; fall back to ZIP member name (seed/broker rows). */
function inboxBatchKey(item: NeedsAttentionItem): string | null {
  if (item.match_type !== 'single_match') return null
  if (item.bulk_process_id != null) return `p:${item.bulk_process_id}`
  if (item.source_csv_filename) return `c:${item.source_csv_filename}`
  return null
}

function inboxBatchLabel(item: NeedsAttentionItem): string {
  if (item.bulk_process_id != null) return `#${item.bulk_process_id}`
  const name = item.source_csv_filename?.split('/').pop() ?? item.source_csv_filename
  if (!name) return 'batch'
  return name.replace(/\.csv$/i, '')
}

/** Threads only when browsing Matching (or All) with no result-type/due filter. */
function shouldGroupThreads(
  inboxKind: InboxKind,
  matchFilter: MatchFilter,
  dueFilter: DueFilter,
): boolean {
  return (
    (inboxKind === 'all' || inboxKind === 'matching') &&
    matchFilter === 'all' &&
    dueFilter === 'all'
  )
}

/** Exact 1:1 matches from the same DROP batch → one expandable thread (ungrouped when filters on). */
function buildInboxRows(
  items: NeedsAttentionItem[],
  groupThreads: boolean,
): InboxRow[] {
  if (!groupThreads) {
    return items.map((item) => ({ kind: 'request' as const, item }))
  }

  const byBatch = new Map<string, NeedsAttentionItem[]>()
  const individuals: NeedsAttentionItem[] = []

  for (const item of items) {
    const key = inboxBatchKey(item)
    if (key != null) {
      const list = byBatch.get(key) ?? []
      list.push(item)
      byBatch.set(key, list)
    } else {
      individuals.push(item)
    }
  }

  type Timed = { t: string; row: InboxRow }
  const timed: Timed[] = []

  for (const [batchKey, members] of byBatch) {
    const sorted = [...members].sort((a, b) =>
      (a.requested_at ?? '').localeCompare(b.requested_at ?? ''),
    )
    if (sorted.length >= 2) {
      timed.push({
        t: sorted[0]?.requested_at ?? '',
        row: {
          kind: 'thread',
          batchKey,
          batchLabel: inboxBatchLabel(sorted[0]!),
          items: sorted,
        },
      })
    } else {
      for (const item of sorted) {
        timed.push({
          t: item.requested_at ?? '',
          row: { kind: 'request', item },
        })
      }
    }
  }

  for (const item of individuals) {
    timed.push({
      t: item.requested_at ?? '',
      row: { kind: 'request', item },
    })
  }

  timed.sort((a, b) => a.t.localeCompare(b.t))
  return timed.map((entry) => entry.row)
}

function ThreadReviewPane({
  batchLabel,
  items,
  canReviewActions,
  onPromoteAll,
  onDeclineAll,
  actionPending,
  actionError,
  onBackToQueue,
}: {
  batchLabel: string
  items: NeedsAttentionItem[]
  canReviewActions: boolean
  onPromoteAll: () => void
  onDeclineAll: () => void
  actionPending: boolean
  actionError: string | null
  onBackToQueue?: () => void
}) {
  const [confirm, setConfirm] = useState<'fulfill' | 'decline' | null>(null)
  const wasActionPending = useRef(false)
  useEffect(() => {
    if (wasActionPending.current && !actionPending) setConfirm(null)
    wasActionPending.current = actionPending
  }, [actionPending])
  const earliest = items.reduce<NeedsAttentionItem | null>((best, item) => {
    if (!best) return item
    return (item.requested_at ?? '') < (best.requested_at ?? '') ? item : best
  }, null)
  const bucket = earliest ? dueBucket(earliest) : 'unknown'

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ConfirmActionDialog
        open={confirm === 'fulfill'}
        onOpenChange={(open) => {
          if (!open && !actionPending) setConfirm(null)
        }}
        title={`Bulk fulfill ${items.length} exact matches?`}
        description={`Approve matching review for all single-match requests from batch ${batchLabel} and release them to fulfillment.`}
        confirmLabel={`Fulfill ${items.length}`}
        confirming={actionPending && confirm === 'fulfill'}
        onConfirm={() => onPromoteAll()}
      />
      <ConfirmActionDialog
        open={confirm === 'decline'}
        onOpenChange={(open) => {
          if (!open && !actionPending) setConfirm(null)
        }}
        title={`Bulk decline ${items.length} exact matches?`}
        description={`Decline all single-match requests from batch ${batchLabel} without fulfillment.`}
        confirmLabel={`Decline ${items.length}`}
        tone="destructive"
        confirming={actionPending && confirm === 'decline'}
        onConfirm={() => onDeclineAll()}
      />

      <div className="shrink-0 space-y-2 border-b border-line px-4 py-3">
        {onBackToQueue ? (
          <button
            type="button"
            onClick={onBackToQueue}
            className="mb-1 text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline md:hidden"
          >
            ← Queue
          </button>
        ) : null}
        <Micro>Batch thread</Micro>
        <h2 className="text-sm font-medium text-ink">
          Exact 1:1 matches · {items.length} requests
        </h2>
        <dl className="flex flex-wrap gap-x-4 gap-y-1 text-[0.7rem] text-ink-soft">
          <div>
            Batch <span className="font-mono text-ink">{batchLabel}</span>
          </div>
          <div>
            Match <span className="text-ink">single match</span>
          </div>
          {earliest ? (
            <div>
              Due{' '}
              <span
                className={cn(
                  bucket === 'overdue'
                    ? 'text-red-700'
                    : bucket === 'due_soon'
                      ? 'text-amber-800'
                      : 'text-ink',
                )}
              >
                {formatDueLabel(earliest)}
              </span>
            </div>
          ) : null}
        </dl>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        <p className="text-xs text-ink-soft">
          These requests each matched exactly one DWID in DROP batch{' '}
          <span className="font-mono">{batchLabel}</span>. Fulfill the whole thread at once,
          or expand the thread in the list to open a single request.
        </p>
        <ul className="max-h-56 divide-y divide-line overflow-y-auto rounded-lg border border-line">
          {items.map((entry) => (
            <li
              key={entry.request_id}
              className="flex items-center justify-between gap-2 px-3 py-2 text-[0.7rem]"
            >
              <span className="font-mono text-ink">{entry.request_id.slice(0, 8)}…</span>
              <span className="text-mute">
                {entry.requestor_state ?? '—'}
                {entry.matched_via ? ` · ${entry.matched_via}` : ''}
              </span>
            </li>
          ))}
        </ul>
        {canReviewActions ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={actionPending} onClick={() => setConfirm('fulfill')}>
              {actionPending && confirm === 'fulfill'
                ? `Fulfilling ${items.length}…`
                : `Bulk fulfill #${items.length}`}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={actionPending}
              onClick={() => setConfirm('decline')}
            >
              {actionPending && confirm === 'decline' ? 'Declining…' : 'Bulk decline'}
            </Button>
          </div>
        ) : null}
        {actionError ? (
          <p className="text-[0.65rem] text-red-700">{actionError}</p>
        ) : null}
      </div>
    </div>
  )
}


export function NeedsAttentionPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const search = useSearch({ from: '/requests/needs-attention' })
  const bulkFilter = search.bulk
  const { isAdmin, me } = useMe()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [activeTarget, setActiveTarget] = useState<ActiveTarget | null>(null)
  const [expandedThreads, setExpandedThreads] = useState<Set<string>>(new Set())
  const [inboxKind, setInboxKind] = useState<InboxKind>(
    bulkFilter != null ? 'matching' : 'all',
  )
  const [matchFilter, setMatchFilter] = useState<MatchFilter>('all')
  const [dueFilter, setDueFilter] = useState<DueFilter>('all')

  useEffect(() => {
    if (bulkFilter != null) setInboxKind('matching')
  }, [bulkFilter])
  const [bulkError, setBulkError] = useState<string | null>(null)
  const [bulkAssignee, setBulkAssignee] = useState('')
  const [threadActionError, setThreadActionError] = useState<string | null>(null)
  const [bulkConfirm, setBulkConfirm] = useState<'fulfill' | 'decline' | 'assign' | null>(
    null,
  )
  /** Narrow viewports: queue or detail — never stack the pane under the list. */
  const [mobilePane, setMobilePane] = useState<'queue' | 'detail'>('queue')

  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention'],
    // Max allowed by admin-api — Select all must cover every filter match loaded,
    // not just the rows currently scrolled into the queue pane.
    queryFn: () => getNeedsAttention(1000),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const items = attentionQuery.data?.items ?? []

  const assigneeCandidates = useMemo(() => {
    const set = new Set<string>()
    if (me?.email) set.add(me.email)
    for (const item of items) {
      const email = item.assignment?.assignee_identity?.trim()
      if (email) set.add(email)
    }
    return [...set].sort((a, b) => a.localeCompare(b))
  }, [items, me?.email])

  const kindCounts = useMemo(() => {
    const myEmail = me?.email
    let matching = 0
    let delivery = 0
    let notice = 0
    let communications = 0
    let pendingTasks = 0
    for (const item of items) {
      if (isMatchingItem(item)) matching += 1
      if (isDeliveryItem(item)) delivery += 1
      if (isNoticeItem(item)) notice += 1
      if (isCommsItem(item)) communications += 1
      if (isPendingTaskFor(item, myEmail)) pendingTasks += 1
    }
    return {
      all: items.length,
      matching,
      delivery,
      notice,
      communications,
      pending_tasks: pendingTasks,
    } satisfies Record<InboxKind, number>
  }, [items, me?.email])

  const matchOptions = useMemo(() => {
    const pool = items.filter(isMatchingItem)
    const counts = new Map<MatchFilter, number>()
    for (const item of pool) {
      const key = (item.match_type as MatchFilter | undefined) ?? 'unknown'
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    return (
      ['single_match', 'multi_match', 'not_found', 'unknown'] as MatchFilter[]
    )
      .filter((key) => (counts.get(key) ?? 0) > 0)
      .map((key) => [key, counts.get(key) ?? 0] as const)
  }, [items])

  const dueOptions = useMemo(() => {
    const counts = new Map<DueFilter, number>()
    for (const item of items) {
      const bucket = dueBucket(item)
      if (bucket === 'unknown') continue
      counts.set(bucket, (counts.get(bucket) ?? 0) + 1)
    }
    return (['overdue', 'due_soon', 'on_track'] as DueFilter[])
      .filter((key) => (counts.get(key) ?? 0) > 0)
      .map((key) => [key, counts.get(key) ?? 0] as const)
  }, [items])

  const filteredItems = useMemo(() => {
    const myEmail = me?.email
    return items.filter((item) => {
      if (bulkFilter != null && item.bulk_process_id !== bulkFilter) return false
      if (inboxKind === 'matching' && !isMatchingItem(item)) return false
      if (inboxKind === 'delivery' && !isDeliveryItem(item)) return false
      if (inboxKind === 'notice' && !isNoticeItem(item)) return false
      if (inboxKind === 'communications' && !isCommsItem(item)) return false
      if (inboxKind === 'pending_tasks' && !isPendingTaskFor(item, myEmail)) {
        return false
      }
      if (inboxKind === 'matching' || inboxKind === 'all') {
        if (matchFilter !== 'all') {
          const key = (item.match_type as MatchFilter | undefined) ?? 'unknown'
          if (key !== matchFilter) return false
        }
      }
      if (dueFilter !== 'all' && dueBucket(item) !== dueFilter) return false
      return true
    })
  }, [items, inboxKind, matchFilter, dueFilter, me?.email, bulkFilter])

  const groupThreads = shouldGroupThreads(inboxKind, matchFilter, dueFilter)

  const inboxRows = useMemo(
    () => buildInboxRows(filteredItems, groupThreads),
    [filteredItems, groupThreads],
  )

  useEffect(() => {
    if (inboxRows.length === 0) {
      setActiveTarget(null)
      return
    }
    const stillValid =
      activeTarget != null &&
      (activeTarget.kind === 'thread'
        ? inboxRows.some(
          (row) =>
            row.kind === 'thread' && row.batchKey === activeTarget.batchKey,
        )
        : filteredItems.some((item) => item.request_id === activeTarget.requestId))
    if (!stillValid) {
      const first = inboxRows[0]!
      setActiveTarget(
        first.kind === 'thread'
          ? { kind: 'thread', batchKey: first.batchKey }
          : { kind: 'request', requestId: first.item.request_id },
      )
    }
  }, [inboxRows, filteredItems, activeTarget])

  const activeThread =
    activeTarget?.kind === 'thread'
      ? (inboxRows.find(
        (row): row is Extract<InboxRow, { kind: 'thread' }> =>
          row.kind === 'thread' && row.batchKey === activeTarget.batchKey,
      ) ?? null)
      : null

  const activeItem =
    activeTarget?.kind === 'request'
      ? (filteredItems.find((item) => item.request_id === activeTarget.requestId) ??
        null)
      : null

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
      action: 'fulfill' | 'decline'
      requestIds: string[]
    }) => {
      const results = await Promise.allSettled(
        requestIds.map((requestId) =>
          action === 'fulfill'
            ? postDropMatchingResultPromote(requestId)
            : postDropMatchingResultDecline(requestId),
        ),
      )
      const failedResults = results.filter(
        (result): result is PromiseRejectedResult => result.status === 'rejected',
      )
      const failed = failedResults.length
      const succeeded = results.length - failed
      const sample =
        failedResults[0]?.reason instanceof Error
          ? failedResults[0].reason.message
          : failedResults[0]
            ? String(failedResults[0].reason)
            : null
      return { succeeded, failed, action, sample }
    },
    onSuccess: async (result) => {
      const verb = result.action === 'fulfill' ? 'fulfilled' : 'declined'
      const message =
        result.failed > 0
          ? `${result.succeeded} ${verb}, ${result.failed} failed${
              result.sample ? ` — ${result.sample}` : ''
            }`
          : null
      setBulkError(message)
      setThreadActionError(message)
      setSelectedIds(new Set())
      setBulkConfirm(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : 'Bulk action failed'
      setBulkError(message)
      setThreadActionError(message)
      setBulkConfirm(null)
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
      setBulkConfirm(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setBulkError(error instanceof Error ? error.message : 'Bulk assign failed')
      setBulkConfirm(null)
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

  function toggleThreadExpand(batchKey: string) {
    setExpandedThreads((previous) => {
      const next = new Set(previous)
      if (next.has(batchKey)) next.delete(batchKey)
      else next.add(batchKey)
      return next
    })
  }

  function toggleThreadSelect(requestIds: string[]) {
    setSelectedIds((previous) => {
      const allSelected = requestIds.every((id) => previous.has(id))
      const next = new Set(previous)
      if (allSelected) {
        for (const id of requestIds) next.delete(id)
      } else {
        for (const id of requestIds) next.add(id)
      }
      return next
    })
  }

  function runBulk(action: 'fulfill' | 'decline') {
    // Always act on the full filtered set when select-all is checked — not only
    // what happens to be scrolled into the left pane viewport.
    const requestIds = allFilteredSelected ? [...filteredIds] : [...selectedIds]
    if (requestIds.length === 0) return
    bulkMutation.mutate({ action, requestIds })
  }

  const selectedCount = selectedIds.size
  const selectedInFilterCount = filteredIds.filter((id) => selectedIds.has(id)).length

  return (
    <section className="flex h-[calc(100vh-6.5rem)] flex-col gap-3">
      <ConfirmActionDialog
        open={bulkConfirm === 'fulfill'}
        onOpenChange={(open) => {
          if (!open && !bulkMutation.isPending) setBulkConfirm(null)
        }}
        title={`Fulfill ${allFilteredSelected ? filteredIds.length : selectedCount} request${
          (allFilteredSelected ? filteredIds.length : selectedCount) === 1 ? '' : 's'
        }?`}
        description="Selected items will leave matching review and move into fulfillment."
        confirmLabel="Fulfill selected"
        confirming={bulkMutation.isPending && bulkConfirm === 'fulfill'}
        onConfirm={() => runBulk('fulfill')}
      />
      <ConfirmActionDialog
        open={bulkConfirm === 'decline'}
        onOpenChange={(open) => {
          if (!open && !bulkMutation.isPending) setBulkConfirm(null)
        }}
        title={`Decline ${allFilteredSelected ? filteredIds.length : selectedCount} request${
          (allFilteredSelected ? filteredIds.length : selectedCount) === 1 ? '' : 's'
        }?`}
        description="Selected items will leave the review queue without fulfillment."
        confirmLabel="Decline selected"
        tone="destructive"
        confirming={bulkMutation.isPending && bulkConfirm === 'decline'}
        onConfirm={() => runBulk('decline')}
      />
      <ConfirmActionDialog
        open={bulkConfirm === 'assign'}
        onOpenChange={(open) => {
          if (!open && !bulkAssignMutation.isPending) setBulkConfirm(null)
        }}
        title={`Assign ${selectedCount} request${selectedCount === 1 ? '' : 's'}?`}
        description={`Assign selected reviews to ${bulkAssignee.trim() || 'the reviewer'}.`}
        confirmLabel="Assign selected"
        confirming={bulkAssignMutation.isPending}
        onConfirm={() => {
          bulkAssignMutation.mutate({
            requestIds: allFilteredSelected ? [...filteredIds] : [...selectedIds],
            assignee: bulkAssignee.trim(),
          })
        }}
      />
      <header className="flex shrink-0 flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>Requests</Micro>
          <div className="mt-1 flex flex-wrap items-baseline gap-2">
            <h2 className="font-display text-xl font-medium tracking-tight text-ink">
              Inbox
            </h2>
            {attentionQuery.isFetching && !attentionQuery.isPending ? (
              <span className="taste-frost-chip text-[0.65rem]">Refreshing</span>
            ) : null}
            {bulkMutation.isPending || bulkAssignMutation.isPending ? (
              <span className="taste-frost-chip text-[0.65rem]" role="status" aria-live="polite">
                {bulkMutation.isPending
                  ? bulkConfirm === 'decline'
                    ? 'Declining…'
                    : 'Fulfilling…'
                  : 'Assigning…'}
              </span>
            ) : null}
            {attentionQuery.data && attentionQuery.data.items.length > 0 ? (
              <Badge variant="notification" aria-label={`${attentionQuery.data.items.length} to review`}>
                {attentionQuery.data.items.length > 99
                  ? '99+'
                  : attentionQuery.data.items.length}
              </Badge>
            ) : null}
          </div>
          <p className="mt-1 max-w-lg text-xs text-ink-soft">
            Pending work stays in Inbox lanes — matching, delivery (shareable URL), DROP
            notice, and requester comms. Exact 1:1 matches in one DROP batch group as a
            thread for bulk fulfill.
          </p>
          {bulkFilter != null ? (
            <p className="mt-1.5 flex flex-wrap items-center gap-2 text-[0.7rem]">
              <span className="taste-frost-chip tabular-nums">
                Bulk run #{bulkFilter}
              </span>
              <button
                type="button"
                className="font-medium text-habeas-navy underline-offset-2 hover:underline"
                onClick={() =>
                  void navigate({
                    to: '/requests/needs-attention',
                    search: {},
                  })
                }
              >
                Clear bulk filter
              </button>
            </p>
          ) : null}
        </div>
        <Link to="/requests" className="taste-btn text-xs">
          All requests
        </Link>
      </header>

      <div className="taste-panel grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-[minmax(16rem,22rem)_minmax(0,1fr)]">
        <div
          className={cn(
            'min-h-0 flex-col border-line md:border-r',
            mobilePane === 'detail' ? 'hidden md:flex' : 'flex',
          )}
        >
          <div className="space-y-1.5 border-b border-line px-2.5 py-2">
            <Tabs
              value={inboxKind}
              onValueChange={(value) => {
                const next = value as InboxKind
                setInboxKind(next)
                setMobilePane('queue')
                if (next !== 'matching' && next !== 'all') {
                  setMatchFilter('all')
                }
              }}
            >
              <TabsList className="h-7 w-full justify-start gap-0.5 overflow-x-auto bg-canvas p-0.5">
                {INBOX_KIND_TABS.map((tab) => (
                  <TabsTrigger
                    key={tab.value}
                    value={tab.value}
                    className="h-6 gap-1 px-1.5 text-[0.65rem]"
                  >
                    {tab.label}
                    <span className="tabular-nums opacity-70">{kindCounts[tab.value]}</span>
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>

            {(inboxKind === 'matching' || inboxKind === 'all') &&
              (matchOptions.length > 0 || dueOptions.length > 0) ? (
              <div className="flex flex-wrap items-center gap-1">
                {inboxKind === 'matching' ? (
                  <>
                    <span className="mr-0.5 text-[0.6rem] uppercase tracking-wide text-mute">
                      Result
                    </span>
                    <FilterChip
                      active={matchFilter === 'all'}
                      label="All results"
                      onClick={() => setMatchFilter('all')}
                    />
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
                  </>
                ) : null}
                {dueOptions.length > 0 ? (
                  <>
                    <span className="ml-1 mr-0.5 text-[0.6rem] uppercase tracking-wide text-mute">
                      Due
                    </span>
                    {dueOptions.map(([due, count]) => (
                      <FilterChip
                        key={due}
                        active={dueFilter === due}
                        label={
                          due === 'overdue'
                            ? 'Overdue'
                            : due === 'due_soon'
                              ? 'Due soon'
                              : 'On track'
                        }
                        count={count}
                        onClick={() =>
                          setDueFilter((current) => (current === due ? 'all' : due))
                        }
                      />
                    ))}
                  </>
                ) : null}
              </div>
            ) : null}
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
                aria-label="Select all matching current filters"
              />
              Select all
            </label>

            {isAdmin ? (
              <>
                <Button
                  size="sm"
                  disabled={selectedCount === 0 || bulkMutation.isPending}
                  onClick={() => setBulkConfirm('fulfill')}
                >
                  {bulkMutation.isPending && bulkConfirm === 'fulfill'
                    ? 'Fulfilling…'
                    : 'Fulfill'}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={selectedCount === 0 || bulkMutation.isPending}
                  onClick={() => setBulkConfirm('decline')}
                >
                  {bulkMutation.isPending && bulkConfirm === 'decline'
                    ? 'Declining…'
                    : 'Decline'}
                </Button>
              </>
            ) : null}

            <div className="ml-auto flex items-center gap-2">
              {selectedCount > 0 ? (
                <span className="taste-frost-chip tabular-nums text-[0.65rem]">
                  {allFilteredSelected
                    ? `All ${filteredIds.length} in filter`
                    : `${selectedInFilterCount} of ${filteredIds.length} in filter`}
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
                  #{filteredItems.length} in filter
                  {items.length >= 1000 ? ' (capped at 1000)' : ''}
                  {groupThreads
                    ? ` · ${inboxRows.filter((row) => row.kind === 'thread').length} threads`
                    : ''}
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
                  : inboxKind === 'delivery'
                    ? 'No access delivery tasks yet — packs appear here after fulfillment.'
                    : inboxKind === 'notice'
                      ? 'No DROP notice.review items waiting.'
                      : inboxKind === 'communications'
                        ? 'No requester comms yet — drafts and replies will land here.'
                        : inboxKind === 'pending_tasks'
                          ? 'No pending tasks assigned to you.'
                          : 'No items match the current view.'}
              </p>
            ) : null}

            {!loading && !attentionQuery.isError && filteredItems.length > 0 ? (
              <ul className="divide-y divide-line">
                {inboxRows.map((row) => {
                  if (row.kind === 'thread') {
                    const ids = row.items.map((item) => item.request_id)
                    const selected = ids.every((id) => selectedIds.has(id))
                    const partial =
                      !selected && ids.some((id) => selectedIds.has(id))
                    const active =
                      activeTarget?.kind === 'thread' &&
                      activeTarget.batchKey === row.batchKey
                    const expanded = expandedThreads.has(row.batchKey)
                    const earliest = row.items[0]!
                    const bucket = dueBucket(earliest)
                    return (
                      <li key={`thread-${row.batchKey}`}>
                        <div
                          className={cn(
                            'relative flex items-stretch gap-0 border-l-2 border-l-habeas-navy/70 transition-colors',
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
                              ref={(element) => {
                                if (element) element.indeterminate = partial
                              }}
                              onChange={() => toggleThreadSelect(ids)}
                              aria-label={`Select bulk batch ${row.batchLabel}`}
                            />
                          </label>
                          <button
                            type="button"
                            className="mt-0.5 shrink-0 self-start rounded px-1 py-2 text-[0.65rem] text-mute hover:bg-panel hover:text-ink"
                            aria-label={
                              expanded
                                ? `Collapse bulk batch ${row.batchLabel}`
                                : `Expand bulk batch ${row.batchLabel}`
                            }
                            onClick={() => toggleThreadExpand(row.batchKey)}
                          >
                            {expanded ? '▾' : '▸'}
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              setActiveTarget({
                                kind: 'thread',
                                batchKey: row.batchKey,
                              })
                              setMobilePane('detail')
                            }}
                            className="flex min-w-0 flex-1 items-start gap-2 px-1 py-2 pr-2 text-left"
                            aria-label={`Bulk inbox group batch ${row.batchLabel}, ${row.items.length} requests`}
                          >
                            <span
                              className="relative mt-0.5 flex h-6 w-7 shrink-0 items-center justify-center"
                              aria-hidden
                              title="Grouped bulk inbox item"
                            >
                              <span className="absolute left-0 top-0.5 h-5 w-5 rounded-md border border-habeas-navy/25 bg-habeas-navy/5" />
                              <span className="absolute left-1 top-0 h-5 w-5 rounded-md border border-habeas-navy/40 bg-habeas-navy/10" />
                              <span className="relative flex h-5 w-5 items-center justify-center rounded-md border border-habeas-navy/50 bg-paper text-[0.55rem] font-semibold tabular-nums text-habeas-navy">
                                {row.items.length > 99 ? '99+' : row.items.length}
                              </span>
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                                <span className="font-mono text-[0.7rem] font-medium text-ink">
                                  {row.batchLabel}
                                </span>
                                <Badge
                                  variant="run"
                                  className="normal-case tracking-normal"
                                >
                                  Bulk group
                                </Badge>
                                <span className="text-[0.7rem] text-mute">
                                  Exact 1:1 · {row.items.length} requests
                                </span>
                              </div>
                              <div className="mt-0.5 flex flex-wrap items-center gap-1.5">
                                <Badge
                                  variant="ok"
                                  className="normal-case tracking-normal"
                                >
                                  single match
                                </Badge>
                                <span
                                  className={cn(
                                    'text-[0.6rem] tabular-nums',
                                    bucket === 'overdue'
                                      ? 'text-red-700'
                                      : bucket === 'due_soon'
                                        ? 'text-amber-800'
                                        : 'text-mute',
                                  )}
                                >
                                  {formatDueLabel(earliest)}
                                </span>
                              </div>
                            </div>
                          </button>
                        </div>
                        {expanded ? (
                          <ul className="border-t border-line/70 bg-canvas/40">
                            {row.items.map((item) => {
                              const childSelected = selectedIds.has(item.request_id)
                              const childActive =
                                activeTarget?.kind === 'request' &&
                                activeTarget.requestId === item.request_id
                              return (
                                <li key={item.request_id}>
                                  <div
                                    className={cn(
                                      'flex items-stretch gap-0 pl-6 transition-colors',
                                      childActive
                                        ? 'bg-habeas-navy/[0.07]'
                                        : childSelected
                                          ? 'bg-habeas-navy/[0.03]'
                                          : 'hover:bg-panel/40',
                                    )}
                                  >
                                    <label
                                      className="flex shrink-0 cursor-pointer items-center px-3"
                                      onClick={(event) => event.stopPropagation()}
                                    >
                                      <input
                                        type="checkbox"
                                        className="h-3.5 w-3.5 rounded border-line accent-habeas-navy"
                                        checked={childSelected}
                                        onChange={() => toggleId(item.request_id)}
                                        aria-label={`Select ${item.request_id}`}
                                      />
                                    </label>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setActiveTarget({
                                          kind: 'request',
                                          requestId: item.request_id,
                                        })
                                        setMobilePane('detail')
                                      }}
                                      className="flex min-w-0 flex-1 items-center gap-2 px-1 py-1.5 pr-3 text-left"
                                    >
                                      <span className="font-mono text-[0.65rem] text-ink">
                                        {item.request_id.slice(0, 8)}…
                                      </span>
                                      <span className="text-[0.6rem] text-mute">
                                        {item.requestor_state ?? '—'}
                                      </span>
                                      {item.bulk_process_id != null ||
                                      item.source_csv_filename ? (
                                        <span className="ml-auto font-mono text-[0.6rem] text-mute">
                                          {inboxBatchLabel(item)}
                                        </span>
                                      ) : null}
                                    </button>
                                  </div>
                                </li>
                              )
                            })}
                          </ul>
                        ) : null}
                      </li>
                    )
                  }

                  const item = row.item
                  const selected = selectedIds.has(item.request_id)
                  const active =
                    activeTarget?.kind === 'request' &&
                    activeTarget.requestId === item.request_id
                  const bucket = dueBucket(item)
                  const assignee = item.assignment?.assignee_identity
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
                          onClick={() => {
                            setActiveTarget({
                              kind: 'request',
                              requestId: item.request_id,
                            })
                            setMobilePane('detail')
                          }}
                          className="flex min-w-0 flex-1 flex-col gap-1 px-1 py-3 pr-3 text-left text-xs"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="min-w-0 truncate font-medium text-ink">
                              {inboxItemTitle(item)}
                            </span>
                            <span className="shrink-0 tabular-nums text-mute">
                              {formatRelativeTime(item.requested_at ?? item.received_at)}
                            </span>
                          </div>
                          <div className="flex flex-wrap items-center gap-1.5 text-[0.65rem] text-ink-soft">
                            <Avatar className="h-4 w-4">
                              <AvatarFallback className="text-[0.45rem]">
                                {emailInitials(assignee)}
                              </AvatarFallback>
                            </Avatar>
                            <span>
                              {SOURCE_LABELS[item.intake_source] ?? item.intake_source}
                            </span>
                            <span className="text-mute">·</span>
                            <span className="capitalize">
                              {isDeliveryItem(item)
                                ? 'delivery'
                                : isNoticeItem(item)
                                  ? 'notice'
                                  : isCommsItem(item)
                                    ? 'comms'
                                    : isMatchingItem(item)
                                      ? 'matching'
                                      : isPendingTaskFor(item, me?.email)
                                        ? 'task'
                                        : 'inbox'}
                            </span>
                            <span className="text-mute">·</span>
                            <span className="truncate font-mono text-mute">
                              {item.request_id.slice(0, 8)}…
                            </span>
                            {item.bulk_process_id != null ||
                            item.source_csv_filename ? (
                              <>
                                <span className="text-mute">·</span>
                                <span className="font-mono text-mute">
                                  {inboxBatchLabel(item)}
                                </span>
                              </>
                            ) : null}
                          </div>
                          <p
                            className={cn(
                              'text-[0.65rem]',
                              bucket === 'overdue'
                                ? 'text-red-700'
                                : bucket === 'due_soon'
                                  ? 'text-amber-800'
                                  : 'text-mute',
                            )}
                          >
                            {reasonLabel(item.reason)} · {formatDueLabel(item)}
                          </p>
                        </button>
                      </div>
                    </li>
                  )
                })}
              </ul>
            ) : null}
          </div>
        </div>

        <div
          className={cn(
            'min-h-0 min-w-0 overflow-hidden',
            mobilePane === 'queue' ? 'hidden md:block' : 'block',
          )}
        >
          {activeThread ? (
            <ThreadReviewPane
              batchLabel={activeThread.batchLabel}
              items={activeThread.items}
              canReviewActions={Boolean(isAdmin)}
              actionPending={bulkMutation.isPending}
              actionError={threadActionError}
              onBackToQueue={() => setMobilePane('queue')}
              onPromoteAll={() => {
                setThreadActionError(null)
                bulkMutation.mutate({
                  action: 'fulfill',
                  requestIds: activeThread.items.map((item) => item.request_id),
                })
              }}
              onDeclineAll={() => {
                setThreadActionError(null)
                bulkMutation.mutate({
                  action: 'decline',
                  requestIds: activeThread.items.map((item) => item.request_id),
                })
              }}
            />
          ) : activeItem ? (
            <InboxReviewPane
              item={activeItem}
              canReviewActions={Boolean(isAdmin)}
              assigneeCandidates={assigneeCandidates}
              onBackToQueue={() => setMobilePane('queue')}
            />
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
