import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { RunTimeline } from '@/components/ops/RunTimeline'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  ConfirmActionDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMe } from '@/lib/auth'
import {
  DROP_RESPONSE_STATUS_OPTIONS,
  getDropMatchingResultDetail,
  getFulfillmentArtifact,
  getRequestJourney,
  patchAccessDeliveryStatus,
  postDropMatchingResultDecline,
  postDropMatchingResultPromote,
  suggestedDropResponseStatus,
  type DropResponseStatusCode,
  type FulfillmentArtifact,
  type JourneyStage,
  type MatchingAttemptRow,
  type MatchingResultDetail,
  type MatchedPersonContact,
  type RunTimelineStep,
} from '@/lib/api'
import { cn } from '@/lib/utils'

/** CA DROP response_status picker for Inbox fulfill confirms. */
export function DropResponseStatusPicker({
  value,
  onChange,
  disabled,
  suggested,
}: {
  value: DropResponseStatusCode | null
  onChange: (code: DropResponseStatusCode) => void
  disabled?: boolean
  suggested?: DropResponseStatusCode | null
}) {
  return (
    <fieldset className="space-y-1.5" disabled={disabled}>
      <legend className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
        CA DROP status result
      </legend>
      <p className="text-[0.65rem] text-ink-soft">
        Confirm the response status code written to DROP (3 Deleted · 4 Opted out ·
        5 Not found). Distinct from ingest Promote-to-raw.
      </p>
      <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="DROP response status">
        {DROP_RESPONSE_STATUS_OPTIONS.map((option) => {
          const selected = value === option.code
          const isSuggested = suggested === option.code
          return (
            <button
              key={option.code}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              onClick={() => onChange(option.code)}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-left text-xs transition-colors',
                selected
                  ? 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
                  : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
                disabled && 'opacity-50',
              )}
            >
              <span className="font-mono tabular-nums">{option.code}</span>
              <span>{option.label}</span>
              {isSuggested && !selected ? (
                <span className="text-[0.55rem] text-mute">suggested</span>
              ) : null}
            </button>
          )
        })}
      </div>
    </fieldset>
  )
}

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

export type RequestDetailDrawerProps = {
  requestId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** @deprecated Prefer RequestDetailDrawer — same component. */
export type RequestTriageDialogProps = RequestDetailDrawerProps

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function journeyStageToTimelineStep(stage: JourneyStage): RunTimelineStep {
  const statusMap: Record<JourneyStage['status'], RunTimelineStep['status']> = {
    not_started: 'pending',
    skipped: 'skipped',
    in_progress: 'running',
    waiting: 'waiting',
    complete: 'completed',
    failed: 'failed',
  }
  return {
    key: stage.stage,
    label: stage.label,
    status: statusMap[stage.status],
    timestamp: stage.completed_at ?? stage.attempted_at,
    detail: stage.blocker ?? undefined,
  }
}

async function fetchMatchingDetailOptional(
  requestId: string,
): Promise<MatchingResultDetail | null> {
  try {
    return await getDropMatchingResultDetail(requestId)
  } catch (error) {
    // 404 = no result yet; 5xx / legacy payload bugs should not crash the drawer.
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

function reviewStatusVariant(status: string): 'default' | 'ok' | 'fail' | 'wait' | 'run' {
  if (status === 'approved') return 'ok'
  if (status === 'declined') return 'fail'
  if (status === 'pending') return 'wait'
  return 'default'
}

function attemptGlance(attempts: MatchingAttemptRow[]): {
  label: string
  tone: 'default' | 'ok' | 'fail' | 'wait' | 'run'
} {
  if (attempts.length === 0) return { label: 'None', tone: 'default' }
  const latest = [...attempts].sort((a, b) => b.attempt_number - a.attempt_number)[0]!
  if (latest.status === 'success') return { label: `${attempts.length} · ok`, tone: 'ok' }
  if (latest.status === 'submit_error' || latest.status === 'outcome_error') {
    return { label: `${attempts.length} · error`, tone: 'fail' }
  }
  if (
    latest.status === 'in_flight' ||
    latest.status === 'claimed' ||
    latest.status === 'pending'
  ) {
    return { label: `${attempts.length} · ${latest.status}`, tone: 'run' }
  }
  return { label: `${attempts.length} · ${latest.status}`, tone: 'wait' }
}

export function StatusAccordion({
  title,
  glance,
  tone = 'default',
  defaultOpen = false,
  children,
}: {
  title: string
  glance: string
  tone?: 'default' | 'ok' | 'fail' | 'wait' | 'run'
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="rounded-md border border-line/80 bg-paper/40">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left hover:bg-panel/40"
          >
            <span className="min-w-0 flex-1 truncate text-[0.7rem] font-medium text-ink">
              {title}
            </span>
            <Badge variant={tone} className="normal-case tracking-normal shrink-0">
              {glance}
            </Badge>
            <span className="shrink-0 text-[0.65rem] text-mute" aria-hidden>
              {open ? '▾' : '▸'}
            </span>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="space-y-1.5 border-t border-line/70 px-2.5 py-2">{children}</div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

function AttemptRow({ attempt }: { attempt: MatchingAttemptRow }) {
  const [open, setOpen] = useState(false)
  const auditKeys = Object.keys(attempt.audit_payload ?? {})
  const tone =
    attempt.status === 'success'
      ? 'ok'
      : attempt.error_code || attempt.status.includes('error')
        ? 'fail'
        : attempt.status === 'in_flight' || attempt.status === 'claimed'
          ? 'run'
          : 'wait'

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div className="rounded-md border border-line/70 bg-canvas/40">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left text-[0.7rem] hover:bg-panel/40"
          >
            <span className="min-w-0 truncate">
              <span className="font-medium text-ink">Attempt #{attempt.attempt_number}</span>
            </span>
            <span className="flex shrink-0 items-center gap-1.5">
              <Badge variant={tone} className="normal-case tracking-normal">
                {attempt.error_code ?? attempt.status}
              </Badge>
              <span className="tabular-nums text-[0.6rem] text-mute">
                {open ? '▾' : '▸'}
              </span>
            </span>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 border-t border-line/60 px-2 py-1.5 text-[0.65rem]">
            <div>
              <dt className="text-mute">Attempted</dt>
              <dd className="tabular-nums text-ink-soft">
                {formatTimestamp(attempt.attempted_at)}
              </dd>
            </div>
            <div>
              <dt className="text-mute">Completed</dt>
              <dd className="tabular-nums text-ink-soft">
                {formatTimestamp(attempt.completed_at)}
              </dd>
            </div>
            <div className="col-span-2">
              <dt className="text-mute">Audit keys</dt>
              <dd className="mt-0.5 font-mono text-ink-soft">
                {auditKeys.length > 0 ? auditKeys.join(', ') : '—'}
              </dd>
            </div>
          </dl>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

/** Outbound email draft for access delivery — operator pastes into external mailer. */
export function buildAccessDeliveryDraft(opts: {
  requestId: string
  shareableUrl: string
}): { subject: string; body: string } {
  const short = opts.requestId.slice(0, 8)
  return {
    subject: `Your Habeas privacy access package (${short}…)`,
    body: [
      'Hello,',
      '',
      'Your data privacy access package is ready. Use this link to download it (the link expires for security):',
      '',
      opts.shareableUrl,
      '',
      'If you did not request this, contact privacy support and do not open the link.',
      '',
      '—',
      'Habeas Data Privacy',
      '',
    ].join('\n'),
  }
}

export function AccessHandoffPanel({
  requestId,
  artifact,
  isPending,
  isError,
  canMutate,
  onCopyUrl,
  onSetStatus,
  busy,
}: {
  requestId: string
  artifact: FulfillmentArtifact | null | undefined
  isPending: boolean
  isError: boolean
  canMutate: boolean
  onCopyUrl: () => void
  onSetStatus: (status: 'delivered' | 'failed' | 'recalled') => void
  busy: boolean
}) {
  const [draftOpen, setDraftOpen] = useState(false)
  const [draftNote, setDraftNote] = useState<string | null>(null)

  if (isPending) {
    return <p className="py-3 text-xs text-ink-soft">Loading fulfillment artifact…</p>
  }
  if (isError || (!artifact?.shareable_url && !artifact?.fulfillment_artifact_uri)) {
    const placeholderDraft = buildAccessDeliveryDraft({
      requestId,
      shareableUrl: '[shareable URL will appear here after fulfillment]',
    })
    return (
      <div className="space-y-3 py-2 text-xs text-ink-soft">
        <p>
          No shareable delivery URL yet for{' '}
          <span className="font-mono text-ink">{requestId.slice(0, 8)}…</span>.
        </p>
        <p className="text-mute">
          Access packs appear here after fulfillment. You can preview the outbound template now.
        </p>
        <Button
          size="sm"
          variant="outline"
          type="button"
          onClick={() => {
            void navigator.clipboard.writeText(placeholderDraft.body).then(() => {
              setDraftNote('Copied draft body (placeholder URL)')
              window.setTimeout(() => setDraftNote(null), 2500)
            })
          }}
        >
          Draft outbound
        </Button>
        {draftNote ? <span className="text-mute">{draftNote}</span> : null}
      </div>
    )
  }

  const url = artifact.shareable_url ?? artifact.fulfillment_artifact_uri ?? ''
  const draft = buildAccessDeliveryDraft({ requestId, shareableUrl: url })

  return (
    <div className="space-y-3 py-1 text-xs">
      <p className="text-ink-soft">
        Copy the shareable URL or draft an outbound message, then paste into your external
        mailer. Mark delivery when sent — the platform does not email requesters.
      </p>
      <div className="rounded-lg border border-line bg-paper/50 px-3 py-2">
        <p className="taste-micro">Shareable URL</p>
        <p className="mt-1 break-all font-mono text-[0.7rem] text-ink">{url}</p>
      </div>
      {artifact.fulfillment_artifact_uri &&
        artifact.fulfillment_artifact_uri !== artifact.shareable_url ? (
        <div className="rounded-lg border border-line/60 px-3 py-2">
          <p className="taste-micro">Internal artifact (ops only)</p>
          <p className="mt-1 break-all font-mono text-[0.65rem] text-mute">
            {artifact.fulfillment_artifact_uri}
          </p>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" type="button" onClick={onCopyUrl} disabled={!url}>
          Copy URL
        </Button>
        <Button size="sm" variant="outline" type="button" onClick={() => setDraftOpen(true)}>
          Draft outbound
        </Button>
        {artifact.kind === 'access' && canMutate ? (
          <>
            <Button
              size="sm"
              variant="outline"
              type="button"
              disabled={busy}
              onClick={() => onSetStatus('delivered')}
            >
              Mark delivered
            </Button>
            <Button
              size="sm"
              variant="outline"
              type="button"
              disabled={busy}
              onClick={() => onSetStatus('failed')}
            >
              Mark failed
            </Button>
            <Button
              size="sm"
              variant="outline"
              type="button"
              disabled={busy}
              onClick={() => onSetStatus('recalled')}
            >
              Mark recalled
            </Button>
          </>
        ) : null}
      </div>
      {artifact.access_delivery_status ? (
        <p className="text-mute">
          Delivery status:{' '}
          <span className="capitalize text-ink">{artifact.access_delivery_status}</span>
        </p>
      ) : null}

      <Dialog open={draftOpen} onOpenChange={setDraftOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Draft access delivery</DialogTitle>
            <DialogDescription>
              Template for external email — copy subject and body, then send outside the platform.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-xs">
            <div>
              <p className="taste-micro">Subject</p>
              <p className="mt-1 rounded-md border border-line bg-paper px-2 py-1.5 text-ink">
                {draft.subject}
              </p>
            </div>
            <div>
              <p className="taste-micro">Body</p>
              <pre className="mt-1 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-md border border-line bg-paper px-2 py-1.5 font-sans text-[0.75rem] text-ink">
                {draft.body}
              </pre>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                type="button"
                onClick={() => {
                  void navigator.clipboard.writeText(draft.body).then(() => {
                    setDraftNote('Copied body')
                    window.setTimeout(() => setDraftNote(null), 2000)
                  })
                }}
              >
                Copy body
              </Button>
              <Button
                size="sm"
                variant="outline"
                type="button"
                onClick={() => {
                  void navigator.clipboard.writeText(draft.subject).then(() => {
                    setDraftNote('Copied subject')
                    window.setTimeout(() => setDraftNote(null), 2000)
                  })
                }}
              >
                Copy subject
              </Button>
              {draftNote ? <span className="text-mute">{draftNote}</span> : null}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function MatchingDetailGrid({
  rows,
}: {
  rows: { label: string; value: ReactNode }[]
}) {
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
      {rows.map((row) => (
        <div key={row.label} className="min-w-0">
          <dt className="text-[0.65rem] text-mute">{row.label}</dt>
          <dd className="mt-0.5 text-ink">{row.value}</dd>
        </div>
      ))}
    </dl>
  )
}

function formatInitials(contact: MatchedPersonContact): string {
  const first = contact.first_initial ?? '·'
  const last = contact.last_initial ?? '·'
  return `${first}${last}`
}

function MatchedContactDetails({ contact }: { contact: MatchedPersonContact }) {
  const phoneSummary =
    contact.phones.length > 0
      ? contact.phones.map((p) => `${p.type}: ${p.number}`).join(' · ')
      : '—'
  return (
    <MatchingDetailGrid
      rows={[
        { label: 'DWID', value: <span className="font-mono tabular-nums">{contact.dwid}</span> },
        { label: 'State', value: <span className="font-mono">{contact.state}</span> },
        {
          label: 'Initials',
          value: <span className="font-mono">{formatInitials(contact)}</span>,
        },
        { label: 'DOB', value: contact.dob ?? '—' },
        { label: 'Email', value: contact.email ?? '—' },
        { label: 'Phones', value: phoneSummary },
      ]}
    />
  )
}

function MatchedContactsPanel({
  matching,
}: {
  matching: MatchingResultDetail
}) {
  const contacts = matching.matched_contacts ?? []
  const status = matching.matched_contacts_status

  if (matching.match_count <= 0) return null

  if (status === 'unavailable') {
    return (
      <p className="text-[0.7rem] text-mute">
        Matched person details are unavailable (BigQuery lookup failed or is not configured
        locally).
      </p>
    )
  }

  if (contacts.length === 0) {
    return (
      <p className="text-[0.7rem] text-mute">
        No person records returned for the matched DWID(s).
      </p>
    )
  }

  if (matching.match_type === 'single_match' && contacts.length === 1) {
    return (
      <div className="space-y-1.5">
        <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
          Matched person
        </p>
        <MatchedContactDetails contact={contacts[0]!} />
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
        Matched persons ({contacts.length})
      </p>
      <div className="space-y-1">
        {contacts.map((contact) => (
          <Collapsible key={contact.dwid}>
            <div className="rounded-md border border-line/80 bg-paper/40">
              <CollapsibleTrigger asChild>
                <button
                  type="button"
                  className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left text-[0.7rem] hover:bg-paper/60"
                >
                  <span className="min-w-0 truncate font-mono tabular-nums">{contact.dwid}</span>
                  <span className="shrink-0 text-mute">
                    {contact.state} · {formatInitials(contact)}
                  </span>
                </button>
              </CollapsibleTrigger>
              <CollapsibleContent className="border-t border-line/60 px-2.5 py-2">
                <MatchedContactDetails contact={contact} />
              </CollapsibleContent>
            </div>
          </Collapsible>
        ))}
      </div>
    </div>
  )
}

export function MatchingReviewPanel({
  requestId,
  matching,
  isPending,
  isError,
  canReviewActions,
  actionPending,
  actionError,
  onPromote,
  onDecline,
  compact = false,
  layout = 'accordion',
  hideActions = false,
}: {
  requestId: string
  matching: MatchingResultDetail | null | undefined
  isPending: boolean
  isError: boolean
  canReviewActions: boolean
  actionPending: boolean
  actionError: string | null
  onPromote: (responseStatus: DropResponseStatusCode) => void
  onDecline: () => void
  /** Denser layout for inbox review pane. */
  compact?: boolean
  /** Tabbed sections instead of collapsible accordions (inbox detail). */
  layout?: 'accordion' | 'tabs'
  /** Hide fulfill/decline buttons (e.g. when inbox header owns actions). */
  hideActions?: boolean
}) {
  const [confirm, setConfirm] = useState<'fulfill' | 'decline' | null>(null)
  const suggestedStatus = suggestedDropResponseStatus(
    matching?.match_type,
    matching?.match_count,
  )
  const [fulfillStatus, setFulfillStatus] = useState<DropResponseStatusCode | null>(
    suggestedStatus,
  )
  const wasActionPending = useRef(false)
  useEffect(() => {
    if (wasActionPending.current && !actionPending) setConfirm(null)
    wasActionPending.current = actionPending
  }, [actionPending])
  useEffect(() => {
    if (confirm === 'fulfill') {
      setFulfillStatus(
        suggestedDropResponseStatus(matching?.match_type, matching?.match_count),
      )
    }
  }, [confirm, matching?.match_type, matching?.match_count])
  const attempts = matching?.attempts ?? []
  const attemptStatus = attemptGlance(attempts)
  const assignment = matching?.assignment?.assignee_identity

  const reviewActions = canReviewActions && !hideActions ? (
    <div className="flex flex-wrap items-center gap-2 pt-1">
      <Button size="sm" disabled={actionPending} onClick={() => setConfirm('fulfill')}>
        {actionPending && confirm === 'fulfill' ? 'Fulfilling…' : 'Fulfill'}
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={actionPending}
        onClick={() => setConfirm('decline')}
      >
        {actionPending && confirm === 'decline' ? 'Declining…' : 'Decline'}
      </Button>
    </div>
  ) : null

  const actionErrorLine = actionError ? (
    <p className="text-[0.65rem] text-red-700">{actionError}</p>
  ) : null

  const tabsBody =
    matching && layout === 'tabs' ? (
      <Tabs defaultValue="overview" className="text-xs">
        <TabsList className="h-7 w-full justify-start">
          <TabsTrigger value="overview" className="h-6 px-2 text-[0.65rem]">
            Overview
          </TabsTrigger>
          <TabsTrigger value="review" className="h-6 px-2 text-[0.65rem]">
            Review
          </TabsTrigger>
          <TabsTrigger value="attempts" className="h-6 px-2 text-[0.65rem]">
            Attempts
            {attempts.length > 0 ? (
              <span className="tabular-nums opacity-70">({attempts.length})</span>
            ) : null}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="mt-2 space-y-3">
          <MatchingDetailGrid
            rows={[
              {
                label: 'Match type',
                value: (matching.match_type ?? '—').replaceAll('_', ' '),
              },
              {
                label: 'Matched',
                value: matching.matched ? 'Yes' : 'No',
              },
              {
                label: 'Count',
                value: <span className="tabular-nums">{matching.match_count}</span>,
              },
              {
                label: 'Via',
                value: matching.matched_via ?? '—',
              },
              {
                label: 'Recorded',
                value: (
                  <span className="tabular-nums">{formatTimestamp(matching.recorded_at)}</span>
                ),
              },
              {
                label: 'Requestor state',
                value: (
                  <span className="font-mono">{matching.requestor_state ?? '—'}</span>
                ),
              },
            ]}
          />
          <MatchedContactsPanel matching={matching} />
        </TabsContent>
        <TabsContent value="review" className="mt-2 space-y-3">
          <MatchingDetailGrid
            rows={[
              {
                label: 'Review status',
                value: (
                  <Badge
                    variant={reviewStatusVariant(matching.review_status)}
                    className="normal-case tracking-normal"
                  >
                    {matching.review_status}
                  </Badge>
                ),
              },
              {
                label: 'Approval id',
                value: (
                  <span className="tabular-nums">{matching.approval_id ?? '—'}</span>
                ),
              },
              {
                label: 'Assignee',
                value: assignment ?? 'Unassigned',
              },
              {
                label: 'Attempt id',
                value: (
                  <span className="tabular-nums">{matching.attempt_id ?? '—'}</span>
                ),
              },
              {
                label: 'Decided by',
                value: matching.decided_by ?? '—',
              },
              {
                label: 'Decided at',
                value: (
                  <span className="tabular-nums">
                    {formatTimestamp(matching.decided_at)}
                  </span>
                ),
              },
              {
                label: 'Reason',
                value: matching.decision_reason ?? '—',
              },
            ]}
          />
          {reviewActions}
          {actionErrorLine}
        </TabsContent>
        <TabsContent value="attempts" className="mt-2 space-y-1.5">
          {attempts.length === 0 ? (
            <p className="text-[0.7rem] text-mute">No matching attempts recorded.</p>
          ) : (
            <div className="space-y-1">
              {attempts.map((attempt) => (
                <AttemptRow key={attempt.id} attempt={attempt} />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    ) : null

  return (
    <div className={cn('text-xs', compact ? 'space-y-1.5' : 'space-y-2')}>
      <ConfirmActionDialog
        open={confirm === 'fulfill'}
        onOpenChange={(open) => {
          if (!open && !actionPending) setConfirm(null)
        }}
        title="Fulfill this match?"
        description={`Approve matching review for ${requestId.slice(0, 8)}… and set the CA DROP status result. This cannot be undone from the inbox.`}
        confirmLabel="Fulfill"
        confirming={actionPending && confirm === 'fulfill'}
        confirmDisabled={fulfillStatus == null}
        onConfirm={() => {
          if (fulfillStatus != null) onPromote(fulfillStatus)
        }}
      >
        <DropResponseStatusPicker
          value={fulfillStatus}
          onChange={setFulfillStatus}
          disabled={actionPending}
          suggested={suggestedStatus}
        />
      </ConfirmActionDialog>
      <ConfirmActionDialog
        open={confirm === 'decline'}
        onOpenChange={(open) => {
          if (!open && !actionPending) setConfirm(null)
        }}
        title="Decline matching review?"
        description={`Decline request ${requestId.slice(0, 8)}… — it will leave the review queue without fulfillment.`}
        confirmLabel="Decline"
        tone="destructive"
        confirming={actionPending && confirm === 'decline'}
        onConfirm={() => onDecline()}
      />
      {isPending && matching == null ? (
        <p className="text-ink-soft">Loading matching result…</p>
      ) : null}
      {isError ? (
        <p className="text-red-700">
          Could not load matching result. Retry or open Workers → matching.
        </p>
      ) : null}
      {matching == null && !isPending && !isError ? (
        <div className="space-y-1 text-ink-soft">
          <p>No matching result payload for this request yet.</p>
          <p className="text-[0.65rem] text-mute">
            Detail appears once a matching_results row exists; review can still wait on
            matching.review independently.
          </p>
        </div>
      ) : null}
      {matching && layout === 'tabs' ? tabsBody : null}
      {matching && layout !== 'tabs' ? (
        <>
          <StatusAccordion
            title="Match result"
            glance={
              matching.match_type
                ? `${matching.match_type.replaceAll('_', ' ')} · ${matching.match_count}`
                : matching.matched
                  ? `Matched · ${matching.match_count}`
                  : 'Not matched'
            }
            tone={
              matching.match_type === 'multi_match'
                ? 'fail'
                : matching.match_type === 'single_match'
                  ? 'wait'
                  : matching.matched
                    ? 'ok'
                    : 'default'
            }
            defaultOpen
          >
            <dl className="grid grid-cols-3 gap-1.5">
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Matched</dt>
                <dd className="text-[0.7rem]">{matching.matched ? 'Yes' : 'No'}</dd>
              </div>
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Count</dt>
                <dd className="tabular-nums text-[0.7rem]">{matching.match_count}</dd>
              </div>
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Type</dt>
                <dd className="truncate text-[0.7rem]">
                  {(matching.match_type ?? '—').replaceAll('_', ' ')}
                </dd>
              </div>
            </dl>
            <div className="mt-2">
              <MatchedContactsPanel matching={matching} />
            </div>
          </StatusAccordion>

          <StatusAccordion
            title="Match method"
            glance={matching.matched_via ?? '—'}
            tone={matching.matched_via ? 'ok' : 'default'}
          >
            <dl className="grid grid-cols-2 gap-1.5">
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Via</dt>
                <dd className="text-[0.7rem]">{matching.matched_via ?? '—'}</dd>
              </div>
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Recorded</dt>
                <dd className="tabular-nums text-[0.7rem]">
                  {formatTimestamp(matching.recorded_at)}
                </dd>
              </div>
            </dl>
          </StatusAccordion>

          <StatusAccordion
            title="Requestor"
            glance={matching.requestor_state ?? 'No state'}
            tone={matching.requestor_state ? 'ok' : 'wait'}
          >
            <dl className="grid grid-cols-2 gap-1.5">
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">State</dt>
                <dd className="font-mono text-[0.7rem]">
                  {matching.requestor_state ?? '—'}
                </dd>
              </div>
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Request</dt>
                <dd className="truncate font-mono text-[0.65rem]">{requestId}</dd>
              </div>
            </dl>
          </StatusAccordion>

          <StatusAccordion
            title="Review gate"
            glance={matching.review_status}
            tone={reviewStatusVariant(matching.review_status)}
            defaultOpen={matching.review_status === 'pending'}
          >
            <dl className="grid grid-cols-2 gap-1.5">
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Status</dt>
                <dd>
                  <Badge
                    variant={reviewStatusVariant(matching.review_status)}
                    className="normal-case tracking-normal"
                  >
                    {matching.review_status}
                  </Badge>
                </dd>
              </div>
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Approval id</dt>
                <dd className="tabular-nums text-[0.7rem]">
                  {matching.approval_id ?? '—'}
                </dd>
              </div>
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Assignee</dt>
                <dd className="truncate text-[0.7rem]">{assignment ?? 'Unassigned'}</dd>
              </div>
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Attempt id</dt>
                <dd className="tabular-nums text-[0.7rem]">
                  {matching.attempt_id ?? '—'}
                </dd>
              </div>
            </dl>
            {reviewActions}
            {actionErrorLine}
          </StatusAccordion>

          <StatusAccordion
            title="Matching attempts"
            glance={attemptStatus.label}
            tone={attemptStatus.tone}
          >
            {attempts.length === 0 ? (
              <p className="text-[0.7rem] text-mute">No matching attempts recorded.</p>
            ) : (
              <div className="space-y-1">
                {attempts.map((attempt) => (
                  <AttemptRow key={attempt.id} attempt={attempt} />
                ))}
              </div>
            )}
          </StatusAccordion>

          <StatusAccordion
            title="Decision"
            glance={
              matching.decided_at
                ? matching.review_status
                : matching.review_status === 'pending'
                  ? 'Awaiting'
                  : 'None'
            }
            tone={
              matching.decided_at
                ? reviewStatusVariant(matching.review_status)
                : matching.review_status === 'pending'
                  ? 'wait'
                  : 'default'
            }
          >
            <dl className="grid grid-cols-2 gap-1.5">
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Decided by</dt>
                <dd className="truncate text-[0.7rem]">{matching.decided_by ?? '—'}</dd>
              </div>
              <div className="rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Decided at</dt>
                <dd className="tabular-nums text-[0.7rem]">
                  {formatTimestamp(matching.decided_at)}
                </dd>
              </div>
              <div className="col-span-2 rounded-md border border-line/70 px-2 py-1">
                <dt className="text-[0.6rem] text-mute">Reason</dt>
                <dd className="text-[0.7rem]">{matching.decision_reason ?? '—'}</dd>
              </div>
            </dl>
          </StatusAccordion>
        </>
      ) : null}
    </div>
  )
}

export function RequestDetailDrawer({ requestId, open, onOpenChange }: RequestDetailDrawerProps) {
  const queryClient = useQueryClient()
  const { isAdmin, isSuperAdmin } = useMe()
  const [actionError, setActionError] = useState<string | null>(null)
  const [copyNote, setCopyNote] = useState<string | null>(null)

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey'],
    queryFn: () => getRequestJourney(requestId!),
    enabled: open && Boolean(requestId),
    refetchInterval: open ? 10_000 : false,
    placeholderData: (previous) => previous,
  })

  const matchingQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop', 'matching-results', requestId],
    queryFn: () => fetchMatchingDetailOptional(requestId!),
    enabled: open && Boolean(requestId),
    refetchInterval: open ? 10_000 : false,
    placeholderData: (previous) => previous,
  })

  const artifactQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', requestId],
    queryFn: () => getFulfillmentArtifact(requestId!),
    enabled: open && Boolean(requestId),
    refetchInterval: open ? 15_000 : false,
    retry: false,
  })

  const deliveryMutation = useMutation({
    mutationFn: (status: 'delivered' | 'failed' | 'recalled') =>
      patchAccessDeliveryStatus(requestId!, { status }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', requestId],
      })
    },
  })

  const promoteMutation = useMutation({
    mutationFn: (responseStatus: DropResponseStatusCode) =>
      postDropMatchingResultPromote(requestId!, { response_status: responseStatus }),
    onSuccess: async () => {
      setActionError(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Fulfill failed')
    },
  })

  const declineMutation = useMutation({
    mutationFn: () => postDropMatchingResultDecline(requestId!),
    onSuccess: async () => {
      setActionError(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Decline failed')
    },
  })

  const timelineSteps = journeyQuery.data?.stages.map(journeyStageToTimelineStep) ?? []
  const matching = matchingQuery.data
  const loading = journeyQuery.isPending && !journeyQuery.data
  const actionPending = promoteMutation.isPending || declineMutation.isPending
  const canReviewActions =
    isAdmin &&
    matching != null &&
    matching.review_status === 'pending' &&
    Boolean(matching.approval_id)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          'inset-y-0 right-0 left-auto top-0 h-full max-h-none w-full max-w-xl translate-x-0 translate-y-0 gap-0 overflow-hidden rounded-none border-y-0 border-l border-r-0 p-0 shadow-xl sm:max-w-xl',
        )}
      >
        <DialogHeader className="shrink-0 border-b border-line px-5 py-4 pr-12">
          <p className="taste-micro">Request detail</p>
          <DialogTitle className="font-mono text-base">{requestId ?? '—'}</DialogTitle>
          <DialogDescription>
            Full journey history and matching review — counts and ids only.
          </DialogDescription>
          {journeyQuery.isFetching && !journeyQuery.isPending ? (
            <span className="taste-frost-chip w-fit text-[0.65rem]">Refreshing</span>
          ) : null}
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {loading ? (
            <div className="px-5 py-8 text-xs text-ink-soft">Loading journey…</div>
          ) : null}

          {journeyQuery.isError ? (
            <div className="px-5 py-6">
              <p className="text-xs text-red-700">Could not load request journey.</p>
              <p className="mt-1 font-mono text-[0.65rem] text-ink-soft">
                {journeyQuery.error instanceof Error
                  ? journeyQuery.error.message
                  : 'Unknown error'}
              </p>
            </div>
          ) : null}

          {journeyQuery.data ? (
            <div className="px-5 pb-8">
              <dl className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line py-3 text-xs">
                <div className="flex items-baseline gap-2">
                  <dt className="taste-micro">Source</dt>
                  <dd>
                    {SOURCE_LABELS[journeyQuery.data.intake_source] ??
                      journeyQuery.data.intake_source}
                  </dd>
                </div>
                <div className="flex items-baseline gap-2">
                  <dt className="taste-micro">Received</dt>
                  <dd className="tabular-nums">
                    {formatTimestamp(journeyQuery.data.received_at)}
                  </dd>
                </div>
                <div className="flex items-baseline gap-2">
                  <dt className="taste-micro">Stage</dt>
                  <dd>
                    <span className="taste-frost-chip text-[0.65rem] capitalize">
                      {(journeyQuery.data.current_stage ?? 'unknown').replaceAll('_', ' ')}
                    </span>
                  </dd>
                </div>
                {journeyQuery.data.blocker ? (
                  <div className="flex min-w-0 items-baseline gap-2 sm:max-w-md">
                    <dt className="taste-micro shrink-0">Blocker</dt>
                    <dd className="truncate text-ink-soft">{journeyQuery.data.blocker}</dd>
                  </div>
                ) : null}
                {journeyQuery.data.source_csv_filename ? (
                  <div className="flex min-w-0 items-baseline gap-2 sm:max-w-md">
                    <dt className="taste-micro shrink-0">Intake CSV</dt>
                    <dd className="truncate font-mono text-[0.7rem] text-ink-soft">
                      {journeyQuery.data.source_csv_filename}
                    </dd>
                  </div>
                ) : null}
                {journeyQuery.data.bulk_process_id != null ? (
                  <div className="flex items-baseline gap-2">
                    <dt className="taste-micro">Batch</dt>
                    <dd>
                      <Link
                        to="/"
                        search={{
                          tab: 'history',
                          process: journeyQuery.data.bulk_process_id,
                        }}
                        className="taste-link tabular-nums text-[0.7rem]"
                        onClick={() => onOpenChange(false)}
                      >
                        process #{journeyQuery.data.bulk_process_id}
                      </Link>
                    </dd>
                  </div>
                ) : null}
              </dl>

              <Tabs defaultValue="history" className="mt-3">
                <TabsList>
                  <TabsTrigger value="history">History</TabsTrigger>
                  <TabsTrigger value="matching">Matching</TabsTrigger>
                  <TabsTrigger value="delivery">Delivery</TabsTrigger>
                </TabsList>

                <TabsContent value="history">
                  <div className="space-y-4">
                    <div className="overflow-x-auto rounded-lg border border-line/80 bg-paper/40 p-3">
                      <RunTimeline
                        steps={timelineSteps}
                        orientation="horizontal"
                        emptyMessage="No journey stages recorded."
                      />
                    </div>
                    <RunTimeline
                      steps={timelineSteps}
                      emptyMessage="No journey stages recorded."
                    />
                    <div className="flex flex-wrap gap-2 border-t border-line pt-4">
                      <Link
                        to="/requests/$requestId"
                        params={{ requestId: journeyQuery.data.request_id }}
                        className="taste-btn text-xs"
                        onClick={() => onOpenChange(false)}
                      >
                        Open full page →
                      </Link>
                      {isSuperAdmin ? (
                        <Link
                          to="/ops/runs"
                          search={{ request_id: journeyQuery.data.request_id }}
                          className="taste-btn text-xs"
                          onClick={() => onOpenChange(false)}
                        >
                          Runs for request →
                        </Link>
                      ) : null}
                    </div>
                  </div>
                </TabsContent>

                <TabsContent value="matching">
                  <MatchingReviewPanel
                    requestId={journeyQuery.data.request_id}
                    matching={matching}
                    isPending={matchingQuery.isPending}
                    isError={matchingQuery.isError}
                    canReviewActions={canReviewActions}
                    actionPending={actionPending}
                    actionError={actionError}
                    onPromote={(responseStatus) =>
                      promoteMutation.mutate(responseStatus)
                    }
                    onDecline={() => declineMutation.mutate()}
                  />
                </TabsContent>

                <TabsContent value="delivery">
                  <AccessHandoffPanel
                    requestId={journeyQuery.data.request_id}
                    artifact={artifactQuery.data}
                    isPending={artifactQuery.isPending}
                    isError={artifactQuery.isError}
                    canMutate={Boolean(isSuperAdmin || isAdmin)}
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
                  {copyNote ? <p className="taste-micro text-mute">{copyNote}</p> : null}
                  {deliveryMutation.isError ? (
                    <p className="text-[0.65rem] text-red-700">
                      {deliveryMutation.error instanceof Error
                        ? deliveryMutation.error.message
                        : 'Could not update delivery status'}
                    </p>
                  ) : null}
                </TabsContent>
              </Tabs>
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** @deprecated Prefer RequestDetailDrawer. */
export const RequestTriageDialog = RequestDetailDrawer
