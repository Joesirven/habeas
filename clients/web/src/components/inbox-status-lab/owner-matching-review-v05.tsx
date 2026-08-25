import { useEffect, useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  ResultApplyBar,
  applyNeedsPeople,
  resultViewEmpty,
} from '@/components/matching-results-lab/ResultViewChrome'
import {
  matchingLabRequestId,
  matchingLabSystemId,
  type MatchingResultsViewProps,
} from '@/components/matching-results-lab/matching-results-lab-types'
import {
  formatMatchedContactLabel,
  matchingDetailIsNotLive,
  matchingDispositionCopy,
  redactHashHex,
  safeMatchedContacts,
} from '@/components/requests/RequestTriageDialog'
import { inboxIntakeSourceLabel, matchTypeLabel } from '@/lib/inbox-batch-status'
import { inboxItemConnections } from '@/lib/inbox-status-lab'
import {
  matchingConnectorGateBannerCopy,
  matchingConnectorGateChip,
  matchingGateFromAttempts,
  ownerConnectorsSearch,
  overlayCalloutShowsOwnerCta,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import { getRequest, suggestedDropResponseStatus, type MatchedPersonContact } from '@/lib/api'
import {
  DROP_HASH_SYSTEM_ID,
  catalogSystemDisplayLabel,
} from '@/lib/legalJourneyLabels'
import { cn } from '@/lib/utils'

/**
 * Owner matching review v05 — legal/compliance evidence cards per person,
 * system stamp, DWID selectable. Email / phone / NDZ are surfaces on that
 * exhibit (evidence fields), not separate matching attempts or cards.
 */

const STATUS_DELETE = '3'
const STATUS_OPT_IN = '4'
const STATUS_NOT_FOUND = '5'

function exhibitLetter(index: number): string {
  if (index < 26) return String.fromCharCode(65 + index)
  return `A${index - 25}`
}

function shortRequestId(requestId: string | null | undefined): string {
  const id = requestId?.trim()
  if (!id) return '—'
  return id.length > 8 ? `${id.slice(0, 8)}…` : id
}

function factDate(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '—'
  return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function isHiddenSystem(system: string | null | undefined): boolean {
  const id = system?.trim().toLowerCase()
  return !id || id === DROP_HASH_SYSTEM_ID || id === 'cassandra'
}

function publicSystemId(system: string | null | undefined): string | null {
  const id = system?.trim() || null
  return id && !isHiddenSystem(id) ? id : null
}

function systemStampLabel(
  item: MatchingResultsViewProps['item'],
  detail: MatchingResultsViewProps['detail'],
): string {
  const system = publicSystemId(detail?.system ?? (item ? matchingLabSystemId(item) : null))
  return (
    catalogSystemDisplayLabel(system, {
      vertical: detail?.vertical ?? item?.vertical,
      systemLabel: detail?.system_label ?? item?.system_label,
    }) ?? 'Unassigned system'
  )
}

function pickText(
  primary: string | null | undefined,
  fallback: string | null | undefined,
): string | null {
  const left = primary?.trim()
  if (left) return left
  const right = fallback?.trim()
  return right || null
}

function mergePhones(
  primary: MatchedPersonContact['phones'] | undefined,
  fallback: MatchedPersonContact['phones'] | undefined,
): MatchedPersonContact['phones'] {
  const seen = new Set<string>()
  const merged: MatchedPersonContact['phones'] = []
  for (const phone of [...(primary ?? []), ...(fallback ?? [])]) {
    const key = `${typeof phone?.type === 'string' ? phone.type : ''}:${typeof phone?.number === 'string' ? phone.number : ''}`
    if (!key || seen.has(key)) continue
    seen.add(key)
    merged.push(phone)
  }
  return merged
}

/** One person / DWID = one exhibit. Surface-split rows merge onto that card. */
function unifyPeopleByDwid(contacts: MatchedPersonContact[]): MatchedPersonContact[] {
  const order: string[] = []
  const byKey = new Map<string, MatchedPersonContact>()
  let anonymous = 0
  for (const contact of contacts) {
    const dwid = contact.dwid?.trim()
    const key = dwid || `__anon-${anonymous++}`
    const existing = byKey.get(key)
    if (!existing) {
      order.push(key)
      byKey.set(key, {
        ...contact,
        phones: Array.isArray(contact.phones) ? [...contact.phones] : [],
      })
      continue
    }
    byKey.set(key, {
      dwid: existing.dwid || contact.dwid,
      state: pickText(existing.state, contact.state) ?? '',
      first_initial: pickText(existing.first_initial, contact.first_initial),
      last_initial: pickText(existing.last_initial, contact.last_initial),
      last_name: pickText(existing.last_name, contact.last_name),
      dob: pickText(existing.dob, contact.dob),
      email: pickText(existing.email, contact.email),
      phones: mergePhones(existing.phones, contact.phones),
    })
  }
  return order.map((key) => byKey.get(key)!).filter((contact) => Boolean(contact))
}

function personName(contact: MatchedPersonContact): string {
  return (
    [contact.first_initial, contact.last_name || contact.last_initial]
      .filter((part) => typeof part === 'string' && part.trim())
      .join(' ') || formatMatchedContactLabel(contact)
  )
}

function identityRows(contact: MatchedPersonContact): { label: string; value: string }[] {
  return [
    { label: 'Name', value: personName(contact) || '—' },
    { label: 'State', value: contact.state?.trim() || '—' },
    { label: 'DOB', value: contact.dob?.trim() || '—' },
  ]
}

/** Email / phone / NDZ — evidence on this exhibit, not channel stamps. */
function surfaceRows(contact: MatchedPersonContact): { label: string; value: string }[] {
  const phones = Array.isArray(contact.phones) ? contact.phones : []
  const phone =
    phones.length > 0
      ? phones
          .map((row) => {
            const type = typeof row?.type === 'string' ? row.type : 'phone'
            const number = typeof row?.number === 'string' ? redactHashHex(row.number) : '—'
            return `${type} ${number}`
          })
          .join(' · ')
      : '—'
  const email =
    typeof contact.email === 'string' && contact.email.trim()
      ? redactHashHex(contact.email)
      : '—'
  const ndz = [personName(contact), contact.dob?.trim(), contact.state?.trim()]
    .filter((part) => typeof part === 'string' && part.trim() && part !== '—')
    .join(' · ')
  return [
    { label: 'Email', value: email },
    { label: 'Phone', value: phone },
    { label: 'NDZ', value: ndz || '—' },
  ]
}

function personSearchHaystack(contact: MatchedPersonContact): string {
  return [personName(contact), contact.state, contact.dob]
    .filter((part) => typeof part === 'string' && part.trim())
    .join(' ')
    .toLowerCase()
}

function resolveCardStackGate(
  item: MatchingResultsViewProps['item'],
  detail: MatchingResultsViewProps['detail'],
): MatchingConnectorGate | null {
  const fromAttempts = matchingGateFromAttempts(detail?.attempts)
  if (fromAttempts) {
    return { ...fromAttempts, system: publicSystemId(fromAttempts.system) }
  }
  if (!matchingDetailIsNotLive(detail ?? undefined)) return null
  const system = publicSystemId(detail?.system ?? (item ? matchingLabSystemId(item) : null))
  const needsRefresh =
    detail?.result_kind === 'sheet_stub' ||
    /stale|refresh|reupload|upload/i.test(detail?.not_live_reason ?? '')
  return {
    blocked: true,
    displayStatus: needsRefresh ? 'needs_refresh' : 'needs_setup',
    gateCode: needsRefresh ? 'upload_stale' : 'wizard_incomplete',
    system,
    source: 'connection',
  }
}

function gateChipLabel(gate: MatchingConnectorGate): string {
  const chip = matchingConnectorGateChip(gate)
  if (chip.label === 'Needs setup') return 'Needs connection'
  return chip.label
}

function CardStackGateBanner({
  gate,
  verticalId,
  fallbackReason,
}: {
  gate: MatchingConnectorGate
  verticalId: string | null
  fallbackReason?: string | null
}) {
  const chip = matchingConnectorGateChip(gate)
  const copy = matchingConnectorGateBannerCopy(gate)
  const description =
    fallbackReason?.trim() && gate.source === 'connection'
      ? fallbackReason.trim()
      : copy.description
  const showCta = overlayCalloutShowsOwnerCta('data_owner', verticalId)
  return (
    <div
      className="rounded-md border border-red-300/80 bg-red-50/80 px-2.5 py-2"
      role="status"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Badge variant={chip.variant} className="normal-case tracking-normal">
            {gateChipLabel(gate)}
          </Badge>
          <span className="text-[0.7rem] font-medium text-red-950">{copy.title}</span>
        </div>
        {showCta ? (
          <Button size="sm" asChild>
            <Link to="/owner/connectors" search={ownerConnectorsSearch(verticalId)}>
              Open connectors
            </Link>
          </Button>
        ) : null}
      </div>
      <p className="mt-1 text-[0.65rem] leading-snug text-red-900/90">{description}</p>
    </div>
  )
}

function SystemStamp({
  label,
  compact = false,
}: {
  label: string
  compact?: boolean
}) {
  return (
    <div
      aria-label={`System stamp ${label}`}
      className={cn(
        'shrink-0 border-2 border-habeas-navy/70 text-center text-habeas-navy',
        compact ? 'px-1.5 py-0.5' : 'min-w-[5.5rem] px-1.5 py-1',
      )}
    >
      <span className="block text-[0.5rem] font-semibold uppercase tracking-[0.16em]">
        Stamped
      </span>
      <span
        className={cn(
          'block font-semibold uppercase leading-tight tracking-wide',
          compact ? 'text-[0.6rem]' : 'text-[0.65rem]',
        )}
      >
        {label}
      </span>
    </div>
  )
}

function EvidenceCard({
  contact,
  index,
  stamp,
  disposition,
  emphasizeDelete,
  emphasizeOptIn,
  selectable,
  disabled,
  onDisposition,
  onRemove,
}: {
  contact: MatchedPersonContact
  index: number
  stamp: string
  disposition: '3' | '4' | null
  emphasizeDelete: boolean
  emphasizeOptIn: boolean
  selectable: boolean
  disabled: boolean
  onDisposition: (statusId: '3' | '4') => void
  onRemove: () => void
}) {
  const exhibit = exhibitLetter(index)
  const dwid = contact.dwid?.trim() || ''
  const canSelect = selectable && Boolean(dwid)
  return (
    <article
      className={cn(
        'relative rounded-md border bg-paper px-3 py-2.5',
        disposition && canSelect ? 'border-habeas-navy' : 'border-line',
        disabled && 'opacity-60',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">
            Exhibit {exhibit}
          </p>
          <h3 className="mt-0.5 truncate text-sm font-medium text-ink">
            {formatMatchedContactLabel(contact)}
          </h3>
        </div>
        <div className="flex shrink-0 items-start gap-1.5">
          <SystemStamp label={stamp} />
          <button
            type="button"
            disabled={disabled}
            onClick={onRemove}
            className="rounded-md border border-line px-1.5 py-0.5 text-[0.6rem] text-ink-soft hover:border-habeas-navy/35 hover:text-ink disabled:opacity-50"
            aria-label={`Remove exhibit ${exhibit}`}
          >
            Remove
          </button>
        </div>
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 border-t border-line/80 pt-2">
        {identityRows(contact).map((row) => (
          <div key={row.label} className="min-w-0">
            <dt className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">
              {row.label}
            </dt>
            <dd className="truncate text-[0.7rem] text-ink">{row.value}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-2 border-t border-line/80 pt-2">
        <p className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">
          Surfaces
        </p>
        <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1">
          {surfaceRows(contact).map((row) => (
            <div
              key={row.label}
              className={cn('min-w-0', row.label === 'NDZ' && 'col-span-2')}
            >
              <dt className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">
                {row.label}
              </dt>
              <dd className="truncate text-[0.7rem] text-ink">{row.value}</dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-line/80 pt-2">
        <span className="sr-only">
          {dwid ? `Exhibit ${exhibit}` : `Exhibit ${exhibit} has no DWID`}
        </span>
        <button
          type="button"
          disabled={disabled || !canSelect}
          onClick={() => onDisposition(STATUS_DELETE)}
          className={cn(
            'rounded-md border px-2 py-1 text-[0.65rem]',
            disposition === STATUS_DELETE
              ? 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
              : emphasizeDelete
                ? 'border-habeas-navy/50 bg-paper text-ink'
                : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
          )}
        >
          Delete
        </button>
        <button
          type="button"
          disabled={disabled || !canSelect}
          onClick={() => onDisposition(STATUS_OPT_IN)}
          className={cn(
            'rounded-md border px-2 py-1 text-[0.65rem]',
            disposition === STATUS_OPT_IN
              ? 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
              : emphasizeOptIn
                ? 'border-habeas-navy/50 bg-paper text-ink'
                : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
          )}
        >
          Opt-in
        </button>
        <span className="ml-auto shrink-0 font-mono tabular-nums text-[0.6rem] text-mute">
          {dwid || '—'}
        </span>
      </div>
    </article>
  )
}

/** Legal/compliance — one exhibit per person, system stamp, DWID selectable. */
export function OwnerMatchingReviewV05({
  item,
  detail,
  contacts,
  loading,
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
  const people = useMemo(() => unifyPeopleByDwid(safeMatchedContacts(contacts)), [contacts])
  const requestId = matchingLabRequestId(item?.request_id ?? '')
  const requestQuery = useQuery({
    queryKey: ['admin-api', 'requests', requestId, 'matching-review-type'],
    queryFn: () => getRequest(requestId!),
    enabled: Boolean(requestId),
    staleTime: 60_000,
    retry: false,
  })
  const [removedDwids, setRemovedDwids] = useState<string[]>([])
  const [dispositions, setDispositions] = useState<Record<string, '3' | '4'>>({})
  const [search, setSearch] = useState('')
  const stackKey = [
    item?.request_id ?? '',
    matchingLabSystemId(item ?? { system: detail?.system }) ?? '',
    people.map((contact) => contact.dwid?.trim() || '').join('|'),
  ].join('::')

  const requestType = requestQuery.data?.request_type?.trim().toLowerCase() ?? ''
  const suggested = suggestedDropResponseStatus(
    detail?.match_type ?? item?.match_type,
    detail?.match_count ?? item?.match_count ?? people.length,
  )
  const defaultDisposition: '3' | '4' =
    requestType === 'opt_out' || requestType === 'opt-out'
      ? STATUS_OPT_IN
      : requestType === 'delete' || requestType === 'deletion'
        ? STATUS_DELETE
        : suggested === 4
          ? STATUS_OPT_IN
          : STATUS_DELETE

  useEffect(() => {
    const matchDwids = people
      .map((contact) => contact.dwid?.trim() || '')
      .filter(Boolean)
    setRemovedDwids([])
    setSearch('')
    setDispositions(
      Object.fromEntries(matchDwids.map((dwid) => [dwid, defaultDisposition])),
    )
    onSelectedDwidsChange(matchDwids)
    // Prefill only when the request/system/person stack changes — not when request type loads.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stackKey is the reset signal
  }, [stackKey])

  const empty = resultViewEmpty(loading, Boolean(item))
  if (empty) return empty

  const locked = Boolean(disabled || pending)
  const stamp = systemStampLabel(item, detail)
  const gate = resolveCardStackGate(item, detail)
  const gated = Boolean(gate?.blocked)
  const notFound = statusId === STATUS_NOT_FOUND
  const notLive = matchingDetailIsNotLive(detail ?? undefined)
  const selectable = !notFound && !notLive && !gated
  const disposition = matchingDispositionCopy('data_owner')
  const matchType = detail?.match_type ?? item?.match_type
  const connections = (item ? inboxItemConnections(item) : []).filter(
    (connection) => !isHiddenSystem(connection.system),
  )
  const sourceLabel = inboxIntakeSourceLabel(item?.intake_source)
  const received = factDate(item?.requested_at ?? item?.received_at ?? detail?.recorded_at)
  const requestorState = detail?.requestor_state ?? item?.requestor_state
  const verticalId = item?.vertical ?? detail?.vertical ?? null
  const emphasizeDelete = defaultDisposition === STATUS_DELETE
  const emphasizeOptIn = defaultDisposition === STATUS_OPT_IN
  const removed = new Set(removedDwids)
  const visiblePeople = people.filter((contact) => {
    const dwid = contact.dwid?.trim() || ''
    return !dwid || !removed.has(dwid)
  })
  const addCandidates = people.filter((contact) => {
    const dwid = contact.dwid?.trim() || ''
    return Boolean(dwid) && removed.has(dwid)
  })
  const query = search.trim().toLowerCase()
  const searchHits = query
    ? addCandidates.filter((contact) => personSearchHaystack(contact).includes(query))
    : addCandidates
  const applyDwids = visiblePeople
    .map((contact) => contact.dwid?.trim() || '')
    .filter((dwid) => dwid && selectedDwids.includes(dwid))
  const applyLocked = locked || gated

  function chooseStatus(next: string) {
    onStatusChange(next)
    if (next === STATUS_NOT_FOUND) {
      onSelectedDwidsChange([])
      return
    }
    const nextDwids = visiblePeople
      .map((contact) => contact.dwid?.trim() || '')
      .filter(Boolean)
    onSelectedDwidsChange(nextDwids)
    if (next === STATUS_DELETE || next === STATUS_OPT_IN) {
      setDispositions((current) => {
        const updated = { ...current }
        for (const dwid of nextDwids) updated[dwid] = next
        return updated
      })
    }
  }

  function setPersonDisposition(dwid: string, next: '3' | '4') {
    if (!dwid || !selectable) return
    onStatusChange(next)
    setDispositions((current) => ({ ...current, [dwid]: next }))
    if (!selectedDwids.includes(dwid)) {
      onSelectedDwidsChange([...selectedDwids, dwid])
    }
  }

  function removePerson(dwid: string) {
    if (!dwid || applyLocked) return
    setRemovedDwids((current) => (current.includes(dwid) ? current : [...current, dwid]))
    onSelectedDwidsChange(selectedDwids.filter((id) => id !== dwid))
    setDispositions((current) => {
      const next = { ...current }
      delete next[dwid]
      return next
    })
  }

  function addPerson(contact: MatchedPersonContact) {
    const dwid = contact.dwid?.trim() || ''
    if (!dwid || applyLocked) return
    setRemovedDwids((current) => current.filter((id) => id !== dwid))
    setDispositions((current) => ({ ...current, [dwid]: defaultDisposition }))
    if (!selectedDwids.includes(dwid)) {
      onSelectedDwidsChange([...selectedDwids, dwid])
    }
    if (statusId === STATUS_NOT_FOUND) onStatusChange(defaultDisposition)
    setSearch('')
  }

  return (
    <div className="space-y-3">
      <header className="space-y-0.5">
        <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
          Owner matching
        </p>
        <h2 className="text-xl font-medium text-ink">Evidence cards</h2>
        <p className="text-xs text-ink-soft">
          One exhibit per person — one matching attempt. Email, phone, and NDZ are
          evidence fields on that exhibit, not separate matches.
        </p>
      </header>

      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 rounded-md border border-line bg-canvas px-2.5 py-2 sm:grid-cols-4">
        <div className="min-w-0">
          <dt className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">Source</dt>
          <dd className="truncate text-[0.7rem] text-ink">{sourceLabel}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">Request</dt>
          <dd className="truncate font-mono text-[0.7rem] text-ink">
            {shortRequestId(item?.request_id)}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">Received</dt>
          <dd className="truncate text-[0.7rem] text-ink">{received}</dd>
        </div>
        <div className="min-w-0">
          <dt className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">State</dt>
          <dd className="truncate font-mono text-[0.7rem] text-ink">{requestorState || '—'}</dd>
        </div>
      </dl>

      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="default" className="normal-case tracking-normal">
          {gated
            ? gateChipLabel(gate!)
            : notLive
              ? detail?.result_kind === 'sheet_stub'
                ? 'Sheet matching not live'
                : 'System matching not live'
              : matchTypeLabel(matchType, ownerLanguage)}
        </Badge>
        <SystemStamp label={stamp} compact />
        {connections.length > 1
          ? connections.map((connection, index) => {
              const label =
                catalogSystemDisplayLabel(connection.system, {
                  vertical: connection.vertical ?? item?.vertical,
                  systemLabel: connection.system_label,
                }) ?? `System ${index + 1}`
              if (label === stamp) return null
              return (
                <Badge
                  key={`${connection.system ?? label}-${index}`}
                  variant="wait"
                  className="normal-case tracking-normal"
                >
                  Also {label}
                </Badge>
              )
            })
          : null}
      </div>

      <fieldset className="space-y-1.5" disabled={applyLocked}>
        <legend className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
          Match result
        </legend>
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Match result">
          {statusOptions.map((option) => {
            const selected = statusId === option.id
            return (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={applyLocked}
                onClick={() => chooseStatus(option.id)}
                className={cn(
                  'rounded-md border px-2.5 py-1.5 text-xs',
                  selected
                    ? 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
                    : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
                )}
              >
                {option.label}
              </button>
            )
          })}
        </div>
      </fieldset>

      <div className="space-y-2">
        {gate ? (
          <CardStackGateBanner
            gate={gate}
            verticalId={verticalId}
            fallbackReason={detail?.not_live_reason}
          />
        ) : null}

        {people.length === 0 ? (
          <p className="rounded-md border border-line bg-canvas px-2.5 py-2 text-xs text-ink-soft">
            {gated || notLive
              ? detail?.not_live_reason?.trim() ||
                'Matching is gated for this system. No person exhibits to file yet.'
              : matchType === 'not_found' || notFound
                ? 'No person exhibits — recorded as not a match.'
                : 'No person records returned for this system.'}
          </p>
        ) : (
          <>
            {visiblePeople.length === 0 ? (
              <p className="rounded-md border border-line bg-canvas px-2.5 py-2 text-xs text-ink-soft">
                All exhibits removed. Search this system to add a person back, or mark not a match.
              </p>
            ) : (
              <div className="grid gap-2 sm:grid-cols-2">
                {visiblePeople.map((contact, index) => {
                  const dwid = contact.dwid?.trim() || ''
                  return (
                    <EvidenceCard
                      key={dwid || `exhibit-${index}`}
                      contact={contact}
                      index={index}
                      stamp={stamp}
                      disposition={dwid ? (dispositions[dwid] ?? null) : null}
                      emphasizeDelete={emphasizeDelete}
                      emphasizeOptIn={emphasizeOptIn}
                      selectable={selectable}
                      disabled={applyLocked || !selectable}
                      onDisposition={(next) => setPersonDisposition(dwid, next)}
                      onRemove={() => removePerson(dwid)}
                    />
                  )
                })}
              </div>
            )}

            <div className="rounded-md border border-line bg-canvas px-2.5 py-2">
              <label className="block text-[0.55rem] font-medium uppercase tracking-wide text-mute">
                Add from this system
              </label>
              <input
                type="search"
                value={search}
                disabled={applyLocked}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search matched people on this system"
                className="mt-1 h-8 w-full rounded-md border border-line bg-paper px-2 text-xs text-ink outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid disabled:opacity-50"
              />
              {addCandidates.length === 0 && !query ? (
                <p className="mt-1.5 text-[0.65rem] text-ink-soft">
                  Matches are pre-filled on the stack. Remove a card, then search to add it back.
                </p>
              ) : searchHits.length > 0 ? (
                <ul className="mt-1.5 space-y-1">
                  {searchHits.map((contact) => {
                    const dwid = contact.dwid?.trim() || ''
                    return (
                      <li key={dwid}>
                        <button
                          type="button"
                          disabled={applyLocked}
                          onClick={() => addPerson(contact)}
                          className="flex w-full items-center justify-between gap-2 rounded-md border border-line bg-paper px-2 py-1 text-left text-[0.7rem] text-ink hover:border-habeas-navy/35 disabled:opacity-50"
                        >
                          <span className="truncate">{formatMatchedContactLabel(contact)}</span>
                          <span className="shrink-0 text-[0.6rem] text-habeas-navy">Add</span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              ) : (
                <p className="mt-1.5 text-[0.65rem] text-ink-soft">
                  No directory search for this system yet.
                </p>
              )}
            </div>
          </>
        )}
      </div>

      {notFound ? (
        <p className="text-[0.65rem] text-mute">
          Not a match — selected people are not sent (selection cleared).
        </p>
      ) : null}

      <ResultApplyBar
        pending={pending}
        disabled={
          applyLocked || statusId == null || applyNeedsPeople(statusId, applyDwids)
        }
        onApply={() => onApply({ statusId: statusId ?? defaultDisposition, selectedDwids: applyDwids })}
        label={disposition.confirmLabel}
      />
    </div>
  )
}
