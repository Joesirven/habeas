import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'

import {
  matchingLabRequestId,
  type MatchingResultsViewProps,
} from '@/components/matching-results-lab/matching-results-lab-types'
import {
  applyNeedsPeople,
  resultViewEmpty,
} from '@/components/matching-results-lab/ResultViewChrome'
import {
  formatMatchedContactLabel,
  formatMatchedContactsSummary,
  matchingDispositionCopy,
} from '@/components/requests/RequestTriageDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  suggestedDropResponseStatus,
  type MatchedPersonContact,
  type NeedsAttentionItem,
} from '@/lib/api'
import {
  matchingConnectorGateChip,
  matchingGateFromAttempts,
  ownerConnectorsSearch,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import {
  inboxIntakeSourceLabel,
  inboxItemSystemId,
  matchTypeLabel,
} from '@/lib/inbox-batch-status'
import {
  inboxItemChannels,
  type InboxItemChannel,
} from '@/lib/inbox-status-lab'
import { catalogSystemDisplayLabel } from '@/lib/legalJourneyLabels'
import { cn } from '@/lib/utils'

/** Product/consumer — decision-first: huge Confirm/Decline, one question, results secondary. */
export const OWNER_MATCHING_REVIEW_V07_PHILOSOPHY =
  'Decision-first: huge Confirm/Decline, one question, results secondary.'

const MATCHING_REVIEW_SLA_HOURS = 48

const SURFACE_ORDER: InboxItemChannel[] = ['email', 'phone', 'ndz']
const SURFACE_LABELS: Record<InboxItemChannel, string> = {
  email: 'Email',
  phone: 'Phone',
  ndz: 'NDZ',
}

const DISPOSITION_DELETE = '3'
const DISPOSITION_OPT_IN = '4'

const PEOPLE_DISPOSITIONS = [
  { id: DISPOSITION_DELETE, label: 'Delete' },
  { id: DISPOSITION_OPT_IN, label: 'Opt-in' },
] as const

export type OwnerMatchingReviewV07Props = MatchingResultsViewProps & {
  /** Formal decline (not fulfill-ready). When omitted, Decline records Not a match (5). */
  onDecline?: () => void
}

function shortRequestId(requestId: string | undefined): string {
  const canonical = requestId ? matchingLabRequestId(requestId) : null
  const raw = canonical ?? requestId?.trim() ?? ''
  if (!raw) return '—'
  return raw.length > 8 ? `${raw.slice(0, 8)}…` : raw
}

function systemLabel(item: NeedsAttentionItem, detailSystem?: string | null): string {
  const system = detailSystem ?? inboxItemSystemId(item)
  return (
    catalogSystemDisplayLabel(system, {
      vertical: item.vertical,
      systemLabel: item.system_label,
    }) ?? 'This system'
  )
}

function dueLabel(item: NeedsAttentionItem): string | null {
  const anchor = item.requested_at ?? item.received_at
  if (!anchor) return null
  const start = new Date(anchor)
  if (Number.isNaN(start.getTime())) return null
  const due = new Date(start.getTime() + MATCHING_REVIEW_SLA_HOURS * 60 * 60 * 1000)
  const when = due.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  if (due.getTime() < Date.now()) return `Overdue · ${when}`
  return `Due ${when}`
}

function decisionQuestion(item: NeedsAttentionItem): string {
  const matchType = item.match_type
  const count = item.match_count
  if (matchType === 'not_found' || count === 0) return 'Confirm nobody matched?'
  if (matchType === 'multi_match' || (count != null && count > 1)) {
    return 'Are these the right people?'
  }
  return 'Is this the right person?'
}

/** One matching attempt’s identifier surfaces — not separate Confirm/Decline questions. */
function attemptSurfaces(
  item: NeedsAttentionItem,
  detail: MatchingResultsViewProps['detail'],
): InboxItemChannel[] {
  return inboxItemChannels({
    request_id: item.request_id,
    matched_via: detail?.matched_via ?? item.matched_via,
    matched_channels: detail?.matched_channels ?? item.channels,
    channels: item.channels,
  })
}

function surfacesForPerson(
  contact: MatchedPersonContact,
  attempt: InboxItemChannel[],
): InboxItemChannel[] {
  const seen = new Set<InboxItemChannel>(attempt)
  if (contact.email?.trim()) seen.add('email')
  if (Array.isArray(contact.phones) && contact.phones.some((phone) => phone?.number?.trim())) {
    seen.add('phone')
  }
  return SURFACE_ORDER.filter((surface) => seen.has(surface))
}

function SurfaceMarks({ surfaces }: { surfaces: InboxItemChannel[] }) {
  if (surfaces.length === 0) return null
  return (
    <p className="text-[0.65rem] text-mute">
      {surfaces.map((surface) => SURFACE_LABELS[surface]).join(' · ')}
    </p>
  )
}

function matchingBlockedGate(
  detail: MatchingResultsViewProps['detail'],
): MatchingConnectorGate | null {
  return matchingGateFromAttempts(detail?.attempts)
}

function gateSupportCopy(gate: MatchingConnectorGate, system: string): string {
  if (gate.displayStatus === 'needs_setup' || gate.gateCode === 'wizard_incomplete') {
    return `Finish connecting ${system} before you can confirm this match.`
  }
  if (gate.displayStatus === 'needs_refresh' || gate.gateCode === 'upload_stale') {
    return `Refresh ${system} before you can confirm this match.`
  }
  if (gate.gateCode === 'rotation_overdue' || gate.displayStatus === 'action_required') {
    return `Reconnect ${system} before you can confirm this match.`
  }
  return `Matching is gated on ${system}. You cannot confirm yet.`
}

function contactMatchesQuery(contact: MatchedPersonContact, query: string): boolean {
  const needle = query.trim().toLowerCase()
  if (!needle) return true
  return formatMatchedContactLabel(contact).toLowerCase().includes(needle)
}

/** Search chrome: Needs refresh / Needs connection — never Connected. */
function peopleSearchNotice(
  blocked?: MatchingConnectorGate | null,
  pending?: { title: string; support: string } | null,
): { title: string; support: string } | null {
  if (blocked?.blocked) {
    const refresh =
      blocked.displayStatus === 'needs_refresh' || blocked.gateCode === 'upload_stale'
    return {
      title: refresh ? 'Needs refresh' : 'Needs connection',
      support: pending?.support ?? '',
    }
  }
  if (!pending) return null
  const title = pending.title.trim() === 'Connected' ? 'Needs connection' : pending.title
  return { title, support: pending.support }
}

function mergePeopleByDwid(
  ...lists: Array<readonly MatchedPersonContact[] | undefined>
): MatchedPersonContact[] {
  const seen = new Set<string>()
  const merged: MatchedPersonContact[] = []
  for (const list of lists) {
    for (const contact of list ?? []) {
      const dwid = contact.dwid?.trim()
      if (!dwid || seen.has(dwid)) continue
      seen.add(dwid)
      merged.push(contact)
    }
  }
  return merged
}

/**
 * Owner matching-only. One question and two large actions lead; match people
 * sit in a collapsed secondary panel. No lifecycle rail.
 * Email / phone / NDZ are surfaces on each person, not separate Confirm/Decline.
 */
export function OwnerMatchingReviewV07({
  item,
  detail,
  contacts,
  loading,
  ownerLanguage,
  statusId,
  onStatusChange,
  selectedDwids,
  onSelectedDwidsChange,
  disabled,
  pending,
  onApply,
  onDecline,
  onSearchPeople,
  peopleSearchBlocked,
  peopleSearchPending,
}: OwnerMatchingReviewV07Props) {
  const empty = resultViewEmpty(loading, Boolean(item))
  const [resultsOpen, setResultsOpen] = useState(false)
  const [addQuery, setAddQuery] = useState('')
  const [extraContacts, setExtraContacts] = useState<MatchedPersonContact[]>([])
  const [directoryHits, setDirectoryHits] = useState<MatchedPersonContact[]>([])
  const [searchBusy, setSearchBusy] = useState(false)
  const [searchFailed, setSearchFailed] = useState(false)
  const searchRef = useRef(onSearchPeople)
  searchRef.current = onSearchPeople

  const connectorGate = matchingBlockedGate(detail)
  const matchingGated = Boolean(connectorGate?.blocked)
  const searchNotice = peopleSearchNotice(peopleSearchBlocked, peopleSearchPending)
  const searchLocked = Boolean(disabled || pending || matchingGated || searchNotice)
  const allContacts = useMemo(
    () => mergePeopleByDwid(contacts, extraContacts),
    [contacts, extraContacts],
  )

  useEffect(() => {
    setExtraContacts([])
    setAddQuery('')
    setDirectoryHits([])
  }, [item?.request_id])

  useEffect(() => {
    const needle = addQuery.trim()
    if (searchLocked || !onSearchPeople || needle.length < 2) {
      setDirectoryHits([])
      setSearchBusy(false)
      setSearchFailed(false)
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      void (async () => {
        setSearchBusy(true)
        setSearchFailed(false)
        try {
          const result = await searchRef.current?.(needle)
          if (!cancelled) setDirectoryHits(result ?? [])
        } catch {
          if (!cancelled) {
            setDirectoryHits([])
            setSearchFailed(true)
          }
        } finally {
          if (!cancelled) setSearchBusy(false)
        }
      })()
    }, 200)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [addQuery, onSearchPeople, searchLocked])

  if (empty) return empty
  if (!item) return empty

  const locked = Boolean(disabled || pending)
  const copy = matchingDispositionCopy('data_owner')
  const system = systemLabel(item, detail?.system)
  const source = inboxIntakeSourceLabel(item.intake_source)
  const due = dueLabel(item)
  const suggested = String(
    suggestedDropResponseStatus(
      detail?.match_type ?? item.match_type,
      detail?.match_count ?? item.match_count,
    ),
  )
  const confirmStatus = statusId ?? suggested
  const notFound = confirmStatus === '5'
  const confirmBlocked = applyNeedsPeople(confirmStatus, selectedDwids)
  const gateChip = connectorGate ? matchingConnectorGateChip(connectorGate) : null
  const includedPeople = notFound
    ? []
    : allContacts.filter((contact) => Boolean(contact.dwid) && selectedDwids.includes(contact.dwid))
  const addablePeople = allContacts.filter(
    (contact) => Boolean(contact.dwid) && !selectedDwids.includes(contact.dwid),
  )
  const localHits = addablePeople.filter((contact) => contactMatchesQuery(contact, addQuery))
  const addHits = mergePeopleByDwid(directoryHits, localHits).filter(
    (contact) => Boolean(contact.dwid) && !selectedDwids.includes(contact.dwid),
  )
  const showAddSearch =
    Boolean(onSearchPeople) ||
    addablePeople.length > 0 ||
    Boolean(searchNotice)
  const peopleLine = matchingGated
    ? 'Cannot confirm until this connector is ready.'
    : notFound
      ? 'No people will be applied.'
      : formatMatchedContactsSummary(allContacts, selectedDwids)
  const showDecline = Boolean(onDecline) || !notFound
  const matchType = detail?.match_type ?? item.match_type
  const matchCount = detail?.match_count ?? item.match_count
  const notLive =
    detail?.matched_contacts_status === 'not_live' ||
    detail?.result_kind === 'sheet_stub' ||
    detail?.result_kind === 'saas_stub'
  const surfaces = attemptSurfaces(item, detail)
  const enrichError = detail?.matched_contacts_error?.message?.trim()
  const peopleOpen = resultsOpen || confirmBlocked

  function setDisposition(next: string) {
    onStatusChange(next)
    if (next === '5') {
      onSelectedDwidsChange([])
      return
    }
    if (selectedDwids.length === 0) {
      onSelectedDwidsChange(allContacts.map((contact) => contact.dwid).filter(Boolean))
    }
  }

  function removePerson(dwid: string) {
    onSelectedDwidsChange(selectedDwids.filter((id) => id !== dwid))
  }

  function addPerson(contact: MatchedPersonContact) {
    const dwid = contact.dwid
    if (!dwid || selectedDwids.includes(dwid)) return
    if (!allContacts.some((row) => row.dwid === dwid)) {
      setExtraContacts((previous) => [...previous, contact])
    }
    if (confirmStatus === '5') onStatusChange(suggested === '5' ? DISPOSITION_DELETE : suggested)
    onSelectedDwidsChange([...selectedDwids, dwid])
    setAddQuery('')
  }

  function confirmMatch() {
    if (matchingGated) return
    if (confirmBlocked) {
      setResultsOpen(true)
      return
    }
    if (statusId == null) onStatusChange(confirmStatus)
    onApply({
      statusId: confirmStatus,
      selectedDwids: confirmStatus === '5' ? [] : selectedDwids,
    })
  }

  function declineMatch() {
    if (onDecline) {
      onDecline()
      return
    }
    onStatusChange('5')
    onSelectedDwidsChange([])
    onApply({ statusId: '5', selectedDwids: [] })
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <header className="space-y-2">
        <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
          Matching review
        </p>
        {matchingGated && connectorGate && gateChip ? (
          <>
            <h2 className="text-xl font-semibold leading-snug text-ink">{gateChip.label}</h2>
            <p className="text-sm text-ink-soft">{gateSupportCopy(connectorGate, system)}</p>
            <p className="text-xs text-mute">{decisionQuestion(item)}</p>
          </>
        ) : (
          <h2 className="text-xl font-semibold leading-snug text-ink">{decisionQuestion(item)}</h2>
        )}
        <p className="text-sm text-ink-soft">
          {system}
          <span className="text-mute"> · {peopleLine}</span>
        </p>
        <p className="flex flex-wrap items-center gap-1.5 text-[0.7rem] text-mute">
          <span>{source}</span>
          <span aria-hidden>·</span>
          <span className="tabular-nums">{shortRequestId(item.request_id)}</span>
          {due ? (
            <>
              <span aria-hidden>·</span>
              <Badge
                variant={due.startsWith('Overdue') ? 'fail' : 'wait'}
                className="normal-case tracking-normal"
              >
                {due}
              </Badge>
            </>
          ) : null}
          {matchingGated && gateChip ? (
            <>
              <span aria-hidden>·</span>
              <Badge variant={gateChip.variant} className="normal-case tracking-normal">
                {gateChip.label}
              </Badge>
            </>
          ) : null}
        </p>
      </header>

      {matchingGated ? (
        <div className="grid grid-cols-1 gap-2">
          <Button asChild className="h-16 text-base font-semibold">
            <Link to="/owner/connectors" search={ownerConnectorsSearch(item.vertical)}>
              Open connectors
            </Link>
          </Button>
          <p className="text-xs text-ink-soft" role="status">
            Connect or refresh this system before you can confirm the match.
          </p>
        </div>
      ) : (
        <>
          <div className={cn('grid grid-cols-1 gap-2', showDecline && 'sm:grid-cols-2')}>
            <Button
              type="button"
              disabled={locked}
              onClick={confirmMatch}
              className="h-16 text-base font-semibold"
            >
              {pending ? copy.pendingLabel : copy.confirmLabel}
            </Button>
            {showDecline ? (
              <Button
                type="button"
                variant="outline"
                disabled={locked}
                onClick={declineMatch}
                className="h-16 text-base font-semibold"
              >
                {pending ? 'Declining…' : 'Decline'}
              </Button>
            ) : null}
          </div>
          {confirmBlocked ? (
            <p className="text-xs text-ink-soft" role="status">
              Open matching results and include at least one person before confirming.
            </p>
          ) : (
            <p className="text-xs text-mute">
              {notFound
                ? 'Confirm records this matching attempt as not a match.'
                : 'One Confirm or Decline covers this system. Email, phone, and NDZ are not extra questions.'}
            </p>
          )}
        </>
      )}

      <Collapsible
        open={peopleOpen}
        onOpenChange={setResultsOpen}
        className="min-h-0"
      >
        <div className="rounded-md border border-line bg-paper">
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className={cn(
                'flex w-full items-center justify-between gap-2 px-3 py-2 text-left',
                'hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid',
              )}
            >
              <span className="text-xs font-medium text-ink">Matching results</span>
              <span className="text-[0.65rem] text-mute">
                {peopleOpen ? 'Hide' : 'Show'}
                {contacts.length > 0 ? (
                  <span className="tabular-nums"> · {contacts.length}</span>
                ) : null}
              </span>
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="space-y-2 border-t border-line px-3 py-2.5">
              <p className="text-[0.7rem] text-ink-soft">
                {notLive
                  ? detail?.result_kind === 'sheet_stub'
                    ? 'Sheet matching not live'
                    : 'System matching not live'
                  : matchTypeLabel(matchType, ownerLanguage)}
                {!notLive && matchCount != null ? (
                  <span className="tabular-nums text-mute">
                    {' '}
                    · {matchCount} {matchCount === 1 ? 'person' : 'people'}
                  </span>
                ) : null}
              </p>
              {notLive && detail?.not_live_reason ? (
                <p className="text-[0.65rem] text-ink-soft">{detail.not_live_reason}</p>
              ) : null}
              {enrichError ? (
                <p className="text-[0.65rem] text-red-800">Contact enrichment unavailable.</p>
              ) : null}

              <fieldset className="space-y-1.5" disabled={locked || matchingGated}>
                <legend className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                  Apply as
                </legend>
                <div
                  className="flex flex-wrap gap-1.5"
                  role="radiogroup"
                  aria-label="Delete or opt-in for this matching attempt"
                >
                  {PEOPLE_DISPOSITIONS.map((option) => {
                    const selected = !notFound && confirmStatus === option.id
                    return (
                      <button
                        key={option.id}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        disabled={locked || matchingGated}
                        onClick={() => setDisposition(option.id)}
                        className={cn(
                          'inline-flex items-center rounded-md border px-2.5 py-1.5 text-xs transition-colors',
                          selected
                            ? 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
                            : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
                          (locked || matchingGated) && 'opacity-50',
                        )}
                      >
                        {option.label}
                      </button>
                    )
                  })}
                </div>
                <p className="text-[0.65rem] text-mute">
                  One Delete or Opt-in applies to every selected person on this attempt.
                </p>
              </fieldset>

              {allContacts.length === 0 ? (
                <p className="text-xs text-mute">
                  {notFound || matchType === 'not_found'
                    ? 'No people for this matching attempt.'
                    : 'No person records for this matching attempt.'}
                </p>
              ) : includedPeople.length === 0 && !notFound ? (
                <p className="text-xs text-mute">
                  No people included. Search to add a match before confirming.
                </p>
              ) : includedPeople.length === 0 ? (
                <p className="text-xs text-mute">No people will be applied.</p>
              ) : (
                <ul className="space-y-2">
                  {includedPeople.map((contact, index) => {
                    const label = formatMatchedContactLabel(contact)
                    return (
                      <li
                        key={contact.dwid || `person-${index}`}
                        className="flex min-w-0 items-start justify-between gap-2"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-xs font-medium text-ink">{label}</p>
                          <SurfaceMarks surfaces={surfacesForPerson(contact, surfaces)} />
                        </div>
                        <button
                          type="button"
                          disabled={locked || matchingGated || !contact.dwid}
                          onClick={() => removePerson(contact.dwid)}
                          className="shrink-0 text-[0.65rem] font-medium text-ink-soft hover:text-ink disabled:opacity-50"
                        >
                          Remove
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}

              {showAddSearch ? (
                <div className="space-y-1.5">
                  <label className="block">
                    <span className="sr-only">Add person by search</span>
                    <input
                      type="search"
                      value={addQuery}
                      disabled={searchLocked}
                      onChange={(event) => setAddQuery(event.target.value)}
                      placeholder={searchNotice ? searchNotice.title : 'Add person…'}
                      className="h-8 w-full rounded-md border border-line bg-paper px-2 text-xs text-ink outline-none placeholder:text-mute focus-visible:ring-2 focus-visible:ring-habeas-mid disabled:opacity-50"
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </label>
                  {searchNotice ? (
                    <p className="text-[0.65rem] text-ink-soft" role="status">
                      {searchNotice.title}
                      {searchNotice.support ? ` — ${searchNotice.support}` : ''}
                    </p>
                  ) : null}
                  {searchBusy ? (
                    <p className="text-[0.65rem] text-mute" role="status">
                      Searching…
                    </p>
                  ) : null}
                  {searchFailed ? (
                    <p className="text-[0.65rem] text-red-800">
                      Could not search this system. Try again.
                    </p>
                  ) : null}
                  {!searchNotice && addHits.length > 0 ? (
                    <ul className="space-y-1">
                      {addHits.map((contact) => {
                        const label = formatMatchedContactLabel(contact)
                        return (
                          <li key={contact.dwid}>
                            <button
                              type="button"
                              disabled={searchLocked || !contact.dwid}
                              onClick={() => addPerson(contact)}
                              className="flex w-full items-center justify-between gap-2 rounded-md px-1 py-1 text-left text-xs hover:bg-canvas disabled:opacity-50"
                            >
                              <span className="min-w-0 truncate text-ink-soft">{label}</span>
                              <span className="shrink-0 text-[0.65rem] font-medium text-habeas-navy">
                                Add
                              </span>
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  ) : !searchNotice && !searchBusy && !searchFailed && addQuery.trim() ? (
                    <p className="text-[0.65rem] text-mute">
                      {onSearchPeople && addQuery.trim().length < 2
                        ? 'Type at least 2 characters to search.'
                        : 'No matching people to add.'}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
          </CollapsibleContent>
        </div>
      </Collapsible>
    </div>
  )
}
