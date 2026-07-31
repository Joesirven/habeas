import { useEffect, useRef, useState, type ReactNode } from 'react'

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
import {
  DROP_RESPONSE_STATUS_OPTIONS,
  getDropMatchingResultDetail,
  suggestedDropResponseStatus,
  type DropResponseStatusCode,
  type FulfillmentArtifact,
  type JourneyStage,
  type MatchingAttemptRow,
  type MatchingResultDetail,
  type MatchedPersonContact,
  type RunTimelineStep,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { actionReasonLabel } from '@/lib/legalJourneyLabels'
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

/** Dense process context strip — inbox/detail panes, not marketing cards. */
function ProcessContextStrip({
  items,
  compact = false,
}: {
  items: { label: string; value: ReactNode; show?: boolean }[]
  compact?: boolean
}) {
  const visible = items.filter((item) => item.show !== false)
  if (visible.length === 0) return null
  return (
    <dl
      className={cn(
        'grid gap-x-3 gap-y-1 rounded-md border border-line/70 bg-paper/40',
        compact
          ? 'grid-cols-2 px-2 py-1.5 sm:grid-cols-3'
          : 'grid-cols-2 px-2.5 py-2 sm:grid-cols-3',
      )}
    >
      {visible.map((item) => (
        <div key={item.label} className="min-w-0">
          <dt className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">
            {item.label}
          </dt>
          <dd className="mt-0.5 truncate text-[0.7rem] text-ink">{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}

/** Human matching-status noun — aligns with overlay / inbox "Matching status". */
function matchingStatusLabel(reviewStatus: string | null | undefined): string {
  const normalized = (reviewStatus ?? '').trim().toLowerCase()
  if (normalized === 'pending') return 'Pending review'
  if (normalized === 'approved') return 'Approved'
  if (normalized === 'declined' || normalized === 'rejected') return 'Declined'
  if (normalized === 'none' || normalized === '') return 'None'
  return (reviewStatus ?? '').replaceAll('_', ' ')
}

/** Compact "Matching results" value — type · count (overlay convention). */
function matchingResultsLabel(matching: MatchingResultDetail): string {
  const type = (
    matching.match_type ?? (matching.matched ? 'matched' : 'not matched')
  ).replaceAll('_', ' ')
  return `${type} · ${matching.match_count}`
}

function matchingProcessStripItems(
  matching: MatchingResultDetail,
): { label: string; value: ReactNode; show?: boolean }[] {
  const latestAttempt =
    matching.attempts && matching.attempts.length > 0
      ? [...matching.attempts].sort((a, b) => b.attempt_number - a.attempt_number)[0]
      : null
  return [
    {
      label: 'Matching results',
      value: matchingResultsLabel(matching),
    },
    {
      label: 'Matching status',
      value: (
        <Badge
          variant={reviewStatusVariant(matching.review_status)}
          className="normal-case tracking-normal"
        >
          {matchingStatusLabel(matching.review_status)}
        </Badge>
      ),
    },
    {
      label: 'Requestor',
      value: (
        <span className="font-mono">{matching.requestor_state ?? '—'}</span>
      ),
      show: Boolean(matching.requestor_state),
    },
    {
      label: 'Recorded',
      value: (
        <span className="tabular-nums">{formatTimestamp(matching.recorded_at)}</span>
      ),
      show: Boolean(matching.recorded_at),
    },
    {
      label: 'Attempted',
      value: (
        <span className="tabular-nums">
          {formatTimestamp(latestAttempt?.attempted_at)}
        </span>
      ),
      show: Boolean(latestAttempt?.attempted_at),
    },
    {
      label: 'Attempt id',
      value: (
        <span className="font-mono tabular-nums">{matching.attempt_id ?? '—'}</span>
      ),
      show: matching.attempt_id != null,
    },
    {
      label: 'Approval id',
      value: (
        <span className="font-mono tabular-nums">{matching.approval_id ?? '—'}</span>
      ),
      show: matching.approval_id != null,
    },
  ]
}

function accessHandoffNextStep(opts: {
  hasShareableUrl: boolean
  deliveryStatus: string | null | undefined
}): string {
  const status = (opts.deliveryStatus ?? '').toLowerCase()
  if (status === 'delivered') {
    return 'Delivered — no further handoff step unless recalled.'
  }
  if (status === 'recalled') {
    return 'Recalled — regenerate or re-send only after ops confirms a new artifact.'
  }
  if (status === 'failed') {
    return 'Delivery failed — fix the outbound path, then copy URL → send outside → mark delivered.'
  }
  if (!opts.hasShareableUrl) {
    return 'Next: wait for a shareable URL after fulfillment, then copy → send outside → mark delivered.'
  }
  return 'Next: Copy URL → send outside the platform → Mark delivered.'
}

export function journeyStageToTimelineStep(stage: JourneyStage): RunTimelineStep {
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

export async function fetchMatchingDetailOptional(
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

  if (isPending) {
    return <p className="py-3 text-xs text-ink-soft">Loading fulfillment artifact…</p>
  }

  const hasShareableUrl = Boolean(artifact?.shareable_url)
  const hasArtifactUri = Boolean(artifact?.fulfillment_artifact_uri)
  const deliveryStatus = artifact?.access_delivery_status ?? null
  const attemptStatus = artifact?.attempt_status ?? null
  const processStrip = (
    <ProcessContextStrip
      compact
      items={[
        {
          label: 'Delivery',
          value: (
            <span className="capitalize">{deliveryStatus ?? 'not set'}</span>
          ),
        },
        {
          label: 'Artifact',
          value: hasArtifactUri || hasShareableUrl ? 'Present' : 'Missing',
        },
        {
          label: 'Shareable URL',
          value: hasShareableUrl ? 'Ready' : 'Not ready',
        },
        {
          label: 'Fulfillment attempt',
          value: <span className="capitalize">{attemptStatus ?? '—'}</span>,
          show: Boolean(attemptStatus),
        },
      ]}
    />
  )
  const nextStep = (
    <p className="text-[0.7rem] text-ink-soft">
      {accessHandoffNextStep({ hasShareableUrl, deliveryStatus })}
    </p>
  )

  if (isError || (!hasShareableUrl && !hasArtifactUri)) {
    const placeholderDraft = buildAccessDeliveryDraft({
      requestId,
      shareableUrl: '[shareable URL will appear here after fulfillment]',
    })
    return (
      <div className="space-y-2 py-2 text-xs text-ink-soft">
        {processStrip}
        {nextStep}
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
            const copyBody = () => {
              void navigator.clipboard.writeText(placeholderDraft.body)
            }
            void navigator.clipboard.writeText(placeholderDraft.body).then(() => {
              actionToast.copied('Copied body', copyBody)
            })
          }}
        >
          Draft outbound
        </Button>
      </div>
    )
  }

  // Guard above: shareable URL and/or internal artifact URI is present.
  const readyArtifact = artifact as FulfillmentArtifact
  const url = readyArtifact.shareable_url ?? readyArtifact.fulfillment_artifact_uri ?? ''
  const draft = buildAccessDeliveryDraft({ requestId, shareableUrl: url })

  return (
    <div className="space-y-2 py-1 text-xs">
      {processStrip}
      {nextStep}
      <p className="text-ink-soft">
        Copy the shareable URL or draft an outbound message, then paste into your external
        mailer. Mark delivered when sent — the platform does not email requesters.
      </p>
      <div className="rounded-md border border-line bg-paper/50 px-2.5 py-1.5">
        <p className="taste-micro">Shareable URL</p>
        <p className="mt-1 break-all font-mono text-[0.7rem] text-ink">{url}</p>
      </div>
      {readyArtifact.fulfillment_artifact_uri &&
        readyArtifact.fulfillment_artifact_uri !== readyArtifact.shareable_url ? (
        <div className="rounded-md border border-line/60 px-2.5 py-1.5">
          <p className="taste-micro">Internal artifact (ops only)</p>
          <p className="mt-1 break-all font-mono text-[0.65rem] text-mute">
            {readyArtifact.fulfillment_artifact_uri}
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
        {readyArtifact.kind === 'access' && canMutate ? (
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
                  const copyBody = () => {
                    void navigator.clipboard.writeText(draft.body)
                  }
                  void navigator.clipboard.writeText(draft.body).then(() => {
                    actionToast.copied('Copied body', copyBody)
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
                  const copySubject = () => {
                    void navigator.clipboard.writeText(draft.subject)
                  }
                  void navigator.clipboard.writeText(draft.subject).then(() => {
                    actionToast.copied('Copied subject', copySubject)
                  })
                }}
              >
                Copy subject
              </Button>
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
  const processStrip = matching ? (
    <ProcessContextStrip
      compact={compact}
      items={matchingProcessStripItems(matching)}
    />
  ) : null

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
                label: 'Matching results',
                value: matchingResultsLabel(matching),
              },
              {
                label: 'Matched',
                value: matching.matched ? 'Yes' : 'No',
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
                label: 'Matching status',
                value: (
                  <Badge
                    variant={reviewStatusVariant(matching.review_status)}
                    className="normal-case tracking-normal"
                  >
                    {matchingStatusLabel(matching.review_status)}
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
                value: matching.decision_reason
                  ? actionReasonLabel(matching.decision_reason)
                  : '—',
              },
            ]}
          />
          {reviewActions}
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
        <p className="text-ink-soft">Loading matching results…</p>
      ) : null}
      {isError ? (
        <p className="text-red-700">
          Could not load matching results. Retry or open Workers → matching.
        </p>
      ) : null}
      {matching == null && !isPending && !isError ? (
        <div className="space-y-1 text-ink-soft">
          <p>No matching results for this request yet.</p>
          <p className="text-[0.65rem] text-mute">
            Detail appears once matching results exist; the queue can still wait on{' '}
            {actionReasonLabel('matching.review')} independently.
          </p>
        </div>
      ) : null}
      {processStrip}
      {matching && layout === 'tabs' ? tabsBody : null}
      {matching && layout !== 'tabs' ? (
        <>
          <StatusAccordion
            title="Matching results"
            glance={matchingResultsLabel(matching)}
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
            title="Matching status"
            glance={matchingStatusLabel(matching.review_status)}
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
                    {matchingStatusLabel(matching.review_status)}
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
                ? matchingStatusLabel(matching.review_status)
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
                <dd className="text-[0.7rem]">
                  {matching.decision_reason
                    ? actionReasonLabel(matching.decision_reason)
                    : '—'}
                </dd>
              </div>
            </dl>
          </StatusAccordion>
        </>
      ) : null}
    </div>
  )
}

import { RequestDetailOverlay } from '@/components/requests/RequestDetailOverlay'

export function RequestDetailDrawer({
  requestId,
  open,
  onOpenChange,
}: RequestDetailDrawerProps) {
  return (
    <RequestDetailOverlay requestId={requestId} open={open} onOpenChange={onOpenChange} />
  )
}

/** @deprecated Prefer RequestDetailDrawer. */
export const RequestTriageDialog = RequestDetailDrawer
