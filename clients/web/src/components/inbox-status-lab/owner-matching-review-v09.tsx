import { useEffect, useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'

import {
  formatMatchedContactLabel,
  formatMatchedContactsSummary,
  matchedChannelsFromDetail,
  matchingDispositionCopy,
  safeMatchedContacts,
} from '@/components/requests/RequestTriageDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useMe } from '@/lib/auth'
import {
  isDataCatalogVertical,
  matchingConnectorGateBannerCopy,
  matchingConnectorGateChip,
  ownerConnectorsSearch,
  resolveMatchingConnectorGate,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import {
  inboxIntakeSourceLabel,
  matchTypeLabel,
} from '@/lib/inbox-batch-status'
import {
  inboxDisplayConnections,
  inboxItemChannels,
  inboxReviewItemSystemLabel,
  inboxReviewItemVerticalLabel,
  type InboxItemChannel,
} from '@/lib/inbox-status-lab'
import { catalogSystemDisplayLabel } from '@/lib/legalJourneyLabels'
import { cn } from '@/lib/utils'

import {
  applyNeedsPeople,
  resultViewEmpty,
} from '../matching-results-lab/ResultViewChrome'
import {
  matchingLabItemKey,
  type MatchingResultsViewProps,
} from '../matching-results-lab/matching-results-lab-types'

/** Product/consumer short guided steps: this request → this system → these people → confirm. */
export const OWNER_MATCHING_REVIEW_V09_PHILOSOPHY =
  'Product/consumer short guided steps: this request → this system → these people → confirm.'

type GuideStep = 'request' | 'system' | 'people' | 'blocked' | 'confirm'
type PeopleAction = '3' | '4'

const MATCHING_REVIEW_SLA_MS = 48 * 60 * 60 * 1000
const DUE_SOON_MS = 24 * 60 * 60 * 1000

/** Identifier surfaces on one matching attempt — not steps, channels, or separate reviews. */
const SURFACE_ORDER = ['email', 'phone', 'ndz'] as const
const SURFACE_LABELS: Record<InboxItemChannel, string> = {
  email: 'Email',
  phone: 'Phone',
  ndz: 'NDZ',
}

const PEOPLE_ACTIONS: { id: PeopleAction; label: string; hint: string }[] = [
  { id: '3', label: 'Delete', hint: 'Record a delete for the selected people in this system.' },
  { id: '4', label: 'Opt-in', hint: 'Record an opt-in for the selected people in this system.' },
]

function matchingSurfaces(
  item: MatchingResultsViewProps['item'],
  detail: MatchingResultsViewProps['detail'],
): InboxItemChannel[] {
  const seen = new Set<InboxItemChannel>()
  if (item) {
    for (const surface of inboxItemChannels(item)) seen.add(surface)
  }
  for (const surface of matchedChannelsFromDetail(detail)) seen.add(surface)
  return SURFACE_ORDER.filter((surface) => seen.has(surface))
}

function formatSurfaceList(surfaces: InboxItemChannel[]): string {
  return surfaces.map((surface) => SURFACE_LABELS[surface]).join(' · ')
}

function shortRequestId(requestId: string | undefined): string {
  const id = requestId?.trim() ?? ''
  return id ? `${id.slice(0, 8)}…` : '—'
}

function dueFacts(
  item: MatchingResultsViewProps['item'],
  now = Date.now(),
): { label: string; bucket: 'overdue' | 'due_soon' | 'on_track' | 'unknown' } {
  const raw = item?.requested_at?.trim() || item?.received_at?.trim()
  if (!raw) return { label: 'No due date', bucket: 'unknown' }
  const start = new Date(raw)
  if (Number.isNaN(start.getTime())) return { label: 'No due date', bucket: 'unknown' }
  const due = new Date(start.getTime() + MATCHING_REVIEW_SLA_MS)
  const when = due.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
  const msLeft = due.getTime() - now
  if (msLeft < 0) return { label: `Overdue · was ${when}`, bucket: 'overdue' }
  if (msLeft <= DUE_SOON_MS) return { label: `Due soon · ${when}`, bucket: 'due_soon' }
  return { label: `Due ${when}`, bucket: 'on_track' }
}

function isHiddenSystem(system: string | null | undefined): boolean {
  const id = system?.trim().toLowerCase() ?? ''
  return id === 'cassandra' || isDataCatalogVertical(id)
}

function activeSystemLabel({
  item,
  detail,
}: Pick<MatchingResultsViewProps, 'item' | 'detail'>): string {
  const system = detail?.system ?? item?.system ?? item?.system_id ?? null
  if (isHiddenSystem(system) && (detail?.vertical ?? item?.vertical) !== 'test') {
    return 'This system'
  }
  return (
    catalogSystemDisplayLabel(system, {
      vertical: detail?.vertical ?? item?.vertical,
      systemLabel: detail?.system_label ?? item?.system_label,
    }) ??
    inboxReviewItemSystemLabel({
      request_id: item?.request_id ?? '',
      system,
      system_label: detail?.system_label ?? item?.system_label,
      vertical: detail?.vertical ?? item?.vertical,
    }) ??
    'This system'
  )
}

function otherSystemLabels(item: MatchingResultsViewProps['item']): string[] {
  if (!item) return []
  const active = (item.system ?? item.system_id)?.trim() || null
  return inboxDisplayConnections(item)
    .map((connection) => ({
      id: connection.system?.trim() || '',
      label: inboxReviewItemSystemLabel({
        request_id: item.request_id,
        system: connection.system,
        system_label: connection.system_label,
        vertical: connection.vertical ?? item.vertical,
      }),
    }))
    .filter((row) => row.label && row.id && row.id !== active && !isHiddenSystem(row.id))
    .map((row) => row.label as string)
}

function guideSteps(blocked: boolean): { id: GuideStep; n: number; label: string }[] {
  if (blocked) {
    return [
      { id: 'request', n: 1, label: 'This request' },
      { id: 'blocked', n: 2, label: 'Blocked' },
      { id: 'confirm', n: 3, label: 'Confirm' },
    ]
  }
  return [
    { id: 'request', n: 1, label: 'This request' },
    { id: 'system', n: 2, label: 'This system' },
    { id: 'people', n: 3, label: 'These people' },
    { id: 'confirm', n: 4, label: 'Confirm' },
  ]
}

function contactSearchHaystack(contact: {
  dwid: string
  first_initial?: string | null
  last_initial?: string | null
  last_name?: string | null
  state?: string | null
}): string {
  return [
    formatMatchedContactLabel(contact),
    contact.last_name,
    contact.first_initial,
    contact.last_initial,
    contact.state,
  ]
    .filter((value): value is string => Boolean(value?.trim()))
    .join(' ')
    .toLowerCase()
}

function safeGateCopy(gate: MatchingConnectorGate, systemName: string): {
  title: string
  description: string
} {
  const displaySystem = isHiddenSystem(gate.system) ? null : gate.system
  const copy = matchingConnectorGateBannerCopy({ ...gate, system: displaySystem })
  return {
    title: copy.title.replace(/cassandra/gi, systemName),
    description: copy.description.replace(/cassandra/gi, systemName),
  }
}

function connectorsVerticalId(
  item: MatchingResultsViewProps['item'],
  detail: MatchingResultsViewProps['detail'],
): string | null {
  const vertical = (detail?.vertical ?? item?.vertical)?.trim() || null
  if (!vertical || isDataCatalogVertical(vertical)) return null
  return vertical
}

/** Owner matching-only — short product steps, not the legal journey rail. */
export function OwnerMatchingReviewV09(props: MatchingResultsViewProps) {
  const empty = resultViewEmpty(props.loading, Boolean(props.item))
  if (empty) return empty
  return <OwnerMatchingGuide key={matchingLabItemKey(props.item!)} {...props} />
}

function OwnerMatchingGuide({
  item,
  detail,
  contacts,
  ownerLanguage,
  statusOptions,
  statusId,
  onStatusChange,
  selectedDwids,
  onSelectedDwidsChange,
  disabled,
  pending,
  onApply,
}: MatchingResultsViewProps) {
  const { me } = useMe()
  const people = safeMatchedContacts(contacts)
  const gate = useMemo(
    () =>
      resolveMatchingConnectorGate({
        attempts: detail?.attempts,
        reminders: (me?.connector_reminders ?? []).filter(
          (reminder) => !isHiddenSystem(reminder.system),
        ),
      }),
    [detail?.attempts, me?.connector_reminders],
  )
  const matchingBlocked = Boolean(gate?.blocked)
  const steps = guideSteps(matchingBlocked)
  const [step, setStep] = useState<GuideStep>('request')
  const [draftStatus, setDraftStatus] = useState<string | null>(statusId)
  const [peopleAction, setPeopleAction] = useState<PeopleAction>(
    statusId === '4' ? '4' : '3',
  )
  const [peopleQuery, setPeopleQuery] = useState('')

  const source = inboxIntakeSourceLabel(item?.intake_source)
  const requestId = shortRequestId(item?.request_id)
  const due = dueFacts(item)
  const systemName = activeSystemLabel({ item, detail })
  const verticalName = item ? inboxReviewItemVerticalLabel(item) : null
  const alsoSystems = otherSystemLabels(item)
  const matchHint = matchTypeLabel(detail?.match_type ?? item?.match_type, ownerLanguage)
  const surfaces = matchingSurfaces(item, detail)
  const surfaceList = formatSurfaceList(surfaces)
  const peopleRequired = applyNeedsPeople(draftStatus, selectedDwids)
  const confirmCopy = matchingDispositionCopy('data_owner')
  const stepIndex = steps.findIndex((entry) => entry.id === step)
  const applyBlocked =
    disabled || pending || matchingBlocked || draftStatus == null || peopleRequired
  const includedPeople = people.filter((contact) => selectedDwids.includes(contact.dwid))
  const addablePeople = useMemo(() => {
    const needle = peopleQuery.trim().toLowerCase()
    return people.filter((contact) => {
      if (!contact.dwid || selectedDwids.includes(contact.dwid)) return false
      if (!needle) return true
      return contactSearchHaystack(contact).includes(needle)
    })
  }, [people, peopleQuery, selectedDwids])
  const connectorsVertical = connectorsVerticalId(item, detail)
  const gateChip = gate ? matchingConnectorGateChip(gate) : null
  const gateCopy = gate ? safeGateCopy(gate, systemName) : null

  useEffect(() => {
    if (matchingBlocked && (step === 'system' || step === 'people')) {
      setStep('blocked')
    }
    if (!matchingBlocked && step === 'blocked') setStep('system')
  }, [matchingBlocked, step])

  useEffect(() => {
    if (step !== 'people' || people.length === 0 || selectedDwids.length > 0) return
    if (draftStatus === '5') return
    const dwids = people.map((contact) => contact.dwid).filter(Boolean)
    if (dwids.length > 0) onSelectedDwidsChange(dwids)
  }, [draftStatus, onSelectedDwidsChange, people, selectedDwids.length, step])

  function goTo(next: GuideStep) {
    const nextIdx = steps.findIndex((entry) => entry.id === next)
    if (nextIdx === -1 || nextIdx > stepIndex) return
    setStep(next)
  }

  function goNext() {
    if (step === 'request') {
      setStep(matchingBlocked ? 'blocked' : 'system')
      return
    }
    if (step === 'system') {
      if (people.length > 0 && selectedDwids.length === 0 && draftStatus !== '5') {
        onSelectedDwidsChange(people.map((contact) => contact.dwid).filter(Boolean))
      }
      setStep('people')
      return
    }
    if (step === 'blocked') {
      setStep('confirm')
      return
    }
    if (step === 'people') {
      const nextStatus =
        selectedDwids.length === 0 ? '5' : peopleAction
      setDraftStatus(nextStatus)
      setStep('confirm')
    }
  }

  function goBack() {
    if (step === 'confirm') {
      setStep(matchingBlocked ? 'blocked' : 'people')
      return
    }
    if (step === 'people') {
      setStep('system')
      return
    }
    if (step === 'blocked' || step === 'system') setStep('request')
  }

  function choosePeopleAction(next: PeopleAction) {
    setPeopleAction(next)
    setDraftStatus(next)
  }

  function removePerson(dwid: string) {
    onSelectedDwidsChange(selectedDwids.filter((id) => id !== dwid))
  }

  function addPerson(dwid: string) {
    if (!dwid || selectedDwids.includes(dwid)) return
    onSelectedDwidsChange([...selectedDwids, dwid])
    setPeopleQuery('')
  }

  function commitAndApply() {
    if (matchingBlocked || draftStatus == null || applyNeedsPeople(draftStatus, selectedDwids)) {
      return
    }
    const nextDwids = draftStatus === '5' ? [] : selectedDwids
    onStatusChange(draftStatus)
    onSelectedDwidsChange(nextDwids)
    onApply({ statusId: draftStatus, selectedDwids: nextDwids })
  }

  return (
    <div className="space-y-3">
      <header className="space-y-0.5">
        <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
          Review this match
        </p>
        <p className="text-sm text-ink">
          {matchingBlocked
            ? 'Matching is gated — refresh the connector first.'
            : 'Four short steps — then confirm.'}
        </p>
      </header>

      <ol className="flex flex-wrap items-center gap-1" aria-label="Match review steps">
        {steps.map((entry, index) => {
          const current = step === entry.id
          const reached = index <= stepIndex
          return (
            <li key={entry.id} className="flex items-center gap-1">
              {index > 0 ? (
                <span className="px-0.5 text-[0.6rem] text-mute" aria-hidden>
                  →
                </span>
              ) : null}
              <button
                type="button"
                disabled={disabled || pending || !reached}
                onClick={() => goTo(entry.id)}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[0.65rem]',
                  current
                    ? 'bg-habeas-navy/10 font-medium text-habeas-navy'
                    : reached
                      ? 'text-ink-soft hover:text-ink'
                      : 'text-mute',
                )}
              >
                <span
                  className={cn(
                    'inline-flex size-4 items-center justify-center rounded-full text-[0.55rem] tabular-nums',
                    current
                      ? 'bg-habeas-navy text-white'
                      : reached
                        ? 'border border-habeas-navy/40 text-habeas-navy'
                        : 'border border-line text-mute',
                  )}
                >
                  {entry.n}
                </span>
                {entry.label}
              </button>
            </li>
          )
        })}
      </ol>

      {step === 'request' ? (
        <section className="space-y-3 rounded-md border border-line bg-paper px-3 py-3">
          <p className="text-sm font-medium text-ink">This request</p>
          <p className="text-xs text-ink-soft">
            A {source} privacy request is waiting on your match review.
          </p>
          <dl className="grid gap-2 text-xs sm:grid-cols-3">
            <div>
              <dt className="text-[0.65rem] text-mute">Request</dt>
              <dd className="font-medium tabular-nums text-ink">{requestId}</dd>
            </div>
            <div>
              <dt className="text-[0.65rem] text-mute">Source</dt>
              <dd className="font-medium text-ink">{source}</dd>
            </div>
            <div>
              <dt className="text-[0.65rem] text-mute">Due</dt>
              <dd>
                <Badge
                  variant={
                    due.bucket === 'overdue'
                      ? 'fail'
                      : due.bucket === 'due_soon'
                        ? 'wait'
                        : 'default'
                  }
                  className="normal-case tracking-normal"
                >
                  {due.label}
                </Badge>
              </dd>
            </div>
          </dl>
          <Button type="button" size="sm" disabled={disabled || pending} onClick={goNext}>
            Continue
          </Button>
        </section>
      ) : null}

      {step === 'system' ? (
        <section className="space-y-3 rounded-md border border-line bg-paper px-3 py-3">
          <p className="text-sm font-medium text-ink">This system</p>
          <p className="text-xs text-ink-soft">
            You are reviewing matches in one system
            {verticalName ? ` on ${verticalName}` : ''}.
          </p>
          <div className="rounded-md border border-habeas-navy/20 bg-habeas-navy/[0.03] px-3 py-2">
            <p className="text-[0.65rem] text-mute">System</p>
            <p className="text-sm font-medium text-habeas-navy">{systemName}</p>
          </div>
          {alsoSystems.length > 0 ? (
            <p className="text-[0.65rem] text-ink-soft">
              Also on this request: {alsoSystems.join(' · ')}
            </p>
          ) : null}
          <div className="flex gap-1.5">
            <Button type="button" size="sm" disabled={disabled || pending} onClick={goNext}>
              Continue
            </Button>
            <Button type="button" variant="ghost" size="sm" disabled={pending} onClick={goBack}>
              Back
            </Button>
          </div>
        </section>
      ) : null}

      {step === 'blocked' ? (
        <section className="space-y-3 rounded-md border border-red-300/80 bg-red-50/80 px-3 py-3">
          <div className="flex flex-wrap items-center gap-2">
            {gateChip ? (
              <Badge variant={gateChip.variant} className="normal-case tracking-normal">
                {gateChip.label}
              </Badge>
            ) : (
              <Badge variant="fail" className="normal-case tracking-normal">
                Action required
              </Badge>
            )}
            <p className="text-sm font-medium text-ink">
              {gateCopy?.title ?? 'Matching is blocked'}
            </p>
          </div>
          <p className="text-xs text-ink-soft">
            {gateCopy?.description ??
              `Matching for ${systemName} is blocked until the connector is connected or refreshed.`}
          </p>
          <div className="flex flex-wrap gap-1.5">
            <Button type="button" size="sm" asChild>
              <Link to="/owner/connectors" search={ownerConnectorsSearch(connectorsVertical)}>
                Open connectors
              </Link>
            </Button>
            <Button type="button" variant="outline" size="sm" disabled={disabled || pending} onClick={goNext}>
              Continue
            </Button>
            <Button type="button" variant="ghost" size="sm" disabled={pending} onClick={goBack}>
              Back
            </Button>
          </div>
        </section>
      ) : null}

      {step === 'people' ? (
        <section className="space-y-3 rounded-md border border-line bg-paper px-3 py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-medium text-ink">These people</p>
            {matchHint ? (
              <Badge variant="default" className="normal-case tracking-normal">
                {matchHint}
              </Badge>
            ) : null}
          </div>

          <fieldset className="space-y-1.5" disabled={disabled || pending}>
            <legend className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
              Record in {systemName}
            </legend>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Delete or opt-in">
              {PEOPLE_ACTIONS.map((action) => {
                const selected = peopleAction === action.id
                return (
                  <button
                    key={action.id}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    disabled={disabled || pending}
                    onClick={() => choosePeopleAction(action.id)}
                    className={cn(
                      'rounded-md border px-2.5 py-1.5 text-xs',
                      selected
                        ? 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
                        : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
                    )}
                  >
                    {action.label}
                  </button>
                )
              })}
            </div>
            <p className="text-[0.65rem] text-mute">
              {PEOPLE_ACTIONS.find((action) => action.id === peopleAction)?.hint}
            </p>
          </fieldset>

          {people.length === 0 ? (
            <>
              <p className="text-xs text-ink-soft">
                No people matched in {systemName}. Continue to record that this is not a match.
              </p>
              {surfaceList ? (
                <p className="text-[0.65rem] text-mute">Found on {surfaceList} — one match.</p>
              ) : null}
            </>
          ) : (
            <>
              <p className="text-xs text-ink-soft">
                Matches in {systemName} are pre-filled. Remove anyone who should not apply, or
                add another person from this system.
              </p>
              {surfaceList ? (
                <p className="text-[0.65rem] text-mute">Surfaces · {surfaceList}</p>
              ) : null}
              {includedPeople.length === 0 ? (
                <p className="text-xs text-ink-soft">
                  No people selected. Add someone from this system, or continue to record not a
                  match.
                </p>
              ) : (
                <ul className="space-y-1 rounded-md border border-line px-2 py-1.5">
                  {includedPeople.map((contact) => (
                    <li
                      key={contact.dwid}
                      className="flex items-center justify-between gap-2 rounded px-1 py-1 text-xs"
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-ink">
                          {formatMatchedContactLabel(contact)}
                        </span>
                        {surfaceList ? (
                          <span className="block text-[0.65rem] text-mute">{surfaceList}</span>
                        ) : null}
                      </span>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        disabled={disabled || pending || !contact.dwid}
                        onClick={() => removePerson(contact.dwid)}
                      >
                        Remove
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="space-y-1.5">
                <label className="block text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                  Add from this system
                </label>
                <input
                  type="search"
                  value={peopleQuery}
                  onChange={(event) => setPeopleQuery(event.target.value)}
                  placeholder="Search people in this system…"
                  disabled={disabled || pending}
                  className="h-7 w-full rounded-md border border-line bg-paper px-2 text-xs text-ink outline-none placeholder:text-mute focus-visible:ring-2 focus-visible:ring-habeas-mid"
                  aria-label="Search people in this system"
                  autoComplete="off"
                  spellCheck={false}
                />
                {addablePeople.length === 0 ? (
                  <p className="text-[0.65rem] text-mute">
                    {peopleQuery.trim()
                      ? 'No people in this system match that search.'
                      : people.every((contact) => selectedDwids.includes(contact.dwid))
                        ? 'Every matched person in this system is already included.'
                        : 'No other people returned for this system.'}
                  </p>
                ) : (
                  <ul className="space-y-0.5 rounded-md border border-line px-2 py-1">
                    {addablePeople.map((contact) => (
                      <li key={contact.dwid}>
                        <button
                          type="button"
                          disabled={disabled || pending || !contact.dwid}
                          onClick={() => addPerson(contact.dwid)}
                          className="flex w-full items-center justify-between gap-2 rounded px-1 py-1 text-left text-xs text-ink hover:bg-canvas"
                        >
                          <span className="truncate">{formatMatchedContactLabel(contact)}</span>
                          <span className="shrink-0 text-[0.65rem] text-habeas-navy">Add</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <p className="text-[0.65rem] text-mute">
                {selectedDwids.length === 0
                  ? 'Select at least one person, or leave none to record not a match.'
                  : formatMatchedContactsSummary(people, selectedDwids)}
              </p>
            </>
          )}
          <div className="flex gap-1.5">
            <Button type="button" size="sm" disabled={disabled || pending} onClick={goNext}>
              Continue
            </Button>
            <Button type="button" variant="ghost" size="sm" disabled={pending} onClick={goBack}>
              Back
            </Button>
          </div>
        </section>
      ) : null}

      {step === 'confirm' ? (
        <section className="space-y-3 rounded-md border border-line bg-canvas px-3 py-3">
          <p className="text-sm font-medium text-ink">Confirm</p>
          <dl className="space-y-1.5 text-xs text-ink">
            <div>
              <dt className="text-[0.65rem] text-mute">This request</dt>
              <dd className="font-medium">
                {source} · {requestId}
              </dd>
            </div>
            <div>
              <dt className="text-[0.65rem] text-mute">This system</dt>
              <dd className="font-medium">{systemName}</dd>
            </div>
            {matchingBlocked ? (
              <div>
                <dt className="text-[0.65rem] text-mute">Blocked</dt>
                <dd>Matching stays gated until the connector is connected or refreshed.</dd>
              </div>
            ) : (
              <div>
                <dt className="text-[0.65rem] text-mute">These people</dt>
                <dd>
                  {draftStatus === '5' || selectedDwids.length === 0
                    ? 'None — not a match'
                    : formatMatchedContactsSummary(people, selectedDwids)}
                </dd>
              </div>
            )}
          </dl>

          {matchingBlocked ? (
            <div className="flex flex-wrap gap-1.5">
              <Button type="button" size="sm" asChild>
                <Link to="/owner/connectors" search={ownerConnectorsSearch(connectorsVertical)}>
                  Open connectors
                </Link>
              </Button>
              <Button type="button" variant="ghost" size="sm" disabled={pending} onClick={goBack}>
                Back
              </Button>
            </div>
          ) : (
            <>
              <fieldset className="space-y-1.5" disabled={disabled || pending}>
                <legend className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                  Record this result
                </legend>
                <div className="space-y-1" role="radiogroup" aria-label="Record this result">
                  {statusOptions.map((option) => {
                    const selected = draftStatus === option.id
                    return (
                      <button
                        key={option.id}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        disabled={disabled || pending}
                        onClick={() => setDraftStatus(option.id)}
                        className={cn(
                          'flex w-full items-center justify-between rounded-md border px-2.5 py-1.5 text-left text-xs',
                          selected
                            ? 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
                            : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
                        )}
                      >
                        {option.label}
                        {selected ? <span className="text-[0.6rem] text-mute">selected</span> : null}
                      </button>
                    )
                  })}
                </div>
              </fieldset>

              {peopleRequired ? (
                <p className="text-[0.65rem] text-mute">
                  Go back and pick at least one person, or choose not a match.
                </p>
              ) : null}

              <div className="flex gap-1.5">
                <Button type="button" size="sm" disabled={applyBlocked} onClick={commitAndApply}>
                  {pending ? confirmCopy.pendingLabel : confirmCopy.confirmLabel}
                </Button>
                <Button type="button" variant="ghost" size="sm" disabled={pending} onClick={goBack}>
                  Back
                </Button>
              </div>
            </>
          )}
        </section>
      ) : null}
    </div>
  )
}
