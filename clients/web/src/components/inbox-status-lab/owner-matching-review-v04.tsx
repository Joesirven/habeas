import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from '@tanstack/react-router'

import {
  applyNeedsPeople,
  resultViewEmpty,
} from '@/components/matching-results-lab/ResultViewChrome'
import {
  matchingLabSystemId,
  type MatchingResultsViewProps,
} from '@/components/matching-results-lab/matching-results-lab-types'
import {
  formatMatchedContactLabel,
  matchedChannelsFromDetail,
  useMatchingConnectorGate,
} from '@/components/requests/RequestTriageDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { suggestedDropResponseStatus, type MatchedPersonContact } from '@/lib/api'
import { useMe } from '@/lib/auth'
import {
  isDataCatalogVertical,
  matchingConnectorGateBannerCopy,
  matchingConnectorGateChip,
  ownerConnectorsSearch,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import { inboxIntakeSourceLabel, matchTypeLabel } from '@/lib/inbox-batch-status'
import {
  inboxDisplayConnections,
  inboxItemChannels,
  inboxReviewItemSystemLabel,
  type InboxItemChannel,
} from '@/lib/inbox-status-lab'
import { catalogSystemDisplayLabel } from '@/lib/legalJourneyLabels'
import { isOwnerWizardHiddenSystem } from '@/lib/owner-connector-ui'
import { cn } from '@/lib/utils'

/** Same floor as Inbox matching.review SLA — case file only, not a second product rule. */
const MATCHING_REVIEW_SLA_HOURS = 48

const EXHIBIT_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

/** Identifier surfaces — evidence fields on an exhibit, never separate case numbers. */
const SURFACE_ORDER: InboxItemChannel[] = ['email', 'phone', 'ndz']
const SURFACE_LABELS: Record<InboxItemChannel, string> = {
  email: 'Email',
  phone: 'Phone',
  ndz: 'NDZ',
}

type PersonFinding = '3' | '4'

function exhibitLetter(index: number): string {
  return EXHIBIT_LETTERS[index] ?? String(index + 1)
}

function exhibitSurfaces(
  item: {
    request_id: string
    matched_via?: string | null
    channels?: InboxItemChannel[]
  },
  detail: Parameters<typeof matchedChannelsFromDetail>[0],
): InboxItemChannel[] {
  const seen = new Set<InboxItemChannel>()
  for (const surface of inboxItemChannels(item)) seen.add(surface)
  for (const surface of matchedChannelsFromDetail(detail)) seen.add(surface)
  return SURFACE_ORDER.filter((surface) => seen.has(surface))
}

function surfaceOnRecord(surfaces: InboxItemChannel[], surface: InboxItemChannel): string {
  return surfaces.includes(surface) ? 'On the record' : '—'
}

function formatCaseDate(value: string | null | undefined): string {
  const raw = value?.trim()
  if (!raw) return '—'
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function reviewDueLabel(received: string | null | undefined): string {
  const raw = received?.trim()
  if (!raw) return 'Not on file'
  const start = new Date(raw)
  if (Number.isNaN(start.getTime())) return 'Not on file'
  const due = new Date(start.getTime() + MATCHING_REVIEW_SLA_HOURS * 60 * 60 * 1000)
  return due.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function CaseSection({
  number,
  title,
  children,
}: {
  number: string
  title: string
  children: ReactNode
}) {
  return (
    <section className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-3 border-t border-line pt-3 first:border-t-0 first:pt-0">
      <p className="pt-px text-[0.65rem] tabular-nums leading-5 text-mute">{number}</p>
      <div className="min-w-0 space-y-2">
        <h3 className="text-xs font-medium leading-5 text-ink">{title}</h3>
        {children}
      </div>
    </section>
  )
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[5.75rem_minmax(0,1fr)] gap-x-3 text-[0.7rem] leading-5">
      <dt className="text-mute">{label}</dt>
      <dd className="min-w-0 text-ink">{value}</dd>
    </div>
  )
}

function findingCopy(
  matchType: string | null | undefined,
  count: number | null | undefined,
  ownerLanguage: boolean,
  notLive: boolean,
): string {
  if (notLive) {
    return 'No live matching evidence is on file for this system. The index has not returned persons.'
  }
  if (matchType === 'not_found' || count === 0) {
    return 'The index returned no persons. The record supports a not-found finding.'
  }
  if (matchType === 'single_match' || count === 1) {
    return ownerLanguage
      ? 'The index returned one person. Review Exhibit A before confirming the match. Email, phone, and NDZ are surfaces on that exhibit.'
      : 'The index returned a single person. Review Exhibit A before recording disposition. Surfaces are recorded on that exhibit.'
  }
  if (matchType === 'multi_match' || (count != null && count > 1)) {
    return `The index returned ${count ?? 'multiple'} persons. Admit only the exhibits that belong on this request. Surfaces are recorded on each exhibit.`
  }
  return 'Match evidence is incomplete. Record a finding only after reviewing the exhibits.'
}

function isHiddenCatalogSystem(
  system: string | null | undefined,
  label?: string | null,
): boolean {
  if (isOwnerWizardHiddenSystem(system)) return true
  return (label ?? '').trim().toLowerCase() === 'cassandra'
}

function suggestedPersonFinding(
  matchType: string | null | undefined,
  count: number | null | undefined,
): PersonFinding {
  return suggestedDropResponseStatus(matchType, count) === 4 ? '4' : '3'
}

function agreedPersonFinding(
  exhibitDwids: string[],
  findings: Record<string, PersonFinding>,
): PersonFinding | null {
  if (exhibitDwids.length === 0) return null
  const unique = new Set(
    exhibitDwids.map((dwid) => findings[dwid]).filter((value): value is PersonFinding => Boolean(value)),
  )
  if (unique.size !== 1) return null
  return [...unique][0] ?? null
}

function gateForThisSystem(
  gate: MatchingConnectorGate | null | undefined,
  item: MatchingResultsViewProps['item'],
): MatchingConnectorGate | null {
  if (!gate?.blocked || !item) return null
  if (isHiddenCatalogSystem(matchingLabSystemId(item), item.system_label)) return null
  if (isHiddenCatalogSystem(gate.system)) return null
  if (isDataCatalogVertical(item.vertical)) return null
  const current = matchingLabSystemId(item)
  if (gate.system && current && gate.system !== current) return null
  return gate
}

function personSearchHaystack(contact: MatchedPersonContact): string {
  return [
    formatMatchedContactLabel(contact),
    contact.state,
    contact.first_initial,
    contact.last_initial,
    contact.last_name,
  ]
    .filter((part): part is string => typeof part === 'string' && Boolean(part.trim()))
    .join(' ')
    .toLowerCase()
}

/**
 * Owner matching review — legal/compliance case file.
 * Numbered sections, evidence tone, people as exhibits. No lifecycle rail.
 * One person = one exhibit / one attempt. Email, phone, and NDZ are surfaces
 * on that exhibit — not parallel findings or “matched via” stamps.
 */
export function OwnerMatchingReviewV04({
  item,
  detail,
  contacts,
  loading,
  ownerLanguage,
  statusOptions,
  statusId,
  onStatusChange,
  onSelectedDwidsChange,
  disabled,
  pending,
  onApply,
}: MatchingResultsViewProps) {
  const { me } = useMe()
  const connectorGate = useMatchingConnectorGate({
    attempts: detail?.attempts,
    reminders: me?.connector_reminders,
    fetchConnections: true,
  })
  const [exhibitDwids, setExhibitDwids] = useState<string[]>([])
  const [findings, setFindings] = useState<Record<string, PersonFinding>>({})
  const [addQuery, setAddQuery] = useState('')

  const contactKey = contacts
    .map((contact) => contact.dwid)
    .filter(Boolean)
    .join('|')
  const matchType = detail?.match_type ?? item?.match_type
  const matchCount = detail?.match_count ?? item?.match_count ?? contacts.length

  useEffect(() => {
    const ids = contacts.map((contact) => contact.dwid).filter(Boolean)
    const emptyMatch = matchType === 'not_found' || matchCount === 0
    if (emptyMatch) {
      setExhibitDwids([])
      setFindings({})
      setAddQuery('')
      return
    }
    const finding = suggestedPersonFinding(matchType, matchCount)
    setExhibitDwids(ids)
    setFindings(Object.fromEntries(ids.map((id) => [id, finding])))
    setAddQuery('')
  }, [
    item?.request_id,
    item?.system,
    item?.system_id,
    item?.vertical,
    contactKey,
    contacts,
    matchType,
    matchCount,
  ])

  const contactByDwid = useMemo(() => {
    const map = new Map<string, MatchedPersonContact>()
    for (const contact of contacts) {
      if (contact.dwid) map.set(contact.dwid, contact)
    }
    return map
  }, [contacts])

  const empty = resultViewEmpty(loading, Boolean(item))
  if (empty) return empty
  if (!item) return empty

  const locked = Boolean(disabled || pending)
  const blockedGate = gateForThisSystem(connectorGate, item)
  const matchingBlocked = Boolean(blockedGate)
  const peopleCleared = statusId === '5'
  const notLive =
    detail?.matched_contacts_status === 'not_live' ||
    detail?.result_kind === 'sheet_stub' ||
    detail?.result_kind === 'saas_stub'
  const received = item.requested_at ?? item.received_at
  const sourceLabel = inboxIntakeSourceLabel(item.intake_source)
  const currentSystem =
    inboxReviewItemSystemLabel(item) ??
    catalogSystemDisplayLabel(item.system ?? item.system_id, {
      vertical: item.vertical,
      systemLabel: item.system_label,
    })
  const systems = inboxDisplayConnections(item).filter(
    (connection) => !isHiddenCatalogSystem(connection.system, connection.system_label),
  )
  const systemRows =
    systems.length > 0
      ? systems.map((connection) => ({
          id: connection.system,
          label:
            catalogSystemDisplayLabel(connection.system, {
              vertical: connection.vertical ?? item.vertical,
              systemLabel: connection.system_label,
            }) ?? 'Unassigned system',
          current:
            (connection.system?.trim() || '') ===
            (item.system?.trim() || item.system_id?.trim() || ''),
        }))
      : currentSystem && !isHiddenCatalogSystem(item.system ?? item.system_id, item.system_label)
        ? [{ id: item.system ?? item.system_id ?? null, label: currentSystem, current: true }]
        : []
  const surfaces = exhibitSurfaces(item, detail)
  const exhibits = exhibitDwids
    .map((dwid) => contactByDwid.get(dwid))
    .filter((contact): contact is MatchedPersonContact => Boolean(contact))
  const addable = contacts.filter(
    (contact) => Boolean(contact.dwid) && !exhibitDwids.includes(contact.dwid),
  )
  const addNeedle = addQuery.trim().toLowerCase()
  const addHits = addable.filter((contact) => {
    if (!addNeedle) return true
    return personSearchHaystack(contact).includes(addNeedle)
  })
  const exhibitFinding = agreedPersonFinding(exhibitDwids, findings)
  const findingsDisagree = exhibitDwids.length > 1 && exhibitFinding == null
  const emphasizedFinding = suggestedPersonFinding(matchType, matchCount)
  const section = matchingBlocked
    ? {
        caption: '01',
        systems: '02',
        status: '03',
        finding: '04',
        exhibits: '05',
        disposition: '06',
      }
    : {
        caption: '01',
        systems: '02',
        status: null,
        finding: '03',
        exhibits: '04',
        disposition: '05',
      }
  const recordLocked = locked || matchingBlocked
  const recordBlocked =
    recordLocked ||
    statusId == null ||
    findingsDisagree ||
    applyNeedsPeople(statusId, exhibitDwids)

  function syncCase(nextIds: string[], nextFindings: Record<string, PersonFinding>) {
    setExhibitDwids(nextIds)
    setFindings(nextFindings)
    onSelectedDwidsChange(nextIds)
    if (nextIds.length === 0) {
      onStatusChange('5')
      return
    }
    const agreed = agreedPersonFinding(nextIds, nextFindings)
    if (agreed) onStatusChange(agreed)
  }

  function chooseStatus(next: string) {
    if (!next || matchingBlocked) return
    if (next === '5') {
      syncCase([], {})
      return
    }
    if (next !== '3' && next !== '4') {
      onStatusChange(next)
      return
    }
    const finding = next as PersonFinding
    const ids = exhibitDwids.length > 0 ? exhibitDwids : contacts.map((contact) => contact.dwid).filter(Boolean)
    const nextFindings: Record<string, PersonFinding> = Object.fromEntries(
      ids.map((id) => [id, finding]),
    )
    syncCase(ids, nextFindings)
  }

  function setExhibitFinding(dwid: string, finding: PersonFinding) {
    if (!dwid || matchingBlocked) return
    const nextFindings = { ...findings, [dwid]: finding }
    const nextIds = exhibitDwids.includes(dwid) ? exhibitDwids : [...exhibitDwids, dwid]
    syncCase(nextIds, nextFindings)
  }

  function removeExhibit(dwid: string) {
    if (!dwid || matchingBlocked) return
    const nextIds = exhibitDwids.filter((id) => id !== dwid)
    const nextFindings = { ...findings }
    delete nextFindings[dwid]
    syncCase(nextIds, nextFindings)
  }

  function addExhibit(dwid: string) {
    if (!dwid || matchingBlocked || exhibitDwids.includes(dwid)) return
    const finding = findings[dwid] ?? exhibitFinding ?? emphasizedFinding
    syncCase([...exhibitDwids, dwid], { ...findings, [dwid]: finding })
    setAddQuery('')
  }

  function recordDisposition() {
    if (recordBlocked) return
    if (exhibitDwids.length === 0) {
      onApply({ statusId: '5', selectedDwids: [] })
      return
    }
    if (!exhibitFinding) return
    onApply({ statusId: exhibitFinding, selectedDwids: exhibitDwids })
  }

  const gateChip = blockedGate ? matchingConnectorGateChip(blockedGate) : null
  const gateCopy = blockedGate ? matchingConnectorGateBannerCopy(blockedGate) : null
  const connectorsVertical = item.vertical?.trim() || null

  return (
    <div className="space-y-4 text-[0.7rem] text-ink">
      <header className="space-y-1">
        <p className="text-[0.65rem] font-medium uppercase tracking-[0.12em] text-mute">
          Case file
        </p>
        <p className="font-mono text-[0.65rem] tabular-nums text-ink-soft">{item.request_id}</p>
      </header>

      <div className="space-y-3">
        <CaseSection number={section.caption} title="Caption">
          <dl className="space-y-0.5">
            <Fact label="Source" value={sourceLabel} />
            <Fact label="Received" value={formatCaseDate(received)} />
            <Fact label="Review due" value={reviewDueLabel(received)} />
            <Fact
              label="Vertical"
              value={item.vertical_label?.trim() || item.vertical?.trim() || '—'}
            />
          </dl>
        </CaseSection>

        <CaseSection number={section.systems} title="Systems examined">
          {systemRows.length === 0 ? (
            <p className="text-ink-soft">No systems on this request.</p>
          ) : (
            <ol className="space-y-1">
              {systemRows.map((row, index) => (
                <li
                  key={`${row.id ?? row.label}-${index}`}
                  className="flex flex-wrap items-baseline gap-x-2"
                >
                  <span className="tabular-nums text-mute">{index + 1}.</span>
                  <span className={row.current ? 'font-medium text-ink' : 'text-ink-soft'}>
                    {row.label}
                  </span>
                  {row.current ? (
                    <span className="text-[0.65rem] text-mute">this review</span>
                  ) : null}
                </li>
              ))}
            </ol>
          )}
        </CaseSection>

        {blockedGate && section.status ? (
          <CaseSection number={section.status} title="Matching status">
            <div className="flex flex-wrap items-center gap-1.5">
              {gateChip ? (
                <Badge variant={gateChip.variant} className="normal-case tracking-normal">
                  {gateChip.label}
                </Badge>
              ) : null}
              <span className="text-ink">Examination stayed</span>
            </div>
            <p className="leading-5 text-ink-soft">
              {gateCopy?.description ??
                'Connect or refresh this system before matching evidence can be taken. Connecting is not matching.'}
            </p>
            <Button asChild size="sm">
              <Link to="/owner/connectors" search={ownerConnectorsSearch(connectorsVertical)}>
                Open connectors
              </Link>
            </Button>
          </CaseSection>
        ) : null}

        <CaseSection number={section.finding} title="Finding">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="default" className="normal-case tracking-normal">
              {matchingBlocked
                ? gateChip?.label ?? 'Matching gated'
                : notLive
                  ? detail?.result_kind === 'sheet_stub'
                    ? 'Sheet matching not live'
                    : 'System matching not live'
                  : matchTypeLabel(matchType, ownerLanguage)}
            </Badge>
            {!matchingBlocked && !notLive && matchCount != null ? (
              <span className="tabular-nums text-ink-soft">
                {matchCount} {matchCount === 1 ? 'person' : 'persons'}
              </span>
            ) : null}
          </div>
          <p className="leading-5 text-ink-soft">
            {matchingBlocked
              ? 'No finding can be recorded until the connector gate clears.'
              : findingCopy(matchType, matchCount, ownerLanguage, notLive)}
          </p>
          {notLive && detail?.not_live_reason ? (
            <p className="text-[0.65rem] text-ink-soft">{detail.not_live_reason}</p>
          ) : null}
        </CaseSection>

        <CaseSection number={section.exhibits} title="Exhibits">
          {notLive ? (
            <p className="text-ink-soft">
              {peopleCleared || matchType === 'not_found' || matchCount === 0
                ? 'No persons entered into the record.'
                : 'No person records returned for this system.'}
            </p>
          ) : exhibits.length === 0 ? (
            <p className="text-ink-soft">
              {peopleCleared || matchType === 'not_found' || matchCount === 0
                ? 'No persons entered into the record.'
                : 'No exhibits on the record. Search this system to enter a person.'}
            </p>
          ) : (
            <ul className="space-y-2">
              {exhibits.map((contact, index) => {
                const letter = exhibitLetter(index)
                const finding = findings[contact.dwid] ?? emphasizedFinding
                const deleteEmphasized = emphasizedFinding === '3'
                return (
                  <li key={contact.dwid || `exhibit-${index}`}>
                    <div
                      className={cn(
                        'space-y-2 rounded-md border border-line bg-paper px-2.5 py-2',
                        (recordLocked || !contact.dwid) && 'opacity-60',
                      )}
                    >
                      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                        <span className="text-[0.65rem] uppercase tracking-[0.08em] text-mute">
                          Exhibit {letter}
                        </span>
                        <button
                          type="button"
                          className="text-[0.65rem] text-mute underline-offset-2 hover:text-ink hover:underline disabled:no-underline disabled:opacity-50"
                          disabled={recordLocked || !contact.dwid}
                          onClick={() => removeExhibit(contact.dwid)}
                        >
                          Remove exhibit
                        </button>
                      </div>
                      <p className="text-xs text-ink">{formatMatchedContactLabel(contact)}</p>
                      <dl className="space-y-0.5">
                        <Fact label="State" value={contact.state || '—'} />
                        {SURFACE_ORDER.map((surface) => (
                          <Fact
                            key={surface}
                            label={SURFACE_LABELS[surface]}
                            value={surfaceOnRecord(surfaces, surface)}
                          />
                        ))}
                      </dl>
                      <fieldset disabled={recordLocked || !contact.dwid} className="space-y-1">
                        <legend className="text-[0.65rem] text-mute">
                          Disposition for this exhibit
                        </legend>
                        <div className="flex flex-wrap gap-1.5">
                          <button
                            type="button"
                            className={cn(
                              'rounded-md border px-2 py-1 text-[0.65rem]',
                              finding === '3'
                                ? 'border-habeas-navy bg-habeas-navy/5 font-medium text-habeas-navy'
                                : 'border-line text-ink',
                              deleteEmphasized && finding !== '3' && 'border-habeas-navy/40',
                            )}
                            aria-pressed={finding === '3'}
                            onClick={() => setExhibitFinding(contact.dwid, '3')}
                          >
                            Delete
                          </button>
                          <button
                            type="button"
                            className={cn(
                              'rounded-md border px-2 py-1 text-[0.65rem]',
                              finding === '4'
                                ? 'border-habeas-navy bg-habeas-navy/5 font-medium text-habeas-navy'
                                : 'border-line text-ink',
                              !deleteEmphasized && finding !== '4' && 'border-habeas-navy/40',
                            )}
                            aria-pressed={finding === '4'}
                            onClick={() => setExhibitFinding(contact.dwid, '4')}
                          >
                            Opt-in
                          </button>
                        </div>
                      </fieldset>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
          {!notLive && addable.length > 0 ? (
            <div className="space-y-1.5 pt-1">
              <label className="block space-y-1">
                <span className="text-[0.65rem] text-mute">Add exhibit from this system</span>
                <input
                  type="search"
                  value={addQuery}
                  disabled={recordLocked}
                  onChange={(event) => setAddQuery(event.target.value)}
                  placeholder="Search persons on this system…"
                  className="h-7 w-full rounded-md border border-line bg-paper px-2 text-xs text-ink outline-none placeholder:text-mute focus-visible:border-habeas-navy"
                  autoComplete="off"
                  spellCheck={false}
                />
              </label>
              <ul className="max-h-36 space-y-0.5 overflow-y-auto">
                {addHits.length === 0 ? (
                  <li className="text-[0.65rem] text-mute">No persons match that search.</li>
                ) : (
                  addHits.map((contact) => (
                    <li key={contact.dwid}>
                      <button
                        type="button"
                        disabled={recordLocked || !contact.dwid}
                        className="flex w-full items-center justify-between gap-2 rounded-md px-1.5 py-1 text-left text-[0.65rem] text-ink hover:bg-panel disabled:opacity-50"
                        onClick={() => addExhibit(contact.dwid)}
                      >
                        <span className="truncate">{formatMatchedContactLabel(contact)}</span>
                        <span className="shrink-0 text-mute">Enter</span>
                      </button>
                    </li>
                  ))
                )}
              </ul>
            </div>
          ) : null}
        </CaseSection>

        <CaseSection number={section.disposition} title="Disposition">
          <fieldset disabled={recordLocked} className="space-y-1.5">
            <legend className="sr-only">Record a matching disposition</legend>
            {statusOptions.map((option) => {
              const selected = statusId === option.id
              return (
                <label
                  key={option.id}
                  className={cn(
                    'flex cursor-pointer items-start gap-2 rounded-md border px-2.5 py-1.5',
                    selected
                      ? 'border-habeas-navy bg-habeas-navy/5'
                      : 'border-line bg-paper',
                    recordLocked && 'cursor-not-allowed opacity-50',
                  )}
                >
                  <input
                    type="radio"
                    name="owner-matching-review-v04-disposition"
                    className="mt-0.5 size-3.5 shrink-0 accent-habeas-navy"
                    checked={selected}
                    disabled={recordLocked}
                    onChange={() => chooseStatus(option.id)}
                  />
                  <span className="min-w-0">
                    <span
                      className={cn(
                        'block text-xs',
                        selected ? 'font-medium text-habeas-navy' : 'text-ink',
                      )}
                    >
                      {option.label}
                    </span>
                    <span className="block text-[0.65rem] text-ink-soft">
                      {option.id === '5'
                        ? 'Enter no exhibits. The index did not identify a person.'
                        : option.id === '4'
                          ? 'Opt-in on each exhibit that belongs on this multi-person finding.'
                          : 'Delete on the exhibit that the index identified.'}
                    </span>
                  </span>
                </label>
              )
            })}
          </fieldset>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button size="sm" disabled={recordBlocked} onClick={recordDisposition}>
              {pending ? 'Recording…' : 'Record disposition'}
            </Button>
            {matchingBlocked ? (
              <span className="text-[0.65rem] text-mute">
                Clear the connector gate before recording.
              </span>
            ) : findingsDisagree ? (
              <span className="text-[0.65rem] text-mute">
                Exhibits must agree on Delete or Opt-in.
              </span>
            ) : statusId == null ? (
              <span className="text-[0.65rem] text-mute">Select a finding first.</span>
            ) : null}
          </div>
        </CaseSection>
      </div>
    </div>
  )
}
