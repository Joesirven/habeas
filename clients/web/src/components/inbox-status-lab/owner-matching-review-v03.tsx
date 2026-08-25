/**
 * Owner matching review · v03
 * Philosophy: Systems operator — split pane: request/source/system meta left,
 * match people table right. Email / phone / NDZ are identifier surfaces on
 * people rows — not a left-pane Channel dimension (one matching attempt).
 */
import { useEffect, useState, type ReactNode } from 'react'
import { Link } from '@tanstack/react-router'

import {
  formatMatchedContactLabel,
  useMatchingConnectorGate,
} from '@/components/requests/RequestTriageDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useMe } from '@/lib/auth'
import { suggestedDropResponseStatus, type MatchedPersonContact } from '@/lib/api'
import {
  isDataCatalogVertical,
  matchingConnectorGateBannerCopy,
  matchingConnectorGateChip,
  ownerConnectorsSearch,
} from '@/lib/connection-display'
import {
  inboxIntakeSourceLabel,
  inboxItemSystemId,
  matchTypeLabel,
} from '@/lib/inbox-batch-status'
import { inboxItemChannels, type InboxItemChannel } from '@/lib/inbox-status-lab'
import { catalogSystemDisplayLabel, verticalLabel } from '@/lib/legalJourneyLabels'
import { isOwnerWizardHiddenSystem } from '@/lib/owner-connector-ui'
import { cn } from '@/lib/utils'

import {
  applyNeedsPeople,
  ResultApplyBar,
  resultViewEmpty,
} from '../matching-results-lab/ResultViewChrome'
import type { MatchingResultsViewProps } from '../matching-results-lab/matching-results-lab-types'

const SURFACE_ORDER: InboxItemChannel[] = ['email', 'phone', 'ndz']
const SURFACE_LABELS: Record<InboxItemChannel, string> = {
  email: 'Email',
  phone: 'Phone',
  ndz: 'NDZ',
}

type PersonDisposition = '3' | '4'

function contactSurfaces(
  contact: MatchedPersonContact,
  attemptSurfaces: InboxItemChannel[],
): InboxItemChannel[] {
  const seen = new Set<InboxItemChannel>(attemptSurfaces)
  if (contact.email?.trim()) seen.add('email')
  if (contact.phones?.some((phone) => phone?.number?.trim())) seen.add('phone')
  return SURFACE_ORDER.filter((surface) => seen.has(surface))
}

function SurfaceMarks({ surfaces }: { surfaces: InboxItemChannel[] }) {
  if (surfaces.length === 0) return <span className="text-mute">—</span>
  const label = surfaces.map((surface) => SURFACE_LABELS[surface]).join(', ')
  return (
    <span className="inline-flex flex-wrap gap-0.5" aria-label={label}>
      {surfaces.map((surface) => (
        <Badge
          key={surface}
          variant="default"
          className="px-1 py-px normal-case tracking-normal"
        >
          {SURFACE_LABELS[surface]}
        </Badge>
      ))}
    </span>
  )
}

function shortRequestId(requestId: string): string {
  return requestId.length > 8 ? `${requestId.slice(0, 8)}…` : requestId
}

function compactReceived(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function compactDob(value: string | null | undefined): string {
  const raw = value?.trim()
  if (!raw) return '—'
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw)
  if (!match) return raw
  return `${match[2]}/${match[3]}/${match[1]!.slice(2)}`
}

function MetaRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">{label}</dt>
      <dd className="min-w-0 truncate text-xs text-ink">{children}</dd>
    </>
  )
}

function seedDisposition(
  statusId: string | null,
  matchType?: string | null,
  matchCount?: number | null,
): PersonDisposition {
  if (statusId === '3' || statusId === '4') return statusId
  return suggestedDropResponseStatus(matchType, matchCount) === 4 ? '4' : '3'
}

function neverShowInfraName(value: string): string {
  return value.replace(/cassandra/gi, 'this system')
}

function personSearchHaystack(
  contact: MatchedPersonContact,
  attemptSurfaces: InboxItemChannel[],
): string {
  const surfaces = contactSurfaces(contact, attemptSurfaces)
    .map((surface) => SURFACE_LABELS[surface])
    .join(' ')
  return [formatMatchedContactLabel(contact), contact.state, contact.email, surfaces]
    .filter((part) => typeof part === 'string' && part.trim())
    .join(' ')
    .toLowerCase()
}

function contactsKey(contacts: MatchedPersonContact[]): string {
  return contacts
    .map((contact) => contact.dwid)
    .filter(Boolean)
    .join('\0')
}

/** Systems-operator split pane: request/source/system meta | match people table. */
export function OwnerMatchingReviewV03({
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
  const { me } = useMe()
  const systemId = item ? inboxItemSystemId(item) : detail?.system ?? null
  const verticalId = item?.vertical ?? detail?.vertical ?? null
  const hideConnectorSurface =
    isOwnerWizardHiddenSystem(systemId) || isDataCatalogVertical(verticalId)
  const gate = useMatchingConnectorGate({
    attempts: detail?.attempts,
    reminders: me?.connector_reminders,
    fetchConnections: Boolean(item) && !hideConnectorSurface,
  })
  const [removedDwids, setRemovedDwids] = useState<string[]>([])
  const [dispositions, setDispositions] = useState<Record<string, PersonDisposition>>({})
  const [addQuery, setAddQuery] = useState('')

  const poolKey = contactsKey(contacts)
  const matchType = detail?.match_type ?? item?.match_type
  const matchCount = detail?.match_count ?? item?.match_count
  useEffect(() => {
    setRemovedDwids([])
    setAddQuery('')
    const seed = seedDisposition(null, matchType, matchCount)
    const next: Record<string, PersonDisposition> = {}
    for (const dwid of poolKey.split('\0')) {
      if (dwid) next[dwid] = seed
    }
    setDispositions(next)
  }, [matchCount, matchType, poolKey])

  const empty = resultViewEmpty(loading, Boolean(item))
  if (empty) return empty

  const locked = Boolean(disabled || pending)
  const gateForThisSystem =
    Boolean(gate?.blocked) &&
    !hideConnectorSurface &&
    !isOwnerWizardHiddenSystem(gate?.system) &&
    (!gate?.system || !systemId || gate.system === systemId)
  const reviewLocked = locked || gateForThisSystem
  const notFound = statusId === '5'
  const systemName =
    catalogSystemDisplayLabel(systemId ?? detail?.system, {
      vertical: item?.vertical ?? detail?.vertical,
      systemLabel: item?.system_label ?? detail?.system_label,
    }) || '—'
  const verticalName =
    item?.vertical_label?.trim() ||
    detail?.vertical_label?.trim() ||
    (item?.vertical ? verticalLabel(item.vertical) : null) ||
    (detail?.vertical ? verticalLabel(detail.vertical) : null) ||
    '—'
  const attemptSurfaces = item
    ? inboxItemChannels({
        request_id: item.request_id,
        matched_via: detail?.matched_via ?? item.matched_via,
        matched_channels: detail?.matched_channels,
        channels: item.channels,
      })
    : []
  const pool = contacts.filter((contact) => Boolean(contact.dwid))
  const removed = new Set(removedDwids)
  const visible = notFound ? [] : pool.filter((contact) => !removed.has(contact.dwid))
  const query = addQuery.trim().toLowerCase()
  const addCandidates = pool.filter((contact) => {
    if (!removed.has(contact.dwid)) return false
    if (!query) return true
    return personSearchHaystack(contact, attemptSurfaces).includes(query)
  })
  const dispositionSet = new Set(
    visible.map((contact) => dispositions[contact.dwid] ?? seedDisposition(statusId)),
  )
  const mixedDispositions = dispositionSet.size > 1
  const unanimousDisposition =
    dispositionSet.size === 1 ? [...dispositionSet][0]! : null

  function handleStatusChange(next: string) {
    onStatusChange(next)
    if (next === '5') {
      onSelectedDwidsChange([])
      return
    }
    if (next === '3' || next === '4') {
      const nextDispositions: Record<string, PersonDisposition> = { ...dispositions }
      for (const contact of pool) {
        if (!removed.has(contact.dwid)) nextDispositions[contact.dwid] = next
      }
      setDispositions(nextDispositions)
      onSelectedDwidsChange(pool.filter((contact) => !removed.has(contact.dwid)).map((c) => c.dwid))
    }
  }

  function setPersonDisposition(dwid: string, next: PersonDisposition) {
    const nextDispositions = { ...dispositions, [dwid]: next }
    setDispositions(nextDispositions)
    const remaining = pool.filter((contact) => !removed.has(contact.dwid))
    const statuses = new Set(remaining.map((contact) => nextDispositions[contact.dwid] ?? next))
    if (statuses.size === 1 && statusId !== next) onStatusChange(next)
    onSelectedDwidsChange(remaining.map((contact) => contact.dwid))
  }

  function removePerson(dwid: string) {
    const nextRemoved = removedDwids.includes(dwid) ? removedDwids : [...removedDwids, dwid]
    setRemovedDwids(nextRemoved)
    const remaining = pool
      .filter((contact) => contact.dwid !== dwid && !nextRemoved.includes(contact.dwid))
      .map((contact) => contact.dwid)
    onSelectedDwidsChange(statusId === '5' ? [] : remaining)
    if (remaining.length === 0 && statusId !== '5') onStatusChange('5')
  }

  function addPerson(dwid: string) {
    const nextRemoved = removedDwids.filter((id) => id !== dwid)
    setRemovedDwids(nextRemoved)
    const remaining = pool
      .filter((contact) => !nextRemoved.includes(contact.dwid))
      .map((contact) => contact.dwid)
    if (statusId === '5') onStatusChange(dispositions[dwid] ?? seedDisposition(statusId))
    onSelectedDwidsChange(remaining)
    setAddQuery('')
  }

  const gateChip = gateForThisSystem && gate ? matchingConnectorGateChip(gate) : null
  const gateCopy =
    gateForThisSystem && gate
      ? (() => {
          const copy = matchingConnectorGateBannerCopy(gate)
          const fallback = systemName === '—' ? 'this system' : systemName
          return {
            title: neverShowInfraName(copy.title).replace(/this system/gi, fallback),
            description: neverShowInfraName(copy.description),
          }
        })()
      : null
  const connectorsVertical =
    verticalId && !isDataCatalogVertical(verticalId) && !isOwnerWizardHiddenSystem(verticalId)
      ? verticalId
      : null

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-[minmax(16rem,20rem)_minmax(0,1fr)]">
        <aside
          className="min-h-0 space-y-3 overflow-y-auto border-b border-line bg-canvas px-3 py-2.5 md:border-b-0 md:border-r"
          aria-labelledby="owner-matching-v03-meta"
        >
          <h3
            id="owner-matching-v03-meta"
            className="text-[0.65rem] font-medium uppercase tracking-wide text-mute"
          >
            Request · source · system
          </h3>
          <dl className="grid grid-cols-[5.5rem_minmax(0,1fr)] items-baseline gap-x-2 gap-y-1.5">
            <MetaRow label="Request">
              <span className="font-mono tabular-nums" title={item?.request_id}>
                {item ? shortRequestId(item.request_id) : '—'}
              </span>
            </MetaRow>
            <MetaRow label="Source">{inboxIntakeSourceLabel(item?.intake_source)}</MetaRow>
            <MetaRow label="System">{systemName}</MetaRow>
            <MetaRow label="Vertical">{verticalName}</MetaRow>
            <MetaRow label="Match">
              <span className="inline-flex flex-wrap items-baseline gap-1.5">
                <span>{matchTypeLabel(matchType, ownerLanguage)}</span>
                {matchCount != null ? (
                  <span className="tabular-nums text-mute">
                    {matchCount} {matchCount === 1 ? 'person' : 'people'}
                  </span>
                ) : null}
              </span>
            </MetaRow>
            <MetaRow label="State">{item?.requestor_state?.trim() || '—'}</MetaRow>
            <MetaRow label="Received">
              {compactReceived(item?.requested_at ?? item?.received_at)}
            </MetaRow>
            {gateChip && gateCopy ? (
              <MetaRow label="Status">
                <span className="inline-flex flex-wrap items-center gap-1.5">
                  <Badge variant={gateChip.variant} className="normal-case tracking-normal">
                    {gateChip.label}
                  </Badge>
                  <span className="text-ink-soft">{gateCopy.title}</span>
                </span>
              </MetaRow>
            ) : null}
          </dl>

          {gateForThisSystem && gateCopy ? (
            <div className="space-y-2 border-t border-line pt-2" role="status">
              <p className="text-[0.65rem] leading-snug text-ink-soft">{gateCopy.description}</p>
              <Button size="sm" asChild>
                <Link to="/owner/connectors" search={ownerConnectorsSearch(connectorsVertical)}>
                  Open connectors
                </Link>
              </Button>
            </div>
          ) : null}

          <fieldset disabled={reviewLocked} className="space-y-1 border-t border-line pt-2">
            <legend className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
              Disposition
            </legend>
            <div role="radiogroup" aria-label="Match disposition" className="space-y-0.5">
              {statusOptions.map((option) => {
                const selected = statusId === option.id
                return (
                  <label
                    key={option.id}
                    className={cn(
                      'flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs',
                      selected
                        ? 'bg-habeas-navy/10 font-medium text-habeas-navy'
                        : 'text-ink hover:bg-paper',
                      reviewLocked && 'cursor-not-allowed opacity-50',
                    )}
                  >
                    <input
                      type="radio"
                      name="owner-matching-v03-status"
                      value={option.id}
                      checked={selected}
                      disabled={reviewLocked}
                      onChange={() => handleStatusChange(option.id)}
                      className="accent-habeas-navy"
                    />
                    {option.label}
                  </label>
                )
              })}
            </div>
          </fieldset>
        </aside>

        <section
          className="flex min-h-0 min-w-0 flex-col overflow-hidden bg-paper px-3 py-2.5"
          aria-labelledby="owner-matching-v03-people"
        >
          <div className="mb-2 flex shrink-0 items-baseline justify-between gap-2">
            <h3
              id="owner-matching-v03-people"
              className="text-[0.65rem] font-medium uppercase tracking-wide text-mute"
            >
              Matched people
            </h3>
            {notFound ? (
              <span className="text-[0.65rem] text-mute">Not a match — no people sent</span>
            ) : visible.length > 0 ? (
              <span className="tabular-nums text-[0.65rem] text-mute">
                {visible.length}/{pool.length} included
              </span>
            ) : null}
          </div>

          <div className="mb-2 flex shrink-0 flex-col gap-1.5">
            <label className="sr-only" htmlFor="owner-matching-v03-add">
              Add person from this system
            </label>
            <input
              id="owner-matching-v03-add"
              type="search"
              value={addQuery}
              disabled={reviewLocked || notFound || pool.length === 0}
              placeholder="Add person from this system…"
              onChange={(event) => setAddQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== 'Enter') return
                event.preventDefault()
                const first = addCandidates[0]
                if (first) addPerson(first.dwid)
              }}
              className="h-7 w-full rounded-md border border-line bg-canvas px-2 text-xs text-ink outline-none placeholder:text-mute focus-visible:ring-2 focus-visible:ring-habeas-mid disabled:opacity-50"
            />
            {!notFound && removed.size > 0 ? (
              addCandidates.length > 0 ? (
                <ul className="max-h-24 space-y-0.5 overflow-y-auto rounded-md border border-line bg-canvas px-1.5 py-1">
                  {addCandidates.map((contact) => (
                    <li key={contact.dwid} className="flex items-center justify-between gap-2">
                      <span className="min-w-0 truncate text-xs text-ink">
                        {formatMatchedContactLabel(contact)}
                      </span>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={reviewLocked}
                        onClick={() => addPerson(contact.dwid)}
                      >
                        Add
                      </Button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[0.65rem] text-mute">No removed people match this search.</p>
              )
            ) : null}
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            {visible.length === 0 ? (
              <p className="text-xs text-mute">
                {notFound || matchType === 'not_found'
                  ? 'No matched people for this system.'
                  : pool.length > 0
                    ? 'People removed — search this system to add one back.'
                    : 'No person records returned for this system.'}
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Person</TableHead>
                    <TableHead>Surfaces</TableHead>
                    <TableHead>State</TableHead>
                    <TableHead>DOB</TableHead>
                    <TableHead>Delete</TableHead>
                    <TableHead>Opt-in</TableHead>
                    <TableHead className="w-16">
                      <span className="sr-only">Remove</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visible.map((contact, index) => {
                    const disposition =
                      dispositions[contact.dwid] ?? seedDisposition(statusId)
                    return (
                      <TableRow key={contact.dwid || `row-${index}`}>
                        <TableCell className="max-w-[14rem] truncate text-xs font-medium text-ink">
                          {formatMatchedContactLabel(contact)}
                        </TableCell>
                        <TableCell className="text-xs">
                          <SurfaceMarks surfaces={contactSurfaces(contact, attemptSurfaces)} />
                        </TableCell>
                        <TableCell className="text-xs text-ink-soft">
                          {contact.state || '—'}
                        </TableCell>
                        <TableCell className="tabular-nums text-xs text-ink-soft">
                          {compactDob(contact.dob)}
                        </TableCell>
                        <TableCell>
                          <label className="inline-flex items-center gap-1 text-xs">
                            <input
                              type="radio"
                              name={`owner-matching-v03-person-${contact.dwid}`}
                              checked={disposition === '3'}
                              disabled={reviewLocked || !contact.dwid}
                              aria-label={`Delete ${formatMatchedContactLabel(contact)}`}
                              onChange={() => setPersonDisposition(contact.dwid, '3')}
                              className="accent-habeas-navy"
                            />
                            <span className="sr-only">Delete</span>
                          </label>
                        </TableCell>
                        <TableCell>
                          <label className="inline-flex items-center gap-1 text-xs">
                            <input
                              type="radio"
                              name={`owner-matching-v03-person-${contact.dwid}`}
                              checked={disposition === '4'}
                              disabled={reviewLocked || !contact.dwid}
                              aria-label={`Opt-in ${formatMatchedContactLabel(contact)}`}
                              onChange={() => setPersonDisposition(contact.dwid, '4')}
                              className="accent-habeas-navy"
                            />
                            <span className="sr-only">Opt-in</span>
                          </label>
                        </TableCell>
                        <TableCell>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            disabled={reviewLocked || !contact.dwid}
                            onClick={() => removePerson(contact.dwid)}
                          >
                            Remove
                          </Button>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            )}
            {mixedDispositions ? (
              <p className="mt-2 text-[0.65rem] text-mute">
                Mixed Delete and Opt-in — choose one disposition to apply.
              </p>
            ) : null}
          </div>
        </section>
      </div>

      <div className="shrink-0 border-t border-line px-3 py-2">
        <ResultApplyBar
          pending={pending}
          disabled={
            disabled ||
            gateForThisSystem ||
            mixedDispositions ||
            statusId == null ||
            applyNeedsPeople(statusId, selectedDwids)
          }
          onApply={() => {
            const applyStatus = notFound ? '5' : (unanimousDisposition ?? statusId)
            if (!applyStatus) return
            onApply({
              statusId: applyStatus,
              selectedDwids: applyStatus === '5' ? [] : visible.map((contact) => contact.dwid),
            })
          }}
        />
      </div>
    </div>
  )
}
