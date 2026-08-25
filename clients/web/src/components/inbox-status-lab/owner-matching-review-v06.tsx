import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'

import {
  formatMatchedContactLabel,
  formatMatchedContactsSummary,
  matchedChannelsFromDetail,
  matchingDetailIsNotLive,
  matchingDispositionCopy,
  redactHashHex,
  safeMatchedContacts,
} from '@/components/requests/RequestTriageDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { MatchedPersonContact, MatchingResultDetail, NeedsAttentionItem } from '@/lib/api'
import { suggestedDropResponseStatus } from '@/lib/api'
import {
  matchingConnectorGateBannerCopy,
  matchingConnectorGateChip,
  matchingGateFromAttempts,
  ownerConnectorsSearch,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import {
  inboxIntakeSourceLabel,
  matchTypeLabel,
} from '@/lib/inbox-batch-status'
import { inboxItemChannels, type InboxItemChannel } from '@/lib/inbox-status-lab'
import { catalogSystemDisplayLabel, DROP_HASH_SYSTEM_ID } from '@/lib/legalJourneyLabels'
import { cn } from '@/lib/utils'

import {
  applyNeedsPeople,
  ResultApplyBar,
  ResultContactPii,
  resultViewEmpty,
} from '../matching-results-lab/ResultViewChrome'
import type { MatchingResultsViewProps } from '../matching-results-lab/matching-results-lab-types'

/** Legal/compliance two-column story: request narrative + source left, matched people right. */
export const OWNER_MATCHING_REVIEW_V06_PHILOSOPHY =
  'Legal/compliance two-column story: request narrative + source left, matched people right.'

const SURFACE_ORDER: InboxItemChannel[] = ['email', 'phone', 'ndz']
const SURFACE_LABEL: Record<InboxItemChannel, string> = {
  email: 'Email',
  phone: 'Phone',
  ndz: 'NDZ',
}

const STATUS_DELETE = '3'
const STATUS_OPT_IN = '4'
const STATUS_NOT_FOUND = '5'

function storyDate(iso: string | null | undefined): string | null {
  const raw = iso?.trim()
  if (!raw) return null
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function shortRequestId(requestId: string | undefined): string {
  const id = requestId?.trim() ?? ''
  return id ? `${id.slice(0, 8)}…` : '—'
}

function isCassandraSlug(value: string | null | undefined): boolean {
  const normalized = value?.trim().toLowerCase() ?? ''
  return normalized === 'cassandra' || normalized === DROP_HASH_SYSTEM_ID
}

function isTestVertical(vertical: string | null | undefined): boolean {
  return (vertical ?? '').trim().toLowerCase() === 'test'
}

function reviewVertical(
  item: MatchingResultsViewProps['item'],
  detail: MatchingResultsViewProps['detail'],
): string | null {
  return (detail?.vertical ?? item?.vertical)?.trim() || null
}

function reviewSystemId(
  item: MatchingResultsViewProps['item'],
  detail: MatchingResultsViewProps['detail'],
): string | null {
  return (detail?.system ?? item?.system ?? item?.system_id)?.trim() || null
}

/** Hash-index source — never a connector chip or wizard target. */
function isDropHashReview(
  item: MatchingResultsViewProps['item'],
  detail: MatchingResultsViewProps['detail'],
): boolean {
  if (isTestVertical(reviewVertical(item, detail))) return false
  return isCassandraSlug(reviewSystemId(item, detail))
}

function connectorsVerticalId(
  item: MatchingResultsViewProps['item'],
  detail: MatchingResultsViewProps['detail'],
): string | null {
  const vertical = reviewVertical(item, detail)
  if (!vertical) return null
  const normalized = vertical.toLowerCase()
  if (normalized === 'data' || isCassandraSlug(vertical)) return null
  return vertical
}

function activeSystemLabel({
  item,
  detail,
}: Pick<MatchingResultsViewProps, 'item' | 'detail'>): string {
  const system = reviewSystemId(item, detail)
  return (
    catalogSystemDisplayLabel(system, {
      vertical: reviewVertical(item, detail),
      systemLabel: detail?.system_label ?? item?.system_label,
    }) ?? 'This system'
  )
}

function requestConnections(item: MatchingResultsViewProps['item']) {
  const rows = item?.connections ?? []
  const seen = new Set<string>()
  const unique: Array<{ key: string; label: string; active: boolean }> = []
  const activeId = (item?.system ?? item?.system_id)?.trim() || null
  const vertical = item?.vertical
  for (const row of rows) {
    const key = row.system?.trim() || row.system_label?.trim() || ''
    if (!key || seen.has(key)) continue
    if (!isTestVertical(row.vertical ?? vertical) && isCassandraSlug(row.system ?? key)) {
      continue
    }
    const label =
      catalogSystemDisplayLabel(row.system, {
        vertical: row.vertical ?? vertical,
        systemLabel: row.system_label,
      }) ?? row.system_label ?? key
    if (!label || isCassandraSlug(label)) continue
    seen.add(key)
    unique.push({
      key,
      label,
      active: Boolean(activeId && row.system?.trim() === activeId),
    })
  }
  return unique
}

type BlockedMatchingStatus = {
  title: string
  description: string
  chipLabel: string
}

/** Connect / refresh gate — owner language. Never names the hash-index slug. */
function blockedMatchingStatus({
  item,
  detail,
}: Pick<MatchingResultsViewProps, 'item' | 'detail'>): BlockedMatchingStatus | null {
  if (!item) return null
  if (isDropHashReview(item, detail)) return null

  const system = activeSystemLabel({ item, detail })
  const gate = matchingGateFromAttempts(detail?.attempts)
  if (gate?.blocked) {
    const refresh =
      gate.displayStatus === 'needs_refresh' || gate.gateCode === 'upload_stale'
    const setup =
      gate.displayStatus === 'needs_setup' || gate.gateCode === 'wizard_incomplete'
    if (refresh) {
      return {
        title: 'Needs refresh',
        chipLabel: 'Needs refresh',
        description: `Upload data for ${system} is stale. Matching stays gated until a fresh file is uploaded.`,
      }
    }
    if (setup) {
      return {
        title: 'Needs connection',
        chipLabel: 'Needs connection',
        description: `Finish connecting ${system} so matching can run.`,
      }
    }
    return {
      title: 'Action required',
      chipLabel: 'Action required',
      description: `Matching on ${system} is blocked until the connector is updated.`,
    }
  }

  if (matchingDetailIsNotLive(detail)) {
    return {
      title: 'Needs connection',
      chipLabel: 'Needs connection',
      description:
        detail?.not_live_reason?.trim() ||
        `Connect ${system} so matching can run. A passing connection test does not enable matching.`,
    }
  }

  return null
}

/** People-count story only — never “matched via phone” or a channel plot. */
function requestNarrative({
  item,
  detail,
  contacts,
  blocked,
}: Pick<MatchingResultsViewProps, 'item' | 'detail' | 'contacts'> & {
  blocked: BlockedMatchingStatus | null
}): string {
  if (!item) return ''
  const source = inboxIntakeSourceLabel(item.intake_source)
  const arrived = storyDate(item.requested_at ?? item.received_at)
  const state = item.requestor_state?.trim()
  const system = activeSystemLabel({ item, detail })
  const vertical = (detail?.vertical_label ?? item.vertical_label)?.trim()
  const matchType = detail?.match_type ?? item.match_type
  const count = detail?.match_count ?? item.match_count ?? contacts.length
  const notLive = matchingDetailIsNotLive(detail)

  const arrival = arrived
    ? `This request arrived through ${source} on ${arrived}`
    : `This request arrived through ${source}`
  const origin = state ? `${arrival} from a ${state} requestor.` : `${arrival}.`

  const where = vertical ? `${system} in ${vertical}` : system
  let matching: string
  if (blocked) {
    matching = `Matching on ${where} is gated (${blocked.title.toLowerCase()}).`
  } else if (notLive) {
    matching = `Matching on ${where} is not live yet${
      detail?.not_live_reason ? ` (${detail.not_live_reason})` : ''
    }.`
  } else if (matchType === 'not_found' || count === 0) {
    matching = `Matching on ${where} found no people.`
  } else if (count === 1) {
    matching = `Matching on ${where} found one person.`
  } else {
    matching = `Matching on ${where} found ${count} people.`
  }

  return `${origin} ${matching} Read the people on the right, then record the match result. This does not start Legal kickoff.`
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">{label}</dt>
      <dd className="mt-0.5 truncate text-xs text-ink">{value}</dd>
    </div>
  )
}

function attemptSurfaces(
  item: NeedsAttentionItem | null,
  detail: MatchingResultDetail | null,
): InboxItemChannel[] {
  const seen = new Set<InboxItemChannel>(
    inboxItemChannels({
      request_id: item?.request_id ?? '',
      matched_via: detail?.matched_via ?? item?.matched_via,
      matched_channels: detail?.matched_channels,
      channels: item?.channels,
    }),
  )
  for (const surface of matchedChannelsFromDetail(detail)) seen.add(surface)
  return SURFACE_ORDER.filter((surface) => seen.has(surface))
}

function safeSurfaceValue(raw: string | null | undefined): string | null {
  const value = raw?.trim()
  if (!value) return null
  const safe = redactHashHex(value)
  return safe === '—' ? null : safe
}

function personName(contact: MatchedPersonContact): string | null {
  const lastName = contact.last_name?.trim()
  const first = contact.first_initial?.trim()
  if (lastName && first) return `${first} ${lastName}`
  if (lastName) return lastName
  const initials = [first, contact.last_initial?.trim()].filter(Boolean).join(' ')
  return initials || null
}

function emailSurfaceValue(contact: MatchedPersonContact): string | null {
  return safeSurfaceValue(contact.email)
}

function phoneSurfaceValue(contact: MatchedPersonContact): string | null {
  const phones = Array.isArray(contact.phones) ? contact.phones : []
  const parts = phones
    .map((phone) => safeSurfaceValue(typeof phone?.number === 'string' ? phone.number : null))
    .filter((part): part is string => Boolean(part))
  return parts.length > 0 ? parts.join(' · ') : null
}

function ndzSurfaceValue(contact: MatchedPersonContact): string | null {
  const parts = [personName(contact), contact.dob?.trim(), contact.state?.trim()].filter(
    (part): part is string => Boolean(part),
  )
  return parts.length > 0 ? parts.join(' · ') : null
}

function surfaceOrOnPerson(
  value: string | null,
  onAttempt: boolean,
): string {
  if (value) return value
  return onAttempt ? 'On this person' : '—'
}

/** Email / phone / NDZ on this person — evidence fields, not separate attempts. */
function personSurfaceRows(
  contact: MatchedPersonContact,
  attempt: InboxItemChannel[],
): Array<{ id: InboxItemChannel; label: string; value: string }> {
  return [
    {
      id: 'email',
      label: SURFACE_LABEL.email,
      value: surfaceOrOnPerson(emailSurfaceValue(contact), attempt.includes('email')),
    },
    {
      id: 'phone',
      label: SURFACE_LABEL.phone,
      value: surfaceOrOnPerson(phoneSurfaceValue(contact), attempt.includes('phone')),
    },
    {
      id: 'ndz',
      label: SURFACE_LABEL.ndz,
      value: surfaceOrOnPerson(ndzSurfaceValue(contact), attempt.includes('ndz')),
    },
  ]
}

const DIRECTORY_SEARCH_DEBOUNCE_MS = 200
const DIRECTORY_SEARCH_MIN_CHARS = 2

type PeopleSearchPending = { title: string; support: string }

function peopleSearchLockCopy(
  blocked: MatchingConnectorGate | null | undefined,
  pending: PeopleSearchPending | null | undefined,
): { label: string; support: string } | null {
  if (blocked?.blocked) {
    const chip = matchingConnectorGateChip(blocked)
    const label =
      chip.label === 'Connected' || chip.label === 'Needs setup'
        ? 'Needs connection'
        : chip.label
    return {
      label,
      support: matchingConnectorGateBannerCopy(blocked).description,
    }
  }
  if (pending) {
    return {
      label: pending.title === 'Connected' ? 'Needs connection' : pending.title,
      support: pending.support,
    }
  }
  return null
}

function unifyPeople(contacts: MatchedPersonContact[]): MatchedPersonContact[] {
  const people: MatchedPersonContact[] = []
  const indexByDwid = new Map<string, number>()
  for (const contact of contacts) {
    const dwid = contact.dwid?.trim()
    if (dwid && indexByDwid.has(dwid)) continue
    if (dwid) indexByDwid.set(dwid, people.length)
    people.push(contact)
  }
  return people
}

function PersonStoryBeat({
  contact,
  attempt,
  selected,
  disposition,
  emphasizeDelete,
  emphasizeOptIn,
  disabled,
  onDelete,
  onOptIn,
  onRemove,
}: {
  contact: MatchedPersonContact
  attempt: InboxItemChannel[]
  selected: boolean
  disposition: string | null
  emphasizeDelete: boolean
  emphasizeOptIn: boolean
  disabled: boolean
  onDelete: () => void
  onOptIn: () => void
  onRemove: () => void
}) {
  const dwid = contact.dwid?.trim() || ''
  const surfaces = personSurfaceRows(contact, attempt)
  const deleteOn = selected && disposition === STATUS_DELETE
  const optInOn = selected && disposition === STATUS_OPT_IN
  return (
    <article
      className={cn(
        'rounded-md border px-2.5 py-2',
        selected ? 'border-habeas-navy bg-habeas-navy/5' : 'border-line bg-paper',
        disabled && 'opacity-60',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <ResultContactPii contact={contact} />
          <span className="mt-0.5 block font-mono tabular-nums text-[0.6rem] text-mute">
            {dwid || '—'}
          </span>
        </div>
        <button
          type="button"
          disabled={disabled}
          onClick={onRemove}
          className="shrink-0 text-[0.65rem] text-mute hover:text-ink disabled:opacity-50"
        >
          Remove
        </button>
      </div>
      <div
        role="radiogroup"
        aria-label={`Disposition for ${formatMatchedContactLabel(contact)}`}
        className="mt-2 flex flex-wrap gap-1"
      >
        <button
          type="button"
          role="radio"
          aria-checked={deleteOn}
          disabled={disabled}
          onClick={onDelete}
          className={cn(
            'rounded-md border px-2 py-1 text-[0.65rem]',
            deleteOn
              ? 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
              : emphasizeDelete
                ? 'border-habeas-navy/40 bg-paper text-ink'
                : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
            disabled && 'opacity-50',
          )}
        >
          Delete
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={optInOn}
          disabled={disabled}
          onClick={onOptIn}
          className={cn(
            'rounded-md border px-2 py-1 text-[0.65rem]',
            optInOn
              ? 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
              : emphasizeOptIn
                ? 'border-habeas-navy/40 bg-paper text-ink'
                : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
            disabled && 'opacity-50',
          )}
        >
          Opt-in
        </button>
      </div>
      <div className="mt-2 border-t border-line/80 pt-1.5">
        <p className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">
          Surfaces
        </p>
        <dl className="mt-1 grid grid-cols-3 gap-x-2">
          {surfaces.map((surface) => (
            <Fact key={surface.id} label={surface.label} value={surface.value} />
          ))}
        </dl>
      </div>
    </article>
  )
}

/**
 * Owner matching-only review — legal/compliance two-column story.
 * Left: request narrative + source. Right: one person = one story beat.
 * Email / phone / NDZ are surfaces on that person, not a left-column channel plot.
 */
export function OwnerMatchingReviewV06({
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
  onSearchPeople,
  peopleSearchBlocked,
  peopleSearchPending,
}: MatchingResultsViewProps & {
  peopleSearchBlocked?: MatchingConnectorGate | null
  peopleSearchPending?: PeopleSearchPending | null
}) {
  const [search, setSearch] = useState('')
  const [removedDwids, setRemovedDwids] = useState<string[]>([])
  const [addedPeople, setAddedPeople] = useState<MatchedPersonContact[]>([])
  const [directoryHits, setDirectoryHits] = useState<MatchedPersonContact[]>([])
  const [directoryPending, setDirectoryPending] = useState(false)
  const [directoryFailed, setDirectoryFailed] = useState(false)
  const searchPeopleRef = useRef(onSearchPeople)
  searchPeopleRef.current = onSearchPeople

  const localBlocked = blockedMatchingStatus({ item, detail })
  const searchLock =
    peopleSearchLockCopy(
      peopleSearchBlocked?.blocked ? peopleSearchBlocked : null,
      peopleSearchPending,
    ) ??
    (!onSearchPeople
      ? {
          label: 'Needs connection',
          support: 'Connect this system before people can be searched.',
        }
      : null)
  const blocked: BlockedMatchingStatus | null = searchLock
    ? {
        title: searchLock.label,
        chipLabel: searchLock.label,
        description: searchLock.support,
      }
    : localBlocked
  const searchLocked =
    Boolean(disabled || pending) ||
    Boolean(peopleSearchBlocked?.blocked) ||
    Boolean(peopleSearchPending) ||
    Boolean(blocked) ||
    !onSearchPeople

  const rosterKey = [
    item?.request_id ?? '',
    reviewSystemId(item, detail) ?? '',
    safeMatchedContacts(contacts)
      .map((contact) => contact.dwid?.trim())
      .filter(Boolean)
      .join(','),
  ].join('::')

  useEffect(() => {
    setSearch('')
    setRemovedDwids([])
    setAddedPeople([])
    setDirectoryHits([])
  }, [rosterKey])

  useEffect(() => {
    const needle = search.trim()
    const searchFn = searchPeopleRef.current
    if (searchLocked || !searchFn || needle.length < DIRECTORY_SEARCH_MIN_CHARS) {
      setDirectoryHits([])
      setDirectoryPending(false)
      setDirectoryFailed(false)
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      void (async () => {
        setDirectoryPending(true)
        setDirectoryFailed(false)
        try {
          const result = await searchFn(needle)
          if (!cancelled) setDirectoryHits(result)
        } catch {
          if (!cancelled) {
            setDirectoryHits([])
            setDirectoryFailed(true)
          }
        } finally {
          if (!cancelled) setDirectoryPending(false)
        }
      })()
    }, DIRECTORY_SEARCH_DEBOUNCE_MS)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [search, searchLocked])

  const empty = resultViewEmpty(loading, Boolean(item))
  const peopleCleared = statusId === STATUS_NOT_FOUND
  const locked = Boolean(disabled || pending || blocked)
  const copy = matchingDispositionCopy(ownerLanguage ? 'data_owner' : 'ops')
  const systems = requestConnections(item)
  const source = inboxIntakeSourceLabel(item?.intake_source)
  const arrived = storyDate(item?.requested_at ?? item?.received_at) ?? '—'
  const narrative = requestNarrative({ item, detail, contacts, blocked })
  const finding = statusOptions.find((option) => option.id === statusId)?.label ?? null
  const matchedPeople = useMemo(
    () => unifyPeople(safeMatchedContacts(contacts)),
    [contacts],
  )
  const addedSafe = useMemo(() => unifyPeople(safeMatchedContacts(addedPeople)), [addedPeople])
  const pool = useMemo(() => {
    const seen = new Set<string>()
    const rows: MatchedPersonContact[] = []
    for (const contact of [...matchedPeople, ...addedSafe]) {
      const dwid = contact.dwid?.trim()
      if (dwid) {
        if (seen.has(dwid)) continue
        seen.add(dwid)
      }
      rows.push(contact)
    }
    return rows
  }, [addedSafe, matchedPeople])
  const visiblePeople = useMemo(
    () =>
      pool.filter((contact) => {
        const dwid = contact.dwid?.trim()
        return !dwid || !removedDwids.includes(dwid)
      }),
    [pool, removedDwids],
  )
  const surfaces = attemptSurfaces(item, detail)
  const notLive = matchingDetailIsNotLive(detail)
  const matchType = detail?.match_type ?? item?.match_type
  const peopleUnavailable = detail?.matched_contacts_status === 'unavailable'
  const suggested = String(
    suggestedDropResponseStatus(
      detail?.match_type ?? item?.match_type,
      detail?.match_count ?? item?.match_count ?? matchedPeople.length,
    ),
  )
  const emphasizeDelete = suggested === STATUS_DELETE
  const emphasizeOptIn = suggested === STATUS_OPT_IN
  const query = search.trim()
  const visibleIds = new Set(
    visiblePeople.map((contact) => contact.dwid?.trim() || '').filter(Boolean),
  )
  const searchHits = directoryHits.filter((contact) => {
    const dwid = contact.dwid?.trim() || ''
    return Boolean(dwid) && !visibleIds.has(dwid)
  })

  function includePerson(dwid: string, nextStatus: string) {
    if (!dwid) return
    setRemovedDwids((current) => current.filter((id) => id !== dwid))
    onStatusChange(nextStatus)
    if (!selectedDwids.includes(dwid)) {
      onSelectedDwidsChange([...selectedDwids, dwid])
    }
  }

  function removePerson(dwid: string) {
    if (!dwid) return
    setRemovedDwids((current) => (current.includes(dwid) ? current : [...current, dwid]))
    onSelectedDwidsChange(selectedDwids.filter((id) => id !== dwid))
  }

  function addPerson(contact: MatchedPersonContact) {
    const dwid = contact.dwid?.trim()
    if (!dwid) return
    const alreadyKnown = pool.some((row) => row.dwid?.trim() === dwid)
    if (!alreadyKnown) setAddedPeople((current) => [...current, contact])
    includePerson(dwid, statusId === STATUS_OPT_IN ? STATUS_OPT_IN : STATUS_DELETE)
    setSearch('')
    setDirectoryHits([])
  }

  if (empty) return empty

  return (
    <div className="flex min-h-0 flex-col gap-3">
      <header className="shrink-0 space-y-1">
        <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
          Matching review
        </p>
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-xl font-semibold text-ink">
            {activeSystemLabel({ item, detail })}
          </h2>
          <Badge variant="default" className="normal-case tracking-normal">
            {matchTypeLabel(matchType, ownerLanguage)}
          </Badge>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 overflow-hidden rounded-md border border-line bg-paper md:grid-cols-2">
        <section
          aria-labelledby="owner-review-v06-story"
          className="min-h-0 min-w-0 space-y-3 overflow-y-auto border-b border-line px-3 py-3 md:border-b-0 md:border-r"
        >
          <h3
            id="owner-review-v06-story"
            className="text-[0.65rem] font-medium uppercase tracking-wide text-mute"
          >
            Request
          </h3>
          <p className="text-xs leading-relaxed text-ink">{narrative}</p>

          {blocked ? (
            <div
              className="space-y-2 rounded-md border border-line bg-canvas px-2.5 py-2"
              role="status"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="fail" className="normal-case tracking-normal">
                  {blocked.chipLabel}
                </Badge>
                <p className="text-xs font-medium text-ink">{blocked.title}</p>
              </div>
              <p className="text-[0.7rem] leading-snug text-ink-soft">{blocked.description}</p>
              <Button asChild size="sm">
                <Link
                  to="/owner/connectors"
                  search={ownerConnectorsSearch(connectorsVerticalId(item, detail))}
                >
                  Open connectors
                </Link>
              </Button>
            </div>
          ) : null}

          <dl className="grid grid-cols-2 gap-x-3 gap-y-2 border-t border-line pt-2">
            <Fact label="Source" value={source} />
            <Fact label="Request" value={shortRequestId(item?.request_id)} />
            <Fact label="Received" value={arrived} />
            <Fact
              label="Requestor state"
              value={item?.requestor_state?.trim() || '—'}
            />
            <Fact
              label="Vertical"
              value={(detail?.vertical_label ?? item?.vertical_label)?.trim() || '—'}
            />
            <Fact label="System" value={activeSystemLabel({ item, detail })} />
          </dl>

          {systems.length > 1 ? (
            <div className="space-y-1.5">
              <p className="text-[0.55rem] font-medium uppercase tracking-wide text-mute">
                Systems on this request
              </p>
              <ul className="flex flex-wrap gap-1">
                {systems.map((system) => (
                  <li key={system.key}>
                    <Badge
                      variant={system.active ? 'run' : 'wait'}
                      className="normal-case tracking-normal"
                    >
                      {system.label}
                      {system.active ? ' · reviewing' : ''}
                    </Badge>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>

        <section
          aria-labelledby="owner-review-v06-people"
          className="min-h-0 min-w-0 space-y-2 overflow-y-auto px-3 py-3"
        >
          <div className="flex items-baseline justify-between gap-2">
            <h3
              id="owner-review-v06-people"
              className="text-[0.65rem] font-medium uppercase tracking-wide text-mute"
            >
              Matched people
            </h3>
            <span className="tabular-nums text-[0.65rem] text-mute">
              {peopleCleared
                ? 'None applied'
                : formatMatchedContactsSummary(visiblePeople, selectedDwids)}
            </span>
          </div>

          {blocked ? (
            <p className="text-xs text-ink-soft">
              Matching is gated on this system. Connect or refresh before selecting people.
            </p>
          ) : notLive ? (
            <p className="text-xs text-ink-soft">
              {detail?.not_live_reason?.trim() ||
                'Matching is not live on this system. No people to review.'}
            </p>
          ) : peopleUnavailable && visiblePeople.length === 0 ? (
            <p className="text-xs text-ink-soft">
              Person records are unavailable for this system.
            </p>
          ) : visiblePeople.length === 0 && !query ? (
            <p className="text-xs text-ink-soft">
              {matchType === 'not_found' || peopleCleared
                ? 'No matched people for this system.'
                : 'No person records on this system. Search below to add someone from this match set.'}
            </p>
          ) : (
            <ul className="space-y-2">
              {visiblePeople.map((contact, index) => {
                const dwid = contact.dwid?.trim() || ''
                return (
                  <li key={dwid || `person-${index}`}>
                    <PersonStoryBeat
                      contact={contact}
                      attempt={surfaces}
                      selected={Boolean(dwid) && selectedDwids.includes(dwid) && !peopleCleared}
                      disposition={peopleCleared ? null : statusId}
                      emphasizeDelete={emphasizeDelete}
                      emphasizeOptIn={emphasizeOptIn}
                      disabled={locked || peopleCleared}
                      onDelete={() => includePerson(dwid, STATUS_DELETE)}
                      onOptIn={() => includePerson(dwid, STATUS_OPT_IN)}
                      onRemove={() => removePerson(dwid)}
                    />
                  </li>
                )
              })}
            </ul>
          )}

          <div className="space-y-1.5 border-t border-line pt-2">
            <label className="block">
              <span className="flex flex-wrap items-center gap-1.5 text-[0.55rem] font-medium uppercase tracking-wide text-mute">
                Add from this system
                {searchLock ? (
                  <Badge variant="fail" className="normal-case tracking-normal">
                    {searchLock.label}
                  </Badge>
                ) : null}
              </span>
              <input
                type="search"
                value={search}
                disabled={searchLocked || peopleCleared}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search this system’s matched people"
                className="mt-1 h-8 w-full rounded-md border border-line bg-paper px-2 text-xs text-ink outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid disabled:opacity-50"
              />
            </label>
            {searchLock ? (
              <p className="text-[0.7rem] text-ink-soft">{searchLock.support}</p>
            ) : directoryPending ? (
              <p className="text-[0.65rem] text-mute">Searching this system…</p>
            ) : directoryFailed ? (
              <p className="text-[0.7rem] text-ink-soft">
                Could not search this system. Try again.
              </p>
            ) : query.length < DIRECTORY_SEARCH_MIN_CHARS ? (
              <p className="text-[0.65rem] text-mute">
                Type at least two characters to search this system.
              </p>
            ) : searchHits.length > 0 ? (
              <ul className="space-y-1">
                {searchHits.map((contact) => {
                  const dwid = contact.dwid?.trim() || ''
                  const onRoster = Boolean(dwid) && !removedDwids.includes(dwid)
                  return (
                    <li key={dwid || formatMatchedContactLabel(contact)}>
                      <button
                        type="button"
                        disabled={searchLocked || peopleCleared || !dwid || onRoster}
                        onClick={() => addPerson(contact)}
                        className="flex w-full items-center justify-between rounded-md border border-line bg-canvas px-2 py-1.5 text-left text-xs text-ink disabled:opacity-50"
                      >
                        <span className="truncate">{formatMatchedContactLabel(contact)}</span>
                        <span className="shrink-0 text-[0.65rem] text-mute">
                          {onRoster ? 'On list' : 'Add'}
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            ) : (
              <p className="text-[0.7rem] text-ink-soft">No persons match that search.</p>
            )}
          </div>
        </section>
      </div>

      <footer className="shrink-0 space-y-2 rounded-md border border-line bg-canvas px-3 py-2.5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
            Match result
          </p>
          {blocked ? (
            <p className="text-[0.65rem] text-ink-soft">Connect or refresh before recording</p>
          ) : finding ? (
            <p className="text-[0.65rem] text-ink-soft">Finding · {finding}</p>
          ) : (
            <p className="text-[0.65rem] text-mute">Choose a result to record</p>
          )}
        </div>
        <div role="radiogroup" aria-label="Match result" className="flex flex-wrap gap-1.5">
          {statusOptions.map((option) => {
            const selected = statusId === option.id
            return (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={locked}
                onClick={() => {
                  onStatusChange(option.id)
                  if (option.id === STATUS_NOT_FOUND) onSelectedDwidsChange([])
                }}
                className={cn(
                  'rounded-md border px-2.5 py-1.5 text-xs',
                  selected
                    ? 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
                    : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
                  locked && 'opacity-50',
                )}
              >
                {option.label}
              </button>
            )
          })}
        </div>
        <ResultApplyBar
          pending={pending}
          disabled={
            Boolean(disabled || blocked) ||
            statusId == null ||
            applyNeedsPeople(statusId, selectedDwids)
          }
          onApply={onApply}
          label={pending ? copy.pendingLabel : copy.confirmLabel}
          statusId={statusId}
          selectedDwids={selectedDwids}
        />
      </footer>
    </div>
  )
}
