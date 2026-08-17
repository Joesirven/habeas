import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { ConfirmActionDialog } from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  DROP_RESPONSE_STATUS_OPTIONS,
  getDropMatchingResultDetail,
  listConnections,
  suggestedDropResponseStatus,
  type ConnectorReminder,
  type DropResponseStatusCode,
  type FulfillmentArtifact,
  type JourneyStage,
  type MatchingAttemptRow,
  type MatchingResultDetail,
  type MatchedPersonContact,
  type RunTimelineStep,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import {
  attemptIsGateBlocked,
  matchingConnectorGateBannerCopy,
  matchingConnectorGateChip,
  matchingGateFromAttempts,
  ownerConnectorsSearch,
  overlayCalloutShowsOwnerCta,
  resolveMatchingConnectorGate,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import { actionReasonLabel } from '@/lib/legalJourneyLabels'
import { cn } from '@/lib/utils'

/**
 * CA DROP response_status picker for Inbox fulfill confirms.
 *
 * E3 wire-up — optional DWID multi-select (status 3/4):
 * - `contacts` / `selectedDwids` / `onSelectedDwidsChange` — when `value` is 3 or 4,
 *   shows a checklist of matched contacts (parent should pre-select all dwids).
 * - When `value` is 5, DWID list is hidden; parent should clear `selectedDwids`.
 * - Promote/fulfill callbacks: `(status, dwids?) => void` — pass selected dwids for
 *   3/4, empty/`[]` for 5.
 */
export const OWNER_RESPONSE_STATUS_OPTIONS: {
  code: DropResponseStatusCode
  label: string
}[] = [
  { code: 3, label: 'Confirm match' },
  { code: 4, label: 'Multi-person' },
  { code: 5, label: 'Not a match' },
]

export type DropResponseStatusPersona = 'data_owner' | 'legal' | 'ops'

const LEGAL_OPS_HELPER =
  'Confirm the response status code written to DROP (3 Deleted · 4 Opted out · 5 Not found). Distinct from ingest Promote-to-raw.'

/** Persona chrome for Inbox fulfill confirm — AE29 owner language vs legal/ops codes. */
export function dropResponseStatusPickerChrome(
  persona?: DropResponseStatusPersona,
) {
  const ownerLanguage = persona === 'data_owner'
  return {
    ownerLanguage,
    options: ownerLanguage
      ? OWNER_RESPONSE_STATUS_OPTIONS
      : DROP_RESPONSE_STATUS_OPTIONS,
    legend: ownerLanguage ? 'Match result' : 'CA DROP status result',
    helperText: ownerLanguage ? null : LEGAL_OPS_HELPER,
    ariaLabel: ownerLanguage ? 'Match result' : 'DROP response status',
    showCodes: !ownerLanguage,
  }
}

export function ownerDropStatusLabel(code: number | null | undefined): string | null {
  return (
    OWNER_RESPONSE_STATUS_OPTIONS.find((row) => row.code === code)?.label ?? null
  )
}

export function matchingDispositionCopy(persona?: DropResponseStatusPersona) {
  const chrome = dropResponseStatusPickerChrome(persona)
  if (chrome.ownerLanguage) {
    return {
      blurb:
        'Matching disposition — Confirm the match result (Confirm match, Multi-person, or Not a match) and which selected people apply. Does not start Legal kickoff.',
      confirmTitle: 'Confirm this match?',
      confirmLabel: 'Confirm',
      pendingLabel: 'Confirming…',
      confirmDescription: (shortId: string) =>
        `Confirm the match result for ${shortId}…. This cannot be undone from here.`,
    }
  }
  return {
    blurb:
      'Matching disposition — Choose CA DROP status (3 Deleted · 4 Opted out · 5 Not found) and which matched people apply. Approves matching review for fulfillment readiness; does not start Legal kickoff.',
    confirmTitle: 'Fulfill this match?',
    confirmLabel: 'Fulfill',
    pendingLabel: 'Fulfilling…',
    confirmDescription: (shortId: string) =>
      `Approve matching review for ${shortId}… and set the CA DROP status result. This cannot be undone from the inbox.`,
  }
}

export function DropResponseStatusPicker({
  value,
  onChange,
  disabled,
  suggested,
  contacts,
  selectedDwids,
  onSelectedDwidsChange,
  persona,
}: {
  value: DropResponseStatusCode | null
  onChange: (code: DropResponseStatusCode) => void
  disabled?: boolean
  suggested?: DropResponseStatusCode | null
  contacts?: MatchedPersonContact[]
  selectedDwids?: string[]
  onSelectedDwidsChange?: (dwids: string[]) => void
  /** data_owner: Confirm match / Multi-person / Not a match. Legal/ops keep code+label chrome. */
  persona?: DropResponseStatusPersona
}) {
  const chrome = dropResponseStatusPickerChrome(persona)
  const needsDwids = value === 3 || value === 4
  const showDwidSelect =
    needsDwids &&
    contacts != null &&
    contacts.length > 0 &&
    onSelectedDwidsChange != null

  return (
    <fieldset className="space-y-1.5" disabled={disabled}>
      <legend className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
        {chrome.legend}
      </legend>
      {chrome.helperText ? (
        <p className="text-[0.65rem] text-ink-soft">{chrome.helperText}</p>
      ) : null}
      <div
        className="flex flex-wrap gap-1.5"
        role="radiogroup"
        aria-label={chrome.ariaLabel}
      >
        {chrome.options.map((option) => {
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
              {chrome.showCodes ? (
                <span className="font-mono tabular-nums">{option.code}</span>
              ) : null}
              <span>{option.label}</span>
              {isSuggested && !selected ? (
                <span className="text-[0.55rem] text-mute">suggested</span>
              ) : null}
            </button>
          )
        })}
      </div>
      {showDwidSelect ? (
        <MatchedContactsPanel
          contacts={contacts}
          selectable
          selectedDwids={selectedDwids ?? []}
          onSelectedDwidsChange={onSelectedDwidsChange}
          disabled={disabled}
        />
      ) : null}
      {value === 5 ? (
        <p className="text-[0.65rem] text-mute">
          {chrome.ownerLanguage
            ? 'Not a match — selected people are not sent (selection cleared).'
            : 'Not found — matched DWIDs are not sent (selection cleared).'}
        </p>
      ) : null}
    </fieldset>
  )
}

/** Compact DOB for labels: `01/01/80` from ISO `1980-01-01`. */
function compactDob(dob: string): string {
  const match = dob.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!match) return dob.trim()
  const [, year, month, day] = match
  return `${month}/${day}/${year!.slice(2)}`
}

/** Compact contact label: `{first_initial} {last_name} {state} {dob}`; initials fallback. */
export function formatMatchedContactLabel(contact: MatchedPersonContact): string {
  const lastName = contact.last_name?.trim()
  const namePart = lastName
    ? [contact.first_initial?.trim() || null, lastName].filter(Boolean).join(' ')
    : formatInitials(contact)
  const dob = contact.dob?.trim() ? compactDob(contact.dob) : null
  return [namePart, contact.state || null, dob].filter(Boolean).join(' ')
}

/** First selected (or first) contact label + ` +N more` when multiple. */
export function formatMatchedContactsSummary(
  contacts: MatchedPersonContact[],
  selectedDwids?: string[],
): string {
  if (contacts.length === 0) return '—'
  const selected =
    selectedDwids && selectedDwids.length > 0
      ? contacts.filter((contact) => selectedDwids.includes(contact.dwid))
      : contacts
  const shown = selected.length > 0 ? selected : contacts
  const firstLabel = formatMatchedContactLabel(shown[0]!)
  const rest = shown.length - 1
  return rest > 0 ? `${firstLabel} +${rest} more` : firstLabel
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
  connectorGate?: MatchingConnectorGate | null,
): { label: string; value: ReactNode; show?: boolean }[] {
  const latestAttempt =
    matching.attempts && matching.attempts.length > 0
      ? [...matching.attempts].sort((a, b) => b.attempt_number - a.attempt_number)[0]
      : null
  const gateChip = connectorGate ? matchingConnectorGateChip(connectorGate) : null
  return [
    {
      label: 'Connector gate',
      value: (
        <Badge variant={gateChip?.variant ?? 'ok'} className="normal-case tracking-normal">
          {gateChip?.label ?? 'Clear'}
        </Badge>
      ),
      show: Boolean(connectorGate),
    },
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

function attemptGlance(
  attempts: MatchingAttemptRow[],
  connectorGate?: MatchingConnectorGate | null,
): {
  label: string
  tone: 'default' | 'ok' | 'fail' | 'wait' | 'run'
} {
  if (connectorGate) {
    const chip = matchingConnectorGateChip(connectorGate)
    return {
      label: `${attempts.length} · ${chip.label}`,
      tone: 'fail',
    }
  }
  if (attempts.length === 0) return { label: 'None', tone: 'default' }
  const latest = [...attempts].sort((a, b) => b.attempt_number - a.attempt_number)[0]!
  const gateFromLatest = attemptIsGateBlocked(latest)
  if (gateFromLatest) {
    const chip = matchingConnectorGateChip(gateFromLatest)
    return { label: `${attempts.length} · ${chip.label}`, tone: 'fail' }
  }
  if (latest.status === 'success') {
    if (attemptIsUnmatchedSuccess(latest)) {
      return { label: `${attempts.length} · not found`, tone: 'wait' }
    }
    return { label: `${attempts.length} · ok`, tone: 'ok' }
  }
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

function auditFieldDisplay(
  payload: Record<string, unknown>,
  key: string,
): string | null {
  if (!(key in payload)) return null
  const value = payload[key]
  if (value == null) return '—'
  if (typeof value === 'boolean' || typeof value === 'number') return String(value)
  if (typeof value === 'string') return value || '—'
  try {
    return JSON.stringify(value)
  } catch {
    return '—'
  }
}

function coerceAuditObject(payload: unknown): Record<string, unknown> {
  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    return payload as Record<string, unknown>
  }
  return {}
}

function attemptIsUnmatchedSuccess(attempt: MatchingAttemptRow): boolean {
  if (attempt.status !== 'success') return false
  const audit = coerceAuditObject(attempt.audit_payload)
  const matchCount = typeof audit.match_count === 'number' ? audit.match_count : null
  const matchedVia =
    typeof audit.matched_via === 'string' ? audit.matched_via.toLowerCase() : ''
  // Domain: matched === (match_count == 1). Multi-match sets matched=false — not "not found".
  if (matchedVia.includes('missing')) return true
  if (matchCount === 0) return true
  if (matchCount != null && matchCount > 0) return false
  return audit.matched === false
}

function attemptRowBadge(attempt: MatchingAttemptRow): {
  label: string
  tone: 'default' | 'ok' | 'fail' | 'wait' | 'run'
} {
  const gate = attemptIsGateBlocked(attempt)
  if (gate) {
    const chip = matchingConnectorGateChip(gate)
    return { label: chip.label, tone: 'fail' }
  }
  if (attempt.status === 'success') {
    const audit = coerceAuditObject(attempt.audit_payload)
    const matchCount = typeof audit.match_count === 'number' ? audit.match_count : null
    if (attemptIsUnmatchedSuccess(attempt)) {
      const matchedVia =
        typeof audit.matched_via === 'string' ? audit.matched_via : null
      return {
        label:
          matchedVia && matchedVia.toLowerCase().includes('missing')
            ? `success · ${matchedVia}`
            : 'success · not found',
        tone: 'wait',
      }
    }
    if (matchCount != null && matchCount > 1) {
      return { label: `success · multi (${matchCount})`, tone: 'ok' }
    }
    return { label: 'success · matched', tone: 'ok' }
  }
  if (attempt.error_code || attempt.status.includes('error')) {
    return { label: attempt.error_code ?? attempt.status, tone: 'fail' }
  }
  if (attempt.status === 'in_flight' || attempt.status === 'claimed') {
    return { label: attempt.status, tone: 'run' }
  }
  return { label: attempt.error_code ?? attempt.status, tone: 'wait' }
}

export function AttemptRow({ attempt }: { attempt: MatchingAttemptRow }) {
  const [open, setOpen] = useState(false)
  const audit = coerceAuditObject(attempt.audit_payload)
  const badge = attemptRowBadge(attempt)
  const errorMessage = attempt.error_message ?? null

  const copyAttemptId = () => {
    void navigator.clipboard
      .writeText(String(attempt.id))
      .then(() => {
        actionToast.copied('Copied attempt id', copyAttemptId)
      })
      .catch(() => {
        actionToast.error({
          title: 'Copy failed',
          description: 'Could not copy attempt id to the clipboard.',
        })
      })
  }

  const summaryRows: { label: string; value: string; show?: boolean }[] = [
    { label: 'Attempted', value: formatTimestamp(attempt.attempted_at) },
    { label: 'Completed', value: formatTimestamp(attempt.completed_at) },
    { label: 'Status', value: attempt.status },
    {
      label: 'Error code',
      value: attempt.error_code ?? '—',
      show: Boolean(attempt.error_code),
    },
    {
      label: 'Gate code',
      value: auditFieldDisplay(audit, 'gate_code') ?? '—',
      show: 'gate_code' in audit || attempt.error_code === 'gate_blocked',
    },
    {
      label: 'Display status',
      value: auditFieldDisplay(audit, 'display_status') ?? '—',
      show: 'display_status' in audit,
    },
    {
      label: 'Blocking system',
      value: auditFieldDisplay(audit, 'blocking_system') ?? '—',
      show: 'blocking_system' in audit,
    },
    {
      label: 'Matched',
      value: auditFieldDisplay(audit, 'matched') ?? '—',
      show: 'matched' in audit,
    },
    {
      label: 'Match count',
      value: auditFieldDisplay(audit, 'match_count') ?? '—',
      show: 'match_count' in audit,
    },
    {
      label: 'Matched via',
      value: auditFieldDisplay(audit, 'matched_via') ?? '—',
      show: 'matched_via' in audit,
    },
    {
      label: 'Lookup state',
      value: auditFieldDisplay(audit, 'lookup_state') ?? '—',
      show: 'lookup_state' in audit,
    },
    {
      label: 'Duration ms',
      value: auditFieldDisplay(audit, 'duration_ms') ?? '—',
      show: 'duration_ms' in audit,
    },
    {
      label: 'Error class',
      value: auditFieldDisplay(audit, 'error_class') ?? '—',
      show: 'error_class' in audit,
    },
    {
      label: 'Error detail',
      value: auditFieldDisplay(audit, 'error_detail') ?? '—',
      show: 'error_detail' in audit,
    },
    {
      label: 'Retry scheduled',
      value: auditFieldDisplay(audit, 'retry_scheduled') ?? '—',
      show: 'retry_scheduled' in audit,
    },
  ]

  let auditJson = '—'
  try {
    auditJson = JSON.stringify(audit, null, 2)
  } catch {
    auditJson = String(audit)
  }

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
              <Badge variant={badge.tone} className="normal-case tracking-normal">
                {badge.label}
              </Badge>
              <span className="tabular-nums text-[0.6rem] text-mute">
                {open ? '▾' : '▸'}
              </span>
            </span>
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="space-y-1.5 border-t border-line/60 px-2 py-1.5 text-[0.65rem]">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-mute">Attempt id</span>
              <span className="font-mono tabular-nums text-ink">{attempt.id}</span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-6 px-1.5 text-[0.6rem]"
                aria-label="Copy attempt id"
                onClick={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  copyAttemptId()
                }}
              >
                Copy
              </Button>
            </div>
            <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
              {summaryRows
                .filter((row) => row.show !== false)
                .map((row) => (
                  <div key={row.label} className="min-w-0">
                    <dt className="text-mute">{row.label}</dt>
                    <dd className="truncate tabular-nums text-ink-soft">{row.value}</dd>
                  </div>
                ))}
            </dl>
            {errorMessage ? (
              <div>
                <p className="text-mute">Error message</p>
                <p className="mt-0.5 whitespace-pre-wrap break-words text-ink-soft">
                  {errorMessage}
                </p>
              </div>
            ) : null}
            <div>
              <p className="text-mute">Audit payload</p>
              <pre className="mt-0.5 max-h-48 overflow-auto rounded-md border border-line/60 bg-paper/50 p-1.5 font-mono text-[0.6rem] leading-snug text-ink-soft">
                {auditJson}
              </pre>
            </div>
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  )
}

/** Outbound Access delivery uses the render API (`AccessDeliveryEmailCard`) — no hardcoded draft. */

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
    return (
      <div className="space-y-2 py-2 text-xs text-ink-soft">
        {processStrip}
        {nextStep}
        <p>
          No shareable delivery URL yet for{' '}
          <span className="font-mono text-ink">{requestId.slice(0, 8)}…</span>.
        </p>
        <p className="text-mute">
          Access packs appear here after fulfillment. Use the Access delivery email
          card (render API) once the pack and identity gates are ready.
        </p>
      </div>
    )
  }

  // Guard above: shareable URL and/or internal artifact URI is present.
  const readyArtifact = artifact as FulfillmentArtifact
  const url = readyArtifact.shareable_url ?? readyArtifact.fulfillment_artifact_uri ?? ''

  return (
    <div className="space-y-2 py-1 text-xs">
      {processStrip}
      {nextStep}
      <p className="text-ink-soft">
        Copy the shareable URL, or use the Access delivery email card to render the
        template and paste into your external mailer. Mark delivered when sent — the
        platform does not email requesters.
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

/** Emphasized fail callout when matched person contact enrichment is unavailable. */
export function MatchedContactsUnavailableCallout({
  matching,
}: {
  matching?: MatchingResultDetail
}) {
  const err = matching?.matched_contacts_error
  const message = err?.message?.trim() || null
  const code = err?.code?.trim() || null
  const stage = err?.stage?.trim() || null
  const hint = err?.hint?.trim() || null
  const excType = err?.exc_type?.trim() || null

  return (
    <div
      role="alert"
      className="space-y-1 rounded-md border border-red-300 bg-red-50 px-2.5 py-2 text-[0.7rem]"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <p className="font-medium text-red-800">Matched person details unavailable</p>
        {code ? (
          <span className="rounded border border-red-300/80 bg-red-50 px-1 py-px font-mono text-[0.6rem] tabular-nums text-red-700">
            {code}
          </span>
        ) : null}
        {stage ? (
          <span className="rounded border border-red-200/80 bg-red-50/60 px-1 py-px font-mono text-[0.6rem] text-red-700/80">
            {stage}
          </span>
        ) : null}
      </div>
      <p className="text-red-700">
        {message ??
          'Contact enrichment returned unavailable without a diagnostic reason. Reload this request; if it persists, the API may be an older build.'}
      </p>
      <p className="text-[0.65rem] text-red-800/80">
        {hint ?? 'Reload this request, then check requestor state and matching configuration.'}
      </p>
      {excType ? (
        <p className="font-mono text-[0.6rem] text-red-800/70">type: {excType}</p>
      ) : null}
    </div>
  )
}

function MatchedContactsPanel({
  matching,
  contacts: contactsProp,
  selectable = false,
  selectedDwids,
  onSelectedDwidsChange,
  disabled = false,
}: {
  matching?: MatchingResultDetail
  contacts?: MatchedPersonContact[]
  selectable?: boolean
  selectedDwids?: string[]
  onSelectedDwidsChange?: (dwids: string[]) => void
  disabled?: boolean
}) {
  const contacts = contactsProp ?? matching?.matched_contacts ?? []
  const status = matching?.matched_contacts_status
  const matchCount = matching?.match_count ?? contacts.length

  if (!selectable && matchCount <= 0) return null
  if (contacts.length === 0 && matchCount <= 0) return null

  if (status === 'unavailable' && contacts.length === 0) {
    return <MatchedContactsUnavailableCallout matching={matching} />
  }

  if (contacts.length === 0) {
    return (
      <p className="text-[0.7rem] text-mute">
        No person records returned for the matched DWID(s).
      </p>
    )
  }

  if (selectable && onSelectedDwidsChange) {
    const selected = selectedDwids ?? []
    const toggle = (dwid: string) => {
      if (selected.includes(dwid)) {
        onSelectedDwidsChange(selected.filter((id) => id !== dwid))
      } else {
        onSelectedDwidsChange([...selected, dwid])
      }
    }
    return (
      <div className="space-y-1.5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
            Matched DWIDs
          </p>
          <p className="min-w-0 truncate text-[0.65rem] text-ink-soft">
            {formatMatchedContactsSummary(contacts, selected)}
          </p>
        </div>
        <ul className="space-y-0.5 rounded-md border border-line/70 bg-paper/40 px-2 py-1.5">
          {contacts.map((contact) => {
            const checked = selected.includes(contact.dwid)
            const inputId = `dwid-${contact.dwid}`
            return (
              <li key={contact.dwid}>
                <label
                  htmlFor={inputId}
                  className={cn(
                    'flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-[0.7rem] hover:bg-panel/40',
                    disabled && 'cursor-not-allowed opacity-50',
                  )}
                >
                  <input
                    id={inputId}
                    type="checkbox"
                    className="size-3.5 shrink-0 accent-habeas-navy"
                    checked={checked}
                    disabled={disabled}
                    onChange={() => toggle(contact.dwid)}
                  />
                  <span className="min-w-0 flex-1 truncate text-ink">
                    {formatMatchedContactLabel(contact)}
                  </span>
                  <span className="shrink-0 font-mono tabular-nums text-[0.6rem] text-mute">
                    {contact.dwid}
                  </span>
                </label>
              </li>
            )
          })}
        </ul>
      </div>
    )
  }

  if (matching?.match_type === 'single_match' && contacts.length === 1) {
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
                    {formatMatchedContactLabel(contact)}
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

/**
 * R52 — banner when connector freshness gate blocks matching (KD18).
 * Uses attempt audit when present; otherwise honest fallback from reminders/connections.
 */
export function MatchingConnectorGateBanner({
  gate,
  compact = false,
  showOwnerLink = false,
  connectorsVerticalId = null,
}: {
  gate: MatchingConnectorGate | null | undefined
  compact?: boolean
  showOwnerLink?: boolean
  connectorsVerticalId?: string | null
}) {
  if (!gate?.blocked) return null
  const chip = matchingConnectorGateChip(gate)
  const copy = matchingConnectorGateBannerCopy(gate)
  const showConnectorsCta =
    showOwnerLink && overlayCalloutShowsOwnerCta('data_owner', connectorsVerticalId)
  return (
    <div
      className={cn(
        'rounded-md border border-red-300/80 bg-red-50/80',
        compact ? 'px-2 py-1.5' : 'px-2.5 py-2',
      )}
      role="status"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={chip.variant} className="normal-case tracking-normal">
          {chip.label}
        </Badge>
        <span className="text-[0.7rem] font-medium text-red-950">{copy.title}</span>
      </div>
      <p className="mt-1 text-[0.65rem] leading-snug text-red-900/90">{copy.description}</p>
      {showConnectorsCta ? (
        <Link
          to="/owner/connectors"
          search={ownerConnectorsSearch(connectorsVerticalId)}
          className="mt-1 inline-block text-[0.65rem] font-medium text-habeas-navy underline-offset-2 hover:underline"
        >
          Open connectors
        </Link>
      ) : null}
    </div>
  )
}

/** Attempt audit first; ops connections or owner reminders when attempts lack gate fields. */
export function useMatchingConnectorGate(options: {
  attempts?: MatchingAttemptRow[] | null
  reminders?: ConnectorReminder[] | null
  fetchConnections?: boolean
}) {
  const fromAttempts = useMemo(
    () => matchingGateFromAttempts(options.attempts),
    [options.attempts],
  )

  const connectionsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'connections', 'matching-gate'],
    queryFn: async () => (await listConnections()).connections,
    enabled: Boolean(options.fetchConnections && !fromAttempts),
    staleTime: 60_000,
    retry: false,
  })

  return useMemo(
    () =>
      resolveMatchingConnectorGate({
        attempts: options.attempts,
        connections: connectionsQuery.data,
        reminders: options.reminders,
      }),
    [options.attempts, connectionsQuery.data, options.reminders],
  )
}

/**
 * Matching review panel — fulfill/decline + attempt drill-down.
 *
 * E3 wire-up — `onPromote` / fulfill disposition:
 *   `(responseStatus: DropResponseStatusCode, dwids?: string[]) => void`
 * Pass selected DWIDs when status is 3 or 4; pass `[]` (or omit) for status 5.
 * Panel pre-selects all matched contact dwids when suggested/chosen status is 3/4
 * and clears selection when status is 5.
 */
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
  connectorReminders,
  fetchConnectorConnections = false,
  persona,
}: {
  requestId: string
  matching: MatchingResultDetail | null | undefined
  isPending: boolean
  isError: boolean
  canReviewActions: boolean
  actionPending: boolean
  /** Fulfill with DROP status + optional selected DWIDs (3/4). */
  onPromote: (responseStatus: DropResponseStatusCode, dwids?: string[]) => void
  onDecline: () => void
  /** Denser layout for inbox review pane. */
  compact?: boolean
  /** Tabbed sections instead of collapsible accordions (inbox detail). */
  layout?: 'accordion' | 'tabs'
  /** Hide fulfill/decline buttons (e.g. when inbox header owns actions). */
  hideActions?: boolean
  /** Soft reminders from `/me` when matching payload lacks gate audit. */
  connectorReminders?: ConnectorReminder[] | null
  /** Ops/admin — load gated connections when attempts lack gate audit. */
  fetchConnectorConnections?: boolean
  /** Owner-language picker when `data_owner`; legal/ops keep code chrome. */
  persona?: 'data_owner' | 'legal' | 'ops'
}) {
  const [confirm, setConfirm] = useState<'fulfill' | 'decline' | null>(null)
  const suggestedStatus = suggestedDropResponseStatus(
    matching?.match_type,
    matching?.match_count,
  )
  const contactDwids = (matching?.matched_contacts ?? []).map((contact) => contact.dwid)
  const [fulfillStatus, setFulfillStatus] = useState<DropResponseStatusCode | null>(
    suggestedStatus,
  )
  const [selectedDwids, setSelectedDwids] = useState<string[]>(() =>
    suggestedStatus === 3 || suggestedStatus === 4 ? contactDwids : [],
  )
  const wasActionPending = useRef(false)
  useEffect(() => {
    if (wasActionPending.current && !actionPending) setConfirm(null)
    wasActionPending.current = actionPending
  }, [actionPending])
  useEffect(() => {
    if (confirm === 'fulfill') {
      const next = suggestedDropResponseStatus(
        matching?.match_type,
        matching?.match_count,
      )
      setFulfillStatus(next)
      const dwids = (matching?.matched_contacts ?? []).map((contact) => contact.dwid)
      setSelectedDwids(next === 3 || next === 4 ? dwids : [])
    }
  }, [confirm, matching?.match_type, matching?.match_count, matching?.matched_contacts])

  const handleFulfillStatusChange = (code: DropResponseStatusCode) => {
    setFulfillStatus(code)
    if (code === 5) {
      setSelectedDwids([])
      return
    }
    if (code === 3 || code === 4) {
      setSelectedDwids((matching?.matched_contacts ?? []).map((contact) => contact.dwid))
    }
  }

  const fulfillNeedsDwids = fulfillStatus === 3 || fulfillStatus === 4
  // Status 3/4 require an explicit DWID selection (do not treat empty contacts as ready —
  // empty [] would let the API default to the full matched set).
  const fulfillDwidsReady = !fulfillNeedsDwids || selectedDwids.length > 0

  const connectorGate = useMatchingConnectorGate({
    attempts: matching?.attempts,
    reminders: connectorReminders,
    fetchConnections: fetchConnectorConnections,
  })

  const attempts = matching?.attempts ?? []
  const attemptStatus = attemptGlance(attempts, connectorGate)
  const assignment = matching?.assignment?.assignee_identity
  const processStrip = matching ? (
    <ProcessContextStrip
      compact={compact}
      items={matchingProcessStripItems(matching, connectorGate)}
    />
  ) : null

  const dispositionCopy = matchingDispositionCopy(persona)
  const ownerConnectorVertical =
    connectorReminders?.find((reminder) => reminder.severity === 'overdue')
      ?.vertical_id ?? connectorReminders?.[0]?.vertical_id ?? null

  const reviewActions = canReviewActions && !hideActions ? (
    <div className="space-y-1.5 pt-1">
      <p className="text-[0.65rem] text-ink-soft">{dispositionCopy.blurb}</p>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={actionPending} onClick={() => setConfirm('fulfill')}>
          {actionPending && confirm === 'fulfill'
            ? dispositionCopy.pendingLabel
            : dispositionCopy.confirmLabel}
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
        title={dispositionCopy.confirmTitle}
        description={dispositionCopy.confirmDescription(requestId.slice(0, 8))}
        confirmLabel={dispositionCopy.confirmLabel}
        confirming={actionPending && confirm === 'fulfill'}
        confirmDisabled={fulfillStatus == null || !fulfillDwidsReady}
        onConfirm={() => {
          if (fulfillStatus == null) return
          const dwids = fulfillStatus === 5 ? [] : selectedDwids
          onPromote(fulfillStatus, dwids)
        }}
      >
        <DropResponseStatusPicker
          value={fulfillStatus}
          onChange={handleFulfillStatusChange}
          disabled={actionPending}
          suggested={suggestedStatus}
          contacts={matching?.matched_contacts}
          selectedDwids={selectedDwids}
          onSelectedDwidsChange={setSelectedDwids}
          persona={persona}
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
      <MatchingConnectorGateBanner
        gate={connectorGate}
        compact={compact}
        showOwnerLink={persona === 'data_owner'}
        connectorsVerticalId={ownerConnectorVertical}
      />
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
